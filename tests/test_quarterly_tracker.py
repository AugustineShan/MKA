from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import copy_fixture_company
from src import forecast as forecast_mod, yaml1_cleaner
from src.workbench import app
from src.quarterly_tracker import (
    check_q4_band,
    clear_override,
    compute_expense_amount_quarters,
    compute_gross_profit_quarters,
    compute_revenue_quarters,
    compute_seasonal_amount_quarters,
    compute_quarterly_view,
    derive_subtotals,
    init_overrides_table,
    load_overrides,
    prior_same_quarter,
    set_override,
)


COMPANY_DIR = next((Path(__file__).resolve().parents[1] / "companies").glob("*002946"))
DB = COMPANY_DIR / "Agent" / "data.db"
CLIENT = TestClient(app)


def _forecast_start_year() -> int:
    """Earliest period in the real 新乳业 forecast_is.csv.

    The quarterly view's default year = min(forecast periods). The real dir's
    forecast rolls forward when clean_annual gains a new actual year, so tests
    must not hardcode the year — derive it from the forecast file.
    """
    p = COMPANY_DIR / "Agent" / "forecast" / "forecast_is.csv"
    with open(p, encoding="utf-8-sig") as f:
        return min(int(row["period"]) for row in csv.DictReader(f))


def test_override_crud_roundtrip(tmp_path):
    db = tmp_path / "data.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE meta (key TEXT, value TEXT)")

    init_overrides_table(db)
    set_override(
        db,
        "002946.SZ",
        "2025Q2",
        "gpm",
        0.31,
        locked_field="gross_profit",
        locked_value=91.0,
        note="旺季",
        updated_at="2026-06-22T00:00:00",
    )

    loaded = load_overrides(db, "002946.SZ")
    assert loaded["2025Q2"]["gpm"] == 0.31
    assert loaded["2025Q2"]["_locked"]["gross_profit"] == 91.0

    set_override(
        db,
        "002946.SZ",
        "2025Q2",
        "gpm",
        0.32,
        locked_field="gross_profit",
        locked_value=94.0,
        updated_at="2026-06-22T00:01:00",
    )

    loaded = load_overrides(db, "002946.SZ")
    assert loaded["2025Q2"]["gpm"] == 0.32
    assert loaded["2025Q2"]["_locked"]["gross_profit"] == 94.0

    clear_override(db, "002946.SZ", "2025Q2")
    assert "2025Q2" not in load_overrides(db, "002946.SZ")


def test_override_replaces_same_locked_field(tmp_path):
    db = tmp_path / "data.db"
    init_overrides_table(db)

    set_override(
        db,
        "002946.SZ",
        "2025Q2",
        "gpm",
        0.31,
        locked_field="gross_profit",
        locked_value=91.0,
        updated_at="2026-06-22T00:00:00",
    )
    set_override(
        db,
        "002946.SZ",
        "2025Q2",
        "gross_profit_abs",
        95.0,
        locked_field="gross_profit",
        locked_value=95.0,
        updated_at="2026-06-22T00:01:00",
    )

    loaded = load_overrides(db, "002946.SZ")["2025Q2"]
    assert "gpm" not in loaded
    assert loaded["gross_profit_abs"] == 95.0
    assert loaded["_locked"]["gross_profit"] == 95.0


def test_clear_override_can_remove_single_param(tmp_path):
    db = tmp_path / "data.db"
    init_overrides_table(db)
    set_override(
        db,
        "002946.SZ",
        "2025Q2",
        "revenue_yoy",
        0.12,
        locked_field="revenue",
        locked_value=240.0,
        updated_at="2026-06-22T00:00:00",
    )
    set_override(
        db,
        "002946.SZ",
        "2025Q2",
        "sell_exp_abs",
        18.0,
        locked_field="sell_exp",
        locked_value=18.0,
        updated_at="2026-06-22T00:01:00",
    )

    clear_override(db, "002946.SZ", "2025Q2", param="revenue_yoy")
    loaded = load_overrides(db, "002946.SZ")["2025Q2"]
    assert "revenue_yoy" not in loaded
    assert loaded["sell_exp_abs"] == 18.0
    assert loaded["_locked"] == {"sell_exp": 18.0}


def test_prior_same_quarter_uses_last_year():
    quarterly_by_year = {
        2017: {3: 100.0, 4: 120.0},
        2018: {1: 90.0, 2: 110.0, 3: 105.0, 4: 130.0},
    }
    assert prior_same_quarter(quarterly_by_year, year=2018, q=3) == 100.0


