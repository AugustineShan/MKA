import pytest
from pathlib import Path
from src.da_facts import validate_da_facts, _POLICY_NOTE_TYPES, _OPTIONAL_NOTE_TYPES


def test_validate_rejects_missing_base_year():
    facts = {"company": "新乳业_002946", "policy": {"ppe_categories": []}}
    errors = validate_da_facts(facts)
    assert any("base_year" in e for e in errors)


def test_validate_rejects_zero_fill_disguised_as_missing():
    # 补零 = 造假;期末余额为 0 必须配 missing_flag(显式 null)
    facts = {"base_year": 2024, "policy": {"ppe_categories": []},
             "ppe_detail": {"2024": {"房屋及建筑物": {"net_closing": 0.0}}}}
    errors = validate_da_facts(facts)
    assert any("net_closing" in e and "zero" in e for e in errors)


def test_validate_zero_fill_checks_bio_and_oil_gas_too():
    """零填充禁令覆盖所有 3-sub-ledger 明细(PP&E/生物/油气)。"""
    facts = {"base_year": 2024, "policy": {"ppe_categories": []},
             "prod_bio_detail": {"2024": {"奶牛": {"gross_closing": 0.0}}},
             "oil_gas_detail": {"2024": {"油气资产": {"accum_closing": 0.0}}}}
    errors = validate_da_facts(facts)
    assert any("奶牛" in e and "zero" in e for e in errors)
    assert any("油气资产" in e and "zero" in e for e in errors)


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


def test_locate_prod_bio_for_dairy():
    """乳业公司(新乳业)年报应定位到生产性生物资产政策段 + 明细段。"""
    from src.da_facts import locate_note_sections
    md = Path("companies/新乳业_002946/公告/年报/2025_年度报告.md")
    if not md.exists():
        pytest.skip("no fixture")
    lines = md.read_text(encoding="utf-8").splitlines()
    sections = locate_note_sections(lines)
    assert "prod_bio_policy" in sections   # "20、生物资产" 政策段
    assert "prod_bio_detail" in sections   # "17、生产性生物资产" 明细段


def test_locate_optional_absent_no_fallback_to_bs_lineitem():
    """可选资产(油气)只作 BS 行-item 出现、无编号附注标题 → 不回退造垃圾段(否则 LLM 全 null 误判)。

    合成一份含"油气资产"行-item 但无"N、油气资产"标题的 md,断言 oil_gas_detail 段不产生。
    """
    from src.da_facts import locate_note_sections
    md_lines = [
        "七、合并财务报表附注",
        "11、固定资产 ", "账面原值 ...",
        "17、生产性生物资产 ", "账面原值 奶牛 ...",
        "油气资产 ", "  ", "  ",          # BS 行-item,非附注标题
        "21、无形资产 ", "土地使用权 ...",
    ]
    sections = locate_note_sections(md_lines)
    assert "oil_gas_detail" not in sections   # 无编号标题 → 不回退 → 不产生段
    assert "oil_gas_policy" not in sections



def test_extract_ppe_detail_rejects_invented_field(monkeypatch):
    # LLM 可能输出 schema 外字段(幻觉),extract_note 必须剥掉
    from src.da_facts import extract_note, PPE_3SUB_FIELDS
    fake = {"categories": [{"name": "房屋及建筑物", "gross_closing": 1.0,
                            "net_closing": 0.8, "invented_field": 999}]}
    monkeypatch.setattr("src.da_facts.call_llm", lambda msgs: fake)
    result = extract_note("ppe_detail", window_text="...", year=2024)
    assert "invented_field" not in result["categories"][0]
    assert result["categories"][0]["gross_closing"] == 1.0  # schema 内字段保留
    assert result["categories"][0]["name"] == "房屋及建筑物"


def test_extract_prod_bio_detail_uses_3sub_ledger_schema(monkeypatch):
    """生物资产明细走与 PP&E 同构的 3-sub-ledger schema(不是单行)。"""
    from src.da_facts import extract_note, PPE_3SUB_FIELDS
    fake = {"categories": [{"name": "奶牛", "gross_closing": 600.0,
                            "accum_closing": 100.0, "net_closing": 500.0}]}
    monkeypatch.setattr("src.da_facts.call_llm", lambda msgs: fake)
    result = extract_note("prod_bio_detail", window_text="...", year=2025)
    cat = result["categories"][0]
    assert cat["name"] == "奶牛"
    assert "gross_closing" in cat and "accum_closing" in cat  # 3-sub-ledger 字段


