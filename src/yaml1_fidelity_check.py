# -*- coding: utf-8 -*-
"""
yaml1_fidelity_check.py — 校验 yaml1 是否忠实翻译自 核心假设.md

定位:补下游 yaml1_cleaner.py 的结构性盲区。
  cleaner 把守 yaml1↔历史现实(fold/回测)与 yaml1↔自洽;
  它从不读 .md,故 yaml1↔.md预测意图 无人把守 —— 这层就是本脚本的活。

三道闸(只打翻译忠实度,不重造下游 fold/回测):
  Gate A 结构      : yaml1 单独 vs 算法契约(深度/family/数组长度/margin二选一)
  Gate B 路径+符号 : yaml1 vs defaults.yaml(路径存在性 + 符号神谕 + 费率合理性)
  Gate C 值双射    : yaml1 vs .md(src 锚点定位小节,符号+量级敏感的集合核对)

哲学(与 skill 一致):翻不了举旗,绝不猜。解析不了的小节标 UNRESOLVED 交人,
不静默判 PASS。报告落盘(UTF-8),不靠中文 stdout。

用法:
  python src/yaml1_fidelity_check.py <yaml1.yaml> <defaults.yaml> <核心假设.md> [report_dir]
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

# 中文走 stdout 会乱码(见 CLAUDE.md):报告落盘,stdout 只打 ASCII 摘要
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ALLOWED_FAMILY = {"factor_product", "driver_rate", "growth", "abs", "vol_price", "vol_price_margin"}
ALLOWED_PROJ = {"yoy", "abs", "constant", "hold"}
RATE_PATH_HINTS = ("cost_rates", "gpm", "effective_tax_rate", "minority_ratio")


# ───────────────────────── 工具 ─────────────────────────
def flatten_defaults(node, prefix="", out=None):
    """defaults.yaml 嵌套 → {dotted_path: value}。只收带 'value' 的叶子。"""
    if out is None:
        out = {}
    if isinstance(node, dict):
        if "value" in node and not isinstance(node["value"], dict):
            out[prefix] = node["value"]
        for k, v in node.items():
            if k in ("value", "source", "note"):
                continue
            child = "{}.{}".format(prefix, k) if prefix else k
            flatten_defaults(v, child, out)
    return out


def parse_numbers(text):
    """从一段文本抽出所有数字(含 % 与全角负号),归一到 yaml1 口径。
    % → /100;全角负号 −/– → -。返回 float 列表。"""
    if not text:
        return []
    t = text.replace("−", "-").replace("–", "-").replace("—", "-")
    nums = []
    # 先吃带 % 的,再吃裸数字(避免 15.4% 被拆成 15.4 和漏 %)
    for m in re.finditer(r"-?\d+(?:\.\d+)?%", t):
        nums.append(float(m.group()[:-1]) / 100.0)
    t_nopct = re.sub(r"-?\d+(?:\.\d+)?%", " ", t)
    for m in re.finditer(r"-?\d+(?:\.\d+)?", t_nopct):
        nums.append(float(m.group()))
    return nums


def near(a, b, tol=5e-4):
    return abs(a - b) <= tol + 1e-9


def in_set(val, pool, tol=5e-4):
    return any(near(val, p, tol) for p in pool)


def split_sections(md_text):
    """按 markdown 标题(##/###/####)切片 → [(heading_text, body_text), ...]"""
    lines = md_text.splitlines()
    secs = []
    cur_head, cur_body = "(preamble)", []
    for ln in lines:
        m = re.match(r"^#{2,4}\s+(.*)$", ln)
        if m:
            secs.append((cur_head, "\n".join(cur_body)))
            cur_head, cur_body = m.group(1).strip(), []
        else:
            cur_body.append(ln)
    secs.append((cur_head, "\n".join(cur_body)))
    return secs


def core_term(src):
    """src '#整体毛利率(主动覆盖·参数化翻转)' → '整体毛利率'(去 # 去括号)"""
    s = src.lstrip("#").strip()
    s = re.sub(r"[（(].*?[)）]", "", s)
    return s.strip()


def longest_common_substr_len(a, b):
    if not a or not b:
        return 0
    dp = [0] * (len(b) + 1)
    best = 0
    for i in range(len(a)):
        ndp = [0] * (len(b) + 1)
        for j in range(len(b)):
            if a[i] == b[j]:
                ndp[j + 1] = dp[j] + 1
                best = max(best, ndp[j + 1])
        dp = ndp
    return best


def resolve_section(src, sections):
    """src 锚点 → 最匹配的 .md 小节 (heading, body)。匹配不上返回 (None, None)。"""
    core = core_term(src)
    best, best_score = (None, None), 0
    for head, body in sections:
        score = longest_common_substr_len(core, head)
        if score > best_score:
            best, best_score = (head, body), score
    # 至少 2 个连续字符重合才算命中
    return best if best_score >= 2 else (None, None)


def scope_to_keyword(body, keyword):
    """小节内多旋钮共存时(如 营业外收入/支出),按分句把范围收到含关键词的句子。"""
    clauses = re.split(r"[;；。\n]", body)
    hit = [c for c in clauses if keyword and keyword in c]
    return "\n".join(hit) if hit else body


def bold_spans(text):
    return re.findall(r"\*\*(.+?)\*\*", text)


# ───────────────────────── 旋钮收集 ─────────────────────────
def collect_knobs(y1):
    """返回标准旋钮 [(path, values, src)] 与收入 leaf 因子 [(seg_path, label, values, src, kind)]"""
    std, leaves = [], []
    for key, node in y1.items():
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "knob":
            std.append((key, node.get("values"), node.get("src", "")))
        if node.get("kind") == "decomposition":
            _walk_segments(key, node, leaves)
    return std, leaves


def _walk_segments(path, node, leaves, depth=0):
    segs = node.get("segments", {})
    for slug, seg in segs.items():
        spath = "{}.segments.{}".format(path, slug)
        if seg.get("kind") == "decomposition":
            _walk_segments(spath, seg, leaves, depth + 1)
            continue
        fam = seg.get("revenue_family")
        src = seg.get("src", "")
        if fam in ("factor_product", "vol_price", "driver_rate"):
            for f in seg.get("factors", []):
                proj = f.get("projection", {})
                leaves.append((spath, f.get("label", f.get("key", "")),
                               proj.get("values"), src, fam, depth))
            # 旧 vol_price 用 knobs
            for fk in ("volume_yoy", "price_yoy"):
                if "knobs" in seg and fk in seg["knobs"]:
                    leaves.append((spath, fk, seg["knobs"][fk], src, fam, depth))
        elif fam in ("growth", "abs"):
            knk = "revenue_yoy" if fam == "growth" else "revenue_abs"
            vals = (seg.get("knobs") or {}).get(knk)
            leaves.append((spath, knk, vals, src, fam, depth))


# ───────────────────────── 三道闸 ─────────────────────────
def gate_a(y1, H, findings):
    for key, node in y1.items():
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "knob":
            v = node.get("values")
            if not isinstance(v, list):
                findings.append(("A", "FAIL", key, "values 不是数组"))
            elif len(v) != H:
                findings.append(("A", "FAIL", key,
                                 "数组长度 {} != horizon {}".format(len(v), H)))
        if node.get("kind") == "decomposition":
            _gate_a_seg(key, node, H, findings, depth=0)
    # margin 二选一
    has_top_gpm = isinstance(y1.get("income.gpm"), dict)
    leaf_margin = _any_leaf_margin(y1)
    if has_top_gpm and leaf_margin:
        findings.append(("A", "FAIL", "income.gpm",
                         "over-determined:顶层 gpm 与 leaf margin 同时存在"))


def _gate_a_seg(path, node, H, findings, depth):
    if node.get("kind") == "decomposition" and "segments" in node and node.get("revenue_family"):
        findings.append(("A", "FAIL", path, "节点既是 decomposition 又挂 revenue_family"))
    for slug, seg in node.get("segments", {}).items():
        spath = "{}.segments.{}".format(path, slug)
        if seg.get("kind") == "decomposition":
            if depth + 1 >= 2:
                findings.append(("A", "FAIL", spath, "decomposition 深度 > 2"))
            _gate_a_seg(spath, seg, H, findings, depth + 1)
            continue
        fam = seg.get("revenue_family")
        if fam and fam not in ALLOWED_FAMILY:
            findings.append(("A", "FAIL", spath, "非法 revenue_family: {}".format(fam)))
        for f in seg.get("factors", []):
            pk = (f.get("projection") or {}).get("kind")
            if pk not in ALLOWED_PROJ:
                findings.append(("A", "FAIL", spath,
                                 "factor {} projection.kind={} 非法".format(f.get("key"), pk)))
            pv = (f.get("projection") or {}).get("values")
            if pk in ("yoy", "abs") and (not isinstance(pv, list) or len(pv) != H):
                findings.append(("A", "FAIL", spath,
                                 "factor {} values 长度!={}".format(f.get("key"), H)))


def _any_leaf_margin(y1):
    found = [False]

    def rec(node):
        for slug, seg in (node.get("segments") or {}).items():
            if seg.get("kind") == "decomposition":
                rec(seg)
            elif (seg.get("knobs") or {}).get("margin") is not None:
                found[0] = True
    rev = y1.get("income.revenue")
    if isinstance(rev, dict):
        rec(rev)
    return found[0]


def gate_b(std_knobs, defaults_flat, findings):
    dpaths = set(defaults_flat.keys())
    for path, vals, src in std_knobs:
        # 路径存在性(抓发明路径 / financial_expense 嵌套错)
        if path not in dpaths:
            findings.append(("B", "FAIL", path,
                             "路径不在 defaults.yaml(发明路径或嵌套错,下游会静默丢弃)"))
            continue
        if not isinstance(vals, list) or not vals:
            continue
        y0 = next((x for x in vals if isinstance(x, (int, float))), None)
        dv = defaults_flat[path]
        # 符号神谕:与 defaults 基年符号比(两边非 0 才比)
        if isinstance(dv, (int, float)) and y0 is not None and dv != 0 and y0 != 0:
            if (dv > 0) != (y0 > 0):
                findings.append(("B", "WARN", path,
                                 "符号与 defaults 基年相反(yaml1={} vs defaults={})".format(y0, dv)))
        # 费率合理性
        if any(h in path for h in RATE_PATH_HINTS):
            bad = [x for x in vals if isinstance(x, (int, float)) and not (0 <= x < 1)]
            if bad:
                findings.append(("B", "WARN", path,
                                 "费率/比率超出 [0,1):{}".format(bad)))


def gate_c_knob(path, vals, src, sections, multi, findings):
    if not src:
        findings.append(("C", "WARN", path, "无 src 锚点,无法对 .md 核对"))
        return
    if not isinstance(vals, list) or not vals:
        return
    _, body = resolve_section(src, sections)
    if body is None:
        findings.append(("C", "UNRESOLVED", path,
                         "src '{}' 无法定位 .md 小节,举旗交人".format(src)))
        return
    # 单旋钮小节:取整节加粗值(避免表格行不含关键词被误伤,如 gpm)
    # 多旋钮共享小节:按关键词收窄(如 营业外收入/支出),防串行误判
    scoped = scope_to_keyword(body, core_term(src)) if multi else body
    pool = parse_numbers("\n".join(bold_spans(scoped))) or parse_numbers(scoped)
    if not pool:
        findings.append(("C", "UNRESOLVED", path,
                         "小节内未抽到数字,举旗交人"))
        return
    uniq = []
    for v in vals:
        if isinstance(v, (int, float)) and not any(near(v, u) for u in uniq):
            uniq.append(v)
    missing = [v for v in uniq if not in_set(v, pool)]
    if missing:
        findings.append(("C", "FAIL", path,
                         "值在 .md 小节找不到:{} | .md 抽到:{}".format(missing, sorted(set(pool)))))
    else:
        # 摊满一致性:全程/平推 但 yaml1 非常量
        flat_decl = ("全程" in scoped) or ("平推" in scoped)
        if flat_decl and len(uniq) > 1:
            findings.append(("C", "WARN", path,
                             ".md 声明全程/平推,但 yaml1 非常量:{}".format(vals)))
        findings.append(("C", "PASS", path, "值与 .md 一致"))


def gate_c_leaf(spath, label, vals, src, sections, findings):
    if not isinstance(vals, list) or not vals:
        findings.append(("C", "WARN", spath + "/" + label, "无 values"))
        return
    body = resolve_section(src, sections)[1]
    if body is None:
        findings.append(("C", "UNRESOLVED", spath + "/" + label,
                         "src '{}' 无法定位 .md 小节".format(src)))
        return
    # 因子级:label 销量/吨价/revenue_yoy → 找含该词的预测行
    kw = {"revenue_yoy": "收入", "revenue_abs": "收入"}.get(label, label)
    lines = [l for l in body.splitlines() if kw and kw in l and ("yoy" in l or "%" in l or "收入" in l)]
    scoped = "\n".join(lines) if lines else body
    pool = parse_numbers(scoped)
    if not pool:
        findings.append(("C", "UNRESOLVED", spath + "/" + label, "未抽到数字"))
        return
    uniq = []
    for v in vals:
        if isinstance(v, (int, float)) and not any(near(v, u) for u in uniq):
            uniq.append(v)
    missing = [v for v in uniq if not in_set(v, pool)]
    tag = spath + "/" + label
    if missing:
        findings.append(("C", "FAIL", tag,
                         "值在 .md 找不到:{} | .md 抽到:{}".format(missing, sorted(set(pool)))))
    else:
        findings.append(("C", "PASS", tag, "值与 .md 一致"))


def coverage_reverse(y1_srcs, sections, findings):
    """反向:.md 里像'预测旋钮'的小节,是否都被某条 yaml1 src 认领(漏译候选)。"""
    claimed_cores = {core_term(s) for s in y1_srcs if s}
    for head, body in sections:
        if not head or head == "(preamble)":
            continue
        looks_forecast = ("预测" in body and ("旋钮" in body or "yoy" in body or "全程" in body
                                              or "平推" in body or "%" in body))
        if not looks_forecast:
            continue
        hc = re.sub(r"\[.*?\]", "", head).strip()
        matched = any(longest_common_substr_len(c, hc) >= 2 for c in claimed_cores)
        if not matched:
            findings.append(("COV", "WARN", hc,
                             ".md 含预测但无 yaml1 src 认领(漏译候选,需人工核)"))


# ───────────────────────── Gate C 无损版:knobs 块结构 diff ─────────────────────────
# 上游生成器若在 .md 吐 ```knobs 块(锚点=生成器自己的上挂科目,与 yaml1 的 src 同源),
# Gate C 从"正则抠人话"退化成"两个结构对象逐条 diff",零脆性、真双射。
# 完全由块内容驱动,不含任何公司特定假设(兼容任意公司)。

_SUB_ALIAS = {"revenue_yoy": ["收入", "revenue_yoy"],
              "revenue_abs": ["收入", "revenue_abs"]}


def extract_knobs_block(md_text):
    """抓出 ```knobs fenced 块并 yaml.safe_load。无块返回 None;解析失败返回 {'_err': ...}。
    唯一保留的正则就是'抓这个块',极稳,不碰人话。"""
    m = re.search(r"```knobs[ \t]*\n(.*?)```", md_text, re.S)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1)) or {}
    except Exception as e:
        return {"_err": str(e)}


