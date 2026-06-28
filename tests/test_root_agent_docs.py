from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_root_agent_docs_point_to_skill_classification_and_sync_rule():
    for path in ["CLAUDE.md", "Codex.md"]:
        text = _read(path)
        assert "docs/技能简要分类.md" in text
        assert "任何新增或修改 skill" in text
        assert "必须同步更新该文档" in text
        assert "/brkd" in text
        assert "/load" in text
        assert "docs/Alphapai/Alphapai业务拆分抓取器.md" in text
        assert "docs/Alphapai/Alphapai-load核心假设参考提示词.md" in text
        assert "/ka" in text
        assert "核心假设生成" in text
        assert "同步共同骨架" in text or "骨架要同步" in text
        assert "职责" in text
        assert "factpack" in text
