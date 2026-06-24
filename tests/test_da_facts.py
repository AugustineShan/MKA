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
