"""Local web workbench for ModelKing.

This is intentionally a thin UI shell. It reads company folders, serves the
React app, and delegates DCF generation to the official forecast pipeline:
defaults.yaml + yaml1*.yaml -> forecast/
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from io import StringIO
from pathlib import Path
from typing import Any

import requests
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import pandas as pd
from src.annual_report_utils import load_env, llm_api_key, llm_base_url, llm_model, llm_timeout_seconds
from src.calc import ForecastBuildResult, value_from_statements
from src.forecast import run_company_forecast


BASE_DIR = Path(__file__).resolve().parents[1]
COMPANIES_DIR = BASE_DIR / "companies"
APP_DIST = BASE_DIR / "app" / "dist"
CORE_ASSUMPTION_NAMES = ("核心假设.md", "核心假设 (1).md")
FORECAST_TABLES = (
    "forecast_is.csv",
    "forecast_bs.csv",
    "forecast_cf.csv",
)
FIELD_REFERENCE_NAME = "\u6570\u636e\u683c\u5f0f\u53c2\u8003.md"
PRESENTATION_SCHEMA_VERSION = 1

STATEMENT_META = {
    "forecast_is.csv": {
        "key": "is",
        "name": "IS",
        "title": "利润表",
        "doc_title": "\u5229\u6da6\u8868",
        "unit": "百万元",
        "category_order": [
            "revenue_item",
            "cost_item",
            "operating_adjustment",
            "below_line",
            "tax",
            "attribution",
            "comprehensive",
            "sub_item",
            "derived",
        ],
        "subtotal_after": {
            "revenue_item": ["total_revenue"],
            "cost_item": ["total_cogs", "total_opcost"],
            "operating_adjustment": ["operate_profit"],
            "below_line": ["total_profit"],
            "tax": ["n_income"],
        },
        # 会计准则展示顺序（数据格式参考.md 是字母序，这里覆盖为严格会计序）。
        # 未列出的字段回退到字母序排在该类末尾，对金融企业字段无害（comp_type≠1 已过滤）。
        "field_order": [
            "revenue",
            "oper_cost", "biz_tax_surchg", "sell_exp", "admin_exp", "rd_exp", "fin_exp",
            "assets_impair_loss", "credit_impa_loss",
            "oth_income", "invest_income", "fv_value_chg_gain", "net_expo_hedging_benefits",
            "asset_disp_income", "forex_gain",
            "non_oper_income", "non_oper_exp",
            "income_tax",
            "n_income_attr_p", "minority_gain",
            "oth_compr_income", "t_compr_income", "compr_inc_attr_p", "compr_inc_attr_m_s",
        ],
    },
    "forecast_bs.csv": {
        "key": "bs",
        "name": "BS",
        "title": "资产负债表",
        "doc_title": "\u8d44\u4ea7\u8d1f\u503a\u8868",
        "unit": "百万元",
        "category_order": [
            "current_asset",
            "noncurrent_asset",
            "current_liab",
            "noncurrent_liab",
            "equity",
            "combo",
            "sub_item",
            "derived",
        ],
        "subtotal_after": {
            "current_asset": ["total_cur_assets"],
            "noncurrent_asset": ["total_nca", "total_assets"],
            "current_liab": ["total_cur_liab"],
            "noncurrent_liab": ["total_ncl", "total_liab"],
            "equity": ["total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int", "total_liab_hldr_eqy"],
        },
        "field_order": [
            # 流动资产
            "money_cap", "notes_receiv", "accounts_receiv", "receiv_financing", "prepayment",
            "oth_receiv", "inventories", "contract_assets", "hfs_assets", "nca_within_1y", "oth_cur_assets",
            # 非流动资产
            "debt_invest", "oth_debt_invest", "lt_rec", "lt_eqt_invest", "oth_eq_invest",
            "oth_illiq_fin_assets", "invest_real_estate", "fix_assets", "cip", "produc_bio_assets",
            "oil_and_gas_assets", "use_right_assets", "intan_assets", "r_and_d", "goodwill",
            "lt_amor_exp", "defer_tax_assets", "oth_nca",
            # 流动负债
            "st_borr", "cb_borr", "loan_oth_bank", "deriv_liab", "notes_payable", "acct_payable",
            "adv_receipts", "contract_liab", "sold_for_repur_fa", "depos", "acting_trading_sec",
            "acting_uw_sec", "payroll_payable", "taxes_payable", "oth_payable", "int_payable",
            "div_payable", "oth_cur_liab", "hfs_sales", "non_cur_liab_due_1y",
            # 非流动负债
            "lt_borr", "bond_payable", "lease_liab", "lt_payable", "lt_payroll_payable",
            "estimated_liab", "defer_inc_non_cur_liab", "defer_tax_liab", "oth_ncl",
            # 所有者权益
            "total_share", "oth_eqt_tools", "cap_rese", "treasury_share", "oth_comp_income",
            "surplus_rese", "ordin_risk_reser", "special_rese", "undistr_porfit", "minority_int",
            "forex_differ",
        ],
    },
    "forecast_cf.csv": {
        "key": "cf",
        "name": "CF",
        "title": "现金流量表",
        "doc_title": "\u73b0\u91d1\u6d41\u91cf\u8868",
        "unit": "百万元",
        "category_order": [
            "cfo_inflow",
            "cfo_outflow",
            "cfi_inflow",
            "cfi_outflow",
            "cff_inflow",
            "cff_outflow",
            "balance",
            "supplementary",
            "sub_item",
            "derived",
        ],
        "subtotal_after": {
            "cfo_inflow": ["c_inf_fr_operate_a"],
            "cfo_outflow": ["st_cash_out_act", "n_cashflow_act"],
            "cfi_inflow": ["stot_inflows_inv_act"],
            "cfi_outflow": ["stot_out_inv_act", "n_cashflow_inv_act"],
            "cff_inflow": ["stot_cash_in_fnc_act"],
            "cff_outflow": ["stot_cashout_fnc_act", "n_cash_flows_fnc_act", "eff_fx_flu_cash", "n_incr_cash_cash_equ"],
        },
        "field_order": [
            # 经营活动流入
            "c_fr_sale_sg", "recp_tax_rends", "c_fr_oth_operate_a",
            # 经营活动流出
            "c_paid_goods_s", "c_paid_to_for_empl", "c_paid_for_taxes", "oth_cash_pay_oper_act",
            # 投资活动流入
            "c_disp_withdrwl_invest", "c_recp_return_invest", "n_recp_disp_fiolta",
            "n_recp_disp_sobu", "oth_recp_ral_inv_act",
            # 投资活动流出
            "c_pay_acq_const_fiolta", "c_paid_invest", "n_disp_subs_oth_biz", "oth_pay_ral_inv_act",
            # 筹资活动流入
            "c_recp_cap_contrib", "c_recp_borrow", "proc_issue_bonds", "oth_cash_recp_ral_fnc_act",
            # 筹资活动流出
            "c_prepay_amt_borr", "c_pay_dist_dpcp_int_exp", "oth_cashpay_ral_fnc_act",
            # 期初/期末现金桥
            "c_cash_equ_beg_period", "c_cash_equ_end_period",
        ],
    },
}

# full_*.csv = history+forecast concatenated, same schema as forecast_*.csv.
# Alias to the forecast meta so _statement_rows shapes them identically (same field labels).
FULL_STATEMENT_TABLES = ("full_is.csv", "full_bs.csv", "full_cf.csv")
for _full_name, _fcst_name in (
    ("full_is.csv", "forecast_is.csv"),
    ("full_bs.csv", "forecast_bs.csv"),
    ("full_cf.csv", "forecast_cf.csv"),
):
    STATEMENT_META[_full_name] = STATEMENT_META[_fcst_name]

app = FastAPI(title="ModelKing Workbench")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(_read_text(path))
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(_read_text(path))
    return data if isinstance(data, dict) else {}


def _read_meta(company_dir: Path) -> dict[str, str]:
    db_path = company_dir / "data.db"
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("select key, value from meta where key in ('name', 'ticker')").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows if value is not None}


def _plain(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _company_dirs() -> list[Path]:
    if not COMPANIES_DIR.exists():
        return []
    return sorted([path for path in COMPANIES_DIR.iterdir() if path.is_dir()], key=lambda item: item.name)


def _company_dir(company_id: str) -> Path:
    target = (COMPANIES_DIR / company_id).resolve()
    companies_root = COMPANIES_DIR.resolve()
    if not target.is_dir() or companies_root not in target.parents:
        raise HTTPException(status_code=404, detail=f"Company not found: {company_id}")
    return target


def _latest_yaml1(company_dir: Path) -> Path | None:
    candidates = sorted(company_dir.glob("yaml1*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _core_assumption(company_dir: Path) -> Path | None:
    for name in CORE_ASSUMPTION_NAMES:
        path = company_dir / name
        if path.exists():
            return path
    candidates = sorted(company_dir.glob("*核心假设*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _forecast_summary(company_dir: Path) -> dict[str, Any]:
    return _read_json(company_dir / "forecast" / "dcf_summary.json")


def _manifest(company_dir: Path) -> dict[str, Any]:
    return _read_json(company_dir / "forecast" / "run_manifest.json")


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        return str(path)


def _csv_preview(path: Path) -> str:
    text = _read_text(path)
    rows = list(csv.reader(StringIO(text)))
    out = StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows(rows[:100])
    return out.getvalue()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return list(csv.DictReader(StringIO(_read_text(path))))


def _field_reference_path() -> Path | None:
    exact = BASE_DIR / "docs" / FIELD_REFERENCE_NAME
    if exact.exists():
        return exact
    for path in (BASE_DIR / "docs").glob("*.md"):
        if "\u53c2\u8003" in path.name:
            return path
    return None


def _parse_field_reference() -> dict[str, list[dict[str, str]]]:
    path = _field_reference_path()
    if not path:
        return {}
    text = _read_text(path)
    result: dict[str, list[dict[str, str]]] = {"is": [], "bs": [], "cf": []}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            title = line[3:]
            if "\u5229\u6da6\u8868" in title:
                current = "is"
            elif "\u8d44\u4ea7\u8d1f\u503a\u8868" in title:
                current = "bs"
            elif "\u73b0\u91d1\u6d41\u91cf\u8868" in title:
                current = "cf"
            else:
                current = None
            continue
        if not current or not line.startswith("| `"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 4:
            continue
        result[current].append(
            {
                "field": parts[0].strip("`"),
                "label": parts[1],
                "category": parts[2].strip("`"),
                "category_label": parts[3],
            }
        )
    return result


FIELD_REFERENCE = _parse_field_reference()

# 展示层标签覆盖：数据格式参考.md 个别标签与会计惯例不一致（如 rd_exp 漏"减:"）。
# 仅影响 workbench 展示，不触碰只读契约文档。
LABEL_OVERRIDE: dict[str, str] = {
    "rd_exp": "减:研发费用",
    "credit_impa_loss": "减:信用减值损失",  # 与 资产减值损失 对齐，明确为营业总成本中的减项
}


# 扁平 字段→中文 索引：复用 FIELD_REFERENCE（数据格式参考.md）+ LABEL_OVERRIDE。
# 用于 stash/历史观测等非报表场景的展示层中文化（行/列标签），纯展示，不碰契约。
def _build_field_label_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for rows in FIELD_REFERENCE.values():
        for r in rows:
            idx[r["field"]] = r["label"]
    idx.update(LABEL_OVERRIDE)
    return idx


FIELD_LABELS = _build_field_label_index()

# 非 TuShare 码（knob 路径/历史观测专用），不在 FIELD_REFERENCE，展示层补中文。
# 仅覆盖本项目 defaults.yaml 命名空间与历史观测常见码；未知码由 _humanize_label 原样回退。
STASH_CODE_LABELS: dict[str, str] = {
    "gpm": "整体毛利率",
    "effective_tax_rate": "有效税率",
    "minority_ratio": "少数股东损益占比",
    "fin_exp_total": "财务费用合计",
    "other_fin_exp_abs": "其他财务费用(外生)",
    "ton_cost": "吨成本",
    "interest_bearing_debt": "有息负债",
    "money_cap": "货币资金",
    "interest_expense_net": "利息净额",
    "interest_income": "利息收入",
    # 驱动/旋钮路径末段（terminal fade_paths/hold_paths 用）
    "revenue_yoy": "营收增速",
    "revenue_abs": "营收绝对值",
    "volume_yoy": "销量增速",
    "price_yoy": "吨价增速",
}

_YEAR_PREFIXD_KEY = re.compile(r"^(\d{4})_(.+)$")


def _humanize_label(token: Any) -> str:
    """通用 token→中文标签解析器（展示层）。任何未知 token 原样返回，零丢失。

    顺序：FIELD_LABELS(TuShare 字段) → STASH_CODE_LABELS(knob 码) →
          YYYY_<code> 拆分递归 → 原样。
    """
    s = str(token)
    if s in FIELD_LABELS:
        return FIELD_LABELS[s]
    if s in STASH_CODE_LABELS:
        return STASH_CODE_LABELS[s]
    m = _YEAR_PREFIXD_KEY.match(s)
    if m:
        return f"{m.group(1)} {_humanize_label(m.group(2))}"
    return s


def _humanize_path(path: Any) -> str:
    """defaults.yaml knob 路径 → 中文末段（展示层）。取最后一个 '.' 后的段交 _humanize_label。

    income.cost_rates.sell_exp → 减:销售费用；income.gpm → 整体毛利率；model.revenue_yoy → 营收增速。
    未知段原样回退，零丢失。
    """
    s = str(path)
    leaf = s.rsplit(".", 1)[-1]
    return _humanize_label(leaf)


def _number_or_none(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _nonzero(values: dict[str, float | None], epsilon: float = 1e-9) -> bool:
    return any(value is not None and abs(value) > epsilon for value in values.values())


def _statement_rows(table_name: str, csv_path: Path) -> dict[str, Any] | None:
    rows = _read_csv_rows(csv_path)
    meta = STATEMENT_META.get(table_name)
    if not rows or not meta:
        return None
    years = [str(int(float(row["period"]))) for row in rows if row.get("period")]
    fields_in_csv = set(rows[0].keys()) - {"period"}
    reference = FIELD_REFERENCE.get(meta["key"], [])
    by_category: dict[str, list[dict[str, str]]] = {}
    by_field: dict[str, dict[str, str]] = {}
    for item in reference:
        by_field[item["field"]] = item
        by_category.setdefault(item["category"], []).append(item)

    # 会计准则展示顺序：field_order 给出严格会计序，未列出字段回退到字母序排在末尾。
    field_rank = {field: idx for idx, field in enumerate(meta.get("field_order", []))}
    fallback_rank = len(field_rank)
    for category, items in by_category.items():
        items.sort(key=lambda it: field_rank.get(it["field"], fallback_rank))

    values_by_field: dict[str, dict[str, float | None]] = {}
    for field in fields_in_csv:
        values_by_field[field] = {str(int(float(row["period"]))): _number_or_none(row.get(field)) for row in rows if row.get("period")}

    used: set[str] = set()
    output_rows: list[dict[str, Any]] = []

    def append_field(field: str, role: str | None = None) -> None:
        if field in used or field not in fields_in_csv:
            return
        ref = by_field.get(field)
        if not ref:
            return
        values = values_by_field[field]
        output_rows.append(
            {
                "field": field,
                "label": LABEL_OVERRIDE.get(field, ref["label"]),
                "category": ref["category"],
                "category_label": ref["category_label"],
                "role": role or ("subtotal" if ref["category"] == "subtotal" else "normal"),
                "level": 0 if role in {"subtotal", "total"} or ref["category"] == "subtotal" else 1,
                "is_zero": not _nonzero(values),
                "values": values,
            }
        )
        used.add(field)

    for category in meta["category_order"]:
        for item in by_category.get(category, []):
            append_field(item["field"])
        for field in meta["subtotal_after"].get(category, []):
            append_field(field, "total" if field in {"total_assets", "total_liab", "total_liab_hldr_eqy"} else "subtotal")

    for field in fields_in_csv:
        append_field(field)

    return {
        "key": meta["key"],
        "name": meta["name"],
        "title": meta["title"],
        "unit": meta["unit"],
        "path": _relative(csv_path),
        "years": years,
        "rows": output_rows,
    }


def _statement_sheets(company_dir: Path) -> list[dict[str, Any]]:
    forecast_dir = company_dir / "forecast"
    sheets = []
    for table_name in FORECAST_TABLES:
        sheet = _statement_rows(table_name, forecast_dir / table_name)
        if sheet:
            sheets.append(sheet)
    return sheets


def _full_statement_sheets(company_dir: Path) -> list[dict[str, Any]]:
    """History+forecast concatenated statements (full_*.csv). Same shaping as forecast."""
    forecast_dir = company_dir / "forecast"
    sheets = []
    for table_name in FULL_STATEMENT_TABLES:
        sheet = _statement_rows(table_name, forecast_dir / table_name)
        if sheet:
            sheets.append(sheet)
    return sheets


def _dcf_detail(company_dir: Path) -> list[dict[str, Any]]:
    """Per-year FCFF build: fcff, discount_factor, pv_fcff, nopat, da, capex, delta_nwc."""
    rows = _read_csv_rows(company_dir / "forecast" / "dcf_detail.csv")
    out: list[dict[str, Any]] = []
    for row in rows:
        period = row.get("period")
        if not period:
            continue
        try:
            period_int = int(float(period))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "period": period_int,
                "fcff": _number_or_none(row.get("fcff")),
                "discount_factor": _number_or_none(row.get("discount_factor")),
                "pv_fcff": _number_or_none(row.get("pv_fcff")),
                "nopat": _number_or_none(row.get("nopat")),
                "da": _number_or_none(row.get("da")),
                "capex": _number_or_none(row.get("capex")),
                "delta_nwc": _number_or_none(row.get("delta_nwc")),
            }
        )
    return out


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_cell(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_cell(item)}" for key, item in value.items())
    return str(value)


def _years_from_yaml1(data: dict[str, Any]) -> list[str]:
    meta = data.get("meta", {})
    if isinstance(meta, dict) and isinstance(meta.get("horizon"), list):
        return [str(year) for year in meta["horizon"]]
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("values"), list):
            return [f"Y{i + 1}" for i in range(len(value["values"]))]
    return []


def _spread_values(values: Any, years: list[str]) -> dict[str, str]:
    cells = {year: "" for year in years}
    if isinstance(values, list):
        for index, value in enumerate(values[: len(years)]):
            cells[years[index]] = _cell(value)
    elif years:
        cells[years[0]] = _cell(values)
    return cells


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _series_value(values: Any, index: int, default: float = 0.0) -> float:
    if isinstance(values, list) and index < len(values):
        return _as_float(values[index], default)
    return _as_float(values, default)


def _numeric_year_series(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    series: dict[str, float] = {}
    for year, value in values.items():
        year_text = str(year)
        if re.fullmatch(r"\d{4}", year_text):
            series[year_text] = _as_float(value)
    return series


def _display_source(payload: dict[str, Any], fallback: str) -> str:
    source = _cell(payload.get("src"))
    return source.lstrip("#") if source else fallback


def _product(values: list[float]) -> float:
    out = 1.0
    for value in values:
        out *= value
    return out


def _factor_projection_values(factor: dict[str, Any], years: list[str]) -> list[float]:
    base = _as_float(factor.get("base"))
    projection = factor.get("projection", {})
    if not isinstance(projection, dict):
        projection = {}
    kind = str(projection.get("kind", "constant"))
    if kind == "yoy":
        current = base
        values: list[float] = []
        for index, _year in enumerate(years):
            current *= 1.0 + _series_value(projection.get("values"), index)
            values.append(current)
        return values
    if kind == "abs":
        return [_series_value(projection.get("values"), index) for index, _year in enumerate(years)]
    return [base for _year in years]


def _iter_revenue_leaves(
    segments: dict[str, Any],
    prefix: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    leaves: list[tuple[str, dict[str, Any]]] = []
    for key, payload in segments.items():
        if not isinstance(payload, dict):
            continue
        name = f"{prefix}.{key}" if prefix else str(key)
        child_segments = payload.get("segments")
        if payload.get("kind") == "decomposition" and isinstance(child_segments, dict):
            leaves.extend(_iter_revenue_leaves(child_segments, name))
        else:
            leaves.append((name, payload))
    return leaves


def _evaluate_yaml1_revenue_leaf(
    payload: dict[str, Any],
    years: list[str],
) -> tuple[float, dict[str, float], dict[str, float], dict[str, float | None]]:
    base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
    knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
    family = _cell(payload.get("revenue_family"))
    unit_factor = _as_float(base.get("unit_factor_to_million_cny"), 1.0) or 1.0
    revenues: dict[str, float] = {}
    yoys: dict[str, float] = {}
    volumes: dict[str, float] = {}
    base_revenue = _as_float(base.get("revenue")) / unit_factor

    if family in {"factor_product", "driver_rate"}:
        factors = payload.get("factors")
        if isinstance(factors, list) and factors:
            base_revenue = _product([_as_float(factor.get("base")) for factor in factors if isinstance(factor, dict)]) / unit_factor
            series = [
                _factor_projection_values(factor, years)
                for factor in factors
                if isinstance(factor, dict)
            ]
            previous = base_revenue
            for index, year in enumerate(years):
                current = _product([values[index] for values in series]) / unit_factor
                revenues[year] = current
                yoys[year] = (current / previous - 1.0) if previous else 0.0
                previous = current
            return base_revenue, revenues, yoys, volumes

    if family in {"vol_price", "vol_price_margin"}:
        volume = _as_float(base.get("volume"))
        price = _as_float(base.get("price"))
        base_revenue = volume * price / unit_factor
        previous = base_revenue
        for index, year in enumerate(years):
            volume *= 1.0 + _series_value(knobs.get("volume_yoy"), index)
            price *= 1.0 + _series_value(knobs.get("price_yoy"), index)
            current = volume * price / unit_factor
            volumes[year] = volume
            revenues[year] = current
            yoys[year] = (current / previous - 1.0) if previous else 0.0
            previous = current
        return base_revenue, revenues, yoys, volumes

    if family == "abs":
        previous = base_revenue
        for index, year in enumerate(years):
            current = _series_value(knobs.get("revenue_abs"), index) / unit_factor
            revenues[year] = current
            yoys[year] = (current / previous - 1.0) if previous else 0.0
            previous = current
        return base_revenue, revenues, yoys, volumes

    previous = base_revenue
    for index, year in enumerate(years):
        current = previous * (1.0 + _series_value(knobs.get("revenue_yoy"), index))
        revenues[year] = current
        yoys[year] = (current / previous - 1.0) if previous else 0.0
        previous = current
    return base_revenue, revenues, yoys, volumes


def _yaml1_revenue_view(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        data = yaml.safe_load(_read_text(path))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    years = _years_from_yaml1(data)
    revenue = data.get("income.revenue", {})
    segments = revenue.get("segments", {}) if isinstance(revenue, dict) else {}
    if not years or not isinstance(segments, dict):
        return None

    segment_rows: list[dict[str, Any]] = []
    driver_rows: list[dict[str, Any]] = []
    total_revenues = {year: 0.0 for year in years}
    base_total = 0.0
    base_year = None

    for segment_key, payload in _iter_revenue_leaves(segments):
        base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
        knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
        history = payload.get("history", {}) if isinstance(payload.get("history"), dict) else {}
        history_series = history.get("series", {}) if isinstance(history.get("series"), dict) else {}
        base_series = base.get("series", {}) if isinstance(base.get("series"), dict) else {}
        payload_series = payload.get("series", {}) if isinstance(payload.get("series"), dict) else {}
        family = _cell(payload.get("revenue_family"))
        unit_factor = _as_float(base.get("unit_factor_to_million_cny"), 1.0) or 1.0
        segment_base_year = int(_as_float(base.get("base_year"), 0))
        base_year = base_year or segment_base_year
        base_revenue, revenues, yoys, volumes = _evaluate_yaml1_revenue_leaf(payload, years)
        base_total += base_revenue

        for year, current_revenue in revenues.items():
            total_revenues[year] += current_revenue

        segment_name = _display_source(payload, str(segment_key))
        segment_rows.append(
            {
                "key": str(segment_key),
                "name": segment_name,
                "family": family,
                "base_year": segment_base_year,
                "base_volume": _as_float(base.get("volume")) if family in {"vol_price", "vol_price_margin"} else None,
                "base_price": _as_float(base.get("price")) if family in {"vol_price", "vol_price_margin"} else None,
                "base_revenue": base_revenue,
                "unit_factor": unit_factor,
                "revenues": revenues,
                "yoys": yoys,
                "volumes": volumes,
                "history_revenues": (
                    _numeric_year_series(history_series.get("revenue"))
                    or _numeric_year_series(base_series.get("revenue"))
                    or _numeric_year_series(payload_series.get("revenue"))
                ),
                "history_volumes": (
                    _numeric_year_series(history_series.get("volume"))
                    or _numeric_year_series(base_series.get("volume"))
                    or _numeric_year_series(payload_series.get("volume"))
                ),
                "note": _cell(payload.get("note")),
            }
        )

        for driver_name, values in knobs.items():
            driver_rows.append(
                {
                    "segment": segment_name,
                    "driver": str(driver_name),
                    "values": {year: _series_value(values, index) for index, year in enumerate(years)},
                }
            )
        factors = payload.get("factors")
        if isinstance(factors, list):
            for factor in factors:
                if not isinstance(factor, dict):
                    continue
                projection = factor.get("projection", {}) if isinstance(factor.get("projection"), dict) else {}
                driver_rows.append(
                    {
                        "segment": segment_name,
                        "driver": _cell(factor.get("label")) or _cell(factor.get("key")),
                        "values": {
                            year: value
                            for year, value in zip(years, _factor_projection_values(factor, years), strict=False)
                        },
                        "projection": _cell(projection.get("kind")),
                    }
                )

    total_yoy: dict[str, float] = {}
    previous_total = base_total
    for year in years:
        value = total_revenues[year]
        total_yoy[year] = (value / previous_total - 1.0) if previous_total else 0.0
        previous_total = value

    return {
        "base_year": base_year,
        "years": years,
        "base_revenue": base_total,
        "revenues": total_revenues,
        "yoy": total_yoy,
        "segments": segment_rows,
        "drivers": driver_rows,
        "source": _cell(revenue.get("src")) if isinstance(revenue, dict) else "",
        "note": _cell(revenue.get("note")) if isinstance(revenue, dict) else "",
    }


def _yaml1_meta_sheet(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    meta = data.get("meta", {})
    if isinstance(meta, dict):
        rows.extend({"section": "meta", "field": str(key), "value": _cell(value)} for key, value in meta.items())
    terminal = data.get("terminal", {})
    if isinstance(terminal, dict):
        for key, value in terminal.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    rows.append({"section": "terminal", "field": f"{key}.{sub_key}", "value": _cell(sub_value)})
            else:
                rows.append({"section": "terminal", "field": str(key), "value": _cell(value)})
    return {
        "name": "Meta",
        "description": "Compiler metadata and terminal settings",
        "columns": ["section", "field", "value"],
        "rows": rows,
    }


def _yaml1_revenue_sheet(data: dict[str, Any], years: list[str]) -> dict[str, Any]:
    columns = [
        "segment",
        "driver",
        "family",
        "base_year",
        "base_volume",
        "base_price",
        "base_revenue",
        "unit_factor",
        *years,
        "source",
        "note",
    ]
    rows: list[dict[str, str]] = []
    revenue = data.get("income.revenue", {})
    segments = revenue.get("segments", {}) if isinstance(revenue, dict) else {}
    if isinstance(segments, dict):
        for segment, payload in _iter_revenue_leaves(segments):
            base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
            knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
            for driver, values in knobs.items():
                rows.append(
                    {
                        "segment": str(segment),
                        "driver": str(driver),
                        "family": _cell(payload.get("revenue_family")),
                        "base_year": _cell(base.get("base_year")),
                        "base_volume": _cell(base.get("volume")),
                        "base_price": _cell(base.get("price")),
                        "base_revenue": _cell(base.get("revenue")),
                        "unit_factor": _cell(base.get("unit_factor_to_million_cny")),
                        **_spread_values(values, years),
                        "source": _cell(payload.get("src")),
                        "note": _cell(payload.get("note")),
                    }
                )
            factors = payload.get("factors")
            if isinstance(factors, list):
                for factor in factors:
                    if not isinstance(factor, dict):
                        continue
                    projection = factor.get("projection", {}) if isinstance(factor.get("projection"), dict) else {}
                    rows.append(
                        {
                            "segment": str(segment),
                            "driver": _cell(factor.get("label")) or _cell(factor.get("key")),
                            "family": _cell(payload.get("revenue_family")),
                            "base_year": _cell(base.get("base_year")),
                            "base_volume": _cell(factor.get("base")),
                            "base_price": "",
                            "base_revenue": "",
                            "unit_factor": _cell(base.get("unit_factor_to_million_cny")),
                            **_spread_values(projection.get("values"), years),
                            "source": _cell(payload.get("src")),
                            "note": f"projection={_cell(projection.get('kind'))}",
                        }
                    )
    return {
        "name": "Revenue Build",
        "description": "Decomposition leaf drivers by segment and year",
        "columns": columns,
        "rows": rows,
    }


def _yaml1_knob_sheet(data: dict[str, Any], years: list[str]) -> dict[str, Any]:
    columns = ["path", "kind", *years, "source", "note"]
    rows: list[dict[str, str]] = []
    skip = {"meta", "terminal", "stash", "income.revenue"}
    for path, payload in data.items():
        if path in skip or not isinstance(payload, dict):
            continue
        values = payload.get("values")
        if values is None:
            continue
        rows.append(
            {
                "path": str(path),
                "kind": _cell(payload.get("kind")),
                **_spread_values(values, years),
                "source": _cell(payload.get("src")),
                "note": _cell(payload.get("note")),
            }
        )
    return {
        "name": "DCF Knobs",
        "description": "Sparse yaml1 overrides that enter the forecast engine",
        "columns": columns,
        "rows": rows,
    }


def _flatten_stash(name: str, payload: Any, prefix: list[str], rows: list[dict[str, str]]) -> None:
    if isinstance(payload, dict):
        series = payload.get("series")
        if isinstance(series, dict):
            for item, values in series.items():
                if isinstance(values, dict):
                    row = {"group": name, "item": " / ".join([*prefix, str(item)]), "note": _cell(payload.get("note")), "unit": _cell(payload.get("unit"))}
                    for year, value in values.items():
                        row[str(year)] = _cell(value)
                    rows.append(row)
            return
        for key, value in payload.items():
            if key not in {"note", "unit"}:
                _flatten_stash(name, value, [*prefix, str(key)], rows)


def _yaml1_stash_sheet(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    stash = data.get("stash", {})
    if isinstance(stash, dict):
        for name, payload in stash.items():
            _flatten_stash(str(name), payload, [], rows)
    year_columns = sorted({key for row in rows for key in row if key.isdigit()})
    return {
        "name": "Stash",
        "description": "Non-DCF structured storage kept for frontend and traceability",
        "columns": ["group", "item", "unit", *year_columns, "note"],
        "rows": rows,
    }


def _yaml1_sheets(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        data = yaml.safe_load(_read_text(path))
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    years = _years_from_yaml1(data)
    sheets = [
        _yaml1_meta_sheet(data),
        _yaml1_revenue_sheet(data, years),
        _yaml1_knob_sheet(data, years),
        _yaml1_stash_sheet(data),
    ]
    return [sheet for sheet in sheets if sheet["rows"]]


# ─────────────────────────── yaml1 stash type-dispatch (universal) ───────────────────────────
# Stash is the most free-form, per-company-different part of yaml1. Render by JSON *shape*
# (not by company/block name) so any company's stash is displayed with nothing dropped.
# Mirrors the philosophy of _iter_revenue_leaves: generic traversal + type dispatch.


def _is_year_key(key: Any) -> bool:
    s = str(key)
    if not s.isdigit():
        return False
    n = int(s)
    return 1900 < n < 2100


def _stash_series_items(series: dict) -> tuple[list[dict], bool]:
    """Return (items, is_year_table). items=[{label, values:{key:value}, note?}]."""
    items: list[dict] = []
    is_year_table = True
    for label, values in series.items():
        if not isinstance(values, dict):
            continue
        entry: dict = {"key": str(label), "label": _humanize_label(label), "values": {}, "note": None}
        block_year = True
        has_value = False
        for k, v in values.items():
            if k == "note":
                entry["note"] = _cell(v)
                continue
            if k in ("unit", "caveat"):
                continue
            entry["values"][str(k)] = v
            has_value = True
            if not _is_year_key(k):
                block_year = False
        if has_value:
            items.append(entry)
            if not block_year:
                is_year_table = False
    if not items:
        is_year_table = False
    return items, is_year_table


def _stash_block(name: str, payload: Any) -> dict:
    """Classify one stash block by JSON shape → typed block. Universal, never drops."""
    if isinstance(payload, list):
        return {"name": name, "type": "list", "items": [x if isinstance(x, str) else _cell(x) for x in payload]}
    if not isinstance(payload, dict):
        return {"name": name, "type": "kv", "items": [{"label": "value", "value": _cell(payload)}]}

    note = _cell(payload["note"]) if isinstance(payload.get("note"), str) else None
    unit = _cell(payload["unit"]) if isinstance(payload.get("unit"), str) else None
    caveat = _cell(payload["caveat"]) if isinstance(payload.get("caveat"), str) else None
    base = {"name": name, "note": note, "unit": unit, "caveat": caveat}

    series = payload.get("series")
    if isinstance(series, dict):
        items, is_year_table = _stash_series_items(series)
        # 列头中文化：并集所有 item 的 values 键 → {rawKey: 中文}，前端优先用，缺失回退 raw。
        col_keys: set[str] = set()
        for it in items:
            col_keys.update(it.get("values", {}).keys())
        col_labels = {k: _humanize_label(k) for k in col_keys}
        extras = [
            _stash_block(str(k), v)
            for k, v in payload.items()
            if k not in ("note", "unit", "caveat", "series")
        ]
        return {
            **base,
            "type": "series_table" if is_year_table else "attr_table",
            "items": items,
            "col_labels": col_labels,
            "extras": extras,
        }

    # dict without series: text_dict / scalar_table / kv (mixed → kv preserves everything)
    text_items: list[dict] = []
    scalar_items: list[dict] = []
    sub_items: list[dict] = []
    has_string = has_scalar = has_other = False
    for k, v in payload.items():
        if k in ("note", "unit", "caveat"):
            continue
        if isinstance(v, str):
            has_string = True
            text_items.append({"label": str(k), "text": v})
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            has_scalar = True
            scalar_items.append({"label": str(k), "value": v})
        else:
            has_other = True
            sub_items.append(_stash_block(str(k), v))
    if has_other or (has_string and has_scalar):
        return {**base, "type": "kv", "items": text_items + scalar_items + sub_items}
    if has_string:
        return {**base, "type": "text_dict", "items": text_items}
    if has_scalar:
        return {**base, "type": "scalar_table", "items": scalar_items}
    return {**base, "type": "kv", "items": []}


def _yaml1_stash_view(data: dict[str, Any]) -> list[dict]:
    stash = data.get("stash")
    if not isinstance(stash, dict):
        return []
    return [_stash_block(str(name), payload) for name, payload in stash.items()]


# ─────────────────────────── yaml1 assumptions view (universal knob grouping) ───────────────────────────
# Group knobs by defaults.yaml standard namespace prefix (universal, not company-specific).
# Absent paths naturally drop out (absent = falls back to yaml2 default).

ASSUMPTION_SECTION_DEFS = (
    ("gpm", "毛利率", ("income.gpm",)),
    ("cost_rates", "费用率", ("income.cost_rates.",)),
    (
        "below_op",
        "营业利润调节 / 营业外收支（绝对值）",
        ("income.cost_abs.", "income.operating_adjustments_abs.", "income.below_line_abs."),
    ),
    ("tax_minority", "税率 / 少数股东", ("income.effective_tax_rate", "income.minority_ratio")),
)
OVERRIDE_MARKERS = ("主动覆盖", "查证", "弃模型", "normalized", "主动收缩", "手拍")


def _yaml1_base_period(data: dict[str, Any]) -> str:
    meta = data.get("meta", {})
    if isinstance(meta, dict) and isinstance(meta.get("horizon"), list) and meta["horizon"]:
        try:
            return str(int(meta["horizon"][0]) - 1)
        except (TypeError, ValueError):
            return ""
    return ""


def _assumptions_terminal(term: Any) -> dict:
    if not isinstance(term, dict):
        return {}
    fade = term.get("fade") if isinstance(term.get("fade"), dict) else {}
    return {
        "explicit_end": term.get("explicit_end"),
        "to_year": fade.get("to_year"),
        "kind": fade.get("kind"),
        "fade_paths": [_humanize_path(p) for p in (fade.get("fade_paths") or [])],
        "hold_paths": [_humanize_path(p) for p in (fade.get("hold_paths") or [])],
        "perpetual_growth": term.get("perpetual_growth"),
        "src": _cell(term.get("src")) or None,
    }


def _assumptions_traceability(data: dict[str, Any]) -> list[dict]:
    """溯源附注 is a skill-defined standard stash block (yaml1compiler_v5 §6.2)."""
    stash = data.get("stash")
    if not isinstance(stash, dict):
        return []
    src = stash.get("溯源附注")
    if not isinstance(src, dict):
        return []
    return [{"name": str(k), "text": v} for k, v in src.items() if isinstance(v, str)]


def _yaml1_assumptions_view(data: dict[str, Any], years: list[str]) -> dict:
    skip = {"meta", "terminal", "stash", "income.revenue"}
    by_section: dict[str, list[dict]] = {key: [] for key, _, _ in ASSUMPTION_SECTION_DEFS}
    other: list[dict] = []
    for path, payload in data.items():
        if path in skip or not isinstance(payload, dict):
            continue
        values = payload.get("values")
        if not isinstance(values, list):
            continue
        src = _cell(payload.get("src"))
        knob = {
            "path": path,
            "src": src,
            "values": [_as_float(v) for v in values],
            "note": _cell(payload.get("note")) or None,
            "is_override": any(m in src for m in OVERRIDE_MARKERS),
        }
        placed = False
        for key, _, prefixes in ASSUMPTION_SECTION_DEFS:
            if any(path == p or path.startswith(p) for p in prefixes):
                by_section[key].append(knob)
                placed = True
                break
        if not placed:
            other.append(knob)
    sections = [
        {"key": key, "title": title, "knobs": by_section[key]}
        for key, title, _ in ASSUMPTION_SECTION_DEFS
        if by_section[key]
    ]
    if other:
        sections.append({"key": "other", "title": "其他覆盖", "knobs": other})
    return {
        "years": years,
        "base_period": _yaml1_base_period(data),
        "sections": sections,
        "terminal": _assumptions_terminal(data.get("terminal")),
        "traceability": _assumptions_traceability(data),
    }


def _presentation_cache_path(company_dir: Path) -> Path:
    return company_dir / ".modelking" / "yaml1_presentation.json"


def _yaml1_presentation_cache(company_dir: Path) -> dict[str, Any] | None:
    path = _presentation_cache_path(company_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(_read_text(path))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_yaml1_presentation_cache(company_dir: Path, presentation: dict[str, Any]) -> None:
    path = _presentation_cache_path(company_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(presentation, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _yaml1_presentation_context(company_dir: Path, yaml1_path: Path, revenue_view: dict[str, Any] | None, sheets: list[dict[str, Any]]) -> dict[str, Any]:
    yaml1_data = _read_yaml(yaml1_path)
    typed_paths: list[dict[str, Any]] = []
    for path, payload in yaml1_data.items():
        if isinstance(payload, dict):
            typed_paths.append(
                {
                    "path": path,
                    "kind": payload.get("kind") or payload.get("type") or payload.get("rollup"),
                    "source": payload.get("src"),
                    "note": _truncate_text(_cell(payload.get("note")), 600),
                }
            )

    return {
        "company": _company_summary(company_dir),
        "yaml1_path": _relative(yaml1_path),
        "yaml1_revenue_view": revenue_view,
        "yaml1_sheets": [
            {
                "name": sheet.get("name"),
                "description": sheet.get("description"),
                "columns": sheet.get("columns"),
                "sample_rows": sheet.get("rows", [])[:12],
            }
            for sheet in sheets
        ],
        "yaml1_typed_paths": typed_paths,
        "yaml1_excerpt": _truncate_text(_read_text(yaml1_path), 20000),
    }


def _presentation_provider_order() -> list[str]:
    load_env(BASE_DIR / ".env")
    providers = []
    if llm_api_key("glm"):
        providers.append("glm")
    if llm_api_key("kimi"):
        providers.append("kimi")
    return providers or ["glm", "kimi"]


def _json_from_llm_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("presentation response must be a JSON object")
    return parsed


def _fallback_presentation(context: dict[str, Any], reason: str) -> dict[str, Any]:
    company = context.get("company", {})
    revenue = context.get("yaml1_revenue_view") or {}
    segments = revenue.get("segments") if isinstance(revenue, dict) else []
    return {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "mode": "fallback",
        "provider": None,
        "model": None,
        "title": f"{company.get('name', '公司')}业务假设",
        "subtitle": "未能调用大模型，暂按确定性收入拆分展示。",
        "business_question": "这份 YAML1 主要覆盖哪些业务判断？",
        "display_strategy": "按已结构化的收入 decomposition 展示业务线和驱动假设。",
        "primary_dimension": "业务线",
        "segment_order": [item.get("name") for item in segments if isinstance(item, dict) and item.get("name")],
        "driver_labels": {
            "volume_yoy": "销量增长",
            "price_yoy": "价格变化",
            "revenue_yoy": "收入增长",
        },
        "insights": [reason],
        "risks": [],
        "source_paths": ["income.revenue", "income.revenue.segments"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _validate_presentation_schema(parsed: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    allowed_driver_labels = parsed.get("driver_labels")
    if not isinstance(allowed_driver_labels, dict):
        allowed_driver_labels = {}
    segment_order = parsed.get("segment_order")
    if not isinstance(segment_order, list):
        segment_order = []
    insights = parsed.get("insights")
    if not isinstance(insights, list):
        insights = []
    risks = parsed.get("risks")
    if not isinstance(risks, list):
        risks = []
    source_paths = parsed.get("source_paths")
    if not isinstance(source_paths, list):
        source_paths = []

    return {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "mode": "llm",
        "provider": provider,
        "model": model,
        "title": str(parsed.get("title") or "业务假设"),
        "subtitle": str(parsed.get("subtitle") or "由 YAML1 生成的业务展示方案。"),
        "business_question": str(parsed.get("business_question") or "这份 YAML1 在表达什么业务判断？"),
        "display_strategy": str(parsed.get("display_strategy") or "按业务驱动展示。"),
        "primary_dimension": str(parsed.get("primary_dimension") or "业务线"),
        "segment_order": [str(item) for item in segment_order if item],
        "driver_labels": {str(key): str(value) for key, value in allowed_driver_labels.items()},
        "insights": [str(item) for item in insights[:6] if item],
        "risks": [str(item) for item in risks[:6] if item],
        "source_paths": [str(item) for item in source_paths[:20] if item],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _call_yaml1_presentation_llm(context: dict[str, Any]) -> dict[str, Any]:
    system = (
        "你是买方投研工作台 ModelKing 的展示编排器。你的任务不是算账、不是修改 YAML、不是补数，"
        "而是阅读 yaml1 的结构，决定前端应该如何给不懂代码的投研负责人展示这家公司。"
        "只能引用输入中已有的路径和事实；不得编造任何数值。输出必须是 JSON object。"
    )
    user = json.dumps(
        {
            "task": "为 YAML1 生成前端展示 schema。优先识别这家公司最自然的业务维度，例如产品线、区域、渠道、量价、产能、客户数、ARPU、息差等。",
            "required_json_schema": {
                "title": "短标题，例如 收入模型 / 产品线假设 / 生息资产模型",
                "subtitle": "给业务读者看的说明，不出现 YAML jargon",
                "business_question": "这一页回答的核心业务问题",
                "display_strategy": "为什么这样组织展示",
                "primary_dimension": "主展示维度",
                "segment_order": ["建议前端展示的业务线名称顺序，必须来自输入名称"],
                "driver_labels": {"volume_yoy": "销量增长", "price_yoy": "价格变化"},
                "insights": ["2-6 条业务读法，不要编数，只能基于结构和方向"],
                "risks": ["可选，展示层应提示的假设张力"],
                "source_paths": ["本展示依赖的 yaml1 路径"],
            },
            "constraints": [
                "不要输出 Markdown。",
                "不要输出代码。",
                "不要创造输入中不存在的业务线或数值。",
                "不要改变 DCF 参数；这只是展示 schema。",
                "如果无法泛化，就说明采用的 fallback 展示方式。",
            ],
            "context": context,
        },
        ensure_ascii=False,
    )

    errors: list[str] = []
    for provider in _presentation_provider_order():
        api_key = llm_api_key(provider)
        if not api_key:
            errors.append(f"{provider}: API key missing")
            continue
        base_url = llm_base_url(provider)
        model = llm_model(provider)
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": int(os.environ.get("YAML1_PRESENTATION_MAX_TOKENS", os.environ.get("LLM_MAX_TOKENS", "4096"))),
            "response_format": {"type": "json_object"},
        }
        if provider != "kimi":
            body["temperature"] = float(os.environ.get("YAML1_PRESENTATION_TEMPERATURE", os.environ.get("LLM_TEMPERATURE", "0.2")))
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=llm_timeout_seconds(provider),
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            parsed = _json_from_llm_text(text)
            presentation = _validate_presentation_schema(parsed, provider, str(data.get("model") or model))
            presentation["_usage"] = data.get("usage", {})
            return presentation
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI as generation status
            errors.append(f"{provider}: {type(exc).__name__}: {exc}")
    return _fallback_presentation(context, "大模型展示编排失败：" + "；".join(errors))


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _material_files(company_dir: Path) -> list[dict[str, Any]]:
    roots = [company_dir / "active_vore", company_dir / "extractions", company_dir / "annuals"]
    files: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "path": _relative(path),
                    "kind": path.suffix.lstrip(".") or "file",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    return files[:300]


def _company_summary(company_dir: Path) -> dict[str, Any]:
    defaults_path = company_dir / "defaults.yaml"
    defaults = _read_yaml(defaults_path)
    meta = _read_meta(company_dir)
    forecast = _forecast_summary(company_dir)
    manifest = _manifest(company_dir)
    yaml1_path = _latest_yaml1(company_dir)
    core_path = _core_assumption(company_dir)
    market = defaults.get("market", {}) if isinstance(defaults.get("market"), dict) else {}
    model = defaults.get("model", {}) if isinstance(defaults.get("model"), dict) else {}
    ticker = meta.get("ticker") or _plain(defaults.get("ticker")) or _plain(market.get("ticker"))
    name = meta.get("name") or _plain(defaults.get("name")) or _plain(market.get("name")) or company_dir.name.rsplit("_", 1)[0]
    code = str(ticker).split(".")[0] if ticker else company_dir.name.rsplit("_", 1)[-1]
    forecast_dir = company_dir / "forecast"
    updated_at = None
    if (forecast_dir / "run_manifest.json").exists():
        updated_at = (forecast_dir / "run_manifest.json").stat().st_mtime
    elif forecast_dir.exists():
        updated_at = forecast_dir.stat().st_mtime
    return {
        "id": company_dir.name,
        "name": str(name),
        "code": code,
        "ticker": ticker,
        "path": _relative(company_dir),
        "has_yaml1": yaml1_path is not None,
        "has_defaults": defaults_path.exists(),
        "has_forecast": forecast_dir.exists(),
        "has_core_assumption": core_path is not None,
        "has_materials": any((company_dir / name).exists() for name in ("active_vore", "extractions", "annuals")),
        "per_share_value": forecast.get("per_share_value"),
        "base_period": forecast.get("base_period") or _plain(model.get("base_year")),
        "forecast_years": forecast.get("forecast_years") or _plain(model.get("forecast_years")),
        "warnings_count": manifest.get("warnings_count"),
        "backtest_status": manifest.get("backtest_status"),
        "updated_at": updated_at,
    }


@app.get("/api/companies")
def list_companies() -> list[dict[str, Any]]:
    return [_company_summary(path) for path in _company_dirs()]


@app.get("/api/companies/{company_id}")
def read_company(company_id: str) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    core_path = _core_assumption(company_dir)
    forecast_dir = company_dir / "forecast"
    yaml1_data = _read_yaml(yaml1_path) if yaml1_path else {}
    yaml1_years = _years_from_yaml1(yaml1_data) if yaml1_data else []
    tables = []
    for name in FORECAST_TABLES:
        path = forecast_dir / name
        if path.exists():
            tables.append({"name": name, "path": _relative(path), "csv": _csv_preview(path)})
    return {
        "summary": _company_summary(company_dir),
        "core_assumption_md": _read_text(core_path) if core_path else None,
        "yaml1_path": _relative(yaml1_path) if yaml1_path else None,
        "yaml1_text": _read_text(yaml1_path) if yaml1_path else None,
        "yaml1_revenue_view": _yaml1_revenue_view(yaml1_path),
        "yaml1_sheets": _yaml1_sheets(yaml1_path),
        "yaml1_stash_view": _yaml1_stash_view(yaml1_data) if yaml1_data else [],
        "yaml1_assumptions_view": _yaml1_assumptions_view(yaml1_data, yaml1_years) if yaml1_data else None,
        "yaml1_presentation": _yaml1_presentation_cache(company_dir),
        "dcf_summary": _forecast_summary(company_dir) or None,
        "manifest": _manifest(company_dir) or None,
        "tables": tables,
        "statement_sheets": _statement_sheets(company_dir),
        "full_statement_sheets": _full_statement_sheets(company_dir),
        "dcf_detail": _dcf_detail(company_dir),
        "materials": _material_files(company_dir),
    }


@app.post("/api/companies/{company_id}/forecast")
def regenerate_forecast(company_id: str) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    summary = _company_summary(company_dir)
    ticker = summary.get("ticker")
    if not ticker:
        raise HTTPException(status_code=400, detail="defaults.yaml does not provide ticker")
    run = run_company_forecast(ticker=str(ticker))
    return {
        "ok": True,
        "stdout": f"Written forecast: {run.output_dir}\nPer-share value: {run.summary['per_share_value']}",
        "stderr": "",
    }


class SensitivityPayload(BaseModel):
    wacc: float
    terminal_growth: float
    terminal_capex_da_ratio: float


def _load_forecast_build(path: Path) -> ForecastBuildResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ForecastBuildResult(
        income_statement=pd.DataFrame(),
        balance_sheet=pd.DataFrame(),
        cash_flow=pd.DataFrame(),
        dcf=pd.DataFrame(data["dcf_rows"]),
        base_period=data["base_period"],
        forecast_years=data["forecast_years"],
        net_debt=data["net_debt"],
        total_shares=data["total_shares"],
        ticker=data["ticker"],
        name=data["name"],
        review_flags=data["review_flags"],
    )


@app.post("/api/companies/{company_id}/dcf-sensitivity")
def dcf_sensitivity(company_id: str, payload: SensitivityPayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    build_path = company_dir / ".modelking" / "forecast_build.json"
    if not build_path.exists():
        raise HTTPException(status_code=400, detail="Run forecast first")
    if payload.wacc <= payload.terminal_growth:
        raise HTTPException(
            status_code=400,
            detail="WACC must be greater than terminal growth",
        )
    build = _load_forecast_build(build_path)
    result = value_from_statements(
        build,
        wacc=payload.wacc,
        terminal_growth=payload.terminal_growth,
        terminal_capex_da_ratio=payload.terminal_capex_da_ratio,
    )
    return {"summary": result["summary"]}


@app.get("/api/companies/{company_id}/yaml1/presentation/stream")
def yaml1_presentation_stream(company_id: str, refresh: bool = True) -> StreamingResponse:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    if not yaml1_path:
        raise HTTPException(status_code=404, detail="yaml1_*.yaml was not found")

    def generate():
        yield _sse("status", {"step": "start", "message": "开始读取 YAML1"})
        cached = _yaml1_presentation_cache(company_dir)
        if cached and not refresh:
            yield _sse("status", {"step": "cache", "message": "已找到缓存展示方案"})
            yield _sse("final", {"presentation": cached})
            return

        revenue_view = _yaml1_revenue_view(yaml1_path)
        sheets = _yaml1_sheets(yaml1_path)
        yield _sse("status", {"step": "parse", "message": "已抽取业务线、驱动和底稿结构"})
        context = _yaml1_presentation_context(company_dir, yaml1_path, revenue_view, sheets)
        provider_order = _presentation_provider_order()
        yield _sse(
            "status",
            {
                "step": "llm",
                "message": f"正在调用展示编排模型（优先 {provider_order[0] if provider_order else 'glm'}）",
            },
        )
        presentation = _call_yaml1_presentation_llm(context)
        yield _sse(
            "status",
            {
                "step": "validate",
                "message": "正在校验展示 schema 与本地 YAML1 事实边界",
                "provider": presentation.get("provider"),
                "model": presentation.get("model"),
            },
        )
        _write_yaml1_presentation_cache(company_dir, presentation)
        yield _sse("status", {"step": "done", "message": "展示方案已生成并缓存"})
        yield _sse("final", {"presentation": presentation})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"app": "modelking-workbench", "status": "ok"}


@app.get("/assets/{asset_path:path}")
def asset(asset_path: str) -> FileResponse:
    path = (APP_DIST / "assets" / asset_path).resolve()
    assets_root = (APP_DIST / "assets").resolve()
    if not path.is_file() or assets_root not in path.parents:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_path}")
    return FileResponse(path)


@app.get("/")
def index() -> FileResponse:
    index_path = APP_DIST / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="Frontend is not built. Run npm run build.")
    return FileResponse(index_path)


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    return index()


def ensure_frontend_built(no_build: bool = False) -> None:
    if (APP_DIST / "index.html").exists():
        return
    if no_build:
        raise RuntimeError("app/dist/index.html missing; run npm run build first")
    npm = "npm.cmd" if (BASE_DIR / "package.json").exists() else None
    if not npm:
        raise RuntimeError("package.json missing; cannot build frontend")
    subprocess.run([npm, "run", "build"], cwd=BASE_DIR, check=True)


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) != 0


def _http_bytes(url: str, timeout: float = 0.8) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except (OSError, urllib.error.URLError):
        return None


def _existing_workbench_is_healthy(url: str) -> bool:
    health_body = _http_bytes(f"{url}/api/health")
    if health_body and b"modelking-workbench" in health_body:
        html = _http_bytes(url)
        if not html:
            return False
        match = re.search(rb'src="/([^"]+\.js)"', html)
        if not match:
            return False
        js = _http_bytes(f"{url}/{match.group(1).decode('ascii')}")
        return bool(js and not js.lstrip().lower().startswith(b"<!doctype"))

    companies_body = _http_bytes(f"{url}/api/companies")
    html = _http_bytes(url)
    if not companies_body or not html:
        return False
    match = re.search(rb'src="/([^"]+\.js)"', html)
    if not match:
        return False
    js = _http_bytes(f"{url}/{match.group(1).decode('ascii')}")
    return bool(js and not js.lstrip().lower().startswith(b"<!doctype"))


def _first_free_port(host: str, start_port: int, attempts: int = 20) -> int:
    for port in range(start_port, start_port + attempts):
        if _port_is_free(host, port):
            return port
    raise RuntimeError(f"No free port found from {start_port} to {start_port + attempts - 1}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local ModelKing web workbench.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open Chrome/browser automatically")
    parser.add_argument("--no-build", action="store_true", help="Require an existing app/dist build")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_frontend_built(no_build=args.no_build)
    requested_url = f"http://{args.host}:{args.port}"
    if not _port_is_free(args.host, args.port):
        if _existing_workbench_is_healthy(requested_url):
            print(f"ModelKing workbench already running: {requested_url}")
            if not args.no_open:
                webbrowser.open(requested_url)
            return 0
        next_port = _first_free_port(args.host, args.port + 1)
        print(f"Port {args.port} is in use by a stale or non-ModelKing service; using {next_port}.")
        args.port = next_port
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    import uvicorn

    print(f"ModelKing workbench: {url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
