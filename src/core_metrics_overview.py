"""Generate a clean-stage annual core metrics overview for agents.

The overview is a deterministic fact sheet built only from ``clean_annual``.
It is intended for /init-time context: LLM-readable, stable across repeated
runs, and independent from forecast/yaml outputs.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.company_paths import company_dir_from_db_path, find_db_path


SCHEMA_VERSION = 1
OUTPUT_STEM = "core_metrics_overview"
MARKDOWN_FILENAME = f"{OUTPUT_STEM}.md"
JSON_FILENAME = f"{OUTPUT_STEM}.json"
CSV_FILENAME = f"{OUTPUT_STEM}.csv"


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    kind: str
    field: str | tuple[str, ...] | None = None
    formula: str | None = None


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("revenue", "营业收入", "million_cny", "field", "revenue", "clean_annual.revenue"),
    MetricSpec("revenue_yoy", "收入同比", "ratio", "yoy", "revenue", "yoy(revenue)"),
    MetricSpec("total_revenue", "营业总收入", "million_cny", "field", "total_revenue", "clean_annual.total_revenue"),
    MetricSpec("oper_cost", "减：营业成本", "million_cny", "field", "oper_cost", "clean_annual.oper_cost"),
    MetricSpec("gross_margin", "毛利率", "ratio", "gross_margin", None, "(revenue-oper_cost)/revenue"),
    MetricSpec("biz_tax_surchg", "减：营业税金及附加", "million_cny", "field", "biz_tax_surchg", "clean_annual.biz_tax_surchg"),
    MetricSpec("biz_tax_surchg_rate", "营业税金及附加率", "ratio", "rate", "biz_tax_surchg", "biz_tax_surchg/revenue"),
    MetricSpec("sell_exp", "减：销售费用", "million_cny", "field", "sell_exp", "clean_annual.sell_exp"),
    MetricSpec("sell_exp_rate", "销售费用率", "ratio", "rate", "sell_exp", "sell_exp/revenue"),
    MetricSpec("admin_exp", "减：管理费用", "million_cny", "field", "admin_exp", "clean_annual.admin_exp"),
    MetricSpec("admin_exp_rate", "管理费用率", "ratio", "rate", "admin_exp", "admin_exp/revenue"),
    MetricSpec("rd_exp", "减：研发费用", "million_cny", "field", "rd_exp", "clean_annual.rd_exp"),
    MetricSpec("rd_exp_rate", "研发费用率", "ratio", "rate", "rd_exp", "rd_exp/revenue"),
    MetricSpec("fin_exp", "减：财务费用", "million_cny", "field", "fin_exp", "clean_annual.fin_exp"),
    MetricSpec("fin_exp_rate", "财务费用率", "ratio", "rate", "fin_exp", "fin_exp/revenue"),
    MetricSpec("total_cogs", "营业总成本", "million_cny", "field", "total_cogs", "clean_annual.total_cogs"),
    MetricSpec("total_cogs_rate", "营业总成本率", "ratio", "rate", "total_cogs", "total_cogs/revenue"),
    MetricSpec("assets_impair_loss", "减：资产减值损失", "million_cny", "field", "assets_impair_loss", "clean_annual.assets_impair_loss"),
    MetricSpec(
        "credit_impa_loss",
        "减：信用减值损失",
        "million_cny",
        "field",
        ("income.credit_impa_loss", "credit_impa_loss"),
        "clean_annual.income.credit_impa_loss",
    ),
    MetricSpec("oth_income", "其他收益", "million_cny", "field", "oth_income", "clean_annual.oth_income"),
    MetricSpec("invest_income", "加：投资净收益", "million_cny", "field", "invest_income", "clean_annual.invest_income"),
    MetricSpec("fv_value_chg_gain", "加：公允价值变动净收益", "million_cny", "field", "fv_value_chg_gain", "clean_annual.fv_value_chg_gain"),
    MetricSpec("asset_disp_income", "资产处置收益", "million_cny", "field", "asset_disp_income", "clean_annual.asset_disp_income"),
    MetricSpec("operate_profit", "营业利润", "million_cny", "field", "operate_profit", "clean_annual.operate_profit"),
    MetricSpec("operate_margin", "营业利润率", "ratio", "rate", "operate_profit", "operate_profit/revenue"),
    MetricSpec("non_oper_income", "加：营业外收入", "million_cny", "field", "non_oper_income", "clean_annual.non_oper_income"),
    MetricSpec("non_oper_exp", "减：营业外支出", "million_cny", "field", "non_oper_exp", "clean_annual.non_oper_exp"),
    MetricSpec("total_profit", "利润总额", "million_cny", "field", "total_profit", "clean_annual.total_profit"),
    MetricSpec("total_profit_margin", "利润总额率", "ratio", "rate", "total_profit", "total_profit/revenue"),
    MetricSpec("income_tax", "所得税费用", "million_cny", "field", "income_tax", "clean_annual.income_tax"),
    MetricSpec("effective_tax_rate", "所得税率", "ratio", "tax_rate", None, "income_tax/total_profit"),
    MetricSpec("n_income", "净利润 (含少数股东损益)", "million_cny", "field", "n_income", "clean_annual.n_income"),
    MetricSpec("n_income_margin", "净利率", "ratio", "rate", "n_income", "n_income/revenue"),
    MetricSpec("n_income_yoy", "净利润同比", "ratio", "yoy", "n_income", "yoy(n_income)"),
)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _yoy(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1.0


def _period_sort_key(period: str) -> tuple[int, str]:
    try:
        return int(period[:4]), period
    except ValueError:
        return 0, period


def _metric_source_fields(field: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if field is None:
        return ()
    if isinstance(field, tuple):
        return field
    return (field,)


def _value(row: dict[str, float | None], field: str | tuple[str, ...] | None) -> float | None:
    for name in _metric_source_fields(field):
        if name in row:
            return row[name]
    return None


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    return f"{value:,.1f}"


def _raw_csv_value(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.12g}"


def _read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(key): str(value) for key, value in rows}


def load_clean_annual(db_path: str | Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Load clean_annual rows with NULL preserved as None."""
    path = Path(db_path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        meta = _read_meta(conn)
        try:
            rows = conn.execute("SELECT * FROM clean_annual").fetchall()
        except sqlite3.OperationalError as exc:
            raise RuntimeError(f"clean_annual not found in {path}") from exc

    parsed: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {"period": str(row["period"])}
        for key in row.keys():
            if key == "period":
                continue
            record[key] = _to_float(row[key])
        parsed.append(record)
    parsed.sort(key=lambda item: _period_sort_key(str(item["period"])))
    if not parsed:
        raise RuntimeError(f"clean_annual is empty in {path}")
    return meta, parsed


def _compute_metric(spec: MetricSpec, row: dict[str, float | None], previous: dict[str, float | None] | None) -> float | None:
    revenue = _value(row, "revenue")
    if spec.kind == "field":
        return _value(row, spec.field)
    if spec.kind == "rate":
        return _safe_div(_value(row, spec.field), revenue)
    if spec.kind == "gross_margin":
        return _safe_div(
            (_value(row, "revenue") or 0.0) - (_value(row, "oper_cost") or 0.0)
            if _value(row, "revenue") is not None and _value(row, "oper_cost") is not None
            else None,
            revenue,
        )
    if spec.kind == "tax_rate":
        return _safe_div(_value(row, "income_tax"), _value(row, "total_profit"))
    if spec.kind == "yoy":
        return _yoy(_value(row, spec.field), _value(previous, spec.field) if previous else None)
    raise ValueError(f"unknown metric kind: {spec.kind}")


def build_core_metrics_overview(db_path: str | Path) -> dict[str, Any]:
    """Build the JSON-serializable overview payload."""
    path = Path(db_path)
    meta, raw_rows = load_clean_annual(path)
    periods = [str(row["period"]) for row in raw_rows]
    annual_rows: list[dict[str, float | None]] = [
        {key: value for key, value in row.items() if key != "period"}
        for row in raw_rows
    ]

    metric_rows: list[dict[str, Any]] = []
    for spec in METRIC_SPECS:
        values: dict[str, float | None] = {}
        for idx, period in enumerate(periods):
            previous = annual_rows[idx - 1] if idx > 0 else None
            values[period] = _compute_metric(spec, annual_rows[idx], previous)
        metric_rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit,
                "formula": spec.formula,
                "source_fields": list(_metric_source_fields(spec.field)),
                "values": values,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "db_file": "Agent/data.db" if path.parent.name == "Agent" else path.name,
            "table": "clean_annual",
            "amount_unit": "million_cny",
            "ratio_unit": "ratio",
        },
        "company": {
            "ticker": meta.get("ticker"),
            "name": meta.get("name"),
        },
        "periods": periods,
        "rows": metric_rows,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    company = payload.get("company") or {}
    source = payload.get("source") or {}
    periods = [str(period) for period in payload.get("periods", [])]
    rows = payload.get("rows", [])

    lines: list[str] = []
    title_name = company.get("name") or "未知公司"
    title_ticker = company.get("ticker") or "未知代码"
    lines.append(f"# 年度核心指标速览 · {title_name} ({title_ticker})")
    lines.append("")
    lines.append(
        "> 来源：Agent/data.db · clean_annual。金额单位为百万元；比率、同比按百分比展示。"
        "本文件只含历史事实与机械计算，不含预测、估值或分析判断。"
    )
    lines.append("")
    if periods:
        lines.append(f"- 覆盖年度：{', '.join(periods)}")
    lines.append(f"- 源表：{source.get('table', 'clean_annual')}")
    lines.append("- 重跑规则：/init 在 clean 年度表成功后覆盖重生成；不写入生成时间，便于 byte-stable 比对。")
    lines.append("")
    lines.append("## 利润表核心链路")
    lines.append("")
    header = ["指标", *periods]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" + "---:|" * len(periods))
    for row in rows:
        cells = [str(row["label"])]
        values = row.get("values") or {}
        for period in periods:
            cells.append(_format_value(values.get(period), str(row.get("unit"))))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 口径提示")
    lines.append("")
    lines.append("- `-` 表示 clean_annual 为空、字段不存在，或比率分母为 0。")
    lines.append("- 费用率、利润率和所得税率均由 clean_annual 的历史字段机械相除得出。")
    lines.append("- 信用减值损失优先读取 `income.credit_impa_loss`，兼容旧口径 `credit_impa_loss`。")
    return "\n".join(lines) + "\n"


