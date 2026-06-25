"""init.py - 一键编排 MKA 核心流程（取数 → 年报 → 清洗校验 → 核心指标速览 → 财务费用细则 → defaults.yaml）。

给 Agent / 人用的单一入口：输入公司名 / 裸代码 / 完整 ticker，自动完成
data_fetcher → report_downloader → clean → core_metrics_overview → financial_expense_analyzer → defaults_gen 的确定性编排，
并保证幂等（增量跳过、重跑只应用补数），最后输出一份"数据拉取报告"。

设计边界（与 CLAUDE.md 纪律一致）：
- 失败的那次年度硬校验运行不会被改判成功；override 只在下一次 clean 运行被应用。
- raw_tushare 永不被本脚本修改。
- 重跑应用 override 后仍年度硬校验失败 = 真问题 → 退出码 3，如实上报，绝不静默放行。

退出码语义（Agent 据此决定下一步）：
    0  全链路成功（纯 TuShare 通过，或经年报确认补全后通过）
    2  输入无法解析为唯一 ticker（中文名歧义/无匹配）→ Agent 用 websearch 查代码后重传
    3  应用年报补数后仍有年度硬校验失败（真数据问题）→ 如实上报，交用户判断
    1  其它异常（API/网络/鉴权/缺年报等）

CLI:
    python -m src.init 美的集团
    python -m src.init 000333
    python -m src.init 000333.SZ 600519.SH        # 批量
    python -m src.init 美的集团 --force            # 全量重拉重下重洗
    python -m src.init 000333.SZ --no-markdown     # 仅下载 PDF 不抽 Markdown
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

import src.data_fetcher as df_mod
from src.business_breakdown_extractor import (
    business_breakdown_max_workers,
    discover_reports as discover_business_breakdown_reports,
    extract_reports as extract_business_breakdown_reports,
    write_breakdown_file_set as write_business_breakdown_file_set,
    write_company_outputs as write_business_breakdown_outputs,
)
from src.clean import (
    approved_override_count,
    auto_reconcile_annual_failure,
    CheckError,
    clean_all,
    default_overrides_path,
    default_plugs_path,
    RECONCILE_MIN_YEAR,
)
from src.company_paths import (
    annual_reports_dir,
    company_dir_from_db_path,
    db_path as agent_db_path,
    ensure_workspace_layout,
    find_company_dir as find_company_root,
    official_breakdowns_dir,
    quarterly_reports_dir,
)
from src.core_metrics_overview import write_core_metrics_overview
from src.defaults_gen import build_defaults, default_output_path
from src.financial_expense_analyzer import (
    analyze_all_periods,
    default_yaml_path,
)
from src.yaml2_schema import write_yaml2

BASE_DIR = Path(__file__).resolve().parent.parent
COMPANIES_DIR = BASE_DIR / "companies"
LOGGER = logging.getLogger("init")

# vendored cninfo guess_plate（裸代码补后缀用）
_VENDORED_SRC = BASE_DIR / "vendor" / "use_cninfo" / "src"
if str(_VENDORED_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDORED_SRC))
from cninfo.api import guess_plate  # noqa: E402

TICKER_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
BARE_CODE_RE = re.compile(r"^\d{6}$")
MAX_BACKFILL_CYCLES = 2  # 两轮 reconcile+apply：第一轮补数，第二轮核对第一轮残差；仍不过→plug 提示
# 与 clean.py CLI --auto-reconcile-max-failures 默认对齐（complex 公司失败可超 30）。
AUTO_RECONCILE_MAX_FAILURES = 60


class TickerResolutionError(RuntimeError):
    """输入无法解析为唯一 ticker。candidates 供 Agent 用 websearch 兜底。"""

    def __init__(self, raw: str, candidates: list[tuple[str, str]] | None = None) -> None:
        self.raw = raw
        self.candidates = candidates or []
        super().__init__(f"无法把 {raw!r} 解析为唯一 A 股 ticker")


# ---------------------------------------------------------------------------
# 输入解析（确定性层；websearch 兜底在 SKILL.md / Agent 层）
# ---------------------------------------------------------------------------

def resolve_ticker(raw: str) -> str:
    """把公司名/裸代码/完整 ticker 解析成规范 ticker（如 000333.SZ）。

    歧义或无匹配时抛 TickerResolutionError（main 据此返回退出码 2）。
    """
    text = raw.strip()
    upper = text.upper()
    if TICKER_RE.match(upper):
        return upper
    if BARE_CODE_RE.match(text):
        plate = guess_plate(text)  # sz/sh/bj
        return f"{text}.{plate.upper()}"
    return _resolve_name_via_tushare(text)


def _resolve_name_via_tushare(name: str) -> str:
    """用 TuShare stock_basic 把公司中文名解析成 ticker。"""
    pro = df_mod.create_tushare_client()
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    except Exception as exc:  # noqa: BLE001
        if df_mod.is_auth_or_permission_error(exc):
            raise
        raise TickerResolutionError(name) from exc
    if df_mod.dataframe_empty(df) or "name" not in df.columns:
        raise TickerResolutionError(name)

    exact = df[df["name"] == name]
    if len(exact) == 1:
        return str(exact.iloc[0]["ts_code"]).upper()

    contains = df[df["name"].str.contains(re.escape(name), na=False)]
    if len(contains) == 1:
        return str(contains.iloc[0]["ts_code"]).upper()

    candidates = [
        (str(row["ts_code"]).upper(), str(row["name"]))
        for _, row in contains.head(10).iterrows()
    ]
    raise TickerResolutionError(name, candidates=candidates)


# ---------------------------------------------------------------------------
# 公司目录 / db 定位
# ---------------------------------------------------------------------------

def find_db_path(ticker: str) -> Path | None:
    try:
        return agent_db_path(find_company_root(ticker, COMPANIES_DIR))
    except FileNotFoundError:
        return None


def read_meta(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.OperationalError:
            return {}
    return {str(k): str(v) for k, v in rows}


# ---------------------------------------------------------------------------
# 各阶段
# ---------------------------------------------------------------------------

def stage_fetch(ticker: str, *, force: bool) -> tuple[Path, str]:
    """阶段①拉取。返回 (db_path, 状态描述)。幂等：当日已拉取则跳过（除非 force）。"""
    db_path = find_db_path(ticker)
    if db_path and not force:
        meta = read_meta(db_path)
        last_updated = meta.get("last_updated", "")
        today = dt.date.today().isoformat()
        if last_updated[:10] == today:
            return db_path, f"跳过（当日已拉取 last_updated={last_updated}）"

    LOGGER.info("[1/5] TuShare 拉取 %s ...", ticker)
    new_path = Path(df_mod.fetch_company(ticker, force_refresh=force, output_root=BASE_DIR))
    return new_path, "已更新" + ("（force 全量重拉）" if force else "（UPSERT 增量）")


def _count_reports(dir_path: Path) -> tuple[int, int]:
    """Count PDF and Markdown files recursively under dir_path."""
    if not dir_path.exists():
        return 0, 0
    pdfs = len(list(dir_path.rglob("*.pdf")))
    mds = len(list(dir_path.rglob("*.md")))
    return pdfs, mds


def stage_reports(
    ticker: str,
    db_path: Path,
    *,
    no_markdown: bool,
    force_markdown: bool,
    no_quarterly: bool,
    min_year: int = RECONCILE_MIN_YEAR,
) -> str:
    """阶段年报/季报下载（必须在 clean 之前）。report_downloader 自身幂等，已有文件跳过。

    默认下载年报+季报；加 --no-quarterly 时仅下载年报。
    2010 闸门：只下载 min_year（默认 clean.RECONCILE_MIN_YEAR=2010）及以后的报告——
    2010 前披露稀疏、reconciler 也不核对，下载纯浪费 cninfo 请求与磁盘。
    失败不致命：仅当后续 clean 需要年报补全时才会暴露为真问题。
    """
    company_dir = company_dir_from_db_path(db_path)
    annuals_dir = annual_reports_dir(company_dir)
    quarterly_dir = quarterly_reports_dir(company_dir)

    pdf_before, md_before = _count_reports(annuals_dir)
    if not no_quarterly:
        q_pdf_before, q_md_before = _count_reports(quarterly_dir)
        pdf_before += q_pdf_before
        md_before += q_md_before

    cmd = [sys.executable, "-m", "src.report_downloader", "--ticker", ticker]
    # 报告落到 data_fetcher 已建的公司目录，避免 cninfo 与 TuShare
    # 公司名口径不一致（半角万科A vs 全角万科Ａ）导致公告目录与 Agent/data.db 分家、
    # find_company_dir 命中多个目录而崩溃。
    cmd.extend(["--company-dir", str(company_dir)])
    cmd.extend(["--min-year", str(min_year)])
    # 半年报 Markdown 仅最近 3 年（人工备查），省 PyMuPDF CPU；年报 md 全量。
    cmd.extend(["--h1-md-recent-years", "3"])
    if not no_quarterly:
        cmd.append("--all-reports")
    if no_markdown:
        cmd.append("--no-markdown")
    if force_markdown:
        cmd.append("--force-markdown")

    LOGGER.info("[2/5] 年报/季报 PDF/Markdown 下载 %s ...", ticker)
    result = subprocess.run(cmd, cwd=BASE_DIR)

    pdf_after, md_after = _count_reports(annuals_dir)
    if not no_quarterly:
        q_pdf_after, q_md_after = _count_reports(quarterly_dir)
        pdf_after += q_pdf_after
        md_after += q_md_after

    if result.returncode != 0:
        LOGGER.warning(
            "报告下载非零退出（returncode=%s）；继续 clean，若需年报补全将暴露为真问题",
            result.returncode,
        )
        status = f"⚠️ 下载未完整完成（PDF={pdf_after}, MD={md_after}）"
    else:
        status = (
            f"PDF {pdf_after} 份（新增 {pdf_after - pdf_before}）/ "
            f"MD {md_after} 份（新增 {md_after - md_before}）"
        )
    return status


def stage_business_breakdown(
    ticker: str,
    db_path: Path,
    *,
    no_markdown: bool,
    max_workers: int | None,
) -> str:
    """Extract official annual and recent H1 revenue breakdowns into Agent/OfficialBreakdowns."""
    if no_markdown:
        return "skipped (--no-markdown)"

    company_dir = company_dir_from_db_path(db_path)
    workers = max_workers or business_breakdown_max_workers()
    try:
        reports = discover_business_breakdown_reports(COMPANIES_DIR, tickers={ticker}, include_h1=True, h1_recent_years=3)
        if not reports:
            write_business_breakdown_file_set([], official_breakdowns_dir(company_dir))
            return "0 reports, wrote empty OfficialBreakdowns"

        rows = extract_business_breakdown_reports(reports, max_workers=workers)
        if rows:
            outputs = write_business_breakdown_outputs(rows, COMPANIES_DIR)
        else:
            csv_path, jsonl_path = write_business_breakdown_file_set([], official_breakdowns_dir(company_dir))
            outputs = [(company_dir.name, csv_path, jsonl_path)]
        return f"{len(reports)} reports, {len(rows)} rows, {len(outputs)} company file set(s), workers={workers}"
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("official revenue breakdown extraction failed: %s", exc)
        return f"warning: extraction failed: {exc}"


def _fmt_dur(seconds: float) -> str:
    """格式化耗时：'1m 23s' / '45s'。供阶段计时展示。"""
    s = max(0, int(round(seconds)))
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def _run_clean_inproc(
    ticker: str,
    db_path: Path,
    *,
    mode: str,
    allow_plug: bool = False,
) -> tuple[bool, list[tuple[str, str, float]], bool]:
    """同进程跑 clean_all，返回 (是否通过, 硬失败列表, 是否年度失败)。

    替代原 `python -m src.clean` subprocess：省 Python 冷启动 + pandas/tushare 重复
    import（两轮 backfill 重跑 4-6 次，每次省 2-4s）。HARD CHECK FAIL 行仍由
    validate_wide 打到 stderr（流式回显保留）；这里另从 CheckError.errors 结构化
    取全量硬失败供 plug 提示，免解析 stderr 文本。

    **不触发 reconciler**——reconciler 需要年报 Markdown，时机由 stage_clean 显式
    调 auto_reconcile_annual_failure 控制：首轮 clean 只读 raw_tushare，可与 ② 年报
    下载并行；reconciler 延后到 ② 完成。

    `is_annual` 复刻 clean.main 的判定（str(exc).startswith("annual validation failed")）：
    reconciler 只对年度硬失败有意义，季度失败直接走 plug/exit 3。
    """
    try:
        clean_all(db_path, ticker, mode=mode, allow_annual_plug=allow_plug)
        return True, [], False
    except CheckError as exc:
        errs = getattr(exc, "errors", None) or [str(exc)]
        is_annual = str(exc).startswith("annual validation failed")
        return False, _parse_hard_failures("\n".join(errs)), is_annual


_HARD_FAIL_RE = re.compile(r"HARD CHECK FAIL:\s+(BS \d\.\d)\s+(\d{4})\b.*?residual=([-\d.]+)")


def _parse_hard_failures(stderr_text: str) -> list[tuple[str, str, float]]:
    """Parse 'HARD CHECK FAIL: BS 2.2 2020 ... residual=6758.08' → (code, period, residual).

    period is the bare year ('2020') — that is the annual wide-table index format
    (TuShare end_date normalized to year), which is what annual_plugs.json and
    apply_annual_bs_plugs key on. NOT 'YYYY-12-31'.
    """
    fails: list[tuple[str, str, float]] = []
    for m in _HARD_FAIL_RE.finditer(stderr_text):
        code, year, res = m.group(1), m.group(2), float(m.group(3))
        fails.append((code, year, res))
    return fails


CORE_VIEW_TEMPLATE = """# 公司判断和最新观点

