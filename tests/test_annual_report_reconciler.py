import json

from src import annual_report_reconciler as ar


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
    assert seen_periods == ["2019", "2020", "2099"]


def test_batch_confirm_empty_candidates_returns_empty():
    assert ar.batch_llm_confirm_candidates("000651.SZ", []) == {"adjustments": []}


def test_comparative_annual_markdown_path_uses_later_report(tmp_path):
    annuals = tmp_path / "annuals"
    annuals.mkdir()
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
