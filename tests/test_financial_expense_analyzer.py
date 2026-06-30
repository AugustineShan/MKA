"""Tests for src.financial_expense_analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import copy_fixture_company
import src.financial_expense_analyzer as fea
from src import defaults_gen
from src.company_paths import db_path, financial_expense_path, recon_dir


def _copy_new_hope_dairy(tmp_path: Path) -> Path:
    # Frozen snapshot incl. 公告/年报/2025_年度报告.md note stub (see tests/conftest.py).
    return copy_fixture_company(tmp_path)


def _mock_llm_response() -> dict:
    return {
        "components": {
            "interest_expense_gross": 124.15265472,
            "capitalized_interest": 14.06033307,
            "interest_subsidy": 3.8242,
            "interest_income": 7.65824373,
            "other_non_interest": 2.35298593,
        },
        "confidence": "high",
        "notes": "mock",
    }


def test_analyze_all_periods_writes_yaml_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    path = fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)
    assert path == financial_expense_path(company_dir)
    assert path.exists()

    archive = fea.load_financial_expense_yaml(company_dir)
    assert archive is not None
    assert archive["version"] == fea.EVIDENCE_VERSION
    assert archive["analyzer_version"] == fea.EVIDENCE_VERSION
    assert archive["ticker"] == "002946.SZ"
    assert "periods" in archive

    periods = archive["periods"]
    assert "2024" in periods
    latest = periods["2024"]
    assert latest["report_year"] == "2025"
    assert latest["target_column"] == "2024年（2025年报上期列）"
    assert "avg_interest_bearing_debt" in latest["anchors"]
    assert latest["status"] == "approved"
    assert latest["confidence"] == "high"
    assert latest["checks"]["basis_check"]["detected"] == "net_of_capitalized_and_subsidy"
    assert latest["components"]["interest_subsidy"] == pytest.approx(3.8242, abs=0.01)


def test_defaults_gen_overrides_financial_expense_from_yaml_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)

    defaults = defaults_gen.build_defaults(db_path(company_dir), ticker="002946.SZ")
    fin_exp = defaults["income"]["financial_expense"]
    assert fin_exp["interest_expense_rate"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["cash_interest_rate"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["other_fin_exp_abs"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_interest_expense"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_interest_income"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_fin_exp"]["source"] == "annual_report.fin_exp_note"
    assert fin_exp["base_fin_exp"]["value"] == pytest.approx(100.96, abs=0.01)
    assert fin_exp["interest_expense_rate"]["method"] == "annual_report_note_average_balance"

    assert fin_exp["interest_expense_rate"]["value"] == pytest.approx(0.032117, abs=1e-4)
    assert fin_exp["other_fin_exp_abs"]["value"] == pytest.approx(-1.47, abs=0.01)


def test_defaults_gen_keeps_mechanical_values_when_no_approved_period(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    # All periods fallback because confidence is low.
    monkeypatch.setattr(
        fea,
        "call_llm",
        lambda _messages: {**_mock_llm_response(), "confidence": "low"},
    )

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)

    defaults = defaults_gen.build_defaults(db_path(company_dir), ticker="002946.SZ")
    fin_exp = defaults["income"]["financial_expense"]
    assert fin_exp["interest_expense_rate"]["source"] == "clean_annual.5y_median.fin_exp_int_exp / avg_interest_bearing_debt"
    assert fin_exp["interest_expense_rate"]["method"] == "median_recent_5y_positive_samples_avg_interest_bearing_debt"
    assert fin_exp["other_fin_exp_abs"]["source"] == "clean_annual.5y_median.fin_exp - fin_exp_int_exp + fin_exp_int_inc"
    assert any(flag["code"] == "financial_expense_evidence_failed" for flag in defaults["review_flags"])


def test_analyze_all_periods_is_idempotent(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    path1 = fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)
    mtime1 = path1.stat().st_mtime
    path2 = fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=False)
    assert path1 == path2
    assert path2.stat().st_mtime == mtime1


def test_analyze_latest_only_writes_debug_evidence(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    monkeypatch.setattr(fea, "call_llm", lambda _messages: _mock_llm_response())

    path = fea.analyze("002946.SZ", company_dir=company_dir, force=True)
    assert path == recon_dir(company_dir) / "financial_expense_detail_latest.json"
    evidence = fea.load_evidence(company_dir)
    assert evidence is not None
    assert evidence["base_period"] == "2024"
    assert evidence["target_column"] == "2024年（2025年报上期列）"
    assert evidence["status"] == "approved"


def test_defaults_gen_dividend_payout_uses_cashflow_net_lagged_policy(tmp_path):
    company_dir = _copy_new_hope_dairy(tmp_path)

    defaults = defaults_gen.build_defaults(db_path(company_dir), ticker="002946.SZ")
    payout = defaults["balance_sheet"]["dividend_payout"]

    assert payout["value"] == pytest.approx(0.176525, abs=1e-6)
    assert payout["value"] > 0
    assert "c_pay_dist_dpcp_int_exp" in payout["source"]
    assert "distr_profit_shrhder" not in payout["source"]
    assert payout["method"] == "median_recent_3y_lagged_cash_payout_net_of_interest_and_minority_dividend"
    assert payout["sample_periods"] == ["2022", "2023", "2024"]


def test_analyze_period_prefers_current_year_current_column(tmp_path, monkeypatch):
    company_dir = tmp_path / "company"
    company_dir.mkdir()
    captured: list[list[dict[str, str]]] = []

    def fake_annual_markdown_path(_company_dir: Path, year: str) -> Path | None:
        return tmp_path / f"{year}.md" if year == "2025" else None

    def fake_read_md_lines(_path: Path) -> list[str]:
        # 逐行格式，模拟真实 PyMuPDF MD 输出（每值一行）。
        return [
            "44、财务费用",
            "项目",
            "本期发生额",
            "上期发生额",
            "利息支出",
            "130,000,000.00",
            "124,152,654.72",
            "减：资本化的利息支出",
            "-15,000,000.00",
            "-14,060,333.07",
            "利息收入",
            "-8,000,000.00",
            "-7,658,243.73",
            "其他",
            "2,500,000.00",
            "2,352,985.93",
        ]

    def fake_call_llm(messages: list[dict[str, str]]) -> dict:
        captured.append(messages)
        return _mock_llm_response()

    monkeypatch.setattr(fea, "annual_markdown_path", fake_annual_markdown_path)
    monkeypatch.setattr(fea, "read_md_lines", fake_read_md_lines)
    monkeypatch.setattr(fea, "call_llm", fake_call_llm)

    row = {
        "fin_exp": 100.96286385,
        "fin_exp_int_exp": 106.26812165,
        "fin_exp_int_inc": 7.65824373,
        "st_borr": 3106.26863603,
        "money_cap": 396.4783577,
        "revenue": 10665.42345785,
    }
    prev_row = {
        "st_borr": 3749.36274611,
        "money_cap": 439.54278948,
    }

    record = fea._analyze_period("002946.SZ", company_dir, tmp_path / "data.db", "2025", row, prev_row)

    assert record["report_year"] == "2025"
    assert record["target_column"] == "2025年（2025年报本期列）"
    assert record["status"] == "approved"
    # prompt 用年份语义指示选列，不再硬编码列头字符串
    assert "2025" in captured[0][1]["content"]
    assert "本期列" in captured[0][1]["content"]
    assert record["derived"]["interest_expense_rate"] == pytest.approx(
        record["derived"]["interest_expense"] / record["anchors"]["avg_interest_bearing_debt"]
    )


def test_analyze_all_periods_retries_current_version_fallback_archive(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    calls = {"count": 0}

    fea.write_financial_expense_yaml(
        financial_expense_path(company_dir),
        {
            "version": fea.EVIDENCE_VERSION,
            "ticker": "002946.SZ",
            "periods": {"2024": {"status": "fallback", "confidence": "low"}},
        },
    )

    def fake_call_llm(_messages):
        calls["count"] += 1
        return _mock_llm_response()

    monkeypatch.setattr(fea, "call_llm", fake_call_llm)

    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=False)

    assert calls["count"] > 0
    archive = fea.load_financial_expense_yaml(company_dir)
    assert archive is not None
    assert archive["periods"]["2024"]["status"] == "approved"


def test_run_checks_extraction_guard_forces_low_on_all_zero_components():
    """#2: fin_exp≠0 但利息支出与收入均 0 → 抽取退化，强制 low（堵 basis N/A 自信幻觉缺口）。"""
    components = {
        "interest_expense_gross": 0.0,
        "capitalized_interest": 0.0,
        "interest_subsidy": 0.0,
        "interest_income": 0.0,
        "other_non_interest": 0.0,
    }
    anchors = {
        "fin_exp": 19.9,          # 非零财务费用
        "fin_exp_int_exp": 0.0,   # TuShare 缺失 → basis N/A
        "interest_bearing_debt": 800.0,
        "money_cap": 1600.0,
        "avg_interest_bearing_debt": 800.0,
        "avg_money_cap": 1600.0,
        "revenue": 11000.0,
    }
    derived = fea._derive_params(components, anchors)
    basis = fea._detect_basis(components, anchors["fin_exp_int_exp"])
    checks = fea._run_checks(derived, components, anchors, basis, llm_confidence="high")

    # total_check 平凡通过（other 桶吸收全部 fin_exp），但退化守卫必须拦下
    assert checks["total_check"]["ok"] is True
    assert checks["extraction_check"]["ok"] is False
    assert checks["confidence"] == "low"
    assert checks["status"] == "fallback"


