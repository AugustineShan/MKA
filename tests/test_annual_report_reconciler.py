import json

from src import annual_report_reconciler as ar
from src.company_paths import annual_reports_dir


def _candidate(period, code, field, value):
    return {
        "period": period,
        "failure": {"period": period, "code": code, "residual": value},
        "candidate": {
            "candidate_tushare_field": field,
            "value_million_cny": value,
            "confidence": "high",
        },
    }


def test_batch_confirm_chunks_by_failure_and_isolates_errors(monkeypatch):
    """Each (period, code) failure is confirmed in its own LLM call; a single
    chunk timing out must not discard confirmations from the other chunks."""
    candidates = [
        _candidate("2019", "BS 2.1", "receiv_financing", 28226.249),
        _candidate("2019", "BS 2.1", "acc_receivable", 28226.249),  # same chunk
        _candidate("2020", "BS 2.2", "oth_eq_invest", 4644.6),
        _candidate("2099", "BS 3.2", "lease_liab", 1.0),  # this chunk "times out"
    ]

    seen_periods: list[str] = []

    def fake_call_llm(messages):
        payload = json.loads(messages[1]["content"].split("输入数据：\n", 1)[1])
        periods = {c["failure"]["period"] for c in payload["candidates"]}
        seen_periods.extend(sorted(periods))
        # one chunk should contain exactly one failure's candidates
        assert len(periods) == 1
        period = next(iter(periods))
        if period == "2099":
            return {"error": "kimi request failed: ReadTimeout", "_provider": "glm"}
        adjustments = [
            {
                "period": c["failure"]["period"],
                "approved": True,
                "confidence": "high",
                "candidate_tushare_field": c["candidate"]["candidate_tushare_field"],
                "value_million_cny": c["candidate"]["value_million_cny"],
            }
            for c in payload["candidates"]
        ]
        return {"adjustments": adjustments, "_provider": "glm", "_usage": {"total_tokens": 10}}

    monkeypatch.setattr(ar, "call_llm", fake_call_llm)

    result = ar.batch_llm_confirm_candidates("000651.SZ", candidates)

    # 2019 (BS 2.1) and 2020 (BS 2.2) confirmed; 2099 chunk isolated as error.
    confirmed = {(a["period"], a["candidate_tushare_field"]) for a in result["adjustments"]}
    assert ("2019", "receiv_financing") in confirmed
    assert ("2020", "oth_eq_invest") in confirmed
    assert result.get("partial") is True
    assert [e["period"] for e in result["chunk_errors"]] == ["2099"]
    assert result["_usage"]["total_tokens"] == 20  # 2 successful chunks × 10 (2099 errored)
    # Chunks now confirm concurrently, so call order is not guaranteed; the
    # contract is that every (period, code) chunk is confirmed exactly once.
    assert sorted(seen_periods) == ["2019", "2020", "2099"]


def test_batch_confirm_empty_candidates_returns_empty():
    assert ar.batch_llm_confirm_candidates("000651.SZ", []) == {"adjustments": []}


def test_comparative_annual_markdown_path_uses_later_report(tmp_path):
    annuals = annual_reports_dir(tmp_path)
    annuals.mkdir(parents=True)
    report = annuals / "2020_年度报告.md"
    report.write_text("placeholder", encoding="utf-8")

    assert ar.comparative_annual_markdown_path(tmp_path, "2019") == report


def test_rule_suggestion_uses_official_field_description_for_single_residual():
    analysis = {
        "failure": {"period": "2024", "code": "BS 3.2", "residual": 62.898462},
        "annual_report_context": {
            "snippets": [
                {
                    "text": "\n".join(
                        [
                            "1: 非流动负债：",
                            "2: 租赁负债",
                            "3: 七、31",
                            "4: 62,898,462.00",
                        ]
                    )
                }
            ]
        },
        "candidate_tushare_fields": [
            {
                "field": "lease_liab",
                "description": "租赁负债",
                "value_million_cny": 0.0,
                "clean_category": None,
            }
        ],
    }

    suggestions = ar.rule_based_override_suggestions(analysis)

    assert len(suggestions) == 1
    assert suggestions[0]["source"] == "rule:alias_exact_residual"
    assert suggestions[0]["candidate_tushare_field"] == "lease_liab"
    assert suggestions[0]["value_million_cny"] == 62.898462


