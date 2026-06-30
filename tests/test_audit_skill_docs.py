from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_audit_route_is_documented_as_read_only_radar():
    classification = _read("docs/技能简要分类.md")
    navigation = _read("docs/MKA规则导航图.md")
    launcher = _read(".claude/skills/audit/SKILL.md")

    for text in [classification, navigation, launcher]:
        assert "/audit" in text
        assert "财务健康度" in text
        assert "不改" in text

    assert "risk_ranking.md" in launcher
    assert "evidence_pack_latest.json" in launcher
    assert "不是买卖建议" in launcher or "不是交易建议" in launcher
