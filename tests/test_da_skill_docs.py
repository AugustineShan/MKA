from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_da_launcher_blocks_official_forecast_when_enabled_roll_fails():
    text = _read(".claude/skills/da/SKILL.md")

    assert "`enabled: true`" in text
    assert "不得自动回退轻资产路径" in text
    assert "阻断 official forecast" in text
    assert "reference·DA未生效" in text


def test_da_runbook_requires_schedule_audit_provenance():
    text = _read("skills/da_折旧摊销排程_skill_v1.md")

    assert "每个数字必须能立刻归入三类之一" in text
    assert "audit:" in text
    assert "facts_source: Agent/recon/da_facts_latest.json" in text
    assert "decision_log:" in text
    assert "gaps:" in text
    assert "不得自动回退轻资产路径" in text
    assert "reference·DA未生效" in text