def test_prior_same_quarter_falls_back_when_missing():
    quarterly_by_year = {
        2017: {3: 100.0, 4: 120.0},
        2018: {1: 90.0, 2: 110.0, 3: 105.0, 4: 130.0},
        2019: {1: 95.0, 2: 115.0, 3: 108.0, 4: 135.0},
    }
    assert prior_same_quarter(quarterly_by_year, year=2018, q=2) is None
    assert prior_same_quarter(quarterly_by_year, year=2019, q=2) == 110.0


def test_prior_same_quarter_ignores_missing_and_zero_values():
    quarterly_by_year = {
        2016: {1: 80.0},
        2017: {1: 0.0},
        2018: {2: 110.0},
    }
    assert prior_same_quarter(quarterly_by_year, year=2019, q=1) == 80.0


def test_revenue_inherit_and_q4_residual():
    prior_q = {1: 200.0, 2: 250.0, 3: 230.0, 4: 320.0}
    out = compute_revenue_quarters(
        annual=1200.0,
        prior_annual=1000.0,
        prior_quarterly=prior_q,
        states={1: "actual", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={1: 210.0},
    )

    assert abs(out[2] - 250.0 * 1.2) < 1e-6
    assert abs(out[3] - 230.0 * 1.2) < 1e-6
    assert abs(out[4] - (1200.0 - (210.0 + 300.0 + 276.0))) < 1e-6
    assert abs(sum(out.values()) - 1200.0) < 1e-6


def test_revenue_manual_yoy_locks_quarter_amount():
    out = compute_revenue_quarters(
        annual=1200.0,
        prior_annual=1000.0,
        prior_quarterly={1: 200.0, 2: 250.0, 3: 230.0, 4: 320.0},
        states={1: "inherit", 2: "manual", 3: "inherit", 4: "q4"},
        actuals={},
        override_yoy={2: 0.4},
    )

    assert abs(out[2] - 350.0) < 1e-6
    assert abs(sum(out.values()) - 1200.0) < 1e-6


def test_revenue_inherit_falls_back_to_even_split_when_no_prior():
    out = compute_revenue_quarters(
        annual=1200.0,
        prior_annual=0.0,
        prior_quarterly={},
        states={1: "inherit", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={},
    )

    assert out == {1: 300.0, 2: 300.0, 3: 300.0, 4: 300.0}


def test_gross_profit_amount_shape_not_flat_rate():
    out = compute_gross_profit_quarters(
        annual_gross_profit=360.0,
        prior_annual_gross_profit=280.0,
        prior_quarterly_gross_profit={1: 60.0, 2: 55.0, 3: 65.0, 4: 100.0},
        revenue_quarters={1: 210.0, 2: 300.0, 3: 276.0, 4: 414.0},
        states={1: "actual", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals_gross_profit={1: 62.0},
    )

    assert abs(out["gross_profit"][2] - (360.0 * 55.0 / 280.0)) < 1e-6
    assert abs(out["oper_cost"][2] - (300.0 - out["gross_profit"][2])) < 1e-6
    assert abs(sum(out["gross_profit"].values()) - 360.0) < 1e-6


def test_gross_profit_manual_gpm_locks_gross_profit_amount():
    out = compute_gross_profit_quarters(
        annual_gross_profit=360.0,
        prior_annual_gross_profit=280.0,
        prior_quarterly_gross_profit={1: 60.0, 2: 55.0, 3: 65.0, 4: 100.0},
        revenue_quarters={1: 210.0, 2: 300.0, 3: 276.0, 4: 414.0},
        states={1: "inherit", 2: "manual", 3: "inherit", 4: "q4"},
        actuals_gross_profit={},
        override_gpm={2: 0.32},
    )

    assert abs(out["gross_profit"][2] - 96.0) < 1e-6
    assert abs(out["gpm"][2] - 0.32) < 1e-6
    assert abs(sum(out["gross_profit"].values()) - 360.0) < 1e-6


def test_expense_amount_shape_then_rate_is_derived():
    out = compute_expense_amount_quarters(
        annual=180.0,
        prior_annual=160.0,
        prior_quarterly={1: 35.0, 2: 45.0, 3: 40.0, 4: 40.0},
        revenue_quarters={1: 210.0, 2: 300.0, 3: 276.0, 4: 414.0},
        states={1: "actual", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={1: 30.0},
    )

    assert abs(out[2] - (180.0 * 45.0 / 160.0)) < 1e-6
    assert abs(sum(out.values()) - 180.0) < 1e-6


def test_expense_manual_rate_locks_amount():
    out = compute_expense_amount_quarters(
        annual=180.0,
        prior_annual=160.0,
        prior_quarterly={1: 35.0, 2: 45.0, 3: 40.0, 4: 40.0},
        revenue_quarters={1: 210.0, 2: 300.0, 3: 276.0, 4: 414.0},
        states={1: "inherit", 2: "manual", 3: "inherit", 4: "q4"},
        actuals={},
        override_rate={2: 0.18},
    )

    assert abs(out[2] - 54.0) < 1e-6
    assert abs(sum(out.values()) - 180.0) < 1e-6


def test_seasonal_amount_phase_distribution():
    out = compute_seasonal_amount_quarters(
        annual=-100.0,
        prior_annual=-80.0,
        prior_quarterly={1: -10.0, 2: -5.0, 3: -5.0, 4: -60.0},
        states={1: "actual", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={1: -12.0},
    )

    assert abs(out[2] - (-6.25)) < 1e-6
    assert abs(out[4] - (-100.0 - (-12.0 - 6.25 - 6.25))) < 1e-6
    assert abs(sum(out.values()) - (-100.0)) < 1e-6


def test_seasonal_amount_fallback_to_even_when_no_prior():
    out = compute_seasonal_amount_quarters(
        annual=-100.0,
        prior_annual=0.0,
        prior_quarterly={},
        states={1: "actual", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={1: -25.0},
    )

    assert abs(out[2] - (-25.0)) < 1e-6
    assert abs(out[4] - (-25.0)) < 1e-6
    assert abs(sum(out.values()) + 100.0) < 1e-6


def test_tax_and_fin_exp_are_amount_shaped_not_flat_rates():
    tax = compute_seasonal_amount_quarters(
        annual=60.0,
        prior_annual=50.0,
        prior_quarterly={1: 8.0, 2: 10.0, 3: 9.0, 4: 23.0},
        states={1: "inherit", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={},
    )
    fin_exp = compute_seasonal_amount_quarters(
        annual=80.0,
        prior_annual=100.0,
        prior_quarterly={1: 18.0, 2: 20.0, 3: 17.0, 4: 45.0},
        states={1: "inherit", 2: "inherit", 3: "inherit", 4: "q4"},
        actuals={},
    )

    assert abs(tax[4] - 60.0 * 23.0 / 50.0) < 1e-6
    assert abs(fin_exp[4] - 80.0 * 45.0 / 100.0) < 1e-6


def test_derive_subtotals_reuses_income_statement_buckets():
    leaves = {
        "revenue": 1000.0,
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
        "oth_income": 0.0,
        "invest_income": 50.0,
        "fv_value_chg_gain": 0.0,
        "asset_disp_income": 0.0,
        "net_expo_hedging_benefits": 0.0,
        "forex_gain": 0.0,
        "non_oper_income": 10.0,
        "non_oper_exp": 5.0,
        "income_tax": 88.75,
        "minority_gain": 16.25,
    }

    sub = derive_subtotals(leaves)
    assert sub["total_revenue"] == 1000.0
    assert sub["total_cogs"] == 700.0
    assert sub["total_opcost"] == 660.0
    assert sub["operate_profit"] == 350.0
    assert sub["total_profit"] == 355.0
    assert sub["n_income"] == 266.25
    assert sub["n_income_attr_p"] == 250.0


def test_compute_quarterly_view_time_machine_default_year(tmp_path, monkeypatch):
    # Use the frozen fixture (data ends 2024, forecast starts 2025) so the view's
    # default year (2025) and Q1=inherit state stay stable. The real dir's forecast
    # rolls forward when clean_annual gains actuals, which would break these
    # hardcoded-2025 assertions. Generate the forecast in the tmp copy (freezing
    # forecast_is.csv in the fixture would break test_forecast_pipeline's mkdir).
    # Workbench endpoints (other two tests) can't be fixture-isolated, so they
    # derive the year dynamically instead.
    company_dir = copy_fixture_company(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")
    forecast_mod.run_company_forecast(ticker="002946.SZ")
    db = company_dir / "Agent" / "data.db"
    clear_override(str(db), "002946.SZ", "2025Q2")
    view = compute_quarterly_view(db=str(db), ticker="002946.SZ", company_dir=str(company_dir))

    assert view["year"] == 2025
    assert view["periods"] == [
        "2023Q1", "2023Q2", "2023Q3", "2023Q4",
        "2024Q1", "2024Q2", "2024Q3", "2024Q4",
        "2025Q1", "2025Q2", "2025Q3", "2025Q4",
    ]
    assert view["quarter_states"] == {
        "1": "inherit",
        "2": "inherit",
        "3": "inherit",
        "4": "q4",
    }
    assert view["period_states"]["2023Q1"] == "actual"
    assert view["period_states"]["2024Q4"] == "actual"
    assert view["period_states"]["2025Q4"] == "q4"

    revenue = next(row for row in view["rows"] if row["field"] == "revenue")
    forecast_periods = [f"2025Q{q}" for q in (1, 2, 3, 4)]
    assert abs(sum(revenue["values"][period] for period in forecast_periods) - view["annual"]["revenue"]) < 1.0

    revenue_yoy = next(row for row in view["rows"] if row["field"] == "revenue_yoy")
    gross_margin = next(row for row in view["rows"] if row["field"] == "gross_margin")
    sell_exp_rate = next(row for row in view["rows"] if row["field"] == "sell_exp_rate")
    n_income = next(row for row in view["rows"] if row["field"] == "n_income")
    n_income_yoy = next(row for row in view["rows"] if row["field"] == "n_income_yoy")
    n_income_margin = next(row for row in view["rows"] if row["field"] == "n_income_margin")
    assert revenue_yoy["format"] == "percent"
    assert gross_margin["format"] == "percent"
    assert sell_exp_rate["format"] == "percent"
    assert n_income["label"] == "净利润"
    assert n_income["highlight"] is True
    assert n_income_yoy["format"] == "percent"
    assert n_income_yoy["highlight"] is True
    assert n_income_margin["format"] == "percent"
    assert n_income_margin["highlight"] is True
    assert all(row["field"] != "n_income_attr_p" for row in view["rows"])

    zero_row = next(row for row in view["rows"] if row["field"] == "int_income")
    assert zero_row["is_zero"] is True

    for field in ["fin_exp", "income_tax", "minority_gain"]:
        row = next(row for row in view["rows"] if row["field"] == field)
        assert abs(sum(row["values"][period] for period in forecast_periods) - view["annual"][field]) < 1.0


def test_q4_band_flags_outlier():
    flags = check_q4_band(
        implied={"revenue_yoy": 0.50, "gpm": 0.30, "tax_rate": 0.42, "fin_exp_rate": 0.08},
        history_q4={
            "revenue_yoy": [0.10, 0.12, 0.11],
            "gpm": [0.28, 0.29, 0.29],
            "tax_rate": [0.14, 0.16, 0.15],
            "fin_exp_rate": [0.02, 0.025, 0.03],
        },
    )

    assert any(flag["ratio"] == "revenue_yoy" for flag in flags)
    assert any(flag["ratio"] == "tax_rate" for flag in flags)
    assert any(flag["ratio"] == "fin_exp_rate" for flag in flags)


def test_q4_band_no_flag_in_range():
    flags = check_q4_band(
        implied={"revenue_yoy": 0.115},
        history_q4={"revenue_yoy": [0.10, 0.12, 0.11]},
    )
    assert flags == []


def test_quarterly_workbench_endpoints_roundtrip():
    company_id = COMPANY_DIR.name
    fs = _forecast_start_year()
    q2 = f"{fs}Q2"
    CLIENT.delete(f"/api/companies/{company_id}/quarterly/override/{q2}")

    response = CLIENT.get(f"/api/companies/{company_id}/quarterly?year={fs}")
    assert response.status_code == 200
    view = response.json()
    assert view["year"] == fs
    assert view["quarter_states"]["2"] == "inherit"

    response = CLIENT.put(
        f"/api/companies/{company_id}/quarterly/override",
        json={"period": q2, "param": "gpm", "value": 0.31},
    )
    assert response.status_code == 200

    response = CLIENT.get(f"/api/companies/{company_id}/quarterly?year={fs}")
    assert response.status_code == 200
    view = response.json()
    assert view["quarter_states"]["2"] == "manual"
    gross_profit = next(row for row in view["rows"] if row["field"] == "oper_cost")
    assert gross_profit["states"][q2] == "manual"

    response = CLIENT.delete(f"/api/companies/{company_id}/quarterly/override/{q2}")
    assert response.status_code == 200
    response = CLIENT.get(f"/api/companies/{company_id}/quarterly?year={fs}")
    assert response.json()["quarter_states"]["2"] == "inherit"


def test_read_company_includes_quarterly_view():
    fs = _forecast_start_year()
    response = CLIENT.get(f"/api/companies/{COMPANY_DIR.name}")
    assert response.status_code == 200
    data = response.json()
    assert data["quarterly_view"]["year"] == fs
    assert data["rating_report"] == {
        "data_start_year": fs - 3,
        "data_end_year": fs - 1,
        "forecast_start_year": fs,
        "forecast_end_year": fs + 2,
    }