def test_analyze_period_distinguishes_llm_call_error_vs_fallback(tmp_path, monkeypatch):
    """#5: LLM 调用失败 → status=error（可重试）；答了但不可解析 → status=fallback。"""
    company_dir = tmp_path / "company"
    company_dir.mkdir()

    def fake_annual_markdown_path(_company_dir: Path, year: str) -> Path | None:
        return tmp_path / f"{year}.md" if year == "2025" else None

    def fake_read_md_lines(_path: Path) -> list[str]:
        return ["44、财务费用", "项目", "本期发生额", "上期发生额",
                "利息支出", "130,000,000.00", "124,152,654.72"]

    row = {"fin_exp": 100.0, "fin_exp_int_exp": 106.0, "fin_exp_int_inc": 7.0,
           "st_borr": 3100.0, "money_cap": 396.0, "revenue": 10000.0}
    prev_row = {"st_borr": 3700.0, "money_cap": 439.0}

    monkeypatch.setattr(fea, "annual_markdown_path", fake_annual_markdown_path)
    monkeypatch.setattr(fea, "read_md_lines", fake_read_md_lines)

    # LLM 调用失败（429/超时/截断）→ error
    monkeypatch.setattr(fea, "call_llm", lambda _m: {"error": "HTTP 429 rate limited", "_provider": "glm"})
    rec = fea._analyze_period("002946.SZ", company_dir, tmp_path / "data.db", "2025", row, prev_row)
    assert rec["status"] == "error"
    assert "LLM call failed" in rec["error"]

    # LLM 答了但不可解析 → fallback
    monkeypatch.setattr(fea, "call_llm", lambda _m: {"components": "not a dict", "confidence": "high"})
    rec = fea._analyze_period("002946.SZ", company_dir, tmp_path / "data.db", "2025", row, prev_row)
    assert rec["status"] == "fallback"


