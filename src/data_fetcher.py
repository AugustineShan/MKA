"""Fetch A-share financial statements from TuShare into SQLite DBs.

Public API for other agents:
    fetch_company("600519.SH", force_refresh=False) -> "D:\\MKA\\companies\\贵州茅台_600519\\data.db"
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import pandas as pd


LOGGER = logging.getLogger("data_fetcher")

TICKER_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TUSHARE_HTTP_URL = "http://api.waditu.com/dataapi"
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.8
OFFICIAL_TUSHARE_DOC_DIR = BASE_DIR / "TushareOfficialAPIMD"
ALLOWED_TUSHARE_HTTP_HOSTS = {"api.waditu.com", "api.tushare.pro"}

REPORT_TYPE_CONSOLIDATED = "1"
REPORT_TYPE_SINGLE_QUARTER_CONSOLIDATED = "2"
STATEMENT_REPORT_TYPES = (
    REPORT_TYPE_CONSOLIDATED,
    REPORT_TYPE_SINGLE_QUARTER_CONSOLIDATED,
)
REQUIRED_REPORT_TYPES_BY_ENDPOINT = {
    "income": (REPORT_TYPE_CONSOLIDATED,),
    "balancesheet": (REPORT_TYPE_CONSOLIDATED,),
    "cashflow": (REPORT_TYPE_CONSOLIDATED,),
}
GENERAL_INDUSTRIAL_COMP_TYPE = "1"

OFFICIAL_STATEMENT_DOCS = {
    "income": "income.md",
    "balancesheet": "balancesheet.md",
    "cashflow": "cashflow.md",
}

STATEMENT_METADATA_FIELDS = {
    "ts_code",
    "ann_date",
    "f_ann_date",
    "start_date",
    "end_date",
    "period",
    "report_type",
    "comp_type",
    "end_type",
    "update_flag",
    "is_calc",
}

UNIT_AMOUNT_CNY = "amount_cny"
UNIT_PERCENT = "percent"
UNIT_RATIO = "ratio"
UNIT_PRICE = "price"
UNIT_TURNOVER_RATE = "turnover_rate"
UNIT_DAILY_SHARE_10K = "daily_basic_share_10k"
UNIT_DAILY_MV_10K_CNY = "daily_basic_mv_10k_cny"
UNIT_SHARE = "share"

BALANCE_TOLERANCE = 0.01
RECONCILIATION_TOLERANCE = 0.01

CORE_LATEST_ANNUAL_FIELDS_BY_ENDPOINT = {
    "income": {
        "revenue",
        "n_income_attr_p",
    },
    "balancesheet": {
        "total_assets",
        "total_liab",
        "total_hldr_eqy_inc_min_int",
    },
    "cashflow": {
        "n_cashflow_act",
        "n_cashflow_inv_act",
        "n_cash_flows_fnc_act",
        "c_pay_acq_const_fiolta",
    },
}


@dataclass(frozen=True)
class FieldMapping:
    field: str
    unit: str
    required: bool = False


class DataHealthError(RuntimeError):
    """Raised when fetched data fails hard health checks before commit."""


_OFFICIAL_DOC_CACHE: dict[str, dict[str, tuple[str, str]]] = {}
_OFFICIAL_MAPPING_CACHE: dict[str, list[FieldMapping]] = {}


def fetch_company(
    ticker: str,
    force_refresh: bool = False,
    *,
    output_root: str | Path | None = None,
    token: str | None = None,
    pro: Any | None = None,
    today: dt.date | None = None,
) -> str:
    """Fetch one A-share company's financial data and return its SQLite path.

    Keyword-only arguments let future agents inject a mock TuShare client or
    redirect output without changing the stable public function signature.
    """

    fetcher = TushareDataFetcher(
        output_root=Path(output_root) if output_root else BASE_DIR,
        token=token,
        pro=pro,
        today=today,
    )
    return str(fetcher.fetch_company(ticker, force_refresh=force_refresh))


def fetch_companies(
    tickers: Iterable[str],
    force_refresh: bool = False,
    *,
    output_root: str | Path | None = None,
    token: str | None = None,
    pro: Any | None = None,
) -> dict[str, str]:
    """Convenience batch API for agents that need several companies."""

    fetcher = TushareDataFetcher(
        output_root=Path(output_root) if output_root else BASE_DIR,
        token=token,
        pro=pro,
    )
    return {
        normalize_ticker(ticker): str(fetcher.fetch_company(ticker, force_refresh=force_refresh))
        for ticker in tickers
    }


class TushareDataFetcher:
    def __init__(
        self,
        *,
        output_root: Path,
        token: str | None = None,
        pro: Any | None = None,
        today: dt.date | None = None,
        request_sleep_seconds: float | None = None,
    ) -> None:
        self.output_root = output_root
        self.token = token
        self._pro = pro
        self.today = today or dt.date.today()
        env_values = load_env_file(BASE_DIR / ".env")
        self.request_sleep_seconds = (
            request_sleep_seconds
            if request_sleep_seconds is not None
            else float(env_values.get("TUSHARE_MIN_INTERVAL_SECONDS", DEFAULT_MIN_REQUEST_INTERVAL_SECONDS))
        )
        self._latest_trade_date_cache: str | None = None

    @property
    def pro(self) -> Any:
        if self._pro is None:
            self._pro = create_tushare_client(self.token)
        return self._pro

    def fetch_company(self, ticker: str, force_refresh: bool = False) -> Path:
        ticker = normalize_ticker(ticker)
        company_name = self._existing_company_name(ticker) or self._get_company_name(ticker)
        db_path = self._company_db_path(ticker, company_name)

        latest_trade_date = self._latest_trade_date()
        mirror_cutoff_year = 0

        statement_dfs: dict[str, list[Any]] = {}
        for endpoint in OFFICIAL_STATEMENT_DOCS:
            statement_dfs[endpoint] = [
                self._fetch_statement(
                    endpoint,
                    ticker,
                    report_type,
                )
                for report_type in STATEMENT_REPORT_TYPES
            ]
        daily_basic_df = self._fetch_daily_basic(ticker, latest_trade_date)
        if not dataframe_empty(daily_basic_df) and "trade_date" in daily_basic_df.columns:
            latest_trade_date = str(daily_basic_df.iloc[0]["trade_date"])

        tushare_records: list[tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]] = []
        for endpoint, dfs in statement_dfs.items():
            for df in dfs:
                tushare_records.extend(
                    records_for_tushare_mirror(
                        ticker,
                        endpoint,
                        df,
                        official_statement_mappings(endpoint),
                        mirror_cutoff_year,
                    )
                )

        report_dfs = [
            df
            for dfs in statement_dfs.values()
            for df in dfs
        ]
        meta = {
            "ticker": ticker,
            "name": company_name,
            "last_updated": dt.datetime.now().isoformat(timespec="seconds"),
            "latest_trade_date": latest_trade_date,
        }
        meta.update(meta_from_daily_basic(daily_basic_df))
        meta.update(meta_from_reports(report_dfs))

        validate_records_before_write(ticker, tushare_records, meta)

        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            initialize_schema(conn)
            conn.commit()
            try:
                conn.execute("BEGIN")
                if force_refresh:
                    clear_company_data(conn, ticker)
                upsert_tushare_records(conn, tushare_records)
                upsert_meta(conn, meta)
                run_quality_checks(conn, ticker)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        LOGGER.info(
            "Fetched %s: %s raw TuShare rows -> %s",
            ticker,
            len(tushare_records),
            db_path,
        )
        return db_path

    def _fetch_statement(
        self,
        endpoint: str,
        ticker: str,
        report_type: str,
    ) -> Any:
        df = self._call_api(endpoint, ts_code=ticker, report_type=report_type)
        return filter_and_dedupe_statement(df, endpoint, report_type)

    def _fetch_daily_basic(self, ticker: str, trade_date: str) -> Any:
        fields = "ts_code,trade_date,total_share,float_share,total_mv,pe_ttm,pb,close"
        start = dt.datetime.strptime(trade_date, "%Y%m%d").date()
        last_candidate = trade_date
        for offset in range(0, 15):
            candidate = (start - dt.timedelta(days=offset)).strftime("%Y%m%d")
            last_candidate = candidate
            df = self._call_api("daily_basic", ts_code=ticker, trade_date=candidate, fields=fields)
            if not dataframe_empty(df):
                if candidate != trade_date:
                    LOGGER.warning("daily_basic empty for %s; using fallback trade_date=%s", trade_date, candidate)
                return df
        raise RuntimeError(
            f"daily_basic returned empty for {ticker} on {trade_date} "
            f"and all fallback trading days back to {last_candidate}"
        )

    def _get_company_name(self, ticker: str) -> str:
        try:
            df = self._call_api(
                "stock_basic",
                ts_code=ticker,
                fields="ts_code,symbol,name,list_status,market,exchange",
            )
            if not dataframe_empty(df) and "name" in df.columns:
                name = first_non_null(df.iloc[0].get("name"))
                if name:
                    return str(name)
        except Exception as exc:
            if is_auth_or_permission_error(exc):
                raise
            LOGGER.warning("Could not fetch stock_basic for %s: %s", ticker, exc)
        return ticker.split(".")[0]

    def _existing_company_name(self, ticker: str) -> str | None:
        code = ticker.split(".")[0]
        companies_dir = self.output_root / "companies"
        if not companies_dir.exists():
            return None
        candidates = sorted(companies_dir.glob(f"*_{code}"))
        if not candidates:
            return None
        name = candidates[0].name.rsplit("_", 1)[0]
        return name or None

    def _latest_trade_date(self) -> str:
        if self._latest_trade_date_cache:
            return self._latest_trade_date_cache
        end = self.today.strftime("%Y%m%d")
        start = (self.today - dt.timedelta(days=45)).strftime("%Y%m%d")
        df = self._call_api(
            "trade_cal",
            exchange="",
            start_date=start,
            end_date=end,
            is_open="1",
            fields="cal_date,is_open,pretrade_date",
        )
        if dataframe_empty(df) or "cal_date" not in df.columns:
            raise RuntimeError("trade_cal returned no open trading days")
        dates = sorted(str(value) for value in df["cal_date"].dropna().tolist())
        self._latest_trade_date_cache = dates[-1]
        return self._latest_trade_date_cache

    def _call_api(self, endpoint: str, **params: Any) -> Any:
        method = getattr(self.pro, endpoint)
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                result = method(**params)
                time.sleep(self.request_sleep_seconds)
                return result
            except Exception as exc:
                last_exc = exc
                if isinstance(exc, KeyError) and str(exc) == "'fields'":
                    LOGGER.warning("%s returned an empty payload without fields; treating as empty", endpoint)
                    time.sleep(self.request_sleep_seconds)
                    return pd.DataFrame()
                message = str(exc).lower()
                if is_auth_or_permission_error(exc):
                    raise RuntimeError(f"TuShare {endpoint} authentication/permission error: {exc}") from exc
                if is_permanent_error(exc):
                    raise RuntimeError(f"TuShare {endpoint} permanent request error, not retrying: {exc}") from exc
                if "fields" in params and ("field" in message or "字段" in message):
                    LOGGER.warning("%s rejected explicit fields; retrying without fields", endpoint)
                    params = {key: value for key, value in params.items() if key != "fields"}
                    continue
                if "频" in message or "limit" in message or "too many" in message:
                    wait_seconds = 60
                else:
                    wait_seconds = min(2**attempt, 10)
                LOGGER.warning(
                    "TuShare %s failed on attempt %s/3: %s; retrying in %ss",
                    endpoint,
                    attempt,
                    exc,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
        raise RuntimeError(f"TuShare {endpoint} failed after 3 attempts: {last_exc}") from last_exc

    def _company_db_path(self, ticker: str, company_name: str) -> Path:
        safe_name = sanitize_path_part(company_name)
        code = ticker.split(".")[0]
        return self.output_root / "companies" / f"{safe_name}_{code}" / "data.db"


def create_tushare_client(token: str | None = None, http_url: str | None = None) -> Any:
    env_values = load_env_file(BASE_DIR / ".env")
    token = (
        token
        or env_values.get("TUSHARE_TOKEN")
        or env_values.get("TUSHARE_API_KEY")
        or os.environ.get("TUSHARE_TOKEN")
        or os.environ.get("TUSHARE_API_KEY")
    )
    http_url = (
        http_url
        or env_values.get("TUSHARE_HTTP_URL")
        or os.environ.get("TUSHARE_HTTP_URL")
        or DEFAULT_TUSHARE_HTTP_URL
    )
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is missing; set it in the environment or .env")
    host = urlparse(http_url).netloc.lower()
    if host not in ALLOWED_TUSHARE_HTTP_HOSTS:
        raise ValueError(f"TUSHARE_HTTP_URL must use official TuShare source, not {host}")
    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError("tushare is not installed. Run: pip install tushare pandas") from exc
    ts.set_token(token)
    pro = ts.pro_api()
    if http_url:
        setattr(pro, "_DataApi__http_url", http_url)
    return pro


def is_auth_or_permission_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in [
            "token不对",
            "token 不对",
            "invalid token",
            "permission",
            "权限",
            "积分",
        ]
    )


def is_permanent_error(exc: Exception) -> bool:
    """Return True for TuShare errors that will not resolve by retrying.

    These are typically client-side mistakes (invalid parameter, unknown
    field/code, non-existent endpoint) rather than transient server issues.
    """
    message = str(exc).lower()
    permanent_markers = [
        "参数错误",
        "参数不对",
        "invalid parameter",
        "参数不能为空",
        "ts_code不存在",
        "ts_code 不存在",
        "股票代码不存在",
        "代码不存在",
        "invalid ts_code",
        "接口不存在",
        "api不存在",
        "field不存在",
        "字段不存在",
        "no such field",
        "unknown field",
        "endpoint不存在",
        "不存在该接口",
    ]
    return any(marker in message for marker in permanent_markers)


def load_env_file(path: Path) -> dict[str, str]:
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


def normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not TICKER_RE.match(normalized):
        raise ValueError(f"Unsupported ticker '{ticker}'. Expected A-share code like 600519.SH")
    return normalized


def sanitize_path_part(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return sanitized or "unknown"


def official_statement_mappings(endpoint: str) -> list[FieldMapping]:
    if endpoint in _OFFICIAL_MAPPING_CACHE:
        return _OFFICIAL_MAPPING_CACHE[endpoint]
    fields = official_doc_fields(endpoint)
    mappings: list[FieldMapping] = []
    for field, (tushare_type, _description) in sorted(fields.items()):
        if field in STATEMENT_METADATA_FIELDS or tushare_type != "float":
            continue
        mappings.append(
            FieldMapping(
                field,
                infer_statement_unit(endpoint, field),
            )
        )
    _OFFICIAL_MAPPING_CACHE[endpoint] = mappings
    return mappings


def official_doc_fields(endpoint: str) -> dict[str, tuple[str, str]]:
    if endpoint in _OFFICIAL_DOC_CACHE:
        return _OFFICIAL_DOC_CACHE[endpoint]
    doc_file = OFFICIAL_STATEMENT_DOCS[endpoint]
    path = OFFICIAL_TUSHARE_DOC_DIR / doc_file
    if not path.exists():
        raise RuntimeError(f"Official TuShare doc is missing: {path}")
    fields: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) >= 4 and parts[1] in {"str", "float", "int"}:
            name, tushare_type, description = parts[0], parts[1], parts[3]
        elif len(parts) >= 3 and parts[1] in {"str", "float", "int"}:
            name, tushare_type, description = parts[0], parts[1], parts[2]
        else:
            continue
        if name and name[0].isalpha() and all(char.isalnum() or char == "_" for char in name):
            fields[name] = (tushare_type, description)
    _OFFICIAL_DOC_CACHE[endpoint] = fields
    return fields


def infer_statement_unit(endpoint: str, field: str) -> str:
    if endpoint == "income" and field in {"basic_eps", "diluted_eps"}:
        return UNIT_PRICE
    if endpoint == "balancesheet" and field == "total_share":
        return UNIT_SHARE
    return UNIT_AMOUNT_CNY


def convert_value(value: Any, unit: str) -> float | None:
    if value is None:
        return None
    try:
        # pandas/numpy NaN is not equal to itself.
        if value != value:
            return None
    except TypeError:
        return None

    number = float(value)
    if unit == UNIT_AMOUNT_CNY:
        converted = number / 1_000_000
    elif unit == UNIT_PERCENT:
        converted = number / 100
    elif unit == UNIT_DAILY_SHARE_10K:
        converted = number / 100
    elif unit == UNIT_DAILY_MV_10K_CNY:
        converted = number / 100
    elif unit == UNIT_SHARE:
        converted = number / 1_000_000
    elif unit == UNIT_TURNOVER_RATE:
        if number <= 0:
            return None
        converted = 365 / number
    elif unit in {UNIT_RATIO, UNIT_PRICE}:
        converted = number
    else:
        raise ValueError(f"Unknown unit: {unit}")

    if unit == UNIT_PERCENT and abs(converted) > 10:
        LOGGER.warning("Percent value looks unusual after conversion: raw=%s converted=%s", value, converted)
    if unit in {UNIT_DAILY_SHARE_10K, UNIT_SHARE} and abs(converted) > 1_000_000:
        LOGGER.warning("Share value looks unusual after conversion: raw=%s converted=%s", value, converted)
    if unit == UNIT_AMOUNT_CNY and abs(converted) > 1_000_000_000:
        LOGGER.warning("CNY amount looks unusual after conversion: raw=%s converted=%s", value, converted)
    return converted


def dataframe_empty(df: Any) -> bool:
    return df is None or getattr(df, "empty", True)


def first_non_null(value: Any) -> Any | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        return None
    return value


def filter_and_dedupe_statement(df: Any, endpoint: str, report_type: str) -> Any:
    if dataframe_empty(df):
        LOGGER.info("%s report_type=%s returned empty DataFrame", endpoint, report_type)
        return df

    filtered = df.copy()
    if "report_type" in filtered.columns:
        filtered = filtered[filtered["report_type"].astype(str) == report_type]
    if "comp_type" in filtered.columns:
        non_general = filtered[filtered["comp_type"].notna() & (filtered["comp_type"].astype(str) != GENERAL_INDUSTRIAL_COMP_TYPE)]
        if not non_general.empty:
            LOGGER.warning(
                "%s returned %s non-general-industrial rows; they will be skipped",
                endpoint,
                len(non_general),
            )
        filtered = filtered[
            filtered["comp_type"].isna()
            | (filtered["comp_type"].astype(str) == GENERAL_INDUSTRIAL_COMP_TYPE)
        ]
    return dedupe_by_period(filtered, endpoint=f"{endpoint}/report_type={report_type}")


def dedupe_by_period(df: Any, endpoint: str) -> Any:
    if dataframe_empty(df) or "end_date" not in df.columns:
        return df
    sort_columns: list[str] = ["end_date"]
    ascending: list[bool] = [True]
    if "update_flag" in df.columns:
        df = df.assign(_update_rank=df["update_flag"].astype(str).eq("1").astype(int))
        sort_columns.append("_update_rank")
        ascending.append(True)
    for column in ["f_ann_date", "ann_date"]:
        if column in df.columns:
            sort_columns.append(column)
            ascending.append(True)
    deduped = df.sort_values(sort_columns, ascending=ascending).drop_duplicates(
        subset=["end_date"], keep="last"
    )
    LOGGER.debug("%s deduped %s -> %s rows", endpoint, len(df), len(deduped))
    return deduped.drop(columns=[col for col in ["_update_rank"] if col in deduped.columns])


def row_to_values(row: Any, mappings: list[FieldMapping]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for mapping in mappings:
        if mapping.field not in row.index:
            if mapping.required:
                LOGGER.warning("Required TuShare field missing: %s", mapping.field)
            values[mapping.field] = None
            continue
        values[mapping.field] = convert_value(row.get(mapping.field), mapping.unit)
    return values


def records_for_tushare_mirror(
    ticker: str,
    endpoint: str,
    df: Any,
    mappings: list[FieldMapping],
    cutoff_year: int,
) -> list[tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]]:
    if dataframe_empty(df) or "end_date" not in df.columns:
        return []
    records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ] = []
    for _, row in df.iterrows():
        end_date = str(row["end_date"])
        if len(end_date) >= 4 and end_date[:4].isdigit() and int(end_date[:4]) < cutoff_year:
            continue
        ann_date = string_or_none(row.get("ann_date")) if "ann_date" in row.index else None
        f_ann_date = string_or_none(row.get("f_ann_date")) if "f_ann_date" in row.index else None
        report_type = string_or_none(row.get("report_type")) if "report_type" in row.index else None
        comp_type = string_or_none(row.get("comp_type")) if "comp_type" in row.index else None
        update_flag = string_or_none(row.get("update_flag")) if "update_flag" in row.index else None
        for mapping in mappings:
            records.append(
                (
                    ticker,
                    endpoint,
                    end_date,
                    mapping.field,
                    convert_value(row.get(mapping.field), mapping.unit) if mapping.field in row.index else None,
                    ann_date,
                    f_ann_date,
                    report_type,
                    comp_type,
                    update_flag,
                )
            )
    return records


def string_or_none(value: Any) -> str | None:
    clean = first_non_null(value)
    return None if clean is None else str(clean)


def meta_from_daily_basic(df: Any) -> dict[str, str]:
    if dataframe_empty(df):
        LOGGER.warning("daily_basic returned empty DataFrame")
        return {}
    row = df.iloc[0]
    meta: dict[str, str] = {}
    if "trade_date" in row.index:
        meta["daily_basic_trade_date"] = str(row["trade_date"])

    for field in ("total_share", "float_share"):
        if field in row.index:
            value = convert_value(row.get(field), UNIT_DAILY_SHARE_10K)
            if value is not None:
                meta[field] = str(value)
    if "total_mv" in row.index:
        value = convert_value(row.get("total_mv"), UNIT_DAILY_MV_10K_CNY)
        if value is not None:
            meta["total_mv"] = str(value)
    for field in ("pe_ttm", "pb"):
        if field in row.index:
            value = convert_value(row.get(field), UNIT_RATIO)
            if value is not None:
                meta[field] = str(value)
    if "close" in row.index:
        value = convert_value(row.get("close"), UNIT_PRICE)
        if value is not None:
            meta["close"] = str(value)
    return meta


def meta_from_reports(dfs: list[Any]) -> dict[str, str]:
    ann_dates: list[str] = []
    f_ann_dates: list[str] = []
    periods: list[str] = []
    for df in dfs:
        if dataframe_empty(df):
            continue
        if "ann_date" in df.columns:
            ann_dates.extend(str(value) for value in df["ann_date"].dropna().tolist())
        if "f_ann_date" in df.columns:
            f_ann_dates.extend(str(value) for value in df["f_ann_date"].dropna().tolist())
        if "end_date" in df.columns:
            periods.extend(str(value) for value in df["end_date"].dropna().tolist())
    meta: dict[str, str] = {}
    if ann_dates:
        meta["last_ann_date"] = max(ann_dates)
    if f_ann_dates:
        meta["last_f_ann_date"] = max(f_ann_dates)
    if periods:
        meta["last_report_period"] = max(periods)
    return meta


def initialize_schema(conn: sqlite3.Connection) -> None:
    ensure_raw_tushare_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def ensure_raw_tushare_schema(conn: sqlite3.Connection) -> None:
    columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(raw_tushare)").fetchall()
    ]
    if not columns:
        create_raw_tushare_table(conn)
        return

    pk_columns = [
        row[1]
        for row in sorted(
            conn.execute("PRAGMA table_info(raw_tushare)").fetchall(),
            key=lambda item: item[5],
        )
        if row[5] > 0
    ]
    expected_pk = ["ticker", "endpoint", "report_type", "end_date", "field"]
    if pk_columns == expected_pk:
        return

    LOGGER.info("Migrating raw_tushare primary key to include report_type")
    conn.execute("ALTER TABLE raw_tushare RENAME TO raw_tushare_legacy")
    create_raw_tushare_table(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO raw_tushare (
            ticker, endpoint, report_type, end_date, field, value,
            ann_date, f_ann_date, comp_type, update_flag
        )
        SELECT ticker, endpoint, report_type, end_date, field, value,
               ann_date, f_ann_date, comp_type, update_flag
        FROM raw_tushare_legacy
        """
    )
    conn.execute("DROP TABLE raw_tushare_legacy")


