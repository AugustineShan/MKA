"""Local web workbench for ModelKing.

This is intentionally a thin UI shell. It reads company folders, serves the
React app, and delegates DCF generation to the official forecast pipeline:
Agent/defaults.yaml + Agent/yaml1*.yaml -> Agent/forecast/
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from io import StringIO
from pathlib import Path
from typing import Any

import requests
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import pandas as pd
from src import app_config
from src import field_registry as _registry
from src.annual_report_utils import load_env, llm_api_key, llm_base_url, llm_model, llm_timeout_seconds
from src.calc import (
    CalcError,
    ForecastBuildResult,
    as_float,
    build_forecast_statements,
    value_from_statements,
)
from src.assumption_staleness import StaleAssumptionError, ensure_assumptions_fresh
from src.company_paths import (
    COMPANIES_DIR as DEFAULT_COMPANIES_DIR,
    active_vore_dir,
    agent_dir,
    annual_reports_dir,
    collection_dir,
    da_schedule_path,
    db_path as company_db_path,
    defaults_path as company_defaults_path,
    forecast_dir as company_forecast_dir,
    important_files_dir,
    ka_reference_dir,
    latest_yaml1_path,
    meeting_notes_dir,
    modelking_dir,
    official_breakdowns_dir,
    quarterly_reports_dir,
    recon_dir,
    research_reports_dir,
)
from src.forecast import FidelityGateError, run_company_forecast
from src.derived_metrics import DERIVED_METRICS_FILENAME, build_derived_metrics_from_frames
from src.quarterly_tracker import (
    clear_override,
    compute_quarterly_view,
    load_overrides,
    set_override,
)
from src.yaml1_cleaner import Yaml1CleanError, clean_yaml1_data
from src.yaml2_schema import DEFAULT_TERMINAL_CAPEX_DA_RATIO, get_path


BASE_DIR = Path(__file__).resolve().parents[1]
COMPANIES_DIR = DEFAULT_COMPANIES_DIR
APP_DIST = BASE_DIR / "app" / "dist"
CORE_ASSUMPTION_NAMES = ("核心假设.md", "核心假设 (1).md")
INDUSTRY_JSON_PATH = BASE_DIR / "industry.json"

_FOLDER_OVERVIEW_TTL = 1.5
_folder_overview_cache: dict[str, Any] = {"ts": 0.0, "rows": None}
FORECAST_TABLES = (
    "forecast_is.csv",
    "forecast_bs.csv",
    "forecast_cf.csv",
)
FIELD_REFERENCE_NAME = "\u6570\u636e\u683c\u5f0f\u53c2\u8003.md"
PRESENTATION_SCHEMA_VERSION = 1
DISPLAY_SCHEMA_VERSION = 1
COMPANY_DIR_RE = re.compile(r"^.+_\d{6}$")

DISPLAY_ROLES = {"primary_model", "primary_attachment", "secondary_split", "reference", "check_only", "deprecated", "technical"}
DISPLAY_PLACEMENTS = {"model_table", "secondary_table", "reference_tab", "technical_tab"}
DISPLAY_DIMENSIONS = {"business_line", "product", "region", "channel", "subsidiary", "customer", "metric", "text", "other"}
DISPLAY_METRICS = {"revenue", "yoy", "gross_margin", "cost", "volume", "price", "rate", "amount", "text", "mixed"}
DISPLAY_STATUSES = {"active", "reference", "deprecated", "check_only", "missing_disclosure", "conflict"}
DISPLAY_DUPLICATE_POLICIES = {"show", "skip_if_equal", "prefer_derived_and_warn", "reference_only"}
DISPLAY_MATCH_POLICIES = {"exact_or_declared_alias", "declared_path", "none"}

STATEMENT_META = {
    "forecast_is.csv": {"key": "is", "name": "IS", "title": "\u5229\u6da6\u8868",
                        "doc_title": "\u5229\u6da6\u8868", "unit": "\u767e\u4e07\u5143"},
    "forecast_bs.csv": {"key": "bs", "name": "BS", "title": "\u8d44\u4ea7\u8d1f\u503a\u8868",
                        "doc_title": "\u8d44\u4ea7\u8d1f\u503a\u8868", "unit": "\u767e\u4e07\u5143"},
    "forecast_cf.csv": {"key": "cf", "name": "CF", "title": "\u73b0\u91d1\u6d41\u91cf\u8868",
                        "doc_title": "\u73b0\u91d1\u6d41\u91cf\u8868", "unit": "\u767e\u4e07\u5143"},
}


# full_*.csv = history+forecast concatenated, same schema as forecast_*.csv.
# Alias to the forecast meta so _statement_rows shapes them identically (same field labels).
FULL_STATEMENT_TABLES = ("full_is.csv", "full_bs.csv", "full_cf.csv")
for _full_name, _fcst_name in (
    ("full_is.csv", "forecast_is.csv"),
    ("full_bs.csv", "forecast_bs.csv"),
    ("full_cf.csv", "forecast_cf.csv"),
):
    STATEMENT_META[_full_name] = STATEMENT_META[_fcst_name]

app = FastAPI(title="ModelKing Workbench")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(_read_text(path))
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(_read_text(path))
    return data if isinstance(data, dict) else {}


def _read_meta(company_dir: Path) -> dict[str, str]:
    db_path = company_db_path(company_dir)
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("select key, value from meta where key in ('name', 'ticker')").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows if value is not None}


def _da_base_reported_dep(company_dir: Path, base_year: str) -> float | None:
    """base 年现金流量表 PP&E 折旧(depr_fa_coga_dpba),与 forecast._maybe_roll_da_series 同源。"""
    db_path = company_db_path(company_dir)
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "select depr_fa_coga_dpba from clean_annual where period = ?", (str(base_year),)
            ).fetchone()
    except sqlite3.Error:
        return None
    return float(row[0]) if row and row[0] is not None else None


def _da_normalization(da_series: list | None, sched: dict) -> dict | None:
    """重算终值归一化门(da_roll.normalization_gate);da_series 缺失→None。展示层不阻塞。"""
    if not da_series:
        return None
    try:
        from src.da_roll import normalization_gate
        g = float(sched.get("ppe", {}).get("存量策略", {}).get("net_growth_rate", 0.0) or 0.0)
        pg = float(sched.get("terminal", {}).get("perpetual_growth", 0.0) or 0.0)
        passed, reason = normalization_gate(da_series, g, pg)
        return {"passed": passed, "reason": reason}
    except Exception as exc:  # 展示层不阻塞,诚实记错
        return {"passed": None, "reason": f"normalization_gate error: {exc}"}


def _da_view(company_dir: Path, base_period: str) -> dict[str, Any] | None:
    """只读装配重资产排程展示数据。enabled/false/缺失 → None(前端不渲染 tab)。

    用 yaml.safe_load 直读 da_schedule.yaml,不走 src.da_roll.load_da_schedule 的对齐校验
    (那是 forecast 运行时硬校验;展示层在 base_year 错位时塞 align_warning 红字标注,不阻塞)。
    """
    sched_path = da_schedule_path(company_dir)
    if not sched_path.exists():
        return None
    sched = _read_yaml(sched_path)
    if not sched.get("enabled", False):
        return None
    base_year = sched.get("base_year")
    base_year_str = str(base_year) if base_year is not None else base_period
    align_warning = None
    if base_year_str != str(base_period)[:4]:
        align_warning = f"da_schedule.base_year={base_year} ≠ defaults.base_period={base_period}"

    def _da_categories(section: dict[str, Any]) -> list[dict[str, Any]]:
        """装配类别列表(含 policy_dep / base_net),PP&E 与 other_depreciating_assets 共用。"""
        out: list[dict[str, Any]] = []
        for c in section.get("categories", []) or []:
            gross = float(c.get("base_gross") or 0.0)
            salv = float(c.get("salvage_rate") or 0.0)
            life = float(c.get("life_years") or 0.0)
            accum = float(c.get("base_accum_dep") or 0.0)
            policy_dep = gross * (1 - salv) / life if life else 0.0
            out.append({
                "name": c.get("name"),
                "life_years": c.get("life_years"),
                "salvage_rate": salv,
                "base_gross": gross,
                "base_accum_dep": accum,
                "base_net": gross - accum,
                "base_cip": float(c.get("base_cip") or 0.0),
                "policy_dep": policy_dep,
            })
        return out

    ppe_section = sched.get("ppe", {}) or {}
    cats = _da_categories(ppe_section)
    # other_depreciating_assets(生物/油气):同结构类别,参与 scale 分母(全口径对齐 depr_fa_coga_dpba)
    other_section = sched.get("other_depreciating_assets", {}) or {}
    other_cats = _da_categories(other_section)
    policy_dep_total = sum(c["policy_dep"] for c in cats) + sum(c["policy_dep"] for c in other_cats)
    reported = _da_base_reported_dep(company_dir, base_year_str)
    scale = (reported / policy_dep_total) if (reported is not None and policy_dep_total > 0) else None

    # da_series:从 .modelking/forecast_params.yaml["da_series"] 透传
    fp_path = modelking_dir(company_dir) / "forecast_params.yaml"
    da_series: list | None = None
    if fp_path.exists():
        fp = _read_yaml(fp_path)
        ds = fp.get("da_series")
        if isinstance(ds, list):
            da_series = ds

    # facts:da_facts_latest.json 透传(原始单位元,展示层按需 ÷1e6)
    facts_path = recon_dir(company_dir) / "da_facts_latest.json"
    facts = _read_json(facts_path) if facts_path.exists() else None

    return {
        "enabled": True,
        "base_year": base_year,
        "align_warning": align_warning,
        "stock_strategy": ppe_section.get("存量策略", {}) or {},
        "categories": cats,
        "other_depreciating_assets": {
            "stock_strategy": other_section.get("存量策略", {}) or {},
            "categories": other_cats,
        } if other_cats else None,
        "scale": scale,
        "base_reported_dep": reported,
        "base_cip_to_fixed": sched.get("base_cip_to_fixed", {}) or {},
        "expansion_plan": sched.get("expansion_plan", {}) or {},
        "terminal": sched.get("terminal", {}) or {},
        "da_series": da_series,
        "normalization": _da_normalization(da_series, sched),
        "facts": facts,
    }


def _base_period_for_company(company_dir: Path) -> str:
    """读 defaults.yaml base_period;缺则返回空串(_da_view 仍装配,align_warning 会触发)。"""
    defaults = _read_yaml(company_defaults_path(company_dir))
    bp = defaults.get("base_period")
    return str(bp) if bp else ""


def _plain(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _companies_root() -> Path:
    return app_config.get_companies_dir()


def _company_dirs() -> list[Path]:
    companies_dir = _companies_root()
    if not companies_dir.exists():
        return []
    return sorted(
        [path for path in companies_dir.iterdir() if path.is_dir() and COMPANY_DIR_RE.match(path.name)],
        key=lambda item: item.name,
    )


def _company_dir(company_id: str) -> Path:
    companies_root = _companies_root().resolve()
    target = (companies_root / company_id).resolve()
    if not target.is_dir() or companies_root not in target.parents or not COMPANY_DIR_RE.match(target.name):
        raise HTTPException(status_code=404, detail=f"Company not found: {company_id}")
    return target


def _latest_yaml1(company_dir: Path) -> Path | None:
    try:
        return latest_yaml1_path(company_dir)
    except FileNotFoundError:
        return None


def _core_assumption(company_dir: Path) -> Path | None:
    for name in CORE_ASSUMPTION_NAMES:
        path = company_dir / name
        if path.exists():
            return path
    candidates = sorted(company_dir.glob("*核心假设*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _pipeline_stage(company_dir: Path) -> str:
    """建模管线推进状态：未初始化 / 初始化完毕 / 预加载完毕 / 建模完毕 / 建模完毕且有DA表。

    预加载完毕 = init 已跑完且 KA 参考稿区（Skills素材包/KA...）已有文件，但尚未生成 yaml1/DCF。
    """
    agent = agent_dir(company_dir)
    if not (agent / "data.db").exists() or not company_defaults_path(company_dir).exists():
        return "未初始化"
    if _latest_yaml1(company_dir) is not None:
        if da_schedule_path(company_dir).exists():
            return "建模完毕且有DA表"
        return "建模完毕"
    if _count_files(ka_reference_dir(company_dir)) > 0:
        return "预加载完毕"
    return "初始化完毕"


_KA_REF_RE = re.compile(r"^核心假设参考([a-z]+)_(\d{8})\.md$")


def _ka_reference_products(company_dir: Path) -> list[dict[str, Any]]:
    """KA 参考稿区的 核心假设参考*.md 产物清单（brkd/load/alphapai），供前端管线推进展示。"""
    ka_dir = ka_reference_dir(company_dir)
    if not ka_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(ka_dir.glob("核心假设参考*.md")):
        match = _KA_REF_RE.match(path.name)
        if match:
            source = match.group(1)
            s = match.group(2)
            date = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        else:
            # 核心假设参考.md 等无来源后缀的裸参考稿
            source = "参考"
            date = None
        items.append({"name": path.name, "source": source, "date": date})
    return items


_YAML1_DATE_RE = re.compile(r"(\d{8})")
_MODEL_DATE_RE = re.compile(r"(\d{6})")

_WORKBENCH_MATERIAL_FNS = {
    "reports": research_reports_dir,
    "notes": meeting_notes_dir,
    "collected": collection_dir,
    "important": important_files_dir,
}


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for _root, _dirs, files in os.walk(path):
        total += len(files)
    return total


def _yaml1_date(path: Path) -> str | None:
    matches = _YAML1_DATE_RE.findall(path.stem)
    if not matches:
        return None
    s = matches[-1]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _folder_overview_signals(company_dir: Path) -> dict[str, Any]:
    yaml1s = sorted(agent_dir(company_dir).glob("yaml1*.yaml"))
    latest = _latest_yaml1(company_dir)
    yaml1_date = _yaml1_date(latest) if latest else None

    excels = [p for p in company_dir.glob("*.xlsx") if not p.name.startswith("~$")]
    locks = list(company_dir.glob("~$*.xlsx"))

    workbench_total = sum(_count_files(fn(company_dir)) for fn in _WORKBENCH_MATERIAL_FNS.values())

    return {
        "pipeline_stage": _pipeline_stage(company_dir),
        "yaml1_date": yaml1_date,
        "yaml1_versions": len(yaml1s),
        "yaml1_archive_eligible": len(yaml1s) > 1,
        "root_models": {
            "excel_count": len(excels),
            "lock_count": len(locks),
            "archive_eligible": len(excels) > 1,
        },
        "workbench_materials": workbench_total,
        "ka_references": _ka_reference_products(company_dir),
        "forecast": _forecast_snapshot(company_dir),
    }


def _git_mv(src: Path, dst: Path) -> None:
    """git mv 保历史；非 tracked 回退 shutil.move。dst 的父目录须已存在。"""
    try:
        subprocess.run(
            ["git", "mv", str(src), str(dst)],
            cwd=BASE_DIR, check=True, capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.move(str(src), str(dst))


def _unique_dst(dst_dir: Path, name: str) -> Path:
    dst = dst_dir / name
    if not dst.exists():
        return dst
    base, _, ext = name.rpartition(".")
    stamp = time.strftime("%H%M%S")
    candidate = dst_dir / f"{base}-{stamp}.{ext}"
    counter = 1
    while candidate.exists():
        candidate = dst_dir / f"{base}-{stamp}-{counter}.{ext}"
        counter += 1
    return candidate


def _model_vintage_key(path: Path) -> str:
    m = _MODEL_DATE_RE.search(path.stem)
    return m.group(1) if m else "000000"


def _archive_models(company_dir: Path) -> dict[str, Any]:
    agent = agent_dir(company_dir)
    yaml1history = agent / "yaml1history"
    modelhistory = agent / "Modelhistory"

    archived_yaml1: list[str] = []
    latest_yaml1 = _latest_yaml1(company_dir)
    if latest_yaml1 is not None:
        yaml1s = sorted(agent.glob("yaml1*.yaml"))
        if len(yaml1s) > 1:
            yaml1history.mkdir(parents=True, exist_ok=True)
            for p in yaml1s:
                if p.resolve() == latest_yaml1.resolve():
                    continue
                dst = _unique_dst(yaml1history, p.name)
                _git_mv(p, dst)
                archived_yaml1.append(p.name)

    archived_models: list[str] = []
    excels = [p for p in company_dir.glob("*.xlsx") if not p.name.startswith("~$")]
    if len(excels) > 1:
        modelhistory.mkdir(parents=True, exist_ok=True)
        newest = max(excels, key=_model_vintage_key)
        for p in excels:
            if p.resolve() == newest.resolve():
                continue
            dst = _unique_dst(modelhistory, p.name)
            _git_mv(p, dst)
            archived_models.append(p.name)

    deleted_locks: list[str] = []
    for lock in company_dir.glob("~$*.xlsx"):
        lock.unlink()
        deleted_locks.append(lock.name)

    return {
        "archived_yaml1": archived_yaml1,
        "archived_models": archived_models,
        "deleted_locks": deleted_locks,
    }


def _forecast_summary(company_dir: Path) -> dict[str, Any]:
    return _read_json(company_forecast_dir(company_dir) / "dcf_summary.json")


def _manifest(company_dir: Path) -> dict[str, Any]:
    return _read_json(company_forecast_dir(company_dir) / "run_manifest.json")


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        return str(path)


def _csv_preview(path: Path) -> str:
    text = _read_text(path)
    rows = list(csv.reader(StringIO(text)))
    out = StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows(rows[:100])
    return out.getvalue()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return list(csv.DictReader(StringIO(_read_text(path))))


# 字段→中文标签扁平索引:统一来自 field_registry(三表 325 字段合并)。
# 仅影响展示层中文化(行/列标签);非 TuShare 码在 STASH_CODE_LABELS 补充。
FIELD_LABELS: dict[str, str] = _registry.LABELS


# 非 TuShare 码(knob 路径/历史观测专用),不在 field_registry,展示层补中文。
STASH_CODE_LABELS: dict[str, str] = {
    "gpm": "整体毛利率",
    "effective_tax_rate": "有效税率",
    "minority_ratio": "少数股东损益占比",
    "fin_exp_total": "财务费用合计",
    "other_fin_exp_abs": "其他财务费用(外生)",
    "ton_cost": "吨成本",
    "interest_bearing_debt": "有息负债",
    "money_cap": "货币资金",
    "interest_expense_net": "利息净额",
    "interest_income": "利息收入",
    # 驱动/旋钮路径末段（terminal fade_paths/hold_paths 用）
    "revenue_yoy": "营收增速",
    "revenue_abs": "营收绝对值",
    "volume_yoy": "销量增速",
    "price_yoy": "吨价增速",
}

_YEAR_PREFIXD_KEY = re.compile(r"^(\d{4})_(.+)$")


def _humanize_label(token: Any) -> str:
    """通用 token→中文标签解析器（展示层）。任何未知 token 原样返回，零丢失。

    顺序：FIELD_LABELS(TuShare 字段) → STASH_CODE_LABELS(knob 码) →
          YYYY_<code> 拆分递归 → 原样。
    """
    s = str(token)
    if s in FIELD_LABELS:
        return FIELD_LABELS[s]
    if s in STASH_CODE_LABELS:
        return STASH_CODE_LABELS[s]
    m = _YEAR_PREFIXD_KEY.match(s)
    if m:
        return f"{m.group(1)} {_humanize_label(m.group(2))}"
    return s


def _humanize_path(path: Any) -> str:
    """defaults.yaml knob 路径 → 中文末段（展示层）。取最后一个 '.' 后的段交 _humanize_label。

    income.cost_rates.sell_exp → 减:销售费用；income.gpm → 整体毛利率；model.revenue_yoy → 营收增速。
    未知段原样回退，零丢失。
    """
    s = str(path)
    leaf = s.rsplit(".", 1)[-1]
    return _humanize_label(leaf)


def _number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _nonzero(values: dict[str, float | None], epsilon: float = 1e-9) -> bool:
    return any(value is not None and abs(value) > epsilon for value in values.values())


def _statement_display_label(field: str, label: str, category: str) -> str:
    """Investor-facing label for statement presentation rows.

    Registry labels stay faithful to TuShare/raw accounting fields; the workbench
    presentation view can remove source-system suffixes when a combo row is used
    as a fallback display row.
    """
    if category != "combo":
        return label
    cleaned = label
    for suffix in ("(合计)(元)", "（合计）（元）", "(合计)（元）", "（合计）(元)", "（元）", "(元)"):
        cleaned = cleaned.replace(suffix, "")
    return cleaned


def _statement_display_role(field: str, category: str, role: str) -> str:
    if field.startswith("qa_") or category in {"combo", "derived", "sub_item"}:
        return "technical"
    if role in {"subtotal", "total"}:
        return "primary"
    return "primary"


def _statement_rows_from_records(table_name: str, rows: list[dict[str, Any]], path_label: str) -> dict[str, Any] | None:
    meta = STATEMENT_META.get(table_name)
    if not rows or not meta:
        return None
    stmt = _registry.statement_meta_for_table(table_name)
    years = [str(int(float(row["period"]))) for row in rows if row.get("period")]
    fields_in_csv = set(rows[0].keys()) - {"period"}

    values_by_field: dict[str, dict[str, float | None]] = {}
    for field in fields_in_csv:
        values_by_field[field] = {str(int(float(row["period"]))): _number_or_none(row.get(field)) for row in rows if row.get("period")}

    used: set[str] = set()
    output_rows: list[dict[str, Any]] = []

    def append_field(field: str) -> None:
        if field in used or field not in fields_in_csv:
            return
        if field not in stmt.labels:
            return
        category = stmt.field_categories[field]
        if field in stmt.total_fields:
            role = "total"
        elif category == "subtotal":
            role = "subtotal"
        else:
            role = "normal"
        values = values_by_field[field]
        display_role = _statement_display_role(field, category, role)
        combo_of = list(stmt.combo_resolve[field][0]) if field in stmt.combo_resolve else []
        output_rows.append(
            {
                "field": field,
                "label": stmt.labels[field],
                "display_label": _statement_display_label(field, stmt.labels[field], category),
                "category": category,
                "category_label": stmt.category_labels.get(category, category),
                "role": role,
                "display_role": display_role,
                "is_technical": display_role == "technical",
                "technical_reason": "combo_or_derived_accounting_field" if display_role == "technical" else None,
                "combo_of": combo_of,
                "level": 0 if role in {"subtotal", "total"} else 1,
                "is_zero": not _nonzero(values),
                "values": values,
            }
        )
        used.add(field)

    # registry.field_order 已是严格会计序(小计内联在其位置),直接迭代即可。
    for field in stmt.field_order:
        append_field(field)
    # 残留:CSV 里但不在 registry 的列(QA plug 等),按 CSV 序兜底;无 label 的自动跳过。
    for field in fields_in_csv:
        append_field(field)

    return {
        "key": meta["key"],
        "name": meta["name"],
        "title": meta["title"],
        "unit": meta["unit"],
        "path": path_label,
        "years": years,
        "rows": output_rows,
    }


def _statement_rows(table_name: str, csv_path: Path) -> dict[str, Any] | None:
    rows = _read_csv_rows(csv_path)
    return _statement_rows_from_records(table_name, rows, _relative(csv_path))


def _statement_rows_from_dataframe(table_name: str, df: pd.DataFrame, path_label: str) -> dict[str, Any] | None:
    if df.empty:
        return None
    rows = df.to_dict(orient="records")
    return _statement_rows_from_records(table_name, rows, path_label)


def _statement_sheets(company_dir: Path) -> list[dict[str, Any]]:
    forecast_dir = company_forecast_dir(company_dir)
    sheets = []
    for table_name in FORECAST_TABLES:
        sheet = _statement_rows(table_name, forecast_dir / table_name)
        if sheet:
            sheets.append(sheet)
    return sheets


def _full_statement_sheets(company_dir: Path) -> list[dict[str, Any]]:
    """History+forecast concatenated statements (full_*.csv). Same shaping as forecast."""
    forecast_dir = company_forecast_dir(company_dir)
    sheets = []
    for table_name in FULL_STATEMENT_TABLES:
        sheet = _statement_rows(table_name, forecast_dir / table_name)
        if sheet:
            sheets.append(sheet)
    return sheets


def _dcf_detail(company_dir: Path) -> list[dict[str, Any]]:
    """Per-year FCFF build: fcff, discount_factor, pv_fcff, nopat, da, capex, delta_nwc."""
    rows = _read_csv_rows(company_forecast_dir(company_dir) / "dcf_detail.csv")
    out: list[dict[str, Any]] = []
    for row in rows:
        period = row.get("period")
        if not period:
            continue
        try:
            period_int = int(float(period))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "period": period_int,
                "fcff": _number_or_none(row.get("fcff")),
                "discount_factor": _number_or_none(row.get("discount_factor")),
                "pv_fcff": _number_or_none(row.get("pv_fcff")),
                "nopat": _number_or_none(row.get("nopat")),
                "da": _number_or_none(row.get("da")),
                "capex": _number_or_none(row.get("capex")),
                "delta_nwc": _number_or_none(row.get("delta_nwc")),
            }
        )
    return out


def _derived_metrics(company_dir: Path) -> dict[str, Any] | None:
    path = company_forecast_dir(company_dir) / DERIVED_METRICS_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(_read_text(path))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _metric_for_year(annual: dict[str, Any], year: int, key: str) -> float | None:
    row = annual.get(str(year))
    if not isinstance(row, dict):
        return None
    raw = row.get(key)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _meta_total_mv(company_dir: Path) -> float | None:
    """从 data.db meta 读最新市值(百万元)。市值是基础行情事实，不依赖 forecast 产物。"""
    db_path = company_db_path(company_dir)
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("select value from meta where key = 'total_mv'").fetchone()
    except sqlite3.Error:
        return None
    if not row or row[0] is None or row[0] == "":
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _forecast_snapshot(company_dir: Path) -> dict[str, Any] | None:
    """预测与估值快照（来自 Agent/forecast/derived_metrics.json）。

    市值是基础行情事实：derived_metrics.market_snapshot 缺失时回退 data.db meta.total_mv，
    保证已初始化公司即使尚未跑 DCF 也显示市值，不因无 forecast 产物而漏市值。
    展示年份由 HOME_DISPLAY_START_YEAR 配置驱动，默认 2026。
    """
    dm = _derived_metrics(company_dir)
    annual = dm.get("annual") if isinstance(dm, dict) and isinstance(dm.get("annual"), dict) else {}
    market = dm.get("market_snapshot") if isinstance(dm, dict) and isinstance(dm.get("market_snapshot"), dict) else {}
    market_cap: float | None = None
    raw_mv = market.get("total_mv")
    if raw_mv is not None and raw_mv != "":
        try:
            market_cap = float(raw_mv)
        except (TypeError, ValueError):
            market_cap = None
    if market_cap is None:
        market_cap = _meta_total_mv(company_dir)
    start_year = app_config.home_display_year()
    end_year = start_year + 1
    snap = {
        "market_cap": market_cap,
        "revenue_yoy": {str(start_year): _metric_for_year(annual, start_year, "revenue_yoy"), str(end_year): _metric_for_year(annual, end_year, "revenue_yoy")},
        "profit_yoy": {str(start_year): _metric_for_year(annual, start_year, "n_income_attr_p_yoy"), str(end_year): _metric_for_year(annual, end_year, "n_income_attr_p_yoy")},
        "pe": {str(start_year): _metric_for_year(annual, start_year, "pe"), str(end_year): _metric_for_year(annual, end_year, "pe")},
    }
    has_any = (
        snap["market_cap"] is not None
        or any(v is not None for v in snap["revenue_yoy"].values())
        or any(v is not None for v in snap["profit_yoy"].values())
        or any(v is not None for v in snap["pe"].values())
    )
    return snap if has_any else None


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_cell(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_cell(item)}" for key, item in value.items())
    return str(value)


def _years_from_yaml1(data: dict[str, Any]) -> list[str]:
    meta = data.get("meta", {})
    if isinstance(meta, dict) and isinstance(meta.get("horizon"), list):
        return [str(year) for year in meta["horizon"]]
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("values"), list):
            return [f"Y{i + 1}" for i in range(len(value["values"]))]
    return []


def _spread_values(values: Any, years: list[str]) -> dict[str, str]:
    cells = {year: "" for year in years}
    if isinstance(values, list):
        for index, value in enumerate(values[: len(years)]):
            cells[years[index]] = _cell(value)
    elif years:
        cells[years[0]] = _cell(values)
    return cells


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _series_value(values: Any, index: int, default: float = 0.0) -> float:
    if isinstance(values, list) and index < len(values):
        return _as_float(values[index], default)
    return _as_float(values, default)


def _numeric_year_series(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    series: dict[str, float] = {}
    for year, value in values.items():
        year_text = str(year)
        if re.fullmatch(r"\d{4}", year_text):
            series[year_text] = _as_float(value)
    return series


def _display_source(payload: dict[str, Any], fallback: str) -> str:
    source = _cell(payload.get("src"))
    return source.lstrip("#") if source else fallback


def _product(values: list[float]) -> float:
    out = 1.0
    for value in values:
        out *= value
    return out


def _factor_projection_values(factor: dict[str, Any], years: list[str]) -> list[float]:
    base = _as_float(factor.get("base"))
    projection = factor.get("projection", {})
    if not isinstance(projection, dict):
        projection = {}
    kind = str(projection.get("kind", "constant"))
    if kind == "yoy":
        current = base
        values: list[float] = []
        for index, _year in enumerate(years):
            current *= 1.0 + _series_value(projection.get("values"), index)
            values.append(current)
        return values
    if kind == "abs":
        return [_series_value(projection.get("values"), index) for index, _year in enumerate(years)]
    return [base for _year in years]


def _iter_revenue_leaves(
    segments: dict[str, Any],
    prefix: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    leaves: list[tuple[str, dict[str, Any]]] = []
    for key, payload in segments.items():
        if not isinstance(payload, dict):
            continue
        name = f"{prefix}.{key}" if prefix else str(key)
        child_segments = payload.get("segments")
        if payload.get("kind") == "decomposition" and isinstance(child_segments, dict):
            leaves.extend(_iter_revenue_leaves(child_segments, name))
        else:
            leaves.append((name, payload))
    return leaves


def _evaluate_yaml1_revenue_leaf(
    payload: dict[str, Any],
    years: list[str],
) -> tuple[float, dict[str, float], dict[str, float], dict[str, float | None]]:
    base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
    knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
    family = _cell(payload.get("revenue_family"))
    unit_factor = _as_float(base.get("unit_factor_to_million_cny"), 1.0) or 1.0
    revenues: dict[str, float] = {}
    yoys: dict[str, float] = {}
    volumes: dict[str, float] = {}
    base_revenue = _as_float(base.get("revenue")) / unit_factor

    if family in {"factor_product", "driver_rate"}:
        factors = payload.get("factors")
        if isinstance(factors, list) and factors:
            base_revenue = _product([_as_float(factor.get("base")) for factor in factors if isinstance(factor, dict)]) / unit_factor
            series = [
                _factor_projection_values(factor, years)
                for factor in factors
                if isinstance(factor, dict)
            ]
            previous = base_revenue
            for index, year in enumerate(years):
                current = _product([values[index] for values in series]) / unit_factor
                revenues[year] = current
                yoys[year] = (current / previous - 1.0) if previous else 0.0
                previous = current
            return base_revenue, revenues, yoys, volumes

    if family in {"vol_price", "vol_price_margin"}:
        volume = _as_float(base.get("volume"))
        price = _as_float(base.get("price"))
        base_revenue = volume * price / unit_factor
        previous = base_revenue
        for index, year in enumerate(years):
            volume *= 1.0 + _series_value(knobs.get("volume_yoy"), index)
            price *= 1.0 + _series_value(knobs.get("price_yoy"), index)
            current = volume * price / unit_factor
            volumes[year] = volume
            revenues[year] = current
            yoys[year] = (current / previous - 1.0) if previous else 0.0
            previous = current
        return base_revenue, revenues, yoys, volumes

    if family == "abs":
        previous = base_revenue
        for index, year in enumerate(years):
            current = _series_value(knobs.get("revenue_abs"), index) / unit_factor
            revenues[year] = current
            yoys[year] = (current / previous - 1.0) if previous else 0.0
            previous = current
        return base_revenue, revenues, yoys, volumes

    previous = base_revenue
    for index, year in enumerate(years):
        current = previous * (1.0 + _series_value(knobs.get("revenue_yoy"), index))
        revenues[year] = current
        yoys[year] = (current / previous - 1.0) if previous else 0.0
        previous = current
    return base_revenue, revenues, yoys, volumes


def _yaml1_revenue_view(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        data = yaml.safe_load(_read_text(path))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    years = _years_from_yaml1(data)
    revenue = data.get("income.revenue", {})
    segments = revenue.get("segments", {}) if isinstance(revenue, dict) else {}
    if not years or not isinstance(segments, dict):
        return None

    segment_rows: list[dict[str, Any]] = []
    driver_rows: list[dict[str, Any]] = []
    total_revenues = {year: 0.0 for year in years}
    base_total = 0.0
    base_year = None

    for segment_key, payload in _iter_revenue_leaves(segments):
        base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
        knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
        history = payload.get("history", {}) if isinstance(payload.get("history"), dict) else {}
        history_series = history.get("series", {}) if isinstance(history.get("series"), dict) else {}
        base_series = base.get("series", {}) if isinstance(base.get("series"), dict) else {}
        payload_series = payload.get("series", {}) if isinstance(payload.get("series"), dict) else {}
        family = _cell(payload.get("revenue_family"))
        unit_factor = _as_float(base.get("unit_factor_to_million_cny"), 1.0) or 1.0
        segment_base_year = int(_as_float(base.get("base_year"), 0))
        base_year = base_year or segment_base_year
        base_revenue, revenues, yoys, volumes = _evaluate_yaml1_revenue_leaf(payload, years)
        base_total += base_revenue

        for year, current_revenue in revenues.items():
            total_revenues[year] += current_revenue

        segment_name = _display_source(payload, str(segment_key))
        segment_rows.append(
            {
                "key": str(segment_key),
                "name": segment_name,
                "family": family,
                "base_year": segment_base_year,
                "base_volume": _as_float(base.get("volume")) if family in {"vol_price", "vol_price_margin"} else None,
                "base_price": _as_float(base.get("price")) if family in {"vol_price", "vol_price_margin"} else None,
                "volume_unit": _cell(base.get("unit", {}).get("volume")) if isinstance(base.get("unit"), dict) else None,
                "base_revenue": base_revenue,
                "unit_factor": unit_factor,
                "revenues": revenues,
                "yoys": yoys,
                "volumes": volumes,
                "history_revenues": (
                    _numeric_year_series(history_series.get("revenue"))
                    or _numeric_year_series(base_series.get("revenue"))
                    or _numeric_year_series(payload_series.get("revenue"))
                ),
                "history_costs": (
                    _numeric_year_series(history_series.get("cost"))
                    or _numeric_year_series(base_series.get("cost"))
                    or _numeric_year_series(payload_series.get("cost"))
                ),
                "history_volumes": (
                    _numeric_year_series(history_series.get("volume"))
                    or _numeric_year_series(base_series.get("volume"))
                    or _numeric_year_series(payload_series.get("volume"))
                ),
                "note": _cell(payload.get("note")),
            }
        )

        for driver_name, values in knobs.items():
            driver_rows.append(
                {
                    "segment": segment_name,
                    "driver": str(driver_name),
                    "values": {year: _series_value(values, index) for index, year in enumerate(years)},
                }
            )
        factors = payload.get("factors")
        if isinstance(factors, list):
            for factor in factors:
                if not isinstance(factor, dict):
                    continue
                projection = factor.get("projection", {}) if isinstance(factor.get("projection"), dict) else {}
                driver_rows.append(
                    {
                        "segment": segment_name,
                        "driver": _cell(factor.get("label")) or _cell(factor.get("key")),
                        "values": {
                            year: value
                            for year, value in zip(years, _factor_projection_values(factor, years), strict=False)
                        },
                        "projection": _cell(projection.get("kind")),
                    }
                )

    total_yoy: dict[str, float] = {}
    previous_total = base_total
    for year in years:
        value = total_revenues[year]
        total_yoy[year] = (value / previous_total - 1.0) if previous_total else 0.0
        previous_total = value

    return {
        "base_year": base_year,
        "years": years,
        "base_revenue": base_total,
        "revenues": total_revenues,
        "yoy": total_yoy,
        "segments": segment_rows,
        "drivers": driver_rows,
        "source": _cell(revenue.get("src")) if isinstance(revenue, dict) else "",
        "note": _cell(revenue.get("note")) if isinstance(revenue, dict) else "",
    }


def _yaml1_meta_sheet(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    meta = data.get("meta", {})
    if isinstance(meta, dict):
        rows.extend({"section": "meta", "field": str(key), "value": _cell(value)} for key, value in meta.items())
    terminal = data.get("terminal", {})
    if isinstance(terminal, dict):
        for key, value in terminal.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    rows.append({"section": "terminal", "field": f"{key}.{sub_key}", "value": _cell(sub_value)})
            else:
                rows.append({"section": "terminal", "field": str(key), "value": _cell(value)})
    return {
        "name": "Meta",
        "description": "Compiler metadata and terminal settings",
        "columns": ["section", "field", "value"],
        "rows": rows,
    }


def _yaml1_revenue_sheet(data: dict[str, Any], years: list[str]) -> dict[str, Any]:
    columns = [
        "segment",
        "driver",
        "family",
        "base_year",
        "base_volume",
        "base_price",
        "base_revenue",
        "unit_factor",
        *years,
        "source",
        "note",
    ]
    rows: list[dict[str, str]] = []
    revenue = data.get("income.revenue", {})
    segments = revenue.get("segments", {}) if isinstance(revenue, dict) else {}
    if isinstance(segments, dict):
        for segment, payload in _iter_revenue_leaves(segments):
            base = payload.get("base", {}) if isinstance(payload.get("base"), dict) else {}
            knobs = payload.get("knobs", {}) if isinstance(payload.get("knobs"), dict) else {}
            for driver, values in knobs.items():
                rows.append(
                    {
                        "segment": str(segment),
                        "driver": str(driver),
                        "family": _cell(payload.get("revenue_family")),
                        "base_year": _cell(base.get("base_year")),
                        "base_volume": _cell(base.get("volume")),
                        "base_price": _cell(base.get("price")),
                        "base_revenue": _cell(base.get("revenue")),
                        "unit_factor": _cell(base.get("unit_factor_to_million_cny")),
                        **_spread_values(values, years),
                        "source": _cell(payload.get("src")),
                        "note": _cell(payload.get("note")),
                    }
                )
            factors = payload.get("factors")
            if isinstance(factors, list):
                for factor in factors:
                    if not isinstance(factor, dict):
                        continue
                    projection = factor.get("projection", {}) if isinstance(factor.get("projection"), dict) else {}
                    rows.append(
                        {
                            "segment": str(segment),
                            "driver": _cell(factor.get("label")) or _cell(factor.get("key")),
                            "family": _cell(payload.get("revenue_family")),
                            "base_year": _cell(base.get("base_year")),
                            "base_volume": _cell(factor.get("base")),
                            "base_price": "",
                            "base_revenue": "",
                            "unit_factor": _cell(base.get("unit_factor_to_million_cny")),
                            **_spread_values(projection.get("values"), years),
                            "source": _cell(payload.get("src")),
                            "note": f"projection={_cell(projection.get('kind'))}",
                        }
                    )
    return {
        "name": "Revenue Build",
        "description": "Decomposition leaf drivers by segment and year",
        "columns": columns,
        "rows": rows,
    }


def _yaml1_knob_sheet(data: dict[str, Any], years: list[str]) -> dict[str, Any]:
    columns = ["path", "kind", *years, "source", "note"]
    rows: list[dict[str, str]] = []
    skip = {"meta", "terminal", "stash", "income.revenue", "display"}
    for path, payload in data.items():
        if path in skip or not isinstance(payload, dict):
            continue
        values = payload.get("values")
        if values is None:
            continue
        rows.append(
            {
                "path": str(path),
                "kind": _cell(payload.get("kind")),
                **_spread_values(values, years),
                "source": _cell(payload.get("src")),
                "note": _cell(payload.get("note")),
            }
        )
    return {
        "name": "DCF Knobs",
        "description": "Sparse yaml1 overrides that enter the forecast engine",
        "columns": columns,
        "rows": rows,
    }


def _flatten_stash(name: str, payload: Any, prefix: list[str], rows: list[dict[str, str]]) -> None:
    if isinstance(payload, dict):
        series = payload.get("series")
        if isinstance(series, dict):
            for item, values in series.items():
                if isinstance(values, dict):
                    row = {"group": name, "item": " / ".join([*prefix, str(item)]), "note": _cell(payload.get("note")), "unit": _cell(payload.get("unit"))}
                    for year, value in values.items():
                        row[str(year)] = _cell(value)
                    rows.append(row)
            return
        for key, value in payload.items():
            if key not in {"note", "unit"}:
                _flatten_stash(name, value, [*prefix, str(key)], rows)


def _yaml1_stash_sheet(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    stash = data.get("stash", {})
    if isinstance(stash, dict):
        for name, payload in stash.items():
            _flatten_stash(str(name), payload, [], rows)
    year_columns = sorted({key for row in rows for key in row if key.isdigit()})
    return {
        "name": "Stash",
        "description": "Non-DCF structured storage kept for frontend and traceability",
        "columns": ["group", "item", "unit", *year_columns, "note"],
        "rows": rows,
    }


def _yaml1_sheets(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        data = yaml.safe_load(_read_text(path))
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    years = _years_from_yaml1(data)
    sheets = [
        _yaml1_meta_sheet(data),
        _yaml1_revenue_sheet(data, years),
        _yaml1_knob_sheet(data, years),
        _yaml1_stash_sheet(data),
    ]
    return [sheet for sheet in sheets if sheet["rows"]]


# ─────────────────────────── yaml1 stash type-dispatch (universal) ───────────────────────────
# Stash is the most free-form, per-company-different part of yaml1. Render by JSON *shape*
# (not by company/block name) so any company's stash is displayed with nothing dropped.
# Mirrors the philosophy of _iter_revenue_leaves: generic traversal + type dispatch.


def _is_year_key(key: Any) -> bool:
    s = str(key)
    if not s.isdigit():
        return False
    n = int(s)
    return 1900 < n < 2100


def _stash_series_items(series: dict) -> tuple[list[dict], bool]:
    """Return (items, is_year_table). items=[{label, values:{key:value}, note?}]."""
    items: list[dict] = []
    is_year_table = True
    for label, values in series.items():
        if not isinstance(values, dict):
            continue
        entry: dict = {"key": str(label), "label": _humanize_label(label), "values": {}, "note": None}
        block_year = True
        has_value = False
        for k, v in values.items():
            if k == "note":
                entry["note"] = _cell(v)
                continue
            if k in ("unit", "caveat"):
                continue
            entry["values"][str(k)] = v
            has_value = True
            if not _is_year_key(k):
                block_year = False
        if has_value:
            items.append(entry)
            if not block_year:
                is_year_table = False
    if not items:
        is_year_table = False
    return items, is_year_table


def _stash_block(name: str, payload: Any, path: str | None = None) -> dict:
    """Classify one stash block by JSON shape → typed block. Universal, never drops."""
    block_path = path or name
    if isinstance(payload, list):
        return {"name": name, "path": block_path, "type": "list", "items": [x if isinstance(x, str) else _cell(x) for x in payload]}
    if not isinstance(payload, dict):
        return {"name": name, "path": block_path, "type": "kv", "items": [{"label": "value", "value": _cell(payload)}]}

    note = _cell(payload["note"]) if isinstance(payload.get("note"), str) else None
    unit = _cell(payload["unit"]) if isinstance(payload.get("unit"), str) else None
    caveat = _cell(payload["caveat"]) if isinstance(payload.get("caveat"), str) else None
    base = {"name": name, "path": block_path, "note": note, "unit": unit, "caveat": caveat}

    series = payload.get("series")
    if isinstance(series, dict):
        items, is_year_table = _stash_series_items(series)
        # 列头中文化：并集所有 item 的 values 键 → {rawKey: 中文}，前端优先用，缺失回退 raw。
        col_keys: set[str] = set()
        for it in items:
            col_keys.update(it.get("values", {}).keys())
        col_labels = {k: _humanize_label(k) for k in col_keys}
        extras = [
            _stash_block(str(k), v, f"{block_path}.{k}")
            for k, v in payload.items()
            if k not in ("note", "unit", "caveat", "series")
        ]
        return {
            **base,
            "type": "series_table" if is_year_table else "attr_table",
            "items": items,
            "col_labels": col_labels,
            "extras": extras,
        }

    # dict without series: text_dict / scalar_table / kv (mixed → kv preserves everything)
    text_items: list[dict] = []
    scalar_items: list[dict] = []
    sub_items: list[dict] = []
    has_string = has_scalar = has_other = False
    for k, v in payload.items():
        if k in ("note", "unit", "caveat"):
            continue
        if isinstance(v, str):
            has_string = True
            text_items.append({"label": str(k), "text": v})
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            has_scalar = True
            scalar_items.append({"label": str(k), "value": v})
        else:
            has_other = True
            sub_items.append(_stash_block(str(k), v, f"{block_path}.{k}"))
    if has_other or (has_string and has_scalar):
        return {**base, "type": "kv", "items": text_items + scalar_items + sub_items}
    if has_string:
        return {**base, "type": "text_dict", "items": text_items}
    if has_scalar:
        return {**base, "type": "scalar_table", "items": scalar_items}
    return {**base, "type": "kv", "items": []}


def _yaml1_stash_view(data: dict[str, Any]) -> list[dict]:
    stash = data.get("stash")
    if not isinstance(stash, dict):
        return []
    return [_stash_block(str(name), payload, f"stash.{name}") for name, payload in stash.items()]


def _display_warning(code: str, message: str, path: str | None = None, severity: str = "warning") -> dict[str, Any]:
    return {"code": code, "message": message, "path": path, "severity": severity}


def _display_enum(value: Any, allowed: set[str], default: str, field: str, path: str, warnings: list[dict[str, Any]]) -> str:
    text = _cell(value)
    if text in allowed:
        return text
    if text:
        warnings.append(_display_warning("invalid_display_enum", f"{path}.{field}={text} is not supported; fallback to {default}", path))
    return default


def _display_label_key(value: Any) -> str:
    return re.sub(r"[（）()及与和、/\\\s·_\-:：]", "", str(value)).lower()


def _revenue_segment_keys(revenue_view: dict[str, Any] | None) -> set[str]:
    segments = revenue_view.get("segments") if isinstance(revenue_view, dict) else []
    keys: set[str] = set()
    if not isinstance(segments, list):
        return keys
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for value in (segment.get("name"), segment.get("key")):
            normalized = _display_label_key(value)
            if normalized:
                keys.add(normalized)
    return keys


def _display_series_labels(block: dict[str, Any]) -> list[str]:
    items = block.get("items") if isinstance(block, dict) else []
    if not isinstance(items, list):
        return []
    labels: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("label"):
            labels.append(str(item["label"]))
    return labels


def _display_exact_segment_hit_count(block: dict[str, Any], segment_keys: set[str]) -> tuple[int, int]:
    labels = _display_series_labels(block)
    if not labels:
        return 0, 0
    hits = sum(1 for label in labels if _display_label_key(label) in segment_keys)
    return hits, len(labels)


def _display_dimension_from_name(name: str) -> str:
    if any(token in name for token in ("地区", "地域", "境内", "境外")):
        return "region"
    if any(token in name for token in ("渠道", "销售模式", "B2C", "B2B")):
        return "channel"
    if "子公司" in name:
        return "subsidiary"
    if any(token in name for token in ("产品", "品类", "单品")):
        return "product"
    if "客户" in name:
        return "customer"
    if any(token in name for token in ("分线", "业务线")):
        return "business_line"
    return "other"


def _display_metric_from_text(name: str, unit: str | None = None) -> str:
    text = f"{name} {unit or ''}".lower()
    if any(token in text for token in ("毛利率", "gpm", "margin")):
        return "gross_margin"
    if any(token in text for token in ("同比", "yoy")):
        return "yoy"
    if any(token in text for token in ("吨成本", "成本", "cost")):
        return "cost"
    if any(token in text for token in ("销量", "volume")):
        return "volume"
    if any(token in text for token in ("吨价", "单价", "price")):
        return "price"
    if any(token in text for token in ("收入", "revenue")):
        return "revenue"
    if any(token in text for token in ("率", "pct", "ratio", "%")):
        return "rate"
    if any(token in text for token in ("百万元", "金额", "amount", "mn")):
        return "amount"
    return "mixed"


def _display_status_from_block(block: dict[str, Any]) -> str:
    text = " ".join(_cell(block.get(key)) for key in ("name", "note", "caveat"))
    if any(token in text for token in ("弃用", "废弃", "deprecated")):
        return "deprecated"
    if any(token in text for token in ("核对", "校验", "check")):
        return "check_only"
    return "reference"


def _display_secondary_metrics(block: dict[str, Any]) -> list[str]:
    metrics = ["revenue"]
    extras = block.get("extras")
    if isinstance(extras, list):
        for extra in extras:
            if not isinstance(extra, dict):
                continue
            metric = _display_metric_from_text(str(extra.get("name") or ""), _cell(extra.get("unit")))
            if metric not in metrics:
                metrics.append(metric)
    return metrics


def _display_partial_metric_warnings(block: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    path = _cell(block.get("path"))
    labels = set(_display_series_labels(block))
    if not labels:
        return warnings
    extras = block.get("extras")
    if not isinstance(extras, list):
        return warnings
    for extra in extras:
        if not isinstance(extra, dict):
            continue
        metric_labels = set(_display_series_labels(extra))
        if metric_labels and metric_labels != labels:
            missing = sorted(labels - metric_labels)
            if missing:
                metric_name = str(extra.get("name") or "metric")
                warnings.append(_display_warning(
                    "partial_metric_disclosure",
                    f"{block.get('name')} 的 {metric_name} 仅披露部分项目，缺失：{', '.join(missing)}",
                    path,
                ))
    return warnings


def _infer_display_block(block: dict[str, Any], revenue_view: dict[str, Any] | None) -> dict[str, Any]:
    name = str(block.get("name") or "")
    path = _cell(block.get("path")) or f"stash.{name}"
    unit = _cell(block.get("unit"))
    status = _display_status_from_block(block)
    segment_keys = _revenue_segment_keys(revenue_view)
    hits, total = _display_exact_segment_hit_count(block, segment_keys)

    if status == "deprecated":
        return {
            "path": path,
            "role": "deprecated",
            "placement": "reference_tab",
            "dimension": _display_dimension_from_name(name),
            "metric": _display_metric_from_text(name, unit),
            "status": "deprecated",
            "duplicate_policy": "reference_only",
            "match_policy": "none",
            "title": name,
        }

    if status == "check_only":
        return {
            "path": path,
            "role": "check_only",
            "placement": "reference_tab",
            "dimension": _display_dimension_from_name(name),
            "metric": _display_metric_from_text(name, unit),
            "status": "check_only",
            "duplicate_policy": "reference_only",
            "match_policy": "none",
            "title": name,
        }

    if name.startswith("副拆分") or "副拆分" in name:
        dimension = _display_dimension_from_name(name)
        return {
            "path": path,
            "role": "secondary_split",
            "placement": "secondary_table",
            "dimension": dimension,
            "metric": "revenue",
            "metrics": _display_secondary_metrics(block),
            "status": "reference",
            "duplicate_policy": "show",
            "match_policy": "declared_path",
            "title": f"副拆分 · {name.replace('副拆分_', '').replace('副拆分', '').strip('_') or name}",
        }

    if block.get("type") == "series_table" and total and hits == total and any(token in name for token in ("分线", "业务线")):
        return {
            "path": path,
            "role": "primary_attachment",
            "placement": "model_table",
            "attach_to": "income.revenue.segments",
            "dimension": "business_line",
            "metric": _display_metric_from_text(name, unit),
            "status": "reference",
            "duplicate_policy": "prefer_derived_and_warn",
            "match_policy": "exact_or_declared_alias",
            "title": name,
        }

    return {
        "path": path,
        "role": "reference",
        "placement": "reference_tab",
        "dimension": _display_dimension_from_name(name),
        "metric": _display_metric_from_text(name, unit),
        "status": "reference",
        "duplicate_policy": "show",
        "match_policy": "none",
        "title": name,
    }


def _normalize_declared_display_block(raw: Any, warnings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        warnings.append(_display_warning("invalid_display_block", "display.blocks item is not an object"))
        return None
    path = _cell(raw.get("path")).strip()
    if not path:
        warnings.append(_display_warning("missing_display_path", "display.blocks item has no path"))
        return None
    role = _display_enum(raw.get("role"), DISPLAY_ROLES, "reference", "role", path, warnings)
    placement_default = "model_table" if role in {"primary_model", "primary_attachment"} else "secondary_table" if role == "secondary_split" else "reference_tab"
    block = {
        "path": path,
        "role": role,
        "placement": _display_enum(raw.get("placement"), DISPLAY_PLACEMENTS, placement_default, "placement", path, warnings),
        "dimension": _display_enum(raw.get("dimension"), DISPLAY_DIMENSIONS, "other", "dimension", path, warnings),
        "metric": _display_enum(raw.get("metric"), DISPLAY_METRICS, "mixed", "metric", path, warnings),
        "status": _display_enum(raw.get("status"), DISPLAY_STATUSES, "reference", "status", path, warnings),
        "duplicate_policy": _display_enum(raw.get("duplicate_policy"), DISPLAY_DUPLICATE_POLICIES, "show", "duplicate_policy", path, warnings),
        "match_policy": _display_enum(raw.get("match_policy"), DISPLAY_MATCH_POLICIES, "exact_or_declared_alias", "match_policy", path, warnings),
        "title": _cell(raw.get("title")) or path,
    }
    if raw.get("attach_to"):
        block["attach_to"] = _cell(raw.get("attach_to"))
    metrics = raw.get("metrics")
    if isinstance(metrics, list):
        block["metrics"] = [str(item) for item in metrics if str(item) in DISPLAY_METRICS]
    return block


def _yaml1_display_contract(data: dict[str, Any], revenue_view: dict[str, Any] | None, stash_view: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    declared = data.get("display") if isinstance(data, dict) else None
    blocks: list[dict[str, Any]] = []
    declared_paths: set[str] = set()
    declared_by_path: dict[str, dict[str, Any]] = {}

    if isinstance(declared, dict):
        raw_blocks = declared.get("blocks")
        if isinstance(raw_blocks, list):
            for raw in raw_blocks:
                block = _normalize_declared_display_block(raw, warnings)
                if block:
                    blocks.append(block)
                    declared_paths.add(block["path"])
                    declared_by_path[block["path"]] = block
        else:
            warnings.append(_display_warning("invalid_display_blocks", "display.blocks must be a list"))
        mode = "declared"
        primary_dimension = _display_enum(declared.get("primary_dimension"), DISPLAY_DIMENSIONS, "business_line", "primary_dimension", "display", warnings)
    else:
        mode = "inferred"
        primary_dimension = "business_line"

    if revenue_view and "income.revenue" not in declared_paths:
        blocks.insert(0, {
            "path": "income.revenue",
            "role": "primary_model",
            "placement": "model_table",
            "dimension": "business_line",
            "metric": "revenue",
            "status": "active",
            "duplicate_policy": "show",
            "match_policy": "declared_path",
            "title": "主拆分 · 业务线",
        })

    for stash_block in stash_view:
        path = _cell(stash_block.get("path"))
        if not path:
            continue
        declared_block = declared_by_path.get(path)
        if declared_block:
            if declared_block.get("role") in {"primary_attachment", "secondary_split"}:
                warnings.extend(_display_partial_metric_warnings(stash_block))
            continue
        inferred = _infer_display_block(stash_block, revenue_view)
        blocks.append(inferred)
        if inferred.get("role") in {"primary_attachment", "secondary_split"}:
            warnings.extend(_display_partial_metric_warnings(stash_block))

    return {
        "schema_version": DISPLAY_SCHEMA_VERSION,
        "mode": mode,
        "primary_dimension": primary_dimension,
        "blocks": blocks,
        "warnings": warnings,
    }


# ─────────────────────────── yaml1 assumptions view (universal knob grouping) ───────────────────────────
# Group knobs by defaults.yaml standard namespace prefix (universal, not company-specific).
# Absent paths naturally drop out (absent = falls back to yaml2 default).

ASSUMPTION_SECTION_DEFS = (
    ("gpm", "毛利率", ("income.gpm",)),
    ("cost_rates", "费用率", ("income.cost_rates.",)),
    (
        "below_op",
        "营业利润调节 / 营业外收支（绝对值）",
        ("income.cost_abs.", "income.operating_adjustments_abs.", "income.below_line_abs."),
    ),
    ("tax_minority", "税率 / 少数股东", ("income.effective_tax_rate", "income.minority_ratio")),
)
OVERRIDE_MARKERS = ("主动覆盖", "查证", "弃模型", "normalized", "主动收缩", "手拍")


def _yaml1_base_period(data: dict[str, Any]) -> str:
    meta = data.get("meta", {})
    if isinstance(meta, dict) and isinstance(meta.get("horizon"), list) and meta["horizon"]:
        try:
            return str(int(meta["horizon"][0]) - 1)
        except (TypeError, ValueError):
            return ""
    return ""


def _assumptions_terminal(term: Any) -> dict:
    if not isinstance(term, dict):
        return {}
    fade = term.get("fade") if isinstance(term.get("fade"), dict) else {}
    return {
        "explicit_end": term.get("explicit_end"),
        "to_year": fade.get("to_year"),
        "kind": fade.get("kind"),
        "target_growth": fade.get("target_growth"),
        "target_basis": fade.get("target_basis"),
        "fade_paths": [_humanize_path(p) for p in (fade.get("fade_paths") or [])],
        "hold_paths": [_humanize_path(p) for p in (fade.get("hold_paths") or [])],
        "perpetual_growth": term.get("perpetual_growth"),
        "src": _cell(term.get("src")) or None,
    }


def _assumptions_traceability(data: dict[str, Any]) -> list[dict]:
    """溯源附注 is a skill-defined standard stash block (yaml1compiler_v5 §6.2)."""
    stash = data.get("stash")
    if not isinstance(stash, dict):
        return []
    src = stash.get("溯源附注")
    if not isinstance(src, dict):
        return []
    return [{"name": str(k), "text": v} for k, v in src.items() if isinstance(v, str)]


def _yaml1_assumptions_view(data: dict[str, Any], years: list[str]) -> dict:
    skip = {"meta", "terminal", "stash", "income.revenue", "display"}
    by_section: dict[str, list[dict]] = {key: [] for key, _, _ in ASSUMPTION_SECTION_DEFS}
    other: list[dict] = []
    for path, payload in data.items():
        if path in skip or not isinstance(payload, dict):
            continue
        values = payload.get("values")
        if not isinstance(values, list):
            continue
        src = _cell(payload.get("src"))
        knob = {
            "path": path,
            "src": src,
            "values": [_as_float(v) for v in values],
            "note": _cell(payload.get("note")) or None,
            "is_override": any(m in src for m in OVERRIDE_MARKERS),
        }
        placed = False
        for key, _, prefixes in ASSUMPTION_SECTION_DEFS:
            if any(path == p or path.startswith(p) for p in prefixes):
                by_section[key].append(knob)
                placed = True
                break
        if not placed:
            other.append(knob)
    sections = [
        {"key": key, "title": title, "knobs": by_section[key]}
        for key, title, _ in ASSUMPTION_SECTION_DEFS
        if by_section[key]
    ]
    if other:
        sections.append({"key": "other", "title": "其他覆盖", "knobs": other})
    return {
        "years": years,
        "base_period": _yaml1_base_period(data),
        "sections": sections,
        "terminal": _assumptions_terminal(data.get("terminal")),
        "traceability": _assumptions_traceability(data),
    }


def _pointer_escape(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _json_pointer(*segments: Any) -> str:
    return "/" + "/".join(_pointer_escape(segment) for segment in segments)


def _decode_pointer_segment(segment: str) -> str:
    return segment.replace("~1", "/").replace("~0", "~")


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _assumption_unit(path: str, payload: dict[str, Any] | None = None) -> str:
    unit = str((payload or {}).get("unit", "")).lower()
    if unit in {"pct", "ratio", "yoy", "percent"}:
        return "pct"
    lowered = path.lower()
    if any(token in lowered for token in ("yoy", "rate", "ratio", "gpm", "margin", "growth")):
        return "pct"
    if any(token in lowered for token in ("_abs", "abs_", "below_line_abs", "cost_abs", "million")):
        return "abs_mn"
    return "number"


def _assumption_format(unit: str) -> str:
    if unit == "pct":
        return "percent"
    if unit == "abs_mn":
        return "integer"
    return "number"


def _assumption_group(path: str) -> str:
    if path.startswith("income.revenue."):
        return "revenue_driver"
    if path.startswith("terminal."):
        return "terminal"
    if path.startswith("income."):
        return "standard_knob"
    return "other"


def _values_cells(values: list[Any], years: list[str], pointer_segments: list[Any]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        year = years[index] if index < len(years) else f"Y{index + 1}"
        cells.append(
            {
                "year": str(year),
                "pointer": _json_pointer(*pointer_segments, index),
                "value": float(value) if _is_numeric(value) else None,
            }
        )
    return cells


def _editable_top_level_value_knobs(data: dict[str, Any], years: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = {"meta", "terminal", "stash", "income.revenue", "display"}
    for path, payload in data.items():
        if path in skip or not isinstance(payload, dict):
            continue
        values = payload.get("values")
        if not isinstance(values, list):
            continue
        unit = _assumption_unit(path, payload)
        rows.append(
            {
                "id": f"top:{path}",
                "label": _humanize_path(path),
                "group": _assumption_group(path),
                "path": path,
                "family": _cell(payload.get("kind")) or None,
                "unit": unit,
                "format": _assumption_format(unit),
                "source": "yaml1_top_level_values",
                "cells": _values_cells(values, years, [path, "values"]),
                "note": _cell(payload.get("note")) or None,
                "src": _cell(payload.get("src")) or None,
            }
        )
    return rows


def _revenue_node_label(node_key: str, node: dict[str, Any]) -> str:
    label = node.get("label")
    if isinstance(label, str) and label:
        return label
    src = node.get("src")
    if isinstance(src, str) and src.startswith("#") and len(src) > 1:
        return src[1:]
    return str(node_key)


def _editable_revenue_driver_knobs(data: dict[str, Any], years: list[str]) -> list[dict[str, Any]]:
    revenue = data.get("income.revenue")
    if not isinstance(revenue, dict):
        return []
    rows: list[dict[str, Any]] = []

    def add_values(
        *,
        label: str,
        path: str,
        pointer_segments: list[Any],
        values: Any,
        family: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(values, list):
            return
        unit = _assumption_unit(path, payload)
        rows.append(
            {
                "id": f"revenue:{path}",
                "label": label,
                "group": "revenue_driver",
                "path": path,
                "family": family,
                "unit": unit,
                "format": _assumption_format(unit),
                "source": "yaml1_revenue_driver",
                "cells": _values_cells(values, years, pointer_segments),
                "note": _cell((payload or {}).get("note")) or None,
                "src": _cell((payload or {}).get("src")) or None,
            }
        )

    def walk(node: Any, pointer_segments: list[Any], label_parts: list[str], path_parts: list[str]) -> None:
        if not isinstance(node, dict):
            return
        segments = node.get("segments")
        if isinstance(segments, dict):
            for key, child in segments.items():
                child_label = _revenue_node_label(str(key), child) if isinstance(child, dict) else str(key)
                walk(
                    child,
                    [*pointer_segments, "segments", key],
                    [*label_parts, child_label],
                    [*path_parts, str(key)],
                )

        factors = node.get("factors")
        if isinstance(factors, list):
            for index, factor in enumerate(factors):
                if not isinstance(factor, dict):
                    continue
                key = str(factor.get("key") or f"factor_{index + 1}")
                label = str(factor.get("label") or _humanize_label(key))
                projection = factor.get("projection")
                if isinstance(projection, dict):
                    values = projection.get("values")
                    add_values(
                        label=" · ".join([*label_parts, label]),
                        path=".".join(["income", "revenue", *path_parts, key]),
                        pointer_segments=[*pointer_segments, "factors", index, "projection", "values"],
                        values=values,
                        family=_cell(projection.get("kind")) or None,
                        payload=projection,
                    )

        projection = node.get("projection")
        if isinstance(projection, dict):
            add_values(
                label=" · ".join([*label_parts, _cell(projection.get("kind")) or "projection"]),
                path=".".join(["income", "revenue", *path_parts, "projection"]),
                pointer_segments=[*pointer_segments, "projection", "values"],
                values=projection.get("values"),
                family=_cell(projection.get("kind")) or None,
                payload=projection,
            )

        knobs = node.get("knobs")
        if isinstance(knobs, dict):
            for key, values in knobs.items():
                add_values(
                    label=" · ".join([*label_parts, _humanize_label(key)]),
                    path=".".join(["income", "revenue", *path_parts, str(key)]),
                    pointer_segments=[*pointer_segments, "knobs", key],
                    values=values,
                    family=str(key),
                    payload={"unit": "pct" if "yoy" in str(key).lower() or "margin" in str(key).lower() else None},
                )

    walk(revenue, ["income.revenue"], [], [])
    return rows


def _editable_terminal_knobs(data: dict[str, Any]) -> list[dict[str, Any]]:
    terminal = data.get("terminal")
    if not isinstance(terminal, dict):
        return []
    rows: list[dict[str, Any]] = []
    scalar_defs = [
        ("perpetual_growth", "永续增速", ["terminal", "perpetual_growth"], "pct"),
        ("explicit_end", "显式期末", ["terminal", "explicit_end"], "number"),
    ]
    fade = terminal.get("fade") if isinstance(terminal.get("fade"), dict) else {}
    if isinstance(fade, dict) and "to_year" in fade:
        scalar_defs.append(("fade.to_year", "衰减至", ["terminal", "fade", "to_year"], "number"))
    for path, label, pointer_segments, unit in scalar_defs:
        target: Any = data
        for segment in pointer_segments:
            if not isinstance(target, dict) or segment not in target:
                target = None
                break
            target = target[segment]
        if not _is_numeric(target):
            continue
        rows.append(
            {
                "id": f"terminal:{path}",
                "label": label,
                "group": "terminal",
                "path": f"terminal.{path}",
                "family": "terminal",
                "unit": unit,
                "format": _assumption_format(unit),
                "source": "yaml1_terminal",
                "cells": [{"year": "terminal", "pointer": _json_pointer(*pointer_segments), "value": float(target)}],
                "note": None,
                "src": _cell(terminal.get("src")) or None,
            }
        )
    return rows


def _editable_assumptions(data: dict[str, Any]) -> list[dict[str, Any]]:
    years = _years_from_yaml1(data)
    rows: list[dict[str, Any]] = []
    rows.extend(_editable_top_level_value_knobs(data, years))
    rows.extend(_editable_revenue_driver_knobs(data, years))
    rows.extend(_editable_terminal_knobs(data))
    return rows


def _editable_cells_by_pointer(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        cell["pointer"]: {**cell, "assumption": row}
        for row in _editable_assumptions(data)
        for cell in row.get("cells", [])
    }


def _pointer_target(root: Any, pointer: str) -> tuple[Any, str | int]:
    if not pointer.startswith("/"):
        raise HTTPException(status_code=400, detail=f"Invalid pointer: {pointer}")
    parts = [_decode_pointer_segment(part) for part in pointer.strip("/").split("/") if part != ""]
    if not parts:
        raise HTTPException(status_code=400, detail="Pointer cannot target document root")
    target = root
    for part in parts[:-1]:
        if isinstance(target, list):
            try:
                target = target[int(part)]
            except (ValueError, IndexError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid list pointer segment: {part}") from exc
        elif isinstance(target, dict):
            if part not in target:
                raise HTTPException(status_code=400, detail=f"Pointer segment not found: {part}")
            target = target[part]
        else:
            raise HTTPException(status_code=400, detail=f"Pointer walks through scalar at: {part}")
    last = parts[-1]
    if isinstance(target, list):
        try:
            return target, int(last)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid list pointer segment: {last}") from exc
    if isinstance(target, dict):
        return target, last
    raise HTTPException(status_code=400, detail=f"Pointer targets scalar parent: {pointer}")


def _values_match(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _apply_assumption_patches(data: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    patched = copy.deepcopy(data)
    editable = _editable_cells_by_pointer(data)
    for patch in patches:
        pointer = str(patch.get("pointer") or "")
        if pointer not in editable:
            raise HTTPException(status_code=400, detail=f"Unsupported editable pointer: {pointer}")
        old_value = patch.get("old_value")
        new_value = patch.get("new_value")
        expected_old = editable[pointer].get("value")
        if not _values_match(old_value, expected_old):
            raise HTTPException(
                status_code=409,
                detail=f"Assumption value changed since preview: {pointer}",
            )
        if not _is_numeric(new_value):
            raise HTTPException(status_code=400, detail=f"Assumption value must be numeric: {pointer}")
        parent, key = _pointer_target(patched, pointer)
        current = parent[key]
        if not _values_match(current, expected_old):
            raise HTTPException(
                status_code=409,
                detail=f"Assumption value changed since preview: {pointer}",
            )
        parent[key] = float(new_value)
    return patched


def _format_patch_value(value: Any) -> str:
    if value is None:
        return "null"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _format_frontend_edit_prompt(
    *,
    company_name: str,
    core_path: str | None,
    yaml1_path: str | None,
    yaml1_data: dict[str, Any],
    patches: list[dict[str, Any]],
    preview_summary: dict[str, Any] | None = None,
) -> str:
    editable = _editable_cells_by_pointer(yaml1_data)
    lines = [
        f"/frontend-edit 进入前端编辑模式，基于当前核心假设.md 更新 {company_name} 的假设并更新DCF",
        "",
        "关键纪律：",
        "- 修改人话权威层 `核心假设.md`（正文预测描述 + 末尾 knobs 块）。",
        "- 保持原有结构、历史事实、来源说明、业务线命名和口径说明。",
        "- 同步定点更新 yaml1 对应旋钮值（小改不跑 compiler）。",
        "- 跑 forecast 覆盖 Agent/forecast/。",
        "",
        f"核心假设路径：{core_path or '未找到'}",
        f"当前 yaml1 路径：{yaml1_path or '未找到'}",
        "",
        "前端试算变更：",
    ]
    for patch in patches:
        pointer = str(patch.get("pointer") or "")
        cell = editable.get(pointer, {})
        assumption = cell.get("assumption", {})
        label = assumption.get("label") or pointer
        path = assumption.get("path") or pointer
        year = cell.get("year") or ""
        old_value = _format_patch_value(patch.get("old_value"))
        new_value = _format_patch_value(patch.get("new_value"))
        lines.append(f"- {label} ({path}) {year}: {old_value} -> {new_value}")
    return "\n".join(lines)


def _dcf_detail_from_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        period = row.get("period")
        try:
            period_int = int(float(period))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "period": period_int,
                "fcff": _number_or_none(row.get("fcff")),
                "discount_factor": _number_or_none(row.get("discount_factor")),
                "pv_fcff": _number_or_none(row.get("pv_fcff")),
                "nopat": _number_or_none(row.get("nopat")),
                "da": _number_or_none(row.get("da")),
                "capex": _number_or_none(row.get("capex")),
                "delta_nwc": _number_or_none(row.get("delta_nwc")),
            }
        )
    return rows


def _ratio_or_none(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den


def _yoy_values(values: dict[str, float | None], years: list[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for index, year in enumerate(years):
        current = values.get(year)
        previous = values.get(years[index - 1]) if index > 0 else None
        out[year] = _ratio_or_none(current - previous, previous) if current is not None and previous is not None else None
    return out


def _make_result_row(field: str, label: str, values: dict[str, float | None]) -> dict[str, Any]:
    return {
        "field": field,
        "label": label,
        "display_label": label,
        "category": "preview_result",
        "category_label": "试算结果",
        "role": "normal",
        "display_role": "primary",
        "is_technical": False,
        "technical_reason": None,
        "combo_of": [],
        "level": 1,
        "is_zero": not _nonzero(values),
        "values": values,
    }


def _result_rows_from_statement_sheet(sheet: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not sheet:
        return []
    rows_by_field = {row.get("field"): row for row in sheet.get("rows", [])}
    years = [str(year) for year in sheet.get("years", [])]

    def values(field: str) -> dict[str, float | None]:
        row = rows_by_field.get(field)
        raw = row.get("values", {}) if isinstance(row, dict) else {}
        return {year: _number_or_none(raw.get(year)) for year in years}

    revenue = values("revenue")
    net_income = values("n_income")
    attr_net_income = values("n_income_attr_p")
    net_margin = {year: _ratio_or_none(net_income.get(year), revenue.get(year)) for year in years}
    return [
        _make_result_row("revenue", "营业收入", revenue),
        _make_result_row("revenue_yoy", "同比增长", _yoy_values(revenue, years)),
        _make_result_row("n_income_attr_p", "归母净利润", attr_net_income),
        _make_result_row("n_income", "净利润", net_income),
        _make_result_row("net_margin", "净利率", net_margin),
        _make_result_row("n_income_yoy", "净利润同比", _yoy_values(net_income, years)),
    ]


def _preview_response(
    cleaned_report: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    statement_sheets = [
        sheet
        for sheet in (
            _statement_rows_from_dataframe("forecast_is.csv", result["income_statement"], "preview:forecast_is.csv"),
            _statement_rows_from_dataframe("forecast_bs.csv", result["balance_sheet"], "preview:forecast_bs.csv"),
            _statement_rows_from_dataframe("forecast_cf.csv", result["cash_flow"], "preview:forecast_cf.csv"),
        )
        if sheet
    ]
    is_sheet = next((sheet for sheet in statement_sheets if sheet.get("key") == "is"), None)
    derived_metrics = build_derived_metrics_from_frames(
        income_statement=result["income_statement"],
        balance_sheet=result["balance_sheet"],
        cash_flow=result["cash_flow"],
        dcf_summary=result["summary"],
        dcf_detail=result["dcf"],
        source_files={"preview": "assumption-preview"},
        warnings=[],
    )
    return {
        "dcf_summary": result["summary"],
        "derived_metrics": derived_metrics,
        "dcf_detail": _dcf_detail_from_dataframe(result["dcf"]),
        "statement_sheets": statement_sheets,
        "result_rows": _result_rows_from_statement_sheet(is_sheet),
        "warnings": cleaned_report.get("warnings", []),
        "errors": cleaned_report.get("errors", []),
    }


def _model_dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _presentation_cache_path(company_dir: Path) -> Path:
    return modelking_dir(company_dir) / "yaml1_presentation.json"


def _yaml1_presentation_cache(company_dir: Path) -> dict[str, Any] | None:
    path = _presentation_cache_path(company_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(_read_text(path))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_yaml1_presentation_cache(company_dir: Path, presentation: dict[str, Any]) -> None:
    path = _presentation_cache_path(company_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(presentation, ensure_ascii=False, indent=2), encoding="utf-8")


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _yaml1_presentation_context(company_dir: Path, yaml1_path: Path, revenue_view: dict[str, Any] | None, sheets: list[dict[str, Any]]) -> dict[str, Any]:
    yaml1_data = _read_yaml(yaml1_path)
    typed_paths: list[dict[str, Any]] = []
    for path, payload in yaml1_data.items():
        if isinstance(payload, dict):
            typed_paths.append(
                {
                    "path": path,
                    "kind": payload.get("kind") or payload.get("type") or payload.get("rollup"),
                    "source": payload.get("src"),
                    "note": _truncate_text(_cell(payload.get("note")), 600),
                }
            )

    return {
        "company": _company_summary(company_dir),
        "yaml1_path": _relative(yaml1_path),
        "yaml1_revenue_view": revenue_view,
        "yaml1_sheets": [
            {
                "name": sheet.get("name"),
                "description": sheet.get("description"),
                "columns": sheet.get("columns"),
                "sample_rows": sheet.get("rows", [])[:12],
            }
            for sheet in sheets
        ],
        "yaml1_typed_paths": typed_paths,
        "yaml1_excerpt": _truncate_text(_read_text(yaml1_path), 20000),
    }


def _presentation_provider_order() -> list[str]:
    load_env(BASE_DIR / ".env")
    providers = []
    if llm_api_key("glm"):
        providers.append("glm")
    if llm_api_key("kimi"):
        providers.append("kimi")
    return providers or ["glm", "kimi"]


def _json_from_llm_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("presentation response must be a JSON object")
    return parsed


def _fallback_presentation(context: dict[str, Any], reason: str) -> dict[str, Any]:
    company = context.get("company", {})
    revenue = context.get("yaml1_revenue_view") or {}
    segments = revenue.get("segments") if isinstance(revenue, dict) else []
    return {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "mode": "fallback",
        "provider": None,
        "model": None,
        "title": f"{company.get('name', '公司')}业务假设",
        "subtitle": "未能调用大模型，暂按确定性收入拆分展示。",
        "business_question": "这份 YAML1 主要覆盖哪些业务判断？",
        "display_strategy": "按已结构化的收入 decomposition 展示业务线和驱动假设。",
        "primary_dimension": "业务线",
        "segment_order": [item.get("name") for item in segments if isinstance(item, dict) and item.get("name")],
        "driver_labels": {
            "volume_yoy": "销量增长",
            "price_yoy": "价格变化",
            "revenue_yoy": "收入增长",
        },
        "insights": [reason],
        "risks": [],
        "source_paths": ["income.revenue", "income.revenue.segments"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _validate_presentation_schema(parsed: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    allowed_driver_labels = parsed.get("driver_labels")
    if not isinstance(allowed_driver_labels, dict):
        allowed_driver_labels = {}
    segment_order = parsed.get("segment_order")
    if not isinstance(segment_order, list):
        segment_order = []
    insights = parsed.get("insights")
    if not isinstance(insights, list):
        insights = []
    risks = parsed.get("risks")
    if not isinstance(risks, list):
        risks = []
    source_paths = parsed.get("source_paths")
    if not isinstance(source_paths, list):
        source_paths = []

    return {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "mode": "llm",
        "provider": provider,
        "model": model,
        "title": str(parsed.get("title") or "业务假设"),
        "subtitle": str(parsed.get("subtitle") or "由 YAML1 生成的业务展示方案。"),
        "business_question": str(parsed.get("business_question") or "这份 YAML1 在表达什么业务判断？"),
        "display_strategy": str(parsed.get("display_strategy") or "按业务驱动展示。"),
        "primary_dimension": str(parsed.get("primary_dimension") or "业务线"),
        "segment_order": [str(item) for item in segment_order if item],
        "driver_labels": {str(key): str(value) for key, value in allowed_driver_labels.items()},
        "insights": [str(item) for item in insights[:6] if item],
        "risks": [str(item) for item in risks[:6] if item],
        "source_paths": [str(item) for item in source_paths[:20] if item],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _call_yaml1_presentation_llm(context: dict[str, Any]) -> dict[str, Any]:
    system = (
        "你是买方投研工作台 ModelKing 的展示编排器。你的任务不是算账、不是修改 YAML、不是补数，"
        "而是阅读 yaml1 的结构，决定前端应该如何给不懂代码的投研负责人展示这家公司。"
        "只能引用输入中已有的路径和事实；不得编造任何数值。输出必须是 JSON object。"
    )
    user = json.dumps(
        {
            "task": "为 YAML1 生成前端展示 schema。优先识别这家公司最自然的业务维度，例如产品线、区域、渠道、量价、产能、客户数、ARPU、息差等。",
            "required_json_schema": {
                "title": "短标题，例如 收入模型 / 产品线假设 / 生息资产模型",
                "subtitle": "给业务读者看的说明，不出现 YAML jargon",
                "business_question": "这一页回答的核心业务问题",
                "display_strategy": "为什么这样组织展示",
                "primary_dimension": "主展示维度",
                "segment_order": ["建议前端展示的业务线名称顺序，必须来自输入名称"],
                "driver_labels": {"volume_yoy": "销量增长", "price_yoy": "价格变化"},
                "insights": ["2-6 条业务读法，不要编数，只能基于结构和方向"],
                "risks": ["可选，展示层应提示的假设张力"],
                "source_paths": ["本展示依赖的 yaml1 路径"],
            },
            "constraints": [
                "不要输出 Markdown。",
                "不要输出代码。",
                "不要创造输入中不存在的业务线或数值。",
                "不要改变 DCF 参数；这只是展示 schema。",
                "如果无法泛化，就说明采用的 fallback 展示方式。",
            ],
            "context": context,
        },
        ensure_ascii=False,
    )

    errors: list[str] = []
    for provider in _presentation_provider_order():
        api_key = llm_api_key(provider)
        if not api_key:
            errors.append(f"{provider}: API key missing")
            continue
        base_url = llm_base_url(provider)
        model = llm_model(provider)
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": int(os.environ.get("YAML1_PRESENTATION_MAX_TOKENS", os.environ.get("LLM_MAX_TOKENS", "4096"))),
            "response_format": {"type": "json_object"},
        }
        if provider != "kimi":
            body["temperature"] = float(os.environ.get("YAML1_PRESENTATION_TEMPERATURE", os.environ.get("LLM_TEMPERATURE", "0.2")))
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=llm_timeout_seconds(provider),
            )
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            parsed = _json_from_llm_text(text)
            presentation = _validate_presentation_schema(parsed, provider, str(data.get("model") or model))
            presentation["_usage"] = data.get("usage", {})
            return presentation
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI as generation status
            errors.append(f"{provider}: {type(exc).__name__}: {exc}")
    return _fallback_presentation(context, "大模型展示编排失败：" + "；".join(errors))


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _material_files(company_dir: Path) -> list[dict[str, Any]]:
    roots = [
        active_vore_dir(company_dir),
        collection_dir(company_dir),
        important_files_dir(company_dir),
        research_reports_dir(company_dir),
        meeting_notes_dir(company_dir),
        annual_reports_dir(company_dir),
        quarterly_reports_dir(company_dir),
    ]
    files: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "path": _relative(path),
                    "kind": path.suffix.lstrip(".") or "file",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    return files[:300]


def _annual_revenue_breakdown(company_dir: Path) -> list[dict[str, Any]]:
    breakdown_dir = official_breakdowns_dir(company_dir)
    path = breakdown_dir / "business_revenue_breakdown_all.csv"
    if not path.exists():
        path = breakdown_dir / "business_revenue_breakdown.csv"
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for row in _read_csv_rows(path):
        rows.append(
            {
                "year": int(_as_float(row.get("year"))),
                "period": row.get("period") or f"{int(_as_float(row.get('year')))}A",
                "period_type": row.get("period_type") or "annual",
                "period_label": row.get("period_label") or "年度",
                "dimension": row.get("dimension") or "",
                "dimension_label": row.get("dimension_label") or "",
                "item_name": row.get("item_name") or "",
                "revenue_yuan": _number_or_none(row.get("revenue_yuan")),
                "revenue_pct": _number_or_none(row.get("revenue_pct")),
                "revenue_yoy_pct": _number_or_none(row.get("revenue_yoy_pct")),
                "cost_yuan": _number_or_none(row.get("cost_yuan")),
                "cost_yoy_pct": _number_or_none(row.get("cost_yoy_pct")),
                "gross_margin_pct": _number_or_none(row.get("gross_margin_pct")),
                "gross_margin_change": row.get("gross_margin_change") or "",
                "source_table": row.get("source_table") or "",
                "source_line": int(_as_float(row.get("source_line"))),
                "confidence": row.get("confidence") or "",
                "source_file": row.get("source_file") or "",
            }
        )

    dimension_rank = {"product": 0, "industry": 1, "region": 2, "sales_model": 3}
    rows.sort(
        key=lambda item: (
            -int(item["year"]),
            0 if str(item.get("period_type")) == "annual" else 1,
            dimension_rank.get(str(item["dimension"]), 99),
            str(item["source_table"]),
            -(float(item["revenue_yuan"]) if item.get("revenue_yuan") is not None else 0.0),
        )
    )
    return rows


def _company_summary(company_dir: Path) -> dict[str, Any]:
    defaults_path = company_defaults_path(company_dir)
    defaults = _read_yaml(defaults_path)
    meta = _read_meta(company_dir)
    forecast = _forecast_summary(company_dir)
    manifest = _manifest(company_dir)
    yaml1_path = _latest_yaml1(company_dir)
    core_path = _core_assumption(company_dir)
    market = defaults.get("market", {}) if isinstance(defaults.get("market"), dict) else {}
    model = defaults.get("model", {}) if isinstance(defaults.get("model"), dict) else {}
    ticker = meta.get("ticker") or _plain(defaults.get("ticker")) or _plain(market.get("ticker"))
    name = meta.get("name") or _plain(defaults.get("name")) or _plain(market.get("name")) or company_dir.name.rsplit("_", 1)[0]
    code = str(ticker).split(".")[0] if ticker else company_dir.name.rsplit("_", 1)[-1]
    forecast_dir = company_forecast_dir(company_dir)
    updated_at = None
    if (forecast_dir / "run_manifest.json").exists():
        updated_at = (forecast_dir / "run_manifest.json").stat().st_mtime
    elif forecast_dir.exists():
        updated_at = forecast_dir.stat().st_mtime
    market_cap = forecast.get("market_cap") if isinstance(forecast, dict) else None
    industry = _read_industry().get("companies", {}).get(code) or _read_industry().get("companies", {}).get(company_dir.name) or None
    return {
        "id": company_dir.name,
        "name": str(name),
        "code": code,
        "industry": industry,
        "ticker": ticker,
        "path": _relative(company_dir),
        "has_yaml1": yaml1_path is not None,
        "has_defaults": defaults_path.exists(),
        "has_forecast": forecast_dir.exists(),
        "has_core_assumption": core_path is not None,
        "has_materials": any(root.exists() for root in (
            active_vore_dir(company_dir),
            collection_dir(company_dir),
            important_files_dir(company_dir),
            research_reports_dir(company_dir),
            meeting_notes_dir(company_dir),
            annual_reports_dir(company_dir),
            quarterly_reports_dir(company_dir),
        )),
        "market_cap": market_cap,
        "per_share_value": forecast.get("per_share_value"),
        "base_period": forecast.get("base_period") or _plain(model.get("base_year")),
        "forecast_years": forecast.get("forecast_years") or _plain(model.get("forecast_years")),
        "warnings_count": manifest.get("warnings_count"),
        "backtest_status": manifest.get("backtest_status"),
        "updated_at": updated_at,
    }


class SettingsPayload(BaseModel):
    companies_dir: str | None = None
    env: dict[str, str] | None = None
    create_companies_dir: bool = False


class IndustryPayload(BaseModel):
    sectors_order: list[str]
    companies: dict[str, str]


_DEFAULT_INDUSTRY: dict[str, Any] = {"version": 1, "sectors_order": [], "companies": {}}


def _read_industry() -> dict[str, Any]:
    if not INDUSTRY_JSON_PATH.exists():
        return copy.deepcopy(_DEFAULT_INDUSTRY)
    try:
        data = json.loads(INDUSTRY_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(_DEFAULT_INDUSTRY)
    if not isinstance(data, dict):
        return copy.deepcopy(_DEFAULT_INDUSTRY)
    data.setdefault("version", 1)
    data.setdefault("sectors_order", [])
    data.setdefault("companies", {})
    return data


def _write_industry(data: dict[str, Any]) -> None:
    INDUSTRY_JSON_PATH.write_text(
        json.dumps({"version": 1, "sectors_order": data.get("sectors_order", []), "companies": data.get("companies", {})}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


@app.get("/api/industry")
def read_industry() -> dict[str, Any]:
    return _read_industry()


@app.put("/api/industry")
def update_industry(payload: IndustryPayload) -> dict[str, Any]:
    sectors_order = [s.strip() for s in payload.sectors_order if s.strip()]
    companies = {k.strip(): v.strip() for k, v in payload.companies.items() if k.strip() and v.strip()}
    data = {"version": 1, "sectors_order": sectors_order, "companies": companies}
    try:
        _write_industry(data)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入 industry.json 失败: {exc}") from exc
    return data


@app.get("/api/settings")
def read_settings() -> dict[str, Any]:
    return app_config.settings_payload()


@app.put("/api/settings")
def update_settings(payload: SettingsPayload) -> dict[str, Any]:
    try:
        return app_config.save_settings(
            companies_dir=payload.companies_dir,
            env=payload.env,
            create_companies_dir=payload.create_companies_dir,
        )
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/settings/validate")
def validate_settings(payload: SettingsPayload) -> dict[str, Any]:
    path = Path(payload.companies_dir).expanduser().resolve() if payload.companies_dir else app_config.get_companies_dir()
    return app_config.validate_companies_dir(path)


@app.get("/api/companies")
def list_companies() -> list[dict[str, Any]]:
    return [_company_summary(path) for path in _company_dirs()]


@app.get("/api/home/folder-overview")
def home_folder_overview() -> list[dict[str, Any]]:
    now = time.time()
    cached = _folder_overview_cache["rows"]
    if cached is not None and now - _folder_overview_cache["ts"] < _FOLDER_OVERVIEW_TTL:
        return cached
    out: list[dict[str, Any]] = []
    for company_dir in _company_dirs():
        meta = _read_meta(company_dir)
        name = meta.get("name") or company_dir.name.rsplit("_", 1)[0]
        code = company_dir.name.rsplit("_", 1)[-1]
        try:
            signals = _folder_overview_signals(company_dir)
        except Exception as exc:  # 单家公司异常不拖垮整表
            signals = None
            error = str(exc)
        else:
            error = None
        out.append({
            "company_id": company_dir.name,
            "name": str(name),
            "code": code,
            "signals": signals,
            "error": error,
        })
    _folder_overview_cache["rows"] = out
    _folder_overview_cache["ts"] = now
    return out


@app.get("/api/companies/{company_id}")
def read_company(company_id: str) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    summary = _company_summary(company_dir)
    yaml1_path = _latest_yaml1(company_dir)
    core_path = _core_assumption(company_dir)
    forecast_dir = company_forecast_dir(company_dir)
    yaml1_data = _read_yaml(yaml1_path) if yaml1_path else {}
    yaml1_years = _years_from_yaml1(yaml1_data) if yaml1_data else []
    yaml1_revenue_view = _yaml1_revenue_view(yaml1_path)
    yaml1_stash_view = _yaml1_stash_view(yaml1_data) if yaml1_data else []
    tables = []
    for name in FORECAST_TABLES:
        path = forecast_dir / name
        if path.exists():
            tables.append({"name": name, "path": _relative(path), "csv": _csv_preview(path)})
    return {
        "summary": summary,
        "core_assumption_md": _read_text(core_path) if core_path else None,
        "yaml1_path": _relative(yaml1_path) if yaml1_path else None,
        "yaml1_text": _read_text(yaml1_path) if yaml1_path else None,
        "yaml1_revenue_view": yaml1_revenue_view,
        "yaml1_sheets": _yaml1_sheets(yaml1_path),
        "yaml1_stash_view": yaml1_stash_view,
        "yaml1_display_contract": _yaml1_display_contract(yaml1_data, yaml1_revenue_view, yaml1_stash_view) if yaml1_data else None,
        "yaml1_assumptions_view": _yaml1_assumptions_view(yaml1_data, yaml1_years) if yaml1_data else None,
        "editable_assumptions": _editable_assumptions(yaml1_data) if yaml1_data else [],
        "yaml1_presentation": _yaml1_presentation_cache(company_dir),
        "dcf_summary": _forecast_summary(company_dir) or None,
        "derived_metrics": _derived_metrics(company_dir),
        "rating_report": app_config.rating_report_year_config(),
        "manifest": _manifest(company_dir) or None,
        "tables": tables,
        "statement_sheets": _statement_sheets(company_dir),
        "full_statement_sheets": _full_statement_sheets(company_dir),
        "dcf_detail": _dcf_detail(company_dir),
        "quarterly_view": _optional_quarterly_for_company(company_dir, summary=summary),
        "annual_revenue_breakdown": _annual_revenue_breakdown(company_dir),
        "materials": _material_files(company_dir),
        "da_view": _da_view(company_dir, base_period=_base_period_for_company(company_dir)),
    }


@app.post("/api/companies/{company_id}/forecast")
def regenerate_forecast(company_id: str) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    summary = _company_summary(company_dir)
    ticker = summary.get("ticker")
    if not ticker:
        raise HTTPException(status_code=400, detail="defaults.yaml does not provide ticker")
    yaml1_path = _latest_yaml1(company_dir)
    if not yaml1_path:
        raise HTTPException(status_code=404, detail="yaml1_*.yaml was not found")
    try:
        run = run_company_forecast(
            yaml1_path=yaml1_path,
            defaults_path=company_defaults_path(company_dir),
            clean_annual_path=company_db_path(company_dir),
            output_dir=company_forecast_dir(company_dir),
        )
    except StaleAssumptionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_assumption_requires_annual_update",
                "message": str(exc),
                "status": exc.status.as_dict(),
            },
        ) from exc
    except FidelityGateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "yaml1_fidelity_gate_block",
                "message": str(exc),
                "findings": exc.findings,
            },
        ) from exc
    return {
        "ok": True,
        "stdout": f"Written forecast: {run.output_dir}\nPer-share value: {run.summary['per_share_value']}",
        "stderr": "",
    }


def _required_float(value: Any, label: str) -> float:
    parsed = _number_or_none(_plain(value))
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"{label} is missing")
    return parsed


def _optional_float(value: Any) -> float | None:
    return _number_or_none(_plain(value))


def _forecast_revenue_by_period(company_dir: Path) -> dict[int, float]:
    rows = _read_csv_rows(company_forecast_dir(company_dir) / "forecast_is.csv")
    out: dict[int, float] = {}
    for row in rows:
        period = row.get("period")
        revenue = _number_or_none(row.get("revenue"))
        if not period or revenue is None:
            continue
        try:
            out[int(float(period))] = revenue
        except (TypeError, ValueError):
            continue
    return out


def _reverse_dcf_yaml1_yoy(params: dict[str, Any]) -> list[float]:
    raw = get_path(params, "model.revenue_yoy")
    if isinstance(raw, dict):
        raw = raw.get("value")
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw:
        value = _number_or_none(item)
        if value is not None:
            values.append(value)
    return values


def _reverse_dcf_base_nopat(company_dir: Path, base_period: str) -> float | None:
    derived = _derived_metrics(company_dir)
    annual = derived.get("annual", {}) if isinstance(derived, dict) else {}
    base_row = annual.get(str(base_period)) if isinstance(annual, dict) else None
    if isinstance(base_row, dict):
        ebit = _optional_float(base_row.get("ebit"))
        tax_rate = _optional_float(base_row.get("effective_tax_rate"))
        if ebit is not None and tax_rate is not None:
            return ebit * (1.0 - tax_rate)

    rows = _read_csv_rows(company_forecast_dir(company_dir) / "full_is.csv")
    for row in rows:
        if str(row.get("period")) != str(base_period):
            continue
        operate_profit = _optional_float(row.get("operate_profit")) or 0.0
        fin_exp = _optional_float(row.get("fin_exp")) or 0.0
        total_profit = _optional_float(row.get("total_profit"))
        income_tax = _optional_float(row.get("income_tax"))
        if total_profit is not None and total_profit > 0 and income_tax is not None:
            tax_rate = income_tax / total_profit
        else:
            tax_rate = 0.0
        return (operate_profit + fin_exp) * (1.0 - tax_rate)
    return None


def _reverse_dcf_market_pack(
    *,
    derived: dict[str, Any] | None,
    dcf_summary: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    snapshot = derived.get("market_snapshot", {}) if isinstance(derived, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    param_market = params.get("market", {}) if isinstance(params.get("market"), dict) else {}

    total_shares = (
        _optional_float(snapshot.get("total_shares"))
        or _optional_float(dcf_summary.get("total_shares"))
        or _optional_float(param_market.get("total_shares"))
    )
    close = _optional_float(snapshot.get("close")) or _optional_float(param_market.get("close"))
    market_cap = _optional_float(snapshot.get("total_mv")) or _optional_float(param_market.get("total_mv"))
    if market_cap is None and close is not None and total_shares is not None:
        market_cap = close * total_shares
    if market_cap is None or market_cap <= 0:
        raise HTTPException(status_code=400, detail="Market cap is missing; refresh market data first")
    if total_shares is None or total_shares <= 0:
        raise HTTPException(status_code=400, detail="Total shares are missing")

    net_debt = _optional_float(dcf_summary.get("net_debt"))
    if net_debt is None:
        net_debt = _required_float(param_market.get("net_debt"), "Net debt")

    return {
        "trade_date": snapshot.get("trade_date"),
        "close": close,
        "total_shares": total_shares,
        "market_cap": market_cap,
        "net_debt": net_debt,
        "target_enterprise_value": market_cap + net_debt,
    }


def _reverse_dcf_profit_yoy(base_nopat: float, yearly: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    previous = base_nopat
    for row in yearly:
        current = _optional_float(row.get("nopat"))
        if current is None or abs(previous) < 1e-9:
            break
        values.append(current / previous - 1.0)
        previous = current
    return values


def _reverse_dcf_base_pack(company_dir: Path) -> dict[str, Any]:
    forecast_dir = company_forecast_dir(company_dir)
    dcf_path = forecast_dir / "dcf_detail.csv"
    forecast_is_path = forecast_dir / "forecast_is.csv"
    summary_path = forecast_dir / "dcf_summary.json"
    params_path = modelking_dir(company_dir) / "forecast_params.yaml"
    missing = [path.name for path in (dcf_path, forecast_is_path, summary_path, params_path) if not path.exists()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Run forecast first; missing {', '.join(missing)}")

    dcf_summary = _forecast_summary(company_dir)
    params = _read_yaml(params_path)
    derived = _derived_metrics(company_dir)
    market = _reverse_dcf_market_pack(derived=derived, dcf_summary=dcf_summary, params=params)
    revenue_by_period = _forecast_revenue_by_period(company_dir)
    dcf_rows = _dcf_detail(company_dir)
    if not dcf_rows:
        raise HTTPException(status_code=400, detail="Run forecast first; dcf_detail.csv is empty")
    if not revenue_by_period:
        raise HTTPException(status_code=400, detail="Run forecast first; forecast revenue is empty")

    terminal_capex_da_ratio = _optional_float(dcf_summary.get("terminal_capex_da_ratio"))
    if terminal_capex_da_ratio is None:
        terminal_capex_da_ratio = _optional_float(get_path(params, "model.terminal_capex_da_ratio"))
    if terminal_capex_da_ratio is None:
        terminal_capex_da_ratio = DEFAULT_TERMINAL_CAPEX_DA_RATIO
    yearly: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, row in enumerate(dcf_rows, start=1):
        period = int(row["period"])
        revenue = revenue_by_period.get(period)
        if revenue is None or abs(revenue) < 1e-9:
            warnings.append(f"Revenue missing or zero for {period}; margins set to 0")
            revenue = 0.0
        fcff = float(row.get("fcff") or 0.0)
        nopat = float(row.get("nopat") or 0.0)
        da = float(row.get("da") or 0.0)
        fcff_margin = fcff / revenue if abs(revenue) >= 1e-9 else 0.0
        nopat_margin = nopat / revenue if abs(revenue) >= 1e-9 else 0.0
        da_margin = da / revenue if abs(revenue) >= 1e-9 else 0.0
        fcff_to_nopat = fcff / nopat if abs(nopat) >= 1e-9 else 0.0
        da_to_nopat = da / nopat if abs(nopat) >= 1e-9 else 0.0
        yearly.append(
            {
                "index": index,
                "period": str(period),
                "revenue": revenue,
                "fcff": fcff,
                "nopat": nopat,
                "da": da,
                "fcff_margin": fcff_margin,
                "nopat_margin": nopat_margin,
                "da_margin": da_margin,
                "terminal_fcff_margin": nopat_margin + da_margin * (1.0 - terminal_capex_da_ratio),
                "fcff_to_nopat": fcff_to_nopat,
                "da_to_nopat": da_to_nopat,
                "terminal_fcff_to_nopat": 1.0 + da_to_nopat * (1.0 - terminal_capex_da_ratio),
            }
        )

    summary = _company_summary(company_dir)
    base_period = str(dcf_summary.get("base_period") or summary.get("base_period") or params.get("base_period") or "")
    base_revenue = _optional_float(get_path(params, "income.revenue"))
    yaml1_revenue_yoy = _reverse_dcf_yaml1_yoy(params)
    if base_revenue is None and yaml1_revenue_yoy:
        first_revenue = yearly[0]["revenue"]
        base_revenue = first_revenue / (1.0 + yaml1_revenue_yoy[0])
    if base_revenue is None:
        raise HTTPException(status_code=400, detail="Base revenue is missing")
    base_nopat = _reverse_dcf_base_nopat(company_dir, base_period)
    if base_nopat is None and yearly:
        first_nopat = _optional_float(yearly[0].get("nopat"))
        first_growth = yaml1_revenue_yoy[0] if yaml1_revenue_yoy else None
        if first_nopat is not None and first_growth is not None and first_growth > -1:
            base_nopat = first_nopat / (1.0 + first_growth)
    if base_nopat is None or abs(base_nopat) < 1e-9:
        raise HTTPException(status_code=400, detail="Base NOPAT is missing")
    current_model_profit_yoy = _reverse_dcf_profit_yoy(base_nopat, yearly)

    return {
        "schema_version": 1,
        "company": {
            "id": company_dir.name,
            "name": summary.get("name") or dcf_summary.get("name") or company_dir.name.rsplit("_", 1)[0],
            "ticker": summary.get("ticker") or dcf_summary.get("ticker"),
            "base_period": base_period,
        },
        "market": market,
        "defaults": {
            "n1": 4,
            "n2": 5,
            "wacc": 0.08,
            "terminal_growth": 0.025,
            "reference_decay": 0.55,
            "terminal_capex_da_ratio": terminal_capex_da_ratio,
        },
        "bounds": {
            "n1": [1, 8],
            "n2": [1, 10],
            "growth": [-0.2, 0.4],
            "wacc": [0.03, 0.2],
            "terminal_growth": [-0.02, 0.06],
            "reference_decay": [0, 1.2],
        },
        "base_model": {
            "base_revenue": base_revenue,
            "base_nopat": base_nopat,
            "growth_metric": "nopat",
            "forecast_years": int(dcf_summary.get("forecast_years") or len(yearly)),
            "current_equity_value": _optional_float(dcf_summary.get("equity_value")),
            "current_per_share_value": _optional_float(dcf_summary.get("per_share_value")),
            "yaml1_revenue_yoy": yaml1_revenue_yoy,
            "current_model_profit_yoy": current_model_profit_yoy,
        },
        "yearly": yearly,
        "warnings": warnings,
    }


@app.post("/api/companies/{company_id}/archive-models")
def archive_models(company_id: str) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    result = _archive_models(company_dir)
    _folder_overview_cache["ts"] = 0.0  # invalidate so next GET recomputes
    return result


@app.post("/api/companies/{company_id}/open-folder")
def open_company_folder(company_id: str) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    try:
        os.startfile(str(company_dir))  # Windows: opens Explorer at the company folder
    except (OSError, AttributeError) as exc:
        raise HTTPException(status_code=500, detail=f"无法打开目录: {exc}")
    return {"ok": True, "path": _relative(company_dir)}


@app.get("/api/companies/{company_id}/reverse-dcf-base")
def read_reverse_dcf_base(company_id: str) -> dict[str, Any]:
    return _reverse_dcf_base_pack(_company_dir(company_id))


class SensitivityPayload(BaseModel):
    wacc: float
    terminal_growth: float
    terminal_capex_da_ratio: float


class AssumptionPatchPayload(BaseModel):
    pointer: str
    old_value: float | None = None
    new_value: float | None = None


class AssumptionPreviewPayload(BaseModel):
    patches: list[AssumptionPatchPayload]


class AssumptionBriefPayload(BaseModel):
    patches: list[AssumptionPatchPayload]
    preview_summary: dict[str, Any] | None = None


@app.post("/api/companies/{company_id}/assumption-preview")
def assumption_preview(company_id: str, payload: AssumptionPreviewPayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    if not yaml1_path:
        raise HTTPException(status_code=404, detail="yaml1_*.yaml was not found")
    yaml1_data = _read_yaml(yaml1_path)
    patches = [_model_dump(item) for item in payload.patches]
    try:
        patched_yaml1 = _apply_assumption_patches(yaml1_data, patches)
        ensure_assumptions_fresh(
            yaml1_data=patched_yaml1,
            yaml1_label=f"{yaml1_path}#preview",
            defaults_path=company_defaults_path(company_dir),
            clean_annual_path=company_db_path(company_dir),
        )
        cleaned = clean_yaml1_data(
            patched_yaml1,
            company_defaults_path(company_dir),
            company_db_path(company_dir),
            yaml1_label=f"{yaml1_path}#preview",
        )
        build = build_forecast_statements(cleaned.forecast_params)
        result = value_from_statements(
            build,
            wacc=as_float(get_path(cleaned.forecast_params, "model.wacc")),
            terminal_growth=as_float(get_path(cleaned.forecast_params, "model.terminal_growth")),
            terminal_capex_da_ratio=as_float(
                get_path(cleaned.forecast_params, "model.terminal_capex_da_ratio"),
                DEFAULT_TERMINAL_CAPEX_DA_RATIO,
            ),
        )
    except (StaleAssumptionError, Yaml1CleanError, CalcError, ValueError) as exc:
        return {
            "dcf_summary": None,
            "dcf_detail": [],
            "statement_sheets": [],
            "result_rows": [],
            "warnings": [],
            "errors": [{"message": str(exc)}],
        }
    return _preview_response(cleaned.report, result)


@app.post("/api/companies/{company_id}/assumption-brief")
def assumption_brief(company_id: str, payload: AssumptionBriefPayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    core_path = _core_assumption(company_dir)
    yaml1_data = _read_yaml(yaml1_path) if yaml1_path else {}
    prompt = _format_frontend_edit_prompt(
        company_name=company_dir.name,
        core_path=str(core_path) if core_path else None,
        yaml1_path=str(yaml1_path) if yaml1_path else None,
        yaml1_data=yaml1_data,
        patches=[_model_dump(item) for item in payload.patches],
        preview_summary=payload.preview_summary,
    )
    return {"prompt": prompt}


class QuarterlyOverridePayload(BaseModel):
    period: str
    param: str
    value: float
    note: str | None = None


QUARTERLY_PERIOD_RE = re.compile(r"^(\d{4})Q([1-4])$")


def _quarterly_ticker(company_dir: Path, summary: dict[str, Any] | None = None) -> str:
    data = summary or _company_summary(company_dir)
    ticker = data.get("ticker")
    if not ticker:
        raise HTTPException(status_code=400, detail="Company ticker is missing")
    return str(ticker)


def _compute_quarterly_for_company(
    company_dir: Path,
    *,
    year: int | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ticker = _quarterly_ticker(company_dir, summary)
    db = company_db_path(company_dir)
    if not db.exists():
        raise HTTPException(status_code=400, detail="Company data.db is missing")
    try:
        return compute_quarterly_view(db=db, ticker=ticker, company_dir=company_dir, year=year)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _optional_quarterly_for_company(
    company_dir: Path,
    *,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        return _compute_quarterly_for_company(company_dir, summary=summary)
    except HTTPException:
        return None


def _quarter_value(view: dict[str, Any], field: str, q: int) -> float:
    period = f"{view.get('year') or ''}Q{q}"
    for row in view.get("rows", []):
        if row.get("field") == field:
            values = row.get("values", {})
            if isinstance(values, dict):
                return float(values.get(period, values.get(f"Q{q}", 0.0)) or 0.0)
    return 0.0


def _prior_same_quarter_value(db: Path, field: str, year: int, q: int) -> float:
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT period, " + field + " FROM clean_quarterly WHERE period LIKE ?",
            (f"%Q{q}",),
        ).fetchall()
    values: dict[int, float] = {}
    for row in rows:
        period = str(row["period"])
        if "Q" not in period:
            continue
        y_text, _ = period.split("Q", 1)
        try:
            y = int(y_text)
        except ValueError:
            continue
        if y < year:
            values[y] = float(row[field] or 0.0)
    for y in sorted(values, reverse=True):
        if abs(values[y]) > 1e-9:
            return values[y]
    return 0.0


def _locked_override_from_payload(
    *,
    company_dir: Path,
    ticker: str,
    payload: QuarterlyOverridePayload,
) -> tuple[str, float]:
    match = QUARTERLY_PERIOD_RE.match(payload.period)
    if not match:
        raise HTTPException(status_code=400, detail="period must be YYYYQq")
    year = int(match.group(1))
    q = int(match.group(2))
    if q == 4:
        raise HTTPException(status_code=400, detail="Q4 is residual and cannot be manually overridden")

    view = compute_quarterly_view(
        db=company_db_path(company_dir),
        ticker=ticker,
        company_dir=company_dir,
        year=year,
    )
    state = str(view.get("quarter_states", {}).get(str(q), ""))
    if state == "actual":
        raise HTTPException(status_code=400, detail="Published quarters are read-only")

    param = payload.param
    value = float(payload.value)
    revenue_q = _quarter_value(view, "revenue", q)

    if param == "gpm":
        return "gross_profit", revenue_q * value
    if param == "gross_profit_abs":
        return "gross_profit", value
    if param == "revenue_abs":
        return "revenue", value
    if param == "revenue_yoy":
        prior = _prior_same_quarter_value(company_db_path(company_dir), "revenue", year, q)
        return "revenue", prior * (1.0 + value)
    if param == "income_tax_rate":
        return "income_tax", _quarter_value(view, "total_profit", q) * value
    if param == "income_tax_abs":
        return "income_tax", value
    if param == "fin_exp_abs":
        return "fin_exp", value
    if param.endswith("_rate"):
        field = param.removesuffix("_rate")
        if field in {"sell_exp", "admin_exp", "rd_exp", "biz_tax_surchg"}:
            return field, revenue_q * value
    if param.endswith("_abs"):
        field = param.removesuffix("_abs")
        if field in {"sell_exp", "admin_exp", "rd_exp", "biz_tax_surchg"}:
            return field, value

    raise HTTPException(status_code=400, detail=f"Unsupported quarterly override param: {param}")


@app.get("/api/companies/{company_id}/quarterly")
def read_quarterly(company_id: str, year: int | None = None) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    return _compute_quarterly_for_company(company_dir, year=year)


@app.put("/api/companies/{company_id}/quarterly/override")
def put_quarterly_override(company_id: str, payload: QuarterlyOverridePayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    ticker = _quarterly_ticker(company_dir)
    locked_field, locked_value = _locked_override_from_payload(
        company_dir=company_dir,
        ticker=ticker,
        payload=payload,
    )
    set_override(
        company_db_path(company_dir),
        ticker,
        payload.period,
        payload.param,
        payload.value,
        locked_field=locked_field,
        locked_value=locked_value,
        note=payload.note,
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return {
        "ok": True,
        "locked_field": locked_field,
        "locked_value": locked_value,
        "view": _compute_quarterly_for_company(company_dir, year=int(payload.period[:4])),
    }


@app.delete("/api/companies/{company_id}/quarterly/override/{period}")
def delete_quarterly_override(
    company_id: str,
    period: str,
    param: str | None = None,
) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    ticker = _quarterly_ticker(company_dir)
    clear_override(company_db_path(company_dir), ticker, period, param=param)
    year = int(period[:4]) if QUARTERLY_PERIOD_RE.match(period) else None
    return {
        "ok": True,
        "view": _compute_quarterly_for_company(company_dir, year=year),
    }


def _load_forecast_build(path: Path) -> ForecastBuildResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ForecastBuildResult(
        income_statement=pd.DataFrame(),
        balance_sheet=pd.DataFrame(),
        cash_flow=pd.DataFrame(),
        dcf=pd.DataFrame(data["dcf_rows"]),
        base_period=data["base_period"],
        forecast_years=data["forecast_years"],
        net_debt=data["net_debt"],
        total_shares=data["total_shares"],
        ticker=data["ticker"],
        name=data["name"],
        review_flags=data["review_flags"],
    )


@app.post("/api/companies/{company_id}/dcf-sensitivity")
def dcf_sensitivity(company_id: str, payload: SensitivityPayload) -> dict[str, Any]:
    company_dir = _company_dir(company_id)
    build_path = modelking_dir(company_dir) / "forecast_build.json"
    if not build_path.exists():
        raise HTTPException(status_code=400, detail="Run forecast first")
    if payload.wacc <= payload.terminal_growth:
        raise HTTPException(
            status_code=400,
            detail="WACC must be greater than terminal growth",
        )
    build = _load_forecast_build(build_path)
    result = value_from_statements(
        build,
        wacc=payload.wacc,
        terminal_growth=payload.terminal_growth,
        terminal_capex_da_ratio=payload.terminal_capex_da_ratio,
    )
    return {"summary": result["summary"]}


@app.get("/api/companies/{company_id}/yaml1/presentation/stream")
def yaml1_presentation_stream(company_id: str, refresh: bool = True) -> StreamingResponse:
    company_dir = _company_dir(company_id)
    yaml1_path = _latest_yaml1(company_dir)
    if not yaml1_path:
        raise HTTPException(status_code=404, detail="yaml1_*.yaml was not found")

    def generate():
        yield _sse("status", {"step": "start", "message": "开始读取 YAML1"})
        cached = _yaml1_presentation_cache(company_dir)
        if cached and not refresh:
            yield _sse("status", {"step": "cache", "message": "已找到缓存展示方案"})
            yield _sse("final", {"presentation": cached})
            return

        revenue_view = _yaml1_revenue_view(yaml1_path)
        sheets = _yaml1_sheets(yaml1_path)
        yield _sse("status", {"step": "parse", "message": "已抽取业务线、驱动和底稿结构"})
        context = _yaml1_presentation_context(company_dir, yaml1_path, revenue_view, sheets)
        provider_order = _presentation_provider_order()
        yield _sse(
            "status",
            {
                "step": "llm",
                "message": f"正在调用展示编排模型（优先 {provider_order[0] if provider_order else 'glm'}）",
            },
        )
        presentation = _call_yaml1_presentation_llm(context)
        yield _sse(
            "status",
            {
                "step": "validate",
                "message": "正在校验展示 schema 与本地 YAML1 事实边界",
                "provider": presentation.get("provider"),
                "model": presentation.get("model"),
            },
        )
        _write_yaml1_presentation_cache(company_dir, presentation)
        yield _sse("status", {"step": "done", "message": "展示方案已生成并缓存"})
        yield _sse("final", {"presentation": presentation})

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"app": "modelking-workbench", "status": "ok"}


@app.get("/assets/{asset_path:path}")
def asset(asset_path: str) -> FileResponse:
    path = (APP_DIST / "assets" / asset_path).resolve()
    assets_root = (APP_DIST / "assets").resolve()
    if not path.is_file() or assets_root not in path.parents:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_path}")
    return FileResponse(path)


@app.get("/")
def index() -> FileResponse:
    index_path = APP_DIST / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="Frontend is not built. Run npm run build.")
    return FileResponse(index_path)


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    return index()


def ensure_frontend_built(no_build: bool = False) -> None:
    if (APP_DIST / "index.html").exists():
        return
    if no_build:
        raise RuntimeError("app/dist/index.html missing; run npm run build first")
    npm = "npm.cmd" if (BASE_DIR / "package.json").exists() else None
    if not npm:
        raise RuntimeError("package.json missing; cannot build frontend")
    subprocess.run([npm, "run", "build"], cwd=BASE_DIR, check=True)


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) != 0


def _http_bytes(url: str, timeout: float = 0.8) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except (OSError, urllib.error.URLError):
        return None


def _existing_workbench_is_healthy(url: str) -> bool:
    health_body = _http_bytes(f"{url}/api/health")
    if health_body and b"modelking-workbench" in health_body:
        html = _http_bytes(url)
        if not html:
            return False
        match = re.search(rb'src="/([^"]+\.js)"', html)
        if not match:
            return False
        js = _http_bytes(f"{url}/{match.group(1).decode('ascii')}")
        return bool(js and not js.lstrip().lower().startswith(b"<!doctype"))

    companies_body = _http_bytes(f"{url}/api/companies")
    html = _http_bytes(url)
    if not companies_body or not html:
        return False
    match = re.search(rb'src="/([^"]+\.js)"', html)
    if not match:
        return False
    js = _http_bytes(f"{url}/{match.group(1).decode('ascii')}")
    return bool(js and not js.lstrip().lower().startswith(b"<!doctype"))


def _first_free_port(host: str, start_port: int, attempts: int = 20) -> int:
    for port in range(start_port, start_port + attempts):
        if _port_is_free(host, port):
            return port
    raise RuntimeError(f"No free port found from {start_port} to {start_port + attempts - 1}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local ModelKing web workbench.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open Chrome/browser automatically")
    parser.add_argument("--no-build", action="store_true", help="Require an existing app/dist build")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_frontend_built(no_build=args.no_build)
    requested_url = f"http://{args.host}:{args.port}"
    if not _port_is_free(args.host, args.port):
        if _existing_workbench_is_healthy(requested_url):
            print(f"ModelKing workbench already running: {requested_url}")
            if not args.no_open:
                webbrowser.open(requested_url)
            return 0
        next_port = _first_free_port(args.host, args.port + 1)
        print(f"Port {args.port} is in use by a stale or non-ModelKing service; using {next_port}.")
        args.port = next_port
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    import uvicorn

    print(f"ModelKing workbench: {url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
