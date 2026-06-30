"""ka_assumption_lint.py 的纯单测。

喂合成 核心假设.md 字符串，断言 PASS/FAIL。无 LLM、无网络、不读真实文件。
"""
from __future__ import annotations

from src.ka_assumption_lint import lint, verdict


def _codes(findings):
    return {f[1] for f in findings if f[0] == "FAIL"}


def _pass_md(family="factor_product", horizon=None, entries=None):
    """造一份合法 .md。horizon 默认 [2026,2027,2028,2029]。"""
    H = horizon or [2026, 2027, 2028, 2029]
    knobs_entries = entries if entries is not None else [
        {"anchor": "#整体毛利率", "family": "gpm", "unit": "pct",
         "values": [29.9, 30.5, 31.1, 31.1]},
        {"anchor": "#销售费用", "family": "cost_rate", "unit": "pct",
         "values": [16.0, 16.0, 16.0, 16.0]},
        {"anchor": "#低温鲜奶", "sub": "销量", "family": "factor_yoy", "unit": "pct",
         "values": [7, 7, 6, 6]},
    ]
    import yaml as _yaml
    block = "horizon: {}\nknobs:\n".format(H)
    for e in knobs_entries:
        block += "  - " + _yaml.safe_dump(e, allow_unicode=True, default_flow_style=True).strip() + "\n"
    md = (
        "# 核心假设 · 示例\n"
        "> 显式预测 2026-2029\n"
        "\n## 收入\n"
        "### 低温鲜奶 [量×价族; compiler: {}]\n"
        "- 旋钮: 销量yoy\n"
        "### 边缘业务 [增速族; compiler: growth]\n"
        "- 旋钮: 收入yoy\n"
        "### 整体毛利率 [income.gpm knob; compiler: 整体手拍]\n"
        "```knobs\n{}\n```\n"
    ).format(family, block)
    return md


# ─────────────── PASS ───────────────

def test_valid_md_passes():
    findings = lint(_pass_md())
    assert _codes(findings) == set()
    assert verdict(findings) == "PASS"


def test_valid_with_growth_family_passes():
    findings = lint(_pass_md(family="growth"))
    assert verdict(findings) == "PASS"


def test_valid_with_driver_rate_passes():
    findings = lint(_pass_md(family="driver_rate"))
    assert verdict(findings) == "PASS"


def test_chinese_compiler_tag_skipped():
    # compiler: 整体手拍 / 分线毛利折叠 是中文语义标签，不是族名，应跳过
    md = _pass_md().replace("compiler: 整体手拍", "compiler: 分线毛利折叠")
    findings = lint(md)
    assert "BAD_FAMILY" not in _codes(findings)


# ─────────────── knobs 块 ───────────────

def test_knobs_block_missing_fails():
    md = "# 核心假设\n## 收入\n### 线A [compiler: growth]\n无 knobs 块"
    findings = lint(md)
    assert "KNOBS_MISSING" in _codes(findings)
    assert verdict(findings) == "BLOCK"


def test_knobs_block_parse_error_fails():
    md = "```knobs\nhorizon: [unclosed\nknobs: [bad\n```"
    findings = lint(md)
    assert "KNOBS_PARSE" in _codes(findings)


# ─────────────── horizon ───────────────

def test_horizon_missing_fails():
    md = _pass_md().replace("horizon: [2026, 2027, 2028, 2029]\n", "")
    findings = lint(md)
    assert "HORIZON" in _codes(findings)


def test_horizon_empty_fails():
    md = _pass_md().replace("horizon: [2026, 2027, 2028, 2029]", "horizon: []")
    findings = lint(md)
    assert "HORIZON" in _codes(findings)


# ─────────────── unit ───────────────

