"""高层抓取协调 — 把 api / parser / cache / orgid 拼起来。

- `fetch_announcement(item, plate, force=False)`:对单条 cninfo announcement 命中 cache 即返回,
  否则下载 PDF + PyMuPDF 解析 + 落三件套 + 返回 metadata。
- `iter_stock_announcements(sec_code, since, until, ...)`:按股票时间窗拉公告(自动用 orgId)。
- `iter_market_slice(plate, category, date, ...)`:按全市场切片拉公告。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass

import requests

from cninfo.api import (
    KIND_TO_CATEGORY,
    adjunct_to_url,
    clean_title,
    epoch_ms_to_ann_date,
    fetch_pdf_bytes,
    guess_plate,
    is_kind_report_body,
    query_all,
    to_ts_code,
)
from cninfo.cache import (
    paths_for,
    read_meta,
    upsert_orgid,
    write_md,
    write_meta,
    write_pdf,
)
from cninfo.orgid import stock_param
from cninfo.parser import parse_pdf_bytes


@dataclass
class FetchResult:
    ann_id: str
    sec_code: str
    ts_code: str
    ann_date: str
    title: str
    category: str | None
    pdf_url: str
    pdf_path: str
    md_path: str
    meta_path: str
    total_pages: int
    extracted_pages: int
    text_chars: int
    cache_hit: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_item(item: dict, plate: str) -> dict:
    """从 cninfo 单条 announcement 提取关键字段(已清洗)。"""
    sec_code = item.get("secCode") or ""
    ts_code = to_ts_code(sec_code, plate) if sec_code and plate in {"sz", "sh", "bj"} else sec_code
    ts_ms = int(item.get("announcementTime") or 0)
    return {
        "ann_id": str(item.get("announcementId") or ""),
        "sec_code": sec_code,
        "ts_code": ts_code,
        "sec_name": item.get("secName") or "",
        "org_id": item.get("orgId") or "",
        "ann_date": epoch_ms_to_ann_date(ts_ms) if ts_ms else "",
        "title": clean_title(item.get("announcementTitle")),
        "category": item.get("announcementType") or "",
        "adjunct_url": item.get("adjunctUrl") or "",
        "adjunct_size_kb": item.get("adjunctSize"),
        "raw": item,
    }


def fetch_announcement(
    item: dict,
    plate: str,
    *,
    force: bool = False,
    session: requests.Session | None = None,
) -> FetchResult:
    """抓取并缓存单条公告。命中 cache 时不发网络。"""
    n = _norm_item(item, plate)
    if not n["ann_id"] or not n["adjunct_url"]:
        raise ValueError(f"item missing ann_id / adjunctUrl: {item!r}")

    if n["org_id"] and n["sec_code"]:
        upsert_orgid(n["sec_code"], n["org_id"])

    paths = paths_for(n["ts_code"], n["ann_date"], n["ann_id"])
    pdf_url = adjunct_to_url(n["adjunct_url"])

    if not force and paths.all_exist():
        meta = read_meta(paths) or {}
        return FetchResult(
            ann_id=n["ann_id"],
            sec_code=n["sec_code"],
            ts_code=n["ts_code"],
            ann_date=n["ann_date"],
            title=n["title"],
            category=meta.get("category") or n["category"],
            pdf_url=pdf_url,
            pdf_path=str(paths.pdf),
            md_path=str(paths.md),
            meta_path=str(paths.meta),
            total_pages=meta.get("total_pages", 0),
            extracted_pages=meta.get("extracted_pages", 0),
            text_chars=meta.get("text_chars", 0),
            cache_hit=True,
        )

    pdf_bytes = fetch_pdf_bytes(pdf_url, session=session)
    parsed = parse_pdf_bytes(pdf_bytes)

    write_pdf(paths, pdf_bytes)
    write_md(
        paths,
        frontmatter={
            "ann_id": n["ann_id"],
            "ts_code": n["ts_code"],
            "sec_code": n["sec_code"],
            "sec_name": n["sec_name"],
            "ann_date": n["ann_date"],
            "title": n["title"],
            "category": n["category"],
            "source": pdf_url,
            "total_pages": parsed.total_pages,
            "extracted_pages": parsed.extracted_pages,
            "text_chars": parsed.text_chars,
        },
        body=parsed.text,
    )
    write_meta(
        paths,
        {
            "ann_id": n["ann_id"],
            "ts_code": n["ts_code"],
            "sec_code": n["sec_code"],
            "sec_name": n["sec_name"],
            "org_id": n["org_id"],
            "ann_date": n["ann_date"],
            "title": n["title"],
            "category": n["category"],
            "adjunct_url": n["adjunct_url"],
            "adjunct_size_kb": n["adjunct_size_kb"],
            "pdf_url": pdf_url,
            "total_pages": parsed.total_pages,
            "extracted_pages": parsed.extracted_pages,
            "text_chars": parsed.text_chars,
            "raw": n["raw"],
        },
    )

    return FetchResult(
        ann_id=n["ann_id"],
        sec_code=n["sec_code"],
        ts_code=n["ts_code"],
        ann_date=n["ann_date"],
        title=n["title"],
        category=n["category"],
        pdf_url=pdf_url,
        pdf_path=str(paths.pdf),
        md_path=str(paths.md),
        meta_path=str(paths.meta),
        total_pages=parsed.total_pages,
        extracted_pages=parsed.extracted_pages,
        text_chars=parsed.text_chars,
        cache_hit=False,
    )


def iter_stock_announcements(
    sec_code: str,
    *,
    since: str,
    until: str,
    plate: str | None = None,
    category: str = "",
    sleep_seconds: float = 0.4,
    session: requests.Session | None = None,
) -> Iterator[dict]:
    """单股时间窗拉公告(自动获取 orgId)。yield cninfo 原始 announcement dict。"""
    if plate is None:
        plate = guess_plate(sec_code)
    se_date = f"{since}~{until}"
    column = "szse" if plate in {"sz", "bj"} else "sse"
    yield from query_all(
        plate=plate,
        category=category,
        se_date=se_date,
        stock=stock_param(sec_code),
        column=column,
        sleep_seconds=sleep_seconds,
        session=session,
    )


def iter_market_slice(
    *,
    plate: str,
    category: str = "",
    date: str | None = None,
    since: str | None = None,
    until: str | None = None,
    searchkey: str = "",
    sleep_seconds: float = 0.4,
    session: requests.Session | None = None,
) -> Iterator[dict]:
    """全市场切片拉公告。date 单日 or since/until 区间。"""
    if date:
        se_date = f"{date}~{date}"
    elif since and until:
        se_date = f"{since}~{until}"
    else:
        raise ValueError("must specify either date or both since+until")
    column = "szse" if plate in {"sz", "bj"} else "sse"
    yield from query_all(
        plate=plate,
        category=category,
        se_date=se_date,
        searchkey=searchkey,
        column=column,
        sleep_seconds=sleep_seconds,
        session=session,
    )


def find_periodic_report(
    sec_code: str,
    *,
    year: int,
    kind: str,
    plate: str | None = None,
    se_date_window: str | None = None,
    sleep_seconds: float = 0.4,
    session: requests.Session | None = None,
) -> dict | None:
    """找指定股票指定年份的定期报告本体(非摘要/审计/内控等)。返回 cninfo 原始 item 或 None。"""
    if plate is None:
        plate = guess_plate(sec_code)
    if kind not in KIND_TO_CATEGORY:
        raise ValueError(f"unknown kind: {kind!r} (expected annual/q1/h1/q3)")
    category = KIND_TO_CATEGORY[kind]

    if se_date_window is None:
        # 各 kind 的常见披露窗口(宽松):
        # annual:次年 1-5 月;q1:次年 4-5 月;h1:同年 7-9 月;q3:同年 9-11 月
        windows = {
            "annual": f"{year + 1}-01-01~{year + 1}-05-31",
            "q1": f"{year + 1}-04-01~{year + 1}-05-31",
            "h1": f"{year}-07-01~{year}-09-30",
            "q3": f"{year}-09-01~{year}-11-30",
        }
        se_date_window = windows[kind]
    since, until = se_date_window.split("~")

    items = iter_stock_announcements(
        sec_code,
        since=since,
        until=until,
        plate=plate,
        category=category,
        sleep_seconds=sleep_seconds,
        session=session,
    )
    for it in items:
        if it.get("secCode") != sec_code:
            continue
        title = clean_title(it.get("announcementTitle"))
        if is_kind_report_body(title, year, kind):
            return it
    return None
