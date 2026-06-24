from __future__ import annotations
from typing import Any

PPE_DETAIL_FIELDS = ("gross", "accum_dep", "impairment", "net",
                     "period_increase", "period_decrease", "period_dep")

def validate_da_facts(facts: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "base_year" not in facts:
        errors.append("base_year missing")
    ppe_detail = facts.get("ppe_detail", {})
    missing_flags = {(m["year"], m["category"], m["field"])
                     for m in facts.get("missing_flags", [])}
    for year, cats in ppe_detail.items():
        for cat, vals in cats.items():
            if not isinstance(vals, dict):
                continue
            for field in PPE_DETAIL_FIELDS:
                if field not in vals:
                    continue
                v = vals[field]
                if v == 0.0 and (year, cat, field) not in missing_flags:
                    errors.append(f"{year}.{cat}.{field}=0 without missing_flag (zero-fill forbidden)")
    return errors
