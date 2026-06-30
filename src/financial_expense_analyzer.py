"""Analyze annual-report financial-expense notes and archive per-year details.

This module produces two artifacts:

1. ``companies/{公司}/Agent/financial_expense.yaml`` — the canonical historical archive
   of financial-expense decompositions, one entry per clean_annual period.
2. ``companies/{公司}/Agent/recon/financial_expense_detail_latest.json`` — a debug/
   audit snapshot of the most recent single-period run.

It never writes ``defaults.yaml``.  The downstream consumer is
``src.defaults_gen``, which reads the YAML archive and decides whether to
override the mechanical ``income.financial_expense`` values.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from src import clean
from src.annual_report_utils import (
    COMPANIES_DIR,
    ROOT,
    annual_markdown_path,
    call_llm,
    compact_window,
    default_db_path,
    find_company_dir,
    find_line,
    load_env,
    parallel_map,
    read_json,
    read_md_lines,
    write_json,
)
from src.company_paths import financial_expense_path, recon_dir


EVIDENCE_VERSION = 2
TOLERANCE = 1.0  # 百万元
INTEREST_BEARING_DEBT_FIELDS = [
    "st_borr",
    "st_fin_payable",
    "st_bonds_payable",
    "non_cur_liab_due_1y",
    "lt_borr",
    "bond_payable",
    "lease_liab",
]

BASIS_HYPOTHESES = {
    "gross": ("interest_expense_gross",),
    "net_of_capitalized": ("interest_expense_gross", "capitalized_interest"),
    "net_of_subsidy": ("interest_expense_gross", "interest_subsidy"),
    "net_of_capitalized_and_subsidy": (
        "interest_expense_gross",
        "capitalized_interest",
        "interest_subsidy",
    ),
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def default_evidence_path(company_dir: Path) -> Path:
    return recon_dir(company_dir) / "financial_expense_detail_latest.json"


def default_yaml_path(company_dir: Path) -> Path:
    return financial_expense_path(company_dir)


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------


def _yaml_dump(data: dict[str, Any]) -> str:
    import yaml  # type: ignore
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )


def write_financial_expense_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_dump(data), encoding="utf-8")


def load_financial_expense_yaml(company_dir: Path) -> dict[str, Any] | None:
    path = default_yaml_path(company_dir)
    if not path.exists():
        return None
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError, ImportError):
        pass
    return None


def load_evidence(company_dir: Path) -> dict[str, Any] | None:
    """Load the latest single-period evidence JSON (debug/audit artifact)."""
    path = default_evidence_path(company_dir)
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Data reading
# ---------------------------------------------------------------------------


def _read_annual_rows(db_path: Path, ticker: str) -> list[tuple[str, dict[str, float]]]:
    with closing(sqlite3.connect(db_path)) as conn:
        raw = clean.load_raw_tushare(conn, ticker, mode="annual")
    raw = clean.dedupe_by_f_ann_date(raw)
    wide, _present = clean.pivot_to_wide(raw, mode="annual")
    if wide.empty:
        raise ValueError("clean_annual is empty")
    rows: list[tuple[str, dict[str, float]]] = []
    for period in sorted(str(p) for p in wide.index.tolist()):
        row = wide.loc[period].to_dict()
        rows.append((period, row))
    return rows


def _read_latest_annual_row(db_path: Path, ticker: str) -> tuple[str, dict[str, float], dict[str, set[str]]]:
    with sqlite3.connect(db_path) as conn:
        raw = clean.load_raw_tushare(conn, ticker, mode="annual")
    raw = clean.dedupe_by_f_ann_date(raw)
    wide, present_by_period = clean.pivot_to_wide(raw, mode="annual")
    if wide.empty:
        raise ValueError("clean_annual is empty")
    latest_period = str(wide.index.max())
    row = wide.loc[latest_period].to_dict()
    return latest_period, row, present_by_period


def _anchor_values(row: dict[str, float], prev_row: dict[str, float] | None = None) -> dict[str, float]:
    debt = sum(row.get(field, 0.0) for field in INTEREST_BEARING_DEBT_FIELDS)
    cash = row.get("money_cap", 0.0)
    if prev_row is None:
        avg_debt = debt
        avg_cash = cash
    else:
        prev_debt = sum(prev_row.get(field, 0.0) for field in INTEREST_BEARING_DEBT_FIELDS)
        prev_cash = prev_row.get("money_cap", 0.0)
        avg_debt = (prev_debt + debt) / 2.0
        avg_cash = (prev_cash + cash) / 2.0
    return {
        "fin_exp": row.get("fin_exp", 0.0),
        "fin_exp_int_exp": row.get("fin_exp_int_exp", 0.0),
        "fin_exp_int_inc": row.get("fin_exp_int_inc", 0.0),
        "interest_bearing_debt": debt,
        "money_cap": cash,
        "avg_interest_bearing_debt": avg_debt,
        "avg_money_cap": avg_cash,
        "revenue": row.get("revenue", 0.0),
    }


# ---------------------------------------------------------------------------
# Markdown slicing and LLM prompt
# ---------------------------------------------------------------------------


# 识别「财务费用」附注靠结构形状，不靠列头措辞。
# 利润表/合并报表里也出现「财务费用」行，但那行后面紧跟数字（当期/上期金额）；
# 而附注标题（如「44、财务费用」）后面跟的是表头/标签行（「项目」「本期金额」等，非数字）。
# 用「标题 + 紧随非数字行」这个形状差异区分附注与报表行，避免枚举 本期发生额/本期金额/本期数/本年金额
# 等随准则版本漂移的列头字符串——每出一个新措辞就不必再补一行。
_NOTE_HEADING = re.compile(
    r"^\s*(?:\d+\s*[、.．:）)]|[（(][一二三四五六七八九十百\d]+[)）]|[一二三四五六七八九十]+、)?\s*财务费用\s*$"
)
# 带编号前缀的附注标题（如「65、财务费用」「（六十五）财务费用」「六十五、财务费用」）。
# A 股年报附注标题强制带序号；利润表里的「财务费用」行是裸标题，不带序号。用这个差异
# 优先命中真正的附注标题，避开利润表「财务费用 + 附注索引标签(如 七．65)」的伪标题——
# 后者「财务费用」后跟的「七．65」是非数字的索引标签，形状上和「附注标题+表头」无法区分。
_NOTE_PREFIX = re.compile(
    r"^\s*(?:\d+\s*[、.．:）)]|[（(][一二三四五六七八九十百\d]+[)）]|[一二三四五六七八九十]+、)"
)
# 纯数字行（含千分位、负号、括号负数、百分号、破折号空值），用于判断「紧随后行是否为数值」。
_NUMERIC_LINE = re.compile(r"^\s*[（(]?-?[\d,]+(?:\.\d+)?%?[)）]?\s*$|^\s*[—–-]\s*$")


def _is_numeric_line(s: str) -> bool:
    return bool(_NUMERIC_LINE.match(s))


def _slice_financial_expense_note(lines: list[str]) -> dict[str, Any] | None:
    """Find the financial-expense note table by structural shape, return a compact window.

    不匹配列头字符串：只在「财务费用」附注标题后紧跟非数字行（表头/标签）时命中，
    从而与利润表里「财务费用」行（后跟数值）区分。列头措辞交给 LLM 按年份语义识别。

    两遍扫描：第一遍只认带编号前缀的附注标题（准则标准格式「65、财务费用」）；找不到
    再退回第二遍认裸「财务费用」标题。利润表里「财务费用」行后常跟附注索引标签（如
    「七．65」，非数字），裸标题无编号前缀被第一遍跳过，从而落点优先到真正的编号附注
    标题，避开利润表伪标题。保留裸标题回退以兼容序号格式异常的年报。

    质量门：标题后表体必须含可读数值。PDF→MD 偶发把老年报扫描页转成 mojibake
    （标题「36、财务费用」在、表体全是乱码、一个数字都没有）——这种 note 不可用，
    跳过它让外层 attempts fall through 到下一份年报（如改用后一年报的上期列）。
    """
    for require_prefix in (True, False):
        for idx, line in enumerate(lines):
            if not _NOTE_HEADING.match(line):
                continue
            if require_prefix and not _NOTE_PREFIX.match(line):
                continue
            j = idx + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines) or _is_numeric_line(lines[j]):
                continue  # 后紧跟数值 = 利润表「财务费用」行，非附注
            numeric_count = sum(
                1 for k in range(idx + 1, min(idx + 61, len(lines)))
                if _is_numeric_line(lines[k])
            )
            if numeric_count < 2:
                continue  # 表体无数值（乱码段），不可用
            window = compact_window(lines, idx, before=5, after=60)
            return {
                "start_line": window["start_line"],
                "end_line": window["end_line"],
                "text": window["text"],
            }
    return None


def _llm_prompt(
    ticker: str,
    base_period: str,
    report_year: str,
    anchors: dict[str, float],
    note: dict[str, Any],
) -> list[dict[str, str]]:
    payload = {
        "ticker": ticker,
        "base_period": base_period,
        "report_year": report_year,
        "clean_anchors_million_cny": anchors,
        "note_unit": "元人民币",
        "note_snippet": note,
    }
    system = (
        "你是A股财报附注解析专家。你的任务是从年报「财务费用」附注表中提取指定年度的明细，"
        "并换算成「百万元人民币」。不要编造表格外数据。"
    )
    user = (
        f"下面是 {report_year} 年年度报告中的「财务费用」附注片段。"
        f"请提取 **{base_period} 年** 对应那一列的各项明细——"
        f"若 {base_period} 与 {report_year} 相同取本期列，若 {base_period} 是 {report_year} 的上一年则取上期列；"
        "按片段中列头与年份的语义对应关系选列（列头措辞不固定，可能是 本期发生额/本期金额/本期数/本年金额 或直接标年份，按语义匹配即可）。\n"
        "换算规则：元人民币 → 百万元人民币，除以 1,000,000。\n"
        "符号规则（关键）：\n"
        "- interest_expense_gross = 利润表「利息费用」行口径：利息支出（银行借款/租赁负债/债券利息支出等，正数）"
        "＋「未确认融资费用转回」（正数加项）－「减：未实现融资收益转回」。"
        "资本化利息、财政贴息不在此列（另计）。这样与 TuShare fin_exp_int_exp 对齐，避免分类飘移。\n"
        "- 资本化利息支出：表中通常以负数列示（加：资本化的利息支出），取绝对值，作为正数 capitalized_interest。\n"
        "- 财政贴息冲减财务费用：表中通常以负数列示，取绝对值，作为正数 interest_subsidy。\n"
        "- 利息收入：表中通常以负数列示，取绝对值，作为正数 interest_income。\n"
        "- 其他非利息项目（净汇兑损益、手续费、其他财务费用等）保持表中符号，计入 other_non_interest。\n"
        "如果某项目为空或不存在，填 0。\n\n"
        "输出必须是一个 JSON object，不要输出 Markdown。\n"
        "JSON schema:\n"
        "{\n"
        '  "components": {\n'
        '    "interest_expense_gross": number,  // 利息支出合计（不含资本化），单位：百万元\n'
        '    "capitalized_interest": number,    // 资本化利息，正数，单位：百万元\n'
        '    "interest_subsidy": number,        // 财政贴息，正数，单位：百万元\n'
        '    "interest_income": number,         // 利息收入，正数，单位：百万元\n'
        '    "other_non_interest": number       // 汇兑损益+手续费+其他，保持表内符号，单位：百万元\n'
        '  },\n'
        '  "confidence": "high|medium|low",\n'
        '  "notes": string\n'
        "}\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_llm_response(parsed: dict[str, Any]) -> dict[str, Any] | None:
    components = parsed.get("components") if isinstance(parsed, dict) else None
    if not isinstance(components, dict):
        return None
    keys = [
        "interest_expense_gross",
        "capitalized_interest",
        "interest_subsidy",
        "interest_income",
        "other_non_interest",
    ]
    try:
        values = {k: float(components.get(k, 0.0) or 0.0) for k in keys}
    except (TypeError, ValueError):
        return None
    return {
        "components": values,
        "confidence": str(parsed.get("confidence", "low")).lower(),
        "notes": str(parsed.get("notes", "")),
    }


# ---------------------------------------------------------------------------
# Derivation and checks
# ---------------------------------------------------------------------------


def _derive_params(components: dict[str, float], anchors: dict[str, float]) -> dict[str, float]:
    interest_expense = components["interest_expense_gross"] - components["capitalized_interest"]
    interest_income = components["interest_income"]
    other_fin_exp_abs = anchors["fin_exp"] - interest_expense + interest_income
    debt = anchors.get("avg_interest_bearing_debt", anchors["interest_bearing_debt"])
    cash = anchors.get("avg_money_cap", anchors["money_cap"])
    return {
        "interest_expense": interest_expense,
        "interest_income": interest_income,
        "other_fin_exp_abs": other_fin_exp_abs,
        "interest_expense_rate": interest_expense / debt if debt else 0.0,
        "cash_interest_rate": interest_income / cash if cash else 0.0,
    }


def _detect_basis(components: dict[str, float], clean_int_exp: float) -> dict[str, Any]:
    candidates = {}
    for name, fields in BASIS_HYPOTHESES.items():
        value = components["interest_expense_gross"]
        for field in fields[1:]:
            value -= components[field]
        candidates[name] = value

    sorted_candidates = sorted(
        candidates.items(),
        key=lambda item: abs(item[1] - clean_int_exp),
    )
    detected_name, detected_value = sorted_candidates[0]
    residual = abs(detected_value - clean_int_exp)
    return {
        "candidates": candidates,
        "detected": detected_name,
        "detected_value": detected_value,
        "clean_value": clean_int_exp,
        "residual": residual,
    }


def _run_checks(
    derived: dict[str, float],
    components: dict[str, float],
    anchors: dict[str, float],
    basis: dict[str, Any],
    llm_confidence: str,
) -> dict[str, Any]:
    total_check_value = derived["interest_expense"] - derived["interest_income"] + derived["other_fin_exp_abs"]
    total_residual = abs(total_check_value - anchors["fin_exp"])
    total_ok = total_residual <= TOLERANCE

    # basis_check 把 LLM 抽的利息支出跟 TuShare 的 fin_exp_int_exp 交叉比对，是「额外」校验。
    # 当 TuShare 该字段为 0/缺失（A 股常见 TuShare 缺口，年报有而 TuShare 留空）时，这个交叉
    # 比对没有独立基准可用——属 N/A，不是年报证据有问题。此时不应用 basis 否决 approved；
    # total_check（components 求和=fin_exp，残差 0）才是真正的完整性门，仍照常把关。
    clean_int_exp = anchors.get("fin_exp_int_exp", 0.0)
    basis_applicable = abs(clean_int_exp) > TOLERANCE
    basis_ok = (not basis_applicable) or (basis["residual"] <= TOLERANCE)
    basis_skip_reason = None if basis_applicable else "TuShare fin_exp_int_exp=0/缺失，basis 交叉校验 N/A"

    fin_exp = anchors["fin_exp"]
    other = derived["other_fin_exp_abs"]
    other_ratio = abs(other) / abs(fin_exp) if abs(fin_exp) > 10 else None
    other_to_revenue = abs(other) / abs(anchors["revenue"]) if anchors["revenue"] else None
    # other_check 防 LLM 把残差全塞进 other 却因 total_check 平凡通过而误 approved。
    # 但分母用 fin_exp（利息收支冲减后的净额），货币资金充裕、利息收入大的公司
    # 净额被冲小、比例放大，1.0/2.0 会误伤正常情形（如永艺 2017 basis N/A=1.06、
    # 2025 basis 通过=2.40）。提到 5.0 容纳利息收入冲减；完整性仍由 total_check
    # （分量求和=fin_exp）+ basis_check（利息支出 vs TuShare）+ extraction_check（非全0）三道把关。
    other_ratio_threshold = 5.0
    other_ok = True
    other_warning = None
    if other_ratio is not None and other_ratio > other_ratio_threshold:
        other_ok = False
        other_warning = f"other_fin_exp_abs / fin_exp = {other_ratio:.2f} (basis {'N/A' if not basis_applicable else 'applicable'}, 阈值 {other_ratio_threshold})"
    elif other_to_revenue is not None and other_to_revenue > 0.10:
        other_ok = False
        other_warning = f"other_fin_exp_abs / revenue = {other_to_revenue:.2f}"

    # 抽取退化守卫：fin_exp≠0 但利息支出与利息收入均为 0 → 几乎必是抽取失败
    # （真实非零财务费用一定有利息收支活动；全 0 时 other_fin_exp_abs=fin_exp，
    # total_check 平凡通过）。强制 low，堵住 basis N/A 路径下「自信但错」的缺口。
    extraction_ok = not (
        abs(fin_exp) > TOLERANCE
        and components["interest_expense_gross"] == 0.0
        and components["interest_income"] == 0.0
    )
    extraction_warning = None if extraction_ok else (
        "fin_exp≠0 但利息支出与利息收入均为 0，疑似抽取失败（全部金额塞进 other）"
    )

    confidence = "low"
    if llm_confidence == "high" and total_ok and basis_ok and other_ok and extraction_ok:
        confidence = "high"
    elif llm_confidence in {"high", "medium"} and total_ok and basis_ok and extraction_ok:
        confidence = "medium"

    status = "approved" if confidence == "high" else "fallback"

    return {
        "total_check": {
            "value": total_check_value,
            "target": anchors["fin_exp"],
            "residual": total_residual,
            "ok": total_ok,
        },
        "basis_check": {
            "detected": basis["detected"],
            "detected_value": basis["detected_value"],
            "clean_value": basis["clean_value"],
            "residual": basis["residual"],
            "applicable": basis_applicable,
            "skip_reason": basis_skip_reason,
            "ok": basis_ok,
        },
        "other_check": {
            "ok": other_ok,
            "warning": other_warning,
            "other_to_fin_exp": other_ratio,
            "other_to_revenue": other_to_revenue,
        },
        "extraction_check": {
            "ok": extraction_ok,
            "warning": extraction_warning,
        },
        "confidence": confidence,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Single-period analysis
# ---------------------------------------------------------------------------


def _analyze_period(
    ticker: str,
    company_dir: Path,
    db_path: Path,
    base_period: str,
    row: dict[str, float],
    prev_row: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Analyze one clean_annual period.  Returns a period record."""
    anchors = _anchor_values(row, prev_row)

    # 先试 base_period 年报（取本期列），再试 base_period+1 年报（取上期列）。
    # 列头措辞不在此判定——LLM 拿到 report_year + base_period 按年份语义选列。
    attempts = [
        (base_period, "本期"),
        (str(int(base_period) + 1), "上期"),
    ]
    report_year = attempts[0][0]
    target_column = None
    md_path = None
    note: dict[str, Any] | None = None
    for attempt_report_year, col_kind in attempts:
        attempt_path = annual_markdown_path(company_dir, attempt_report_year)
        if attempt_path is None:
            continue
        lines = read_md_lines(attempt_path)
        attempt_note = _slice_financial_expense_note(lines)
        if attempt_note is None:
            continue
        report_year = attempt_report_year
        target_column = f"{base_period}年（{attempt_report_year}年报{col_kind}列）"
        md_path = attempt_path
        note = attempt_note
        break

    record: dict[str, Any] = {
        "report_year": report_year,
        "target_column": target_column,
        "source_markdown_path": str(md_path) if md_path else None,
        "anchors": anchors,
        "llm": None,
        "components": None,
        "derived": None,
        "checks": None,
        "status": "error",
        "confidence": "low",
    }

    if md_path is None or note is None or target_column is None:
        record["error"] = (
            f"No financial expense note found for report years "
            f"{attempts[0][0]} (本期) or {attempts[1][0]} (上期)"
        )
        return record

    messages = _llm_prompt(ticker, base_period, report_year, anchors, note)
    llm_response = call_llm(messages)
    record["llm"] = llm_response

    # 区分两类失败：
    # - status="error"：LLM 调用本身失败（429/超时/截断/空 env/key 未配置），可重试，
    #   下次 init 自动重跑（_archive_covers 把非 approved 期视作待重跑）。
    # - status="fallback"：LLM 答了但不可解析或低置信，是证据不足非调用故障。
    if isinstance(llm_response, dict) and llm_response.get("error") and not llm_response.get("components"):
        record["error"] = f"LLM call failed: {llm_response['error']}"
        record["status"] = "error"
        return record

    parsed = _parse_llm_response(llm_response)
    if parsed is None:
        record["error"] = "LLM response did not contain valid components"
        record["status"] = "fallback"
        return record

    record["components"] = parsed["components"]
    derived = _derive_params(parsed["components"], anchors)
    record["derived"] = derived

    basis = _detect_basis(parsed["components"], anchors["fin_exp_int_exp"])
    record["basis_detection"] = basis

    checks = _run_checks(
        derived,
        parsed["components"],
        anchors,
        basis,
        parsed["confidence"],
    )
    record["checks"] = checks
    record["confidence"] = checks["confidence"]
    record["status"] = checks["status"]

    return record


