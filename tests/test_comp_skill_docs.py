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
    assert "{原Excel文件名}_核心假设_load{YYYYMMDD}.md" in text
    assert "不能被本 `/comp` 当作公司当前正式假设" in text
    assert "读取五份输入材料" in text
    assert "docs\\knobs块契约.md" in text


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


def test_architecture_comp_contract_matches_launcher_order():
    text = _read("docs/ARCHITECTURE.md")

    assert "正式假设选择门" in text
    assert "先跑年份门禁" in text
    assert "读取五份输入材料" in text
    assert "docs/knobs块契约.md" in text


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