def test_bad_unit_fails():
    entries = [
        {"anchor": "#销售费用", "family": "cost_rate", "unit": "percent",  # 非法 unit
         "values": [16.0, 16.0, 16.0, 16.0]},
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "UNIT" in _codes(findings)


# ─────────────── values 长度 ───────────────

def test_values_length_mismatch_fails():
    entries = [
        {"anchor": "#销售费用", "family": "cost_rate", "unit": "pct",
         "values": [16.0, 16.0, 16.0]},  # 长度 3 vs horizon 4
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "LEN" in _codes(findings)


def test_values_not_list_fails():
    entries = [
        {"anchor": "#销售费用", "family": "cost_rate", "unit": "pct", "values": "全程 16%"},
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "LEN" in _codes(findings)


def test_entry_missing_anchor_fails():
    entries = [
        {"family": "cost_rate", "unit": "pct", "values": [16.0, 16.0, 16.0, 16.0]},  # 缺 anchor
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "KNOBS_PARSE" in _codes(findings)


# ─────────────── margin 互斥 ───────────────

def test_margin_mutex_fails():
    # 同时有 gpm（整体手拍）和 leaf_margin（分线折叠）
    entries = [
        {"anchor": "#整体毛利率", "family": "gpm", "unit": "pct",
         "values": [29.9, 29.9, 29.9, 29.9]},
        {"anchor": "#低温鲜奶", "sub": "毛利率", "family": "leaf_margin", "unit": "pct",
         "values": [35.0, 35.0, 35.0, 35.0]},
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "MARGIN_MUTEX" in _codes(findings)


def test_leaf_margin_alone_passes():
    # 只有 leaf_margin，无 gpm → 合法
    entries = [
        {"anchor": "#低温鲜奶", "sub": "毛利率", "family": "leaf_margin", "unit": "pct",
         "values": [35.0, 35.0, 35.0, 35.0]},
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "MARGIN_MUTEX" not in _codes(findings)


# ─────────────── compiler family ───────────────

def test_bad_ascii_family_fails():
    # 自创英文族名 → FAIL
    md = _pass_md().replace("compiler: factor_product", "compiler: volume_x_price")
    findings = lint(md)
    assert "BAD_FAMILY" in _codes(findings)


def test_typo_family_fails():
    # 拼写错 factor_producte
    md = _pass_md().replace("compiler: factor_product", "compiler: factor_producte")
    findings = lint(md)
    assert "BAD_FAMILY" in _codes(findings)


def test_renamed_family_fails():
    # vol_price 是兼容名但仍合法；改成 vol_price2 应 FAIL
    md = _pass_md(family="vol_price")  # 合法
    assert "BAD_FAMILY" not in _codes(lint(md))
    md2 = _pass_md(family="vol_price2")  # 非法
    assert "BAD_FAMILY" in _codes(lint(md2))


def test_no_compiler_in_block_header_skipped():
    # 块头没有 compiler: 字段 → 不抓（不强制每块都有）
    md = _pass_md().replace("[量×价族; compiler: factor_product]", "[量×价族]")
    findings = lint(md)
    assert "BAD_FAMILY" not in _codes(findings)


# ─────────────── knobs §7 family 块头标签合法（revenue_family ∪ knobs family） ───────────────

def test_knobs_family_compiler_tag_accepted():
    # cost_rate / cost_abs / op_adj_abs / below_line_abs / tax_rate / minor_rate / bs_scalar_pct
    # 都是合法的 knobs §7 family 块头标签，不得误报 BAD_FAMILY
    for tag in ["cost_rate", "cost_abs", "op_adj_abs", "below_line_abs",
                "tax_rate", "minor_rate", "bs_scalar_pct", "gpm", "leaf_margin"]:
        md = _pass_md().replace("compiler: factor_product", "compiler: " + tag)
        assert "BAD_FAMILY" not in _codes(lint(md)), tag


def test_formula_compiler_tag_accepted():
    # formula 块头标签合法（formula leaf 用 kind: formula，不是 revenue_family，但 .md 块头可写 compiler: formula）
    md = _pass_md().replace("compiler: factor_product", "compiler: formula")
    assert "BAD_FAMILY" not in _codes(lint(md))


# ─────────────── cost_abs 减值符号门 ───────────────

def test_cost_abs_positive_fails():
    # .md 作者误写正数幅度（"损失项写正数金额"）→ FAIL COST_ABS_SIGN
    entries = [
        {"anchor": "#资产减值损失", "family": "cost_abs", "unit": "abs_mn",
         "values": [66, 66, 66, 66]},
    ]
    md = _pass_md(entries=entries)
    findings = lint(md)
    assert "COST_ABS_SIGN" in _codes(findings)
    assert verdict(findings) == "BLOCK"


def test_cost_abs_negative_passes():
    entries = [
        {"anchor": "#资产减值损失", "family": "cost_abs", "unit": "abs_mn",
         "values": [-66, -66, -66, -66]},
    ]
    findings = lint(_pass_md(entries=entries))
    assert "COST_ABS_SIGN" not in _codes(findings)


def test_cost_abs_zero_passes():
    # 零放行（信用减值归零等合法）
    entries = [
        {"anchor": "#信用减值损失", "family": "cost_abs", "unit": "abs_mn",
         "values": [0, 0, 0, 0]},
    ]
    findings = lint(_pass_md(entries=entries))
    assert "COST_ABS_SIGN" not in _codes(findings)


def test_non_cost_abs_positive_not_flagged():
    # op_adj_abs（其他收益）正数合法 —— 只 cost_abs 族受符号门约束
    entries = [
        {"anchor": "#其他收益", "family": "op_adj_abs", "unit": "abs_mn",
         "values": [85, 85, 85, 85]},
    ]
    findings = lint(_pass_md(entries=entries))
    assert "COST_ABS_SIGN" not in _codes(findings)