def _build_latest_evidence(
    ticker: str,
    company_dir: Path,
    db_path: Path,
    base_period: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Build the legacy single-period evidence JSON from a period record."""
    return {
        "version": EVIDENCE_VERSION,
        "ticker": ticker,
        "company_dir": str(company_dir),
        "db_path": str(db_path),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_period": base_period,
        "report_year": record.get("report_year"),
        "target_column": record.get("target_column"),
        "source_markdown_path": record.get("source_markdown_path"),
        "anchors": record.get("anchors"),
        "llm": record.get("llm"),
        "components": record.get("components"),
        "derived": record.get("derived"),
        "checks": record.get("checks"),
        "basis_detection": record.get("basis_detection"),
        "status": record.get("status"),
        "confidence": record.get("confidence"),
        "error": record.get("error"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    ticker: str,
    db_path: Path | None = None,
    company_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Analyze the latest clean_annual period and write the single-period evidence JSON.

    This is the legacy/debug entry point.  The canonical archive is built by
    ``analyze_all_periods()``.
    """
    if company_dir is None:
        company_dir = find_company_dir(ticker)
    db_path = default_db_path(company_dir, str(db_path) if db_path else None)

    evidence_path = default_evidence_path(company_dir)
    if evidence_path.exists() and not force:
        return evidence_path

    rows = _read_annual_rows(db_path, ticker)
    base_period, row = rows[-1]
    prev_row = rows[-2][1] if len(rows) > 1 else None
    record = _analyze_period(ticker, company_dir, db_path, base_period, row, prev_row)
    evidence = _build_latest_evidence(ticker, company_dir, db_path, base_period, record)
    write_json(evidence_path, evidence)
    return evidence_path


def _archive_covers(
    archive: dict[str, Any] | None,
    rows: list[tuple[str, dict[str, float]]],
    company_dir: Path,
) -> bool:
    """旧 archive 是否完整覆盖 clean_annual 所有期、无需重跑。

    任一期缺失、版本过期、或非 approved 且仍有匹配年报 MD 可重试 → 返回 False。
    非 approved 但无年报 MD 的期（pre-IPO/未下载）作为永久无证据接受，不触发重跑。
    """
    if archive is None:
        return False
    if int(archive.get("version") or 0) != EVIDENCE_VERSION:
        return False
    periods = archive.get("periods")
    if not isinstance(periods, dict):
        return False
    for base_period, _row in rows:
        record = periods.get(base_period)
        if isinstance(record, dict) and record.get("status") == "approved" and record.get("confidence") == "high":
            continue
        try:
            next_report_year = str(int(base_period) + 1)
        except (TypeError, ValueError):
            return False
        has_md = (
            annual_markdown_path(company_dir, str(base_period)) is not None
            or annual_markdown_path(company_dir, next_report_year) is not None
        )
        if has_md:
            return False  # 非 approved 且有 MD → 值得重跑
    return True


def _is_approved_record(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and record.get("status") == "approved"
        and record.get("confidence") == "high"
        and bool((record.get("checks") or {}).get("total_check", {}).get("ok"))
    )


def analyze_all_periods(
    ticker: str,
    db_path: Path | None = None,
    company_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Build the canonical ``financial_expense.yaml`` archive for one company.

    Iterates every period in ``clean_annual`` and, when a matching annual-report
    Markdown exists, extracts the financial-expense note decomposition.  The
    resulting YAML is the historical archive; ``defaults_gen`` reads the latest
    approved year from it.

    增量合并：非 force 时复用旧 archive 里 approved+high 且 total_check 过的记录，
    只重跑非 approved 的期（含 LLM 调用失败的 error 期、低置信 fallback 期、新增期），
    合并写入——避免每次 init 把已通过期也重调 LLM。force 时全重跑。
    """
    if company_dir is None:
        company_dir = find_company_dir(ticker)
    db_path = default_db_path(company_dir, str(db_path) if db_path else None)

    yaml_path = default_yaml_path(company_dir)
    old_archive: dict[str, Any] | None = None
    if yaml_path.exists() and not force:
        old_archive = load_financial_expense_yaml(company_dir)

    rows = _read_annual_rows(db_path, ticker)
    if not force and old_archive is not None and _archive_covers(old_archive, rows, company_dir):
        return yaml_path

    rows_with_prev = [
        (period, row, rows[idx - 1][1] if idx > 0 else None)
        for idx, (period, row) in enumerate(rows)
    ]

    # 旧 archive 里可复用的 approved 记录（仅同版本且非 force）。
    old_periods: dict[str, Any] = {}
    if not force and isinstance(old_archive, dict) and int(old_archive.get("version") or 0) == EVIDENCE_VERSION:
        old_periods = old_archive.get("periods") or {}

    def _keep(period: str) -> bool:
        return _is_approved_record(old_periods.get(period))

    to_run = [(p, row, prev) for (p, row, prev) in rows_with_prev if not _keep(p)]

    # 只重跑非 approved 的期；每期独立（自己的 MD 切片 + LLM 调用，无共享状态），
    # 并发跑。parallel_map 保持输入顺序。
    records = parallel_map(
        lambda item: _analyze_period(ticker, company_dir, db_path, item[0], item[1], item[2]),
        to_run,
    ) if to_run else []

    periods: dict[str, Any] = {}
    latest_period: str | None = None
    latest_record: dict[str, Any] | None = None
    run_iter = iter(records)
    for base_period, _row, _prev in rows_with_prev:
        record = old_periods[base_period] if _keep(base_period) else next(run_iter)
        periods[base_period] = record
        if latest_period is None or base_period > latest_period:
            latest_period = base_period
            latest_record = record

    data: dict[str, Any] = {
        "version": EVIDENCE_VERSION,
        "analyzer_version": EVIDENCE_VERSION,
        "retry_policy": "retry_non_approved_periods_merge_approved_keep",
        "ticker": ticker,
        "company_dir": str(company_dir),
        "db_path": str(db_path),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "annual_report.fin_exp_note",
        "periods": periods,
    }
    write_financial_expense_yaml(yaml_path, data)

    # Also keep the latest-period JSON as a debug/audit artifact.
    if latest_record is not None:
        evidence = _build_latest_evidence(
            ticker, company_dir, db_path, latest_period, latest_record
        )
        write_json(default_evidence_path(company_dir), evidence)

    return yaml_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze annual-report financial-expense notes and archive per-year details."
    )
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 002946.SZ")
    parser.add_argument("--company-dir", help="Company directory; defaults to companies/*_{code}")
    parser.add_argument("--db", help="SQLite data.db path; defaults to company-dir/Agent/data.db")
    parser.add_argument("--force", action="store_true", help="Regenerate archive even if it exists")
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Only analyze the latest clean_annual period and write the debug evidence JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env(ROOT / ".env")
    company_dir = find_company_dir(args.ticker, args.company_dir) if args.company_dir else None
    db_path = Path(args.db) if args.db else None
    try:
        if args.latest_only:
            path = analyze(args.ticker, db_path=db_path, company_dir=company_dir, force=args.force)
        else:
            path = analyze_all_periods(
                args.ticker, db_path=db_path, company_dir=company_dir, force=args.force
            )
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {args.ticker}: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
