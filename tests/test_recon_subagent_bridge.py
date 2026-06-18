"""Tests for src.recon_subagent_bridge — the init skill's subagent escalation tier.

锁定 BYD 002594 2019/2021 BS 3.2 场景：estimated_liab 已被 reconciler 地板重分类
出非流动侧，净残差 = lease_liab 缺口。subagent 风格提案经 bridge 服务端验闭合后
应写出 source=claude 的 approved override；脏配平（金额不闭合 / 字段不在 candidate
集）必须被拒。
"""

import json

from src import recon_subagent_bridge as bridge
from src import annual_report_reconciler as recon


# ── resolve_candidate_field（轻量①，reconciler 侧） ──────────────────

def test_resolve_candidate_field_maps_lease_ncl_via_item():
    """LLM 把租赁负债映射成不存在的 lease_ncl → 服务端用科目名映射回 lease_liab。"""
    cands = [
        {"field": "lease_liab", "description": "租赁负债", "annual_report_alias": "租赁负债"},
        {"field": "estimated_liab", "description": "预计负债"},
    ]
    assert recon.resolve_candidate_field("lease_ncl", "租赁负债", cands) == "lease_liab"
    assert recon.resolve_candidate_field(None, "租赁负债", cands) == "lease_liab"
    assert recon.resolve_candidate_field("lease_liab", "租赁负债", cands) == "lease_liab"


def test_resolve_candidate_field_rejects_unknown_item():
    cands = [{"field": "lease_liab", "description": "租赁负债"}]
    assert recon.resolve_candidate_field("bogus", "不存在的科目", cands) is None
    assert recon.resolve_candidate_field("bogus", None, cands) is None


def test_resolve_candidate_field_prefers_longer_specific_name():
    """『非流动负债』不应误命中『其他非流动负债』——长名优先。"""
    cands = [
        {"field": "oth_ncl", "description": "其他非流动负债"},
        {"field": "total_ncl", "description": "非流动负债合计"},
    ]
    # 精确『其他非流动负债』只命中 oth_ncl
    assert recon.resolve_candidate_field(None, "其他非流动负债", cands) == "oth_ncl"


# ── evaluate_proposals（验闭合，防脏配平核心） ────────────────────────

def _byd_2019_context(residual=548.68, direction="target_gt_calc"):
    return {
        "failure": {
            "code": "BS 3.2", "period": "2019", "statement": "balancesheet",
            "residual": residual, "target_value": 25011.226, "calc_value": 24462.546,
            "direction": direction, "message": "BS 3.2 2019 ... residual=...", "title": "非流动负债",
        },
        "bucket": "noncurrent_liab",
        "candidate_fields": [
            {"field": "lease_liab", "description": "租赁负债", "value_million_cny": 0.0, "clean_category": None},
            {"field": "estimated_liab", "description": "预计负债", "value_million_cny": 1824.194, "clean_category": "current_liab"},
            {"field": "lt_borr", "description": "长期借款", "value_million_cny": 11947.932, "clean_category": None},
        ],
        # estimated_liab 已被地板重分类出非流动侧
        "reclass_for_period": {"estimated_liab": "current_liab"},
        "net_residual": residual, "net_direction": direction, "markdown_path": "D:/x.md",
    }


def _lease_liab_proposal(period="2019", value=548.68, raw=548680000.0):
    return {
        "period": period, "code": "BS 3.2", "field": "lease_liab", "operation": "add_override",
        "value_million_cny": value, "annual_report_item": "租赁负债",
        "annual_report_value_raw": raw, "unit": "元人民币",
        "evidence_lines": "10427-10428: 租赁负债 548,680,000.00 元",
        "reasoning": "年报非流动负债段租赁负债 = 净残差",
    }


def test_evaluate_closes_byd_2019_lease_liab():
    ctx = _byd_2019_context()
    approved = bridge.evaluate_proposals(ctx, [_lease_liab_proposal()])
    assert len(approved) == 1
    prop, clean_cat = approved[0]
    assert prop["field"] == "lease_liab"
    assert clean_cat is None  # add_override, no reclass


def test_evaluate_closes_byd_2021_lease_liab():
    ctx = _byd_2019_context(residual=1415.291)
    ctx["failure"]["period"] = "2021"
    p = _lease_liab_proposal(period="2021", value=1415.291, raw=1415291000.0)
    approved = bridge.evaluate_proposals(ctx, [p])
    assert len(approved) == 1


def test_evaluate_rejects_non_closing_amount():
    """金额 666 不闭合 548.68 残差 → 整组拒绝（防脏配平）。"""
    ctx = _byd_2019_context()
    assert bridge.evaluate_proposals(ctx, [_lease_liab_proposal(value=666.0)]) == []


