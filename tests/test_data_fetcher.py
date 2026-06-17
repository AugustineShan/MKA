"""Unit tests for data_fetcher.py helpers."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src import data_fetcher


class TestConvertValue:
    def test_amount_cny_converts_yuan_to_million(self):
        assert data_fetcher.convert_value(1_000_000, data_fetcher.UNIT_AMOUNT_CNY) == 1.0

    def test_percent_converts_to_decimal(self):
        assert data_fetcher.convert_value(15.5, data_fetcher.UNIT_PERCENT) == 0.155

    def test_share_converts_shares_to_million(self):
        assert data_fetcher.convert_value(1_000_000, data_fetcher.UNIT_SHARE) == 1.0

    def test_daily_basic_share_10k(self):
        assert data_fetcher.convert_value(100, data_fetcher.UNIT_DAILY_SHARE_10K) == 1.0

    def test_daily_basic_mv_10k_cny(self):
        assert data_fetcher.convert_value(100, data_fetcher.UNIT_DAILY_MV_10K_CNY) == 1.0

    def test_turnover_rate_converts_to_days(self):
        assert data_fetcher.convert_value(365, data_fetcher.UNIT_TURNOVER_RATE) == 1.0

    def test_turnover_rate_non_positive_returns_none(self):
        assert data_fetcher.convert_value(0, data_fetcher.UNIT_TURNOVER_RATE) is None
        assert data_fetcher.convert_value(-5, data_fetcher.UNIT_TURNOVER_RATE) is None

    def test_none_returns_none(self):
        assert data_fetcher.convert_value(None, data_fetcher.UNIT_AMOUNT_CNY) is None

    def test_nan_returns_none(self):
        assert data_fetcher.convert_value(float("nan"), data_fetcher.UNIT_AMOUNT_CNY) is None
        assert data_fetcher.convert_value(np.nan, data_fetcher.UNIT_AMOUNT_CNY) is None

    def test_ratio_and_price_unconverted(self):
        assert data_fetcher.convert_value(2.5, data_fetcher.UNIT_RATIO) == 2.5
        assert data_fetcher.convert_value(100.0, data_fetcher.UNIT_PRICE) == 100.0

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError):
            data_fetcher.convert_value(1.0, "not_a_unit")


class TestIsAuthOrPermissionError:
    def test_invalid_token(self):
        assert data_fetcher.is_auth_or_permission_error(RuntimeError("invalid token"))

    def test_permission_error(self):
        assert data_fetcher.is_auth_or_permission_error(RuntimeError("permission denied"))

    def test_other_error(self):
        assert not data_fetcher.is_auth_or_permission_error(RuntimeError("network timeout"))


class TestIsPermanentError:
    def test_invalid_parameter(self):
        assert data_fetcher.is_permanent_error(RuntimeError("参数错误"))

    def test_unknown_ts_code(self):
        assert data_fetcher.is_permanent_error(RuntimeError("ts_code不存在"))

    def test_rate_limit_is_not_permanent(self):
        assert not data_fetcher.is_permanent_error(RuntimeError("limit exceeded"))

    def test_network_timeout_is_not_permanent(self):
        assert not data_fetcher.is_permanent_error(RuntimeError("timeout"))


class TestOfficialTuShareSource:
    def test_default_tushare_url_is_official(self):
        assert data_fetcher.DEFAULT_TUSHARE_HTTP_URL == "http://api.waditu.com/dataapi"

    def test_non_official_tushare_url_is_rejected_before_sdk_import(self):
        with pytest.raises(ValueError, match="official TuShare source"):
            data_fetcher.create_tushare_client(token="fake-token", http_url="https://example.invalid")

    def test_income_report_type_2_is_not_required_for_health_check(self):
        assert data_fetcher.REQUIRED_REPORT_TYPES_BY_ENDPOINT["income"] == (
            data_fetcher.REPORT_TYPE_CONSOLIDATED,
        )

    def test_official_doc_fields_read_from_skill_export(self):
        fields = data_fetcher.official_doc_fields("income")
        assert fields["total_cogs"][0] == "float"
        assert "营业总成本" in fields["total_cogs"][1]
