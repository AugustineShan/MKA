from __future__ import annotations

import csv
import json
import math
from io import StringIO
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src import app_config
from src.workbench import app
from src.workbench import _reverse_dcf_default_segments


def _write_csv(path: Path, rows: list[dict[str, float | int]]) -> None:
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8")


def _summary_from_rows(
    dcf_rows: list[dict[str, float | int]],
    *,
    wacc: float,
    terminal_growth: float,
    terminal_capex_da_ratio: float,
    net_debt: float,
    total_shares: float,
) -> dict[str, float | str | int | list[dict[str, str]]]:
    years = len(dcf_rows)
    pv_fcff = sum(float(row["fcff"]) / ((1 + wacc) ** idx) for idx, row in enumerate(dcf_rows, start=1))
    last = dcf_rows[-1]
    terminal_fcff = float(last["nopat"]) + float(last["da"]) * (1 - terminal_capex_da_ratio)
    terminal_value = terminal_fcff * (1 + terminal_growth) / (wacc - terminal_growth)
    terminal_pv = terminal_value / ((1 + wacc) ** years)
    enterprise_value = pv_fcff + terminal_pv
    equity_value = enterprise_value - net_debt
    return {
        "ticker": "000001.SZ",
        "name": "Sample",
        "base_period": "2024",
        "forecast_years": years,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "terminal_capex_da_ratio": terminal_capex_da_ratio,
        "pv_fcff": pv_fcff,
        "terminal_value": terminal_value,
        "terminal_pv": terminal_pv,
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
        "equity_value": equity_value,
        "total_shares": total_shares,
        "per_share_value": equity_value / total_shares,
        "review_flags": [],
    }


def _make_reverse_company(tmp_path: Path, *, include_forecast: bool = True, include_market: bool = True) -> tuple[Path, str]:
    companies_root = tmp_path / "companies"
    company_id = "Sample_000001"
    company_dir = companies_root / company_id
    forecast_dir = company_dir / "Agent" / "forecast"
    modelking_dir = company_dir / "Agent" / ".modelking"
    forecast_dir.mkdir(parents=True)
    modelking_dir.mkdir(parents=True)

    revenue_rows = [
        {"period": 2025, "revenue": 110.0},
        {"period": 2026, "revenue": 121.0},
        {"period": 2027, "revenue": 133.1},
    ]
    dcf_rows = [
        {"period": 2025, "fcff": 11.0, "discount_factor": 0.0, "pv_fcff": 0.0, "nopat": 16.5, "da": 5.5, "capex": 7.0, "delta_nwc": 4.0},
        {"period": 2026, "fcff": 12.1, "discount_factor": 0.0, "pv_fcff": 0.0, "nopat": 18.15, "da": 6.05, "capex": 7.7, "delta_nwc": 4.4},
        {"period": 2027, "fcff": 13.31, "discount_factor": 0.0, "pv_fcff": 0.0, "nopat": 19.965, "da": 6.655, "capex": 8.47, "delta_nwc": 4.84},
    ]
    summary = _summary_from_rows(
        dcf_rows,
        wacc=0.08,
        terminal_growth=0.025,
        terminal_capex_da_ratio=1.0,
        net_debt=100.0,
        total_shares=10.0,
    )
    if include_forecast:
        _write_csv(forecast_dir / "forecast_is.csv", revenue_rows)
        _write_csv(forecast_dir / "dcf_detail.csv", dcf_rows)
        (forecast_dir / "dcf_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    derived = {
        "schema_version": 1,
        "annual": {
            "2024": {
                "ebit": 15.0,
                "effective_tax_rate": 0.0,
            }
        },
    }
    if include_market:
        derived["market_snapshot"] = {
            "trade_date": "20260623",
            "close": 80.0,
            "total_shares": 10.0,
            "total_mv": 800.0,
        }
    (forecast_dir / "derived_metrics.json").write_text(json.dumps(derived), encoding="utf-8")

    params: dict[str, object] = {
        "version": 2,
        "ticker": "000001.SZ",
        "name": "Sample",
        "base_period": "2024",
        "model": {
            "forecast_years": {"value": 3},
            "revenue_yoy": {"value": [0.10, 0.10, 0.10]},
            "wacc": {"value": 0.08},
            "terminal_growth": {"value": 0.025},
            "terminal_capex_da_ratio": {"value": 1.0},
        },
        "market": {
            "total_shares": {"value": 10.0},
            "net_debt": {"value": 100.0},
        },
        "income": {"revenue": {"value": 100.0}},
    }
    (modelking_dir / "forecast_params.yaml").write_text(yaml.safe_dump(params), encoding="utf-8")
    return companies_root, company_id


def _client_for(companies_root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app_config, "get_companies_dir", lambda: companies_root)
    return TestClient(app)


