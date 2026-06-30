"""yaml1_fidelity_check.py 的纯单测。

定位：fidelity checker 是 /comp 的 .md↔yaml1 双射守门员，此前无任何测试。
本套件只测它的三道闸 + helpers，喂合成 dict/字符串，不跑 LLM、不读真实文件、不联网。
所有用例都是毫秒级。
"""
from __future__ import annotations

from src.yaml1_fidelity_check import (
    ALLOWED_FAMILY,
    collect_knobs,
    core_term,
    extract_knobs_block,
    flatten_defaults,
    gate_a,
    gate_b,
    gate_c_diff,
    in_set,
    near,
    parse_numbers,
    resolve_section,
    scope_to_keyword,
    split_sections,
)


# ─────────────── 合成 fixture 构造器 ───────────────

def _seg(family="growth", values=None, margin=None, factor_kind="yoy"):
    """造一个 revenue leaf segment。"""
    seg = {"revenue_family": family, "src": "#业务A"}
    if family in ("factor_product", "vol_price", "driver_rate"):
        seg["factors"] = [{
            "key": "f", "label": "销量", "base": 1,
            "projection": {"kind": factor_kind, "values": values or [0.1, 0.1, 0.1]},
        }]
    elif family in ("growth", "abs"):
        knk = "revenue_yoy" if family == "growth" else "revenue_abs"
        seg["knobs"] = {knk: values or [0.1, 0.1, 0.1]}
    if margin is not None:
        seg.setdefault("knobs", {})["margin"] = margin
    return seg


def _yaml1(family="growth", values=None, margin=None, horizon=3, top_gpm=None, extra_seg=None):
    """造一个最小 yaml1 dict。horizon=3 → meta.horizon 三年。"""
    y1 = {
        "meta": {"horizon": list(range(2025, 2025 + horizon))},
        "income.revenue": {
            "kind": "decomposition",
            "segments": {"a": _seg(family, values, margin)},
        },
    }
    if top_gpm is not None:
        y1["income.gpm"] = {"kind": "knob", "values": top_gpm, "src": "#整体毛利率"}
    if extra_seg is not None:
        y1["income.revenue"]["segments"]["b"] = extra_seg
    return y1


def _fails(findings):
    return [f for f in findings if f[1] == "FAIL"]


def _warns(findings):
    return [f for f in findings if f[1] == "WARN"]


def _paths(findings):
    return {f[2] for f in findings}


# ─────────────── Gate A：结构 ───────────────

def test_gate_a_valid_growth_passes():
    findings = []
    gate_a(_yaml1("growth"), 3, findings)
    assert _fails(findings) == []


def test_gate_a_valid_factor_product_passes():
    findings = []
    gate_a(_yaml1("factor_product"), 3, findings)
    assert _fails(findings) == []


def test_gate_a_illegal_family_fails():
    findings = []
    gate_a(_yaml1("bogus_family"), 3, findings)
    fails = _fails(findings)
    assert len(fails) == 1
    assert "非法 revenue_family" in fails[0][3]


def test_gate_a_illegal_projection_kind_fails():
    y1 = _yaml1("factor_product")
    y1["income.revenue"]["segments"]["a"]["factors"][0]["projection"]["kind"] = "bogus"
    findings = []
    gate_a(y1, 3, findings)
    assert any("projection.kind" in f[3] for f in _fails(findings))


def test_gate_a_array_length_mismatch_fails():
    # 顶层 knob values 长度 2，horizon 3
    y1 = {
        "meta": {"horizon": [2025, 2026, 2027]},
        "income.gpm": {"kind": "knob", "values": [0.3, 0.3], "src": "#整体毛利率"},
        "income.revenue": {"kind": "decomposition", "segments": {"a": _seg("growth")}},
    }
    findings = []
    gate_a(y1, 3, findings)
    assert any("数组长度" in f[3] for f in _fails(findings))


def test_gate_a_factor_values_length_mismatch_fails():
    # factor_product 的 factor projection values 长度 2，horizon 3
    y1 = _yaml1("factor_product", values=[0.1, 0.1])
    findings = []
    gate_a(y1, 3, findings)
    assert any("长度" in f[3] for f in _fails(findings))


def test_gate_a_margin_mutex_fails():
    # 顶层 gpm + leaf margin 同时存在 = over-determined
    y1 = _yaml1("growth", margin=[0.3, 0.3, 0.3], top_gpm=[0.3, 0.3, 0.3])
    findings = []
    gate_a(y1, 3, findings)
    assert any("over-determined" in f[3] for f in _fails(findings))


