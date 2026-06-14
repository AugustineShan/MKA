"""Regression gate for yearly-shaped calc inputs."""

from __future__ import annotations

import json
import math
from io import StringIO
from pathlib import Path

import pandas as pd

from src.calc import run_forecast
from src.yaml1_cleaner import broadcast_yaml2_defaults
from src.yaml2_schema import read_yaml2


BASELINE_PATH = Path("tests/fixtures/calc_scalar_baseline.json")
ABS_TOL = 1e-6
REL_TOL = 1e-9


def _result_payload(result: dict) -> dict[str, str]:
    return {
        "income_statement": result["income_statement"].to_csv(index=False),
        "balance_sheet": result["balance_sheet"].to_csv(index=False),
        "cash_flow": result["cash_flow"].to_csv(index=False),
        "dcf": result["dcf"].to_csv(index=False),
        "summary_json": json.dumps(
            result["summary"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _assert_frame_equivalent(actual_csv: str, expected_csv: str, ticker: str, table: str) -> None:
    actual = pd.read_csv(StringIO(actual_csv))
    expected = pd.read_csv(StringIO(expected_csv))
    assert list(actual.columns) == list(expected.columns), f"{ticker} {table} columns changed"
    assert len(actual) == len(expected), f"{ticker} {table} row count changed"
    if "period" in expected.columns:
        assert actual["period"].astype(str).tolist() == expected["period"].astype(str).tolist()

    for col in expected.columns:
        if col == "period":
            continue
        actual_num = pd.to_numeric(actual[col], errors="coerce")
        expected_num = pd.to_numeric(expected[col], errors="coerce")
        if actual_num.notna().all() and expected_num.notna().all():
            diffs = (actual_num - expected_num).abs()
            for idx, diff in diffs.items():
                a = float(actual_num.iloc[idx])
                e = float(expected_num.iloc[idx])
                assert math.isclose(a, e, abs_tol=ABS_TOL, rel_tol=REL_TOL), (
                    f"{ticker} {table}.{col} row={idx} expected={e} actual={a} diff={diff}"
                )
        else:
            assert actual[col].astype(str).tolist() == expected[col].astype(str).tolist(), (
                f"{ticker} {table}.{col} non-numeric values changed"
            )


def _assert_summary_equivalent(actual_json: str, expected_json: str, ticker: str) -> None:
    actual = json.loads(actual_json)
    expected = json.loads(expected_json)
    assert set(actual) == set(expected), f"{ticker} summary keys changed"
    for key in expected:
        _assert_json_equivalent(actual[key], expected[key], f"{ticker} summary.{key}")


def _assert_json_equivalent(actual, expected, label: str) -> None:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        assert math.isclose(float(actual), float(expected), abs_tol=ABS_TOL, rel_tol=REL_TOL), (
            f"{label} expected={expected} actual={actual}"
        )
    elif isinstance(actual, list) and isinstance(expected, list):
        assert len(actual) == len(expected), f"{label} length changed"
        for idx, (a_item, e_item) in enumerate(zip(actual, expected)):
            _assert_json_equivalent(a_item, e_item, f"{label}[{idx}]")
    elif isinstance(actual, dict) and isinstance(expected, dict):
        assert set(actual) == set(expected), f"{label} keys changed"
        for key in expected:
            _assert_json_equivalent(actual[key], expected[key], f"{label}.{key}")
    else:
        assert actual == expected, f"{label} changed"


def test_broadcast_defaults_are_numerically_equivalent_to_scalar_baseline():
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline, "baseline fixture must contain at least one company"

    missing: list[str] = []
    for ticker, expected in sorted(baseline.items()):
        defaults_path = Path(expected["defaults_path"])
        if not defaults_path.exists():
            missing.append(f"{ticker}: {defaults_path}")
            continue
        yaml2 = read_yaml2(defaults_path)
        yearly = broadcast_yaml2_defaults(yaml2)
        actual = _result_payload(run_forecast(yearly))
        for table in ["income_statement", "balance_sheet", "cash_flow", "dcf"]:
            _assert_frame_equivalent(actual[table], expected[table], ticker, table)
        _assert_summary_equivalent(actual["summary_json"], expected["summary_json"], ticker)

    assert missing == []
