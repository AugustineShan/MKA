import json
import pytest
from pathlib import Path
from src.da_facts import validate_da_facts

def test_validate_rejects_missing_base_year():
    facts = {"company": "新乳业_002946", "policy": {"ppe_categories": []}}
    errors = validate_da_facts(facts)
    assert any("base_year" in e for e in errors)

def test_validate_rejects_zero_fill_disguised_as_missing():
    # 补零 = 造假;missing 必须显式 null
    facts = {"base_year": 2024, "policy": {"ppe_categories": []},
             "ppe_detail": {"2024": {"房屋及建筑物": {"period_dep": 0.0}}}}
    errors = validate_da_facts(facts)
    assert any("period_dep" in e and "zero" in e for e in errors)  # 0 且无 missing_flag → 报错

def test_locate_ppe_policy_section():
    from src.da_facts import locate_note_sections
    md = Path("companies/新乳业_002946/公告/年报/2024_年度报告.md")
    if not md.exists():
        pytest.skip("no fixture")
    lines = md.read_text(encoding="utf-8").splitlines()
    sections = locate_note_sections(lines)
    assert "ppe_policy" in sections
    assert "ppe_detail" in sections
    assert "cip_detail" in sections
    assert "intangible_policy" in sections

def test_extract_ppe_detail_rejects_invented_field(monkeypatch):
    # LLM 可能输出 schema 外字段(幻觉),extract_note 必须剥掉
    from src.da_facts import extract_note
    fake = {"categories": [{"name": "房屋及建筑物", "gross": 1.0, "accum_dep": 0.2,
                            "period_dep": 0.05, "invented_field": 999}]}
    monkeypatch.setattr("src.da_facts.call_llm", lambda msgs: fake)
    result = extract_note("ppe_detail", window_text="...", year=2024,
                          allowed_fields={"gross", "accum_dep", "period_dep", "net"})
    assert "invented_field" not in result["categories"][0]
    # schema 内字段保留
    assert result["categories"][0]["gross"] == 1.0
    assert result["categories"][0]["name"] == "房屋及建筑物"

def test_rollforward_closed():
    # 期初+增加-折旧-减少-减值 = 期末 → closed
    from src.da_facts import check_rollforward
    cat = {"opening_net": 100.0, "period_increase": 20.0, "period_dep": 15.0,
           "period_decrease": 5.0, "impairment": 0.0, "closing_net": 100.0}
    assert check_rollforward(2024, "房屋及建筑物", cat)["closed"] is True

def test_rollforward_broken_flags():
    # 期末对不上 → closed=False,残差>容差
    from src.da_facts import check_rollforward
    cat = {"opening_net": 100.0, "period_increase": 20.0, "period_dep": 15.0,
           "period_decrease": 5.0, "impairment": 0.0, "closing_net": 90.0}
    r = check_rollforward(2024, "房屋及建筑物", cat)
    assert r["closed"] is False
    assert abs(r["residual"]) > 1.0

def test_extract_company_facts_parallel(monkeypatch, tmp_path):
    # mock 提取+定位+年报路径,验并行编排 + merge 逻辑 + 落盘
    from src.da_facts import extract_company_facts

    def fake_extract(note_type, window_text, year, allowed_fields):
        return {"categories": [{"name": "房屋及建筑物", "gross": 1.0}]}

    monkeypatch.setattr("src.da_facts.extract_note", fake_extract)
    monkeypatch.setattr("src.da_facts.locate_note_sections",
                        lambda lines: {"ppe_detail": {"text": "x"}})
    monkeypatch.setattr("src.da_facts.annual_markdown_path",
                        lambda cd, y: tmp_path / f"{y}_年度报告.md")
    (tmp_path / "2024_年度报告.md").write_text("固定资产\n...", encoding="utf-8")

    facts = extract_company_facts(company_dir=tmp_path, base_year=2024, years=[2024])
    assert facts["base_year"] == 2024
    # merge 真发生:facts["ppe_detail"]["2024"] 非空 init dict,且 categories 塞进去了
    assert facts["ppe_detail"]["2024"]
    assert facts["ppe_detail"]["2024"]["categories"][0]["name"] == "房屋及建筑物"
    # 落盘产物存在
    from src.company_paths import recon_dir
    out = recon_dir(tmp_path) / "da_facts_latest.json"
    assert out.exists()
