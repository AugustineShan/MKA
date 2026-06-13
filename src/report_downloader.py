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
    KIND_TO_TITLE_TAIL,
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
EXCLUDED_TITLE_KEYWORDS: tuple[str, ...] = (
    "摘要",
    "审计报告",
    "内部控制",
    "提示性公告",
    "鉴证报告",
    "披露",
    "更新",
    "取消",
    "英文",
)


def parse_report(item: dict, allowed_kinds: set[str]) -> Report | None:
    raw_title = clean_title(item.get("announcementTitle"))
    if any(kw in raw_title for kw in EXCLUDED_TITLE_KEYWORDS):
        return None

    for kind in allowed_kinds:
        tail = KIND_TO_TITLE_TAIL.get(kind)
        if not tail:
            continue

        pattern = rf"(?P<year>\d{{4}}){re.escape(tail)}(?P<body_suffix>全文|正文)?(?P<revision>（修订版）|\(修订版\))?$"
        match = re.search(pattern, raw_title)
        if match:
            adjunct_url = item.get("adjunctUrl") or ""
            ann_id = str(item.get("announcementId") or "")
            if not adjunct_url or not ann_id:
                return None

            ann_time = int(item.get("announcementTime") or 0)
            return Report(
                year=int(match.group("year")),
                kind=kind,
                is_revision=bool(match.group("revision")),
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
    periodic_tails = ("年年度报告", "年第一季度报告", "年半年度报告", "年第三季度报告")
    return any(tail in title for tail in periodic_tails)


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


def target_dir_for(company: CompanyInfo, kind: str) -> Path:
    company_dir = f"{safe_path_component(company.name)}_{company.code}"
    if kind == "annual":
        return BASE_DIR / "companies" / company_dir / "annuals"
    return BASE_DIR / "companies" / company_dir / "quarterlyreports"


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

    if generate_markdown:
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
    max_workers: int = 4,
) -> tuple[int, int, int, int]:
    """Download reports concurrently with controlled parallelism."""
    target_dir.mkdir(parents=True, exist_ok=True)

    if not reports:
        return 0, 0, 0, 0

    total_downloaded = 0
    total_skipped_pdf = 0
    total_written_md = 0
    total_skipped_md = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _download_single_report,
                report,
                company,
                target_dir,
                timeout=timeout,
                generate_markdown=generate_markdown,
                force_markdown=force_markdown,
                min_interval=min_interval,
                max_interval=max_interval,
            ): report
            for report in reports
        }

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
    parser.add_argument("--min-interval", type=float, default=1.0, help="minimum seconds between requests")
    parser.add_argument("--max-interval", type=float, default=2.0, help="maximum seconds between requests")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    parser.add_argument("--list-only", action="store_true", help="only list matched reports")
    parser.add_argument("--no-markdown", action="store_true", help="download PDFs only, without Markdown extraction")
    parser.add_argument("--force-markdown", action="store_true", help="regenerate Markdown even when .md exists")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="max concurrent download workers (default: 4)",
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

    # Determine target dir based on primary kind
    if args.quarterly:
        target_dir = target_dir_for(company, kind="quarterly")
    elif args.all_reports:
        # Annuals go to annuals/, quarterlies go to quarterlyreports/
        # We'll handle this inside the download loop by filtering reports
        target_dir = target_dir_for(company, kind="annual")
    else:
        target_dir = target_dir_for(company, kind="annual")

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
        # Download annuals and quarterlies to their respective directories
        annual_reports = [r for r in reports if r.kind == "annual"]
        quarterly_reports = [r for r in reports if r.kind != "annual"]

        annual_dir = target_dir_for(company, kind="annual")
        quarterly_dir = target_dir_for(company, kind="quarterly")

        total_downloaded = 0
        total_skipped_pdf = 0
        total_written_md = 0
        total_skipped_md = 0

        if annual_reports:
            d, s, w, m = download_reports(
                company,
                annual_reports,
                annual_dir,
                session=session,
                timeout=args.timeout,
                min_interval=args.min_interval,
                max_interval=args.max_interval,
                generate_markdown=not args.no_markdown,
                force_markdown=args.force_markdown,
                max_workers=args.max_workers,
            )
            total_downloaded += d
            total_skipped_pdf += s
            total_written_md += w
            total_skipped_md += m

        if quarterly_reports:
            d, s, w, m = download_reports(
                company,
                quarterly_reports,
                quarterly_dir,
                session=session,
                timeout=args.timeout,
                min_interval=args.min_interval,
                max_interval=args.max_interval,
                generate_markdown=not args.no_markdown,
                force_markdown=args.force_markdown,
                max_workers=args.max_workers,
            )
            total_downloaded += d
            total_skipped_pdf += s
            total_written_md += w
            total_skipped_md += m

        print(
            "done: "
            f"pdf_downloaded={total_downloaded}, pdf_skipped={total_skipped_pdf}, "
            f"md_written={total_written_md}, md_skipped={total_skipped_md}, total={len(reports)}"
        )
    else:
        target_dir = target_dir_for(company, kind="quarterly" if args.quarterly else "annual")
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
