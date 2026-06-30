"""Deterministic Layer 1 engine for the /audit financial health radar."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from src import audit_data_toolkit as toolkit


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = ROOT / "audit_runs"
SEVERITY_WEIGHTS = {"CRITICAL": 100, "HIGH": 60, "MEDIUM": 25, "LOW": 5}


@dataclass(frozen=True)
class AuditFlag:
    rule_id: str
    severity: str
    period: str
    value: float | None
    threshold: str
    evidence_text: str
    source_fields: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompanyAuditResult:
    ticker: str
    company: str
    company_dir: str
    risk_score: int
    risk_level: str
    pattern_tags: list[str]
    flags: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class AuditRunResult:
    run_id: str
    output_dir: str
    results: list[CompanyAuditResult]


def compute_flags(history: toolkit.CompanyHistory) -> list[AuditFlag]:
    rows = history.annual
    quarterly = history.quarterly
    flags: list[AuditFlag] = []
    if len(rows) < 2:
        return flags

    flags.extend(_beneish_m_score(rows))
    flags.extend(_altman_z_score(rows))
    flags.extend(_earnings_quality(rows))
    flags.extend(_cash_receipt_ratio(rows))
    flags.extend(_sloan_accrual_ratio(rows))
    flags.extend(_cfo_ni_trend_divergence(rows))
    flags.extend(_ar_revenue_ratio(rows))
    flags.extend(_inventory_revenue_ratio(rows))
    flags.extend(_deposit_loan_mismatch(rows))
    flags.extend(_cip_not_transferring(rows))
    flags.extend(_other_receivable_high(rows))
    flags.extend(_goodwill_high(rows))
    flags.extend(_prepayment_high(rows))
    flags.extend(_q4_revenue_anomaly(quarterly, industry=history.industry))
    flags.extend(_contract_liability_decline(rows))
    flags.extend(_gross_margin_deviation(rows))
    flags.extend(_selling_expense_inefficiency(rows))
    return flags


def run_audit(
    coverage: str | Iterable[str],
    *,
    with_evidence: bool = True,
    include_tushare: bool = True,
    top: int = 20,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
) -> AuditRunResult:
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path(output_root) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    company_dirs = toolkit.resolve_coverage(coverage)
    pro = None
    if with_evidence and include_tushare:
        try:
            from src.data_fetcher import create_tushare_client

            pro = create_tushare_client()
        except Exception:
            pro = None

    results: list[CompanyAuditResult] = []
    for company_dir in company_dirs:
        try:
            history = toolkit.load_company_history(company_dir)
            flags = _sort_flags([flag.to_dict() for flag in compute_flags(history)])
            risk_score = score_flags(flags)
            result = CompanyAuditResult(
                ticker=history.ticker,
                company=history.name,
                company_dir=str(history.company_dir),
                risk_score=risk_score,
                risk_level=risk_level(risk_score),
                pattern_tags=pattern_tags(flags),
                flags=flags,
            )
            if with_evidence:
                pack = toolkit.build_evidence_pack(
                    history,
                    flags,
                    include_tushare=include_tushare,
                    pro=pro,
                )
                audit_dir = toolkit.audit_dir(history.company_dir)
                toolkit.write_json(audit_dir / "flags_latest.json", {"version": 1, **asdict(result)})
                toolkit.write_json(audit_dir / "evidence_pack_latest.json", pack)
            results.append(result)
        except Exception as exc:
            results.append(
                CompanyAuditResult(
                    ticker="",
                    company=company_dir.name,
                    company_dir=str(company_dir),
                    risk_score=0,
                    risk_level="ERROR",
                    pattern_tags=[],
                    flags=[],
                    error=str(exc),
                )
            )

    results.sort(key=lambda item: item.risk_score, reverse=True)
    _write_run_outputs(output_dir, run_id, results, top=top, with_evidence=with_evidence)
    return AuditRunResult(run_id=run_id, output_dir=str(output_dir), results=results)


def score_flags(flags: list[dict[str, Any]]) -> int:
    weights = sorted(
        (SEVERITY_WEIGHTS.get(str(flag.get("severity")), 0) for flag in flags),
        reverse=True,
    )
    return int(sum(weights[:8]))


def _sort_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        flags,
        key=lambda flag: (
            SEVERITY_WEIGHTS.get(str(flag.get("severity")), 0),
            str(flag.get("rule_id")),
        ),
        reverse=True,
    )


def risk_level(score: int) -> str:
    if score >= 200:
        return "CRITICAL"
    if score >= 120:
        return "HIGH"
    if score >= 50:
        return "MEDIUM"
    return "LOW"


def pattern_tags(flags: list[dict[str, Any]]) -> list[str]:
    ids = {str(flag.get("rule_id")) for flag in flags}
    severity_by_id = {str(flag.get("rule_id")): str(flag.get("severity")) for flag in flags}
    tags: list[str] = []
    if len({"AR_REVENUE_RATIO_HIGH", "CFO_NI_DIVERGENCE", "CONTRACT_LIABILITY_DECLINE"} & ids) >= 2:
        tags.append("CHANNEL_STUFFING")
    if "DEPOSIT_LOAN_MISMATCH" in ids and (
        {"LOW_EARNINGS_QUALITY", "CFO_NI_DIVERGENCE", "SLOAN_ACCRUAL_HIGH", "OTHER_RECEIVABLE_HIGH"} & ids
    ):
        tags.append("CASH_FABRICATION")
    if len({"CIP_NOT_TRANSFERRING", "GOODWILL_HIGH", "OTHER_RECEIVABLE_HIGH", "PREPAYMENT_HIGH"} & ids) >= 2:
        tags.append("ASSET_HOLE")
    if {"AR_REVENUE_RATIO_HIGH", "CASH_RECEIPT_LOW"} <= ids:
        tags.append("RECEIVABLE_INFLATION")
    if "Q4_REVENUE_ANOMALY" in ids and (
        {"LOW_EARNINGS_QUALITY", "CFO_NI_DIVERGENCE", "GROSS_MARGIN_DEVIATION"} & ids
        or severity_by_id.get("BENEISH_M_SCORE") in {"MEDIUM", "HIGH"}
    ):
        tags.append("BIG_BATH_OR_CUTOFF")
    return tags


def _write_run_outputs(
    output_dir: Path,
    run_id: str,
    results: list[CompanyAuditResult],
    *,
    top: int,
    with_evidence: bool,
) -> None:
    matrix = {
        "version": 1,
        "run_id": run_id,
        "with_evidence": with_evidence,
        "companies": [asdict(item) for item in results],
    }
    (output_dir / "flags_matrix.yaml").write_text(
        yaml.safe_dump(matrix, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    manifest = {
        "version": 1,
        "run_id": run_id,
        "company_count": len(results),
        "with_evidence": with_evidence,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "risk_ranking.md").write_text(_ranking_markdown(results, top=top), encoding="utf-8")


def _ranking_markdown(results: list[CompanyAuditResult], *, top: int) -> str:
    lines = [
        "# /audit 财务健康度风险排序",
        "",
        "| rank | company | ticker | risk | score | patterns | top flags |",
        "|---:|---|---|---|---:|---|---|",
    ]
    for idx, item in enumerate(results[:top], start=1):
        top_flags = ", ".join(
            f"{flag['rule_id']}:{flag['severity']}"
            for flag in item.flags[:5]
        )
        patterns = ", ".join(item.pattern_tags) if item.pattern_tags else "-"
        lines.append(
            f"| {idx} | {item.company} | {item.ticker or '-'} | {item.risk_level} | "
            f"{item.risk_score} | {patterns} | {top_flags or item.error or '-'} |"
        )
    lines.extend(
        [
            "",
            "> 本报告是确定性历史数据雷达，不构成买卖建议；请用 evidence_pack 继续做 Layer 2 取证。",
        ]
    )
    return "\n".join(lines) + "\n"


def _beneish_m_score(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    prev, cur = rows[-2], rows[-1]
    factors: dict[str, float] = {}
    factors["DSRI"] = _ratio(_ratio(_v(cur, "accounts_receiv"), _v(cur, "revenue")), _ratio(_v(prev, "accounts_receiv"), _v(prev, "revenue")))
    factors["GMI"] = _ratio(_gross_margin(prev), _gross_margin(cur))
    factors["AQI"] = _ratio(_asset_quality(cur), _asset_quality(prev))
    factors["SGI"] = _ratio(_v(cur, "revenue"), _v(prev, "revenue"))
    factors["DEPI"] = _ratio(_depreciation_rate(prev), _depreciation_rate(cur))
    factors["SGAI"] = _ratio(
        _ratio(_sum(cur, "sell_exp", "admin_exp"), _v(cur, "revenue")),
        _ratio(_sum(prev, "sell_exp", "admin_exp"), _v(prev, "revenue")),
    )
    factors["TATA"] = _ratio((_v(cur, "n_income") or 0.0) - (_v(cur, "n_cashflow_act") or 0.0), _v(cur, "total_assets"))
    factors["LVGI"] = _ratio(_ratio(_v(cur, "total_liab"), _v(cur, "total_assets")), _ratio(_v(prev, "total_liab"), _v(prev, "total_assets")))
    if any(value is None for value in factors.values()):
        return []
    score = (
        -4.84
        + 0.92 * factors["DSRI"]
        + 0.528 * factors["GMI"]
        + 0.404 * factors["AQI"]
        + 0.892 * factors["SGI"]
        + 0.115 * factors["DEPI"]
        - 0.172 * factors["SGAI"]
        + 4.679 * factors["TATA"]
        - 0.327 * factors["LVGI"]
    )
    severity = "LOW"
    if score > -1.78:
        severity = "HIGH"
    elif score > -2.22:
        severity = "MEDIUM"
    return [
        AuditFlag(
            "BENEISH_M_SCORE",
            severity,
            str(cur["period"]),
            score,
            "HIGH if > -1.78; MEDIUM if -2.22 to -1.78",
            f"Beneish M-Score={score:.2f}, factors={_round_dict(factors)}",
            [
                "accounts_receiv",
                "revenue",
                "oper_cost",
                "total_assets",
                "n_income",
                "n_cashflow_act",
                "total_liab",
            ],
            {"factors": _round_dict(factors)},
        )
    ]


def _altman_z_score(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    row = rows[-1]
    assets = _v(row, "total_assets")
    liab = _v(row, "total_liab")
    if not assets or not liab:
        return []
    ebit = (_v(row, "operate_profit") or 0.0) + (_v(row, "fin_exp") or 0.0)
    components = [
        _ratio((_v(row, "total_cur_assets") or 0.0) - (_v(row, "total_cur_liab") or 0.0), assets),
        _ratio(_v(row, "undistr_porfit"), assets),
        _ratio(ebit, assets),
        _ratio(_v(row, "total_hldr_eqy_inc_min_int"), liab),
        _ratio(_v(row, "revenue"), assets),
    ]
    if any(component is None for component in components):
        return []
    z = (
        0.717 * components[0]
        + 0.847 * components[1]
        + 3.107 * components[2]
        + 0.420 * components[3]
        + 0.998 * components[4]
    )
    severity = "LOW"
    if z < 1.2:
        severity = "HIGH"
    elif z < 2.9:
        severity = "MEDIUM"
    return [
        AuditFlag(
            "ALTMAN_Z_SCORE",
            severity,
            str(row["period"]),
            z,
            "HIGH if < 1.2; MEDIUM if 1.2 to 2.9",
            f"Altman Z-Score={z:.2f}",
            ["total_cur_assets", "total_cur_liab", "undistr_porfit", "operate_profit", "fin_exp", "total_assets"],
            {},
        )
    ]


def _earnings_quality(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    flags: list[AuditFlag] = []
    latest = rows[-1]
    ratio = _ratio(_v(latest, "n_cashflow_act"), _v(latest, "n_income"))
    if ratio is None:
        return flags
    last_two = [_ratio(_v(row, "n_cashflow_act"), _v(row, "n_income")) for row in rows[-2:]]
    severity: str | None = None
    if (_v(latest, "n_income") or 0) > 0 and (_v(latest, "n_cashflow_act") or 0) < 0:
        severity = "CRITICAL"
    elif all(value is not None and value < 0.5 for value in last_two):
        severity = "HIGH"
    elif ratio < 0.5:
        severity = "MEDIUM"
    if severity:
        flags.append(
            AuditFlag(
                "LOW_EARNINGS_QUALITY",
                severity,
                str(latest["period"]),
                ratio,
                "MEDIUM if < 0.5; HIGH if two consecutive years < 0.5; CRITICAL if profit positive but CFO negative",
                f"净现比={ratio:.2f}; CFO={_v(latest, 'n_cashflow_act')}, net income={_v(latest, 'n_income')}",
                ["n_cashflow_act", "n_income"],
                {},
            )
        )
    return flags


def _cash_receipt_ratio(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    latest = rows[-1]
    ratio = _ratio(_v(latest, "c_fr_sale_sg"), _v(latest, "revenue"))
    if ratio is None or ratio >= 0.8:
        return []
    last_two = [_ratio(_v(row, "c_fr_sale_sg"), _v(row, "revenue")) for row in rows[-2:]]
    severity = "HIGH" if all(value is not None and value < 0.8 for value in last_two) else "MEDIUM"
    return [
        AuditFlag(
            "CASH_RECEIPT_LOW",
            severity,
            str(latest["period"]),
            ratio,
            "MEDIUM if < 0.8; HIGH if two consecutive years < 0.8",
            f"收现比={ratio:.2f}",
            ["c_fr_sale_sg", "revenue"],
            {},
        )
    ]


def _sloan_accrual_ratio(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    latest = rows[-1]
    ratio = _ratio(
        (_v(latest, "n_income") or 0.0)
        - (_v(latest, "n_cashflow_act") or 0.0)
        - (_v(latest, "n_cashflow_inv_act") or 0.0),
        _v(latest, "total_assets"),
    )
    if ratio is None or abs(ratio) <= 0.25:
        return []
    return [
        AuditFlag(
            "SLOAN_ACCRUAL_HIGH",
            "HIGH",
            str(latest["period"]),
            ratio,
            "HIGH if absolute value > 25%",
            f"Sloan accrual ratio={ratio:.1%}",
            ["n_income", "n_cashflow_act", "n_cashflow_inv_act", "total_assets"],
            {},
        )
    ]


def _cfo_ni_trend_divergence(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    sample = rows[-5:]
    ni_slope = _slope([_v(row, "n_income") for row in sample])
    cfo_slope = _slope([_v(row, "n_cashflow_act") for row in sample])
    if ni_slope is None or cfo_slope is None or ni_slope <= 0:
        return []
    if cfo_slope < 0:
        severity = "HIGH"
    elif abs(cfo_slope) < abs(ni_slope) * 0.1:
        severity = "MEDIUM"
    else:
        return []
    return [
        AuditFlag(
            "CFO_NI_DIVERGENCE",
            severity,
            str(sample[-1]["period"]),
            cfo_slope,
            "HIGH if net income slope > 0 and CFO slope < 0; MEDIUM if CFO roughly flat",
            f"近{len(sample)}年净利润斜率={ni_slope:.2f}, CFO斜率={cfo_slope:.2f}",
            ["n_income", "n_cashflow_act"],
            {"n_income_slope": ni_slope, "cfo_slope": cfo_slope},
        )
    ]


def _ar_revenue_ratio(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    prev, cur = rows[-2], rows[-1]
    ar_growth = _growth(_v(cur, "accounts_receiv"), _v(prev, "accounts_receiv"))
    revenue_growth = _growth(_v(cur, "revenue"), _v(prev, "revenue"))
    if ar_growth is None or revenue_growth is None:
        return []
    if revenue_growth <= 0.03:
        current_ratio = _ratio(_v(cur, "accounts_receiv"), _v(cur, "revenue"))
        previous_ratio = _ratio(_v(prev, "accounts_receiv"), _v(prev, "revenue"))
        ratio = _growth(current_ratio, previous_ratio)
        value_text = "AR/revenue growth"
    else:
        ratio = ar_growth / revenue_growth if revenue_growth else None
        value_text = "AR growth / revenue growth"
    if ratio is None or ratio <= 1.3:
        return []
    severity = "HIGH" if ratio > 1.5 else "MEDIUM"
    return [
        AuditFlag(
            "AR_REVENUE_RATIO_HIGH",
            severity,
            str(cur["period"]),
            ratio,
            "MEDIUM if > 1.3; HIGH if > 1.5",
            f"{value_text}={ratio:.2f}; AR growth={ar_growth:.1%}, revenue growth={revenue_growth:.1%}",
            ["accounts_receiv", "revenue"],
            {},
        )
    ]


def _inventory_revenue_ratio(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    prev, cur = rows[-2], rows[-1]
    inv_growth = _growth(_v(cur, "inventories"), _v(prev, "inventories"))
    revenue_growth = _growth(_v(cur, "revenue"), _v(prev, "revenue"))
    if inv_growth is None or revenue_growth is None:
        return []
    if abs(revenue_growth) < 0.03:
        current_ratio = _ratio(_v(cur, "inventories"), _v(cur, "revenue"))
        previous_ratio = _ratio(_v(prev, "inventories"), _v(prev, "revenue"))
        ratio = _growth(current_ratio, previous_ratio)
        trigger = ratio is not None and ratio > 0.20
        severity = "HIGH" if ratio is not None and ratio > 0.35 else "MEDIUM"
        threshold = "MEDIUM if inventory/revenue ratio grows >20%; HIGH if >35% when revenue growth is within +/-3%"
        evidence_value = f"inventory/revenue ratio growth={ratio:.2f}" if ratio is not None else "inventory/revenue ratio growth=-"
    else:
        ratio = inv_growth / revenue_growth if revenue_growth else None
        trigger = (ratio is not None and ratio > 1.5) or (inv_growth > 0.2 and revenue_growth < 0.05)
        severity = "HIGH" if (ratio is not None and ratio > 2.0) or (inv_growth > 0.2 and revenue_growth < 0.05) else "MEDIUM"
        threshold = "MEDIUM if > 1.5; HIGH if > 2.0 or inventory growth >20% while revenue growth <5%"
        evidence_value = f"inventory growth / revenue growth={ratio:.2f}" if ratio is not None else "inventory growth / revenue growth=-"
    if not trigger:
        return []
    return [
        AuditFlag(
            "INVENTORY_REVENUE_RATIO_HIGH",
            severity,
            str(cur["period"]),
            ratio,
            threshold,
            f"{evidence_value}; inventory YoY={inv_growth:.1%}, revenue YoY={revenue_growth:.1%}",
            ["inventories", "revenue"],
            {},
        )
    ]


def _deposit_loan_mismatch(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    prev, cur = rows[-2], rows[-1]
    assets = _v(cur, "total_assets")
    debt = _interest_bearing_debt(cur)
    if not assets or not debt:
        return []
    cash_ratio = _ratio(_v(cur, "money_cap"), assets)
    debt_ratio = _ratio(debt, assets)
    avg_debt = _average([_interest_bearing_debt(prev), debt])
    implied_rate = _ratio(_v(cur, "fin_exp_int_exp"), avg_debt)
    if cash_ratio is None or debt_ratio is None or cash_ratio <= 0.15 or debt_ratio <= 0.20:
        return []
    severity = "HIGH" if implied_rate is not None and (implied_rate < 0.005 or implied_rate > 0.08) else "MEDIUM"
    return [
        AuditFlag(
            "DEPOSIT_LOAN_MISMATCH",
            severity,
            str(cur["period"]),
            cash_ratio,
            "cash/assets >15% and interest-bearing debt/assets >20%; HIGH if implied rate abnormal",
            f"货币资金/总资产={cash_ratio:.1%}, 有息负债/总资产={debt_ratio:.1%}, 隐含利率={_format_optional_pct(implied_rate)}",
            ["money_cap", "st_borr", "lt_borr", "bond_payable", "fin_exp_int_exp", "total_assets"],
            {"debt_ratio": debt_ratio, "implied_rate": implied_rate},
        )
    ]


def _cip_not_transferring(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    sample = rows[-3:]
    ratios = [_ratio(_v(row, "cip"), _v(row, "fix_assets")) for row in sample]
    if len(sample) < 3 or not all(value is not None and value > 0.30 for value in ratios):
        return []
    cip_growth = _growth(_v(sample[-1], "cip"), _v(sample[0], "cip"))
    revenue_growth = _growth(_v(sample[-1], "revenue"), _v(sample[0], "revenue"))
    severity = "HIGH" if cip_growth is not None and revenue_growth is not None and cip_growth > revenue_growth else "MEDIUM"
    return [
        AuditFlag(
            "CIP_NOT_TRANSFERRING",
            severity,
            str(sample[-1]["period"]),
            ratios[-1],
            "MEDIUM if CIP/fixed assets >30% for 3 years; HIGH if CIP growth > revenue growth",
            f"连续3年在建工程/固定资产={', '.join(f'{r:.1%}' for r in ratios if r is not None)}",
            ["cip", "fix_assets", "revenue"],
            {"cip_growth_3y": cip_growth, "revenue_growth_3y": revenue_growth},
        )
    ]


def _other_receivable_high(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    prev, cur = rows[-2], rows[-1]
    ratio = _ratio(_v(cur, "oth_receiv"), _v(cur, "total_assets"))
    growth = _growth(_v(cur, "oth_receiv"), _v(prev, "oth_receiv"))
    if ratio is None or ratio <= 0.05:
        return []
    severity = "HIGH" if growth is not None and growth > 0.30 else "MEDIUM"
    return [
        AuditFlag(
            "OTHER_RECEIVABLE_HIGH",
            severity,
            str(cur["period"]),
            ratio,
            "MEDIUM if >5% of total assets; HIGH if YoY growth >30%",
            f"其他应收款/总资产={ratio:.1%}, YoY={_format_optional_pct(growth)}",
            ["oth_receiv", "total_assets"],
            {"growth": growth},
        )
    ]


def _goodwill_high(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    cur = rows[-1]
    ratio = _ratio(_v(cur, "goodwill"), _v(cur, "total_hldr_eqy_inc_min_int"))
    if ratio is None or ratio <= 0.30:
        return []
    severity = "HIGH" if ratio > 0.50 else "MEDIUM"
    return [
        AuditFlag(
            "GOODWILL_HIGH",
            severity,
            str(cur["period"]),
            ratio,
            "MEDIUM if >30% of equity; HIGH if >50%",
            f"商誉/股东权益={ratio:.1%}",
            ["goodwill", "total_hldr_eqy_inc_min_int"],
            {},
        )
    ]


def _prepayment_high(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    sample = rows[-3:]
    cur = sample[-1]
    ratio = _ratio(_v(cur, "prepayment"), _v(cur, "oper_cost"))
    if ratio is None or ratio <= 0.15:
        return []
    rising = all(
        (_v(sample[idx], "prepayment") or 0.0) > (_v(sample[idx - 1], "prepayment") or 0.0)
        for idx in range(1, len(sample))
    )
    severity = "HIGH" if ratio > 0.20 else "MEDIUM"
    if not rising and severity == "MEDIUM":
        return []
    return [
        AuditFlag(
            "PREPAYMENT_HIGH",
            severity,
            str(cur["period"]),
            ratio,
            "MEDIUM if continuously rising and >15% of COGS; HIGH if >20%",
            f"预付款项/营业成本={ratio:.1%}",
            ["prepayment", "oper_cost"],
            {"continuous_rising": rising},
        )
    ]


def _q4_revenue_anomaly(rows: list[dict[str, Any]], *, industry: str = "general") -> list[AuditFlag]:
    by_year: dict[str, dict[str, float]] = {}
    for row in rows:
        period = str(row.get("period", ""))
        if len(period) != 6 or period[4] != "Q":
            continue
        year = period[:4]
        by_year.setdefault(year, {})
        by_year[year][period[-1]] = _v(row, "revenue") or 0.0
    ratios: list[tuple[str, float]] = []
    for year, quarters in sorted(by_year.items()):
        if set(quarters) >= {"1", "2", "3", "4"}:
            total = sum(quarters[q] for q in ["1", "2", "3", "4"])
            if total:
                ratios.append((year, quarters["4"] / total))
    if len(ratios) < 4:
        return []
    latest_year, latest_ratio = ratios[-1]
    history = [value for _, value in ratios[-4:-1]]
    mean = statistics.mean(history)
    std = statistics.pstdev(history)
    benchmark = _q4_benchmark(industry)
    normal_low = benchmark["normal_low"]
    normal_high = benchmark["normal_high"]
    if (
        normal_low is not None
        and normal_high is not None
        and normal_low <= latest_ratio <= normal_high
    ):
        return []
    deviation = (latest_ratio - mean) / std if std else None
    if deviation is None:
        if abs(latest_ratio - mean) < benchmark["min_abs_deviation"]:
            return []
        severity = "MEDIUM"
    elif abs(deviation) > 2.0:
        severity = "HIGH"
    elif abs(deviation) > 1.5:
        severity = "MEDIUM"
    else:
        return []
    if abs(latest_ratio - mean) < benchmark["min_abs_deviation"]:
        return []
    return [
        AuditFlag(
            "Q4_REVENUE_ANOMALY",
            severity,
            f"{latest_year}Q4",
            latest_ratio,
            "MEDIUM if |deviation| > 1.5σ; HIGH if > 2σ; industry normal ranges suppress expected seasonality",
            f"Q4 revenue mix={latest_ratio:.1%}, 3-year mean={mean:.1%}, deviation={deviation}, industry={industry}",
            ["revenue"],
            {
                "history_ratios": dict(ratios[-4:]),
                "deviation": deviation,
                "industry": industry,
                "industry_benchmark": benchmark,
            },
        )
    ]


def _q4_benchmark(industry: str) -> dict[str, float | None]:
    benchmarks: dict[str, dict[str, float | None]] = {
        "dairy": {"normal_low": 0.15, "normal_high": 0.35, "min_abs_deviation": 0.08},
        "beer": {"normal_low": 0.10, "normal_high": 0.35, "min_abs_deviation": 0.06},
        "alcohol": {"normal_low": 0.0, "normal_high": 0.30, "min_abs_deviation": 0.05},
    }
    return benchmarks.get(
        industry,
        {"normal_low": None, "normal_high": None, "min_abs_deviation": 0.05},
    )


def _contract_liability_decline(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    sample = rows[-4:]
    values = [_contract_liability(row) for row in sample]
    if len(values) < 3 or any(value is None for value in values):
        return []
    declines = 0
    for idx in range(len(values) - 1, 0, -1):
        if values[idx] < values[idx - 1]:
            declines += 1
        else:
            break
    if declines < 2:
        return []
    latest = sample[-1]
    revenue_growth = _growth(_v(sample[-1], "revenue"), _v(sample[-2], "revenue"))
    severity = "CRITICAL" if declines >= 3 and revenue_growth is not None and revenue_growth > 0 else "HIGH" if declines >= 3 else "MEDIUM"
    return [
        AuditFlag(
            "CONTRACT_LIABILITY_DECLINE",
            severity,
            str(latest["period"]),
            values[-1],
            "MEDIUM if down 2 years; HIGH if down 3 years; CRITICAL if down while revenue grows",
            f"合同负债/预收款连续下降{declines}年; latest={values[-1]:.2f}, revenue YoY={_format_optional_pct(revenue_growth)}",
            ["contract_liab", "adv_receipts", "revenue"],
            {"decline_years": declines, "revenue_growth": revenue_growth},
        )
    ]


def _gross_margin_deviation(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    sample = rows[-6:]
    margins = [_gross_margin(row) for row in sample]
    if len(margins) < 4 or any(value is None for value in margins):
        return []
    latest = margins[-1]
    history = margins[:-1]
    mean = statistics.mean(history)
    std = statistics.pstdev(history)
    if not std:
        return []
    deviation = (latest - mean) / std
    if abs(deviation) <= 2.0:
        return []
    severity = "HIGH" if abs(deviation) > 3.0 else "MEDIUM"
    return [
        AuditFlag(
            "GROSS_MARGIN_DEVIATION",
            severity,
            str(sample[-1]["period"]),
            latest,
            "MEDIUM if |deviation| > 2σ; HIGH if > 3σ",
            f"毛利率={latest:.1%}, 历史均值={mean:.1%}, deviation={deviation:.2f}σ",
            ["revenue", "oper_cost"],
            {"deviation_sigma": deviation},
        )
    ]


def _selling_expense_inefficiency(rows: list[dict[str, Any]]) -> list[AuditFlag]:
    prev, cur = rows[-2], rows[-1]
    sell_growth = _growth(_v(cur, "sell_exp"), _v(prev, "sell_exp"))
    revenue_growth = _growth(_v(cur, "revenue"), _v(prev, "revenue"))
    if sell_growth is None or revenue_growth is None:
        return []
    if abs(revenue_growth) < 0.03:
        current_ratio = _ratio(_v(cur, "sell_exp"), _v(cur, "revenue"))
        previous_ratio = _ratio(_v(prev, "sell_exp"), _v(prev, "revenue"))
        value = _growth(current_ratio, previous_ratio)
        if value is None or value <= 0.15:
            return []
        severity = "HIGH" if value > 0.30 else "MEDIUM"
        threshold = "MEDIUM if selling expense/revenue ratio grows >15%; HIGH if >30% when revenue growth is within +/-3%"
        evidence_text = (
            f"selling expense/revenue ratio growth={value:.2f}; "
            f"sales expense YoY={sell_growth:.1%}, revenue YoY={revenue_growth:.1%}"
        )
    elif revenue_growth <= 0:
        return []
    else:
        value = sell_growth / revenue_growth
        if value <= 2.0:
            return []
        severity = "HIGH" if value > 3.0 else "MEDIUM"
        threshold = "MEDIUM if >2.0; HIGH if >3.0"
        evidence_text = (
            f"selling expense elasticity={value:.2f}; "
            f"sales expense YoY={sell_growth:.1%}, revenue YoY={revenue_growth:.1%}"
        )
    if value is None:
        return []
    return [
        AuditFlag(
            "SELLING_EXPENSE_INEFFICIENCY",
            severity,
            str(cur["period"]),
            value,
            threshold,
            evidence_text,
            ["sell_exp", "revenue"],
            {},
        )
    ]


def _v(row: dict[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sum(row: dict[str, Any], *fields: str) -> float | None:
    values = [_v(row, field) for field in fields]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1.0


def _gross_margin(row: dict[str, Any]) -> float | None:
    revenue = _v(row, "revenue")
    cost = _v(row, "oper_cost")
    if revenue in (None, 0) or cost is None:
        return None
    return (revenue - cost) / revenue


def _asset_quality(row: dict[str, Any]) -> float | None:
    assets = _v(row, "total_assets")
    if not assets:
        return None
    hard_assets = sum(
        value or 0.0
        for value in [
            _v(row, "total_cur_assets"),
            _v(row, "fix_assets"),
            _v(row, "lt_eqt_invest"),
            _v(row, "oth_eq_invest"),
            _v(row, "oth_illiq_fin_assets"),
        ]
    )
    return 1.0 - hard_assets / assets


def _depreciation_rate(row: dict[str, Any]) -> float | None:
    depreciation = _v(row, "depr_fa_coga_dpba")
    fixed_assets = _v(row, "fix_assets")
    if depreciation is None or fixed_assets is None or depreciation + fixed_assets == 0:
        return None
    return depreciation / (depreciation + fixed_assets)


def _interest_bearing_debt(row: dict[str, Any]) -> float | None:
    return _sum(row, "st_borr", "lt_borr", "bond_payable")


def _contract_liability(row: dict[str, Any]) -> float | None:
    values = [_v(row, "contract_liab"), _v(row, "adv_receipts")]
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _slope(values: list[float | None]) -> float | None:
    pairs = [(idx, value) for idx, value in enumerate(values) if value is not None]
    if len(pairs) < 3:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom


def _round_dict(data: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 4) for key, value in data.items()}


def _format_optional_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="/audit financial health radar")
    parser.add_argument("--coverage", default="all", help="'all', comma-separated tickers/codes, or a file path")
    parser.add_argument("--top", type=int, default=20, help="Rows to show in risk_ranking.md")
    parser.add_argument("--with-evidence", action="store_true", help="Write per-company evidence packs")
    parser.add_argument("--no-tushare", action="store_true", help="Do not call TuShare auxiliary endpoints")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    result = run_audit(
        args.coverage,
        with_evidence=args.with_evidence,
        include_tushare=not args.no_tushare,
        top=args.top,
        output_root=Path(args.output_root),
        run_id=args.run_id,
    )
    print(f"/audit run {result.run_id}: {len(result.results)} companies -> {result.output_dir}")
    for item in result.results[: args.top]:
        print(f"{item.risk_level:8} {item.risk_score:4d} {item.ticker or '-':10} {item.company}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