def test_rule_suggestion_supports_grouped_residual_matches():
    analysis = {
        "failure": {"period": "2024", "code": "BS 2.2", "residual": 1386.60199595},
        "annual_report_context": {
            "snippets": [
                {
                    "text": "\n".join(
                        [
                            "1: 非流动资产：",
                            "2: 其他非流动金融资产",
                            "3: 七、9",
                            "4: 1,270,327,174.19",
                            "5: 使用权资产",
                            "6: 七、13",
                            "7: 116,274,821.76",
                            "8: 非流动资产合计",
                            "9: 4,236,157,933.96",
                        ]
                    )
                }
            ]
        },
        "candidate_tushare_fields": [
            {
                "field": "oth_illiq_fin_assets",
                "description": "其他非流动金融资产(元)",
                "value_million_cny": 0.0,
                "clean_category": None,
            },
            {
                "field": "use_right_assets",
                "description": "使用权资产",
                "value_million_cny": 0.0,
                "clean_category": None,
            },
        ],
    }

    suggestions = ar.rule_based_override_suggestions(analysis)

    fields = {item["candidate_tushare_field"] for item in suggestions}
    assert fields == {"oth_illiq_fin_assets", "use_right_assets"}
    assert {item["source"] for item in suggestions} == {"rule:alias_group_residual"}
    assert {round(float(item["group_value_million_cny"]), 6) for item in suggestions} == {1386.601996}


def test_exact_single_match_suppresses_speculative_groups():
    """When one annual-report line equals the residual exactly, the weaker
    'fields that merely sum to the residual' groups must not be emitted —
    they can attribute the missing amount to the wrong fields."""
    analysis = {
        "failure": {"period": "2024", "code": "BS 2.1", "residual": 9600.726284},
        "annual_report_context": {
            "snippets": [
                {
                    "text": "\n".join(
                        [
                            "1: 流动资产：",
                            "2: 应收款项融资",
                            "3: 9,600,726,284.77",
                            "4: 应收账款",
                            "5: 6,000,000,000.00",
                            "6: 其他流动资产",
                            "7: 3,600,726,284.77",
                        ]
                    )
                }
            ]
        },
        "candidate_tushare_fields": [
            {"field": "receiv_financing", "description": "应收款项融资", "value_million_cny": 0.0, "clean_category": None},
            {"field": "acc_receivable", "description": "应收账款", "value_million_cny": 0.0, "clean_category": None},
            {"field": "oth_cur_assets", "description": "其他流动资产", "value_million_cny": 0.0, "clean_category": None},
        ],
    }

    suggestions = ar.rule_based_override_suggestions(analysis)

    sources = {item["source"] for item in suggestions}
    assert sources == {"rule:alias_exact_residual"}  # no alias_group_residual
    assert "receiv_financing" in {item["candidate_tushare_field"] for item in suggestions}
    # acc_receivable + oth_cur_assets sum to the residual but must NOT form a group
    assert not any(item.get("candidate_group_id") for item in suggestions)


def test_target_lt_calc_matches_negative_line_item():
    """A target_lt_calc failure (detail sum > subtotal) is explained by a
    NEGATIVE missing line item (e.g. a discontinued-operations loss), so the
    matcher must look for -residual, not +residual."""
    analysis = {
        "failure": {
            "period": "2025",
            "code": "IS 6.3",
            "residual": 21.988382,
            "direction": "target_lt_calc",
        },
        "annual_report_context": {
            "snippets": [
                {
                    "text": "\n".join(
                        [
                            "1: 2、终止经营净利润（净亏损以“-”号填列）",
                            "2: -21,988,381.97",
                            "3: 60,003,164.25",
                        ]
                    )
                }
            ]
        },
        "candidate_tushare_fields": [
            {"field": "end_net_profit", "description": "终止经营净利润", "value_million_cny": 0.0, "clean_category": None},
        ],
    }

    suggestions = ar.rule_based_override_suggestions(analysis)

    assert len(suggestions) == 1
    assert suggestions[0]["candidate_tushare_field"] == "end_net_profit"
    assert round(float(suggestions[0]["value_million_cny"]), 4) == -21.9884


