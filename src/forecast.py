"""One-command company forecast pipeline.

User-facing contract:
    defaults.yaml + yaml1*.yaml -> forecast/

The resolved forecast parameters and yaml1 clean report are implementation
artifacts. They are written under .modelking/ for audit/debug instead of the
company directory top level.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.calc import run_forecast, write_outputs
from src.yaml1_cleaner import (
    clean_yaml1,
    default_yaml1_path,
    find_company_dir,
    mark_hidden,
    write_json,
)
from src.yaml2_schema import write_yaml2


INTERNAL_DIR_NAME = ".modelking"
FORECAST_PARAMS_FILENAME = "forecast_params.yaml"
CLEAN_REPORT_FILENAME = "yaml1_clean_report.json"
MANIFEST_FILENAME = "run_manifest.json"


@dataclass
class ForecastRun:
    company_dir: Path
    yaml1_path: Path
    defaults_path: Path
    clean_annual_path: Path
    forecast_params_path: Path
    clean_report_path: Path
    output_dir: Path
    manifest_path: Path
    summary: dict[str, Any]
    warnings_count: int


def _infer_company_dir(ticker: str | None, yaml1_path: Path | None, defaults_path: Path | None) -> Path:
    if ticker:
        return find_company_dir(ticker)
    if yaml1_path:
        return yaml1_path.resolve().parent
    if defaults_path:
        return defaults_path.resolve().parent
    raise ValueError("--ticker, --yaml1, or --defaults is required")


def _infer_code(company_dir: Path, ticker: str | None) -> str:
    if ticker:
        return ticker.split(".")[0]
    return company_dir.name.rsplit("_", 1)[-1]


def _manifest(
    run: ForecastRun,
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": "defaults.yaml + yaml1*.yaml -> forecast/",
        "yaml2_defaults_path": str(run.defaults_path),
        "yaml1_path": str(run.yaml1_path),
        "clean_annual_path": str(run.clean_annual_path),
        "internal_forecast_params_path": str(run.forecast_params_path),
        "internal_clean_report_path": str(run.clean_report_path),
        "output_dir": str(run.output_dir),
        "backtest_status": report.get("backtest", {}).get("status"),
        "warnings_count": run.warnings_count,
        "errors_count": len(report.get("errors", [])),
        "summary": run.summary,
    }


def run_company_forecast(
    ticker: str | None = None,
    yaml1_path: str | Path | None = None,
    defaults_path: str | Path | None = None,
    clean_annual_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    internal_dir: str | Path | None = None,
) -> ForecastRun:
    yaml1 = Path(yaml1_path) if yaml1_path else None
    defaults = Path(defaults_path) if defaults_path else None
    company_dir = _infer_company_dir(ticker, yaml1, defaults)
    code = _infer_code(company_dir, ticker)

    yaml1 = yaml1 or default_yaml1_path(company_dir)
    defaults = defaults or company_dir / "defaults.yaml"
    clean_annual = Path(clean_annual_path) if clean_annual_path else company_dir / "data.db"
    internal = Path(internal_dir) if internal_dir else company_dir / INTERNAL_DIR_NAME
    forecast_params_path = internal / FORECAST_PARAMS_FILENAME
    clean_report_path = internal / CLEAN_REPORT_FILENAME
    out_dir = Path(output_dir) if output_dir else company_dir / "forecast"
    manifest_path = out_dir / MANIFEST_FILENAME

    cleaned = clean_yaml1(yaml1, defaults, clean_annual)
    write_yaml2(forecast_params_path, cleaned.forecast_params)
    write_json(clean_report_path, cleaned.report)
    mark_hidden(internal)

    result = run_forecast(cleaned.forecast_params)
    warnings_count = len(cleaned.report.get("warnings", []))
    run = ForecastRun(
        company_dir=company_dir,
        yaml1_path=yaml1,
        defaults_path=defaults,
        clean_annual_path=clean_annual,
        forecast_params_path=forecast_params_path,
        clean_report_path=clean_report_path,
        output_dir=out_dir,
        manifest_path=manifest_path,
        summary=result["summary"],
        warnings_count=warnings_count,
    )
    write_outputs(result, out_dir)
    manifest_path.write_text(
        json.dumps(_manifest(run, cleaned.report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run company DCF from defaults.yaml + yaml1.")
    parser.add_argument("--ticker", help="A-share ticker used to infer company paths")
    parser.add_argument("--yaml1", help="Path to yaml1; defaults to latest company yaml1*.yaml")
    parser.add_argument("--defaults", help="Path to defaults.yaml; defaults to company/defaults.yaml")
    parser.add_argument("--clean-annual", help="Path to clean_annual data source; defaults to company/data.db")
    parser.add_argument("--output-dir", help="Output directory; defaults to company/forecast and must be named forecast")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run = run_company_forecast(
        ticker=args.ticker,
        yaml1_path=args.yaml1,
        defaults_path=args.defaults,
        clean_annual_path=args.clean_annual,
        output_dir=args.output_dir,
    )
    print(f"Written forecast: {run.output_dir}")
    print(f"Per-share value: {run.summary['per_share_value']}")
    if run.warnings_count:
        print(f"Warnings: {run.warnings_count} (details in internal clean report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
