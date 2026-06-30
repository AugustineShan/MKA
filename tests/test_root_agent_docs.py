from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_root_agent_docs_point_to_skill_classification_and_sync_rule():
    for path in ["CLAUDE.md", "Codex.md"]:
        text = _read(path)
        opening = text[:900]
        assert "STOP" in opening
        assert "先判斜杠路由，再选择任何外部技能" in opening
        assert "/ka 百润股份" in opening
        assert "/ka 002568" in opening
        assert "即使公司名或股票代码像证券问题" in opening
        assert "股票行情分析能力" in opening
        assert "docs/技能简要分类.md" in text
        assert "docs/MKA规则导航图.md" in text
        assert "斜杠词" in text
        assert "不是行情查询" in text
        assert "不是 shell" in text
        assert "人工筛选" in text
        assert "cache 默认不是证据入口" in text
        assert "KA 目录顶层 markdown" in text
        assert "入口窄，收纳宽" in text
        assert "宁可进收纳区/stash" in text
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
        assert "财务费用" in text
        assert "`other_fin_exp_abs`" in text
        assert "`income.financial_expense.other_fin_exp_abs`" in text
