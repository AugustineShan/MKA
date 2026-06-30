"""Shared derived financial metrics for frontend and Boshi Excel output."""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.company_paths import db_path as company_db_path
from src.company_paths import forecast_dir as company_forecast_dir
from src.company_paths import modelking_dir
from src.defaults_gen import INTEREST_BEARING_DEBT_FIELDS, operating_working_capital
from src.quarterly_tracker import compute_quarterly_view


SCHEMA_VERSION = 1
DERIVED_METRICS_FILENAME = "derived_metrics.json"
DERIVED_ANNUAL_FILENAME = "derived_metrics_annual.csv"
DERIVED_QUARTERLY_FILENAME = "derived_metrics_quarterly.csv"
LOGGER = logging.getLogger(__name__)

DA_FIELDS = (
    "depr_fa_coga_dpba",
    "amort_intang_assets",
    "lt_amort_deferred_exp",
    "use_right_asset_dep",
)

IMPAIRMENT_FIELDS = (
    "assets_impair_loss",
    "credit_impa_loss",
    "oth_impair_loss_assets",
)

OPERATING_CURRENT_ASSET_FIELDS = (
    "notes_receiv",
    "accounts_receiv",
    "receiv_financing",
    "prepayment",
    "inventories",
    "oth_receiv",
    "contract_assets",
    "oth_cur_assets",
)

OPERATING_CURRENT_LIABILITY_FIELDS = (
    "notes_payable",
    "acct_payable",
    "adv_receipts",
    "contract_liab",
    "payroll_payable",
    "taxes_payable",
    "oth_payable",
    "oth_cur_liab",
)

ANNUAL_METRIC_LABELS: dict[str, str] = {
    "revenue": "营业收入",
    "revenue_yoy": "营业收入yoy",
    "oper_cost": "营业成本",
    "oper_cost_yoy": "营业成本yoy",
    "gross_profit": "毛利",
    "gross_margin": "毛利率",
    "biz_tax_surchg": "营业税金及附加",
    "biz_tax_surchg_rate": "营业税金及附加率",
    "sell_exp": "销售费用",
    "sell_exp_rate": "销售费用率",
    "admin_exp": "管理费用",
    "admin_exp_rate": "管理费用率",
    "rd_exp": "研发费用",
    "rd_exp_rate": "研发费用率",
    "fin_exp": "财务费用",
    "fin_exp_rate": "财务费用率",
    "total_cogs": "营业总成本",
    "total_cogs_rate": "营业总成本率",
    "operate_profit": "营业利润",
    "operate_margin": "营业利润率",
    "total_profit_margin": "利润总额率",
    "impairment": "减值准备",
    "impairment_rate": "减值准备率",
    "sgna": "SG&A",
    "sgna_rate": "SG&A/收入",
    "ebit": "EBIT",
    "ebit_margin": "EBIT率",
    "da": "折旧摊销",
    "ebitda": "EBITDA",
    "ebitda_margin": "EBITDA率",
    "invest_income_fv": "投资收益/公允价值变化",
    "non_operating_net": "营业外收支净额",
    "total_profit": "税前利润",
    "income_tax": "所得税",
    "effective_tax_rate": "有效税率",
    "minority_gain": "少数股东损益",
    "minority_gain_rate": "少数股东损益/税前利润",
    "n_income": "净利润",
    "n_income_yoy": "净利润yoy",
    "n_income_margin": "净利率",
    "n_income_attr_p": "归母净利润",
    "n_income_attr_p_yoy": "归母净利润yoy",
    "n_income_attr_p_margin": "归母净利率",
    "fixed_intangible_longterm_assets": "固定资产/无形资产/长期待摊",
    "operating_wc_assets": "营运资金资产方",
    "operating_wc_liabilities": "营运资金负债方",
    "operating_nwc": "营运资金净额",
    "invested_capital": "投入资本",
    "invested_capital_turnover": "投入资本周转率",
    "cash": "现金",
    "interest_bearing_debt": "带息负债",
    "net_cash": "净现金",
    "net_debt": "净负债",
    "minority_int": "少数股东权益",
    "parent_equity": "归母权益",
    "total_equity": "所有者权益",
    "total_assets": "资产总额",
    "total_liab": "负债总额",
    "cfo": "经营活动现金流",
    "capex": "资本开支",
    "investment_acquisition": "投资/收购",
    "cfi": "投资活动现金流",
    "equity_financing": "股本融资",
    "cff": "融资活动现金流",
    "debt_financing": "债务融资",
    "cash_net_change": "现金净变动",
    "net_cash_change": "净现金变化",
    "fcf": "FCF",
    "total_shares": "股本总额",
    "eps": "EPS",
    "bvps": "BVPS",
    "dps": "DPS",
    "pe": "PE",
    "pb": "PB",
    "dividend_yield": "股息率",
    "market_cap": "股票市值",
    "avg_minority_int": "平均少数股东权益",
    "avg_net_debt": "平均净负债",
    "enterprise_value": "EV",
    "ev_ebitda": "EV/EBITDA",
    "ev_sales": "EV/Sales",
    "tax_burden": "税收负担",
    "interest_burden": "利息负担",
    "sales_profit_margin": "销售利润率",
    "asset_turnover": "资产周转率",
    "roa": "ROA",
    "leverage": "杠杆比例",
    "roe": "ROE",
    "roic": "ROIC",
    "capex_to_revenue": "资本开支/收入",
    "capex_to_ebitda": "资本开支/EBITDA",
    "capex_to_da": "资本开支/折旧摊销",
    "asset_liability_ratio": "资产负债率",
    "net_debt_ratio": "净负债率",
    "ebitda_interest_coverage": "EBITDA/利息",
}

