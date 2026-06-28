from __future__ import annotations

from pathlib import Path

from src.init import _format_defaults_status


def test_format_defaults_status_without_flags():
    status = _format_defaults_status(
        Path("defaults.yaml"),
        {"base_period": "2025", "review_flags": []},
    )

    assert "base_period=2025" in status
    assert "review_flags=0" in status
    assert status.startswith("✅")


def test_format_defaults_status_with_flags_summarizes_top_items():
    status = _format_defaults_status(
        Path("defaults.yaml"),
        {
            "base_period": "2025",
            "review_flags": [
                {"code": "latest_outlier", "path": "balance_sheet.dividend_payout"},
                {"code": "one_off_candidate", "path": "income.cost_abs.assets_impair_loss"},
                {"code": "financial_expense_evidence_failed", "path": "income.financial_expense"},
                {"code": "missing_as_zero", "path": "income.minority_ratio"},
            ],
        },
    )

    assert status.startswith("⚠️")
    assert "review_flags=4" in status
    assert "latest_outlier: balance_sheet.dividend_payout" in status
    assert "financial_expense_evidence_failed: income.financial_expense" in status
    assert "另 1 项" in status
