"""Download all cninfo annual report PDFs for one A-share company.

Usage:
    python report_downloader.py --ticker 000333.SZ

This script vendors and reuses rollysys/use_cninfo under vendor/use_cninfo.
It intentionally stays thin: cninfo query details, title cleanup, and PDF
fetching come from the vendored cninfo package; this file handles ticker
parsing, annual-report filtering, naming, and project-local output layout.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import requests


BASE_DIR = Path(__file__).resolve().parent
VENDORED_CNINFO_SRC = BASE_DIR / "vendor" / "use_cninfo" / "src"
if str(VENDORED_CNINFO_SRC) not in sys.path:
    sys.path.insert(0, str(VENDORED_CNINFO_SRC))

from cninfo.api import (  # noqa: E402
    CATEGORY_NDBG,
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
ANNUAL_TITLE_RE = re.compile(
    r"(?P<year>\d{4})年年度报告(?P<revision>（修订版）|\(修订版\))?$"
)
SAFE_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

PLATE_BY_SUFFIX = {"SZ": "sz", "SH": "sh", "BJ": "bj"}
COLUMN_BY_PLATE = {"sz": "szse", "bj": "szse", "sh": "sse"}
PDF_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}


@dataclass(frozen=True)
class CompanyInfo:
    code: str
    ticker: str
    plate: str
    org_id: str
    name: str


@dataclass(frozen=True)
class AnnualReport:
    year: int
    is_revision: bool
    ann_date: str
    ann_id: str
    title: str
    pdf_url: str
    adjunct_size_kb: int | None

    @property
    def filename(self) -> str:
        if self.is_revision:
            return f"{self.year}_年度报告_修订版.pdf"
        return f"{self.year}_年度报告.pdf"

    @property
    def markdown_filename(self) -> str:
        return Path(self.filename).with_suffix(".md").name


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


def iter_company_annual_category(
    company: CompanyInfo,
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
            category=CATEGORY_NDBG,
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


def parse_annual_report(item: dict) -> AnnualReport | None:
    raw_title = clean_title(item.get("announcementTitle"))
    if "摘要" in raw_title:
        return None

    match = ANNUAL_TITLE_RE.search(raw_title)
    if not match:
        return None

    adjunct_url = item.get("adjunctUrl") or ""
    ann_id = str(item.get("announcementId") or "")
    if not adjunct_url or not ann_id:
        return None

    ann_time = int(item.get("announcementTime") or 0)
    return AnnualReport(
        year=int(match.group("year")),
        is_revision=bool(match.group("revision")),
        ann_date=epoch_ms_to_ann_date(ann_time) if ann_time else "",
        ann_id=ann_id,
        title=raw_title,
        pdf_url=adjunct_to_url(adjunct_url),
        adjunct_size_kb=item.get("adjunctSize"),
    )


def collect_annual_reports(
    company: CompanyInfo,
    *,
    session: requests.Session,
    timeout: float,
    min_interval: float,
    max_interval: float,
) -> list[AnnualReport]:
    reports: list[AnnualReport] = []
    seen: set[tuple[int, bool, str]] = set()

    for item in iter_company_annual_category(
        company,
        session=session,
        timeout=timeout,
        min_interval=min_interval,
        max_interval=max_interval,
    ):
        if item.get("secCode") != company.code:
            continue
        report = parse_annual_report(item)
        if report is None:
            continue

        key = (report.year, report.is_revision, report.ann_id)
        if key in seen:
            continue
        seen.add(key)
        reports.append(report)

    return sorted(reports, key=lambda r: (r.year, r.is_revision, r.ann_date, r.ann_id), reverse=True)


def safe_path_component(value: str) -> str:
    cleaned = SAFE_FILENAME_CHARS_RE.sub("_", value).strip()
    return cleaned or "unknown"


def target_dir_for(company: CompanyInfo) -> Path:
    company_dir = f"{safe_path_component(company.name)}_{company.code}"
    return BASE_DIR / "companies" / company_dir / "annuals"


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
    report: AnnualReport,
    pdf_path: Path,
    md_path: Path,
    force: bool,
) -> bool:
    if md_path.exists() and not force:
        print(f"skip  md {report.year} -> {md_path}")
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


def download_reports(
    company: CompanyInfo,
    reports: list[AnnualReport],
    target_dir: Path,
    *,
    session: requests.Session,
    timeout: float,
    min_interval: float,
    max_interval: float,
    generate_markdown: bool,
    force_markdown: bool,
) -> tuple[int, int, int, int]:
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped_pdf = 0
    written_md = 0
    skipped_md = 0
    for index, report in enumerate(reports, start=1):
        pdf_path = target_dir / report.filename
        md_path = target_dir / report.markdown_filename
        if pdf_path.exists():
            print(f"skip  pdf {report.year} {'修订版' if report.is_revision else '原始版'} -> {pdf_path}")
            skipped_pdf += 1
        else:
            print(f"down  pdf {report.year} {'修订版' if report.is_revision else '原始版'} {report.title}")
            data = fetch_pdf_bytes(report.pdf_url, timeout=timeout, session=session)
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

        if index < len(reports):
            sleep_between_requests(min_interval, max_interval)

    return downloaded, skipped_pdf, written_md, skipped_md


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 000333.SZ")
    parser.add_argument("--min-interval", type=float, default=1.0, help="minimum seconds between requests")
    parser.add_argument("--max-interval", type=float, default=2.0, help="maximum seconds between requests")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    parser.add_argument("--list-only", action="store_true", help="only list matched annual reports")
    parser.add_argument("--no-markdown", action="store_true", help="download PDFs only, without Markdown extraction")
    parser.add_argument("--force-markdown", action="store_true", help="regenerate Markdown even when .md exists")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_interval < 0 or args.max_interval < args.min_interval:
        raise ValueError("--max-interval must be >= --min-interval >= 0")

    code, plate = parse_ticker(args.ticker)
    session = requests.Session()

    company = fetch_company_info(code, plate, session=session, timeout=args.timeout)
    sleep_between_requests(args.min_interval, args.max_interval)

    reports = collect_annual_reports(
        company,
        session=session,
        timeout=args.timeout,
        min_interval=args.min_interval,
        max_interval=args.max_interval,
    )
    target_dir = target_dir_for(company)

    print(f"company: {company.name} {company.ticker} orgId={company.org_id}")
    print(f"target : {target_dir}")
    print(f"matched: {len(reports)} annual report PDF(s)")
    for report in reports:
        flag = "修订版" if report.is_revision else "原始版"
        print(f"  {report.year} {flag} {report.ann_date} {report.ann_id} {report.title}")

    if args.list_only:
        return 0

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
    )
    print(
        "done: "
        f"pdf_downloaded={downloaded}, pdf_skipped={skipped_pdf}, "
        f"md_written={written_md}, md_skipped={skipped_md}, total={len(reports)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
