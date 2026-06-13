"""Shared helpers for YAML2 defaults and DCF calculation.

YAML2 stores parameters as small records:

    some_parameter:
      value: 123.0
      source: clean_annual.some_field

calc.py always consumes the ``value`` member. Keeping the source next to the
value makes defaults.yaml auditable without making the calculator know about
TuShare or clean.py internals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


YAML2_VERSION = 2
DEFAULT_FORECAST_YEARS = 8
DEFAULT_WACC = 0.08
DEFAULT_TERMINAL_GROWTH = 0.025
DEFAULT_PLUG = "cash"

REVIEW_FLAG_NEGATIVE_CASH = "negative_cash_from_plug"

REQUIRED_PATHS = [
    "version",
    "ticker",
    "base_period",
    "model.forecast_years",
    "model.revenue_yoy",
    "model.wacc",
    "model.terminal_growth",
    "model.plug",
    "market.total_shares",
    "market.net_debt",
    "income.revenue",
    "income.gpm",
    "income.effective_tax_rate",
    "income.minority_ratio",
    "balance_sheet.base",
]


class YAML2Error(ValueError):
    """Raised when a YAML2 file is structurally invalid."""


def param(value: Any, source: str, note: str | None = None) -> dict[str, Any]:
    item = {"value": value, "source": source}
    if note:
        item["note"] = note
    return item


def plain_value(item: Any) -> Any:
    if isinstance(item, dict) and "value" in item:
        return item["value"]
    return item


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return plain_value(cur)


def require_paths(data: dict[str, Any], paths: list[str] | None = None) -> None:
    missing = [path for path in (paths or REQUIRED_PATHS) if get_path(data, path) is None]
    if missing:
        raise YAML2Error("YAML2 missing required path(s): " + ", ".join(missing))


def validate_yaml2(data: dict[str, Any]) -> None:
    require_paths(data)
    version = get_path(data, "version")
    if int(version) != YAML2_VERSION:
        raise YAML2Error(f"Unsupported YAML2 version: {version}")
    wacc = float(get_path(data, "model.wacc"))
    terminal_growth = float(get_path(data, "model.terminal_growth"))
    if wacc <= terminal_growth:
        raise YAML2Error(
            f"model.wacc must be greater than terminal_growth ({wacc} <= {terminal_growth})"
        )
    years = int(get_path(data, "model.forecast_years"))
    if years <= 0:
        raise YAML2Error("model.forecast_years must be positive")


def read_yaml2(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise YAML2Error(f"YAML2 root must be a mapping: {path}")
    validate_yaml2(data)
    return data


def write_yaml2(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    validate_yaml2(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        text = yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=100,
        )
        path.write_text(text, encoding="utf-8")
