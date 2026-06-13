"""Annual report extractor: send skill + markdown to the configured LLM, archive the response.

Usage:
    python annual_report_extractor.py --ticker 002946.SZ --year 2025

Output:
    companies/{公司名}_{代码}/Extraction/{公司名}-{年度}-年报萃取.md

Provider selection (via .env):
    LLM_PROVIDER=glm  -> GLM-5-Turbo (default fallback)
    LLM_PROVIDER=kimi -> Kimi K2.6; set KIMI_THINKING=disabled for Instant mode
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
SKILL_PATH = BASE_DIR / "skills" / "annual_report_extractor_v2.md"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def llm_config() -> dict[str, Any]:
    env = load_env(BASE_DIR / ".env")
    provider = (
        env.get("LLM_PROVIDER")
        or os.environ.get("LLM_PROVIDER", "glm")
    ).lower()

    if provider == "kimi":
        return {
            "provider": "kimi",
            "api_key": env.get("KIMI_API_KEY") or os.environ.get("KIMI_API_KEY", ""),
            "base_url": (env.get("KIMI_BASE_URL") or os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1")).rstrip("/"),
            "model": env.get("KIMI_MODEL") or os.environ.get("KIMI_MODEL", "kimi-k2.6"),
            "thinking": (env.get("KIMI_THINKING") or os.environ.get("KIMI_THINKING", "enabled")).lower(),
            "timeout": int(env.get("KIMI_TIMEOUT_SECONDS") or os.environ.get("KIMI_TIMEOUT_SECONDS", "600")),
            "max_tokens": int(env.get("LLM_MAX_TOKENS") or os.environ.get("LLM_MAX_TOKENS", "8192")),
        }

    return {
        "provider": "glm",
        "api_key": env.get("GLM_API_KEY") or os.environ.get("GLM_API_KEY", ""),
        "base_url": (env.get("GLM_BASE_URL") or os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")).rstrip("/"),
        "model": env.get("GLM_MODEL") or os.environ.get("GLM_MODEL", "glm-5-turbo"),
        "thinking": None,
        "timeout": int(env.get("GLM_TIMEOUT_SECONDS") or os.environ.get("GLM_TIMEOUT_SECONDS", "600")),
        "max_tokens": int(env.get("LLM_MAX_TOKENS") or os.environ.get("LLM_MAX_TOKENS", "8192")),
    }


def call_llm(
    messages: list[dict[str, str]],
    cfg: dict[str, Any],
    max_retries: int = 3,
) -> dict[str, Any]:
    url = f"{cfg['base_url']}/chat/completions"
    provider = cfg["provider"]

    if provider == "kimi":
        # Instant mode: disable the K2.6 thinking chain.
        body: dict[str, Any] = {
            "model": cfg["model"],
            "messages": messages,
            "max_tokens": cfg["max_tokens"],
            "temperature": 0.6,
            "top_p": 0.95,
        }
        if cfg["thinking"] == "disabled":
            body["thinking"] = {"type": "disabled"}
    else:
        body = {
            "model": cfg["model"],
            "messages": messages,
            "max_tokens": cfg["max_tokens"],
            "temperature": 0.2,
        }

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                json=body,
                timeout=cfg["timeout"],
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "content": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "model": data.get("model", cfg["model"]),
            }
        except Exception as exc:
            last_exc = exc
            print(f"  {provider} call failed ({attempt}/{max_retries}): {exc}", file=sys.stderr)
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                print(f"  retrying in {wait}s ...", file=sys.stderr)
                time.sleep(wait)

    raise RuntimeError(f"{provider} failed after {max_retries} attempts: {last_exc}")


def find_company_dir(ticker: str) -> Path | None:
    code = ticker.split(".")[0]
    candidates = sorted((BASE_DIR / "companies").glob(f"*_{code}"))
    return candidates[0] if candidates else None


def extract_annual_report(ticker: str, year: int) -> Path:
    company_dir = find_company_dir(ticker)
    if company_dir is None:
        raise FileNotFoundError(f"Company directory not found for {ticker}")

    md_path = company_dir / "annuals" / f"{year}_年度报告.md"
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown annual report not found: {md_path}")

    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    annual_text = md_path.read_text(encoding="utf-8")
    company_name = company_dir.name.rsplit("_", 1)[0]

    cfg = llm_config()
    if not cfg["api_key"]:
        raise RuntimeError(f"{cfg['provider'].upper()} API key is not configured")

    system_msg = (
        "你是一名严格按契约执行的年报萃取档案员。"
        "请根据下面提供的《年报萃取器 Skill 契约 v2》，把给定的一份年报 markdown 萃取重组成完整的公司事实档案。"
        "只忠实记录、不做投资判断；量化明细带出处/口径/年份覆盖；质化叙事带出处和'管理层称'归因。"
        "直接输出 markdown 格式的公司事实档案。"
    )

    user_msg = (
        "## 契约\n\n"
        f"{skill_text}\n\n"
        "## 年报原文\n\n"
        f"{annual_text}\n\n"
        "请按契约萃取上述年报，输出完整的公司事实档案。"
    )

    mode_label = "Instant" if cfg["provider"] == "kimi" and cfg["thinking"] == "disabled" else "default"
    print(f"Calling {cfg['model']} ({cfg['provider']}, {mode_label}) with {len(user_msg):,} chars of input ...")
    result = call_llm(
        [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        cfg,
    )
    content = result["content"]
    print(f"Received {len(content):,} chars of output. Usage: {result.get('usage')}")

    output_dir = company_dir / "Extraction"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{company_name}-{year}-年报萃取.md"
    out_path.write_text(content, encoding="utf-8")

    print(f"Wrote {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract annual report facts archive")
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 002946.SZ")
    parser.add_argument("--year", type=int, default=2025, help="Annual report year")
    args = parser.parse_args(argv)

    try:
        extract_annual_report(args.ticker, args.year)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