请在此文件填写对这家公司的核心投资观点。

建议结构：
- 一句话逻辑
- 三个支柱
- 动能拆分
- 催化 / 风险
"""


def ensure_company_artifacts(db_path: Path) -> str:
    """确保公司根目录存在人工维护入口与基本面工作台骨架。

    若文件/文件夹已存在则跳过，不覆盖已有内容。
    返回状态描述供报告使用。
    """
    company_dir = company_dir_from_db_path(db_path)
    created: list[str] = []
    ensure_workspace_layout(company_dir)

    core_view_path = company_dir / "公司判断和最新观点.md"
    if not core_view_path.exists():
        core_view_path.write_text(CORE_VIEW_TEMPLATE, encoding="utf-8")
        created.append("公司判断和最新观点.md")

    if created:
        return f"✅ 已创建 {', '.join(created)}"
    return "⏭️ 已存在"


def stage_clean(
    ticker: str,
    db_path: Path,
    *,
    mode: str,
    verbose: bool,
    ensure_reports_done: Callable[[], None],
) -> tuple[bool, str]:
    """阶段③清洗校验：首轮与 ② 年报下载并行 + 两轮年报补全 + plug 兜底。

    首轮 clean 只读 raw_tushare（不读年报），故可与 ② 年报下载并行：
      - 纯 TuShare 配平的公司首轮秒级通过，不等 ②，直接进 ④。
      - 首轮失败 → reconciler 需要年报 Markdown，调 ensure_reports_done() 等 ② 完成，
        再显式触发 reconciler（reconciler 自行重算失败，不必 clean 重跑）。
    之后两轮 apply + 必要时第 2 轮强触发，与原逻辑一致。
    reconciler 只对年度硬失败有意义；季度失败直接走 plug/exit 3。

    返回 (是否最终通过, 状态描述)。最终未通过 → 调用方返回退出码 3。
    """
    override_path = default_overrides_path(db_path)
    approved_before = approved_override_count(override_path)
    # 既有 plug 指令 = 用户已批准的硬残差兜底。重跑时 clean 自动沿用（allow_annual_plug），
    # 这些残差被吸收不再触发提示；只有新出现的、plug 文件未覆盖的硬失败才进 plug 提示。
    plug_path = default_plugs_path(db_path)
    allow_plug = plug_path.exists()

    LOGGER.info("[3/5] clean 配平校验 %s (mode=%s) ...（首轮与年报下载并行）", ticker, mode)
    # 首轮：只读 raw_tushare，不触发 reconciler——与 ② 并行。
    ok, fails, is_annual = _run_clean_inproc(ticker, db_path, mode=mode, allow_plug=allow_plug)
    if ok:
        if approved_before > 0:
            return True, f"✅ 通过（含 {approved_before} 项既有年报补数，详见下方科目）"
        return True, "✅ 全部通过（纯 TuShare 数据已配平）"

    # 非年度失败（季度硬失败）——reconciler 帮不上，直接走 plug/exit 3，不等 ②。
    if not is_annual:
        return _offer_annual_plug(ticker, db_path, mode, fails, verbose)

    # 年度硬失败 → reconciler 需要年报 Markdown，等 ② 下载完成。
    LOGGER.info("首轮 clean 有年度硬失败，等年报下载完成后触发年报核对 ...")
    ensure_reports_done()

    # ② 完成后重跑 clean：年报 MD 现已可用 → pre-IPO 闸门生效，早于最早年报 MD 的
    # 年度硬失败降级为 warning 不阻塞；既有 approved override 也一并应用。若由此通过，
    # 直接成功，无需再触发 reconciler（pre-IPO 年本就无 MD 可核对，reconciler 空跑）。
    ok, fails, is_annual = _run_clean_inproc(ticker, db_path, mode=mode, allow_plug=allow_plug)
    if ok:
        if approved_before > 0:
            return True, f"✅ 通过（含 {approved_before} 项既有年报补数 + pre-IPO 闸门降级，详见下方科目）"
        return True, "✅ 通过（pre-IPO 闸门降级后纯 TuShare 数据已配平）"

    # 仍有 post-IPO 年度硬失败 → reconciler 用年报 MD 核对（MD 现已可用）。
    # 第 1 轮强触发 reconciler（直接调，免 clean 重跑——reconciler 内部自行重算失败）。
    auto_reconcile_annual_failure(db_path, ticker, max_failures=AUTO_RECONCILE_MAX_FAILURES)

    # 两轮 apply + 必要时第 2 轮强触发
    for cycle in range(MAX_BACKFILL_CYCLES):
        approved_after = approved_override_count(override_path)
        if approved_after <= approved_before:
            LOGGER.info("年报核对未产生新 approved override，停止重跑。")
            break
        new_count = approved_after - approved_before
        approved_before = approved_after
        LOGGER.info("第 %d 轮：年报核对累计 %d 条 approved override（新增 %d），重跑 clean 应用 ...",
                    cycle + 1, approved_after, new_count)
        ok, fails, is_annual = _run_clean_inproc(ticker, db_path, mode=mode, allow_plug=allow_plug)
        if ok:
            return True, f"✅ 通过（其中 {approved_after} 项经年报确认后补全，详见 clean_adjustments）"
        if not is_annual:
            break  # 转为季度失败，reconciler 无效，走 plug
        if cycle < MAX_BACKFILL_CYCLES - 1:
            LOGGER.info("第 %d 轮应用后仍有硬失败，强触发 reconciler 核对残差 ...", cycle + 1)
            auto_reconcile_annual_failure(db_path, ticker, max_failures=AUTO_RECONCILE_MAX_FAILURES)

    # 两轮都不过 → plug 提示（fails 只含 plug 未覆盖的新硬失败，既有 plug 已被 allow_plug 吸收）
    return _offer_annual_plug(ticker, db_path, mode, fails, verbose)


def _offer_annual_plug(
    ticker: str,
    db_path: Path,
    mode: str,
    hard_failures: list[tuple[str, str, float]],
    verbose: bool,
) -> tuple[bool, str]:
    """两轮年报核对后仍有硬失败 → 问用户是否塞年度 QA plug。

    hard_failures: (code, period, residual) 来自最后一次 clean 的 HARD CHECK FAIL 行，
    即 override 全部应用后的真残差。用户同意 → 写 annual_plugs.json → 重跑 clean
    用 qa_bs_*_plug 吸收残差（带 warning + 审计）。不同意 → 如实留 exit 3。
    """
    if mode not in {"annual", "all"} or not hard_failures:
        return False, (
            f"❌ 年度硬校验失败，两轮年报核对（rule + LLM fallback）均未能解释残差"
            f"（{len(hard_failures)} 个）；需人工核对年报/口径"
        )

    plug_path = default_plugs_path(db_path)
    # 既有 plug 指令（用户此前已批准）——只追加新硬失败，不覆盖，保证重跑幂等。
    existing_plugs: list[dict[str, object]] = []
    if plug_path.exists():
        try:
            existing_plugs = json.loads(plug_path.read_text(encoding="utf-8")).get("plugs", []) or []
        except (json.JSONDecodeError, OSError):
            existing_plugs = []
    existing_keys = {(str(p.get("period")), str(p.get("code"))) for p in existing_plugs if isinstance(p, dict)}
    new_plugs = [
        {"period": period, "code": code}
        for code, period, _ in hard_failures
        if (period, code) not in existing_keys
    ]

    print("\n" + "=" * 64)
    print(f"⚠️  {ticker} 两轮年报核对后仍有 {len(new_plugs)} 个未被既有 plug 覆盖的年度硬失败：")
    for code, period, residual in hard_failures:
        tag = "（既有 plug 已覆盖，跳过）" if (period, code) in existing_keys else ""
        print(f"    {code} {period}: 残差 {residual:.2f} 百万元 {tag}")
    if not new_plugs:
        # 既有 plug 应已吸收全部残差（allow_plug 路径）；走到这里说明 plug 没生效，如实报失败。
        return False, "❌ 残差均已被既有 plug 覆盖但仍未通过（不应发生，请检查 annual_plugs.json）"
    print("\n两轮 reconciler（rule + LLM fallback，glm-5.2，全上下文）都无法用年报证据解释这些残差。")
    print("  y = 塞年度 QA plug：吸收残差入库（带 warning + 审计），clean 通过；")
    print("      建议后续人工核对年报/口径，定位科目后改用 LLM override 并删除本 plug。")
    print("  n = 不塞：保持 exit 3，如实留硬失败（关键科目推荐）。")
    try:
        ans = input("是否对这些硬失败塞年度 plug？[y/N]: ").strip().lower()
    except EOFError:
        ans = ""

    if ans != "y":
        return False, (
            f"❌ 用户未同意 plug，{len(new_plugs)} 个硬失败如实保留（exit 3）"
        )

    all_plugs = existing_plugs + new_plugs
    plug_path.parent.mkdir(parents=True, exist_ok=True)
    plug_path.write_text(
        json.dumps({"ticker": ticker, "plugs": all_plugs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("已写 %s（追加 %d 条新 plug，累计 %d 条），重跑 clean 应用年度 plug ...",
                plug_path, len(new_plugs), len(all_plugs))
    ok, _, _is_annual = _run_clean_inproc(ticker, db_path, mode="annual", allow_plug=True)
    if ok:
        return True, (
            f"✅ 通过（新增 {len(new_plugs)} 个硬失败用年度 QA plug 吸收，累计 {len(all_plugs)} 条 plug；"
            "详见 clean_warnings annual_bs_plug；建议人工核对后改用 LLM override 并删 plug）"
        )
    return False, "❌ 塞年度 plug 后仍失败（不应发生，请检查 annual_plugs.json 与残差方向）"


def stage_core_metrics_overview(ticker: str, db_path: Path, *, mode: str) -> str:
    """生成 clean_annual 年度核心指标速览。

    这是 /init 后续 Agent 的历史事实底稿，只读 clean_annual，失败不阻塞 init 主链路。
    """
    if mode == "quarterly":
        return "⏭️ --mode quarterly 未更新年度速览"

    LOGGER.info("[4/5] 年度核心指标速览 %s ...", ticker)
    try:
        paths = write_core_metrics_overview(db_path)
        names = ", ".join(path.name for path in paths.values())
        return f"✅ 已生成 {names}"
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("年度核心指标速览生成失败（不影响 init 退出码）: %s", exc)
        return f"⚠️ 生成失败: {exc}"


def stage_financial_expense(
    ticker: str,
    db_path: Path,
    *,
    force: bool,
    verbose: bool,
) -> tuple[str, dict[str, Any] | None]:
    """阶段⑤：财务费用细则分析（clean 之后、defaults 之前）。

    生成 companies/{公司}/Agent/financial_expense.yaml 多年档案；失败仅 warning，不阻塞管线。
    返回 (状态描述, archive dict 或 None)。
    """
    LOGGER.info("[5/5] 财务费用细则分析 %s ...", ticker)
    try:
        yaml_path = analyze_all_periods(ticker, db_path=db_path, force=force)
        import yaml  # type: ignore
        archive = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        periods = archive.get("periods", {}) if isinstance(archive, dict) else {}
        approved = sum(
            1 for rec in periods.values()
            if isinstance(rec, dict) and rec.get("status") == "approved" and rec.get("confidence") == "high"
        )
        total = len(periods)
        return f"✅ 已生成 {yaml_path.name}（{approved}/{total} 年 approved）", archive
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("财务费用细则分析失败（不影响后续流程）: %s", exc)
        return f"⚠️ 分析失败: {exc}", None


def stage_defaults(ticker: str, db_path: Path, *, verbose: bool) -> str:
    """阶段⑥：生成 defaults.yaml（YAML2 机器平推底座）。

    从 clean_annual + meta + financial_expense.yaml 派生 companies/{公司}/Agent/defaults.yaml，
    供 /comp 与 src.forecast 消费。必须在 ③clean（产 clean_annual）与 ⑤财务费用细则（产
    financial_expense.yaml）之后跑。失败仅 warning 不阻塞，但缺 defaults.yaml 会让 /comp 卡门禁。
    """
    LOGGER.info("[6/6] 生成 defaults.yaml %s ...", ticker)
    try:
        data = build_defaults(db_path, ticker=ticker)
        output = default_output_path(db_path)
        write_yaml2(output, data)
        base_period = data.get("base_period", "?")
        return f"✅ 已生成 {output.name}（base_period={base_period}）"
    except Exception as exc:  # noqa: BLE001
        if verbose:
            LOGGER.exception("defaults.yaml 生成失败")
        LOGGER.warning("defaults.yaml 生成失败（/comp 与 forecast 将不可用）: %s", exc)
        return f"⚠️ 生成失败: {exc}"


def build_report(
    ticker: str,
    db_path: Path,
    artifacts_status: str,
    fetch_status: str,
    report_status: str,
    revenue_breakdown_status: str,
    clean_status: str,
    core_metrics_status: str,
    fin_exp_status: str,
    defaults_status: str,
) -> str:
    meta = read_meta(db_path)
    name = meta.get("name", "?")
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"  init 数据拉取报告: {name} ({ticker})")
    lines.append("=" * 64)
    lines.append(f"  [0/6] 公司目录入口    : {artifacts_status}")
    lines.append(f"  [1/6] TuShare 拉取      : {fetch_status}")
    if meta:
        lines.append(
            f"          latest_trade_date={meta.get('latest_trade_date','?')} "
            f"last_report_period={meta.get('last_report_period','?')}"
        )
    lines.append(f"  [2/6] 年报 PDF/Markdown : {report_status}")
    lines.append(f"  [3/6] clean 配平校验    : {clean_status}")
    lines.append(f"  [4/6] 核心指标速览      : {core_metrics_status}")
    lines.append(f"  [5/6] 财务费用细则      : {fin_exp_status}")
    lines.append(f"  [6/6] defaults.yaml     : {defaults_status}")

    with closing(sqlite3.connect(db_path)) as conn:
        def _count(table: str) -> int:
            try:
                return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.OperationalError:
                return 0

        annual_n = _count("clean_annual")
        quarterly_n = _count("clean_quarterly")
        lines.append(f"          年度 {annual_n} 期 / 季度 {quarterly_n} 期")

        # 年报确认补全（clean_adjustments）
        try:
            adj = conn.execute(
                "SELECT field, failure_code, COUNT(*) FROM clean_adjustments GROUP BY field, failure_code"
            ).fetchall()
        except sqlite3.OperationalError:
            adj = []
        if adj:
            lines.append("  —— 年报确认后补全的科目（clean_adjustments，不改 raw_tushare）——")
            for field, code, n in adj:
                lines.append(f"          • {field} × {n} 期  [{code}] 来源=年报")

        # 季度 QA plug / 软校验 warning（clean_warnings）
        try:
            warn = conn.execute(
                "SELECT code, severity, COUNT(*) FROM clean_warnings GROUP BY code, severity"
            ).fetchall()
        except sqlite3.OperationalError:
            warn = []
        if warn:
            lines.append("  —— clean_warnings 汇总 ——")
            for code, severity, n in warn:
                lines.append(f"          • {code} ({severity}) × {n}")

    lines.append("-" * 64)
    if adj:
        lines.append("  说明：纯 TuShare 部分已配平通过；标注科目经本地年报确认后补全，全程可追溯。")
    else:
        lines.append("  说明：全部为 TuShare 原始数据，未使用任何年报补数。")
    lines.append(f"  annual revenue split: {revenue_breakdown_status}")
    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 单公司编排
# ---------------------------------------------------------------------------

def run_one(
    raw_input: str,
    *,
    force: bool,
    no_markdown: bool,
    force_markdown: bool,
    no_quarterly: bool,
    mode: str,
    verbose: bool,
    breakdown_workers: int | None,
    min_year: int = RECONCILE_MIN_YEAR,
) -> int:
    try:
        ticker = resolve_ticker(raw_input)
    except TickerResolutionError as exc:
        print(f"\n❌ 输入解析失败: {exc}", file=sys.stderr)
        if exc.candidates:
            print("  候选（请用 websearch 确认正确代码后重传完整 ticker）:", file=sys.stderr)
            for code, nm in exc.candidates:
                print(f"    {code}  {nm}", file=sys.stderr)
        else:
            print("  无候选匹配。请用 websearch 查询该公司的 A 股代码后重传，如 000333.SZ。",
                  file=sys.stderr)
        return 2

    LOGGER.info("输入 %r → 解析为 %s", raw_input, ticker)

    t_total = time.monotonic()
    t0 = time.monotonic()
    db_path, fetch_status = stage_fetch(ticker, force=force)
    t_fetch = time.monotonic() - t0
    LOGGER.info("⏱ 阶段① TuShare 取数用时 %s", _fmt_dur(t_fetch))

    artifacts_status = ensure_company_artifacts(db_path)

    # ② 年报/季报下载丢后台线程，与 ③ 首轮 clean 并行（clean 首轮只读 raw_tushare，不读年报）。
    # 首轮纯 TuShare 配平的公司，③ 秒级完成时 ② 仍在后台下载，不阻塞 ③→④。
    t_reports_start = time.monotonic()
    reports_box: dict[str, str] = {}

    def _run_reports_stage() -> None:
        try:
            reports_box["report"] = stage_reports(
                ticker,
                db_path,
                no_markdown=no_markdown,
                force_markdown=force_markdown,
                no_quarterly=no_quarterly,
                min_year=min_year,
            )
            reports_box["breakdown"] = stage_business_breakdown(
                ticker,
                db_path,
                no_markdown=no_markdown,
                max_workers=breakdown_workers,
            )
        except Exception as exc:  # noqa: BLE001
            reports_box["error"] = f"⚠️ ② 阶段异常: {exc}"

    reports_thread = threading.Thread(
        target=_run_reports_stage, name=f"init-reports-{ticker}", daemon=True
    )
    reports_thread.start()

    reports_joined = {"done": False}

    def _ensure_reports_done() -> None:
        if reports_joined["done"]:
            return
        reports_thread.join()
        reports_joined["done"] = True
        dur = time.monotonic() - t_reports_start
        reports_joined["dur"] = dur
        LOGGER.info("⏱ 阶段② 年报/季报下载用时 %s（与 ③ 首轮 clean 并行）", _fmt_dur(dur))

    t0 = time.monotonic()
    ok, clean_status = stage_clean(
        ticker, db_path, mode=mode, verbose=verbose, ensure_reports_done=_ensure_reports_done
    )
    t_clean = time.monotonic() - t0
    LOGGER.info("⏱ 阶段③ clean 配平+年报核对用时 %s", _fmt_dur(t_clean))

    # ③ 完成后确保 ② 也完成：⑤ 财务费用细则读年报 Markdown，报告也需要 ② 状态。
    _ensure_reports_done()
    report_status = reports_box.get("report", "")
    revenue_breakdown_status = reports_box.get("breakdown", "")
    if not report_status:
        report_status = reports_box.get("error", "⚠️ ② 阶段未产出状态")

    if ok:
        t0 = time.monotonic()
        core_metrics_status = stage_core_metrics_overview(ticker, db_path, mode=mode)
        t_core_metrics = time.monotonic() - t0
    else:
        core_metrics_status = "⏭️ clean 未通过，未生成"
        t_core_metrics = 0.0
    LOGGER.info("⏱ 阶段④ 年度核心指标速览用时 %s", _fmt_dur(t_core_metrics))

    t0 = time.monotonic()
    fin_exp_status, _evidence = stage_financial_expense(
        ticker, db_path, force=force, verbose=verbose
    )
    t_finexp = time.monotonic() - t0
    LOGGER.info("⏱ 阶段⑤ 财务费用细则用时 %s", _fmt_dur(t_finexp))

    # ⑥ defaults.yaml：clean 通过才派生（defaults_gen 读 clean_annual + financial_expense.yaml）。
    if ok:
        t0 = time.monotonic()
        defaults_status = stage_defaults(ticker, db_path, verbose=verbose)
        t_defaults = time.monotonic() - t0
    else:
        defaults_status = "⏭️ clean 未通过，未生成"
        t_defaults = 0.0
    LOGGER.info("⏱ 阶段⑥ defaults.yaml 用时 %s", _fmt_dur(t_defaults))

    LOGGER.info(
        "⏱ 总用时 %s（取数 %s / 下载 %s / clean %s / 速览 %s / 财务费用 %s / defaults %s）",
        _fmt_dur(time.monotonic() - t_total), _fmt_dur(t_fetch),
        _fmt_dur(reports_joined.get("dur", 0.0)),
        _fmt_dur(t_clean), _fmt_dur(t_core_metrics), _fmt_dur(t_finexp),
        _fmt_dur(t_defaults),
    )

    print("\n" + build_report(
        ticker, db_path, artifacts_status, fetch_status, report_status,
        revenue_breakdown_status, clean_status, core_metrics_status, fin_exp_status,
        defaults_status,
    ))

    return 0 if ok else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一键编排 MKA 核心流程：取数 → 年报 → 清洗校验 → 核心指标速览 → 财务费用细则 → defaults.yaml（幂等）。"
    )
    parser.add_argument("inputs", nargs="+", help="公司名 / 裸代码 / 完整 ticker（可多个）")
    parser.add_argument("--force", action="store_true",
                        help="全量重拉并重跑财务费用分析")
    parser.add_argument("--no-markdown", action="store_true", help="年报仅下载 PDF，不抽 Markdown")
    parser.add_argument("--force-markdown", action="store_true", help="即使已存在也重抽 Markdown")
    parser.add_argument("--no-quarterly", action="store_true",
                        help="跳过季报下载，仅下载年报（默认下载年报+季报）")
    parser.add_argument("--breakdown-workers", type=int, default=None,
                        help="annual revenue breakdown extraction workers")
    parser.add_argument("--min-year", type=int, default=RECONCILE_MIN_YEAR,
                        help=f"年报/季报只下载该年及以后（默认 {RECONCILE_MIN_YEAR}，"
                        "与 clean.RECONCILE_MIN_YEAR 对齐；2010 前不核对不值得下载）")
    parser.add_argument("--mode", choices=["annual", "quarterly", "all"], default="all",
                        help="clean 生成哪些表，默认 all")
    parser.add_argument("--verbose", action="store_true", help="调试日志")
    args = parser.parse_args(argv)

    # Windows 控制台默认 GBK，报告里的 ✅/❌ 等会崩溃；强制 UTF-8 输出。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    worst = 0
    for raw in args.inputs:
        try:
            rc = run_one(
                raw,
                force=args.force,
                no_markdown=args.no_markdown,
                force_markdown=args.force_markdown,
                no_quarterly=args.no_quarterly,
                mode=args.mode,
                verbose=args.verbose,
                breakdown_workers=args.breakdown_workers,
                min_year=args.min_year,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"\n❌ {raw}: 处理异常: {exc}", file=sys.stderr)
            rc = 1
        # 严重度优先级：3 > 2 > 1 > 0
        priority = {0: 0, 1: 1, 2: 2, 3: 3}
        if priority[rc] > priority[worst]:
            worst = rc
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