def create_raw_tushare_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare (
            ticker TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            report_type TEXT NOT NULL,
            end_date TEXT NOT NULL,
            field TEXT NOT NULL,
            value REAL,
            ann_date TEXT,
            f_ann_date TEXT,
            comp_type TEXT,
            update_flag TEXT,
            PRIMARY KEY (ticker, endpoint, report_type, end_date, field)
        )
        """
    )


def clear_company_data(conn: sqlite3.Connection, ticker: str) -> None:
    conn.execute("DELETE FROM raw_tushare WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM meta")
    for table in ("clean_annual", "clean_quarterly"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def upsert_tushare_records(
    conn: sqlite3.Connection,
    records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
) -> None:
    upsert_rows = [
        (ticker, endpoint, report_type, end_date, field, value, ann_date, f_ann_date, comp_type, update_flag)
        for ticker, endpoint, end_date, field, value, ann_date, f_ann_date, report_type, comp_type, update_flag
        in records
    ]
    conn.executemany(
        """
        INSERT INTO raw_tushare (
            ticker, endpoint, report_type, end_date, field, value,
            ann_date, f_ann_date, comp_type, update_flag
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, endpoint, report_type, end_date, field) DO UPDATE SET
            value = excluded.value,
            ann_date = excluded.ann_date,
            f_ann_date = excluded.f_ann_date,
            comp_type = excluded.comp_type,
            update_flag = excluded.update_flag
        """,
        upsert_rows,
    )


def upsert_meta(conn: sqlite3.Connection, meta: Mapping[str, str]) -> None:
    conn.executemany(
        """
        INSERT INTO meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        [(key, str(value)) for key, value in meta.items()],
    )


