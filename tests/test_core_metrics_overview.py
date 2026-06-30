from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from src.core_metrics_overview import _yoy, build_core_metrics_overview, write_core_metrics_overview


FIELDS = [
    "revenue",
    "total_revenue",
    "oper_cost",
    "biz_tax_surchg",
    "sell_exp",
    "admin_exp",
    "rd_exp",
    "fin_exp",
    "total_cogs",
    "assets_impair_loss",
    "income.credit_impa_loss",
    "oth_income",
    "invest_income",
    "fv_value_chg_gain",
    "asset_disp_income",
    "operate_profit",
    "non_oper_income",
    "non_oper_exp",
    "total_profit",
    "income_tax",
    "n_income",
]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _make_db(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "Agent"
    agent_dir.mkdir()
    db_path = agent_dir / "data.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [
                ("ticker", "000001.SZ"),
                ("name", "测试公司"),
                ("last_updated", "2099-01-01T00:00:00"),
                ("latest_trade_date", "20990101"),
            ],
        )
        cols = ["period TEXT PRIMARY KEY", *[f"{_quote(field)} REAL" for field in FIELDS]]
        conn.execute(f"CREATE TABLE clean_annual ({', '.join(cols)})")
        placeholders = ", ".join(["?"] * (len(FIELDS) + 1))
        insert_cols = ", ".join(["period", *[_quote(field) for field in FIELDS]])
        conn.executemany(
            f"INSERT INTO clean_annual ({insert_cols}) VALUES ({placeholders})",
            [
                (
                    "2023",
                    1000.0,
                    1000.0,
                    700.0,
                    6.0,
                    80.0,
                    50.0,
                    20.0,
                    10.0,
                    860.0,
                    -5.0,
                    -2.0,
                    3.0,
                    4.0,
                    -1.0,
                    2.0,
                    130.0,
                    5.0,
                    2.0,
                    133.0,
                    33.25,
                    100.0,
                ),
                (
                    "2024",
                    1200.0,
                    1200.0,
                    780.0,
                    8.0,
                    90.0,
                    60.0,
                    24.0,
                    15.0,
                    969.0,
                    -6.0,
                    -3.0,
                    5.0,
                    6.0,
                    1.0,
                    3.0,
                    210.0,
                    6.0,
                    4.0,
                    212.0,
                    53.0,
                    150.0,
                ),
            ],
        )
        conn.execute(f"CREATE TABLE clean_quarterly ({', '.join(cols)})")
        quarterly_rows = []
        for year in [2022, 2023, 2024, 2025]:
            for quarter in [1, 2, 3, 4]:
                period = f"{year}Q{quarter}"
                revenue = (year - 2020) * 100.0 + quarter * 10.0
                quarterly_rows.append(
                    (
                        period,
                        revenue,
                        revenue,
                        revenue * 0.60,
                        1.0,
                        revenue * 0.08,
                        revenue * 0.05,
                        revenue * 0.02,
                        revenue * 0.01,
                        revenue * 0.75,
                        -1.0,
                        -0.5,
                        1.0,
                        1.0,
                        0.0,
                        0.0,
                        revenue * 0.20,
                        1.0,
                        0.5,
                        revenue * 0.205,
                        revenue * 0.05,
                        revenue * 0.15,
                    )
                )
        conn.executemany(
            f"INSERT INTO clean_quarterly ({insert_cols}) VALUES ({placeholders})",
            quarterly_rows,
        )
    return db_path


def _metric(payload: dict, key: str) -> dict:
    return next(row for row in payload["rows"] if row["key"] == key)


def test_yoy_handles_turnaround() -> None:
    assert math.isclose(_yoy(108.0, -85.0), 193.0 / 85.0)
    assert math.isclose(_yoy(-100.0, -85.0), -15.0 / 85.0)


def test_build_core_metrics_overview_computes_profit_chain(tmp_path: Path):
    db_path = _make_db(tmp_path)

    payload = build_core_metrics_overview(db_path)

    assert payload["periods"] == ["2023", "2024"]
    assert payload["company"] == {"ticker": "000001.SZ", "name": "测试公司"}
    assert "last_updated" not in json.dumps(payload, ensure_ascii=False)
    assert _metric(payload, "revenue")["values"]["2024"] == 1200.0
    assert math.isclose(_metric(payload, "revenue_yoy")["values"]["2024"], 0.2)
    assert math.isclose(_metric(payload, "gross_margin")["values"]["2024"], 0.35)
    assert math.isclose(_metric(payload, "effective_tax_rate")["values"]["2024"], 0.25)
    assert math.isclose(_metric(payload, "n_income_yoy")["values"]["2024"], 0.5)
    assert _metric(payload, "credit_impa_loss")["values"]["2024"] == -3.0
    assert payload["source"]["tables"] == ["clean_annual", "clean_quarterly"]
    assert payload["quarterly"]["periods"] == [
        "2023Q3",
        "2023Q4",
        "2024Q1",
        "2024Q2",
        "2024Q3",
        "2024Q4",
        "2025Q1",
        "2025Q2",
        "2025Q3",
        "2025Q4",
    ]
    quarterly_revenue_yoy = next(row for row in payload["quarterly"]["rows"] if row["key"] == "revenue_yoy")
    assert math.isclose(
        quarterly_revenue_yoy["values"]["2024Q1"],
        ((2024 - 2020) * 100.0 + 10.0) / ((2023 - 2020) * 100.0 + 10.0) - 1.0,
    )


def test_write_core_metrics_overview_is_byte_stable_and_llm_readable(tmp_path: Path):
    db_path = _make_db(tmp_path)

    paths = write_core_metrics_overview(db_path)
    before = {name: path.read_bytes() for name, path in paths.items()}
    paths = write_core_metrics_overview(db_path)
    after = {name: path.read_bytes() for name, path in paths.items()}

    assert before == after
    md = paths["markdown"].read_text(encoding="utf-8")
    assert "年度核心指标速览" in md
    assert "收入同比" in md
    assert "最近10个季度核心证据" in md
    assert "季度同比按同季度上一年计算" in md
    assert "2025Q4" in md
    assert "35.0%" in md
    assert "不含预测、估值或分析判断" in md

    csv_text = paths["csv"].read_text(encoding="utf-8-sig")
    assert "revenue_yoy" in csv_text
    assert "0.2" in csv_text
