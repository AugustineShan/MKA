"""Run a deterministic YAML2 DCF forecast.

The calculator is intentionally accounting-first:
1. income statement
2. balance sheet with explicit plug
3. cash flow statement derived from IS + BS movements
4. FCFF DCF valuation

Economic review issues (for example a cash plug producing negative cash) are
reported in review_flags, while accounting identities remain hard checks.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.clean import BS_FIELD_CATEGORIES, QA_FIELDS, bs_bucket_sum
from src.defaults_gen import (
    COGS_DAYS_FIELDS,
    INTEREST_BEARING_DEBT_FIELDS,
    REVENUE_DRIVER_FIELDS,
    operating_working_capital,
)
from src.yaml2_schema import (
    DEFAULT_TERMINAL_CAPEX_DA_RATIO,
    REVIEW_FLAG_NEGATIVE_CASH,
    get_path,
    plain_value,
    read_yaml2,
)


BASE_DIR = Path(__file__).resolve().parent.parent
TOLERANCE = 1e-4
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-7

# Impairment-like fields are signed P&L adjustments, not positive costs.
# They are read from cost_abs but merged into operate_profit algebraically.
IMPACT_ADJUSTMENT_FIELDS = {
    "assets_impair_loss",
    "credit_impa_loss",
    "oth_impair_loss_assets",
}


class CalcError(RuntimeError):
    """Raised when the forecast violates accounting identities."""


def as_float(value: Any, default: float = 0.0) -> float:
    value = plain_value(value)
    if value is None:
        return default
    try:
        if value != value:
            return default
    except TypeError:
        return default
    return float(value)


def as_int(value: Any, default: int = 0) -> int:
    return int(as_float(value, float(default)))


def value_map(section: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(section, dict):
        return {}
    return {str(k): as_float(v) for k, v in section.items()}


def year_value(value: Any, idx: int, path: str) -> Any:
    value = plain_value(value)
    if not isinstance(value, list):
        raise CalcError(f"{path} must be a yearly array")
    pos = idx - 1
    if pos < 0 or pos >= len(value):
        raise CalcError(f"{path} missing value for forecast index {idx}")
    return plain_value(value[pos])


def get_year_float(yaml2: dict[str, Any], path: str, idx: int, default: float = 0.0) -> float:
    value = get_path(yaml2, path)
    if value is None:
        return default
    return as_float(year_value(value, idx, path), default)


def value_map_at(section: dict[str, Any] | None, idx: int, section_path: str) -> dict[str, float]:
    if not isinstance(section, dict):
        return {}
    return {
        str(k): as_float(year_value(v, idx, f"{section_path}.{k}"))
        for k, v in section.items()
    }


def cfg_year_float(section: dict[str, Any], key: str, idx: int, default: float = 0.0) -> float:
    if key not in section:
        return default
    return as_float(year_value(section[key], idx, key), default)


def base_bs(yaml2: dict[str, Any]) -> dict[str, float]:
    raw = get_path(yaml2, "balance_sheet.base")
    if not isinstance(raw, dict):
        raise CalcError("balance_sheet.base must be a mapping")
    row = {str(k): as_float(v) for k, v in raw.items()}
    for field in set(BS_FIELD_CATEGORIES) | set(QA_FIELDS):
        row.setdefault(field, 0.0)
    return row


def interest_bearing_debt(row: dict[str, float]) -> float:
    return sum(row.get(field, 0.0) for field in INTEREST_BEARING_DEBT_FIELDS)


def financial_expense_from_balances(
    yaml2: dict[str, Any],
    prev_bs: dict[str, float],
    bs_row: dict[str, float],
    idx: int,
) -> dict[str, float]:
    fin_cfg = get_path(yaml2, "income.financial_expense", {})
    if not isinstance(fin_cfg, dict):
        fin_cfg = {}
    mode = plain_value(fin_cfg.get("interest_mode", "circular_average_balance"))
    if mode == "historical_abs":
        fin_exp = cfg_year_float(fin_cfg, "base_fin_exp", idx, get_year_float(yaml2, "income.cost_abs.fin_exp", idx))
        return {
            "fin_exp": fin_exp,
            "fin_exp_int_exp": cfg_year_float(fin_cfg, "base_interest_expense", idx),
            "fin_exp_int_inc": cfg_year_float(fin_cfg, "base_interest_income", idx),
            "other_fin_exp": fin_exp,
        }
    if mode != "circular_average_balance":
        raise CalcError(f"Unsupported financial expense mode: {mode}")

    debt_rate = cfg_year_float(fin_cfg, "interest_expense_rate", idx)
    cash_rate = cfg_year_float(fin_cfg, "cash_interest_rate", idx)
    other_fin_exp = cfg_year_float(fin_cfg, "other_fin_exp_abs", idx)
    avg_debt = max((interest_bearing_debt(prev_bs) + interest_bearing_debt(bs_row)) / 2.0, 0.0)
    avg_cash = max((prev_bs.get("money_cap", 0.0) + bs_row.get("money_cap", 0.0)) / 2.0, 0.0)
    interest_expense = avg_debt * debt_rate
    interest_income = avg_cash * cash_rate
    return {
        "fin_exp": interest_expense - interest_income + other_fin_exp,
        "fin_exp_int_exp": interest_expense,
        "fin_exp_int_inc": interest_income,
        "other_fin_exp": other_fin_exp,
    }


def build_income_statement(
    yaml2: dict[str, Any],
    revenue: float,
    financial_expense: dict[str, float],
    idx: int,
) -> dict[str, float]:
    income = yaml2.get("income", {})
    gpm = get_year_float(yaml2, "income.gpm", idx)
    tax_rate = get_year_float(yaml2, "income.effective_tax_rate", idx)
    minority_ratio = get_year_float(yaml2, "income.minority_ratio", idx)

    revenue_items = value_map_at(income.get("revenue_items_abs") if isinstance(income, dict) else None, idx, "income.revenue_items_abs")
    cost_rates = value_map_at(income.get("cost_rates") if isinstance(income, dict) else None, idx, "income.cost_rates")
    cost_abs = value_map_at(income.get("cost_abs") if isinstance(income, dict) else None, idx, "income.cost_abs")
    op_adj = value_map_at(income.get("operating_adjustments_abs") if isinstance(income, dict) else None, idx, "income.operating_adjustments_abs")
    below_line = value_map_at(income.get("below_line_abs") if isinstance(income, dict) else None, idx, "income.below_line_abs")

    row: dict[str, float] = {}
    row["revenue"] = revenue
    for field, value in revenue_items.items():
        row[field] = value
    row["total_revenue"] = revenue + sum(revenue_items.values())

    row["oper_cost"] = revenue * (1.0 - gpm)
    for field, rate in cost_rates.items():
        row[field] = revenue * rate
    for field, value in cost_abs.items():
        row[field] = value
    row["fin_exp"] = financial_expense["fin_exp"]
    row["fin_exp_int_exp"] = financial_expense["fin_exp_int_exp"]
    row["fin_exp_int_inc"] = financial_expense["fin_exp_int_inc"]

    cost_fields = (
        set(["oper_cost", "fin_exp"])
        | set(cost_rates)
        | (set(cost_abs) - IMPACT_ADJUSTMENT_FIELDS)
    )
    row["total_cogs"] = sum(row.get(field, 0.0) for field in cost_fields)
    row["total_opcost"] = row["total_cogs"]

    for field, value in op_adj.items():
        row[field] = value
    impact_fields = set(cost_abs) & IMPACT_ADJUSTMENT_FIELDS
    impact_adjustment = sum(row.get(field, 0.0) for field in impact_fields)
    row["operate_profit"] = (
        row["total_revenue"] - row["total_cogs"] + sum(op_adj.values()) + impact_adjustment
    )

    for field, value in below_line.items():
        row[field] = value
    row["total_profit"] = (
        row["operate_profit"]
        + row.get("non_oper_income", 0.0)
        - row.get("non_oper_exp", 0.0)
    )
    row["income_tax"] = row["total_profit"] * tax_rate if row["total_profit"] > 0 else 0.0
    row["n_income"] = row["total_profit"] - row["income_tax"]
    row["minority_gain"] = row["n_income"] * minority_ratio
    row["n_income_attr_p"] = row["n_income"] - row["minority_gain"]
    return row


def recompute_bs_totals(row: dict[str, float]) -> None:
    present = set(row)
    row["total_cur_assets"] = bs_bucket_sum("current_asset", row, present)
    row["total_nca"] = bs_bucket_sum("noncurrent_asset", row, present)
    row["total_assets"] = row["total_cur_assets"] + row["total_nca"]
    row["total_cur_liab"] = bs_bucket_sum("current_liab", row, present)
    row["total_ncl"] = bs_bucket_sum("noncurrent_liab", row, present)
    row["total_liab"] = row["total_cur_liab"] + row["total_ncl"]
    row["total_hldr_eqy_inc_min_int"] = bs_bucket_sum("equity", row, present)
    row["total_hldr_eqy_exc_min_int"] = (
        row["total_hldr_eqy_inc_min_int"] - row.get("minority_int", 0.0)
    )
    row["total_liab_hldr_eqy"] = row["total_liab"] + row["total_hldr_eqy_inc_min_int"]


def build_balance_sheet(
    yaml2: dict[str, Any],
    prev_bs: dict[str, float],
    income_row: dict[str, float],
    idx: int,
    review_flags: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    row = prev_bs.copy()
    revenue = income_row["revenue"]
    oper_cost = income_row["oper_cost"]
    bs_cfg = yaml2.get("balance_sheet", {})
    revenue_pct = value_map_at(bs_cfg.get("revenue_pct") if isinstance(bs_cfg, dict) else None, idx, "balance_sheet.revenue_pct")
    cogs_days = value_map_at(bs_cfg.get("cogs_days") if isinstance(bs_cfg, dict) else None, idx, "balance_sheet.cogs_days")
    capex_pct = get_year_float(yaml2, "balance_sheet.capex_pct", idx)
    depr_rate = get_year_float(yaml2, "balance_sheet.depr_rate", idx)
    dividend_payout = get_year_float(yaml2, "balance_sheet.dividend_payout", idx)
    plug = str(get_path(yaml2, "model.plug", "cash"))

    for field in REVENUE_DRIVER_FIELDS:
        if field in revenue_pct:
            row[field] = revenue * revenue_pct[field]
    for field in COGS_DAYS_FIELDS:
        if field in cogs_days:
            row[field] = oper_cost * cogs_days[field] / 365.0

    capex = revenue * capex_pct
    prev_fix = max(prev_bs.get("fix_assets", 0.0), prev_bs.get("fix_assets_total", 0.0), 0.0)
    depreciation = prev_fix * depr_rate
    row["fix_assets"] = max(prev_fix + capex - depreciation, 0.0)
    if prev_bs.get("fix_assets_total", 0.0) != 0.0:
        row["fix_assets_total"] = row["fix_assets"]

    dividends = max(income_row["n_income_attr_p"], 0.0) * dividend_payout
    row["undistr_porfit"] = (
        prev_bs.get("undistr_porfit", 0.0) + income_row["n_income_attr_p"] - dividends
    )
    row["minority_int"] = prev_bs.get("minority_int", 0.0) + income_row["minority_gain"]

    if plug == "cash":
        row["money_cap"] = 0.0
        recompute_bs_totals(row)
        assets_without_cash = row["total_assets"]
        required_cash = row["total_liab"] + row["total_hldr_eqy_inc_min_int"] - assets_without_cash
        row["money_cap"] = required_cash
        if required_cash < 0 and review_flags is not None:
            review_flags.append(
                {
                    "code": REVIEW_FLAG_NEGATIVE_CASH,
                    "severity": "warning",
                    "period": None,
                    "message": "plug产生负现金，建议切换为st_borr模式或检查参数",
                    "value": required_cash,
                }
            )
    elif plug == "st_borr":
        row["st_borr"] = 0.0
        recompute_bs_totals(row)
        required_st_borr = row["total_assets"] - row["total_hldr_eqy_inc_min_int"] - row["total_liab"]
        row["st_borr"] = required_st_borr
    else:
        raise CalcError(f"Unsupported plug mode: {plug}")

    recompute_bs_totals(row)
    metrics = {
        "capex": capex,
        "depreciation": depreciation,
        "dividends": dividends,
        "nwc": operating_working_capital(row),
    }
    return row, metrics


def solve_forecast_year(
    yaml2: dict[str, Any],
    period: str,
    prev_bs: dict[str, float],
    revenue: float,
    review_flags: list[dict[str, Any]],
    idx: int,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Solve one forecast year with circular interest and plug feedback.

    Financial expense depends on average debt/cash balances. Cash or debt is a
    BS plug, and retained earnings depend on net income after financial expense.
    The engine therefore iterates IS -> BS -> financial expense until both the
    financial expense and plug output converge.
    """
    fin_cfg = get_path(yaml2, "income.financial_expense", {})
    base_fin_exp = 0.0
    if isinstance(fin_cfg, dict):
        base_fin_exp = cfg_year_float(fin_cfg, "base_fin_exp", idx)
    financial_expense = {
        "fin_exp": base_fin_exp,
        "fin_exp_int_exp": cfg_year_float(fin_cfg, "base_interest_expense", idx) if isinstance(fin_cfg, dict) else 0.0,
        "fin_exp_int_inc": cfg_year_float(fin_cfg, "base_interest_income", idx) if isinstance(fin_cfg, dict) else 0.0,
        "other_fin_exp": cfg_year_float(fin_cfg, "other_fin_exp_abs", idx) if isinstance(fin_cfg, dict) else 0.0,
    }
    last_key: tuple[float, float] | None = None
    income_row: dict[str, float] = {}
    bs_row: dict[str, float] = {}
    metrics: dict[str, float] = {}

    for _ in range(MAX_ITERATIONS):
        income_row = build_income_statement(yaml2, revenue, financial_expense, idx)
        bs_row, metrics = build_balance_sheet(yaml2, prev_bs, income_row, idx, None)
        next_financial_expense = financial_expense_from_balances(yaml2, prev_bs, bs_row, idx)
        key = (next_financial_expense["fin_exp"], bs_row.get("money_cap", 0.0) + bs_row.get("st_borr", 0.0))
        if last_key is not None and max(abs(key[0] - last_key[0]), abs(key[1] - last_key[1])) < CONVERGENCE_TOLERANCE:
            financial_expense = next_financial_expense
            break
        financial_expense = next_financial_expense
        last_key = key
    else:
        raise CalcError(f"{period} circular interest/plug calculation did not converge")

    income_row = build_income_statement(yaml2, revenue, financial_expense, idx)
    bs_row, metrics = build_balance_sheet(yaml2, prev_bs, income_row, idx, review_flags)
    return income_row, bs_row, metrics


