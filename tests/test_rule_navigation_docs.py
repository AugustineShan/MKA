from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rule_navigation_doc_is_index_not_new_truth_source():
    text = _read("docs/MKA规则导航图.md")

    assert "规则索引，不是新的真源" in text
    assert "以被引用的契约和 skill runbook 为准" in text
    assert "`核心假设.md` 是 canonical 判断源头" in text
    assert "`yaml1` 是派生缓存" in text
    assert "Semantic IR 是 `/comp` 的翻译账本" in text
    assert "raw 投研材料" in text
    assert "待 /ka 裁决清单" in text
    assert "reference 裁决回执" in text
    assert "yaml1 + audit 六段" in text
    assert "## 0.1 人工筛选门" in text
    assert "看见 markdown 不等于必须吸收" in text
    assert "markdown 数量" in text
    assert "KA 目录顶层全部 markdown" in text
    assert "这里的顶层 `*.md` 都是给 `/ka` 的人工筛选材料" in text
    assert "其他 markdown 按信息指引读取" in text
    assert "入口窄，收纳宽" in text
    assert "人工筛选门只限制读取范围，不削弱接缝铁律" in text
    assert "有复盘价值但不入模的信息优先进入收纳区/stash" in text


def test_rule_navigation_doc_points_to_contracts_and_runbooks():
    text = _read("docs/MKA规则导航图.md")

    for path in [
        "docs/技能简要分类.md",
        "docs/核心假设源语言语法规范.md",
        "skills/核心假设源语言_skill_v1.md",
        "skills/核心纪律_skill_v1.md",
        "skills/核心假设编辑器_skill_v1.md",
        "docs/核心假设翻译IR契约.md",
        "skills/yaml1compiler_v5.md",
        "docs/knobs块契约.md",
        "docs/yaml1前端展示契约.md",
        "docs/yaml1算法模板契约.md",
        "docs/数据格式参考.md",
    ]:
        assert path in text


def test_rule_navigation_doc_clarifies_command_boundaries():
    text = _read("docs/MKA规则导航图.md")

    for route in [
        "/brkd",
        "/load",
        "/ka",
        "/adj quick",
        "/frontend-edit",
        "/adj incremental",
        "/annual-update",
        "/comp",
        "/da",
    ]:
        assert route in text
    assert "不在 `/comp` 里重判" in text
    assert "不直接 `/comp`" in text
    assert "不在 `/ka` 自造排程" in text
    assert "只是某个目录里出现了 markdown cache" in text
    assert "不让 `/ka` 主动扩读" in text


def test_rule_navigation_doc_clarifies_b_class_and_bs_cf_exceptions():
    text = _read("docs/MKA规则导航图.md")

    for phrase in [
        "leaf `history`",
        "顶层 `stash`",
        "顶层 `display`",
        "`decision_receipt`",
        "`audit_flag` / `unaligned`",
        "禁止把 B 类塞进 A 类 note",
        "B 类默认是“收纳/展示/审计”的候选",
        "只有确认无复盘价值时",
        "生息财务费用/利息净额",
        "`interest_expense_rate`",
        "`cash_interest_rate`",
        "`financial expense`",
        "`other_fin_exp_abs`",
        "`Agent/financial_expense.yaml`",
        "`income.financial_expense.other_fin_exp_abs` 平推",
        "`balance_sheet.dividend_payout`",
        "`balance_sheet.revenue_pct.*`",
        "`balance_sheet.cogs_days.*`",
        "`balance_sheet.capex_pct`",
        "`balance_sheet.depr_rate`",
        "`# 路径待核`",
        "WACC",
    ]:
        assert phrase in text
