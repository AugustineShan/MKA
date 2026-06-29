from __future__ import annotations

from pathlib import Path

from src.company_paths import (
    important_files_dir,
    top_weight_markdown_store_dir,
    top_weight_material_dir,
)
from src.ka_prepare import DEFAULT_CORE_VIEW, MANIFEST_NAME, prepare_top_weight_materials


def test_prepare_top_weight_materials_includes_default_core_view(tmp_path: Path):
    companies_dir = tmp_path / "companies"
    company = companies_dir / "新乳业_002946"
    company.mkdir(parents=True)
    (company / DEFAULT_CORE_VIEW).write_text("默认 thesis", encoding="utf-8")
    important_dir = important_files_dir(company)
    important_dir.mkdir(parents=True)
    (important_dir / "最新会议纪要.txt").write_text("最重要最新的会议纪要", encoding="utf-8")
    source_dir = top_weight_material_dir(company)
    source_dir.mkdir(parents=True)
    (source_dir / "最高权重补充.txt").write_text("管理层最新口径", encoding="utf-8")

    manifest = prepare_top_weight_materials(company, companies_dir=companies_dir)
    store = top_weight_markdown_store_dir(company)

    assert manifest["source_count"] == 3
    assert manifest["important_dir"] == str(important_dir)
    assert store.is_dir()
    assert (store / "00_公司判断和最新观点__md.md").exists()
    assert (store / "01_重要文件_最新会议纪要__txt.md").exists()
    assert (store / "最高权重补充__txt.md").exists()
    assert (store / MANIFEST_NAME).exists()
    assert "默认 thesis" in (store / "00_公司判断和最新观点__md.md").read_text(encoding="utf-8")
    assert "最重要最新的会议纪要" in (store / "01_重要文件_最新会议纪要__txt.md").read_text(encoding="utf-8")
    assert "管理层最新口径" in (store / "最高权重补充__txt.md").read_text(encoding="utf-8")
    assert {item["role"] for item in manifest["materials"]} == {
        "default_core_view",
        "root_important_material",
        "top_weight_material",
    }


def test_prepare_top_weight_materials_idempotent_skips_unchanged(tmp_path: Path):
    companies_dir = tmp_path / "companies"
    company = companies_dir / "新乳业_002946"
    company.mkdir(parents=True)
    (company / DEFAULT_CORE_VIEW).write_text("v1", encoding="utf-8")

    first = prepare_top_weight_materials(company, companies_dir=companies_dir)
    second = prepare_top_weight_materials(company, companies_dir=companies_dir)

    assert first["counts"]["converted"] == 1
    assert second["counts"]["skipped"] == 1


def test_prepare_top_weight_materials_allows_empty_high_weight_inputs(tmp_path: Path):
    companies_dir = tmp_path / "companies"
    company = companies_dir / "新乳业_002946"
    company.mkdir(parents=True)

    manifest = prepare_top_weight_materials(company, companies_dir=companies_dir)

    assert manifest["source_count"] == 0
    assert top_weight_markdown_store_dir(company).is_dir()
    assert (top_weight_markdown_store_dir(company) / MANIFEST_NAME).exists()
