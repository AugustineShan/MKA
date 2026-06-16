"""cninfo 公告抓取实战代码示例 — 给新项目复制粘贴用。

已 smoke test 实证可跑(2026-05-04)。

依赖:
    pip install requests pymupdf  # PyMuPDF 包名是 pymupdf,import 是 fitz
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

import fitz  # PyMuPDF
import requests

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

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

# 已知 category 值
CATEGORY_NDBG = "category_ndbg_szsh"   # 年度报告
CATEGORY_YJDBG = "category_yjdbg_szsh"  # 一季度报告
CATEGORY_BNDBG = "category_bndbg_szsh"  # 半年度报告
CATEGORY_SJDBG = "category_sjdbg_szsh"  # 三季度报告

# 北京时区
BEIJING = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 1. 单次查询(单页)
# ---------------------------------------------------------------------------

def query_page(
    *,
    plate: str = "",          # sz / sh / bj 或空
    category: str = "",       # category_ndbg_szsh 等,空 = 全
    se_date: str = "",        # "YYYY-MM-DD~YYYY-MM-DD"
    stock: str = "",          # "<6位>,<orgId>"
    searchkey: str = "",
    page_num: int = 1,
    column: str = "szse",
    timeout: float = 15.0,
) -> dict:
    """单次查询,返回 cninfo JSON dict。"""
    body = {
        "tabName": "fulltext",
        "pageSize": "30",      # 服务端硬限,传别的也只返 30
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
    r = requests.post(CNINFO_QUERY, headers=DEFAULT_HEADERS, data=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# 2. 翻页迭代器(自动跑完所有页)
# ---------------------------------------------------------------------------

def query_all(
    *,
    plate: str = "",
    category: str = "",
    se_date: str = "",
    stock: str = "",
    searchkey: str = "",
    column: str = "szse",
    sleep_seconds: float = 0.4,
    max_pages: int = 1000,    # 安全上限
) -> Iterator[dict]:
    """翻页迭代器,yield 每条 announcement。"""
    page = 1
    while page <= max_pages:
        body = query_page(
            plate=plate, category=category, se_date=se_date,
            stock=stock, searchkey=searchkey, column=column,
            page_num=page,
        )
        items = body.get("announcements") or []
        if not items:
            return
        for it in items:
            yield it
        if not body.get("hasMore"):
            return
        page += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)


# ---------------------------------------------------------------------------
# 3. 时间转换(注意 cninfo 的 announcementTime 是 UTC ms,要转北京时间)
# ---------------------------------------------------------------------------

def epoch_ms_to_ann_date(ts_ms: int) -> str:
    """epoch ms (UTC) → 北京日期 YYYYMMDD"""
    return datetime.fromtimestamp(ts_ms / 1000, tz=BEIJING).strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# 4. 标题清洗(去 <em> 高亮)
# ---------------------------------------------------------------------------

def clean_title(raw: str) -> str:
    """去除 cninfo searchkey 命中时插入的 <em>...</em> 高亮标签。"""
    return re.sub(r"</?em>", "", raw or "").strip()


# ---------------------------------------------------------------------------
# 5. 定期报告本体过滤(避开摘要 / 审计 / 内控等)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 6. PDF 下载 + PyMuPDF 解析
# ---------------------------------------------------------------------------

def fetch_and_parse_pdf(url: str, timeout: float = 60.0) -> tuple[str, int, int]:
    """下载 PDF 并解析全文。

    返回 (text, total_pages, extracted_pages)
    extracted_pages = 真正提取到字的页数(< total_pages 表示部分页是扫描/空白)
    """
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    doc = fitz.open(stream=r.content, filetype="pdf")
    total_pages = len(doc)
    parts = []
    extracted = 0
    for page in doc:
        t = page.get_text()
        if t.strip():
            extracted += 1
        parts.append(t)
    doc.close()
    return "\n\n".join(parts), total_pages, extracted


# ---------------------------------------------------------------------------
# 7. 拼 PDF 直链
# ---------------------------------------------------------------------------

def adjunct_to_url(adjunct_path: str) -> str:
    """cninfo 返回的 adjunctUrl 是相对路径,前缀 PDF_BASE 即直链。"""
    return PDF_BASE + adjunct_path.lstrip("/")


# ---------------------------------------------------------------------------
# 8. 实战示例:拉单股最新年报
# ---------------------------------------------------------------------------

def fetch_stock_latest_annual_report(
    sec_code: str,           # "301580"
    plate: str,              # "sz" / "sh" / "bj"
    year: int,               # 2025
    se_date_window: str,     # "2026-04-01~2026-05-04" 披露窗口
) -> dict | None:
    """找指定股票指定年份的年报本体 PDF。

    返回 {ann_id, ann_date, title, url, text, total_pages, extracted_pages}
    或 None(没找到)
    """
    target_title_tail = f"{year}年年度报告"
    for it in query_all(plate=plate, category=CATEGORY_NDBG, se_date=se_date_window):
        if it.get("secCode") != sec_code:
            continue
        title = clean_title(it.get("announcementTitle"))
        if not title.endswith(target_title_tail) or title.endswith("摘要"):
            continue
        ann_id = int(it["announcementId"])
        ann_date = epoch_ms_to_ann_date(int(it["announcementTime"]))
        url = adjunct_to_url(it["adjunctUrl"])
        text, total, extracted = fetch_and_parse_pdf(url)
        return {
            "ann_id": ann_id,
            "ann_date": ann_date,
            "title": title,
            "url": url,
            "text": text,
            "total_pages": total,
            "extracted_pages": extracted,
        }
    return None


# ---------------------------------------------------------------------------
# 9. 实战示例:全市场单日全公告(增量入库典型场景)
# ---------------------------------------------------------------------------

def iter_market_one_day(date_str: str, plate: str = "sz") -> Iterator[dict]:
    """yield 当日全市场单 plate 的所有公告(自动翻页)。

    用法:每天 22:30 cron 跑一次 plate=sz, sh, bj 三次,落盘新增。
    """
    se_date = f"{date_str}~{date_str}"  # 单日
    yield from query_all(plate=plate, se_date=se_date, sleep_seconds=0.4)


# ---------------------------------------------------------------------------
# 10. 实战示例:拼接 ts_code(cninfo secCode 加后缀)
# ---------------------------------------------------------------------------

def to_ts_code(sec_code: str, plate: str) -> str:
    """sec_code='301580', plate='sz' → '301580.SZ'"""
    suffix_map = {"sz": "SZ", "sh": "SH", "bj": "BJ"}
    return f"{sec_code}.{suffix_map[plate]}"


# ---------------------------------------------------------------------------
# Demo / smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Demo 1: 拉爱迪特 2025 年报
    print("=== Demo 1: 爱迪特 2025 年报 ===")
    r = fetch_stock_latest_annual_report(
        sec_code="301580",
        plate="sz",
        year=2025,
        se_date_window="2026-04-01~2026-05-04",
    )
    if r:
        print(f"  found: ann_id={r['ann_id']} ann_date={r['ann_date']}")
        print(f"  title: {r['title']}")
        print(f"  pages: {r['total_pages']} (extracted {r['extracted_pages']})")
        print(f"  text_chars: {len(r['text'])}")
        print(f"  snippet: {r['text'][:200]}")
    else:
        print("  not found")

    # Demo 2: 4/29 当天 sz plate 前 3 条公告
    print("\n=== Demo 2: 4/29 sz plate 前 3 条 ===")
    for i, it in enumerate(iter_market_one_day("2026-04-29", plate="sz")):
        if i >= 3:
            break
        title = clean_title(it.get("announcementTitle", ""))
        sec_code = it.get("secCode")
        ann_date = epoch_ms_to_ann_date(int(it["announcementTime"]))
        print(f"  {ann_date} {sec_code} {title}")