def build_cash_flow(
    yaml2: dict[str, Any],
    prev_bs: dict[str, float],
    bs_row: dict[str, float],
    income_row: dict[str, float],
    metrics: dict[str, float],
    prev_nwc: float,
    idx: int,
) -> dict[str, float]:
    amort_intang = get_year_float(yaml2, "balance_sheet.amort_intang_assets", idx)
    lt_amort = get_year_float(yaml2, "balance_sheet.lt_amort_deferred_exp", idx)
    use_right_dep = get_year_float(yaml2, "balance_sheet.use_right_asset_dep", idx)
    da = metrics["depreciation"] + amort_intang + lt_amort + use_right_dep
    delta_nwc = metrics["nwc"] - prev_nwc
    cfo = income_row["n_income"] + da - delta_nwc
    cfi = -metrics["capex"]
    cash_change = bs_row.get("money_cap", 0.0) - prev_bs.get("money_cap", 0.0)
    cff = cash_change - cfo - cfi

    row = {
        "net_profit": income_row["n_income"],
        "depr_fa_coga_dpba": metrics["depreciation"],
        "amort_intang_assets": amort_intang,
        "lt_amort_deferred_exp": lt_amort,
        "use_right_asset_dep": use_right_dep,
        "n_cashflow_act": cfo,
        "n_cashflow_inv_act": cfi,
        "n_cash_flows_fnc_act": cff,
        "eff_fx_flu_cash": 0.0,
        "n_incr_cash_cash_equ": cash_change,
        "c_cash_equ_beg_period": prev_bs.get("money_cap", 0.0),
        "c_cash_equ_end_period": bs_row.get("money_cap", 0.0),
        "c_pay_acq_const_fiolta": metrics["capex"],
        "c_pay_dist_dpcp_int_exp": metrics["dividends"],
        "c_recp_borrow": max(cff + metrics["dividends"], 0.0),
        "c_prepay_amt_borr": max(-(cff + metrics["dividends"]), 0.0),
    }
    return row