def test_evaluate_rejects_field_outside_candidate_set():
    """subagent 映射到 lease_ncl（不在 candidate 集）→ 拒绝。"""
    ctx = _byd_2019_context()
    bad = {**_lease_liab_proposal(), "field": "lease_ncl"}
    assert bridge.evaluate_proposals(ctx, [bad]) == []


def test_evaluate_reclass_closes_target_lt_calc():
    """移除 estimated_liab(1824.194) 出非流动侧，闭合 target_lt_calc 残差 1824.194。"""
    ctx = _byd_2019_context(residual=1824.194, direction="target_lt_calc")
    ctx["reclass_for_period"] = {}  # 尚未重分类
    p = {
        "period": "2019", "code": "BS 3.2", "field": "estimated_liab", "operation": "reclass",
        "value_million_cny": 1824.194, "clean_category": "current_liab",
        "annual_report_item": "预计负债", "annual_report_value_raw": 1824194000.0,
        "unit": "元人民币", "evidence_lines": "10388-10389: 预计负债 (列示在流动负债项下)",
        "reasoning": "年报预计负债在流动侧，TuShare 默认非流动，需重分类",
    }
    approved = bridge.evaluate_proposals(ctx, [p])
    assert len(approved) == 1
    _, clean_cat = approved[0]
    assert clean_cat == "current_liab"


# ── proposals_to_override_records（审计 schema） ─────────────────────

def test_override_record_is_approved_claude_source():
    ctx = _byd_2019_context()
    approved = bridge.evaluate_proposals(ctx, [_lease_liab_proposal()])
    recs = bridge.proposals_to_override_records(
        ctx, approved, ticker="002594.SZ", source_reconciliation_path="recon/latest.json"
    )
    assert len(recs) == 1
    r = recs[0]
    assert r["status"] == "approved"
    assert r["source"] == "claude"
    assert r["approved_by"] == "claude:high_confidence"
    assert r["field"] == "lease_liab"
    assert r["new_value_million_cny"] == 548.68
    assert r["old_value_million_cny"] == 0.0
    assert r["failure_code"] == "BS 3.2"
    assert r["period"] == "2019"
    assert r["evidence_lines"].startswith("10427-10428")
    assert r["clean_category"] is None


# ── merge_and_write_overrides（去重 + 不覆盖已有） ───────────────────

def test_merge_does_not_duplicate_existing_approved(tmp_path):
    override_path = tmp_path / "annual_report_overrides.json"
    existing = {
        "version": 1, "ticker": "002594.SZ", "adjustments": [
            {"status": "approved", "period": "2019", "field": "lease_liab",
             "source": "glm", "new_value_million_cny": 548.68},
        ],
    }
    override_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    ctx = _byd_2019_context()
    approved = bridge.evaluate_proposals(ctx, [_lease_liab_proposal()])
    recs = bridge.proposals_to_override_records(
        ctx, approved, ticker="002594.SZ", source_reconciliation_path="recon/latest.json"
    )
    summary = bridge.merge_and_write_overrides(override_path, "002594.SZ", recs)
    assert summary["added"] == 0  # 已有 approved (2019, lease_liab) → 跳过
    assert summary["total"] == 1

    # 不同期则正常新增
    recs[0]["period"] = "2021"
    summary = bridge.merge_and_write_overrides(override_path, "002594.SZ", recs)
    assert summary["added"] == 1
    assert summary["total"] == 2


# ── parse_hard_check_failures ────────────────────────────────────────

def test_parse_hard_check_failures_extracts_net_residual():
    stderr = (
        "2026-06-18 12:30:43,993 ERROR clean: ❌ BS 3.2 2019 非流动负债: total_ncl=25011.2260 calc=24462.5460 residual=548.6800\n"
        "HARD CHECK FAIL: BS 3.2 2019 非流动负债: total_ncl=25011.2260 calc=24462.5460 residual=548.6800\n"
        "HARD CHECK FAIL: BS 3.2 2021 非流动负债: total_ncl=20231.9940 calc=18816.7030 residual=1415.2910\n"
        "Validation failed: annual validation failed: 2 hard check(s) failed\n"
    )
    failures = bridge.parse_hard_check_failures(stderr)
    assert len(failures) == 2
    assert failures[0].code == "BS 3.2"
    assert failures[0].period == "2019"
    assert abs(failures[0].residual - 548.68) < 1e-6
    assert failures[0].direction == "target_gt_calc"  # target(25011) > calc(24462)
    assert failures[1].period == "2021"
    assert abs(failures[1].residual - 1415.291) < 1e-6


