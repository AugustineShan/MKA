from __future__ import annotations

import math

import pandas as pd

from src.derived_metrics import build_derived_metrics_from_frames, safe_div, yoy


def test_safe_div_and_yoy_guard_zero_and_missing_values():
    assert safe_div(10, 2) == 5
    assert safe_div(10, 0) is None
    assert safe_div(None, 3) is None
    assert yoy(120, 100) == 0.2
    assert math.isclose(yoy(108, -85), 193 / 85)
    assert math.isclose(yoy(-100, -85), -15 / 85)
    assert yoy(120, 0) is None


def test_build_derived_metrics_from_frames_computes_core_financial_metrics():
    income = pd.DataFrame(
        [
            {
                "period": 2023,
                "revenue": 1000.0,
                "total_revenue": 1000.0,
                "oper_cost": 700.0,
                "sell_exp": 80.0,
                "admin_exp": 50.0,
                "rd_exp": 20.0,
                "fin_exp": 10.0,
                "fin_exp_int_exp": 12.0,
                "total_cogs": 860.0,
                "operate_profit": 130.0,
                "total_profit": 120.0,
                "income_tax": 30.0,
                "n_income": 90.0,
                "minority_gain": 10.0,
                "n_income_attr_p": 80.0,
            },
            {
                "period": 2024,
                "revenue": 1200.0,
                "total_revenue": 1200.0,
                "oper_cost": 780.0,
                "sell_exp": 90.0,
                "admin_exp": 60.0,
                "rd_exp": 24.0,
                "fin_exp": 15.0,
                "fin_exp_int_exp": 18.0,
                "total_cogs": 969.0,
                "operate_profit": 210.0,
                "total_profit": 200.0,
                "income_tax": 50.0,
                "n_income": 150.0,
                "minority_gain": 20.0,
                "n_income_attr_p": 130.0,
            },
        ]
    )
    balance = pd.DataFrame(
        [
            {
                "period": 2023,
                "money_cap": 100.0,
                "st_borr": 40.0,
                "lt_borr": 60.0,
                "total_hldr_eqy_exc_min_int": 400.0,
                "total_hldr_eqy_inc_min_int": 430.0,
                "minority_int": 30.0,
                "total_assets": 900.0,
                "total_liab": 470.0,
                "total_share": 100.0,
            },
            {
                "period": 2024,
                "money_cap": 120.0,
                "st_borr": 50.0,
                "lt_borr": 70.0,
                "total_hldr_eqy_exc_min_int": 500.0,
                "total_hldr_eqy_inc_min_int": 540.0,
                "minority_int": 40.0,
                "total_assets": 1100.0,
                "total_liab": 560.0,
                "total_share": 100.0,
            },
        ]
    )
    cash_flow = pd.DataFrame(
        [
            {
                "period": 2023,
                "depr_fa_coga_dpba": 30.0,
                "amort_intang_assets": 5.0,
                "lt_amort_deferred_exp": 3.0,
                "use_right_asset_dep": 2.0,
                "n_cashflow_act": 140.0,
                "n_cashflow_inv_act": -80.0,
                "n_cash_flows_fnc_act": -20.0,
                "n_incr_cash_cash_equ": 40.0,
                "c_pay_acq_const_fiolta": 60.0,
                "c_recp_borrow": 30.0,
                "c_prepay_amt_borr": 15.0,
            },
            {
                "period": 2024,
                "depr_fa_coga_dpba": 40.0,
                "amort_intang_assets": 6.0,
                "lt_amort_deferred_exp": 3.0,
                "use_right_asset_dep": 1.0,
                "n_cashflow_act": 180.0,
                "n_cashflow_inv_act": -90.0,
                "n_cash_flows_fnc_act": -30.0,
                "n_incr_cash_cash_equ": 60.0,
                "c_pay_acq_const_fiolta": 70.0,
                "c_recp_borrow": 35.0,
                "c_prepay_amt_borr": 10.0,
            },
        ]
    )

    metrics = build_derived_metrics_from_frames(
        income_statement=income,
        balance_sheet=balance,
        cash_flow=cash_flow,
        dcf_summary={"ticker": "000001.SZ", "name": "测试公司", "base_period": 2024, "total_shares": 100.0},
        meta={"total_mv": "1300", "close": "13", "pe_ttm": "10", "pb": "2"},
    )

    row = metrics["annual"]["2024"]
    assert row["ebit"] == 225.0
    assert row["da"] == 50.0
    assert row["ebitda"] == 275.0
    assert row["eps"] == 1.3
    assert row["bvps"] == 5.0
    assert row["pe"] == 10.0
    assert row["pb"] == 2.6
    assert math.isclose(row["ev_ebitda"], 1300.0 / 275.0)
    assert row["revenue_yoy"] == 0.2
    assert row["gross_margin"] == 0.35
