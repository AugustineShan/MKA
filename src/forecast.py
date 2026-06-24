"""One-command company forecast pipeline.

User-facing contract:
    Agent/defaults.yaml + Agent/yaml1*.yaml -> Agent/forecast/

The resolved forecast parameters and yaml1 clean report are implementation
artifacts. They are written under Agent/.modelking/ for audit/debug instead
of the company directory top level.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.calc import (
    as_float,
    build_forecast_statements,
    value_from_statements,
    write_outputs,
)
from src.yaml1_cleaner import (
    clean_yaml1,
    find_company_dir,
    load_clean_annual,
    mark_hidden,
    write_json,
)
from src.company_paths import (
    company_dir_from_agent_path,
    db_path as company_db_path,
    defaults_path as company_defaults_path,
    forecast_dir as company_forecast_dir,
    latest_yaml1_path,
    modelking_dir,
)
from src.yaml2_schema import DEFAULT_TERMINAL_CAPEX_DA_RATIO, get_path, write_yaml2


INTERNAL_DIR_NAME = ".modelking"
FORECAST_PARAMS_FILENAME = "forecast_params.yaml"
CLEAN_REPORT_FILENAME = "yaml1_clean_report.json"
FORECAST_BUILD_FILENAME = "forecast_build.json"
MANIFEST_FILENAME = "run_manifest.json"


def gpm_to_ex_dep(gpm: float, base_total_dep: float, revenue: float) -> float:
    """把 loaded gpm 转成 ex-depreciation gpm,保留 /ka 输入语义。"""
    return gpm + (base_total_dep / revenue if revenue else 0.0)


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
        return company_dir_from_agent_path(yaml1_path)
    if defaults_path:
        return company_dir_from_agent_path(defaults_path)
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
        "contract": "Agent/defaults.yaml + Agent/yaml1*.yaml -> Agent/forecast/",
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


def _load_clean_annual_df(clean_annual_path: Path) -> pd.DataFrame:
    """Load clean_annual as a DataFrame with string period column."""
    rows = load_clean_annual(clean_annual_path)
    df = pd.DataFrame.from_dict(rows, orient="index").reset_index().rename(columns={"index": "period"})
    df["period"] = df["period"].astype(str)
    return df


def _write_full_tables(
    output_dir: Path,
    clean_annual_path: Path,
    income_statement: pd.DataFrame,
    balance_sheet: pd.DataFrame,
    cash_flow: pd.DataFrame,
    base_period: str,
) -> None:
    """Concatenate clean_annual history with forecast statements.

    The only column rename is ``income.credit_impa_loss`` -> ``credit_impa_loss``,
    matching the forecast engine's internal name. Historical ``total_opcost`` is
    aligned to the forecast definition (``total_opcost = total_cogs``) so the
    full series has a consistent meaning.
    """
    hist_df = _load_clean_annual_df(clean_annual_path)
    base_year = int(base_period[:4])
    hist_df = hist_df[hist_df["period"].astype(int) <= base_year]
    forecast_periods = set(income_statement["period"])
    hist_df = hist_df[~hist_df["period"].isin(forecast_periods)]
    if hist_df.empty:
        return

    is_cols = list(income_statement.columns)
    is_hist_cols = ["income.credit_impa_loss" if c == "credit_impa_loss" else c for c in is_cols]
    is_hist = hist_df[is_hist_cols].rename(columns={"income.credit_impa_loss": "credit_impa_loss"})
    if "total_opcost" in is_hist.columns and "total_cogs" in is_hist.columns:
        is_hist = is_hist.copy()
        is_hist["total_opcost"] = is_hist["total_cogs"]
    is_hist = is_hist[is_cols]
    full_is = pd.concat([is_hist, income_statement], ignore_index=True).sort_values("period")

    bs_cols = list(balance_sheet.columns)
    bs_hist = hist_df[bs_cols]
    full_bs = pd.concat([bs_hist, balance_sheet], ignore_index=True).sort_values("period")

    cf_cols = list(cash_flow.columns)
    cf_hist = hist_df[cf_cols]
    full_cf = pd.concat([cf_hist, cash_flow], ignore_index=True).sort_values("period")

    full_is.to_csv(output_dir / "full_is.csv", index=False, encoding="utf-8-sig")
    full_bs.to_csv(output_dir / "full_bs.csv", index=False, encoding="utf-8-sig")
    full_cf.to_csv(output_dir / "full_cf.csv", index=False, encoding="utf-8-sig")


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

    yaml1 = yaml1 or latest_yaml1_path(company_dir)
    defaults = defaults or company_defaults_path(company_dir)
    clean_annual = Path(clean_annual_path) if clean_annual_path else company_db_path(company_dir)
    internal = Path(internal_dir) if internal_dir else modelking_dir(company_dir)
    forecast_params_path = internal / FORECAST_PARAMS_FILENAME
    clean_report_path = internal / CLEAN_REPORT_FILENAME
    out_dir = Path(output_dir) if output_dir else company_forecast_dir(company_dir)
    manifest_path = out_dir / MANIFEST_FILENAME

    cleaned = clean_yaml1(yaml1, defaults, clean_annual)
    write_yaml2(forecast_params_path, cleaned.forecast_params)
    write_json(clean_report_path, cleaned.report)
    mark_hidden(internal)

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
    warnings_count = len(cleaned.report.get("warnings", []))

    build_payload = {
        "dcf_rows": build.dcf.to_dict(orient="records"),
        "base_period": build.base_period,
        "forecast_years": build.forecast_years,
        "net_debt": build.net_debt,
        "total_shares": build.total_shares,
        "ticker": build.ticker,
        "name": build.name,
        "review_flags": build.review_flags,
    }
    (internal / FORECAST_BUILD_FILENAME).write_text(
        json.dumps(build_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

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
    _write_full_tables(
        out_dir,
        clean_annual,
        result["income_statement"],
        result["balance_sheet"],
        result["cash_flow"],
        build.base_period,
    )
    manifest_path.write_text(
        json.dumps(_manifest(run, cleaned.report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run company DCF from Agent/defaults.yaml + Agent/yaml1.")
    parser.add_argument("--ticker", help="A-share ticker used to infer company paths")
    parser.add_argument("--yaml1", help="Path to yaml1; defaults to latest company yaml1*.yaml")
    parser.add_argument("--defaults", help="Path to defaults.yaml; defaults to company/Agent/defaults.yaml")
    parser.add_argument("--clean-annual", help="Path to clean_annual data source; defaults to company/Agent/data.db")
    parser.add_argument("--output-dir", help="Output directory; defaults to company/Agent/forecast and must be named forecast")
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
