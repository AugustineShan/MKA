"""init.py - 一键编排 MKA 核心流程（取数 → 年报 → 清洗校验 → 年报补全重跑）。

给 Agent / 人用的单一入口：输入公司名 / 裸代码 / 完整 ticker，自动完成
data_fetcher → report_downloader → clean 的确定性编排，
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
import logging
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import src.data_fetcher as df_mod
from src.clean import approved_override_count, default_overrides_path

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
MAX_BACKFILL_CYCLES = 1  # 一次 reconcile + 一次重跑应用，足够；多于此视为真失败


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
    code = ticker.split(".")[0]
    candidates = sorted(COMPANIES_DIR.glob(f"*_{code}/data.db"))
    return candidates[0] if candidates else None


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

    LOGGER.info("[1/3] TuShare 拉取 %s ...", ticker)
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
) -> str:
    """阶段年报/季报下载（必须在 clean 之前）。report_downloader 自身幂等，已有文件跳过。

    默认下载年报+季报；加 --no-quarterly 时仅下载年报。
    失败不致命：仅当后续 clean 需要年报补全时才会暴露为真问题。
    """
    annuals_dir = db_path.parent / "annuals"
    quarterly_dir = db_path.parent / "quarterlyreports"

    pdf_before, md_before = _count_reports(annuals_dir)
    if not no_quarterly:
        q_pdf_before, q_md_before = _count_reports(quarterly_dir)
        pdf_before += q_pdf_before
        md_before += q_md_before

    cmd = [sys.executable, str(BASE_DIR / "src" / "report_downloader.py"), "--ticker", ticker]
    if not no_quarterly:
        cmd.append("--all-reports")
    if no_markdown:
        cmd.append("--no-markdown")
    if force_markdown:
        cmd.append("--force-markdown")

    LOGGER.info("[2/3] 年报/季报 PDF/Markdown 下载 %s ...", ticker)
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


def _run_clean(ticker: str, db_path: Path, *, mode: str, no_auto_reconcile: bool, verbose: bool) -> int:
    cmd = [
        sys.executable, str(BASE_DIR / "src" / "clean.py"),
        "--ticker", ticker,
        "--db", str(db_path),
        "--mode", mode,
    ]
    if no_auto_reconcile:
        cmd.append("--no-auto-reconcile")
    if verbose:
        cmd.append("--verbose")
    return subprocess.run(cmd, cwd=BASE_DIR).returncode


def stage_clean(ticker: str, db_path: Path, *, mode: str, verbose: bool) -> tuple[bool, str]:
    """阶段②清洗校验，含年报补全的"失败→生成override→重跑应用"两段式。

    返回 (是否最终通过, 状态描述)。最终未通过 → 调用方返回退出码 3。
    """
    override_path = default_overrides_path(db_path)
    approved_before = approved_override_count(override_path)

    LOGGER.info("[3/4] clean 配平校验 %s (mode=%s) ...", ticker, mode)
    rc = _run_clean(ticker, db_path, mode=mode, no_auto_reconcile=False, verbose=verbose)
    if rc == 0:
        # 首跑即通过：可能是纯 TuShare 配平，也可能是已存在的 approved override 被自动应用。
        if approved_before > 0:
            return True, f"✅ 通过（含 {approved_before} 项既有年报补数，详见下方科目）"
        return True, "✅ 全部通过（纯 TuShare 数据已配平）"

    # 年度硬校验失败：clean 内部已强触发 reconciler，可能生成新 approved override。
    approved_after = approved_override_count(override_path)
    if approved_after <= approved_before:
        return False, (
            "❌ 年度硬校验失败，且年报核对未能生成可应用的补数证据"
            f"（approved override 仍为 {approved_after}）"
        )

    new_count = approved_after - approved_before
    LOGGER.info("年报核对新增 %s 条 approved override；重跑 clean 应用补数 ...", new_count)
    rc2 = _run_clean(ticker, db_path, mode=mode, no_auto_reconcile=True, verbose=verbose)
    if rc2 == 0:
        return True, f"✅ 通过（其中 {new_count} 项经年报确认后补全）"
    return False, (
        f"❌ 应用 {new_count} 条年报补数后仍有年度硬校验失败 —— 这不是已知 TuShare "
        "缺陷能解释的残差，需人工核对年报/口径"
    )


def build_report(
    ticker: str,
    db_path: Path,
    fetch_status: str,
    report_status: str,
    clean_status: str,
) -> str:
    meta = read_meta(db_path)
    name = meta.get("name", "?")
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"  init 数据拉取报告: {name} ({ticker})")
    lines.append("=" * 64)
    lines.append(f"  [1/3] TuShare 拉取      : {fetch_status}")
    if meta:
        lines.append(
            f"          latest_trade_date={meta.get('latest_trade_date','?')} "
            f"last_report_period={meta.get('last_report_period','?')}"
        )
    lines.append(f"  [2/3] 年报 PDF/Markdown : {report_status}")
    lines.append(f"  [3/3] clean 配平校验    : {clean_status}")

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

    db_path, fetch_status = stage_fetch(ticker, force=force)
    report_status = stage_reports(
        ticker,
        db_path,
        no_markdown=no_markdown,
        force_markdown=force_markdown,
        no_quarterly=no_quarterly,
    )
    ok, clean_status = stage_clean(ticker, db_path, mode=mode, verbose=verbose)

    print("\n" + build_report(
        ticker, db_path, fetch_status, report_status, clean_status
    ))

    return 0 if ok else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一键编排 MKA 核心流程：取数 → 年报 → 清洗校验 → 年报补全重跑（幂等）。"
    )
    parser.add_argument("inputs", nargs="+", help="公司名 / 裸代码 / 完整 ticker（可多个）")
    parser.add_argument("--force", action="store_true",
                        help="全量重拉（清空旧 raw_tushare 后重拉）")
    parser.add_argument("--no-markdown", action="store_true", help="年报仅下载 PDF，不抽 Markdown")
    parser.add_argument("--force-markdown", action="store_true", help="即使已存在也重抽 Markdown")
    parser.add_argument("--no-quarterly", action="store_true",
                        help="跳过季报下载，仅下载年报（默认下载年报+季报）")
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
