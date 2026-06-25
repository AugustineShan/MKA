from __future__ import annotations
import re
import sys
from typing import Any

from pathlib import Path

from src.annual_report_utils import (find_line, compact_window, find_all_lines,
                                     call_llm, parallel_map, annual_markdown_path, write_json,
                                     load_env, ROOT)
from src.company_paths import recon_dir

TOLERANCE_MILLION = 1.0  # roll-forward 闭合容差(百万元),与 clean.py 硬校验对齐

# ---- 按 note_type 分 schema(spec §12.1):政策段 ≠ 明细段;PPE 明细走 3-sub-ledger ----
# 政策段(会计政策年限残值率表):年限/残值率/年折旧率,均为 [下限,上限] 区间
POLICY_FIELDS = {"life_years", "salvage_rate", "annual_dep_rate"}

# PPE 明细 3-sub-ledger(对齐年报披露的三本子账 + 账面价值):
#   账面原值 / 累计折旧 / 减值准备 各 期初/增加/减少/期末;账面净值 期初/期末。
# 单行混杂 schema 会让 roll-forward identity 漏"处置转出的累计折旧/减值"→ 系统性误报,
# 故拆成三本子账,每本 期初+增加−减少=期末 是有处置也成立的精确恒等式。
PPE_3SUB_FIELDS = {
    "gross_opening", "gross_increase", "gross_decrease", "gross_closing",
    "accum_opening", "accum_increase", "accum_decrease", "accum_closing",
    "impair_opening", "impair_increase", "impair_decrease", "impair_closing",
    "net_opening", "net_closing",
}
PPE_3SUB_KEY_FIELDS = ("gross_closing", "accum_closing", "impair_closing", "net_closing",
                       "gross_increase", "accum_increase", "gross_decrease", "accum_decrease")

# CIP / 无形资产 明细:单行(各只有一本账或非消耗项)
DETAIL_FIELDS = {"gross", "accum_dep", "impairment", "net",
                 "period_increase", "period_decrease", "period_dep",
                 "opening_net", "closing_net"}
CIP_KEY_FIELDS = ("opening_net", "closing_net", "period_increase", "period_decrease")
INTANGIBLE_KEY_FIELDS = ("gross", "accum_dep", "period_dep", "period_increase")

_POLICY_NOTE_TYPES = {"ppe_policy", "intangible_policy",
                      "prod_bio_policy", "oil_gas_policy"}
_POLICY_KEY = {"ppe_policy": "ppe_categories", "intangible_policy": "intangible_categories",
               "prod_bio_policy": "prod_bio_categories", "oil_gas_policy": "oil_gas_categories"}

# 可选 note 类型(生产性生物资产/油气资产):非乳业/非油气公司不披露 → 段定位失败时
# 返回 not_disclosed 静默跳过(不进 missing_flag,不触发 sanity gate hard-stop)。
# 披露了但 LLM 抽取失败仍走 missing_flag → 真失败照样 hard-stop(不静默吞)。
_OPTIONAL_NOTE_TYPES = {"prod_bio_detail", "oil_gas_detail",
                        "prod_bio_policy", "oil_gas_policy"}

# 抽取理智闸门(spec §0.4 对偶):任一 note_type 关键字段 null 率超此阈值 → hard-stop
# (区分"数据真没有"=标 flag vs "我根本没读到"=hard-stop)
SANITY_NULL_RATE_THRESHOLD = 0.80
_SUBTOTAL_NAMES = {"合计", "总计", "小计"}

# 零填充禁令只查"绝不该为 0"的期末余额字段(原值/累计折旧/净值 closing),
# 不查 increase/decrease/impairment 这类可合理为 0 的流量项(避免合法 0 被当造假噪声)。
_PPE_ZERO_CHECK_FIELDS = ("gross_closing", "accum_closing", "net_closing")


class DaFactsExtractionError(RuntimeError):
    """抽取本身疑似失败(配置/schema/provider),不是数据缺口——禁止当事实往下传。"""


_NOTE_TITLE_RE = re.compile(
    r"^\s*\d+、(固定资产|在建工程|无形资产|生产性生物资产|生物资产|油气资产)\s*$")
# 任意"N、xxx"附注标题(用于明细段窗口找下一附注边界,跨公司通用)
_NEXT_NOTE_RE = re.compile(r"^\s*\d+、\S")