def test_gate_a_leaf_margin_without_top_gpm_passes():
    # 分线 margin 单独存在，无顶层 gpm → 合法
    findings = []
    gate_a(_yaml1("growth", margin=[0.3, 0.3, 0.3]), 3, findings)
    assert _fails(findings) == []


def test_gate_a_node_both_decomposition_and_leaf_fails():
    # 节点既是 decomposition 又挂 revenue_family
    y1 = _yaml1("growth")
    y1["income.revenue"]["revenue_family"] = "growth"  # decomposition 节点不该挂 family
    findings = []
    gate_a(y1, 3, findings)
    assert any("既是 decomposition 又挂 revenue_family" in f[3] for f in _fails(findings))


def test_gate_a_depth_exceeds_two_fails():
    # income.revenue -> segments.a(decomposition) -> segments.b(decomposition) -> segments.c
    # 第二级 decomposition 已是 depth 1→2，再嵌一层就 >2
    deep = {
        "kind": "decomposition",
        "segments": {"c": {"kind": "decomposition", "segments": {
            "d": _seg("growth")
        }}},
    }
    y1 = _yaml1("growth", extra_seg=deep)
    findings = []
    gate_a(y1, 3, findings)
    assert any("深度 > 2" in f[3] for f in _fails(findings))


def test_gate_a_knob_values_not_list_fails():
    y1 = {"meta": {"horizon": [2025, 2026, 2027]},
          "income.gpm": {"kind": "knob", "values": "not a list", "src": "#整体毛利率"},
          "income.revenue": {"kind": "decomposition", "segments": {"a": _seg("growth")}}}
    findings = []
    gate_a(y1, 3, findings)
    assert any("values 不是数组" in f[3] for f in _fails(findings))


# ─────────────── Gate B：路径 + 符号 + 费率 ───────────────

def test_gate_b_path_missing_fails():
    std_knobs = [("income.cost_rates.sell_exp", [0.1, 0.1, 0.1], "#销售费用")]
    defaults_flat = {"income.gpm": 0.3}  # 故意不含 sell_exp
    findings = []
    gate_b(std_knobs, defaults_flat, findings)
    assert any("不在 defaults" in f[3] for f in _fails(findings))


def test_gate_b_sign_opposite_warns():
    # yaml1 基年 +0.1，defaults 基年 -0.5，符号相反 → WARN（不是 FAIL）
    std_knobs = [("income.operating_adjustments_abs.asset_disp_income", [0.1, 0.1, 0.1], "#资产处置")]
    defaults_flat = {"income.operating_adjustments_abs.asset_disp_income": -0.5}
    findings = []
    gate_b(std_knobs, defaults_flat, findings)
    assert any("符号与 defaults" in f[3] for f in _warns(findings))
    assert _fails(findings) == []


def test_gate_b_rate_out_of_range_warns():
    # 费率路径值 > 1 → WARN
    std_knobs = [("income.cost_rates.sell_exp", [1.5, 1.5, 1.5], "#销售费用")]
    defaults_flat = {"income.cost_rates.sell_exp": 0.15}
    findings = []
    gate_b(std_knobs, defaults_flat, findings)
    assert any("超出 [0,1)" in f[3] for f in _warns(findings))


def test_gate_b_valid_passes():
    std_knobs = [("income.cost_rates.sell_exp", [0.15, 0.15, 0.15], "#销售费用")]
    defaults_flat = {"income.cost_rates.sell_exp": 0.15}
    findings = []
    gate_b(std_knobs, defaults_flat, findings)
    assert findings == []


# ─────────────── Gate C-DIFF：knobs 块结构双射 ───────────────

def _block(entries):
    return {"knobs": entries}


def test_gate_c_diff_match_passes():
    std_knobs = [("income.cost_rates.sell_exp", [0.154, 0.154, 0.154], "#销售费用")]
    block = _block([{"anchor": "#销售费用", "family": "cost_rate", "unit": "pct",
                     "values": [15.4, 15.4, 15.4]}])  # pct → /100 = 0.154
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any(f[1] == "PASS" for f in findings)
    assert _fails(findings) == []


def test_gate_c_diff_value_mismatch_fails():
    std_knobs = [("income.cost_rates.sell_exp", [0.20, 0.20, 0.20], "#销售费用")]
    block = _block([{"anchor": "#销售费用", "unit": "pct", "values": [15.4, 15.4, 15.4]}])
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any("值与生成器自报不符" in f[3] for f in _fails(findings))