RATING_REPORT_METRICS: tuple[tuple[str, str], ...] = (
    ("revenue", "营业收入"),
    ("revenue_yoy", "营收YOY"),
    ("gross_margin", "毛利率"),
    ("n_income_attr_p", "归母净利润"),
    ("n_income_attr_p_yoy", "归母净利润YOY"),
    ("roe", "ROE"),
    ("eps", "EPS"),
    ("pe", "PE"),
    ("pb", "PB"),
    ("ev_ebitda", "EV/EBITDA"),
)


def to_float(value: Any) -> float | None:
    """Convert spreadsheet/database values to finite floats."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def safe_div(numerator: Any, denominator: Any) -> float | None:
    num = to_float(numerator)
    den = to_float(denominator)
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den


def yoy(current: Any, previous: Any) -> float | None:
    cur = to_float(current)
    prev = to_float(previous)
    if cur is None or prev is None:
        return None
    denominator = abs(prev) if prev < 0 else prev
    return safe_div(cur - prev, denominator)


def _sum_fields(row: dict[str, Any], fields: tuple[str, ...] | list[str]) -> float:
    return sum(to_float(row.get(field)) or 0.0 for field in fields)


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = to_float(value)
        if number is not None:
            return number
    return None


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _period_key(value: Any) -> str:
    number = to_float(value)
    if number is None:
        return str(value)
    return str(int(number))


def _records_by_period(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if df.empty or "period" not in df.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for record in df.to_dict(orient="records"):
        period = _period_key(record.get("period"))
        out[period] = {str(key): value for key, value in record.items() if str(key) != "period"}
    return out


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _read_meta(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("select key, value from meta").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows if value is not None}


def _json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_json_clean(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int | str | bool) or value is None:
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return number if math.isfinite(number) else None


def _market_snapshot(
    *,
    meta: dict[str, Any] | None,
    forecast_params: dict[str, Any] | None,
    dcf_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = meta or {}
    forecast_params = forecast_params or {}
    dcf_summary = dcf_summary or {}
    market = forecast_params.get("market") if isinstance(forecast_params.get("market"), dict) else {}

    total_shares = _first_number(
        dcf_summary.get("total_shares"),
        market.get("total_shares"),
        meta.get("total_share"),
        meta.get("total_shares"),
    )
    close = _first_number(market.get("close"), meta.get("close"))
    total_mv = _first_number(market.get("total_mv"), meta.get("total_mv"))
    if total_mv is None and close is not None and total_shares is not None:
        total_mv = close * total_shares

    return {
        "trade_date": meta.get("daily_basic_trade_date"),
        "close": close,
        "total_shares": total_shares,
        "float_shares": _first_number(market.get("float_share"), meta.get("float_share")),
        "total_mv": total_mv,
        "pe_ttm": _first_number(market.get("pe_ttm"), meta.get("pe_ttm")),
        "pb": _first_number(market.get("pb"), meta.get("pb")),
    }


def _live_market_enabled() -> bool:
    raw = os.environ.get("MKA_LIVE_MARKET_SNAPSHOT")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def refresh_market_snapshot(
    ticker: str | None,
    current: dict[str, Any] | None = None,
    *,
    today: dt.date | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Fetch the latest available daily_basic market snapshot when TuShare is configured.

    The forecast model stores market values in RMB million. TuShare daily_basic
    reports market cap in 10k RMB and share count in 10k shares; meta_from_daily_basic
    applies the same conversion used during init, keeping PE/PB/EV calculations aligned.
    """
    snapshot = dict(current or {})
    if not ticker or not _live_market_enabled():
        return snapshot, None
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("MKA_LIVE_MARKET_SNAPSHOT_IN_TESTS") != "1":
        return snapshot, None

    try:
        from src.data_fetcher import create_tushare_client, dataframe_empty, meta_from_daily_basic

        pro = create_tushare_client()
        run_date = today or dt.date.today()
        start = (run_date - dt.timedelta(days=45)).strftime("%Y%m%d")
        end = run_date.strftime("%Y%m%d")
        cal_df = pro.trade_cal(
            exchange="",
            start_date=start,
            end_date=end,
            is_open="1",
            fields="cal_date,is_open,pretrade_date",
        )
        if dataframe_empty(cal_df) or "cal_date" not in cal_df.columns:
            candidates = [(run_date - dt.timedelta(days=offset)).strftime("%Y%m%d") for offset in range(0, 16)]
        else:
            candidates = sorted((str(value) for value in cal_df["cal_date"].dropna().tolist()), reverse=True)

        fields = "ts_code,trade_date,total_share,float_share,total_mv,pe_ttm,pb,close"
        for trade_date in candidates[:16]:
            daily_df = pro.daily_basic(ts_code=ticker, trade_date=trade_date, fields=fields)
            if dataframe_empty(daily_df):
                continue
            meta = meta_from_daily_basic(daily_df)
            fresh = _market_snapshot(
                meta=meta,
                forecast_params={},
                dcf_summary={"total_shares": snapshot.get("total_shares")},
            )
            merged = {**snapshot, **{key: value for key, value in fresh.items() if value is not None}}
            merged["source"] = "tushare.daily_basic"
            return merged, None
    except Exception as exc:  # noqa: BLE001 - live quotes are best-effort only.
        LOGGER.warning("Latest market snapshot skipped for %s: %s", ticker, exc)
        return snapshot, f"latest market snapshot skipped: {exc}"

    warning = f"latest market snapshot skipped: daily_basic returned empty for {ticker}"
    LOGGER.warning(warning)
    return snapshot, warning


