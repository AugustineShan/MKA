from src import annual_report_reconciler as ar


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