def render_csv(payload: dict[str, Any]) -> str:
    periods = [str(period) for period in payload.get("periods", [])]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["key", "label", "unit", "formula", *periods])
    for row in payload.get("rows", []):
        values = row.get("values") or {}
        writer.writerow(
            [
                row.get("key"),
                row.get("label"),
                row.get("unit"),
                row.get("formula"),
                *[_raw_csv_value(values.get(period)) for period in periods],
            ]
        )
    return output.getvalue()


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding=encoding, newline="")
    os.replace(tmp_path, path)


def output_paths_for_db(db_path: str | Path) -> dict[str, Path]:
    company_dir = company_dir_from_db_path(db_path)
    agent_dir = company_dir / "Agent"
    return {
        "markdown": agent_dir / MARKDOWN_FILENAME,
        "json": agent_dir / JSON_FILENAME,
        "csv": agent_dir / CSV_FILENAME,
    }


def write_core_metrics_overview(db_path: str | Path) -> dict[str, Path]:
    """Build and overwrite the three overview artifacts."""
    payload = build_core_metrics_overview(db_path)
    paths = output_paths_for_db(db_path)
    _atomic_write_text(paths["markdown"], render_markdown(payload), encoding="utf-8")
    _atomic_write_text(
        paths["json"],
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _atomic_write_text(paths["csv"], render_csv(payload), encoding="utf-8-sig")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Agent/core_metrics_overview.* from clean_annual.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", help="A-share ticker, e.g. 002946.SZ")
    group.add_argument("--db", help="Path to Agent/data.db")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    db = find_db_path(args.ticker) if args.ticker else Path(args.db)
    paths = write_core_metrics_overview(db)
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
