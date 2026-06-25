from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from src.workbench import _da_view


def _make_company(tmp_path: Path, *, da_schedule: dict | None, da_series: list | None,
                  da_facts: dict | None, with_db: bool, base_year: int = 2025) -> Path:
    company = tmp_path / "companies" / "测试公司_002946"
    agent = company / "Agent"
    (agent / "recon").mkdir(parents=True)
    (agent / ".modelking").mkdir(parents=True)
    if da_schedule is not None:
        (agent / "da_schedule.yaml").write_text(
            yaml.safe_dump(da_schedule, allow_unicode=True), encoding="utf-8")
    if da_facts is not None:
        (agent / "recon" / "da_facts_latest.json").write_text(
            json.dumps(da_facts, ensure_ascii=False), encoding="utf-8")
    if da_series is not None:
        (agent / ".modelking" / "forecast_params.yaml").write_text(
            yaml.safe_dump({"da_series": da_series}, allow_unicode=True), encoding="utf-8")
    if with_db:
        db = agent / "data.db"
        with sqlite3.connect(db) as con:
            con.execute("create table clean_annual (period text, depr_fa_coga_dpba real)")
            con.execute("insert into clean_annual values (?, ?)", (str(base_year), 424.708))
    return company


def _minimal_schedule(enabled=True, base_year=2025):
    return {
        "enabled": enabled, "base_year": base_year,
        "ppe": {"存量策略": {"mode": "perpetual_renewal", "net_growth_rate": 0.0},
                "categories": [
                    {"name": "房屋及建筑物", "life_years": 20, "salvage_rate": 0.05,
                     "base_gross": 2222.666, "base_accum_dep": 578.130, "base_cip": 0.0},
                    {"name": "机器设备", "life_years": 10, "salvage_rate": 0.05,
                     "base_gross": 2394.970, "base_accum_dep": 1395.677, "base_cip": 19.415},
                ]},
        "base_cip_to_fixed": {"2026": {"机器设备": 19.415}},
        "expansion_plan": {"2026": {"capex_by_cat": {"机器设备": 120.0}, "cip_to_fixed": {}}},
        "terminal": {"capex_da_ratio": 1.0, "perpetual_growth": 0.025},
    }


def test_da_view_none_when_no_schedule(tmp_path):
    company = _make_company(tmp_path, da_schedule=None, da_series=None, da_facts=None, with_db=False)
    assert _da_view(company, base_period="2025") is None


def test_da_view_none_when_disabled(tmp_path):
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(enabled=False),
                            da_series=None, da_facts=None, with_db=False)
    assert _da_view(company, base_period="2025") is None


def test_da_view_assembles_categories_and_scale(tmp_path):
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(),
                            da_series=None, da_facts=None, with_db=True)
    view = _da_view(company, base_period="2025")
    assert view is not None
    assert view["enabled"] is True
    assert view["base_year"] == 2025
    cats = view["categories"]
    assert len(cats) == 2                      # N 类 N 元素,数据驱动
    assert cats[0]["name"] == "房屋及建筑物"
    assert cats[0]["policy_dep"] == pytest.approx(2222.666 * 0.95 / 20, rel=1e-4)
    assert cats[0]["base_net"] == pytest.approx(2222.666 - 578.130, rel=1e-4)
    # policy_dep = 2222.666*0.95/20 + 2394.970*0.95/10 = 105.577 + 227.522 = 333.099
    assert view["base_reported_dep"] == pytest.approx(424.708, rel=1e-4)
    assert view["scale"] == pytest.approx(424.708 / 333.099, rel=1e-3)
    assert view["stock_strategy"]["mode"] == "perpetual_renewal"
    assert view["expansion_plan"]["2026"]["capex_by_cat"]["机器设备"] == 120.0


def test_da_view_da_series_passthrough_and_null_when_absent(tmp_path):
    # 无 forecast_params → da_series None
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(),
                            da_series=None, da_facts=None, with_db=True)
    assert _da_view(company, base_period="2025")["da_series"] is None

    # 有 → 透传
    series = [{"period": "2026", "ppe_depreciation": 426.6, "fix_assets_net": 2870.7,
               "cip_balance": 200.0, "ppe_capex": 624.7,
               "ppe_capex_split": {"maintenance": 425, "expansion": 200, "organic": 0}}]
    company2 = _make_company(tmp_path / "b", da_schedule=_minimal_schedule(),
                             da_series=series, da_facts=None, with_db=True)
    view = _da_view(company2, base_period="2025")
    assert view["da_series"] == series


def test_da_view_facts_passthrough(tmp_path):
    facts = {"ppe_detail": {"2025": {}}, "roll_forward_checks": [], "policy": {"source_year": 2025}}
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(),
                            da_series=None, da_facts=facts, with_db=True)
    view = _da_view(company, base_period="2025")
    assert view["facts"] == facts


def test_da_view_align_warning_when_base_year_mismatch(tmp_path):
    company = _make_company(tmp_path, da_schedule=_minimal_schedule(base_year=2024),
                            da_series=None, da_facts=None, with_db=True, base_year=2024)
    view = _da_view(company, base_period="2025")   # defaults base_period=2025, schedule base_year=2024
    assert view is not None
    assert view.get("align_warning")


def test_da_view_other_depreciating_assets_in_scale_and_payload(tmp_path):
    """生物资产类别参与 scale 分母 + 出现在 payload(无 other 时 payload 字段为 None)。"""
    sched = _minimal_schedule()
    sched["other_depreciating_assets"] = {
        "存量策略": {"net_growth_rate": 0.0},
        "categories": [{"name": "生产性生物资产", "life_years": 5, "salvage_rate": 0.20,
                        "base_gross": 1360.099, "base_accum_dep": 290.367, "base_cip": 0.0}],
    }
    company = _make_company(tmp_path, da_schedule=sched, da_series=None, da_facts=None, with_db=True)
    view = _da_view(company, base_period="2025")
    # other 出现在 payload
    assert view["other_depreciating_assets"] is not None
    other_cats = view["other_depreciating_assets"]["categories"]
    assert len(other_cats) == 1
    assert other_cats[0]["name"] == "生产性生物资产"
    assert other_cats[0]["policy_dep"] == pytest.approx(1360.099 * 0.80 / 5, rel=1e-4)
    # scale 分母含 other:ppe policy_dep=333.099 + other 217.616 = 550.715;reported 424.708
    assert view["scale"] == pytest.approx(424.708 / 550.715, rel=1e-3)

    # 无 other_depreciating_assets → payload 字段 None
    company2 = _make_company(tmp_path / "b", da_schedule=_minimal_schedule(),
                             da_series=None, da_facts=None, with_db=True)
    view2 = _da_view(company2, base_period="2025")
    assert view2["other_depreciating_assets"] is None

