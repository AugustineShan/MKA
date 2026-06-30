from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from src.audit_data_toolkit import (
    CompanyHistory,
    annual_report_chunks,
    build_evidence_pack,
    fetch_tushare_auxiliary,
    load_company_history,
)
from src.audit_engine import compute_flags, pattern_tags, run_audit


FIELDS = [
    "revenue",
    "oper_cost",
    "accounts_receiv",
    "inventories",
    "total_assets",
    "total_cur_assets",
    "fix_assets",
    "lt_eqt_invest",
    "oth_eq_invest",
    "oth_illiq_fin_assets",
    "total_liab",
    "total_cur_liab",
    "undistr_porfit",
    "total_hldr_eqy_inc_min_int",
    "operate_profit",
    "fin_exp",
    "n_income",
    "n_income_attr_p",
    "n_cashflow_act",
    "n_cashflow_inv_act",
    "depr_fa_coga_dpba",
    "sell_exp",
    "admin_exp",
    "c_fr_sale_sg",
    "money_cap",
    "st_borr",
    "lt_borr",
    "bond_payable",
    "fin_exp_int_exp",
    "cip",
    "goodwill",
    "oth_receiv",
    "prepayment",
    "contract_liab",
    "adv_receipts",
]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _row(period: str, **overrides: float) -> dict:
    base = {
        "period": period,
        "revenue": 1000.0,
        "oper_cost": 650.0,
        "accounts_receiv": 100.0,
        "inventories": 120.0,
        "total_assets": 1000.0,
        "total_cur_assets": 450.0,
        "fix_assets": 220.0,
        "lt_eqt_invest": 30.0,
        "oth_eq_invest": 20.0,
        "oth_illiq_fin_assets": 10.0,
        "total_liab": 450.0,
        "total_cur_liab": 250.0,
        "undistr_porfit": 120.0,
        "total_hldr_eqy_inc_min_int": 550.0,
        "operate_profit": 100.0,
        "fin_exp": 10.0,
        "n_income": 80.0,
        "n_income_attr_p": 80.0,
        "n_cashflow_act": 90.0,
        "n_cashflow_inv_act": -30.0,
        "depr_fa_coga_dpba": 30.0,
        "sell_exp": 80.0,
        "admin_exp": 50.0,
        "c_fr_sale_sg": 980.0,
        "money_cap": 80.0,
        "st_borr": 60.0,
        "lt_borr": 80.0,
        "bond_payable": 0.0,
        "fin_exp_int_exp": 4.0,
        "cip": 20.0,
        "goodwill": 20.0,
        "oth_receiv": 20.0,
        "prepayment": 30.0,
        "contract_liab": 180.0,
        "adv_receipts": 0.0,
    }
    base.update(overrides)
    return base


def _history(
    rows: list[dict],
    company_dir: Path | None = None,
    *,
    industry: str = "general",
    quarterly: list[dict] | None = None,
) -> CompanyHistory:
    company_dir = company_dir or Path("D:/MKA/companies/测试_000001")
    return CompanyHistory(
        ticker="000001.SZ",
        name="测试公司",
        company_dir=company_dir,
        db_path=company_dir / "Agent" / "data.db",
        meta={"ticker": "000001.SZ", "name": "测试公司"},
        annual=rows,
        quarterly=quarterly or [],
        industry=industry,
    )


def _make_company_db(tmp_path: Path, rows: list[dict]) -> Path:
    company_dir = tmp_path / "companies" / "测试公司_000001"
    agent_dir = company_dir / "Agent"
    agent_dir.mkdir(parents=True)
    db_path = agent_dir / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [("ticker", "000001.SZ"), ("name", "测试公司")],
        )
        cols = ["period TEXT PRIMARY KEY", *[f"{_quote(field)} REAL" for field in FIELDS]]
        conn.execute(f"CREATE TABLE clean_annual ({', '.join(cols)})")
        conn.execute(f"CREATE TABLE clean_quarterly ({', '.join(cols)})")
        insert_cols = ", ".join(["period", *[_quote(field) for field in FIELDS]])
        placeholders = ", ".join(["?"] * (len(FIELDS) + 1))
        values = [tuple(row.get(field) for field in ["period", *FIELDS]) for row in rows]
        conn.executemany(f"INSERT INTO clean_annual ({insert_cols}) VALUES ({placeholders})", values)
    return company_dir


