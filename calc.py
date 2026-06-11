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
from pathlib import Path
from typing import Any

import pandas as pd

from clean import BS_FIELD_CATEGORIES, QA_FIELDS, bs_bucket_sum
from defaults_gen import (
    COGS_DAYS_FIELDS,
    INTEREST_BEARING_DEBT_FIELDS,
    REVENUE_DRIVER_FIELDS,
    operating_working_capital,
)
from yaml2_schema import REVIEW_FLAG_NEGATIVE_CASH, get_path, plain_value, read_yaml2


BASE_DIR = Path(__file__).resolve().parent
COMPANIES_DIR = BASE_DIR / "companies"
TOLERANCE = 1e-4
MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-7


class CalcError(RuntimeError):
    """Raised when the forecast violates accounting identities."""


def find_defaults_path(ticker: str) -> Path:
    code = ticker.split(".")[0]
    candidates = sorted(COMPANIES_DIR.glob(f"*_{code}/defaults.yaml"))
    if not candidates:
        raise FileNotFoundError(f"No defaults.yaml found for {ticker} under {COMPANIES_DIR}")
    return candidates[0]


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


def financial_expense_from_balances(yaml2: dict[str, Any], prev_bs: dict[str, float], bs_row: dict[str, float]) -> dict[str, float]:
    fin_cfg = get_path(yaml2, "income.financial_expense", {})
    if not isinstance(fin_cfg, dict):
        fin_cfg = {}
    mode = plain_value(fin_cfg.get("interest_mode", "circular_average_balance"))
    if mode == "historical_abs":
        fin_exp = as_float(fin_cfg.get("base_fin_exp"), as_float(get_path(yaml2, "income.cost_abs.fin_exp")))
        return {
            "fin_exp": fin_exp,
            "fin_exp_int_exp": as_float(fin_cfg.get("base_interest_expense")),
            "fin_exp_int_inc": as_float(fin_cfg.get("base_interest_income")),
            "other_fin_exp": fin_exp,
        }
    if mode != "circular_average_balance":
        raise CalcError(f"Unsupported financial expense mode: {mode}")

    debt_rate = as_float(fin_cfg.get("interest_expense_rate"))
    cash_rate = as_float(fin_cfg.get("cash_interest_rate"))
    other_fin_exp = as_float(fin_cfg.get("other_fin_exp_abs"))
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


def build_income_statement(yaml2: dict[str, Any], revenue: float, financial_expense: dict[str, float]) -> dict[str, float]:
    income = yaml2.get("income", {})
    gpm = as_float(get_path(yaml2, "income.gpm"))
    tax_rate = as_float(get_path(yaml2, "income.effective_tax_rate"))
    minority_ratio = as_float(get_path(yaml2, "income.minority_ratio"))

    revenue_items = value_map(income.get("revenue_items_abs") if isinstance(income, dict) else None)
    cost_rates = value_map(income.get("cost_rates") if isinstance(income, dict) else None)
    cost_abs = value_map(income.get("cost_abs") if isinstance(income, dict) else None)
    op_adj = value_map(income.get("operating_adjustments_abs") if isinstance(income, dict) else None)
    below_line = value_map(income.get("below_line_abs") if isinstance(income, dict) else None)

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

    cost_fields = set(["oper_cost", "fin_exp"]) | set(cost_rates) | set(cost_abs)
    row["total_cogs"] = sum(row.get(field, 0.0) for field in cost_fields)
    row["total_opcost"] = row["total_cogs"]

    for field, value in op_adj.items():
        row[field] = value
    row["operate_profit"] = row["total_revenue"] - row["total_cogs"] + sum(op_adj.values())

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
    review_flags: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    row = prev_bs.copy()
    revenue = income_row["revenue"]
    oper_cost = income_row["oper_cost"]
    bs_cfg = yaml2.get("balance_sheet", {})
    revenue_pct = value_map(bs_cfg.get("revenue_pct") if isinstance(bs_cfg, dict) else None)
    cogs_days = value_map(bs_cfg.get("cogs_days") if isinstance(bs_cfg, dict) else None)
    capex_pct = as_float(get_path(yaml2, "balance_sheet.capex_pct"))
    depr_rate = as_float(get_path(yaml2, "balance_sheet.depr_rate"))
    dividend_payout = as_float(get_path(yaml2, "balance_sheet.dividend_payout"))
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
        base_fin_exp = as_float(fin_cfg.get("base_fin_exp"))
    financial_expense = {
        "fin_exp": base_fin_exp,
        "fin_exp_int_exp": as_float(fin_cfg.get("base_interest_expense")) if isinstance(fin_cfg, dict) else 0.0,
        "fin_exp_int_inc": as_float(fin_cfg.get("base_interest_income")) if isinstance(fin_cfg, dict) else 0.0,
        "other_fin_exp": as_float(fin_cfg.get("other_fin_exp_abs")) if isinstance(fin_cfg, dict) else 0.0,
    }
    last_key: tuple[float, float] | None = None
    income_row: dict[str, float] = {}
    bs_row: dict[str, float] = {}
    metrics: dict[str, float] = {}

    for _ in range(MAX_ITERATIONS):
        income_row = build_income_statement(yaml2, revenue, financial_expense)
        bs_row, metrics = build_balance_sheet(yaml2, prev_bs, income_row, None)
        next_financial_expense = financial_expense_from_balances(yaml2, prev_bs, bs_row)
        key = (next_financial_expense["fin_exp"], bs_row.get("money_cap", 0.0) + bs_row.get("st_borr", 0.0))
        if last_key is not None and max(abs(key[0] - last_key[0]), abs(key[1] - last_key[1])) < CONVERGENCE_TOLERANCE:
            financial_expense = next_financial_expense
            break
        financial_expense = next_financial_expense
        last_key = key
    else:
        raise CalcError(f"{period} circular interest/plug calculation did not converge")

    income_row = build_income_statement(yaml2, revenue, financial_expense)
    bs_row, metrics = build_balance_sheet(yaml2, prev_bs, income_row, review_flags)
    return income_row, bs_row, metrics


