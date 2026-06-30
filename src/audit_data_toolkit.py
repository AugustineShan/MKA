"""Data access helpers for the /audit financial health radar.

This module is intentionally a thin, read-mostly boundary.  Layer 1 rules read
clean historical tables from each company's Agent/data.db; evidence collection
can add local annual-report snippets and optional TuShare auxiliary data.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.annual_report_utils import annual_markdown_path, compact_window, read_md_lines
from src.company_paths import COMPANIES_DIR, agent_dir, db_path, find_company_dir, recon_dir
from src.data_fetcher import create_tushare_client


ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR_NAME = "audit"
TUSHARE_REFERENCE_DIR = ROOT / "TushareOfficialAPIMD" / "fulltushare"

SECTION_KEYWORDS: dict[str, list[str]] = {
    "revenue_recognition": ["收入确认", "控制权转移", "商品控制权", "会计政策"],
    "receivables_aging": ["账龄分析", "应收账款", "坏账准备", "坏账计提"],
    "related_party": ["关联方", "关联交易", "关联方应收", "关联方往来"],
    "audit_opinion": ["审计意见", "强调事项", "保留意见", "持续经营"],
    "mda_risk": ["风险因素", "可能面临的风险", "经营风险", "市场风险"],
    "inventory_detail": ["存货", "库存商品", "在产品", "存货跌价"],
    "cip_detail": ["在建工程", "工程进度", "转固", "预算"],
    "goodwill_detail": ["商誉", "减值测试", "商誉减值"],
    "other_receivables": ["其他应收款", "往来款", "资金占用"],
    "pledge_guarantee": ["质押", "担保", "对外担保"],
}


@dataclass(frozen=True)
class CompanyHistory:
    ticker: str
    name: str
    company_dir: Path
    db_path: Path
    meta: dict[str, str]
    annual: list[dict[str, Any]]
    quarterly: list[dict[str, Any]]
    industry: str = "general"


def audit_dir(company_dir: Path) -> Path:
    return agent_dir(company_dir) / AUDIT_DIR_NAME


def resolve_coverage(coverage: str | Iterable[str], companies_dir: Path = COMPANIES_DIR) -> list[Path]:
    """Resolve all supported coverage inputs to company directories."""

    if isinstance(coverage, str):
        text = coverage.strip()
        if text.lower() == "all":
            return sorted(
                path.parent.parent
                for path in companies_dir.glob("*/Agent/data.db")
                if path.is_file()
            )
        candidate_path = Path(text)
        if candidate_path.exists() and candidate_path.is_file():
            items = [
                line.strip()
                for line in candidate_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        else:
            items = [part.strip() for part in re.split(r"[,，\s]+", text) if part.strip()]
    else:
        items = [str(item).strip() for item in coverage if str(item).strip()]

    resolved: list[Path] = []
    seen: set[Path] = set()
    for item in items:
        company_dir = _resolve_company_dir(item, companies_dir)
        if company_dir not in seen:
            resolved.append(company_dir)
            seen.add(company_dir)
    return resolved


def load_company_history(identifier: str | Path, companies_dir: Path = COMPANIES_DIR) -> CompanyHistory:
    """Load one company's clean annual and quarterly history from Agent/data.db."""

    company_dir = identifier if isinstance(identifier, Path) else _resolve_company_dir(identifier, companies_dir)
    database = db_path(company_dir)
    if not database.exists():
        raise FileNotFoundError(f"No Agent/data.db found under {company_dir}")

    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        meta = _load_meta(conn)
        annual = _load_clean_table(conn, "clean_annual")
        quarterly = _load_clean_table(conn, "clean_quarterly")

    ticker = meta.get("ticker") or _ticker_from_company_dir(company_dir)
    name = meta.get("name") or company_dir.name.rsplit("_", 1)[0]
    return CompanyHistory(
        ticker=ticker,
        name=name,
        company_dir=company_dir,
        db_path=database,
        meta=meta,
        annual=annual,
        quarterly=quarterly,
        industry=infer_industry(name, company_dir.name),
    )


