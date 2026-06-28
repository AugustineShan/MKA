"""Proactive TuShare gap fill — known fields that clean.py hard checks don't catch.

背景
----
clean.py 的硬校验是**失败驱动**：reconciler 只在年度硬失败时触发。当某字段 TuShare
留空但 revenue 本身正确、且该字段不进任何 subtotal 公式时（典型：`oth_b_income`
其他业务收入），clean 通过、reconciler 不跑，缺口被静默携带到 /comp 回测闸
（leaf base 和 vs clean_annual.revenue）才暴露，还常被误诊为"口径/rounding 差"。

本模块在 clean 成功后**主动**扫这类已知缺口字段，用确定性来源补 clean_annual：
写 approved override 到 `annual_report_overrides.json`，由下次 clean_all 应用
（raw_tushare 永不被改，补数只进 clean_adjustments，与 reconciler 同审计链）。

纪律
----
- 只补 TuShare=0/NULL 且有**确定性年报来源**的字段；不调 LLM，不改正既有非零值。
- 只填正向缺口（其他业务收入应为正）；负向或 rounding 级差额不填。
- 已有 approved override 的 cell 不重复写（source 优先级由 clean.load_approved_overrides 裁决）。
- 失败不阻塞 init（catch 后 warning）。
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from pathlib import Path
from contextlib import closing

from . import clean

LOGGER = logging.getLogger(__name__)

# 填值阈值：gap > max(1 Mn, 0.1% revenue) 才视为真实其他业务收入而非 rounding。
_GAP_MIN_MN = 1.0
_GAP_REV_PCT = 0.001


def _company_dir(db_path: Path) -> Path:
    return clean.company_dir_from_db_path(db_path)


def _breakdown_csv(db_path: Path) -> Path | None:
    """OfficialBreakdowns 全量分产品收入 CSV（annual product 维度）。"""
    d = _company_dir(db_path) / "Agent" / "OfficialBreakdowns"
    for name in ("business_revenue_breakdown_all.csv", "business_revenue_breakdown.csv"):
        p = d / name
        if p.exists():
            return p
    return None


def _product_sum_by_year(csv_path: Path) -> dict[int, float]:
    """{year_int: 主营业务收入 Mn} = Σ 年报分产品（dimension=product, annual）revenue_yuan / 1e6。

    年报"主营业务分产品"表按定义只拆主营业务收入（不含其他业务收入），故 Σ product
    = 主营业务收入，可作 `oth_b_income = revenue − Σ product` 的确定性来源。
    """
    sums: dict[int, float] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("dimension") != "product" or row.get("period_type") != "annual":
                continue
            year_str = row.get("year") or ""
            if not year_str.isdigit():
                continue
            raw = (row.get("revenue_yuan") or "").replace(",", "").strip()
            if not raw:
                continue
            try:
                val_yuan = float(raw)
            except ValueError:
                continue
            sums[int(year_str)] = sums.get(int(year_str), 0.0) + val_yuan / 1_000_000.0
    return sums


def _clean_revenue_and_oth_b(db_path: Path) -> dict[int, tuple[float, float]]:
    """{year_int: (revenue_mn, oth_b_income_mn)} from clean_annual."""
    out: dict[int, tuple[float, float]] = {}
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            "SELECT period, revenue, oth_b_income FROM clean_annual ORDER BY period"
        )
        for period, rev, oth_b in cur.fetchall():
            try:
                year = int(str(period)[:4])
            except (TypeError, ValueError):
                continue
            out[year] = (float(rev or 0.0), float(oth_b or 0.0))
    return out


def _existing_approved_cells(override_path: Path, ticker: str) -> set[tuple[str, str]]:
    """已存在 approved override 的 (period, column) 集合，避免重复写。"""
    if not override_path.exists():
        return set()
    try:
        data = json.loads(override_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    cells: set[tuple[str, str]] = set()
    for item in data.get("adjustments", []):
        if item.get("status") != "approved":
            continue
        period = str(item.get("period") or "")
        column = clean.override_column_name(
            str(item.get("endpoint") or ""), str(item.get("field") or "")
        )
        cells.add((period, column))
    return cells


def _merge_overrides(override_path: Path, ticker: str, new_records: list[dict]) -> None:
    """合并追加新 override 记录，保留既有记录与 ticker。"""
    if override_path.exists():
        try:
            data = json.loads(override_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    data.setdefault("ticker", ticker)
    data.setdefault("adjustments", [])
    data["adjustments"].extend(new_records)
    override_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def proactive_fill_oth_b_income(db_path: Path, ticker: str) -> int:
    """补 oth_b_income：TuShare=0 时用 clean.revenue − Σ 分产品收入 填其他业务收入。

    返回新写入的 approved override 条数。
    """
    db_path = Path(db_path)
    csv_path = _breakdown_csv(db_path)
    if csv_path is None:
        LOGGER.info("proactive_gap_fill: 无 OfficialBreakdowns，跳过 oth_b_income")
        return 0

    product_sum = _product_sum_by_year(csv_path)
    if not product_sum:
        LOGGER.info("proactive_gap_fill: OfficialBreakdowns 无 annual product 行，跳过")
        return 0

    clean_rows = _clean_revenue_and_oth_b(db_path)
    override_path = clean.default_overrides_path(db_path)
    existing = _existing_approved_cells(override_path, ticker)

    new_records: list[dict] = []
    for year, (rev, oth_b) in sorted(clean_rows.items()):
        if year not in product_sum:
            continue
        # 只补 TuShare 留空（oth_b_income ≈ 0）的 cell
        if abs(oth_b) >= 1e-9:
            continue
        psum = product_sum[year]
        gap = rev - psum  # = 其他业务收入（营业收入 − 主营业务收入）
        threshold = max(_GAP_MIN_MN, _GAP_REV_PCT * abs(rev))
        # 只填正向真实缺口；负向/rounding 不填
        if gap <= threshold:
            continue
        period = str(year)
        column = clean.override_column_name("income", "oth_b_income")
        if (period, column) in existing:
            continue
        new_records.append(
            {
                "period": period,
                "endpoint": "income",
                "field": "oth_b_income",
                "new_value_million_cny": gap,
                "status": "approved",
                "source": "proactive",
                "approved_by": "proactive_gap_fill:revenue_minus_product_breakdown",
                "confidence": "high",
                "annual_report_item": "其他业务收入",
                "failure_code": None,
                "reason": (
                    f"TuShare oth_b_income=0（披露缺口，known_tushare_defects 同族）；"
                    f"clean.revenue({rev:.2f}) − Σ年报分产品收入/主营业务收入({psum:.2f}) "
                    f"= 其他业务收入 {gap:.2f} Mn。确定性补数，非 LLM。"
                ),
                "source_markdown_path": str(csv_path),
                "evidence_lines": (
                    f"{year}: clean.revenue={rev:.2f} Mn, Σproduct={psum:.2f} Mn, gap={gap:.2f} Mn"
                ),
            }
        )
        LOGGER.info(
            "proactive_gap_fill: %s oth_b_income %s = %.2f Mn (revenue %.2f − product %.2f)",
            ticker, year, gap, rev, psum,
        )

    if new_records:
        _merge_overrides(override_path, ticker, new_records)
        LOGGER.info(
            "proactive_gap_fill: %s 写入 %d 条 oth_b_income override → %s",
            ticker, len(new_records), override_path,
        )
    return len(new_records)


def proactive_field_gap_fill(db_path: Path, ticker: str) -> int:
    """入口：跑全部白名单字段的主动补缺。返回新写入 override 总条数。

    当前白名单：oth_b_income（其他业务收入）。后续可按 known_tushare_defects 同族扩展。
    """
    return proactive_fill_oth_b_income(db_path, ticker)
