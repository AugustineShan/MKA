from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from src.company_paths import load_model_dir, webclaude_dir
from src.webload import MERGED_WEBLOAD_FILE, WEBLOAD_SUBDIR, copy_to_webload, newest_versioned_file


def _write_workbook(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    for idx, label in enumerate([2022, 2023, 2024, "2025E", "2026E"], start=2):
        ws.cell(1, idx).value = label
    wb.save(path)
    return path


def test_newest_versioned_file_picks_highest_v_number(tmp_path: Path):
    older = tmp_path / "模型装载器_skill_v1.md"
    newer = tmp_path / "模型装载器_skill_v12.md"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")

    assert newest_versioned_file("模型装载器_skill_v*.md", tmp_path) == newer


def test_copy_to_webload_prepares_sandbox_and_packages_safe_materials(tmp_path: Path):
    company_dir = tmp_path / "影石创新_688775"
    _write_workbook(load_model_dir(company_dir) / "model20250527.xlsx")

    package = copy_to_webload(company_dir, load_id="case", overwrite=True)
    load_dir = Path(package["source_load_manifest"]["load_dir"])
    package_dir = webclaude_dir(company_dir) / WEBLOAD_SUBDIR

    assert Path(package["package_dir"]) == package_dir
    assert load_dir.name == "case"
    assert (load_dir / "model_boundary.json").exists()
    assert (package_dir / MERGED_WEBLOAD_FILE).exists()
    assert not list(package_dir.glob("01_核心纪律_skill_v*.md"))
    assert not list(package_dir.glob("02_核心假设源语言_skill_v*.md"))
    assert not (package_dir / "03_load启动器_SKILL.md").exists()
    assert not (package_dir / "04_model_boundary.md").exists()
    assert not (package_dir / "05_model_boundary.json").exists()
    assert not (package_dir / "06_forbidden_materials.md").exists()
    assert not (package_dir / "07_model20250527_核心假设.md").exists()
    assert not list(package_dir.glob("08_模型装载器_skill_v*.md"))
    assert not (package_dir / "09_load_manifest.json").exists()
    assert list((package_dir / "allowed_materials").glob("model20250527.xlsx"))
    assert not (package_dir / "data_cutoff.db").exists()

    prompt = (package_dir / MERGED_WEBLOAD_FILE).read_text(encoding="utf-8")
    assert "你现在要在网页端执行 `/load`，不是 `/ka`" in prompt
    assert "核心纪律 A：必须完整遵守" in prompt
    assert "核心假设源语言 B：输出语法" in prompt
    assert "模型边界 JSON：精确边界数据" in prompt
    assert "禁读清单：只能作为边界，不得打开正文" in prompt
    assert "模型装载器：/load 独有读法" in prompt
    assert "核心假设脚手架：按这个文件名和结构输出" in prompt
    assert "先给用户完整 overview" in prompt
    assert "data_cutoff.db 不打包到网页端" in prompt

    contract = package["package_contract"]
    assert MERGED_WEBLOAD_FILE in contract["include"]
    assert "核心纪律_skill_v*.md" in contract["embedded_in_merged_markdown"]
    assert "核心假设源语言_skill_v*.md" in contract["embedded_in_merged_markdown"]
    assert "data_cutoff.db" in contract["exclude"]
    assert "load_manifest.json" in contract["exclude"]
    assert "defaults.yaml" in contract["exclude"]
