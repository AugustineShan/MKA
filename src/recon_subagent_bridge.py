"""recon_subagent_bridge — init skill 的 subagent 升级通道桥接器。

定位（混合分层架构的第二层，交互层）
======================================

MKA 的年度硬校验失败有两层处理：

1. **无人值守地板**：`annual_report_reconciler.py`（rule + GLM fallback），
   `init.py` 串两轮。关简单/精确案例，关不掉就 exit 3。
2. **subagent 升级通道**（本模块服务的层）：当 `init` exit 3 且有 Claude
   agent 在线时，`init` SKILL 读残差失败 → 并发派 Agent subagent 各读年报
   干净 Markdown 找证据 → 本模块**服务端验闭合**后写 approved override →
   重跑 clean。

为什么需要这一层
----------------
reconciler 的 GLM 在结构上赢不了某些案例（BYD 002594 2019/2021 BS 3.2）：
- 它喂给 GLM 的是 PyMuPDF 抽散的 snippet，subagent 直接读干净 Markdown；
- 它的 GLM 拿到 compound 残差（重分类未反映），单字段打分结构性闭合不了，
  subagent 拿到的是 clean.py 自己跑出来的**净残差**（已扣已批准 override）；
- GLM 发字段名会飘（lease_ncl/null），subagent 用 candidate 集确定性映射。

纪律（不可妥协）
----------------
- **subagent 只读只提案**：不写文件、不跑 clean、不批准自己。写/批准/验闭合
  全在本模块（确定性代码）。防脏配平闸门在代码，不信 subagent 自报。
- **净残差来自 clean.py 自己的运行**：reconciler 内部 collect_failures 曾出
  现重分类未反映进残差的问题；本模块用 `python -m src.clean --mode annual
  --no-auto-reconcile` 的 `HARD CHECK FAIL` 输出作为净残差真值，绕开该问题。
- **raw_tushare 永不被修改**：override 只进年度 clean 宽表 + clean_adjustments
  审计，与 glm/kimi override 同款可追溯（source=`claude:subagent`）。

两个 CLI 模式
=============
```
# 1) context：重跑 clean 取净残差失败，为每个失败算 subagent 所需上下文
python -m src.recon_subagent_bridge context --ticker 002594.SZ

# 2) apply：吃 subagent 提案，服务端验闭合，写 approved override
python -m src.recon_subagent_bridge apply --ticker 002594.SZ
```
context 写 `recon/subagent_context.json`；apply 读 `recon/subagent_proposals.json`
（SKILL 把各 subagent 输出合并到此），验闭合后合并写 `recon/annual_report_overrides.json`。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# 允许 `python -m src.recon_subagent_bridge` 与直接运行两种入口
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import clean  # noqa: E402
    from src import annual_report_reconciler as recon  # noqa: E402
else:
    from . import clean
    from . import annual_report_reconciler as recon

from src.annual_report_reconciler import (  # noqa: E402
    Failure,
    _build_adjustment_record,
    annual_markdown_path,
    build_field_context,
    extract_markdown_context,
    failure_candidate_fields,
    known_defect_hints_for_failure,
    parse_failure_message,
    read_tushare_field_docs,
)
from src.company_paths import recon_dir

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = clean.TOLERANCE
HARD_FAIL_RE = re.compile(r"HARD CHECK FAIL:\s*(.+)")


# ─────────────────────────────────────────────────────────────────────
# 净残差失败收集（context 模式第 1 步）
# ─────────────────────────────────────────────────────────────────────

def run_clean_annual(ticker: str, db_path: Path | None = None) -> str:
    """跑 `clean --mode annual --no-auto-reconcile`，返回 stderr 文本。

    用 clean.py 自己的生产路径应用所有 approved override（含 reclass）再硬校验，
    其 `HARD CHECK FAIL` 行就是**净残差**真值。--no-auto-reconcile 防递归触发
    reconciler。clean 遇硬失败会非零退出并打印 HARD CHECK FAIL，属预期。
    """
    cmd = [sys.executable, "-m", "src.clean", "--ticker", ticker, "--mode", "annual", "--no-auto-reconcile"]
    if db_path:
        cmd += ["--db", str(db_path)]
    # 强制子进程按 UTF-8 输出：Windows 默认按系统 locale（cp936/GBK）写 stderr，
    # 而 clean 的 HARD CHECK FAIL 行含中文（如『跨表 7.4 … 上期CF期末 ≠ 本期CF期初』）。
    # 若不强制，GBK 字节被下面 encoding="utf-8" 误解码成乱码，parse_failure_message
    # 的 `(?P<prefix>IS|BS|CF|跨表)` 正则匹配不到乱码的『跨表』→ code="UNKNOWN" → 被过滤
    # → bridge 误报 "annual clean already passes"，把真失败静默吞掉。ASCII code（BS/IS/CF）
    # 因 GBK/UTF-8 同形而幸存，唯独中文 prefix 的『跨表 7.4』会被吞，是隐蔽的静默错误。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(ROOT))
    return proc.stderr or ""


def parse_hard_check_failures(stderr_text: str) -> list[Failure]:
    """从 clean stderr 解析 HARD CHECK FAIL 行 → Failure 列表。"""
    failures: list[Failure] = []
    for line in stderr_text.splitlines():
        m = HARD_FAIL_RE.search(line)
        if not m:
            continue
        failure = parse_failure_message(m.group(1).strip())
        if failure and failure.code != "UNKNOWN":
            failures.append(failure)
    return failures


# ─────────────────────────────────────────────────────────────────────
# 上下文构建（context 模式第 2 步）
# ─────────────────────────────────────────────────────────────────────

def build_failure_context(
    ticker: str,
    company_dir: Path,
    db_path: Path,
    failure: Failure,
    field_docs: dict[str, dict[str, str]],
    known_defects: list[dict[str, Any]],
    approved_overrides: list[dict[str, Any]],
    wide_row: dict[str, float],
    present: set[str],
    reclass_for_period: dict[str, str],
) -> dict[str, Any]:
    """为单个残差失败构建 subagent 所需上下文。

    返回字段：
      failure            : Failure asdict（含净残差 target/calc/residual/direction）
      bucket             : 失败对应的 BS bucket（如 noncurrent_liab），用于验闭合
      candidate_fields   : candidate TuShare 字段（field/description/alias/value/clean_category）
      approved_overrides : 本期已批准 override（subagent 据此知哪些已补/已重分类）
      reclass_for_period : 本期已批准 reclass {field: target_bucket}
      markdown_path      : 年报 Markdown 路径
      section_start/end  : 报表段行号范围（subagent 直接 Read 该范围）
      net_residual       : 净残差（百万元，= failure.residual）
      net_direction      : target_gt_calc(calc偏低,需补) | target_lt_calc(calc偏高,需移除)
    """
    known_hints = known_defect_hints_for_failure(failure, wide_row, present, known_defects)
    candidate_fields = build_field_context(failure, wide_row, present, field_docs, known_hints)
    bucket = failure_candidate_fields(failure)[0]

    md_path = annual_markdown_path(company_dir, failure.period)
    markdown_context = {"error": f"No annual markdown for {failure.period}", "snippets": []}
    if md_path is not None:
        markdown_context = extract_markdown_context(failure, md_path, candidate_fields, known_hints)

    section_start = section_end = None
    for snip in markdown_context.get("snippets", []):
        if snip.get("kind") == "statement":
            section_start = snip.get("start_line")
            section_end = snip.get("end_line")
            break

    period_overrides = [o for o in approved_overrides if str(o.get("period")) == str(failure.period)]

    return {
        "failure": failure.__dict__,
        "bucket": bucket,
        "candidate_fields": candidate_fields,
        "approved_overrides_for_period": period_overrides,
        "reclass_for_period": reclass_for_period,
        "markdown_path": str(md_path) if md_path else None,
        "section_start": section_start,
        "section_end": section_end,
        "net_residual": failure.residual,
        "net_direction": failure.direction,
    }


# ─────────────────────────────────────────────────────────────────────
# 验闭合（apply 模式核心，确定性，防脏配平）
# ─────────────────────────────────────────────────────────────────────

def _effective_bucket(field: str, reclass_for_period: dict[str, str]) -> str | None:
    """字段在本期的有效 bucket：已批准 reclass 优先，否则 BS_FIELD_CATEGORIES 静态分类。"""
    if field in reclass_for_period:
        return reclass_for_period[field]
    return clean.BS_FIELD_CATEGORIES.get(field)


def evaluate_proposals(
    context: dict[str, Any],
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """服务端验证 subagent 提案是否闭合净残差，返回 approved override 记录。

    纪律：
    - 提议字段必须在 failure 的 candidate 集内（反脏配平 / 反幻觉）；
    - 闭合判断用**提案集合的净影响**对 calc 的有符号累加，而非单字段自报 diff；
    - 闭合条件 |净影响 − 所需影响| < TOLERANCE 才整组批准，否则一组都不批。

    操作类型对 calc（本 bucket）的有符号影响：
      add_override（补 0/缺字段）  ：字段有效 bucket == 本 bucket → +new_value
      reclass（字段移出本 bucket） ：有效 bucket == 本 bucket 且目标 != 本 bucket → −cur_value
      reclass（字段移入本 bucket） ：目标 == 本 bucket 且有效 != 本 bucket → +cur_value

    所需影响：target_gt_calc(calc 偏低) → +net_residual；target_lt_calc(calc 偏高) → −net_residual。
    """
    failure = context["failure"]
    bucket = context["bucket"]
    net_residual = float(failure.get("residual") or 0.0)
    direction = failure.get("direction")
    reclass_for_period = context.get("reclass_for_period") or {}
    candidates = {str(c["field"]): c for c in context.get("candidate_fields", []) if isinstance(c, dict) and c.get("field")}

    period = str(failure.get("period"))
    code = failure.get("code")
    # 本 failure 的提案（按 period+code 归组）
    mine = [
        p for p in proposals
        if isinstance(p, dict) and str(p.get("period")) == period and p.get("code") == code
    ]

    signed_effect = 0.0
    approved: list[tuple[dict[str, Any], str | None]] = []
    for p in mine:
        field = str(p.get("field") or "")
        if field not in candidates:
            # 反幻觉：subagent 映射到的字段不在 candidate 集 → 整组放弃该提案
            continue
        cand = candidates[field]
        cur_value = float(cand.get("value_million_cny") or 0.0)
        op = str(p.get("operation") or "")
        eff_bucket = _effective_bucket(field, reclass_for_period)
        new_value = float(p.get("value_million_cny") or 0.0)
        target_cat = p.get("clean_category")

        if op == "add_override":
            if eff_bucket == bucket:
                signed_effect += new_value
                approved.append((p, None))
        elif op == "reclass":
            if not target_cat:
                continue
            if eff_bucket == bucket and str(target_cat) != bucket:
                signed_effect -= cur_value
                approved.append((p, str(target_cat)))
            elif str(target_cat) == bucket and eff_bucket != bucket:
                signed_effect += cur_value
                approved.append((p, str(target_cat)))

    if not approved:
        return []

    needed = net_residual if direction == "target_gt_calc" else -net_residual
    if abs(signed_effect - needed) < TOLERANCE:
        return [(p, cat) for (p, cat) in approved]
    return []


def proposals_to_override_records(
    context: dict[str, Any],
    approved_pairs: list[tuple[dict[str, Any], str | None]],
    *,
    ticker: str,
    source_reconciliation_path: str,
) -> list[dict[str, Any]]:
    """把验通过的 (提案, clean_category) 转成 override 记录（source=claude:subagent）。"""
    failure = context["failure"]
    period = str(failure.get("period"))
    md_path = context.get("markdown_path")
    records: list[dict[str, Any]] = []
    for proposal, clean_category in approved_pairs:
        field = str(proposal.get("field"))
        op = str(proposal.get("operation") or "")
        new_value = float(proposal.get("value_million_cny") or 0.0)
        # add_override：字段原值通常为 0；reclass：值不变只改 bucket
        old_value = 0.0 if op == "add_override" else new_value
        records.append(
            _build_adjustment_record(
                ticker=ticker,
                period=period,
                field=field,
                new_value=new_value,
                old_value=old_value,
                failure=failure,
                status="approved",
                approved_by="claude:high_confidence",
                source="claude",
                confidence="high",
                annual_report_item=proposal.get("annual_report_item"),
                annual_report_value_raw=proposal.get("annual_report_value_raw"),
                annual_report_unit=proposal.get("unit"),
                evidence_lines=proposal.get("evidence_lines"),
                reason=(
                    f"subagent 升级通道：读年报干净 Markdown 定位『{proposal.get('annual_report_item')}』"
                    f"金额 {new_value:.4f} 百万元，服务端按净残差 {context.get('net_residual')} "
                    f"验闭合通过。操作={op}。{proposal.get('reasoning') or ''}"
                ),
                source_markdown_path=md_path,
                source_reconciliation_path=source_reconciliation_path,
                clean_category=clean_category,
            )
        )
    return records


# ─────────────────────────────────────────────────────────────────────
# override 合并写盘
# ─────────────────────────────────────────────────────────────────────

def merge_and_write_overrides(
    override_path: Path,
    ticker: str,
    new_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """把新 approved override 合并进 annual_report_overrides.json（保留已有）。

    去重：同 (period, field) 已有 approved 记录则跳过，不覆盖已有 LLM 证据。
    """
    if override_path.exists():
        data = json.loads(override_path.read_text(encoding="utf-8"))
    else:
        data = {"version": 1, "ticker": ticker, "adjustments": []}
    adjustments = data.get("adjustments", [])

    existing_keys = {
        (str(a.get("period")), str(a.get("field")))
        for a in adjustments
        if a.get("status") == "approved"
    }
    added = 0
    for rec in new_records:
        key = (str(rec.get("period")), str(rec.get("field")))
        if key in existing_keys:
            continue
        adjustments.append(rec)
        existing_keys.add(key)
        added += 1

    data["adjustments"] = adjustments
    data["ticker"] = ticker
    data["new_adjustments_from_current_run"] = data.get("new_adjustments_from_current_run", 0) + added
    override_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "total": len(adjustments), "path": str(override_path)}


# ─────────────────────────────────────────────────────────────────────
# 跨表 7.4 重述豁免通道
# ─────────────────────────────────────────────────────────────────────
#
# 跨表 7.4（上期CF期末 == 本期CF期初）失败的本质是年报重述：公司在新一年年报的比较列里
# 把上年期末现金追溯重述，TuShare 存的却是各年原始披露值，于是边界不衔接。
#
# 多年连续重述无法用 override 干净闭合——override 一侧会破坏该侧 CF 5.5（期末=期初+净增加），
# 改净增加又级联到 CF 5.4/5.1-5.3；要彻底闭合得整体重载被重述年份的整张现金流量表，fragile
# 且破坏 TuShare 口径。重述是公司披露的会计事件、非数据错误，故走【证据化豁免 → clean 降级软
# warning】，与 2010 闸门降级同性质（有据、可审计，非静默改判）。
#
# 分工（与 BS override 通道一致的反脏配平纪律）：
# - subagent 只读只确认：读本期年报合并现金流量表，抽本期期初现金 + 上年比较列期末现金 +
#   证据行号，返回结构化结果。
# - bridge 服务端验证据：读 subagent 引用的行号，确认其声称的元金额真实出现在年报原文
#   （反幻觉）；再按确定性逻辑闸门判明是真重述（本期期初 == 上年比较列期末 ≥ TuShare 上年期末）。
# - 写 restatement_exemptions.json（source=claude:subagent），clean.py 加载后把该边界降级。

RESTATEMENT_FAIL_RE = re.compile(
    r"上期CF期末\(([0-9.]+)\)\s*≠\s*本期CF期初\(([0-9.]+)\)"
)
# 证据行号引用格式："9418-9419; 9421-9423" 或 "9418"
EVIDENCE_LINE_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+))?")


def build_restatement_context(ticker: str, company_dir: Path, failure: Failure) -> dict[str, Any]:
    """为单个 跨表 7.4 失败构建 subagent 确认所需上下文。

    与 BS 残差 context 不同：这里没有 bucket/candidate 字段（重述不补数），只需指 subagent
    去读本期年报合并现金流量表，抽『期初现金及现金等价物余额』(本期列) 与『期末现金及现金等价物
    余额』(上年比较列) 两个数 + 行号。
    """
    message = failure.message or ""
    m = RESTATEMENT_FAIL_RE.search(message)
    if not m:
        return {
            "kind": "restatement", "failure": failure.__dict__,
            "error": f"无法解析 跨表 7.4 残差金额: {message}",
        }
    prev_end_cash = float(m.group(1))  # TuShare 上年期末（原始披露值）
    cur_beg_cash = float(m.group(2))   # TuShare 本期期初（重述后值，来自本期年报）
    residual = abs(cur_beg_cash - prev_end_cash)
    direction = "restated_up" if cur_beg_cash > prev_end_cash else "restated_down"

    period = str(failure.period)
    try:
        prev_period = str(int(period) - 1)
    except ValueError:
        prev_period = str(clean.period_year(period) - 1)

    md_path = annual_markdown_path(company_dir, period)
    cf_hint = None
    if md_path is not None:
        cf_hint = _locate_consolidated_cf_cash_lines(md_path)

    return {
        "kind": "restatement",
        "failure": failure.__dict__,
        "prev_period": prev_period,
        "prev_end_cash": prev_end_cash,          # 百万元（TuShare 原始）
        "cur_beg_cash": cur_beg_cash,            # 百万元（TuShare = 本期年报期初）
        "net_residual": residual,                # 与 BS context 同名，供 summary 复用
        "net_direction": direction,
        "markdown_path": str(md_path) if md_path else None,
        "cf_section_hint": cf_hint,              # 合并现金流量表 期初/期末现金 行号提示
    }


def _locate_consolidated_cf_cash_lines(md_path: Path) -> dict[str, Any] | None:
    """在年报 Markdown 里定位合并现金流量表的期初/期末现金行号，给 subagent 一个起点。

    合并现金流量表后紧跟『母公司现金流量表』，取该块内最后一次出现的期初/期末现金行。
    返回 {section_start, section_end, beg_line, end_line} 或 None。定位失败不阻塞——
    subagent 仍可自行 Read 全文找。
    """
    try:
        lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    # 找『母公司现金流量表』分界，合并表在其之前
    parent_idx = None
    for i, l in enumerate(lines):
        if "母公司现金流量表" in l:
            parent_idx = i
            break
    scan_end = parent_idx if parent_idx is not None else len(lines)
    beg_line = end_line = None
    section_start = None
    for i in range(scan_end):
        l = lines[i]
        if "合并现金流量表" in l and section_start is None:
            section_start = i + 1
        if "期初现金及现金等价物余额" in l:
            beg_line = i + 1
        if "期末现金及现金等价物余额" in l:
            end_line = i + 1
    if beg_line is None or end_line is None:
        return None
    return {
        "section_start": section_start,
        "section_end": scan_end,
        "beg_line": beg_line,
        "end_line": end_line,
    }


def _read_evidence_lines(md_path: Path, evidence_lines: str) -> str:
    """按 subagent 引用的行号范围（"9418-9419; 9421-9423"）拼出原文文本。"""
    if not md_path or not evidence_lines:
        return ""
    try:
        lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    out: list[str] = []
    for m in EVIDENCE_LINE_RE.finditer(evidence_lines):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        for n in range(start, end + 1):
            if 1 <= n <= len(lines):
                out.append(lines[n - 1])
    return "\n".join(out)


def _value_in_evidence(value_yuan: float, evidence_clean: str) -> bool:
    """校验元金额是否真实出现在年报引用行里（反幻觉）。

    A 股合并现金流量表单位有元、千元两种（少数百万元），同一元值在原文里的写法随单位而变：
      元制   → 5,287,303,894.20 / 5287303894（多带两位小数）
      千元制 → 5,287,303 / 5287303（多写整数，无小数）
    故对元值在「元、千元」两单位下各取整数与两位小数共四种去逗号写法，任一作为子串出现在
    evidence_clean 即认为该披露数字真实存在。反幻觉不单靠此步——闸门 ③-⑥ 要求披露期初同时
    与 TuShare 本期期初、上年期末、残差三者数值吻合才会批准，胡乱报数即便侥幸命中某候选，
    数值闸门也会挡下。
    """
    for divisor in (1.0, 1000.0):  # 元、千元
        scaled = value_yuan / divisor
        for fmt in (".2f", ".0f"):
            if f"{scaled:{fmt}}".replace(",", "") in evidence_clean:
                return True
    return False


def evaluate_restatement_proposal(
    context: dict[str, Any], proposal: dict[str, Any]
) -> dict[str, Any] | None:
    """服务端验证 subagent 重述确认，返回豁免记录或 None（不批）。

    闸门（全确定性，反脏配平/反幻觉）：
    1. confirmed == true；
    2. subagent 引用的年报行号里必须真实出现其声称的『本期期初现金』与『上年比较列期末现金』
       元金额（反幻觉：不许凭空报数）；
    3. 本期期初(披露) == 上年比较列期末(披露)：年报内部自洽（本期期初 = 重述后上年期末）；
    4. 本期期初(披露) == TuShare 本期期初：TuShare 的本期值与年报一致（TuShare 本期是对的）；
    5. 本期期初(披露) != TuShare 上年期末：才是重述（上年 TuShare 存原始值，未被重述覆盖）；
    6. |本期期初(披露) - TuShare 上年期末| ≈ context 残差：残差吻合。

    全过才写豁免：prev_end_cash/cur_beg_cash 取 TuShare 值（clean 据此验豁免仍有效）。
    """
    if not proposal.get("confirmed"):
        return None
    md_path = Path(context.get("markdown_path") or "")
    evidence = _read_evidence_lines(md_path, str(proposal.get("evidence_lines") or ""))
    if not evidence:
        return None
    evidence_clean = evidence.replace(",", "").replace(" ", "").replace("　", "")

    cur_beg_yuan = float(proposal.get("cur_beg_disclosed_yuan") or 0.0)
    prev_end_comp_yuan = float(proposal.get("prev_end_comparative_yuan") or 0.0)
    if cur_beg_yuan <= 0 or prev_end_comp_yuan <= 0:
        return None

    # 闸门 2：披露数字必须真实出现在引用行（反幻觉；元/千元两单位皆可）
    if not _value_in_evidence(cur_beg_yuan, evidence_clean):
        return None
    if not _value_in_evidence(prev_end_comp_yuan, evidence_clean):
        return None

    cur_beg_m = cur_beg_yuan / 1_000_000.0
    prev_end_comp_m = prev_end_comp_yuan / 1_000_000.0
    prev_end_cash = float(context.get("prev_end_cash") or 0.0)
    cur_beg_cash = float(context.get("cur_beg_cash") or 0.0)
    residual = float(context.get("net_residual") or 0.0)

    # 闸门 3：年报本期期初 == 上年比较列期末（内部自洽）
    if abs(cur_beg_m - prev_end_comp_m) >= TOLERANCE:
        return None
    # 闸门 4：披露本期期初 == TuShare 本期期初
    if abs(cur_beg_m - cur_beg_cash) >= TOLERANCE:
        return None
    # 闸门 5：披露本期期初 != TuShare 上年期末（确属重述，非数据错误）
    if abs(cur_beg_m - prev_end_cash) < TOLERANCE:
        return None
    # 闸门 6：残差吻合
    if abs(abs(cur_beg_m - prev_end_cash) - residual) >= TOLERANCE:
        return None

    return {
        "period": str(context["failure"].get("period")),
        "prev_period": context.get("prev_period"),
        "check_code": "跨表 7.4",
        "prev_end_cash": prev_end_cash,
        "cur_beg_cash": cur_beg_cash,
        "residual": residual,
        "status": "approved",
        "source": "claude",
        "approved_by": "claude:high_confidence",
        "annual_report": md_path.name if md_path else None,
        "cur_beg_disclosed_yuan": cur_beg_yuan,
        "prev_end_comparative_yuan": prev_end_comp_yuan,
        "evidence_lines": proposal.get("evidence_lines"),
        "reason": (
            f"重述豁免：本期年报合并现金流量表期初现金 {cur_beg_yuan:.2f} 元 = 上年比较列期末现金 "
            f"{prev_end_comp_yuan:.2f} 元（年报内部自洽，即上年期末被追溯重述）；TuShare 本期期初 "
            f"{cur_beg_cash:.4f} 百万元与年报一致，TuShare 上年期末 {prev_end_cash:.4f} 百万元为原始"
            f"披露值，差额 {residual:.4f} 百万元属披露重述非数据错误。{proposal.get('reasoning') or ''}"
        ),
    }


def merge_and_write_exemptions(
    exemption_path: Path, ticker: str, new_records: list[dict[str, Any]]
) -> dict[str, Any]:
    """把新 approved 重述豁免合并进 restatement_exemptions.json（保留已有，同 period 跳过）。"""
    if exemption_path.exists():
        data = json.loads(exemption_path.read_text(encoding="utf-8"))
    else:
        data = {"version": 1, "ticker": ticker, "exemptions": []}
    exemptions = data.get("exemptions", [])
    existing = {str(e.get("period")) for e in exemptions if e.get("status") == "approved"}
    added = 0
    for rec in new_records:
        if str(rec.get("period")) in existing:
            continue
        exemptions.append(rec)
        existing.add(str(rec.get("period")))
        added += 1
    data["exemptions"] = exemptions
    data["ticker"] = ticker
    exemption_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "total": len(exemptions), "path": str(exemption_path)}


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def _find_company_dir(ticker: str) -> Path:
    return recon.find_company_dir(ticker, None)


def _default_db_path(company_dir: Path) -> Path:
    return recon.default_db_path(company_dir, None)


def cmd_context(args: argparse.Namespace) -> int:
    ticker = args.ticker.strip().upper()
    company_dir = _find_company_dir(ticker)
    db_path = _default_db_path(company_dir)
    company_recon_dir = recon_dir(company_dir)
    override_path = company_recon_dir / "annual_report_overrides.json"

    stderr_text = run_clean_annual(ticker, db_path)
    failures = parse_hard_check_failures(stderr_text)
    if not failures:
        print(json.dumps({"failures": [], "note": "no HARD CHECK FAIL — annual clean already passes"}, ensure_ascii=False))
        return 0

    wide, present_by_period = recon.collect_annual_wide(db_path, ticker)
    approved_overrides = clean.load_approved_overrides(override_path, ticker)
    # 应用已批准 override 到 wide（与 clean.py 生产路径一致），使 candidate 字段值反映已补/已重分类
    if approved_overrides:
        clean.apply_annual_overrides(wide, present_by_period, ticker, approved_overrides)
    field_docs = read_tushare_field_docs()
    known_defects = recon.load_known_defects()

    contexts: list[dict[str, Any]] = []
    for failure in failures:
        period = str(failure.period)
        # 跨表 7.4 走重述豁免通道（不补数、不重分类，只需 subagent 读本期年报确认重述）
        if failure.code == "跨表 7.4":
            contexts.append(build_restatement_context(ticker, company_dir, failure))
            continue
        if period not in wide.index:
            continue
        row = wide.loc[period].to_dict()
        present = present_by_period.get(period, set())
        reclass_for_period = {
            str(o.get("field")): str(o.get("clean_category"))
            for o in approved_overrides
            if str(o.get("period")) == period and o.get("clean_category")
        }
        ctx = build_failure_context(
            ticker, company_dir, db_path, failure, field_docs, known_defects,
            approved_overrides, row, present, reclass_for_period,
        )
        contexts.append(ctx)

    out_path = Path(args.out) if args.out else company_recon_dir / "subagent_context.json"
    out_path.write_text(json.dumps({"ticker": ticker, "contexts": contexts}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "failures": len(failures),
        "contexts": len(contexts),
        "out": str(out_path),
        "summary": [
            {"code": c["failure"]["code"], "period": c["failure"]["period"],
             "kind": c.get("kind", "bs_residual"),
             "net_residual": c.get("net_residual"), "net_direction": c.get("net_direction"),
             "markdown": c.get("markdown_path") is not None}
            for c in contexts
        ],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    ticker = args.ticker.strip().upper()
    company_dir = _find_company_dir(ticker)
    company_recon_dir = recon_dir(company_dir)
    context_path = Path(args.context) if args.context else company_recon_dir / "subagent_context.json"
    proposals_path = Path(args.proposals) if args.proposals else company_recon_dir / "subagent_proposals.json"
    override_path = company_recon_dir / "annual_report_overrides.json"

    if not context_path.exists():
        print(f"context not found: {context_path}（先跑 `context` 模式）", file=sys.stderr)
        return 2
    if not proposals_path.exists():
        print(f"proposals not found: {proposals_path}（SKILL 需先把 subagent 输出合并到此）", file=sys.stderr)
        return 2

    contexts = json.loads(context_path.read_text(encoding="utf-8")).get("contexts", [])
    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    if isinstance(proposals, dict):
        proposals = proposals.get("proposals", [])

    source_recon = str(company_recon_dir / "annual_report_reconciliation_latest.json")
    all_new_records: list[dict[str, Any]] = []
    verdict: list[dict[str, Any]] = []
    for ctx in contexts:
        # 跨表 7.4 重述走 apply-restatements，这里跳过（evaluate_proposals 是 BS 残差专用）
        if ctx.get("kind") == "restatement":
            continue
        approved_pairs = evaluate_proposals(ctx, proposals)
        if approved_pairs:
            records = proposals_to_override_records(
                ctx, approved_pairs, ticker=ticker, source_reconciliation_path=source_recon,
            )
            all_new_records.extend(records)
            verdict.append({
                "code": ctx["failure"]["code"], "period": ctx["failure"]["period"],
                "status": "closed",
                "fields": [r["field"] for r in records],
            })
        else:
            verdict.append({
                "code": ctx["failure"]["code"], "period": ctx["failure"]["period"],
                "status": "not_closed", "net_residual": ctx["net_residual"],
            })

    write_summary = merge_and_write_overrides(override_path, ticker, all_new_records)
    print(json.dumps({
        "verdict": verdict,
        "new_overrides": write_summary["added"],
        "total_overrides": write_summary["total"],
        "override_path": write_summary["path"],
        "next": "重跑 `python -m src.clean --ticker <t> --mode annual` 验证",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_apply_restatements(args: argparse.Namespace) -> int:
    """吃 subagent 重述确认，服务端验证据 + 写 restatement_exemptions.json。"""
    ticker = args.ticker.strip().upper()
    company_dir = _find_company_dir(ticker)
    company_recon_dir = recon_dir(company_dir)
    context_path = Path(args.context) if args.context else company_recon_dir / "subagent_context.json"
    proposals_path = Path(args.proposals) if args.proposals else company_recon_dir / "subagent_restatement_proposals.json"
    exemption_path = company_recon_dir / "restatement_exemptions.json"

    if not context_path.exists():
        print(f"context not found: {context_path}（先跑 `context` 模式）", file=sys.stderr)
        return 2
    if not proposals_path.exists():
        print(f"proposals not found: {proposals_path}（SKILL 需先把重述确认 subagent 输出合并到此）", file=sys.stderr)
        return 2

    contexts = json.loads(context_path.read_text(encoding="utf-8")).get("contexts", [])
    restatement_ctxs = [c for c in contexts if c.get("kind") == "restatement"]
    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    if isinstance(proposals, dict):
        proposals = proposals.get("proposals", [])

    # 按 period 索引 subagent 确认
    by_period: dict[str, dict[str, Any]] = {}
    for p in proposals:
        if isinstance(p, dict) and p.get("period"):
            by_period[str(p.get("period"))] = p

    new_records: list[dict[str, Any]] = []
    verdict: list[dict[str, Any]] = []
    for ctx in restatement_ctxs:
        period = str(ctx["failure"].get("period"))
        proposal = by_period.get(period)
        if not proposal:
            verdict.append({"code": "跨表 7.4", "period": period, "status": "no_proposal"})
            continue
        record = evaluate_restatement_proposal(ctx, proposal)
        if record:
            new_records.append(record)
            verdict.append({"code": "跨表 7.4", "period": period, "status": "exempted",
                            "residual": record["residual"]})
        else:
            verdict.append({"code": "跨表 7.4", "period": period, "status": "rejected",
                            "net_residual": ctx.get("net_residual"),
                            "reason": "证据闸门未过（confirmed/行号金额不符/非重述/残差不吻合）"})

    write_summary = merge_and_write_exemptions(exemption_path, ticker, new_records)
    print(json.dumps({
        "verdict": verdict,
        "new_exemptions": write_summary["added"],
        "total_exemptions": write_summary["total"],
        "exemption_path": write_summary["path"],
        "next": "重跑 `python -m src.clean --ticker <t> --mode annual` 验证（7.4 豁免边界降级为 warning）",
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="init skill subagent 升级通道桥接器")
    sub = p.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("context", help="重跑 clean 取净残差失败 + 算 subagent 上下文")
    pc.add_argument("--ticker", required=True)
    pc.add_argument("--db", default=None)
    pc.add_argument("--out", default=None)
    pc.set_defaults(func=cmd_context)
    pa = sub.add_parser("apply", help="验闭合 subagent 提案 + 写 approved override")
    pa.add_argument("--ticker", required=True)
    pa.add_argument("--context", default=None)
    pa.add_argument("--proposals", default=None)
    pa.set_defaults(func=cmd_apply)
    par = sub.add_parser("apply-restatements", help="验 跨表 7.4 重述确认 + 写 restatement_exemptions.json")
    par.add_argument("--ticker", required=True)
    par.add_argument("--context", default=None)
    par.add_argument("--proposals", default=None)
    par.set_defaults(func=cmd_apply_restatements)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
