from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_brkd_launcher_refs_shared_sources_and_v19_style_draft_discipline():
    text = _read(".claude/skills/brkd/SKILL.md")

    assert "BRKD业务理解器（研报和纪要放在这里）" in text
    assert "py -m src.brkd_prepare" in text
    assert "markdown存储区" in text
    assert "AI 不直接读取这些源文件" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "A1/A2/A3/A7" in text
    assert "Agent业务讨论.md" in text
    assert "年报是 X 光片" in text
    assert "draft / 待 /ka 拍板" in text
    assert "不锁最终时间轴" in text
    assert "不编造量价原子" in text
    assert "不生成 YAML1、DCF 或完整 `model_assumption_schema.json`" in text


def test_business_preunderstanding_v3_outputs_comp_style_draft():
    text = _read("skills/业务预理解器_skill_v3.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "markdown存储区" in text
    assert "`核心假设.md` 的半成品" in text
    assert "draft" in text
    assert "不锁定最终时间轴" in text
    assert "headline 财务事实" in text
    assert "不允许静默忽略" in text
    assert "factor_product" in text
    assert "growth" in text
    assert "abs below-OP" in text
    assert "待 /ka 拍板" in text
    assert "```knobs" in text