def validate_accounting(period: str, bs_row: dict[str, float], cf_row: dict[str, float]) -> None:
    bs_residual = bs_row["total_assets"] - bs_row["total_liab_hldr_eqy"]
    if abs(bs_residual) > TOLERANCE:
        raise CalcError(f"{period} BS does not balance: residual={bs_residual:.6f}")
    cf_residual = (
        cf_row["c_cash_equ_beg_period"]
        + cf_row["n_incr_cash_cash_equ"]
        + cf_row.get("qa_cf_cash_reconcile_plug", 0.0)
        - cf_row["c_cash_equ_end_period"]
    )
    if abs(cf_residual) > TOLERANCE:
        raise CalcError(f"{period} CF cash bridge does not balance: residual={cf_residual:.6f}")


@dataclass
class ForecastBuildResult:
    """Intermediate result after building the three statements and explicit FCFF.

    This intentionally does not include any DCF-layer discounting or terminal
    value, so WACC / terminal assumptions can be changed without rebuilding the
    statements.
    """

    income_statement: pd.DataFrame
    balance_sheet: pd.DataFrame
    cash_flow: pd.DataFrame
    dcf: pd.DataFrame
    base_period: str
    forecast_years: int
    net_debt: float
    total_shares: float
    ticker: Any
    name: Any
    review_flags: list[dict[str, Any]]


