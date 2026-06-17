"""Diagnose clean.py hard-check failures against annual-report Markdown.

This is an out-of-band companion for clean.py.  It reuses clean.py's annual
wide-table pipeline and hard-check functions, then inspects the corresponding
annual-report Markdown only for failed checks.  When configured, it asks an LLM
to return structured evidence about whether the failure is likely caused by
missing or wrong TuShare fields.

The script never mutates raw_tushare, clean_annual, clean_quarterly, or data.db.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src import clean
from src.annual_report_utils import (
    COMPANIES_DIR,
    ROOT,
    annual_markdown_path,
    call_llm,
    compact_window,
    default_db_path,
    find_all_lines,
    find_company_dir,
    find_line,
    load_env,
    llm_provider,
    parse_ticker,
    read_md_lines,
    write_json,
)


DOCS_DIR = ROOT / "TushareOfficialAPIMD"
KNOWN_DEFECTS_PATH = ROOT / "knowledge" / "known_tushare_defects.json"

# 单次自动核对分析的年度失败上限。年度失败天然有界（约 ≤10 年年报 × 每年少数
# 勾稽检查），复杂公司（如有金融子公司、逐年漏同一明细字段）可达 30+ 个失败。
# 上限太低会让复杂公司"永远补不全"——简单公司能过、复杂公司悄悄漏，等同隐性公司特判。
# LLM 确认已按失败分片（见 batch_llm_confirm_candidates），单片成本独立，故放宽到可
# 覆盖完整年报历史；仍保留一个上限作为失控保护。
DEFAULT_MAX_FAILURES = 60
EVIDENCE_VERSION = 1
OVERRIDE_VERSION = 1
COMMON_ANNUAL_ALIASES = {
    "lending_funds": "发放贷款和垫款",
    "decr_in_disbur": "发放贷款和垫款",
    "money_cap": "货币资金",
    "nca_within_1y": "一年内到期的非流动资产",
    "oth_cur_assets": "其他流动资产",
    "total_cur_assets": "流动资产合计",
    "total_nca": "非流动资产合计",
    "total_cur_liab": "流动负债合计",
    "total_ncl": "非流动负债合计",
}


@dataclass
class Failure:
    period: str
    code: str
    statement: str
    title: str
    message: str
    residual: float | None
    target_value: float | None
    calc_value: float | None
    direction: str | None


def collect_annual_wide(db_path: Path, ticker: str) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    with sqlite3.connect(db_path) as conn:
        raw = clean.load_raw_tushare(conn, ticker, mode="annual")
    raw = clean.dedupe_by_f_ann_date(raw)
    return clean.pivot_to_wide(raw, mode="annual")


def parse_failure_message(message: str) -> Failure:
    residual_match = re.search(r"residual=([0-9.]+)", message)
    residual = float(residual_match.group(1)) if residual_match else None

    header = re.match(r"(?P<prefix>IS|BS|CF|跨表)\s+(?P<code>[0-9.]+[ab]?)\s+(?P<period>\d{4})\s+(?P<title>[^:：]+)", message)
    if header:
        prefix = header.group("prefix")
        code = f"{prefix} {header.group('code')}"
        period = header.group("period")
        title = header.group("title").strip()
    else:
        code = "UNKNOWN"
        period = "UNKNOWN"
        title = message.split(":", 1)[0]

    statement = {
        "IS": "income",
        "BS": "balancesheet",
        "CF": "cashflow",
        "跨表": "cross_table",
    }.get(code.split(" ", 1)[0], "unknown")

    values = [float(x) for x in re.findall(r"=(-?[0-9.]+)", message)]
    target_value = values[0] if values else None
    calc_value = values[1] if len(values) > 1 else None
    direction = None
    if target_value is not None and calc_value is not None:
        if target_value > calc_value:
            direction = "target_gt_calc"
        elif target_value < calc_value:
            direction = "target_lt_calc"
        else:
            direction = "equal"

    return Failure(
        period=period,
        code=code,
        statement=statement,
        title=title,
        message=message,
        residual=residual,
        target_value=target_value,
        calc_value=calc_value,
        direction=direction,
    )


def collect_failures(wide: pd.DataFrame, present_by_period: dict[str, set[str]]) -> list[Failure]:
    failures: list[Failure] = []
    prev_period_end_cash: float | None = None

    for period in sorted(str(period) for period in wide.index.tolist()):
        row = wide.loc[period].to_dict()
        present = present_by_period.get(period, set())

        messages: list[str] = []
        messages.extend(clean.check_is(row, present, period))
        messages.extend(clean.check_bs(row, present, period)[0])
        messages.extend(clean.check_cf(row, present, period))
        messages.extend(clean.check_is_supplement(row, present, period))
        messages.extend(clean.check_cross_table(row, present, period))

        c_cash_equ_beg = clean.get_cashflow_value(row, "c_cash_equ_beg_period")
        if prev_period_end_cash is not None and c_cash_equ_beg != 0:
            residual = abs(prev_period_end_cash - c_cash_equ_beg)
            if residual >= clean.TOLERANCE:
                messages.append(
                    f"跨表 7.4 {period} 上期CF期末({prev_period_end_cash:.4f}) "
                    f"≠ 本期CF期初({c_cash_equ_beg:.4f}) residual={residual:.4f}"
                )
        prev_period_end_cash = clean.get_cashflow_value(row, "c_cash_equ_end_period")

        failures.extend(parse_failure_message(message) for message in messages)

    return failures


def read_tushare_field_docs() -> dict[str, dict[str, str]]:
    docs = {
        "income": DOCS_DIR / "income.md",
        "balancesheet": DOCS_DIR / "balancesheet.md",
        "cashflow": DOCS_DIR / "cashflow.md",
    }
    out: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s+\|\s+float\s+\|\s+[^|]+\|\s+(.+?)\s*$")
    for endpoint, path in docs.items():
        fields: dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                match = pattern.match(line.strip())
                if match:
                    fields[match.group(1)] = match.group(2).strip()
        out[endpoint] = fields
    return out


def comparative_annual_markdown_path(company_dir: Path, year: str, *, max_offset: int = 2) -> Path | None:
    """Use a later annual report as comparative evidence when the target year is absent."""
    try:
        base_year = int(year)
    except ValueError:
        return None
    for offset in range(1, max_offset + 1):
        path = annual_markdown_path(company_dir, str(base_year + offset))
        if path is not None:
            return path
    return None


def failure_candidate_fields(failure: Failure) -> tuple[str, list[str]]:
    code = failure.code

    if code == "BS 2.1":
        return "current_asset", bs_fields_for_bucket("current_asset")
    if code == "BS 2.2":
        return "noncurrent_asset", bs_fields_for_bucket("noncurrent_asset")
    if code == "BS 3.1":
        return "current_liab", bs_fields_for_bucket("current_liab")
    if code == "BS 3.2":
        return "noncurrent_liab", bs_fields_for_bucket("noncurrent_liab")
    if code == "BS 4.1":
        return "equity", bs_fields_for_bucket("equity")

    if code == "IS 1.1":
        return "cost_item", fields_by_category(clean.IS_FIELD_CATEGORIES, {"cost_item", "subtotal"})
    if code in {"IS 1.2", "IS 1.3", "IS 1.4", "IS 1.5", "IS 6.1", "IS 6.2", "IS 6.3"}:
        return "income_formula", fields_by_category(
            clean.IS_FIELD_CATEGORIES,
            {"revenue_item", "cost_item", "operating_adjustment", "below_line", "tax", "attribution", "comprehensive", "subtotal", "sub_item"},
        )
    if code == "IS 1.6":
        return "revenue_item", fields_by_category(clean.IS_FIELD_CATEGORIES, {"revenue_item", "subtotal"})

    if code == "CF 5.1":
        return "cfo", fields_by_category(clean.CF_FIELD_CATEGORIES, {"cfo_inflow", "cfo_outflow", "subtotal"})
    if code == "CF 5.2":
        return "cfi", fields_by_category(clean.CF_FIELD_CATEGORIES, {"cfi_inflow", "cfi_outflow", "subtotal"})
    if code == "CF 5.3":
        return "cff", fields_by_category(clean.CF_FIELD_CATEGORIES, {"cff_inflow", "cff_outflow", "subtotal"})
    if code in {"CF 5.4", "CF 5.5"}:
        return "cashflow_formula", fields_by_category(clean.CF_FIELD_CATEGORIES, {"subtotal", "balance"})

    return "all_relevant", []


def load_known_defects(path: Path = KNOWN_DEFECTS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [
        item
        for item in data.get("defects", [])
        if isinstance(item, dict) and item.get("status", "active") == "active"
    ]


def known_defect_hints_for_failure(
    failure: Failure,
    row: dict[str, float],
    present: set[str],
    known_defects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bucket, _fields = failure_candidate_fields(failure)
    hints: list[dict[str, Any]] = []

    for defect in known_defects:
        if defect.get("check_code") not in {failure.code, None}:
            continue
        if defect.get("endpoint") not in {failure.statement, None}:
            continue
        if defect.get("bucket_or_scope") not in {bucket, None}:
            continue

        trigger = defect.get("trigger", {})
        if isinstance(trigger, dict) and trigger.get("direction") not in {failure.direction, None}:
            continue

        field = str(defect.get("field") or "")
        field_value = float(row.get(field, 0.0) or 0.0) if field else 0.0
        value_pattern = trigger.get("field_value_pattern") if isinstance(trigger, dict) else None
        if value_pattern == "missing_or_zero" and field:
            if field in present and abs(field_value) >= clean.TOLERANCE:
                continue

        hints.append(
            {
                "id": defect.get("id"),
                "check_code": defect.get("check_code"),
                "endpoint": defect.get("endpoint"),
                "bucket_or_scope": defect.get("bucket_or_scope"),
                "field": field,
                "field_cn": defect.get("field_cn"),
                "clean_category": defect.get("clean_category"),
                "trigger": trigger,
                "current_tushare_value_million_cny": field_value,
                "present_in_raw_tushare": field in present if field else None,
                "llm_hint": defect.get("llm_hint", {}),
                "confirmed_examples": defect.get("confirmed_examples", []),
            }
        )

    return hints


def fields_by_category(categories: dict[str, str], selected: set[str]) -> list[str]:
    return sorted(field for field, cat in categories.items() if cat in selected)


def bs_fields_for_bucket(bucket: str) -> list[str]:
    fields = [field for field, cat in clean.BS_FIELD_CATEGORIES.items() if cat == bucket]
    for combo, (_splits, combo_bucket) in clean.COMBO_RESOLVE.items():
        if combo_bucket == bucket:
            fields.append(combo)
    return sorted(set(fields))


def statement_endpoint_for_field(failure: Failure, field: str) -> str:
    if failure.statement == "cross_table":
        if field in clean.CF_FIELD_CATEGORIES:
            return "cashflow"
        return "income"
    if failure.statement in {"income", "balancesheet", "cashflow"}:
        return failure.statement
    return "unknown"


def build_field_context(
    failure: Failure,
    row: dict[str, float],
    present: set[str],
    field_docs: dict[str, dict[str, str]],
    known_defect_hints: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    _bucket, fields = failure_candidate_fields(failure)
    if not fields:
        fields = sorted(
            set(clean.IS_FIELD_CATEGORIES)
            | set(clean.BS_FIELD_CATEGORIES)
            | set(clean.CF_FIELD_CATEGORIES)
        )

    # 已知缺陷提示卡命中的字段，即便其 TuShare 静态分类不在本 bucket（如
    # estimated_liab 默认非流动、但本公司列报为流动负债），也要纳入候选，
    # 否则 reconciler 永远提不出这个补数。clean_category/别名从提示卡透传。
    hint_meta: dict[str, dict[str, Any]] = {}
    for hint in known_defect_hints or []:
        field = str(hint.get("field") or "")
        if not field:
            continue
        llm_hint = hint.get("llm_hint", {}) if isinstance(hint.get("llm_hint"), dict) else {}
        hint_meta[field] = {
            "clean_category": hint.get("clean_category") or llm_hint.get("clean_category"),
            "alias": hint.get("field_cn") or (llm_hint.get("search_aliases") or [None])[0],
        }
    fields = sorted(set(fields) | set(hint_meta))

    context: list[dict[str, Any]] = []
    for field in fields:
        endpoint = statement_endpoint_for_field(failure, field)
        col = field
        if endpoint == "income" and field in clean.CROSS_ENDPOINT_FIELDS:
            col = f"income.{field}"
        elif endpoint == "cashflow" and field in clean.CROSS_ENDPOINT_FIELDS:
            col = f"cashflow.{field}"

        value = float(row.get(col, row.get(field, 0.0)) or 0.0)
        desc = field_docs.get(endpoint, {}).get(field, "")
        if value == 0.0 and field not in present and desc == "" and field not in hint_meta:
            continue
        meta = hint_meta.get(field, {})
        context.append(
            {
                "field": field,
                "endpoint": endpoint,
                "description": desc,
                "annual_report_alias": COMMON_ANNUAL_ALIASES.get(field) or meta.get("alias"),
                "value_million_cny": value,
                "present_in_raw_tushare": field in present,
                "clean_category": meta.get("clean_category"),
            }
        )

    context.sort(key=lambda item: (abs(float(item["value_million_cny"])) == 0.0, item["field"]))
    return context


def section_markers(failure: Failure) -> list[list[str]]:
    if failure.statement == "balancesheet":
        return [["合并及公司资产负债表"], ["资产负债表"]]
    if failure.statement == "income":
        return [["合并及公司利润表"], ["利润表"]]
    if failure.statement == "cashflow":
        return [["合并及公司现金流量表"], ["现金流量表"]]
    return [["合并及公司"], ["财务报表"]]


def search_terms_for_failure(failure: Failure, field_context: list[dict[str, Any]]) -> list[str]:
    terms = [failure.title.strip()]
    alias_items = [item for item in field_context[:80] if COMMON_ANNUAL_ALIASES.get(str(item.get("field")))]
    alias_items.sort(key=lambda item: (abs(float(item.get("value_million_cny") or 0.0)) != 0.0, str(item.get("field"))))
    for item in alias_items:
        alias = COMMON_ANNUAL_ALIASES.get(str(item.get("field")))
        if alias and alias not in terms:
            terms.append(alias)
    for item in field_context[:80]:
        desc = str(item.get("description") or "").strip()
        if desc and desc not in terms:
            terms.append(desc)
    return [term for term in terms if term]


def add_known_defect_search_terms(terms: list[str], hints: list[dict[str, Any]]) -> list[str]:
    hint_terms: list[str] = []
    for hint in hints:
        llm_hint = hint.get("llm_hint", {})
        if isinstance(llm_hint, dict):
            hint_terms.extend(str(alias) for alias in llm_hint.get("search_aliases", []) if alias)
        if hint.get("field_cn"):
            hint_terms.append(str(hint["field_cn"]))

    out = hint_terms + list(terms)
    uniq: list[str] = []
    for term in out:
        term = term.strip()
        if term and term not in uniq:
            uniq.append(term)
    return uniq[:24]


def slim_field_context_for_llm(field_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep LLM input compact while preserving likely missing-field candidates."""
    slim: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in field_context:
        field = str(item.get("field"))
        desc = str(item.get("description") or "")
        value = float(item.get("value_million_cny") or 0.0)
        keep = value != 0.0 or field in COMMON_ANNUAL_ALIASES or any(term in desc for term in ("贷款", "垫款", "融资", "资金"))
        if keep and field not in seen:
            slim.append(item)
            seen.add(field)
    return slim[:80]


