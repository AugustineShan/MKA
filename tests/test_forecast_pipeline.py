"""User-facing forecast pipeline tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src import yaml1_cleaner
from src.calc import _refuse_baseline_over_yaml1
from src.forecast import run_company_forecast


def _source_company_dir() -> Path:
    return next(Path("companies").glob("*_002946"))


def _copy_new_hope_dairy(tmp_path: Path) -> Path:
    src = _source_company_dir()
    dst = tmp_path / "companies" / src.name
    dst.mkdir(parents=True)
    yaml1_path = yaml1_cleaner.default_yaml1_path(src)
    for name in ["defaults.yaml", "data.db"]:
        shutil.copy2(src / name, dst / name)
    shutil.copy2(yaml1_path, dst / yaml1_path.name)
    return dst


def test_run_company_forecast_hides_intermediates_and_rebuilds_forecast(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")

    stale_dir = company_dir / "forecast"
    stale_dir.mkdir()
    (stale_dir / "stale.txt").write_text("old output", encoding="utf-8")

    run = run_company_forecast(ticker="002946.SZ")

    assert run.output_dir == company_dir / "forecast"
    assert not (company_dir / "forecast_params.yaml").exists()
    assert not (company_dir / "yaml1_clean_report.json").exists()
    assert not (company_dir / "yaml2_yearly.yaml").exists()
    assert not (stale_dir / "stale.txt").exists()

    assert (company_dir / ".modelking" / "forecast_params.yaml").exists()
    assert (company_dir / ".modelking" / "yaml1_clean_report.json").exists()
    assert (company_dir / ".modelking" / "forecast_build.json").exists()
    assert (company_dir / "forecast" / "forecast_is.csv").exists()
    assert (company_dir / "forecast" / "forecast_bs.csv").exists()
    assert (company_dir / "forecast" / "forecast_cf.csv").exists()
    assert (company_dir / "forecast" / "dcf_summary.json").exists()

    summary = json.loads((company_dir / "forecast" / "dcf_summary.json").read_text(encoding="utf-8"))
    assert summary["per_share_value"] == pytest.approx(16.808711166101325)

    manifest = json.loads((company_dir / "forecast" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract"] == "defaults.yaml + yaml1*.yaml -> forecast/"
    assert manifest["yaml2_defaults_path"].endswith("defaults.yaml")
    assert "yaml1_002946" in manifest["yaml1_path"]
    assert ".modelking" in manifest["internal_forecast_params_path"]
    assert manifest["backtest_status"] == "passed"


def test_run_company_forecast_rejects_noncanonical_output_dir(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")

    with pytest.raises(Exception, match="must be named forecast"):
        run_company_forecast(ticker="002946.SZ", output_dir=company_dir / "forecast_yaml1")


def test_calc_cli_refuses_baseline_when_yaml1_exists(tmp_path):
    company_dir = _copy_new_hope_dairy(tmp_path)

    with pytest.raises(SystemExit, match="yaml1 exists"):
        _refuse_baseline_over_yaml1(company_dir / "defaults.yaml", allow_baseline=False)

    _refuse_baseline_over_yaml1(company_dir / "defaults.yaml", allow_baseline=True)