def annual_report_chunks(
    company_dir: Path,
    year: str,
    section: str,
    *,
    max_windows: int = 3,
) -> list[dict[str, Any]]:
    """Return compact windows from a local annual-report Markdown file."""

    path = annual_markdown_path(company_dir, year)
    if path is None:
        return []
    keywords = SECTION_KEYWORDS.get(section, [section])
    lines = read_md_lines(path)
    windows: list[dict[str, Any]] = []
    used_centers: set[int] = set()
    for keyword in keywords:
        for idx, line in enumerate(lines):
            if keyword not in line or idx in used_centers:
                continue
            used_centers.add(idx)
            window = compact_window(lines, idx, before=30, after=90)
            windows.append(
                {
                    "section": section,
                    "keyword": keyword,
                    "path": str(path),
                    **window,
                }
            )
            if len(windows) >= max_windows:
                return windows
    return windows


def build_evidence_pack(
    history: CompanyHistory,
    flags: list[dict[str, Any]],
    *,
    include_tushare: bool = True,
    pro: Any | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Collect local and optional TuShare evidence for a company's flags."""

    target_sections = _sections_for_flags(flags)
    years = _years_for_flags(flags)
    snippets: list[dict[str, Any]] = []
    for year in years:
        for section in target_sections:
            snippets.extend(annual_report_chunks(history.company_dir, year, section))

    pack: dict[str, Any] = {
        "version": 1,
        "ticker": history.ticker,
        "company": history.name,
        "company_dir": str(history.company_dir),
        "tushare_reference_dir": str(TUSHARE_REFERENCE_DIR),
        "flags": flags,
        "local_sources": local_source_summary(history.company_dir),
        "annual_report_snippets": snippets,
        "layer2_playbook_reviews": build_layer2_playbook_reviews(history, flags),
        "tushare_auxiliary": {"status": "skipped"},
        "verdict": {
            "status": "not_run",
            "reason": "v1 evidence pack only; Layer 2 LLM auditor has not judged these signals.",
        },
    }

    if include_tushare:
        pack["tushare_auxiliary"] = fetch_tushare_auxiliary(
            history,
            pro=pro,
            use_cache=use_cache,
        )
    return pack


def fetch_tushare_auxiliary(
    history: CompanyHistory,
    *,
    pro: Any | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch optional Layer 2 evidence from TuShare, with a local cache."""

    cache_path = audit_dir(history.company_dir) / "tushare_aux_cache.json"
    if use_cache and cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    try:
        client = pro or create_tushare_client()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}

    latest_year = _latest_annual_year(history) or 2026
    start_date = f"{max(latest_year - 5, 1990)}0101"
    end_date = f"{latest_year}1231"
    endpoints = {
        "fina_indicator": lambda: client.fina_indicator(
            ts_code=history.ticker,
            start_date=start_date,
            end_date=end_date,
        ),
        "fina_audit": lambda: client.fina_audit(ts_code=history.ticker, start_date=start_date, end_date=end_date),
        "stk_managers": lambda: client.stk_managers(ts_code=history.ticker),
        "pledge_stat": lambda: client.query("pledge_stat", ts_code=history.ticker),
        "pledge_detail": lambda: client.query("pledge_detail", ts_code=history.ticker),
        "stk_holdertrade": lambda: client.query(
            "stk_holdertrade",
            ts_code=history.ticker,
            start_date=start_date,
            end_date=end_date,
        ),
        "block_trade": lambda: client.query(
            "block_trade",
            ts_code=history.ticker,
            start_date=start_date,
            end_date=end_date,
        ),
    }

    payload: dict[str, Any] = {
        "status": "ok",
        "date_range": {"start_date": start_date, "end_date": end_date},
        "endpoints": {},
    }
    for endpoint, call in endpoints.items():
        try:
            payload["endpoints"][endpoint] = _dataframe_summary(call())
        except Exception as exc:
            payload["endpoints"][endpoint] = {"status": "error", "error": str(exc)}

    payload = _json_safe(payload)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return payload


def local_source_summary(company_dir: Path) -> dict[str, Any]:
    annual_dir = company_dir / "公告" / "年报"
    recon = recon_dir(company_dir)
    agent = agent_dir(company_dir)
    annual_markdowns = sorted(annual_dir.glob("*.md")) if annual_dir.exists() else []
    recon_files = sorted(recon.glob("*.json")) if recon.exists() else []
    return {
        "annual_markdown_count": len(annual_markdowns),
        "annual_markdowns": [str(path) for path in annual_markdowns[-5:]],
        "recon_json_count": len(recon_files),
        "recon_latest": str(recon / "annual_report_reconciliation_latest.json")
        if (recon / "annual_report_reconciliation_latest.json").exists()
        else None,
        "da_facts_latest": str(recon / "da_facts_latest.json")
        if (recon / "da_facts_latest.json").exists()
        else None,
        "financial_expense": str(agent / "financial_expense.yaml")
        if (agent / "financial_expense.yaml").exists()
        else None,
    }


def infer_industry(name: str, folder_name: str = "") -> str:
    text = f"{name} {folder_name}"
    if any(token in text for token in ["伊利", "乳业", "乳制品", "奶"]):
        return "dairy"
    if any(token in text for token in ["茅台", "五粮液", "百润", "会稽山", "白酒", "黄酒", "预调酒"]):
        return "alcohol"
    if "啤酒" in text:
        return "beer"
    if any(token in text for token in ["绿联", "消费电子", "电子"]):
        return "consumer_electronics"
    if any(token in text for token in ["华凯", "赛维", "跨境"]):
        return "cross_border_ecommerce"
    if any(token in text for token in ["世纪华通", "游戏"]):
        return "gaming"
    return "general"


def build_layer2_playbook_reviews(
    history: CompanyHistory,
    flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build deterministic Layer 2 playbook inputs without making a verdict."""

    ids = {str(flag.get("rule_id")) for flag in flags}
    reviews: list[dict[str, Any]] = []
    if {"AR_REVENUE_RATIO_HIGH", "CFO_NI_DIVERGENCE"} & ids or (
        "BENEISH_M_SCORE" in ids and history.industry in {"consumer_electronics", "cross_border_ecommerce"}
    ):
        reviews.append(_growth_cash_consumption_review(history, flags))
    if "DEPOSIT_LOAN_MISMATCH" in ids:
        reviews.append(_cash_fabrication_review(history, flags))
    if {"CIP_NOT_TRANSFERRING", "GOODWILL_HIGH", "OTHER_RECEIVABLE_HIGH"} & ids:
        reviews.append(_asset_hole_review(history, flags))
    return reviews


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _growth_cash_consumption_review(
    history: CompanyHistory,
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    prev, cur = _latest_annual_pair(history)
    observations = _working_capital_observations(prev, cur)
    possible_growth_case = (
        history.industry in {"consumer_electronics", "cross_border_ecommerce"}
        and (observations.get("revenue_growth") or 0.0) > 0.25
        and (observations.get("ar_growth") or 0.0) > (observations.get("revenue_growth") or 0.0)
    )
    return {
        "playbook_id": "DSRI_HIGH_GROWTH_CASH_CONSUMPTION",
        "trigger_flags": _flag_summaries(flags, ["AR_REVENUE_RATIO_HIGH", "CFO_NI_DIVERGENCE", "BENEISH_M_SCORE"]),
        "industry_context": history.industry,
        "preliminary_frame": "possible_growth_cash_consumption" if possible_growth_case else "needs_targeted_revenue_collection_review",
        "observations": observations,
        "hypotheses": [
            {
                "id": "H1_aggressive_revenue_recognition",
                "question": "收入确认是否激进或有截止性问题？",
                "evidence_sections": ["revenue_recognition", "audit_opinion"],
                "dismiss_if": "收入确认政策稳定，审计关键事项未指出异常截止性问题。",
            },
            {
                "id": "H2_normal_growth_working_capital_drag",
                "question": "是否是高增长出口/平台客户账期导致的合理营运资本占用？",
                "evidence_sections": ["receivables_aging", "mda_risk"],
                "confirm_if": "收入高增长、应收账龄未恶化、客户为大型平台或账期稳定。",
            },
            {
                "id": "H3_collection_deterioration",
                "question": "回款能力是否恶化？",
                "evidence_sections": ["receivables_aging"],
                "confirm_if": "1年以上应收占比上升、坏账计提不足或主要客户回款延长。",
            },
        ],
        "required_next_evidence": [
            "应收账款账龄结构和坏账计提政策",
            "前五大客户及平台客户账期",
            "收入确认关键审计事项",
            "同行同期 DSRI / CFO 转化率",
        ],
        "verdict": "insufficient_evidence",
    }


def _cash_fabrication_review(history: CompanyHistory, flags: list[dict[str, Any]]) -> dict[str, Any]:
    prev, cur = _latest_annual_pair(history)
    return {
        "playbook_id": "CASH_FABRICATION",
        "trigger_flags": _flag_summaries(flags, ["DEPOSIT_LOAN_MISMATCH", "LOW_EARNINGS_QUALITY", "CFO_NI_DIVERGENCE"]),
        "industry_context": history.industry,
        "observations": {
            "money_cap_to_assets": _ratio(_value(cur, "money_cap"), _value(cur, "total_assets")),
            "interest_bearing_debt_to_assets": _ratio(_interest_debt(cur), _value(cur, "total_assets")),
            "previous_interest_bearing_debt": _interest_debt(prev),
            "current_interest_bearing_debt": _interest_debt(cur),
        },
        "hypotheses": [
            {
                "id": "H1_restricted_or_pledged_cash",
                "question": "货币资金是否受限或被质押但未充分解释？",
                "evidence_sections": ["pledge_guarantee", "audit_opinion"],
            },
            {
                "id": "H2_controlling_shareholder_fund_occupation",
                "question": "是否存在控股股东资金占用或关联方往来？",
                "evidence_sections": ["related_party", "other_receivables"],
            },
        ],
        "required_next_evidence": ["受限资金附注", "短长期借款明细", "利息收入/货币资金隐含收益率", "质押和担保记录"],
        "verdict": "insufficient_evidence",
    }


def _asset_hole_review(history: CompanyHistory, flags: list[dict[str, Any]]) -> dict[str, Any]:
    _, cur = _latest_annual_pair(history)
    return {
        "playbook_id": "ASSET_HOLE",
        "trigger_flags": _flag_summaries(flags, ["CIP_NOT_TRANSFERRING", "GOODWILL_HIGH", "OTHER_RECEIVABLE_HIGH", "PREPAYMENT_HIGH"]),
        "industry_context": history.industry,
        "observations": {
            "cip_to_fixed_assets": _ratio(_value(cur, "cip"), _value(cur, "fix_assets")),
            "goodwill_to_equity": _ratio(_value(cur, "goodwill"), _value(cur, "total_hldr_eqy_inc_min_int")),
            "other_receivable_to_assets": _ratio(_value(cur, "oth_receiv"), _value(cur, "total_assets")),
        },
        "hypotheses": [
            {
                "id": "H1_real_project_delay",
                "question": "在建工程或商誉风险是否有真实经营解释？",
                "evidence_sections": ["cip_detail", "goodwill_detail"],
            },
            {
                "id": "H2_hidden_asset_hole",
                "question": "是否存在虚增资产、延迟转固或关联方占用？",
                "evidence_sections": ["cip_detail", "related_party", "other_receivables"],
            },
        ],
        "required_next_evidence": ["在建工程项目明细", "商誉减值测试", "其他应收款对象", "关联方往来"],
        "verdict": "insufficient_evidence",
    }


def _resolve_company_dir(identifier: str, companies_dir: Path) -> Path:
    item = identifier.strip()
    if not item:
        raise ValueError("empty company identifier")
    maybe_path = Path(item)
    if maybe_path.exists() and maybe_path.is_dir():
        return maybe_path.resolve()
    if re.fullmatch(r"\d{6}(\.(SZ|SH|BJ))?", item.upper()):
        return find_company_dir(item.upper(), companies_dir)

    matches = sorted(path for path in companies_dir.glob(f"*{item}*") if path.is_dir())
    if not matches:
        raise FileNotFoundError(f"No company directory matching {identifier!r}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple company directories match {identifier!r}: {matches}")
    return matches[0]


def _latest_annual_pair(history: CompanyHistory) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(history.annual) >= 2:
        return history.annual[-2], history.annual[-1]
    if history.annual:
        return history.annual[-1], history.annual[-1]
    return {}, {}


def _working_capital_observations(prev: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    return {
        "period": cur.get("period"),
        "revenue_growth": _growth(_value(cur, "revenue"), _value(prev, "revenue")),
        "ar_growth": _growth(_value(cur, "accounts_receiv"), _value(prev, "accounts_receiv")),
        "inventory_growth": _growth(_value(cur, "inventories"), _value(prev, "inventories")),
        "ar_to_revenue": _ratio(_value(cur, "accounts_receiv"), _value(cur, "revenue")),
        "inventory_to_revenue": _ratio(_value(cur, "inventories"), _value(cur, "revenue")),
        "cfo_to_net_income": _ratio(_value(cur, "n_cashflow_act"), _value(cur, "n_income")),
    }


def _flag_summaries(flags: list[dict[str, Any]], rule_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(rule_ids)
    return [
        {
            "rule_id": flag.get("rule_id"),
            "severity": flag.get("severity"),
            "period": flag.get("period"),
            "value": flag.get("value"),
            "evidence_text": flag.get("evidence_text"),
        }
        for flag in flags
        if flag.get("rule_id") in wanted
    ]


def _value(row: dict[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1.0


def _interest_debt(row: dict[str, Any]) -> float | None:
    values = [_value(row, "st_borr"), _value(row, "lt_borr"), _value(row, "bond_payable")]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _load_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(row["key"]): str(row["value"]) for row in rows}


def _load_clean_table(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    parsed: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {"period": str(row["period"])}
        for key in row.keys():
            if key == "period":
                continue
            record[key] = _finite_or_none(row[key])
        parsed.append(record)
    parsed.sort(key=lambda item: _period_sort_key(str(item["period"])))
    return parsed


def _period_sort_key(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})(?:Q([1-4]))?", period)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2) or 5))


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ticker_from_company_dir(company_dir: Path) -> str:
    code = company_dir.name.rsplit("_", 1)[-1]
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return code


def _sections_for_flags(flags: list[dict[str, Any]]) -> list[str]:
    mapping = {
        "BENEISH_M_SCORE": ["revenue_recognition", "receivables_aging", "mda_risk"],
        "AR_REVENUE_RATIO_HIGH": ["receivables_aging", "revenue_recognition"],
        "CASH_RECEIPT_LOW": ["revenue_recognition", "receivables_aging"],
        "CONTRACT_LIABILITY_DECLINE": ["revenue_recognition", "mda_risk"],
        "INVENTORY_REVENUE_RATIO_HIGH": ["inventory_detail"],
        "CIP_NOT_TRANSFERRING": ["cip_detail"],
        "GOODWILL_HIGH": ["goodwill_detail"],
        "OTHER_RECEIVABLE_HIGH": ["other_receivables", "related_party"],
        "PREPAYMENT_HIGH": ["related_party", "other_receivables"],
        "DEPOSIT_LOAN_MISMATCH": ["pledge_guarantee", "audit_opinion"],
        "Q4_REVENUE_ANOMALY": ["revenue_recognition", "mda_risk"],
    }
    sections: list[str] = ["audit_opinion", "mda_risk"]
    for flag in flags:
        for section in mapping.get(str(flag.get("rule_id")), []):
            if section not in sections:
                sections.append(section)
    return sections


def _years_for_flags(flags: list[dict[str, Any]]) -> list[str]:
    years = sorted(
        {
            str(flag.get("period", ""))[:4]
            for flag in flags
            if re.match(r"^\d{4}", str(flag.get("period", "")))
        },
        reverse=True,
    )
    return years[:3]


def _latest_annual_year(history: CompanyHistory) -> int | None:
    years = [int(row["period"]) for row in history.annual if str(row.get("period", "")).isdigit()]
    return max(years) if years else None


def _dataframe_summary(df: Any, *, sample_rows: int = 8) -> dict[str, Any]:
    if df is None:
        return {"status": "ok", "rows": 0, "columns": [], "sample": []}
    if not isinstance(df, pd.DataFrame):
        return {"status": "ok", "raw_type": type(df).__name__, "value": repr(df)[:500]}
    sample = df.head(sample_rows).astype(object)
    sample = sample.where(pd.notnull(sample), None)
    return {
        "status": "ok",
        "rows": int(len(df)),
        "columns": list(df.columns),
        "sample": _json_safe(sample.to_dict(orient="records")),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            return None
    return value