def test_substring_alias_collision_is_suppressed():
    """A short field alias matching inside a longer, more specific line label on
    the same line with the same amount is spurious and must be dropped, so the
    LLM gate sees only the correct field (no ambiguous competitor)."""
    analysis = {
        "failure": {"period": "2021", "code": "BS 2.1", "residual": 25612.056693, "direction": "target_gt_calc"},
        "annual_report_context": {
            "snippets": [
                {
                    "text": "\n".join(
                        [
                            "7376: 应收款项融资",
                            "7377: 七、5",
                            "7378: 25,612,056,693.07",
                        ]
                    )
                }
            ]
        },
        "candidate_tushare_fields": [
            {"field": "acc_receivable", "description": "应收款项", "value_million_cny": 0.0, "clean_category": None},
            {"field": "receiv_financing", "description": "应收款项融资", "value_million_cny": 0.0, "clean_category": None},
        ],
    }

    suggestions = ar.rule_based_override_suggestions(analysis)

    fields = {s["candidate_tushare_field"] for s in suggestions}
    assert fields == {"receiv_financing"}  # acc_receivable substring match dropped


def _failure_from_message(message):
    return ar.parse_failure_message(message)


def test_failure_candidate_fields_exclude_subtotal_targets():
    """subtotal 字段（total_cogs/operate_profit/total_revenue 等）是被校验等式的
    汇总目标本身，不是待补明细。把它们纳入 candidate 会让 LLM 提议"把汇总目标改成
    残差值"——永远脏配平（贵州茅台 IS 1.1：total_cogs 被改成"信用减值损失"值）。
    所有 IS/CF check 的 candidate 集一律不得含 subtotal。"""
    from src import clean

    subtotal_is = {f for f, c in clean.IS_FIELD_CATEGORIES.items() if c == "subtotal"}
    subtotal_cf = {f for f, c in clean.CF_FIELD_CATEGORIES.items() if c == "subtotal"}
    all_subtotal = subtotal_is | subtotal_cf
    assert "total_cogs" in all_subtotal  # 守卫：测试前提成立

    cases = {
        "IS 1.1": "IS 1.1 2024 营业总成本: total_cogs=29817.5665 cost_items=29812.2530 residual=5.3135",
        "IS 1.2": "IS 1.2 2024 营业利润: operate_profit=119688.5795 calc=119690.2096 residual=-1.6301",
        "IS 1.6": "IS 1.6 2024 综合收益: total_compre_income=100.0 calc=95.0 residual=5.0",
        "CF 5.4": "CF 5.4 2024 现金净增加: n_incr_cash_cash_equ=100.0 calc=95.0 residual=5.0",
    }
    for code, msg in cases.items():
        failure = _failure_from_message(msg)
        _bucket, fields = ar.failure_candidate_fields(failure)
        leak = [f for f in fields if f in all_subtotal]
        assert not leak, f"{code} candidate 集泄漏 subtotal: {leak}"


def test_is12_candidates_exclude_revenue_item():
    """IS 1.2 营业利润 = revenue_base - total_cogs + Σ(operating_adjustment)。
    revenue_base/total_cogs 已被 IS 1.6/1.1 钉死，IS 1.2 残差只能由
    operating_adjustment 解释。revenue_item（int_income 等）不在 operate_profit
    公式里——纳入 candidate 会让 LLM 提议对 IS 1.2 calc 零影响的字段，联合闭合
    用 Σ(值) 批准后却制造 IS 1.6 失败（会稽山 2022 int_income 脏 override）。
    IS 1.2 candidate 集必须 = operating_adjustment，排除 revenue_item/cost_item。"""
    from src import clean

    operating = {f for f, c in clean.IS_FIELD_CATEGORIES.items() if c == "operating_adjustment"}
    revenue_items = {f for f, c in clean.IS_FIELD_CATEGORIES.items() if c == "revenue_item"}
    assert "int_income" in revenue_items  # 守卫：测试前提成立
    assert "oth_income" in operating

    failure = _failure_from_message(
        "IS 1.2 2022 营业利润: operate_profit=199.4805 calc=181.9809 residual=17.4996"
    )
    _bucket, fields = ar.failure_candidate_fields(failure)

    # 必须全部是 operating_adjustment
    non_op = [f for f in fields if f not in operating]
    assert not non_op, f"IS 1.2 candidate 含非 operating_adjustment 字段: {non_op}"
    # 关键：int_income（revenue_item）绝不能进 IS 1.2 candidate
    assert "int_income" not in fields, "int_income 不在 IS 1.2 公式，泄漏进 candidate 会脏配平"
    # operating_adjustment 全员到齐（oth_income/credit_impa_loss/asset_disp_income 等）
    assert operating.issubset(set(fields)), f"IS 1.2 candidate 缺 operating_adjustment: {operating - set(fields)}"


