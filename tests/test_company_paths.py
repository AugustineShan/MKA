from pathlib import Path
from src.company_paths import (
    ensure_workspace_layout,
    active_vore_dir,
    ka_model_dir,
    brkd_material_dir,
)


def test_ensure_workspace_layout_creates_active_vore_subfolders(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    company.mkdir(parents=True)

    ensure_workspace_layout(company)

    assert ka_model_dir(company).is_dir()
    assert brkd_material_dir(company).is_dir()
    assert ka_model_dir(company).parent == active_vore_dir(company)
    assert brkd_material_dir(company).parent == active_vore_dir(company)


def test_ensure_workspace_layout_idempotent(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    company.mkdir(parents=True)
    ensure_workspace_layout(company)
    ensure_workspace_layout(company)
    assert ka_model_dir(company).is_dir()
