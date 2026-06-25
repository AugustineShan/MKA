from __future__ import annotations

from pathlib import Path

from src.adj_prepare import prepare_adj_materials
from src.company_paths import adj_increment_dir, adj_markdown_store_dir


def test_prepare_adj_materials_writes_markdown_store(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    source_dir = adj_increment_dir(company)
    source_dir.mkdir(parents=True)
    (source_dir / "边际信息.txt").write_text("毛利率边际改善", encoding="utf-8")

    manifest = prepare_adj_materials(company, companies_dir=tmp_path / "companies")
    store = adj_markdown_store_dir(company)

    assert manifest["mode"] == "adj_prepare"
    assert manifest["source_count"] == 1
    assert manifest["counts"]["converted"] == 1
    assert store.is_dir()
    assert (store / "边际信息__txt.md").exists()
    assert (store / "adj_prepare_manifest.json").exists()
    assert "毛利率边际改善" in (store / "边际信息__txt.md").read_text(encoding="utf-8")


def test_prepare_adj_materials_idempotent_skips_unchanged(tmp_path: Path):
    company = tmp_path / "companies" / "测试公司_000001"
    source_dir = adj_increment_dir(company)
    source_dir.mkdir(parents=True)
    (source_dir / "边际信息.txt").write_text("v1", encoding="utf-8")

    first = prepare_adj_materials(company, companies_dir=tmp_path / "companies")
    second = prepare_adj_materials(company, companies_dir=tmp_path / "companies")

    assert first["counts"]["converted"] == 1
    assert second["counts"]["skipped"] == 1
