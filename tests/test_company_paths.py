from pathlib import Path
from src.company_paths import (
    ensure_workspace_layout,
    active_vore_dir,
    ka_model_dir,
    brkd_material_dir,
    brkd_markdown_store_dir,
    top_weight_material_dir,
    top_weight_markdown_store_dir,
    adj_increment_dir,
    adj_markdown_store_dir,
    pjbg_rating_report_dir,
    ka_reference_dir,
    load_model_dir,
    skills_materials_dir,
    internal_reports_dir,
    rating_reports_dir,
    tracking_reports_dir,
    deep_reports_dir,
    other_materials_dir,
)


def test_ensure_workspace_layout_creates_active_vore_subfolders(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    company.mkdir(parents=True)

    ensure_workspace_layout(company)

    assert ka_model_dir(company).is_dir()
    assert brkd_material_dir(company).is_dir()
    assert brkd_markdown_store_dir(company).is_dir()
    assert top_weight_material_dir(company).is_dir()
    assert top_weight_markdown_store_dir(company).is_dir()
    assert adj_increment_dir(company).is_dir()
    assert adj_markdown_store_dir(company).is_dir()
    assert pjbg_rating_report_dir(company).is_dir()
    assert ka_reference_dir(company).is_dir()
    assert load_model_dir(company).is_dir()
    assert ka_model_dir(company).parent == active_vore_dir(company)
    assert brkd_material_dir(company).parent == active_vore_dir(company)
    assert brkd_markdown_store_dir(company).parent == brkd_material_dir(company)
    assert top_weight_material_dir(company).parent == active_vore_dir(company)
    assert top_weight_markdown_store_dir(company).parent == top_weight_material_dir(company)
    assert adj_increment_dir(company).parent == active_vore_dir(company)
    assert adj_markdown_store_dir(company).parent == adj_increment_dir(company)
    assert pjbg_rating_report_dir(company).parent == active_vore_dir(company)
    assert ka_reference_dir(company).parent == active_vore_dir(company)
    assert load_model_dir(company).parent == skills_materials_dir(company)


def test_ensure_workspace_layout_creates_internal_reports_subfolders(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    company.mkdir(parents=True)

    ensure_workspace_layout(company)

    assert internal_reports_dir(company).is_dir()
    # 四个子材料夹都落在 内部报告/ 下
    for sub in (rating_reports_dir, tracking_reports_dir, deep_reports_dir, other_materials_dir):
        assert sub(company).is_dir()
        assert sub(company).parent == internal_reports_dir(company)


def test_ensure_workspace_layout_idempotent(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    company.mkdir(parents=True)
    ensure_workspace_layout(company)
    ensure_workspace_layout(company)
    assert ka_model_dir(company).is_dir()
    assert load_model_dir(company).is_dir()
    assert rating_reports_dir(company).is_dir()
