import json
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
