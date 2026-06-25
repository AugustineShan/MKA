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


class TestParseReportLenient:
    """兜底解析：strict parse_report 漏掉、但形似定期报告本体的标题。

    仅由 collect_reports 在 _looks_like_periodic_report 为真时调用；这里直接单测
    parse_report_lenient，锁定 kind 优先级首匹配、EXCLUDED 前置排除、年份抽取。
    """

    def _item(self, title: str, adjunct_url: str = "test.pdf", announcement_id: str = "1", announcement_time: int = 0) -> dict:
        return {
            "announcementTitle": title,
            "adjunctUrl": adjunct_url,
            "announcementId": announcement_id,
            "announcementTime": announcement_time,
        }

    ALL = {"annual", "h1", "q1", "q3"}

    def test_half_year_full_text(self):
        r = report_downloader.parse_report_lenient(self._item("2023年半年度报告全文"), {"h1"})
        assert r is not None and r.kind == "h1" and r.year == 2023 and not r.is_revision

    def test_half_year_revision(self):
        r = report_downloader.parse_report_lenient(self._item("2023年半年度报告（修订版）"), {"h1"})
        assert r is not None and r.is_revision

    def test_q1_without_di(self):
        # 比亚迪 2022 起去"第"字变体：strict 旧形会漏，lenient 必须接住
        r = report_downloader.parse_report_lenient(self._item("2022年一季度报告"), {"q1"})
        assert r is not None and r.kind == "q1" and r.year == 2022

    def test_annual_short_form(self):
        r = report_downloader.parse_report_lenient(self._item("2024年年报"), {"annual"})
        assert r is not None and r.kind == "annual" and r.year == 2024

    def test_duplicated_nian(self):
        r = report_downloader.parse_report_lenient(self._item("2020年年年度报告"), {"annual"})
        assert r is not None and r.kind == "annual" and r.year == 2020

    def test_half_year_not_misclassified_as_annual(self):
        """关键回归："半年度报告"含子串"年度报告"，优先级必须保证判 h1 而非 annual。"""
        r = report_downloader.parse_report_lenient(self._item("2023年半年度报告"), self.ALL)
        assert r is not None and r.kind == "h1"

    def test_kind_not_in_allowed_rejected(self):
        """标题是 h1 但 allowed 只含 annual → 放弃，不 fall-through 成 annual。"""
        assert report_downloader.parse_report_lenient(self._item("2023年半年度报告"), {"annual"}) is None

    def test_excluded_keywords_rejected(self):
        for title in (
            "2023年年度报告摘要",
            "关于2023年半年度报告的补充公告",
            "2023年半年度报告更正公告",
            "2023年半年度报告（英文版）",
        ):
            assert report_downloader.parse_report_lenient(self._item(title), self.ALL) is None, (
                f"非正文不应被 lenient 接住: {title}"
            )

    def test_no_kind_word_rejected(self):
        # 含年份但无 kind 词
        assert report_downloader.parse_report_lenient(self._item("2023年股东大会通知"), self.ALL) is None

    def test_missing_adjunct_url(self):
        assert report_downloader.parse_report_lenient(self._item("2023年半年度报告", adjunct_url=""), {"h1"}) is None


class TestH1MarkdownGate:
    """半年报 Markdown 仅最近 N 年生成；年报全量；Q1/Q3 不生成。"""

    def _report(self, kind: str, year: int) -> "report_downloader.Report":
        return report_downloader.Report(
            year=year, kind=kind, is_revision=False, ann_date="", ann_id="1",
            title=f"{year} {kind}", pdf_url="x", adjunct_size_kb=None,
        )

    def _run(self, monkeypatch, tmp_path, report, h1_markdown_years):
        monkeypatch.setattr(report_downloader, "_fetch_pdf_with_retry", lambda *a, **k: b"%PDF-fake")
        rendered: list[tuple[int, str]] = []

        def fake_render(*, company, report, pdf_path, md_path, force):
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text("md", encoding="utf-8")
            rendered.append((report.year, report.kind))
            return True

        monkeypatch.setattr(report_downloader, "render_markdown", fake_render)
        company = report_downloader.CompanyInfo(
            code="000333", ticker="000333.SZ", plate="sz", org_id="x", name="t",
        )
        report_downloader._download_single_report(
            report, company, tmp_path,
            timeout=1, generate_markdown=True, force_markdown=False,
            h1_markdown_years=h1_markdown_years,
        )
        return rendered

    def test_h1_in_allowed_years_rendered(self, monkeypatch, tmp_path):
        rendered = self._run(monkeypatch, tmp_path, self._report("h1", 2024), {2023, 2024})
        assert (2024, "h1") in rendered

    def test_h1_outside_allowed_years_not_rendered(self, monkeypatch, tmp_path):
        rendered = self._run(monkeypatch, tmp_path, self._report("h1", 2020), {2023, 2024})
        assert rendered == []

    def test_h1_none_means_all_years(self, monkeypatch, tmp_path):
        rendered = self._run(monkeypatch, tmp_path, self._report("h1", 2015), None)
        assert (2015, "h1") in rendered

    def test_q1_never_rendered(self, monkeypatch, tmp_path):
        rendered = self._run(monkeypatch, tmp_path, self._report("q1", 2024), None)
        assert rendered == []

    def test_q3_never_rendered(self, monkeypatch, tmp_path):
        rendered = self._run(monkeypatch, tmp_path, self._report("q3", 2024), None)
        assert rendered == []

    def test_annual_always_rendered(self, monkeypatch, tmp_path):
        # 年报不受 h1_markdown_years 限制
        rendered = self._run(monkeypatch, tmp_path, self._report("annual", 2012), {2024})
        assert (2012, "annual") in rendered


