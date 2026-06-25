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


# ---------------------------------------------------------------------------
# Task 2.5: 有机增长 capex organic_capex
# ---------------------------------------------------------------------------
def test_organic_capex_zero_when_g0():
    from src.da_roll import organic_capex
    assert organic_capex(stock_net=1000.0, g=0.0) == 0.0


def test_organic_capex_funds_stock_growth():
    from src.da_roll import organic_capex
    assert organic_capex(stock_net=1000.0, g=0.03) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Task 2.6: ppe_capex 现金口径 + roll_da_series 装配
# ---------------------------------------------------------------------------
def test_ppe_capex_excludes_transfers():
    """现金支出口径:维持 + 扩张 capex_by_cat + 有机;不含任何 cip_to_fixed 转固额。"""
    from src.da_roll import compute_ppe_capex
    capex = compute_ppe_capex(
        maintenance_dep=100.0,
        expansion_capex_by_cat={2025: 50.0},
        organic={2025: 30.0},
        year=2025)
    assert capex == 180.0  # 100 + 50 + 30, 不含转固


def test_ppe_capex_missing_year_defaults_zero():
    """expansion/organic 当年缺 key → 0(不报错)。"""
    from src.da_roll import compute_ppe_capex
    capex = compute_ppe_capex(
        maintenance_dep=100.0,
        expansion_capex_by_cat={2025: 50.0},
        organic={2025: 30.0},
        year=2026)  # expansion/organic 都无 2026
    assert capex == 100.0  # 仅维持


def test_roll_da_series_smoke_structure():
    """roll_da_series 端到端冒烟:验证产出结构 + 核心口径不为空、不含转固。

    非行为精确断言(留整合测试),只验装配正确:每元素 6 字段齐、period 逐年、
    ppe_capex == maintenance+expansion+organic(口径一致性)。
    """
    from src.da_roll import roll_da_series
    sched = {
        "enabled": True, "base_year": 2024,
        "ppe": {
            "categories": [
                {"name": "房屋", "base_gross": 1000.0, "base_accum_dep": 200.0,
                 "life_years": 20, "salvage_rate": 0.05, "base_cip": 50.0},
            ],
            "存量策略": {"net_growth_rate": 0.03},
        },
        "expansion_plan": {
            2025: {"capex_by_cat": {"房屋": 40.0}, "cip_to_fixed": {"房屋": 20.0}},
        },
        "base_cip_to_fixed": {"房屋": {2025: 30.0}},
    }
    series = roll_da_series(sched, base_bs={}, forecast_years=3,
                            base_year=2024, base_reported_dep=60.0)
    assert len(series) == 3
    assert series[0]["period"] == "2025"
    assert series[2]["period"] == "2027"
    for row in series:
        # 6 字段齐
        assert {"period", "ppe_depreciation", "fix_assets_net", "cip_balance",
                "ppe_capex", "ppe_capex_split"} <= set(row.keys())
        # 口径一致性:ppe_capex = maintenance + expansion + organic
        s = row["ppe_capex_split"]
        assert row["ppe_capex"] == pytest.approx(
            s["maintenance"] + s["expansion"] + s["organic"])
        # 存量净值 > 0(有 base_gross)
        assert row["fix_assets_net"] > 0
        # ppe_depreciation 含存量折旧(scale 校准后 > 0)
        assert row["ppe_depreciation"] > 0


# ---------------------------------------------------------------------------
# Task 2.7: base 年校准 _calibrate_scale
# ---------------------------------------------------------------------------
def test_base_year_calibrates_to_reported_dep():
    """policy_dep = 1000*(1-0.05)/20 = 47.5;披露 60 → scale = 60/47.5。"""
    from src.da_roll import _calibrate_scale
    cats = [{"name": "房屋", "base_gross": 1000, "base_accum_dep": 200,
             "life_years": 20, "salvage_rate": 0.05}]
    scale = _calibrate_scale(cats, base_reported_dep=60.0)
    assert scale == pytest.approx(60.0 / 47.5)


def test_calibrate_scale_empty_cats_returns_one():
    """空 cats → policy_dep=0 → 返回 1.0(不除零)。"""
    from src.da_roll import _calibrate_scale
    assert _calibrate_scale([], base_reported_dep=60.0) == 1.0


def test_calibrate_scale_zero_reported_returns_zero():
    """reported=0 → scale=0(无折旧,合理退化)。"""
    from src.da_roll import _calibrate_scale
    cats = [{"name": "房屋", "base_gross": 1000, "life_years": 20, "salvage_rate": 0.05}]
    assert _calibrate_scale(cats, base_reported_dep=0.0) == 0.0


