"""Analyze annual-report financial-expense notes and archive per-year details.

This module produces two artifacts:

1. ``companies/{公司}/financial_expense.yaml`` — the canonical historical archive
   of financial-expense decompositions, one entry per clean_annual period.
2. ``companies/{公司}/recon/financial_expense_detail_latest.json`` — a debug/
   audit snapshot of the most recent single-period run.

It never writes ``defaults.yaml``.  The downstream consumer is
``src.defaults_gen``, which reads the YAML archive and decides whether to
override the mechanical ``income.financial_expense`` values.
"""

from __future__ import annotations

import argparse
import json
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
    read_json,
    read_md_lines,
    write_json,
)


EVIDENCE_VERSION = 1
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
    return company_dir / "recon" / "financial_expense_detail_latest.json"


def default_yaml_path(company_dir: Path) -> Path:
    return company_dir / "financial_expense.yaml"


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


def _anchor_values(row: dict[str, float]) -> dict[str, float]:
    debt = sum(row.get(field, 0.0) for field in INTEREST_BEARING_DEBT_FIELDS)
    cash = row.get("money_cap", 0.0)
    return {
        "fin_exp": row.get("fin_exp", 0.0),
        "fin_exp_int_exp": row.get("fin_exp_int_exp", 0.0),
        "fin_exp_int_inc": row.get("fin_exp_int_inc", 0.0),
        "interest_bearing_debt": debt,
        "money_cap": cash,
        "revenue": row.get("revenue", 0.0),
    }


# ---------------------------------------------------------------------------
# Markdown slicing and LLM prompt
# ---------------------------------------------------------------------------


def _slice_financial_expense_note(lines: list[str]) -> dict[str, Any] | None:
    """Find the financial-expense note table and return a compact window."""
    for idx, line in enumerate(lines):
        if "财务费用" not in line:
            continue
        stripped = line.strip().lstrip("-").strip()
        if not stripped or ("财务费用" not in stripped):
            continue
        nearby = lines[idx : idx + 8]
        has_current = any("本期发生额" in ln for ln in nearby)
        has_previous = any("上期发生额" in ln for ln in nearby)
        if has_current and has_previous:
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
        "target_column": "上期发生额",
        "note_snippet": note,
    }
    system = (
        "你是A股财报附注解析专家。你的任务是从年报「财务费用」附注表中提取指定年度的明细，"
        "并换算成「百万元人民币」。不要编造表格外数据。"
    )
    user = (
        "请读取下面年报片段中的「财务费用」附注表，提取 base_period 对应的「上期发生额」列数据。\n"
        "换算规则：元人民币 → 百万元人民币，除以 1,000,000。\n"
        "符号规则（关键）：\n"
        "- 利息支出类项目（银行借款利息支出、租赁负债利息支出、债券利息支出等）取正数，计入 interest_expense_gross。\n"
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
    debt = anchors["interest_bearing_debt"]
    cash = anchors["money_cap"]
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

    basis_ok = basis["residual"] <= TOLERANCE

    fin_exp = anchors["fin_exp"]
    other = derived["other_fin_exp_abs"]
    other_ratio = abs(other) / abs(fin_exp) if abs(fin_exp) > 10 else None
    other_to_revenue = abs(other) / abs(anchors["revenue"]) if anchors["revenue"] else None
    other_ok = True
    other_warning = None
    if other_ratio is not None and other_ratio > 2.0:
        other_ok = False
        other_warning = f"other_fin_exp_abs / fin_exp = {other_ratio:.2f}"
    elif other_to_revenue is not None and other_to_revenue > 0.10:
        other_ok = False
        other_warning = f"other_fin_exp_abs / revenue = {other_to_revenue:.2f}"

    confidence = "low"
    if llm_confidence == "high" and total_ok and basis_ok and other_ok:
        confidence = "high"
    elif llm_confidence in {"high", "medium"} and total_ok and basis_ok:
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
            "ok": basis_ok,
        },
        "other_check": {
            "ok": other_ok,
            "warning": other_warning,
            "other_to_fin_exp": other_ratio,
            "other_to_revenue": other_to_revenue,
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
) -> dict[str, Any]:
    """Analyze one clean_annual period.  Returns a period record."""
    anchors = _anchor_values(row)
    report_year = str(int(base_period) + 1)

    md_path = annual_markdown_path(company_dir, report_year)
    note: dict[str, Any] | None = None
    if md_path is not None:
        lines = read_md_lines(md_path)
        note = _slice_financial_expense_note(lines)

    record: dict[str, Any] = {
        "report_year": report_year,
        "source_markdown_path": str(md_path) if md_path else None,
        "anchors": anchors,
        "llm": None,
        "components": None,
        "derived": None,
        "checks": None,
        "status": "error",
        "confidence": "low",
    }

    if md_path is None:
        record["error"] = f"No annual markdown found for report year {report_year}"
        return record

    if note is None:
        record["error"] = f"Financial expense note not found in {md_path}"
        return record

    messages = _llm_prompt(ticker, base_period, report_year, anchors, note)
    llm_response = call_llm(messages)
    record["llm"] = llm_response

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

    base_period, row, _present = _read_latest_annual_row(db_path, ticker)
    record = _analyze_period(ticker, company_dir, db_path, base_period, row)
    evidence = _build_latest_evidence(ticker, company_dir, db_path, base_period, record)
    write_json(evidence_path, evidence)
    return evidence_path


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
    """
    if company_dir is None:
        company_dir = find_company_dir(ticker)
    db_path = default_db_path(company_dir, str(db_path) if db_path else None)

    yaml_path = default_yaml_path(company_dir)
    if yaml_path.exists() and not force:
        return yaml_path

    rows = _read_annual_rows(db_path, ticker)
    periods: dict[str, Any] = {}
    latest_period: str | None = None
    latest_record: dict[str, Any] | None = None

    for base_period, row in rows:
        record = _analyze_period(ticker, company_dir, db_path, base_period, row)
        periods[base_period] = record
        if latest_period is None or base_period > latest_period:
            latest_period = base_period
            latest_record = record

    data: dict[str, Any] = {
        "version": EVIDENCE_VERSION,
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
    parser.add_argument("--db", help="SQLite data.db path; defaults to company-dir/data.db")
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