def _norm_unit(v, unit):
    if isinstance(v, (int, float)) and unit == "pct":
        return v / 100.0
    return v


def gate_c_diff(std_knobs, leaves, block, findings):
    """yaml1 旋钮 ←(src/锚点+sub)→ knobs 块条目,逐条结构 diff + 双向兜底。"""
    entries = block.get("knobs", []) if isinstance(block, dict) else []
    index = {}
    for e in entries:
        if not isinstance(e, dict) or "anchor" not in e:
            findings.append(("C-DIFF", "FAIL", "knobs块", "条目缺 anchor 或非映射:{}".format(e)))
            continue
        anchor = core_term(str(e.get("anchor", "")))
        sub = e.get("sub")
        index[(anchor, str(sub) if sub is not None else None)] = {"e": e, "hit": False}

    def block_vals(e):
        vs = e.get("values")
        return [_norm_unit(v, e.get("unit", "")) for v in vs] if isinstance(vs, list) else None

    def cmp_vals(yv, bv):
        if not isinstance(yv, list) or bv is None:
            return "无法比较(values 缺失)"
        if len(yv) != len(bv):
            return "数组长度不符:yaml1={} block={}".format(len(yv), len(bv))
        bad = []
        for i, (a, b) in enumerate(zip(yv, bv)):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if not near(a, b):
                    bad.append(i)
            elif a != b:
                bad.append(i)
        return bad  # 空 list = 一致

    def lookup(anchor_core, sub=None):
        if sub is None:
            return index.get((anchor_core, None))
        for s in [str(sub)] + _SUB_ALIAS.get(sub, []):
            hit = index.get((anchor_core, s))
            if hit:
                return hit
        return None

    def check(tag, vals, hit):
        hit["hit"] = True
        res = cmp_vals(vals, block_vals(hit["e"]))
        if isinstance(res, str):
            findings.append(("C-DIFF", "FAIL", tag, res))
        elif res:
            findings.append(("C-DIFF", "FAIL", tag,
                             "值与生成器自报不符 @年索引{}:yaml1={} block={}".format(
                                 res, vals, block_vals(hit["e"]))))
        else:
            findings.append(("C-DIFF", "PASS", tag, "值与生成器自报一致"))

    for path, vals, src in std_knobs:
        hit = lookup(core_term(src) if src else "", None)
        if not hit:
            findings.append(("C-DIFF", "FAIL", path,
                             "yaml1 旋钮在 knobs 块无对应(幻觉/src错):src='{}'".format(src)))
        else:
            check(path, vals, hit)

    for spath, label, vals, src, fam, depth in leaves:
        hit = lookup(core_term(src) if src else "", label)
        tag = spath + "/" + label
        if not hit:
            findings.append(("C-DIFF", "FAIL", tag,
                             "yaml1 因子在 knobs 块无对应:anchor='{}' sub='{}'".format(
                                 core_term(src or ""), label)))
        else:
            check(tag, vals, hit)

    for (anchor, sub), rec in index.items():
        if not rec["hit"]:
            findings.append(("C-DIFF", "FAIL", "knobs:{}|{}".format(anchor, sub),
                             "生成器自报但 yaml1 无对应(漏译):{}".format(rec["e"])))


