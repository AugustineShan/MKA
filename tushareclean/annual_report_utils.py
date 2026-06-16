"""Shared helpers for annual-report based analysis and reconciliation.

Functions that are useful both to src.annual_report_reconciler and to other
annual-report consumers (e.g. the financial-expense detail analyzer) live here.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from .config import COMPANIES_DIR, PROJECT_ROOT, load_env

LLM_TIMEOUT_SECONDS = 120

def parse_ticker(ticker: str) -> tuple[str, str]:
    match = re.fullmatch(r"(\d{6})\.(SZ|SH|BJ)", ticker.strip().upper())
    if not match:
        raise ValueError("ticker must look like 000333.SZ / 600519.SH / 430047.BJ")
    return match.group(1), match.group(2)


def find_company_dir(ticker: str, explicit: str | None = None) -> Path:
    if explicit:
        company_dir = Path(explicit).resolve()
        if not company_dir.exists():
            raise FileNotFoundError(company_dir)
        return company_dir

    code, _ = parse_ticker(ticker)
    matches = sorted(COMPANIES_DIR.glob(f"*_{code}"))
    if not matches:
        raise FileNotFoundError(f"No company directory matching companies/*_{code}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple company directories match {code}: {matches}")
    return matches[0]


def default_db_path(company_dir: Path, explicit: str | None = None) -> Path:
    if explicit:
        db_path = Path(explicit).resolve()
    else:
        db_path = company_dir / "data.db"
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Markdown slicing utilities
# ---------------------------------------------------------------------------


def annual_markdown_path(company_dir: Path, year: str) -> Path | None:
    annuals = company_dir / "annuals"
    if not annuals.exists():
        return None
    matches = sorted(annuals.glob(f"{year}_*.md"))
    return matches[0] if matches else None


def read_md_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def find_line(lines: list[str], patterns: list[str], start: int = 0) -> int | None:
    for idx in range(max(start, 0), len(lines)):
        line = lines[idx]
        if all(pattern in line for pattern in patterns):
            return idx
    return None


def find_all_lines(lines: list[str], patterns: list[str]) -> list[int]:
    """Return all line indices matching every pattern."""
    return [idx for idx, line in enumerate(lines) if all(p in line for p in patterns)]


def compact_window(lines: list[str], center: int, before: int = 35, after: int = 80) -> dict[str, Any]:
    start = max(0, center - before)
    end = min(len(lines), center + after)
    text = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
    return {"start_line": start + 1, "end_line": end, "text": text}


# ---------------------------------------------------------------------------
# LLM plumbing
# ---------------------------------------------------------------------------


def llm_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        return provider
    if os.environ.get("GLM_API_KEY"):
        return "glm"
    if os.environ.get("KIMI_API_KEY"):
        return "kimi"
    return "openai"


def llm_api_key(provider: str) -> str | None:
    if provider == "glm":
        return os.environ.get("GLM_API_KEY") or os.environ.get("LLM_API_KEY")
    if provider == "kimi":
        return os.environ.get("KIMI_API_KEY") or os.environ.get("LLM_API_KEY")
    return os.environ.get("LLM_API_KEY")


def llm_base_url(provider: str) -> str:
    if provider == "glm":
        return os.environ.get("GLM_BASE_URL") or os.environ.get(
            "LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        ).rstrip("/")
    if provider == "kimi":
        return os.environ.get("KIMI_BASE_URL") or os.environ.get(
            "LLM_BASE_URL", "https://api.moonshot.cn/v1"
        ).rstrip("/")
    return os.environ.get("LLM_BASE_URL", "").rstrip("/")


def llm_model(provider: str) -> str:
    if provider == "glm":
        return os.environ.get("GLM_MODEL") or os.environ.get("LLM_MODEL", "glm-5-turbo")
    if provider == "kimi":
        return os.environ.get("KIMI_MODEL") or os.environ.get("LLM_MODEL", "kimi-k2.6")
    return os.environ.get("LLM_MODEL", "")


def llm_timeout_seconds(provider: str) -> int:
    if provider == "glm":
        return int(os.environ.get("GLM_TIMEOUT_SECONDS", os.environ.get("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS))))
    if provider == "kimi":
        return int(os.environ.get("KIMI_TIMEOUT_SECONDS", os.environ.get("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS))))
    return int(os.environ.get("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS)))


def call_llm(messages: list[dict[str, str]]) -> dict[str, Any]:
    provider = llm_provider()
    api_key = llm_api_key(provider)
    if not api_key:
        return {"error": f"{provider.upper()} API key is not configured", "_provider": provider}

    base_url = llm_base_url(provider)
    model = llm_model(provider)
    if not base_url or not model:
        return {"error": f"{provider} base URL/model is not configured", "_provider": provider}
    url = f"{base_url}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", os.environ.get("KIMI_MAX_TOKENS", "8192"))),
        "response_format": {"type": "json_object"},
    }
    # kimi-k2.6 only allows temperature=1; skip it for Kimi to use the default.
    if provider != "kimi":
        body["temperature"] = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=llm_timeout_seconds(provider),
        )
    except requests.RequestException as exc:
        return {"error": f"{provider} request failed: {type(exc).__name__}", "detail": str(exc), "_provider": provider}
    if response.status_code >= 400:
        return {"error": f"{provider} HTTP {response.status_code}", "body": response.text[:1000], "_provider": provider}

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"error": "LLM response was not valid JSON", "raw": content}
    parsed["_usage"] = data.get("usage", {})
    parsed["_model"] = data.get("model", model)
    parsed["_provider"] = provider
    return parsed


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
