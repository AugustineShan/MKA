"""Local web workbench for ModelKing.

This is intentionally a thin UI shell. It reads company folders, serves the
React app, and delegates DCF generation to the official forecast pipeline:
defaults.yaml + yaml1*.yaml -> forecast/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
import webbrowser
from io import StringIO
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

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
    },
}

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
                "label": ref["label"],
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


def _display_source(payload: dict[str, Any], fallback: str) -> str:
    source = _cell(payload.get("src"))
    return source.lstrip("#") if source else fallback


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

    for segment_key, payload in segments.items():
        if not isinstance(payload, dict):
            continue
        base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
        knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
        family = _cell(payload.get("revenue_family"))
        unit_factor = _as_float(base.get("unit_factor_to_million_cny"), 1.0) or 1.0
        segment_base_year = int(_as_float(base.get("base_year"), 0))
        base_year = base_year or segment_base_year
        volume = _as_float(base.get("volume"))
        price = _as_float(base.get("price"))
        base_revenue = _as_float(base.get("revenue"))
        if family == "vol_price":
            base_revenue = volume * price / unit_factor
        base_total += base_revenue

        revenues: dict[str, float] = {}
        yoys: dict[str, float] = {}
        previous_revenue = base_revenue
        current_volume = volume
        current_price = price
        for index, year in enumerate(years):
            if family == "vol_price":
                current_volume *= 1.0 + _series_value(knobs.get("volume_yoy"), index)
                current_price *= 1.0 + _series_value(knobs.get("price_yoy"), index)
                current_revenue = current_volume * current_price / unit_factor
            else:
                current_revenue = previous_revenue * (1.0 + _series_value(knobs.get("revenue_yoy"), index))
            revenues[year] = current_revenue
            yoys[year] = (current_revenue / previous_revenue - 1.0) if previous_revenue else 0.0
            total_revenues[year] += current_revenue
            previous_revenue = current_revenue

        segment_name = _display_source(payload, str(segment_key))
        segment_rows.append(
            {
                "key": str(segment_key),
                "name": segment_name,
                "family": family,
                "base_year": segment_base_year,
                "base_volume": volume if family == "vol_price" else None,
                "base_price": price if family == "vol_price" else None,
                "base_revenue": base_revenue,
                "unit_factor": unit_factor,
                "revenues": revenues,
                "yoys": yoys,
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
        for segment, payload in segments.items():
            if not isinstance(payload, dict):
                continue
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
        "dcf_summary": _forecast_summary(company_dir) or None,
        "manifest": _manifest(company_dir) or None,
        "tables": tables,
        "statement_sheets": _statement_sheets(company_dir),
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
