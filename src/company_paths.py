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
INTERNAL_REPORTS_DIR = "内部报告"
RATING_REPORTS_DIR = "评级报告"
TRACKING_REPORTS_DIR = "跟踪报告"
DEEP_REPORTS_DIR = "深度报告"
OTHER_MATERIALS_DIR = "其他材料"
ACTIVE_VORE_DIR = "Skills素材包"
KA_MODEL_SUBDIR = "LOAD外部EXCEL模型理解器（一次最多一个）"
BRKD_MATERIAL_SUBDIR = "BRKD业务理解器（研报和纪要放在这里）"
TOP_WEIGHT_MATERIAL_SUBDIR = "最高权重材料-放Agent最应对齐的材料"
ADJ_INCREMENT_SUBDIR = "ADJ增量信息（用来改模型的边际信息）"
PJBG_RATING_REPORT_SUBDIR = "PJBG评级报告素材区"
KA_REFERENCE_SUBDIR = "KA（ALPHAPAI拆出来的东西放在这里）"
BRKD_MARKDOWN_STORE_SUBDIR = "markdown存储区"
TOP_WEIGHT_MARKDOWN_STORE_SUBDIR = "markdown存储区"
ADJ_MARKDOWN_STORE_SUBDIR = "markdown存储区"
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


def da_schedule_path(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "da_schedule.yaml"


def da_history_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / "DAhistory"


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


def internal_reports_dir(company_dir: Path) -> Path:
    return company_dir / INTERNAL_REPORTS_DIR


def rating_reports_dir(company_dir: Path) -> Path:
    return internal_reports_dir(company_dir) / RATING_REPORTS_DIR


def tracking_reports_dir(company_dir: Path) -> Path:
    return internal_reports_dir(company_dir) / TRACKING_REPORTS_DIR


def deep_reports_dir(company_dir: Path) -> Path:
    return internal_reports_dir(company_dir) / DEEP_REPORTS_DIR


def other_materials_dir(company_dir: Path) -> Path:
    return internal_reports_dir(company_dir) / OTHER_MATERIALS_DIR


def active_vore_dir(company_dir: Path) -> Path:
    return company_dir / ACTIVE_VORE_DIR


def ka_model_dir(company_dir: Path) -> Path:
    """历史名称：当前指向 LOAD 外部 Excel 模型素材文件夹。"""
    return active_vore_dir(company_dir) / KA_MODEL_SUBDIR


def brkd_material_dir(company_dir: Path) -> Path:
    """/brkd 读研报/纪要的子文件夹。"""
    return active_vore_dir(company_dir) / BRKD_MATERIAL_SUBDIR


def brkd_markdown_store_dir(company_dir: Path) -> Path:
    """/brkd deterministic prepare 输出的 markdown 存储区。"""
    return brkd_material_dir(company_dir) / BRKD_MARKDOWN_STORE_SUBDIR


def skills_materials_dir(company_dir: Path) -> Path:
    return active_vore_dir(company_dir)


def load_model_dir(company_dir: Path) -> Path:
    """/load 读取外部 Excel 模型的唯一素材文件夹。"""
    return ka_model_dir(company_dir)


def top_weight_material_dir(company_dir: Path) -> Path:
    """最高权重材料子文件夹（Agent 最应该对齐的材料放这里）。/ka 经 ka_prepare 读取并 markdown 化。"""
    return active_vore_dir(company_dir) / TOP_WEIGHT_MATERIAL_SUBDIR


def adj_increment_dir(company_dir: Path) -> Path:
    """ADJ增量信息子文件夹（用来改模型的边际信息放这里）。/adj incremental 经 adj_prepare 读取并 markdown 化。"""
    return active_vore_dir(company_dir) / ADJ_INCREMENT_SUBDIR


def adj_markdown_store_dir(company_dir: Path) -> Path:
    """/adj deterministic prepare 输出的 markdown 存储区。"""
    return adj_increment_dir(company_dir) / ADJ_MARKDOWN_STORE_SUBDIR


def pjbg_rating_report_dir(company_dir: Path) -> Path:
    """PJBG 评级报告素材区（评级报告素材放这里）。当前无消费方，仅建目录占位。"""
    return active_vore_dir(company_dir) / PJBG_RATING_REPORT_SUBDIR


def ka_reference_dir(company_dir: Path) -> Path:
    """KA 参考稿区：brkd/load/alphapai 产出的 核心假设参考*.md 统一放这里，/ka 到这里找。"""
    return active_vore_dir(company_dir) / KA_REFERENCE_SUBDIR


def top_weight_markdown_store_dir(company_dir: Path) -> Path:
    """/ka deterministic prepare 输出的最高权重材料 markdown 存储区。"""
    return top_weight_material_dir(company_dir) / TOP_WEIGHT_MARKDOWN_STORE_SUBDIR


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
        internal_reports_dir(company_dir),
        rating_reports_dir(company_dir),
        tracking_reports_dir(company_dir),
        deep_reports_dir(company_dir),
        other_materials_dir(company_dir),
        active_vore_dir(company_dir),
        ka_model_dir(company_dir),
        brkd_material_dir(company_dir),
        brkd_markdown_store_dir(company_dir),
        top_weight_material_dir(company_dir),
        top_weight_markdown_store_dir(company_dir),
        adj_increment_dir(company_dir),
        adj_markdown_store_dir(company_dir),
        pjbg_rating_report_dir(company_dir),
        ka_reference_dir(company_dir),
        webclaude_dir(company_dir),
    ):
        path.mkdir(parents=True, exist_ok=True)


def find_db_path(ticker: str, companies_dir: Path = COMPANIES_DIR) -> Path:
    company_dir = find_company_dir(ticker, companies_dir)
    path = db_path(company_dir)
    if not path.exists():
        raise FileNotFoundError(f"No Agent/data.db found for {ticker} under {company_dir}")
    return path
