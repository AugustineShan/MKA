"""Generate YAML2 defaults.yaml from validated clean tables.

First implementation uses the latest annual clean row as the base period. It
does not make forecasts; it only turns audited historical state into complete
DCF engine defaults.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd

from clean import (
    BS_FIELD_CATEGORIES,
    IS_FIELD_CATEGORIES,
    QA_FIELDS,
)
from yaml2_schema import (
    DEFAULT_FORECAST_YEARS,
    DEFAULT_PLUG,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_WACC,
    YAML2_VERSION,
    param,
    write_yaml2,
)


BASE_DIR = Path(__file__).resolve().parent
COMPANIES_DIR = BASE_DIR / "companies"

REVENUE_RATE_FIELDS = [
    "biz_tax_surchg",
    "sell_exp",
    "admin_exp",
    "rd_exp",
    "other_bus_cost",
]

COST_ABS_EXCLUDE = {"oper_cost", *REVENUE_RATE_FIELDS}

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


def find_db_path(ticker: str) -> Path:
    code = ticker.split(".")[0]
    candidates = sorted(COMPANIES_DIR.glob(f"*_{code}/data.db"))
    if not candidates:
        raise FileNotFoundError(f"No data.db found for {ticker} under {COMPANIES_DIR}")
    return candidates[0]


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {str(k): str(v) for k, v in rows}


def read_latest_annual(conn: sqlite3.Connection) -> tuple[str, dict[str, float]]:
    df = pd.read_sql_query("SELECT * FROM clean_annual ORDER BY period DESC LIMIT 1", conn)
    if df.empty:
        raise ValueError("clean_annual is empty")
    row = df.iloc[0].to_dict()
    period = str(row.pop("period"))
    values = {str(k): to_float(v) for k, v in row.items()}
    for field in QA_FIELDS:
        values.setdefault(field, 0.0)
    return period, values


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        if value != value:
            return 0.0
    except TypeError:
        return 0.0
    return float(value)


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


def build_defaults(db_path: Path, ticker: str | None = None) -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as conn:
        meta = read_meta(conn)
        base_period, row = read_latest_annual(conn)

    ticker = ticker or meta.get("ticker") or ""
    name = meta.get("name") or db_path.parent.name
    revenue = row.get("revenue", 0.0)
    oper_cost = row.get("oper_cost", 0.0)
    total_profit = row.get("total_profit", 0.0)
    income_tax = row.get("income_tax", 0.0)
    n_income = row.get("n_income", 0.0)
    minority_gain = row.get("minority_gain", 0.0)
    n_income_attr_p = row.get("n_income_attr_p", 0.0)
    cogs_base = oper_cost
    fin_exp = row.get("fin_exp", 0.0)
    interest_expense = row.get("fin_exp_int_exp", 0.0)
    interest_income = row.get("fin_exp_int_inc", 0.0)

    cost_abs_fields = [
        field
        for field, category in IS_FIELD_CATEGORIES.items()
        if category == "cost_item" and field not in COST_ABS_EXCLUDE | {"fin_exp"}
    ]
    revenue_item_fields = [
        field
        for field, category in IS_FIELD_CATEGORIES.items()
        if category == "revenue_item" and field != "revenue"
    ]
    operating_adjustment_fields = [
        field for field, category in IS_FIELD_CATEGORIES.items() if category == "operating_adjustment"
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
    depreciable_assets = max(
        row.get("fix_assets", 0.0),
        row.get("fix_assets_total", 0.0),
        0.0,
    )
    dividend_basis = max(row.get("distr_profit_shrhder", 0.0), row.get("comshare_payable_dvd", 0.0), 0.0)
    dividend_payout = clamp(safe_div(dividend_basis, n_income_attr_p, 0.0), 0.0, 1.0)
    debt = sum(row.get(field, 0.0) for field in INTEREST_BEARING_DEBT_FIELDS)
    cash = row.get("money_cap", 0.0)

    bs_fields = sorted(set(BS_FIELD_CATEGORIES) | set(QA_FIELDS))
    base_bs = {
        field: param(row.get(field, 0.0), source_col("balancesheet", field))
        for field in bs_fields
    }

    revenue_pct = {
        field: param(safe_div(row.get(field, 0.0), revenue), f"{source_col('balancesheet', field)} / clean_annual.revenue")
        for field in REVENUE_DRIVER_FIELDS
    }
    cogs_days = {
        field: param(
            safe_div(row.get(field, 0.0), cogs_base) * 365.0,
            f"{source_col('balancesheet', field)} / clean_annual.oper_cost * 365",
        )
        for field in COGS_DAYS_FIELDS
    }

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
            "revenue_items_abs": build_param_map(revenue_item_fields, row, endpoint="income"),
            "gpm": param(1.0 - safe_div(oper_cost, revenue), "1 - clean_annual.oper_cost / clean_annual.revenue"),
            "cost_rates": {
                field: param(row.get(field, 0.0) / revenue if revenue else 0.0, f"{source_col('income', field)} / clean_annual.revenue")
                for field in REVENUE_RATE_FIELDS
            },
            "cost_abs": build_param_map(cost_abs_fields, row, endpoint="income"),
            "financial_expense": {
                "interest_mode": param(
                    "circular_average_balance",
                    "model_default",
                    "Engine computes fin_exp from average interest-bearing debt and cash.",
                ),
                "interest_expense_rate": param(
                    clamp(safe_div(interest_expense, debt, 0.0), 0.0, 1.0),
                    "clean_annual.fin_exp_int_exp / base_interest_bearing_debt",
                ),
                "cash_interest_rate": param(
                    clamp(safe_div(interest_income, cash, 0.0), 0.0, 1.0),
                    "clean_annual.fin_exp_int_inc / clean_annual.money_cap",
                ),
                "other_fin_exp_abs": param(
                    fin_exp - interest_expense + interest_income,
                    "clean_annual.fin_exp - clean_annual.fin_exp_int_exp + clean_annual.fin_exp_int_inc",
                    "财务费用 = 利息支出 - 利息收入 + 其他财务费用。",
                ),
                "base_interest_expense": param(interest_expense, "clean_annual.fin_exp_int_exp"),
                "base_interest_income": param(interest_income, "clean_annual.fin_exp_int_inc"),
                "base_fin_exp": param(fin_exp, "clean_annual.fin_exp"),
            },
            "operating_adjustments_abs": build_param_map(operating_adjustment_fields, row, endpoint="income"),
            "below_line_abs": build_param_map(below_line_fields, row, endpoint="income"),
            "effective_tax_rate": param(
                clamp(safe_div(income_tax, total_profit, 0.0), 0.0, 1.0),
                "clean_annual.income_tax / clean_annual.total_profit",
            ),
            "minority_ratio": param(
                clamp(safe_div(minority_gain, n_income, 0.0), 0.0, 1.0),
                "clean_annual.minority_gain / clean_annual.n_income",
            ),
        },
        "balance_sheet": {
            "base": base_bs,
            "revenue_pct": revenue_pct,
            "cogs_days": cogs_days,
            "capex_pct": param(safe_div(capex, revenue), "clean_annual.c_pay_acq_const_fiolta / clean_annual.revenue"),
            "depr_rate": param(
                clamp(safe_div(row.get("depr_fa_coga_dpba", 0.0), depreciable_assets, 0.0), 0.0, 1.0),
                "clean_annual.depr_fa_coga_dpba / fixed_assets_base",
            ),
            "amort_intang_assets": param(row.get("amort_intang_assets", 0.0), "clean_annual.amort_intang_assets"),
            "lt_amort_deferred_exp": param(row.get("lt_amort_deferred_exp", 0.0), "clean_annual.lt_amort_deferred_exp"),
            "use_right_asset_dep": param(row.get("use_right_asset_dep", 0.0), "clean_annual.use_right_asset_dep"),
            "dividend_payout": param(
                dividend_payout,
                "max(clean_annual.distr_profit_shrhder, clean_annual.comshare_payable_dvd) / clean_annual.n_income_attr_p",
                "Falls back to 0 if no dividend distribution field is present.",
            ),
        },
        "cashflow": {
            "capex": param(capex, "clean_annual.c_pay_acq_const_fiolta"),
            "da": param(da, "depr_fa_coga_dpba + amort_intang_assets + lt_amort_deferred_exp + use_right_asset_dep"),
            "base_nwc": param(operating_working_capital(row), "operating current assets - operating current liabilities"),
        },
        "review_flags": [],
    }
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
    return db_path.parent / "defaults.yaml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate YAML2 defaults.yaml from clean annual data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", help="A-share ticker, e.g. 300866.SZ")
    group.add_argument("--db", help="Path to companies/*/data.db")
    parser.add_argument("--output", help="Output defaults.yaml path; defaults to company directory")
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
