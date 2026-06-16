"""Tests for the restricted YAML1 formula/DAG evaluator."""

from __future__ import annotations

import pytest

from src.yaml1_formula import FormulaError, evaluate_formula_graph


def test_formula_evaluates_lagged_self_recursion():
    yaml1 = {
        "formulas": {
            "nodes": {
                "openings": {"kind": "input", "unit": "store", "values": [10, 20]},
                "closures": {"kind": "input", "unit": "store", "values": [1, 2]},
                "stores": {
                    "kind": "formula",
                    "unit": "store",
                    "expr": "lag(stores, 1) + openings - closures",
                    "inputs": ["stores", "openings", "closures"],
                    "seeds": {2024: 100},
                    "history": {2024: 100},
                },
            }
        }
    }

    result = evaluate_formula_graph(yaml1, [2025, 2026])

    assert result.values("stores") == pytest.approx([109, 127])
    assert result.dependencies["stores"][2025] == ["stores[2024]", "openings[2025]", "closures[2025]"]


def test_formula_supports_safe_functions_and_if_else_short_circuit():
    yaml1 = {
        "formulas": {
            "nodes": {
                "stores": {"kind": "input", "unit": "store", "values": [100, 200]},
                "large_value": {
                    "kind": "formula",
                    "unit": "million_cny",
                    "expr": "if_else(stores > 150, clip(stores * 2, 0, 350), min(stores * 3, 250))",
                    "inputs": ["stores"],
                },
            }
        }
    }

    result = evaluate_formula_graph(yaml1, [2025, 2026])

    assert result.values("large_value") == pytest.approx([250, 350])


def test_formula_rejects_unsafe_expression_syntax():
    yaml1 = {
        "formulas": {
            "nodes": {
                "x": {"kind": "input", "unit": "x", "values": [1]},
                "bad": {
                    "kind": "formula",
                    "unit": "x",
                    "expr": "__import__('os').system('echo bad')",
                    "inputs": ["x"],
                },
            }
        }
    }

    with pytest.raises(FormulaError, match="Unsupported function"):
        evaluate_formula_graph(yaml1, [2025])


def test_formula_inputs_must_match_expression_references():
    missing = {
        "formulas": {
            "nodes": {
                "x": {"kind": "input", "unit": "x", "values": [1]},
                "y": {"kind": "formula", "unit": "x", "expr": "x + z", "inputs": ["x"]},
            }
        }
    }
    unused = {
        "formulas": {
            "nodes": {
                "x": {"kind": "input", "unit": "x", "values": [1]},
                "z": {"kind": "input", "unit": "x", "values": [2]},
                "y": {"kind": "formula", "unit": "x", "expr": "x + 1", "inputs": ["x", "z"]},
            }
        }
    }

    with pytest.raises(FormulaError, match="unknown node|undeclared"):
        evaluate_formula_graph(missing, [2025])
    with pytest.raises(FormulaError, match="unused inputs"):
        evaluate_formula_graph(unused, [2025])


def test_formula_detects_current_year_cycle():
    yaml1 = {
        "formulas": {
            "nodes": {
                "a": {"kind": "formula", "unit": "x", "expr": "b + 1", "inputs": ["b"]},
                "b": {"kind": "formula", "unit": "x", "expr": "a + 1", "inputs": ["a"]},
            }
        }
    }

    with pytest.raises(FormulaError, match="cycle"):
        evaluate_formula_graph(yaml1, [2025])


def test_formula_lag_requires_seed_or_history():
    yaml1 = {
        "formulas": {
            "nodes": {
                "stores": {
                    "kind": "formula",
                    "unit": "store",
                    "expr": "lag(stores, 1) + 1",
                    "inputs": ["stores"],
                },
            }
        }
    }

    with pytest.raises(FormulaError, match="missing seed/history"):
        evaluate_formula_graph(yaml1, [2025])


def test_formula_history_backtest_passes_and_fails():
    passing = {
        "formulas": {
            "nodes": {
                "a": {"kind": "input", "unit": "x", "values": [1], "history": {2024: 2}},
                "b": {
                    "kind": "formula",
                    "unit": "x",
                    "expr": "a * 2",
                    "inputs": ["a"],
                    "history": {2024: 4},
                },
            }
        }
    }
    failing = {
        "formulas": {
            "nodes": {
                "a": {"kind": "input", "unit": "x", "values": [1], "history": {2024: 2}},
                "b": {
                    "kind": "formula",
                    "unit": "x",
                    "expr": "a * 2",
                    "inputs": ["a"],
                    "history": {2024: 5},
                },
            }
        }
    }

    result = evaluate_formula_graph(passing, [2025])
    assert result.backtests["b"]["status"] == "ok"
    with pytest.raises(FormulaError, match="backtest failed"):
        evaluate_formula_graph(failing, [2025])
