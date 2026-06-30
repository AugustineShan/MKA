from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_codex_tutorial_prompt_points_to_rule_navigation():
    text = _read("app/src/tutorialContent.ts")

    assert r"D:\\MKA\\docs\\MKA规则导航图.md" in text
    assert "它只是契约索引，不替代具体 skill" in text
    assert "候选晋升" in text
    assert "B 类去向" in text
    assert "BS/CF 例外" in text
    assert "/ka、/adj、/annual-update" in text
    assert "规则迷路看导航图" in text
    assert "STOP，先判斜杠路由，再选择任何外部技能" in text
    assert "/ka 百润股份" in text
    assert "/ka 002568" in text
    assert "即使公司名或股票代码像证券问题" in text
    assert "不是行情查询" in text
    assert "股票行情分析能力" in text
    assert "人工筛选是第一门禁" in text
    assert "cache 默认不是证据入口" in text
    assert "KA 目录顶层 markdown" in text
    assert "KA 目录顶层全部 markdown" in text
    assert "其他 markdown 按信息指引读" in text
    assert "不主动扩大材料面" in text
    assert "入口窄，收纳宽" in text
    assert "有复盘价值但暂不入模的信息宁可进收纳区/stash" in text
    assert "已入场材料有价值但不入模时，进收纳区/stash" in text


def test_codex_tutorial_guides_ka_to_check_other_fin_exp_abs():
    text = _read("app/src/tutorialContent.ts")

    assert "非息财务费用 other_fin_exp_abs" in text
    assert "沿用 defaults 也要写入 official knobs" in text
    assert "financial_expense.yaml 会进入速查参考" in text
    assert "core_metrics_overview.md + financial_expense.yaml + OfficialBreakdowns csv" in text


def test_codex_tutorial_view_mentions_rule_navigation():
    text = _read("app/src/Tutorial.tsx")

    assert "规则导航图" in text
    assert "人工筛选入口" in text
    assert "进收纳区/stash" in text
    assert "D:\\MKA\\docs\\MKA规则导航图.md" in text