def build_forecast_statements(yaml2: dict[str, Any]) -> ForecastBuildResult:
    """Build the three statements and explicit-period FCFF only.

    Does not apply any DCF discounting or terminal value.  The returned object
    can be passed to ``value_from_statements`` with different WACC / terminal
    assumptions.
    """
    base_period = str(get_path(yaml2, "base_period"))
    base_year = int(base_period[:4])
    years = as_int(get_path(yaml2, "model.forecast_years"))
    net_debt = as_float(get_path(yaml2, "market.net_debt"))
    total_shares = as_float(get_path(yaml2, "market.total_shares"))

    review_flags: list[dict[str, Any]] = []
    prev_bs = base_bs(yaml2)
    prev_nwc = as_float(get_path(yaml2, "cashflow.base_nwc"), operating_working_capital(prev_bs))
    revenue = as_float(get_path(yaml2, "income.revenue"))

    is_rows: list[dict[str, Any]] = []
    bs_rows: list[dict[str, Any]] = []
    cf_rows: list[dict[str, Any]] = []
    dcf_rows: list[dict[str, Any]] = []

    for idx in range(1, years + 1):
        period = str(base_year + idx)
        revenue_yoy = get_year_float(yaml2, "model.revenue_yoy", idx)
        revenue *= 1.0 + revenue_yoy
        income_row, bs_row, metrics = solve_forecast_year(
            yaml2,
            period,
            prev_bs,
            revenue,
            review_flags,
            idx,
        )
        cf_row = build_cash_flow(yaml2, prev_bs, bs_row, income_row, metrics, prev_nwc, idx)
        validate_accounting(period, bs_row, cf_row)

        for flag in review_flags:
            if flag.get("period") is None:
                flag["period"] = period

        ebit = income_row["operate_profit"] + income_row.get("fin_exp", 0.0)
        tax_rate = get_year_float(yaml2, "income.effective_tax_rate", idx)
        nopat = ebit * (1.0 - tax_rate)
        da = (
            cf_row["depr_fa_coga_dpba"]
            + cf_row["amort_intang_assets"]
            + cf_row["lt_amort_deferred_exp"]
            + cf_row["use_right_asset_dep"]
        )
        delta_nwc = metrics["nwc"] - prev_nwc
        fcff = nopat + da - metrics["capex"] - delta_nwc
        dcf_rows.append(
            {
                "period": period,
                "fcff": fcff,
                "nopat": nopat,
                "da": da,
                "capex": metrics["capex"],
                "delta_nwc": delta_nwc,
            }
        )

        is_rows.append({"period": period, **income_row})
        bs_rows.append({"period": period, **bs_row})
        cf_rows.append({"period": period, **cf_row})
        prev_bs = bs_row
        prev_nwc = metrics["nwc"]

    # Deduplicate identical review flags from consecutive negative cash periods.
    deduped_flags: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for flag in review_flags:
        key = (flag.get("code"), flag.get("period"), round(float(flag.get("value", 0.0)), 6))
        if key not in seen:
            seen.add(key)
            deduped_flags.append(flag)

    return ForecastBuildResult(
        income_statement=pd.DataFrame(is_rows),
        balance_sheet=pd.DataFrame(bs_rows),
        cash_flow=pd.DataFrame(cf_rows),
        dcf=pd.DataFrame(dcf_rows),
        base_period=base_period,
        forecast_years=years,
        net_debt=net_debt,
        total_shares=total_shares,
        ticker=get_path(yaml2, "ticker"),
        name=get_path(yaml2, "name"),
        review_flags=deduped_flags,
    )