def test_reverse_dcf_base_endpoint_returns_market_and_yearly_pack(tmp_path: Path, monkeypatch):
    companies_root, company_id = _make_reverse_company(tmp_path)
    client = _client_for(companies_root, monkeypatch)

    response = client.get(f"/api/companies/{company_id}/reverse-dcf-base")

    assert response.status_code == 200
    pack = response.json()
    assert pack["schema_version"] == 1
    assert pack["company"]["id"] == company_id
    assert pack["defaults"]["n1"] == 1
    assert pack["defaults"]["n2"] == 2
    assert pack["defaults"]["wacc"] == 0.08
    assert pack["market"]["market_cap"] == 800.0
    assert pack["market"]["target_enterprise_value"] == 900.0
    assert pack["base_model"]["base_revenue"] == 100.0
    assert pack["base_model"]["base_nopat"] == 15.0
    assert pack["base_model"]["growth_metric"] == "nopat"
    assert pack["base_model"]["yaml1_revenue_yoy"] == [0.10, 0.10, 0.10]
    assert all(math.isclose(value, 0.10) for value in pack["base_model"]["current_model_profit_yoy"])
    assert len(pack["yearly"]) == 3
    assert math.isclose(pack["yearly"][0]["fcff_margin"], 0.10)
    assert math.isclose(pack["yearly"][0]["fcff_to_nopat"], 11.0 / 16.5)
    assert math.isclose(pack["yearly"][0]["terminal_fcff_to_nopat"], 1.0)


def test_reverse_dcf_base_pack_reprices_current_profit_path(tmp_path: Path, monkeypatch):
    companies_root, company_id = _make_reverse_company(tmp_path)
    client = _client_for(companies_root, monkeypatch)

    pack = client.get(f"/api/companies/{company_id}/reverse-dcf-base").json()
    wacc = pack["defaults"]["wacc"]
    terminal_growth = pack["defaults"]["terminal_growth"]
    nopat = pack["base_model"]["base_nopat"]
    pv_fcff = 0.0
    for index, year in enumerate(pack["yearly"], start=1):
        nopat *= 1 + pack["base_model"]["current_model_profit_yoy"][index - 1]
        pv_fcff += nopat * year["fcff_to_nopat"] / ((1 + wacc) ** index)
    terminal_fcff = nopat * pack["yearly"][-1]["terminal_fcff_to_nopat"]
    terminal_pv = terminal_fcff * (1 + terminal_growth) / (wacc - terminal_growth) / ((1 + wacc) ** len(pack["yearly"]))

    assert math.isclose(
        pv_fcff + terminal_pv,
        pack["base_model"]["current_equity_value"] + pack["market"]["net_debt"],
    )


def test_reverse_dcf_base_endpoint_rejects_missing_forecast(tmp_path: Path, monkeypatch):
    companies_root, company_id = _make_reverse_company(tmp_path, include_forecast=False)
    client = _client_for(companies_root, monkeypatch)

    response = client.get(f"/api/companies/{company_id}/reverse-dcf-base")

    assert response.status_code == 400
    assert "Run forecast first" in response.text


def test_reverse_dcf_base_endpoint_rejects_missing_market_cap(tmp_path: Path, monkeypatch):
    companies_root, company_id = _make_reverse_company(tmp_path, include_market=False)
    client = _client_for(companies_root, monkeypatch)

    response = client.get(f"/api/companies/{company_id}/reverse-dcf-base")

    assert response.status_code == 400
    assert "Market cap is missing" in response.text


def test_reverse_dcf_default_segments_derives_from_terminal_structure():
    # n1 = explicit_end - base_period, n2 = fade_to_year - explicit_end
    # 伊利-like: 3 explicit (2026-2028) + 5 fade (2029-2033) = 8 forecast years
    assert _reverse_dcf_default_segments(8, "2025", 2028, 2033) == (3, 5)
    # 4 explicit (2026-2029) + 4 fade (2030-2033) = 8 forecast years
    assert _reverse_dcf_default_segments(8, "2025", 2029, 2033) == (4, 4)
    # 2 explicit + 3 fade = 5 forecast years
    assert _reverse_dcf_default_segments(5, "2024", 2026, 2029) == (2, 3)


def test_reverse_dcf_default_segments_fallback_when_terminal_absent():
    # No terminal info → fall back to 4 explicit / 5 mid, but capped so n1+n2 <= forecast_years
    # (the old hardcoded 4+5=9 would exceed an 8-year forecast and make g2 null).
    assert _reverse_dcf_default_segments(8, "2025", None, None) == (3, 5)
    assert _reverse_dcf_default_segments(9, "2025", None, None) == (4, 5)
    assert _reverse_dcf_default_segments(3, "2024", None, None) == (1, 2)


def test_reverse_dcf_default_segments_handles_bad_terminal_values():
    # fade_to_year not greater than explicit_end → fall back
    assert _reverse_dcf_default_segments(8, "2025", 2028, 2028) == (3, 5)
    # non-numeric terminal values → fall back
    assert _reverse_dcf_default_segments(8, "2025", "n/a", None) == (3, 5)
    # n1+n2 would exceed forecast_years → fall back
    assert _reverse_dcf_default_segments(6, "2025", 2028, 2033) == (1, 5)

