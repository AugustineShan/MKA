from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_webka_skill_doc_structure():
    text = _read(".claude/skills/webka/SKILL.md")

    # 纯打包器定位
    assert "网页端 /ka 打包器" in text
    assert "纯打包器" in text
    assert "不在本地做裁决" in text
    # 执行动作
    assert "py -m src.webka" in text
    assert "src.ka_prepare" in text
    assert "同权重判断材料" in text
    assert "重要文件" in text
    # 两道门禁
    assert "§2 已有正式稿门禁" in text
    assert "§6b 骨架门禁" in text
    assert "--rebuild" in text
    # 三份 md
    assert "readme first.md" in text
    assert "必读和素材.md" in text
    assert "不必要读强制碰到再速查.md" in text
    # 输出目录
    assert "webka(Claude帮你统摄核心假设）" in text
    # 打包 4 份规则
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "knobs块契约.md" in text
    assert "核心假设编辑器_skill_v*.md" in text
    # 明确不打包
    assert "financial_expense.yaml" in text
    assert "data.db" in text
    assert "yaml1算法模板契约" in text
    # 带回本地走 /ka 铁律 1
    assert "py scripts/ka_archive.py" in text
    # 退出码
    assert "退出码" in text


def test_webka_module_constants_and_imports():
    from src import webka

    assert webka.WEBKA_SUBDIR == "webka(Claude帮你统摄核心假设）"
    assert webka.README_NAME == "readme first.md"
    assert webka.MUST_READ_NAME == "必读和素材.md"
    assert webka.LOOKUP_NAME == "不必要读强制碰到再速查.md"
    # 非正式稿后缀剔除集
    assert "_核心假设_load" in webka.NON_OFFICIAL_TAGS
    assert "核心假设参考" in webka.NON_OFFICIAL_TAGS


def test_official_draft_filter_excludes_candidates(tmp_path: Path):
    from src import webka

    # 模拟公司根目录：正式稿 + load/brkd/alphapai/参考 候选
    (tmp_path / "新乳业-20260101-核心假设.md").write_text("状态: official", encoding="utf-8")
    (tmp_path / "model_核心假设_load20260101.md").write_text("```knobs\n```", encoding="utf-8")
    (tmp_path / "x_核心假设_brkd20260101.md").write_text("状态: draft", encoding="utf-8")
    (tmp_path / "核心假设参考.md").write_text("状态: reference", encoding="utf-8")
    (tmp_path / "y_核心假设_alphapai20260101.md").write_text("模式: alphapai-load", encoding="utf-8")

    officials = webka._official_drafts(tmp_path)
    names = [p.name for p in officials]
    assert names == ["新乳业-20260101-核心假设.md"]


def test_valid_load_filter_rejects_scaffold(tmp_path: Path):
    from src.company_paths import ka_reference_dir
    from src import webka

    ka_dir = ka_reference_dir(tmp_path)
    ka_dir.mkdir(parents=True)
    # 完整 LOAD：有 knobs 块
    (ka_dir / "核心假设参考load_20260101.md").write_text(
        "模式: load\n状态: model-extracted\n```knobs\nhorizon: []\n```\n", encoding="utf-8"
    )
    # 脚手架：仍是「待模型装载器补全」
    (ka_dir / "核心假设参考load_20260102.md").write_text(
        "待模型装载器补全\n```knobs\n```\n", encoding="utf-8"
    )
    # 无 knobs 块
    (ka_dir / "核心假设参考load_20260103.md").write_text("模式: load\n", encoding="utf-8")

    valid = webka._valid_load_drafts(tmp_path)
    names = [p.name for p in valid]
    assert names == ["核心假设参考load_20260101.md"]


def test_reference_candidates_from_ka_dir_exclude_load(tmp_path: Path):
    from src.company_paths import ka_reference_dir
    from src import webka

    ka_dir = ka_reference_dir(tmp_path)
    ka_dir.mkdir(parents=True)
    (ka_dir / "核心假设参考load_20260101.md").write_text("```knobs\n```", encoding="utf-8")
    (ka_dir / "核心假设参考brkd_20260101.md").write_text("状态: draft", encoding="utf-8")
    (ka_dir / "核心假设参考alphapai_20260101.md").write_text("模式: alphapai-load", encoding="utf-8")

    refs = webka._reference_candidates(tmp_path)
    names = sorted(p.name for p in refs)
    assert names == ["核心假设参考alphapai_20260101.md", "核心假设参考brkd_20260101.md"]


def test_gate_blocks_when_no_skeleton(tmp_path: Path):
    from src import webka

    # 无 BRKD、无 LOAD、无 reference -> §6b 硬停
    with pytest.raises(webka.WebkaGateError, match="骨架门禁|凭空生成"):
        webka._check_gates(tmp_path, rebuild=False)
