"""Clean raw TuShare EAV data into validated wide tables in SQLite.

Public API:
    clean("D:\\MKA\\companies\\安克创新_300866\\Agent\\data.db", "300866.SZ") -> pd.DataFrame
"""

from __future__ import annotations

import logging
import json
import itertools
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pandas as pd

from src.company_paths import (
    company_dir_from_db_path,
    find_db_path as find_agent_db_path,
    recon_dir,
    annual_reports_dir,
)

from .field_registry import (
    IS_FIELD_CATEGORIES, BS_FIELD_CATEGORIES, CF_FIELD_CATEGORIES,
    IS_SUB_RESOLVE, CF_SUB_RESOLVE, COMBO_RESOLVE,
    SIGN_QUESTIONABLE_IS_FIELDS,
)

LOGGER = logging.getLogger("clean")

TOLERANCE = 1.0  # 百万元，残差容差
ANNUAL_TOLERANCE = 1.0
QUARTERLY_TOLERANCE = 1.0

# 年度硬校验失败只对 2010 及以后触发年报核对（annual_report_reconciler）；
# 2010 之前的年度披露稀疏、格式早期，不值得对年报核对，clean 直接入库
# （硬错误降级为 warning，不阻塞、不触发 reconciler）。
RECONCILE_MIN_YEAR = 2010


def earliest_annual_md_year(db_path: str | Path) -> int | None:
    """Earliest fiscal year for which a cninfo annual-report Markdown exists locally.

    IPO-boundary proxy: a公司上市前年份的 TuShare 数据来自招股说明书，cninfo 上
    没有该年年度报告 PDF/Markdown，reconciler 无 MD 可核对。本函数扫描
    ``companies/{公司}/公告/年报/*_年度报告.md`` 取最小年份作为"IPO 后首份年报"。
    clean 的 pre-IPO 闸门据此把早于该年的年度硬校验失败降级为 warning（不阻塞、
    不触发 reconciler）；reconciler 的 collect_failures 也据此跳过这些年，避免
    在无 MD 的 pre-IPO 年上空跑 LLM / 造脏 override。无年报 MD 时返回 None（闸门
    关闭，退回原行为）。
    """
    reports_dir = annual_reports_dir(company_dir_from_db_path(Path(db_path)))
    years: list[int] = []
    for md in reports_dir.glob("*_年度报告.md"):
        m = re.match(r"(\d{4})", md.stem)
        if m:
            years.append(int(m.group(1)))
    return min(years) if years else None


def period_year(period) -> int:
    """Leading 4-digit year of a period label ('2022' or '20221231' → 2022).

    Unparseable labels return a large int so they are never treated as pre-min-year.
    """
    try:
        return int(str(period)[:4])
    except (ValueError, TypeError):
        return 9999


# TuShare balancesheet total_share 是股数（百万股），不是股本(元)。权益校验需
# 股本(元)=par×total_share。面值是公司级离散法定常量，按权益恒等式跨年推断。
COMMON_PAR_VALUES = (1.0, 0.1, 0.5, 0.2, 0.05, 0.02, 0.01)


def infer_par_value(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
    bs_reclass_by_period: dict[str, dict[str, str]] | None = None,
) -> float:
    """Infer the company's share par value (面值).

    TuShare ``total_share`` is the share COUNT (百万股), not 股本(元); the equity
    bucket must use 股本(元) = par × total_share. For par=1 companies (most
    A-shares) shares numerically equal 股本(元) so BS 4.1 balances; for par≠1
    (e.g. 紫金矿业 par 0.1) it fails by (1-par)×total_share. par is a discrete
    legal constant, so infer it by picking the value that makes the equity
    identity (Σ equity leaves, with total_share scaled by par) hold for the most
    periods. Returns 1.0 when no alternative strictly beats 1.0, so par=1
    companies are unaffected and genuine component errors (no par fits) still
    fail the check naturally.
    """
    bs_reclass_by_period = bs_reclass_by_period or {}
    samples: list[tuple[float, float, float]] = []  # (equity_raw, total_share, target)
    for period in sorted(str(p) for p in wide.index.tolist()):
        row = wide.loc[period].to_dict()
        present = present_by_period.get(period, set())
        reclass = bs_reclass_by_period.get(period)
        equity_raw = bs_bucket_sum("equity", row, present, reclass)
        total_share = float(row.get("total_share") or 0.0)
        target = float(row.get("total_hldr_eqy_inc_min_int") or 0.0)
        if total_share and target:
            samples.append((equity_raw, total_share, target))
    if not samples:
        return 1.0
    best_par, best_count = 1.0, 0
    for p in COMMON_PAR_VALUES:
        count = sum(
            1
            for equity_raw, ts, target in samples
            if abs((equity_raw + (p - 1.0) * ts) - target) < TOLERANCE
        )
        if count > best_count:
            best_par, best_count = p, count
    return best_par

QUARTER_BY_SUFFIX = {
    "0331": "Q1",
    "0630": "Q2",
    "0930": "Q3",
    "1231": "Q4",
}

QA_BS_PLUG_FIELDS: dict[str, str] = {
    "current_asset": "qa_bs_current_asset_plug",
    "noncurrent_asset": "qa_bs_noncurrent_asset_plug",
    "current_liab": "qa_bs_current_liab_plug",
    "noncurrent_liab": "qa_bs_noncurrent_liab_plug",
    "equity": "qa_bs_equity_plug",
}

QA_CF_CASH_PLUG_FIELD = "qa_cf_cash_reconcile_plug"
QA_FIELDS = sorted([*QA_BS_PLUG_FIELDS.values(), QA_CF_CASH_PLUG_FIELD])
APPROVED_OVERRIDE_SOURCES = {"glm", "kimi", "claude"}
# audit H4:override 文件跨运行 merge-append,同一 (period, 解析后列名) 可能累积多条
# approved 记录(不同 source / 不同 new_value)。旧实现按列表序 last-write-wins=非确定。
# 这里按显式 source 优先级裁决,保证可复现:claude(subagent bridge 逐数字证据闭合)
# > glm(rule+LLM) > kimi(旧)。同 cell 不同值的冲突显式 LOG.warning,不静默。
OVERRIDE_SOURCE_PRECEDENCE = ("claude", "glm", "kimi")
# "claude" 来源的 override 由 init skill 的 subagent 升级通道产出（见
# src/recon_subagent_bridge.py）：subagent 读年报干净 Markdown 定位科目金额，
# bridge 服务端按净残差验闭合后才标 approved。与 glm/kimi 同等审计可追溯。

# ── 跨端点同名字段（需在 pivot 时消歧） ───────────────────────
# credit_impa_loss 同时存在于 income 和 cashflow，值可能不同
CROSS_ENDPOINT_FIELDS = {"credit_impa_loss"}


# IS_FIELD_CATEGORIES / IS_SUB_RESOLVE / SIGN_QUESTIONABLE_IS_FIELDS
# 统一来自 field_registry(单一真源,见 src/field_registry.yaml)。

OPTIONAL_IS_ADJUSTMENT_FIELDS = {
    "oth_income",
    "credit_impa_loss",
    "oth_impair_loss_assets",
    "asset_disp_income",
    "net_expo_hedging_benefits",
    "forex_gain",
}


# CF_FIELD_CATEGORIES / CF_SUB_RESOLVE → field_registry(单一真源)。

def _bucket_sum(
    categories: dict[str, str],
    sub_resolve: dict[str, list[str]],
    getter: callable,
    bucket: str,
    row: dict[str, float],
    present: set[str],
) -> float:
    """Generic bucket sum; sub-items are skipped (already in parent)."""
    total = 0.0
    for field, cat in categories.items():
        if cat != bucket:
            continue
        # Skip fields that are sub-items of another field
        if any(field in subs for subs in sub_resolve.values()):
            continue
        total += getter(row, field)
    return total


def is_bucket_sum(bucket: str, row: dict[str, float], present: set[str]) -> float:
    """Sum all fields in an IS bucket; sub-items skipped."""
    return _bucket_sum(IS_FIELD_CATEGORIES, IS_SUB_RESOLVE, get_income_value, bucket, row, present)


def cf_bucket_sum(bucket: str, row: dict[str, float], present: set[str]) -> float:
    """Sum all fields in a CF bucket; sub-items skipped."""
    return _bucket_sum(CF_FIELD_CATEGORIES, CF_SUB_RESOLVE, get_cashflow_value, bucket, row, present)

# BS_FIELD_CATEGORIES / COMBO_RESOLVE → field_registry(单一真源)。

PREFER_COMBO_FIELDS = {"oth_pay_total"}


# ── resolve 逻辑 ───────────────────────────────────────────────

def resolve(
    split_fields: list[str],
    combo_field: str,
    row: dict[str, float],
    present_fields: set[str],
) -> float:
    """Return the value for a merged/split field group.

    1. If ALL split_fields are in present_fields → sum split values
    2. Else if combo_field is in present_fields → use combo value
    3. Else → 0.0
    """
    if combo_field in PREFER_COMBO_FIELDS and combo_field in present_fields:
        combo_val = row.get(combo_field, 0.0)
        if combo_val != 0.0:
            return combo_val

    if all(f in present_fields for f in split_fields):
        split_sum = sum(row.get(f, 0.0) for f in split_fields)
        # If combo is also present and split sum is 0 but combo is non-zero,
        # the company reports only the aggregate (e.g. oth_receiv=0 but
        # oth_rcv_total=126.61). Use combo as authoritative.
        if split_sum == 0.0 and combo_field in present_fields:
            combo_val = row.get(combo_field, 0.0)
            if combo_val != 0.0:
                return combo_val
        return split_sum
    if combo_field in present_fields:
        return row.get(combo_field, 0.0)
    return 0.0


def bs_bucket_sum(
    bucket: str,
    row: dict[str, float],
    present: set[str],
    reclass: dict[str, str] | None = None,
) -> float:
    """Sum all fields in a BS bucket, handling combo/resolve logic.

    Atomic fields in the bucket are summed directly.  Combo fields that
    belong to the bucket are resolved (split parts vs combo value) and
    added.  Split parts are skipped to avoid double counting.

    ``reclass`` lets an approved annual-report override move a field into a
    different bucket for one period (e.g. 比亚迪 estimated_liab 预计负债 列报为
    流动而非 TuShare 默认的非流动)。它只覆盖 BS_FIELD_CATEGORIES 的静态归类，
    不修改全局分类，也不影响其他公司/期间。
    """
    reclass = reclass or {}
    # Atomic fields belonging to this bucket（含被 override 重分类进来的字段）
    atomic_fields = [
        f for f, c in BS_FIELD_CATEGORIES.items() if reclass.get(f, c) == bucket
    ]

    # Which fields are split parts of combos in this bucket?
    skip: set[str] = set()
    combo_fields: list[str] = []
    for combo, (splits, combo_bucket) in COMBO_RESOLVE.items():
        if combo_bucket == bucket:
            skip.update(splits)
            combo_fields.append(combo)

    # Quarterly disclosure quirks
    if bucket == "current_asset" and row.get("oth_receiv", 0.0) == 0.0 and row.get("oth_rcv_total", 0.0) != 0.0:
        skip.update({"int_receiv", "div_receiv"})
    if bucket == "noncurrent_liab" and row.get("lt_payable", 0.0) == 0.0 and row.get("long_pay_total", 0.0) != 0.0:
        skip.add("specific_payables")

    total = 0.0
    for f in atomic_fields:
        if f in skip:
            continue
        if f == "treasury_share":
            total -= row.get(f, 0.0)
        else:
            total += row.get(f, 0.0)

    # Add combo values via resolve (handles split-vs-combo mutual exclusion)
    for combo in combo_fields:
        splits, _ = COMBO_RESOLVE[combo]
        total += resolve(splits, combo, row, present)

    plug_field = QA_BS_PLUG_FIELDS.get(bucket)
    if plug_field:
        total += row.get(plug_field, 0.0)

    return total


def ensure_qa_columns(wide: pd.DataFrame) -> pd.DataFrame:
    for field in QA_FIELDS:
        if field not in wide.columns:
            wide[field] = 0.0
    return wide


# ── 数据读取与透视 ─────────────────────────────────────────────

def load_raw_tushare(conn: sqlite3.Connection, ticker: str, *, mode: str) -> pd.DataFrame:
    """Read raw_tushare for annual or quarterly cleaning."""
    if mode == "annual":
        where = "ticker = ? AND report_type = '1' AND comp_type = '1'"
    elif mode == "quarterly":
        # income report_type=2 provides true single-quarter data when available.
        # We also read report_type=1 as a fallback so that BS/CF data for a
        # quarter is not silently dropped just because single-quarter income is
        # missing.  balancesheet is point-in-time, so report_type=1 is used
        # directly.  cashflow report_type=1 quarterly cumulative data is split
        # locally in split_cashflow_quarterly().
        where = (
            "ticker = ? AND comp_type = '1' AND ("
            "(endpoint = 'income' AND report_type IN ('1', '2')) OR "
            "(endpoint IN ('balancesheet', 'cashflow') AND report_type = '1')"
            ")"
        )
    else:
        raise ValueError(f"Unknown clean mode: {mode}")

    df = pd.read_sql_query(
        f"SELECT * FROM raw_tushare WHERE {where}",
        conn,
        params=(ticker,),
    )
    if df.empty:
        raise RuntimeError(f"No raw_tushare data for {ticker} in {mode} mode")
    return df


