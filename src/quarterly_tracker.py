"""Quarterly tracking layer calculation helpers.

The module starts small: override persistence plus the first amount-anchor
quarterly allocation primitives. Higher-level view assembly builds on these
helpers in later tasks.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Mapping

EPSILON = 1e-9
STATIC_UPDATED_AT = "1970-01-01T00:00:00"


def _db_path(db: str | Path) -> str:
    return str(Path(db))


def init_overrides_table(db: str | Path) -> None:
    """Create the quarterly override table if it does not already exist."""
    with sqlite3.connect(_db_path(db)) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS quarterly_overrides (
              ticker       TEXT NOT NULL,
              period       TEXT NOT NULL,
              param        TEXT NOT NULL,
              value        REAL NOT NULL,
              locked_field TEXT,
              locked_value REAL,
              updated_at   TEXT NOT NULL,
              note         TEXT,
              PRIMARY KEY (ticker, period, param)
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_quarterly_overrides_locked
            ON quarterly_overrides (ticker, period, locked_field)
            """
        )


def set_override(
    db: str | Path,
    ticker: str,
    period: str,
    param: str,
    value: float,
    *,
    locked_field: str | None = None,
    locked_value: float | None = None,
    note: str | None = None,
    updated_at: str | None = None,
) -> None:
    """Insert or update one manual override.

    If a new input locks the same accounting field as an older input in the
    same quarter, the older row is removed so calculation sees one amount.
    """
    init_overrides_table(db)
    timestamp = updated_at or STATIC_UPDATED_AT
    with sqlite3.connect(_db_path(db)) as con:
        con.execute("BEGIN")
        if locked_field is not None:
            con.execute(
                """
                DELETE FROM quarterly_overrides
                WHERE ticker = ? AND period = ? AND locked_field = ? AND param <> ?
                """,
                (ticker, period, locked_field, param),
            )
        con.execute(
            """
            INSERT INTO quarterly_overrides
                (ticker, period, param, value, locked_field, locked_value, updated_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, period, param) DO UPDATE SET
                value = excluded.value,
                locked_field = excluded.locked_field,
                locked_value = excluded.locked_value,
                updated_at = excluded.updated_at,
                note = excluded.note
            """,
            (ticker, period, param, value, locked_field, locked_value, timestamp, note),
        )


def clear_override(
    db: str | Path,
    ticker: str,
    period: str,
    *,
    param: str | None = None,
) -> None:
    """Clear all overrides for a quarter, or one specific input parameter."""
    init_overrides_table(db)
    with sqlite3.connect(_db_path(db)) as con:
        if param is None:
            con.execute(
                "DELETE FROM quarterly_overrides WHERE ticker = ? AND period = ?",
                (ticker, period),
            )
        else:
            con.execute(
                """
                DELETE FROM quarterly_overrides
                WHERE ticker = ? AND period = ? AND param = ?
                """,
                (ticker, period, param),
            )


