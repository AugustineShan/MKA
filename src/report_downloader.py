"""Download cninfo annual/quarterly report PDFs and Markdown text for one A-share company.

Usage:
    python -m src.report_downloader --ticker 000333.SZ
    python -m src.report_downloader --ticker 000333.SZ --quarterly
    python -m src.report_downloader --ticker 000333.SZ --all-reports

This script vendors and reuses rollysys/use_cninfo under vendor/use_cninfo.
It intentionally stays thin: cninfo query details, title cleanup, and PDF
fetching/text extraction come from the vendored cninfo package; this file
handles ticker parsing, report filtering, naming, and project-local output layout.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import requests


BASE_DIR = Path(__file__).resolve().parent.parent
VENDORED_CNINFO_SRC = BASE_DIR / "vendor" / "use_cninfo" / "src"
if str(VENDORED_CNINFO_SRC) not in sys.path:
    sys.path.insert(0, str(VENDORED_CNINFO_SRC))

from cninfo.api import (  # noqa: E402
    CATEGORY_BNDBG,
    CATEGORY_NDBG,
    CATEGORY_SJDBG,
    CATEGORY_YJDBG,
    KIND_TO_CATEGORY,
    adjunct_to_url,
    clean_title,
    epoch_ms_to_ann_date,
    fetch_pdf_bytes,
    guess_plate,
    query_page,
)
from cninfo.cache import upsert_orgid  # noqa: E402
from cninfo.orgid import TOPSEARCH_URL  # noqa: E402


TICKER_RE = re.compile(r"^(?P<code>\d{6})\.(?P<suffix>SH|SZ|BJ)$", re.IGNORECASE)
SAFE_FILENAME_CHARS_RE = re.compile(r'[<>"/\\|?*\x00-\x1f]')

PLATE_BY_SUFFIX = {"SZ": "sz", "SH": "sh", "BJ": "bj"}
COLUMN_BY_PLATE = {"sz": "szse", "bj": "szse", "sh": "sse"}
PDF_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}

KIND_TO_FILENAME_CN: dict[str, str] = {
    "annual": "年度报告",
    "q1": "第一季度报告",
    "h1": "半年度报告",
    "q3": "第三季度报告",
}

# Categories to query for each report kind set
ANNUAL_CATEGORIES = [CATEGORY_NDBG]
QUARTERLY_CATEGORIES = [CATEGORY_YJDBG, CATEGORY_BNDBG, CATEGORY_SJDBG]
ALL_CATEGORIES = [CATEGORY_NDBG, CATEGORY_YJDBG, CATEGORY_BNDBG, CATEGORY_SJDBG]

# 2010 闸门：与 clean.RECONCILE_MIN_YEAR 对齐——2010 之前的年报/季报披露稀疏、
# 格式早期，reconciler 也不会核对 2010 前年度，下载它们纯浪费 cninfo 请求与磁盘。
# report_downloader 是不导入 src.clean 的薄脚本，故在此独立声明同名默认值；
# init.py 调用时显式传 --min-year=clean.RECONCILE_MIN_YEAR 保持单一真源。
DEFAULT_MIN_REPORT_YEAR = 2010


@dataclass(frozen=True)
class CompanyInfo:
    code: str
    ticker: str
    plate: str
    org_id: str
    name: str


@dataclass(frozen=True)
class Report:
    year: int
    kind: str
    is_revision: bool
    ann_date: str
    ann_id: str
    title: str
    pdf_url: str
    adjunct_size_kb: int | None

    @property
    def filename(self) -> str:
        kind_cn = KIND_TO_FILENAME_CN[self.kind]
        if self.is_revision:
            return f"{self.year}_{kind_cn}_修订版.pdf"
        return f"{self.year}_{kind_cn}.pdf"

    @property
    def markdown_filename(self) -> str:
        return Path(self.filename).with_suffix(".md").name

    @property
    def year_subdir(self) -> str | None:
        """Return year subdirectory for non-annual reports."""
        if self.kind == "annual":
            return None
        return str(self.year)


def parse_ticker(ticker: str) -> tuple[str, str]:
    match = TICKER_RE.match(ticker.strip())
    if not match:
        raise ValueError("ticker must look like 000333.SZ / 600519.SH / 430047.BJ")
    code = match.group("code")
    suffix = match.group("suffix").upper()
    plate = PLATE_BY_SUFFIX[suffix]
    guessed = guess_plate(code)
    if guessed != plate:
        raise ValueError(f"ticker suffix {suffix} does not match inferred plate {guessed!r}")
    return code, plate


def sleep_between_requests(min_seconds: float, max_seconds: float) -> None:
    if max_seconds <= 0:
        return
    time.sleep(random.uniform(min_seconds, max_seconds))


def fetch_company_info(
    code: str,
    plate: str,
    *,
    session: requests.Session,
    timeout: float,
) -> CompanyInfo:
    response = session.post(
        TOPSEARCH_URL,
        headers=PDF_REQUEST_HEADERS,
        data={"keyWord": code, "maxNum": "10"},
        timeout=timeout,
    )
    response.raise_for_status()
    items = response.json()
    if not isinstance(items, list):
        raise RuntimeError(f"unexpected topSearch response for {code}: {items!r}")

    for item in items:
        if item.get("code") != code or not item.get("orgId"):
            continue
        org_id = str(item["orgId"])
        upsert_orgid(code, org_id)
        suffix = {"sz": "SZ", "sh": "SH", "bj": "BJ"}[plate]
        return CompanyInfo(
            code=code,
            ticker=f"{code}.{suffix}",
            plate=plate,
            org_id=org_id,
            name=str(item.get("zwjc") or code),
        )

    raise RuntimeError(f"cninfo topSearch did not return an orgId for {code}")


def iter_company_category(
    company: CompanyInfo,
    category: str,
    *,
    session: requests.Session,
    timeout: float,
    min_interval: float,
    max_interval: float,
    max_pages: int = 100,
) -> Iterator[dict]:
    page = 1
    while page <= max_pages:
        data = query_page(
            plate=company.plate,
            category=category,
            stock=f"{company.code},{company.org_id}",
            page_num=page,
            column=COLUMN_BY_PLATE[company.plate],
            timeout=timeout,
            session=session,
        )
        items = data.get("announcements") or []
        yield from items
        if not data.get("hasMore"):
            return
        page += 1
        sleep_between_requests(min_interval, max_interval)
    raise RuntimeError(f"too many cninfo pages for {company.ticker}; stopped at {max_pages}")


# Titles containing these keywords are not the body of a periodic report.
# 用"公告/报告"完整短语而非裸"更新/更正"，避免与版本尾缀"更新版/更正版"相撞——
# 后者是正文修订版必须放行，前者是独立公告必须排除。
EXCLUDED_TITLE_KEYWORDS: tuple[str, ...] = (
    "摘要",
    "审计报告",
    "内部控制",
    "提示性公告",
    "鉴证报告",
    "披露",
    "补充公告",
    "更正公告",
    "更新公告",
    "取消",
    "英文",
)

# Stems that follow the 4-digit year (and its "年" unit word) in cninfo titles.
# cninfo/issuer naming drifts over time and across companies — driven by
# "what shapes do these titles take", never by one sample company:
#   annual — 紫金矿业 601899 的 2024 年报标题是 "2024年年报报告"（年度→年报），
#            只认 "年度报告" 会整年漏掉年报 Markdown。
#   q1/q3  — 比亚迪 002594 从 2022 年起标题由 "第X季度报告" 改为 "X季度报告"
#            （去掉"第"字），只认带"第"的旧形会丢掉 2022+ 全部一季报/三季报，
#            这正是"季报只剩半年报"的根因。
#
# "年"字重复是 cninfo 录入的整类错误，不靠再加变体去补某一家：
#   三一重工 600031 的 2020 年报标题是 "2020年年年度报告"（三个"年"），
#   固定 "年年" 个数会整年漏掉。故正则用 年+（一个或多个"年"）容忍重复，
#   而非把"年"个数焊死——换任何公司、任何"年"重复次数都能跑。
KIND_TITLE_STEMS: dict[str, tuple[str, ...]] = {
    "annual": ("度报告", "报报告", "报"),  # 年度报告 / 年报报告 / 年报
    "q1": ("第一季度报告", "一季度报告"),
    "h1": ("半年度报告",),
    "q3": ("第三季度报告", "三季度报告"),
}

# 版本尾缀：词干之后允许的正文版本标记。裸写（全文/正文）或带全/半角括号
# （修订版/正式版/…）都可。只认这些白名单尾缀 + $ 锚定，既容忍版本变体，
# 又能挡住"…年度报告的补充公告/更正公告"这类非正文（其尾串不在白名单）。
# 修订类 → 文件名加 _修订版；其余（含正式版/最终版/全文/正文）→ 原始版命名。
BODY_VERSION_BARE: tuple[str, ...] = ("全文", "正文")
BODY_VERSION_PAREN: tuple[str, ...] = (
    "修订版", "更正版", "更新版", "取代版",  # 修订类
    "正式版", "最终版",                      # 非修订类
)
REVISION_VERSIONS: frozenset[str] = frozenset({"修订版", "更正版", "更新版", "取代版"})

# Canonical report-name fragments for the "looks periodic but unmatched" warning.
# More specific than the match stems (no bare "报") so the warning stays meaningful.
PERIODIC_REPORT_KEYWORDS: tuple[str, ...] = (
    "年度报告", "年报",
    "半年度报告",
    "第一季度报告", "一季度报告",
    "第三季度报告", "三季度报告",
)


def parse_report(item: dict, allowed_kinds: set[str]) -> Report | None:
    raw_title = clean_title(item.get("announcementTitle"))
    if any(kw in raw_title for kw in EXCLUDED_TITLE_KEYWORDS):
        return None

    # 版本尾缀正则：白名单版本标记（裸写或全/半角括号），整体可选。
    all_versions = BODY_VERSION_BARE + BODY_VERSION_PAREN
    version_alt = "|".join(re.escape(v) for v in all_versions)
    trailer_re = rf"(?:[（(]?(?P<version>{version_alt})[）)]?)?"

    for kind in allowed_kinds:
        stems = KIND_TITLE_STEMS.get(kind)
        if not stems:
            continue
        # 年+ 容忍 cninfo 录入重复"年"字（如 "2020年年年度报告"）；
        # 版本尾缀白名单 + $ 锚定：容忍正文版本变体（正式版/最终版/更正版…），
        # 同时挡住"…补充公告/更正公告"等非正文尾串。
        stem_re = "(?:" + "|".join(re.escape(s) for s in stems) + ")"

        pattern = rf"(?P<year>\d{{4}})年+{stem_re}{trailer_re}$"
        match = re.search(pattern, raw_title)
        if match:
            adjunct_url = item.get("adjunctUrl") or ""
            ann_id = str(item.get("announcementId") or "")
            if not adjunct_url or not ann_id:
                return None

            ann_time = int(item.get("announcementTime") or 0)
            version = match.group("version") or ""
            return Report(
                year=int(match.group("year")),
                kind=kind,
                is_revision=version in REVISION_VERSIONS,
                ann_date=epoch_ms_to_ann_date(ann_time) if ann_time else "",
                ann_id=ann_id,
                title=raw_title,
                pdf_url=adjunct_to_url(adjunct_url),
                adjunct_size_kb=item.get("adjunctSize"),
            )

    return None


def _fetch_category_items(
    category: str,
    company: CompanyInfo,
    timeout: float,
    min_interval: float,
    max_interval: float,
) -> list[dict]:
    """Query one cninfo category; each caller gets its own session for thread safety."""
    worker_session = requests.Session()
    return list(
        iter_company_category(
            company,
            category=category,
            session=worker_session,
            timeout=timeout,
            min_interval=min_interval,
            max_interval=max_interval,
        )
    )


def _looks_like_periodic_report(title: str) -> bool:
    """Return True if title resembles a periodic report body (but not a non-body variant)."""
    if any(kw in title for kw in EXCLUDED_TITLE_KEYWORDS):
        return False
    return any(kw in title for kw in PERIODIC_REPORT_KEYWORDS)


def collect_reports(
    company: CompanyInfo,
    allowed_kinds: set[str],
    categories: list[str],
    *,
    session: requests.Session,
    timeout: float,
    min_interval: float,
    max_interval: float,
    max_query_workers: int = 3,
) -> list[Report]:
    """Collect reports across multiple cninfo categories (concurrent query)."""
    reports: list[Report] = []
    seen: set[tuple[int, str, bool, str]] = set()

    # Map category back to the primary kind we expect from it.
    category_to_kind: dict[str, str] = {
        cat: kind for kind, cat in KIND_TO_CATEGORY.items()
    }

    # Concurrent query across categories to save time; keep results per category.
    category_items: dict[str, list[dict]] = {}
    if len(categories) <= 1:
        category_items[categories[0]] = _fetch_category_items(
            categories[0], company, timeout, min_interval, max_interval
        ) if categories else []
    else:
        with ThreadPoolExecutor(max_workers=max_query_workers) as executor:
            futures = {
                executor.submit(
                    _fetch_category_items,
                    cat,
                    company,
                    timeout,
                    min_interval,
                    max_interval,
                ): cat
                for cat in categories
            }
            for future in as_completed(futures):
                cat = futures[future]
                try:
                    category_items[cat] = future.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"warn  category query failed {cat}: {exc}", file=sys.stderr)

    # Match reports per category and detect likely missed periodic reports.
    for cat, items in category_items.items():
        cat_matched = 0
        unmatched_titles: list[str] = []
        for item in items:
            if item.get("secCode") != company.code:
                continue
            report = parse_report(item, allowed_kinds)
            if report is None:
                title = clean_title(item.get("announcementTitle") or "")
                if _looks_like_periodic_report(title):
                    unmatched_titles.append(title)
                continue

            cat_matched += 1
            key = (report.year, report.kind, report.is_revision, report.ann_id)
            if key in seen:
                continue
            seen.add(key)
            reports.append(report)

        expected_kind = category_to_kind.get(cat)
        if expected_kind and expected_kind in allowed_kinds:
            if items and cat_matched == 0:
                print(
                    f"warn  category {cat}: {len(items)} items returned but 0 matched",
                    file=sys.stderr,
                )
            if unmatched_titles:
                print(
                    f"warn  category {cat}: {len(unmatched_titles)} items look like periodic reports but were not matched",
                    file=sys.stderr,
                )
                for title in unmatched_titles[:5]:
                    print(f"  unmatched: {title}", file=sys.stderr)

    def _body_preference(title: str) -> int:
        """Prefer full text over body-only reports."""
        if "全文" in title:
            return 0
        if "正文" in title:
            return 2
        return 1

    # Sort: newest year first, then kind order (annual > q3 > h1 > q1), revision last,
    # full-text before body-only so deduplication keeps the fuller document.
    kind_order = {"annual": 0, "q3": 1, "h1": 2, "q1": 3}
    reports = sorted(
        reports,
        key=lambda r: (
            -r.year,
            kind_order.get(r.kind, 99),
            r.is_revision,
            _body_preference(r.title),
            r.ann_date,
            r.ann_id,
        ),
    )

    # Deduplicate by (year, kind, is_revision), keeping the first (full text preferred).
    deduped: list[Report] = []
    seen_periodic: set[tuple[int, str, bool]] = set()
    for report in reports:
        key = (report.year, report.kind, report.is_revision)
        if key in seen_periodic:
            continue
        seen_periodic.add(key)
        deduped.append(report)
    return deduped


def safe_path_component(value: str) -> str:
    cleaned = SAFE_FILENAME_CHARS_RE.sub("_", value).strip()
    return cleaned or "unknown"


def target_dir_for(company: CompanyInfo, kind: str, company_dir_override=None) -> Path:
    if company_dir_override is not None:
        base = Path(company_dir_override)
    else:
        base = BASE_DIR / "companies" / f"{safe_path_component(company.name)}_{company.code}"
    sub = "annuals" if kind == "annual" else "quarterlyreports"
    return base / sub


def markdown_frontmatter(data: dict) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, str):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def render_markdown(
    *,
    company: CompanyInfo,
    report: Report,
    pdf_path: Path,
    md_path: Path,
    force: bool,
) -> bool:
    if md_path.exists() and not force:
        print(f"skip  md {report.year} {report.kind} -> {md_path}")
        return False

    try:
        from cninfo.parser import parse_pdf_bytes
    except ModuleNotFoundError as exc:
        if exc.name == "fitz":
            raise RuntimeError(
                "PyMuPDF is required to generate Markdown. "
                "Install dependencies with: python -m pip install -r requirements.txt"
            ) from exc
        raise

    parsed = parse_pdf_bytes(pdf_path.read_bytes())
    frontmatter = markdown_frontmatter(
        {
            "ann_id": report.ann_id,
            "ticker": company.ticker,
            "sec_code": company.code,
            "sec_name": company.name,
            "year": report.year,
            "kind": report.kind,
            "ann_date": report.ann_date,
            "title": report.title,
            "revision": report.is_revision,
            "source": report.pdf_url,
            "pdf_path": pdf_path.name,
            "adjunct_size_kb": report.adjunct_size_kb,
            "total_pages": parsed.total_pages,
            "extracted_pages": parsed.extracted_pages,
            "text_chars": parsed.text_chars,
        }
    )
    md_path.write_text(f"{frontmatter}\n\n# {report.title}\n\n{parsed.text}", encoding="utf-8")
    print(
        f"save  md {md_path} "
        f"(pages={parsed.total_pages}, extracted={parsed.extracted_pages}, chars={parsed.text_chars})"
    )
    return True


def _download_single_report(
    report: Report,
    company: CompanyInfo,
    target_dir: Path,
    *,
    timeout: float,
    generate_markdown: bool,
    force_markdown: bool,
    min_interval: float = 1.0,
    max_interval: float = 2.0,
) -> tuple[int, int, int, int]:
    """Download one report (PDF + optional Markdown) in a worker thread."""
    # Each worker gets its own session for thread safety
    worker_session = requests.Session()

    if report.year_subdir:
        report_dir = target_dir / report.year_subdir
        report_dir.mkdir(parents=True, exist_ok=True)
    else:
        report_dir = target_dir

    pdf_path = report_dir / report.filename
    md_path = report_dir / report.markdown_filename
    kind_label = {
        "annual": "年报",
        "q1": "一季报",
        "h1": "半年报",
        "q3": "三季报",
    }.get(report.kind, report.kind)

    downloaded = 0
    skipped_pdf = 0
    written_md = 0
    skipped_md = 0

    if pdf_path.exists():
        print(f"skip  pdf {report.year} {kind_label} {'修订版' if report.is_revision else '原始版'} -> {pdf_path}")
        skipped_pdf += 1
    else:
        print(f"down  pdf {report.year} {kind_label} {'修订版' if report.is_revision else '原始版'} {report.title}")
        sleep_between_requests(min_interval, max_interval)
        data = fetch_pdf_bytes(report.pdf_url, timeout=timeout, session=worker_session)
        pdf_path.write_bytes(data)
        downloaded += 1
        print(f"save  pdf {pdf_path}")

    # Markdown 抽取只对年报有意义：reconciler / financial_expense 只读年报 md，
    # 季报 md 零消费者，PyMuPDF 抽取是纯 CPU 浪费。季报只保留 PDF 下载。
    if generate_markdown and report.kind == "annual":
        if render_markdown(
            company=company,
            report=report,
            pdf_path=pdf_path,
            md_path=md_path,
            force=force_markdown,
        ):
            written_md += 1
        else:
            skipped_md += 1

    return downloaded, skipped_pdf, written_md, skipped_md


def download_reports(
    company: CompanyInfo,
    reports: list[Report],
    target_dir: Path,
    *,
    session: requests.Session,
    timeout: float,
    min_interval: float,
    max_interval: float,
    generate_markdown: bool,
    force_markdown: bool,
    max_workers: int = 6,
    quarterly_target_dir: Path | None = None,
) -> tuple[int, int, int, int]:
    """Download reports concurrently with controlled parallelism.

    ``reports`` may mix annual and quarterly kinds; annuals land in
    ``target_dir`` (annuals/), quarterlies in ``quarterly_target_dir``
    (quarterlyreports/) when provided, else in ``target_dir``. A single
    ThreadPoolExecutor drains the whole list so annual and quarterly
    downloads share one pool instead of two serial passes.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    if quarterly_target_dir is not None:
        quarterly_target_dir.mkdir(parents=True, exist_ok=True)

    if not reports:
        return 0, 0, 0, 0

    total_downloaded = 0
    total_skipped_pdf = 0
    total_written_md = 0
    total_skipped_md = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for report in reports:
            dir_for_report = (
                target_dir
                if report.kind == "annual" or quarterly_target_dir is None
                else quarterly_target_dir
            )
            futures[executor.submit(
                _download_single_report,
                report,
                company,
                dir_for_report,
                timeout=timeout,
                generate_markdown=generate_markdown,
                force_markdown=force_markdown,
                min_interval=min_interval,
                max_interval=max_interval,
            )] = report

        for future in as_completed(futures):
            report = futures[future]
            try:
                d, s, w, m = future.result()
                total_downloaded += d
                total_skipped_pdf += s
                total_written_md += w
                total_skipped_md += m
            except Exception as exc:  # noqa: BLE001
                kind_label = {
                    "annual": "年报",
                    "q1": "一季报",
                    "h1": "半年报",
                    "q3": "三季报",
                }.get(report.kind, report.kind)
                print(
                    f"err   {report.year} {kind_label} download failed: {exc}",
                    file=sys.stderr,
                )
                total_skipped_pdf += 1

    return total_downloaded, total_skipped_pdf, total_written_md, total_skipped_md


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 000333.SZ")
    parser.add_argument(
        "--company-dir",
        default=None,
        help="explicit company directory (e.g. the data_fetcher-created dir holding data.db). "
        "When set, annuals/quarterlyreports land here instead of being re-derived from the "
        "cninfo company name — avoids dir splits when cninfo and TuShare disagree on the name "
        "(e.g. half-width 万科A vs full-width 万科Ａ).",
    )
    parser.add_argument("--min-interval", type=float, default=1.0, help="minimum seconds between requests")
    parser.add_argument("--max-interval", type=float, default=2.0, help="maximum seconds between requests")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    parser.add_argument("--list-only", action="store_true", help="only list matched reports")
    parser.add_argument(
        "--min-year",
        type=int,
        default=DEFAULT_MIN_REPORT_YEAR,
        help=f"only download reports from this year onward (default: {DEFAULT_MIN_REPORT_YEAR}, "
        "aligned with clean.RECONCILE_MIN_YEAR; pre-2010 reports are sparse and never reconciled)",
    )
    parser.add_argument("--no-markdown", action="store_true", help="download PDFs only, without Markdown extraction")
    parser.add_argument("--force-markdown", action="store_true", help="regenerate Markdown even when .md exists")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=6,
        help="max concurrent download workers (default: 6)",
    )

    report_group = parser.add_mutually_exclusive_group()
    report_group.add_argument(
        "--quarterly",
        action="store_true",
        help="download quarterly reports (Q1/H1/Q3) instead of annuals",
    )
    report_group.add_argument(
        "--all-reports",
        action="store_true",
        help="download both annual and quarterly reports",
    )
    return parser


