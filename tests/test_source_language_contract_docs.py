from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_source_language_syntax_contract_defines_markdown_shapes():
    text = _read("docs/核心假设源语言语法规范.md")

    assert "`核心假设.md` 是判断源头" in text
    assert "`yaml1` 是派生缓存" in text
    assert "Semantic IR 是 `/comp` 的翻译账本" in text
    assert "## 待 /ka 裁决清单" in text
    assert "| 事项 | 候选值/方向 | 证据 | 分歧/缺口 | 建议处理 |" in text
    assert "### {名称} [上挂: {科目}; compiler: {family}; status: official]" in text
    assert "## reference 裁决回执" in text
    assert "| 来源 | 事项 | 处理 | official 去处 | 理由 |" in text
    assert "history" in text
    assert "stash" in text
    assert "display" in text
    assert "docs/knobs块契约.md" in text


def test_source_language_syntax_contract_controls_vocabularies():
    text = _read("docs/核心假设源语言语法规范.md")

    for label in ["status", "decision", "source_layer", "unit", "family", "audit_status", "forecast_status"]:
        assert f"### {label}" in text
    assert "draft / reference / model-extracted / factpack/reference / official" in text
    assert "adopted / stashed / gap / rejected" in text
    assert "同权重判断材料 / BRKD / LOAD / Alphapai / init / 年报查证 / 分析师确认" in text
    assert "pct / ratio / abs_mn" in text
    assert "§B4 为唯一真源" in text
    assert "audit_clean / reference_only / failed" in text
    assert "not_run / skipped_missing_data / ran_ok / failed_after_audit_clean / pending_comp_step" in text


def test_translation_ir_contract_defines_semantic_ir_and_audit():
    text = _read("docs/核心假设翻译IR契约.md")

    assert "Semantic IR 翻译账本" in text
    assert "不是新的判断源" in text
    assert "不要求第一版落地成 JSON 文件" in text
    assert "源文块识别 -> IR 分类 -> yaml1 落点 -> audit 六段" in text
    assert "kind, anchor, subject, family, unit, horizon, values, source_layer, decision, target, audit_flags" in text
    for kind in ["calc_knob", "history_atom", "stash_item", "display_item", "decision_receipt", "audit_flag"]:
        assert kind in text
    for decision in ["adopted", "stashed", "gap", "rejected"]:
        assert decision in text
    assert "A 类 = calc_knob" in text
    assert "B 类 = history_atom / stash_item / display_item" in text
    assert "C 类 = decision_receipt / audit_flag" in text
    for heading in ["A 类覆盖", "B 类保全", "路径待核", "语义待核", "主动覆盖回读", "Forecast 状态"]:
        assert heading in text
    assert "py -m src.assumption_md_lint <核心假设.md>" in text
    assert "本轮只预留名字，不实现 CLI" in text
