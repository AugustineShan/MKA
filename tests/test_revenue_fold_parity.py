"""Guards the single revenue engine (src.revenue_fold) and its two callers.

Before this engine was unified, the workbench preview reimplemented the
per-family revenue math separately from the forecast fold and silently diverged
on long-tail company shapes. These tests pin:

1. project_leaf produces correct numbers per family, and raises (never silently
   wrong) on unknown families / mis-lengthed series / formula-without-graph.
2. the forecast fold (yaml1_cleaner.fold_revenue) and the workbench preview
   (workbench._yaml1_revenue_view_from_data) agree to the cent on total revenue
   and yoy — including the clean_annual base-year anchor.
"""

from __future__ import annotations

import pytest

from src.revenue_fold import Yaml1CleanError, project_leaf
from src.workbench import _yaml1_revenue_view_from_data
from src.yaml1_cleaner import fold_revenue


HORIZON = [2025, 2026, 2027]
YEARS = ["2025", "2026", "2027"]


def _yaml1() -> dict:
    """Minimal two-leaf decomposition spanning two families."""
    return {
        "meta": {"horizon": HORIZON},
        "income.revenue": {
            "kind": "decomposition",
            "segments": {
                "线A": {
                    "revenue_family": "growth",
                    "base": {"base_year": 2024, "revenue": 1000.0, "unit_factor_to_million_cny": 1.0},
                    "knobs": {"revenue_yoy": [0.10, 0.10, 0.10]},
                },
                "线B": {
                    "revenue_family": "vol_price",
                    "base": {"base_year": 2024, "volume": 10.0, "price": 50.0, "unit_factor_to_million_cny": 1.0},
                    "knobs": {"volume_yoy": [0.05, 0.05, 0.05], "price_yoy": [0.02, 0.02, 0.02]},
                },
            },
        },
    }


# ── per-family math ─────────────────────────────────────────────────────────
def test_growth_leaf_numbers() -> None:
    seg = {
        "revenue_family": "growth",
        "base": {"revenue": 1000.0, "unit_factor_to_million_cny": 1.0},
        "knobs": {"revenue_yoy": [0.10, 0.20, 0.0]},
    }
    proj = project_leaf("g", seg, "p", "", HORIZON, [])
    assert proj.base_revenue == pytest.approx(1000.0)
    assert proj.revenue_by_year[2025] == pytest.approx(1100.0)
    assert proj.revenue_by_year[2026] == pytest.approx(1320.0)
    assert proj.revenue_by_year[2027] == pytest.approx(1320.0)


def test_vol_price_leaf_tracks_volume() -> None:
    seg = {
        "revenue_family": "vol_price",
        "base": {"volume": 10.0, "price": 50.0, "unit_factor_to_million_cny": 1.0},
        "knobs": {"volume_yoy": [0.05, 0.0, 0.0], "price_yoy": [0.02, 0.0, 0.0]},
    }
    proj = project_leaf("vp", seg, "p", "", HORIZON, [])
    assert proj.base_revenue == pytest.approx(500.0)
    assert proj.volume_by_year[2025] == pytest.approx(10.5)
    assert proj.revenue_by_year[2025] == pytest.approx(10.5 * 51.0)


def test_abs_leaf_numbers() -> None:
    seg = {
        "revenue_family": "abs",
        "base": {"revenue": 100.0, "unit_factor_to_million_cny": 1.0},
        "knobs": {"revenue_abs": [200.0, 300.0, 400.0]},
    }
    proj = project_leaf("a", seg, "p", "", HORIZON, [])
    assert [proj.revenue_by_year[y] for y in HORIZON] == pytest.approx([200.0, 300.0, 400.0])


def test_factor_product_leaf_numbers() -> None:
    seg = {
        "revenue_family": "factor_product",
        "base": {"unit_factor_to_million_cny": 1.0},
        "factors": [
            {"base": 10.0, "projection": {"kind": "yoy", "values": [0.10, 0.0, 0.0]}},
            {"base": 50.0, "projection": {"kind": "constant"}},
        ],
    }
    proj = project_leaf("f", seg, "p", "", HORIZON, [])
    assert proj.base_revenue == pytest.approx(500.0)
    assert proj.revenue_by_year[2025] == pytest.approx(11.0 * 50.0)


def test_unknown_family_raises_not_silent() -> None:
    seg = {"revenue_family": "made_up", "base": {"revenue": 1.0, "unit_factor_to_million_cny": 1.0}}
    with pytest.raises(Yaml1CleanError):
        project_leaf("x", seg, "p", "", HORIZON, [])


def test_short_series_raises_not_silent() -> None:
    seg = {
        "revenue_family": "growth",
        "base": {"revenue": 1000.0, "unit_factor_to_million_cny": 1.0},
        "knobs": {"revenue_yoy": [0.10]},  # shorter than horizon
    }
    with pytest.raises(Yaml1CleanError):
        project_leaf("g", seg, "p", "", HORIZON, [])


def test_formula_leaf_without_graph_raises_not_silent() -> None:
    seg = {
        "kind": "formula",
        "formula_ref": "node1",
        "base": {"revenue": 100.0, "unit_factor_to_million_cny": 1.0},
    }
    with pytest.raises(Yaml1CleanError):
        project_leaf("fm", seg, "p", "", HORIZON, [])  # formula_result is None


# ── preview == forecast parity ───────────────────────────────────────────────
def _assert_engines_agree(clean_annual: dict) -> None:
    yaml1 = _yaml1()
    fold = fold_revenue(yaml1, clean_annual, None)
    view = _yaml1_revenue_view_from_data(yaml1, clean_annual)
    assert view is not None
    for i, year in enumerate(YEARS):
        assert view["revenues"][year] == pytest.approx(fold.revenue_by_year[int(year)])
        assert view["yoy"][year] == pytest.approx(fold.revenue_yoy[i])


def test_parity_when_leaf_bases_sum_to_total() -> None:
    # leaf sum == 1500; anchor matches leaf sum.
    _assert_engines_agree({2024: {"revenue": 1500.0}})


def test_parity_when_leaf_bases_disagree_with_total() -> None:
    # leaf sum == 1500 but actual base total == 1600. Both engines must anchor
    # the first-year yoy to 1600 — this is the previously-latent drift, now pinned.
    _assert_engines_agree({2024: {"revenue": 1600.0}})


def test_preview_falls_back_to_leaf_sum_without_clean_annual() -> None:
    # No clean_annual: preview anchors to the leaf-base sum (documented fallback).
    view = _yaml1_revenue_view_from_data(_yaml1(), None)
    assert view is not None
    assert view["base_revenue"] == pytest.approx(1500.0)
