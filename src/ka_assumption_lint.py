# -*- coding: utf-8 -*-
"""
ka_assumption_lint.py — 校验 核心假设.md 是否满足 /ka 输出契约

定位：/ka 的判断不可机械验证，但 /ka 产出的 .md 必须满足一组硬结构契约。
本 lint 把这组契约翻成可机器校验断言，补 /ka 输出层的守门员。
纯 Python，无 LLM、无网络、不读真实文件（调用方传 md_text）。

硬规则（零误报，只抓确定违规）：
  1. official 稿必须有 ```knobs 块且可解析
  2. knobs 块 horizon 是非空 int 列表
  3. 每条 knob：anchor/family/unit/values 齐全；unit ∈ {pct, ratio, abs_mn}；len(values)==len(horizon)
  4. margin 互斥：knobs 块不能同时有 family:gpm（整体手拍）和 family:leaf_margin（分线折叠）
  5. 正文 `### ... [上挂: ...; compiler: <X>]` 块头：若 X 是纯 ASCII（族名都是英文），
     必须 ∈ ALLOWED_FAMILY；中文标签（如"整体手拍"）跳过。抓自创族名/拼写错。

不抓（太 fuzzy，会误报）：
  - BS/CF 驱动是否该进 knobs（bs_scalar_pct 等是合法人工覆盖，需 thesis 触发，.md 层判不出）
  - knobs family 枚举（knobs契约 §7 是推荐表，非硬 enum）
  - 抬头时间轴四数（人话，正则抽不稳）

用法：
  python src/ka_assumption_lint.py <核心假设.md> [report_dir]
"""
import sys
import io
import os
import re
import json

try:
    import yaml
except ImportError:
    sys.stderr.write("need pyyaml: pip install pyyaml\n")
    sys.exit(2)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from .yaml1_fidelity_check import ALLOWED_FAMILY, extract_knobs_block

KNOBS_UNIT = {"pct", "ratio", "abs_mn"}

# compiler 块头标签合法集 = revenue_family（收入 leaf 算法模板）∪ knobs 块 §7 family 名。
# .md `### ... [上挂: ...; compiler: <X>]` 的 X 可能是任一侧；只校验 ASCII X 不自创/拼错。
ALLOWED_COMPILER_TAGS = ALLOWED_FAMILY | {
    "factor_yoy", "gpm", "leaf_margin", "cost_rate", "tax_rate",
    "minor_rate", "op_adj_abs", "cost_abs", "below_line_abs",
    "other_fin_exp_abs", "bs_revenue_pct", "bs_cogs_days",
    "bs_scalar_pct", "formula_input", "formula",
}

# margin 互斥的 knobs family
GPM_FAMILY = "gpm"
LEAF_MARGIN_FAMILY = "leaf_margin"


def _is_ascii(s):
    """纯 ASCII（族名都是英文 token）；含中文等非 ASCII → False。"""
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def lint(md_text):
    """校验 核心假设.md，返回 findings 列表 [(severity, code, detail), ...]。

    severity ∈ {"FAIL", "WARN"}；有 FAIL 即 verdict=BLOCK。
    code 是稳定标识（供测试断言）：KNOBS_MISSING / KNOBS_PARSE / HORIZON / UNIT / LEN / MARGIN_MUTEX / BAD_FAMILY / COST_ABS_SIGN。
    """
    findings = []

    # ── 1. knobs 块存在 + 可解析 ──
    block = extract_knobs_block(md_text)
    if block is None:
        findings.append(("FAIL", "KNOBS_MISSING",
                         "official 稿必须有 ```knobs 块（末尾机器自报清单）"))
        # 没有 knobs 块就做不了后续 knobs 检查；继续做正文 family 检查
        block = {}
    elif isinstance(block, dict) and "_err" in block:
        findings.append(("FAIL", "KNOBS_PARSE",
                         "knobs 块 YAML 解析失败：{}".format(block["_err"])))
        block = {}

    # ── 2-4. knobs 块内部契约 ──
    horizon = block.get("horizon") if isinstance(block, dict) else None
    H = _check_horizon(horizon, findings)
    entries = block.get("knobs", []) if isinstance(block, dict) else []
    if isinstance(entries, list):
        families_in_block = _check_knob_entries(entries, H, findings)
        _check_margin_mutex(families_in_block, findings)
    elif entries:
        findings.append(("FAIL", "KNOBS_PARSE", "knobs 块 knobs 字段非列表"))

    # ── 5. 正文 compiler family ──
    _check_compiler_families(md_text, findings)

    return findings


def _check_horizon(horizon, findings):
    if horizon is None:
        findings.append(("FAIL", "HORIZON", "knobs 块缺 horizon"))
        return None
    if not isinstance(horizon, list) or not horizon:
        findings.append(("FAIL", "HORIZON", "horizon 必须是非空列表"))
        return None
    if not all(isinstance(x, int) for x in horizon):
        findings.append(("FAIL", "HORIZON", "horizon 必须是 int 列表：{}".format(horizon)))
        return None
    return len(horizon)


