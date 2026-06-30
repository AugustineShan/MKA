from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_knobs_contract_has_one_parseable_official_example():
    path = next((ROOT / "docs").glob("knobs*.md"))
    text = path.read_text(encoding="utf-8")

    blocks = re.findall(r"```knobs\n(.*?)```", text, flags=re.S)

    assert len(blocks) == 1
    doc = yaml.safe_load(blocks[0])
    assert sorted(doc) == ["horizon", "knobs", "terminal"]
    horizon = doc["horizon"]
    assert horizon
    assert doc["terminal"]["fade"]["target_growth"] == 0.055
    for item in doc["knobs"]:
        assert item["anchor"].startswith("#")
        assert item["unit"] in {"pct", "ratio", "abs_mn"}
        assert len(item["values"]) == len(horizon)


def test_shared_knobs_docs_point_to_single_contract():
    targets = [
        ROOT / ".claude" / "skills" / "adj" / "SKILL.md",
        ROOT / ".claude" / "skills" / "annual-update" / "SKILL.md",
        ROOT / ".claude" / "skills" / "brkd" / "SKILL.md",
        ROOT / ".claude" / "skills" / "comp" / "SKILL.md",
        ROOT / ".claude" / "skills" / "frontend-edit" / "SKILL.md",
        ROOT / ".claude" / "skills" / "ka" / "SKILL.md",
        ROOT / ".claude" / "skills" / "load" / "SKILL.md",
        ROOT / ".claude" / "skills" / "webload" / "SKILL.md",
        ROOT / "skills" / "yaml1compiler_v5.md",
        ROOT / "skills" / "业务预理解器_skill_v3.md",
        ROOT / "skills" / "年度更新器_skill_v1.md",
        ROOT / "skills" / "核心假设源语言_skill_v1.md",
        ROOT / "skills" / "核心纪律_skill_v1.md",
        ROOT / "skills" / "核心假设编辑器_skill_v1.md",
        ROOT / "skills" / "核心假设调整器_skill_v1.md",
        ROOT / "skills" / "模型装载器_skill_v3.md",
        ROOT / "docs" / "yaml1忠实度校验.md",
        ROOT / "docs" / "核心假设与编译器技能指南.md",
    ]

    for path in targets:
        assert "knobs块契约.md" in path.read_text(encoding="utf-8")


def test_knobs_contract_defines_manual_bs_cf_override_families():
    path = next((ROOT / "docs").glob("knobs*.md"))
    text = path.read_text(encoding="utf-8")

    assert "`bs_revenue_pct`" in text
    assert "`bs_cogs_days`" in text
    assert "`bs_scalar_pct`" in text
    assert "balance_sheet.revenue_pct.*" in text
    assert "balance_sheet.cogs_days.*" in text
    assert "balance_sheet.capex_pct" in text
    assert "balance_sheet.depr_rate" in text
    assert "balance_sheet.dividend_payout" in text
    assert "`dividend_payout` 是 `/ka` 强制检测项" in text
    assert "`family: bs_scalar_pct`、`sub: dividend_payout`、`unit: pct`" in text
    assert "若只是明确沿用 defaults，只在正文说明，不写入 `knobs`" in text
    assert "`other_fin_exp_abs` 与分红率不同" in text
    assert "若明确沿用 defaults，也要写 `family: other_fin_exp_abs`" in text
    assert "确保 yaml1 有 `income.financial_expense.other_fin_exp_abs` 可供前端编辑" in text
    assert "重资产排程优先 `/da`" in text
    assert "未被明示为核心 thesis 的 BS/CF/DCF 驱动因素" in text
    assert "`balance_sheet.dividend_payout` 是强制检测例外" in text
    assert "`terminal.fade.target_growth`" in text
    assert "不是可 quick 拨动的 knobs" in text


def test_every_skill_that_mentions_knobs_points_to_contract():
    roots = [ROOT / ".claude" / "skills", ROOT / "skills"]
    offenders: list[str] = []
    needles = ("knobs", "```knobs", "机器自报清单")

    for root in roots:
        for path in root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if any(needle in text for needle in needles) and "knobs块契约.md" not in text:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
