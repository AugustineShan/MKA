"""CLI 子命令测试 — 走 main([...]) 入口。"""

import json
from unittest.mock import patch

import pytest

from cninfo.cli import main


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "fetch-report" in out
    assert "fetch-stock" in out
    assert "cache" in out


def test_cache_stats_empty(tmp_cache_dir, capsys):
    rc = main(["cache", "stats"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["pdf_count"] == 0
    assert data["md_count"] == 0
    assert data["orgid_count"] == 0


def test_orgid_cache_only_missing(tmp_cache_dir, capsys):
    rc = main(["orgid", "999999", "--cache-only"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "orgId not cached" in err


def test_orgid_cache_hit(tmp_cache_dir, capsys):
    from cninfo.cache import upsert_orgid

    upsert_orgid("600519", "gssh0600519")
    rc = main(["orgid", "600519", "--cache-only"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"sec_code": "600519", "orgId": "gssh0600519"}


def test_fetch_report_runs(tmp_cache_dir, sample_query_response, sample_pdf_bytes, capsys):
    items = sample_query_response["announcements"]

    def fake_iter(*a, **kw):
        yield from items

    with (
        patch("cninfo.fetcher.iter_stock_announcements", fake_iter),
        patch("cninfo.fetcher.fetch_pdf_bytes", return_value=sample_pdf_bytes),
    ):
        rc = main(["fetch-report", "600519", "--year", "2024", "--kind", "annual", "--plate", "sh"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ann_id"] == "9999000001"
    assert data["ts_code"] == "600519.SH"
    assert data["total_pages"] == 2
    assert data["cache_hit"] is False