def build_cash_flow(
    yaml2: dict[str, Any],
    prev_bs: dict[str, float],
    bs_row: dict[str, float],
    income_row: dict[str, float],
    metrics: dict[str, float],
    prev_nwc: float,
) -> dict[str, float]:
    amort_intang = as_float(get_path(yaml2, "balance_sheet.amort_intang_assets"))
    lt_amort = as_float(get_path(yaml2, "balance_sheet.lt_amort_deferred_exp"))
    use_right_dep = as_float(get_path(yaml2, "balance_sheet.use_right_asset_dep"))
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


def run_forecast(yaml2: dict[str, Any]) -> dict[str, Any]:
    base_period = str(get_path(yaml2, "base_period"))
    base_year = int(base_period[:4])
    years = as_int(get_path(yaml2, "model.forecast_years"))
    revenue_yoy = as_float(get_path(yaml2, "model.revenue_yoy"))
    wacc = as_float(get_path(yaml2, "model.wacc"))
    terminal_growth = as_float(get_path(yaml2, "model.terminal_growth"))
    tax_rate = as_float(get_path(yaml2, "income.effective_tax_rate"))
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
        revenue *= 1.0 + revenue_yoy
        income_row, bs_row, metrics = solve_forecast_year(
            yaml2,
            period,
            prev_bs,
            revenue,
            review_flags,
        )
        cf_row = build_cash_flow(yaml2, prev_bs, bs_row, income_row, metrics, prev_nwc)
        validate_accounting(period, bs_row, cf_row)

        for flag in review_flags:
            if flag.get("period") is None:
                flag["period"] = period

        ebit = income_row["operate_profit"] + income_row.get("fin_exp", 0.0)
        nopat = ebit * (1.0 - tax_rate)
        da = (
            cf_row["depr_fa_coga_dpba"]
            + cf_row["amort_intang_assets"]
            + cf_row["lt_amort_deferred_exp"]
            + cf_row["use_right_asset_dep"]
        )
        delta_nwc = metrics["nwc"] - prev_nwc
        fcff = nopat + da - metrics["capex"] - delta_nwc
        discount_factor = 1.0 / ((1.0 + wacc) ** idx)
        dcf_rows.append(
            {
                "period": period,
                "fcff": fcff,
                "discount_factor": discount_factor,
                "pv_fcff": fcff * discount_factor,
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

    last_fcff = dcf_rows[-1]["fcff"]
    terminal_value = last_fcff * (1.0 + terminal_growth) / (wacc - terminal_growth)
    terminal_pv = terminal_value / ((1.0 + wacc) ** years)
    pv_fcff = sum(row["pv_fcff"] for row in dcf_rows)
    enterprise_value = pv_fcff + terminal_pv
    equity_value = enterprise_value - net_debt
    per_share_value = equity_value / total_shares if total_shares else None

    # Deduplicate identical review flags from consecutive negative cash periods.
    deduped_flags: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for flag in review_flags:
        key = (flag.get("code"), flag.get("period"), round(float(flag.get("value", 0.0)), 6))
        if key not in seen:
            seen.add(key)
            deduped_flags.append(flag)

    return {
        "income_statement": pd.DataFrame(is_rows),
        "balance_sheet": pd.DataFrame(bs_rows),
        "cash_flow": pd.DataFrame(cf_rows),
        "dcf": pd.DataFrame(dcf_rows),
        "summary": {
            "ticker": get_path(yaml2, "ticker"),
            "name": get_path(yaml2, "name"),
            "base_period": base_period,
            "forecast_years": years,
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "pv_fcff": pv_fcff,
            "terminal_value": terminal_value,
            "terminal_pv": terminal_pv,
            "enterprise_value": enterprise_value,
            "net_debt": net_debt,
            "equity_value": equity_value,
            "total_shares": total_shares,
            "per_share_value": per_share_value,
            "review_flags": deduped_flags,
        },
    }


def default_output_dir(defaults_path: Path) -> Path:
    return defaults_path.parent / "forecast"


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
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
    parser = argparse.ArgumentParser(description="Run YAML2 default DCF forecast.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--defaults", help="Path to defaults.yaml")
    group.add_argument("--ticker", help="A-share ticker; defaults.yaml is located under companies/*_{code}/")
    parser.add_argument("--output-dir", help="Output forecast directory; defaults to company/forecast")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    defaults_path = Path(args.defaults) if args.defaults else find_defaults_path(args.ticker)
    yaml2 = read_yaml2(defaults_path)
    result = run_forecast(yaml2)
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(defaults_path)
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
