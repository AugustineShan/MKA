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


LOGGER = logging.getLogger("data_fetcher")

TICKER_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TUSHARE_HTTP_URL = "https://fastapic.stockai888.top"
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.8

REPORT_TYPE_CONSOLIDATED = "1"
GENERAL_INDUSTRIAL_COMP_TYPE = "1"

OFFICIAL_STATEMENT_DOCS = {
    "income": 33,
    "balancesheet": 36,
    "cashflow": 44,
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

QUARTER_BY_SUFFIX = {
    "0331": "Q1",
    "0630": "Q2",
    "0930": "Q3",
    "1231": "Q4",
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

CORE_LATEST_ANNUAL_FIELDS = {
    "revenue",
    "n_income_attr_p",
    "total_assets",
    "total_liab",
    "total_hldr_eqy_inc_min_int",
    "n_cashflow_act",
    "n_cashflow_inv_act",
    "n_cash_flows_fnc_act",
    "c_pay_acq_const_fiolta",
}

FLOW_RECONCILIATION_FIELDS = {
    "revenue",
    "n_income_attr_p",
    "n_cashflow_act",
    "n_cashflow_inv_act",
    "n_cash_flows_fnc_act",
    "c_pay_acq_const_fiolta",
    "n_incr_cash_cash_equ",
}


@dataclass(frozen=True)
class FieldMapping:
    field: str
    unit: str
    required: bool = False


class DataHealthError(RuntimeError):
    """Raised when fetched data fails hard health checks before commit."""


INCOME_MAPPINGS = [
    FieldMapping("revenue", UNIT_AMOUNT_CNY, True),
    FieldMapping("total_revenue", UNIT_AMOUNT_CNY),
    FieldMapping("oper_cost", UNIT_AMOUNT_CNY),
    FieldMapping("total_cogs", UNIT_AMOUNT_CNY),
    FieldMapping("biz_tax_surchg", UNIT_AMOUNT_CNY),
    FieldMapping("sell_exp", UNIT_AMOUNT_CNY),
    FieldMapping("admin_exp", UNIT_AMOUNT_CNY),
    FieldMapping("rd_exp", UNIT_AMOUNT_CNY),
    FieldMapping("fin_exp", UNIT_AMOUNT_CNY),
    FieldMapping("fin_exp_int_exp", UNIT_AMOUNT_CNY),
    FieldMapping("fin_exp_int_inc", UNIT_AMOUNT_CNY),
    FieldMapping("assets_impair_loss", UNIT_AMOUNT_CNY),
    FieldMapping("credit_impa_loss", UNIT_AMOUNT_CNY),
    FieldMapping("oth_income", UNIT_AMOUNT_CNY),
    FieldMapping("invest_income", UNIT_AMOUNT_CNY),
    FieldMapping("fv_value_chg_gain", UNIT_AMOUNT_CNY),
    FieldMapping("asset_disp_income", UNIT_AMOUNT_CNY),
    FieldMapping("operate_profit", UNIT_AMOUNT_CNY),
    FieldMapping("non_oper_income", UNIT_AMOUNT_CNY),
    FieldMapping("non_oper_exp", UNIT_AMOUNT_CNY),
    FieldMapping("total_profit", UNIT_AMOUNT_CNY),
    FieldMapping("income_tax", UNIT_AMOUNT_CNY),
    FieldMapping("n_income", UNIT_AMOUNT_CNY),
    FieldMapping("minority_gain", UNIT_AMOUNT_CNY),
    FieldMapping("n_income_attr_p", UNIT_AMOUNT_CNY, True),
]

BALANCE_MAPPINGS = [
    FieldMapping("money_cap", UNIT_AMOUNT_CNY),
    FieldMapping("trad_asset", UNIT_AMOUNT_CNY),
    FieldMapping("notes_receiv", UNIT_AMOUNT_CNY),
    FieldMapping("accounts_receiv", UNIT_AMOUNT_CNY),
    FieldMapping("prepayment", UNIT_AMOUNT_CNY),
    FieldMapping("oth_receiv", UNIT_AMOUNT_CNY),
    FieldMapping("inventories", UNIT_AMOUNT_CNY),
    FieldMapping("contract_assets", UNIT_AMOUNT_CNY),
    FieldMapping("total_cur_assets", UNIT_AMOUNT_CNY),
    FieldMapping("fix_assets", UNIT_AMOUNT_CNY),
    FieldMapping("cip", UNIT_AMOUNT_CNY),
    FieldMapping("intan_assets", UNIT_AMOUNT_CNY),
    FieldMapping("goodwill", UNIT_AMOUNT_CNY),
    FieldMapping("lt_amor_exp", UNIT_AMOUNT_CNY),
    FieldMapping("use_right_assets", UNIT_AMOUNT_CNY),
    FieldMapping("defer_tax_assets", UNIT_AMOUNT_CNY),
    FieldMapping("total_nca", UNIT_AMOUNT_CNY),
    FieldMapping("total_assets", UNIT_AMOUNT_CNY, True),
    FieldMapping("st_borr", UNIT_AMOUNT_CNY),
    FieldMapping("notes_payable", UNIT_AMOUNT_CNY),
    FieldMapping("acct_payable", UNIT_AMOUNT_CNY),
    FieldMapping("contract_liab", UNIT_AMOUNT_CNY),
    FieldMapping("adv_receipts", UNIT_AMOUNT_CNY),
    FieldMapping("payroll_payable", UNIT_AMOUNT_CNY),
    FieldMapping("taxes_payable", UNIT_AMOUNT_CNY),
    FieldMapping("oth_payable", UNIT_AMOUNT_CNY),
    FieldMapping("total_cur_liab", UNIT_AMOUNT_CNY),
    FieldMapping("lt_borr", UNIT_AMOUNT_CNY),
    FieldMapping("bond_payable", UNIT_AMOUNT_CNY),
    FieldMapping("lease_liab", UNIT_AMOUNT_CNY),
    FieldMapping("defer_tax_liab", UNIT_AMOUNT_CNY),
    FieldMapping("total_ncl", UNIT_AMOUNT_CNY),
    FieldMapping("total_liab", UNIT_AMOUNT_CNY, True),
    FieldMapping("total_share", UNIT_SHARE),
    FieldMapping("cap_rese", UNIT_AMOUNT_CNY),
    FieldMapping("surplus_rese", UNIT_AMOUNT_CNY),
    FieldMapping("undistr_porfit", UNIT_AMOUNT_CNY),
    FieldMapping("minority_int", UNIT_AMOUNT_CNY),
    FieldMapping("total_hldr_eqy_exc_min_int", UNIT_AMOUNT_CNY),
    FieldMapping("total_hldr_eqy_inc_min_int", UNIT_AMOUNT_CNY, True),
]

CASHFLOW_MAPPINGS = [
    FieldMapping("n_cashflow_act", UNIT_AMOUNT_CNY, True),
    FieldMapping("depr_fa_coga_dpba", UNIT_AMOUNT_CNY),
    FieldMapping("amort_intang_assets", UNIT_AMOUNT_CNY),
    FieldMapping("lt_amort_deferred_exp", UNIT_AMOUNT_CNY),
    FieldMapping("n_cashflow_inv_act", UNIT_AMOUNT_CNY, True),
    FieldMapping("c_pay_acq_const_fiolta", UNIT_AMOUNT_CNY, True),
    FieldMapping("c_paid_invest", UNIT_AMOUNT_CNY),
    FieldMapping("c_disp_withdrwl_invest", UNIT_AMOUNT_CNY),
    FieldMapping("c_recp_return_invest", UNIT_AMOUNT_CNY),
    FieldMapping("n_cash_flows_fnc_act", UNIT_AMOUNT_CNY, True),
    FieldMapping("c_recp_borrow", UNIT_AMOUNT_CNY),
    FieldMapping("c_prepay_amt_borr", UNIT_AMOUNT_CNY),
    FieldMapping("c_pay_dist_dpcp_int_exp", UNIT_AMOUNT_CNY),
    FieldMapping("c_recp_cap_contrib", UNIT_AMOUNT_CNY),
    FieldMapping("eff_fx_flu_cash", UNIT_AMOUNT_CNY),
    FieldMapping("n_incr_cash_cash_equ", UNIT_AMOUNT_CNY),
]

FINA_INDICATOR_MAPPINGS = [
    FieldMapping("roe", UNIT_PERCENT),
    FieldMapping("roe_dt", UNIT_PERCENT),
    FieldMapping("roa", UNIT_PERCENT),
    FieldMapping("grossprofit_margin", UNIT_PERCENT),
    FieldMapping("netprofit_margin", UNIT_PERCENT),
    FieldMapping("debt_to_assets", UNIT_PERCENT),
    FieldMapping("current_ratio", UNIT_RATIO),
    FieldMapping("ar_turn", UNIT_TURNOVER_RATE),
    FieldMapping("inv_turn", UNIT_TURNOVER_RATE),
    FieldMapping("profit_dedt", UNIT_AMOUNT_CNY),
    FieldMapping("ebit", UNIT_AMOUNT_CNY),
    FieldMapping("ebitda", UNIT_AMOUNT_CNY),
]

DAILY_BASIC_MAPPINGS = [
    FieldMapping("total_share", UNIT_DAILY_SHARE_10K),
    FieldMapping("float_share", UNIT_DAILY_SHARE_10K),
    FieldMapping("total_mv", UNIT_DAILY_MV_10K_CNY),
    FieldMapping("pe_ttm", UNIT_RATIO),
    FieldMapping("pb", UNIT_RATIO),
    FieldMapping("close", UNIT_PRICE),
]

_OFFICIAL_DOC_CACHE: dict[str, dict[str, tuple[str, str]]] = {}
_OFFICIAL_MAPPING_CACHE: dict[str, list[FieldMapping]] = {}

METADATA_FIELDS = [
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "update_flag",
]


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
        company_name = self._get_company_name(ticker)
        db_path = self._company_db_path(ticker, company_name)

        latest_trade_date = self._latest_trade_date()
        annual_cutoff_year = self.today.year - 10
        quarterly_cutoff_year = self.today.year - 3

        income_df = self._fetch_statement("income", ticker, official_statement_mappings("income"))
        balance_df = self._fetch_statement(
            "balancesheet", ticker, official_statement_mappings("balancesheet")
        )
        cashflow_df = self._fetch_statement(
            "cashflow", ticker, official_statement_mappings("cashflow")
        )
        fina_df = self._fetch_fina_indicator(ticker)
        daily_basic_df = self._fetch_daily_basic(ticker, latest_trade_date)

        annual_records: list[tuple[str, int, str, float | None]] = []
        quarterly_records: list[tuple[str, str, str, float | None]] = []
        tushare_records: list[tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]] = []

        annual_records.extend(
            records_for_annual(ticker, income_df, INCOME_MAPPINGS, annual_cutoff_year)
        )
        annual_records.extend(
            records_for_annual(ticker, balance_df, BALANCE_MAPPINGS, annual_cutoff_year)
        )
        annual_records.extend(
            records_for_annual(ticker, cashflow_df, CASHFLOW_MAPPINGS, annual_cutoff_year)
        )
        annual_records.extend(
            records_for_annual(ticker, fina_df, FINA_INDICATOR_MAPPINGS, annual_cutoff_year)
        )

        quarterly_records.extend(
            records_for_quarterly_flow(
                ticker, income_df, INCOME_MAPPINGS, quarterly_cutoff_year
            )
        )
        quarterly_records.extend(
            records_for_quarterly_point(
                ticker, balance_df, BALANCE_MAPPINGS, quarterly_cutoff_year
            )
        )
        quarterly_records.extend(
            records_for_quarterly_flow(
                ticker, cashflow_df, CASHFLOW_MAPPINGS, quarterly_cutoff_year
            )
        )
        tushare_records.extend(
            records_for_tushare_mirror(
                ticker, "income", income_df, official_statement_mappings("income"), annual_cutoff_year
            )
        )
        tushare_records.extend(
            records_for_tushare_mirror(
                ticker,
                "balancesheet",
                balance_df,
                official_statement_mappings("balancesheet"),
                annual_cutoff_year,
            )
        )
        tushare_records.extend(
            records_for_tushare_mirror(
                ticker,
                "cashflow",
                cashflow_df,
                official_statement_mappings("cashflow"),
                annual_cutoff_year,
            )
        )

        meta = {
            "ticker": ticker,
            "name": company_name,
            "last_updated": dt.datetime.now().isoformat(timespec="seconds"),
            "latest_trade_date": latest_trade_date,
        }
        meta.update(meta_from_daily_basic(daily_basic_df, DAILY_BASIC_MAPPINGS))
        meta.update(meta_from_reports([income_df, balance_df, cashflow_df, fina_df]))

        validate_records_before_write(ticker, annual_records, quarterly_records, tushare_records, meta)

        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            initialize_schema(conn)
            try:
                conn.execute("BEGIN")
                if force_refresh:
                    clear_company_data(conn, ticker)
                upsert_tushare_records(conn, tushare_records)
                upsert_annual_records(conn, annual_records)
                upsert_quarterly_records(conn, quarterly_records)
                upsert_meta(conn, meta)
                run_quality_checks(conn, ticker)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        LOGGER.info(
            "Fetched %s: %s raw TuShare rows, %s annual rows, %s quarterly rows -> %s",
            ticker,
            len(tushare_records),
            len(annual_records),
            len(quarterly_records),
            db_path,
        )
        return db_path

    def _fetch_statement(
        self,
        endpoint: str,
        ticker: str,
        mappings: list[FieldMapping],
    ) -> Any:
        fields = fields_for_mappings(mappings)
        df = self._call_api(endpoint, ts_code=ticker, report_type=REPORT_TYPE_CONSOLIDATED, fields=fields)
        return filter_and_dedupe_statement(df, endpoint)

    def _fetch_fina_indicator(self, ticker: str) -> Any:
        fields = fields_for_mappings(FINA_INDICATOR_MAPPINGS, include_report_type=False)
        df = self._call_api("fina_indicator", ts_code=ticker, fields=fields)
        return dedupe_by_period(df, endpoint="fina_indicator")

    def _fetch_daily_basic(self, ticker: str, trade_date: str) -> Any:
        fields = ",".join(["ts_code", "trade_date"] + [m.field for m in DAILY_BASIC_MAPPINGS])
        return self._call_api("daily_basic", ts_code=ticker, trade_date=trade_date, fields=fields)

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
                message = str(exc).lower()
                if is_auth_or_permission_error(exc):
                    raise RuntimeError(f"TuShare {endpoint} authentication/permission error: {exc}") from exc
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


def fields_for_mappings(mappings: list[FieldMapping], include_report_type: bool = True) -> str:
    fields = list(METADATA_FIELDS if include_report_type else ["ts_code", "ann_date", "end_date", "update_flag"])
    fields.extend(mapping.field for mapping in mappings)
    return ",".join(dict.fromkeys(fields))


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
    doc_id = OFFICIAL_STATEMENT_DOCS[endpoint]
    path = BASE_DIR / ".refs" / "tushare-docs" / f"{doc_id}.md"
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


def filter_and_dedupe_statement(df: Any, endpoint: str) -> Any:
    if dataframe_empty(df):
        LOGGER.info("%s returned empty DataFrame", endpoint)
        return df

    filtered = df.copy()
    if "report_type" in filtered.columns:
        filtered = filtered[filtered["report_type"].astype(str) == REPORT_TYPE_CONSOLIDATED]
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
    return dedupe_by_period(filtered, endpoint=endpoint)


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


def records_for_annual(
    ticker: str,
    df: Any,
    mappings: list[FieldMapping],
    cutoff_year: int,
) -> list[tuple[str, int, str, float | None]]:
    if dataframe_empty(df) or "end_date" not in df.columns:
        return []
    records: list[tuple[str, int, str, float | None]] = []
    annual_df = df[df["end_date"].astype(str).str.endswith("1231")]
    for _, row in annual_df.iterrows():
        end_date = str(row["end_date"])
        year = int(end_date[:4])
        if year < cutoff_year:
            continue
        for field, value in row_to_values(row, mappings).items():
            records.append((ticker, year, field, value))
    return records


def records_for_quarterly_point(
    ticker: str,
    df: Any,
    mappings: list[FieldMapping],
    cutoff_year: int,
) -> list[tuple[str, str, str, float | None]]:
    if dataframe_empty(df) or "end_date" not in df.columns:
        return []
    records: list[tuple[str, str, str, float | None]] = []
    for _, row in df.iterrows():
        period = period_label(str(row["end_date"]))
        if period is None or int(period[:4]) < cutoff_year:
            continue
        for field, value in row_to_values(row, mappings).items():
            records.append((ticker, period, field, value))
    return records


def records_for_quarterly_flow(
    ticker: str,
    df: Any,
    mappings: list[FieldMapping],
    cutoff_year: int,
) -> list[tuple[str, str, str, float | None]]:
    if dataframe_empty(df) or "end_date" not in df.columns:
        return []

    by_year: dict[int, dict[str, dict[str, float | None]]] = {}
    for _, row in df.iterrows():
        end_date = str(row["end_date"])
        label = period_label(end_date)
        if label is None:
            continue
        year = int(label[:4])
        if year < cutoff_year:
            continue
        quarter = label[-2:]
        by_year.setdefault(year, {})[quarter] = row_to_values(row, mappings)

    records: list[tuple[str, str, str, float | None]] = []
    for year, quarters in by_year.items():
        fields = [mapping.field for mapping in mappings]
        for field in fields:
            q1 = value_for(quarters, "Q1", field)
            h1 = value_for(quarters, "Q2", field)
            q3_cum = value_for(quarters, "Q3", field)
            annual = value_for(quarters, "Q4", field)
            single_values = {
                "Q1": q1,
                "Q2": subtract_or_none(h1, q1),
                "Q3": subtract_or_none(q3_cum, h1),
                "Q4": subtract_or_none(annual, q3_cum),
            }
            for quarter, value in single_values.items():
                if value is not None and value < 0:
                    LOGGER.warning("%s %s%s %s split to negative value %s", ticker, year, quarter, field, value)
                records.append((ticker, f"{year}{quarter}", field, value))
    return records


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
            if mapping.field not in row.index:
                continue
            records.append(
                (
                    ticker,
                    endpoint,
                    end_date,
                    mapping.field,
                    convert_value(row.get(mapping.field), mapping.unit),
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


def value_for(quarters: Mapping[str, Mapping[str, float | None]], quarter: str, field: str) -> float | None:
    return quarters.get(quarter, {}).get(field)


def subtract_or_none(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def period_label(end_date: str) -> str | None:
    if len(end_date) != 8 or not end_date[:4].isdigit():
        return None
    quarter = QUARTER_BY_SUFFIX.get(end_date[4:])
    if not quarter:
        return None
    return f"{end_date[:4]}{quarter}"


def meta_from_daily_basic(df: Any, mappings: list[FieldMapping]) -> dict[str, str]:
    if dataframe_empty(df):
        LOGGER.warning("daily_basic returned empty DataFrame")
        return {}
    row = df.iloc[0]
    meta: dict[str, str] = {}
    if "trade_date" in row.index:
        meta["daily_basic_trade_date"] = str(row["trade_date"])
    for mapping in mappings:
        if mapping.field in row.index:
            value = convert_value(row.get(mapping.field), mapping.unit)
            if value is not None:
                meta[mapping.field] = str(value)
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_tushare (
            ticker TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            end_date TEXT NOT NULL,
            field TEXT NOT NULL,
            value REAL,
            ann_date TEXT,
            f_ann_date TEXT,
            report_type TEXT,
            comp_type TEXT,
            update_flag TEXT,
            PRIMARY KEY (ticker, endpoint, end_date, field)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_annual (
            ticker TEXT NOT NULL,
            year INTEGER NOT NULL,
            field TEXT NOT NULL,
            value REAL,
            PRIMARY KEY (ticker, year, field)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_quarterly (
            ticker TEXT NOT NULL,
            period TEXT NOT NULL,
            field TEXT NOT NULL,
            value REAL,
            PRIMARY KEY (ticker, period, field)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def clear_company_data(conn: sqlite3.Connection, ticker: str) -> None:
    conn.execute("DELETE FROM raw_tushare WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM raw_annual WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM raw_quarterly WHERE ticker = ?", (ticker,))
    conn.execute("DELETE FROM meta")


def upsert_tushare_records(
    conn: sqlite3.Connection,
    records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
) -> None:
    conn.executemany(
        """
        INSERT INTO raw_tushare (
            ticker, endpoint, end_date, field, value,
            ann_date, f_ann_date, report_type, comp_type, update_flag
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, endpoint, end_date, field) DO UPDATE SET
            value = excluded.value,
            ann_date = excluded.ann_date,
            f_ann_date = excluded.f_ann_date,
            report_type = excluded.report_type,
            comp_type = excluded.comp_type,
            update_flag = excluded.update_flag
        """,
        records,
    )


def upsert_annual_records(
    conn: sqlite3.Connection,
    records: list[tuple[str, int, str, float | None]],
) -> None:
    conn.executemany(
        """
        INSERT INTO raw_annual (ticker, year, field, value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker, year, field) DO UPDATE SET value = excluded.value
        """,
        records,
    )


def upsert_quarterly_records(
    conn: sqlite3.Connection,
    records: list[tuple[str, str, str, float | None]],
) -> None:
    conn.executemany(
        """
        INSERT INTO raw_quarterly (ticker, period, field, value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker, period, field) DO UPDATE SET value = excluded.value
        """,
        records,
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
    annual_records: list[tuple[str, int, str, float | None]],
    quarterly_records: list[tuple[str, str, str, float | None]],
    tushare_records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
    meta: Mapping[str, str],
) -> None:
    errors: list[str] = []

    if not tushare_records:
        errors.append("no raw_tushare mirror records were generated")
    if not annual_records:
        errors.append("no annual records were generated")
    if not quarterly_records:
        errors.append("no quarterly records were generated")

    annual_keys = [(ticker_, year, field) for ticker_, year, field, _ in annual_records]
    quarterly_keys = [(ticker_, period, field) for ticker_, period, field, _ in quarterly_records]
    tushare_keys = [
        (ticker_, endpoint, end_date, field)
        for ticker_, endpoint, end_date, field, *_rest in tushare_records
    ]
    errors.extend(duplicate_key_errors("raw_tushare", tushare_keys))
    errors.extend(duplicate_key_errors("raw_annual", annual_keys))
    errors.extend(duplicate_key_errors("raw_quarterly", quarterly_keys))

    if any(ticker_ != ticker for ticker_, *_rest in tushare_records):
        errors.append("raw_tushare records contain a different ticker")
    if any(ticker_ != ticker for ticker_, _, _, _ in annual_records):
        errors.append("annual records contain a different ticker")
    if any(ticker_ != ticker for ticker_, _, _, _ in quarterly_records):
        errors.append("quarterly records contain a different ticker")

    annual_by_year_field = {
        (year, field): value for _, year, field, value in annual_records
    }
    if annual_by_year_field:
        latest_year = max(year for _, year, _, _ in annual_records)
        missing_latest_fields = sorted(
            field
            for field in CORE_LATEST_ANNUAL_FIELDS
            if annual_by_year_field.get((latest_year, field)) is None
        )
        if missing_latest_fields:
            errors.append(
                f"latest annual year {latest_year} is missing core fields: "
                + ", ".join(missing_latest_fields)
            )

    required_meta = {"ticker", "name", "latest_trade_date", "total_share", "total_mv"}
    missing_meta = sorted(key for key in required_meta if not meta.get(key))
    if missing_meta:
        errors.append("meta is missing required keys: " + ", ".join(missing_meta))

    if meta.get("ticker") and meta["ticker"] != ticker:
        errors.append(f"meta ticker {meta['ticker']} does not match requested ticker {ticker}")

    errors.extend(tushare_mirror_coverage_errors(tushare_records))

    if errors:
        raise DataHealthError("Data health check failed before write: " + "; ".join(errors))


def tushare_mirror_coverage_errors(
    records: list[
        tuple[str, str, str, str, float | None, str | None, str | None, str | None, str | None, str | None]
    ],
) -> list[str]:
    errors: list[str] = []
    fields_by_endpoint_period: dict[tuple[str, str], set[str]] = {}
    endpoints_present = {record[1] for record in records}
    for endpoint in OFFICIAL_STATEMENT_DOCS:
        if endpoint not in endpoints_present:
            errors.append(f"raw_tushare missing endpoint: {endpoint}")
    for _ticker, endpoint, end_date, field, *_rest in records:
        fields_by_endpoint_period.setdefault((endpoint, end_date), set()).add(field)
    for (endpoint, end_date), actual_fields in fields_by_endpoint_period.items():
        expected_fields = {mapping.field for mapping in official_statement_mappings(endpoint)}
        missing = sorted(expected_fields - actual_fields)
        if missing:
            errors.append(
                f"raw_tushare {endpoint} {end_date} missing official fields: "
                + ", ".join(missing[:20])
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

    for period, assets, liab, equity in conn.execute(
        """
        SELECT period,
               MAX(CASE WHEN field = 'total_assets' THEN value END),
               MAX(CASE WHEN field = 'total_liab' THEN value END),
               MAX(CASE WHEN field = 'total_hldr_eqy_inc_min_int' THEN value END)
        FROM raw_quarterly
        WHERE ticker = ?
        GROUP BY period
        """,
        (ticker,),
    ):
        if assets is None or liab is None or equity is None:
            continue
        diff = abs(assets - liab - equity)
        if diff > BALANCE_TOLERANCE:
            errors.append(f"{period} balance sheet does not balance: diff={diff}")

    for period, cfo, cfi, cff, fx_effect, net_change in conn.execute(
        """
        SELECT period,
               MAX(CASE WHEN field = 'n_cashflow_act' THEN value END),
               MAX(CASE WHEN field = 'n_cashflow_inv_act' THEN value END),
               MAX(CASE WHEN field = 'n_cash_flows_fnc_act' THEN value END),
               MAX(CASE WHEN field = 'eff_fx_flu_cash' THEN value END),
               MAX(CASE WHEN field = 'n_incr_cash_cash_equ' THEN value END)
        FROM raw_quarterly
        WHERE ticker = ?
        GROUP BY period
        """,
        (ticker,),
    ):
        if cfo is None or cfi is None or cff is None or net_change is None:
            continue
        fx = fx_effect or 0
        diff = abs((cfo + cfi + cff + fx) - net_change)
        if diff > RECONCILIATION_TOLERANCE:
            errors.append(f"{period} cash flow reconciliation differs by {diff}")

    errors.extend(quarterly_sum_errors(conn, ticker))

    if errors:
        raise DataHealthError("Data health check failed before commit: " + "; ".join(errors[:20]))


def quarterly_sum_errors(conn: sqlite3.Connection, ticker: str) -> list[str]:
    errors: list[str] = []
    for field in sorted(FLOW_RECONCILIATION_FIELDS):
        for year, annual_value, quarter_count, quarter_sum in conn.execute(
            """
            SELECT a.year, a.value, COUNT(q.value), SUM(q.value)
            FROM raw_annual a
            LEFT JOIN raw_quarterly q
              ON q.ticker = a.ticker
             AND q.field = a.field
             AND q.period IN (
                CAST(a.year AS TEXT) || 'Q1',
                CAST(a.year AS TEXT) || 'Q2',
                CAST(a.year AS TEXT) || 'Q3',
                CAST(a.year AS TEXT) || 'Q4'
             )
            WHERE a.ticker = ? AND a.field = ?
            GROUP BY a.year, a.value
            """,
            (ticker, field),
        ):
            if annual_value is None or quarter_count != 4 or quarter_sum is None:
                continue
            diff = abs(annual_value - quarter_sum)
            if diff > RECONCILIATION_TOLERANCE:
                errors.append(f"{year} {field} quarterly sum differs from annual by {diff}")
    return errors


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



