"""Extract self-described business revenue breakdowns from annual-report Markdown.

The extractor is intentionally conservative. It targets the recurring annual
report tables where companies describe their own operating split: by product,
industry, region, and sales model. It keeps source line numbers so analysts can
audit every extracted row against the original report.

Example:
    python -m src.business_breakdown_extractor --year 2024 --tickers 600031,300866
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from src.annual_report_utils import parallel_map
from src.company_paths import annual_reports_dir, official_breakdowns_dir, quarterly_reports_dir


ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"


DIMENSION_LABELS = {
    "industry": "行业",
    "product": "产品",
    "region": "地区",
    "sales_model": "销售模式",
    "volume": "产销量",
    "cost_composition": "成本构成",
}

DIMENSION_PATTERNS = [
    ("industry", re.compile(r"^(主营业务)?分行业(情况)?$")),
    ("industry", re.compile(r"^行业$")),
    ("product", re.compile(r"^(主营业务)?分产品(情况)?$")),
    ("region", re.compile(r"^(主营业务)?分地区(情况)?$")),
    ("sales_model", re.compile(r"^(主营业务)?分销售模式(情况)?$")),
    ("sales_model", re.compile(r"^销售模式$")),
]

# 产销量情况分析表 / 成本分析表 是"收入和成本分析"同节里的另两张表，
# 结构与主营收四维表不同（列数/语义不同），由专用解析器处理，不走主状态机。
VOLUME_SECTION_START_RE = re.compile(r"产销量情况分析表")
COST_SECTION_START_RE = re.compile(r"成本分析表")

VOLUME_UNIT_RE = re.compile(
    r"^(万千升|千升|升|万吨|吨|千克|克|万件|件|万台|台|万套|套|千米|米|平方米|立方米|"
    r"万千瓦时|千瓦时|度|万瓶|瓶|万箱|箱|万支|支|万盒|盒|万包|包|万桶|桶|张|块|"
    r"万头|头|万只|只|万辆|部)$"
)

# 成本构成项目常见名（用于 segment 跨行时把上一行认作分部）。
COST_ITEM_KEYWORDS = {
    "直接材料", "直接人工", "制造费用", "制造费用及其他", "外购产成品",
    "燃料及动力", "燃料动力", "折旧", "折旧费", "工资及福利", "工资",
    "福利费", "动力", "材料", "人工", "其他",
}

_VOLUME_HEADER_NOISE = {
    "主要", "产品", "主要产品", "生产量", "销售量", "库存量",
    "生产量销售量", "年增减", "比上", "增减", "生产量比上",
    "销售量比上年", "库存量比上年", "情况", "说明",
}

_COST_HEADER_NOISE = {
    "分行业", "分产品", "分行业情况", "分产品情况", "成本构成项目",
    "本期金额", "本期占总成本比例", "上年同期金额", "上年同期占总成本比例",
    "本期金额较上年同期变动比例", "情况", "说明", "情况说明",
}

# 专用 section 内需要按片段过滤的表头残留。
_SECTION_HEADER_FRAGMENTS = ("增减", "比上", "占总成本", "较上年同期变动", "成本构成")

NUMBER_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
OUTPUT_CSV_NAME = "business_revenue_breakdown.csv"
OUTPUT_JSONL_NAME = "business_revenue_breakdown.jsonl"
OUTPUT_H1_CSV_NAME = "business_revenue_breakdown_h1.csv"
OUTPUT_H1_JSONL_NAME = "business_revenue_breakdown_h1.jsonl"
OUTPUT_ALL_CSV_NAME = "business_revenue_breakdown_all.csv"
OUTPUT_ALL_JSONL_NAME = "business_revenue_breakdown_all.jsonl"


@dataclass
class BusinessBreakdownRow:
    company_name: str
    stock_code: str
    year: int
    period: str
    period_type: str
    period_label: str
    source_file: str
    source_section: str
    source_table: str
    dimension: str
    dimension_label: str
    item_name: str
    revenue: float | None
    revenue_unit: str
    revenue_yuan: float | None
    revenue_pct: float | None
    revenue_previous: float | None
    revenue_previous_yuan: float | None
    revenue_previous_pct: float | None
    revenue_yoy_pct: float | None
    cost: float | None
    cost_yuan: float | None
    cost_yoy_pct: float | None
    gross_margin_pct: float | None
    gross_margin_change: str
    source_line: int
    confidence: str
    raw_values: str
    # 产销量维度（dimension=volume）专用：物理量及其同比。
    quantity_unit: str = ""
    production_qty: float | None = None
    sales_qty: float | None = None
    inventory_qty: float | None = None
    production_yoy_pct: float | None = None
    sales_qty_yoy_pct: float | None = None
    inventory_yoy_pct: float | None = None
    # 成本构成维度（dimension=cost_composition）专用：成本构成项目名。
    cost_item: str = ""


@dataclass
class _Line:
    number: int
    text: str


@dataclass
class _PendingRow:
    dimension: str
    source_section: str
    unit_label: str
    unit_multiplier: float
    start_line: int | None = None
    name_parts: list[str] | None = None
    values: list[str] | None = None
    gross_margin_change_parts: list[str] | None = None

    def __post_init__(self) -> None:
        self.name_parts = [] if self.name_parts is None else self.name_parts
        self.values = [] if self.values is None else self.values
        self.gross_margin_change_parts = (
            [] if self.gross_margin_change_parts is None else self.gross_margin_change_parts
        )

    @property
    def item_name(self) -> str:
        return clean_item_name("".join(self.name_parts or []))


def read_markdown_lines(path: Path) -> list[str]:
    """Read annual-report Markdown with common Chinese encoding fallbacks."""

    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").splitlines()


def infer_company_dir_from_report(path: Path) -> Path:
    for depth in (2, 3):
        try:
            candidate = path.parents[depth]
        except IndexError:
            continue
        if annual_reports_dir(candidate) == path.parent:
            return candidate
        if path.parent.parent == quarterly_reports_dir(candidate):
            return candidate
    return path.parent.parent


def extract_report(path: Path, company_dir: Path | None = None) -> list[BusinessBreakdownRow]:
    company_dir = company_dir or infer_company_dir_from_report(path)
    company_name, stock_code = parse_company_dir(company_dir)
    year, period, period_type, period_label = parse_period(path)
    lines = [_Line(idx + 1, normalize_space(line)) for idx, line in enumerate(read_markdown_lines(path))]

    rows: list[BusinessBreakdownRow] = []
    dimension: str | None = None
    source_section = ""
    unit_label = "元"
    unit_multiplier = 1.0
    pending: _PendingRow | None = None
    active_context_lines = 0

    # 产销量 / 成本构成两张表由专用解析器处理，主营收状态机跳过这些行区间。
    extra_rows: list[BusinessBreakdownRow] = []
    skip_set: set[int] = set()
    skip_starts: set[int] = set()
    for s, e in _find_section_ranges(lines, VOLUME_SECTION_START_RE):
        extra_rows.extend(
            _extract_volume_section(
                lines, s, e, company_name, stock_code, year, period, period_type, period_label, path
            )
        )
        skip_starts.add(s)
        skip_set.update(range(s, e))
    for s, e in _find_section_ranges(lines, COST_SECTION_START_RE):
        extra_rows.extend(
            _extract_cost_composition_section(
                lines, s, e, company_name, stock_code, year, period, period_type, period_label, path
            )
        )
        skip_starts.add(s)
        skip_set.update(range(s, e))

    for line in lines:
        text = line.text
        if not text:
            continue
        idx = line.number - 1
        if idx in skip_set:
            # 进入专用 section 区间前，先把主状态机里挂起的营收行落盘，避免被跳过丢失。
            if idx in skip_starts:
                append_pending(rows, pending, company_name, stock_code, year, period, period_type, period_label, path)
                pending = None
                dimension = None
            continue
        if active_context_lines > 0:
            active_context_lines -= 1

        new_unit = parse_unit(text)
        if new_unit:
            unit_label, unit_multiplier = new_unit
            if pending is not None and not pending.values:
                pending.unit_label = unit_label
                pending.unit_multiplier = unit_multiplier

        if is_section_hint(text):
            source_section = text
            active_context_lines = 260

        new_dimension = parse_dimension(text)
        if new_dimension and ("主营业务" in text or active_context_lines > 0):
            append_pending(rows, pending, company_name, stock_code, year, period, period_type, period_label, path)
            dimension = new_dimension
            pending = _PendingRow(dimension, source_section, unit_label, unit_multiplier)
            continue

        if is_hard_stop(text):
            append_pending(rows, pending, company_name, stock_code, year, period, period_type, period_label, path)
            pending = None
            dimension = None
            active_context_lines = 0
            continue

        if dimension is None:
            continue
        if is_header_noise(text):
            continue

        numeric_values = numeric_line_values(text)
        if numeric_values:
            if pending is None:
                pending = _PendingRow(dimension, source_section, unit_label, unit_multiplier)
            if pending.start_line is not None and pending.item_name:
                pending.values.extend(numeric_values)
            continue

        mixed_values = mixed_value_line(text)
        if mixed_values and pending is not None and pending.start_line is not None and pending.item_name:
            if len(pending.values or []) < 5:
                pending.values.append(mixed_values[0])
                change_text = text.replace(mixed_values[0], "", 1).strip()
                if change_text:
                    pending.gross_margin_change_parts.append(change_text)
                continue

        if pending is None:
            pending = _PendingRow(dimension, source_section, unit_label, unit_multiplier)

        if is_gross_margin_change_text(text) and pending.values and len(pending.values) >= 5:
            if pending.gross_margin_change_parts and "百分点" in "".join(pending.gross_margin_change_parts):
                continue
            pending.gross_margin_change_parts.append(text)
            continue

        if pending.values and row_has_enough_values(pending):
            append_pending(rows, pending, company_name, stock_code, year, period, period_type, period_label, path)
            pending = _PendingRow(dimension, source_section, unit_label, unit_multiplier)

        if not is_header_noise(text):
            if pending.start_line is None:
                pending.start_line = line.number
            pending.name_parts.append(text)

    append_pending(rows, pending, company_name, stock_code, year, period, period_type, period_label, path)
    rows.extend(extra_rows)
    return dedupe_rows(rows)


def append_pending(
    rows: list[BusinessBreakdownRow],
    pending: _PendingRow | None,
    company_name: str,
    stock_code: str,
    year: int,
    period: str,
    period_type: str,
    period_label: str,
    path: Path,
) -> None:
    if pending is None:
        return
    item_name = pending.item_name
    values = pending.values or []
    if not item_name or len(values) < 5 or is_bad_item_name(item_name):
        return

    row = build_row(company_name, stock_code, year, period, period_type, period_label, path, pending)
    if row:
        rows.append(row)


def build_row(
    company_name: str,
    stock_code: str,
    year: int,
    period: str,
    period_type: str,
    period_label: str,
    path: Path,
    pending: _PendingRow,
) -> BusinessBreakdownRow | None:
    values = pending.values or []
    item_name = pending.item_name
    source_table = infer_table_type(values, pending.source_section)
    source_line = pending.start_line or 0

    if source_table == "revenue_composition":
        revenue = parse_number(values[0])
        revenue_pct = parse_percent(values[1])
        revenue_previous = parse_number(values[2])
        revenue_previous_pct = parse_percent(values[3])
        revenue_yoy_pct = parse_percent(values[4])
        return BusinessBreakdownRow(
            company_name=company_name,
            stock_code=stock_code,
            year=year,
            period=period,
            period_type=period_type,
            period_label=period_label,
            source_file=str(path),
            source_section=pending.source_section,
            source_table=source_table,
            dimension=pending.dimension,
            dimension_label=DIMENSION_LABELS[pending.dimension],
            item_name=item_name,
            revenue=revenue,
            revenue_unit=pending.unit_label,
            revenue_yuan=scale_amount(revenue, pending.unit_multiplier),
            revenue_pct=revenue_pct,
            revenue_previous=revenue_previous,
            revenue_previous_yuan=scale_amount(revenue_previous, pending.unit_multiplier),
            revenue_previous_pct=revenue_previous_pct,
            revenue_yoy_pct=revenue_yoy_pct,
            cost=None,
            cost_yuan=None,
            cost_yoy_pct=None,
            gross_margin_pct=None,
            gross_margin_change="",
            source_line=source_line,
            confidence="high",
            raw_values="|".join(values[:5]),
        )

    if source_table == "business_profitability_yoy_split":
        revenue = parse_number(values[0])
        revenue_yoy_pct = parse_percent(values[1])
        cost = parse_number(values[2])
        cost_yoy_pct = parse_percent(values[3])
        gross_margin_pct = parse_percent(values[4])
    else:
        revenue = parse_number(values[0])
        cost = parse_number(values[1])
        gross_margin_pct = parse_percent(values[2])
        revenue_yoy_pct = parse_percent(values[3])
        cost_yoy_pct = parse_percent(values[4])
    gross_margin_change = ""
    if len(values) >= 6:
        gross_margin_change = values[5]
    if pending.gross_margin_change_parts:
        gross_margin_change = "".join(pending.gross_margin_change_parts)

    return BusinessBreakdownRow(
        company_name=company_name,
        stock_code=stock_code,
        year=year,
        period=period,
        period_type=period_type,
        period_label=period_label,
        source_file=str(path),
        source_section=pending.source_section,
        source_table=source_table,
        dimension=pending.dimension,
        dimension_label=DIMENSION_LABELS[pending.dimension],
        item_name=item_name,
        revenue=revenue,
        revenue_unit=pending.unit_label,
        revenue_yuan=scale_amount(revenue, pending.unit_multiplier),
        revenue_pct=None,
        revenue_previous=None,
        revenue_previous_yuan=None,
        revenue_previous_pct=None,
        revenue_yoy_pct=revenue_yoy_pct,
        cost=cost,
        cost_yuan=scale_amount(cost, pending.unit_multiplier),
        cost_yoy_pct=cost_yoy_pct,
        gross_margin_pct=gross_margin_pct,
        gross_margin_change=gross_margin_change,
        source_line=source_line,
        confidence="high" if gross_margin_change or len(values) >= 6 else "medium",
        raw_values="|".join(values[:6]),
    )


def infer_table_type(values: list[str], source_section: str = "") -> str:
    if len(values) >= 5 and is_percent_token(values[1]) and is_percent_token(values[3]):
        if "营业收入构成" in source_section:
            return "revenue_composition"
        return "business_profitability_yoy_split"
    return "major_business_profitability"


def _is_section_boundary(compact: str) -> bool:
    """专用 section 的结束边界：编号小节标题 / 情况说明 / 下一张分析表 / 已知硬截断关键词。"""
    if re.match(r"^[（(]?\d+[.、)](?!\d)", compact):
        return True
    # 只认 section 尾的"其他情况说明"(成本分析表尾)/"产销量情况说明"(产销量表尾)，
    # 不认裸"情况说明"——它是表内"情况说明"列头（常单字拆行，但合并成一行时不能误判为边界）。
    if "其他情况说明" in compact or "产销量情况说明" in compact:
        return True
    if "分析表" in compact:
        return True
    for kw in (
        "主要销售客户", "主要供应商", "研发投入", "资产及负债",
        "采购模式", "销售费用", "现金流", "重大采购", "重大销售",
        "报告期主要子公司", "公司报告期内业务", "主营业务数据统计口径",
        "收入确认和计量",
    ):
        if kw in compact:
            return True
    return False


def _find_section_ranges(lines: list[_Line], start_re: re.Pattern) -> list[tuple[int, int]]:
    """定位 start_re 命中的 section 行区间 [start, end)（半开，含起始行、不含边界行）。"""
    ranges: list[tuple[int, int]] = []
    n = len(lines)
    i = 0
    while i < n:
        compact = re.sub(r"\s+", "", lines[i].text)
        if start_re.search(compact):
            j = i + 1
            while j < n:
                cj = re.sub(r"\s+", "", lines[j].text)
                if _is_section_boundary(cj):
                    break
                j += 1
            ranges.append((i, j))
            i = j
        else:
            i += 1
    return ranges


def _is_number_token(tok: str) -> bool:
    """单个 token 是否为纯数字（含千分位/百分号/负号）。逐 token 判定，避免去空格合并相邻数字。"""
    compact = tok.replace("，", ",").replace("％", "%")
    return bool(
        re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?", compact)
        or re.fullmatch(r"[-+]?\d+(?:\.\d+)?%?", compact)
    )


# 成本表表头残留片段：出现在非数字 token 里即判为表头丢弃（数据 token 如"啤酒销售""直接材料"不含这些）。
_COST_NAME_FILTER_FRAGMENTS = (
    "占", "成本", "比例", "金额", "变动", "同期", "本期", "上年", "较上",
    "情况", "说明", "项目", "分行业", "分产品", "%", "(", ")", "（", "）",
)

# 产销量表表头残留片段：生产量/销售量/库存量/单位/主要产品 等列头拆分后按片段丢弃。
_VOLUME_NAME_FILTER_FRAGMENTS = (
    "生产", "销售", "库存", "主要", "产品", "单位", "增减", "上年",
    "情况", "说明", "%", "(", ")", "（", "）",
)


def _cost_name_token_ok(compact: str) -> bool:
    if compact == "合计":
        return True
    if len(compact) < 2:
        return False
    return not any(frag in compact for frag in _COST_NAME_FILTER_FRAGMENTS)


def _flatten_tokens(
    lines: list[_Line], start: int, end: int, header_noise: set[str], mode: str,
) -> list[tuple[int, str, bool]]:
    """把 section 展平成 (line_no, token, is_number) 流：按空白拆 token，逐 token 判数字/表头。
    mode='volume' 按行级表头过滤（物理单位可能是单字，不能按 token 长度过滤）；
    mode='cost' 按 token 级表头片段过滤（"啤酒销售 直接材料"拆成两个名字 token）。"""
    out: list[tuple[int, str, bool]] = []
    for k in range(start + 1, end):
        text = lines[k].text
        if not text:
            continue
        compact_line = re.sub(r"\s+", "", text)
        if parse_unit(compact_line):
            continue
        if "适用" in compact_line and "不适用" in compact_line:
            continue
        if "年度报告" in compact_line:
            continue
        if compact_line in header_noise:
            continue
        if any(frag in compact_line for frag in _SECTION_HEADER_FRAGMENTS):
            continue
        for tok in text.split():
            compact = re.sub(r"\s+", "", tok)
            if not compact:
                continue
            if _is_number_token(compact):
                out.append((lines[k].number, tok, True))
            else:
                if mode == "cost" and not _cost_name_token_ok(compact):
                    continue
                if mode == "volume" and (
                    compact in _VOLUME_HEADER_NOISE
                    or any(frag in compact for frag in _VOLUME_NAME_FILTER_FRAGMENTS)
                ):
                    continue
                out.append((lines[k].number, tok, False))
    return out


def _flat_runs(
    tokens: list[tuple[int, str, bool]],
) -> list[tuple[list[str], list[str], int]]:
    """返回 (name_tokens, values, first_value_line)：name_tokens 为上一 run 以来累积的非数字 token。"""
    runs: list[tuple[list[str], list[str], int]] = []
    name_buf: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i][2]:
            run: list[str] = []
            line_no = tokens[i][0]
            while i < n and tokens[i][2]:
                run.append(tokens[i][1])
                i += 1
            runs.append((name_buf, run, line_no))
            name_buf = []
        else:
            name_buf.append(tokens[i][1])
            i += 1
    return runs


def _section_unit(lines: list[_Line], start: int, end: int) -> tuple[str, float]:
    """扫 section 内最后出现的'单位：'行，取货币单位与倍数（成本分析表常用千元）。"""
    unit_label, unit_multiplier = "元", 1.0
    for k in range(start + 1, end):
        compact = re.sub(r"\s+", "", lines[k].text)
        new_unit = parse_unit(compact)
        if new_unit:
            unit_label, unit_multiplier = new_unit
    return unit_label, unit_multiplier


def _extract_volume_section(
    lines: list[_Line], start: int, end: int,
    company_name: str, stock_code: str, year: int, period: str,
    period_type: str, period_label: str, path: Path,
) -> list[BusinessBreakdownRow]:
    tokens = _flatten_tokens(lines, start, end, _VOLUME_HEADER_NOISE, mode="volume")
    rows: list[BusinessBreakdownRow] = []
    for name_buf, run, line_no in _flat_runs(tokens):
        if not (3 <= len(run) <= 7):
            continue
        unit = ""
        if name_buf and VOLUME_UNIT_RE.fullmatch(name_buf[-1]):
            unit = name_buf[-1]
            name = "".join(name_buf[:-1])
        else:
            name = "".join(name_buf)
        name = clean_item_name(name)
        if not name or is_bad_item_name(name):
            continue
        rows.append(
            _build_volume_row(
                name, unit, run, line_no,
                company_name, stock_code, year, period, period_type, period_label, path,
            )
        )
    return rows


def _build_volume_row(
    name: str, unit: str, values: list[str], source_line: int,
    company_name: str, stock_code: str, year: int, period: str,
    period_type: str, period_label: str, path: Path,
) -> BusinessBreakdownRow:
    def _nth(i: int) -> float | None:
        return parse_number(values[i]) if i < len(values) else None

    return BusinessBreakdownRow(
        company_name=company_name, stock_code=stock_code, year=year, period=period,
        period_type=period_type, period_label=period_label, source_file=str(path),
        source_section="", source_table="volume", dimension="volume",
        dimension_label=DIMENSION_LABELS["volume"], item_name=name,
        revenue=None, revenue_unit="", revenue_yuan=None, revenue_pct=None,
        revenue_previous=None, revenue_previous_yuan=None, revenue_previous_pct=None,
        revenue_yoy_pct=None, cost=None, cost_yuan=None, cost_yoy_pct=None,
        gross_margin_pct=None, gross_margin_change="",
        source_line=source_line, confidence="high" if len(values) >= 5 else "medium",
        raw_values="|".join(values),
        quantity_unit=unit,
        production_qty=_nth(0), sales_qty=_nth(1), inventory_qty=_nth(2),
        production_yoy_pct=_nth(3), sales_qty_yoy_pct=_nth(4), inventory_yoy_pct=_nth(5),
    )


def _extract_cost_composition_section(
    lines: list[_Line], start: int, end: int,
    company_name: str, stock_code: str, year: int, period: str,
    period_type: str, period_label: str, path: Path,
) -> list[BusinessBreakdownRow]:
    """成本分析表：每行 = [分部] 成本构成项目 + 4-6 个数(本期金额/本期占比/上年金额/上年占比/变动%)。
    分部只写一次时（会稽山式）按 current_segment 继承；每行都写时（青岛啤酒式）按 name_buf 末位拆。"""
    tokens = _flatten_tokens(lines, start, end, _COST_HEADER_NOISE, mode="cost")
    unit_label, unit_multiplier = _section_unit(lines, start, end)
    rows: list[BusinessBreakdownRow] = []
    current_segment = ""
    for name_buf, run, line_no in _flat_runs(tokens):
        if not (4 <= len(run) <= 6):
            continue
        if not name_buf:
            continue
        if len(name_buf) >= 2:
            segment = clean_item_name("".join(name_buf[:-1]))
            cost_item = clean_item_name(name_buf[-1])
            if segment:
                current_segment = segment
        else:
            tok = clean_item_name(name_buf[0])
            if tok == "合计":
                segment, cost_item = "合计", ""
            else:
                segment, cost_item = current_segment, tok
        if not segment:
            continue
        rows.append(
            _build_cost_row(
                segment, cost_item, run, unit_label, unit_multiplier, line_no,
                company_name, stock_code, year, period, period_type, period_label, path,
            )
        )
    return rows


def _build_cost_row(
    name: str, cost_item: str, values: list[str],
    unit_label: str, unit_multiplier: float, source_line: int,
    company_name: str, stock_code: str, year: int, period: str,
    period_type: str, period_label: str, path: Path,
) -> BusinessBreakdownRow:
    def _nth(i: int) -> float | None:
        return parse_number(values[i]) if i < len(values) else None

    revenue = _nth(0)
    revenue_pct = parse_percent(values[1]) if len(values) > 1 else None
    revenue_previous = _nth(2) if len(values) > 2 else None
    revenue_previous_pct = parse_percent(values[3]) if len(values) > 3 else None
    revenue_yoy_pct = parse_percent(values[4]) if len(values) > 4 else None
    return BusinessBreakdownRow(
        company_name=company_name, stock_code=stock_code, year=year, period=period,
        period_type=period_type, period_label=period_label, source_file=str(path),
        source_section="", source_table="cost_composition", dimension="cost_composition",
        dimension_label=DIMENSION_LABELS["cost_composition"], item_name=name,
        revenue=revenue, revenue_unit=unit_label,
        revenue_yuan=scale_amount(revenue, unit_multiplier), revenue_pct=revenue_pct,
        revenue_previous=revenue_previous,
        revenue_previous_yuan=scale_amount(revenue_previous, unit_multiplier),
        revenue_previous_pct=revenue_previous_pct, revenue_yoy_pct=revenue_yoy_pct,
        cost=None, cost_yuan=None, cost_yoy_pct=None,
        gross_margin_pct=None, gross_margin_change="",
        source_line=source_line, confidence="high", raw_values="|".join(values),
        cost_item=cost_item,
    )


def discover_reports(
    companies_dir: Path,
    years: set[int] | None = None,
    tickers: set[str] | None = None,
    limit: int | None = None,
    include_h1: bool = True,
    h1_recent_years: int = 3,
) -> list[Path]:
    reports: list[Path] = []
    code_filter = {ticker_code(ticker) for ticker in tickers} if tickers else None

    for company_dir in sorted(path for path in companies_dir.iterdir() if path.is_dir()):
        try:
            _, code = parse_company_dir(company_dir)
        except ValueError:
            continue
        if code_filter and code not in code_filter:
            continue
        annuals = annual_reports_dir(company_dir)
        if not annuals.exists():
            continue
        for report in sorted(annuals.glob("*_*.md")):
            year = parse_year(report)
            if years and year not in years:
                continue
            reports.append(report)
            if limit and len(reports) >= limit:
                return reports
        if include_h1:
            for report in discover_h1_reports(company_dir, years=years, recent_years=h1_recent_years):
                reports.append(report)
                if limit and len(reports) >= limit:
                    return reports
    return reports


def discover_h1_reports(
    company_dir: Path,
    *,
    years: set[int] | None = None,
    recent_years: int = 3,
) -> list[Path]:
    quarterly = quarterly_reports_dir(company_dir)
    if not quarterly.exists():
        return []

    reports: list[Path] = []
    for report in sorted(quarterly.glob("*/*.md")):
        try:
            year = parse_year(report)
        except ValueError:
            continue
        if years and year not in years:
            continue
        if report_kind(report) != "h1":
            continue
        reports.append(report)

    if recent_years > 0:
        allowed_years = set(sorted({parse_year(report) for report in reports}, reverse=True)[:recent_years])
        reports = [report for report in reports if parse_year(report) in allowed_years]
    return sorted(reports, key=lambda path: (parse_year(path), path.name))


def write_outputs(rows: list[BusinessBreakdownRow], output_dir: Path) -> tuple[Path, Path]:
    return write_named_outputs(rows, output_dir, OUTPUT_CSV_NAME, OUTPUT_JSONL_NAME)


def write_named_outputs(
    rows: list[BusinessBreakdownRow],
    output_dir: Path,
    csv_name: str,
    jsonl_name: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / csv_name
    jsonl_path = output_dir / jsonl_name
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(BusinessBreakdownRow.__dataclass_fields__.keys())

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    return csv_path, jsonl_path


def write_company_outputs(rows: list[BusinessBreakdownRow], companies_dir: Path = COMPANIES_DIR) -> list[tuple[str, Path, Path]]:
    company_dirs: dict[str, Path] = {}
    for company_dir in sorted(path for path in companies_dir.iterdir() if path.is_dir()):
        try:
            _, code = parse_company_dir(company_dir)
        except ValueError:
            continue
        company_dirs[code] = company_dir

    rows_by_code: dict[str, list[BusinessBreakdownRow]] = {}
    for row in rows:
        rows_by_code.setdefault(row.stock_code, []).append(row)

    outputs: list[tuple[str, Path, Path]] = []
    for code, company_rows in sorted(rows_by_code.items()):
        company_dir = company_dirs.get(code)
        if company_dir is None:
            continue
        csv_path, jsonl_path = write_breakdown_file_set(company_rows, official_breakdowns_dir(company_dir))
        outputs.append((company_dir.name, csv_path, jsonl_path))
    return outputs


def write_breakdown_file_set(rows: list[BusinessBreakdownRow], output_dir: Path) -> tuple[Path, Path]:
    annual_rows = [row for row in rows if row.period_type == "annual"]
    h1_rows = [row for row in rows if row.period_type == "h1"]
    annual_csv, annual_jsonl = write_outputs(annual_rows, output_dir)
    write_named_outputs(h1_rows, output_dir, OUTPUT_H1_CSV_NAME, OUTPUT_H1_JSONL_NAME)
    write_named_outputs(rows, output_dir, OUTPUT_ALL_CSV_NAME, OUTPUT_ALL_JSONL_NAME)
    return annual_csv, annual_jsonl


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def parse_company_dir(path: Path) -> tuple[str, str]:
    match = re.match(r"(.+?)_(\d{6})$", path.name)
    if not match:
        raise ValueError(f"Company directory must look like 名称_代码: {path}")
    return match.group(1), match.group(2)


def parse_year(path: Path) -> int:
    match = re.match(r"(\d{4})_", path.name)
    if not match:
        raise ValueError(f"Annual report filename must start with YYYY_: {path}")
    return int(match.group(1))


def parse_period(path: Path) -> tuple[int, str, str, str]:
    year = parse_year(path)
    kind = report_kind(path)
    if kind == "h1":
        return year, f"{year}H1", "h1", "半年度"
    return year, f"{year}A", "annual", "年度"


def report_kind(path: Path) -> str:
    for line in read_markdown_lines(path)[:30]:
        match = re.match(r"kind:\s*[\"']?([^\"']+)[\"']?", line.strip())
        if match:
            kind = match.group(1).strip().lower()
            return "h1" if kind == "h1" else "annual"
    name = path.name
    if "半年度" in name or "半年报" in name:
        return "h1"
    return "annual"


def ticker_code(ticker: str) -> str:
    match = re.search(r"(\d{6})", ticker)
    if not match:
        raise ValueError(f"Ticker must contain a 6-digit code: {ticker}")
    return match.group(1)


def parse_unit(text: str) -> tuple[str, float] | None:
    if "单位" not in text:
        return None
    if "千元" in text:
        return "千元", 1_000.0
    if "万元" in text:
        return "万元", 10_000.0
    if "亿元" in text:
        return "亿元", 100_000_000.0
    if "元" in text:
        return "元", 1.0
    return None


def parse_dimension(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    for dimension, pattern in DIMENSION_PATTERNS:
        if pattern.match(compact):
            return dimension
    return None


def is_section_hint(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "营业收入构成",
            "收入与成本",
            "收入和成本分析",
            "主营业务分行业、分产品",
            "占公司营业收入或营业利润10%以上",
            "营业收入和营业成本",
            "主营业务经营情况",
        )
    )


def is_hard_stop(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    stop_keywords = (
        "情况的说明",
        "产销量情况",
        "成本构成",
        "成本分析",
        "收入确认和计量所采用的会计政策",
        "公司实物销售收入是否大于劳务收入",
        "公司主营业务数据统计口径",
        "相关数据同比发生变动",
        "主要销售客户",
        "采购模式",
        "研发投入",
        "资产及负债状况",
        "销售费用、管理费用",
        "现金流",
    )
    if any(keyword in compact for keyword in stop_keywords):
        return True
    if re.match(r"^\d+[.、](主营业务|其他业务)", compact):
        return False
    if mixed_value_line(text):
        return False
    if not numeric_line_values(text) and re.match(r"^[（(]?\d+[）).、]", compact):
        target_heading = "占公司营业收入或营业利润10%以上" in compact
        target_heading = target_heading or "主营业务分行业、分产品" in compact
        target_heading = target_heading or "营业收入构成" in compact
        return not target_heading
    return False


def is_header_noise(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if parse_unit(compact):
        return True
    if re.fullmatch(r"注\d+", compact):
        return True
    if re.fullmatch(r"\d+(?:/\d+)?", compact):
        return True
    if "年度报告" in compact:
        return True
    if compact in {
        "项目",
        "金额",
        "单位",
        "币种：人民币",
        "2024年",
        "2023年",
        "同比增减",
        "占营业收入比重",
        "营业利润率",
        "数值",
        "营业收入整体情况",
        "营业收入合计",
        "合计",
        "√适用□不适用",
        "☑适用□不适用",
        "适用□不适用",
        "□适用☑不适用",
    }:
        return True
    header_fragments = (
        "营业收入",
        "营业成本",
        "毛利率",
        "比上年",
        "上年同期",
        "增减",
        "（%）",
        "(%)",
        "公司主营业务数据统计口径",
        "最近1年按报告期末口径",
    )
    return any(fragment in compact for fragment in header_fragments)


def is_bad_item_name(item_name: str) -> bool:
    if item_name in {"主营业务", "营业收入合计", "合计", "百分点", "分点"}:
        return True
    if len(item_name) > 40:
        return True
    if re.search(r"\d{4,}|,\d{3}|\d+\.\d+", item_name):
        return True
    bad_fragments = (
        "年度报告",
        "报告全文",
        "单位：",
        "主营业务数据统计口径",
        "公司主营业务收入",
        "营业收入比上年同期",
        "营业成本比上年同期",
        "适用不适用",
        "分部间抵消",
        "抵消",
    )
    return any(fragment in item_name for fragment in bad_fragments)


def numeric_line_values(text: str) -> list[str]:
    compact = text.replace(" ", "")
    if not compact:
        return []
    without_numbers = NUMBER_RE.sub("", compact)
    without_numbers = re.sub(r"[,，.%％()（）+\-]", "", without_numbers)
    if without_numbers:
        return []
    return [match.group(0).replace("％", "%") for match in NUMBER_RE.finditer(compact)]


def mixed_value_line(text: str) -> list[str]:
    compact = text.replace(" ", "")
    if not any(word in compact for word in ("增加", "减少", "下降", "上升")):
        return []
    matches = [match.group(0).replace("％", "%") for match in NUMBER_RE.finditer(compact)]
    if not matches:
        return []
    return matches


def is_gross_margin_change_text(text: str) -> bool:
    compact = text.replace(" ", "")
    return (
        "百分点" in compact
        or (("增加" in compact or "减少" in compact or "下降" in compact or "上升" in compact) and NUMBER_RE.search(compact))
    )


def row_has_enough_values(pending: _PendingRow) -> bool:
    values = pending.values or []
    if len(values) >= 6:
        return True
    if len(values) >= 5 and infer_table_type(values, pending.source_section) in {"revenue_composition", "business_profitability_yoy_split"}:
        return True
    return len(values) >= 5 and bool(pending.gross_margin_change_parts)


def clean_item_name(name: str) -> str:
    name = normalize_space(name)
    name = re.sub(r"^\d+[.、]", "", name)
    name = name.replace("其中：", "")
    name = re.sub(r"注\d+", "", name)
    return name.strip(" ：:")


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("%", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_percent(value: str | None) -> float | None:
    return parse_number(value)


def is_percent_token(value: str) -> bool:
    return value.endswith("%")


def scale_amount(value: float | None, multiplier: float) -> float | None:
    return None if value is None else value * multiplier


def dedupe_rows(rows: list[BusinessBreakdownRow]) -> list[BusinessBreakdownRow]:
    seen: set[tuple[object, ...]] = set()
    out: list[BusinessBreakdownRow] = []
    for row in rows:
        # 不含 source_line：成本分析表"分行业/分产品"两张子表常完全重复，
        # 按 (维度+科目+表+数值+成本项+物理量) 去重即整组合并。
        key = (
            row.company_name,
            row.year,
            row.period,
            row.dimension,
            row.item_name,
            row.source_table,
            row.revenue,
            row.cost,
            row.cost_item,
            row.quantity_unit,
            row.production_qty,
            row.sales_qty,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def parse_years(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    years: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            years.update(range(int(start), int(end) + 1))
        else:
            years.add(int(part))
    return years


def parse_tickers(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def business_breakdown_max_workers() -> int:
    raw = os.environ.get("BUSINESS_BREAKDOWN_MAX_WORKERS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return 6
    return max(1, min(8, os.cpu_count() or 6))


def extract_reports(
    reports: Iterable[Path],
    *,
    max_workers: int | None = None,
) -> list[BusinessBreakdownRow]:
    batches = parallel_map(
        extract_report,
        reports,
        max_workers=max_workers or business_breakdown_max_workers(),
    )
    rows: list[BusinessBreakdownRow] = []
    for batch in batches:
        rows.extend(batch)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies-dir", default=str(COMPANIES_DIR), help="Root companies directory.")
    parser.add_argument("--year", "--years", dest="years", help="Year list/range, e.g. 2024 or 2020-2024.")
    parser.add_argument("--tickers", help="Comma-separated stock codes/tickers, e.g. 600031,300866.SZ.")
    parser.add_argument("--limit", type=int, help="Stop after N annual reports, useful for smoke tests.")
    parser.add_argument("--no-h1", action="store_true", help="Only extract annual reports, without recent half-year reports.")
    parser.add_argument(
        "--h1-recent-years",
        type=int,
        default=3,
        help="Number of most recent half-year report years to include per company. 0 means all available H1 reports.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Concurrent annual-report Markdown extraction workers. Defaults to BUSINESS_BREAKDOWN_MAX_WORKERS or CPU-bounded 8.",
    )
    parser.add_argument(
        "--aggregate-output-dir",
        "--output-dir",
        dest="aggregate_output_dir",
        help="Optional directory for an all-company aggregate CSV/JSONL copy.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    companies_dir = Path(args.companies_dir)
    reports = discover_reports(
        companies_dir,
        years=parse_years(args.years),
        tickers=parse_tickers(args.tickers),
        limit=args.limit,
        include_h1=not args.no_h1,
        h1_recent_years=args.h1_recent_years,
    )
    rows = extract_reports(reports, max_workers=args.workers)
    company_outputs = write_company_outputs(rows, companies_dir)
    print(f"Reports scanned: {len(reports)}")
    print(f"Rows extracted: {len(rows)}")
    print(f"Companies written: {len(company_outputs)}")
    for company_name, csv_path, jsonl_path in company_outputs:
        print(f"{company_name}: {csv_path} | {jsonl_path}")
    if args.aggregate_output_dir:
        csv_path, jsonl_path = write_outputs(rows, Path(args.aggregate_output_dir))
        print(f"Aggregate CSV: {csv_path}")
        print(f"Aggregate JSONL: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

















