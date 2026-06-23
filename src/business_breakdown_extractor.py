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
from src.company_paths import annual_reports_dir, official_breakdowns_dir


ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"


DIMENSION_LABELS = {
    "industry": "行业",
    "product": "产品",
    "region": "地区",
    "sales_model": "销售模式",
}

DIMENSION_PATTERNS = [
    ("industry", re.compile(r"^(主营业务)?分行业(情况)?$")),
    ("industry", re.compile(r"^行业$")),
    ("product", re.compile(r"^(主营业务)?分产品(情况)?$")),
    ("region", re.compile(r"^(主营业务)?分地区(情况)?$")),
    ("sales_model", re.compile(r"^(主营业务)?分销售模式(情况)?$")),
    ("sales_model", re.compile(r"^销售模式$")),
]

NUMBER_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
OUTPUT_CSV_NAME = "business_revenue_breakdown.csv"
OUTPUT_JSONL_NAME = "business_revenue_breakdown.jsonl"


@dataclass
class BusinessBreakdownRow:
    company_name: str
    stock_code: str
    year: int
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
    try:
        candidate = path.parents[2]
    except IndexError:
        return path.parent.parent
    if annual_reports_dir(candidate) == path.parent:
        return candidate
    return path.parent.parent


def extract_report(path: Path, company_dir: Path | None = None) -> list[BusinessBreakdownRow]:
    company_dir = company_dir or infer_company_dir_from_report(path)
    company_name, stock_code = parse_company_dir(company_dir)
    year = parse_year(path)
    lines = [_Line(idx + 1, normalize_space(line)) for idx, line in enumerate(read_markdown_lines(path))]

    rows: list[BusinessBreakdownRow] = []
    dimension: str | None = None
    source_section = ""
    unit_label = "元"
    unit_multiplier = 1.0
    pending: _PendingRow | None = None
    active_context_lines = 0

    for line in lines:
        text = line.text
        if not text:
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
            append_pending(rows, pending, company_name, stock_code, year, path)
            dimension = new_dimension
            pending = _PendingRow(dimension, source_section, unit_label, unit_multiplier)
            continue

        if is_hard_stop(text):
            append_pending(rows, pending, company_name, stock_code, year, path)
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
            append_pending(rows, pending, company_name, stock_code, year, path)
            pending = _PendingRow(dimension, source_section, unit_label, unit_multiplier)

        if not is_header_noise(text):
            if pending.start_line is None:
                pending.start_line = line.number
            pending.name_parts.append(text)

    append_pending(rows, pending, company_name, stock_code, year, path)
    return dedupe_rows(rows)


def append_pending(
    rows: list[BusinessBreakdownRow],
    pending: _PendingRow | None,
    company_name: str,
    stock_code: str,
    year: int,
    path: Path,
) -> None:
    if pending is None:
        return
    item_name = pending.item_name
    values = pending.values or []
    if not item_name or len(values) < 5 or is_bad_item_name(item_name):
        return

    row = build_row(company_name, stock_code, year, path, pending)
    if row:
        rows.append(row)


def build_row(
    company_name: str,
    stock_code: str,
    year: int,
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


def discover_reports(
    companies_dir: Path,
    years: set[int] | None = None,
    tickers: set[str] | None = None,
    limit: int | None = None,
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
    return reports


def write_outputs(rows: list[BusinessBreakdownRow], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / OUTPUT_CSV_NAME
    jsonl_path = output_dir / OUTPUT_JSONL_NAME
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
        csv_path, jsonl_path = write_outputs(company_rows, official_breakdowns_dir(company_dir))
        outputs.append((company_dir.name, csv_path, jsonl_path))
    return outputs


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
        key = (
            row.company_name,
            row.year,
            row.dimension,
            row.item_name,
            row.source_table,
            row.revenue,
            row.cost,
            row.source_line,
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

















