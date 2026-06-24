"""Integration tests for the /da skill (forecast injection + calc heavy-asset branches)."""

import pathlib

import pytest
import yaml

from conftest import copy_fixture_company
from src import forecast as forecast_mod
from src import yaml1_cleaner
from src.company_paths import da_history_dir, da_schedule_path


_DA_SCHEDULE = """\
enabled: true
base_year: 2024
ppe:
  categories:
    - name: 房屋
      base_gross: 1000.0
      base_accum_dep: 200.0
      life_years: 20
      salvage_rate: 0.05
      base_cip: 50.0
  存量策略:
    net_growth_rate: 0.03
"""


def _read_params(company_dir: pathlib.Path) -> dict:
    p = company_dir / "Agent" / ".modelking" / "forecast_params.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_da_schedule_path(tmp_path: pathlib.Path):
    """Test da_schedule_path returns correct path."""
    cd = tmp_path
    result = da_schedule_path(cd)
    assert result.name == "da_schedule.yaml"


def test_da_history_dir(tmp_path: pathlib.Path):
    """Test da_history_dir returns correct path."""
    cd = tmp_path
    result = da_history_dir(cd)
    assert result.name == "DAhistory"


def test_gpm_to_ex_dep_identity_at_base():
    from src.forecast import gpm_to_ex_dep
    # gpm_ex_dep = gpm + base_total_dep/revenue
    assert gpm_to_ex_dep(gpm=0.30, base_total_dep=60.0, revenue=1000.0) == pytest.approx(0.36)

def test_ebit_identity_heavy_equals_light_at_base():
    # EBIT_heavy(base) = EBIT_light(base) when da_roll base dep = base_total_dep
    from src.forecast import gpm_to_ex_dep
    revenue = 1000.0
    gpm_light = 0.30
    oper_cost_light = revenue * (1 - gpm_light)          # 700
    base_dep = 60.0
    gpm_ex = gpm_to_ex_dep(gpm_light, base_dep, revenue) # 0.36
    oper_cost_heavy = revenue * (1 - gpm_ex)             # 640
    ebit_light = revenue - oper_cost_light               # 300
    ebit_heavy = revenue - oper_cost_heavy - base_dep    # 1000-640-60=300
    assert ebit_heavy == pytest.approx(ebit_light)