def validate_records_before_write(
    ticker: str,
    tushare_records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
    meta: Mapping[str, str],
) -> None:
    errors: list[str] = []

    if not tushare_records:
        errors.append("no raw_tushare mirror records were generated")

    tushare_keys = [
        (ticker_, endpoint, report_type, end_date, field)
        for ticker_, endpoint, end_date, field, _value, _ann_date, _f_ann_date, report_type, *_rest in tushare_records
    ]
    errors.extend(duplicate_key_errors("raw_tushare", tushare_keys))

    if any(ticker_ != ticker for ticker_, *_rest in tushare_records):
        errors.append("raw_tushare records contain a different ticker")

    required_meta = {"ticker", "name", "latest_trade_date", "total_share", "total_mv"}
    missing_meta = sorted(key for key in required_meta if not meta.get(key))
    if missing_meta:
        errors.append("meta is missing required keys: " + ", ".join(missing_meta))

    if meta.get("ticker") and meta["ticker"] != ticker:
        errors.append(f"meta ticker {meta['ticker']} does not match requested ticker {ticker}")

    errors.extend(tushare_mirror_coverage_errors(tushare_records))
    errors.extend(latest_annual_core_errors(tushare_records))

    if errors:
        raise DataHealthError("Data health check failed before write: " + "; ".join(errors))


