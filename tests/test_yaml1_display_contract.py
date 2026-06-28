from __future__ import annotations

from src.workbench import _yaml1_display_contract, _yaml1_stash_view


def _revenue_view(*names: str) -> dict:
    return {"segments": [{"key": name, "name": name} for name in names]}


def _blocks_by_path(contract: dict) -> dict:
    return {block["path"]: block for block in contract["blocks"]}


def test_display_contract_infers_saiwei_stash_roles_without_partial_match_leak():
    data = {
        "stash": {
            "分线毛利率": {
                "unit": "ratio",
                "series": {
                    "服饰配饰": {"2023": 0.49},
                    "非服饰配饰": {"2023": 0.38},
                },
            },
            "副拆分_按渠道": {
                "unit": "百万元",
                "series": {
                    "B2C 商品销售": {"2023": 6331.68},
                    "B2B 商品销售": {"2023": 75.85},
                    "物流服务": {"2023": 125.77},
                    "其他": {"2023": 30.36},
                },
                "毛利率": {"series": {"B2C 商品销售": {"2023": 0.464}}},
            },
        }
    }

    contract = _yaml1_display_contract(
        data,
        _revenue_view("服饰配饰", "非服饰配饰", "物流服务", "其他业务"),
        _yaml1_stash_view(data),
    )

    blocks = _blocks_by_path(contract)
    assert contract["mode"] == "inferred"
    assert blocks["stash.分线毛利率"]["role"] == "primary_attachment"
    assert blocks["stash.分线毛利率"]["placement"] == "model_table"
    assert blocks["stash.副拆分_按渠道"]["role"] == "secondary_split"
    assert blocks["stash.副拆分_按渠道"]["placement"] == "secondary_table"
    assert any(warning["code"] == "partial_metric_disclosure" for warning in contract["warnings"])


def test_display_contract_keeps_deprecated_business_line_stash_in_reference():
    data = {
        "stash": {
            "LOAD分线销量吨价原子_弃用": {
                "unit": "万吨 / 元",
                "series": {
                    "中高档黄酒": {"2024_LOAD销量": 61474},
                    "普通黄酒及其他酒": {"2024_LOAD销量": 52149},
                },
            }
        }
    }

    contract = _yaml1_display_contract(
        data,
        _revenue_view("中高档黄酒", "普通黄酒及其他酒"),
        _yaml1_stash_view(data),
    )

    block = _blocks_by_path(contract)["stash.LOAD分线销量吨价原子_弃用"]
    assert block["role"] == "deprecated"
    assert block["status"] == "deprecated"
    assert block["placement"] == "reference_tab"


def test_reference_blocks_do_not_emit_partial_metric_disclosure_warnings():
    data = {
        "stash": {
            "finance_history": {
                "unit": "mixed",
                "series": {
                    "interest_income": {"2025_anchor": 12},
                    "other_finance_expense": {"2025_anchor": -3},
                },
                "gross_margin": {"series": {"interest_income": {"2025": 0.1}}},
            }
        }
    }

    contract = _yaml1_display_contract(data, _revenue_view("business_a"), _yaml1_stash_view(data))

    block = _blocks_by_path(contract)["stash.finance_history"]
    assert block["role"] == "reference"
    assert not [warning for warning in contract["warnings"] if warning["code"] == "partial_metric_disclosure"]


def test_declared_display_contract_can_attach_attr_table_stash():
    data = {
        "display": {
            "schema_version": 1,
            "primary_dimension": "business_line",
            "blocks": [
                {
                    "path": "stash.分线毛利率吨成本",
                    "role": "primary_attachment",
                    "placement": "model_table",
                    "dimension": "business_line",
                    "metric": "mixed",
                    "status": "reference",
                }
            ],
        },
        "stash": {
            "分线毛利率吨成本": {
                "unit": "pct / cny_per_ton",
                "series": {
                    "低温鲜奶": {"2024_gpm": 45.65, "2024_ton_cost": 7512.41},
                    "低温酸奶": {"2024_gpm": 31.13, "2024_ton_cost": 7706.76},
                },
            }
        },
    }

    contract = _yaml1_display_contract(
        data,
        _revenue_view("低温鲜奶", "低温酸奶"),
        _yaml1_stash_view(data),
    )

    block = _blocks_by_path(contract)["stash.分线毛利率吨成本"]
    assert contract["mode"] == "declared"
    assert block["role"] == "primary_attachment"
    assert block["placement"] == "model_table"


def test_declared_display_contract_invalid_enum_warns_and_falls_back():
    data = {
        "display": {
            "blocks": [
                {"path": "stash.foo", "role": "not_a_role", "placement": "reference_tab"},
            ]
        },
        "stash": {"foo": {"series": {"bar": {"2024": 1}}}},
    }

    contract = _yaml1_display_contract(data, _revenue_view("业务线"), _yaml1_stash_view(data))

    assert _blocks_by_path(contract)["stash.foo"]["role"] == "reference"
    assert any(warning["code"] == "invalid_display_enum" for warning in contract["warnings"])