def test_is_candidates_narrowed_to_formula_category():
    """每个 IS check 的候选必须窄化到其公式实际用到的 category，排除非公式字段
    （会稽山 int_income 脏 override 同类防御：非公式字段进候选→联合闭合 Σ≈残差
    批准→对 calc 零影响→制造下游 check 失败）。"""
    from src import clean

    cat = clean.IS_FIELD_CATEGORIES
    cases = {
        # code: (message, expected_category_subset, must_exclude_example)
        "IS 1.3": ("IS 1.3 2024 利润总额: total_profit=100.0 calc=95.0 residual=5.0",
                   "below_line", "oth_income"),
        "IS 1.4": ("IS 1.4 2024 净利润: n_income=100.0 calc=95.0 residual=5.0",
                   "tax", "oth_income"),
        "IS 1.5": ("IS 1.5 2024 净利润归属: n_income=100.0 attr_p=80.0 minority=15.0 residual=5.0",
                   "attribution", "oth_income"),
        "IS 1.6": ("IS 1.6 2024 营业总收入≠收入项之和: total_revenue=100.0 revenue_items=95.0 residual=5.0",
                   "revenue_item", "oth_income"),
    }
    for code, (msg, expected_cat, exclude_example) in cases.items():
        failure = _failure_from_message(msg)
        _bucket, fields = ar.failure_candidate_fields(failure)
        expected_fields = {f for f, c in cat.items() if c == expected_cat}
        # 全部候选必须在 expected category
        non_cat = [f for f in fields if f not in expected_fields]
        assert not non_cat, f"{code} candidate 含非 {expected_cat} 字段: {non_cat}"
        # 排除非公式字段（如 oth_income 不在 IS 1.3/1.4/1.5/1.6 公式）
        assert exclude_example not in fields, f"{code} candidate 不应含 {exclude_example}"


def test_llm_propose_fallback_rejects_nonzero_old_value(monkeypatch):
    """add_override 语义只补 TuShare 漏录/为 0 字段，不得覆盖已有非 0 值。
    贵州茅台 IS 1.1 的脏 override 就是 LLM 把"信用减值损失 -5.31 百万"写进
    total_cogs（old=29817≠0）。fallback 必须对齐 rule_based 既有守卫：old_value
    非 0 一律拒绝，即使 LLM 自报 diff<TOLERANCE 也不批。"""
    analysis = {
        "failure": {
            "period": "2024",
            "code": "IS 1.1",
            "residual": 5.3135,
            "direction": "target_gt_calc",
        },
        "annual_report_context": {
            "markdown_path": "fake.md",
            "snippets": [{"text": "5271: 信用减值损失\n5272: -5,313,489.80"}],
        },
        "candidate_tushare_fields": [
            # 一个已有非 0 值的成本明细字段——LLM 企图覆盖它即脏配平
            {"field": "sell_exp", "description": "销售费用", "value_million_cny": 3340.0, "clean_category": None},
        ],
    }

    def fake_call_llm(messages):
        return {
            "suspected_tushare_issue": True,
            "confidence": "high",
            "recommended_action": "add_override",
            "missing_or_suspicious_items": [
                {
                    "candidate_tushare_field": "sell_exp",
                    "annual_report_item": "销售费用",
                    "value_million_cny": -5.3135,
                    "residual_difference_million_cny": 0.0,  # LLM 自报闭合——不可信
                }
            ],
            "_provider": "glm",
        }

    monkeypatch.setattr(ar, "call_llm", fake_call_llm)

    adjustments = ar._llm_propose_fallback(
        "600519.SH",
        None,  # company_dir 未使用（call_llm 已 mock，不读盘）
        None,  # reconciliation_path
        [analysis],
        approve_high_confidence=True,
    )

    # sell_exp 的 old_value=3340≠0，add_override 守卫拒绝，不得生成任何 adjustment
    fields = [a.get("field") for a in adjustments]
    assert "sell_exp" not in fields
    assert adjustments == []


