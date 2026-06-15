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
    assert fold.segment_base_revenue["lowtemp_fresh"] == pytest.approx(2739.38166)
    assert fold.segment_base_revenue["lowtemp_yogurt"] == pytest.approx(2767.5343)
    assert fold.segment_base_revenue["ambient"] == pytest.approx(4329.41292)
    assert fold.segment_base_revenue["edge"] == pytest.approx(829.24)
    assert fold.revenue_by_year[2025] == pytest.approx(10856.464272046602)
    assert fold.revenue_yoy[0] == pytest.approx(10856.464272046602 / 10665.42345785 - 1)
    # If this accidentally anchors to the four-line base sum, it will be slightly different.
    segment_sum = sum(fold.segment_base_revenue.values())
    assert fold.revenue_yoy[0] != pytest.approx(10856.464272046602 / segment_sum - 1)
    assert fold.unit_factors == {
        "lowtemp_fresh": 100.0,
        "lowtemp_yogurt": 100.0,
        "ambient": 100.0,
        "edge": 1.0,
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
            0.017912155998109676,
            0.01429369244644741,
            0.018567033928240348,
            0.021777251881713918,
            0.024119016865376824,
            0.025798808087965483,
            0.0239548357758661,
        ]
    )
    assert revenue_yoy[7:] == pytest.approx(
        [
            0.02416386862069288,
            0.02437290146551966,
            0.024581934310346443,
            0.024790967155173222,
            0.025,
        ]
    )
    assert y["income"]["gpm"]["value"][-5:] == pytest.approx([0.305] * 5)
    assert y["income"]["cost_rates"]["admin_exp"]["value"][-5:] == pytest.approx([0.036] * 5)

    assert any("fade path alias" in message for message in warnings)
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