def dedupe_by_f_ann_date(df: pd.DataFrame) -> pd.DataFrame:
    """For same (endpoint, end_date, field), keep row with max f_ann_date.

    For income in quarterly mode, single-quarter report_type='2' takes
    precedence over cumulative report_type='1' so that a missing rt2 does not
    silently drop the whole quarter; if rt2 is absent, rt1 is kept as fallback.
    """
    if df.empty:
        return df
    df = df.copy()
    df["_f_ann_sort"] = df["f_ann_date"].fillna("")
    # Prefer income report_type=2 over report_type=1 when both exist.
    df["_rt_sort"] = df.apply(
        lambda r: (
            0
            if r.get("endpoint") == "income" and str(r.get("report_type")) == "2"
            else 1
        ),
        axis=1,
    )
    df = df.sort_values(
        ["endpoint", "end_date", "field", "_rt_sort", "_f_ann_sort"],
        ascending=[True, True, True, False, True],
    )
    df = df.drop_duplicates(subset=["endpoint", "end_date", "field"], keep="last")
    df = df.drop(columns=["_f_ann_sort", "_rt_sort"])
    return df


def period_label(end_date: str) -> str | None:
    if len(end_date) != 8 or not end_date[:4].isdigit():
        return None
    quarter = QUARTER_BY_SUFFIX.get(end_date[4:])
    if quarter is None:
        return None
    return f"{end_date[:4]}{quarter}"


