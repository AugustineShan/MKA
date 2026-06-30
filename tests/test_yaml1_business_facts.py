from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from src.workbench import (
    _editable_assumptions,
    _yaml1_display_contract,
    _yaml1_revenue_view,
    _yaml1_stash_view,
)
from src.yaml1_business_facts import _yoy, build_business_fact_view


def _write_yaml1(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "yaml1_test.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _view(tmp_path: Path, body: str) -> dict:
    path = _write_yaml1(tmp_path, body)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    revenue_view = _yaml1_revenue_view(path)
    stash_view = _yaml1_stash_view(data)
    display_contract = _yaml1_display_contract(data, revenue_view, stash_view)
    return build_business_fact_view(
        data,
        revenue_view=revenue_view,
        stash_view=stash_view,
        display_contract=display_contract,
        editable_assumptions=_editable_assumptions(data),
    )


def _rows(view: dict, path: str) -> list[dict]:
    block = next(block for block in view["blocks"] if block["path"] == path)
    return block["rows"]


def _row(view: dict, path: str, entity: str, metric: str) -> dict:
    return next(row for row in _rows(view, path) if row["entity_key"] == entity and row["metric"] == metric)


def test_business_fact_yoy_handles_negative_base() -> None:
    values = _yoy({"2023": -85.0, "2024": 108.0})
    assert values["2024"] == pytest.approx(193 / 85)


def test_revenue_leaf_direct_margin_is_canonical_business_fact(tmp_path: Path) -> None:
    view = _view(
        tmp_path,
        """
        meta:
          horizon: [2026, 2027]
        income.revenue:
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

    row = _row(view, "income.revenue", "charging", "gross_margin")

    assert row["metric_label"] == "毛利率"
    assert row["values"] == {"2024": 0.361, "2025": 0.3623, "2026": 0.37, "2027": 0.375}
    assert row["value_source"] == "direct"
    assert row["editable_path"] == "income.revenue.charging.margin"


def test_revenue_leaf_derives_margin_only_when_direct_margin_missing(tmp_path: Path) -> None:
    view = _view(
        tmp_path,
        """
        meta:
          horizon: [2026]
        income.revenue:
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

    row = _row(view, "income.revenue", "legacy", "gross_margin")

    assert row["values"] == {"2024": pytest.approx(0.4), "2025": pytest.approx(0.4)}
    assert row["value_source"] == "fallback"


def test_direct_margin_conflict_warns_and_keeps_direct_value(tmp_path: Path) -> None:
    view = _view(
        tmp_path,
        """
        meta:
          horizon: [2026]
        income.revenue:
          segments:
            conflict:
              revenue_family: growth
              base: {base_year: 2025, revenue: 100.0}
              knobs:
                revenue_yoy: [0.10]
              history:
                series:
                  revenue: {2025: 100.0}
                  cost: {2025: 50.0}
                  margin: {2025: 0.30}
        """,
    )

    row = _row(view, "income.revenue", "conflict", "gross_margin")

    assert row["values"]["2025"] == pytest.approx(0.30)
    assert any(warning["code"] == "business_fact_conflict" for warning in view["warnings"])


def test_unknown_history_metric_is_kept_as_custom_with_warning(tmp_path: Path) -> None:
    view = _view(
        tmp_path,
        """
        meta:
          horizon: [2026]
        income.revenue:
          segments:
            weird:
              revenue_family: growth
              base: {base_year: 2025, revenue: 100.0}
              knobs:
                revenue_yoy: [0.10]
              history:
                series:
                  revenue: {2025: 100.0}
                  mystery_kpi: {2025: 7.0}
        """,
    )

    row = _row(view, "income.revenue", "weird", "custom:mysterykpi")

    assert row["values"] == {"2025": 7.0}
    assert any(warning["code"] == "unknown_metric" for warning in view["warnings"])


def test_stash_secondary_split_generates_revenue_margin_and_yoy_rows(tmp_path: Path) -> None:
    view = _view(
        tmp_path,
        """
        meta:
          horizon: [2026]
        income.revenue:
          segments:
            total:
              revenue_family: growth
              base: {base_year: 2025, revenue: 100.0}
              knobs: {revenue_yoy: [0.10]}
        display:
          schema_version: 1
          blocks:
            - path: stash.by_region
              role: secondary_split
              placement: secondary_table
              dimension: region
              metrics: [revenue, gross_margin, revenue_yoy]
        stash:
          by_region:
            unit: 百万元
            series:
              Domestic: {2024: 100.0, 2025: 120.0}
            毛利率:
              series:
                Domestic: {2024: 0.30, 2025: 0.32}
            同比:
              series:
                Domestic: {2025: 0.20}
        """,
    )

    block = next(block for block in view["blocks"] if block["path"] == "stash.by_region")
    metrics = {(row["entity_key"], row["metric"]) for row in block["rows"]}

    assert block["role"] == "secondary_split"
    assert block["placement"] == "secondary_table"
    assert ("Domestic", "revenue") in metrics
    assert ("Domestic", "gross_margin") in metrics
    assert ("Domestic", "revenue_yoy") in metrics


def test_stash_attr_table_metric_aliases_are_recognized(tmp_path: Path) -> None:
    view = _view(
        tmp_path,
        """
        meta:
          horizon: [2026]
        income.revenue:
          segments:
            total:
              revenue_family: growth
              base: {base_year: 2025, revenue: 100.0}
              knobs: {revenue_yoy: [0.10]}
        display:
          schema_version: 1
          blocks:
            - path: stash.line_attrs
              role: primary_attachment
              placement: model_table
              dimension: business_line
              metric: mixed
        stash:
          line_attrs:
            series:
              Product A: {2024_gpm: 0.41, 2025_ton_cost: 7512.5}
        """,
    )

    metrics = {row["metric"]: row for row in _rows(view, "stash.line_attrs")}

    assert metrics["gross_margin"]["values"] == {"2024": 0.41}
    assert metrics["unit_cost"]["values"] == {"2025": 7512.5}
