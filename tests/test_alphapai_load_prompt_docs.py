from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    return (ROOT / "docs/Alphapai-load核心假设参考提示词.md").read_text(encoding="utf-8")


def test_alphapai_load_prompt_keeps_reference_boundary_and_time_axis_discipline():
    text = _read()

    assert "模式：`alphapai-load`" in text
    assert "状态：`reference`" in text
    assert "不可直接编译" in text
    assert "先会议 memo，后完整参考稿" in text
    assert "不要第一轮直接输出完整 `核心假设参考.md`" in text
    assert "像分析师开会一样" in text
    assert "这个理解方向可以吗？确认后我再输出完整 `核心假设参考.md`" in text
    assert "时间轴四数是参考候选，不是拍板结果" in text
    assert "显式期不能机械默认 5 年" in text
    assert "总览只是导读，不能替代后面 4.4-4.9 的结构化候选" in text
    assert "建议衰减期至: {YYYY / 待裁决}" in text
    assert "永续增长候选: {x% / 待裁决}" in text
    assert "第一轮只输出会议 memo 并等待确认" in text
    assert "用户确认后，第二轮直接输出完整 `核心假设参考.md`" in text


def test_alphapai_load_prompt_keeps_bs_cf_and_knobs_boundaries():
    text = _read()

    assert "BS/CF 硬边界" in text
    assert "不得自行判断它们是核心 thesis" in text
    assert "本节只收纳，不预测，不给逐年候选，不进 `knobs`" in text
    assert "可能的 BS/CF thesis，待人工判断是否走 /da 或专门流程" in text
    assert "`family` 在这里是语义标签，不是 YAML1 path" in text
    assert "只允许以下保守 family" in text
    assert "`bs_revenue_pct`" not in text
    assert "`bs_cogs_days`" not in text
    assert "`bs_scalar_pct`" not in text
    assert "示例年份和值没有被照抄" in text
    assert "不得照抄年份和值" in text