def value_from_statements(
    build: ForecastBuildResult,
    *,
    wacc: float,
    terminal_growth: float,
    terminal_capex_da_ratio: float,
) -> dict[str, Any]:
    """Compute terminal value and DCF summary from a previously built forecast.

    The three statements and explicit-period FCFF are taken as given; only the
    discounting and terminal-value assumptions are applied here.
    """
    years = build.forecast_years
    dcf = build.dcf.copy()
    dcf["discount_factor"] = [1.0 / ((1.0 + wacc) ** idx) for idx in range(1, years + 1)]
    dcf["pv_fcff"] = dcf["fcff"] * dcf["discount_factor"]
    dcf = dcf[["period", "fcff", "discount_factor", "pv_fcff", "nopat", "da", "capex", "delta_nwc"]]

    last = dcf.iloc[-1]
    terminal_fcff = last["nopat"] + last["da"] * (1.0 - terminal_capex_da_ratio)
    terminal_value = terminal_fcff * (1.0 + terminal_growth) / (wacc - terminal_growth)
    terminal_pv = terminal_value / ((1.0 + wacc) ** years)
    pv_fcff = dcf["pv_fcff"].sum()
    enterprise_value = pv_fcff + terminal_pv
    equity_value = enterprise_value - build.net_debt
    per_share_value = equity_value / build.total_shares if build.total_shares else None

    return {
        "income_statement": build.income_statement,
        "balance_sheet": build.balance_sheet,
        "cash_flow": build.cash_flow,
        "dcf": dcf,
        "summary": {
            "ticker": build.ticker,
            "name": build.name,
            "base_period": build.base_period,
            "forecast_years": years,
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "terminal_capex_da_ratio": terminal_capex_da_ratio,
            "pv_fcff": pv_fcff,
            "terminal_value": terminal_value,
            "terminal_pv": terminal_pv,
            "enterprise_value": enterprise_value,
            "net_debt": build.net_debt,
            "equity_value": equity_value,
            "total_shares": build.total_shares,
            "per_share_value": per_share_value,
            "review_flags": build.review_flags,
        },
    }


