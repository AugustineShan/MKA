"""Tests for deterministic yaml1 cleaning."""

from __future__ import annotations

from pathlib import Path

import pytest

from src import yaml1_cleaner


def company_dir() -> Path:
    return next(Path("companies").glob("*_002946"))


def paths() -> tuple[Path, Path, Path]:
    base = company_dir()
    return (
        yaml1_cleaner.default_yaml1_path(base),
        base / "defaults.yaml",
        base / "data.db",
    )


def test_fold_revenue_uses_structured_unit_factor_and_clean_anchor():
    yaml1_path, _, clean_path = paths()
    yaml1 = yaml1_cleaner.load_yaml(yaml1_path)
    clean_annual = yaml1_cleaner.load_clean_annual(clean_path)

    fold = yaml1_cleaner.fold_revenue(yaml1, clean_annual)

    assert fold.base_year == 2024
    assert fold.base_revenue == pytest.approx(10665.42345785)
    assert fold.segment_base_revenue["low_temp_fresh_milk"] == pytest.approx(2739.3222)
    assert fold.segment_base_revenue["low_temp_yogurt"] == pytest.approx(2767.5343)
    assert fold.segment_base_revenue["ambient"] == pytest.approx(4329.5231)
    assert fold.segment_base_revenue["fringe_business"] == pytest.approx(829.24)
    assert fold.revenue_by_year[2025] == pytest.approx(10856.504606625)
    assert fold.revenue_yoy[0] == pytest.approx(10856.504606625 / 10665.42345785 - 1)
    # If this accidentally anchors to the four-line base sum, it will be slightly different.
    segment_sum = sum(fold.segment_base_revenue.values())
    assert fold.revenue_yoy[0] != pytest.approx(10856.504606625 / segment_sum - 1)
    assert fold.unit_factors == {
        "low_temp_fresh_milk": 100.0,
        "low_temp_yogurt": 100.0,
        "ambient": 100.0,
        "fringe_business": 1.0,
    }


def test_clean_yaml1_expands_fade_hold_default_hold_and_alias_warning():
    yaml1_path, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(
        yaml1_path,
        defaults_path,
        clean_path,
    )

    y = result.forecast_params
    warnings = [item["message"] for item in result.report["warnings"]]

    assert y["model"]["forecast_years"]["value"] == 12
    assert y["meta"]["horizon"] == list(range(2025, 2037))
    revenue_yoy = y["model"]["revenue_yoy"]["value"]
    assert len(revenue_yoy) == 12
    assert revenue_yoy[:7] == pytest.approx(
        [
            0.017915945815949685,
            0.014292883231659115,
            0.01856631471147141,
            0.021776623729457878,
            0.02411847415260815,
            0.025798344902929538,
            0.02395436614151536,
        ]
    )
    assert revenue_yoy[7:] == pytest.approx(
        [
            0.02416349291321229,
            0.024372619684909218,
            0.024581746456606143,
            0.024790873228303072,
            0.025,
        ]
    )
    assert y["income"]["gpm"]["value"][-5:] == pytest.approx([0.314] * 5)
    assert y["income"]["cost_rates"]["admin_exp"]["value"][-5:] == pytest.approx([0.036] * 5)

    assert any("总增速低于永续" in message for message in warnings)
    assert any("末年增速<永续" in message for message in warnings)


def test_resolve_yearly_shape_keeps_base_and_constants_scalar():
    yaml1_path, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(
        yaml1_path,
        defaults_path,
        clean_path,
    )
    y = result.forecast_params

    assert y["base_period"] == "2024"
    assert y["income"]["revenue"]["value"] == pytest.approx(10665.42345785)
    assert isinstance(y["balance_sheet"]["base"]["money_cap"]["value"], float)
    assert isinstance(y["cashflow"]["base_nwc"]["value"], float)
    assert isinstance(y["market"]["total_shares"]["value"], float)
    assert y["model"]["wacc"]["value"] == pytest.approx(0.08)
    assert y["income"]["financial_expense"]["interest_mode"]["value"] == "circular_average_balance"

    horizon_len = y["model"]["forecast_years"]["value"]
    yearly_paths = result.report["yearly_paths"]
    assert "income.financial_expense.interest_expense_rate" in yearly_paths
    assert len(y["income"]["financial_expense"]["interest_expense_rate"]["value"]) == horizon_len
    assert len(y["balance_sheet"]["revenue_pct"]["accounts_receiv"]["value"]) == horizon_len
    assert len(y["balance_sheet"]["amort_intang_assets"]["value"]) == horizon_len


def test_backtest_hard_gate_passes_for_new_hope_dairy():
    yaml1_path, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(
        yaml1_path,
        defaults_path,
        clean_path,
    )

    backtest = result.report["backtest"]
    assert backtest["status"] == "passed"
    assert backtest["anchor"]["residual"] < 1.0
    assert not result.report["errors"]


def test_defaults_only_identity_clean_matches_yaml2_broadcast():
    _, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(None, defaults_path, clean_path)

    assert result.report.get("defaults_only") is True
    assert result.report["backtest"]["status"] == "skipped"
    forecast_params = result.forecast_params

    # Horizon comes from YAML2 base_period + forecast_years, no fade.
    base_period = forecast_params["base_period"]
    base_year = int(str(base_period)[:4])
    years = int(forecast_params["model"]["forecast_years"]["value"])
    assert forecast_params["meta"]["horizon"] == list(range(base_year + 1, base_year + 1 + years))

    # model.revenue_yoy is broadcast from scalar YAML2 default.
    revenue_yoy = forecast_params["model"]["revenue_yoy"]["value"]
    assert isinstance(revenue_yoy, list)
    assert len(revenue_yoy) == years
    assert revenue_yoy == pytest.approx([revenue_yoy[0]] * years)

    # Numerically identical to the legacy broadcast helper.
    yaml2 = yaml1_cleaner.read_yaml2(defaults_path)
    broadcast = yaml1_cleaner.broadcast_yaml2_defaults(yaml2)
    assert (
        forecast_params["model"]["revenue_yoy"]["value"]
        == broadcast["model"]["revenue_yoy"]["value"]
    )