# ───────────────────────── 主流程 ─────────────────────────
def main():
    if len(sys.argv) < 4:
        sys.stderr.write(__doc__)
        sys.exit(2)
    yaml1_path, defaults_path, md_path = sys.argv[1], sys.argv[2], sys.argv[3]
    report_dir = sys.argv[4] if len(sys.argv) > 4 else None

    with open(yaml1_path, encoding="utf-8") as f:
        y1 = yaml.safe_load(f)
    with open(defaults_path, encoding="utf-8") as f:
        defaults = yaml.safe_load(f)
    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()

    H = len(y1.get("meta", {}).get("horizon", []))
    defaults_flat = flatten_defaults(defaults)
    sections = split_sections(md_text)
    std_knobs, leaves = collect_knobs(y1)

    findings = []
    gate_a(y1, H, findings)
    gate_b(std_knobs, defaults_flat, findings)

    # Gate C 路由:有 ```knobs 块走无损结构 diff;无块(或解析失败)回退正则版
    block = extract_knobs_block(md_text)
    if isinstance(block, dict) and "_err" in block:
        findings.append(("C", "WARN", "knobs块", "解析失败,回退正则:{}".format(block["_err"])))
        block = None
    if isinstance(block, dict) and block.get("knobs"):
        gate_c_mode = "block-diff(无损)"
        gate_c_diff(std_knobs, leaves, block, findings)
    else:
        gate_c_mode = "regex(脆性·回退)"
        head_count = {}
        for _, _, src in std_knobs:
            h = resolve_section(src, sections)[0] if src else None
            if h:
                head_count[h] = head_count.get(h, 0) + 1
        for path, vals, src in std_knobs:
            h = resolve_section(src, sections)[0] if src else None
            multi = bool(h) and head_count.get(h, 0) > 1
            gate_c_knob(path, vals, src, sections, multi, findings)
        for spath, label, vals, src, fam, depth in leaves:
            gate_c_leaf(spath, label, vals, src, sections, findings)
        all_srcs = [s for _, _, s in std_knobs] + [s for _, _, _, s, _, _ in leaves]
        coverage_reverse(all_srcs, sections, findings)

    # 汇总
    counts = {}
    for gate, status, _, _ in findings:
        counts[status] = counts.get(status, 0) + 1
    hard = [f for f in findings if f[1] in ("FAIL",)]
    blocked = len(hard) > 0

    report = {
        "yaml1": yaml1_path,
        "horizon_len": H,
        "gate_c_mode": gate_c_mode,
        "knob_count": len(std_knobs),
        "leaf_factor_count": len(leaves),
        "summary": counts,
        "verdict": "BLOCK" if blocked else "PASS",
        "findings": [
            {"gate": g, "status": s, "path": p, "detail": d}
            for (g, s, p, d) in findings
        ],
    }

    # 落盘(UTF-8),不靠中文 stdout
    if not report_dir:
        base = os.path.dirname(os.path.abspath(yaml1_path))
        mk = os.path.join(base, ".modelking")
        report_dir = mk if os.path.isdir(mk) else base
    jpath = os.path.join(report_dir, "yaml1_fidelity_report.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # stdout 只打 ASCII 安全摘要
    print("verdict: {}".format(report["verdict"]))
    print("summary: {}".format(json.dumps(counts)))
    print("report : {}".format(jpath))
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
