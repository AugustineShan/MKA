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

    def test_duplicated_nian_is_tolerated(self):
        """cninfo 录入重复"年"字是整类错误，正则用 年+ 兜住，不靠逐家加变体。

        三一重工 600031 的 2020 年报标题是 "2020年年年度报告"（三个"年"）。
        任何"年"重复次数都必须匹配，否则整年漏下载。
        """
        for title in (
            "2020年年年度报告",      # 三一重工 2020（三个"年"）
            "2024年年度报告",        # 正常双"年"
            "2025年年度报告",        # 正常双"年"
            "2024年年报报告",        # 紫金 2024（年度→年报）
            "2024年年报",            # 短形年报
        ):
            report = report_downloader.parse_report(self._item(title), {"annual"})
            assert report is not None, f"annual title should match: {title}"
            assert report.kind == "annual"
        # 四个"年"的极端重复也必须匹配——这正是 年+ 相对固定变体的意义。
        assert report_downloader.parse_report(
            self._item("2020年年年年度报告"), {"annual"}
        ) is not None

    def test_quarterly_duplicated_nian_tolerated(self):
        """季报标题同样容忍"年"字重复。"""
        assert report_downloader.parse_report(
            self._item("2023年年第一季度报告"), {"q1"}
        ).kind == "q1"
        assert report_downloader.parse_report(
            self._item("2023年年一季度报告"), {"q1"}
        ).kind == "q1"

    def test_version_suffix_tolerated(self):
        """词干后的正文版本变体（白名单）必须匹配，不再只认 修订版。

        正式版/最终版/更正版/更新版/取代版 都是正文，cninfo 常见，原正则一律漏。
        """
        cases = {
            "2023年年度报告": (False, "原始版无尾缀"),
            "2023年年度报告全文": (False, "全文非修订"),
            "2023年年度报告正文": (False, "正文非修订"),
            "2023年年度报告（修订版）": (True, "修订类"),
            "2023年年度报告(修订版)": (True, "半角括号修订类"),
            "2023年年度报告（更正版）": (True, "更正版属修订类"),
            "2023年年度报告（更新版）": (True, "更新版属修订类，且不被'更新公告'排除误伤"),
            "2023年年度报告（取代版）": (True, "取代版属修订类"),
            "2023年年度报告（正式版）": (False, "正式版非修订"),
            "2023年年度报告（最终版）": (False, "最终版非修订"),
        }
        for title, (expect_revision, why) in cases.items():
            report = report_downloader.parse_report(self._item(title), {"annual"})
            assert report is not None, f"应匹配正文版本: {title}  ({why})"
            assert report.is_revision is expect_revision, (
                f"is_revision 判定错: {title} 期望 {expect_revision} ({why}) 实际 {report.is_revision}"
            )

    def test_non_body_tails_rejected(self):
        """非正文尾串（补充公告/更正公告/英文版）即使含词干也必须排除，防误下错 PDF。"""
        for title in (
            "2023年年度报告摘要",
            "2023年年度报告审计报告",
            "关于2023年年度报告的补充公告",
            "2023年年度报告更正公告",
            "2023年年度报告（英文版）",
            "2023年年度报告更新公告",
        ):
            assert report_downloader.parse_report(self._item(title), {"annual"}) is None, (
                f"非正文不应匹配: {title}"
            )


class TestSleepBetweenRequests:
    def test_zero_max_interval_is_noop(self):
        import time
        start = time.monotonic()
        report_downloader.sleep_between_requests(1.0, 0.0)
        # Should return immediately
        assert time.monotonic() - start < 0.1


class TestMinYearGate:
    """2010 闸门：report_downloader 的下载下限必须与 clean.RECONCILE_MIN_YEAR 对齐。

    两常量分属不互相导入的模块（report_downloader 不 import src.clean），故显式锁定
    它们相等，防止日后单边改动造成「校验侧 / 下载侧」口径漂移。
    """

    def test_default_min_report_year_equals_reconcile_min_year(self):
        from src.clean import RECONCILE_MIN_YEAR

        assert report_downloader.DEFAULT_MIN_REPORT_YEAR == RECONCILE_MIN_YEAR == 2010

    def test_filter_drops_reports_before_min_year(self):
        """main() 在 collect_reports 之后按 --min-year 丢弃早期报告。复刻该过滤逻辑
        以锁定语义：只保留 year >= min_year。"""
        Report = report_downloader.Report
        reports = [
            Report(year=y, kind="annual", is_revision=False, ann_date="", ann_id=str(y),
                   title=f"{y}年年度报告", pdf_url="x", adjunct_size_kb=None)
            for y in (2008, 2009, 2010, 2011, 2024)
        ]
        kept = [r for r in reports if r.year >= report_downloader.DEFAULT_MIN_REPORT_YEAR]
        assert [r.year for r in kept] == [2010, 2011, 2024]