def _avg(current: Any, previous: Any) -> float | None:
    cur = to_float(current)
    prev = to_float(previous)
    if cur is None and prev is None:
        return None
    if cur is None:
        return prev
    if prev is None:
        return cur
    return (cur + prev) / 2.0


def _metric_row(metric: str, label: str, annual: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "metric": metric,
        "label": label,
        "values": {period: annual.get(period, {}).get(metric) for period in annual},
    }


def _build_quarterly_payload(quarterly_view: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quarterly_view:
        return None
    periods = [str(period) for period in quarterly_view.get("periods", [])]
    rows = list(quarterly_view.get("rows", []))
    row_values = {str(row.get("field")): dict(row.get("values", {})) for row in rows if row.get("field")}

    n_income = row_values.get("n_income", {})
    minority_gain = row_values.get("minority_gain", {})
    attr_values: dict[str, float | None] = {}
    for period in periods:
        net = to_float(n_income.get(period))
        minority = to_float(minority_gain.get(period)) or 0.0
        attr_values[period] = None if net is None else net - minority
    attr_yoy: dict[str, float | None] = {}
    for period in periods:
        year = period[:4]
        quarter = period[-2:]
        prior = f"{int(year) - 1}{quarter}" if year.isdigit() else ""
        attr_yoy[period] = yoy(attr_values.get(period), attr_values.get(prior))
    revenue_values = row_values.get("revenue", {})

    metrics_by_period = {}
    for period in periods:
        metrics_by_period[period] = {
            "revenue": to_float(revenue_values.get(period)),
            "revenue_yoy": to_float(row_values.get("revenue_yoy", {}).get(period)),
            "oper_cost": to_float(row_values.get("oper_cost", {}).get(period)),
            "oper_cost_yoy": to_float(row_values.get("oper_cost_yoy", {}).get(period)),
            "n_income_attr_p": attr_values.get(period),
            "n_income_attr_p_yoy": attr_yoy.get(period),
            "gross_margin": to_float(row_values.get("gross_margin", {}).get(period)),
            "sell_exp_rate": to_float(row_values.get("sell_exp_rate", {}).get(period)),
            "admin_exp_rate": to_float(row_values.get("admin_exp_rate", {}).get(period)),
            "rd_exp_rate": to_float(row_values.get("rd_exp_rate", {}).get(period)),
            "fin_exp_rate": to_float(row_values.get("fin_exp_rate", {}).get(period)),
            "effective_tax_rate": to_float(row_values.get("income_tax_rate", {}).get(period)),
            "n_income_attr_p_margin": safe_div(attr_values.get(period), revenue_values.get(period)),
        }

    return {
        "periods": periods,
        "rows": rows,
        "annual": quarterly_view.get("annual", {}),
        "variance": quarterly_view.get("variance", {}),
        "quarter_states": quarterly_view.get("quarter_states", {}),
        "period_states": quarterly_view.get("period_states", {}),
        "q4_flags": quarterly_view.get("q4_flags", []),
        "metrics_by_period": metrics_by_period,
    }


def build_derived_metrics_from_frames(
    *,
    income_statement: pd.DataFrame,
    balance_sheet: pd.DataFrame,
    cash_flow: pd.DataFrame,
    dcf_summary: dict[str, Any] | None = None,
    dcf_detail: pd.DataFrame | None = None,
    forecast_params: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    market_snapshot: dict[str, Any] | None = None,
    quarterly_view: dict[str, Any] | None = None,
    source_files: dict[str, str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build shared annual/quarterly/valuation metrics from statement frames."""
    is_by_period = _records_by_period(income_statement)
    bs_by_period = _records_by_period(balance_sheet)
    cf_by_period = _records_by_period(cash_flow)
    periods = sorted(set(is_by_period) & set(bs_by_period) & set(cf_by_period), key=lambda item: int(item))
    dcf_summary = dcf_summary or {}
    market = dict(market_snapshot or _market_snapshot(meta=meta, forecast_params=forecast_params, dcf_summary=dcf_summary))
    base_period = str(int(to_float(dcf_summary.get("base_period")) or int(periods[-1] if periods else 0)))
    ticker = dcf_summary.get("ticker") or (forecast_params or {}).get("ticker") or (meta or {}).get("ticker")
    name = dcf_summary.get("name") or (forecast_params or {}).get("name") or (meta or {}).get("name")

    annual: dict[str, dict[str, Any]] = {}
    previous_metrics: dict[str, Any] | None = None
    previous_bs: dict[str, Any] | None = None
    for period in periods:
        is_row = is_by_period[period]
        bs_row = bs_by_period[period]
        cf_row = cf_by_period[period]
        previous = previous_metrics or {}

        revenue = _first_number(is_row.get("revenue"), is_row.get("total_revenue"))
        total_revenue = _first_number(is_row.get("total_revenue"), revenue)
        oper_cost = to_float(is_row.get("oper_cost"))
        gross_profit = None if revenue is None or oper_cost is None else revenue - oper_cost
        biz_tax_surchg = to_float(is_row.get("biz_tax_surchg")) or 0.0
        sales_profit = None if gross_profit is None else gross_profit - biz_tax_surchg
        impairment = _sum_fields(is_row, IMPAIRMENT_FIELDS)
        sell_exp = to_float(is_row.get("sell_exp"))
        admin_exp = to_float(is_row.get("admin_exp"))
        rd_exp = to_float(is_row.get("rd_exp"))
        fin_exp = to_float(is_row.get("fin_exp"))
        total_cogs = to_float(is_row.get("total_cogs"))
        operate_profit = to_float(is_row.get("operate_profit"))
        ebit = (operate_profit or 0.0) + (fin_exp or 0.0)
        da = _sum_fields(cf_row, DA_FIELDS)
        ebitda = ebit + da
        invest_income_fv = (to_float(is_row.get("invest_income")) or 0.0) + (to_float(is_row.get("fv_value_chg_gain")) or 0.0)
        non_operating_net = (to_float(is_row.get("non_oper_income")) or 0.0) - (to_float(is_row.get("non_oper_exp")) or 0.0)
        total_profit = to_float(is_row.get("total_profit"))
        income_tax = to_float(is_row.get("income_tax"))
        n_income = to_float(is_row.get("n_income"))
        minority_gain = to_float(is_row.get("minority_gain"))
        n_income_attr_p = to_float(is_row.get("n_income_attr_p"))

        debt = _sum_fields(bs_row, INTEREST_BEARING_DEBT_FIELDS)
        cash = to_float(bs_row.get("money_cap"))
        net_debt = None if cash is None else debt - cash
        net_cash = None if net_debt is None else -net_debt
        parent_equity = to_float(bs_row.get("total_hldr_eqy_exc_min_int"))
        total_equity = to_float(bs_row.get("total_hldr_eqy_inc_min_int"))
        total_assets = to_float(bs_row.get("total_assets"))
        total_liab = to_float(bs_row.get("total_liab"))
        minority_int = to_float(bs_row.get("minority_int"))
        total_shares = _first_number(bs_row.get("total_share"), market.get("total_shares"))
        market_cap = market.get("total_mv")
        enterprise_value = None if market_cap is None or net_debt is None else market_cap + net_debt

        bs_float = {key: to_float(value) or 0.0 for key, value in bs_row.items()}
        operating_wc_assets = _sum_fields(bs_row, OPERATING_CURRENT_ASSET_FIELDS)
        operating_wc_liabilities = _sum_fields(bs_row, OPERATING_CURRENT_LIABILITY_FIELDS)
        operating_nwc = operating_working_capital(bs_float)
        fixed_assets = _sum_fields(bs_row, ("fix_assets", "cip", "intan_assets", "lt_amor_exp", "use_right_assets"))
        invested_capital = None
        if total_equity is not None and cash is not None:
            invested_capital = total_equity + debt - cash

        avg_assets = _avg(total_assets, previous_bs.get("total_assets") if previous_bs else None)
        avg_parent_equity = _avg(parent_equity, previous_bs.get("total_hldr_eqy_exc_min_int") if previous_bs else None)
        avg_total_equity = _avg(total_equity, previous_bs.get("total_hldr_eqy_inc_min_int") if previous_bs else None)
        avg_minority_int = _avg(minority_int, previous_bs.get("minority_int") if previous_bs else None)
        avg_net_debt = _avg(net_debt, previous.get("net_debt"))
        avg_invested_capital = _avg(invested_capital, previous.get("invested_capital"))
        tax_rate = safe_div(income_tax, total_profit)
        nopat = ebit * (1.0 - tax_rate) if tax_rate is not None else None

        cfo = to_float(cf_row.get("n_cashflow_act"))
        capex = to_float(cf_row.get("c_pay_acq_const_fiolta"))
        cfi = to_float(cf_row.get("n_cashflow_inv_act"))
        cff = to_float(cf_row.get("n_cash_flows_fnc_act"))
        debt_financing = (to_float(cf_row.get("c_recp_borrow")) or 0.0) - (to_float(cf_row.get("c_prepay_amt_borr")) or 0.0)
        cash_net_change = to_float(cf_row.get("n_incr_cash_cash_equ"))
        fcf = None if cfo is None or capex is None else cfo - capex
        net_cash_change = None if net_cash is None or previous.get("net_cash") is None else net_cash - previous["net_cash"]

        annual[period] = {
            "revenue": revenue,
            "revenue_yoy": yoy(revenue, previous.get("revenue")),
            "oper_cost": oper_cost,
            "oper_cost_yoy": yoy(oper_cost, previous.get("oper_cost")),
            "gross_profit": gross_profit,
            "gross_margin": safe_div(gross_profit, revenue),
            "biz_tax_surchg": biz_tax_surchg,
            "biz_tax_surchg_rate": safe_div(biz_tax_surchg, revenue),
            "sales_profit": sales_profit,
            "sales_profit_margin": safe_div(ebit, revenue),
            "sell_exp": sell_exp,
            "sell_exp_rate": safe_div(sell_exp, revenue),
            "admin_exp": admin_exp,
            "admin_exp_rate": safe_div(admin_exp, revenue),
            "rd_exp": rd_exp,
            "rd_exp_rate": safe_div(rd_exp, revenue),
            "fin_exp": fin_exp,
            "fin_exp_rate": safe_div(fin_exp, revenue),
            "total_cogs": total_cogs,
            "total_cogs_rate": safe_div(total_cogs, revenue),
            "operate_profit": operate_profit,
            "operate_margin": safe_div(operate_profit, revenue),
            "impairment": impairment,
            "impairment_rate": safe_div(impairment, revenue),
            "sgna": (sell_exp or 0.0) + (admin_exp or 0.0) + impairment,
            "sgna_rate": safe_div((sell_exp or 0.0) + (admin_exp or 0.0) + impairment, revenue),
            "ebit": ebit,
            "ebit_margin": safe_div(ebit, revenue),
            "da": da,
            "ebitda": ebitda,
            "ebitda_margin": safe_div(ebitda, revenue),
            "invest_income_fv": invest_income_fv,
            "non_operating_net": non_operating_net,
            "total_profit": total_profit,
            "total_profit_margin": safe_div(total_profit, revenue),
            "income_tax": income_tax,
            "effective_tax_rate": tax_rate,
            "minority_gain": minority_gain,
            "minority_gain_rate": safe_div(minority_gain, total_profit),
            "n_income": n_income,
            "n_income_yoy": yoy(n_income, previous.get("n_income")),
            "n_income_margin": safe_div(n_income, revenue),
            "n_income_attr_p": n_income_attr_p,
            "n_income_attr_p_yoy": yoy(n_income_attr_p, previous.get("n_income_attr_p")),
            "n_income_attr_p_margin": safe_div(n_income_attr_p, revenue),
            "fixed_intangible_longterm_assets": fixed_assets,
            "operating_wc_assets": operating_wc_assets,
            "operating_wc_liabilities": operating_wc_liabilities,
            "operating_nwc": operating_nwc,
            "invested_capital": invested_capital,
            "invested_capital_turnover": safe_div(revenue, invested_capital),
            "cash": cash,
            "interest_bearing_debt": debt,
            "net_cash": net_cash,
            "net_debt": net_debt,
            "minority_int": minority_int,
            "parent_equity": parent_equity,
            "total_equity": total_equity,
            "total_assets": total_assets,
            "total_liab": total_liab,
            "cfo": cfo,
            "capex": capex,
            "investment_acquisition": None if cfi is None or capex is None else cfi + capex,
            "cfi": cfi,
            "equity_financing": None,
            "cff": cff,
            "debt_financing": debt_financing,
            "cash_net_change": cash_net_change,
            "net_cash_change": net_cash_change,
            "fcf": fcf,
            "total_shares": total_shares,
            "eps": safe_div(n_income_attr_p, total_shares),
            "bvps": safe_div(parent_equity, total_shares),
            "dps": None,
            "pe": safe_div(market_cap, n_income_attr_p),
            "pb": safe_div(market_cap, parent_equity),
            "dividend_yield": None,
            "market_cap": market_cap,
            "avg_minority_int": avg_minority_int,
            "avg_net_debt": avg_net_debt,
            "enterprise_value": enterprise_value,
            "ev_ebitda": safe_div(enterprise_value, ebitda),
            "ev_sales": safe_div(enterprise_value, revenue),
            "tax_burden": safe_div(n_income, total_profit),
            "interest_burden": safe_div(total_profit, ebit),
            "asset_turnover": safe_div(revenue, avg_assets),
            "roa": safe_div(n_income, avg_assets),
            "leverage": safe_div(avg_assets, avg_total_equity),
            "roe": safe_div(n_income_attr_p, avg_parent_equity),
            "roic": safe_div(nopat, avg_invested_capital),
            "capex_to_revenue": safe_div(capex, revenue),
            "capex_to_ebitda": safe_div(capex, ebitda),
            "capex_to_da": safe_div(capex, da),
            "asset_liability_ratio": safe_div(total_liab, total_assets),
            "net_debt_ratio": safe_div(net_debt, parent_equity),
            "ebitda_interest_coverage": safe_div(ebitda, is_row.get("fin_exp_int_exp")),
        }
        previous_metrics = annual[period]
        previous_bs = bs_row

    valuation = dict(dcf_summary)
    if dcf_detail is not None and not dcf_detail.empty:
        valuation["dcf_detail_periods"] = [int(to_float(period) or 0) for period in dcf_detail.get("period", [])]
    if periods:
        first_forecast = min((period for period in periods if int(period) > int(base_period)), default=None)
        if first_forecast and first_forecast in annual:
            valuation["forward_pe"] = annual[first_forecast].get("pe")
            valuation["forward_pb"] = annual[first_forecast].get("pb")
            valuation["forward_ev_ebitda"] = annual[first_forecast].get("ev_ebitda")

    rating_rows = [_metric_row(metric, label, annual) for metric, label in RATING_REPORT_METRICS]

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "name": name,
        "base_period": base_period,
        "periods": periods,
        "market_snapshot": market,
        "annual": annual,
        "quarterly": _build_quarterly_payload(quarterly_view),
        "valuation": valuation,
        "rating_report_rows": rating_rows,
        "metric_labels": ANNUAL_METRIC_LABELS,
        "source_files": source_files or {},
        "warnings": warnings or [],
    }
    return _json_clean(result)


def build_derived_metrics(company_dir: str | Path, *, include_quarterly: bool = True) -> dict[str, Any]:
    company_path = Path(company_dir)
    forecast_path = company_forecast_dir(company_path)
    dcf_summary = _read_json(forecast_path / "dcf_summary.json")
    forecast_params_path = modelking_dir(company_path) / "forecast_params.yaml"
    forecast_params = _read_yaml(forecast_params_path)
    meta = _read_meta(company_db_path(company_path))
    warnings: list[str] = []
    ticker = str(dcf_summary.get("ticker") or forecast_params.get("ticker") or meta.get("ticker") or "")
    base_market = _market_snapshot(meta=meta, forecast_params=forecast_params, dcf_summary=dcf_summary)
    market_snapshot, market_warning = refresh_market_snapshot(ticker, base_market)
    if market_warning:
        warnings.append(market_warning)
    quarterly_view = None
    if include_quarterly:
        try:
            if ticker:
                quarterly_view = compute_quarterly_view(
                    db=company_db_path(company_path),
                    ticker=ticker,
                    company_dir=company_path,
                )
        except Exception as exc:  # noqa: BLE001 - surfaced as a non-blocking export warning.
            warnings.append(f"quarterly metrics skipped: {exc}")

    return build_derived_metrics_from_frames(
        income_statement=_read_csv(forecast_path / "full_is.csv"),
        balance_sheet=_read_csv(forecast_path / "full_bs.csv"),
        cash_flow=_read_csv(forecast_path / "full_cf.csv"),
        dcf_summary=dcf_summary,
        dcf_detail=_read_csv(forecast_path / "dcf_detail.csv"),
        forecast_params=forecast_params,
        meta=meta,
        market_snapshot=market_snapshot,
        quarterly_view=quarterly_view,
        source_files={
            "full_is": str(forecast_path / "full_is.csv"),
            "full_bs": str(forecast_path / "full_bs.csv"),
            "full_cf": str(forecast_path / "full_cf.csv"),
            "dcf_summary": str(forecast_path / "dcf_summary.json"),
            "dcf_detail": str(forecast_path / "dcf_detail.csv"),
            "forecast_params": str(forecast_params_path),
            "data_db": str(company_db_path(company_path)),
        },
        warnings=warnings,
    )


def write_derived_metrics_outputs(company_dir: str | Path, metrics: dict[str, Any]) -> dict[str, Path]:
    company_path = Path(company_dir)
    out_dir = company_forecast_dir(company_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / DERIVED_METRICS_FILENAME
    annual_path = out_dir / DERIVED_ANNUAL_FILENAME
    quarterly_path = out_dir / DERIVED_QUARTERLY_FILENAME

    json_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    annual = metrics.get("annual") if isinstance(metrics.get("annual"), dict) else {}
    metric_keys = sorted({key for row in annual.values() if isinstance(row, dict) for key in row})
    with annual_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["period", *metric_keys])
        writer.writeheader()
        for period in metrics.get("periods", []):
            row = annual.get(str(period), {}) if isinstance(annual, dict) else {}
            writer.writerow({"period": period, **{key: row.get(key) for key in metric_keys}})

    quarterly = metrics.get("quarterly") if isinstance(metrics.get("quarterly"), dict) else None
    with quarterly_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["period", "metric", "label", "value"])
        writer.writeheader()
        if quarterly:
            q_metrics = quarterly.get("metrics_by_period", {})
            labels = metrics.get("metric_labels", {})
            for period in quarterly.get("periods", []):
                row = q_metrics.get(str(period), {})
                for metric, value in row.items():
                    writer.writerow({"period": period, "metric": metric, "label": labels.get(metric, metric), "value": value})

    return {
        "json": json_path,
        "annual_csv": annual_path,
        "quarterly_csv": quarterly_path,
    }


def build_and_write_derived_metrics(company_dir: str | Path, *, include_quarterly: bool = True) -> tuple[dict[str, Any], dict[str, Path]]:
    metrics = build_derived_metrics(company_dir, include_quarterly=include_quarterly)
    return metrics, write_derived_metrics_outputs(company_dir, metrics)