def pivot_to_wide(
    df: pd.DataFrame,
    *,
    mode: str,
    max_quarters: int = 48,
) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    """Pivot EAV to wide table, handling cross-endpoint field name collisions.

    For fields that exist in multiple endpoints (e.g. credit_impa_loss
    in both income and cashflow), prefix with endpoint name.

    Returns (wide_df, present_fields_by_period).
    """
    df = df.copy()
    if mode == "annual":
        df = df[df["end_date"].astype(str).str.endswith("1231")]
        df["period"] = df["end_date"].astype(str).str[:4]
        latest_periods = sorted(df["period"].unique())[-10:]
        df = df[df["period"].isin(latest_periods)]
    elif mode == "quarterly":
        df["period"] = df["end_date"].astype(str).map(period_label)
        df = df[df["period"].notna()]
        income_single_periods = set(
            df[
                (df["endpoint"] == "income")
                & (df["report_type"].astype(str) == "2")
            ]["period"].tolist()
        )
        income_any_periods = set(
            df[df["endpoint"] == "income"]["period"].tolist()
        )
        missing_single_quarter_income = income_any_periods - income_single_periods
        if missing_single_quarter_income:
            LOGGER.warning(
                "Income report_type=2 missing for quarterly periods %s; "
                "report_type=1 cumulative values will be used as fallback where available. "
                "Single-quarter income semantics may be affected.",
                sorted(missing_single_quarter_income),
            )
        # Keep only last 12 years of quarters to avoid early-disclosure quirks
        all_periods = sorted(str(p) for p in df["period"].unique())
        cashflow_periods = set(
            str(p) for p in df[df["endpoint"] == "cashflow"]["period"].unique()
        )

        def previous_cf_period(period: str) -> str | None:
            quarter = period[4:]
            if quarter == "Q1":
                return None
            previous = {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3"}.get(quarter)
            return f"{period[:4]}{previous}" if previous else None

        def cf_buildable(period: str) -> bool:
            if period not in cashflow_periods:
                return False
            previous = previous_cf_period(period)
            return previous is None or previous in cashflow_periods

        buildable_periods = [period for period in all_periods if cf_buildable(period)]
        candidate_periods = buildable_periods or all_periods
        if max_quarters > 0 and len(candidate_periods) > max_quarters:
            dropped_periods = candidate_periods[:-max_quarters]
            output_periods = candidate_periods[-max_quarters:]
            LOGGER.warning(
                "Quarterly mode dropped %d early period(s) beyond max_quarters=%d: %s",
                len(dropped_periods),
                max_quarters,
                dropped_periods,
            )
        else:
            output_periods = candidate_periods

        # Cashflow data is cumulative inside a year. Keep only the output
        # periods plus their immediate cumulative predecessors as split helpers.
        helper_periods_set = set(output_periods)
        for period in output_periods:
            previous = previous_cf_period(period)
            if previous:
                helper_periods_set.add(previous)
        helper_periods = [period for period in all_periods if period in helper_periods_set]
        df = df[df["period"].isin(helper_periods)]
    else:
        raise ValueError(f"Unknown clean mode: {mode}")

    if df.empty:
        raise RuntimeError(f"No {mode} rows after report-period filtering")

    # Detect cross-endpoint field name collisions
    field_endpoints: dict[str, set[str]] = {}
    for field, group in df.groupby("field"):
        field_endpoints[field] = set(group["endpoint"].unique())

    collision_fields = {f for f, eps in field_endpoints.items() if len(eps) > 1}

    # Rename colliding fields: "field" → "endpoint.field"
    def rename_field(row: pd.Series) -> str:
        if row["field"] in collision_fields:
            return f"{row['endpoint']}.{row['field']}"
        return row["field"]

    df["_col"] = df.apply(rename_field, axis=1)

    # Build present_fields (using original field names, not prefixed)
    present_by_period: dict[str, set[str]] = {}
    # null_fields_by_period: income-endpoint fields whose raw value is NULL,
    # captured BEFORE fillna(0) so the validator can distinguish a TuShare
    # data-source gap (NULL → hard-fail IS 1.2 → reconciler backfills) from a
    # company-reported 0 (legit empty optional adjustment). Income-only because
    # missing_optional gates IS checks; a cashflow credit_impa_loss NULL must
    # not masquerade as an income gap.
    null_fields_by_period: dict[str, set[str]] = {}
    for period, group in df.groupby("period"):
        present_by_period[str(period)] = set(group["field"].tolist())
        income_group = group[group["endpoint"] == "income"]
        null_fields_by_period[str(period)] = set(
            income_group.loc[income_group["value"].isna(), "field"].tolist()
        )

    # Pivot using renamed columns
    # Collect ALL column names before pivot so that all-NaN columns are not
    # silently dropped by pivot_table.  This ensures every company outputs the
    # same column set (all TuShare fields), filling missing values with 0.
    all_columns = sorted(df["_col"].unique())

    pivot = df.pivot_table(
        index="period",
        columns="_col",
        values="value",
        aggfunc="first",
    )
    # Re-index columns to include every field, even those that are all-NaN
    pivot = pivot.reindex(columns=all_columns)
    pivot = pivot.fillna(0.0)
    pivot = ensure_qa_columns(pivot)
    pivot.attrs["null_fields_by_period"] = null_fields_by_period
    if mode == "quarterly":
        pivot.attrs["output_periods"] = output_periods
        pivot.attrs["helper_periods"] = helper_periods

    return pivot, present_by_period


CF_BEG_END_FIELDS = {"c_cash_equ_beg_period", "c_cash_equ_end_period"}


def cashflow_column_map(wide: pd.DataFrame, raw: pd.DataFrame) -> dict[str, str]:
    cf_fields = set(raw[raw["endpoint"] == "cashflow"]["field"].unique())
    col_to_field: dict[str, str] = {}
    for col in wide.columns:
        if col.startswith("cashflow."):
            orig = col[len("cashflow."):]
            if orig in cf_fields:
                col_to_field[col] = orig
        elif col in cf_fields:
            col_to_field[col] = col
    return col_to_field


def split_cashflow_quarterly(wide: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Split cumulative cashflow quarterly data into single-quarter values.

    For each year:
        Q1 (0331) = Q1 cumulative (unchanged)
        Q2 (0630) = H1 cumulative - Q1 cumulative
        Q3 (0930) = Q3 cumulative - H1 cumulative
        Q4 (1231) = Annual cumulative - Q3 cumulative

    Also adjusts ``c_cash_equ_beg_period`` to the previous quarter's
    ``c_cash_equ_end_period`` so that CF 5.5 (end = beg + net change)
    continues to hold at the single-quarter level.
    """
    cf_fields = set(raw[raw["endpoint"] == "cashflow"]["field"].unique())
    if not cf_fields:
        LOGGER.warning("No cashflow fields found; skipping quarterly split")
        return wide

    col_to_field = cashflow_column_map(wide, raw)

    # Columns to split: all CF flow fields except point-in-time beg/end
    split_cols = [
        col for col, field in col_to_field.items()
        if field not in CF_BEG_END_FIELDS
    ]

    # Locate beg/end columns (may carry endpoint prefix)
    beg_col = end_col = None
    for col, field in col_to_field.items():
        if field == "c_cash_equ_beg_period":
            beg_col = col
        elif field == "c_cash_equ_end_period":
            end_col = col

    # Group periods by year
    year_periods: dict[str, list[str]] = {}
    for period in wide.index:
        p = str(period)
        if len(p) >= 5 and p[4:] in QUARTER_BY_SUFFIX.values():
            year_periods.setdefault(p[:4], []).append(p)

    result = wide.copy()

    prev_quarter = {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3"}
    output_periods = set(str(period) for period in wide.attrs.get("output_periods", wide.index.tolist()))

    for year, periods in year_periods.items():
        q_map: dict[str, str] = {}
        for p in periods:
            q_map[p[4:]] = p

        # Split cumulative flow fields into single-quarter values
        for col in split_cols:
            cumulative = {q: float(wide.loc[p, col]) for q, p in q_map.items()}
            for q in ("Q2", "Q3", "Q4"):
                if q not in q_map:
                    continue
                prev_q = prev_quarter[q]
                if prev_q not in q_map:
                    if q_map[q] in output_periods:
                        LOGGER.warning(
                            "CF split left cumulative value for %s%s %s: missing %s helper",
                            year,
                            q,
                            col,
                            prev_q,
                        )
                    continue
                result.loc[q_map[q], col] = cumulative[q] - cumulative[prev_q]

        # Adjust beg cash to previous quarter's end cash
        if beg_col is not None and end_col is not None:
            for q in ("Q2", "Q3", "Q4"):
                if q not in q_map:
                    continue
                prev_q = prev_quarter[q]
                if prev_q in q_map:
                    result.loc[q_map[q], beg_col] = wide.loc[q_map[prev_q], end_col]

    result.attrs = wide.attrs.copy()

    return result


def filter_to_output_periods(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    output_periods = wide.attrs.get("output_periods")
    if not output_periods:
        return wide, present_by_period

    keep = [period for period in output_periods if period in wide.index]
    filtered = wide.loc[keep].copy()
    filtered.attrs = wide.attrs.copy()
    filtered_present = {
        period: present_by_period.get(period, set())
        for period in keep
    }
    return filtered, filtered_present


def raw_cashflow_quarterly_wide(raw: pd.DataFrame) -> pd.DataFrame:
    cf = raw[raw["endpoint"] == "cashflow"].copy()
    if cf.empty:
        return pd.DataFrame()
    cf["period"] = cf["end_date"].astype(str).map(period_label)
    cf = cf[cf["period"].notna()]
    if cf.empty:
        return pd.DataFrame()
    return cf.pivot_table(
        index="period",
        columns="field",
        values="value",
        aggfunc="first",
    ).fillna(0.0)


def validate_quarterly_cf_split(
    wide: pd.DataFrame,
    raw: pd.DataFrame,
    *,
    tolerance: float,
) -> list[str]:
    """Hard-check that clean quarterly CF equals raw cumulative differences."""
    raw_cf = raw_cashflow_quarterly_wide(raw)
    if raw_cf.empty:
        return ["CF split audit: no raw cashflow rows are available"]

    col_to_field = cashflow_column_map(wide, raw)
    split_cols = [
        col for col, field in col_to_field.items()
        if field not in CF_BEG_END_FIELDS
    ]
    if not split_cols:
        return ["CF split audit: no cashflow flow columns are available"]

    errors: list[str] = []
    prev_quarter = {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3"}
    raw_periods = set(str(period) for period in raw_cf.index.tolist())

    for period in sorted(str(p) for p in wide.index.tolist()):
        if len(period) < 6 or period[-2] != "Q":
            continue
        if period not in raw_periods:
            errors.append(f"CF split audit {period}: raw cashflow period is missing")
            continue

        year = period[:4]
        quarter = period[4:]
        prev_period = None
        if quarter in prev_quarter:
            prev_period = f"{year}{prev_quarter[quarter]}"
            if prev_period not in raw_periods:
                errors.append(
                    f"CF split audit {period}: missing raw {prev_period} helper for cumulative-to-single-quarter split"
                )
                continue

        for col in split_cols:
            field = col_to_field[col]
            current_raw = float(raw_cf.loc[period, field]) if field in raw_cf.columns else 0.0
            if prev_period is None:
                expected = current_raw
            else:
                prev_raw = float(raw_cf.loc[prev_period, field]) if field in raw_cf.columns else 0.0
                expected = current_raw - prev_raw
            actual = float(wide.loc[period, col])
            residual = abs(actual - expected)
            if residual >= tolerance:
                errors.append(
                    f"CF split audit {period} {field}: clean={actual:.4f} "
                    f"raw_diff={expected:.4f} residual={residual:.4f}"
                )
                if len(errors) >= 50:
                    return errors

    return errors


# ── 校验引擎 ───────────────────────────────────────────────────

class CheckError(Exception):
    """Raised when a hard check fails."""


def get_value(row: dict[str, float], field: str) -> float:
    """Get value from row, default 0.0."""
    return row.get(field, 0.0)


def get_income_value(row: dict[str, float], field: str) -> float:
    """Get income-endpoint value from row (handles cross-endpoint prefix)."""
    prefixed = f"income.{field}"
    if prefixed in row:
        return row[prefixed]
    return row.get(field, 0.0)


def get_cashflow_value(row: dict[str, float], field: str) -> float:
    """Get cashflow-endpoint value from row (handles cross-endpoint prefix)."""
    prefixed = f"cashflow.{field}"
    if prefixed in row:
        return row[prefixed]
    return row.get(field, 0.0)


def signed_is_cost_sum(row: dict[str, float], sign_map: dict[str, int] | None) -> float:
    """Sum cost_item fields excluding sign-questionable impairment fields.

    When a sign_map is provided, impairment-like fields are handled in the
    adjustment sum instead of the cost sum.
    """
    total = 0.0
    for field, cat in IS_FIELD_CATEGORIES.items():
        if cat != "cost_item":
            continue
        if any(field in subs for subs in IS_SUB_RESOLVE.values()):
            continue
        if field in SIGN_QUESTIONABLE_IS_FIELDS:
            continue
        total += get_income_value(row, field)
    return total


def signed_is_adjustment_sum(row: dict[str, float], sign_map: dict[str, int] | None) -> float:
    """Sum operating_adjustment fields plus sign-questionable fields with resolved signs."""
    total = base_is_adjustment_sum(row)
    for field in SIGN_QUESTIONABLE_IS_FIELDS:
        if sign_map and field in sign_map:
            total += sign_map[field] * get_income_value(row, field)
        else:
            total += get_income_value(row, field)
    return total


def base_is_adjustment_sum(row: dict[str, float]) -> float:
    """Sum operating adjustments excluding sign-questionable impairment fields."""
    total = 0.0
    for field, cat in IS_FIELD_CATEGORIES.items():
        if cat != "operating_adjustment":
            continue
        if field in SIGN_QUESTIONABLE_IS_FIELDS:
            continue
        total += get_income_value(row, field)
    return total


def missing_optional_is_adjustments(
    row: dict[str, float],
    present: set[str],
    null_fields: set[str] | None = None,
) -> list[str]:
    """Return optional operating adjustments that are present, truly 0, and NOT raw-NULL.

    A field counts as "optional-empty" (→ trust official subtotal, no hard-fail)
    only when the company actually reported 0. A TuShare NULL (captured in
    null_fields_by_period before fillna(0)) is a data-source gap, not a reported
    0 — excluding it makes the gap surface as an IS 1.2 hard failure so the
    reconciler fires and backfills from the annual report. Without this, fillna(0)
    erases the NULL-vs-0 distinction and the gap is silently swallowed.
    """
    null_set = null_fields or set()
    missing: list[str] = []
    for field in sorted(OPTIONAL_IS_ADJUSTMENT_FIELDS):
        if field in null_set:
            continue
        if field in present and abs(get_income_value(row, field)) <= 1e-9:
            missing.append(field)
    return missing


def resolve_is_signs(
    row: dict[str, float],
    present: set[str],
    year: str,
    tolerance: float = TOLERANCE,
    raw_total_cogs: float | None = None,
) -> tuple[dict[str, int] | None, list[str]]:
    """Resolve signs for impairment-like fields, per-year data-driven regime.

    The 2017→2019 三版报表格式修订（财会30号/15号/6号）让 sign-questionable 字段
    的口径随公司/年份而变，不是单一全局断点：assets_impair_loss 旧口径(pre-6号)以
    正数损失记在 total_cogs 内，6号起改为"损失以'-'号填列"的独立调整项；credit_impair_loss
    /oth_impair_loss_assets 出生即为独立调整项。故 regime 按"该字段是否在 total_cogs
    内"逐年逐字段判定，不硬编码年份。

    The identity used is:
        operate_profit = revenue_base
                         - sum(stable cost_item fields)
                         + sum(operating_adjustment fields)
                         + sum(sign_f * value_f for f in questionable fields)

    Regime detection: ``raw_total_cogs − stable_cost_sum`` 是 total_cogs 中超出
    稳定成本明细的部分。若某 questionable 字段值 ≈ 该残差，说明它被记在 total_cogs
    内（旧口径）→ semantic sign −1（正数损失应作负调整）；否则 +1（保留披露符号，新
    口径损失已为负）。``raw_total_cogs`` 必须是 adaptation 前的官方值（adaptation 会
    把 total_cogs 改成明细和、剔除 impair，破坏信号）；调用方从
    ``wide.attrs["raw_total_cogs_by_period"]`` 传入，未传则回退 row["total_cogs"]。

    Exhaustive residual minimisation is only allowed to override the regime
    default when the improvement is large enough to exceed small-item noise.

    All inputs come from the same TuShare income table, so residuals are a
    sanity check on internal consistency, not an independent cross-validation.

    Returns (sign_map, warnings). sign_map is None when signs cannot be
    resolved. Warnings are emitted instead of errors; callers decide whether
    to hard-fail. The residual is never absorbed into a plug field.
    """
    revenue = get_income_value(row, "revenue")
    total_revenue = get_income_value(row, "total_revenue")
    other_revenue = (
        get_income_value(row, "int_income")
        + get_income_value(row, "comm_income")
        + get_income_value(row, "n_oth_b_income")
    )
    revenue_base = revenue
    if abs(total_revenue - revenue) >= tolerance and abs(total_revenue - revenue - other_revenue) < tolerance:
        revenue_base = total_revenue

    operate_profit = get_income_value(row, "operate_profit")

    stable_cost_sum = signed_is_cost_sum(row, None)
    stable_adj_sum = base_is_adjustment_sum(row)

    Q_present = [
        f
        for f in SIGN_QUESTIONABLE_IS_FIELDS
        if f in present and abs(get_income_value(row, f)) > 1e-9
    ]
    if not Q_present:
        return {}, []

    base = revenue_base - stable_cost_sum + stable_adj_sum
    candidates: list[tuple[tuple[int, ...], float]] = []
    best_signs: tuple[int, ...] = ()
    best_signed_residual = 0.0
    best_abs_residual = float("inf")

    for signs in itertools.product([1, -1], repeat=len(Q_present)):
        adj_from_q = sum(sign * get_income_value(row, f) for sign, f in zip(signs, Q_present))
        residual = operate_profit - (base + adj_from_q)
        abs_residual = abs(residual)
        candidates.append((signs, residual))
        if abs_residual < best_abs_residual:
            best_abs_residual = abs_residual
            best_signed_residual = residual
            best_signs = signs

    # Regime detection: which questionable fields sit inside total_cogs (旧口径,
    # 损失记正号)? raw_total_cogs must be the pre-adaptation official value
    # (caller threads it via wide.attrs["raw_total_cogs_by_period"]); fall back
    # to row["total_cogs"] when not supplied (direct tests, quarterly mode
    # where total_cogs is never adapted).
    cogs_for_regime = (
        raw_total_cogs if raw_total_cogs is not None
        else get_income_value(row, "total_cogs")
    )
    cogs_residual = cogs_for_regime - stable_cost_sum
    semantic_signs = tuple(
        -1 if abs(cogs_residual - get_income_value(row, f)) <= tolerance else 1
        for f in Q_present
    )
    semantic_residual = next(residual for signs, residual in candidates if signs == semantic_signs)
    semantic_abs_residual = abs(semantic_residual)
    values_str = ", ".join(f"{f}={get_income_value(row, f):.4f}" for f in Q_present)

    def make_map(signs: tuple[int, ...]) -> dict[str, int]:
        return dict(zip(Q_present, signs))

    def format_pairs(signs: tuple[int, ...]) -> str:
        return ", ".join(f"{f}={s:+d}" for f, s in zip(Q_present, signs))

    if semantic_abs_residual < tolerance:
        sign_map = make_map(semantic_signs)
        return sign_map, [
            f"IS sign {year} resolved by semantic reported signs: {format_pairs(semantic_signs)}, "
            f"residual={semantic_residual:.4f}"
        ]

    improvement = semantic_abs_residual - best_abs_residual
    smallest_disputed = min(abs(get_income_value(row, f)) for f in Q_present)
    noise_band = 2.0 * smallest_disputed + tolerance

    if best_signs != semantic_signs and best_abs_residual < semantic_abs_residual:
        if improvement <= noise_band:
            sign_map = make_map(semantic_signs)
            return sign_map, [
                f"IS sign {year} retained semantic reported signs within noise band: "
                f"fields={Q_present}, values=[{values_str}], semantic=({format_pairs(semantic_signs)}, "
                f"residual={semantic_residual:.4f}), best=({format_pairs(best_signs)}, "
                f"residual={best_signed_residual:.4f}), improvement={improvement:.4f}, "
                f"noise_band={noise_band:.4f}"
            ]
        if best_abs_residual < tolerance:
            sign_map = make_map(best_signs)
            return sign_map, [
                f"IS sign {year} overrode semantic signs because residual improvement is material: "
                f"fields={Q_present}, values=[{values_str}], semantic=({format_pairs(semantic_signs)}, "
                f"residual={semantic_residual:.4f}), best=({format_pairs(best_signs)}, "
                f"residual={best_signed_residual:.4f}), improvement={improvement:.4f}, "
                f"noise_band={noise_band:.4f}"
            ]

    sign_map = make_map(semantic_signs)
    return sign_map, [
        f"IS sign {year} retained semantic reported signs with unresolved optional-adjustment residual: fields={Q_present}, "
        f"values=[{values_str}], semantic=({format_pairs(semantic_signs)}, "
        f"residual={semantic_residual:.4f}), best=({format_pairs(best_signs)}, "
        f"residual={best_signed_residual:.4f}), tolerance={tolerance:.4f}"
    ]


def check_is(row: dict[str, float], present: set[str], year: str, sign_map: dict[str, int] | None = None, null_fields: set[str] | None = None) -> list[str]:
    """Income statement hard checks using exhaustive field categorisation."""
    errors: list[str] = []

    # Determine the correct revenue base for IS checks.
    # Some companies (e.g. 伊利 600887) have int_income/comm_income that flows
    # into total_revenue but not revenue. When the gap is explained by these
    # items, use total_revenue as the income base so that operate_profit and
    # total_cogs consistency checks hold.
    revenue = get_income_value(row, "revenue")
    total_revenue = get_income_value(row, "total_revenue")
    other_revenue = get_income_value(row, "int_income") + get_income_value(row, "comm_income") + get_income_value(row, "n_oth_b_income")
    revenue_base = revenue
    if abs(total_revenue - revenue) >= TOLERANCE and abs(total_revenue - revenue - other_revenue) < TOLERANCE:
        revenue_base = total_revenue

    # 1.1 营业总成本 = sum(cost_item)
    total_cogs = get_income_value(row, "total_cogs")
    if sign_map:
        cogs_calc = signed_is_cost_sum(row, sign_map)
        residual = abs(total_cogs - cogs_calc)
        if residual >= TOLERANCE:
            # With modern sign-resolved cost fields, the residual represents
            # unattributed costs (e.g. 合同履约成本) not itemised in TuShare.
            # This is informational only; the hard identity check is IS 1.2.
            LOGGER.info(
                "IS 1.1 %s total_cogs includes %.4f unattributed other costs "
                "(not in standard line items, likely 合同履约成本 etc.)",
                year, total_cogs - cogs_calc,
            )
    else:
        cogs_calc = is_bucket_sum("cost_item", row, present)
        residual = abs(total_cogs - cogs_calc)

        if residual >= TOLERANCE:
            # Step A: total_cogs = total_opcost + fin_exp
            total_opcost = get_income_value(row, "total_opcost")
            fin_exp = get_income_value(row, "fin_exp")
            cogs_via_opcost = total_opcost + fin_exp
            residual2 = abs(total_cogs - cogs_via_opcost)
            if residual2 < TOLERANCE:
                opcost_items = cogs_calc - fin_exp
                other_costs = total_opcost - opcost_items
                if abs(other_costs) >= TOLERANCE:
                    LOGGER.info(
                        "IS 1.1 %s total_opcost includes %.4f unattributed other costs "
                        "(not in standard line items, likely 合同履约成本 etc.)",
                        year, other_costs,
                    )
            else:
                # Step B: verify total_cogs via operate_profit consistency
                operate_profit_prelim = get_income_value(row, "operate_profit")
                other_gains = is_bucket_sum("operating_adjustment", row, present)
                cogs_via_profit = revenue_base + other_gains - operate_profit_prelim
                if abs(total_cogs - cogs_via_profit) < TOLERANCE:
                    LOGGER.info(
                        "IS 1.1 %s total_cogs verified via operate_profit; "
                        "%.4f unattributed costs (likely 合同履约成本 etc.)",
                        year, total_cogs - cogs_calc,
                    )
                else:
                    errors.append(
                        f"IS 1.1 {year} 营业总成本: total_cogs={total_cogs:.4f} "
                        f"cost_items={cogs_calc:.4f} opcost+fe={cogs_via_opcost:.4f} "
                        f"profit-route={cogs_via_profit:.4f} residual={residual:.4f}"
                    )

    # 1.2 营业利润
    operate_profit = get_income_value(row, "operate_profit")
    if sign_map:
        oper_profit_calc = revenue_base - cogs_calc + signed_is_adjustment_sum(row, sign_map)
    else:
        oper_profit_calc = revenue_base - total_cogs + is_bucket_sum("operating_adjustment", row, present)
    residual = abs(operate_profit - oper_profit_calc)
    if residual >= TOLERANCE:
        missing_optional = missing_optional_is_adjustments(row, present, null_fields)
        null_optional = OPTIONAL_IS_ADJUSTMENT_FIELDS & (null_fields or set())
        if null_optional:
            # A TuShare-NULL optional adjustment is contributing to the residual —
            # a data-source gap, not a company-not-disclosed situation. Hard-fail so
            # the reconciler fires and backfills from the annual report. A reported-0
            # optional alone must not smuggle a coexisting NULL gap through the放行
            # gate (e.g. forex_gain reported 0 + oth_income NULL in the same period).
            errors.append(
                f"IS 1.2 {year} 营业利润: operate_profit={operate_profit:.4f} "
                f"calc={oper_profit_calc:.4f} residual={residual:.4f} "
                f"(TuShare-NULL optional: {sorted(null_optional)})"
            )
        elif missing_optional:
            LOGGER.warning(
                "IS 1.2 %s uses official operate_profit because optional operating adjustments are empty: "
                "missing=%s operate_profit=%.4f calc=%.4f residual=%.4f",
                year, missing_optional, operate_profit, oper_profit_calc, residual,
            )
        else:
            errors.append(
                f"IS 1.2 {year} 营业利润: operate_profit={operate_profit:.4f} "
                f"calc={oper_profit_calc:.4f} residual={residual:.4f}"
            )

    # 1.3 利润总额
    total_profit = get_income_value(row, "total_profit")
    total_profit_calc = operate_profit + get_income_value(row, "non_oper_income") - get_income_value(row, "non_oper_exp")
    residual = abs(total_profit - total_profit_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.3 {year} 利润总额: total_profit={total_profit:.4f} "
            f"calc={total_profit_calc:.4f} residual={residual:.4f}"
        )

    # 1.4 净利润
    n_income = get_income_value(row, "n_income")
    n_income_calc = total_profit - get_income_value(row, "income_tax")
    residual = abs(n_income - n_income_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.4 {year} 净利润: n_income={n_income:.4f} "
            f"calc={n_income_calc:.4f} residual={residual:.4f}"
        )

    # 1.5 净利润归属
    n_income_attr_p = get_income_value(row, "n_income_attr_p")
    minority_gain = get_income_value(row, "minority_gain")
    residual = abs(n_income - (n_income_attr_p + minority_gain))
    if residual >= TOLERANCE:
        errors.append(
            f"IS 1.5 {year} 净利润归属: n_income={n_income:.4f} "
            f"attr_p={n_income_attr_p:.4f} minority={minority_gain:.4f} residual={residual:.4f}"
        )

    # 1.6 营业总收入 = sum(revenue_item)
    revenue_calc = is_bucket_sum("revenue_item", row, present)
    if abs(total_revenue - revenue_calc) >= TOLERANCE and abs(total_revenue - revenue - other_revenue) >= TOLERANCE:
        errors.append(
            f"IS 1.6 {year} 营业总收入≠收入项之和: total_revenue={total_revenue:.4f} "
            f"revenue_items={revenue_calc:.4f} residual={abs(total_revenue - revenue_calc):.4f} "
            f"(疑似金融企业数据混入)"
        )

    return errors


def check_bs(
    row: dict[str, float],
    present: set[str],
    year: str,
    reclass: dict[str, str] | None = None,
    par: float = 1.0,
) -> tuple[list[str], list[str]]:
    """Balance sheet hard checks using exhaustive field categorisation.

    Returns (errors, warnings).  ``reclass`` 是本期 override 重分类映射
    （field -> bucket），用于把如 estimated_liab 这类 TuShare 默认非流动、
    但本公司本年列报为流动的科目，在 bucket 加总时移到正确的 bucket。

    ``par`` 是股票面值（默认 1.0）。TuShare balancesheet 的 ``total_share`` 是
    股数（百万股），不是股本(元)；权益 bucket 求和需用股本(元)=par×total_share。
    面值 1 元的公司 par=1.0 不受影响；面值≠1（如紫金 0.1）按 par 折算后 BS 4.1
    才配平。仅校验折算，不改 total_share 存储值（下游每股计算仍用股数）。
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 2.1 流动资产合计
    total_cur_assets = get_value(row, "total_cur_assets")
    cur_assets_calc = bs_bucket_sum("current_asset", row, present, reclass)
    residual = abs(total_cur_assets - cur_assets_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 2.1 {year} 流动资产: total_cur_assets={total_cur_assets:.4f} "
            f"calc={cur_assets_calc:.4f} residual={residual:.4f}"
        )

    # 2.2 非流动资产合计
    total_nca = get_value(row, "total_nca")
    nca_calc = bs_bucket_sum("noncurrent_asset", row, present, reclass)
    residual = abs(total_nca - nca_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 2.2 {year} 非流动资产: total_nca={total_nca:.4f} "
            f"calc={nca_calc:.4f} residual={residual:.4f}"
        )

    # 2.3 总资产 = 流动 + 非流动
    total_assets = get_value(row, "total_assets")
    residual = abs(total_assets - (total_cur_assets + total_nca))
    if residual >= TOLERANCE:
        errors.append(
            f"BS 2.3 {year} 总资产: total_assets={total_assets:.4f} "
            f"cur+nca={total_cur_assets + total_nca:.4f} residual={residual:.4f}"
        )

    # 3.1 流动负债合计
    total_cur_liab = get_value(row, "total_cur_liab")
    cur_liab_calc = bs_bucket_sum("current_liab", row, present, reclass)
    residual = abs(total_cur_liab - cur_liab_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 3.1 {year} 流动负债: total_cur_liab={total_cur_liab:.4f} "
            f"calc={cur_liab_calc:.4f} residual={residual:.4f}"
        )

    # 3.2 非流动负债合计
    total_ncl = get_value(row, "total_ncl")
    ncl_calc = bs_bucket_sum("noncurrent_liab", row, present, reclass)
    residual = abs(total_ncl - ncl_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"BS 3.2 {year} 非流动负债: total_ncl={total_ncl:.4f} "
            f"calc={ncl_calc:.4f} residual={residual:.4f}"
        )

    # 3.3 总负债 = 流动 + 非流动
    total_liab = get_value(row, "total_liab")
    residual = abs(total_liab - (total_cur_liab + total_ncl))
    if residual >= TOLERANCE:
        errors.append(
            f"BS 3.3 {year} 总负债: total_liab={total_liab:.4f} "
            f"cur+ncl={total_cur_liab + total_ncl:.4f} residual={residual:.4f}"
        )

    # 4.1 权益明细加总
    equity_calc = bs_bucket_sum("equity", row, present, reclass)
    # total_share 在 TuShare 是股数（百万股），权益 bucket 需要股本(元)。
    # 按 par 折算：股本(元) = par × total_share。par=1 时无影响。
    total_share_val = get_value(row, "total_share")
    if total_share_val:
        equity_calc += (par - 1.0) * total_share_val
    total_hldr_eqy_inc_min_int = get_value(row, "total_hldr_eqy_inc_min_int")
    residual = abs(total_hldr_eqy_inc_min_int - equity_calc)

    treasury_share = get_value(row, "treasury_share")
    treasury_share_anomaly = (
        treasury_share != 0
        and abs(residual - 2 * treasury_share) < TOLERANCE
    )
    if treasury_share_anomaly:
        warnings.append(
            f"BS 4.1 {year} treasury_share 符号异常（经验规则），"
            f"residual={residual:.4f} ≈ 2*treasury_share={2*treasury_share:.4f}；"
            f"请核对年报中库藏股列报口径。"
        )

    if residual >= TOLERANCE and not treasury_share_anomaly:
        errors.append(
            f"BS 4.1 {year} 权益合计: total_hldr_eqy_inc_min_int={total_hldr_eqy_inc_min_int:.4f} "
            f"calc={equity_calc:.4f} residual={residual:.4f}"
        )

    # 4.2 归母 + 少数 = 合计
    total_hldr_eqy_exc_min_int = get_value(row, "total_hldr_eqy_exc_min_int")
    residual = abs(total_hldr_eqy_inc_min_int - (total_hldr_eqy_exc_min_int + get_value(row, "minority_int")))
    if residual >= TOLERANCE:
        errors.append(
            f"BS 4.2 {year} 归母+少数: total_inc={total_hldr_eqy_inc_min_int:.4f} "
            f"exc+min={total_hldr_eqy_exc_min_int + get_value(row, 'minority_int'):.4f} residual={residual:.4f}"
        )

    # 4.3 终极配平
    residual1 = abs(total_assets - total_liab - total_hldr_eqy_inc_min_int)
    if residual1 >= TOLERANCE:
        errors.append(
            f"BS 4.3a {year} 资产=负债+权益: assets={total_assets:.4f} "
            f"liab+eqy={total_liab + total_hldr_eqy_inc_min_int:.4f} residual={residual1:.4f}"
        )

    total_liab_hldr_eqy = get_value(row, "total_liab_hldr_eqy")
    residual2 = abs(total_assets - total_liab_hldr_eqy)
    if total_liab_hldr_eqy != 0 and residual2 >= TOLERANCE:
        errors.append(
            f"BS 4.3b {year} 资产=负债+权益(合并项): assets={total_assets:.4f} "
            f"total_liab_hldr_eqy={total_liab_hldr_eqy:.4f} residual={residual2:.4f}"
        )

    return errors, warnings


def apply_quarterly_bs_plugs(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
    ticker: str,
) -> list[dict[str, object]]:
    """Apply transparent BS plug fields for incomplete quarterly disclosures.

    Quarterly reports often disclose subtotals without all line-item details.
    For bucket subtotal checks only, absorb the residual into explicit QA plug
    fields.  Parent equations remain hard-checked afterwards.
    """
    records: list[dict[str, object]] = []
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    specs = [
        ("BS 2.1", "current_asset", "total_cur_assets", "流动资产"),
        ("BS 2.2", "noncurrent_asset", "total_nca", "非流动资产"),
        ("BS 3.1", "current_liab", "total_cur_liab", "流动负债"),
        ("BS 3.2", "noncurrent_liab", "total_ncl", "非流动负债"),
        ("BS 4.1", "equity", "total_hldr_eqy_inc_min_int", "权益合计"),
    ]

    for period in sorted(str(period) for period in wide.index.tolist()):
        present = present_by_period.get(period, set())
        for code, bucket, target_field, label in specs:
            row_before = wide.loc[period].to_dict()
            target = get_value(row_before, target_field)
            calc = bs_bucket_sum(bucket, row_before, present)
            residual = target - calc
            if abs(residual) < TOLERANCE:
                continue

            plug_field = QA_BS_PLUG_FIELDS[bucket]
            raw_plug = wide.loc[period, plug_field]
            old_plug = 0.0 if pd.isna(raw_plug) else float(raw_plug)
            new_plug = old_plug + residual
            wide.loc[period, plug_field] = new_plug

            message = (
                f"{period} {code} {label}季度明细披露不完整，使用 {plug_field}={residual:.4f} "
                f"吸收差额；公式: {target_field}({target:.4f}) - 明细和({calc:.4f}) = {residual:.4f}。"
                f"建议检查对应季报/半年报/三季报资产负债表明细，若可定位具体科目，应改用 LLM evidence override。"
            )
            records.append(
                {
                    "created_at": created_at,
                    "ticker": ticker,
                    "period": period,
                    "severity": "warning",
                    "code": "quarterly_bs_plug",
                    "message": message,
                    "source": "clean.py:quarterly_bs_plug",
                    "evidence": (
                        f"check={code}; target_field={target_field}; bucket={bucket}; "
                        f"target={target:.4f}; detail_sum_before_plug={calc:.4f}; "
                        f"plug_field={plug_field}; plug_delta={residual:.4f}; plug_total={new_plug:.4f}"
                    ),
                }
            )
            LOGGER.warning("⚠️  %s", message)

    return records


# 年度 QA plug 的 bucket 规格：code → (bucket, target_field, label)。
# 年度 plug 与季度 plug 共用 qa_bs_*_plug 字段（bs_bucket_sum 已把它们计入
# bucket 求和），但年度 plug 不是披露不完整的兜底，而是"两轮 reconciler 都
# 无法用年报证据解释的硬残差"的逃生通道，只在用户明确同意时对指定 (period,
# code) 生效，带 warning + 审计，透明可追溯。
ANNUAL_PLUG_SPECS: dict[str, tuple[str, str, str]] = {
    "BS 2.1": ("current_asset", "total_cur_assets", "流动资产"),
    "BS 2.2": ("noncurrent_asset", "total_nca", "非流动资产"),
    "BS 3.1": ("current_liab", "total_cur_liab", "流动负债"),
    "BS 3.2": ("noncurrent_liab", "total_ncl", "非流动负债"),
    "BS 4.1": ("equity", "total_hldr_eqy_inc_min_int", "权益合计"),
}


def apply_annual_bs_plugs(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
    ticker: str,
    plug_directives: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Apply user-approved annual QA plugs for hard residuals two reconciler
    rounds could not close.

    Unlike ``apply_quarterly_bs_plugs`` (automatic for every period — quarterly
    disclosure is routinely incomplete), annual plugs fire ONLY for the
    (period, code) pairs the user explicitly approved in ``annual_plugs.json``
    via init.py's plug prompt. The plug absorbs the post-override residual into
    the bucket's qa_bs_*_plug field so check_bs passes; a warning records the
    unexplained residual so it stays auditable, not silently swallowed.
    """
    records: list[dict[str, object]] = []
    if not plug_directives:
        return records
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    directive_keys = {
        (str(d.get("period")), str(d.get("code")))
        for d in plug_directives
        if isinstance(d, dict)
    }
    bs_reclass_by_period = wide.attrs.get("bs_reclass", {})

    for period in sorted(str(period) for period in wide.index.tolist()):
        present = present_by_period.get(period, set())
        row = wide.loc[period].to_dict()
        reclass = bs_reclass_by_period.get(period, {})
        for code, (bucket, target_field, label) in ANNUAL_PLUG_SPECS.items():
            if (period, code) not in directive_keys:
                continue
            target = get_value(row, target_field)
            calc = bs_bucket_sum(bucket, row, present, reclass=reclass)
            residual = target - calc
            if abs(residual) < TOLERANCE:
                continue
            plug_field = QA_BS_PLUG_FIELDS[bucket]
            raw_plug = wide.loc[period, plug_field]
            old_plug = 0.0 if pd.isna(raw_plug) else float(raw_plug)
            new_plug = old_plug + residual
            wide.loc[period, plug_field] = new_plug
            message = (
                f"{period} {code} {label}两轮年报核对（rule + LLM fallback）均无法用"
                f"年报证据解释残差，按用户指令用 {plug_field}={residual:.4f} 吸收差额"
                f"（硬问题 plug，非披露不完整）；公式: {target_field}({target:.4f}) - "
                f"明细和({calc:.4f}) = {residual:.4f}。建议人工核对年报/口径，定位具体"
                f"科目后改用 LLM evidence override 并删除本 plug。"
            )
            records.append(
                {
                    "created_at": created_at,
                    "ticker": ticker,
                    "period": period,
                    "severity": "warning",
                    "code": "annual_bs_plug",
                    "message": message,
                    "source": "clean.py:annual_bs_plug",
                    "evidence": (
                        f"check={code}; target_field={target_field}; bucket={bucket}; "
                        f"target={target:.4f}; detail_sum_before_plug={calc:.4f}; "
                        f"plug_field={plug_field}; plug_delta={residual:.4f}; plug_total={new_plug:.4f}; "
                        f"approved_via=annual_plugs.json"
                    ),
                }
            )
            LOGGER.warning("⚠️  %s", message)

    return records


def default_plugs_path(db_path: Path) -> Path:
    return recon_dir(company_dir_from_db_path(db_path)) / "annual_plugs.json"


def load_annual_plugs(path: Path | None, ticker: str) -> list[dict[str, object]]:
    """Load user-approved annual plug directives (written by init.py's plug prompt)."""
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("ticker") not in {ticker, None}:
        raise ValueError(f"Annual plug ticker mismatch: {data.get('ticker')} != {ticker}")
    plugs = [p for p in data.get("plugs", []) if isinstance(p, dict)]
    LOGGER.info("Loaded %d annual plug directive(s) from %s", len(plugs), path)
    return plugs


def apply_annual_income_subtotal_adaptations(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
    ticker: str,
) -> list[dict[str, object]]:
    """Prefer stable cost detail when official annual total_cogs conflicts."""
    records: list[dict[str, object]] = []
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    for period in sorted(str(period) for period in wide.index.tolist()):
        row = wide.loc[period].to_dict()
        present = present_by_period.get(period, set())
        if "total_cogs" not in present:
            continue
        official_total = get_income_value(row, "total_cogs")
        detail_total = signed_is_cost_sum(row, None)
        residual = official_total - detail_total
        if abs(residual) < TOLERANCE or abs(detail_total) < 1e-9:
            continue

        wide.loc[period, "total_cogs"] = detail_total
        message = (
            f"{period} IS 1.1 官方 total_cogs 与稳定成本明细不一致，clean 使用明细重算值："
            f"official={official_total:.4f}, detail={detail_total:.4f}, residual={residual:.4f}。"
        )
        records.append(
            {
                "created_at": created_at,
                "ticker": ticker,
                "period": period,
                "severity": "warning",
                "code": "annual_income_subtotal_adaptation",
                "message": message,
                "source": "clean.py:annual_income_subtotal_adaptation",
                "evidence": (
                    f"field=total_cogs; official={official_total:.4f}; "
                    f"stable_cost_detail={detail_total:.4f}; residual={residual:.4f}"
                ),
            }
        )
        LOGGER.warning("⚠️  %s", message)

    return records


def apply_quarterly_cf_cash_plugs(
    wide: pd.DataFrame,
    ticker: str,
    *,
    tolerance: float,
) -> list[dict[str, object]]:
    """Apply an explicit QA plug for quarterly CF cash-balance residuals."""
    records: list[dict[str, object]] = []
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    for period in sorted(str(period) for period in wide.index.tolist()):
        row = wide.loc[period].to_dict()
        end_cash = get_cashflow_value(row, "c_cash_equ_end_period")
        beg_cash = get_cashflow_value(row, "c_cash_equ_beg_period")
        net_increase = get_cashflow_value(row, "n_incr_cash_cash_equ")
        residual = end_cash - (beg_cash + net_increase)
        if abs(residual) < tolerance:
            continue

        old_plug = 0.0 if pd.isna(wide.loc[period, QA_CF_CASH_PLUG_FIELD]) else float(wide.loc[period, QA_CF_CASH_PLUG_FIELD])
        new_plug = old_plug + residual
        wide.loc[period, QA_CF_CASH_PLUG_FIELD] = new_plug

        message = (
            f"{period} CF 5.5 季度现金期初期末桥接存在原始残差，使用 "
            f"{QA_CF_CASH_PLUG_FIELD}={residual:.4f} 吸收差额；公式: "
            f"c_cash_equ_end_period({end_cash:.4f}) - "
            f"[c_cash_equ_beg_period({beg_cash:.4f}) + "
            f"n_incr_cash_cash_equ({net_increase:.4f})] = {residual:.4f}。"
            f"建议核对现金流量表期初现金、期末现金和现金净增加额；"
            f"该 plug 不参与 CF 5.1-5.4 的流量明细加总。"
        )
        records.append(
            {
                "created_at": created_at,
                "ticker": ticker,
                "period": period,
                "severity": "warning",
                "code": "quarterly_cf_cash_plug",
                "message": message,
                "source": "clean.py:quarterly_cf_cash_plug",
                "evidence": (
                    f"check=CF 5.5; end={end_cash:.4f}; beg={beg_cash:.4f}; "
                    f"net_increase={net_increase:.4f}; plug_field={QA_CF_CASH_PLUG_FIELD}; "
                    f"plug_delta={residual:.4f}; plug_total={new_plug:.4f}"
                ),
            }
        )
        LOGGER.warning("⚠️  %s", message)

    return records


def check_cf(row: dict[str, float], present: set[str], year: str) -> list[str]:
    """Cash flow statement hard checks."""
    errors: list[str] = []

    # 5.1 经营活动
    n_cashflow_act = get_cashflow_value(row, "n_cashflow_act")
    c_inf_fr_operate_a = get_cashflow_value(row, "c_inf_fr_operate_a")
    st_cash_out_act = get_cashflow_value(row, "st_cash_out_act")
    residual = abs(n_cashflow_act - (c_inf_fr_operate_a - st_cash_out_act))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.1 {year} 经营: n_cashflow_act={n_cashflow_act:.4f} "
            f"inf-out={c_inf_fr_operate_a - st_cash_out_act:.4f} residual={residual:.4f}"
        )

    # 5.2 投资活动
    n_cashflow_inv_act = get_cashflow_value(row, "n_cashflow_inv_act")
    stot_inflows_inv_act = get_cashflow_value(row, "stot_inflows_inv_act")
    stot_out_inv_act = get_cashflow_value(row, "stot_out_inv_act")
    residual = abs(n_cashflow_inv_act - (stot_inflows_inv_act - stot_out_inv_act))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.2 {year} 投资: n_cashflow_inv_act={n_cashflow_inv_act:.4f} "
            f"inf-out={stot_inflows_inv_act - stot_out_inv_act:.4f} residual={residual:.4f}"
        )

    # 5.3 筹资活动
    n_cash_flows_fnc_act = get_cashflow_value(row, "n_cash_flows_fnc_act")
    stot_cash_in_fnc_act = get_cashflow_value(row, "stot_cash_in_fnc_act")
    stot_cashout_fnc_act = get_cashflow_value(row, "stot_cashout_fnc_act")
    residual = abs(n_cash_flows_fnc_act - (stot_cash_in_fnc_act - stot_cashout_fnc_act))
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.3 {year} 筹资: n_cash_flows_fnc_act={n_cash_flows_fnc_act:.4f} "
            f"inf-out={stot_cash_in_fnc_act - stot_cashout_fnc_act:.4f} residual={residual:.4f}"
        )

    # 5.4 三大活动汇总
    n_incr_cash_cash_equ = get_cashflow_value(row, "n_incr_cash_cash_equ")
    eff_fx_flu_cash = get_cashflow_value(row, "eff_fx_flu_cash")
    total_calc = n_cashflow_act + n_cashflow_inv_act + n_cash_flows_fnc_act + eff_fx_flu_cash
    residual = abs(n_incr_cash_cash_equ - total_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.4 {year} 汇总: n_incr_cash={n_incr_cash_cash_equ:.4f} "
            f"act+inv+fnc+fx={total_calc:.4f} residual={residual:.4f}"
        )

    # 5.5 期初期末
    c_cash_equ_end_period = get_cashflow_value(row, "c_cash_equ_end_period")
    c_cash_equ_beg_period = get_cashflow_value(row, "c_cash_equ_beg_period")
    qa_cf_cash_reconcile_plug = get_value(row, QA_CF_CASH_PLUG_FIELD)
    cash_bridge_calc = c_cash_equ_beg_period + n_incr_cash_cash_equ + qa_cf_cash_reconcile_plug
    residual = abs(c_cash_equ_end_period - cash_bridge_calc)
    if residual >= TOLERANCE:
        errors.append(
            f"CF 5.5 {year} 期初期末: end={c_cash_equ_end_period:.4f} "
            f"beg+incr+qa_plug={cash_bridge_calc:.4f} residual={residual:.4f}"
        )

    return errors


def check_is_supplement(row: dict[str, float], present: set[str], year: str) -> list[str]:
    """IS supplement hard checks (6.1, 6.2, 6.3)."""
    errors: list[str] = []

    t_compr_income = get_income_value(row, "t_compr_income")
    n_income = get_income_value(row, "n_income")
    oth_compr_income = get_income_value(row, "oth_compr_income")

    # 6.1 综合收益 = 净利润 + 其他综合收益
    residual = abs(t_compr_income - (n_income + oth_compr_income))
    if residual >= TOLERANCE:
        errors.append(
            f"IS 6.1 {year} 综合收益: t_compr_income={t_compr_income:.4f} "
            f"n_income+oci={n_income + oth_compr_income:.4f} residual={residual:.4f}"
        )

    # 6.2 综合收益归属
    compr_inc_attr_p = get_income_value(row, "compr_inc_attr_p")
    compr_inc_attr_m_s = get_income_value(row, "compr_inc_attr_m_s")
    residual = abs(t_compr_income - (compr_inc_attr_p + compr_inc_attr_m_s))
    if residual >= TOLERANCE:
        errors.append(
            f"IS 6.2 {year} 综合收益归属: t_compr_income={t_compr_income:.4f} "
            f"attr_p+m_s={compr_inc_attr_p + compr_inc_attr_m_s:.4f} residual={residual:.4f}"
        )

    # 6.3 持续/终止经营
    # 仅当公司有实质披露（至少一个非零）时校验；
    # 2020年前旧准则不强制拆分，字段存在但为0属正常。
    if "continued_net_profit" in present:
        continued_net_profit = get_income_value(row, "continued_net_profit")
        end_net_profit = get_income_value(row, "end_net_profit")
        if continued_net_profit != 0.0 or end_net_profit != 0.0:
            residual = abs(n_income - (continued_net_profit + end_net_profit))
            if residual >= TOLERANCE:
                errors.append(
                    f"IS 6.3 {year} 持续+终止: n_income={n_income:.4f} "
                    f"continued+end={continued_net_profit + end_net_profit:.4f} residual={residual:.4f}"
                )

    return errors


def check_cross_table(row: dict[str, float], present: set[str], year: str) -> list[str]:
    """Cross-table hard checks (7.1). 7.2 moved to soft checks."""
    errors: list[str] = []

    # 7.1 IS 净利润 = CF 附注净利润
    # Only check when CF net_profit is non-zero (some years lack indirect method data)
    is_n_income = get_income_value(row, "n_income")
    cf_net_profit = get_cashflow_value(row, "net_profit")
    if "net_profit" in present and cf_net_profit != 0.0:
        residual = abs(cf_net_profit - is_n_income)
        if residual >= TOLERANCE:
            errors.append(
                f"跨表 7.1 {year} 净利润: IS n_income={is_n_income:.4f} "
                f"CF net_profit={cf_net_profit:.4f} residual={residual:.4f}"
            )

    # 7.2 moved to soft checks — CF finan_exp is the interest expense component
    # only, not the net fin_exp (which nets interest income). They rarely match
    # for companies with significant interest income.

    return errors


def check_soft(row: dict[str, float], present: set[str], year: str, null_fields: set[str] | None = None) -> list[str]:
    """Soft checks — warnings only."""
    warnings: list[str] = []

    revenue = get_income_value(row, "revenue")
    total_revenue = get_income_value(row, "total_revenue")
    other_revenue = (
        get_income_value(row, "int_income")
        + get_income_value(row, "comm_income")
        + get_income_value(row, "n_oth_b_income")
    )
    revenue_base = revenue
    if abs(total_revenue - revenue) >= TOLERANCE and abs(total_revenue - revenue - other_revenue) < TOLERANCE:
        revenue_base = total_revenue

    semantic_sign_map = {field: 1 for field in SIGN_QUESTIONABLE_IS_FIELDS}
    oper_profit_calc = (
        revenue_base
        - signed_is_cost_sum(row, None)
        + signed_is_adjustment_sum(row, semantic_sign_map)
    )
    operate_profit = get_income_value(row, "operate_profit")
    optional_gap = operate_profit - oper_profit_calc
    missing_optional = missing_optional_is_adjustments(row, present, null_fields)
    null_optional = OPTIONAL_IS_ADJUSTMENT_FIELDS & (null_fields or set())
    if abs(optional_gap) >= TOLERANCE and missing_optional and not null_optional:
        warnings.append(
            f"IS 1.2 {year} 官方源缺少可选营业调整项，营业利润按官方 subtotal 保留: "
            f"missing={missing_optional} operate_profit={operate_profit:.4f} "
            f"calc={oper_profit_calc:.4f} residual={optional_gap:.4f}"
        )

    # 7.2 IS 财务费用 vs CF 附注财务费用 (soft — CF finan_exp is often
    # the interest expense component only, not the net fin_exp)
    is_fin_exp = get_income_value(row, "fin_exp")
    cf_finan_exp = get_cashflow_value(row, "finan_exp")
    if cf_finan_exp != 0.0 or is_fin_exp != 0.0:
        diff = abs(cf_finan_exp - is_fin_exp)
        if diff > TOLERANCE:
            warnings.append(
                f"跨表 7.2 {year} IS fin_exp({is_fin_exp:.4f}) ≠ CF finan_exp({cf_finan_exp:.4f}), 差{diff:.4f}"
            )

    # 7.3 CF期末现金 vs BS货币资金
    c_cash_equ_end = get_cashflow_value(row, "c_cash_equ_end_period")
    money_cap = get_value(row, "money_cap")
    diff = abs(c_cash_equ_end - money_cap)
    if diff > TOLERANCE:
        warnings.append(
            f"跨表 7.3 {year} CF期末现金({c_cash_equ_end:.4f}) ≠ BS货币资金({money_cap:.4f}), 差{diff:.4f}"
        )

    # 10.1 方向合理性
    total_assets = get_value(row, "total_assets")
    n_income_attr_p = get_income_value(row, "n_income_attr_p")
    basic_eps = get_income_value(row, "basic_eps")

    if revenue < 0:
        warnings.append(f"10.1 {year} 营业收入为负: {revenue:.4f}")
    if total_assets < 0:
        warnings.append(f"10.1 {year} 总资产为负: {total_assets:.4f}")
    if n_income_attr_p != 0 and basic_eps != 0:
        if (n_income_attr_p > 0) != (basic_eps > 0):
            warnings.append(
                f"10.1 {year} EPS({basic_eps:.4f})与归母净利润({n_income_attr_p:.4f})方向不一致"
            )

    # 10.2 量级合理性
    if total_assets > 10_000_000:
        warnings.append(f"10.2 {year} 总资产 {total_assets:.0f}M > 10万亿，请确认")
    if total_revenue > 0 and abs(operate_profit) > total_revenue:
        warnings.append(f"10.2 {year} 营业利润绝对值({operate_profit:.4f})大于营业收入({total_revenue:.4f})")

    # 10.3 折旧 vs 固定资产
    depr_fa_coga_dpba = get_cashflow_value(row, "depr_fa_coga_dpba")
    fix_assets = get_value(row, "fix_assets")
    fix_assets_total = get_value(row, "fix_assets_total")
    fix_val = fix_assets_total if fix_assets_total != 0 else fix_assets
    if fix_val != 0 and depr_fa_coga_dpba > fix_val * 1.5:
        warnings.append(f"10.3 {year} 折旧({depr_fa_coga_dpba:.4f})超过固定资产({fix_val:.4f})的150%")

    # 10.4 毛利率范围
    oper_cost = get_income_value(row, "oper_cost")
    if revenue > 0:
        gpm = (revenue - oper_cost) / revenue
        if gpm < -0.5 or gpm > 1.0:
            warnings.append(f"10.4 {year} 毛利率 {gpm:.2%} 超出合理范围")

    return warnings


# ── 主入口 ─────────────────────────────────────────────────────

def validate_wide(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
    *,
    label: str,
    restatement_exemptions: list[dict[str, object]] | None = None,
    pre_ipo_year: int | None = None,
) -> list[str]:
    """Run hard and soft checks on a wide table."""
    all_errors: list[str] = []
    all_warnings: list[str] = []

    sorted_periods = sorted(str(period) for period in wide.index.tolist())
    prev_period_end_cash: float | None = None
    bs_reclass_by_period: dict[str, dict[str, str]] = wide.attrs.get("bs_reclass", {})

    # 跨表 7.4 重述豁免：经 subagent 读年报确认属披露重述的边界，降级为软 warning。
    # key 为本期 period（期初现金所在年），与 7.4 失败行的 period 一致。
    exempted_periods: dict[str, dict[str, object]] = {
        str(e.get("period")): e
        for e in (restatement_exemptions or [])
        if e.get("check_code") == "跨表 7.4"
    }

    # 推断股票面值：TuShare total_share 是股数，权益校验需股本(元)=par×total_share。
    par_value = infer_par_value(wide, present_by_period, bs_reclass_by_period)
    if label == "annual" and abs(par_value - 1.0) > 1e-9:
        msg = (
            f"BS 权益面值推断 par={par_value}（TuShare total_share 为股数百万股，"
            f"权益校验按 par×total_share 折算股本元；total_share 存储值不变）"
        )
        all_warnings.append(msg)
        LOGGER.warning("⚠️  %s", msg)

    for period in sorted_periods:
        row = wide.loc[period].to_dict()
        present = present_by_period.get(period, set())
        null_fields = wide.attrs.get("null_fields_by_period", {}).get(period, set())
        reclass = bs_reclass_by_period.get(period)

        # pre-IPO 闸门：年度早于最早可用年报 Markdown 的，TuShare 数据源自招股书、
        # 无 cninfo 年报 MD 可核对，硬校验失败降级为 warning 不阻塞（与 2010 闸门
        # 同性质：有据可审计，非静默改判）。季度不启用。
        pre_ipo = (
            label == "annual"
            and pre_ipo_year is not None
            and period_year(period) < pre_ipo_year
        )

        period_errors: list[str] = []
        period_warnings: list[str] = []

        # Dynamic sign resolution for impairment-like fields. Regime is detected
        # per-year from raw_total_cogs (pre-adaptation) vs stable cost detail;
        # annual mode threads it via attrs, quarterly/tests fall back to row.
        raw_tc = wide.attrs.get("raw_total_cogs_by_period", {}).get(period)
        sign_map, sign_warnings = resolve_is_signs(row, present, period, raw_total_cogs=raw_tc)
        period_warnings.extend(sign_warnings)

        if label == "quarterly":
            period_warnings.extend(check_is(row, present, period, sign_map=sign_map, null_fields=null_fields))
        else:
            period_errors.extend(check_is(row, present, period, sign_map=sign_map, null_fields=null_fields))
        bs_errors, bs_warnings = check_bs(row, present, period, reclass, par=par_value)
        period_errors.extend(bs_errors)
        period_warnings.extend(bs_warnings)
        period_errors.extend(check_cf(row, present, period))
        if label == "quarterly":
            period_warnings.extend(check_is_supplement(row, present, period))
        else:
            period_errors.extend(check_is_supplement(row, present, period))
        if label != "quarterly":
            period_errors.extend(check_cross_table(row, present, period))

        # 7.4 连续性：上一期 CF 期末 = 本期 CF 期初
        c_cash_equ_beg = get_cashflow_value(row, "c_cash_equ_beg_period")
        if label != "quarterly" and prev_period_end_cash is not None and c_cash_equ_beg != 0:
            residual = abs(prev_period_end_cash - c_cash_equ_beg)
            if residual >= TOLERANCE:
                # 残差需与豁免记录吻合（防脏豁免：TuShare 值变动后旧豁免不再适用）
                ex = exempted_periods.get(period)
                ex_matches = (
                    ex is not None
                    and abs(float(ex.get("prev_end_cash") or 0.0) - prev_period_end_cash) < TOLERANCE
                    and abs(float(ex.get("cur_beg_cash") or 0.0) - c_cash_equ_beg) < TOLERANCE
                )
                if ex_matches:
                    period_warnings.append(
                        f"跨表 7.4 {period} 重述豁免：上期CF期末({prev_period_end_cash:.4f}) "
                        f"≠ 本期CF期初({c_cash_equ_beg:.4f})，差额 {residual:.4f}，"
                        f"经年报确认属披露重述（exemption source={ex.get('source')}，"
                        f"prev_period={ex.get('prev_period')}）。重述非数据错误，降级为 warning。"
                    )
                else:
                    period_errors.append(
                        f"跨表 7.4 {period} 上期CF期末({prev_period_end_cash:.4f}) ≠ 本期CF期初({c_cash_equ_beg:.4f})"
                    )

        prev_period_end_cash = get_cashflow_value(row, "c_cash_equ_end_period")

        period_warnings.extend(check_soft(row, present, period, null_fields=null_fields))

        if period_errors:
            if pre_ipo:
                # pre-IPO 年度：无年报 MD 可核对，硬失败降级为 warning 直接入库，
                # 不阻塞 clean、不触发 reconciler。明确标注原因，下游可见可审计。
                for e in period_errors:
                    msg = (
                        f"pre-IPO年度 {period}（早于最早可用年报MD {pre_ipo_year}，"
                        f"TuShare源自招股书、无年报MD可核对，硬失败降级为warning不阻塞）: {e}"
                    )
                    all_warnings.append(msg)
                    LOGGER.warning("⚠️  %s", msg)
                LOGGER.info(
                    "⏭️  %s annual %s pre-IPO年度，%d 个硬失败降级为 warning",
                    label, period, len(period_errors),
                )
            elif label == "annual" and period_year(period) < RECONCILE_MIN_YEAR:
                # 2010 闸门(audit C5):A 股 2010 前披露稀疏、格式早期,年报核对得不偿失。
                # 年度早于 RECONCILE_MIN_YEAR 的硬失败降级为 warning 直接入库,不阻塞、
                # 不触发 reconciler(与 pre-IPO 闸门同性质:有据可审计,非静默改判;
                # reconciler.collect_failures 与年报下载也以同一常量跳过 2010 前)。季度不启用。
                for e in period_errors:
                    msg = (
                        f"2010前年度 {period}（早于 RECONCILE_MIN_YEAR={RECONCILE_MIN_YEAR}，"
                        f"A股早期披露稀疏、年报核对得不偿失，硬失败降级为warning不阻塞）: {e}"
                    )
                    all_warnings.append(msg)
                    LOGGER.warning("⚠️  %s", msg)
                LOGGER.info(
                    "⏭️  %s annual %s 2010前年度，%d 个硬失败降级为 warning",
                    label, period, len(period_errors),
                )
            else:
                all_errors.extend(period_errors)
                for e in period_errors:
                    LOGGER.error("❌ %s", e)
        else:
            LOGGER.info("✅ %s %s all hard checks passed", label, period)

        for w in period_warnings:
            LOGGER.warning("⚠️  %s", w)
            all_warnings.append(w)

    if all_errors:
        for e in all_errors[:20]:
            print(f"HARD CHECK FAIL: {e}", file=sys.stderr)
        if len(all_errors) > 20:
            print(f"... and {len(all_errors) - 20} more errors", file=sys.stderr)
        err = CheckError(f"{len(all_errors)} hard check(s) failed")
        # 附加结构化错误列表供同进程调用方（init.py）解析硬失败，免解析 stderr 文本。
        # stderr 流式打印已发生，CLI 行为不变。
        err.errors = [str(e) for e in all_errors]
        raise err

    return all_warnings


def write_clean_table(conn: sqlite3.Connection, table_name: str, wide: pd.DataFrame) -> None:
    """Write the full validated clean wide table consumed by downstream models.

    QA plug fields are part of the clean-data contract. They keep quarterly
    residual absorption explicit and make downstream reconciliation auditable.
    Annual plugs normally remain zero, but the schema stays identical.
    """
    out = ensure_qa_columns(wide.copy())
    out.index.name = "period"
    out.to_sql(table_name, conn, if_exists="replace", index=True, index_label="period")


ADJUSTMENT_COLUMNS = [
    "applied_at",
    "ticker",
    "period",
    "endpoint",
    "field",
    "old_value_million_cny",
    "new_value_million_cny",
    "delta_million_cny",
    "failure_code",
    "annual_report_item",
    "confidence",
    "source",
    "source_markdown_path",
    "source_reconciliation_path",
    "evidence_lines",
    "reason",
    "clean_category",
]

WARNING_COLUMNS = [
    "created_at",
    "ticker",
    "period",
    "severity",
    "code",
    "message",
    "source",
    "evidence",
]


def default_overrides_path(db_path: Path) -> Path:
    return recon_dir(company_dir_from_db_path(db_path)) / "annual_report_overrides.json"


def load_approved_overrides(path: Path | None, ticker: str) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("ticker") not in {ticker, None}:
        raise ValueError(f"Override ticker mismatch: {data.get('ticker')} != {ticker}")

    def _rank(src: object) -> int:
        s = str(src)
        return OVERRIDE_SOURCE_PRECEDENCE.index(s) if s in OVERRIDE_SOURCE_PRECEDENCE else len(OVERRIDE_SOURCE_PRECEDENCE)

    # audit H4:按 (period, 解析后列名) 去重,source 优先级裁决冲突(确定性,不靠列表序)。
    by_cell: dict[tuple[str, str], dict[str, object]] = {}
    for item in data.get("adjustments", []):
        if item.get("status") != "approved":
            continue
        if item.get("source") not in APPROVED_OVERRIDE_SOURCES:
            LOGGER.warning(
                "Override skipped: %s %s.%s source=%s is not approved LLM evidence",
                item.get("period"),
                item.get("endpoint"),
                item.get("field"),
                item.get("source"),
            )
            continue
        period = str(item.get("period") or "")
        column = override_column_name(str(item.get("endpoint") or ""), str(item.get("field") or ""))
        key = (period, column)
        prev = by_cell.get(key)
        if prev is None:
            by_cell[key] = item
            continue
        # 同 cell 冲突:按 source 优先级取胜者(rank 小者赢),记录可见、可审计。
        winner, loser = (item, prev) if _rank(item.get("source")) < _rank(prev.get("source")) else (prev, item)
        if prev.get("new_value_million_cny") != item.get("new_value_million_cny"):
            LOGGER.warning(
                "Override conflict at %s %s: source=%s val=%s vs source=%s val=%s -> 取 source=%s val=%s",
                period, column,
                prev.get("source"), prev.get("new_value_million_cny"),
                item.get("source"), item.get("new_value_million_cny"),
                winner.get("source"), winner.get("new_value_million_cny"),
            )
        by_cell[key] = winner
    adjustments = list(by_cell.values())
    LOGGER.info("Loaded %d approved annual-report override(s) from %s", len(adjustments), path)
    return adjustments


def override_column_name(endpoint: str, field: str) -> str:
    if field in CROSS_ENDPOINT_FIELDS and endpoint in {"income", "cashflow"}:
        return f"{endpoint}.{field}"
    return field


def default_restatement_exemptions_path(db_path: Path) -> Path:
    """跨表 7.4 重述豁免文件：由 subagent 升级通道确认后写入，clean 加载后把对应边界降级为软 warning。"""
    return recon_dir(company_dir_from_db_path(db_path)) / "restatement_exemptions.json"


def load_restatement_exemptions(path: Path | None, ticker: str) -> list[dict[str, object]]:
    """Load approved 跨表 7.4 restatement exemptions.

    与 override 不同：重述豁免不补数、不重分类，只是把『上期CF期末 ≠ 本期CF期初』这条
    经年报确认属披露重述的边界从硬校验降级为软 warning。多年连续重述无法用 override 干净
    闭合（会级联破坏 CF 5.5/5.4/5.1-5.3），重述是公司披露的会计事件、非数据错误，故走豁免。
    """
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("ticker") not in {ticker, None}:
        raise ValueError(f"Restatement exemption ticker mismatch: {data.get('ticker')} != {ticker}")
    exemptions = [
        item
        for item in data.get("exemptions", [])
        if isinstance(item, dict) and item.get("status") == "approved"
    ]
    if exemptions:
        LOGGER.info("Loaded %d approved restatement exemption(s) from %s", len(exemptions), path)
    return exemptions



def apply_annual_overrides(
    wide: pd.DataFrame,
    present_by_period: dict[str, set[str]],
    ticker: str,
    adjustments: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Apply approved annual-report overrides to the clean annual wide table.

    raw_tushare remains untouched.  Every applied adjustment is returned for
    SQLite audit tables and warning logs.
    """
    applied: list[dict[str, object]] = []
    applied_at = time.strftime("%Y-%m-%d %H:%M:%S")
    bs_reclass: dict[str, dict[str, str]] = wide.attrs.get("bs_reclass", {})

    for item in adjustments:
        period = str(item.get("period") or "")
        endpoint = str(item.get("endpoint") or "")
        field = str(item.get("field") or "")
        if not period or not field:
            continue
        if period not in wide.index:
            LOGGER.warning("Override skipped: period %s not in annual wide table", period)
            continue

        column = override_column_name(endpoint, field)
        if column not in wide.columns:
            wide[column] = 0.0
        old_value = float(wide.loc[period, column] or 0.0)
        new_value = float(item.get("new_value_million_cny") or 0.0)
        wide.loc[period, column] = new_value
        present_by_period.setdefault(period, set()).add(field)

        # 可选：override 指定 clean_category 时，把该字段在本期重分类到目标 bucket。
        # 用于 TuShare 字段默认 bucket 与本公司列报口径不一致（如比亚迪 estimated_liab
        # 预计负债列报为流动而非 TuShare 默认非流动）。只影响本期 bucket 加总，不改静态分类。
        clean_category = item.get("clean_category")
        if clean_category and endpoint == "balancesheet":
            default_cat = BS_FIELD_CATEGORIES.get(field)
            if str(clean_category) != default_cat:
                bs_reclass.setdefault(period, {})[field] = str(clean_category)
                LOGGER.warning(
                    "Override reclassified %s %s: %s -> %s (本期 bucket 归属)",
                    period, field, default_cat, clean_category,
                )

        record = {
            "applied_at": applied_at,
            "ticker": ticker,
            "period": period,
            "endpoint": endpoint,
            "field": field,
            "old_value_million_cny": old_value,
            "new_value_million_cny": new_value,
            "delta_million_cny": new_value - old_value,
            "failure_code": item.get("failure_code"),
            "annual_report_item": item.get("annual_report_item"),
            "confidence": item.get("confidence"),
            "source": item.get("source"),
            "source_markdown_path": item.get("source_markdown_path"),
            "source_reconciliation_path": item.get("source_reconciliation_path"),
            "evidence_lines": item.get("evidence_lines"),
            "reason": item.get("reason"),
            "clean_category": item.get("clean_category"),
        }
        applied.append(record)
        LOGGER.warning(
            "Applied annual-report override %s %s.%s: %.4f -> %.4f (%s)",
            period,
            endpoint,
            field,
            old_value,
            new_value,
            item.get("evidence_lines"),
        )

    if bs_reclass:
        wide.attrs["bs_reclass"] = bs_reclass

    return applied


def warning_period(message: str) -> str | None:
    match = re.search(r"\b(20\d{2}(?:Q[1-4])?)\b", message)
    return match.group(1) if match else None


def warning_code(message: str) -> str:
    match = re.match(r"((?:跨表\s+)?\d+(?:\.\d+)?[a-z]?)", message)
    return match.group(1) if match else "warning"


def write_audit_tables(
    conn: sqlite3.Connection,
    adjustments: list[dict[str, object]],
    validation_warnings: list[dict[str, object]],
) -> None:
    adj_df = pd.DataFrame(adjustments, columns=ADJUSTMENT_COLUMNS)
    adj_df.to_sql("clean_adjustments", conn, if_exists="replace", index=False)

    warnings = [
        {
            "created_at": item["applied_at"],
            "ticker": item["ticker"],
            "period": item["period"],
            "severity": "warning",
            "code": "annual_report_override",
            "message": (
                f"Applied annual-report override for {item['endpoint']}.{item['field']}: "
                f"{item['old_value_million_cny']:.4f} -> {item['new_value_million_cny']:.4f}"
            ),
            "source": item["source"],
            "evidence": item["evidence_lines"],
        }
        for item in adjustments
    ]
    warnings.extend(validation_warnings)
    warn_df = pd.DataFrame(warnings, columns=WARNING_COLUMNS)
    warn_df.to_sql("clean_warnings", conn, if_exists="replace", index=False)


def read_audit_table(conn: sqlite3.Connection, table_name: str, columns: list[str]) -> list[dict[str, object]]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if not exists:
        return []
    return pd.read_sql_query(f"SELECT * FROM {table_name}", conn).reindex(columns=columns).to_dict("records")


def write_audit_tables_for_mode(
    conn: sqlite3.Connection,
    adjustments: list[dict[str, object]],
    validation_warnings: list[dict[str, object]],
    *,
    mode: str,
) -> None:
    """Update audit tables without deleting unrelated mode history."""
    if mode == "all":
        write_audit_tables(conn, adjustments, validation_warnings)
        return

    existing_adjustments = read_audit_table(conn, "clean_adjustments", ADJUSTMENT_COLUMNS)
    existing_warnings = read_audit_table(conn, "clean_warnings", WARNING_COLUMNS)

    if mode == "quarterly":
        kept_adjustments = existing_adjustments
        kept_warnings = [
            item for item in existing_warnings
            if item.get("source") not in {
                "clean.py:quarterly",
                "clean.py:quarterly_bs_plug",
                "clean.py:quarterly_cf_cash_plug",
            }
            and item.get("code") not in {"quarterly_bs_plug", "quarterly_cf_cash_plug"}
        ]
        write_audit_tables(conn, kept_adjustments + adjustments, kept_warnings + validation_warnings)
        return

    if mode == "annual":
        kept_warnings = [
            item for item in existing_warnings
            if item.get("source") in {
                "clean.py:quarterly",
                "clean.py:quarterly_bs_plug",
                "clean.py:quarterly_cf_cash_plug",
            }
            or item.get("code") in {"quarterly_bs_plug", "quarterly_cf_cash_plug"}
        ]
        write_audit_tables(conn, adjustments, kept_warnings + validation_warnings)
        return

    raise ValueError(f"Unknown clean mode: {mode}")


def approved_override_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(
        1
        for item in data.get("adjustments", [])
        if item.get("status") == "approved" and item.get("source") in APPROVED_OVERRIDE_SOURCES
    )


def auto_reconcile_annual_failure(db_path: Path, ticker: str, *, max_failures: int) -> int:
    """Strong-trigger annual report reconciliation after an annual hard-check failure."""
    script = Path(__file__).resolve().parent / "annual_report_reconciler.py"
    if not script.exists():
        print(
            f"Annual reconciliation skipped: {script.name} was not found next to clean.py.",
            file=sys.stderr,
            flush=True,
        )
        return 127

    override_path = default_overrides_path(db_path)
    before_approved = approved_override_count(override_path)
    cmd = [
        sys.executable,
        "-m",
        "src.annual_report_reconciler",
        "--ticker",
        ticker,
        "--db",
        str(db_path),
        "--max-failures",
        str(max_failures),
        "--write-overrides",
        "--approve-high-confidence",
    ]

    print(
        "\nAnnual hard checks failed. This is a clean-data blocker, not a soft warning.",
        file=sys.stderr,
        flush=True,
    )
    print(
        "clean.py has stopped before producing a trusted annual clean output for this run.",
        file=sys.stderr,
        flush=True,
    )
    print(
        "Strong trigger: running annual_report_reconciler.py with LLM evidence to inspect local annual-report Markdown.",
        file=sys.stderr,
        flush=True,
    )
    print("Command: " + " ".join(cmd), file=sys.stderr, flush=True)

    result = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent)
    after_approved = approved_override_count(override_path)
    if result.returncode == 0:
        latest_path = recon_dir(company_dir_from_db_path(db_path)) / "annual_report_reconciliation_latest.json"
        print(f"Annual reconciliation evidence: {latest_path}", file=sys.stderr, flush=True)
        print(f"Annual override file: {override_path}", file=sys.stderr, flush=True)
        if after_approved > before_approved:
            print(
                f"LLM approved {after_approved - before_approved} new override(s). "
                "Rerun clean.py to apply them; raw_tushare remains unchanged.",
                file=sys.stderr,
                flush=True,
            )
        elif after_approved:
            print(
                f"No new approved override was added; {after_approved} approved override(s) already exist. "
                "Inspect the reconciliation JSON if annual clean still fails.",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                "No approved override was generated. Treat this as manual review: "
                "check the reconciliation JSON for classification/formula/TuShare evidence.",
                file=sys.stderr,
                flush=True,
            )
    else:
        print(
            f"annual_report_reconciler.py exited with code {result.returncode}. "
            "Inspect its output before trusting annual clean data.",
            file=sys.stderr,
            flush=True,
        )
    return result.returncode


def clean_dataset(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    mode: str,
    table_name: str,
    tolerance: float,
    annual_overrides: list[dict[str, object]] | None = None,
    applied_adjustments: list[dict[str, object]] | None = None,
    warning_records: list[dict[str, object]] | None = None,
    annual_plugs: list[dict[str, object]] | None = None,
    restatement_exemptions: list[dict[str, object]] | None = None,
    max_quarters: int = 48,
    pre_ipo_year: int | None = None,
) -> pd.DataFrame:
    """Clean one report_type/mode pair and write its wide table."""
    global TOLERANCE

    raw = load_raw_tushare(conn, ticker, mode=mode)
    raw = dedupe_by_f_ann_date(raw)
    wide, present_by_period = pivot_to_wide(raw, mode=mode, max_quarters=max_quarters)

    if mode == "quarterly":
        wide = split_cashflow_quarterly(wide, raw)
        wide, present_by_period = filter_to_output_periods(wide, present_by_period)
        cf_split_errors = validate_quarterly_cf_split(wide, raw, tolerance=tolerance)
        if cf_split_errors:
            print("\n❌ Quarterly CF split validation failed:", file=sys.stderr)
            for err in cf_split_errors[:20]:
                print("  - " + err, file=sys.stderr)
            if len(cf_split_errors) > 20:
                print(f"... and {len(cf_split_errors) - 20} more errors", file=sys.stderr)
            raise CheckError(f"{len(cf_split_errors)} quarterly CF split audit error(s)")
        cf_cash_warnings = apply_quarterly_cf_cash_plugs(wide, ticker, tolerance=tolerance)
        bs_plug_warnings = apply_quarterly_bs_plugs(wide, present_by_period, ticker)
        if warning_records is not None:
            warning_records.extend(cf_cash_warnings)
            warning_records.extend(bs_plug_warnings)
    elif mode == "annual":
        # Capture official total_cogs BEFORE adaptation mutates it (adaptation
        # rebuilds total_cogs from cost details, dropping impair). resolve_is_signs
        # needs the pre-adaptation value to detect whether a sign-questionable
        # field sits inside total_cogs (旧口径 regime). Quarterly mode never
        # adapts, so row["total_cogs"] is already raw there.
        wide.attrs["raw_total_cogs_by_period"] = {
            str(p): float(wide.loc[p, "total_cogs"] or 0.0) for p in wide.index
        }
        income_adaptation_warnings = apply_annual_income_subtotal_adaptations(wide, present_by_period, ticker)
        if warning_records is not None:
            warning_records.extend(income_adaptation_warnings)
        if annual_overrides:
            applied = apply_annual_overrides(wide, present_by_period, ticker, annual_overrides)
            if applied_adjustments is not None:
                applied_adjustments.extend(applied)
        # 年度 QA plug：两轮 reconciler 都无法解释的硬残差，用户明确同意后才塞。
        # 在 override 之后、validate 之前应用，plug 字段进 bs_bucket_sum 让 check_bs 通过。
        if annual_plugs:
            plug_warnings = apply_annual_bs_plugs(wide, present_by_period, ticker, annual_plugs)
            if warning_records is not None:
                warning_records.extend(plug_warnings)

    old_tolerance = TOLERANCE
    TOLERANCE = tolerance
    try:
        validation_warnings = validate_wide(
            wide, present_by_period, label=mode,
            restatement_exemptions=restatement_exemptions if mode == "annual" else None,
            pre_ipo_year=pre_ipo_year if mode == "annual" else None,
        )
    finally:
        TOLERANCE = old_tolerance

    if warning_records is not None:
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        for message in validation_warnings:
            warning_records.append(
                {
                    "created_at": created_at,
                    "ticker": ticker,
                    "period": warning_period(message),
                    "severity": "warning",
                    "code": warning_code(message),
                    "message": message,
                    "source": f"clean.py:{mode}",
                    "evidence": None,
                }
            )

    write_clean_table(conn, table_name, wide)
    sqlite_field_count = len(ensure_qa_columns(wide.copy()).columns)
    LOGGER.info("Written table %s (%d periods, %d fields)", table_name, len(wide), sqlite_field_count)
    return wide


def clean_all(
    db_path: str | Path,
    ticker: str,
    *,
    overrides_path: str | Path | None = None,
    apply_overrides: bool = True,
    mode: str = "all",
    max_quarters: int = 48,
    allow_annual_plug: bool = False,
    plugs_path: str | Path | None = None,
    restatement_exemptions_path: str | Path | None = None,
    apply_restatement_exemptions: bool = True,
) -> dict[str, pd.DataFrame]:
    """Clean annual and quarterly data and write SQLite tables."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if mode not in {"annual", "quarterly", "all"}:
        raise ValueError("mode must be annual, quarterly, or all")

    override_file = Path(overrides_path) if overrides_path else default_overrides_path(db_path)
    annual_overrides = (
        load_approved_overrides(override_file, ticker)
        if apply_overrides and mode in {"annual", "all"}
        else []
    )
    exemption_file = (
        Path(restatement_exemptions_path) if restatement_exemptions_path
        else default_restatement_exemptions_path(db_path)
    )
    restatement_exemptions = (
        load_restatement_exemptions(exemption_file, ticker)
        if apply_restatement_exemptions and mode in {"annual", "all"}
        else []
    )
    plug_file = Path(plugs_path) if plugs_path else default_plugs_path(db_path)
    annual_plugs = (
        load_annual_plugs(plug_file, ticker)
        if allow_annual_plug and mode in {"annual", "all"}
        else []
    )
    # pre-IPO 闸门：按最早可用年报 Markdown 判定 IPO 边界，早于该年的年度硬失败
    # 降级为 warning 不阻塞。无年报 MD 时返回 None（闸门关闭）。
    pre_ipo_year = earliest_annual_md_year(db_path)
    if pre_ipo_year is not None:
        LOGGER.info("pre-IPO 闸门：最早可用年报MD=%d，早于该年的年度硬失败将降级为 warning", pre_ipo_year)
    applied_adjustments: list[dict[str, object]] = []
    warning_records: list[dict[str, object]] = []
    outputs: dict[str, pd.DataFrame] = {}

    with closing(sqlite3.connect(db_path)) as conn:
        if mode in {"annual", "all"}:
            try:
                outputs["annual"] = clean_dataset(
                    conn,
                    ticker,
                    mode="annual",
                    table_name="clean_annual",
                    tolerance=ANNUAL_TOLERANCE,
                    annual_overrides=annual_overrides,
                    applied_adjustments=applied_adjustments,
                    warning_records=warning_records,
                    annual_plugs=annual_plugs,
                    restatement_exemptions=restatement_exemptions,
                    pre_ipo_year=pre_ipo_year,
                )
            except CheckError as exc:
                wrapper = CheckError(f"annual validation failed: {exc}")
                wrapper.errors = getattr(exc, "errors", [str(exc)])
                raise wrapper from exc
        if mode in {"quarterly", "all"}:
            try:
                outputs["quarterly"] = clean_dataset(
                    conn,
                    ticker,
                    mode="quarterly",
                    table_name="clean_quarterly",
                    tolerance=QUARTERLY_TOLERANCE,
                    warning_records=warning_records,
                    max_quarters=max_quarters,
                )
            except CheckError as exc:
                wrapper = CheckError(f"quarterly validation failed: {exc}")
                wrapper.errors = getattr(exc, "errors", [str(exc)])
                raise wrapper from exc
        write_audit_tables_for_mode(conn, applied_adjustments, warning_records, mode=mode)
        conn.commit()

    return outputs


def clean(db_path: str | Path, ticker: str) -> pd.DataFrame:
    """Clean annual and quarterly data, returning the annual wide table for compatibility."""
    return clean_all(db_path, ticker)["annual"]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Clean TuShare raw data into validated wide tables in SQLite.")
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 300866.SZ")
    parser.add_argument("--db", default=None, help="Path to data.db (auto-detected if omitted)")
    parser.add_argument("--overrides", default=None, help="Approved annual-report override JSON (default: company/Agent/recon/annual_report_overrides.json)")
    parser.add_argument("--no-overrides", action="store_true", help="Do not apply approved annual-report overrides")
    parser.add_argument("--allow-annual-plug", action="store_true", help="Apply user-approved annual QA plugs (annual_plugs.json) for hard residuals two reconciler rounds could not close. Written by init.py's plug prompt.")
    parser.add_argument("--plugs", default=None, help="Annual plug directive JSON (default: company/Agent/recon/annual_plugs.json)")
    parser.add_argument("--no-restatement-exemptions", action="store_true", help="Do not apply approved 跨表 7.4 restatement exemptions (restatement_exemptions.json)")
    parser.add_argument("--restatement-exemptions", default=None, help="Restatement exemption JSON (default: company/Agent/recon/restatement_exemptions.json)")
    parser.add_argument("--mode", choices=["annual", "quarterly", "all"], default="all", help="Which clean table(s) to build")
    parser.add_argument("--no-auto-reconcile", action="store_true", help="Do not run annual_report_reconciler.py after annual hard-check failure")
    parser.add_argument("--auto-reconcile-max-failures", type=int, default=60, help="Maximum annual failures to analyze when auto-reconciliation is triggered. Complex companies (financial subsidiaries, recurring missing fields) can exceed 30 failures; the cap must cover the full annual history so they reconcile fully rather than silently leaving later years unbalanced.")
    parser.add_argument("--max-quarters", type=int, default=48, help="Maximum quarterly periods to retain (default: 48)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ticker = args.ticker
    if args.db:
        db_path = Path(args.db)
    else:
        base = Path(__file__).resolve().parent.parent / "companies"
        try:
            db_path = find_agent_db_path(ticker, base)
        except FileNotFoundError:
            print(f"No Agent/data.db found for {ticker} in {base}", file=sys.stderr)
            return 1

    try:
        clean_all(
            db_path,
            ticker,
            overrides_path=args.overrides,
            apply_overrides=not args.no_overrides,
            mode=args.mode,
            max_quarters=args.max_quarters,
            allow_annual_plug=args.allow_annual_plug,
            plugs_path=args.plugs,
            restatement_exemptions_path=args.restatement_exemptions,
            apply_restatement_exemptions=not args.no_restatement_exemptions,
        )
    except CheckError as exc:
        print(f"\nValidation failed: {exc}", file=sys.stderr)
        annual_failure = args.mode == "annual" or str(exc).startswith("annual validation failed")
        if annual_failure and not args.no_auto_reconcile:
            auto_reconcile_annual_failure(
                Path(db_path),
                ticker,
                max_failures=max(args.auto_reconcile_max_failures, 0),
            )
        return 1
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        raise

    print("All checks passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