def test_analyze_all_periods_merges_approved_only_reruns_non_approved(tmp_path, monkeypatch):
    """#1: force=False 复用旧 archive 的 approved 记录，只重跑非 approved 期（含 error/fallback/新增）。"""
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.setattr(fea, "COMPANIES_DIR", tmp_path / "companies")
    stub_path = company_dir / "公告" / "年报" / "2025_年度报告.md"

    # 让 2023、2024 期都有「年报 MD」（都指向同一份 stub，LLM 被 mock，内容不重要）。
    def fake_annual_markdown_path(_cd: Path, year: str) -> Path | None:
        return stub_path if year in {"2024", "2025"} else None

    monkeypatch.setattr(fea, "annual_markdown_path", fake_annual_markdown_path)
    calls = {"count": 0}

    def fake_call_llm(messages):
        calls["count"] += 1
        # 从 prompt 解析该期 anchors，返回与之配平的 components（净利息支出=TuShare int_exp 过 basis，
        # 利息收入=int_inc，other 吸收剩余）——使每期都 approved，从而纯测合并/keep 逻辑。
        import re
        content = messages[1]["content"]

        def grab(key):
            m = re.search(rf'"{key}":\s*(-?[\d.eE+]+)', content)
            return float(m.group(1)) if m else 0.0

        fin_exp, int_exp, int_inc = grab("fin_exp"), grab("fin_exp_int_exp"), grab("fin_exp_int_inc")
        return {"components": {
            "interest_expense_gross": int_exp,
            "capitalized_interest": 0.0,
            "interest_subsidy": 0.0,
            "interest_income": int_inc,
            "other_non_interest": fin_exp - int_exp + int_inc,
        }, "confidence": "high", "notes": "mock-balanced"}

    monkeypatch.setattr(fea, "call_llm", fake_call_llm)

    # 首跑 force=True：2023、2024 可分析（各 1 次 LLM），其余期无 MD 不调 LLM。
    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=True)
    assert calls["count"] == 2
    archive = fea.load_financial_expense_yaml(company_dir)
    assert archive["periods"]["2023"]["status"] == "approved"
    assert archive["periods"]["2024"]["status"] == "approved"
    kept_components_2024 = archive["periods"]["2024"]["components"]

    # 全 approved → force=False 直接跳过，0 次 LLM。
    calls["count"] = 0
    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=False)
    assert calls["count"] == 0

    # 把 2023 改成 fallback、2024 保持 approved → force=False 只应重跑 2023（1 次 LLM），
    # 2024 复用旧 approved 记录（components 不变）。
    archive["periods"]["2023"] = {"status": "fallback", "confidence": "low"}
    fea.write_financial_expense_yaml(financial_expense_path(company_dir), archive)
    calls["count"] = 0
    fea.analyze_all_periods("002946.SZ", company_dir=company_dir, force=False)
    assert calls["count"] == 1
    archive2 = fea.load_financial_expense_yaml(company_dir)
    assert archive2["periods"]["2023"]["status"] == "approved"
    assert archive2["periods"]["2024"]["components"] == kept_components_2024