def tushare_mirror_coverage_errors(
    records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
) -> list[str]:
    errors: list[str] = []
    fields_by_endpoint_report_period: dict[tuple[str, str, str], set[str]] = {}
    endpoints_present = {(record[1], record[7]) for record in records}
    for endpoint in OFFICIAL_STATEMENT_DOCS:
        for report_type in REQUIRED_REPORT_TYPES_BY_ENDPOINT[endpoint]:
            if (endpoint, report_type) not in endpoints_present:
                errors.append(f"raw_tushare missing endpoint/report_type: {endpoint}/{report_type}")
    for _ticker, endpoint, end_date, field, _value, _ann_date, _f_ann_date, report_type, *_rest in records:
        fields_by_endpoint_report_period.setdefault((endpoint, report_type, end_date), set()).add(field)
    for (endpoint, report_type, end_date), actual_fields in fields_by_endpoint_report_period.items():
        expected_fields = {mapping.field for mapping in official_statement_mappings(endpoint)}
        missing = sorted(expected_fields - actual_fields)
        if missing:
            errors.append(
                f"raw_tushare {endpoint} report_type={report_type} {end_date} missing official fields: "
                + ", ".join(missing[:20])
            )
    return errors


def latest_annual_core_errors(
    records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
) -> list[str]:
    errors: list[str] = []
    annual_values: dict[tuple[str, str], float | None] = {}
    annual_periods = {
        end_date
        for _ticker, _endpoint, end_date, _field, _value, _ann_date, _f_ann_date, report_type, *_rest in records
        if report_type == REPORT_TYPE_CONSOLIDATED and end_date.endswith("1231")
    }
    if not annual_periods:
        return ["raw_tushare contains no annual 1231 report periods"]

    latest_end_date = max(annual_periods)
    for _ticker, endpoint, end_date, field, value, _ann_date, _f_ann_date, report_type, *_rest in records:
        if report_type == REPORT_TYPE_CONSOLIDATED and end_date == latest_end_date:
            annual_values[(endpoint, field)] = value

    for endpoint, fields in CORE_LATEST_ANNUAL_FIELDS_BY_ENDPOINT.items():
        missing_fields = sorted(
            field for field in fields if annual_values.get((endpoint, field)) is None
        )
        if missing_fields:
            errors.append(
                f"latest annual period {latest_end_date} {endpoint} missing core fields: "
                + ", ".join(missing_fields)
            )
    return errors