# ── 跨表 7.4 重述豁免通道 ─────────────────────────────────────────────
#
# 回归锁定 bridge 编码缺陷修复：clean 的 7.4 HARD CHECK FAIL 行含中文『跨表』，
# bridge 子进程未强制 UTF-8 时按 cp936→utf-8 误解码成乱码，parse_failure_message
# 正则失配 → code=UNKNOWN → 被过滤 → 误报 "already passes"。此处用纯 ASCII 构造
# 的 7.4 行锁定解析能识别『跨表 7.4』code（真实中文由 run_clean_annual 的 UTF-8 env 保证）。

def test_parse_hard_check_failures_sees_cross_table_74():
    """跨表 7.4 失败行能被解析（regression for bridge 编码静默吞错缺陷）。"""
    stderr = (
        "HARD CHECK FAIL: 跨表 7.4 2021 上期CF期末(52734.0527) ≠ 本期CF期初(52873.0389)\n"
        "HARD CHECK FAIL: 跨表 7.4 2022 上期CF期末(65134.0340) ≠ 本期CF期初(68626.2808)\n"
        "Validation failed: annual validation failed: 2 hard check(s) failed\n"
    )
    failures = bridge.parse_hard_check_failures(stderr)
    assert len(failures) == 2
    assert failures[0].code == "跨表 7.4"
    assert failures[0].period == "2021"
    assert failures[0].statement == "cross_table"


def test_build_restatement_context_parses_residual_and_direction():
    """build_restatement_context 从 7.4 message 解析 prev_end/cur_beg/残差/方向。"""
    failure = recon.parse_failure_message(
        "跨表 7.4 2021 上期CF期末(52734.0527) ≠ 本期CF期初(52873.0389) residual=138.9862"
    )
    from pathlib import Path
    ctx = bridge.build_restatement_context("000338.SZ", Path("D:/MKA/companies/潍柴动力_000338"), failure)
    assert ctx["kind"] == "restatement"
    assert ctx["prev_period"] == "2020"
    assert abs(ctx["prev_end_cash"] - 52734.0527) < 1e-6
    assert abs(ctx["cur_beg_cash"] - 52873.0389) < 1e-6
    assert abs(ctx["net_residual"] - 138.9862) < 1e-4
    assert ctx["net_direction"] == "restated_up"


def _weichai_2021_context(md_path):
    return {
        "kind": "restatement",
        "failure": {"code": "跨表 7.4", "period": "2021"},
        "prev_period": "2020",
        "prev_end_cash": 52734.0527,   # TuShare 上年期末（原始）
        "cur_beg_cash": 52873.0389,    # TuShare 本期期初（重述后）
        "net_residual": 138.9862,
        "net_direction": "restated_up",
        "markdown_path": str(md_path),
    }


def _write_cf_markdown(md_path, cur_beg_yuan="52,873,038,942.90", prev_end_comp_yuan="52,873,038,942.90"):
    """写一份迷你合并现金流量表期末段，供证据行号校验。"""
    md_path.write_text(
        "加：期初现金及现金等价物余额\n"
        f"{cur_beg_yuan}  42,390,137,403.49\n"
        "六、期末现金及现金等价物余额\n"
        f"65,134,034,010.10  {prev_end_comp_yuan}\n",
        encoding="utf-8",
    )


def test_evaluate_restatement_approves_confirmed(tmp_path):
    """subagent 确认 + 金额在引用行 + 年报自洽 + TuShare 吻合 → 批准豁免。"""
    md = tmp_path / "2021.md"
    _write_cf_markdown(md)
    ctx = _weichai_2021_context(md)
    proposal = {
        "confirmed": True, "period": "2021",
        "cur_beg_disclosed_yuan": 52873038942.90,
        "prev_end_comparative_yuan": 52873038942.90,
        "evidence_lines": "1-4",
        "reasoning": "本期期初=上年比较列期末=52,873,038,942.90，年报自洽，属重述",
    }
    rec = bridge.evaluate_restatement_proposal(ctx, proposal)
    assert rec is not None
    assert rec["status"] == "approved"
    assert rec["source"] == "claude"
    assert rec["check_code"] == "跨表 7.4"
    assert rec["period"] == "2021"
    assert abs(rec["prev_end_cash"] - 52734.0527) < 1e-6
    assert abs(rec["cur_beg_cash"] - 52873.0389) < 1e-6
    assert abs(rec["residual"] - 138.9862) < 1e-4


