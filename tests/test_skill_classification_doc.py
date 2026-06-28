from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    return (ROOT / "docs/技能简要分类.md").read_text(encoding="utf-8")


def test_skill_classification_doc_covers_active_entrypoints():
    text = _read()

    for skill in [
        "/init",
        "/brkd",
        "/load",
        "/webload",
        "/ka",
        "/comp",
        "/adj quick",
        "/adj incremental",
        "/frontend-edit",
        "/annual-update",
        "/da",
    ]:
        assert skill in text

    assert "Alphapai-load prompt" in text
    assert "Alphapai业务拆分抓取器" in text
    assert "docs/Alphapai/Alphapai业务拆分抓取器.md" in text
    assert "docs/Alphapai/Alphapai-load核心假设参考提示词.md" in text
    assert "不是本地启动器" in text
    assert "只抓历史 factpack" in text
    assert "不写预测、不写 knobs、不写 terminal" in text
    assert "定向 leaf 表" in text
    assert "最近 5 年完整性优先" in text
    assert "核心假设参考load_{YYYYMMDD}.md" in text
    assert "核心假设参考alphapai_{YYYYMMDD}.md" in text
    assert "核心假设.md 是判断源头" in text
    assert "yaml1" in text
    assert "Agent/forecast/" in text


def test_skill_classification_doc_names_shared_sources_and_boundaries():
    text = _read()

    assert "skills/核心纪律_skill_v1.md" in text
    assert "skills/核心假设源语言_skill_v1.md" in text
    assert "docs/knobs块契约.md" in text
    assert "skills/yaml1compiler_v5.md" in text
    assert "BS/CF/DCF" in text
    assert "重资产 DA/CAPEX" in text
    assert "时间轴" in text
    assert "knobs 同源" in text
