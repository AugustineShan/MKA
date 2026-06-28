"""Tests for src.financial_expense_analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import copy_fixture_company
import src.financial_expense_analyzer as fea
from src import defaults_gen
from src.company_paths import db_path, financial_expense_path, recon_dir


def _copy_new_hope_dairy(tmp_path: Path) -> Path:
    # Frozen snapshot incl. 公告/年报/2025_年度报告.md note stub (see tests/conftest.py).
    return copy_fixture_company(tmp_path)


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
    assert path == financial_expense_path(company_dir)
    assert path.exists()

    archive = fea.load_financial_expense_yaml(company_dir)
    assert archive is not None
    assert archive["version"] == fea.EVIDENCE_VERSION
    assert archive["analyzer_version"] == fea.EVIDENCE_VERSION
    assert archive["ticker"] == "002946.SZ"
    assert "periods" in archive

    periods = archive["periods"]
    assert "2024" in periods
    latest = periods["2024"]
    assert latest["report_year"] == "2025"
    assert latest["target_column"] == "上期发生额"
    assert "avg_interest_bearing_debt" in latest["anchors"]
    assert latest["status"] == "approved"
    assert latest["confidence"] == "high"
    assert latest["checks"]["basis_check"]["detected"] == "net_of_capitalized_and_subsidy"
    assert latest["components"]["interest_subsidy"] == pytest.approx(3.8242, abs=0.01)


def test_defaults_gen_overrides_financial_expense_from_yaml_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)

    defaults = defaults_gen.build_defaults(db_path(company_dir), ticker="002946.SZ")
    fin_exp = defaults["income"]["financial_expense"]
    assert fin_exp["interest_expense_rate"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["cash_interest_rate"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["other_fin_exp_abs"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_interest_expense"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_interest_income"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_fin_exp"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_fin_exp"]["value"] == pytest.approx(100.96, abs=0.01)
    assert fin_exp["interest_expense_rate"]["method"] == "annual_report_note_average_balance"

    assert fin_exp["interest_expense_rate"]["value"] == pytest.approx(0.032117, abs=1e-4)
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

    defaults = defaults_gen.build_defaults(db_path(company_dir), ticker="002946.SZ")
    fin_exp = defaults["income"]["financial_expense"]
    assert fin_exp["interest_expense_rate"]["source"] == "clean_annual.5y_median.fin_exp_int_exp / avg_interest_bearing_debt"
    assert fin_exp["interest_expense_rate"]["method"] == "median_recent_5y_positive_samples_avg_interest_bearing_debt"
    assert fin_exp["other_fin_exp_abs"]["source"] == "clean_annual.5y_median.fin_exp - fin_exp_int_exp + fin_exp_int_inc"
    assert any(flag["code"] == "financial_expense_evidence_failed" for flag in defaults["review_flags"])


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
    assert path == recon_dir(company_dir) / "financial_expense_detail_latest.json"
    evidence = fea.load_evidence(company_dir)
    assert evidence is not None
    assert evidence["base_period"] == "2024"
    assert evidence["target_column"] == "上期发生额"
    assert evidence["status"] == "approved"


def test_defaults_gen_dividend_payout_uses_cashflow_net_lagged_policy(tmp_path):
    company_dir = _copy_new_hope_dairy(tmp_path)

    defaults = defaults_gen.build_defaults(db_path(company_dir), ticker="002946.SZ")
    payout = defaults["balance_sheet"]["dividend_payout"]

    assert payout["value"] == pytest.approx(0.176525, abs=1e-6)
    assert payout["value"] > 0
    assert "c_pay_dist_dpcp_int_exp" in payout["source"]
    assert "distr_profit_shrhder" not in payout["source"]
    assert payout["method"] == "median_recent_3y_lagged_cash_payout_net_of_interest_and_minority_dividend"
    assert payout["sample_periods"] == ["2022", "2023", "2024"]


def test_analyze_period_prefers_current_year_current_column(tmp_path, monkeypatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir()
    captured: list[list[dict[str, str]]] = []

    def fake_annual_markdown_path(_company_dir: Path, year: str) -> Path | None:
        return tmp_path / f"{year}.md" if year == "2025" else None

    def fake_read_md_lines(_path: Path) -> list[str]:
        return [
            "# 财务费用",
            "| 项目 | 本期发生额 | 上期发生额 |",
            "| 利息支出 | 1 | 1 |",
        ]

    def fake_call_llm(messages: list[dict[str, str]]) -> dict:
        captured.append(messages)
        return _mock_llm_response()

    monkeypatch.setattr(fea, "annual_markdown_path", fake_annual_markdown_path)
    monkeypatch.setattr(fea, "read_md_lines", fake_read_md_lines)
    monkeypatch.setattr(fea, "call_llm", fake_call_llm)

    row = {
        "fin_exp": 100.96286385,
        "fin_exp_int_exp": 106.26812165,
        "fin_exp_int_inc": 7.65824373,
        "st_borr": 3106.26863603,
        "money_cap": 396.4783577,
        "revenue": 10665.42345785,
    }
    prev_row = {
        "st_borr": 3749.36274611,
        "money_cap": 439.54278948,
    }

    record = fea._analyze_period("002946.SZ", company_dir, tmp_path / "data.db", "2025", row, prev_row)

    assert record["report_year"] == "2025"
    assert record["target_column"] == "本期发生额"
    assert record["status"] == "approved"
    assert "本期发生额" in captured[0][1]["content"]
    assert record["derived"]["interest_expense_rate"] == pytest.approx(
        record["derived"]["interest_expense"] / record["anchors"]["avg_interest_bearing_debt"]
    )


def test_analyze_all_periods_retries_current_version_fallback_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    calls = {"count": 0}

    fea.write_financial_expense_yaml(
        financial_expense_path(company_dir),
        {
            "version": fea.EVIDENCE_VERSION,
            "ticker": "002946.SZ",
            "periods": {"2024": {"status": "fallback", "confidence": "low"}},
        },
    )

    def fake_call_llm(_messages):
        calls["count"] += 1
        return _mock_llm_response()

    monkeypatch.setattr(fea, "call_llm", fake_call_llm)

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=False)

    assert calls["count"] > 0
    archive = fea.load_financial_expense_yaml(company_dir)
    assert archive is not None
    assert archive["periods"]["2024"]["status"] == "approved"