def _detail_window_after(lines: list[str], start: int, cap: int = 600) -> int:
    """明细段窗口延伸到下一附注标题(覆盖账面原值/累计折旧/减值/账面价值全部子表)。

    固定 after=120 会截断累计折旧/账面价值子表 → accum_dep/opening_net/closing_net
    抽不到(实测新乳业 2024:窗口止于 18022,账面价值在 18108)→ roll-forward 无输入。
    喂整张附注(平移 LLM 调用准则"上下文喂全,锚定完整语义块");找不到下一标题则 cap 兜底。
    """
    for j in range(start + 1, min(start + cap, len(lines))):
        if _NEXT_NOTE_RE.match(lines[j]):
            return max(50, j - start)
    return cap

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
    # 生物资产:政策段标题"N、生物资产",明细段标题"N、生产性生物资产"(含"生物资产"子串,
    # 故 label="生物资产" 两者都命中;first=policy,last=detail 仍成立——政策章在前)。
    label_map = [("固定资产", "ppe_policy", "ppe_detail"),
                 ("在建工程", None, "cip_detail"),
                 ("无形资产", "intangible_policy", "intangible_detail"),
                 ("生物资产", "prod_bio_policy", "prod_bio_detail"),
                 ("油气资产", "oil_gas_policy", "oil_gas_detail")]
    for label, pol_key, det_key in label_map:
        hits = [i for i, ln in enumerate(lines) if _NOTE_TITLE_RE.match(ln) and label in ln]
        if not hits:
            # 可选资产(生物/油气)无"N、xxx"编号标题 → 不回退,直接判未披露(not_disclosed)。
            # 否则 find_all_lines 会抓到资产负债表的"油气资产/生产性生物资产"行-item(非附注段),
            # 造出垃圾窗口 → LLM 全 null → sanity gate 误判 hard-stop。
            keys = [k for k in (pol_key, det_key) if k]
            if keys and all(k in _OPTIONAL_NOTE_TYPES for k in keys):
                continue
            # 回退:用 find_all_lines 取所有含 label 的行(含散文提及),选中位数附近窗口。
            # 兜底通道,保证 locate 不静默返回空(下游按 section 缺失走 missing_flag)。
            all_hits = find_all_lines(lines, [label])
            if all_hits:
                mid = all_hits[len(all_hits) // 2]
                if det_key:
                    sections[det_key] = compact_window(lines, mid, before=5,
                                                       after=_detail_window_after(lines, mid))
                if pol_key and pol_key not in sections:
                    sections[pol_key] = compact_window(lines, mid, before=2, after=60)
            continue
        if pol_key:
            # 政策段 = 首次命中;窗口 before=2 含标题行,after=60 覆盖整张年限残值率表
            sections[pol_key] = compact_window(lines, hits[0], before=2, after=60)
        if det_key:
            # 明细段 = 末次命中;窗口延伸到下一附注标题,覆盖三本子账 + 账面价值全部子表
            sections[det_key] = compact_window(lines, hits[-1], before=5,
                                               after=_detail_window_after(lines, hits[-1]))
    return sections

def _schema_and_fields(note_type: str) -> tuple[set[str], dict[str, Any]]:
    """按 note_type 选 allowed_fields + schema_hint。"""
    if note_type in _POLICY_NOTE_TYPES:
        hint = {"categories": [{"name": "房屋及建筑物",
                                "life_years": [10, 40], "salvage_rate": [0.03, 0.05],
                                "annual_dep_rate": [0.0238, 0.0970]}]}
        return POLICY_FIELDS, hint
    # ppe_detail / prod_bio_detail / oil_gas_detail 同走 3-sub-ledger(账面原值/累计折旧/减值/净值,
    # 年报披露结构同构),复用 PPE_3SUB_FIELDS + check_ppe_rollforward。
    if note_type in ("ppe_detail", "prod_bio_detail", "oil_gas_detail"):
        ex_name = {"ppe_detail": "房屋及建筑物",
                   "prod_bio_detail": "奶牛",
                   "oil_gas_detail": "油气资产"}[note_type]
        hint = {"categories": [{"name": ex_name, **{f: 0.0 for f in PPE_3SUB_FIELDS}}]}
        return PPE_3SUB_FIELDS, hint
    hint = {"categories": [{"name": "苏州双喜新建仓库项目", **{f: 0.0 for f in DETAIL_FIELDS}}]}
    return DETAIL_FIELDS, hint

def extract_note(note_type: str, window_text: str, year: int) -> dict[str, Any]:
    """LLM 从年报附注/政策段提取结构化数据,带 schema 守卫剥掉幻觉字段。

    ppe_detail / prod_bio_detail / oil_gas_detail 走 3-sub-ledger(三本子账各自
    期初/增加/减少/期末 + 净值期初期末,年报披露结构同构);
    cip_detail/intangible_detail 走单行;policy 走年限残值率区间。
    返回 {"categories":[{"name":.., **fields}], "_usage":..,"_model":..,"_provider":..}
    或 {"error": str, "categories": []}。
    """
    allowed_fields, schema_hint = _schema_and_fields(note_type)
    if note_type in _POLICY_NOTE_TYPES:
        bio_hint = ("只抽生产性生物资产(如奶牛)的使用寿命/残值率/年折旧率;"
                    "消耗性生物资产不折旧,忽略它。"
                    if note_type == "prod_bio_policy" else "")
        task = (f"从年报会计政策段提取{note_type}的折旧/摊销年限与残值率(年份{year})。"
                f"life_years/salvage_rate/annual_dep_rate 都是 [下限,上限] 两个数的列表(如 [10,40])。"
                f"只填表不推算,抽不到留 null。{bio_hint}"
                f"严格按 schema:{schema_hint}。不要输出 schema 外字段。"
                f"政策片段:\n{window_text}")
    elif note_type in ("ppe_detail", "prod_bio_detail", "oil_gas_detail"):
        asset_label = {"ppe_detail": "固定资产", "prod_bio_detail": "生产性生物资产",
                       "oil_gas_detail": "油气资产"}[note_type]
        task = (f"从年报{asset_label}附注变动表提取{year}数据。附注含三本子账(一、账面原值;二、累计折旧;"
                f"三、减值准备),每本有 期初余额/本期增加/本期减少/期末余额;另有四、账面价值(净值)期初/期末。"
                f"只填表不推算,抽不到留 null。字段映射:\n"
                f"  gross_* = 账面原值(期初余额/本期增加/本期减少/期末余额)\n"
                f"  accum_* = 累计折旧(期初余额/本期增加=计提/本期减少=处置转出/期末余额)\n"
                f"  impair_* = 减值准备(期初余额/本期增加=计提/本期减少=转回或处置转出/期末余额)\n"
                f"  net_opening/net_closing = 账面价值(净值)期初/期末(直接抄披露值,不推算)\n"
                f"不要输出'合计'行,不要输出 schema 外字段。严格按 schema:{schema_hint}。附注片段:\n{window_text}")
    else:  # cip_detail / intangible_detail
        transfer_hint = ("period_decrease 必须填本期转固/处置金额;确无则填 0,不得留 null。"
                         if note_type == "cip_detail" else "")
        task = (f"从年报附注变动表提取{note_type}({year})。只填表不推算,抽不到留 null。"
                f"字段:gross=期末原值,accum_dep=期末累计折旧/摊销,net=期末净值,"
                f"opening_net=期初净值,closing_net=期末净值,period_increase=本期增加,"
                f"period_decrease=本期减少{('(转固/处置)' if note_type=='cip_detail' else '(处置)')},"
                f"period_dep=本期计提折旧/摊销。{transfer_hint}"
                f"严格按 schema:{schema_hint}。不要输出'合计'行或 schema 外字段。附注片段:\n{window_text}")
    raw = call_llm([{"role": "user", "content": task}])
    if raw.get("error"):
        return {"error": raw["error"], "categories": []}
    # 防脏守卫:剥掉 LLM 编造的 schema 外字段(保留 name + allowed_fields 内字段)
    for cat in raw.get("categories", []):
        for k in list(cat.keys()):
            if k != "name" and k not in allowed_fields:
                del cat[k]
    return raw

def check_ppe_rollforward(year: int, category: str, vals: dict[str, Any]) -> dict[str, Any]:
    """PPE 3-sub-ledger 精确 roll-forward(spec §3.3 修正版)。

    每本子账 期初+增加−减少=期末,各自在有处置时也成立(处置的累计折旧/减值随之转出,
    体现在各子账的"减少"里,不再像单行净值 identity 那样漏掉);
    再加净值一致性:net_closing = gross_closing − accum_closing − impair_closing。
    closed=True 仅当三本子账都闭合且净值一致;任一关键输入缺失 → closed=None(不假装闭合)。
    """
    sub: dict[str, dict] = {}
    overall_closed = True
    verifiable = True
    for ledger in ("gross", "accum", "impair"):
        o = vals.get(f"{ledger}_opening"); i = vals.get(f"{ledger}_increase")
        d = vals.get(f"{ledger}_decrease"); c = vals.get(f"{ledger}_closing")
        if o is None or c is None:
            sub[ledger] = {"opening": o, "increase": i, "decrease": d, "closing": c,
                           "residual": None, "closed": None}
            verifiable = False
            continue
        calc = (o or 0.0) + (i or 0.0) - (d or 0.0)
        r = calc - (c or 0.0)
        closed = abs(r) < TOLERANCE_MILLION
        sub[ledger] = {"opening": o, "increase": i, "decrease": d, "closing": c,
                       "residual": r, "closed": closed}
        if not closed:
            overall_closed = False
    no = vals.get("net_opening"); nc = vals.get("net_closing")
    net_residual = None; net_closed = None
    gc = sub["gross"]["closing"]; ac = sub["accum"]["closing"]; ic = sub["impair"]["closing"]
    if nc is not None and gc is not None and ac is not None and ic is not None:
        calc_nc = (gc or 0.0) - (ac or 0.0) - (ic or 0.0)
        net_residual = calc_nc - (nc or 0.0)
        net_closed = abs(net_residual) < TOLERANCE_MILLION
        if not net_closed:
            overall_closed = False
    else:
        verifiable = False
    return {"year": year, "category": category, "sub_ledgers": sub,
            "net_opening": no, "net_closing": nc,
            "net_residual": net_residual, "net_closed": net_closed,
            "closed": overall_closed if verifiable else None}

def check_cip_rollforward(year: int, category: str, vals: dict[str, Any]) -> dict[str, Any]:
    """CIP 单本账:期初净值 + 本期增加 − 本期减少(转固/处置) = 期末净值。

    转固额(period_decrease)是 CIP 的核心流量,缺失则无法验证 → closed=None(不假闭合)。
    """
    o = vals.get("opening_net"); i = vals.get("period_increase")
    d = vals.get("period_decrease"); c = vals.get("closing_net")
    base = {"year": year, "category": category, "opening_net": o, "increase": i,
            "decrease": d, "closing_net": c}
    if o is None or c is None or d is None:
        return {**base, "residual": None, "closed": None}
    calc = (o or 0.0) + (i or 0.0) - (d or 0.0)
    r = calc - (c or 0.0)
    return {**base, "residual": r, "closed": abs(r) < TOLERANCE_MILLION}

def validate_da_facts(facts: dict[str, Any]) -> list[str]:
    """零填充禁令:期末余额字段为 0 必须配 missing_flag(补零=静默造假)。

    只查绝不该为 0 的 closing 余额(原值/累计折旧/净值),不查可合理为 0 的流量项。
    """
    errors: list[str] = []
    if "base_year" not in facts:
        errors.append("base_year missing")
    missing_flags = {(m["year"], m["category"], m["field"])
                     for m in facts.get("missing_flags", [])
                     if "category" in m and "field" in m}
    # 零填充禁令适用于所有 3-sub-ledger 明细(PP&E/生物/油气):期末余额为 0 必须配 missing_flag
    for detail_key in ("ppe_detail", "prod_bio_detail", "oil_gas_detail"):
        for year, by_name in facts.get(detail_key, {}).items():
            for cat, vals in by_name.items():
                if cat == "_meta" or not isinstance(vals, dict) or cat in _SUBTOTAL_NAMES:
                    continue
                for field in _PPE_ZERO_CHECK_FIELDS:
                    v = vals.get(field)
                    if v == 0.0 and (year, cat, field) not in missing_flags:
                        errors.append(f"{year}.{cat}.{field}=0 without missing_flag (zero-fill forbidden)")
    # CIP 不查零填充:项目完工全额转固后 closing_net=0、新项目 opening_net=0 都是合法披露值,
    # 不是 LLM 造假(查了就是 crying wolf)。PPE closing 余额为 0 才不可信。
    return errors

# detail note_type → (sanity-gate 关键字段, roll-forward 函数 or None)
_DETAIL_CONFIG = {
    "ppe_detail": (PPE_3SUB_KEY_FIELDS, check_ppe_rollforward),
    "cip_detail": (CIP_KEY_FIELDS, check_cip_rollforward),
    "intangible_detail": (INTANGIBLE_KEY_FIELDS, None),  # 非消耗项,不跑 roll-forward(避免单行 identity 噪声)
    # 生物资产/油气资产:3-sub-ledger 与 PP&E 同构,复用 roll-forward(可选,非披露公司静默跳过)
    "prod_bio_detail": (PPE_3SUB_KEY_FIELDS, check_ppe_rollforward),
    "oil_gas_detail": (PPE_3SUB_KEY_FIELDS, check_ppe_rollforward),
}

def _sanity_gate(facts: dict[str, Any], n_years: int) -> None:
    """抽取理智闸门(spec §0.4 在 Phase 1 的对偶):区分"数据真没有"(标 flag)与
    "我根本没读到"(hard-stop)。三类失败模式各自触发,任一命中即 raise,不落盘骗人产物。

    ① detail 全年 LLM 报错 / 段定位失败 → provider/load_env/locate 配置问题;
    ② detail 关键字段跨年跨类 null 率 > 阈值 → schema 错配等抽取失败;
    ③ policy.ppe_categories 全类 life_years null → 政策段 schema 错配复发。
    """
    failures: list[str] = []

    # ① detail 全年失败(provider/locate)— 看缺失信号而非 null 率(空 dict 时 null 率无意义)
    for nt in _DETAIL_CONFIG:
        llm_err = [m for m in facts["missing_flags"]
                   if m.get("note_type") == nt and "llm:" in str(m.get("reason", ""))]
        if len(llm_err) >= n_years:
            failures.append(
                f"{nt}: {len(llm_err)}/{n_years} 年 LLM 报错——疑似 provider/load_env 配置失败(非数据缺口)")
            continue
        sec_err = [m for m in facts["missing_flags"] if m.get("note_type") == nt]
        if len(facts.get(nt, {})) == 0 and len(sec_err) >= n_years:
            failures.append(
                f"{nt}: {len(sec_err)}/{n_years} 年附注段定位失败——疑似 locate/schema 问题(非数据缺口)")

    # ② detail 关键字段 null 率(按 note_type 取各自关键字段集)
    for nt, (key_fields, _check) in _DETAIL_CONFIG.items():
        total, nulls = 0, 0
        for by_name in facts.get(nt, {}).values():
            for cat, vals in by_name.items():
                if cat == "_meta" or not isinstance(vals, dict) or cat in _SUBTOTAL_NAMES:
                    continue
                for f in key_fields:
                    total += 1
                    if vals.get(f) is None:
                        nulls += 1
        if total > 0 and nulls / total > SANITY_NULL_RATE_THRESHOLD:
            failures.append(
                f"{nt}: 关键字段 null 率 {nulls}/{total}={nulls / total:.0%}"
                f" > {SANITY_NULL_RATE_THRESHOLD:.0%}(抽取疑似失败,非数据缺口)")

    # ③ policy ppe 全类 life_years null(政策段 schema 错配复发)
    ppe_cats = facts.get("policy", {}).get("ppe_categories", [])
    if ppe_cats and all(c.get("life_years") is None for c in ppe_cats):
        failures.append(
            f"policy.ppe_categories: 全部 {len(ppe_cats)} 类 life_years 为 null(政策段抽取失败)")

    if failures:
        raise DaFactsExtractionError(
            "da_facts 抽取理智闸门触发——抽取本身疑似失败(配置/schema/provider),不是数据缺口:\n  - "
            + "\n  - ".join(failures)
            + "\n请检查 load_env / LLM provider / 附注段定位 / schema 配置,"
              "而非把这份数据当事实往下传(平移 reconciler exit-3 哲学)。")

def extract_company_facts(company_dir: Path, base_year: int,
                          years: list[int]) -> dict[str, Any]:
    """并行从年报 Markdown 提取 DA 事实,合并落盘到 recon/da_facts_latest.json。

    存储(spec §12.1):detail = {year: {category_name: {fields}, "_meta": ..}};
    policy = {ppe_categories:[..], intangible_categories:[..], source_year}。
    落盘前跑 roll-forward 闭合自校验(§3.3,PPE 走 3-sub-ledger 精确恒等式)+ 抽取理智闸门,
    闸门触发不落盘。
    """
    jobs = [(nt, y) for nt in _DETAIL_CONFIG for y in years]
    jobs.append(("ppe_policy", base_year))
    jobs.append(("intangible_policy", base_year))
    jobs.append(("prod_bio_policy", base_year))   # 可选:非乳业公司不披露 → not_disclosed 跳过
    jobs.append(("oil_gas_policy", base_year))    # 可选:非油气公司不披露 → not_disclosed 跳过

    def run(job: tuple[str, int]) -> dict[str, Any]:
        nt, year = job
        md = annual_markdown_path(company_dir, str(year))
        if not md:
            return {"note_type": nt, "year": year, "error": "md not found"}
        lines = md.read_text(encoding="utf-8").splitlines()
        sections = locate_note_sections(lines)
        sec = sections.get(nt)
        if not sec:
            # 可选资产(生物/油气)未披露 → 静默跳过(不进 missing_flag,不触发 sanity gate);
            # 强制类型(PP&E/CIP/无形)段定位失败仍走 error → missing_flag → hard-stop。
            if nt in _OPTIONAL_NOTE_TYPES:
                return {"note_type": nt, "year": year, "not_disclosed": True}
            return {"note_type": nt, "year": year, "error": "section not located"}
        return {"note_type": nt, "year": year,
                "data": extract_note(nt, sec["text"], year)}

    results = parallel_map(run, jobs, max_workers=3)

    facts: dict[str, Any] = {
        "company": company_dir.name, "base_year": base_year,
        "ppe_detail": {}, "cip_detail": {}, "intangible_detail": {},
        "prod_bio_detail": {}, "oil_gas_detail": {},
        "policy": {}, "roll_forward_checks": [],
        "missing_flags": [], "evidence_anchors": [],
    }
    for r in results:
        nt, year = r["note_type"], r["year"]
        if r.get("not_disclosed"):
            continue  # 可选资产未披露,静默跳过
        if r.get("error"):
            facts["missing_flags"].append({"note_type": nt, "year": year, "reason": r["error"]})
            continue
        data = r["data"]
        if data.get("error"):
            facts["missing_flags"].append(
                {"note_type": nt, "year": year, "reason": f"llm: {data['error']}"})
            continue
        cats = data.get("categories", [])
        if nt in _DETAIL_CONFIG:  # detail 类:name-keyed dict(spec §12.1)+ _meta 审计
            by_name: dict[str, Any] = {
                c["name"]: {k: v for k, v in c.items() if k != "name"}
                for c in cats if isinstance(c, dict) and c.get("name")
            }
            by_name["_meta"] = {"_usage": data.get("_usage"), "_model": data.get("_model"),
                                "_provider": data.get("_provider")}
            facts[nt][str(year)] = by_name
        else:  # policy 类
            facts["policy"][_POLICY_KEY[nt]] = [c for c in cats if isinstance(c, dict)]
    facts["policy"]["source_year"] = base_year

    # roll-forward 闭合自校验(spec §3.3):PPE 走 3-sub-ledger,CIP 走单账;逐年逐类,不静默放行
    for nt, (_key_fields, check_fn) in _DETAIL_CONFIG.items():
        if check_fn is None:
            continue
        for year_str, by_name in facts[nt].items():
            for cat, vals in by_name.items():
                if cat == "_meta" or not isinstance(vals, dict) or cat in _SUBTOTAL_NAMES:
                    continue
                facts["roll_forward_checks"].append(check_fn(int(year_str), cat, vals))

    facts["validation_errors"] = validate_da_facts(facts)

    # 抽取理智闸门:触发即 raise,不落盘(禁止把"没读到"伪装成"数据没有"往下传)
    _sanity_gate(facts, len(years))

    out = recon_dir(company_dir) / "da_facts_latest.json"
    write_json(out, facts)
    return facts

if __name__ == "__main__":
    import argparse
    from src.company_paths import find_company_dir

    p = argparse.ArgumentParser(description="提取年报 DA 事实(固定资产/无形资产/在建工程)")
    p.add_argument("--ticker", required=True, help="股票代码,如 002946.SZ")
    p.add_argument("--base-year", type=int, required=True, help="基年,如 2024")
    p.add_argument("--years", type=int, default=5, help="回溯年数(含基年),默认 5")
    args = p.parse_args()

    # 与 annual_report_reconciler / financial_expense_analyzer 同:CLI 入口先 load .env,
    # 否则 call_llm 读不到 GLM_API_KEY/LLM_PROVIDER,provider 回退链落到 kimi 报
    # "KIMI API key is not configured"(setdefault 幂等,已设的环境变量不被覆盖)。
    load_env(ROOT / ".env")

    cd = find_company_dir(args.ticker)
    yrs = list(range(args.base_year - args.years + 1, args.base_year + 1))
    try:
        extract_company_facts(cd, args.base_year, yrs)
    except DaFactsExtractionError as e:
        print(f"[da_facts] 抽取理智闸门触发,未落盘 da_facts_latest.json:\n{e}",
              file=sys.stderr)
        sys.exit(1)
