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
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.calc import (
    as_float,
    as_int,
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
from src.yaml2_schema import (
    DEFAULT_TERMINAL_CAPEX_DA_RATIO,
    get_path,
    plain_value,
    write_yaml2,
)


INTERNAL_DIR_NAME = ".modelking"
FORECAST_PARAMS_FILENAME = "forecast_params.yaml"
CLEAN_REPORT_FILENAME = "yaml1_clean_report.json"
FORECAST_BUILD_FILENAME = "forecast_build.json"
MANIFEST_FILENAME = "run_manifest.json"

_log = logging.getLogger(__name__)


def gpm_to_ex_dep(gpm: float, base_total_dep: float, revenue: float) -> float:
    """把 loaded gpm 转成 ex-depreciation gpm,保留 /ka 输入语义。"""
    return gpm + (base_total_dep / revenue if revenue else 0.0)


def _apply_gpm_ex_dep(forecast_params: dict[str, Any], base_ppe_dep: float) -> None:
    """重资产模式:把 income.gpm 逐年覆盖为 ex-PP&E-depreciation gpm。

    gpm_ex[t] = gpm_loaded[t] + base_ppe_dep / revenue[t],revenue[t] 由
    base_revenue × ∏(1+revenue_yoy) 滚动得到。da_roll 只建模 PP&E 折旧,故只把
    PP&E 折旧从 oper_cost 拆出(三类摊销仍嵌在 gpm 内,与轻资产一致);base 年因
    da_roll 校准使 ppe_dep ≈ base_ppe_dep,故 EBIT_heavy(base) = EBIT_light(base)
    (会计中性)。保留 /ka 常规 loaded-gpm 输入语义;PP&E 折旧拆出为显式 IS 行在
    calc 重资产分支(Step 4)处理,此处只改 gpm 输入。
    """
    income = forecast_params.get("income")
    gpm_arr = get_path(forecast_params, "income.gpm")
    if not isinstance(gpm_arr, list) or not isinstance(income, dict):
        return
    base_revenue = as_float(get_path(forecast_params, "income.revenue"))
    yoy_raw = get_path(forecast_params, "model.revenue_yoy")
    yoy = plain_value(yoy_raw) if isinstance(yoy_raw, list) else []
    revenue = base_revenue
    new_arr: list[float] = []
    for i, gpm_val in enumerate(gpm_arr):
        y = plain_value(yoy[i]) if i < len(yoy) else 0.0
        revenue *= 1.0 + as_float(y)
        new_arr.append(as_float(gpm_val) + (base_ppe_dep / revenue if revenue else 0.0))
    income["gpm"] = new_arr


def _maybe_roll_da_series(
    forecast_params: dict[str, Any],
    company_dir: Path,
    clean_annual_path: Path,
    gate_warnings: list[dict[str, Any]] | None = None,
) -> list[dict] | None:
    """重资产模式注入:若 Agent/da_schedule.yaml 启用则滚动 da_series。

    返回 da_series(并已就地完成 gpm→ex-dep 覆盖),否则 None(轻资产,bit-exact)。
    DaAlignError(base 对齐失败)向上抛(硬错);其余异常记 warning 回退轻资产,
    绝不阻塞 forecast。

    base_ppe_dep = 现金流量表 depr_fa_coga_dpba(仅 PP&E 折旧):同时给 roll_da_series
    校准存量折旧、给 gpm→ex-dep 加回。三类摊销不进 da_roll 也不进 gpm 加回。

    gate_warnings:终值归一化门(da_roll.normalization_gate)若末年未归一,
    把 warning dict 追加到此列表,由调用方并入 clean report warnings(不静默放行)。
    """
    from src.company_paths import da_schedule_path
    from src.da_roll import (
        DaAlignError,
        load_da_schedule,
        normalization_gate,
        roll_da_series,
    )

    sched_path = da_schedule_path(company_dir)
    base_period = str(get_path(forecast_params, "base_period"))
    try:
        sched = load_da_schedule(sched_path, base_period)
    except DaAlignError:
        raise
    if sched is None:
        return None

    base_year = int(base_period[:4])
    years = as_int(get_path(forecast_params, "model.forecast_years"))
    base_bs_dict = get_path(forecast_params, "balance_sheet.base") or {}

    try:
        clean_annual = load_clean_annual(clean_annual_path)
    except Exception as exc:  # noqa: BLE001 - fall back, do not block forecast.
        _log.warning("da_roll: clean_annual load failed, falling back to light-asset: %s", exc)
        return None
    base_row = clean_annual.get(base_year, {})
    base_ppe_dep = as_float(base_row.get("depr_fa_coga_dpba"))

    try:
        da_series = roll_da_series(
            sched, base_bs_dict, years, base_year, base_ppe_dep
        )
    except DaAlignError:
        raise
    except Exception as exc:  # noqa: BLE001 - fall back, do not block forecast.
        _log.warning("da_roll failed, falling back to light-asset: %s", exc)
        return None

    _apply_gpm_ex_dep(forecast_params, base_ppe_dep)

    # 终值双边归一化门(spec §9.4):末年 cip 应抽干 + Δda/da 接近稳态增速。
    g = as_float(get_path(sched, "ppe.存量策略.net_growth_rate"))
    perpetual = as_float(get_path(forecast_params, "model.terminal_growth"))
    passed, reason = normalization_gate(da_series, g, perpetual)
    if not passed and gate_warnings is not None:
        gate_warnings.append({
            "code": "da_not_normalized",
            "severity": "warning",
            "message": f"终值未归一化:{reason}(显式期 da 是瞬态,终值 da 不可信;建议拉长显式期或由分析师确认接受偏差)",
        })
    return da_series


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
    # reindex (fill 0) 容忍 forecast-only 列(重资产 IS 的显式 depreciation 行历史无)
    is_hist = hist_df.reindex(columns=is_hist_cols, fill_value=0.0).rename(
        columns={"income.credit_impa_loss": "credit_impa_loss"})
    if "total_opcost" in is_hist.columns and "total_cogs" in is_hist.columns:
        is_hist = is_hist.copy()
        is_hist["total_opcost"] = is_hist["total_cogs"]
    is_hist = is_hist[is_cols]
    full_is = pd.concat([is_hist, income_statement], ignore_index=True).sort_values("period")

    bs_cols = list(balance_sheet.columns)
    bs_hist = hist_df.reindex(columns=bs_cols, fill_value=0.0)
    full_bs = pd.concat([bs_hist, balance_sheet], ignore_index=True).sort_values("period")

    cf_cols = list(cash_flow.columns)
    cf_hist = hist_df.reindex(columns=cf_cols, fill_value=0.0)
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
    da_warnings: list[dict[str, Any]] = []
    da_series = _maybe_roll_da_series(
        cleaned.forecast_params, company_dir, clean_annual, da_warnings)
    if da_series is not None:
        cleaned.forecast_params["da_series"] = da_series
    if da_warnings:
        cleaned.report.setdefault("warnings", []).extend(da_warnings)
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