# ---------------------------------------------------------------------------
# Task 3.2: forecast.py da_series injection + fallback
# ---------------------------------------------------------------------------
def test_da_series_injected_when_enabled(tmp_path, monkeypatch):
    """da_schedule.yaml enabled → forecast_params carries da_series + gpm overridden."""
    company_dir = copy_fixture_company(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")
    (company_dir / "Agent" / "da_schedule.yaml").write_text(_DA_SCHEDULE, encoding="utf-8")

    fake_series = [{
        "period": "2025",
        "ppe_depreciation": 50.0,
        "fix_assets_net": 500.0,
        "cip_balance": 80.0,
        "ppe_capex": 60.0,
        "ppe_capex_split": {"maintenance": 50.0, "expansion": 10.0, "organic": 0.0},
    }]

    def fake_roll(sched, base_bs, years, base_year, base_ppe_dep):
        # 产出 years 个元素,供 build_forecast_statements 逐年消费
        return [
            {**fake_series[0], "period": str(base_year + i)}
            for i in range(1, years + 1)
        ]

    monkeypatch.setattr("src.da_roll.roll_da_series", fake_roll)

    forecast_mod.run_company_forecast(ticker="002946.SZ")
    params = _read_params(company_dir)
    injected = params.get("da_series")
    assert injected is not None and len(injected) >= 1
    assert injected[0]["ppe_depreciation"] == 50.0
    # gpm 被覆盖为 ex-dep(每项为正且大于 0)
    gpm = params["income"]["gpm"]
    assert isinstance(gpm, list) and gpm[0] > 0


def test_falls_back_when_da_roll_fails(tmp_path, monkeypatch):
    """roll_da_series 抛非对齐异常 → 回退轻资产,不阻塞,无 da_series,gpm 未被覆盖。"""
    company_dir = copy_fixture_company(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")
    (company_dir / "Agent" / "da_schedule.yaml").write_text(_DA_SCHEDULE, encoding="utf-8")

    def boom(*a, **k):
        raise ValueError("roll exploded")
    monkeypatch.setattr("src.da_roll.roll_da_series", boom)

    # spy:gpm 覆盖在回退路径上绝不应被触发
    override_called = {"v": False}
    orig_override = forecast_mod._apply_gpm_ex_dep

    def spy(fp, btd):
        override_called["v"] = True
        return orig_override(fp, btd)

    monkeypatch.setattr(forecast_mod, "_apply_gpm_ex_dep", spy)

    # 不抛 — 回退轻资产
    forecast_mod.run_company_forecast(ticker="002946.SZ")
    params = _read_params(company_dir)
    assert "da_series" not in params
    assert override_called["v"] is False  # gpm 未被覆盖为 ex-dep


# ---------------------------------------------------------------------------
# Step 4: calc.py heavy-asset branches
# ---------------------------------------------------------------------------
def _heavy_da_series():
    return [{
        "period": "2025",
        "fix_assets_net": 500.0,
        "cip_balance": 80.0,
        "ppe_depreciation": 50.0,
        "ppe_capex": 60.0,
        "ppe_capex_split": {"maintenance": 50.0, "expansion": 10.0, "organic": 0.0},
    }]


def _heavy_bs_yaml2(da_series=None):
    yaml2 = {
        "balance_sheet": {
            "revenue_pct": {"accounts_receiv": [0.1]},
            "cogs_days": {},
            "capex_pct": [0.05],
            "depr_rate": [0.1],
            "dividend_payout": [0.0],
            "amort_intang_assets": [0.0],
            "use_right_asset_dep": [0.0],
            "lt_amort_deferred_exp": [0.0],
        },
        "model": {"plug": "cash"},
    }
    if da_series is not None:
        yaml2["da_series"] = da_series
    return yaml2


def _prev_bs():
    return {
        "fix_assets": 400.0,
        "money_cap": 100.0,
        "undistr_porfit": 200.0,
        "minority_int": 0.0,
    }


def _income_row():
    return {
        "revenue": 1000.0,
        "oper_cost": 640.0,
        "n_income_attr_p": 200.0,
        "minority_gain": 0.0,
    }


def test_heavy_bs_takes_fix_assets_and_cip_from_da_series():
    from src.calc import build_balance_sheet, operating_working_capital
    yaml2 = _heavy_bs_yaml2(_heavy_da_series())
    prev_bs = _prev_bs()
    prev_nwc = operating_working_capital(prev_bs)
    row, metrics = build_balance_sheet(yaml2, prev_bs, _income_row(), idx=1, review_flags=[])
    assert row["fix_assets"] == 500.0          # 取 da_series,不滚 prev_fix*depr_rate
    assert row["cip"] == 80.0                  # cip_balance 进 BS 在建工程行
    assert abs(row["total_assets"] - row["total_liab_hldr_eqy"]) < 1e-4  # BS 配平(plug 跑了)
    assert metrics["nwc"] != prev_nwc          # 营运资本逐年变(没冻在 prev_bs.copy())
    assert metrics["dividends"] is not None    # dividends 算了(防 NameError)
    assert metrics["capex"] == 60.0            # 合并 capex = ppe_capex + 三类(0)
    assert metrics["depreciation"] == 50.0     # ppe_dep 从 da_series


def test_heavy_is_subtracts_explicit_dep_line():
    from src.calc import build_income_statement
    yaml2 = {
        "income": {
            "gpm": [0.36],            # ex-dep gpm
            "effective_tax_rate": [0.25],
            "minority_ratio": [0.0],
        },
        "da_series": _heavy_da_series(),
    }
    fe = {"fin_exp": 0.0, "fin_exp_int_exp": 0.0, "fin_exp_int_inc": 0.0, "other_fin_exp": 0.0}
    row = build_income_statement(yaml2, revenue=1000.0, financial_expense=fe, idx=1)
    assert row["oper_cost"] == pytest.approx(640.0)   # 1000*(1-0.36)
    assert row["depreciation"] == 50.0                 # 显式折旧行 = ppe_dep
    assert row["total_cogs"] == pytest.approx(640.0 + 50.0)  # oper_cost + ppe_dep


def test_heavy_cf_capex_da_from_da_series():
    from src.calc import build_cash_flow
    yaml2 = {
        "balance_sheet": {
            "amort_intang_assets": [5.0],
            "lt_amort_deferred_exp": [0.0],
            "use_right_asset_dep": [0.0],
        },
        "da_series": [{"ppe_depreciation": 50.0, "ppe_capex": 60.0}],
    }
    prev_bs = {"money_cap": 100.0}
    bs_row = {"money_cap": 150.0}
    income_row = {"n_income": 200.0}
    metrics = {"depreciation": 50.0, "capex": 60.0, "nwc": 100.0, "dividends": 10.0}
    cf = build_cash_flow(yaml2, prev_bs, bs_row, income_row, metrics, prev_nwc=90.0, idx=1)
    assert cf["depr_fa_coga_dpba"] == 50.0            # ppe_dep 从 da_series(metrics)
    assert cf["c_pay_acq_const_fiolta"] == 60.0       # 合并 capex(metrics)
    assert cf["amort_intang_assets"] == 5.0           # 三类仍从 yaml1


def test_yaml1_capex_pct_warns_in_heavy_mode():
    from src.calc import build_balance_sheet
    yaml2 = _heavy_bs_yaml2(_heavy_da_series())
    flags = []
    build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1, review_flags=flags)
    assert any(f["code"] == "heavy_capex_pct_ignored" for f in flags)


def test_light_mode_no_capex_pct_warning():
    from src.calc import build_balance_sheet
    yaml2 = _heavy_bs_yaml2(da_series=None)  # 轻资产:无 da_series
    flags = []
    build_balance_sheet(yaml2, _prev_bs(), _income_row(), idx=1, review_flags=flags)
    assert not any(f["code"] == "heavy_capex_pct_ignored" for f in flags)