def test_gate_c_diff_length_mismatch_fails():
    std_knobs = [("income.cost_rates.sell_exp", [0.15, 0.15, 0.15], "#销售费用")]
    block = _block([{"anchor": "#销售费用", "unit": "pct", "values": [15.4, 15.4]}])  # 长度 2 vs 3
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any("数组长度不符" in f[3] for f in _fails(findings))


def test_gate_c_diff_yaml1_knob_missing_in_block_fails():
    # yaml1 有旋钮，knobs 块没有 → 幻觉/src 错
    std_knobs = [("income.cost_rates.sell_exp", [0.15, 0.15, 0.15], "#销售费用")]
    block = _block([{"anchor": "#管理费用", "unit": "pct", "values": [5.0, 5.0, 5.0]}])
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any("yaml1 旋钮在 knobs 块无对应" in f[3] for f in _fails(findings))


def test_gate_c_diff_block_entry_missing_in_yaml1_fails():
    # knobs 块有条目，yaml1 没认领 → 漏译
    std_knobs = [("income.cost_rates.sell_exp", [0.15, 0.15, 0.15], "#销售费用")]
    block = _block([
        {"anchor": "#销售费用", "unit": "pct", "values": [15.0, 15.0, 15.0]},
        {"anchor": "#管理费用", "unit": "pct", "values": [5.0, 5.0, 5.0]},
    ])
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any("漏译" in f[3] for f in _fails(findings))


def test_gate_c_diff_leaf_factor_via_sub_matches():
    # 收入 leaf 因子（销量）通过 anchor+sub 匹配 knobs 块条目
    std_knobs = []
    leaves = [("income.revenue.segments.a", "销量", [0.07, 0.06, 0.06], "#业务A", "factor_product", 0)]
    block = _block([{"anchor": "#业务A", "sub": "销量", "family": "factor_yoy", "unit": "pct",
                     "values": [7.0, 6.0, 6.0]}])
    findings = []
    gate_c_diff(std_knobs, leaves, block, findings)
    assert any(f[1] == "PASS" for f in findings)
    assert _fails(findings) == []


def test_gate_c_diff_block_entry_without_anchor_fails():
    block = _block([{"family": "cost_rate", "unit": "pct", "values": [15.0, 15.0, 15.0]}])  # 缺 anchor
    findings = []
    gate_c_diff([], [], block, findings)
    assert any("缺 anchor" in f[3] for f in _fails(findings))


# ─────────────── 减值符号门 + top-level knob sub 兜底 ───────────────

def test_impact_sign_positive_fails():
    # assets_impair_loss 存正数 → 引擎会当加项加回虚增利润 → FAIL
    std_knobs = [("income.cost_abs.assets_impair_loss", [66.0, 66.0, 66.0], "#资产减值损失")]
    block = _block([{"anchor": "#资产减值损失", "family": "cost_abs", "unit": "abs_mn",
                     "values": [66, 66, 66]}])  # 块也正（block-diff 会 PASS，但符号门独立 FAIL）
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any("IMPACT" in str(f[2]) or "减值项" in f[3] for f in _fails(findings))


def test_impact_sign_negative_passes():
    # 损失存负 → 不触发符号门
    std_knobs = [("income.cost_abs.assets_impair_loss", [-66.0, -66.0, -66.0], "#资产减值损失")]
    block = _block([{"anchor": "#资产减值损失", "family": "cost_abs", "unit": "abs_mn",
                     "values": [-66, -66, -66]}])
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert all("减值项" not in f[3] for f in _fails(findings))


def test_impact_sign_zero_passes():
    # 零放行（百润 assets_impair=0、绿联 credit=0 合法）
    std_knobs = [("income.cost_abs.credit_impa_loss", [0.0, 0.0, 0.0], "#信用减值损失")]
    block = _block([{"anchor": "#信用减值损失", "family": "cost_abs", "unit": "abs_mn",
                     "values": [0, 0, 0]}])
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert all("减值项" not in f[3] for f in _fails(findings))


def test_impact_sign_only_for_impact_fields():
    # 非 IMPACT 的 cost_abs（如 comm_exp）存正不触发（走 total_cogs 正成本路径）
    std_knobs = [("income.cost_abs.comm_exp", [10.0, 10.0, 10.0], "#手续费")]
    block = _block([{"anchor": "#手续费", "family": "cost_abs", "unit": "abs_mn",
                     "values": [10, 10, 10]}])
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert all("减值项" not in f[3] for f in _fails(findings))


