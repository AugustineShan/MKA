"""Unit tests for clean.py core logic."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src import clean


class TestResolve:
    """Tests for the combo-field resolve() helper."""

    def test_all_splits_present_uses_split_sum(self):
        row = {"notes_receiv": 10.0, "accounts_receiv": 20.0, "accounts_receiv_bill": 999.0}
        present = {"notes_receiv", "accounts_receiv"}
        assert clean.resolve(["notes_receiv", "accounts_receiv"], "accounts_receiv_bill", row, present) == 30.0

    def test_missing_splits_uses_combo(self):
        row = {"accounts_receiv_bill": 50.0}
        present = {"accounts_receiv_bill"}
        assert clean.resolve(["notes_receiv", "accounts_receiv"], "accounts_receiv_bill", row, present) == 50.0

    def test_missing_both_returns_zero(self):
        row = {"other": 10.0}
        present = {"other"}
        assert clean.resolve(["notes_receiv", "accounts_receiv"], "accounts_receiv_bill", row, present) == 0.0

    def test_prefer_combo_field(self):
        # oth_pay_total is in PREFER_COMBO_FIELDS
        row = {"oth_payable": 5.0, "int_payable": 3.0, "div_payable": 2.0, "oth_pay_total": 15.0}
        present = {"oth_payable", "int_payable", "div_payable", "oth_pay_total"}
        assert clean.resolve(["oth_payable", "int_payable", "div_payable"], "oth_pay_total", row, present) == 15.0

    def test_split_sum_zero_falls_back_to_combo(self):
        row = {"notes_receiv": 0.0, "accounts_receiv": 0.0, "accounts_receiv_bill": 40.0}
        present = {"notes_receiv", "accounts_receiv", "accounts_receiv_bill"}
        assert clean.resolve(["notes_receiv", "accounts_receiv"], "accounts_receiv_bill", row, present) == 40.0


class TestPeriodLabel:
    def test_valid_quarter_end_dates(self):
        assert clean.period_label("20240331") == "2024Q1"
        assert clean.period_label("20240630") == "2024Q2"
        assert clean.period_label("20240930") == "2024Q3"
        assert clean.period_label("20241231") == "2024Q4"

    def test_invalid_end_date_returns_none(self):
        assert clean.period_label("20241331") is None
        assert clean.period_label("notadate") is None
        assert clean.period_label("2024121") is None


class TestIncomeStatementChecks:
    def _minimal_is_row(self, **overrides: float) -> dict[str, float]:
        base: dict[str, float] = {
            "revenue": 1000.0,
            "total_revenue": 1000.0,
            "int_income": 0.0,
            "comm_income": 0.0,
            "n_oth_b_income": 0.0,
            "oper_cost": 600.0,
            "biz_tax_surchg": 10.0,
            "sell_exp": 20.0,
            "admin_exp": 30.0,
            "fin_exp": 40.0,
            "rd_exp": 0.0,
            "assets_impair_loss": 0.0,
            "credit_impa_loss": 0.0,
            "other_bus_cost": 0.0,
            "oth_impair_loss_assets": 0.0,
            "int_exp": 0.0,
            "comm_exp": 0.0,
            "prem_refund": 0.0,
            "compens_payout": 0.0,
            "reser_insur_liab": 0.0,
            "div_payt": 0.0,
            "reins_exp": 0.0,
            "oper_exp": 0.0,
            "insurance_exp": 0.0,
            "out_prem": 0.0,
            "une_prem_reser": 0.0,
            "compens_payout_refu": 0.0,
            "insur_reser_refu": 0.0,
            "reins_cost_refund": 0.0,
            "total_cogs": 700.0,
            "total_opcost": 660.0,
            "oth_income": 0.0,
            "invest_income": 50.0,
            "fv_value_chg_gain": 0.0,
            "asset_disp_income": 0.0,
            "net_expo_hedging_benefits": 0.0,
            "forex_gain": 0.0,
            "operate_profit": 350.0,
            "non_oper_income": 10.0,
            "non_oper_exp": 5.0,
            "total_profit": 355.0,
            "income_tax": 88.75,
            "n_income": 266.25,
            "n_income_attr_p": 250.0,
            "minority_gain": 16.25,
        }
        base.update(overrides)
        return base

    def test_check_is_passes_for_balanced_row(self):
        row = self._minimal_is_row()
        present = {k for k, v in row.items() if v != 0.0}
        errors = clean.check_is(row, present, "2024")
        assert errors == []

    def test_check_is_fails_when_total_profit_mismatches(self):
        row = self._minimal_is_row(total_profit=999.0)
        present = {k for k, v in row.items() if v != 0.0}
        errors = clean.check_is(row, present, "2024")
        assert any("IS 1.3" in e for e in errors)


class TestBalanceSheetChecks:
    def _minimal_bs_row(self, **overrides: float) -> dict[str, float]:
        base: dict[str, float] = {
            # Current assets
            "money_cap": 115.0,
            "total_cur_assets": 115.0,
            # Non-current assets
            "fix_assets_total": 50.0,
            "total_nca": 50.0,
            # Total assets
            "total_assets": 165.0,
            # Current liabilities
            "accounts_pay": 40.0,
            "total_cur_liab": 40.0,
            # Non-current liabilities
            "long_pay_total": 10.0,
            "total_ncl": 10.0,
            # Total liabilities
            "total_liab": 50.0,
            # Equity
            "total_share": 10.0,
            "cap_rese": 20.0,
            "undistr_porfit": 80.0,
            "surplus_rese": 0.0,
            "special_rese": 0.0,
            "treasury_share": 0.0,
            "ordin_risk_reser": 0.0,
            "forex_differ": 0.0,
            "oth_comp_income": 0.0,
            "oth_eqt_tools": 0.0,
            "total_hldr_eqy_exc_min_int": 110.0,
            "minority_int": 5.0,
            "total_hldr_eqy_inc_min_int": 115.0,
            "total_liab_hldr_eqy": 165.0,
        }
        base.update(overrides)
        return base

    def test_check_bs_passes_for_balanced_row(self):
        row = self._minimal_bs_row()
        present = {k for k, v in row.items() if v != 0.0}
        errors, warnings = clean.check_bs(row, present, "2024")
        assert errors == []

    def test_check_bs_fails_when_assets_not_equal_liab_plus_equity(self):
        row = self._minimal_bs_row(total_assets=999.0)
        present = {k for k, v in row.items() if v != 0.0}
        errors, warnings = clean.check_bs(row, present, "2024")
        assert any("BS 4.3" in e for e in errors)

    def test_treasury_share_anomaly_is_warning_not_error(self):
        # Construct a balanced BS where equity residual ≈ 2 * treasury_share.
        # equity_calc = 10 + 20 + 55 - 10 + 5 = 80
        # residual = |80 - 80| = 0 ... need residual=20.
        # Set undistr_porfit=75, treasury_share=10 → equity_calc=10+20+75-10+5=100
        # residual = |100 - 80| ... no.
        # We want equity_calc such that |total_hldr_eqy_inc_min_int - equity_calc| = 2*treasury_share = 20.
        # Let equity_calc=100, total_hldr_eqy_inc_min_int=80.
        # 10 + 20 + undistr - 10 + 5 = 100 → undistr=75.
        # total_hldr_eqy_exc_min_int = 100 - 5 = 95.
        # total_assets = total_liab + total_hldr_eqy_inc_min_int = 50 + 80 = 130,
        # but current assets default to 115, so total_assets must be 145 and nca=30.
        row = self._minimal_bs_row(
            money_cap=100.0,
            total_cur_assets=100.0,
            undistr_porfit=75.0,
            treasury_share=10.0,
            fix_assets_total=30.0,
            total_nca=30.0,
            total_assets=130.0,
            total_hldr_eqy_exc_min_int=75.0,
            total_hldr_eqy_inc_min_int=80.0,
            total_liab_hldr_eqy=130.0,
        )
        present = {k for k, v in row.items() if v != 0.0}
        errors, warnings = clean.check_bs(row, present, "2024")
        assert errors == []
        assert any("treasury_share" in w for w in warnings)


class TestCashFlowChecks:
    def _minimal_cf_row(self, **overrides: float) -> dict[str, float]:
        base: dict[str, float] = {
            "c_fr_sale_sg": 1000.0,
            "recp_tax_rends": 0.0,
            "n_depos_incr_fi": 0.0,
            "n_incr_loans_cb": 0.0,
            "n_inc_borr_oth_fi": 0.0,
            "prem_fr_orig_contr": 0.0,
            "n_incr_insured_dep": 0.0,
            "n_reinsur_prem": 0.0,
            "n_incr_disp_tfa": 0.0,
            "ifc_cash_incr": 0.0,
            "n_incr_disp_faas": 0.0,
            "n_incr_loans_oth_bank": 0.0,
            "n_cap_incr_repur": 0.0,
            "c_fr_oth_operate_a": 0.0,
            "c_paid_goods_s": 500.0,
            "c_paid_to_for_empl": 100.0,
            "c_paid_for_taxes": 50.0,
            "n_incr_clt_loan_adv": 0.0,
            "n_incr_dep_cbob": 0.0,
            "c_pay_claims_orig_inco": 0.0,
            "pay_handling_chrg": 0.0,
            "pay_comm_insur_plcy": 0.0,
            "oth_cash_pay_oper_act": 0.0,
            "c_inf_fr_operate_a": 1000.0,
            "st_cash_out_act": 650.0,
            "n_cashflow_act": 350.0,
            "oth_recp_ral_inv_act": 0.0,
            "c_disp_withdrwl_invest": 0.0,
            "c_recp_return_invest": 0.0,
            "n_recp_disp_fiolta": 0.0,
            "n_recp_disp_sobu": 0.0,
            "c_pay_acq_const_fiolta": 0.0,
            "c_paid_invest": 0.0,
            "n_disp_subs_oth_biz": 0.0,
            "oth_pay_ral_inv_act": 0.0,
            "n_incr_pledge_loan": 0.0,
            "stot_inflows_inv_act": 0.0,
            "stot_out_inv_act": 0.0,
            "n_cashflow_inv_act": 0.0,
            "c_recp_borrow": 0.0,
            "proc_issue_bonds": 0.0,
            "oth_cash_recp_ral_fnc_act": 0.0,
            "c_recp_cap_contrib": 0.0,
            "c_prepay_amt_borr": 0.0,
            "c_pay_dist_dpcp_int_exp": 0.0,
            "oth_cashpay_ral_fnc_act": 0.0,
            "stot_cash_in_fnc_act": 0.0,
            "stot_cashout_fnc_act": 0.0,
            "n_cash_flows_fnc_act": 0.0,
            "eff_fx_flu_cash": 0.0,
            "n_incr_cash_cash_equ": 350.0,
            "c_cash_equ_beg_period": 100.0,
            "c_cash_equ_end_period": 450.0,
        }
        base.update(overrides)
        return base

    def test_check_cf_passes_for_balanced_row(self):
        row = self._minimal_cf_row()
        present = {k for k, v in row.items() if v != 0.0}
        errors = clean.check_cf(row, present, "2024")
        assert errors == []

    def test_check_cf_fails_when_cfo_mismatches(self):
        row = self._minimal_cf_row(n_cashflow_act=999.0)
        present = {k for k, v in row.items() if v != 0.0}
        errors = clean.check_cf(row, present, "2024")
        assert any("CF 5.1" in e for e in errors)


class TestPivotToWideQuarterly:
    def test_income_rt1_fallback_retains_bs_period(self, tmp_path: Path):
        """If income report_type=2 is missing for a quarter, BS/CF data is still kept."""
        db_path = tmp_path / "data.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE raw_tushare (
                ticker TEXT, endpoint TEXT, report_type TEXT, comp_type TEXT,
                end_date TEXT, field TEXT, value REAL, f_ann_date TEXT, ann_date TEXT
            )
            """
        )
        records = [
            # BS Q1 (point-in-time, report_type=1)
            ("000001.SZ", "balancesheet", "1", "1", "20240331", "money_cap", 100.0, "20240430", "20240430"),
            ("000001.SZ", "balancesheet", "1", "1", "20240331", "total_cur_assets", 100.0, "20240430", "20240430"),
            # CF Q1 (cumulative, report_type=1)
            ("000001.SZ", "cashflow", "1", "1", "20240331", "n_cashflow_act", 10.0, "20240430", "20240430"),
            # Income Q1 has only report_type=1 (cumulative fallback), no rt2
            ("000001.SZ", "income", "1", "1", "20240331", "revenue", 50.0, "20240430", "20240430"),
        ]
        conn.executemany(
            "INSERT INTO raw_tushare VALUES (?,?,?,?,?,?,?,?,?)",
            records,
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_path)
        raw = clean.load_raw_tushare(conn, "000001.SZ", mode="quarterly")
        raw = clean.dedupe_by_f_ann_date(raw)
        wide, present_by_period = clean.pivot_to_wide(raw, mode="quarterly", max_quarters=10)
        conn.close()

        assert "2024Q1" in wide.index
        assert wide.loc["2024Q1", "money_cap"] == 100.0

    def test_max_quarters_drops_early_periods(self, tmp_path: Path):
        db_path = tmp_path / "data.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE raw_tushare (
                ticker TEXT, endpoint TEXT, report_type TEXT, comp_type TEXT,
                end_date TEXT, field TEXT, value REAL, f_ann_date TEXT, ann_date TEXT
            )
            """
        )
        records = []
        # Create 5 quarters: 2023Q1-Q4 + 2024Q1
        for i, end_date in enumerate(["20230331", "20230630", "20230930", "20231231", "20240331"]):
            records.append(("000001.SZ", "balancesheet", "1", "1", end_date, "money_cap", float(i + 1), "20240430", "20240430"))
            records.append(("000001.SZ", "balancesheet", "1", "1", end_date, "total_cur_assets", float(i + 1), "20240430", "20240430"))
            records.append(("000001.SZ", "income", "2", "1", end_date, "revenue", float(i + 1), "20240430", "20240430"))
        conn.executemany("INSERT INTO raw_tushare VALUES (?,?,?,?,?,?,?,?,?)", records)
        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_path)
        raw = clean.load_raw_tushare(conn, "000001.SZ", mode="quarterly")
        raw = clean.dedupe_by_f_ann_date(raw)
        wide, _ = clean.pivot_to_wide(raw, mode="quarterly", max_quarters=4)
        conn.close()

        output_periods = list(wide.attrs.get("output_periods", []))
        assert "2023Q1" not in output_periods
        assert "2024Q1" in output_periods
        assert len(output_periods) == 4
