from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workbench import _pipeline_stage


def _make_company(tmp_path: Path, name: str = "测试公司_002946") -> Path:
    company = tmp_path / "companies" / name
    company.mkdir(parents=True)
    return company


def test_stage_uninitialized_no_db(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    assert _pipeline_stage(company) == "未初始化"


def test_stage_init_done(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    assert _pipeline_stage(company) == "初始化完毕"


def test_stage_preloaded_done(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    ka_dir = company / "Skills素材包" / "KA（ALPHAPAI拆出来的东西放在这里）"
    ka_dir.mkdir(parents=True)
    (ka_dir / "核心假设参考alphapai_20260626.md").write_text("# 参考")
    assert _pipeline_stage(company) == "预加载完毕"


def test_stage_modeled(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    (company / "Agent" / "yaml1_测试公司_20260626.yaml").write_text("meta: {}")
    assert _pipeline_stage(company) == "建模完毕"


def test_stage_modeled_with_da(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    (company / "Agent" / "yaml1_测试公司_20260626.yaml").write_text("meta: {}")
    (company / "Agent" / "da_schedule.yaml").write_text("meta: {}")
    assert _pipeline_stage(company) == "建模完毕且有DA表"


from src.workbench import _folder_overview_signals, _count_files


def test_count_files_handles_missing_dir(tmp_path: Path) -> None:
    assert _count_files(tmp_path / "nope") == 0


def test_count_files_counts_recursively(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.pdf").write_bytes(b"")
    (d / "sub").mkdir()
    (d / "sub" / "b.pdf").write_bytes(b"")
    assert _count_files(d) == 2


def test_signals_full(tmp_path: Path) -> None:
    import os, time
    company = _make_company(tmp_path)
    agent = company / "Agent"
    agent.mkdir()
    (agent / "data.db").write_bytes(b"")
    (agent / "defaults.yaml").write_text("meta: {}")
    (agent / "yaml1_测试公司_20260624.yaml").write_text("meta: {}")
    (agent / "yaml1_测试公司_20260626.yaml").write_text("meta: {}")
    os.utime(agent / "yaml1_测试公司_20260624.yaml", (time.time() - 100, time.time() - 100))
    (agent / "da_schedule.yaml").write_text("meta: {}")
    (company / "测试公司Model-260624.xlsx").write_bytes(b"")
    (company / "测试公司Model-260626.xlsx").write_bytes(b"")
    (company / "~$测试公司Model-260624.xlsx").write_bytes(b"")
    for sub in ("研报", "纪要", "收集", "重要文件"):
        d = company / sub
        d.mkdir()
        (d / "x.pdf").write_bytes(b"")
    sv = company / "Skills素材包"
    for sub in (
        "LOAD外部EXCEL模型理解器（一次最多一个）",
        "BRKD业务理解器（研报和纪要放在这里）",
        "最高权重材料-放Agent最应对齐的材料",
        "ADJ增量信息（用来改模型的边际信息）",
        "PJBG评级报告素材区",
    ):
        d = sv / sub
        d.mkdir(parents=True)
        (d / "y.pdf").write_bytes(b"")

    signals = _folder_overview_signals(company)

    assert signals["pipeline_stage"] == "建模完毕且有DA表"
    assert signals["yaml1_date"] == "2026-06-26"
    assert signals["yaml1_versions"] == 2
    assert signals["yaml1_archive_eligible"] is True
    assert signals["root_models"] == {"excel_count": 2, "lock_count": 1, "archive_eligible": True}
    assert signals["workbench_materials"] == 4
    assert signals["forecast"] is None


def test_signals_no_yaml1_date_null(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    signals = _folder_overview_signals(company)
    assert signals["yaml1_date"] is None
    assert signals["yaml1_versions"] == 0
    assert signals["root_models"]["archive_eligible"] is False


from src.workbench import _archive_models, _unique_dst


def test_archive_yaml1_keeps_latest_moves_rest(tmp_path: Path) -> None:
    import os, time
    company = _make_company(tmp_path)
    agent = company / "Agent"
    agent.mkdir()
    old = agent / "yaml1_测试公司_20260624.yaml"
    new = agent / "yaml1_测试公司_20260626.yaml"
    old.write_text("old")
    new.write_text("new")
    os.utime(old, (time.time() - 100, time.time() - 100))

    result = _archive_models(company)

    assert new.exists() and new.read_text() == "new"
    assert not old.exists()
    assert (agent / "yaml1history" / old.name).exists()
    assert result["archived_yaml1"] == [old.name]


def test_archive_models_keeps_latest_moves_rest_deletes_locks(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    agent = company / "Agent"
    agent.mkdir()
    old_model = company / "测试公司Model-260624.xlsx"
    new_model = company / "测试公司Model-260626.xlsx"
    lock = company / "~$测试公司Model-260624.xlsx"
    old_model.write_bytes(b"old")
    new_model.write_bytes(b"new")
    lock.write_bytes(b"lock")

    result = _archive_models(company)

    assert new_model.exists()
    assert not old_model.exists()
    assert (agent / "Modelhistory" / old_model.name).exists()
    assert not lock.exists()
    assert result["archived_models"] == [old_model.name]
    assert result["deleted_locks"] == [lock.name]


def test_archive_guard_latest_yaml1_untouched(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    agent = company / "Agent"
    agent.mkdir()
    only = agent / "yaml1_测试公司_20260626.yaml"
    only.write_text("only")
    result = _archive_models(company)
    assert only.exists()
    assert result["archived_yaml1"] == []


def test_archive_guard_no_models_no_locks(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    result = _archive_models(company)
    assert result == {"archived_yaml1": [], "archived_models": [], "deleted_locks": []}


def test_archive_guard_forecast_not_touched(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    agent = company / "Agent"
    agent.mkdir()
    fc = agent / "forecast"
    fc.mkdir()
    (fc / "dcf_summary.json").write_text("{}")
    _archive_models(company)
    assert (fc / "dcf_summary.json").exists()


def test_unique_dst_no_collision_on_same_second(tmp_path: Path) -> None:
    d = tmp_path / "hist"
    d.mkdir()
    # First call: base name free → returns base name
    first = _unique_dst(d, "yaml1_x_20260626.yaml")
    assert first == d / "yaml1_x_20260626.yaml"
    # Simulate the base name now exists (e.g. an earlier archive landed there)
    first.write_text("base archive same second")
    # Simulate that the stamped second is already taken (same-second collision)
    base, _, ext = "yaml1_x_20260626.yaml".rpartition(".")
    import time as _time
    stamp = _time.strftime("%H%M%S")
    preplaced = d / f"{base}-{stamp}.{ext}"
    preplaced.write_text("earlier archive same second")
    # Now base exists AND stamped exists → must NOT return preplaced; must append counter
    result = _unique_dst(d, "yaml1_x_20260626.yaml")
    assert result != preplaced
    assert not result.exists()  # caller will create it
    assert result.name.startswith(f"{base}-{stamp}")


def test_forecast_snapshot_extracts_metrics(tmp_path: Path) -> None:
    from src.workbench import _forecast_snapshot
    from src.company_paths import forecast_dir
    from src.derived_metrics import DERIVED_METRICS_FILENAME
    company = _make_company(tmp_path)
    fc = forecast_dir(company)
    fc.mkdir(parents=True)
    (fc / DERIVED_METRICS_FILENAME).write_text(json.dumps({
        "market_snapshot": {"total_mv": 15230.0},
        "annual": {
            "2026": {"revenue_yoy": 0.123, "n_income_attr_p_yoy": 0.15, "pe": 18.5},
            "2027": {"revenue_yoy": 0.10, "n_income_attr_p_yoy": 0.12, "pe": 16.0},
        },
    }), encoding="utf-8")
    snap = _forecast_snapshot(company)
    assert snap is not None
    assert snap["market_cap"] == 15230.0
    assert snap["revenue_yoy"]["2026"] == pytest.approx(0.123)
    assert snap["profit_yoy"]["2027"] == pytest.approx(0.12)
    assert snap["pe"]["2026"] == pytest.approx(18.5)


def test_forecast_snapshot_none_without_forecast(tmp_path: Path) -> None:
    from src.workbench import _forecast_snapshot
    company = _make_company(tmp_path)
    assert _forecast_snapshot(company) is None
