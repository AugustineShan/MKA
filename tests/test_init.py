"""Tests for src/init.py orchestration helpers."""

from src.init import _round2_residuals_unchanged


def test_round2_skip_when_all_residuals_unchanged():
    """Opt 2: round 1 closed BS, IS 1.2 residuals untouched → skip round 2.

    Mirrors 新乳业: round-1 overrides (oth_eq_invest/use_right_assets/lease_liab)
    close BS 2.2/3.2 but do not touch IS 1.2 (oth_income/asset_disp/credit_impa)
    residuals, so round 2 on IS 1.2 would retry identical failures.
    """
    before = {("BS 2.2", "2021"): 1180.99, ("BS 3.2", "2021"): 40.83, ("IS 1.2", "2021"): 15.04}
    # BS closed (gone), IS 1.2 remains with the SAME residual
    after = [("IS 1.2", "2021", 15.04)]
    assert _round2_residuals_unchanged(after, before) is True


def test_round2_run_when_residual_changed():
    """Round 1's override shrank a still-failing residual → round 2 may close it."""
    before = {("BS 2.2", "2021"): 1180.99, ("IS 1.2", "2021"): 15.04}
    # IS 1.2 residual shrank after a shared-field override
    after = [("IS 1.2", "2021", 3.50)]
    assert _round2_residuals_unchanged(after, before) is False


def test_round2_run_when_new_failure_appeared():
    """A new (code, period) not in round-1's set → round 2 should attempt it."""
    before = {("BS 2.2", "2021"): 1180.99}
    after = [("BS 3.2", "2021", 40.83)]  # was not a round-1 failure
    assert _round2_residuals_unchanged(after, before) is False


def test_round2_skip_when_empty_after():
    """All failures closed → nothing to retry (loop would have returned ok)."""
    before = {("BS 2.2", "2021"): 1180.99}
    assert _round2_residuals_unchanged([], before) is True
