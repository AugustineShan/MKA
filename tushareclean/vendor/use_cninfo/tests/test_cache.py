"""cache 模块测试 — 用 tmp_cache_dir 隔离。"""

import json

from cninfo import cache


def test_cache_root_respects_env(tmp_cache_dir):
    assert cache.cache_root() == tmp_cache_dir


def test_paths_for_layout(tmp_cache_dir):
    p = cache.paths_for("600519.SH", "20240412", "9999000001")
    assert p.pdf == tmp_cache_dir / "pdf" / "600519.SH" / "20240412__9999000001.pdf"
    assert p.md == tmp_cache_dir / "md" / "600519.SH" / "20240412__9999000001.md"
    assert p.meta == tmp_cache_dir / "meta" / "9999000001.json"


def test_write_read_three_files(tmp_cache_dir):
    p = cache.paths_for("600519.SH", "20240412", "9999000001")
    assert not p.all_exist()

    cache.write_pdf(p, b"%PDF-fake")
    cache.write_md(p, {"title": "贵州茅台2024年年度报告", "pages": 2}, "正文 body")
    cache.write_meta(p, {"ann_id": "9999000001", "title": "贵州茅台2024年年度报告"})
    assert p.all_exist()

    md = cache.read_md(p)
    assert md is not None
    assert "---" in md
    assert "title:" in md
    assert "正文 body" in md

    meta = cache.read_meta(p)
    assert meta is not None and meta["ann_id"] == "9999000001"


def test_orgid_map_round_trip(tmp_cache_dir):
    assert cache.load_orgid_map() == {}
    cache.upsert_orgid("600519", "gssh0600519")
    cache.upsert_orgid("301580", "gfbj0870132")
    m = cache.load_orgid_map()
    assert m == {"600519": "gssh0600519", "301580": "gfbj0870132"}
    raw = json.loads((tmp_cache_dir / "orgid_map.json").read_text())
    assert raw == m


def test_stats_and_verify(tmp_cache_dir):
    p = cache.paths_for("600519.SH", "20240412", "9999000001")
    cache.write_pdf(p, b"%PDF-fake")
    cache.write_md(p, {"title": "x"}, "body")
    cache.write_meta(p, {"ann_id": "9999000001"})

    s = cache.stats()
    assert s.pdf_count == 1
    assert s.md_count == 1
    assert s.meta_count == 1
    assert s.total_bytes > 0
    assert cache.verify() == []

    # 删 md 制造不一致
    p.md.unlink()
    warns = cache.verify()
    assert any("no md" in w for w in warns)


def test_prune_older_than(tmp_cache_dir):
    import os
    import time

    p = cache.paths_for("600519.SH", "20240412", "9999000001")
    cache.write_pdf(p, b"%PDF")
    cache.write_md(p, {"title": "x"}, "body")
    cache.write_meta(p, {"ann_id": "9999000001", "ts_code": "600519.SH", "ann_date": "20240412"})

    # 把 meta mtime 改成 2 天前
    old = time.time() - 2 * 86400
    os.utime(p.meta, (old, old))

    n = cache.prune_older_than(1)
    assert n == 1
    assert not p.pdf.exists()
    assert not p.md.exists()
    assert not p.meta.exists()