def load_overrides(db: str | Path, ticker: str) -> dict[str, dict[str, object]]:
    """Load overrides grouped by period, including a `_locked` amount map."""
    init_overrides_table(db)
    with sqlite3.connect(_db_path(db)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT period, param, value, locked_field, locked_value, updated_at, note
            FROM quarterly_overrides
            WHERE ticker = ?
            ORDER BY period, param
            """,
            (ticker,),
        ).fetchall()

    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        period = row["period"]
        bucket = grouped.setdefault(period, {"_locked": {}})
        bucket[row["param"]] = float(row["value"])
        locked_field = row["locked_field"]
        if locked_field is not None and row["locked_value"] is not None:
            locked = bucket["_locked"]
            if isinstance(locked, dict):
                locked[locked_field] = float(row["locked_value"])
    return grouped


def prior_same_quarter(
    quarterly_by_year: Mapping[int, Mapping[int, float | int | None]],
    *,
    year: int,
    q: int,
) -> float | None:
    """Return the nearest previous non-zero value for the same quarter."""
    for candidate_year in sorted((y for y in quarterly_by_year if y < year), reverse=True):
        value = quarterly_by_year[candidate_year].get(q)
        if value is None:
            continue
        value_float = float(value)
        if abs(value_float) <= EPSILON:
            continue
        return value_float
    return None


def _state_for(states: Mapping[int, str], q: int) -> str:
    if q == 4:
        return "q4"
    return states.get(q, "inherit")


def _inherit_amount(annual: float, prior_annual: float, prior_value: float | None) -> float:
    if prior_value is None or abs(prior_annual) <= EPSILON:
        return annual / 4.0
    return annual * prior_value / prior_annual


def _override_for(override_yoy: Mapping[int, float] | float | None, q: int) -> float | None:
    if override_yoy is None:
        return None
    if isinstance(override_yoy, Mapping):
        value = override_yoy.get(q)
        return None if value is None else float(value)
    return float(override_yoy)


def _amount_quarters(
    *,
    annual: float,
    prior_annual: float,
    prior_quarterly: Mapping[int, float | int | None],
    states: Mapping[int, str],
    actuals: Mapping[int, float | int],
    manual_amounts: Mapping[int, float] | float | None = None,
) -> dict[int, float]:
    out: dict[int, float] = {}
    annual_float = float(annual)
    prior_annual_float = float(prior_annual)

    for q in (1, 2, 3):
        state = _state_for(states, q)
        if state == "actual" and q in actuals:
            out[q] = float(actuals[q])
            continue

        manual_amount = _override_for(manual_amounts, q)
        if state == "manual" and manual_amount is not None:
            out[q] = manual_amount
            continue

        prior_value_raw = prior_quarterly.get(q)
        prior_value = None if prior_value_raw is None else float(prior_value_raw)
        out[q] = _inherit_amount(annual_float, prior_annual_float, prior_value)

    out[4] = annual_float - sum(out[q] for q in (1, 2, 3))
    return out


def compute_revenue_quarters(
    *,
    annual: float,
    prior_annual: float,
    prior_quarterly: Mapping[int, float | int | None],
    states: Mapping[int, str],
    actuals: Mapping[int, float | int],
    override_yoy: Mapping[int, float] | float | None = None,
    override_amount: Mapping[int, float] | float | None = None,
) -> dict[int, float]:
    """Allocate annual revenue to quarters with Q4 as the residual."""
    out: dict[int, float] = {}
    annual_float = float(annual)
    prior_annual_float = float(prior_annual)

    for q in (1, 2, 3):
        state = _state_for(states, q)
        if state == "actual" and q in actuals:
            out[q] = float(actuals[q])
            continue

        manual_amount = _override_for(override_amount, q)
        if state == "manual" and manual_amount is not None:
            out[q] = manual_amount
            continue

        yoy = _override_for(override_yoy, q)
        prior_value_raw = prior_quarterly.get(q)
        prior_value = None if prior_value_raw is None else float(prior_value_raw)
        if state == "manual" and yoy is not None and prior_value is not None:
            out[q] = prior_value * (1.0 + yoy)
            continue

        out[q] = _inherit_amount(annual_float, prior_annual_float, prior_value)

    out[4] = annual_float - sum(out[q] for q in (1, 2, 3))
    return out


def compute_expense_amount_quarters(
    *,
    annual: float,
    prior_annual: float,
    prior_quarterly: Mapping[int, float | int | None],
    revenue_quarters: Mapping[int, float | int],
    states: Mapping[int, str],
    actuals: Mapping[int, float | int],
    override_rate: Mapping[int, float] | float | None = None,
    override_amount: Mapping[int, float] | float | None = None,
) -> dict[int, float]:
    """Allocate an annual expense amount, deriving rates only for display."""
    manual_amounts: dict[int, float] = {}
    for q in (1, 2, 3):
        amount = _override_for(override_amount, q)
        if amount is not None:
            manual_amounts[q] = amount
            continue
        rate = _override_for(override_rate, q)
        if rate is not None:
            manual_amounts[q] = float(revenue_quarters.get(q, 0.0)) * rate

    return _amount_quarters(
        annual=annual,
        prior_annual=prior_annual,
        prior_quarterly=prior_quarterly,
        states=states,
        actuals=actuals,
        manual_amounts=manual_amounts,
    )


def compute_gross_profit_quarters(
    *,
    annual_gross_profit: float,
    prior_annual_gross_profit: float,
    prior_quarterly_gross_profit: Mapping[int, float | int | None],
    revenue_quarters: Mapping[int, float | int],
    states: Mapping[int, str],
    actuals_gross_profit: Mapping[int, float | int],
    override_gpm: Mapping[int, float] | float | None = None,
    override_gross_profit: Mapping[int, float] | float | None = None,
) -> dict[str, dict[int, float]]:
    """Allocate annual gross profit amount and derive cost/GPM per quarter."""
    manual_amounts: dict[int, float] = {}
    for q in (1, 2, 3):
        amount = _override_for(override_gross_profit, q)
        if amount is not None:
            manual_amounts[q] = amount
            continue
        gpm = _override_for(override_gpm, q)
        if gpm is not None:
            manual_amounts[q] = float(revenue_quarters.get(q, 0.0)) * gpm

    gross_profit = _amount_quarters(
        annual=annual_gross_profit,
        prior_annual=prior_annual_gross_profit,
        prior_quarterly=prior_quarterly_gross_profit,
        states=states,
        actuals=actuals_gross_profit,
        manual_amounts=manual_amounts,
    )
    oper_cost = {
        q: float(revenue_quarters.get(q, 0.0)) - gross_profit[q]
        for q in (1, 2, 3, 4)
    }
    gpm = {
        q: (gross_profit[q] / float(revenue_quarters.get(q, 0.0)))
        if abs(float(revenue_quarters.get(q, 0.0))) > EPSILON else 0.0
        for q in (1, 2, 3, 4)
    }
    return {"gross_profit": gross_profit, "oper_cost": oper_cost, "gpm": gpm}


def _has_mixed_sign(values: list[float]) -> bool:
    positives = any(v > EPSILON for v in values)
    negatives = any(v < -EPSILON for v in values)
    return positives and negatives


def _abs_weight_value(
    annual: float,
    q: int,
    abs_weight_history: Mapping[int, Mapping[int, float | int | None]] | None,
) -> float | None:
    if not abs_weight_history:
        return None
    weights: dict[int, float] = {quarter: 0.0 for quarter in (1, 2, 3, 4)}
    for quarters in abs_weight_history.values():
        for quarter in (1, 2, 3, 4):
            value = quarters.get(quarter)
            if value is not None:
                weights[quarter] += abs(float(value))
    total_weight = sum(weights.values())
    if total_weight <= EPSILON:
        return None
    return annual * weights[q] / total_weight


def compute_seasonal_amount_quarters(
    *,
    annual: float,
    prior_annual: float,
    prior_quarterly: Mapping[int, float | int | None],
    states: Mapping[int, str],
    actuals: Mapping[int, float | int],
    override_amount: Mapping[int, float] | float | None = None,
    abs_weight_history: Mapping[int, Mapping[int, float | int | None]] | None = None,
) -> dict[int, float]:
    """Allocate a seasonal amount item such as tax, finance cost, or loss."""
    prior_values = [
        float(value)
        for value in prior_quarterly.values()
        if value is not None and abs(float(value)) > EPSILON
    ]
    use_abs_weights = abs(float(prior_annual)) <= EPSILON or _has_mixed_sign(prior_values)

    if use_abs_weights:
        adjusted_prior: dict[int, float] = {}
        for q in (1, 2, 3, 4):
            weighted = _abs_weight_value(float(annual), q, abs_weight_history)
            if weighted is not None:
                adjusted_prior[q] = weighted
        if adjusted_prior:
            return _amount_quarters(
                annual=annual,
                prior_annual=annual,
                prior_quarterly=adjusted_prior,
                states=states,
                actuals=actuals,
                manual_amounts=override_amount,
            )

    return _amount_quarters(
        annual=annual,
        prior_annual=prior_annual,
        prior_quarterly=prior_quarterly,
        states=states,
        actuals=actuals,
        manual_amounts=override_amount,
    )


def derive_subtotals(leaves: Mapping[str, float | int | None]) -> dict[str, float]:
    """Derive income statement subtotals using clean.py bucket definitions."""
    from .clean import is_bucket_sum

    row = {
        field: (0.0 if value is None else float(value))
        for field, value in leaves.items()
    }
    present = {field for field, value in row.items() if value is not None}

    total_revenue = is_bucket_sum("revenue_item", row, present)
    total_cogs = is_bucket_sum("cost_item", row, present)
    operating_adjustment = is_bucket_sum("operating_adjustment", row, present)
    operate_profit = total_revenue - total_cogs + operating_adjustment
    total_profit = operate_profit + row.get("non_oper_income", 0.0) - row.get("non_oper_exp", 0.0)
    n_income = total_profit - row.get("income_tax", 0.0)
    n_income_attr_p = n_income - row.get("minority_gain", 0.0)

    return {
        "total_revenue": total_revenue,
        "total_cogs": total_cogs,
        "total_opcost": total_cogs - row.get("fin_exp", 0.0),
        "operate_profit": operate_profit,
        "total_profit": total_profit,
        "n_income": n_income,
        "n_income_attr_p": n_income_attr_p,
    }


EXPENSE_AMOUNT_FIELDS = {
    "biz_tax_surchg",
    "sell_exp",
    "admin_exp",
    "rd_exp",
    "other_bus_cost",
}

EXCLUDED_ROW_CATEGORIES = {"derived", "comprehensive", "sub_item"}


def _to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_forecast_is(company_dir: Path) -> list[dict[str, float]]:
    path = company_dir / "Agent" / "forecast" / "forecast_is.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows: list[dict[str, float]] = []
        for raw in csv.DictReader(fh):
            row: dict[str, float] = {"period": int(_to_float(raw.get("period")))}
            for key, value in raw.items():
                if key != "period":
                    row[key] = _to_float(value)
            rows.append(row)
    return rows


def _fetch_rows_by_period(db: str | Path, table: str) -> dict[str, dict[str, float]]:
    with sqlite3.connect(_db_path(db)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(f"SELECT * FROM {table}").fetchall()
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        period = str(row["period"])
        out[period] = {
            key: _to_float(row[key])
            for key in row.keys()
            if key != "period"
        }
    return out


def _field_history(
    quarterly_rows: Mapping[str, Mapping[str, float]],
    field: str,
) -> dict[int, dict[int, float]]:
    history: dict[int, dict[int, float]] = {}
    for period, row in quarterly_rows.items():
        if "Q" not in period:
            continue
        year_text, q_text = period.split("Q", 1)
        try:
            year = int(year_text)
            q = int(q_text)
        except ValueError:
            continue
        history.setdefault(year, {})[q] = _to_float(row.get(field))
    return history


def _prior_quarters(
    quarterly_rows: Mapping[str, Mapping[str, float]],
    *,
    field: str,
    year: int,
) -> dict[int, float | None]:
    history = _field_history(quarterly_rows, field)
    return {
        q: prior_same_quarter(history, year=year, q=q)
        for q in (1, 2, 3, 4)
    }


def _clean_annual_value(
    annual_rows: Mapping[str, Mapping[str, float]],
    *,
    year: int,
    field: str,
) -> float:
    return _to_float(annual_rows.get(str(year), {}).get(field))


def _actuals_for_field(
    quarterly_rows: Mapping[str, Mapping[str, float]],
    *,
    year: int,
    field: str,
) -> dict[int, float]:
    actuals: dict[int, float] = {}
    for q in (1, 2, 3, 4):
        row = quarterly_rows.get(f"{year}Q{q}")
        if row is not None:
            actuals[q] = _to_float(row.get(field))
    return actuals


def _quarter_states(
    *,
    year: int,
    quarterly_rows: Mapping[str, Mapping[str, float]],
    overrides: Mapping[str, dict[str, object]],
) -> dict[int, str]:
    states: dict[int, str] = {}
    for q in (1, 2, 3, 4):
        period = f"{year}Q{q}"
        if period in quarterly_rows:
            states[q] = "actual"
        elif q == 4:
            states[q] = "q4"
        elif period in overrides:
            states[q] = "manual"
        else:
            states[q] = "inherit"
    return states


def _locked_amounts(
    overrides: Mapping[str, dict[str, object]],
    *,
    year: int,
    field: str,
) -> dict[int, float]:
    out: dict[int, float] = {}
    for q in (1, 2, 3):
        period = f"{year}Q{q}"
        locked = overrides.get(period, {}).get("_locked")
        if isinstance(locked, dict) and field in locked:
            out[q] = float(locked[field])
    return out


def _prior_gross_profit_quarters(
    quarterly_rows: Mapping[str, Mapping[str, float]],
    *,
    year: int,
) -> dict[int, float | None]:
    revenue = _field_history(quarterly_rows, "revenue")
    oper_cost = _field_history(quarterly_rows, "oper_cost")
    out: dict[int, float | None] = {}
    for q in (1, 2, 3, 4):
        rev = prior_same_quarter(revenue, year=year, q=q)
        cost = prior_same_quarter(oper_cost, year=year, q=q)
        out[q] = None if rev is None or cost is None else rev - cost
    return out


def _parse_period(period: str) -> tuple[int, int] | None:
    if "Q" not in period:
        return None
    year_text, q_text = period.split("Q", 1)
    try:
        year = int(year_text)
        q = int(q_text)
    except ValueError:
        return None
    if q not in (1, 2, 3, 4):
        return None
    return year, q


def _safe_ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    denom = _to_float(denominator)
    if abs(denom) <= EPSILON:
        return None
    return _to_float(numerator) / denom


def _pct_change(current: float | int | None, previous: float | int | None) -> float | None:
    base = _to_float(previous)
    if abs(base) <= EPSILON:
        return None
    return _to_float(current) / base - 1.0


def compute_quarterly_view(
    *,
    db: str | Path,
    ticker: str,
    company_dir: str | Path,
    year: int | None = None,
) -> dict[str, object]:
    """Compute the four-state quarterly IS tracking view."""
    from .field_registry import get_statement

    company_path = Path(company_dir)
    forecast_rows = _read_forecast_is(company_path)
    if not forecast_rows:
        raise ValueError(f"No forecast_is.csv rows for {company_path}")

    selected_year = int(year or min(int(row["period"]) for row in forecast_rows))
    annual_by_year = {int(row["period"]): row for row in forecast_rows}
    annual = annual_by_year[selected_year]

    quarterly_rows = _fetch_rows_by_period(db, "clean_quarterly")
    annual_rows = _fetch_rows_by_period(db, "clean_annual")
    overrides = load_overrides(db, ticker)
    states = _quarter_states(year=selected_year, quarterly_rows=quarterly_rows, overrides=overrides)

    stmt = get_statement("income")
    quarter_leaves: dict[int, dict[str, float]] = {q: {} for q in (1, 2, 3, 4)}

    revenue = compute_revenue_quarters(
        annual=annual.get("revenue", 0.0),
        prior_annual=_clean_annual_value(annual_rows, year=selected_year - 1, field="revenue"),
        prior_quarterly=_prior_quarters(quarterly_rows, field="revenue", year=selected_year),
        states=states,
        actuals=_actuals_for_field(quarterly_rows, year=selected_year, field="revenue"),
        override_amount=_locked_amounts(overrides, year=selected_year, field="revenue"),
    )
    for q, value in revenue.items():
        quarter_leaves[q]["revenue"] = value

    annual_gp = annual.get("revenue", 0.0) - annual.get("oper_cost", 0.0)
    prior_gp = (
        _clean_annual_value(annual_rows, year=selected_year - 1, field="revenue")
        - _clean_annual_value(annual_rows, year=selected_year - 1, field="oper_cost")
    )
    gross = compute_gross_profit_quarters(
        annual_gross_profit=annual_gp,
        prior_annual_gross_profit=prior_gp,
        prior_quarterly_gross_profit=_prior_gross_profit_quarters(quarterly_rows, year=selected_year),
        revenue_quarters=revenue,
        states=states,
        actuals_gross_profit={
            q: _to_float(row.get("revenue")) - _to_float(row.get("oper_cost"))
            for q in (1, 2, 3, 4)
            if (row := quarterly_rows.get(f"{selected_year}Q{q}")) is not None
        },
        override_gross_profit=_locked_amounts(overrides, year=selected_year, field="gross_profit"),
    )
    for q, value in gross["oper_cost"].items():
        quarter_leaves[q]["oper_cost"] = value

    for field in stmt.field_order:
        category = stmt.field_categories[field]
        if field in quarter_leaves[1] or category in {"subtotal", *EXCLUDED_ROW_CATEGORIES}:
            continue

        actuals = _actuals_for_field(quarterly_rows, year=selected_year, field=field)
        prior_quarterly = _prior_quarters(quarterly_rows, field=field, year=selected_year)
        prior_annual = _clean_annual_value(annual_rows, year=selected_year - 1, field=field)
        locked = _locked_amounts(overrides, year=selected_year, field=field)

        if field in EXPENSE_AMOUNT_FIELDS:
            values = compute_expense_amount_quarters(
                annual=annual.get(field, 0.0),
                prior_annual=prior_annual,
                prior_quarterly=prior_quarterly,
                revenue_quarters=revenue,
                states=states,
                actuals=actuals,
                override_amount=locked,
            )
        else:
            values = compute_seasonal_amount_quarters(
                annual=annual.get(field, 0.0),
                prior_annual=prior_annual,
                prior_quarterly=prior_quarterly,
                states=states,
                actuals=actuals,
                override_amount=locked,
            )
        for q, value in values.items():
            quarter_leaves[q][field] = value

    quarter_values: dict[int, dict[str, float]] = {}
    for q in (1, 2, 3, 4):
        quarter_values[q] = dict(quarter_leaves[q])
        quarter_values[q].update(derive_subtotals(quarter_leaves[q]))

    periods = [
        f"{period_year}Q{q}"
        for period_year in (selected_year - 2, selected_year - 1, selected_year)
        for q in (1, 2, 3, 4)
    ]
    period_states: dict[str, str] = {}
    period_values: dict[str, dict[str, float]] = {}
    for period in periods:
        parsed = _parse_period(period)
        if parsed is None:
            continue
        period_year, q = parsed
        if period_year == selected_year:
            period_values[period] = quarter_values[q]
            period_states[period] = states[q]
            continue
        historical = dict(quarterly_rows.get(period, {}))
        if historical:
            historical.update(derive_subtotals(historical))
        period_values[period] = historical
        period_states[period] = "actual" if period in quarterly_rows else "inherit"

    def value_for_period(period: str, field: str) -> float:
        if period in period_values and field in period_values[period]:
            return _to_float(period_values[period].get(field))
        raw = quarterly_rows.get(period)
        if not raw:
            return 0.0
        if field in raw:
            return _to_float(raw.get(field))
        derived = derive_subtotals(raw)
        return _to_float(derived.get(field))

    annual_out = {
        field: _to_float(annual.get(field))
        for field in stmt.field_order
        if stmt.field_categories[field] in {"subtotal", "revenue_item", "cost_item", "operating_adjustment", "below_line", "tax", "attribution"}
    }
    if "total_revenue" not in annual_out:
        annual_out["total_revenue"] = annual_out.get("revenue", 0.0)

    def is_zero_row(values: Mapping[str, float | None], annual_value: float | None = None) -> bool:
        candidates = list(values.values())
        if annual_value is not None:
            candidates.append(annual_value)
        return all(abs(_to_float(value)) <= EPSILON for value in candidates)

    def metric_states() -> dict[str, str]:
        return {period: period_states.get(period, "inherit") for period in periods}

    def annual_ratio(numerator: str, denominator: str) -> float | None:
        return _safe_ratio(annual_out.get(numerator), annual_out.get(denominator))

    def annual_yoy(field: str) -> float | None:
        return _pct_change(
            annual_out.get(field),
            _clean_annual_value(annual_rows, year=selected_year - 1, field=field),
        )

    def make_metric_row(
        *,
        field: str,
        label: str,
        values: dict[str, float | None],
        annual_value: float | None,
        highlight: bool = False,
    ) -> dict[str, object]:
        annual_out[field] = annual_value
        return {
            "field": field,
            "label": label,
            "category": "metric",
            "role": "metric",
            "format": "percent",
            "values": values,
            "states": metric_states(),
            "is_zero": is_zero_row(values, annual_value),
            "highlight": highlight,
        }

    def yoy_metric(field: str) -> dict[str, float | None]:
        values: dict[str, float | None] = {}
        for period in periods:
            parsed = _parse_period(period)
            if parsed is None:
                values[period] = None
                continue
            period_year, q = parsed
            values[period] = _pct_change(value_for_period(period, field), value_for_period(f"{period_year - 1}Q{q}", field))
        return values

    def rate_metric(numerator: str, denominator: str = "revenue") -> dict[str, float | None]:
        return {
            period: _safe_ratio(value_for_period(period, numerator), value_for_period(period, denominator))
            for period in periods
        }

    rows: list[dict[str, object]] = []
    included_categories = {"subtotal", "revenue_item", "cost_item", "operating_adjustment", "below_line", "tax", "attribution"}
    for field in stmt.field_order:
        if field in {"total_opcost", "n_income_attr_p"}:
            continue
        category = stmt.field_categories[field]
        if category not in included_categories:
            continue
        values = {period: period_values.get(period, {}).get(field, 0.0) for period in periods}
        row_states = {}
        for period in periods:
            parsed = _parse_period(period)
            if parsed is None:
                row_states[period] = period_states.get(period, "inherit")
                continue
            period_year, q = parsed
            if period_year != selected_year:
                row_states[period] = period_states.get(period, "actual")
                continue
            locked = _locked_amounts(overrides, year=selected_year, field=field)
            gross_locked = _locked_amounts(overrides, year=selected_year, field="gross_profit") if field == "oper_cost" else {}
            row_states[period] = "manual" if q in locked or q in gross_locked else states[q]
        rows.append(
            {
                "field": field,
                "label": "净利润" if field == "n_income" else stmt.labels.get(field, field),
                "category": category,
                "role": "total" if category == "subtotal" else "leaf",
                "format": "number",
                "values": values,
                "states": row_states,
                "is_zero": is_zero_row(values, annual_out.get(field)),
                "highlight": field == "n_income",
            }
        )
        if field == "revenue":
            rows.append(
                make_metric_row(
                    field="revenue_yoy",
                    label="yoy",
                    values=yoy_metric("revenue"),
                    annual_value=annual_yoy("revenue"),
                )
            )
        elif field == "oper_cost":
            gross_margin_values = {
                period: _safe_ratio(value_for_period(period, "revenue") - value_for_period(period, "oper_cost"), value_for_period(period, "revenue"))
                for period in periods
            }
            rows.append(
                make_metric_row(
                    field="oper_cost_yoy",
                    label="yoy",
                    values=yoy_metric("oper_cost"),
                    annual_value=annual_yoy("oper_cost"),
                )
            )
            rows.append(
                make_metric_row(
                    field="gross_margin",
                    label="毛利率",
                    values=gross_margin_values,
                    annual_value=_safe_ratio(annual_out.get("revenue", 0.0) - annual_out.get("oper_cost", 0.0), annual_out.get("revenue")),
                )
            )
        elif field in {"sell_exp", "admin_exp", "rd_exp", "fin_exp", "biz_tax_surchg"}:
            rows.append(
                make_metric_row(
                    field=f"{field}_rate",
                    label="%Rev",
                    values=rate_metric(field),
                    annual_value=annual_ratio(field, "revenue"),
                )
            )
        elif field == "income_tax":
            rows.append(
                make_metric_row(
                    field="income_tax_rate",
                    label="税率",
                    values=rate_metric("income_tax", "total_profit"),
                    annual_value=annual_ratio("income_tax", "total_profit"),
                )
            )
        elif field == "n_income":
            rows.append(
                make_metric_row(
                    field="n_income_yoy",
                    label="yoy",
                    values=yoy_metric("n_income"),
                    annual_value=annual_yoy("n_income"),
                    highlight=True,
                )
            )
            rows.append(
                make_metric_row(
                    field="n_income_margin",
                    label="净利率",
                    values=rate_metric("n_income"),
                    annual_value=annual_ratio("n_income", "revenue"),
                    highlight=True,
                )
            )

    return {
        "year": selected_year,
        "periods": periods,
        "quarter_states": {str(q): states[q] for q in (1, 2, 3, 4)},
        "period_states": period_states,
        "rows": rows,
        "annual": annual_out,
        "variance": {},
        "q4_flags": [],
    }


def check_q4_band(
    *,
    implied: Mapping[str, float | int | None],
    history_q4: Mapping[str, list[float]],
    n: int = 3,
) -> list[dict[str, float | str]]:
    """Return soft flags when implied Q4 ratios sit outside history bands."""
    flags: list[dict[str, float | str]] = []
    for ratio, raw_implied in implied.items():
        if raw_implied is None:
            continue
        history = [float(v) for v in history_q4.get(ratio, [])[-n:] if v is not None]
        if not history:
            continue
        low = min(history)
        high = max(history)
        pad = max((high - low) * 0.2, 0.02)
        band_min = low - pad
        band_max = high + pad
        value = float(raw_implied)
        if value < band_min or value > band_max:
            flags.append(
                {
                    "ratio": ratio,
                    "implied": value,
                    "band_min": band_min,
                    "band_max": band_max,
                    "msg": f"{ratio} Q4 implied {value:.4f} outside history band",
                }
            )
    return flags
