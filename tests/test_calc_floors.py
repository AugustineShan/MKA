"""Unit tests for calc.py accounting floors.

These tests lock in behavior that is easy to omit from high-level regression
fixtures: loss-year tax/dividend floors and the fixed-asset non-negativity
constraint.
"""

from __future__ import annotations

import pytest

from src.calc import build_balance_sheet, build_income_statement


def test_build_income_statement_floors_tax_at_zero_for_losses():
    """Income tax must be zero when total profit is non-positive."""
    yaml2 = {
        "income": {
            "gpm": {"value": [0.5]},
            "effective_tax_rate": {"value": [0.25]},
            "minority_ratio": {"value": [0.0]},
            "cost_abs": {
                "big_cost": {"value": [300.0]},
            },
        }
    }
    financial_expense = {
        "fin_exp": 0.0,
        "fin_exp_int_exp": 0.0,
        "fin_exp_int_inc": 0.0,
        "other_fin_exp": 0.0,
    }
    row = build_income_statement(yaml2, revenue=100.0, financial_expense=financial_expense, idx=1)

    # revenue=100, oper_cost=50, big_cost=300 -> operate_profit = -250
    assert row["operate_profit"] == pytest.approx(-250.0)
    assert row["total_profit"] == pytest.approx(-250.0)
    # Tax must be floored at 0; without the floor it would be -62.5.
    assert row["income_tax"] == pytest.approx(0.0)
    assert row["n_income"] == pytest.approx(-250.0)


def test_build_income_statement_computes_tax_for_profits():
    """Sanity check that tax is positive when the company is profitable."""
    yaml2 = {
        "income": {
            "gpm": {"value": [0.5]},
            "effective_tax_rate": {"value": [0.25]},
            "minority_ratio": {"value": [0.0]},
        }
    }
    financial_expense = {
        "fin_exp": 0.0,
        "fin_exp_int_exp": 0.0,
        "fin_exp_int_inc": 0.0,
        "other_fin_exp": 0.0,
    }
    row = build_income_statement(yaml2, revenue=100.0, financial_expense=financial_expense, idx=1)

    assert row["operate_profit"] == pytest.approx(50.0)
    assert row["income_tax"] == pytest.approx(12.5)
    assert row["n_income"] == pytest.approx(37.5)


def test_build_balance_sheet_floors_dividends_at_zero_for_losses():
    """Dividends must be zero when attributable net income is negative."""
    yaml2 = {
        "balance_sheet": {
            "dividend_payout": {"value": [0.3]},
        }
    }
    prev_bs = {
        "money_cap": 100.0,
        "undistr_porfit": 200.0,
        "minority_int": 0.0,
        "fix_assets": 0.0,
    }
    income_row = {
        "revenue": 100.0,
        "oper_cost": 50.0,
        "n_income_attr_p": -10.0,
        "minority_gain": 0.0,
    }
    bs_row, _ = build_balance_sheet(yaml2, prev_bs, income_row, idx=1)

    # Without the floor, dividends would be -3.0 (a dividend *credit*), which
    # would incorrectly inflate retained earnings.
    assert bs_row["undistr_porfit"] == pytest.approx(200.0 + (-10.0) - 0.0)


def test_build_balance_sheet_pays_dividends_for_profits():
    """Sanity check that dividends are paid when the company is profitable."""
    yaml2 = {
        "balance_sheet": {
            "dividend_payout": {"value": [0.3]},
        }
    }
    prev_bs = {
        "money_cap": 100.0,
        "undistr_porfit": 200.0,
        "minority_int": 0.0,
        "fix_assets": 0.0,
    }
    income_row = {
        "revenue": 100.0,
        "oper_cost": 50.0,
        "n_income_attr_p": 40.0,
        "minority_gain": 0.0,
    }
    bs_row, _ = build_balance_sheet(yaml2, prev_bs, income_row, idx=1)

    assert bs_row["undistr_porfit"] == pytest.approx(200.0 + 40.0 - 12.0)


def test_build_balance_sheet_floors_fixed_assets_at_zero():
    """Fixed assets must never be negative; depreciation can only reduce to zero."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.0]},
            "depr_rate": {"value": [1.0]},
        }
    }
    prev_bs = {
        "money_cap": 100.0,
        "undistr_porfit": 200.0,
        "minority_int": 0.0,
        "fix_assets": 50.0,
    }
    income_row = {
        "revenue": 100.0,
        "oper_cost": 50.0,
        "n_income_attr_p": 10.0,
        "minority_gain": 0.0,
    }
    bs_row, _ = build_balance_sheet(yaml2, prev_bs, income_row, idx=1)

    # capex=0, depreciation=50 -> net change -50, floored at 0.
    assert bs_row["fix_assets"] == pytest.approx(0.0)
