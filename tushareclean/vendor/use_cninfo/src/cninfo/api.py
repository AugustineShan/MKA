"""cninfo `hisAnnouncement/query` 接口客户端。

从 docs/cookbook.py 抽出的纯 API 层 — 单页查询 / 翻页迭代器 / 标题清洗 / 时区转换 / PDF 直链拼接。

接口约束(详见 docs/api_reference.md & docs/gotchas.md):
- pageSize 服务端硬限 30,传别的也只返 30
- stock 参数必须是 `<6位code>,<orgId>`,只传 6 位返 0 条
- announcementTime 是 UTC epoch ms,要按北京时区转 ann_date
- title 含 `<em>` 高亮标签时需清洗
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import requests

CNINFO_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "http://static.cninfo.com.cn/"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.2 Safari/605.1.15"
    ),
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}

CATEGORY_NDBG = "category_ndbg_szsh"
CATEGORY_YJDBG = "category_yjdbg_szsh"
CATEGORY_BNDBG = "category_bndbg_szsh"
CATEGORY_SJDBG = "category_sjdbg_szsh"

KIND_TO_CATEGORY = {
    "annual": CATEGORY_NDBG,
    "q1": CATEGORY_YJDBG,
    "h1": CATEGORY_BNDBG,
    "q3": CATEGORY_SJDBG,
}

KIND_TO_TITLE_TAIL = {
    "annual": "年年度报告",
    "q1": "年第一季度报告",
    "h1": "年半年度报告",
    "q3": "年第三季度报告",
}

BEIJING = timezone(timedelta(hours=8))

PLATE_TO_SUFFIX = {"sz": "SZ", "sh": "SH", "bj": "BJ"}


def query_page(
    *,
    plate: str = "",
    category: str = "",
    se_date: str = "",
    stock: str = "",
    searchkey: str = "",
    page_num: int = 1,
    column: str = "szse",
    timeout: float = 15.0,
    session: requests.Session | None = None,
) -> dict:
    """单次查询,返回 cninfo JSON dict。"""
    body = {
        "tabName": "fulltext",
        "pageSize": "30",
        "pageNum": str(page_num),
        "column": column,
        "category": category,
        "plate": plate,
        "searchkey": searchkey,
        "secid": "",
        "trade": "",
        "seDate": se_date,
        "stock": stock,
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    s = session or requests
    r = s.post(CNINFO_QUERY, headers=DEFAULT_HEADERS, data=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def query_all(
    *,
    plate: str = "",
    category: str = "",
    se_date: str = "",
    stock: str = "",
    searchkey: str = "",
    column: str = "szse",
    sleep_seconds: float = 0.4,
    max_pages: int = 1000,
    session: requests.Session | None = None,
) -> Iterator[dict]:
    """翻页迭代器,yield 每条 announcement。"""
    page = 1
    while page <= max_pages:
        body = query_page(
            plate=plate,
            category=category,
            se_date=se_date,
            stock=stock,
            searchkey=searchkey,
            column=column,
            page_num=page,
            session=session,
        )
        items = body.get("announcements") or []
        if not items:
            return
        yield from items
        if not body.get("hasMore"):
            return
        page += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


def epoch_ms_to_ann_date(ts_ms: int) -> str:
    """epoch ms (UTC) → 北京日期 YYYYMMDD"""
    return datetime.fromtimestamp(ts_ms / 1000, tz=BEIJING).strftime("%Y%m%d")


def clean_title(raw: str | None) -> str:
    """去除 cninfo searchkey 命中时插入的 <em>...</em> 高亮标签。"""
    return re.sub(r"</?em>", "", raw or "").strip()


def adjunct_to_url(adjunct_path: str) -> str:
    """cninfo 返回的 adjunctUrl 是相对路径,拼接 PDF_BASE 即直链。"""
    return PDF_BASE + adjunct_path.lstrip("/")


_REPORT_TAIL_RE = re.compile(r"\d{4}年(年度|第一季度|半年度|第三季度)报告$")
_NOT_BODY_KW = ("审计报告", "内部控制", "提示性公告", "披露", "鉴证报告")


def is_periodic_report_body(title: str) -> bool:
    """匹配 'YYYY年[年度/第一季度/半年度/第三季度]报告' 本体,排除摘要/审计/内控等。"""
    t = clean_title(title)
    if t.endswith("摘要"):
        return False
    if any(kw in t for kw in _NOT_BODY_KW):
        return False
    return bool(_REPORT_TAIL_RE.search(t))


def is_kind_report_body(title: str, year: int, kind: str) -> bool:
    """是否是指定年份指定 kind 的定期报告本体(非摘要)。"""
    t = clean_title(title)
    if t.endswith("摘要"):
        return False
    if any(kw in t for kw in _NOT_BODY_KW):
        return False
    tail = KIND_TO_TITLE_TAIL.get(kind)
    if not tail:
        return False
    return t.endswith(f"{year}{tail}")


def to_ts_code(sec_code: str, plate: str) -> str:
    """sec_code='301580', plate='sz' → '301580.SZ'"""
    suffix = PLATE_TO_SUFFIX.get(plate)
    if not suffix:
        raise ValueError(f"unknown plate: {plate!r}")
    return f"{sec_code}.{suffix}"


def guess_plate(sec_code: str) -> str:
    """根据 6 位代码粗略推测 plate(sz/sh/bj)。

    粗略规则(用于无 orgId 时辅助):
    - 0xx / 3xx → sz(深主板 / 创业板)
    - 6xx → sh(沪主板 / 科创板 688)
    - 4xx / 8xx / 92xx → bj(北交所)

    严谨场景仍应通过查询返回的实际 column / plate 确认。
    """
    if not sec_code or len(sec_code) != 6 or not sec_code.isdigit():
        raise ValueError(f"invalid sec_code: {sec_code!r}")
    head = sec_code[0]
    if head in ("0", "3"):
        return "sz"
    if head == "6":
        return "sh"
    if head in ("4", "8", "9"):
        return "bj"
    raise ValueError(f"cannot infer plate from sec_code: {sec_code!r}")


def fetch_pdf_bytes(url: str, *, timeout: float = 60.0, session: requests.Session | None = None) -> bytes:
    """下载 PDF 二进制。"""
    s = session or requests
    r = s.get(url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]}, timeout=timeout)
    r.raise_for_status()
    return r.content
