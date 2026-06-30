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
    assert "核心假设参考load_{YYYYMMDD}.md" in text
    assert "不能被本 `/comp` 当作公司当前正式假设" in text
    assert "读取输入材料" in text
    assert "docs\\knobs块契约.md" in text
    assert "docs\\yaml1前端展示契约.md" in text


def test_comp_launcher_requires_compiler_audit_before_forecast():
    text = _read(".claude/skills/comp/SKILL.md")

    assert "compiler audit" in text
    assert "audit_clean" in text
    assert "覆盖双射" in text
    assert "B 类完整性" in text
    assert "`unaligned`/路径待核" in text
    assert "语义待核" in text
    assert "A 类覆盖" in text
    assert "B 类保全" in text
    assert "主动覆盖回读" in text
    assert "Forecast 状态" in text
    assert "Semantic IR" in text
    assert "源文块识别 -> IR 分类 -> yaml1 落点 -> audit 六段" in text
    assert "docs\\核心假设翻译IR契约.md" in text
    assert "docs\\MKA规则导航图.md" in text
    assert "索引，不算公司输入材料" in text
    assert "reference yaml1" in text
    assert "不跑 official forecast" in text
    assert "落盘即 official 成功" in text
    assert "汇报口吻要像 compiler 审计 memo" in text
    assert "不要把 stdout、yaml1 大段内容或 audit JSON 原样倾倒给用户" in text


def test_yaml1compiler_declares_official_audit_gate():
    text = _read("skills/yaml1compiler_v5.md")

    assert "official 门禁" in text
    assert "audit_clean = true" in text
    assert "覆盖双射 ok" in text
    assert "B 类完整性 ok" in text
    assert "`unaligned`/路径待核为空" in text
    assert "不得**继续跑 official forecast" in text
    assert "verdict: audit_clean / reference_only" in text
    assert "## 9. 翻译后:校对 + 固定报告" in text
    assert "docs/核心假设翻译IR契约.md" in text
    assert "docs/MKA规则导航图.md" in text
    assert "IR 是审计模型" in text
    for heading in ["A 类覆盖", "B 类保全", "路径待核", "语义待核", "主动覆盖回读", "Forecast 状态"]:
        assert heading in text


def test_yaml1compiler_splits_interest_fin_exp_from_other_fin_exp_abs():
    text = _read("skills/yaml1compiler_v5.md")

    assert "财务费用不是铁板一块" in text
    assert "利息净额" in text
    assert "引擎按现金/负债余额倒算" in text
    assert "其他财务费用(外生、非利息项" in text
    assert "income.financial_expense.other_fin_exp_abs" in text
    assert "无论裁决是覆盖还是明确沿用 defaults，都必须写上面的 knob" in text
    assert "沿用 defaults 时从 `defaults.yaml income.financial_expense.other_fin_exp_abs` 取满数组回声" in text
    assert "只有 legacy official 完全未提 `other_fin_exp_abs` 时，yaml1 才可缺席" in text
    assert "不是落 0" in text


def test_comp_launcher_splits_interest_fin_exp_from_other_fin_exp_abs():
    text = _read(".claude/skills/comp/SKILL.md")

    assert "财务费用翻译闸" in text
    assert "生息利息项、利息净额" in text
    assert "`interest_expense_rate`、`cash_interest_rate` 默认缺席" in text
    assert "official 源文若拍了其他财务费用外生·非利息项 `other_fin_exp_abs`" in text
    assert "费用段明确写了“非息财务费用沿用 defaults”" in text
    assert "必须翻成 `income.financial_expense.other_fin_exp_abs`" in text
    assert "不能提到顶层 `financial_expense.*`" in text
    assert "沿用 defaults 时从 `defaults.yaml income.financial_expense.other_fin_exp_abs` 回声满数组" in text
    assert "回落到 `/init` 生成的 defaults" in text


def test_architecture_comp_contract_matches_launcher_order():
    text = _read("docs/ARCHITECTURE.md")

    assert "正式假设选择门" in text
    assert "先跑年份门禁" in text
    assert "读取输入材料" in text
    assert "docs/knobs块契约.md" in text
    assert "docs/yaml1前端展示契约.md" in text


def test_yaml1compiler_allows_manual_bs_cf_overrides_only_on_defaults_paths():
    text = _read("skills/yaml1compiler_v5.md")

    assert "人工 BS/CF 覆盖闸" in text
    assert "balance_sheet.revenue_pct.*" in text
    assert "balance_sheet.cogs_days.*" in text
    assert "balance_sheet.capex_pct" in text
    assert "balance_sheet.depr_rate" in text
    assert "确认不了路径就落值 + `# 路径待核` + `unaligned`" in text
    assert "重资产排程优先 `/da`" in text
    assert "未触发人工覆盖闸的 BS/CF/DCF 驱动" in text


def test_yaml1compiler_translates_fade_target_without_rejudging_it():
    text = _read("skills/yaml1compiler_v5.md")

    assert "target_growth: <衰减交接增速>" in text
    assert "`target_growth` 与 `perpetual_growth` 是两个数" in text
    assert "你不重新计算 target" in text
    assert "若源文没写 target，字段可省略" in text
