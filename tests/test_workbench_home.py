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
    assert signals["workbench_materials"] == {"reports": 1, "notes": 1, "collected": 1, "important": 1}
    assert signals["agent_materials"]["load"] == 1
    assert signals["agent_materials"]["pjbg"] == 1


def test_signals_no_yaml1_date_null(tmp_path: Path) -> None:
    company = _make_company(tmp_path)
    (company / "Agent").mkdir()
    (company / "Agent" / "data.db").write_bytes(b"")
    (company / "Agent" / "defaults.yaml").write_text("meta: {}")
    signals = _folder_overview_signals(company)
    assert signals["yaml1_date"] is None
    assert signals["yaml1_versions"] == 0
    assert signals["root_models"]["archive_eligible"] is False
