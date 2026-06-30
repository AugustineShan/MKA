"""Shared helpers for annual-report based analysis and reconciliation.

Functions that are useful both to src.annual_report_reconciler and to other
annual-report consumers (e.g. the financial-expense detail analyzer) live here.
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

import requests

from src.company_paths import (
    COMPANIES_DIR,
    annual_reports_dir,
    db_path as agent_db_path,
    find_company_dir as find_company_root,
)

ROOT = Path(__file__).resolve().parent.parent

# 默认 LLM 请求超时（秒）。结构化的年报勾稽确认是推理型任务，glm-5-turbo 单批可达
# ~150s，kimi 更慢；统一兑齐到 300s，避免未显式配置 *_TIMEOUT_SECONDS 的 provider
# （历史上 kimi 默认仅 120s）在复杂公司上 ReadTimeout 丢掉全部年报证据。
LLM_TIMEOUT_SECONDS = 300


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
    return find_company_root(code, COMPANIES_DIR)


def default_db_path(company_dir: Path, explicit: str | None = None) -> Path:
    if explicit:
        db_path = Path(explicit).resolve()
    else:
        db_path = agent_db_path(company_dir)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Markdown slicing utilities
# ---------------------------------------------------------------------------


def annual_markdown_path(company_dir: Path, year: str) -> Path | None:
    annuals = annual_reports_dir(company_dir)
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
    return os.environ.get("LLM_PROVIDER") or ("glm" if os.environ.get("GLM_API_KEY") else "kimi")


def llm_api_key(provider: str) -> str | None:
    if provider == "glm":
        return os.environ.get("GLM_API_KEY")
    if provider == "kimi":
        return os.environ.get("KIMI_API_KEY")
    return os.environ.get("LLM_API_KEY")


def llm_base_url(provider: str) -> str:
    if provider == "glm":
        return os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    if provider == "kimi":
        return os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/")
    return os.environ.get("LLM_BASE_URL", "").rstrip("/")


def llm_model(provider: str) -> str:
    if provider == "glm":
        return os.environ.get("GLM_MODEL", "glm-5-turbo")
    if provider == "kimi":
        return os.environ.get("KIMI_MODEL", "kimi-k2.6")
    return os.environ.get("LLM_MODEL", "")


def llm_timeout_seconds(provider: str) -> int:
    if provider == "glm":
        return int(os.environ.get("GLM_TIMEOUT_SECONDS", os.environ.get("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS))))
    if provider == "kimi":
        return int(os.environ.get("KIMI_TIMEOUT_SECONDS", os.environ.get("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS))))
    return int(os.environ.get("LLM_TIMEOUT_SECONDS", str(LLM_TIMEOUT_SECONDS)))


_T = TypeVar("_T")
_R = TypeVar("_R")


def llm_max_workers() -> int:
    """Bounded concurrency for independent LLM calls (per-year confirm / analyze).

    Each call keeps its own provider timeout + retry; concurrency only collapses
    wall-clock from sum(calls) to ~max(call). Default 6 is conservative for
    GLM/Kimi rate limits; override with LLM_MAX_WORKERS.
    """
    try:
        return max(1, int(os.environ.get("LLM_MAX_WORKERS", "6")))
    except ValueError:
        return 6


def parallel_map(
    func: Callable[[_T], _R],
    items: Iterable[_T],
    *,
    max_workers: int | None = None,
) -> list[_R]:
    """Run ``func`` over ``items`` concurrently, returning results in input order.

    Order-preserving (result[i] corresponds to items[i]) so callers stay
    deterministic regardless of completion order. Exceptions propagate exactly
    as in a serial loop (first failing result re-raises after in-flight tasks
    settle). A single item or max_workers==1 runs inline without thread overhead.
    """
    materialized = list(items)
    if not materialized:
        return []
    workers = max(1, min(max_workers or llm_max_workers(), len(materialized)))
    if workers == 1:
        return [func(item) for item in materialized]

    results: list[Any] = [None] * len(materialized)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(func, item): idx
            for idx, item in enumerate(materialized)
        }
        for future in as_completed(future_to_index):
            results[future_to_index[future]] = future.result()
    return results


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
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", os.environ.get("KIMI_MAX_TOKENS", "16384"))),
        "response_format": {"type": "json_object"},
    }
    # kimi-k2.6 only allows temperature=1; skip it for Kimi to use the default.
    # For every other provider use temperature=0: the hard-check reconciliation
    # is a deterministic accounting judgement, and any randomness made the same
    # candidate get approved one year and rejected the next (false "instability").
    if provider != "kimi":
        body["temperature"] = float(os.environ.get("LLM_TEMPERATURE", "0"))

    # glm-5.2 is a reasoning model: without disabling, it spends the max_tokens
    # budget on reasoning_tokens and returns empty content (finish=length). The
    # reconciliation tasks here are deterministic table reading / structured
    # extraction, not reasoning, so disable thinking by default. Gate precisely
    # on the model name so glm-5-turbo / glm-4-long (non-reasoning) are untouched
    # — sending `thinking` to them is either ignored or rejected. Override with
    # GLM_THINKING=enabled for genuinely hard disambiguation calls.
    if provider == "glm" and "5.2" in model and os.environ.get("GLM_THINKING", "disabled").lower() != "enabled":
        body["thinking"] = {"type": "disabled"}

    # Transient failures (network blips, empty/truncated bodies, malformed JSON)
    # must not silently drop an entire confirmation chunk. Retry with backoff;
    # only return the error after the final attempt.
    attempts = max(1, int(os.environ.get("LLM_MAX_RETRIES", "3")))
    base_max_tokens = int(body.get("max_tokens") or os.environ.get("LLM_MAX_TOKENS", "16384"))
    # 截断重试时 max_tokens 翻倍（封顶）：否则用同一 max_tokens 重试 3 次必然再截，
    # 烧完配额后失败。封顶避免超出模型输出上限。
    max_tokens_cap = int(os.environ.get("LLM_MAX_TOKENS_CAP", "65536"))
    cur_max_tokens = base_max_tokens
    last_error: dict[str, Any] = {}
    for attempt in range(attempts):
        body["max_tokens"] = cur_max_tokens
        result = _call_llm_once(provider, url, api_key, body, model)
        if not result.get("error"):
            return result
        last_error = result
        truncated = "truncated" in str(result.get("error", "")) or result.get("_truncated")
        if truncated and attempt < attempts - 1:
            cur_max_tokens = min(cur_max_tokens * 2, max_tokens_cap)
        if attempt < attempts - 1:
            if result.get("_status") == 429:
                # GLM's rate limit is a per-minute request cap, so the default
                # 2-4s backoff just re-trips 429 and silently drops the chunk as
                # "no proposal". Wait for the window to reset (30/60/90s) before
                # retrying. Combined with bounded fallback concurrency this keeps
                # heavy full-context propose calls under the limit.
                time.sleep(30 * (attempt + 1))
            else:
                time.sleep(2 * (attempt + 1))
    last_error.setdefault("_provider", provider)
    last_error["_attempts"] = attempts
    return last_error


def _call_llm_once(
    provider: str,
    url: str,
    api_key: str,
    body: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=llm_timeout_seconds(provider),
        )
    except requests.RequestException as exc:
        return {"error": f"{provider} request failed: {type(exc).__name__}", "detail": str(exc), "_provider": provider}
    if response.status_code == 429:
        # Rate limited. The default short retry backoff (2-4s) is far too short
        # for GLM's per-minute request cap — it just re-trips 429 and the whole
        # chunk silently degrades to "no proposal" (which reads as "LLM found
        # nothing" when really it was never answered). Surface the status so
        # call_llm can apply a long backoff instead of swallowing the failure.
        return {"error": f"{provider} HTTP 429 rate limited", "_provider": provider, "_status": 429, "_retryable": True}
    if response.status_code >= 400:
        return {"error": f"{provider} HTTP {response.status_code}", "body": response.text[:1000], "_provider": provider}

    try:
        data = response.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        return {"error": f"{provider} response had no usable content: {type(exc).__name__}", "_provider": provider}

    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        # Truncated output is unparseable JSON; treat as retryable so a larger
        # response can complete instead of dropping the chunk.
        return {
            "error": f"{provider} response truncated (finish_reason=length); raise LLM_MAX_TOKENS",
            "_provider": provider,
            "_truncated": True,
        }
    if not content or not content.strip():
        return {"error": f"{provider} returned empty content", "_provider": provider}

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"error": "LLM response was not valid JSON", "raw": content[:1000], "_provider": provider}
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
