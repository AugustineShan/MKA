"""Unit tests for report_downloader.py helpers."""

from __future__ import annotations

import pytest

from src import report_downloader


class TestParseReport:
    def _item(self, title: str, adjunct_url: str = "test.pdf", announcement_id: str = "1", announcement_time: int = 0) -> dict:
        return {
            "announcementTitle": title,
            "adjunctUrl": adjunct_url,
            "announcementId": announcement_id,
            "announcementTime": announcement_time,
        }

    def test_annual_report_matches(self):
        item = self._item("2023年年度报告")
        report = report_downloader.parse_report(item, {"annual"})
        assert report is not None
        assert report.year == 2023
        assert report.kind == "annual"
        assert not report.is_revision

    def test_revision_annual_report_matches(self):
        item = self._item("2023年年度报告（修订版）")
        report = report_downloader.parse_report(item, {"annual"})
        assert report is not None
        assert report.is_revision

    def test_summary_is_excluded(self):
        item = self._item("2023年年度报告摘要")
        assert report_downloader.parse_report(item, {"annual"}) is None

    def test_english_is_excluded(self):
        item = self._item("2023年年度报告（英文版）")
        assert report_downloader.parse_report(item, {"annual"}) is None

    def test_audit_report_is_excluded(self):
        item = self._item("2023年年度报告审计报告")
        assert report_downloader.parse_report(item, {"annual"}) is None

    def test_quarterly_reports(self):
        assert report_downloader.parse_report(self._item("2023年第一季度报告"), {"q1"}).kind == "q1"
        assert report_downloader.parse_report(self._item("2023年半年度报告"), {"h1"}).kind == "h1"
        assert report_downloader.parse_report(self._item("2023年第三季度报告"), {"q3"}).kind == "q3"

    def test_missing_adjunct_url_returns_none(self):
        item = self._item("2023年年度报告", adjunct_url="")
        assert report_downloader.parse_report(item, {"annual"}) is None


class TestSleepBetweenRequests:
    def test_zero_max_interval_is_noop(self):
        import time
        start = time.monotonic()
        report_downloader.sleep_between_requests(1.0, 0.0)
        # Should return immediately
        assert time.monotonic() - start < 0.1
