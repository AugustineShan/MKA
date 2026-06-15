"""Tests for src.financial_expense_analyzer."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import src.financial_expense_analyzer as fea
from src import defaults_gen


def _source_company_dir() -> Path:
    return next(Path("companies").glob("*_002946"))


def _copy_new_hope_dairy(tmp_path: Path) -> Path:
    src = _source_company_dir()
    dst = tmp_path / "companies" / src.name
    dst.mkdir(parents=True)
    for name in ["defaults.yaml", "data.db"]:
        shutil.copy2(src / name, dst / name)
    (dst / "annuals").mkdir()
    for md in (src / "annuals").glob("*.md"):
        shutil.copy2(md, dst / "annuals" / md.name)
    return dst


def _mock_llm_response() -> dict:
    return {
        "components": {
            "interest_expense_gross": 124.15265472,
            "capitalized_interest": 14.06033307,
            "interest_subsidy": 3.8242,
            "interest_income": 7.65824373,
            "other_non_interest": 2.35298593,
        },
        "confidence": "high",
        "notes": "mock",
    }


def test_analyze_all_periods_writes_yaml_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    path = fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)
    assert path == company_dir / "financial_expense.yaml"
    assert path.exists()

    archive = fea.load_financial_expense_yaml(company_dir)
    assert archive is not None
    assert archive["ticker"] == "002946.SZ"
    assert "periods" in archive

    periods = archive["periods"]
    assert "2024" in periods
    latest = periods["2024"]
    assert latest["status"] == "approved"
    assert latest["confidence"] == "high"
    assert latest["checks"]["basis_check"]["detected"] == "net_of_capitalized_and_subsidy"
    assert latest["components"]["interest_subsidy"] == pytest.approx(3.8242, abs=0.01)


def test_defaults_gen_overrides_financial_expense_from_yaml_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)

    defaults = defaults_gen.build_defaults(company_dir / "data.db", ticker="002946.SZ")
    fin_exp = defaults["income"]["financial_expense"]
    assert fin_exp["interest_expense_rate"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["cash_interest_rate"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["other_fin_exp_abs"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_interest_expense"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_interest_income"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_fin_exp"]["source"] == "clean_annual.fin_exp"

    assert fin_exp["interest_expense_rate"]["value"] == pytest.approx(0.03544, abs=1e-4)
    assert fin_exp["other_fin_exp_abs"]["value"] == pytest.approx(-1.47, abs=0.01)


def test_defaults_gen_keeps_mechanical_values_when_no_approved_period(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    # All periods fallback because confidence is low.
    monkeypatch.setattr(
        fea,
        "call_llm",
        lambda _messages: {**_mock_llm_response(), "confidence": "low"},
    )

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)

    defaults = defaults_gen.build_defaults(company_dir / "data.db", ticker="002946.SZ")
    fin_exp = defaults["income"]["financial_expense"]
    assert fin_exp["interest_expense_rate"]["source"] == "clean_annual.fin_exp_int_exp / base_interest_bearing_debt"
    assert fin_exp["other_fin_exp_abs"]["source"] == "clean_annual.fin_exp - clean_annual.fin_exp_int_exp + clean_annual.fin_exp_int_inc"


def test_analyze_all_periods_is_idempotent(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    path1 = fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)
    mtime1 = path1.stat().st_mtime
    path2 = fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=False)
    assert path1 == path2
    assert path2.stat().st_mtime == mtime1


def test_analyze_latest_only_writes_debug_evidence(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    path = fea.analyze("002946.SZ", company_dir=company_dir, force=True)
    assert path == company_dir / "recon" / "financial_expense_detail_latest.json"
    evidence = fea.load_evidence(company_dir)
    assert evidence is not None
    assert evidence["base_period"] == "2024"
    assert evidence["status"] == "approved"
