from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from src.core_metrics_overview import build_core_metrics_overview, write_core_metrics_overview


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
    return db_path


def _metric(payload: dict, key: str) -> dict:
    return next(row for row in payload["rows"] if row["key"] == key)


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
    assert "35.0%" in md
    assert "不含预测、估值或分析判断" in md

    csv_text = paths["csv"].read_text(encoding="utf-8-sig")
    assert "revenue_yoy" in csv_text
    assert "0.2" in csv_text
