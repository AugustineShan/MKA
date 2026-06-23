"""Unit tests for capex routing in build_balance_sheet.

Locks in: only the PP&E portion of combined capex rolls into fix_assets;
metrics["capex"] (used by CFI/FCFF) stays the full combined capex.
"""

from __future__ import annotations

import pytest

from src.calc import build_balance_sheet
from src.yaml2_schema import REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT


def _income_row(revenue=1000.0, n_income_attr_p=10.0):
    return {
        "revenue": revenue,
        "oper_cost": revenue * 0.5,
        "n_income_attr_p": n_income_attr_p,
        "minority_gain": 0.0,
    }


def _prev_bs(fix_assets=50.0):
    return {
        "money_cap": 100.0,
        "undistr_porfit": 1000.0,  # 充足权益，避免负现金噪声
        "minority_int": 0.0,
        "fix_assets": fix_assets,
    }


def test_fix_assets_rolls_with_capex_ppe_not_full_capex():
    """Only capex_ppe (= combined capex - non-PP&E amortization) rolls into fix_assets."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10]},       # combined capex = 10% x 1000 = 100
            "depr_rate": {"value": [0.0]},         # zero depreciation, isolate routing effect
            "amort_intang_assets": {"value": [3.0]},
            "use_right_asset_dep": {"value": [2.0]},
            "lt_amort_deferred_exp": {"value": [1.0]},
        }
    }
    bs_row, metrics = build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1)

    # capex_ppe = 100 - (3+2+1) = 94; depreciation = 50 x 0.0 = 0
    # fix_assets = 50 + 94 - 0 = 144 (not 50 + 100 = 150)
    assert bs_row["fix_assets"] == pytest.approx(144.0)
    # metrics["capex"] must remain the full combined capex (used by CFI/FCFF)
    assert metrics["capex"] == pytest.approx(100.0)


def test_depreciation_not_inflated_by_non_ppE_capex():
    """Phantom depreciation removed: depreciation base is capex_ppe, not full capex."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10, 0.10]},
            "depr_rate": {"value": [0.20, 0.20]},
            "amort_intang_assets": {"value": [3.0, 3.0]},
            "use_right_asset_dep": {"value": [2.0, 2.0]},
            "lt_amort_deferred_exp": {"value": [1.0, 1.0]},
        }
    }
    bs_row1, _ = build_balance_sheet(yaml2, _prev_bs(fix_assets=0.0), _income_row(), idx=1)
    # year1: capex_ppe = 100 - 6 = 94; depr = 0 x 0.2 = 0; fix_assets = 0 + 94 = 94
    assert bs_row1["fix_assets"] == pytest.approx(94.0)

    bs_row2, metrics2 = build_balance_sheet(yaml2, bs_row1, _income_row(), idx=2)
    # year2: depr = 94 x 0.2 = 18.8 (based on capex_ppe base 94, not phantom 100 x 0.2 = 20)
    assert metrics2["depreciation"] == pytest.approx(18.8)


def test_balance_sheet_still_balances_with_capex_routing():
    """Plug still balances BS (fix_assets reduction offset by higher cash plug)."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10]},
            "depr_rate": {"value": [0.0]},
            "amort_intang_assets": {"value": [3.0]},
            "use_right_asset_dep": {"value": [2.0]},
            "lt_amort_deferred_exp": {"value": [1.0]},
        }
    }
    bs_row, _ = build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1)
    residual = (
        bs_row["total_assets"]
        - bs_row["total_liab"]
        - bs_row["total_hldr_eqy_inc_min_int"]
    )
    assert abs(residual) < 1e-4


def test_asset_light_company_unchanged():
    """When all three amortization knobs are absent (default 0), capex_ppe == capex, behavior identical to before."""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.10]},
            "depr_rate": {"value": [0.0]},
            # three amortization knobs not set -> get_year_float defaults to 0.0
        }
    }
    bs_row, metrics = build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1)
    # capex_ppe = 100 - 0 = 100; fix_assets = 50 + 100 = 150
    assert bs_row["fix_assets"] == pytest.approx(150.0)
    assert metrics["capex"] == pytest.approx(100.0)


def test_capex_below_non_ppE_amort_floors_and_flags():
    """合并 capex < 非 PP&E 摊销时，capex_ppe 落底 0 并发 review flag。"""
    yaml2 = {
        "balance_sheet": {
            "capex_pct": {"value": [0.001]},      # capex = 0.1% x 1000 = 1.0
            "depr_rate": {"value": [0.0]},
            "amort_intang_assets": {"value": [3.0]},
            "use_right_asset_dep": {"value": [2.0]},
            "lt_amort_deferred_exp": {"value": [1.0]},
        }
    }
    flags = []
    bs_row, metrics = build_balance_sheet(
        yaml2, _prev_bs(), _income_row(), idx=1, review_flags=flags
    )

    # capex=1.0 < amort_sum=6.0 -> capex_ppe 落底 0; fix_assets = 50 + 0 - 0 = 50
    assert bs_row["fix_assets"] == pytest.approx(50.0)
    assert metrics["capex"] == pytest.approx(1.0)   # 完整 capex 仍 1.0
    assert any(f["code"] == REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT for f in flags)
