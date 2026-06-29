from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.workbench import _yaml1_revenue_view


def _write_yaml1(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "yaml1_test.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_revenue_view_preserves_history_series_and_prefers_direct_margin(tmp_path: Path) -> None:
    path = _write_yaml1(
        tmp_path,
        """
        meta:
          horizon: [2026, 2027]
        income.revenue:
          kind: decomposition
          segments:
            charging:
              revenue_family: growth
              src: "#Charging"
              base: {base_year: 2025, revenue: 4355.9}
              knobs:
                revenue_yoy: [0.27, 0.19]
                margin: [0.370, 0.375]
              history:
                series:
                  revenue: {2024: 2957.6, 2025: 4355.9}
                  margin: {2024: 0.3610, 2025: 0.3623}
        """,
    )

    view = _yaml1_revenue_view(path)

    assert view is not None
    segment = view["segments"][0]
    assert segment["history_series"]["margin"] == {"2024": 0.3610, "2025": 0.3623}
    assert segment["history_margins"] == {"2024": 0.3610, "2025": 0.3623}
    assert segment["history_metrics"]["gross_margin"]["values"] == {"2024": 0.3610, "2025": 0.3623}
    assert segment["history_metrics"]["gross_margin"]["source"] == "history.series.margin"


def test_revenue_view_derives_margin_only_when_direct_margin_missing(tmp_path: Path) -> None:
    path = _write_yaml1(
        tmp_path,
        """
        meta:
          horizon: [2026]
        income.revenue:
          kind: decomposition
          segments:
            legacy:
              revenue_family: growth
              base: {base_year: 2025, revenue: 100.0}
              knobs:
                revenue_yoy: [0.10]
              history:
                series:
                  revenue: {2024: 100.0, 2025: 120.0}
                  cost: {2024: 60.0, 2025: 72.0}
        """,
    )

    view = _yaml1_revenue_view(path)

    assert view is not None
    segment = view["segments"][0]
    assert segment["history_margins"] == {"2024": pytest.approx(0.4), "2025": pytest.approx(0.4)}
    assert segment["history_metrics"]["gross_margin"]["source"] == "derived_from_history_revenue_cost"
    assert segment["history_metrics"]["gross_margin"]["fallback"] is True