def test_top_level_knob_sub_fallback_matches_dividend_payout():
    # balance_sheet.dividend_payout（path 叶子=dividend_payout）匹配 knobs 块
    # {anchor:#分红率, sub:dividend_payout} —— sub 兜底命中，不误报"幻觉"
    std_knobs = [("balance_sheet.dividend_payout", [0.55, 0.55, 0.55], "#分红率")]
    block = _block([{"anchor": "#分红率", "sub": "dividend_payout", "family": "bs_scalar_pct",
                     "unit": "pct", "values": [55, 55, 55]}])  # pct → /100 = 0.55
    findings = []
    gate_c_diff(std_knobs, [], block, findings)
    assert any(f[1] == "PASS" for f in findings)
    assert all("yaml1 旋钮在 knobs 块无对应" not in f[3] for f in _fails(findings))


# ─────────────── helpers ───────────────

def test_parse_numbers_percent():
    assert parse_numbers("15.4%") == [0.154]


def test_parse_numbers_fullwidth_minus():
    # 全角负号 −/– 应归一为 -
    assert parse_numbers("−47.39") == [-47.39]
    assert parse_numbers("–10") == [-10.0]


def test_parse_numbers_mixed():
    # 先吃带 % 的，再吃裸数字，不互相干扰
    nums = parse_numbers("增速 15.4%，金额 200 万元")
    assert 0.154 in nums
    assert 200.0 in nums


def test_core_term_strips_hash_and_parens():
    assert core_term("#整体毛利率(主动覆盖·参数化翻转)") == "整体毛利率"
    assert core_term("#销售费用") == "销售费用"
    assert core_term("#营业外收入（非经常）") == "营业外收入"


def test_near_and_in_set():
    assert near(0.154, 0.1540001)
    assert not near(0.154, 0.16)
    assert in_set(0.154, [0.15, 0.154])
    assert not in_set(0.2, [0.15, 0.154])


def test_extract_knobs_block_present():
    md = "前置\n```knobs\nhorizon: [2025]\nknobs:\n  - anchor: '#销售费用'\n    values: [15.0]\n```\n后置"
    block = extract_knobs_block(md)
    assert isinstance(block, dict)
    assert "knobs" in block
    assert block["knobs"][0]["anchor"] == "#销售费用"


def test_extract_knobs_block_absent_returns_none():
    assert extract_knobs_block("没有 knobs 块的 md") is None


def test_extract_knobs_block_parse_error_captured():
    # 故意写坏 YAML
    md = "```knobs\nknobs: [unclosed\n```"
    block = extract_knobs_block(md)
    assert isinstance(block, dict) and "_err" in block


def test_flatten_defaults_collects_value_leaves():
    defaults = {
        "income": {
            "gpm": {"value": 0.3, "source": "平推"},
            "cost_rates": {"sell_exp": {"value": 0.15}},
        }
    }
    flat = flatten_defaults(defaults)
    assert flat.get("income.gpm") == 0.3
    assert flat.get("income.cost_rates.sell_exp") == 0.15
    # source/note 不进 flat
    assert "income.gpm.source" not in flat


def test_split_sections_and_resolve():
    md = "## 销售费用\n正文\n## 管理费用\n另一段"
    secs = split_sections(md)
    heads = [h for h, _ in secs if h != "(preamble)"]
    assert "销售费用" in heads and "管理费用" in heads
    # resolve_section 能定位
    head, body = resolve_section("#销售费用", secs)
    assert head == "销售费用"
    assert "正文" in body


def test_scope_to_keyword_narrows():
    body = "销售费用率 15.4%\n管理费用率 5.0%"
    scoped = scope_to_keyword(body, "销售费用")
    assert "15.4" in scoped
    assert "5.0" not in scoped


def test_collect_knobs_std_and_leaves():
    y1 = _yaml1("factor_product")
    std, leaves = collect_knobs(y1)
    # factor_product leaf → 收成 leaves（因子级），不是 std
    assert len(leaves) == 1
    assert leaves[0][1] == "销量"
    assert std == []


def test_collect_knobs_top_level_knob():
    y1 = _yaml1("growth", top_gpm=[0.3, 0.3, 0.3])
    std, leaves = collect_knobs(y1)
    # 顶层 income.gpm 是 std knob；growth leaf 是 leaf
    paths = [s[0] for s in std]
    assert "income.gpm" in paths
    assert len(leaves) == 1


def test_allowed_family_is_canonical_set():
    # 与契约/源语言 §B4 对齐：六个族（formula 不是 family，走 kind:formula）
    assert ALLOWED_FAMILY == {
        "factor_product", "driver_rate", "growth", "abs", "vol_price", "vol_price_margin"
    }
