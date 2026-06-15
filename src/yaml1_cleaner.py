"""Clean yaml1 sparse assumptions into a yearly YAML2-compatible object.

This module is deliberately deterministic: it folds yaml1 decomposition,
expands terminal fade rules, resolves sparse overrides onto YAML2 defaults,
and emits a report. It does not call LLMs, plug residuals, or run valuation.
"""

from __future__ import annotations

import argparse
import ctypes
import copy
import csv
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.clean import resolve_is_signs
from src.yaml2_schema import plain_value, read_yaml2, write_yaml2


TOLERANCE_MILLION_CNY = 1.0
BASE_DIR = Path(__file__).resolve().parent.parent
COMPANIES_DIR = BASE_DIR / "companies"

MODEL_REVENUE_YOY = "model.revenue_yoy"
REVENUE_ALIASES = {"revenue", "income.revenue", MODEL_REVENUE_YOY}

FINANCIAL_EXPENSE_NUMERIC_KEYS = {
    "interest_expense_rate",
    "cash_interest_rate",
    "other_fin_exp_abs",
    "base_interest_expense",
    "base_interest_income",
    "base_fin_exp",
}

BS_YEARLY_SCALAR_KEYS = {
    "capex_pct",
    "depr_rate",
    "amort_intang_assets",
    "lt_amort_deferred_exp",
    "use_right_asset_dep",
    "dividend_payout",
}


class Yaml1CleanError(RuntimeError):
    """Raised when yaml1 cannot be cleaned deterministically."""


@dataclass
class FoldResult:
    base_year: int
    explicit_horizon: list[int]
    base_revenue: float
    revenue_by_year: dict[int, float]
    revenue_yoy: list[float]
    segment_base_revenue: dict[str, float]
    segment_revenue_by_year: dict[str, dict[int, float]]
    unit_factors: dict[str, float]
    warnings: list[dict[str, Any]]


@dataclass
class CleanResult:
    forecast_params: dict[str, Any]
    report: dict[str, Any]

    @property
    def yaml2_yearly(self) -> dict[str, Any]:
        """Backward-compatible alias for the resolved forecast parameters."""
        return self.forecast_params


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - repository depends on pyyaml
        raise Yaml1CleanError("pyyaml is required to read yaml1") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise Yaml1CleanError(f"YAML root must be a mapping: {path}")
    return data


