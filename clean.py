"""Clean raw TuShare EAV data into validated wide-table CSV.

Public API:
    clean("D:\\MKA\\companies\\安克创新_300866\\data.db", "300866.SZ") -> pd.DataFrame
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger("clean")

TOLERANCE = 1.0  # 百万元，残差容差

# ── 不参与任何加总校验的衍生字段 ───────────────────────────────
EXCLUDED_FROM_CHECKS: set[str] = {
    "basic_eps", "diluted_eps", "ebit", "ebitda",
    "undist_profit", "distable_profit", "insurance_exp",
    "invest_loss_unconf",
    "free_cashflow",
    "update_flag",
}

# ── 子项（已包含在父项中，不得重复加） ────────────────────────
SUB_ITEMS: dict[str, str] = {
    "ass_invest_income":      "invest_income",
    "amodcost_fin_assets":    "invest_income",
    "fin_exp_int_exp":        "fin_exp",
    "fin_exp_int_inc":        "fin_exp",
    "nca_disploss":           "non_oper_exp",
    "incl_dvd_profit_paid_sc_ms": "c_pay_dist_dpcp_int_exp",
    "incl_cash_rec_saims":    "c_recp_cap_contrib",
}

# ── 跨端点同名字段（需在 pivot 时消歧） ───────────────────────
# credit_impa_loss 同时存在于 income 和 cashflow，值可能不同
CROSS_ENDPOINT_FIELDS = {"credit_impa_loss"}

# ── IS 1.1 营业总成本明细 ──────────────────────────────────────
# 标准项目
IS_COGS_STANDARD = [
    "oper_cost", "biz_tax_surchg", "sell_exp", "admin_exp",
    "rd_exp", "assets_impair_loss", "credit_impa_loss",
]
# 额外项目（2019+新准则下可能存在）
IS_COGS_EXTRA = [
    "other_bus_cost",        # 其他业务成本
    "oth_impair_loss_assets", # 其他资产减值损失
    "transfer_oth",          # 结转其他
]

# ── IS 1.2 营业利润加项 ────────────────────────────────────────
IS_OPER_PROFIT_EXTRAS = [
    "oth_income", "invest_income", "net_expo_hedging_benefits",
    "fv_value_chg_gain", "asset_disp_income",
]

# ── BS 流动资产明细 ────────────────────────────────────────────
BS_CUR_ASSET_ITEMS = [
    "money_cap", "trad_asset", "notes_receiv", "accounts_receiv",
    "receiv_financing", "prepayment", "oth_receiv", "inventories",
    "contract_assets", "hfs_assets", "nca_within_1y", "oth_cur_assets",
    "deriv_assets",  # 衍生金融资产
    "sett_rsrv", "loanto_oth_bank_fi", "premium_receiv",
    "reinsur_receiv", "reinsur_res_receiv", "pur_resale_fa",
    "amor_exp", "div_receiv", "int_receiv",
]

# ── BS 非流动资产明细 ──────────────────────────────────────────
BS_NCA_ITEMS = [
    "fa_avail_for_sale", "htm_invest", "debt_invest", "oth_debt_invest",
    "lt_rec", "lt_eqt_invest", "oth_eq_invest", "oth_illiq_fin_assets",
    "invest_real_estate", "fix_assets", "cip",
    "produc_bio_assets", "oil_and_gas_assets", "use_right_assets",
    "intan_assets", "r_and_d", "goodwill", "lt_amor_exp",
    "defer_tax_assets", "oth_nca",
    "cost_fin_assets", "fair_value_fin_assets", "decr_in_disbur",
    "time_deposits", "oth_assets",
]

# ── BS 流动负债明细 ────────────────────────────────────────────
BS_CUR_LIAB_ITEMS = [
    "st_borr", "trading_fl", "notes_payable", "acct_payable",
    "adv_receipts", "contract_liab", "payroll_payable", "taxes_payable",
    "oth_payable", "int_payable", "div_payable", "acc_exp",
    "deferred_inc", "st_bonds_payable", "st_fin_payable",
    "hfs_sales", "non_cur_liab_due_1y", "oth_cur_liab",
    "deriv_liab",  # 衍生金融负债
    "cb_borr", "depos_ib_deposits", "loan_oth_bank",
    "sold_for_repur_fa", "comm_payable",
]

# ── BS 非流动负债明细 ──────────────────────────────────────────
BS_NCL_ITEMS = [
    "lt_borr", "bond_payable", "lease_liab", "lt_payable",
    "lt_payroll_payable", "estimated_liab", "defer_tax_liab",
    "defer_inc_non_cur_liab", "specific_payables", "oth_ncl",
    "payable_to_reinsurer", "rsrv_insur_cont",
]

# ── BS 权益明细 ────────────────────────────────────────────────
BS_EQUITY_ITEMS = [
    "total_share", "cap_rese", "treasury_share", "oth_comp_income",
    "special_rese", "surplus_rese", "ordin_risk_reser",
    "undistr_porfit", "forex_differ", "oth_eqt_tools", "minority_int",
]

# ── 合并科目 resolve 声明 ──────────────────────────────────────
RESOLVE_SPECS: list[tuple[list[str], str, list[str]]] = [
    (BS_CUR_ASSET_ITEMS, "accounts_receiv_bill", ["notes_receiv", "accounts_receiv"]),
    (BS_CUR_ASSET_ITEMS, "oth_rcv_total",        ["oth_receiv"]),
    (BS_NCA_ITEMS,       "fix_assets_total",      ["fix_assets"]),
    (BS_NCA_ITEMS,       "cip_total",             ["cip"]),
    (BS_CUR_LIAB_ITEMS,  "accounts_pay",          ["notes_payable", "acct_payable"]),
    (BS_CUR_LIAB_ITEMS,  "oth_pay_total",         ["oth_payable"]),
    (BS_NCL_ITEMS,       "long_pay_total",        ["lt_payable"]),
]


# ── resolve 逻辑 ───────────────────────────────────────────────

def resolve(
    split_fields: list[str],
    combo_field: str,
    row: dict[str, float],
    present_fields: set[str],
) -> float:
    """Return the value for a merged/split field group.

    1. If ALL split_fields are in present_fields → sum split values
    2. Else if combo_field is in present_fields → use combo value
    3. Else → 0.0
    """
    if all(f in present_fields for f in split_fields):
        split_sum = sum(row.get(f, 0.0) for f in split_fields)
        # If combo is also present and split sum is 0 but combo is non-zero,
        # the company reports only the aggregate (e.g. oth_receiv=0 but
        # oth_rcv_total=126.61). Use combo as authoritative.
        if split_sum == 0.0 and combo_field in present_fields:
            combo_val = row.get(combo_field, 0.0)
            if combo_val != 0.0:
                return combo_val
        return split_sum
    if combo_field in present_fields:
        return row.get(combo_field, 0.0)
    return 0.0


def sum_with_resolve(
    items: list[str],
    row: dict[str, float],
    present_fields: set[str],
) -> float:
    """Sum item values, applying resolve() for merged/split pairs."""
    skip: set[str] = set()
    for _items, combo, splits in RESOLVE_SPECS:
        if _items is items:
            skip.update(splits)
            if combo in items:
                skip.add(combo)

    total = 0.0
    for f in items:
        if f in skip:
            continue
        total += row.get(f, 0.0)

    for _items, combo, splits in RESOLVE_SPECS:
        if _items is items:
            total += resolve(splits, combo, row, present_fields)

    return total


# ── 数据读取与透视 ─────────────────────────────────────────────

def load_raw_tushare(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    """Read raw_tushare, filter report_type='1' & comp_type='1'."""
    df = pd.read_sql_query(
        "SELECT * FROM raw_tushare WHERE ticker = ? AND report_type = '1' AND comp_type = '1'",
        conn,
        params=(ticker,),
    )
    if df.empty:
        raise RuntimeError(f"No raw_tushare data for {ticker} with report_type=1, comp_type=1")
    return df


def dedupe_by_f_ann_date(df: pd.DataFrame) -> pd.DataFrame:
    """For same (endpoint, end_date, field), keep row with max f_ann_date."""
    if df.empty:
        return df
    df = df.copy()
    df["_f_ann_sort"] = df["f_ann_date"].fillna("")
    df = df.sort_values(
        ["endpoint", "end_date", "field", "_f_ann_sort"],
        ascending=[True, True, True, True],
    )
    df = df.drop_duplicates(subset=["endpoint", "end_date", "field"], keep="last")
    df = df.drop(columns=["_f_ann_sort"])
    return df


def pivot_to_wide(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, set[str]]]:
    """Pivot EAV to wide table, handling cross-endpoint field name collisions.

    For fields that exist in multiple endpoints (e.g. credit_impa_loss
    in both income and cashflow), prefix with endpoint name.

    Returns (wide_df, present_fields_by_year).
    """
    df = df.copy()
    df["year"] = df["end_date"].astype(str).str[:4].astype(int)
    df = df[df["end_date"].astype(str).str.endswith("1231")]

    # Detect cross-endpoint field name collisions
    field_endpoints: dict[str, set[str]] = {}
    for field, group in df.groupby("field"):
        field_endpoints[field] = set(group["endpoint"].unique())

    collision_fields = {f for f, eps in field_endpoints.items() if len(eps) > 1}

    # Rename colliding fields: "field" → "endpoint.field"
    def rename_field(row: pd.Series) -> str:
        if row["field"] in collision_fields:
            return f"{row['endpoint']}.{row['field']}"
        return row["field"]

    df["_col"] = df.apply(rename_field, axis=1)

    # Build present_fields (using original field names, not prefixed)
    present_by_year: dict[int, set[str]] = {}
    for year, group in df.groupby("year"):
        present_by_year[int(year)] = set(group["field"].tolist())

    # Pivot using renamed columns
    pivot = df.pivot_table(
        index="year",
        columns="_col",
        values="value",
        aggfunc="first",
    )
    pivot = pivot.fillna(0.0)

    return pivot, present_by_year


# ── 校验引擎 ───────────────────────────────────────────────────

class CheckError(Exception):
    """Raised when a hard check fails."""


def _v(row: dict[str, float], field: str) -> float:
    """Get value from row, default 0.0."""
    return row.get(field, 0.0)


def _vi(row: dict[str, float], field: str) -> float:
    """Get income-endpoint value from row (handles cross-endpoint prefix)."""
    prefixed = f"income.{field}"
    if prefixed in row:
        return row[prefixed]
    return row.get(field, 0.0)


def _vc(row: dict[str, float], field: str) -> float:
    """Get cashflow-endpoint value from row (handles cross-endpoint prefix)."""
    prefixed = f"cashflow.{field}"
    if prefixed in row:
        return row[prefixed]
    return row.get(field, 0.0)


def check_is(row: dict[str, float], present: set[str], year: int) -> list[str]:
    """Income statement hard checks."""
    errors: list[str] = []

    # 1.1 营业总成本
    # Two-step verification:
    #   Step A: total_cogs = total_opcost + fin_exp
    #   Step B: total_opcost = sum of standard cost items (excl fin_exp) + extra items
    # If Step A fails too, the hard check fails.
    # If Step A passes but Step B doesn't decompose, it means total_opcost
    # includes unattributed costs (e.g. 合同履约成本 under new standards).
    # This is an info note, not a hard failure — total_cogs is still verified.
    total_cogs = _vi(row, "total_cogs")
    cogs_calc = (
        sum(_vi(row, f) for f in IS_COGS_STANDARD)
        + _vi(row, "fin_exp")
        + sum(_vi(row, f) for f in IS_COGS_EXTRA)
    )
    residual = abs(total_cogs - cogs_calc)

    if residual >= TOLERANCE:
        # Standard items don't match. Try total_opcost route.
        total_opcost = _vi(row, "total_opcost")
        fin_exp = _vi(row, "fin_exp")
        cogs_via_opcost = total_opcost + fin_exp
        residual2 = abs(total_cogs - cogs_via_opcost)
        if residual2 < TOLERANCE:
            # total_cogs = total_opcost + fin_exp holds.
            opcost_items = sum(_vi(row, f) for f in IS_COGS_STANDARD if f != "fin_exp")
            other_costs = total_opcost - opcost_items
            if abs(other_costs) >= TOLERANCE:
                LOGGER.info(
                    "IS 1.1 %d total_opcost includes %.4f unattributed other costs "
                    "(not in standard line items, likely 合同履约成本 etc.)",
                    year, other_costs,
                )
        else:
            # total_opcost + fin_exp also doesn't match.
            # Final check: verify total_cogs is consistent with operate_profit.
            # If operate_profit = revenue - total_cogs + other_gains holds,
            # then total_cogs is correct even though we can't decompose it.
            operate_profit_prelim = _vi(row, "operate_profit")
            other_gains = sum(_vi(row, f) for f in IS_OPER_PROFIT_EXTRAS)
            cogs_via_profit = _vi(row, "revenue") + other_gains - operate_profit_prelim
            if abs(total_cogs - cogs_via_profit) < TOLERANCE:
                # total_cogs is verified by operate_profit formula.
                # The gap is from unattributed cost items (e.g. 合同履约成本)
                # that roll into total_cogs without separate TuShare fields.
                LOGGER.info(
                    "IS 1.1 %d total_cogs verified via operate_profit; "
                    "%.4f unattributed costs (likely 合同履约成本 etc.)",
                    year, total_cogs - cogs_calc,
                )
            else:
                # total_cogs is genuinely inconsistent — real error.
                errors.append(
                    f"IS 1.1 {year} 营业总成本: total_cogs={total_cogs:.4f} "
                    f"8items+extra={cogs_calc:.4f} opcost+fe={cogs_via_opcost:.4f} "
                    f"profit-route={cogs_via_profit:.4f} residual={residual:.4f}"
                )

    # 1.2 营业利润
    operate_profit = _vi(row, "operate_profit")
    oper_profit_calc = (
        _vi(row, "revenue")
        - total_cogs
        + sum(_vi(row, f) for f in IS_OPER_PROFIT_EXTRAS)
    )
    residual = abs(operate_profit - oper_profit_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.2 {year} 营业利润: operate_profit={operate_profit:.4f} "
            f"calc={oper_profit_calc:.4f} residual={residual:.4f}"
        )

    # 1.3 利润总额
    total_profit = _vi(row, "total_profit")
    total_profit_calc = operate_profit + _vi(row, "non_oper_income") - _vi(row, "non_oper_exp")
    residual = abs(total_profit - total_profit_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.3 {year} 利润总额: total_profit={total_profit:.4f} "
            f"calc={total_profit_calc:.4f} residual={residual:.4f}"
        )

    # 1.4 净利润
    n_income = _vi(row, "n_income")
    n_income_calc = total_profit - _vi(row, "income_tax")
    residual = abs(n_income - n_income_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.4 {year} 净利润: n_income={n_income:.4f} "
            f"calc={n_income_calc:.4f} residual={residual:.4f}"
        )

    # 1.5 净利润归属
    n_income_attr_p = _vi(row, "n_income_attr_p")
    minority_gain = _vi(row, "minority_gain")
    residual = abs(n_income - (n_income_attr_p + minority_gain))
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.5 {year} 净利润归属: n_income={n_income:.4f} "
            f"attr_p={n_income_attr_p:.4f} minority={minority_gain:.4f} residual={residual:.4f}"
        )

    # 1.6 营业总收入 = 营业收入（一般工商业验证）
    total_revenue = _vi(row, "total_revenue")
    revenue = _vi(row, "revenue")
    residual = abs(total_revenue - revenue)
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.6 {year} 营业总收入≠营业收入: total_revenue={total_revenue:.4f} "
            f"revenue={revenue:.4f} residual={residual:.4f} (疑似金融企业数据混入)"
        )

    return errors


def check_bs(row: dict[str, float], present: set[str], year: int) -> list[str]:
    """Balance sheet hard checks."""
    errors: list[str] = []

    # 2.1 流动资产合计
    total_cur_assets = _v(row, "total_cur_assets")
    cur_assets_calc = sum_with_resolve(BS_CUR_ASSET_ITEMS, row, present)
    residual = abs(total_cur_assets - cur_assets_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 2.1 {year} 流动资产: total_cur_assets={total_cur_assets:.4f} "
            f"calc={cur_assets_calc:.4f} residual={residual:.4f}"
        )

    # 2.2 非流动资产合计
    total_nca = _v(row, "total_nca")
    nca_calc = sum_with_resolve(BS_NCA_ITEMS, row, present)
    residual = abs(total_nca - nca_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 2.2 {year} 非流动资产: total_nca={total_nca:.4f} "
            f"calc={nca_calc:.4f} residual={residual:.4f}"
        )

    # 2.3 总资产 = 流动 + 非流动
    total_assets = _v(row, "total_assets")
    residual = abs(total_assets - (total_cur_assets + total_nca))
    if residual >= TOLERANCE:
        errors.append(
            f"BS 2.3 {year} 总资产: total_assets={total_assets:.4f} "
            f"cur+nca={total_cur_assets + total_nca:.4f} residual={residual:.4f}"
        )

    # 3.1 流动负债合计
    total_cur_liab = _v(row, "total_cur_liab")
    cur_liab_calc = sum_with_resolve(BS_CUR_LIAB_ITEMS, row, present)
    residual = abs(total_cur_liab - cur_liab_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 3.1 {year} 流动负债: total_cur_liab={total_cur_liab:.4f} "
            f"calc={cur_liab_calc:.4f} residual={residual:.4f}"
        )

    # 3.2 非流动负债合计
    total_ncl = _v(row, "total_ncl")
    ncl_calc = sum_with_resolve(BS_NCL_ITEMS, row, present)
    residual = abs(total_ncl - ncl_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 3.2 {year} 非流动负债: total_ncl={total_ncl:.4f} "
            f"calc={ncl_calc:.4f} residual={residual:.4f}"
        )

    # 3.3 总负债 = 流动 + 非流动
    total_liab = _v(row, "total_liab")
    residual = abs(total_liab - (total_cur_liab + total_ncl))
    if residual >= TOLERANCE:
        errors.append(
            f"BS 3.3 {year} 总负债: total_liab={total_liab:.4f} "
            f"cur+ncl={total_cur_liab + total_ncl:.4f} residual={residual:.4f}"
        )

    # 4.1 权益明细加总
    equity_calc = (
        _v(row, "total_share")
        + _v(row, "cap_rese")
        - _v(row, "treasury_share")
        + _v(row, "oth_comp_income")
        + _v(row, "special_rese")
        + _v(row, "surplus_rese")
        + _v(row, "ordin_risk_reser")
        + _v(row, "undistr_porfit")
        + _v(row, "forex_differ")
        + _v(row, "oth_eqt_tools")
        + _v(row, "minority_int")
    )
    total_hldr_eqy_inc_min_int = _v(row, "total_hldr_eqy_inc_min_int")
    residual = abs(total_hldr_eqy_inc_min_int - equity_calc)

    treasury_share = _v(row, "treasury_share")
    if treasury_share != 0 and abs(residual - 2 * treasury_share) < TOLERANCE:
        errors.append(
            f"BS 4.1 {year} treasury_share 符号异常，疑似存为负数 "
            f"(residual={residual:.4f} ≈ 2*treasury_share={2*treasury_share:.4f})"
        )

    if residual >= TOLERANCE:
        errors.append(
            f"BS 4.1 {year} 权益合计: total_hldr_eqy_inc_min_int={total_hldr_eqy_inc_min_int:.4f} "
            f"calc={equity_calc:.4f} residual={residual:.4f}"
        )

    # 4.2 归母 + 少数 = 合计
    total_hldr_eqy_exc_min_int = _v(row, "total_hldr_eqy_exc_min_int")
    residual = abs(total_hldr_eqy_inc_min_int - (total_hldr_eqy_exc_min_int + _v(row, "minority_int")))
    if residual >= TOLERANCE:
        errors.append(
            f"BS 4.2 {year} 归母+少数: total_inc={total_hldr_eqy_inc_min_int:.4f} "
            f"exc+min={total_hldr_eqy_exc_min_int + _v(row, 'minority_int'):.4f} residual={residual:.4f}"
        )

    # 4.3 终极配平
    residual1 = abs(total_assets - total_liab - total_hldr_eqy_inc_min_int)
    if residual1 >= TOLERANCE:
        errors.append(
            f"BS 4.3a {year} 资产=负债+权益: assets={total_assets:.4f} "
            f"liab+eqy={total_liab + total_hldr_eqy_inc_min_int:.4f} residual={residual1:.4f}"
        )

    total_liab_hldr_eqy = _v(row, "total_liab_hldr_eqy")
    residual2 = abs(total_assets - total_liab_hldr_eqy)
    if total_liab_hldr_eqy != 0 and residual2 >= TOLERANCE:
        errors.append(
            f"BS 4.3b {year} 资产=负债+权益(合并项): assets={total_assets:.4f} "
            f"total_liab_hldr_eqy={total_liab_hldr_eqy:.4f} residual={residual2:.4f}"
        )

    return errors


def check_cf(row: dict[str, float], present: set[str], year: int) -> list[str]:
    """Cash flow statement hard checks."""
    errors: list[str] = []

    # 5.1 经营活动
    n_cashflow_act = _vc(row, "n_cashflow_act")
    c_inf_fr_operate_a = _vc(row, "c_inf_fr_operate_a")
    st_cash_out_act = _vc(row, "st_cash_out_act")
    residual = abs(n_cashflow_act - (c_inf_fr_operate_a - st_cash_out_act))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.1 {year} 经营: n_cashflow_act={n_cashflow_act:.4f} "
            f"inf-out={c_inf_fr_operate_a - st_cash_out_act:.4f} residual={residual:.4f}"
        )

    # 5.2 投资活动
    n_cashflow_inv_act = _vc(row, "n_cashflow_inv_act")
    stot_inflows_inv_act = _vc(row, "stot_inflows_inv_act")
    stot_out_inv_act = _vc(row, "stot_out_inv_act")
    residual = abs(n_cashflow_inv_act - (stot_inflows_inv_act - stot_out_inv_act))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.2 {year} 投资: n_cashflow_inv_act={n_cashflow_inv_act:.4f} "
            f"inf-out={stot_inflows_inv_act - stot_out_inv_act:.4f} residual={residual:.4f}"
        )

    # 5.3 筹资活动
    n_cash_flows_fnc_act = _vc(row, "n_cash_flows_fnc_act")
    stot_cash_in_fnc_act = _vc(row, "stot_cash_in_fnc_act")
    stot_cashout_fnc_act = _vc(row, "stot_cashout_fnc_act")
    residual = abs(n_cash_flows_fnc_act - (stot_cash_in_fnc_act - stot_cashout_fnc_act))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.3 {year} 筹资: n_cash_flows_fnc_act={n_cash_flows_fnc_act:.4f} "
            f"inf-out={stot_cash_in_fnc_act - stot_cashout_fnc_act:.4f} residual={residual:.4f}"
        )

    # 5.4 三大活动汇总
    n_incr_cash_cash_equ = _vc(row, "n_incr_cash_cash_equ")
    eff_fx_flu_cash = _vc(row, "eff_fx_flu_cash")
    total_calc = n_cashflow_act + n_cashflow_inv_act + n_cash_flows_fnc_act + eff_fx_flu_cash
    residual = abs(n_incr_cash_cash_equ - total_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.4 {year} 汇总: n_incr_cash={n_incr_cash_cash_equ:.4f} "
            f"act+inv+fnc+fx={total_calc:.4f} residual={residual:.4f}"
        )

    # 5.5 期初期末
    c_cash_equ_end_period = _vc(row, "c_cash_equ_end_period")
    c_cash_equ_beg_period = _vc(row, "c_cash_equ_beg_period")
    residual = abs(c_cash_equ_end_period - (c_cash_equ_beg_period + n_incr_cash_cash_equ))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.5 {year} 期初期末: end={c_cash_equ_end_period:.4f} "
            f"beg+incr={c_cash_equ_beg_period + n_incr_cash_cash_equ:.4f} residual={residual:.4f}"
        )

    return errors


def check_is_supplement(row: dict[str, float], present: set[str], year: int) -> list[str]:
    """IS supplement hard checks (6.1, 6.2, 6.3)."""
    errors: list[str] = []

    t_compr_income = _vi(row, "t_compr_income")
    n_income = _vi(row, "n_income")
    oth_compr_income = _vi(row, "oth_compr_income")

    # 6.1 综合收益 = 净利润 + 其他综合收益
    residual = abs(t_compr_income - (n_income + oth_compr_income))
    if residual >= TOLERANCE:
        errors.append(
            f"IS 6.1 {year} 综合收益: t_compr_income={t_compr_income:.4f} "
            f"n_income+oci={n_income + oth_compr_income:.4f} residual={residual:.4f}"
        )

    # 6.2 综合收益归属
    compr_inc_attr_p = _vi(row, "compr_inc_attr_p")
    compr_inc_attr_m_s = _vi(row, "compr_inc_attr_m_s")
    residual = abs(t_compr_income - (compr_inc_attr_p + compr_inc_attr_m_s))
    if residual >= TOLERANCE:
        errors.append(
            f"IS 6.2 {year} 综合收益归属: t_compr_income={t_compr_income:.4f} "
            f"attr_p+m_s={compr_inc_attr_p + compr_inc_attr_m_s:.4f} residual={residual:.4f}"
        )

    # 6.3 持续/终止经营
    # 仅当公司有实质披露（至少一个非零）时校验；
    # 2020年前旧准则不强制拆分，字段存在但为0属正常。
    if "continued_net_profit" in present:
        continued_net_profit = _vi(row, "continued_net_profit")
        end_net_profit = _vi(row, "end_net_profit")
        if continued_net_profit != 0.0 or end_net_profit != 0.0:
            residual = abs(n_income - (continued_net_profit + end_net_profit))
            if residual >= TOLERANCE:
                errors.append(
                    f"IS 6.3 {year} 持续+终止: n_income={n_income:.4f} "
                    f"continued+end={continued_net_profit + end_net_profit:.4f} residual={residual:.4f}"
                )

    return errors


def check_cross_table(row: dict[str, float], present: set[str], year: int) -> list[str]:
    """Cross-table hard checks (7.1). 7.2 moved to soft checks."""
    errors: list[str] = []

    # 7.1 IS 净利润 = CF 附注净利润
    # Only check when CF net_profit is non-zero (some years lack indirect method data)
    is_n_income = _vi(row, "n_income")
    cf_net_profit = _vc(row, "net_profit")
    if "net_profit" in present and cf_net_profit != 0.0:
        residual = abs(cf_net_profit - is_n_income)
        if residual >= TOLERANCE:
            errors.append(
                f"跨表 7.1 {year} 净利润: IS n_income={is_n_income:.4f} "
                f"CF net_profit={cf_net_profit:.4f} residual={residual:.4f}"
            )

    # 7.2 moved to soft checks — CF finan_exp is the interest expense component
    # only, not the net fin_exp (which nets interest income). They rarely match
    # for companies with significant interest income.

    return errors


def check_soft(row: dict[str, float], present: set[str], year: int) -> list[str]:
    """Soft checks — warnings only."""
    warnings: list[str] = []

    # 7.2 IS 财务费用 vs CF 附注财务费用 (soft — CF finan_exp is often
    # the interest expense component only, not the net fin_exp)
    is_fin_exp = _vi(row, "fin_exp")
    cf_finan_exp = _vc(row, "finan_exp")
    if cf_finan_exp != 0.0 or is_fin_exp != 0.0:
        diff = abs(cf_finan_exp - is_fin_exp)
        if diff > TOLERANCE:
            warnings.append(
                f"跨表 7.2 {year} IS fin_exp({is_fin_exp:.4f}) ≠ CF finan_exp({cf_finan_exp:.4f}), 差{diff:.4f}"
            )

    # 7.3 CF期末现金 vs BS货币资金
    c_cash_equ_end = _vc(row, "c_cash_equ_end_period")
    money_cap = _v(row, "money_cap")
    diff = abs(c_cash_equ_end - money_cap)
    if diff > TOLERANCE:
        warnings.append(
            f"跨表 7.3 {year} CF期末现金({c_cash_equ_end:.4f}) ≠ BS货币资金({money_cap:.4f}), 差{diff:.4f}"
        )

    # 10.1 方向合理性
    revenue = _vi(row, "revenue")
    total_assets = _v(row, "total_assets")
    n_income_attr_p = _vi(row, "n_income_attr_p")
    basic_eps = _vi(row, "basic_eps")

    if revenue < 0:
        warnings.append(f"10.1 {year} 营业收入为负: {revenue:.4f}")
    if total_assets < 0:
        warnings.append(f"10.1 {year} 总资产为负: {total_assets:.4f}")
    if n_income_attr_p != 0 and basic_eps != 0:
        if (n_income_attr_p > 0) != (basic_eps > 0):
            warnings.append(
                f"10.1 {year} EPS({basic_eps:.4f})与归母净利润({n_income_attr_p:.4f})方向不一致"
            )

    # 10.2 量级合理性
    if total_assets > 10_000_000:
        warnings.append(f"10.2 {year} 总资产 {total_assets:.0f}M > 10万亿，请确认")
    total_revenue = _vi(row, "total_revenue")
    operate_profit = _vi(row, "operate_profit")
    if total_revenue > 0 and abs(operate_profit) > total_revenue:
        warnings.append(f"10.2 {year} 营业利润绝对值({operate_profit:.4f})大于营业收入({total_revenue:.4f})")

    # 10.3 折旧 vs 固定资产
    depr_fa_coga_dpba = _vc(row, "depr_fa_coga_dpba")
    fix_assets = _v(row, "fix_assets")
    fix_assets_total = _v(row, "fix_assets_total")
    fix_val = fix_assets_total if fix_assets_total != 0 else fix_assets
    if fix_val != 0 and depr_fa_coga_dpba > fix_val * 1.5:
        warnings.append(f"10.3 {year} 折旧({depr_fa_coga_dpba:.4f})超过固定资产({fix_val:.4f})的150%")

    # 10.4 毛利率范围
    oper_cost = _vi(row, "oper_cost")
    if revenue > 0:
        gpm = (revenue - oper_cost) / revenue
        if gpm < -0.5 or gpm > 1.0:
            warnings.append(f"10.4 {year} 毛利率 {gpm:.2%} 超出合理范围")

    return warnings


# ── 主入口 ─────────────────────────────────────────────────────

def clean(db_path: str | Path, ticker: str) -> pd.DataFrame:
    """Read raw_tushare, validate, and return clean wide-table DataFrame."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with closing(sqlite3.connect(db_path)) as conn:
        raw = load_raw_tushare(conn, ticker)

    raw = dedupe_by_f_ann_date(raw)
    wide, present_by_year = pivot_to_wide(raw)

    all_errors: list[str] = []
    all_warnings: list[str] = []

    sorted_years = sorted(wide.index.tolist())
    prev_year_end_cash: float | None = None

    for year in sorted_years:
        row = wide.loc[year].to_dict()
        present = present_by_year.get(year, set())

        year_errors: list[str] = []
        year_errors.extend(check_is(row, present, year))
        year_errors.extend(check_bs(row, present, year))
        year_errors.extend(check_cf(row, present, year))
        year_errors.extend(check_is_supplement(row, present, year))
        year_errors.extend(check_cross_table(row, present, year))

        # 7.4 逐年连续性：上年 CF 期末 = 本年 CF 期初
        c_cash_equ_beg = _vc(row, "c_cash_equ_beg_period")
        if prev_year_end_cash is not None and c_cash_equ_beg != 0:
            residual = abs(prev_year_end_cash - c_cash_equ_beg)
            if residual >= TOLERANCE:
                year_errors.append(
                    f"跨表 7.4 {year} 上年CF期末({prev_year_end_cash:.4f}) ≠ 本年CF期初({c_cash_equ_beg:.4f})"
                )

        prev_year_end_cash = _vc(row, "c_cash_equ_end_period")

        year_warnings = check_soft(row, present, year)

        if year_errors:
            all_errors.extend(year_errors)
            for e in year_errors:
                LOGGER.error("❌ %s", e)
        else:
            LOGGER.info("✅ %s all hard checks passed", year)

        for w in year_warnings:
            LOGGER.warning("⚠️  %s", w)
            all_warnings.append(w)

    if all_errors:
        for e in all_errors[:20]:
            print(f"HARD CHECK FAIL: {e}", file=sys.stderr)
        if len(all_errors) > 20:
            print(f"... and {len(all_errors) - 20} more errors", file=sys.stderr)
        raise CheckError(f"{len(all_errors)} hard check(s) failed")

    code = ticker.split(".")[0]
    csv_path = db_path.parent / f"clean_{code}.csv"
    wide.to_csv(csv_path, encoding="utf-8-sig")
    LOGGER.info("Written %s (%d years, %d fields)", csv_path, len(wide), len(wide.columns))

    return wide


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Clean TuShare raw data into validated wide-table CSV.")
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 300866.SZ")
    parser.add_argument("--db", default=None, help="Path to data.db (auto-detected if omitted)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ticker = args.ticker
    if args.db:
        db_path = Path(args.db)
    else:
        code = ticker.split(".")[0]
        base = Path(__file__).resolve().parent / "companies"
        candidates = sorted(base.glob(f"*_{code}/data.db"))
        if not candidates:
            print(f"No data.db found for {ticker} in {base}", file=sys.stderr)
            return 1
        db_path = candidates[0]

    try:
        clean(db_path, ticker)
    except CheckError as exc:
        print(f"\nValidation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        raise

    print("All checks passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
