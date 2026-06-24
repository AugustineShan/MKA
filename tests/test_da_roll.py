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


# ---------------------------------------------------------------------------
# Task 2.3: 扩张 Cohort 直线折旧
# ---------------------------------------------------------------------------
def test_expansion_cohort_depreciates_from_transfer_year():
    from src.da_roll import Cohort
    c = Cohort(gross=1000.0, salvage_rate=0.05, life=10, start_year=2025)
    assert c.annual_dep() == pytest.approx(95.0)
    assert c.dep_in_year(2025) == 95.0
    assert c.dep_in_year(2024) == 0.0
    assert c.dep_in_year(2035) == 0.0  # 折 10 年后折尽


def test_cohort_residual_floor():
    from src.da_roll import Cohort
    c = Cohort(gross=1000.0, salvage_rate=0.05, life=10, start_year=2025)
    total = sum(c.dep_in_year(y) for y in range(2025, 2040))
    assert total <= 950.0 + 1e-6


# ---------------------------------------------------------------------------
# Task 2.4: base_cip_to_fixed 转固
# ---------------------------------------------------------------------------
def test_base_cip_transfers_and_depreciates():
    from src.da_roll import roll_cip
    state = roll_cip(base_cip=200.0,
                     base_cip_to_fixed={2025: 80.0, 2026: 60.0},
                     expansion_capex_by_year={2025: 50.0},
                     expansion_cip_to_fixed={2025: 30.0},
                     cat_life=10, cat_salvage=0.05, start_year=2025)
    assert state.cip_balance(2025) == 200.0 + 50.0 - 80.0 - 30.0  # 140
    assert state.transferred_cohorts(2025)[0].gross == 80.0 + 30.0  # base+expansion 转固合并


def test_base_cip_over_transfer_raises():
    """base 转固累计 > base_cip → CipInvariantError(不许凭空创造资产)。"""
    from src.da_roll import roll_cip, CipInvariantError
    with pytest.raises(CipInvariantError, match="over-transferred"):
        roll_cip(base_cip=100.0,
                 base_cip_to_fixed={2025: 80.0, 2026: 30.0},  # 110 > 100
                 expansion_capex_by_year={},
                 expansion_cip_to_fixed={},
                 cat_life=10, cat_salvage=0.05, start_year=2025)


def test_cip_negative_raises():
    """某年 cip 余额 < 0(转固超 capex 堆积)→ CipInvariantError。"""
    from src.da_roll import roll_cip, CipInvariantError
    state = roll_cip(base_cip=0.0,
                     base_cip_to_fixed={},
                     expansion_capex_by_year={2025: 50.0},
                     expansion_cip_to_fixed={2025: 60.0, 2026: 0.0},  # 转固 > 当年 capex
                     cat_life=10, cat_salvage=0.05, start_year=2025)
    with pytest.raises(CipInvariantError, match="negative"):
        state.cip_balance(2025)
