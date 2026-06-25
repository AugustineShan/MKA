"""Guard official forecasts against stale assumption horizons.

When clean_annual already contains a real year that the current assumptions
still model as forecast, the model must be rolled through /annual-update before
it can produce official DCF outputs.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.company_paths import (
    db_path as company_db_path,
    defaults_path as company_defaults_path,
    find_company_dir,
)
from src.yaml1_cleaner import load_clean_annual, load_yaml
from src.yaml2_schema import get_path, read_yaml2


CORE_ASSUMPTION_GLOB = "*核心假设*.md"

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_OFFICIAL_STATUS_RE = re.compile(r"状态\s*[:：]\s*official\b", re.IGNORECASE)
_NON_OFFICIAL_STATUS_RE = re.compile(r"状态\s*[:：]\s*(?:reference|draft|model-extracted)\b", re.IGNORECASE)
_HORIZON_LIST_RE = re.compile(r"horizon\s*[:=]\s*\[([^\]]+)\]", re.IGNORECASE)
_HORIZON_RANGE_RE = re.compile(
    r"(?:horizon|forecast|预测期|显式期)[^\n\r]{0,80}?((?:19|20)\d{2})\s*[-~—–至到]\s*((?:19|20)\d{2})",
    re.IGNORECASE,
)
_HISTORY_RANGE_RE = re.compile(
    r"(?:历史|history)[^\n\r]{0,80}?((?:19|20)\d{2})\s*[-~—–至到]\s*((?:19|20)\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ForecastHorizonSource:
    source: str
    forecast_start: int

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "forecast_start": self.forecast_start}


@dataclass(frozen=True)
class AssumptionFreshnessStatus:
    data_end: int
    defaults_base_year: int | None
    horizon_sources: tuple[ForecastHorizonSource, ...]
    reasons: tuple[str, ...]
    clean_annual_path: str
    defaults_path: str | None = None

    @property
    def stale(self) -> bool:
        return bool(self.reasons)

    @property
    def forecast_start(self) -> int | None:
        if not self.horizon_sources:
            return None
        return min(source.forecast_start for source in self.horizon_sources)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stale": self.stale,
            "data_end": self.data_end,
            "defaults_base_year": self.defaults_base_year,
            "forecast_start": self.forecast_start,
            "horizon_sources": [source.as_dict() for source in self.horizon_sources],
            "reasons": list(self.reasons),
            "clean_annual_path": self.clean_annual_path,
            "defaults_path": self.defaults_path,
        }

    def message(self) -> str:
        if not self.stale:
            return "Assumption year gate passed."
        detail = "; ".join(self.reasons)
        return (
            "需要先运行 /annual-update："
            f"clean_annual 已有 {self.data_end} 实际数据，但当前假设/底座仍未滚到该年份。"
            f" {detail}"
        )


class StaleAssumptionError(RuntimeError):
    """Raised when official forecast inputs need /annual-update first."""

    def __init__(self, status: AssumptionFreshnessStatus):
        self.status = status
        super().__init__(status.message())


def _read_text_for_status(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _has_official_status(path: Path) -> bool:
    return bool(_OFFICIAL_STATUS_RE.search(_read_text_for_status(path)))


def _looks_non_official_candidate(path: Path) -> bool:
    name = path.name
    if (
        "核心假设参考" in name
        or "_核心假设_load" in name
        or "_核心假设_brkd" in name
        or "_核心假设_alphapai" in name
    ):
        return True
    text = _read_text_for_status(path)
    return bool(_NON_OFFICIAL_STATUS_RE.search(text))


def latest_core_assumption_path(company_dir: Path) -> Path | None:
    candidates = [path for path in company_dir.glob(CORE_ASSUMPTION_GLOB) if path.is_file()]
    if not candidates:
        return None
    official = [path for path in candidates if _has_official_status(path)]
    if official:
        return max(official, key=lambda path: path.stat().st_mtime)
    # Legacy compatibility: older fixtures/companies may lack a status header.
    # Even in fallback mode, never let LOAD/BRKD/Alphapai/reference drafts become
    # the official source for fidelity/staleness checks.
    legacy = [path for path in candidates if not _looks_non_official_candidate(path)]
    if not legacy:
        return None
    return max(legacy, key=lambda path: path.stat().st_mtime)


def forecast_start_from_yaml1_data(data: dict[str, Any], *, label: str = "yaml1") -> ForecastHorizonSource | None:
    meta = data.get("meta")
    horizon = meta.get("horizon") if isinstance(meta, dict) else None
    if not isinstance(horizon, list) or not horizon:
        return None
    years = [int(year) for year in horizon]
    return ForecastHorizonSource(label, min(years))


def forecast_start_from_yaml1_path(path: str | Path) -> ForecastHorizonSource | None:
    path = Path(path)
    return forecast_start_from_yaml1_data(load_yaml(path), label=str(path))


def forecast_start_from_core_md(path: str | Path) -> ForecastHorizonSource | None:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    match = _HORIZON_LIST_RE.search(text)
    if match:
        years = [int(year) for year in _YEAR_RE.findall(match.group(1))]
        if years:
            return ForecastHorizonSource(str(path), min(years))

    match = _HORIZON_RANGE_RE.search(text)
    if match:
        return ForecastHorizonSource(str(path), int(match.group(1)))

    match = _HISTORY_RANGE_RE.search(text)
    if match:
        return ForecastHorizonSource(str(path), int(match.group(2)) + 1)

    return None


def _latest_actual_year(clean_annual_path: str | Path) -> int:
    rows = load_clean_annual(clean_annual_path)
    return max(int(year) for year in rows)


def _year_from_period(value: Any) -> int | None:
    if value is None:
        return None
    match = _YEAR_RE.search(str(value))
    return int(match.group(0)) if match else None


def _defaults_base_year(defaults_path: str | Path | None) -> int | None:
    if defaults_path is None:
        return None
    defaults = read_yaml2(defaults_path)
    return _year_from_period(get_path(defaults, "base_period"))


def inspect_assumption_freshness(
    *,
    clean_annual_path: str | Path,
    defaults_path: str | Path | None = None,
    yaml1_path: str | Path | None = None,
    yaml1_data: dict[str, Any] | None = None,
    yaml1_label: str = "<memory>",
    core_md_path: str | Path | None = None,
) -> AssumptionFreshnessStatus:
    data_end = _latest_actual_year(clean_annual_path)
    defaults_base_year = _defaults_base_year(defaults_path)

    sources: list[ForecastHorizonSource] = []
    if yaml1_data is not None:
        source = forecast_start_from_yaml1_data(yaml1_data, label=yaml1_label)
        if source:
            sources.append(source)
    if yaml1_path is not None:
        source = forecast_start_from_yaml1_path(yaml1_path)
        if source:
            sources.append(source)
    if core_md_path is not None:
        source = forecast_start_from_core_md(core_md_path)
        if source:
            sources.append(source)

    reasons: list[str] = []
    for source in sources:
        if data_end >= source.forecast_start:
            reasons.append(
                f"{source.source} forecast_start={source.forecast_start} 与 data_end={data_end} 重叠"
            )
    if defaults_base_year is not None and data_end > defaults_base_year:
        reasons.append(
            f"defaults.yaml base_period={defaults_base_year} 早于 data_end={data_end}"
        )

    return AssumptionFreshnessStatus(
        data_end=data_end,
        defaults_base_year=defaults_base_year,
        horizon_sources=tuple(sources),
        reasons=tuple(reasons),
        clean_annual_path=str(clean_annual_path),
        defaults_path=str(defaults_path) if defaults_path is not None else None,
    )


def ensure_assumptions_fresh(**kwargs: Any) -> AssumptionFreshnessStatus:
    status = inspect_assumption_freshness(**kwargs)
    if status.stale:
        raise StaleAssumptionError(status)
    return status


def _infer_company_paths(args: argparse.Namespace) -> tuple[Path | None, Path, Path, Path | None]:
    company_dir: Path | None = None
    if args.company_dir:
        company_dir = Path(args.company_dir)
    elif args.ticker:
        company_dir = find_company_dir(args.ticker)

    if args.clean_annual:
        clean_annual = Path(args.clean_annual)
    elif company_dir is not None:
        clean_annual = company_db_path(company_dir)
    else:
        raise SystemExit("--clean-annual is required without --ticker/--company-dir")

    defaults = Path(args.defaults) if args.defaults else (
        company_defaults_path(company_dir) if company_dir is not None else None
    )

    core_md = Path(args.core_md) if args.core_md else (
        latest_core_assumption_path(company_dir) if company_dir is not None else None
    )
    return company_dir, clean_annual, defaults, core_md


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether assumptions must be rolled by /annual-update.")
    parser.add_argument("--ticker", help="A-share ticker used to infer company paths")
    parser.add_argument("--company-dir", help="Company directory")
    parser.add_argument("--yaml1", help="yaml1 path; if omitted, only core-md/defaults are checked")
    parser.add_argument("--core-md", help="Core assumption Markdown path")
    parser.add_argument("--defaults", help="defaults.yaml path")
    parser.add_argument("--clean-annual", help="clean_annual csv/db path")
    parser.add_argument("--json", action="store_true", help="Print machine-readable status")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _company_dir, clean_annual, defaults, core_md = _infer_company_paths(args)
    status = inspect_assumption_freshness(
        clean_annual_path=clean_annual,
        defaults_path=defaults,
        yaml1_path=args.yaml1,
        core_md_path=core_md,
    )
    if args.json:
        print(json.dumps(status.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(status.message())
    return 2 if status.stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
