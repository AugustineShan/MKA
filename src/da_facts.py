from __future__ import annotations
import re
from typing import Any

from src.annual_report_utils import find_line, compact_window, find_all_lines, call_llm

PPE_DETAIL_FIELDS = ("gross", "accum_dep", "impairment", "net",
                     "period_increase", "period_decrease", "period_dep")

# 附注/政策章节标题行:"N、固定资产" / "N、在建工程" / "N、无形资产"。
# N 是附注或政策编号,跨公司会变,故用 \d+ 不写死。标题行通常是裸行(仅"17、固定资产"+尾随空格),
# 用 ^...$ 锁死整行,排除正文里"与固定资产相关"这类散文提及。
_NOTE_TITLE_RE = re.compile(r"^\s*\d+、(固定资产|在建工程|无形资产)\s*$")

def locate_note_sections(lines: list[str]) -> dict[str, dict]:
    """定位固定资产/无形资产/在建工程附注 + 会计政策年限残值率表。

    返回 {section_key: {"start_line","end_line","text"}}。section_key:
      ppe_policy / intangible_policy       — 会计政策段(折旧/摊销年限残值率表)
      ppe_detail / cip_detail / intangible_detail — 附注明细段(账面原值/累计折旧/增减变动)
    """
    sections: dict[str, dict] = {}

    # 会计政策段 + 附注明细段共用标题形 "N、固定资产"。年报里同一标题通常出现两次:
    #   ① 会计政策段(在"重要会计政策及会计估计"章,含折旧年限/残值率表)
    #   ② 附注明细段(在"财务报表附注"章,含账面原值/累计折旧/增减变动表)
    # 政策段在前、明细段在后,故 first hit = policy,last hit = detail。
    label_map = [("固定资产", "ppe_policy", "ppe_detail"),
                 ("在建工程", None, "cip_detail"),
                 ("无形资产", "intangible_policy", "intangible_detail")]
    for label, pol_key, det_key in label_map:
        hits = [i for i, ln in enumerate(lines) if _NOTE_TITLE_RE.match(ln) and label in ln]
        if not hits:
            # 回退:用 find_all_lines 取所有含 label 的行(含散文提及),选中位数附近窗口。
            # 兜底通道,保证 locate 不静默返回空(下游按 section 缺失走 missing_flag)。
            all_hits = find_all_lines(lines, [label])
            if all_hits:
                mid = all_hits[len(all_hits) // 2]
                if det_key:
                    sections[det_key] = compact_window(lines, mid, before=5, after=120)
                if pol_key and pol_key not in sections:
                    sections[pol_key] = compact_window(lines, mid, before=2, after=60)
            continue
        if pol_key:
            # 政策段 = 首次命中;窗口 before=2 含标题行,after=60 覆盖整张年限残值率表
            sections[pol_key] = compact_window(lines, hits[0], before=2, after=60)
        if det_key:
            # 明细段 = 末次命中;after=120 覆盖账面原值/累计折旧/增减变动/减值准备多张子表
            sections[det_key] = compact_window(lines, hits[-1], before=5, after=120)
    return sections

def extract_note(note_type: str, window_text: str, year: int,
                 allowed_fields: set[str]) -> dict[str, Any]:
    """LLM 从年报附注片段提取结构化数据,带 schema 守卫剥掉幻觉字段。

    note_type: ppe_detail / cip_detail / intangible_detail / ppe_policy / intangible_policy
    allowed_fields: 允许输出的数值字段集合(不含 name);schema 外字段一律删除。
    返回 {"categories": [{"name": str, **{f: float|null}}]} 或 {"error": str, "categories": []}。
    """
    schema_hint = {"categories": [{"name": str, **{f: float for f in allowed_fields}}]}
    messages = [{
        "role": "user",
        "content": f"从年报附注提取{note_type}(年份{year})。只填表不推算,抽不到留 null。"
                   f"严格按 schema:{schema_hint}。不要输出 schema 外字段。附注片段:\n{window_text}"
    }]
    raw = call_llm(messages)
    if raw.get("error"):
        return {"error": raw["error"], "categories": []}
    # 防脏守卫:剥掉 LLM 编造的 schema 外字段(保留 name + allowed_fields 内字段)
    for cat in raw.get("categories", []):
        for k in list(cat.keys()):
            if k != "name" and k not in allowed_fields:
                del cat[k]
    return raw

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