def slim_markdown_context_for_llm(markdown_context: dict[str, Any]) -> dict[str, Any]:
    snippets = markdown_context.get("snippets")
    if not isinstance(snippets, list):
        return markdown_context
    # glm-5-turbo carries 150–200k context, so there is no reason to collapse to
    # a single truncated snippet. Keep the full statement snippet plus a generous
    # set of term snippets; only bound the total to stay well within context.
    MAX_SNIPPETS = 24
    PER_SNIPPET_CHARS = 24000
    TOTAL_CHARS = 160000
    compact_snippets: list[dict[str, Any]] = []
    total = 0
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        text = str(snippet.get("text", ""))[:PER_SNIPPET_CHARS]
        if total + len(text) > TOTAL_CHARS:
            break
        compact = dict(snippet)
        compact["text"] = text
        compact_snippets.append(compact)
        total += len(text)
        if len(compact_snippets) >= MAX_SNIPPETS:
            break
    return {**markdown_context, "snippets": compact_snippets}


def _overlaps(span: tuple[int, int], used_ranges: list[tuple[int, int]]) -> bool:
    return any(not (span[1] < old[0] or old[1] < span[0]) for old in used_ranges)


def extract_markdown_context(
    failure: Failure,
    md_path: Path,
    field_context: list[dict[str, Any]],
    known_defect_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lines = read_md_lines(md_path)
    snippets: list[dict[str, Any]] = []
    used_ranges: list[tuple[int, int]] = []

    # 1. Statement-level snippet (balance sheet / income / cashflow).
    #    A full consolidated statement can run several hundred extracted lines —
    #    e.g. companies with financial subsidiaries push receivables/financing
    #    lines 250+ lines below the heading. A short window silently cut those
    #    off, so the residual-matching line was never seen. glm-5-turbo carries
    #    150–200k context, so capture the whole statement generously.
    for marker in section_markers(failure):
        idx = find_line(lines, marker)
        if idx is not None:
            window = compact_window(lines, idx, before=10, after=520)
            snippets.append({"kind": "statement", "patterns": marker, **window})
            used_ranges.append((window["start_line"], window["end_line"]))
            break

    # 2. Term-level snippets: generate one for *every* occurrence so the LLM
    #    can pick the context where the matching number actually appears.
    #    glm-5-turbo context is 150–200k; 40 snippets of ~120 lines each is
    #    well within budget and avoids dropping the relevant occurrence.
    terms = add_known_defect_search_terms(
        search_terms_for_failure(failure, field_context),
        known_defect_hints or [],
    )
    MAX_TERM_SNIPPETS = 40
    for term in terms:
        indices = find_all_lines(lines, [term])
        for idx in indices:
            center_line = idx + 1
            # Only skip when this exact occurrence line is already inside a
            # captured snippet; mere window overlap must not drop an occurrence,
            # otherwise the line that actually carries the matching amount can
            # fall into the gap between two adjacent snippets.
            if any(lo <= center_line <= hi for lo, hi in used_ranges):
                continue
            window = compact_window(lines, idx, before=20, after=100)
            snippets.append({"kind": "term", "term": term, **window})
            used_ranges.append((window["start_line"], window["end_line"]))
            if len(snippets) >= MAX_TERM_SNIPPETS:
                break
        if len(snippets) >= MAX_TERM_SNIPPETS:
            break

    return {
        "markdown_path": str(md_path),
        "snippets": snippets,
    }


def llm_prompt(
    ticker: str,
    company_dir: Path,
    failure: Failure,
    field_context: list[dict[str, Any]],
    markdown_context: dict[str, Any],
    known_defect_hints: list[dict[str, Any]],
) -> list[dict[str, str]]:
    payload = {
        "ticker": ticker,
        "company_dir": str(company_dir),
        "failure": asdict(failure),
        "tushare_unit": "百万元人民币",
        "annual_report_unit": "通常为千元人民币；如片段另有说明，以片段为准。换算到 TuShare 口径需除以 1000。",
        "known_tushare_defect_hints": known_defect_hints,
        "candidate_tushare_fields": slim_field_context_for_llm(field_context),
        "annual_report_markdown_context": slim_markdown_context_for_llm(markdown_context),
    }

    system = (
        "你是A股财报勾稽核对专家。你的任务是判断 clean.py 的硬校验失败是否可能由 TuShare "
        "字段缺失、字段取错、字段口径不完整或重复字段口径导致。必须只基于用户提供的 TuShare "
        "字段值和年报 Markdown 片段作判断，不要编造片段外的数据。"
    )
    user = (
        "请核对下面的失败项。输出必须是一个 JSON object，不要输出 Markdown。\n"
        "JSON schema:\n"
        "{\n"
        '  "suspected_tushare_issue": boolean,\n'
        '  "confidence": "high|medium|low",\n'
        '  "failure_code": string,\n'
        '  "period": string,\n'
        '  "root_cause": string,\n'
        '  "missing_or_suspicious_items": [\n'
        "    {\n"
        '      "annual_report_item": string,\n'
        '      "annual_report_value_raw": number|null,\n'
        '      "annual_report_unit": string,\n'
        '      "value_million_cny": number|null,\n'
        '      "candidate_tushare_field": string|null,\n'
        '      "tushare_value_million_cny": number|null,\n'
        '      "explains_residual": boolean,\n'
        '      "residual_difference_million_cny": number|null,\n'
        '      "evidence_lines": string\n'
        "    }\n"
        "  ],\n"
        '  "duplicate_or_combo_risks": [string],\n'
        '  "recommended_action": "none|manual_review|add_override|fix_classification|fix_combo_resolve|rerun_clean",\n'
        '  "notes": string\n'
        "}\n\n"
        "判断要求：\n"
        "1. 如果年报某个明细科目能解释 target-calc 残差，优先指出该科目和对应 TuShare 字段；"
        "candidate_tushare_fields 里的 annual_report_alias 是本地维护的年报常见别名，可用于映射。\n"
        "2. known_tushare_defect_hints 只是检索提示，不是证据；只有年报片段金额真正解释残差时才可据此判断。\n"
        "3. 如果残差更像重复计入、分类错误或公式口径问题，不要误判为 TuShare 错。\n"
        "4. 年报金额若是千元，换算成百万元时除以 1000。\n"
        "5. residual_difference_million_cny 应填 abs(失败残差 - 该年报科目换算后的百万元值)。\n"
        "6. evidence_lines 填引用的片段行号范围和简短证据，不要大段复制。\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def analyze_failure(
    ticker: str,
    company_dir: Path,
    failure: Failure,
    row: dict[str, float],
    present: set[str],
    field_docs: dict[str, dict[str, str]],
    known_defects: list[dict[str, Any]],
    *,
    use_llm: bool,
) -> dict[str, Any]:
    known_defect_hints = known_defect_hints_for_failure(failure, row, present, known_defects)
    field_context = build_field_context(failure, row, present, field_docs, known_defect_hints)
    md_path = annual_markdown_path(company_dir, failure.period)
    comparative_source = False
    if md_path is None:
        md_path = comparative_annual_markdown_path(company_dir, failure.period)
        comparative_source = md_path is not None
    markdown_context: dict[str, Any]
    if md_path is None:
        markdown_context = {"error": f"No annual markdown found for {failure.period}"}
    else:
        markdown_context = extract_markdown_context(failure, md_path, field_context, known_defect_hints)
        if comparative_source:
            markdown_context["comparative_source_for_period"] = failure.period
            markdown_context["comparative_source_note"] = (
                "Target-year annual report was not available; this later annual report is used because "
                "annual financial statements usually include a comparative column for the prior year."
            )

    result: dict[str, Any] = {
        "failure": asdict(failure),
        "bucket_or_scope": failure_candidate_fields(failure)[0],
        "known_tushare_defect_hints": known_defect_hints,
        "candidate_tushare_fields": field_context,
        "annual_report_context": markdown_context,
        "llm": None,
    }

    if use_llm and md_path is not None:
        messages = llm_prompt(ticker, company_dir, failure, field_context, markdown_context, known_defect_hints)
        result["llm"] = call_llm(messages)

    return result


def output_path(company_dir: Path, explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    ts = time.strftime("%Y%m%d_%H%M%S")
    return company_dir / "recon" / f"annual_report_reconciliation_{ts}.json"


def parse_report_number(value: str) -> float | None:
    cleaned = value.strip()
    if cleaned in {"", "-", "—"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()").replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -number if negative else number


def numbered_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        match = re.match(r"\s*(\d+):\s*(.*)$", raw)
        if match:
            out.append((int(match.group(1)), match.group(2)))
    return out


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def annual_report_aliases_for_field(field: dict[str, Any], hint_aliases: list[str]) -> list[str]:
    aliases: list[str] = []
    if field.get("annual_report_alias"):
        aliases.append(str(field["annual_report_alias"]))
    desc = str(field.get("description") or "").strip()
    if desc:
        aliases.append(desc)
        # Official TuShare descriptions sometimes carry unit suffixes such as
        # "(元)"; annual reports usually print the plain item name.
        aliases.append(re.sub(r"[（(]\s*元\s*[）)]$", "", desc).strip())
    aliases.extend(hint_aliases)

    out: list[str] = []
    for alias in aliases:
        alias = alias.strip()
        if alias and alias not in out:
            out.append(alias)
    return out


def find_alias_amount_matches(
    snippets: list[str],
    aliases: list[str],
    *,
    expected_million: float | None = None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for text in snippets:
        lines = numbered_lines(text)
        for idx, (line_no, content) in enumerate(lines):
            matched_alias = next(
                (alias for alias in aliases if compact_text(alias) in compact_text(content)),
                None,
            )
            if not matched_alias:
                continue
            nearby = lines[idx + 1 : idx + 10]
            for value_line_no, value_text in nearby:
                stripped_value = value_text.strip()
                if not re.search(r"\d", stripped_value):
                    if stripped_value in {"", "-", "—", "－"}:
                        continue
                    break
                for token in re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", value_text):
                    raw_value = parse_report_number(token)
                    if raw_value is None:
                        continue
                    candidates = [
                        ("千元人民币", raw_value / 1000.0, "千元"),
                        ("元人民币", raw_value / 1_000_000.0, "元"),
                    ]
                    for unit, value_million, evidence_unit in candidates:
                        if expected_million is None and abs(value_million) < clean.TOLERANCE:
                            continue
                        if expected_million is not None:
                            tolerance = max(1.0, abs(expected_million) * 0.00001)
                            if abs(value_million - expected_million) > tolerance:
                                continue
                        matches.append(
                            {
                                "annual_report_item": matched_alias,
                                "annual_report_value_raw": raw_value,
                                "annual_report_unit": unit,
                                "value_million_cny": value_million,
                                "evidence_lines": f"{line_no}-{value_line_no}: {matched_alias} {token} {evidence_unit}",
                            }
                        )
    return matches


def find_alias_amount_match(
    snippets: list[str],
    aliases: list[str],
    *,
    expected_million: float | None = None,
) -> dict[str, Any] | None:
    matches = find_alias_amount_matches(snippets, aliases, expected_million=expected_million)
    return matches[0] if matches else None


def rule_based_override_suggestions(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Find exact annual-report line-item matches without an LLM.

    This is intentionally conservative: it only suggests fields when an annual
    report alias appears in the statement snippet and the nearby reported
    amount, or a small group of such amounts, equals the hard-check residual
    after converting the annual-report unit to million CNY.
    It is diagnostic-only; approved override generation is LLM-only.
    """
    failure = analysis.get("failure", {})
    residual = failure.get("residual")
    if residual is None:
        return []

    # A target_lt_calc failure (detail sum > subtotal) means TuShare dropped a
    # NEGATIVE line item (e.g. a discontinued-operations loss), so the amount
    # that closes the gap is -residual, not +residual.
    signed_residual = (
        -float(residual)
        if str(failure.get("direction")) == "target_lt_calc"
        else float(residual)
    )

    snippets = [
        str(snippet.get("text") or "")
        for snippet in analysis.get("annual_report_context", {}).get("snippets", [])
        if isinstance(snippet, dict)
    ]
    if not snippets:
        return []

    suggestions: list[dict[str, Any]] = []
    hint_alias_by_field: dict[str, list[str]] = {}
    for hint in analysis.get("known_tushare_defect_hints", []):
        if not isinstance(hint, dict):
            continue
        field = str(hint.get("field") or "")
        llm_hint = hint.get("llm_hint", {})
        aliases = []
        if isinstance(llm_hint, dict):
            aliases.extend(str(alias) for alias in llm_hint.get("search_aliases", []) if alias)
        if hint.get("field_cn"):
            aliases.append(str(hint["field_cn"]))
        if field and aliases:
            hint_alias_by_field[field] = aliases

    matched_items: list[dict[str, Any]] = []
    for field in analysis.get("candidate_tushare_fields", []):
        aliases = annual_report_aliases_for_field(field, hint_alias_by_field.get(str(field.get("field")), []))
        if not aliases:
            continue
        old_value = float(field.get("value_million_cny") or 0.0)
        if abs(old_value) >= clean.TOLERANCE:
            continue
        matches = find_alias_amount_matches(snippets, aliases)
        if not matches:
            continue
        for match in matches:
            item = {
                **match,
                "candidate_tushare_field": field.get("field"),
                "clean_category": field.get("clean_category"),
                "tushare_value_million_cny": old_value,
            }
            matched_items.append(item)
        single_match = find_alias_amount_match(snippets, aliases, expected_million=signed_residual)
        if single_match:
            item = {
                **single_match,
                "candidate_tushare_field": field.get("field"),
                "clean_category": field.get("clean_category"),
                "tushare_value_million_cny": old_value,
            }
            value_million = float(single_match["value_million_cny"])
            suggestions.append(
                {
                    "source": "rule:alias_exact_residual",
                    "confidence": "high",
                    **item,
                    "explains_residual": True,
                    "residual_difference_million_cny": abs(signed_residual - value_million),
                }
            )

    def _evidence_line(sug):
        ev = str(sug.get("evidence_lines") or "")
        return ev.split(":", 1)[0].strip()

    spurious_substring: set[int] = set()
    exact = [s for s in suggestions if s.get("source") == "rule:alias_exact_residual"]
    for i, a in enumerate(exact):
        for bsug in exact:
            if a is bsug:
                continue
            item_a = str(a.get("annual_report_item") or "")
            item_b = str(bsug.get("annual_report_item") or "")
            same_line = _evidence_line(a) == _evidence_line(bsug)
            same_value = abs(float(a.get("value_million_cny") or 0) - float(bsug.get("value_million_cny") or 0)) < clean.TOLERANCE
            if same_line and same_value and item_a != item_b and item_a in item_b:
                spurious_substring.add(id(a))
    if spurious_substring:
        suggestions = [s for s in suggestions if id(s) not in spurious_substring]

    # A single annual-report line item whose name matches a TuShare field and
    # whose value equals the residual is the most reliable signal possible.
    # Speculative groups — several fields whose values merely *sum* to the
    # residual — are far weaker and can attribute the missing amount to the
    # wrong fields (e.g. acc_receivable+amor_exp+lending_funds coincidentally
    # summing to a receiv_financing residual). So only build group candidates
    # when no single exact-residual match exists for this failure.
    has_exact_single = any(s.get("source") == "rule:alias_exact_residual" for s in suggestions)
    grouped_fields: set[str] = set()
    group_range = range(0) if has_exact_single else range(2, min(5, len(matched_items) + 1))
    for size in group_range:
        for group in itertools.combinations(matched_items, size):
            fields = tuple(str(item.get("candidate_tushare_field")) for item in group)
            if len(set(fields)) != len(fields):
                continue
            if any(field in grouped_fields for field in fields):
                continue
            group_total = sum(float(item["value_million_cny"]) for item in group)
            diff = abs(signed_residual - group_total)
            if diff >= clean.TOLERANCE:
                continue
            group_id = f"{failure.get('period')}_{failure.get('code')}_{'_'.join(fields)}"
            group_items = [
                {
                    "candidate_tushare_field": item.get("candidate_tushare_field"),
                    "annual_report_item": item.get("annual_report_item"),
                    "value_million_cny": item.get("value_million_cny"),
                    "evidence_lines": item.get("evidence_lines"),
                }
                for item in group
            ]
            for item in group:
                suggestions.append(
                    {
                        "source": "rule:alias_group_residual",
                        "confidence": "high",
                        **item,
                        "explains_residual": True,
                        "residual_difference_million_cny": diff,
                        "candidate_group_id": group_id,
                        "group_value_million_cny": group_total,
                        "group_residual_difference_million_cny": diff,
                        "group_items": group_items,
                    }
                )
                grouped_fields.add(str(item.get("candidate_tushare_field")))
    return suggestions


def llm_override_suggestions(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    llm = analysis.get("llm")
    if not isinstance(llm, dict) or llm.get("error"):
        return []
    if not llm.get("suspected_tushare_issue"):
        return []
    if llm.get("confidence") != "high":
        return []

    out: list[dict[str, Any]] = []
    provider = str(llm.get("_provider") or llm_provider())
    for item in llm.get("missing_or_suspicious_items", []):
        if not isinstance(item, dict):
            continue
        field = item.get("candidate_tushare_field")
        value = item.get("value_million_cny")
        diff = item.get("residual_difference_million_cny")
        if not field or value is None:
            continue
        if diff is not None and abs(float(diff)) >= clean.TOLERANCE:
            continue
        out.append({"source": provider, "confidence": llm.get("confidence"), **item})
    return out


def collect_rule_candidates(reconciliation: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for analysis in reconciliation.get("analyses", []):
        failure = analysis.get("failure", {})
        for candidate in rule_based_override_suggestions(analysis):
            candidates.append(
                {
                    "period": str(failure.get("period")),
                    "failure": failure,
                    "candidate": candidate,
                }
            )
    return candidates


def format_known_defects_for_prompt(known_defects: list[dict[str, Any]]) -> str:
    """Render active known defects as concise prompt guidance for the LLM."""
    if not known_defects:
        return "（当前无已知 TuShare 缺陷提示卡）"
    lines: list[str] = []
    for defect in known_defects:
        field = defect.get("field", "")
        field_cn = defect.get("field_cn", "")
        check_code = defect.get("check_code", "")
        clean_category = defect.get("clean_category", "")
        llm_hint = defect.get("llm_hint", {}) or {}
        search_aliases = llm_hint.get("search_aliases", [])
        diagnosis = llm_hint.get("diagnosis_hint", "")
        line = f"- {check_code} / {field_cn} ({field}): 年报检索词：{', '.join(search_aliases)}；"
        if clean_category:
            line += f" 如批准需带回 clean_category={clean_category}；"
        line += f" {diagnosis}"
        lines.append(line)
    return "\n".join(lines)


def validate_batch_llm_response(parsed: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitize the JSON object returned by the batch LLM call.

    Required top-level key: adjustments (list).  Each adjustment must contain
    at least period and approved; malformed entries are dropped and counted.
    """
    if "error" in parsed:
        return parsed
    adjustments = parsed.get("adjustments")
    if not isinstance(adjustments, list):
        parsed["error"] = "LLM response missing valid 'adjustments' list"
        parsed["adjustments"] = []
        parsed["_malformed"] = True
        return parsed

    validated: list[dict[str, Any]] = []
    malformed_indices: list[int] = []
    for idx, item in enumerate(adjustments):
        if not isinstance(item, dict):
            malformed_indices.append(idx)
            continue
        if "period" not in item or "approved" not in item:
            malformed_indices.append(idx)
            continue
        validated.append(item)

    parsed["adjustments"] = validated
    if malformed_indices:
        parsed["_malformed_indices"] = malformed_indices
    return parsed


def _confirm_candidate_chunk(
    ticker: str,
    candidates: list[dict[str, Any]],
    known_defects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Confirm one small group of candidates in a single LLM call.

    Kept deliberately small (one hard-check failure's candidates) so the request
    stays well within the provider timeout. See batch_llm_confirm_candidates.
    """
    payload = {
        "ticker": ticker,
        "unit": "TuShare/clean values are 百万元人民币; annual_report_value_raw is 千元人民币.",
        "candidates": candidates,
    }
    system = (
        "你是A股财报勾稽核对专家。你要审核一组候选年报补数。"
        "候选项由本地规则提出，但只有你确认后才可写入 clean override。"
        "必须基于 failure、candidate、evidence_lines 判断，不要编造额外数据。"
    )
    user = (
        "请逐条判断候选补数是否可以作为 TuShare 字段缺失的 approved override。"
        "输出必须是 JSON object，不要输出 Markdown。\n"
        "JSON schema:\n"
        "{\n"
        '  "adjustments": [\n'
        "    {\n"
        '      "period": string,\n'
        '      "approved": boolean,\n'
        '      "confidence": "high|medium|low",\n'
        '      "candidate_tushare_field": string|null,\n'
        '      "value_million_cny": number|null,\n'
        '      "annual_report_item": string|null,\n'
        '      "annual_report_value_raw": number|null,\n'
        '      "annual_report_unit": string|null,\n'
        '      "tushare_value_million_cny": number|null,\n'
        '      "residual_difference_million_cny": number|null,\n'
        '      "evidence_lines": string|null,\n'
        '      "reason": string\n'
        "    }\n"
        "  ],\n"
        '  "notes": string\n'
        "}\n\n"
        "批准标准：\n"
        "1. failure residual 与候选年报值换算为百万元后的金额必须在 1 百万元内吻合；"
        "如果候选项带 candidate_group_id/group_items，则按同一 group 的 group_value_million_cny 与 residual 是否吻合判断，"
        "吻合时可逐条批准该 group 内每个缺失字段。\n"
        "2. 候选字段必须能对应年报科目；如果只是规则猜测但字段不可靠，不批准。\n"
        "3. 只批准 suspected TuShare field missing/zero 的情形；重复计入或分类错误不批准。\n"
        "4. 已知 TuShare 字段缺失模式（按年报核对提示卡），金额吻合且字段匹配时可批准；"
        "不要依赖公司名称，只根据字段和金额判断：\n"
        f"{format_known_defects_for_prompt(known_defects or [])}\n"
        "5. 若候选项带有 clean_category（说明该 TuShare 字段默认 bucket 与本公司列报口径不一致，"
        "如 estimated_liab 预计负债默认非流动但本年列报为流动），且年报金额与残差吻合、"
        "TuShare 该字段缺失/为0，可批准；批准时在该条 adjustment 中原样回传 clean_category 字段。\n\n"
        "若候选项含 clean_category，请在对应 adjustment JSON 中加入 \"clean_category\": string 字段原样返回。\n\n"
        f"输入数据：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return validate_batch_llm_response(
        call_llm([{"role": "system", "content": system}, {"role": "user", "content": user}])
    )


def batch_llm_confirm_candidates(
    ticker: str,
    candidates: list[dict[str, Any]],
    known_defects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Confirm rule-based candidates via the LLM, chunked per hard-check failure.

    A single monolithic call carrying every candidate scales with the number of
    failing periods/buckets; complex companies (many year×bucket failures) make
    that one request slow enough to ReadTimeout, which drops *all* annual-report
    evidence and yields zero overrides. Chunking by (period, code) keeps every
    call small and within the provider timeout, keeps a candidate group's
    members together, and isolates failures: one chunk timing out no longer
    discards the others' confirmations. The return shape stays identical
    (adjustments list + provider/usage metadata) so callers are unaffected.
    """
    if not candidates:
        return {"adjustments": []}

    # Group by hard-check failure; grouped (candidate_group_id) members always
    # share one (period, code) so they stay in the same chunk.
    chunks: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []
    for cand in candidates:
        failure = cand.get("failure", {}) if isinstance(cand, dict) else {}
        key = (str(failure.get("period")), str(failure.get("code")))
        if key not in chunks:
            chunks[key] = []
            order.append(key)
        chunks[key].append(cand)

    merged_adjustments: list[dict[str, Any]] = []
    chunk_errors: list[dict[str, Any]] = []
    usage_total: dict[str, Any] = {}
    provider: str | None = None
    model: str | None = None

    for key in order:
        result = _confirm_candidate_chunk(ticker, chunks[key], known_defects)
        provider = provider or result.get("_provider")
        model = model or result.get("_model")
        usage = result.get("_usage")
        if isinstance(usage, dict):
            for name, value in usage.items():
                if isinstance(value, (int, float)):
                    usage_total[name] = usage_total.get(name, 0) + value
        if result.get("error"):
            chunk_errors.append(
                {
                    "period": key[0],
                    "code": key[1],
                    "error": result.get("error"),
                    "detail": result.get("detail"),
                }
            )
            continue
        merged_adjustments.extend(result.get("adjustments", []))

    out: dict[str, Any] = {"adjustments": merged_adjustments}
    if provider:
        out["_provider"] = provider
    if model:
        out["_model"] = model
    if usage_total:
        out["_usage"] = usage_total
    if chunk_errors:
        out["chunk_errors"] = chunk_errors
        out["partial"] = True
    return out


def _build_adjustment_record(
    ticker: str,
    period: str,
    field: str,
    new_value: float,
    old_value: float,
    failure: dict[str, Any],
    *,
    status: str,
    approved_by: str | None,
    source: str,
    confidence: str | None,
    annual_report_item: str | None,
    annual_report_value_raw: float | None,
    annual_report_unit: str | None,
    evidence_lines: str | None,
    reason: str | None,
    source_markdown_path: str | None,
    source_reconciliation_path: str,
    clean_category: str | None = None,
) -> dict[str, Any]:
    """Construct a single override adjustment record with consistent fields."""
    statement = str(failure.get("statement"))
    endpoint = "balancesheet" if statement == "balancesheet" else statement
    return {
        "status": status,
        "approved_by": approved_by,
        "ticker": ticker,
        "period": period,
        "endpoint": endpoint,
        "field": field,
        "old_value_million_cny": old_value,
        "new_value_million_cny": new_value,
        "delta_million_cny": new_value - old_value,
        "failure_code": failure.get("code"),
        "failure_message": failure.get("message"),
        "annual_report_item": annual_report_item,
        "annual_report_value_raw": annual_report_value_raw,
        "annual_report_unit": annual_report_unit,
        "confidence": confidence,
        "source": source,
        "source_markdown_path": source_markdown_path,
        "source_reconciliation_path": source_reconciliation_path,
        "evidence_lines": evidence_lines,
        "reason": reason,
        "clean_category": clean_category,
    }


def build_override_file_from_batch_llm(
    ticker: str,
    reconciliation_path: Path,
    reconciliation: dict[str, Any],
    llm_confirmation: dict[str, Any],
    *,
    approve_high_confidence: bool,
) -> dict[str, Any]:
    failure_by_period = {
        str(analysis.get("failure", {}).get("period")): analysis.get("failure", {})
        for analysis in reconciliation.get("analyses", [])
    }
    field_values: dict[tuple[str, str], float] = {}
    clean_category_by: dict[tuple[str, str], str] = {}
    markdown_by_period: dict[str, str | None] = {}
    for analysis in reconciliation.get("analyses", []):
        period = str(analysis.get("failure", {}).get("period"))
        markdown_by_period[period] = analysis.get("annual_report_context", {}).get("markdown_path")
        for item in analysis.get("candidate_tushare_fields", []):
            if isinstance(item, dict):
                field_values[(period, str(item.get("field")))] = float(item.get("value_million_cny") or 0.0)
                if item.get("clean_category"):
                    clean_category_by[(period, str(item.get("field")))] = str(item["clean_category"])

    adjustments: list[dict[str, Any]] = []
    provider = str(llm_confirmation.get("_provider") or llm_provider())
    for item in llm_confirmation.get("adjustments", []):
        if not isinstance(item, dict):
            continue
        if not item.get("approved") or item.get("confidence") != "high":
            continue
        field = item.get("candidate_tushare_field")
        period = str(item.get("period"))
        value = item.get("value_million_cny")
        if not field or value is None:
            continue

        failure = failure_by_period.get(period, {})
        old_value = field_values.get((period, str(field)), float(item.get("tushare_value_million_cny") or 0.0))
        new_value = float(value)
        status = "approved" if approve_high_confidence else "candidate"
        adjustments.append(
            _build_adjustment_record(
                ticker=ticker,
                period=period,
                field=str(field),
                new_value=new_value,
                old_value=old_value,
                failure=failure,
                status=status,
                approved_by=f"{provider}:high_confidence" if status == "approved" else None,
                source=provider,
                confidence=item.get("confidence"),
                annual_report_item=item.get("annual_report_item"),
                annual_report_value_raw=item.get("annual_report_value_raw"),
                annual_report_unit=item.get("annual_report_unit"),
                evidence_lines=item.get("evidence_lines"),
                reason=item.get("reason"),
                source_markdown_path=markdown_by_period.get(period),
                source_reconciliation_path=str(reconciliation_path),
                clean_category=clean_category_by.get((period, str(field))),
            )
        )

    return {
        "version": OVERRIDE_VERSION,
        "ticker": ticker,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "annual_report_reconciler.py",
        "source_reconciliation_path": str(reconciliation_path),
        "approval_policy": "LLM-only; approved only when --approve-high-confidence is used",
        "llm_provider": provider,
        "llm_confirmation": llm_confirmation,
        "adjustments": adjustments,
    }


def merge_existing_overrides(override_path: Path, overrides: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Preserve existing override adjustments when regenerating the default file."""
    if not override_path.exists():
        return overrides
    try:
        existing = json.loads(override_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return overrides
    if existing.get("ticker") not in {ticker, None}:
        return overrides

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in existing.get("adjustments", []):
        if not isinstance(item, dict):
            continue
        period, endpoint, field = item.get("period"), item.get("endpoint"), item.get("field")
        if period and endpoint and field:
            key = (str(period), str(endpoint), str(field))
            merged[key] = item

    new_count = 0
    for item in overrides.get("adjustments", []):
        if not isinstance(item, dict):
            continue
        period, endpoint, field = item.get("period"), item.get("endpoint"), item.get("field")
        if period and endpoint and field:
            key = (str(period), str(endpoint), str(field))
            merged[key] = item
            new_count += 1

    out = dict(overrides)
    out["adjustments"] = [
        merged[key]
        for key in sorted(
            merged,
            key=lambda value: (value[0], value[1], value[2]),
        )
    ]
    out["merged_existing_override_path"] = str(override_path)
    out["new_adjustments_from_current_run"] = new_count
    out["preserved_existing_adjustments"] = max(len(out["adjustments"]) - new_count, 0)
    return out


def build_override_file(
    ticker: str,
    reconciliation_path: Path,
    reconciliation: dict[str, Any],
    *,
    approve_high_confidence: bool,
) -> dict[str, Any]:
    adjustments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for analysis in reconciliation.get("analyses", []):
        failure = analysis.get("failure", {})
        candidates = llm_override_suggestions(analysis)
        field_values = {
            item.get("field"): float(item.get("value_million_cny") or 0.0)
            for item in analysis.get("candidate_tushare_fields", [])
            if isinstance(item, dict)
        }
        markdown_path = analysis.get("annual_report_context", {}).get("markdown_path")
        for candidate in candidates:
            period = str(failure.get("period"))
            field = str(candidate.get("candidate_tushare_field"))
            if not period or not field or (period, field) in seen:
                continue
            new_value = float(candidate["value_million_cny"])
            old_value = field_values.get(field, float(candidate.get("tushare_value_million_cny") or 0.0))
            status = "approved" if approve_high_confidence and candidate.get("confidence") == "high" else "candidate"
            source = str(candidate.get("source"))
            adjustments.append(
                _build_adjustment_record(
                    ticker=ticker,
                    period=period,
                    field=field,
                    new_value=new_value,
                    old_value=old_value,
                    failure=failure,
                    status=status,
                    approved_by=f"{source}:high_confidence_exact_residual" if status == "approved" else None,
                    source=source,
                    confidence=candidate.get("confidence"),
                    annual_report_item=candidate.get("annual_report_item"),
                    annual_report_value_raw=candidate.get("annual_report_value_raw"),
                    annual_report_unit=candidate.get("annual_report_unit"),
                    evidence_lines=candidate.get("evidence_lines"),
                    reason=(
                        f"{candidate.get('annual_report_item')} from annual report explains "
                        f"{failure.get('code')} residual; applying to TuShare field {field}."
                    ),
                    source_markdown_path=markdown_path,
                    source_reconciliation_path=str(reconciliation_path),
                )
            )
            seen.add((period, field))

    return {
        "version": OVERRIDE_VERSION,
        "ticker": ticker,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "annual_report_reconciler.py",
        "source_reconciliation_path": str(reconciliation_path),
        "approval_policy": "LLM-only; approved only when --approve-high-confidence is used",
        "adjustments": adjustments,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 000333.SZ")
    parser.add_argument("--company-dir", help="Company directory; defaults to companies/*_{code}")
    parser.add_argument("--db", help="SQLite data.db path; defaults to company-dir/data.db")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES)
    parser.add_argument("--only-year", help="Limit to one annual period, e.g. 2025")
    parser.add_argument("--only-code", help="Limit to one check code, e.g. 'BS 2.1'")
    parser.add_argument("--no-llm", action="store_true", help="Do not call the configured LLM; only collect snippets/context")
    parser.add_argument("--no-kimi", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--write-overrides", action="store_true", help="Write recon/annual_report_overrides.json from high-confidence LLM evidence")
    parser.add_argument("--approve-high-confidence", action="store_true", help="Mark exact high-confidence LLM override suggestions as approved")
    parser.add_argument("--override-output", help="Override JSON path; defaults to recon/annual_report_overrides.json")
    parser.add_argument("--fail-on-findings", action="store_true", help="Exit with code 1 when hard-check failures are found")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.no_kimi:
        args.no_llm = True
    if args.write_overrides and args.no_llm:
        print("--write-overrides requires LLM evidence; remove --no-llm.", file=sys.stderr)
        return 2

    load_env(ROOT / ".env")

    ticker = args.ticker.strip().upper()
    company_dir = find_company_dir(ticker, args.company_dir)
    db_path = default_db_path(company_dir, args.db)

    wide, present_by_period = collect_annual_wide(db_path, ticker)
    failures = collect_failures(wide, present_by_period)

    if args.only_year:
        failures = [failure for failure in failures if failure.period == args.only_year]
    if args.only_code:
        failures = [failure for failure in failures if failure.code == args.only_code]

    total_failures = len(failures)
    failures = failures[: max(args.max_failures, 0)]
    field_docs = read_tushare_field_docs()
    known_defects = load_known_defects()

    analyses: list[dict[str, Any]] = []
    use_llm = not args.no_llm and not args.write_overrides
    for failure in failures:
        row = wide.loc[failure.period].to_dict()
        present = present_by_period.get(failure.period, set())
        if args.verbose:
            print(f"Analyzing {failure.code} {failure.period}: {failure.title}", file=sys.stderr)
        analyses.append(
            analyze_failure(
                ticker,
                company_dir,
                failure,
                row,
                present,
                field_docs,
                known_defects,
                use_llm=use_llm,
            )
        )

    out = {
        "version": EVIDENCE_VERSION,
        "ticker": ticker,
        "company_dir": str(company_dir),
        "db_path": str(db_path),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "annual_report_reconciler.py",
        "total_failures_found": total_failures,
        "failures_analyzed": len(analyses),
        "llm_provider": llm_provider(),
        "known_defects_path": str(KNOWN_DEFECTS_PATH),
        "known_defects_loaded": len(known_defects),
        "used_llm": use_llm or args.write_overrides,
        "used_llm_per_failure": use_llm,
        "requested_llm_override_confirmation": bool(args.write_overrides),
        "analyses": analyses,
    }

    path = output_path(company_dir, args.output)
    write_json(path, out)
    latest_path = company_dir / "recon" / "annual_report_reconciliation_latest.json"
    write_json(latest_path, out)

    override_path: Path | None = None
    if args.write_overrides:
        override_path = Path(args.override_output).resolve() if args.override_output else company_dir / "recon" / "annual_report_overrides.json"
        rule_candidates = collect_rule_candidates(out)
        llm_confirmation = batch_llm_confirm_candidates(ticker, rule_candidates, known_defects=known_defects)
        overrides = build_override_file_from_batch_llm(
            ticker,
            path,
            out,
            llm_confirmation,
            approve_high_confidence=args.approve_high_confidence,
        )
        overrides = merge_existing_overrides(override_path, overrides, ticker)
        write_json(override_path, overrides)

    print(f"Wrote {path}")
    print(f"Wrote {latest_path}")
    if override_path is not None:
        approved = sum(1 for item in overrides["adjustments"] if item.get("status") == "approved")
        print(f"Wrote {override_path} ({approved}/{len(overrides['adjustments'])} approved adjustment(s)).")
    print(f"Found {total_failures} failure(s), analyzed {len(analyses)}.")
    if args.fail_on_findings and total_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