def test_evaluate_restatement_approves_confirmed_qianyuan_unit(tmp_path):
    """千元制年报（三一重工 600031 2020）也能确认重述豁免。

    回归锁定 bridge 通用性修复：闸门②原只认元制数字串，千元制公司（A 股常见）的
    合并现金流量表写 "4,541,395"（千元整数），元值 4,541,395,000 的数字串不在原文
    → 真实重述被误拒。修复后元/千元两单位皆可，反幻觉仍由闸门③-⑥数值比对兜底。
    """
    md = tmp_path / "2020.md"
    md.write_text(
        "加：期初现金及现金等价物余额\n"
        "4,541,395  5,243,442\n"      # 本期列(2020期初) | 上年比较列(2019期初)
        "六、期末现金及现金等价物余额\n"
        "4,182,163  4,541,395\n",     # 本期列(2020期末) | 上年比较列(2019期末,重述后)
        encoding="utf-8",
    )
    ctx = {
        "kind": "restatement",
        "failure": {"code": "跨表 7.4", "period": "2020"},
        "prev_period": "2019",
        "prev_end_cash": 4451.478,     # TuShare 2019 期末（原始披露）
        "cur_beg_cash": 4541.395,      # TuShare 2020 期初（=年报本期列期初）
        "net_residual": 89.917,
        "net_direction": "restated_up",
        "markdown_path": str(md),
    }
    proposal = {
        "confirmed": True, "period": "2020",
        "cur_beg_disclosed_yuan": 4541395000.0,        # 4,541,395 千元 → 元
        "prev_end_comparative_yuan": 4541395000.0,     # 上年比较列期末（重述后）同值
        "evidence_lines": "1-4",
        "reasoning": "本期期初=上年比较列期末=4,541,395千元，年报自洽，2019期末被追溯重述",
    }
    rec = bridge.evaluate_restatement_proposal(ctx, proposal)
    assert rec is not None
    assert rec["status"] == "approved"
    assert rec["source"] == "claude"
    assert abs(rec["prev_end_cash"] - 4451.478) < 1e-6
    assert abs(rec["cur_beg_cash"] - 4541.395) < 1e-6
    assert abs(rec["residual"] - 89.917) < 1e-4


def test_evaluate_restatement_rejects_fabricated_numbers(tmp_path):
    """subagent 谎报金额（不在引用行原文）→ 反幻觉闸门拒绝。"""
    md = tmp_path / "2021.md"
    _write_cf_markdown(md)
    ctx = _weichai_2021_context(md)
    proposal = {
        "confirmed": True, "period": "2021",
        "cur_beg_disclosed_yuan": 99999999999.99,  # 凭空报数，原文没有
        "prev_end_comparative_yuan": 99999999999.99,
        "evidence_lines": "1-4",
        "reasoning": "骗你的",
    }
    assert bridge.evaluate_restatement_proposal(ctx, proposal) is None


def test_evaluate_restatement_rejects_unrestated_value(tmp_path):
    """subagent 报的是上年原始值（非重述值）→ 闸门4（披露=TuShare本期期初）拒绝。"""
    md = tmp_path / "2021.md"
    _write_cf_markdown(md, cur_beg_yuan="52,734,052,700.00", prev_end_comp_yuan="52,734,052,700.00")
    ctx = _weichai_2021_context(md)
    proposal = {
        "confirmed": True, "period": "2021",
        "cur_beg_disclosed_yuan": 52734052700.00,  # = TuShare 上年期末，非本期期初
        "prev_end_comparative_yuan": 52734052700.00,
        "evidence_lines": "1-4",
        "reasoning": "报错了",
    }
    assert bridge.evaluate_restatement_proposal(ctx, proposal) is None


def test_evaluate_restatement_rejects_unconfirmed(tmp_path):
    md = tmp_path / "2021.md"
    _write_cf_markdown(md)
    ctx = _weichai_2021_context(md)
    assert bridge.evaluate_restatement_proposal(ctx, {"confirmed": False, "period": "2021"}) is None


def test_merge_exemptions_dedup_by_period(tmp_path):
    """同 period 已有 approved 豁免 → 跳过，不覆盖。"""
    path = tmp_path / "restatement_exemptions.json"
    existing = {"version": 1, "ticker": "000338.SZ", "exemptions": [
        {"status": "approved", "period": "2021", "check_code": "跨表 7.4", "source": "claude"},
    ]}
    path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
    new = [
        {"status": "approved", "period": "2021", "check_code": "跨表 7.4", "source": "claude"},  # 重复
        {"status": "approved", "period": "2022", "check_code": "跨表 7.4", "source": "claude"},  # 新增
    ]
    summary = bridge.merge_and_write_exemptions(path, "000338.SZ", new)
    assert summary["added"] == 1
    assert summary["total"] == 2
