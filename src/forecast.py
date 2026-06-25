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
import os
import subprocess
import sys
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
from src.assumption_staleness import ensure_assumptions_fresh, latest_core_assumption_path
from src.company_excel_export import export_company_excel
from src.derived_metrics import build_and_write_derived_metrics
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
from src.da_roll import DaRollFailedError


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

    返回 da_series(并已就地完成 gpm→ex-dep 覆盖);sched=None(文件缺失或
    enabled:false)返回 None(合法轻资产,bit-exact)。

    enabled:true 下任何失败都向上抛,阻断 official forecast —— 绝不静默回退
    轻资产(见 da SKILL 铁律):DaAlignError(base 对齐硬错)直接抛;clean_annual
    加载或 roll_da_series 的其他异常包成 DaRollFailedError 抛。分析师要临时
    忽略 DA 须显式把 da_schedule.enabled 改 false(则返回 None 走轻资产)。

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
        return None  # 文件缺失或 enabled:false -> 合法轻资产路径

    # 以下 sched 已 enabled:true:任何 da_roll 失败都阻断 official forecast,
    # 不静默回退轻资产(见 da SKILL 铁律)。只有 sched=None 才允许轻资产。
    base_year = int(base_period[:4])
    years = as_int(get_path(forecast_params, "model.forecast_years"))
    base_bs_dict = get_path(forecast_params, "balance_sheet.base") or {}

    try:
        clean_annual = load_clean_annual(clean_annual_path)
    except Exception as exc:
        raise DaRollFailedError(
            "enabled:true 但 clean_annual 加载失败,阻断 official forecast"
            "(重资产假设无法滚进 forecast;参考 reference·DA未生效): {}".format(exc)
        ) from exc
    base_row = clean_annual.get(base_year, {})
    base_ppe_dep = as_float(base_row.get("depr_fa_coga_dpba"))
    # 守卫(audit H1):重资产模式 base 年 PP&E 折旧锚点必须存在且为正。
    # depr_fa_coga_dpba 缺失/NULL/<=0 时 as_float→0,会让 roll_da_series 的
    # scale=base_reported_dep/total_policy_dep 归零,静默把存量折旧抹平成"仅扩张"、
    # 维持性 capex→0,一个结构完整但完全错误的 da_series 驱动正式 DCF。这正是项目
    # 别处当 reconciler blocker 的 TuShare-NULL 类,绝不静默归零——显式阻断。
    if base_ppe_dep <= 0.0:
        raise DaRollFailedError(
            "enabled:true 但 base 年({})PP&E 折旧锚点 depr_fa_coga_dpba 缺失或<=0"
            "(={}),无法校准存量折旧,阻断 official forecast——绝不静默归零"
            "(参考 reference·DA未生效;请核对 clean_annual 该年现金流量表折旧 depr_fa_coga_dpba,"
            "或显式把 da_schedule.enabled 改 false 走轻资产)".format(base_year, base_ppe_dep)
        )

    try:
        da_series = roll_da_series(
            sched, base_bs_dict, years, base_year, base_ppe_dep
        )
    except DaAlignError:
        raise
    except Exception as exc:
        raise DaRollFailedError(
            "enabled:true 但 da_roll 执行失败,阻断 official forecast"
            "(重资产假设未生效;参考 reference·DA未生效): {}".format(exc)
        ) from exc

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
    derived_metrics_path: Path | None = None
    derived_metrics_annual_path: Path | None = None
    derived_metrics_quarterly_path: Path | None = None
    company_excel_output_path: Path | None = None
    company_excel_export_status: str | None = None
    company_excel_export_warning: str | None = None


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
    *,
    mode: str = "official",
) -> dict[str, Any]:
    contract = "Agent/defaults.yaml + Agent/yaml1*.yaml -> Agent/forecast/"
    if mode != "official":
        contract = "load vintage sandbox: defaults.yaml + yaml1*.yaml -> Load/{id}/forecast/"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "contract": contract,
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
        "derived_metrics_path": str(run.derived_metrics_path) if run.derived_metrics_path else None,
        "derived_metrics_annual_path": str(run.derived_metrics_annual_path) if run.derived_metrics_annual_path else None,
        "derived_metrics_quarterly_path": str(run.derived_metrics_quarterly_path) if run.derived_metrics_quarterly_path else None,
        "company_excel_output_path": str(run.company_excel_output_path) if run.company_excel_output_path else None,
        "company_excel_export_status": run.company_excel_export_status,
        "company_excel_export_warning": run.company_excel_export_warning,
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


