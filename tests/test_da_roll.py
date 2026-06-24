"""Tests for src/da_roll.py — 确定性滚动执行器 (Step 2)."""
import pytest


# ---------------------------------------------------------------------------
# Task 2.1: da_schedule loader + base 对齐
# ---------------------------------------------------------------------------
def test_base_year_mismatch_raises(tmp_path):
    from src.da_roll import load_da_schedule, DaAlignError
    sched = tmp_path / "da_schedule.yaml"
    sched.write_text("enabled: true\nbase_year: 2023\n", encoding="utf-8")
    with pytest.raises(DaAlignError, match="base_year"):
        load_da_schedule(sched, defaults_base_period="2024")


def test_disabled_returns_none(tmp_path):
    from src.da_roll import load_da_schedule
    sched = tmp_path / "da_schedule.yaml"
    sched.write_text("enabled: false\nbase_year: 2024\n", encoding="utf-8")
    assert load_da_schedule(sched, defaults_base_period="2024") is None


# ---------------------------------------------------------------------------
# Task 2.2: 存量永续更新折旧
# ---------------------------------------------------------------------------
def test_stock_depreciation_constant_at_g0():
    from src.da_roll import stock_depreciation
    assert stock_depreciation(base_dep=100.0, g=0.0, t=5) == 100.0


def test_stock_depreciation_grows_with_g():
    from src.da_roll import stock_depreciation
    assert stock_depreciation(100.0, g=0.03, t=1) == 103.0
    assert stock_depreciation(100.0, g=0.03, t=2) == pytest.approx(106.09)