def duplicate_key_errors(label: str, keys: list[tuple[Any, ...]]) -> list[str]:
    seen: set[tuple[Any, ...]] = set()
    duplicates: list[tuple[Any, ...]] = []
    for key in keys:
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if not duplicates:
        return []
    sample = ", ".join(str(key) for key in duplicates[:5])
    return [f"{label} contains duplicate primary keys: {sample}"]


def run_quality_checks(conn: sqlite3.Connection, ticker: str) -> None:
    errors: list[str] = []

    for end_date, assets, liab, equity in conn.execute(
        """
        SELECT end_date,
               MAX(CASE WHEN field = 'total_assets' THEN value END),
               MAX(CASE WHEN field = 'total_liab' THEN value END),
               MAX(CASE WHEN field = 'total_hldr_eqy_inc_min_int' THEN value END)
        FROM raw_tushare
        WHERE ticker = ? AND endpoint = 'balancesheet' AND report_type = '1'
        GROUP BY end_date
        """,
        (ticker,),
    ):
        if assets is None or liab is None or equity is None:
            continue
        diff = abs(assets - liab - equity)
        if diff > BALANCE_TOLERANCE:
            errors.append(f"{end_date} balance sheet does not balance: diff={diff}")

    for end_date, cfo, cfi, cff, fx_effect, net_change in conn.execute(
        """
        SELECT end_date,
               MAX(CASE WHEN field = 'n_cashflow_act' THEN value END),
               MAX(CASE WHEN field = 'n_cashflow_inv_act' THEN value END),
               MAX(CASE WHEN field = 'n_cash_flows_fnc_act' THEN value END),
               MAX(CASE WHEN field = 'eff_fx_flu_cash' THEN value END),
               MAX(CASE WHEN field = 'n_incr_cash_cash_equ' THEN value END)
        FROM raw_tushare
        WHERE ticker = ? AND endpoint = 'cashflow' AND report_type = '1'
        GROUP BY end_date
        """,
        (ticker,),
    ):
        if cfo is None or cfi is None or cff is None or net_change is None:
            continue
        fx = fx_effect or 0
        diff = abs((cfo + cfi + cff + fx) - net_change)
        if diff > RECONCILIATION_TOLERANCE:
            errors.append(f"{end_date} cash flow reconciliation differs by {diff}")

    if errors:
        raise DataHealthError("Data health check failed before commit: " + "; ".join(errors[:20]))


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch TuShare financial data into SQLite.")
    parser.add_argument("--ticker", required=True, help="A-share ticker, e.g. 600519.SH")
    parser.add_argument("--force", action="store_true", help="Clear existing company data before fetching")
    parser.add_argument("--output-root", default=str(BASE_DIR), help="Output root, default is project root")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    db_path = fetch_company(args.ticker, force_refresh=args.force, output_root=args.output_root)
    print(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
