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
    assert "_核心假设_brkd{运行YYYYMMDD}.md" in text
    assert "不得命名为普通 `*_核心假设.md`" in text
    assert "年报是 X 光片" in text
    assert "draft / 待 /ka 拍板" in text
    assert "不锁最终时间轴" in text
    assert "overview 第一项必须先报时间线索" in text
    assert "会议 memo" in text
    assert "用户要的是你读完后的判断" in text
    assert "不编造量价原子" in text
    assert "利润表 + 业务层盈利模型理解器" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "由 BS/现金/债务派生的 `financial expense`" in text
    assert "other_fin_exp_abs" in text
    assert "是否升格为 `/ka` 的人工 BS/CF 覆盖，只能由最高权重材料或分析师明示触发" in text
    assert "不生成 YAML1、DCF 或完整 `model_assumption_schema.json`" in text


def test_business_preunderstanding_v3_outputs_comp_style_draft():
    text = _read("skills/业务预理解器_skill_v3.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "markdown存储区" in text
    assert "`核心假设.md` 的半成品" in text
    assert "_核心假设_brkd{运行YYYYMMDD}.md" in text
    assert "draft" in text
    assert "不锁定最终时间轴" in text
    assert "第一幕 overview 必须先报这些时间线索" in text
    assert "时间线索：材料年份、历史事实区间、建议 horizon" in text
    assert "像分析师开会，不像机器审表" in text
    assert "业务理解会议 memo" in text
    assert "确认后，文件里仍按下面模板写全历史事实" in text
    assert "headline 财务事实" in text
    assert "不允许静默忽略" in text
    assert "利润表 + 业务层盈利模型理解器" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "不在 BRKD 中裁决" in text
    assert "是否升格为 `/ka` 的人工 BS/CF 覆盖，只能由最高权重材料或分析师明示触发" in text
    assert "factor_product" in text
    assert "growth" in text
    assert "abs below-OP" in text
    assert "BS/现金/债务派生的 `financial expense` 不写" in text
    assert "other_fin_exp_abs" in text
    assert "待 /ka 拍板" in text
    assert "```knobs" in text