def test_llm_propose_fallback_approves_joint_residual_closure(monkeypatch):
    """IS 1.2 同时缺多个 operating_adjustment（oth_income/credit_impa_loss/
    asset_disp_income）时，单字段都不闭合残差，但三者合计 = signed_residual。
    llm_override_suggestions 的联合闭合分支必须返回整组，fallback 据此批准
    （每字段 old_value=0），让 reconciler 能补 IS operating_adjustment 的
    TuShare-NULL 缺口。这是新乳业 002946 IS 1.2 的典型形态。"""
    analysis = {
        "failure": {
            "period": "2024",
            "code": "IS 1.2",
            "statement": "income",
            "title": "营业利润",
            "message": "IS 1.2 2024 营业利润: operate_profit=680.0076 calc=704.7943 residual=24.7867",
            "residual": 24.7867,  # calc(704.79) > operate_profit(680) → target_lt_calc
            "target_value": 680.0076,
            "calc_value": 704.7943,
            "direction": "target_lt_calc",
        },
        "annual_report_context": {
            "markdown_path": "fake.md",
            "snippets": [{"text": "13730: 加：其他收益 53,883,758.84\n13753: 信用减值损失 8,567,480.16\n13759: 资产处置收益 -87,237,912.06"}],
        },
        "candidate_tushare_fields": [
            {"field": "oth_income", "description": "其他收益", "value_million_cny": 0.0, "clean_category": None},
            {"field": "credit_impa_loss", "description": "信用减值损失", "value_million_cny": 0.0, "clean_category": None},
            {"field": "asset_disp_income", "description": "资产处置收益", "value_million_cny": 0.0, "clean_category": None},
        ],
    }

    def fake_call_llm(messages):
        # 单字段 diff 都大（29.10/16.22/62.45），但 53.88+8.57-87.24 = -24.79 = signed_residual
        return {
            "suspected_tushare_issue": True,
            "confidence": "high",
            "recommended_action": "add_override",
            "missing_or_suspicious_items": [
                {"candidate_tushare_field": "oth_income", "annual_report_item": "其他收益", "value_million_cny": 53.8838, "residual_difference_million_cny": 29.0971},
                {"candidate_tushare_field": "credit_impa_loss", "annual_report_item": "信用减值损失", "value_million_cny": 8.5675, "residual_difference_million_cny": 16.2192},
                {"candidate_tushare_field": "asset_disp_income", "annual_report_item": "资产处置收益", "value_million_cny": -87.2379, "residual_difference_million_cny": 62.4512},
            ],
            "_provider": "glm",
        }

    monkeypatch.setattr(ar, "call_llm", fake_call_llm)
    adjustments = ar._llm_propose_fallback("002946.SZ", None, None, [analysis], approve_high_confidence=True)

    fields = {a.get("field") for a in adjustments}
    assert fields == {"oth_income", "credit_impa_loss", "asset_disp_income"}
    # 联合闭合 + 每字段 old_value=0 → 全部 approved
    assert all(a.get("status") == "approved" for a in adjustments)