def test_compute_flags_detects_core_red_flags():
    rows = [
        _row("2021", revenue=900, n_income=50, n_cashflow_act=120, contract_liab=300, cip=120, fix_assets=300),
        _row("2022", revenue=1000, n_income=70, n_cashflow_act=100, contract_liab=240, cip=130, fix_assets=320),
        _row("2023", revenue=1100, n_income=90, n_cashflow_act=80, contract_liab=180, cip=140, fix_assets=330),
        _row("2024", revenue=1200, n_income=120, n_cashflow_act=60, contract_liab=120, cip=150, fix_assets=340),
        _row(
            "2025",
            revenue=1300,
            accounts_receiv=220,
            inventories=400,
            n_income=150,
            n_cashflow_act=20,
            contract_liab=80,
            money_cap=350,
            st_borr=180,
            lt_borr=150,
            fin_exp_int_exp=1.0,
            cip=160,
            fix_assets=350,
        ),
    ]

    flags = {flag.rule_id: flag for flag in compute_flags(_history(rows))}

    assert flags["CFO_NI_DIVERGENCE"].severity == "HIGH"
    assert flags["CONTRACT_LIABILITY_DECLINE"].severity == "CRITICAL"
    assert flags["INVENTORY_REVENUE_RATIO_HIGH"].severity == "HIGH"
    assert flags["DEPOSIT_LOAN_MISMATCH"].severity == "HIGH"
    assert flags["CIP_NOT_TRANSFERRING"].severity in {"MEDIUM", "HIGH"}


def test_ar_rule_uses_ar_to_revenue_when_revenue_is_not_growing():
    rows = [
        _row("2024", revenue=1000, accounts_receiv=300),
        _row("2025", revenue=900, accounts_receiv=200),
    ]

    flags = {flag.rule_id for flag in compute_flags(_history(rows))}

    assert "AR_REVENUE_RATIO_HIGH" not in flags


def test_inventory_rule_uses_ratio_change_when_revenue_growth_is_tiny():
    normal_rows = [
        _row("2024", revenue=1000, inventories=100),
        _row("2025", revenue=1010, inventories=101),
    ]
    expansion_rows = [
        _row("2024", revenue=1000, inventories=100),
        _row("2025", revenue=1010, inventories=130),
    ]

    normal_flags = {flag.rule_id for flag in compute_flags(_history(normal_rows))}
    expansion_flags = {flag.rule_id: flag for flag in compute_flags(_history(expansion_rows))}

    assert "INVENTORY_REVENUE_RATIO_HIGH" not in normal_flags
    assert expansion_flags["INVENTORY_REVENUE_RATIO_HIGH"].severity == "MEDIUM"
    assert "inventory/revenue ratio growth" in expansion_flags["INVENTORY_REVENUE_RATIO_HIGH"].evidence_text


def test_selling_expense_rule_uses_ratio_change_when_revenue_growth_is_tiny():
    normal_rows = [
        _row("2024", revenue=1000, sell_exp=100),
        _row("2025", revenue=1010, sell_exp=102),
    ]
    expansion_rows = [
        _row("2024", revenue=1000, sell_exp=100),
        _row("2025", revenue=1010, sell_exp=140),
    ]

    normal_flags = {flag.rule_id for flag in compute_flags(_history(normal_rows))}
    expansion_flags = {flag.rule_id: flag for flag in compute_flags(_history(expansion_rows))}

    assert "SELLING_EXPENSE_INEFFICIENCY" not in normal_flags
    assert expansion_flags["SELLING_EXPENSE_INEFFICIENCY"].severity == "HIGH"
    assert "selling expense/revenue ratio growth" in expansion_flags["SELLING_EXPENSE_INEFFICIENCY"].evidence_text


def test_dairy_q4_seasonality_does_not_flag_normal_q4_mix():
    quarterly = []
    for year in range(2021, 2025):
        quarterly.extend(
            [
                _row(f"{year}Q1", revenue=230),
                _row(f"{year}Q2", revenue=240),
                _row(f"{year}Q3", revenue=230),
                _row(f"{year}Q4", revenue=300),
            ]
        )

    flags = {
        flag.rule_id
        for flag in compute_flags(
            _history([_row("2023"), _row("2024")], industry="dairy", quarterly=quarterly)
        )
    }

    assert "Q4_REVENUE_ANOMALY" not in flags