class FidelityGateError(RuntimeError):
    """audit H2a:yaml1 结构/路径保真闸门硬失败,阻断 official forecast。"""

    def __init__(self, message: str, findings: list[dict[str, Any]]):
        super().__init__(message)
        self.findings = findings


FIDELITY_GATE_ENV = "MKA_FIDELITY_GATE"  # block_structural(默认) | warn | off


def _run_fidelity_gate(
    yaml1: Path,
    defaults: Path,
    company_dir: Path,
    internal: Path,
    report: dict[str, Any],
) -> None:
    """audit H2a:把确定性保真校验器 yaml1_fidelity_check 接进控制流。

    此前该校验器只由 skill prose 唤起(/frontend-edit 让 LLM 跑、/adj quick 连让都没让),
    forecast 本身从不调用 —— 越权手 patch 的 yaml1(翻 family、加删 knob、偏离 defaults
    命名空间)可直达 DCF。现在 official forecast 自动运行它:

    - Gate A(结构:深度/family/数组长度)+ Gate B(路径存在性/符号)是确定性判定,
      FAIL → 硬阻断(这正是结构性越权的指纹)。
    - Gate C(值双射,正则回退脆性)→ 仅并入 warning,不因脆性误阻断。
    - 无论结果如何,verdict + findings 始终并入 report.warnings(绝不静默)。
    - 校验器自身不可用/无产物 → fail-open 记 warning 放行(不让闸门自身的脆弱阻断 forecast);
      只有确凿的结构 FAIL 才 fail-closed。
    - 逃生阀:MKA_FIDELITY_GATE=warn 全降级为 warning;=off 完全跳过。
    """
    mode_env = os.environ.get(FIDELITY_GATE_ENV, "block_structural").lower()
    if mode_env == "off":
        return
    md = latest_core_assumption_path(company_dir)
    if md is None or not Path(md).exists():
        report.setdefault("warnings", []).append({
            "code": "fidelity_skipped_no_md",
            "severity": "warning",
            "message": "未找到核心假设.md,跳过 yaml1 保真闸门(无法核对 yaml1↔.md 翻译忠实度)",
        })
        return
    internal.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "src.yaml1_fidelity_check",
             str(yaml1), str(defaults), str(md), str(internal)],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 - 闸门自身故障 fail-open,只记 warning
        report.setdefault("warnings", []).append({
            "code": "fidelity_check_unavailable",
            "severity": "warning",
            "message": f"yaml1 保真闸门无法运行,放行(fail-open):{exc}",
        })
        return
    rpt_path = internal / "yaml1_fidelity_report.json"
    if not rpt_path.exists():
        report.setdefault("warnings", []).append({
            "code": "fidelity_check_unavailable",
            "severity": "warning",
            "message": f"yaml1 保真闸门未产出报告(exit={proc.returncode}),放行(fail-open);stderr={proc.stderr[:300]}",
        })
        return
    rpt = json.loads(rpt_path.read_text(encoding="utf-8"))
    findings = rpt.get("findings", [])
    structural_fail = [
        f for f in findings
        if f.get("gate") in ("A", "B") and f.get("status") == "FAIL"
    ]
    # 始终把 verdict + 摘要并入 report(可见、可审计,绝不静默)
    report.setdefault("warnings", []).append({
        "code": "fidelity_report",
        "severity": "warning" if findings else "info",
        "message": f"yaml1 保真闸门 verdict={rpt.get('verdict')} summary={rpt.get('summary')}",
        "findings": findings,
    })
    if structural_fail and mode_env != "warn":
        detail = "; ".join(
            f"{f.get('gate')}:{f.get('path')}:{f.get('detail')}" for f in structural_fail[:8]
        )
        raise FidelityGateError(
            "yaml1 结构/路径保真闸门 FAIL,阻断 official forecast(Gate A/B 确定性失败="
            "yaml1 偏离算法契约或 defaults 命名空间,常见于越权手 patch yaml1;请修 yaml1 或"
            "回 /comp 重译;确需临时放行设环境变量 MKA_FIDELITY_GATE=warn): " + detail,
            structural_fail,
        )


