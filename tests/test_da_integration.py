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
    monkeypatch.setattr("src.da_roll.roll_da_series", lambda *a, **k: fake_series)

    forecast_mod.run_company_forecast(ticker="002946.SZ")
    params = _read_params(company_dir)
    assert params.get("da_series") == fake_series
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