def test_slice_financial_expense_note_prefers_numbered_heading_over_income_statement_row():
    """回归：利润表里「财务费用」行后跟附注索引标签（如「七．65」，非数字），形状上和
    「附注标题+表头」无法区分，会被误判为附注标题。切片器必须优先命中带编号前缀的
    真附注标题（「65、财务费用」），避开利润表伪标题。妙可蓝多 2016/2017/2020/2025 踩此坑。
    """
    lines = [
        "管理费用",
        "七．64 109,127,961.03",
        "63,682,002.40",
        "财务费用",        # 利润表行：裸标题
        "七．65",          # 后跟附注索引标签（非数字）→ 伪标题，须跳过
        "21,125,540.98",
        "3,667,925.92",
        "资产减值损失",
        "七．66 13,695,460.69",
        "...大量无关正文省略...",
        "64、 管理费用",
        "√适用 □不适用",
        "项目",
        "本期发生额",
        "上期发生额",
        "65、 财务费用",   # 真附注标题：带编号前缀
        "√适用 □不适用",
        "单位：元 币种：人民币",
        "项目",
        "本期发生额",
        "上期发生额",
        "利息支出",
        "33,247,744.29",
        "5,305,439.77",
        "减：利息收入",
        "-13,473,519.11",
        "-1,365,347.05",
        "汇兑损益",
        "611,575.89",
        "-357,631.21",
        "合计",
        "21,125,540.98",
        "3,667,925.92",
    ]
    note = fea._slice_financial_expense_note(lines)
    assert note is not None
    # 落点必须是带编号的真附注标题，不是利润表那行裸「财务费用」
    assert "65" in note["text"].splitlines()[5] or any(
        "65" in ln for ln in note["text"].splitlines()[:8]
    )
    # 片段必须含附注明细（利息支出/利息收入），证明切到了真附注而非利润表汇总
    assert "利息支出" in note["text"]
    assert "利息收入" in note["text"]
    # 利润表伪标题区的「资产减值损失」不应出现在附注片段里
    assert "资产减值损失" not in note["text"]