def test_llm_propose_rejects_value_not_in_consolidated_statement(monkeypatch):
    """抓错列防御：LLM 把附注/母公司表的同名字段值当合并主表值（会稽山 2022
    oth_income 抓成 7.88 而非合并主表 10.54）。用合并利润表 statement snippet
    确定性重抽验证：LLM 值与主表重抽值均不匹配→拒绝该提议，不得生成 override。"""
    analysis = {
        "failure": {
            "period": "2022", "code": "IS 1.2", "statement": "income", "title": "营业利润",
            "message": "IS 1.2 2022 ...", "residual": 7.88,
            "target_value": 199.48, "calc_value": 191.60, "direction": "target_gt_calc",
        },
        "annual_report_context": {
            "markdown_path": "fake.md",
            # 合并利润表 statement snippet（numbered 格式）：其他收益主表 = 10,537,937.53 元
            "snippets": [{"kind": "statement", "text":
                "1: 合并利润表\n2: 加：其他收益\n3: \n4: 10,537,937.53\n5: 8,327,975.56"}],
        },
        "candidate_tushare_fields": [
            {"field": "oth_income", "description": "其他收益", "value_million_cny": 0.0, "clean_category": None},
        ],
    }

    def fake_call_llm(messages):
        return {
            "suspected_tushare_issue": True, "confidence": "high",
            "recommended_action": "add_override",
            "missing_or_suspicious_items": [
                # LLM 自报闭合(7.88≈残差 7.88)，但 7.88 不在合并主表（主表 10.54）→抓错表
                {"candidate_tushare_field": "oth_income", "annual_report_item": "其他收益",
                 "value_million_cny": 7.88, "residual_difference_million_cny": 0.0},
            ],
            "_provider": "glm",
        }
    monkeypatch.setattr(ar, "call_llm", fake_call_llm)
    adjustments = ar._llm_propose_fallback("601579.SH", None, None, [analysis], approve_high_confidence=True)
    # 7.88 与合并主表重抽值(10.5379/8.3280)均不匹配→拒绝，不得生成 override
    assert adjustments == []
    # 拒绝理由落盘 evidence JSON
    assert any(r.get("stage") == "value_not_in_consolidated_statement"
               for r in analysis.get("override_rejections", []))


def test_llm_propose_accepts_value_matching_consolidated_statement(monkeypatch):
    """对照：LLM 值与合并主表重抽值匹配→放行，正常生成 override（不误杀）。"""
    analysis = {
        "failure": {
            "period": "2022", "code": "IS 1.2", "statement": "income", "title": "营业利润",
            "message": "IS 1.2 2022 ...", "residual": 10.5379,
            "target_value": 200.0, "calc_value": 189.4621, "direction": "target_gt_calc",
        },
        "annual_report_context": {
            "markdown_path": "fake.md",
            "snippets": [{"kind": "statement", "text":
                "1: 合并利润表\n2: 加：其他收益\n3: \n4: 10,537,937.53\n5: 8,327,975.56"}],
        },
        "candidate_tushare_fields": [
            {"field": "oth_income", "description": "其他收益", "value_million_cny": 0.0, "clean_category": None},
        ],
    }

    def fake_call_llm(messages):
        return {
            "suspected_tushare_issue": True, "confidence": "high",
            "recommended_action": "add_override",
            "missing_or_suspicious_items": [
                {"candidate_tushare_field": "oth_income", "annual_report_item": "其他收益",
                 "value_million_cny": 10.5379, "residual_difference_million_cny": 0.0},
            ],
            "_provider": "glm",
        }
    monkeypatch.setattr(ar, "call_llm", fake_call_llm)
    adjustments = ar._llm_propose_fallback("601579.SH", None, None, [analysis], approve_high_confidence=True)
    fields = {a.get("field") for a in adjustments}
    assert fields == {"oth_income"}
    assert all(a.get("status") == "approved" for a in adjustments)


def test_empty_override_hint_nudges_only_when_relevant():
    """Opt 5: hint fires iff failures found AND overrides won't be persisted."""
    # failures + no --write-overrides → nudge
    assert ar.empty_override_hint(3, write_overrides=False) is not None
    assert "write-overrides" in ar.empty_override_hint(3, write_overrides=False)
    # failures + --write-overrides → no nudge (overrides will be cached)
    assert ar.empty_override_hint(3, write_overrides=True) is None
    # no failures → no nudge regardless
    assert ar.empty_override_hint(0, write_overrides=False) is None
    assert ar.empty_override_hint(0, write_overrides=True) is None