def load_clean_annual(path: str | Path) -> dict[int, dict[str, float]]:
    path = Path(path)
    if path.suffix.lower() == ".db":
        return _load_clean_annual_db(path)
    if not path.exists():
        db_path = path.parent / "data.db"
        if db_path.exists():
            return _load_clean_annual_db(db_path)
    rows: dict[int, dict[str, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            period = int(str(row["period"])[:4])
            values: dict[str, float] = {}
            for key, value in row.items():
                if key == "period":
                    continue
                values[key] = _to_float(value)
            rows[period] = values
    if not rows:
        raise Yaml1CleanError(f"clean_annual is empty: {path}")
    return rows


def _load_clean_annual_db(path: Path) -> dict[int, dict[str, float]]:
    rows: dict[int, dict[str, float]] = {}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("select * from clean_annual order by period")
        for row in cursor:
            period = int(str(row["period"])[:4])
            values: dict[str, float] = {}
            for key in row.keys():
                if key == "period":
                    continue
                values[key] = _to_float(row[key])
            rows[period] = values
    if not rows:
        raise Yaml1CleanError(f"clean_annual is empty in database: {path}")
    return rows


def find_company_dir(ticker: str) -> Path:
    code = ticker.split(".")[0]
    candidates = sorted(COMPANIES_DIR.glob(f"*_{code}"))
    if not candidates:
        raise FileNotFoundError(f"No company directory found for {ticker}")
    return candidates[0]


def default_yaml1_path(company_dir: Path) -> Path:
    candidates = sorted(
        company_dir.glob("yaml1*.yaml"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No yaml1*.yaml found under {company_dir}")
    return candidates[0]


def _to_float(value: Any, default: float = 0.0) -> float:
    value = plain_value(value)
    if value is None or value == "":
        return default
    try:
        if value != value:
            return default
    except TypeError:
        return default
    return float(value)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Yaml1CleanError(f"{label} must be a mapping")
    return value


def _path_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _path_exists(data: dict[str, Any], path: str) -> bool:
    sentinel = object()
    return _path_get(data, path, sentinel) is not sentinel


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    cur: dict[str, Any] = data
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur.setdefault(part, {})
        if not isinstance(nxt, dict):
            raise Yaml1CleanError(f"Cannot set {path}: {part} is not a mapping")
        cur = nxt
    cur[parts[-1]] = value


def _param(value: Any, source: str, note: str | None = None) -> dict[str, Any]:
    out = {"value": value, "source": source}
    if note:
        out["note"] = note
    return out


def _existing_param_with_value(node: Any, value: Any) -> Any:
    if isinstance(node, dict) and "value" in node:
        out = copy.deepcopy(node)
        out["value"] = value
        return out
    return value


def _infer_unit_factor_from_text(text: str, warnings: list[dict[str, Any]], path: str) -> float | None:
    match = re.search(r"(?:÷|/)\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    factor = float(match.group(1))
    warnings.append(
        {
            "stage": "fold",
            "path": path,
            "message": f"unit_factor 从文本推断: {factor:g}",
        }
    )
    return factor


def _unit_factor(segment: dict[str, Any], inherited_note: str, path: str, warnings: list[dict[str, Any]]) -> float:
    base = _require_mapping(segment.get("base"), f"{path}.base")
    if "unit_factor_to_million_cny" in base:
        return _to_float(base["unit_factor_to_million_cny"])
    if "unit_factor_to_million_cny" in segment:
        return _to_float(segment["unit_factor_to_million_cny"])
    text = "\n".join(str(part) for part in [segment.get("note", ""), inherited_note] if part)
    inferred = _infer_unit_factor_from_text(text, warnings, path)
    if inferred is not None:
        return inferred
    raise Yaml1CleanError(f"{path} missing structured unit_factor_to_million_cny")


def fold_revenue(yaml1: dict[str, Any], clean_annual: dict[int, dict[str, float]]) -> FoldResult:
    revenue_node = _require_mapping(yaml1.get("income.revenue"), "income.revenue")
    if revenue_node.get("kind") != "decomposition":
        raise Yaml1CleanError("income.revenue must be kind=decomposition")
    explicit_horizon = [int(year) for year in yaml1.get("meta", {}).get("horizon", [])]
    if not explicit_horizon:
        raise Yaml1CleanError("meta.horizon is required")

    base_year = _detect_base_year(revenue_node, explicit_horizon)
    if base_year not in clean_annual:
        raise Yaml1CleanError(f"clean_annual missing base year {base_year}")
    base_revenue = clean_annual[base_year].get("revenue", 0.0)
    if abs(base_revenue) < 1e-12:
        raise Yaml1CleanError(f"clean_annual revenue is zero for {base_year}")

    warnings: list[dict[str, Any]] = []
    segments = _require_mapping(revenue_node.get("segments"), "income.revenue.segments")
    segment_base_revenue: dict[str, float] = {}
    segment_revenue_by_year: dict[str, dict[int, float]] = {}
    unit_factors: dict[str, float] = {}
    revenue_by_year = {year: 0.0 for year in explicit_horizon}

    for name, segment_any in segments.items():
        path = f"income.revenue.segments.{name}"
        segment = _require_mapping(segment_any, path)
        family = segment.get("revenue_family")
        factor = _unit_factor(segment, str(revenue_node.get("note", "")), path, warnings)
        unit_factors[str(name)] = factor
        base = _require_mapping(segment.get("base"), f"{path}.base")
        series: dict[int, float] = {}

        if family == "vol_price":
            volume = _to_float(base.get("volume"))
            price = _to_float(base.get("price"))
            segment_base_revenue[str(name)] = volume * price / factor
            knobs = _require_mapping(segment.get("knobs"), f"{path}.knobs")
            volume_yoy = _year_values(knobs.get("volume_yoy"), explicit_horizon, f"{path}.knobs.volume_yoy")
            price_yoy = _year_values(knobs.get("price_yoy"), explicit_horizon, f"{path}.knobs.price_yoy")
            for idx, year in enumerate(explicit_horizon):
                volume *= 1.0 + volume_yoy[idx]
                price *= 1.0 + price_yoy[idx]
                series[year] = volume * price / factor
        elif family == "growth":
            revenue = _to_float(base.get("revenue"))
            segment_base_revenue[str(name)] = revenue / factor
            knobs = _require_mapping(segment.get("knobs"), f"{path}.knobs")
            revenue_yoy = _year_values(knobs.get("revenue_yoy"), explicit_horizon, f"{path}.knobs.revenue_yoy")
            for idx, year in enumerate(explicit_horizon):
                revenue *= 1.0 + revenue_yoy[idx]
                series[year] = revenue / factor
        else:
            raise Yaml1CleanError(f"Unsupported revenue_family at {path}: {family}")

        segment_revenue_by_year[str(name)] = series
        for year, value in series.items():
            revenue_by_year[year] += value

    yoy: list[float] = []
    prev = base_revenue
    for year in explicit_horizon:
        revenue = revenue_by_year[year]
        yoy.append(revenue / prev - 1.0)
        prev = revenue

    return FoldResult(
        base_year=base_year,
        explicit_horizon=explicit_horizon,
        base_revenue=base_revenue,
        revenue_by_year=revenue_by_year,
        revenue_yoy=yoy,
        segment_base_revenue=segment_base_revenue,
        segment_revenue_by_year=segment_revenue_by_year,
        unit_factors=unit_factors,
        warnings=warnings,
    )


def _detect_base_year(revenue_node: dict[str, Any], explicit_horizon: list[int]) -> int:
    years: set[int] = set()
    for segment in _require_mapping(revenue_node.get("segments"), "income.revenue.segments").values():
        if isinstance(segment, dict):
            base = segment.get("base", {})
            if isinstance(base, dict) and "base_year" in base:
                years.add(int(base["base_year"]))
    if len(years) > 1:
        raise Yaml1CleanError(f"Inconsistent segment base_year values: {sorted(years)}")
    if years:
        return years.pop()
    return min(explicit_horizon) - 1


def _year_values(values: Any, horizon: list[int], path: str) -> list[float]:
    values = plain_value(values)
    if not isinstance(values, list):
        raise Yaml1CleanError(f"{path} must be a list")
    if len(values) != len(horizon):
        raise Yaml1CleanError(f"{path} length {len(values)} != horizon length {len(horizon)}")
    return [_to_float(value) for value in values]


def _empty_fold_from_yaml2(yaml2: dict[str, Any]) -> FoldResult:
    """Build a degenerate FoldResult for a defaults-only (no yaml1) clean pass.

    The horizon is taken from YAML2's ``base_period`` + ``model.forecast_years``.
    ``model.revenue_yoy`` is broadcast from its scalar default so the same
    resolve/validate pipeline can be used unchanged.
    """
    base_period = str(_path_get(yaml2, "base_period"))
    base_year = int(base_period[:4])
    years = int(_to_float(_path_get(yaml2, "model.forecast_years")))
    explicit_horizon = list(range(base_year + 1, base_year + 1 + years))
    base_revenue = _to_float(_path_get(yaml2, "income.revenue"))
    revenue_yoy = [_to_float(_path_get(yaml2, "model.revenue_yoy"))] * years
    return FoldResult(
        base_year=base_year,
        explicit_horizon=explicit_horizon,
        base_revenue=base_revenue,
        revenue_by_year={},
        revenue_yoy=revenue_yoy,
        segment_base_revenue={},
        segment_revenue_by_year={},
        unit_factors={},
        warnings=[
            {
                "stage": "defaults_only",
                "message": "No yaml1 provided; using YAML2 baseline as identity clean pass.",
            }
        ],
    )


def _empty_terminal_from_yaml2(yaml2: dict[str, Any], explicit_horizon: list[int]) -> dict[str, Any]:
    """Return a terminal block with no fade for a defaults-only run."""
    explicit_end = explicit_horizon[-1]
    return {
        "explicit_end": explicit_end,
        "fade": {"kind": "linear", "fade_paths": [], "hold_paths": [], "to_year": explicit_end},
        "perpetual_growth": _to_float(_path_get(yaml2, "model.terminal_growth")),
    }


def clean_yaml1(
    yaml1_path: str | Path | None,
    defaults_path: str | Path,
    clean_annual_path: str | Path,
) -> CleanResult:
    yaml2 = read_yaml2(defaults_path)
    clean_annual = load_clean_annual(clean_annual_path)

    if yaml1_path is None:
        yaml1: dict[str, Any] = {}
        fold = _empty_fold_from_yaml2(yaml2)
        defaults_only = True
    else:
        yaml1 = load_yaml(yaml1_path)
        fold = fold_revenue(yaml1, clean_annual)
        defaults_only = False

    report = _initial_report(
        str(yaml1_path) if yaml1_path else "<defaults-only>",
        defaults_path,
        clean_annual_path,
        fold,
    )
    report["defaults_only"] = defaults_only
    report["warnings"].extend(fold.warnings)

    overlay = _collect_explicit_overlay(yaml1, fold, report)
    terminal = yaml1.get("terminal") if yaml1 else _empty_terminal_from_yaml2(yaml2, fold.explicit_horizon)
    full_horizon = _full_horizon(terminal, fold.explicit_horizon)
    expanded = _expand_overlay(overlay, terminal, fold.explicit_horizon, full_horizon, report)
    forecast_params, yearly_paths = _resolve_yaml2_yearly(yaml2, expanded, len(full_horizon))
    forecast_params.setdefault("meta", {})["horizon"] = full_horizon
    report["yearly_paths"] = yearly_paths

    if defaults_only:
        _collect_sign_warnings(clean_annual, report)
        backtest = {"status": "skipped", "reason": "defaults_only"}
    else:
        backtest = _run_backtests(yaml1, clean_annual, fold, report)
    report["backtest"] = backtest
    if not defaults_only:
        _add_growth_diagnostics(fold, yaml1, report)
    validate_yaml2_yearly(forecast_params, yearly_paths, report)
    if report["errors"]:
        first = report["errors"][0]
        raise Yaml1CleanError(first["message"])
    return CleanResult(forecast_params=forecast_params, report=report)


def _initial_report(
    yaml1_path: str | Path,
    defaults_path: str | Path,
    clean_annual_path: str | Path,
    fold: FoldResult,
) -> dict[str, Any]:
    return {
        "yaml1_path": str(yaml1_path),
        "defaults_path": str(defaults_path),
        "clean_annual_path": str(clean_annual_path),
        "base_year": fold.base_year,
        "explicit_horizon": fold.explicit_horizon,
        "unit_factors": fold.unit_factors,
        "fold": {
            "base_revenue": fold.base_revenue,
            "segment_base_revenue": fold.segment_base_revenue,
            "revenue_by_year": {str(k): v for k, v in fold.revenue_by_year.items()},
            "revenue_yoy": fold.revenue_yoy,
        },
        "warnings": [],
        "errors": [],
    }


def _collect_explicit_overlay(
    yaml1: dict[str, Any],
    fold: FoldResult,
    report: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    defaults_only = not yaml1
    revenue_node = yaml1.get("income.revenue") if yaml1 else {}
    overlay: dict[str, dict[str, Any]] = {
        MODEL_REVENUE_YOY: {
            "values": fold.revenue_yoy,
            "source": (
                "yaml2.baseline"
                if defaults_only
                else (revenue_node.get("src") if isinstance(revenue_node, dict) else None)
                or "yaml1.income.revenue"
            ),
            "note": (
                "Broadcast from YAML2 baseline (no yaml1 decomposition)."
                if defaults_only
                else "Folded from yaml1 income.revenue decomposition."
            ),
        }
    }
    horizon = fold.explicit_horizon
    for path, item_any in yaml1.items():
        if path in {"meta", "income.revenue", "terminal", "stash"}:
            continue
        item = _require_mapping(item_any, path)
        kind = item.get("kind")
        if kind != "knob":
            raise Yaml1CleanError(f"Unsupported yaml1 item kind at {path}: {kind}")
        overlay[path] = {
            "values": _year_values(item.get("values"), horizon, f"{path}.values"),
            "source": item.get("src", f"yaml1.{path}"),
        }
    return overlay


def _full_horizon(terminal: dict[str, Any], explicit_horizon: list[int]) -> list[int]:
    fade = _require_mapping(terminal.get("fade"), "terminal.fade")
    explicit_end = int(terminal.get("explicit_end"))
    to_year = int(fade.get("to_year"))
    if explicit_end != explicit_horizon[-1]:
        raise Yaml1CleanError("terminal.explicit_end must equal the last explicit horizon year")
    if to_year < explicit_end:
        raise Yaml1CleanError("terminal.fade.to_year must not be less than explicit_end")
    return list(range(explicit_horizon[0], to_year + 1))


def _canonical_fade_path(path: str, report: dict[str, Any]) -> str:
    if path in REVENUE_ALIASES:
        if path != MODEL_REVENUE_YOY:
            report["warnings"].append(
                {
                    "stage": "expand",
                    "path": path,
                    "message": f"fade path alias {path} normalized to {MODEL_REVENUE_YOY}",
                }
            )
        return MODEL_REVENUE_YOY
    return path


def _expand_overlay(
    overlay: dict[str, dict[str, Any]],
    terminal: dict[str, Any],
    explicit_horizon: list[int],
    full_horizon: list[int],
    report: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    fade = _require_mapping(terminal.get("fade"), "terminal.fade")
    if fade.get("kind") != "linear":
        raise Yaml1CleanError(f"Unsupported fade kind: {fade.get('kind')}")
    terminal_growth = _to_float(terminal.get("perpetual_growth"))
    fade_paths = {_canonical_fade_path(str(path), report) for path in fade.get("fade_paths", [])}
    hold_paths = {_canonical_fade_path(str(path), report) for path in fade.get("hold_paths", [])}
    extra_years = len(full_horizon) - len(explicit_horizon)
    if extra_years <= 0:
        return overlay

    expanded: dict[str, dict[str, Any]] = {}
    for path, item in overlay.items():
        values = list(item["values"])
        last = _to_float(values[-1])
        if path in fade_paths:
            tail = [
                last + (terminal_growth - last) * step / extra_years
                for step in range(1, extra_years + 1)
            ]
        else:
            tail = [last] * extra_years
        expanded[path] = {**item, "values": values + tail}

    for path in fade_paths | hold_paths:
        if path not in expanded:
            raise Yaml1CleanError(f"terminal fade/hold path does not exist in overlay: {path}")
    return expanded


def _resolve_yaml2_yearly(
    yaml2: dict[str, Any],
    overlay: dict[str, dict[str, Any]],
    horizon_len: int,
) -> tuple[dict[str, Any], list[str]]:
    out = copy.deepcopy(yaml2)
    _set_path(out, "model.forecast_years", _existing_param_with_value(_path_get(out, "model.forecast_years"), horizon_len))
    yearly_paths = set(_default_yearly_paths(yaml2))

    for path, item in overlay.items():
        if not _path_exists(yaml2, path) and path != MODEL_REVENUE_YOY:
            raise Yaml1CleanError(f"yaml1 path has no matching yaml2 path: {path}")
        node = _path_get(out, path)
        source = str(item.get("source", f"yaml1.{path}"))
        value = list(item["values"])
        if isinstance(node, dict) and "value" in node:
            replacement = copy.deepcopy(node)
            replacement["value"] = value
            replacement["source"] = source
            if item.get("note"):
                replacement["note"] = item["note"]
        else:
            replacement = _param(value, source, item.get("note"))
        _set_path(out, path, replacement)
        yearly_paths.add(path)

    for path in sorted(yearly_paths):
        node = _path_get(out, path)
        if node is None:
            continue
        value = plain_value(node)
        if isinstance(value, list):
            continue
        broadcast = [value for _ in range(horizon_len)]
        _set_path(out, path, _existing_param_with_value(node, broadcast))
    return out, sorted(yearly_paths)


def _default_yearly_paths(yaml2: dict[str, Any]) -> list[str]:
    paths = [MODEL_REVENUE_YOY]
    income = yaml2.get("income", {})
    if isinstance(income, dict):
        for section in [
            "revenue_items_abs",
            "cost_rates",
            "cost_abs",
            "operating_adjustments_abs",
            "below_line_abs",
        ]:
            mapping = income.get(section)
            if isinstance(mapping, dict):
                paths.extend(f"income.{section}.{field}" for field in mapping)
        paths.extend(["income.gpm", "income.effective_tax_rate", "income.minority_ratio"])
        fin = income.get("financial_expense")
        if isinstance(fin, dict):
            paths.extend(
                f"income.financial_expense.{field}"
                for field in FINANCIAL_EXPENSE_NUMERIC_KEYS
                if field in fin
            )
    bs = yaml2.get("balance_sheet", {})
    if isinstance(bs, dict):
        for section in ["revenue_pct", "cogs_days"]:
            mapping = bs.get(section)
            if isinstance(mapping, dict):
                paths.extend(f"balance_sheet.{section}.{field}" for field in mapping)
        paths.extend(f"balance_sheet.{field}" for field in BS_YEARLY_SCALAR_KEYS if field in bs)
    return sorted(set(paths))


def _run_backtests(
    yaml1: dict[str, Any],
    clean_annual: dict[int, dict[str, float]],
    fold: FoldResult,
    report: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    segment_sum = sum(fold.segment_base_revenue.values())
    anchor_residual = segment_sum - fold.base_revenue
    if abs(anchor_residual) >= TOLERANCE_MILLION_CNY:
        errors.append(
            {
                "stage": "backtest",
                "path": "income.revenue",
                "year": fold.base_year,
                "message": "四线 base 加总未复现 clean_annual revenue",
                "expected": fold.base_revenue,
                "actual": segment_sum,
                "residual": anchor_residual,
            }
        )

    _backtest_stash_history(yaml1, clean_annual, report, errors)
    _collect_sign_warnings(clean_annual, report)
    report["errors"].extend(errors)
    return {
        "status": "failed" if errors else "passed",
        "anchor": {
            "year": fold.base_year,
            "clean_revenue": fold.base_revenue,
            "segment_sum": segment_sum,
            "residual": abs(anchor_residual),
        },
        "errors": errors,
    }


def _backtest_stash_history(
    yaml1: dict[str, Any],
    clean_annual: dict[int, dict[str, float]],
    report: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    stash = yaml1.get("stash", {})
    if not isinstance(stash, dict):
        return
    history = stash.get("分线历史_收入销量吨价")
    if not isinstance(history, dict):
        return
    labels = ["低温鲜奶", "低温酸奶", "常温", "边缘业务"]
    checked: list[int] = []
    skipped: list[int] = []
    for year, row in sorted(clean_annual.items()):
        total = 0.0
        ok = True
        for label in labels:
            block = history.get(label)
            if not isinstance(block, dict) or not isinstance(block.get("收入"), dict):
                ok = False
                break
            value = block["收入"].get(year)
            if value is None:
                ok = False
                break
            total += _to_float(value)
        if not ok:
            skipped.append(year)
            continue
        residual = total - row.get("revenue", 0.0)
        checked.append(year)
        if abs(residual) >= TOLERANCE_MILLION_CNY:
            errors.append(
                {
                    "stage": "backtest",
                    "path": "stash.分线历史_收入销量吨价",
                    "year": year,
                    "message": "stash 分线历史收入加总未复现 clean_annual revenue",
                    "expected": row.get("revenue", 0.0),
                    "actual": total,
                    "residual": residual,
                }
            )
    report.setdefault("backtest_detail", {})["historical_revenue"] = {
        "checked_years": checked,
        "skipped_years": skipped,
    }


def _collect_sign_warnings(clean_annual: dict[int, dict[str, float]], report: dict[str, Any]) -> None:
    for year, row in sorted(clean_annual.items()):
        income_row = dict(row)
        if "income.credit_impa_loss" in income_row:
            income_row["credit_impa_loss"] = income_row["income.credit_impa_loss"]
        present = {field for field, value in income_row.items() if abs(_to_float(value)) > 1e-9}
        _, warnings = resolve_is_signs(income_row, present, str(year))
        for message in warnings:
            report["warnings"].append(
                {
                    "stage": "backtest",
                    "path": "income.signs",
                    "year": year,
                    "message": message,
                }
            )


def _add_growth_diagnostics(fold: FoldResult, yaml1: dict[str, Any], report: dict[str, Any]) -> None:
    terminal_growth = _to_float(yaml1.get("terminal", {}).get("perpetual_growth"))
    first = fold.revenue_by_year[fold.explicit_horizon[0]]
    last = fold.revenue_by_year[fold.explicit_horizon[-1]]
    years = len(fold.explicit_horizon) - 1
    if first > 0 and years > 0:
        cagr = (last / first) ** (1.0 / years) - 1.0
        report["fold"]["explicit_revenue_cagr"] = cagr
        if cagr + 1e-12 < terminal_growth:
            report["warnings"].append(
                {
                    "stage": "diagnostic",
                    "path": "model.revenue_yoy",
                    "message": "总增速低于永续,与成长假设张力大,请核对收缩线(常温)假设",
                    "value": cagr,
                    "terminal_growth": terminal_growth,
                }
            )
    if fold.revenue_yoy[-1] + 1e-12 < terminal_growth:
        report["warnings"].append(
            {
                "stage": "diagnostic",
                "path": "model.revenue_yoy",
                "message": "末年增速<永续,fade 段反向,意义弱化",
                "value": fold.revenue_yoy[-1],
                "terminal_growth": terminal_growth,
            }
        )


def validate_yaml2_yearly(
    yaml2_yearly: dict[str, Any],
    yearly_paths: list[str],
    report: dict[str, Any] | None = None,
) -> None:
    years = int(_to_float(_path_get(yaml2_yearly, "model.forecast_years")))
    errors: list[dict[str, Any]] = []
    for path in yearly_paths:
        value = plain_value(_path_get(yaml2_yearly, path))
        if not isinstance(value, list) or len(value) != years:
            errors.append(
                {
                    "stage": "validate",
                    "path": path,
                    "message": f"yearly path must be list length {years}",
                    "actual_length": len(value) if isinstance(value, list) else None,
                }
            )
    if report is not None:
        report["errors"].extend(errors)
    if errors and report is None:
        raise Yaml1CleanError(errors[0]["message"])


def broadcast_yaml2_defaults(yaml2: dict[str, Any]) -> dict[str, Any]:
    """Return a yearly-shaped YAML2 object that preserves scalar-flat behavior."""
    years = int(_to_float(_path_get(yaml2, "model.forecast_years")))
    yearly, _ = _resolve_yaml2_yearly(yaml2, {}, years)
    return yearly


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_hidden(path: str | Path) -> None:
    if not hasattr(ctypes, "windll"):
        return
    path = Path(path)
    if not path.exists():
        return
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | 0x02)
    except OSError:
        return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean yaml1 into forecast parameters.")
    parser.add_argument("--yaml1", help="Path to yaml1; defaults to latest company yaml1*.yaml")
    parser.add_argument("--defaults", help="Path to defaults.yaml")
    parser.add_argument("--clean-annual", help="Path to clean_annual data source; defaults to company/data.db")
    parser.add_argument("--ticker", help="Ticker used to infer paths")
    parser.add_argument("--output", help="Output forecast_params.yaml path")
    parser.add_argument("--report", help="Output report JSON path")
    parser.add_argument(
        "--defaults-only",
        action="store_true",
        help="Do not require yaml1; run an identity clean pass over YAML2 defaults only",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.defaults_only and args.yaml1:
        raise SystemExit("--defaults-only and --yaml1 are mutually exclusive")
    if args.ticker:
        company_dir = find_company_dir(args.ticker)
    elif args.yaml1:
        company_dir = Path(args.yaml1).resolve().parent
    elif args.defaults:
        company_dir = Path(args.defaults).resolve().parent
    else:
        raise SystemExit("--ticker, --yaml1, or --defaults is required")

    yaml1_path = None if args.defaults_only else (Path(args.yaml1) if args.yaml1 else default_yaml1_path(company_dir))
    defaults_path = Path(args.defaults) if args.defaults else company_dir / "defaults.yaml"
    clean_annual_path = Path(args.clean_annual) if args.clean_annual else company_dir / "data.db"
    internal_dir = company_dir / ".modelking"
    output_path = Path(args.output) if args.output else internal_dir / "forecast_params.yaml"
    report_path = Path(args.report) if args.report else internal_dir / "yaml1_clean_report.json"

    result = clean_yaml1(yaml1_path, defaults_path, clean_annual_path)
    write_yaml2(output_path, result.forecast_params)
    write_json(report_path, result.report)
    if output_path.parent == internal_dir or report_path.parent == internal_dir:
        mark_hidden(internal_dir)
    print(f"Written forecast params: {output_path}")
    print(f"Written yaml1 clean report: {report_path}")
    if result.report["warnings"]:
        print(f"Warnings: {len(result.report['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