# ---------------------------------------------------------------------------
# other_depreciating_assets(生产性生物资产/油气资产):折旧流量 + 稳态再投资,
# 净值不进 fix_assets(仍 PP&E only)。g=0 稳态平推(reinvest=折旧,自洽)。
# ---------------------------------------------------------------------------
def _sched_with_other(*, other_cats=None, reported=167.5, g=0.0):
    return {
        "enabled": True, "base_year": 2024,
        "ppe": {"categories": [
            {"name": "房屋", "base_gross": 1000.0, "base_accum_dep": 200.0,
             "life_years": 20, "salvage_rate": 0.05, "base_cip": 0.0}],
            "存量策略": {"net_growth_rate": g}},
        "other_depreciating_assets": {"categories": other_cats or [
            {"name": "生产性生物资产", "base_gross": 600.0, "base_accum_dep": 100.0,
             "life_years": 5, "salvage_rate": 0.0}]},
        # ppe policy_dep=47.5, other policy_dep=120 → 总 167.5 → scale=1.0(当 reported=167.5)
    }


def test_other_depreciating_assets_add_to_depreciation():
    """其他折旧类(生物资产)的存量折旧并入 ppe_depreciation;scale 分母含 other policy_dep。

    ppe_pol=47.5 + other_pol=120 = 167.5;reported=167.5 → scale=1.0;
    t=1 g=0:ppe_depreciation = 47.5 + 120 = 167.5(=披露,真对齐,非偶然)。
    """
    from src.da_roll import roll_da_series
    sched = _sched_with_other(reported=167.5)
    series = roll_da_series(sched, base_bs={}, forecast_years=2,
                            base_year=2024, base_reported_dep=167.5)
    assert series[0]["ppe_depreciation"] == pytest.approx(167.5)
    # other_depreciation 透明键 = other 存量折旧
    assert series[0]["other_depreciation"] == pytest.approx(120.0)


def test_other_assets_maintenance_folded_into_capex():
    """其他折旧类的稳态再投资(=其折旧)并入 ppe_capex(堵 FCFF 陷阱:加回 DA 必须减 reinvest)。

    ppe_capex = ppe_maint(47.5) + other_maint(120) = 167.5(无扩张/有机,g=0)。
    maintenance split = ppe_maint + other_maint。
    """
    from src.da_roll import roll_da_series
    sched = _sched_with_other(reported=167.5)
    series = roll_da_series(sched, base_bs={}, forecast_years=1,
                            base_year=2024, base_reported_dep=167.5)
    row = series[0]
    assert row["ppe_capex"] == pytest.approx(167.5)
    assert row["ppe_capex_split"]["maintenance"] == pytest.approx(167.5)  # 47.5+120


def test_fix_assets_net_excludes_other_assets():
    """fix_assets_net 只含 PP&E 净值,不含生物资产净值(后者 BS held flat,由 calc 平推)。

    ppe base_net=800;other base_net=500。fix_assets_net=800,不是 1300。
    """
    from src.da_roll import roll_da_series
    sched = _sched_with_other(reported=167.5)
    series = roll_da_series(sched, base_bs={}, forecast_years=1,
                            base_year=2024, base_reported_dep=167.5)
    assert series[0]["fix_assets_net"] == pytest.approx(800.0)  # 不含 other 的 500


def test_scale_denominator_includes_other_policy_dep():
    """scale = reported / (ppe_pol + other_pol);other 让 scale 偏离纯 PP&E 的值。

    reported=100:纯 PP&E scale=100/47.5=2.105;含 other scale=100/167.5=0.597。
    验证含 other 时 scale 走 0.597(ppe_depreciation=100)。
    """
    from src.da_roll import roll_da_series
    sched = _sched_with_other(reported=100.0)
    series = roll_da_series(sched, base_bs={}, forecast_years=1,
                            base_year=2024, base_reported_dep=100.0)
    # stock_dep_total = (47.5+120)*0.597 = 100;scale 把总折旧校准到 reported
    assert series[0]["ppe_depreciation"] == pytest.approx(100.0)


def test_no_other_assets_is_bit_exact_ppe_only():
    """无 other_depreciating_assets 时,行为与纯 PP&E 一致(回归保护,other_depreciation=0)。"""
    from src.da_roll import roll_da_series
    sched = {
        "enabled": True, "base_year": 2024,
        "ppe": {"categories": [
            {"name": "房屋", "base_gross": 1000.0, "base_accum_dep": 200.0,
             "life_years": 20, "salvage_rate": 0.05, "base_cip": 0.0}],
            "存量策略": {"net_growth_rate": 0.0}},
    }
    series = roll_da_series(sched, base_bs={}, forecast_years=1,
                            base_year=2024, base_reported_dep=47.5)
    assert series[0]["other_depreciation"] == 0.0
    assert series[0]["ppe_depreciation"] == pytest.approx(47.5)  # scale=1.0, 纯 PP&E
    assert series[0]["fix_assets_net"] == pytest.approx(800.0)