def run_company_forecast(
    ticker: str | None = None,
    yaml1_path: str | Path | None = None,
    defaults_path: str | Path | None = None,
    clean_annual_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    internal_dir: str | Path | None = None,
    skip_staleness_gate: bool = False,
    mode: str = "official",
    write_derived_outputs: bool = True,
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

    if not skip_staleness_gate:
        ensure_assumptions_fresh(
            yaml1_path=yaml1,
            defaults_path=defaults,
            clean_annual_path=clean_annual,
        )
    cleaned = clean_yaml1(yaml1, defaults, clean_annual)
    if mode == "official":
        # audit H2a:official forecast 自动跑确定性保真闸门(load_vintage/sandbox 不跑)。
        _run_fidelity_gate(yaml1, defaults, company_dir, internal, cleaned.report)
    da_warnings: list[dict[str, Any]] = []
    try:
        da_series = _maybe_roll_da_series(
            cleaned.forecast_params, company_dir, clean_annual, da_warnings)
    except DaRollFailedError as exc:
        # enabled:true 但 da_roll 失败:阻断 official forecast,不覆盖 Agent/forecast/。
        # 写 marker 让下游/工作台感知(参考 reference·DA未生效 语义);成功重跑时
        # write_outputs 的 reset_forecast_dir 会 rmtree 清掉本 marker。
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "DA_NOT_EFFECTIVE.json").write_text(
            json.dumps(
                {"marker": "reference·DA未生效", "reason": str(exc),
                 "action": "修 da_schedule 后重跑,或显式 enabled:false 走轻资产"},
                ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        raise
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
    if write_derived_outputs:
        try:
            derived_metrics, derived_paths = build_and_write_derived_metrics(company_dir)
            run.derived_metrics_path = derived_paths.get("json")
            run.derived_metrics_annual_path = derived_paths.get("annual_csv")
            run.derived_metrics_quarterly_path = derived_paths.get("quarterly_csv")
            try:
                run.company_excel_output_path = export_company_excel(company_dir, metrics=derived_metrics)
                run.company_excel_export_status = "written"
            except Exception as exc:  # noqa: BLE001 - Excel export is non-blocking.
                run.company_excel_export_status = "failed"
                run.company_excel_export_warning = str(exc)
        except Exception as exc:  # noqa: BLE001 - keep the core DCF contract available.
            run.company_excel_export_status = "skipped"
            run.company_excel_export_warning = f"derived metrics failed: {exc}"
    else:
        run.company_excel_export_status = "skipped"
        run.company_excel_export_warning = "derived outputs disabled"
    manifest_path.write_text(
        json.dumps(_manifest(run, cleaned.report, mode=mode), ensure_ascii=False, indent=2) + "\n",
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
    try:
        run = run_company_forecast(
            ticker=args.ticker,
            yaml1_path=args.yaml1,
            defaults_path=args.defaults,
            clean_annual_path=args.clean_annual,
            output_dir=args.output_dir,
        )
    except FidelityGateError as exc:
        print(f"FIDELITY GATE BLOCK: {exc}", file=sys.stderr, flush=True)
        return 4
    print(f"Written forecast: {run.output_dir}")
    print(f"Per-share value: {run.summary['per_share_value']}")
    if run.warnings_count:
        print(f"Warnings: {run.warnings_count} (details in internal clean report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