def test_ppe_rollforward_closed():
    # 三本子账各自 期初+增加-减少=期末 + 净值一致 → closed
    from src.da_facts import check_ppe_rollforward
    vals = {"gross_opening": 100.0, "gross_increase": 20.0, "gross_decrease": 10.0, "gross_closing": 110.0,
            "accum_opening": 30.0, "accum_increase": 15.0, "accum_decrease": 5.0, "accum_closing": 40.0,
            "impair_opening": 0.0, "impair_increase": 0.0, "impair_decrease": 0.0, "impair_closing": 0.0,
            "net_opening": 70.0, "net_closing": 70.0}  # 110-40-0=70 ✓
    assert check_ppe_rollforward(2024, "房屋及建筑物", vals)["closed"] is True


def test_ppe_rollforward_broken_flags():
    # 净值对不上 → closed=False,残差>容差
    from src.da_facts import check_ppe_rollforward
    vals = {"gross_opening": 100.0, "gross_increase": 20.0, "gross_decrease": 10.0, "gross_closing": 110.0,
            "accum_opening": 30.0, "accum_increase": 15.0, "accum_decrease": 5.0, "accum_closing": 40.0,
            "impair_opening": 0.0, "impair_increase": 0.0, "impair_decrease": 0.0, "impair_closing": 0.0,
            "net_opening": 70.0, "net_closing": 60.0}  # 应 70,实 60
    r = check_ppe_rollforward(2024, "房屋及建筑物", vals)
    assert r["closed"] is False
    assert abs(r["net_residual"]) > 1.0


def _fake_extract(note_type, window_text, year):
    """按 note_type 返回合法 fixture(policy 带年限;detail 带闭合的 3-sub-ledger/单行)。"""
    if note_type in _POLICY_NOTE_TYPES:
        return {"categories": [{"name": "X", "life_years": [10, 20],
                                "salvage_rate": [0.03, 0.05], "annual_dep_rate": [0.05, 0.1]}]}
    if note_type in ("ppe_detail", "prod_bio_detail", "oil_gas_detail"):
        return {"categories": [{"name": "X",
            "gross_opening": 100.0, "gross_increase": 20.0, "gross_decrease": 10.0, "gross_closing": 110.0,
            "accum_opening": 30.0, "accum_increase": 15.0, "accum_decrease": 5.0, "accum_closing": 40.0,
            "impair_opening": 0.0, "impair_increase": 0.0, "impair_decrease": 0.0, "impair_closing": 0.0,
            "net_opening": 70.0, "net_closing": 70.0}]}
    # cip / intangible 单行
    return {"categories": [{"name": "X", "gross": 15.0, "accum_dep": 3.0, "net": 12.0,
                            "opening_net": 10.0, "closing_net": 12.0,
                            "period_increase": 5.0, "period_decrease": 3.0, "period_dep": 2.0}]}


def test_extract_company_facts_parallel(monkeypatch, tmp_path):
    # mock 提取+定位+年报路径,验并行编排 + merge 逻辑 + 可选类型 not_disclosed + 落盘
    from src.da_facts import extract_company_facts

    monkeypatch.setattr("src.da_facts.extract_note", _fake_extract)
    # 只返回强制类型段;生物/油气段缺席 → 可选 → not_disclosed 静默跳过
    monkeypatch.setattr("src.da_facts.locate_note_sections", lambda lines: {
        "ppe_detail": {"text": "x"}, "cip_detail": {"text": "x"},
        "intangible_detail": {"text": "x"},
        "ppe_policy": {"text": "x"}, "intangible_policy": {"text": "x"},
    })
    monkeypatch.setattr("src.da_facts.annual_markdown_path",
                        lambda cd, y: tmp_path / f"{y}_年度报告.md")
    (tmp_path / "2024_年度报告.md").write_text("固定资产\n...", encoding="utf-8")

    facts = extract_company_facts(company_dir=tmp_path, base_year=2024, years=[2024])
    assert facts["base_year"] == 2024
    # 强制 detail merge:name-keyed dict
    assert "X" in facts["ppe_detail"]["2024"]
    # 可选类型未披露 → 空 dict,不进 missing_flag,不触发 hard-stop
    assert facts["prod_bio_detail"] == {}
    assert facts["oil_gas_detail"] == {}
    assert not any(m["note_type"] in _OPTIONAL_NOTE_TYPES for m in facts["missing_flags"])
    # 落盘产物存在
    from src.company_paths import recon_dir
    out = recon_dir(tmp_path) / "da_facts_latest.json"
    assert out.exists()
