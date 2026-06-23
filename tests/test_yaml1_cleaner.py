"""Tests for deterministic yaml1 cleaning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import yaml1_cleaner
from src.calc import build_forecast_statements
from src.company_paths import db_path as company_db_path, defaults_path as company_defaults_path
from src.yaml1_formula import evaluate_formula_graph


def synthetic_clean_annual(revenue: float = 100.0) -> dict[int, dict[str, float]]:
    return {2024: {"revenue": revenue}}


def synthetic_yaml1(segments: dict[str, object], extra: dict[str, object] | None = None) -> dict[str, object]:
    data: dict[str, object] = {
        "meta": {"horizon": [2025, 2026]},
        "income.revenue": {
            "kind": "decomposition",
            "segments": segments,
        },
        "terminal": {
            "explicit_end": 2026,
            "fade": {"kind": "linear", "to_year": 2026, "fade_paths": [], "hold_paths": []},
            "perpetual_growth": 0.02,
        },
    }
    if extra:
        data.update(extra)
    return data


def company_dir() -> Path:
    # Frozen snapshot (see tests/conftest.py) — decoupled from the live workspace.
    return Path(__file__).resolve().parent / "fixtures" / "company_002946"


def paths() -> tuple[Path, Path, Path]:
    base = company_dir()
    return (
        yaml1_cleaner.default_yaml1_path(base),
        company_defaults_path(base),
        company_db_path(base),
    )


def write_yaml1_fixture(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "yaml1_contract.yaml"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_clean_yaml1_data_matches_file_path():
    yaml1_path, defaults_path, clean_path = paths()
    yaml1_data = yaml1_cleaner.load_yaml(yaml1_path)

    from_path = yaml1_cleaner.clean_yaml1(yaml1_path, defaults_path, clean_path)
    from_data = yaml1_cleaner.clean_yaml1_data(
        yaml1_data,
        defaults_path,
        clean_path,
        yaml1_label=str(yaml1_path),
    )

    assert from_data.forecast_params == from_path.forecast_params
    assert from_data.report["backtest"]["status"] == from_path.report["backtest"]["status"]


def test_fold_revenue_uses_structured_unit_factor_and_clean_anchor():
    yaml1_path, _, clean_path = paths()
    yaml1 = yaml1_cleaner.load_yaml(yaml1_path)
    clean_annual = yaml1_cleaner.load_clean_annual(clean_path)

    fold = yaml1_cleaner.fold_revenue(yaml1, clean_annual)

    assert fold.base_year == 2024
    assert fold.base_revenue == pytest.approx(10665.42345785)
    assert fold.segment_base_revenue["fresh_milk"] == pytest.approx(2739.3222)
    assert fold.segment_base_revenue["yogurt"] == pytest.approx(2767.5343)
    assert fold.segment_base_revenue["ambient"] == pytest.approx(4329.5231)
    assert fold.segment_base_revenue["other_business"] == pytest.approx(829.2)
    assert fold.revenue_by_year[2025] == pytest.approx(10856.464606625)
    assert fold.revenue_yoy[0] == pytest.approx(10856.464606625 / 10665.42345785 - 1)
    # If this accidentally anchors to the four-line base sum, it will be slightly different.
    segment_sum = sum(fold.segment_base_revenue.values())
    assert fold.revenue_yoy[0] != pytest.approx(10856.464606625 / segment_sum - 1)
    assert fold.unit_factors == {
        "fresh_milk": 100.0,
        "yogurt": 100.0,
        "ambient": 100.0,
        "other_business": 1.0,
    }


def test_fold_revenue_supports_factor_product_two_factor_alias_shape():
    yaml1 = synthetic_yaml1(
        {
            "retail": {
                "revenue_family": "factor_product",
                "base": {"base_year": 2024, "unit_factor_to_million_cny": 1},
                "factors": [
                    {"key": "stores", "label": "门店数", "base": 10, "projection": {"kind": "yoy", "values": [0.1, 0.0]}},
                    {"key": "sales_per_store", "label": "单店收入", "base": 10, "projection": {"kind": "yoy", "values": [0.0, 0.1]}},
                ],
            }
        }
    )

    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())

    assert fold.segment_base_revenue["retail"] == pytest.approx(100.0)
    assert fold.revenue_by_year[2025] == pytest.approx(110.0)
    assert fold.revenue_by_year[2026] == pytest.approx(121.0)
    assert fold.revenue_yoy == pytest.approx([0.1, 0.1])


def test_fold_revenue_supports_factor_product_three_factors_with_mixed_projection():
    yaml1 = synthetic_yaml1(
        {
            "power": {
                "revenue_family": "factor_product",
                "base": {"base_year": 2024, "unit_factor_to_million_cny": 1},
                "factors": [
                    {"key": "capacity", "label": "装机量", "base": 10, "projection": {"kind": "constant"}},
                    {"key": "hours", "label": "利用小时", "base": 5, "projection": {"kind": "abs", "values": [6, 7]}},
                    {"key": "tariff", "label": "电价", "base": 2, "projection": {"kind": "constant"}},
                ],
            }
        }
    )

    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())

    assert fold.revenue_by_year[2025] == pytest.approx(120.0)
    assert fold.revenue_by_year[2026] == pytest.approx(140.0)
    assert fold.revenue_yoy == pytest.approx([0.2, 140.0 / 120.0 - 1.0])


def test_fold_revenue_supports_abs_family():
    yaml1 = synthetic_yaml1(
        {
            "direct_amount": {
                "revenue_family": "abs",
                "base": {"base_year": 2024, "revenue": 100, "unit_factor_to_million_cny": 1},
                "knobs": {"revenue_abs": [120, 150]},
            }
        }
    )

    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())

    assert fold.revenue_by_year == pytest.approx({2025: 120.0, 2026: 150.0})
    assert fold.revenue_yoy == pytest.approx([0.2, 0.25])


def test_contract_fixture_cleans_to_calc_with_current_templates(tmp_path):
    _, defaults_path, clean_path = paths()
    base_revenue = 10665.42345785
    yaml1 = {
        "meta": {"horizon": [2025, 2026, 2027]},
        "income.revenue": {
            "kind": "decomposition",
            "rollup": "sum",
            "src": "#contract",
            "segments": {
                "retail": {
                    "kind": "decomposition",
                    "rollup": "sum",
                    "segments": {
                        "stores": {
                            "revenue_family": "factor_product",
                            "base": {"base_year": 2024, "unit_factor_to_million_cny": 1},
                            "factors": [
                                {
                                    "key": "stores",
                                    "label": "门店数",
                                    "base": 100,
                                    "projection": {"kind": "yoy", "values": [0.10, 0.0, 0.0]},
                                },
                                {
                                    "key": "sales_per_store",
                                    "label": "单店收入",
                                    "base": 50,
                                    "projection": {"kind": "abs", "values": [52, 54, 56]},
                                },
                            ],
                        },
                        "online": {
                            "revenue_family": "growth",
                            "base": {
                                "base_year": 2024,
                                "revenue": 2000,
                                "unit_factor_to_million_cny": 1,
                            },
                            "knobs": {"revenue_yoy": [0.05, 0.04, 0.03]},
                        },
                    },
                },
                "contracted": {
                    "revenue_family": "abs",
                    "base": {
                        "base_year": 2024,
                        "revenue": base_revenue - 7000,
                        "unit_factor_to_million_cny": 1,
                    },
                    "knobs": {"revenue_abs": [3800, 3900, 4000]},
                },
            },
        },
        "income.gpm": {"kind": "knob", "values": [0.30, 0.31, 0.32], "src": "#top_gpm"},
        "income.financial_expense.other_fin_exp_abs": {
            "kind": "knob",
            "values": [1.0, 1.0, 1.0],
            "src": "#other_fin_exp_abs",
        },
        "terminal": {
            "explicit_end": 2027,
            "fade": {
                "kind": "linear",
                "to_year": 2029,
                "fade_paths": ["model.revenue_yoy"],
                "hold_paths": ["income.gpm"],
            },
            "perpetual_growth": 0.025,
        },
    }

    result = yaml1_cleaner.clean_yaml1(write_yaml1_fixture(tmp_path, yaml1), defaults_path, clean_path)
    forecast_params = result.forecast_params
    build = build_forecast_statements(forecast_params)

    assert result.report["backtest"]["status"] == "passed"
    assert result.report["fold"]["segment_base_revenue"]["retail.stores"] == pytest.approx(5000)
    assert result.report["fold"]["segment_base_revenue"]["retail.online"] == pytest.approx(2000)
    assert result.report["fold"]["segment_base_revenue"]["contracted"] == pytest.approx(base_revenue - 7000)
    assert forecast_params["model"]["revenue_yoy"]["source"] == "#contract"
    assert forecast_params["income"]["gpm"]["value"][:3] == pytest.approx([0.30, 0.31, 0.32])
    assert forecast_params["income"]["financial_expense"]["other_fin_exp_abs"]["value"][:3] == pytest.approx(
        [1.0, 1.0, 1.0]
    )
    assert build.forecast_years == forecast_params["model"]["forecast_years"]["value"]
    assert not build.income_statement.empty


def test_contract_fixture_leaf_margin_fold_also_reaches_calc(tmp_path):
    _, defaults_path, clean_path = paths()
    base_revenue = 10665.42345785
    yaml1 = {
        "meta": {"horizon": [2025, 2026]},
        "income.revenue": {
            "kind": "decomposition",
            "rollup": "sum",
            "src": "#margin_contract",
            "segments": {
                "fresh": {
                    "revenue_family": "growth",
                    "base": {"base_year": 2024, "revenue": 6000, "unit_factor_to_million_cny": 1},
                    "knobs": {"revenue_yoy": [0.05, 0.04], "margin": [0.35, 0.36]},
                },
                "ambient": {
                    "revenue_family": "growth",
                    "base": {
                        "base_year": 2024,
                        "revenue": base_revenue - 6000,
                        "unit_factor_to_million_cny": 1,
                    },
                    "knobs": {"revenue_yoy": [0.00, -0.02], "margin": [0.20, 0.21]},
                },
            },
        },
        "terminal": {
            "explicit_end": 2026,
            "fade": {"kind": "linear", "to_year": 2028, "fade_paths": ["model.revenue_yoy"], "hold_paths": []},
            "perpetual_growth": 0.025,
        },
    }

    result = yaml1_cleaner.clean_yaml1(write_yaml1_fixture(tmp_path, yaml1), defaults_path, clean_path)
    forecast_params = result.forecast_params
    build = build_forecast_statements(forecast_params)

    fresh_2025 = 6000 * 1.05
    ambient_2025 = base_revenue - 6000
    expected_gpm_2025 = (fresh_2025 * 0.35 + ambient_2025 * 0.20) / (fresh_2025 + ambient_2025)
    assert result.report["backtest"]["status"] == "passed"
    assert forecast_params["income"]["gpm"]["source"] == "yaml1.income.revenue.margin_fold"
    assert forecast_params["income"]["gpm"]["value"][0] == pytest.approx(expected_gpm_2025)
    assert not build.income_statement.empty


def test_fold_revenue_recurses_nested_decomposition_sum():
    yaml1 = synthetic_yaml1(
        {
            "retail": {
                "kind": "decomposition",
                "segments": {
                    "stores": {
                        "revenue_family": "growth",
                        "base": {"base_year": 2024, "revenue": 60, "unit_factor_to_million_cny": 1},
                        "knobs": {"revenue_yoy": [0.1, 0.0]},
                    },
                    "online": {
                        "revenue_family": "growth",
                        "base": {"base_year": 2024, "revenue": 40, "unit_factor_to_million_cny": 1},
                        "knobs": {"revenue_yoy": [0.0, 0.1]},
                    },
                },
            }
        }
    )

    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())

    assert fold.segment_base_revenue["retail.stores"] == pytest.approx(60.0)
    assert fold.segment_base_revenue["retail.online"] == pytest.approx(40.0)
    assert fold.revenue_by_year[2025] == pytest.approx(106.0)
    assert fold.revenue_by_year[2026] == pytest.approx(110.0)


def test_fold_revenue_derives_gpm_when_all_leaves_have_margin():
    yaml1 = synthetic_yaml1(
        {
            "a": {
                "revenue_family": "growth",
                "base": {"base_year": 2024, "revenue": 60, "unit_factor_to_million_cny": 1},
                "knobs": {"revenue_yoy": [0.0, 0.0], "margin": [0.3, 0.4]},
            },
            "b": {
                "revenue_family": "growth",
                "base": {"base_year": 2024, "revenue": 40, "unit_factor_to_million_cny": 1},
                "knobs": {"revenue_yoy": [0.0, 0.0], "margin": [0.45, 0.5]},
            },
        }
    )

    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())
    overlay = yaml1_cleaner._collect_explicit_overlay(yaml1, fold, {"warnings": []})

    assert fold.gpm_values == pytest.approx([0.36, 0.44])
    assert overlay["income.gpm"]["values"] == pytest.approx([0.36, 0.44])


def test_fold_revenue_rejects_partial_leaf_margin():
    yaml1 = synthetic_yaml1(
        {
            "a": {
                "revenue_family": "growth",
                "base": {"base_year": 2024, "revenue": 60, "unit_factor_to_million_cny": 1},
                "knobs": {"revenue_yoy": [0.0, 0.0], "margin": [0.3, 0.4]},
            },
            "b": {
                "revenue_family": "growth",
                "base": {"base_year": 2024, "revenue": 40, "unit_factor_to_million_cny": 1},
                "knobs": {"revenue_yoy": [0.0, 0.0]},
            },
        }
    )

    with pytest.raises(yaml1_cleaner.Yaml1CleanError, match="partial leaf margin"):
        yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())


def test_collect_overlay_rejects_leaf_margin_and_top_level_gpm():
    yaml1 = synthetic_yaml1(
        {
            "a": {
                "revenue_family": "growth",
                "base": {"base_year": 2024, "revenue": 100, "unit_factor_to_million_cny": 1},
                "knobs": {"revenue_yoy": [0.0, 0.0], "margin": [0.3, 0.4]},
            }
        },
        extra={"income.gpm": {"kind": "knob", "values": [0.31, 0.41]}},
    )

    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual())
    with pytest.raises(yaml1_cleaner.Yaml1CleanError, match="leaf margin.*income.gpm"):
        yaml1_cleaner._collect_explicit_overlay(yaml1, fold, {"warnings": []})


def test_fold_revenue_supports_formula_leaf():
    yaml1 = synthetic_yaml1(
        {
            "formula_line": {
                "kind": "formula",
                "formula_ref": "retail_revenue",
                "base": {"base_year": 2024, "revenue": 100, "unit_factor_to_million_cny": 1},
            }
        },
        extra={
            "formulas": {
                "nodes": {
                    "stores": {"kind": "input", "unit": "store", "values": [11, 11]},
                    "sales_per_store": {"kind": "input", "unit": "million_cny_per_store", "values": [10, 11]},
                    "retail_revenue": {
                        "kind": "formula",
                        "unit": "million_cny",
                        "expr": "stores * sales_per_store",
                        "inputs": ["stores", "sales_per_store"],
                    },
                }
            }
        },
    )

    formulas = evaluate_formula_graph(yaml1, [2025, 2026])
    fold = yaml1_cleaner.fold_revenue(yaml1, synthetic_clean_annual(), formulas)

    assert fold.segment_base_revenue["formula_line"] == pytest.approx(100)
    assert fold.revenue_by_year == pytest.approx({2025: 110, 2026: 121})
    assert fold.revenue_yoy == pytest.approx([0.10, 0.10])
    assert formulas.report()["targets"]["income.revenue.segments.formula_line"] == "retail_revenue"


def test_clean_yaml1_formula_leaf_and_formula_overlay_reach_calc(tmp_path):
    base = company_dir()
    defaults_path = company_defaults_path(base)
    clean_path = company_db_path(base)
    base_revenue = 10665.42345785
    yaml1 = {
        "meta": {"horizon": [2025, 2026, 2027]},
        "formulas": {
            "nodes": {
                "openings": {"kind": "input", "unit": "store", "values": [20, 25, 25]},
                "closures": {"kind": "input", "unit": "store", "values": [5, 5, 5]},
                "stores": {
                    "kind": "formula",
                    "unit": "store",
                    "expr": "lag(stores, 1) + openings - closures",
                    "inputs": ["stores", "openings", "closures"],
                    "seeds": {2024: 100},
                    "history": {2024: 100},
                },
                "sales_per_store": {
                    "kind": "input",
                    "unit": "million_cny_per_store",
                    "values": [base_revenue / 115, base_revenue * 1.02 / 135, base_revenue * 1.03 / 155],
                },
                "retail_revenue": {
                    "kind": "formula",
                    "unit": "million_cny",
                    "expr": "stores * sales_per_store",
                    "inputs": ["stores", "sales_per_store"],
                },
                "gpm_formula": {"kind": "input", "unit": "ratio", "values": [0.30, 0.31, 0.32]},
            }
        },
        "income.revenue": {
            "kind": "decomposition",
            "rollup": "sum",
            "src": "#formula_contract",
            "segments": {
                "retail": {
                    "kind": "formula",
                    "formula_ref": "retail_revenue",
                    "base": {"base_year": 2024, "revenue": base_revenue, "unit_factor_to_million_cny": 1},
                },
            },
        },
        "income.gpm": {"kind": "formula", "formula_ref": "gpm_formula", "src": "#formula_gpm"},
        "terminal": {
            "explicit_end": 2027,
            "fade": {"kind": "linear", "to_year": 2027, "fade_paths": [], "hold_paths": []},
            "perpetual_growth": 0.025,
        },
    }

    result = yaml1_cleaner.clean_yaml1(write_yaml1_fixture(tmp_path, yaml1), defaults_path, clean_path)
    forecast_params = result.forecast_params
    build = build_forecast_statements(forecast_params)

    assert result.report["formula"]["status"] == "ok"
    assert result.report["formula"]["targets"]["income.revenue.segments.retail"] == "retail_revenue"
    assert result.report["formula"]["targets"]["income.gpm"] == "gpm_formula"
    assert forecast_params["model"]["revenue_yoy"]["source"] == "#formula_contract"
    assert forecast_params["model"]["revenue_yoy"]["value"][:3] == pytest.approx([0.0, 0.02, 1.03 / 1.02 - 1.0])
    assert forecast_params["income"]["gpm"]["value"][:3] == pytest.approx([0.30, 0.31, 0.32])
    assert not build.income_statement.empty


def test_clean_yaml1_expands_fade_hold_default_hold_and_alias_warning():
    yaml1_path, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(
        yaml1_path,
        defaults_path,
        clean_path,
    )

    y = result.forecast_params
    warnings = [item["message"] for item in result.report["warnings"]]

    assert y["model"]["forecast_years"]["value"] == 10
    assert y["meta"]["horizon"] == list(range(2025, 2035))
    revenue_yoy = y["model"]["revenue_yoy"]["value"]
    assert len(revenue_yoy) == 10
    assert revenue_yoy == pytest.approx(
        [
            0.017912195378833262,
            0.01429330433700926,
            0.018566702336527907,
            0.0217769755064936,
            0.024118789962974452,
            0.02529503197037956,
            0.02647127397778467,
            0.02764751598518978,
            0.02882375799259489,
            0.03,
        ]
    )
    assert y["income"]["gpm"]["value"][-5:] == pytest.approx([0.316] * 5)
    assert y["income"]["cost_rates"]["admin_exp"]["value"][-5:] == pytest.approx([0.036] * 5)

    assert any("总增速低于永续" in message for message in warnings)
    assert any("末年增速<永续" in message for message in warnings)


def test_resolve_yearly_shape_keeps_base_and_constants_scalar():
    yaml1_path, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(
        yaml1_path,
        defaults_path,
        clean_path,
    )
    y = result.forecast_params

    assert y["base_period"] == "2024"
    assert y["income"]["revenue"]["value"] == pytest.approx(10665.42345785)
    assert isinstance(y["balance_sheet"]["base"]["money_cap"]["value"], float)
    assert isinstance(y["cashflow"]["base_nwc"]["value"], float)
    assert isinstance(y["market"]["total_shares"]["value"], float)
    assert y["model"]["wacc"]["value"] == pytest.approx(0.08)
    assert y["income"]["financial_expense"]["interest_mode"]["value"] == "circular_average_balance"

    horizon_len = y["model"]["forecast_years"]["value"]
    yearly_paths = result.report["yearly_paths"]
    assert "income.financial_expense.interest_expense_rate" in yearly_paths
    assert len(y["income"]["financial_expense"]["interest_expense_rate"]["value"]) == horizon_len
    assert len(y["balance_sheet"]["revenue_pct"]["accounts_receiv"]["value"]) == horizon_len
    assert len(y["balance_sheet"]["amort_intang_assets"]["value"]) == horizon_len


def test_backtest_hard_gate_passes_for_new_hope_dairy():
    yaml1_path, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(
        yaml1_path,
        defaults_path,
        clean_path,
    )

    backtest = result.report["backtest"]
    assert backtest["status"] == "passed"
    assert backtest["anchor"]["residual"] < 1.0
    assert not result.report["errors"]


def test_defaults_only_identity_clean_matches_yaml2_broadcast():
    _, defaults_path, clean_path = paths()

    result = yaml1_cleaner.clean_yaml1(None, defaults_path, clean_path)

    assert result.report.get("defaults_only") is True
    assert result.report["backtest"]["status"] == "skipped"
    forecast_params = result.forecast_params

    # Horizon comes from YAML2 base_period + forecast_years, no fade.
    base_period = forecast_params["base_period"]
    base_year = int(str(base_period)[:4])
    years = int(forecast_params["model"]["forecast_years"]["value"])
    assert forecast_params["meta"]["horizon"] == list(range(base_year + 1, base_year + 1 + years))

    # model.revenue_yoy is broadcast from scalar YAML2 default.
    revenue_yoy = forecast_params["model"]["revenue_yoy"]["value"]
    assert isinstance(revenue_yoy, list)
    assert len(revenue_yoy) == years
    assert revenue_yoy == pytest.approx([revenue_yoy[0]] * years)

    # Numerically identical to the legacy broadcast helper.
    yaml2 = yaml1_cleaner.read_yaml2(defaults_path)
    broadcast = yaml1_cleaner.broadcast_yaml2_defaults(yaml2)
    assert (
        forecast_params["model"]["revenue_yoy"]["value"]
        == broadcast["model"]["revenue_yoy"]["value"]
    )
