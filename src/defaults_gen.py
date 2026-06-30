"""Generate YAML2 defaults.yaml from validated clean tables.

The latest annual clean row remains the base period for balance-sheet state,
while flow and ratio defaults are normalized from recent clean_annual history.
This keeps defaults.yaml as a deterministic machine baseline rather than an
analyst judgment layer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from src.clean import (
    BS_FIELD_CATEGORIES,
    IS_FIELD_CATEGORIES,
    QA_FIELDS,
)
from src.yaml2_schema import (
    DEFAULT_FORECAST_YEARS,
    DEFAULT_PLUG,
    DEFAULT_TERMINAL_CAPEX_DA_RATIO,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_WACC,
    YAML2_VERSION,
    param,
    write_yaml2,
)
from src.financial_expense_analyzer import EVIDENCE_VERSION, load_financial_expense_yaml
from src.company_paths import (
    COMPANIES_DIR,
    company_dir_from_db_path,
    defaults_path,
    find_db_path as find_agent_db_path,
)


BASE_DIR = Path(__file__).resolve().parent.parent

REVENUE_RATE_FIELDS = [
    "biz_tax_surchg",
    "sell_exp",
    "admin_exp",
    "rd_exp",
    "other_bus_cost",
]

COST_ABS_EXCLUDE = {"oper_cost", *REVENUE_RATE_FIELDS}
IMPAIRMENT_COST_ABS_FIELDS = {
    "assets_impair_loss",
    "credit_impa_loss",
    "oth_impair_loss_assets",
}

REVENUE_DRIVER_FIELDS = [
    "notes_receiv",
    "accounts_receiv",
    "receiv_financing",
    "prepayment",
    "oth_receiv",
    "contract_assets",
    "oth_cur_assets",
    "adv_receipts",
    "contract_liab",
    "payroll_payable",
    "taxes_payable",
    "oth_payable",
    "oth_cur_liab",
]

COGS_DAYS_FIELDS = ["inventories", "notes_payable", "acct_payable"]

INTEREST_BEARING_DEBT_FIELDS = [
    "st_borr",
    "st_fin_payable",
    "st_bonds_payable",
    "non_cur_liab_due_1y",
    "lt_borr",
    "bond_payable",
    "lease_liab",
]

NORMALIZATION_YEARS = 5
SHORT_NORMALIZATION_YEARS = 3
MIN_VALID_SAMPLES = 2
MIN_INTEREST_BEARING_DEBT = 100.0
MIN_CASH_BALANCE = 100.0


@dataclass(frozen=True)
class HistoryRow:
    period: str
    raw: dict[str, Any]
    values: dict[str, float]


@dataclass(frozen=True)
class Sample:
    period: str
    value: float


def find_db_path(ticker: str) -> Path:
    return find_agent_db_path(ticker, COMPANIES_DIR)


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {str(k): str(v) for k, v in rows}


def read_clean_annual_history(conn: sqlite3.Connection) -> list[HistoryRow]:
    df = pd.read_sql_query("SELECT * FROM clean_annual ORDER BY period", conn)
    if df.empty:
        raise ValueError("clean_annual is empty")
    for field in QA_FIELDS:
        if field not in df.columns:
            df[field] = 0.0

    history: list[HistoryRow] = []
    for _, series in df.iterrows():
        raw = series.to_dict()
        period = str(raw.pop("period"))
        values = {str(k): to_float(v) for k, v in raw.items()}
        for field in QA_FIELDS:
            values.setdefault(field, 0.0)
            raw.setdefault(field, 0.0)
        history.append(HistoryRow(period=period, raw={str(k): v for k, v in raw.items()}, values=values))
    return history


def read_latest_annual(conn: sqlite3.Connection) -> tuple[str, dict[str, float]]:
    history = read_clean_annual_history(conn)
    latest = history[-1]
    return latest.period, latest.values


def to_float(value: Any) -> float:
    parsed = to_float_or_none(value)
    return parsed if parsed is not None else 0.0


def to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    if abs(den) < 1e-12:
        return default
    return num / den


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def col(endpoint: str, field: str) -> str:
    if field == "credit_impa_loss" and endpoint in {"income", "cashflow"}:
        return f"{endpoint}.{field}"
    return field


def source_col(endpoint: str, field: str) -> str:
    return f"clean_annual.{col(endpoint, field)}"


def build_param_map(
    fields: list[str],
    row: dict[str, float],
    *,
    endpoint: str,
    source_prefix: str | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for field in fields:
        column = col(endpoint, field)
        out[field] = param(row.get(column, 0.0), source_prefix or source_col(endpoint, field))
    return out


def _param(
    value: Any,
    source: str,
    note: str | None = None,
    *,
    method: str | None = None,
    sample_periods: list[str] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    item = param(value, source, note)
    if method:
        item["method"] = method
    if sample_periods:
        item["sample_periods"] = sample_periods
    if fallback_reason:
        item["fallback_reason"] = fallback_reason
    return item


def _add_flag(
    review_flags: list[dict[str, Any]],
    code: str,
    path: str,
    message: str,
    **extra: Any,
) -> None:
    flag = {
        "code": code,
        "path": path,
        "message": message,
        "severity": extra.pop("severity", "warning"),
    }
    for key, value in extra.items():
        if value is not None:
            flag[key] = value
    review_flags.append(flag)


def _recent(history: list[HistoryRow], years: int = NORMALIZATION_YEARS) -> list[HistoryRow]:
    return history[-years:]


def _row_value(row: HistoryRow, field: str) -> float | None:
    return to_float_or_none(row.raw.get(field))


def _sample_periods(samples: list[Sample]) -> list[str]:
    return [sample.period for sample in samples]


def _safe_samples(samples: list[Sample]) -> list[Sample]:
    return [sample for sample in samples if math.isfinite(sample.value)]


def _latest_sample(samples: list[Sample], latest_period: str) -> Sample | None:
    for sample in reversed(samples):
        if sample.period == latest_period:
            return sample
    return samples[-1] if samples else None


def _is_outlier(latest: float, center: float, values: list[float], *, abs_floor: float) -> bool:
    if len(values) < 3:
        return False
    deviations = [abs(value - center) for value in values]
    mad = median(deviations)
    if mad > 1e-9:
        threshold = max(3.0 * 1.4826 * mad, abs(center) * 0.50, abs_floor)
    else:
        threshold = max(abs(center) * 0.50, abs_floor)
    return abs(latest - center) > threshold


def _normalized_param(
    *,
    path: str,
    samples: list[Sample],
    source: str,
    review_flags: list[dict[str, Any]],
    latest_period: str,
    method: str,
    min_samples: int = MIN_VALID_SAMPLES,
    default: float = 0.0,
    bounds: tuple[float, float] | None = None,
    allow_single_sample: bool = True,
    outlier_code: str = "latest_outlier",
    outlier_abs_floor: float = 1e-6,
    note: str | None = None,
) -> dict[str, Any]:
    valid = _safe_samples(samples)
    fallback_reason: str | None = None

    if len(valid) >= min_samples:
        value = float(median(sample.value for sample in valid))
    elif valid and allow_single_sample:
        value = float(median(sample.value for sample in valid))
        fallback_reason = "insufficient_history_samples"
        _add_flag(
            review_flags,
            "insufficient_history_samples",
            path,
            f"Only {len(valid)} valid historical sample(s); used available sample median.",
            periods=_sample_periods(valid),
        )
    else:
        value = default
        fallback_reason = "no_valid_history_samples"
        _add_flag(
            review_flags,
            "missing_as_zero",
            path,
            "No valid historical samples; defaulted to 0.",
            periods=_sample_periods(samples),
        )

    if bounds is not None:
        value = clamp(value, bounds[0], bounds[1])

    if len(valid) >= min_samples:
        latest = _latest_sample(valid, latest_period)
        values = [sample.value for sample in valid]
        if latest is not None and _is_outlier(latest.value, value, values, abs_floor=outlier_abs_floor):
            _add_flag(
                review_flags,
                outlier_code,
                path,
                "Latest clean_annual sample differs materially from the normalized median.",
                period=latest.period,
                latest_value=latest.value,
                normalized_value=value,
                sample_periods=_sample_periods(valid),
            )

    return _param(
        value,
        source,
        note,
        method=method,
        sample_periods=_sample_periods(valid),
        fallback_reason=fallback_reason,
    )


def _ratio_samples(
    history: list[HistoryRow],
    *,
    numerator: str,
    denominator: str,
    review_flags: list[dict[str, Any]],
    path: str,
    years: int = NORMALIZATION_YEARS,
    min_denominator: float = 1e-9,
    require_positive_denominator: bool = True,
    require_positive_numerator: bool = False,
) -> list[Sample]:
    samples: list[Sample] = []
    for row in _recent(history, years):
        num = _row_value(row, numerator)
        den = _row_value(row, denominator)
        if num is None or den is None:
            continue
        den_abs = abs(den)
        if den_abs < min_denominator or (require_positive_denominator and den <= 0):
            if row.period == history[-1].period:
                _add_flag(
                    review_flags,
                    "small_denominator",
                    path,
                    f"Latest denominator {denominator} is too small for a stable ratio.",
                    period=row.period,
                    denominator=den,
                )
            continue
        if require_positive_numerator and num <= 0:
            continue
        samples.append(Sample(row.period, num / den))
    return samples


def _value_samples(
    history: list[HistoryRow],
    field: str,
    *,
    years: int = NORMALIZATION_YEARS,
) -> list[Sample]:
    samples: list[Sample] = []
    for row in _recent(history, years):
        value = _row_value(row, field)
        if value is not None:
            samples.append(Sample(row.period, value))
    return samples


def _ratio_param(
    history: list[HistoryRow],
    *,
    path: str,
    numerator: str,
    denominator: str,
    source: str,
    review_flags: list[dict[str, Any]],
    method: str,
    bounds: tuple[float, float] | None = None,
    years: int = NORMALIZATION_YEARS,
    min_denominator: float = 1e-9,
    require_positive_denominator: bool = True,
    require_positive_numerator: bool = False,
    min_samples: int = MIN_VALID_SAMPLES,
    allow_single_sample: bool = True,
    outlier_abs_floor: float = 1e-6,
) -> dict[str, Any]:
    samples = _ratio_samples(
        history,
        numerator=numerator,
        denominator=denominator,
        review_flags=review_flags,
        path=path,
        years=years,
        min_denominator=min_denominator,
        require_positive_denominator=require_positive_denominator,
        require_positive_numerator=require_positive_numerator,
    )
    return _normalized_param(
        path=path,
        samples=samples,
        source=source,
        review_flags=review_flags,
        latest_period=history[-1].period,
        method=method,
        bounds=bounds,
        min_samples=min_samples,
        allow_single_sample=allow_single_sample,
        outlier_abs_floor=outlier_abs_floor,
    )


def _value_param(
    history: list[HistoryRow],
    *,
    path: str,
    field: str,
    source: str,
    review_flags: list[dict[str, Any]],
    method: str,
    years: int = NORMALIZATION_YEARS,
    min_samples: int = MIN_VALID_SAMPLES,
    outlier_code: str = "one_off_candidate",
    outlier_abs_floor: float = 10.0,
) -> dict[str, Any]:
    samples = _value_samples(history, field, years=years)
    return _normalized_param(
        path=path,
        samples=samples,
        source=source,
        review_flags=review_flags,
        latest_period=history[-1].period,
        method=method,
        min_samples=min_samples,
        outlier_code=outlier_code,
        outlier_abs_floor=outlier_abs_floor,
    )


def _normalized_param_map(
    fields: list[str],
    history: list[HistoryRow],
    *,
    endpoint: str,
    review_flags: list[dict[str, Any]],
    path_prefix: str,
    source_prefix: str | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for field in fields:
        column = col(endpoint, field)
        out[field] = _value_param(
            history,
            path=f"{path_prefix}.{field}",
            field=column,
            source=source_prefix or f"{source_col(endpoint, field)} 5y_median",
            review_flags=review_flags,
            method="median_recent_5y_clean_annual",
        )
    return out


def _interest_bearing_debt(row: dict[str, float]) -> float:
    return sum(row.get(field, 0.0) for field in INTEREST_BEARING_DEBT_FIELDS)


def _avg_balance(current: HistoryRow, previous: HistoryRow | None, fields: list[str]) -> float:
    current_value = sum(current.values.get(field, 0.0) for field in fields)
    if previous is None:
        return current_value
    previous_value = sum(previous.values.get(field, 0.0) for field in fields)
    return (previous_value + current_value) / 2.0


def _avg_single_balance(current: HistoryRow, previous: HistoryRow | None, field: str) -> float:
    current_value = current.values.get(field, 0.0)
    if previous is None:
        return current_value
    previous_value = previous.values.get(field, 0.0)
    return (previous_value + current_value) / 2.0


def _financial_rate_samples(
    history: list[HistoryRow],
    *,
    numerator: str,
    denominator_fields: list[str],
    min_denominator: float,
    path: str,
    review_flags: list[dict[str, Any]],
    years: int = NORMALIZATION_YEARS,
) -> list[Sample]:
    recent = _recent(history, years)
    first_index = len(history) - len(recent)
    samples: list[Sample] = []
    for offset, row in enumerate(recent):
        idx = first_index + offset
        previous = history[idx - 1] if idx > 0 else None
        den = _avg_balance(row, previous, denominator_fields)
        num = _row_value(row, numerator)
        if num is None or num <= 0:
            continue
        if den < min_denominator:
            if row.period == history[-1].period:
                _add_flag(
                    review_flags,
                    "small_denominator",
                    path,
                    "Latest average balance is too small for a stable financial-expense rate.",
                    period=row.period,
                    denominator=den,
                )
            continue
        samples.append(Sample(row.period, num / den))
    return samples


def _financial_expense_params(
    history: list[HistoryRow],
    review_flags: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest = history[-1].values
    fin_exp = latest.get("fin_exp", 0.0)
    interest_expense = latest.get("fin_exp_int_exp", 0.0)
    interest_income = latest.get("fin_exp_int_inc", 0.0)

    interest_samples = _financial_rate_samples(
        history,
        numerator="fin_exp_int_exp",
        denominator_fields=INTEREST_BEARING_DEBT_FIELDS,
        min_denominator=MIN_INTEREST_BEARING_DEBT,
        path="income.financial_expense.interest_expense_rate",
        review_flags=review_flags,
    )
    cash_samples: list[Sample] = []
    recent = _recent(history, NORMALIZATION_YEARS)
    first_index = len(history) - len(recent)
    for offset, row in enumerate(recent):
        idx = first_index + offset
        previous = history[idx - 1] if idx > 0 else None
        cash = _avg_single_balance(row, previous, "money_cap")
        num = _row_value(row, "fin_exp_int_inc")
        if num is None or num <= 0:
            continue
        if cash < MIN_CASH_BALANCE:
            if row.period == history[-1].period:
                _add_flag(
                    review_flags,
                    "small_denominator",
                    "income.financial_expense.cash_interest_rate",
                    "Latest average cash balance is too small for a stable interest-income rate.",
                    period=row.period,
                    denominator=cash,
                )
            continue
        cash_samples.append(Sample(row.period, num / cash))

    other_samples: list[Sample] = []
    for row in recent:
        row_fin_exp = _row_value(row, "fin_exp")
        row_interest_expense = _row_value(row, "fin_exp_int_exp")
        row_interest_income = _row_value(row, "fin_exp_int_inc")
        if row_fin_exp is None or row_interest_expense is None or row_interest_income is None:
            continue
        other_samples.append(Sample(row.period, row_fin_exp - row_interest_expense + row_interest_income))

    return {
        "interest_mode": param(
            "circular_average_balance",
            "model_default",
            "Engine computes fin_exp from average interest-bearing debt and cash.",
        ),
        "interest_expense_rate": _normalized_param(
            path="income.financial_expense.interest_expense_rate",
            samples=interest_samples,
            source="clean_annual.5y_median.fin_exp_int_exp / avg_interest_bearing_debt",
            review_flags=review_flags,
            latest_period=history[-1].period,
            method="median_recent_5y_positive_samples_avg_interest_bearing_debt",
            bounds=(0.0, 1.0),
            outlier_abs_floor=0.005,
        ),
        "cash_interest_rate": _normalized_param(
            path="income.financial_expense.cash_interest_rate",
            samples=cash_samples,
            source="clean_annual.5y_median.fin_exp_int_inc / avg_money_cap",
            review_flags=review_flags,
            latest_period=history[-1].period,
            method="median_recent_5y_positive_samples_avg_money_cap",
            bounds=(0.0, 1.0),
            outlier_abs_floor=0.005,
        ),
        "other_fin_exp_abs": _normalized_param(
            path="income.financial_expense.other_fin_exp_abs",
            samples=other_samples,
            source="clean_annual.5y_median.fin_exp - fin_exp_int_exp + fin_exp_int_inc",
            review_flags=review_flags,
            latest_period=history[-1].period,
            method="median_recent_5y_clean_annual_other_fin_exp",
            outlier_code="one_off_candidate",
            outlier_abs_floor=10.0,
            note="Financial expense = interest expense - interest income + other financial expense.",
        ),
        "base_interest_expense": param(interest_expense, "clean_annual.fin_exp_int_exp"),
        "base_interest_income": param(interest_income, "clean_annual.fin_exp_int_inc"),
        "base_fin_exp": param(fin_exp, "clean_annual.fin_exp"),
    }


def _dividend_payout_param(
    history: list[HistoryRow],
    review_flags: list[dict[str, Any]],
) -> dict[str, Any]:
    same_year: list[Sample] = []
    lagged: list[Sample] = []
    recent = _recent(history, SHORT_NORMALIZATION_YEARS)
    first_index = len(history) - len(recent)

    for offset, row in enumerate(recent):
        idx = first_index + offset
        pay_dist = _row_value(row, "c_pay_dist_dpcp_int_exp")
        interest_expense = _row_value(row, "fin_exp_int_exp")
        minority_dividend = _row_value(row, "incl_dvd_profit_paid_sc_ms")
        if pay_dist is None or interest_expense is None or minority_dividend is None:
            continue
        common_dividend_cash = max(pay_dist - interest_expense - minority_dividend, 0.0)

        current_profit = _row_value(row, "n_income_attr_p")
        if current_profit is not None and current_profit > 0:
            same_year.append(Sample(row.period, common_dividend_cash / current_profit))
        elif row.period == history[-1].period:
            _add_flag(
                review_flags,
                "small_denominator",
                "balance_sheet.dividend_payout",
                "Latest attributable net income is not positive for same-year payout.",
                period=row.period,
                denominator=current_profit,
            )

        if idx > 0:
            prev_profit = _row_value(history[idx - 1], "n_income_attr_p")
            if prev_profit is not None and prev_profit > 0:
                lagged.append(Sample(row.period, common_dividend_cash / prev_profit))

    source = (
        "median(common_dividend_cash / lagged_n_income_attr_p), "
        "common_dividend_cash=max(c_pay_dist_dpcp_int_exp - fin_exp_int_exp - incl_dvd_profit_paid_sc_ms, 0)"
    )
    if len(lagged) >= MIN_VALID_SAMPLES:
        return _normalized_param(
            path="balance_sheet.dividend_payout",
            samples=lagged,
            source=source,
            review_flags=review_flags,
            latest_period=history[-1].period,
            method="median_recent_3y_lagged_cash_payout_net_of_interest_and_minority_dividend",
            min_samples=MIN_VALID_SAMPLES,
            allow_single_sample=False,
            bounds=(0.0, 1.0),
            outlier_abs_floor=0.05,
        )
    if len(same_year) >= MIN_VALID_SAMPLES:
        item = _normalized_param(
            path="balance_sheet.dividend_payout",
            samples=same_year,
            source=source.replace("lagged_n_income_attr_p", "same_year_n_income_attr_p"),
            review_flags=review_flags,
            latest_period=history[-1].period,
            method="median_recent_3y_same_year_cash_payout_net_of_interest_and_minority_dividend",
            min_samples=MIN_VALID_SAMPLES,
            allow_single_sample=False,
            bounds=(0.0, 1.0),
            outlier_abs_floor=0.05,
        )
        item["fallback_reason"] = "lagged_payout_samples_insufficient"
        return item

    _add_flag(
        review_flags,
        "missing_as_zero",
        "balance_sheet.dividend_payout",
        "No valid recent lagged or same-year cash payout samples; defaulted to 0.",
        lagged_sample_periods=_sample_periods(lagged),
        same_year_sample_periods=_sample_periods(same_year),
    )
    return _param(
        0.0,
        source,
        "No valid recent cash payout samples.",
        method="median_recent_3y_cash_payout_net_of_interest_and_minority_dividend",
        sample_periods=_sample_periods(lagged) or _sample_periods(same_year),
        fallback_reason="no_valid_payout_samples",
    )


def build_defaults(db_path: Path, ticker: str | None = None) -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as conn:
        meta = read_meta(conn)
        history = read_clean_annual_history(conn)

    latest = history[-1]
    base_period = latest.period
    row = latest.values
    review_flags: list[dict[str, Any]] = []
    ticker = ticker or meta.get("ticker") or ""
    company_dir = company_dir_from_db_path(db_path)
    name = meta.get("name") or company_dir.name
    revenue = row.get("revenue", 0.0)
    oper_cost = row.get("oper_cost", 0.0)

    cost_abs_fields = sorted(
        {
            field
            for field, category in IS_FIELD_CATEGORIES.items()
            if category == "cost_item" and field not in COST_ABS_EXCLUDE | {"fin_exp"}
        }
        | IMPAIRMENT_COST_ABS_FIELDS
    )
    revenue_item_fields = [
        field
        for field, category in IS_FIELD_CATEGORIES.items()
        if category == "revenue_item" and field != "revenue"
    ]
    operating_adjustment_fields = [
        field
        for field, category in IS_FIELD_CATEGORIES.items()
        if category == "operating_adjustment" and field not in IMPAIRMENT_COST_ABS_FIELDS
    ]
    below_line_fields = [
        field for field, category in IS_FIELD_CATEGORIES.items() if category == "below_line"
    ]

    capex = row.get("c_pay_acq_const_fiolta", 0.0)
    da = (
        row.get("depr_fa_coga_dpba", 0.0)
        + row.get("amort_intang_assets", 0.0)
        + row.get("lt_amort_deferred_exp", 0.0)
        + row.get("use_right_asset_dep", 0.0)
    )
    debt = _interest_bearing_debt(row)
    cash = row.get("money_cap", 0.0)

    bs_fields = sorted(set(BS_FIELD_CATEGORIES) | set(QA_FIELDS))
    base_bs = {
        field: param(row.get(field, 0.0), source_col("balancesheet", field))
        for field in bs_fields
    }

    revenue_pct = {
        field: _ratio_param(
            history,
            path=f"balance_sheet.revenue_pct.{field}",
            numerator=field,
            denominator="revenue",
            source=f"{source_col('balancesheet', field)} / clean_annual.revenue 5y_median",
            review_flags=review_flags,
            method="median_recent_5y_ratio_to_revenue",
            min_denominator=1e-9,
            outlier_abs_floor=0.02,
        )
        for field in REVENUE_DRIVER_FIELDS
    }

    cogs_days: dict[str, dict[str, Any]] = {}
    for field in COGS_DAYS_FIELDS:
        samples = [
            Sample(sample.period, sample.value * 365.0)
            for sample in _ratio_samples(
                history,
                numerator=field,
                denominator="oper_cost",
                review_flags=review_flags,
                path=f"balance_sheet.cogs_days.{field}",
                min_denominator=1e-9,
            )
        ]
        cogs_days[field] = _normalized_param(
            path=f"balance_sheet.cogs_days.{field}",
            samples=samples,
            source=f"{source_col('balancesheet', field)} / clean_annual.oper_cost * 365 5y_median",
            review_flags=review_flags,
            latest_period=base_period,
            method="median_recent_5y_cogs_days",
            outlier_abs_floor=15.0,
        )

    gpm_samples: list[Sample] = []
    for hist_row in _recent(history, NORMALIZATION_YEARS):
        hist_revenue = _row_value(hist_row, "revenue")
        hist_oper_cost = _row_value(hist_row, "oper_cost")
        if hist_revenue is None or hist_oper_cost is None or hist_revenue <= 0:
            continue
        gpm_samples.append(Sample(hist_row.period, 1.0 - hist_oper_cost / hist_revenue))

    depr_samples: list[Sample] = []
    for hist_row in _recent(history, NORMALIZATION_YEARS):
        depr = _row_value(hist_row, "depr_fa_coga_dpba")
        depreciable_assets = max(
            hist_row.values.get("fix_assets", 0.0),
            hist_row.values.get("fix_assets_total", 0.0),
            0.0,
        )
        if depr is None or depreciable_assets <= 0:
            if hist_row.period == base_period:
                _add_flag(
                    review_flags,
                    "small_denominator",
                    "balance_sheet.depr_rate",
                    "Latest fixed-assets base is too small for a stable depreciation rate.",
                    period=hist_row.period,
                    denominator=depreciable_assets,
                )
            continue
        depr_samples.append(Sample(hist_row.period, depr / depreciable_assets))

    revenue_items_abs = _normalized_param_map(
        revenue_item_fields,
        history,
        endpoint="income",
        review_flags=review_flags,
        path_prefix="income.revenue_items_abs",
    )
    # oth_b_income 已包含在 income.revenue（clean_annual.revenue = 营业收入总额）内。
    # 若 revenue_items_abs.oth_b_income 再以 5y median 计入，calc.py 的
    # total_revenue = revenue + sum(revenue_items_abs) 会双计其他业务收入、虚增利润。
    # 归零；其他业务收入由 income.revenue 承载（分解含 bridge leaf 时由 bridge 表达其 0% 增长）。
    revenue_items_abs["oth_b_income"] = _param(
        0.0,
        "zeroed: oth_b_income included in income.revenue (clean_annual.revenue total)",
        note="其他业务收入已含在 income.revenue 总额内；归零防 calc total_revenue 双计。",
        method="zeroed_avoid_double_count",
    )

    data: dict[str, Any] = {
        "version": YAML2_VERSION,
        "ticker": ticker,
        "name": name,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "base_period": base_period,
        "unit": "million_cny",
        "model": {
            "forecast_years": param(DEFAULT_FORECAST_YEARS, "model_default"),
            "revenue_yoy": param(0.0, "default_flat_no_forecast"),
            "wacc": param(DEFAULT_WACC, "model_default"),
            "terminal_growth": param(DEFAULT_TERMINAL_GROWTH, "model_default"),
            "terminal_capex_da_ratio": param(DEFAULT_TERMINAL_CAPEX_DA_RATIO, "model_default"),
            "plug": param(DEFAULT_PLUG, "model_default"),
        },
        "market": {
            "total_shares": param(to_float(meta.get("total_share")), "meta.total_share"),
            "net_debt": param(debt - cash, "interest_bearing_debt - clean_annual.money_cap"),
            "total_mv": param(to_float(meta.get("total_mv")), "meta.total_mv"),
            "close": param(to_float(meta.get("close")), "meta.close"),
        },
        "income": {
            "revenue": param(revenue, "clean_annual.revenue"),
            "revenue_items_abs": revenue_items_abs,
            "gpm": _normalized_param(
                path="income.gpm",
                samples=gpm_samples,
                source="1 - clean_annual.oper_cost / clean_annual.revenue 5y_median",
                review_flags=review_flags,
                latest_period=base_period,
                method="median_recent_5y_gross_margin",
                bounds=(-1.0, 1.0),
                outlier_abs_floor=0.03,
            ),
            "cost_rates": {
                field: _ratio_param(
                    history,
                    path=f"income.cost_rates.{field}",
                    numerator=col("income", field),
                    denominator="revenue",
                    source=f"{source_col('income', field)} / clean_annual.revenue 5y_median",
                    review_flags=review_flags,
                    method="median_recent_5y_ratio_to_revenue",
                    bounds=(-1.0, 1.0),
                    outlier_abs_floor=0.01,
                )
                for field in REVENUE_RATE_FIELDS
            },
            "cost_abs": _normalized_param_map(
                cost_abs_fields,
                history,
                endpoint="income",
                review_flags=review_flags,
                path_prefix="income.cost_abs",
            ),
            "financial_expense": _financial_expense_params(history, review_flags),
            "operating_adjustments_abs": _normalized_param_map(
                operating_adjustment_fields,
                history,
                endpoint="income",
                review_flags=review_flags,
                path_prefix="income.operating_adjustments_abs",
            ),
            "below_line_abs": _normalized_param_map(
                below_line_fields,
                history,
                endpoint="income",
                review_flags=review_flags,
                path_prefix="income.below_line_abs",
            ),
            "effective_tax_rate": _ratio_param(
                history,
                path="income.effective_tax_rate",
                numerator="income_tax",
                denominator="total_profit",
                source="clean_annual.income_tax / clean_annual.total_profit 5y_median",
                review_flags=review_flags,
                method="median_recent_5y_positive_profit_tax_rate",
                bounds=(0.0, 1.0),
                outlier_abs_floor=0.05,
            ),
            "minority_ratio": _ratio_param(
                history,
                path="income.minority_ratio",
                numerator="minority_gain",
                denominator="n_income",
                source="clean_annual.minority_gain / clean_annual.n_income 5y_median",
                review_flags=review_flags,
                method="median_recent_5y_positive_net_income_minority_ratio",
                bounds=(0.0, 1.0),
                outlier_abs_floor=0.03,
            ),
        },
        "balance_sheet": {
            "base": base_bs,
            "revenue_pct": revenue_pct,
            "cogs_days": cogs_days,
            "capex_pct": _ratio_param(
                history,
                path="balance_sheet.capex_pct",
                numerator="c_pay_acq_const_fiolta",
                denominator="revenue",
                source="clean_annual.c_pay_acq_const_fiolta / clean_annual.revenue 5y_median",
                review_flags=review_flags,
                method="median_recent_5y_capex_to_revenue",
                bounds=(0.0, 1.0),
                outlier_abs_floor=0.03,
            ),
            "depr_rate": _normalized_param(
                path="balance_sheet.depr_rate",
                samples=depr_samples,
                source="clean_annual.depr_fa_coga_dpba / fixed_assets_base 5y_median",
                review_flags=review_flags,
                latest_period=base_period,
                method="median_recent_5y_depreciation_to_fixed_assets",
                bounds=(0.0, 1.0),
                outlier_abs_floor=0.02,
            ),
            "amort_intang_assets": param(row.get("amort_intang_assets", 0.0), "clean_annual.amort_intang_assets"),
            "lt_amort_deferred_exp": param(row.get("lt_amort_deferred_exp", 0.0), "clean_annual.lt_amort_deferred_exp"),
            "use_right_asset_dep": param(row.get("use_right_asset_dep", 0.0), "clean_annual.use_right_asset_dep"),
            "dividend_payout": _dividend_payout_param(history, review_flags),
        },
        "cashflow": {
            "capex": param(capex, "clean_annual.c_pay_acq_const_fiolta"),
            "da": param(da, "depr_fa_coga_dpba + amort_intang_assets + lt_amort_deferred_exp + use_right_asset_dep"),
            "base_nwc": param(operating_working_capital(row), "operating current assets - operating current liabilities"),
        },
        "review_flags": review_flags,
    }
    data = _apply_financial_expense_evidence(data, db_path)
    return data


def _apply_financial_expense_evidence(data: dict[str, Any], db_path: Path) -> dict[str, Any]:
    """Override mechanical financial_expense params with approved annual-report evidence.

    Reads ``financial_expense.yaml`` and picks the latest approved+high period
    whose checks pass and whose base_period matches the YAML2 base_period.
    """
    company_dir = company_dir_from_db_path(db_path)
    archive = load_financial_expense_yaml(company_dir)
    if archive is None:
        return data
    review_flags = data.setdefault("review_flags", [])

    if int(archive.get("version") or 0) != EVIDENCE_VERSION:
        _add_flag(
            review_flags,
            "financial_expense_evidence_failed",
            "income.financial_expense",
            "financial_expense.yaml version is stale; using clean_annual normalized defaults.",
            archive_version=archive.get("version"),
            expected_version=EVIDENCE_VERSION,
        )
        return data

    periods = archive.get("periods") or {}
    if not isinstance(periods, dict):
        _add_flag(
            review_flags,
            "financial_expense_evidence_failed",
            "income.financial_expense",
            "financial_expense.yaml has no usable periods mapping.",
        )
        return data

    # Pick the latest (lexicographically last) approved+high period.
    candidate: tuple[str, dict[str, Any]] | None = None
    for base_period in sorted(periods):
        record = periods[base_period]
        if not isinstance(record, dict):
            continue
        if record.get("status") != "approved" or record.get("confidence") != "high":
            continue
        checks = record.get("checks") or {}
        if not checks.get("total_check", {}).get("ok"):
            continue
        if not checks.get("basis_check", {}).get("ok"):
            continue
        candidate = (base_period, record)

    if candidate is None:
        _add_flag(
            review_flags,
            "financial_expense_evidence_failed",
            "income.financial_expense",
            "No approved high-confidence financial expense evidence; using clean_annual normalized defaults.",
        )
        return data

    base_period, record = candidate
    if base_period != str(data.get("base_period")):
        _add_flag(
            review_flags,
            "financial_expense_evidence_failed",
            "income.financial_expense",
            "Latest approved financial expense evidence does not match defaults base_period.",
            evidence_period=base_period,
            base_period=data.get("base_period"),
        )
        return data

    derived = record.get("derived")
    if not isinstance(derived, dict):
        _add_flag(
            review_flags,
            "financial_expense_evidence_failed",
            "income.financial_expense",
            "Approved financial expense evidence has no derived values.",
            evidence_period=base_period,
        )
        return data

    fin_exp = data["income"]["financial_expense"]
    source = "annual_report.fin_exp_note"
    fin_exp["interest_expense_rate"]["value"] = float(derived["interest_expense_rate"])
    fin_exp["interest_expense_rate"]["source"] = source
    fin_exp["interest_expense_rate"]["method"] = "annual_report_note_average_balance"
    fin_exp["interest_expense_rate"]["sample_periods"] = [base_period]
    fin_exp["cash_interest_rate"]["value"] = float(derived["cash_interest_rate"])
    fin_exp["cash_interest_rate"]["source"] = source
    fin_exp["cash_interest_rate"]["method"] = "annual_report_note_average_balance"
    fin_exp["cash_interest_rate"]["sample_periods"] = [base_period]
    fin_exp["other_fin_exp_abs"]["value"] = float(derived["other_fin_exp_abs"])
    fin_exp["other_fin_exp_abs"]["source"] = source
    fin_exp["other_fin_exp_abs"]["method"] = "annual_report_note_components"
    fin_exp["other_fin_exp_abs"]["sample_periods"] = [base_period]
    fin_exp["base_interest_expense"]["value"] = float(derived["interest_expense"])
    fin_exp["base_interest_expense"]["source"] = source
    fin_exp["base_interest_income"]["value"] = float(derived["interest_income"])
    fin_exp["base_interest_income"]["source"] = source
    # Reconcile base_fin_exp from the same derived components so the entire
    # financial_expense block carries one consistent annual-report source.
    # By construction this equals the original clean_annual.fin_exp total.
    fin_exp["base_fin_exp"]["value"] = (
        float(derived["interest_expense"])
        - float(derived["interest_income"])
        + float(derived["other_fin_exp_abs"])
    )
    fin_exp["base_fin_exp"]["source"] = source
    return data


def operating_working_capital(row: dict[str, float]) -> float:
    operating_current_assets = [
        "notes_receiv",
        "accounts_receiv",
        "receiv_financing",
        "prepayment",
        "inventories",
        "oth_receiv",
        "contract_assets",
        "oth_cur_assets",
    ]
    operating_current_liab = [
        "notes_payable",
        "acct_payable",
        "adv_receipts",
        "contract_liab",
        "payroll_payable",
        "taxes_payable",
        "oth_payable",
        "oth_cur_liab",
    ]
    return sum(row.get(f, 0.0) for f in operating_current_assets) - sum(
        row.get(f, 0.0) for f in operating_current_liab
    )


def default_output_path(db_path: Path) -> Path:
    return defaults_path(company_dir_from_db_path(db_path))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate YAML2 defaults.yaml from clean annual data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", help="A-share ticker, e.g. 300866.SZ")
    group.add_argument("--db", help="Path to companies/*/Agent/data.db")
    parser.add_argument("--output", help="Output defaults.yaml path; defaults to company/Agent/defaults.yaml")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db) if args.db else find_db_path(args.ticker)
    data = build_defaults(db_path, ticker=args.ticker)
    output = Path(args.output) if args.output else default_output_path(db_path)
    write_yaml2(output, data)
    print(f"Written YAML2 defaults: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