def run_forecast(yaml2: dict[str, Any]) -> dict[str, Any]:
    """Run a full forecast using the assumptions embedded in ``yaml2``."""
    build = build_forecast_statements(yaml2)
    return value_from_statements(
        build,
        wacc=as_float(get_path(yaml2, "model.wacc")),
        terminal_growth=as_float(get_path(yaml2, "model.terminal_growth")),
        terminal_capex_da_ratio=as_float(
            get_path(yaml2, "model.terminal_capex_da_ratio"),
            DEFAULT_TERMINAL_CAPEX_DA_RATIO,
        ),
    )


def default_output_dir(defaults_path: Path) -> Path:
    return defaults_path.parent / "forecast"


def reset_forecast_dir(output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    if output_dir.name != "forecast":
        raise CalcError(f"Official forecast output directory must be named forecast: {output_dir}")
    if output_dir.exists() and not output_dir.is_dir():
        raise CalcError(f"Forecast output path exists and is not a directory: {output_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    reset_forecast_dir(output_dir)
    result["income_statement"].to_csv(output_dir / "forecast_is.csv", index=False, encoding="utf-8-sig")
    result["balance_sheet"].to_csv(output_dir / "forecast_bs.csv", index=False, encoding="utf-8-sig")
    result["cash_flow"].to_csv(output_dir / "forecast_cf.csv", index=False, encoding="utf-8-sig")
    result["dcf"].to_csv(output_dir / "dcf_detail.csv", index=False, encoding="utf-8-sig")
    summary = result["summary"]
    (output_dir / "dcf_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame([{k: v for k, v in summary.items() if k != "review_flags"}]).to_csv(
        output_dir / "dcf_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DCF from cleaned forecast parameters.")
    parser.add_argument("--forecast-params", required=True, help="Path to forecast_params.yaml (yearly YAML2)")
    parser.add_argument("--output-dir", help="Output forecast directory; must be named forecast")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    params_path = Path(args.forecast_params)
    if not params_path.exists():
        raise FileNotFoundError(f"forecast params not found: {params_path}")
    yaml2 = read_yaml2(params_path)
    result = run_forecast(yaml2)
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(params_path)
    write_outputs(result, output_dir)
    summary = result["summary"]
    print(f"Written forecast: {output_dir}")
    print(f"Per-share value: {summary['per_share_value']}")
    if summary["review_flags"]:
        print(f"Review flags: {len(summary['review_flags'])}")
        for flag in summary["review_flags"]:
            print(f"- {flag['period']} {flag['code']}: {flag['message']} ({flag['value']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
