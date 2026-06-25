"""Application-level configuration for the local ModelKing workbench.

The workbench is distributed as a local product, so runtime configuration lives
in the project ``.env`` file instead of a database. This module keeps the
parsing/writing rules in one place and avoids returning secret values to the UI.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DEFAULT_COMPANIES_DIR = ROOT / "companies"
COMPANIES_DIR_KEY = "MKA_COMPANIES_DIR"
COMPANY_DIR_RE = re.compile(r"^.+_\d{6}$")
RATING_REPORT_DATA_START_YEAR_KEY = "MKA_RATING_REPORT_DATA_START_YEAR"
RATING_REPORT_DATA_END_YEAR_KEY = "MKA_RATING_REPORT_DATA_END_YEAR"
RATING_REPORT_FORECAST_START_YEAR_KEY = "MKA_RATING_REPORT_FORECAST_START_YEAR"
RATING_REPORT_FORECAST_END_YEAR_KEY = "MKA_RATING_REPORT_FORECAST_END_YEAR"
RATING_REPORT_DEFAULTS = {
    RATING_REPORT_DATA_START_YEAR_KEY: 2023,
    RATING_REPORT_DATA_END_YEAR_KEY: 2025,
    RATING_REPORT_FORECAST_START_YEAR_KEY: 2026,
    RATING_REPORT_FORECAST_END_YEAR_KEY: 2028,
}


@dataclass(frozen=True)
class EnvField:
    key: str
    label: str
    section: str
    secret: bool = False
    placeholder: str = ""


ENV_FIELDS: tuple[EnvField, ...] = (
    EnvField(COMPANIES_DIR_KEY, "工作台路径", "workspace", placeholder=str(DEFAULT_COMPANIES_DIR)),
    EnvField("TUSHARE_TOKEN", "TuShare Token", "data", secret=True),
    EnvField("TUSHARE_HTTP_URL", "TuShare HTTP URL", "data", placeholder="http://api.waditu.com/dataapi"),
    EnvField("TUSHARE_MIN_INTERVAL_SECONDS", "请求间隔秒数", "data", placeholder="0.8"),
    EnvField("LLM_PROVIDER", "默认大模型", "llm", placeholder="glm"),
    EnvField("GLM_API_KEY", "GLM API Key", "llm", secret=True),
    EnvField("GLM_BASE_URL", "GLM Base URL", "llm", placeholder="https://open.bigmodel.cn/api/paas/v4"),
    EnvField("GLM_MODEL", "GLM Model", "llm", placeholder="glm-5.2"),
    EnvField("GLM_TIMEOUT_SECONDS", "GLM Timeout", "llm", placeholder="300"),
    EnvField("GLM_THINKING", "GLM Thinking", "llm", placeholder="disabled"),
    EnvField("KIMI_API_KEY", "Kimi API Key", "llm", secret=True),
    EnvField("KIMI_BASE_URL", "Kimi Base URL", "llm", placeholder="https://api.moonshot.cn/v1"),
    EnvField("KIMI_MODEL", "Kimi Model", "llm", placeholder="kimi-k2.6"),
    EnvField("KIMI_THINKING", "Kimi Thinking", "llm", placeholder="disabled"),
    EnvField("LLM_MAX_TOKENS", "最大输出 Tokens", "llm", placeholder="32768"),
    EnvField("LLM_MAX_WORKERS", "并发 workers", "llm", placeholder="5"),
    EnvField(RATING_REPORT_DATA_START_YEAR_KEY, "评级报告取数开始年", "excel", placeholder=str(RATING_REPORT_DEFAULTS[RATING_REPORT_DATA_START_YEAR_KEY])),
    EnvField(RATING_REPORT_DATA_END_YEAR_KEY, "评级报告取数结束年", "excel", placeholder=str(RATING_REPORT_DEFAULTS[RATING_REPORT_DATA_END_YEAR_KEY])),
    EnvField(RATING_REPORT_FORECAST_START_YEAR_KEY, "评级报告预测开始年", "excel", placeholder=str(RATING_REPORT_DEFAULTS[RATING_REPORT_FORECAST_START_YEAR_KEY])),
    EnvField(RATING_REPORT_FORECAST_END_YEAR_KEY, "评级报告预测结束年", "excel", placeholder=str(RATING_REPORT_DEFAULTS[RATING_REPORT_FORECAST_END_YEAR_KEY])),
)
ENV_FIELD_KEYS = {field.key for field in ENV_FIELDS}


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, _unquote_env_value(value.strip())


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _format_env_value(value: str) -> str:
    text = str(value)
    if any(ch.isspace() for ch in text) or "#" in text or '"' in text or "'" in text:
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


def read_env_values(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed:
            key, value = parsed
            values[key] = value
    return values


def write_env_updates(updates: dict[str, str], path: Path = ENV_PATH) -> None:
    cleaned = {key: str(value) for key, value in updates.items() if key in ENV_FIELD_KEYS}
    if not cleaned:
        return

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []

    for raw_line in lines:
        parsed = _parse_env_line(raw_line)
        if not parsed:
            next_lines.append(raw_line)
            continue
        key, _value = parsed
        if key in cleaned:
            next_lines.append(f"{key}={_format_env_value(cleaned[key])}")
            seen.add(key)
        else:
            next_lines.append(raw_line)

    missing = [key for key in cleaned if key not in seen]
    if missing and next_lines and next_lines[-1].strip():
        next_lines.append("")
    for key in missing:
        next_lines.append(f"{key}={_format_env_value(cleaned[key])}")

    path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    for key, value in cleaned.items():
        os.environ[key] = value


def get_companies_dir() -> Path:
    values = read_env_values()
    raw = values.get(COMPANIES_DIR_KEY) or os.environ.get(COMPANIES_DIR_KEY)
    if not raw:
        return DEFAULT_COMPANIES_DIR
    return Path(raw).expanduser().resolve()


def validate_companies_dir(path: Path) -> dict[str, Any]:
    exists = path.exists()
    is_dir = path.is_dir()
    writable = False
    company_count = 0
    if exists and is_dir:
        writable = os.access(path, os.W_OK)
        company_count = sum(1 for child in path.iterdir() if child.is_dir() and COMPANY_DIR_RE.match(child.name))
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "writable": writable,
        "company_count": company_count,
    }


def _int_setting(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(key) or os.environ.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        year = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default
    return year if 1900 <= year <= 2200 else default


def rating_report_year_config(path: Path = ENV_PATH) -> dict[str, int]:
    values = read_env_values(path)
    data_start = _int_setting(values, RATING_REPORT_DATA_START_YEAR_KEY, RATING_REPORT_DEFAULTS[RATING_REPORT_DATA_START_YEAR_KEY])
    data_end = _int_setting(values, RATING_REPORT_DATA_END_YEAR_KEY, RATING_REPORT_DEFAULTS[RATING_REPORT_DATA_END_YEAR_KEY])
    forecast_start = _int_setting(
        values,
        RATING_REPORT_FORECAST_START_YEAR_KEY,
        RATING_REPORT_DEFAULTS[RATING_REPORT_FORECAST_START_YEAR_KEY],
    )
    forecast_end = _int_setting(
        values,
        RATING_REPORT_FORECAST_END_YEAR_KEY,
        RATING_REPORT_DEFAULTS[RATING_REPORT_FORECAST_END_YEAR_KEY],
    )
    if data_end < data_start:
        data_end = data_start
    if forecast_end < forecast_start:
        forecast_end = forecast_start
    return {
        "data_start_year": data_start,
        "data_end_year": data_end,
        "forecast_start_year": forecast_start,
        "forecast_end_year": forecast_end,
    }


def masked_secret(value: str | None) -> str | None:
    if not value:
        return None
    tail = value[-4:] if len(value) > 4 else value
    return f"****{tail}"


def settings_payload() -> dict[str, Any]:
    values = read_env_values()
    companies_dir = Path(values.get(COMPANIES_DIR_KEY) or os.environ.get(COMPANIES_DIR_KEY) or DEFAULT_COMPANIES_DIR).expanduser().resolve()
    rating_report = rating_report_year_config()
    fields = []
    for field in ENV_FIELDS:
        value = values.get(field.key) or os.environ.get(field.key) or ""
        default_value = RATING_REPORT_DEFAULTS.get(field.key)
        display_value = str(default_value) if default_value is not None and not value else value
        item: dict[str, Any] = {
            "key": field.key,
            "label": field.label,
            "section": field.section,
            "secret": field.secret,
            "placeholder": field.placeholder,
            "configured": bool(value),
        }
        if field.secret:
            item["masked"] = masked_secret(value)
        else:
            item["value"] = str(companies_dir) if field.key == COMPANIES_DIR_KEY else display_value
        fields.append(item)

    return {
        "env_path": str(ENV_PATH),
        "root": str(ROOT),
        "companies_dir": str(companies_dir),
        "default_companies_dir": str(DEFAULT_COMPANIES_DIR),
        "fields": fields,
        "validation": validate_companies_dir(companies_dir),
        "rating_report": rating_report,
    }


def save_settings(
    *,
    companies_dir: str | None = None,
    env: dict[str, str] | None = None,
    create_companies_dir: bool = False,
) -> dict[str, Any]:
    updates: dict[str, str] = {}
    if env:
        for key, value in env.items():
            if key in ENV_FIELD_KEYS and key != COMPANIES_DIR_KEY:
                updates[key] = str(value)
    if companies_dir is not None:
        path = Path(companies_dir).expanduser().resolve()
        if create_companies_dir:
            path.mkdir(parents=True, exist_ok=True)
        updates[COMPANIES_DIR_KEY] = str(path)
    write_env_updates(updates)
    return settings_payload()
