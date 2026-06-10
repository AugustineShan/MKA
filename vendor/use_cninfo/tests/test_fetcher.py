"""fetcher 模块测试 — mock cninfo + PDF 下载。"""

from unittest.mock import patch

from cninfo.fetcher import fetch_announcement, find_periodic_report


def _items(sample_query_response):
    return sample_query_response["announcements"]


def test_fetch_announcement_writes_three_files(
    tmp_cache_dir, sample_query_response, sample_pdf_bytes
):
    item = _items(sample_query_response)[0]  # 年报本体
    with patch("cninfo.fetcher.fetch_pdf_bytes", return_value=sample_pdf_bytes):
        res = fetch_announcement(item, plate="sh")

    assert res.cache_hit is False
    assert res.ann_id == "9999000001"
    assert res.ts_code == "600519.SH"
    assert res.ann_date == "20240412"
    assert res.total_pages == 2
    assert res.extracted_pages == 2
    assert res.text_chars > 0

    pdf = tmp_cache_dir / "pdf" / "600519.SH" / "20240412__9999000001.pdf"
    md = tmp_cache_dir / "md" / "600519.SH" / "20240412__9999000001.md"
    meta = tmp_cache_dir / "meta" / "9999000001.json"
    assert pdf.exists() and pdf.read_bytes() == sample_pdf_bytes
    assert md.exists()
    md_text = md.read_text(encoding="utf-8")
    assert "title:" in md_text
    assert "Hello cninfo" in md_text
    assert meta.exists()


def test_fetch_announcement_cache_hit_skips_network(
    tmp_cache_dir, sample_query_response, sample_pdf_bytes
):
    item = _items(sample_query_response)[0]
    with patch("cninfo.fetcher.fetch_pdf_bytes", return_value=sample_pdf_bytes) as fpb:
        fetch_announcement(item, plate="sh")
        assert fpb.call_count == 1
        # 二次调用应当命中 cache
        res = fetch_announcement(item, plate="sh")
        assert fpb.call_count == 1
        assert res.cache_hit is True
        assert res.total_pages == 2


def test_fetch_announcement_force_redownloads(
    tmp_cache_dir, sample_query_response, sample_pdf_bytes
):
    item = _items(sample_query_response)[0]
    with patch("cninfo.fetcher.fetch_pdf_bytes", return_value=sample_pdf_bytes) as fpb:
        fetch_announcement(item, plate="sh")
        fetch_announcement(item, plate="sh", force=True)
        assert fpb.call_count == 2


def test_find_periodic_report_picks_body_not_summary(
    tmp_cache_dir, sample_query_response
):
    items = _items(sample_query_response)

    def fake_iter(*a, **kw):
        yield from items

    with patch("cninfo.fetcher.iter_stock_announcements", fake_iter):
        hit = find_periodic_report("600519", year=2024, kind="annual", plate="sh")

    assert hit is not None
    assert hit["announcementId"] == "9999000001"  # 本体,非摘要


def test_find_periodic_report_returns_none_for_wrong_year(
    tmp_cache_dir, sample_query_response
):
    items = _items(sample_query_response)

    def fake_iter(*a, **kw):
        yield from items

    with patch("cninfo.fetcher.iter_stock_announcements", fake_iter):
        hit = find_periodic_report("600519", year=2023, kind="annual", plate="sh")
    assert hit is None
