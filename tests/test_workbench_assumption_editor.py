from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.workbench import (
    _apply_assumption_patches,
    _assumptions_terminal,
    _editable_assumptions,
    _format_frontend_edit_prompt,
    _yaml1_assumptions_view,
)


def test_editable_assumptions_include_top_level_values():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.gpm": {"values": [0.29, 0.30], "src": "test"},
    }

    rows = _editable_assumptions(data)

    row = next(item for item in rows if item["path"] == "income.gpm")
    assert row["group"] == "standard_knob"
    assert row["cells"][0]["pointer"] == "/income.gpm/values/0"
    assert row["cells"][0]["year"] == "2025"


def test_other_fin_exp_abs_groups_with_expense_rows():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.financial_expense.other_fin_exp_abs": {
            "values": [3.0, 2.0],
            "src": "#其他财务费用(外生·非利息)",
        },
        "income.cost_rates.sell_exp": {"values": [0.18, 0.17], "src": "#销售费用"},
        "income.cost_rates.admin_exp": {"values": [0.04, 0.04], "src": "#管理费用"},
        "income.cost_rates.rd_exp": {"values": [0.01, 0.01], "src": "#研发费用"},
        "income.cost_rates.biz_tax_surchg": {"values": [0.006, 0.006], "src": "#税金及附加"},
    }

    view = _yaml1_assumptions_view(data, ["2025", "2026"])
    section = next(item for item in view["sections"] if item["key"] == "cost_rates")
    paths = [row["path"] for row in section["knobs"]]

    assert paths == [
        "income.cost_rates.sell_exp",
        "income.cost_rates.admin_exp",
        "income.cost_rates.rd_exp",
        "income.cost_rates.biz_tax_surchg",
        "income.financial_expense.other_fin_exp_abs",
    ]


def test_other_fin_exp_abs_is_editable_abs_amount():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.financial_expense.other_fin_exp_abs": {
            "values": [3.0, 2.0],
            "src": "#其他财务费用(外生·非利息)",
        },
    }

    rows = _editable_assumptions(data)
    row = next(item for item in rows if item["path"] == "income.financial_expense.other_fin_exp_abs")

    assert row["label"] == "非息财务费用"
    assert row["unit"] == "abs_mn"
    assert row["format"] == "integer"
    assert row["cells"][0]["pointer"] == "/income.financial_expense.other_fin_exp_abs/values/0"


def test_editable_assumptions_include_revenue_driver_values():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.revenue": {
            "kind": "decomposition",
            "segments": {
                "低温鲜奶": {
                    "revenue_family": "factor_product",
                    "factors": [
                        {"key": "volume", "projection": {"kind": "yoy", "values": [0.07, 0.06]}},
                        {"key": "price", "projection": {"kind": "yoy", "values": [0.003, 0.003]}},
                    ],
                }
            },
        },
    }

    rows = _editable_assumptions(data)
    labels = {row["label"] for row in rows}

    assert "低温鲜奶 · volume" in labels
    assert "低温鲜奶 · price" in labels
    assert any(row["path"] == "income.revenue.低温鲜奶.volume" for row in rows)


def test_editable_assumptions_include_terminal_growth():
    data = {"terminal": {"perpetual_growth": 0.025}}

    rows = _editable_assumptions(data)

    assert any(row["cells"][0]["pointer"] == "/terminal/perpetual_growth" for row in rows)


def test_assumptions_terminal_displays_fade_target_growth():
    terminal = {
        "explicit_end": 2030,
        "fade": {
            "kind": "linear",
            "to_year": 2037,
            "target_growth": 0.055,
            "target_basis": "auto_stable_brand",
            "fade_paths": ["model.revenue_yoy"],
            "hold_paths": ["income.gpm"],
        },
        "perpetual_growth": 0.02,
    }

    view = _assumptions_terminal(terminal)

    assert view["target_growth"] == 0.055
    assert view["target_basis"] == "auto_stable_brand"
    assert view["perpetual_growth"] == 0.02


def test_apply_assumption_patches_updates_only_requested_pointer():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.gpm": {"values": [0.29, 0.30]},
    }

    patched = _apply_assumption_patches(
        data,
        [{"pointer": "/income.gpm/values/1", "old_value": 0.30, "new_value": 0.31}],
    )

    assert patched["income.gpm"]["values"] == [0.29, 0.31]
    assert data["income.gpm"]["values"] == [0.29, 0.30]


def test_apply_assumption_patches_rejects_unknown_pointer():
    data = {
        "meta": {"horizon": [2025]},
        "income.gpm": {"values": [0.29]},
    }

    with pytest.raises(HTTPException, match="Unsupported editable pointer"):
        _apply_assumption_patches(
            data,
            [{"pointer": "/income.gpm/src", "old_value": None, "new_value": 0.31}],
        )


def test_apply_assumption_patches_rejects_old_value_mismatch():
    data = {
        "meta": {"horizon": [2025]},
        "income.gpm": {"values": [0.29]},
    }

    with pytest.raises(HTTPException, match="changed since preview"):
        _apply_assumption_patches(
            data,
            [{"pointer": "/income.gpm/values/0", "old_value": 0.28, "new_value": 0.31}],
        )


def test_format_frontend_edit_prompt_lists_changed_revenue_driver_and_standard_knob():
    data = {
        "meta": {"horizon": [2025, 2026]},
        "income.gpm": {"values": [0.29, 0.30], "src": "#整体毛利率"},
        "income.revenue": {
            "segments": {
                "低温鲜奶": {
                    "factors": [
                        {"key": "volume", "label": "销量", "projection": {"values": [0.07, 0.06]}},
                    ]
                }
            }
        },
    }
    patches = [
        {"pointer": "/income.gpm/values/0", "old_value": 0.29, "new_value": 0.31},
        {
            "pointer": "/income.revenue/segments/低温鲜奶/factors/0/projection/values/0",
            "old_value": 0.07,
            "new_value": 0.08,
        },
    ]

    prompt = _format_frontend_edit_prompt(
        company_name="新乳业_002946",
        core_path="D:/MKA/companies/新乳业_002946/新乳业-20260618-核心假设.md",
        yaml1_path="D:/MKA/companies/新乳业_002946/Agent/yaml1_新乳业_20260616.yaml",
        yaml1_data=data,
        patches=patches,
        preview_summary={"per_share_value": 18.5},
    )

    assert "yaml1" in prompt
    assert prompt.startswith("/frontend-edit 进入前端编辑模式")
    assert "进入前端编辑模式" in prompt
    assert "并更新DCF" in prompt
    assert "核心假设.md" in prompt
    assert "income.gpm" in prompt
    assert "低温鲜奶 · 销量" in prompt
    assert "2025" in prompt
    assert "0.29 -> 0.31" in prompt
    assert "/frontend-edit" in prompt
    assert "forecast" in prompt
    assert "试算结果摘要" not in prompt
    assert "per_share_value" not in prompt
