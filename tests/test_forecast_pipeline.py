"""User-facing forecast pipeline tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from conftest import copy_fixture_company
from src import yaml1_cleaner
from src.company_paths import forecast_dir, modelking_dir
from src.forecast import run_company_forecast


def _copy_new_hope_dairy(tmp_path: Path) -> Path:
    # Frozen snapshot (see tests/conftest.py) — deterministic forecast inputs.
    return copy_fixture_company(tmp_path)


def test_run_company_forecast_hides_intermediates_and_rebuilds_forecast(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")

    out_dir = forecast_dir(company_dir)
    internal_dir = modelking_dir(company_dir)
    stale_dir = out_dir
    stale_dir.mkdir(parents=True)
    (stale_dir / "stale.txt").write_text("old output", encoding="utf-8")

    run = run_company_forecast(ticker="002946.SZ")

    assert run.output_dir == out_dir
    assert not (company_dir / "forecast_params.yaml").exists()
    assert not (company_dir / "yaml1_clean_report.json").exists()
    assert not (company_dir / "yaml2_yearly.yaml").exists()
    assert not (stale_dir / "stale.txt").exists()

    assert (internal_dir / "forecast_params.yaml").exists()
    assert (internal_dir / "yaml1_clean_report.json").exists()
    assert (internal_dir / "forecast_build.json").exists()
    assert (out_dir / "forecast_is.csv").exists()
    assert (out_dir / "forecast_bs.csv").exists()
    assert (out_dir / "forecast_cf.csv").exists()
    assert (out_dir / "full_is.csv").exists()
    assert (out_dir / "full_bs.csv").exists()
    assert (out_dir / "full_cf.csv").exists()
    assert (out_dir / "dcf_summary.json").exists()

    # Invariant assertions (not a brittle golden point value coupled to mutable
    # company data): the engine must produce a finite, positive, sanely-bounded
    # per-share value, and the projected balance sheet must balance every year.
    # The historical backtest hard-gate is asserted via the manifest below.
    summary = json.loads((out_dir / "dcf_summary.json").read_text(encoding="utf-8"))
    per_share = summary["per_share_value"]
    assert math.isfinite(per_share)
    assert 1.0 < per_share < 200.0

    bs = pd.read_csv(out_dir / "forecast_bs.csv")
    residual = (bs["total_assets"] - bs["total_liab"] - bs["total_hldr_eqy_inc_min_int"]).abs()
    assert (residual < 1.0).all(), f"projected balance sheet does not balance: max residual {residual.max()}"

    manifest = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract"] == "Agent/defaults.yaml + Agent/yaml1*.yaml -> Agent/forecast/"
    assert manifest["yaml2_defaults_path"].endswith("defaults.yaml")
    # Naming-scheme-agnostic: the manifest must record a yaml1 file, not a specific stem.
    assert Path(manifest["yaml1_path"]).name.startswith("yaml1")
    assert manifest["yaml1_path"].endswith(".yaml")
    assert ".modelking" in manifest["internal_forecast_params_path"]
    assert manifest["backtest_status"] == "passed"


def test_run_company_forecast_rejects_noncanonical_output_dir(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")

    with pytest.raises(Exception, match="must be named forecast"):
        run_company_forecast(ticker="002946.SZ", output_dir=company_dir / "Agent" / "forecast_yaml1")