def _check_knob_entries(entries, H, findings):
    """逐条校验，返回 knobs 块里出现的 family 集合（供 margin 互斥判断）。"""
    families = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            findings.append(("FAIL", "KNOBS_PARSE", "knobs[{}] 非映射：{}".format(i, e)))
            continue
        anchor = e.get("anchor")
        family = e.get("family")
        unit = e.get("unit")
        values = e.get("values")
        if not anchor:
            findings.append(("FAIL", "KNOBS_PARSE", "knobs[{}] 缺 anchor".format(i)))
        if not family:
            findings.append(("FAIL", "KNOBS_PARSE", "knobs[{}] 缺 family".format(i)))
        else:
            families.add(str(family))
        if unit not in KNOBS_UNIT:
            findings.append(("FAIL", "UNIT",
                             "knobs[{}] unit='{}' 不在 {{pct,ratio,abs_mn}}".format(i, unit)))
        if not isinstance(values, list):
            findings.append(("FAIL", "LEN",
                             "knobs[{}] values 非列表（anchor={}）".format(i, anchor)))
        elif H is not None and len(values) != H:
            findings.append(("FAIL", "LEN",
                             "knobs[{}] values 长度 {} != horizon {}（anchor={}）".format(
                                 i, len(values), H, anchor)))
        # cost_abs 减值符号门：cost_abs 族（资产减值/信用减值/其他资产减值）按附录A 存负值
        # （损失为负，零允许）。引擎以 +impact_adjustment 把这些字段带符号加进 operate_profit，
        # 正数会被当加项加回致利润虚增。.md 作者常误写正数幅度（"损失项写正数金额"），此门早拦。
        if str(family) == "cost_abs" and isinstance(values, list):
            pos = [v for v in values if isinstance(v, (int, float)) and v > 0]
            if pos:
                findings.append(("FAIL", "COST_ABS_SIGN",
                                 "knobs[{}] anchor='{}' family=cost_abs 存正数 {}；"
                                 "减值项按附录A 存负值（零允许），引擎按带符号损益调整加进 operate_profit，"
                                 "正数会虚增利润。改负值。".format(i, anchor, pos)))
    return families


def _check_margin_mutex(families, findings):
    if GPM_FAMILY in families and LEAF_MARGIN_FAMILY in families:
        findings.append(("FAIL", "MARGIN_MUTEX",
                         "knobs 块同时有 family:gpm（整体手拍）和 family:leaf_margin（分线折叠）"
                         "——margin 互斥硬规则，二选一"))


def _check_compiler_families(md_text, findings):
    """抓 `### ... [上挂: ...; compiler: <X>]` 块头，ASCII X 必须 ∈ ALLOWED_FAMILY。"""
    # 块头形如：### 标题 [...; compiler: factor_product] 或 ### 标题 [compiler: growth; ...]
    for m in re.finditer(r"^#{2,4}\s+.*?\[(.*?)\]\s*$", md_text, re.M):
        bracket = m.group(1)
        cm = re.search(r"compiler:\s*([^\];]+)", bracket)
        if not cm:
            continue
        val = cm.group(1).strip()
        # 中文标签（整体手拍 / 分线毛利折叠 等）→ 语义标签，不是族名，跳过
        if not _is_ascii(val):
            continue
        # income.gpm knob / leaf margin -> income.gpm 这类带空格/箭头的非族 tag → 跳过
        if " " in val or "->" in val or "." in val:
            continue
        if val not in ALLOWED_COMPILER_TAGS:
            findings.append(("FAIL", "BAD_FAMILY",
                             "块头 compiler:'{}' 不在合法集（revenue_family ∪ knobs §7 family；疑似自创族名/拼写错）".format(val)))


def verdict(findings):
    return "BLOCK" if any(f[0] == "FAIL" for f in findings) else "PASS"


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        sys.exit(2)
    md_path = sys.argv[1]
    report_dir = sys.argv[2] if len(sys.argv) > 2 else None
    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()
    findings = lint(md_text)
    v = verdict(findings)
    counts = {}
    for sev, _, _ in findings:
        counts[sev] = counts.get(sev, 0) + 1
    report = {
        "md": md_path,
        "verdict": v,
        "summary": counts,
        "findings": [{"severity": s, "code": c, "detail": d} for (s, c, d) in findings],
    }
    if not report_dir:
        base = os.path.dirname(os.path.abspath(md_path))
        report_dir = os.path.join(base, ".modelking") if os.path.isdir(os.path.join(base, ".modelking")) else base
    os.makedirs(report_dir, exist_ok=True)
    jpath = os.path.join(report_dir, "ka_assumption_lint_report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("verdict: {}".format(v))
    print("summary: {}".format(json.dumps(counts, ensure_ascii=False)))
    print("report : {}".format(jpath))
    sys.exit(1 if v == "BLOCK" else 0)


if __name__ == "__main__":
    main()