def test_pattern_tags_require_multi_flag_confirmation():
    assert "CASH_FABRICATION" not in pattern_tags(
        [{"rule_id": "DEPOSIT_LOAN_MISMATCH", "severity": "HIGH"}]
    )
    assert "CASH_FABRICATION" in pattern_tags(
        [
            {"rule_id": "DEPOSIT_LOAN_MISMATCH", "severity": "HIGH"},
            {"rule_id": "CFO_NI_DIVERGENCE", "severity": "HIGH"},
        ]
    )
    assert "ASSET_HOLE" not in pattern_tags([{"rule_id": "GOODWILL_HIGH", "severity": "HIGH"}])
    assert "ASSET_HOLE" in pattern_tags(
        [
            {"rule_id": "GOODWILL_HIGH", "severity": "HIGH"},
            {"rule_id": "CIP_NOT_TRANSFERRING", "severity": "MEDIUM"},
        ]
    )
    assert "BIG_BATH_OR_CUTOFF" not in pattern_tags(
        [{"rule_id": "Q4_REVENUE_ANOMALY", "severity": "HIGH"}]
    )
    assert "BIG_BATH_OR_CUTOFF" in pattern_tags(
        [
            {"rule_id": "Q4_REVENUE_ANOMALY", "severity": "HIGH"},
            {"rule_id": "GROSS_MARGIN_DEVIATION", "severity": "MEDIUM"},
        ]
    )


def test_evidence_pack_includes_growth_cash_consumption_playbook():
    history = _history(
        [
            _row("2024", revenue=1000, accounts_receiv=100, n_income=80, n_cashflow_act=90),
            _row("2025", revenue=1400, accounts_receiv=260, n_income=100, n_cashflow_act=-20),
        ],
        industry="consumer_electronics",
    )
    flags = [flag.to_dict() for flag in compute_flags(history)]

    pack = build_evidence_pack(history, flags, include_tushare=False)

    assert any(
        review["playbook_id"] == "DSRI_HIGH_GROWTH_CASH_CONSUMPTION"
        for review in pack["layer2_playbook_reviews"]
    )


def test_load_company_history_reads_clean_tables(tmp_path: Path):
    company_dir = _make_company_db(tmp_path, [_row("2024"), _row("2025", revenue=1200)])

    history = load_company_history(company_dir)

    assert history.ticker == "000001.SZ"
    assert history.name == "测试公司"
    assert [row["period"] for row in history.annual] == ["2024", "2025"]
    assert history.annual[-1]["revenue"] == 1200.0


def test_annual_report_chunks_returns_line_windows(tmp_path: Path):
    company_dir = tmp_path / "companies" / "测试公司_000001"
    annual_dir = company_dir / "公告" / "年报"
    annual_dir.mkdir(parents=True)
    report = annual_dir / "2025_年度报告.md"
    report.write_text("\n".join(["前文"] * 5 + ["本公司收入确认政策如下"] + ["后文"] * 5), encoding="utf-8")

    chunks = annual_report_chunks(company_dir, "2025", "revenue_recognition")

    assert chunks
    assert chunks[0]["keyword"] == "收入确认"
    assert "收入确认政策" in chunks[0]["text"]
    assert chunks[0]["start_line"] <= 6 <= chunks[0]["end_line"]


def test_fetch_tushare_auxiliary_accepts_fake_client(tmp_path: Path):
    class FakePro:
        def fina_indicator(self, **kwargs):
            return pd.DataFrame([{"ts_code": kwargs["ts_code"], "roe": 0.12}])

        def fina_audit(self, **kwargs):
            return pd.DataFrame([{"ts_code": kwargs["ts_code"], "audit_result": "标准无保留意见"}])

        def stk_managers(self, **kwargs):
            return pd.DataFrame([{"ts_code": kwargs["ts_code"], "name": "张三"}])

        def query(self, endpoint, **kwargs):
            return pd.DataFrame([{"endpoint": endpoint, "ts_code": kwargs["ts_code"]}])

    company_dir = _make_company_db(tmp_path, [_row("2024"), _row("2025")])
    history = load_company_history(company_dir)

    payload = fetch_tushare_auxiliary(history, pro=FakePro(), use_cache=False)

    assert payload["status"] == "ok"
    assert payload["endpoints"]["fina_indicator"]["rows"] == 1
    assert payload["endpoints"]["fina_audit"]["rows"] == 1
    assert payload["endpoints"]["pledge_stat"]["sample"][0]["endpoint"] == "pledge_stat"


def test_run_audit_writes_global_and_company_outputs(tmp_path: Path):
    company_dir = _make_company_db(tmp_path, [_row("2024"), _row("2025", revenue=1200)])

    result = run_audit(
        str(company_dir),
        with_evidence=True,
        include_tushare=False,
        output_root=tmp_path / "audit_runs",
        run_id="test-run",
    )

    output_dir = Path(result.output_dir)
    assert (output_dir / "flags_matrix.yaml").exists()
    assert (output_dir / "risk_ranking.md").exists()
    assert (output_dir / "run_manifest.json").exists()
    evidence = company_dir / "Agent" / "audit" / "evidence_pack_latest.json"
    assert evidence.exists()
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["verdict"]["status"] == "not_run"
