"""Canonical company workspace paths.

The company root is an analyst-facing fundamental workspace. Runtime artifacts
for the modelling agent live under ``Agent/`` so they do not compete with
research materials such as announcements, notes, reports, and active inputs.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"

AGENT_DIR = "Agent"
AGENT_LOGS_DIR = "Logs"
OFFICIAL_BREAKDOWNS_DIR = "OfficialBreakdowns"
ANNOUNCEMENTS_DIR = "公告"
ANNUAL_REPORTS_DIR = "年报"
QUARTERLY_REPORTS_DIR = "季报"
TEMP_ANNOUNCEMENTS_DIR = "临时公告"
RESEARCH_REPORTS_DIR = "研报"
MEETING_NOTES_DIR = "纪要"
COLLECTION_DIR = "收集"
IMPORTANT_FILES_DIR = "重要文件"
ACTIVE_VORE_DIR = "active_vore"
WEBCLAUDE_DIR = "WEBCLAUDE"

TICKER_RE = re.compile(r"^\d{6}\.(SZ|SH|BJ)$")


def code_from_ticker(ticker: str) -> str:
    text = ticker.strip().upper()
    if TICKER_RE.match(text):
        return text.split(".")[0]
    if re.fullmatch(r"\d{6}", text):
        return text
    return text.split(".")[0]


def find_company_dir(ticker: str, companies_dir: Path = COMPANIES_DIR) -> Path:
    code = code_from_ticker(ticker)
    candidates = sorted(companies_dir.glob(f"*_{code}"))
    if not candidates:
        raise FileNotFoundError(f"No company directory matching companies/*_{code}")
    if len(candidates) > 1:
        raise RuntimeError(f"Multiple company directories match {code}: {candidates}")
    return candidates[0]


def company_dir_from_agent_path(path: str | Path) -> Path:
    path = Path(path).resolve()
    if path.parent.name == AGENT_DIR:
        return path.parent.parent
    return path.parent


def company_dir_from_db_path(db_path: str | Path) -> Path:
    return company_dir_from_agent_path(db_path)


def agent_dir(company_dir: Path) -> Path:
    return company_dir / AGENT_DIR


def agent_logs_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / AGENT_LOGS_DIR


def official_breakdowns_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / OFFICIAL_BREAKDOWNS_DIR


def db_path(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "data.db"


def defaults_path(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "defaults.yaml"


def financial_expense_path(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "financial_expense.yaml"


def yaml1_glob_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir)


def latest_yaml1_path(company_dir: Path) -> Path:
    candidates = sorted(
        yaml1_glob_dir(company_dir).glob("yaml1*.yaml"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No yaml1*.yaml found under {yaml1_glob_dir(company_dir)}")
    return candidates[0]


def forecast_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "forecast"


def modelking_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / ".modelking"


def recon_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "recon"


def announcements_dir(company_dir: Path) -> Path:
    return company_dir / ANNOUNCEMENTS_DIR


def annual_reports_dir(company_dir: Path) -> Path:
    return announcements_dir(company_dir) / ANNUAL_REPORTS_DIR


def quarterly_reports_dir(company_dir: Path) -> Path:
    return announcements_dir(company_dir) / QUARTERLY_REPORTS_DIR


def temp_announcements_dir(company_dir: Path) -> Path:
    return announcements_dir(company_dir) / TEMP_ANNOUNCEMENTS_DIR


def research_reports_dir(company_dir: Path) -> Path:
    return company_dir / RESEARCH_REPORTS_DIR


def meeting_notes_dir(company_dir: Path) -> Path:
    return company_dir / MEETING_NOTES_DIR


def collection_dir(company_dir: Path) -> Path:
    return company_dir / COLLECTION_DIR


def important_files_dir(company_dir: Path) -> Path:
    return company_dir / IMPORTANT_FILES_DIR


def active_vore_dir(company_dir: Path) -> Path:
    return company_dir / ACTIVE_VORE_DIR


def webclaude_dir(company_dir: Path) -> Path:
    return company_dir / WEBCLAUDE_DIR


def extraction_dir(company_dir: Path) -> Path:
    return collection_dir(company_dir) / "年报萃取"


def ensure_workspace_layout(company_dir: Path) -> None:
    for path in (
        agent_dir(company_dir),
        agent_logs_dir(company_dir),
        official_breakdowns_dir(company_dir),
        recon_dir(company_dir),
        annual_reports_dir(company_dir),
        quarterly_reports_dir(company_dir),
        temp_announcements_dir(company_dir),
        research_reports_dir(company_dir),
        meeting_notes_dir(company_dir),
        collection_dir(company_dir),
        important_files_dir(company_dir),
        active_vore_dir(company_dir),
        webclaude_dir(company_dir),
    ):
        path.mkdir(parents=True, exist_ok=True)


def find_db_path(ticker: str, companies_dir: Path = COMPANIES_DIR) -> Path:
    company_dir = find_company_dir(ticker, companies_dir)
    path = db_path(company_dir)
    if not path.exists():
        raise FileNotFoundError(f"No Agent/data.db found for {ticker} under {company_dir}")
    return path
