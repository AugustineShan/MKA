from __future__ import annotations

from pathlib import Path

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


def test_stage_core_assumption_done(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    (company / "测试公司-20260626-核心假设.md").write_text("# 假设")
    assert _pipeline_stage(company) == "核心假设完毕"


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
