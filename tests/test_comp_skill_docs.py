from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_comp_launcher_only_compiles_official_current_assumptions():
    text = _read(".claude/skills/comp/SKILL.md")

    assert "正式假设选择门" in text
    assert "排除 `*参考*.md`" in text
    assert "状态: official" in text
    assert "状态: reference" in text
    assert "状态: draft" in text
    assert "model-extracted" in text
    assert "不能被本 `/comp` 当作公司当前正式假设" in text


def test_comp_launcher_requires_compiler_audit_before_forecast():
    text = _read(".claude/skills/comp/SKILL.md")

    assert "compiler audit" in text
    assert "audit_clean" in text
    assert "覆盖双射" in text
    assert "B 类完整性" in text
    assert "`unaligned` / 路径待核" in text
    assert "语义待核" in text
    assert "reference yaml1" in text
    assert "不跑 official forecast" in text
    assert "落盘即 official 成功" in text


def test_yaml1compiler_declares_official_audit_gate():
    text = _read("skills/yaml1compiler_v5.md")

    assert "official 门禁" in text
    assert "audit_clean = true" in text
    assert "覆盖双射 ok" in text
    assert "B 类完整性 ok" in text
    assert "`unaligned`/路径待核为空" in text
    assert "不得**继续跑 official forecast" in text
    assert "verdict: audit_clean / reference_only" in text