class TestFetchPdfWithRetry:
    """_fetch_pdf_with_retry：瞬态重试、4xx 不重试、最终失败抛出。"""

    def _make_response(self, status_code: int):
        import requests
        resp = requests.Response()
        resp.status_code = status_code
        resp._content = b""
        return resp

    def test_success_first_try(self, monkeypatch):
        calls = {"n": 0}

        def fake_fetch(url, *, timeout, session):
            calls["n"] += 1
            return b"%PDF-ok"

        monkeypatch.setattr(report_downloader, "fetch_pdf_bytes", fake_fetch)
        monkeypatch.setattr(report_downloader.time, "sleep", lambda s: None)
        data = report_downloader._fetch_pdf_with_retry("u", timeout=1, session=None)
        assert data == b"%PDF-ok"
        assert calls["n"] == 1

    def test_timeout_then_success(self, monkeypatch):
        import requests
        calls = {"n": 0}

        def fake_fetch(url, *, timeout, session):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.exceptions.Timeout("boom")
            return b"%PDF-ok"

        monkeypatch.setattr(report_downloader, "fetch_pdf_bytes", fake_fetch)
        monkeypatch.setattr(report_downloader.time, "sleep", lambda s: None)
        data = report_downloader._fetch_pdf_with_retry("u", timeout=1, session=None, max_retries=3)
        assert data == b"%PDF-ok"
        assert calls["n"] == 2

    def test_5xx_retried(self, monkeypatch):
        import requests
        calls = {"n": 0}

        def fake_fetch(url, *, timeout, session):
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.exceptions.HTTPError(response=self._make_response(503))
            return b"%PDF-ok"

        monkeypatch.setattr(report_downloader, "fetch_pdf_bytes", fake_fetch)
        monkeypatch.setattr(report_downloader.time, "sleep", lambda s: None)
        data = report_downloader._fetch_pdf_with_retry("u", timeout=1, session=None, max_retries=3)
        assert data == b"%PDF-ok"
        assert calls["n"] == 3

    def test_404_not_retried(self, monkeypatch):
        import requests
        calls = {"n": 0}

        def fake_fetch(url, *, timeout, session):
            calls["n"] += 1
            raise requests.exceptions.HTTPError(response=self._make_response(404))

        monkeypatch.setattr(report_downloader, "fetch_pdf_bytes", fake_fetch)
        monkeypatch.setattr(report_downloader.time, "sleep", lambda s: None)
        with pytest.raises(requests.exceptions.HTTPError):
            report_downloader._fetch_pdf_with_retry("u", timeout=1, session=None, max_retries=3)
        assert calls["n"] == 1  # 4xx 不重试

    def test_all_timeouts_raise(self, monkeypatch):
        import requests
        calls = {"n": 0}

        def fake_fetch(url, *, timeout, session):
            calls["n"] += 1
            raise requests.exceptions.Timeout("boom")

        monkeypatch.setattr(report_downloader, "fetch_pdf_bytes", fake_fetch)
        monkeypatch.setattr(report_downloader.time, "sleep", lambda s: None)
        with pytest.raises(requests.exceptions.Timeout):
            report_downloader._fetch_pdf_with_retry("u", timeout=1, session=None, max_retries=2)
        assert calls["n"] == 3  # 1 初试 + 2 重试