def resolve_kinds_and_categories(args: argparse.Namespace) -> tuple[set[str], list[str]]:
    if args.all_reports:
        return set(KIND_TO_CATEGORY.keys()), ALL_CATEGORIES
    if args.quarterly:
        return {"q1", "h1", "q3"}, QUARTERLY_CATEGORIES
    return {"annual"}, ANNUAL_CATEGORIES


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_interval < 0 or args.max_interval < args.min_interval:
        raise ValueError("--max-interval must be >= --min-interval >= 0")

    code, plate = parse_ticker(args.ticker)
    session = requests.Session()

    company = fetch_company_info(code, plate, session=session, timeout=args.timeout)
    sleep_between_requests(args.min_interval, args.max_interval)

    allowed_kinds, categories = resolve_kinds_and_categories(args)
    reports = collect_reports(
        company,
        allowed_kinds=allowed_kinds,
        categories=categories,
        session=session,
        timeout=args.timeout,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
    )

    # 2010 闸门：丢弃 min-year 之前的报告，不下载、不抽取 Markdown。
    min_year = args.min_year
    before = len(reports)
    reports = [r for r in reports if r.year >= min_year]
    dropped = before - len(reports)
    if dropped:
        print(f"filter: dropped {dropped} report(s) before {min_year} (2010 闸门)")

    # Determine target dir based on primary kind
    company_dir_override = args.company_dir
    if args.quarterly:
        target_dir = target_dir_for(company, kind="quarterly", company_dir_override=company_dir_override)
    elif args.all_reports:
        # Annuals go to annuals/, quarterlies go to quarterlyreports/
        # We'll handle this inside the download loop by filtering reports
        target_dir = target_dir_for(company, kind="annual", company_dir_override=company_dir_override)
    else:
        target_dir = target_dir_for(company, kind="annual", company_dir_override=company_dir_override)

    print(f"company: {company.name} {company.ticker} orgId={company.org_id}")
    print(f"target : {target_dir.parent} (annuals + quarterlyreports)")
    print(f"matched: {len(reports)} report(s)")
    for report in reports:
        kind_label = {
            "annual": "年报",
            "q1": "一季报",
            "h1": "半年报",
            "q3": "三季报",
        }.get(report.kind, report.kind)
        flag = "修订版" if report.is_revision else "原始版"
        print(f"  {report.year} {kind_label} {flag} {report.ann_date} {report.ann_id} {report.title}")

    if args.list_only:
        return 0

    if args.all_reports:
        # Annuals go to annuals/, quarterlies go to quarterlyreports/.
        # Both share one download pool (single ThreadPoolExecutor) so annual
        # and quarterly PDFs download concurrently instead of two serial passes.
        annual_dir = target_dir_for(company, kind="annual", company_dir_override=company_dir_override)
        quarterly_dir = target_dir_for(company, kind="quarterly", company_dir_override=company_dir_override)

        total_downloaded, total_skipped_pdf, total_written_md, total_skipped_md = download_reports(
            company,
            reports,
            annual_dir,
            session=session,
            timeout=args.timeout,
            min_interval=args.min_interval,
            max_interval=args.max_interval,
            generate_markdown=not args.no_markdown,
            force_markdown=args.force_markdown,
            max_workers=args.max_workers,
            quarterly_target_dir=quarterly_dir,
        )

        print(
            "done: "
            f"pdf_downloaded={total_downloaded}, pdf_skipped={total_skipped_pdf}, "
            f"md_written={total_written_md}, md_skipped={total_skipped_md}, total={len(reports)}"
        )
    else:
        target_dir = target_dir_for(company, kind="quarterly" if args.quarterly else "annual", company_dir_override=company_dir_override)
        downloaded, skipped_pdf, written_md, skipped_md = download_reports(
            company,
            reports,
            target_dir,
            session=session,
            timeout=args.timeout,
            min_interval=args.min_interval,
            max_interval=args.max_interval,
            generate_markdown=not args.no_markdown,
            force_markdown=args.force_markdown,
            max_workers=args.max_workers,
        )
        print(
            "done: "
            f"pdf_downloaded={downloaded}, pdf_skipped={skipped_pdf}, "
            f"md_written={written_md}, md_skipped={skipped_md}, total={len(reports)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
