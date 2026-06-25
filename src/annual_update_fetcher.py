#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""年度更新器·标准线财务数据取数脚本

从 data.db 的 clean_annual 表 + financial_expense.yaml 取 (H, A] 年度的标准线
财务数据(收入 headline / 费用率 / below-OP 绝对值 / 有效税率 / 其他财务费用),
输出结构化 JSON 供年度更新器 skill 第2步"标准线填历史"直接使用。

职责边界(铁律):
- 只取数 + 算历史实际比率 + 标缺口。零判断、零估算、零写 .md。
- 符号直接搬(clean_annual 已是"对利润正负贡献"口径,与旧稿一致),不翻号——
  翻号是 compiler 的事(→compiler 附录 A)。
- 费用率/税率的除法是搬运历史事实(分母分子都在 clean_annual),不是预测派生
  序列,与生成器"派生量不手算"不冲突。
- 字段映射与 `skills/年度更新器_skill_v1.md` 第2步同源;字段名为 TuShare 官方名,
  通用于所有公司,不写死任何公司特征。

CLI:
    py -m src.annual_update_fetcher --ticker 002946.SZ --history-end 2024
    py -m src.annual_update_fetcher --ticker 002946.SZ --history-end 2024 --out path.json

退出码:0 = ok 或 noop(无需更新);2 = gap(守门失败,有核心字段缺失,指 /init)。
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

import yaml

from src.company_paths import (
    COMPANIES_DIR,
    agent_logs_dir,
    company_dir_from_db_path,
    financial_expense_path,
    find_db_path,
)


# 标准线 ↔ clean_annual 字段映射(与 年度更新器_skill_v1.md 第2步同源)。
# kind:
#   direct = 直接取绝对值(clean_annual 符号已是"对利润贡献"口径,原样搬)
#   ratio  = field / revenue(历史实际费用率)
#   tax    = income_tax / total_profit(历史实际有效税率)
#   yaml   = financial_expense.yaml · periods.{年}.derived.other_fin_exp_abs
# core = True 的字段缺失 → status=gap(守门失败,指 /init + clean.py);
#        core = False 的字段缺失 → 值留 null,不阻塞(skill 自行判断 / 年报 fallback)。
STANDARD_LINES: list[tuple[str, str, str | None, str, bool]] = [
    # (key,                 kind,     field,                     unit,          core)
    ("revenue_headline",    "direct", "revenue",                 "million_cny", True),
    ("sell_exp_rate",       "ratio",  "sell_exp",                "ratio",       True),
    ("admin_exp_rate",      "ratio",  "admin_exp",               "ratio",       True),
    ("rd_exp_rate",         "ratio",  "rd_exp",                  "ratio",       False),
    ("biz_tax_surchg_rate", "ratio",  "biz_tax_surchg",          "ratio",       False),
    ("assets_impair_loss",  "direct", "assets_impair_loss",      "million_cny", False),
    ("credit_impa_loss",    "direct", "income.credit_impa_loss", "million_cny", False),
    ("oth_income",          "direct", "oth_income",              "million_cny", False),
    ("invest_income",       "direct", "invest_income",           "million_cny", False),
    ("fv_value_chg_gain",   "direct", "fv_value_chg_gain",       "million_cny", False),
    ("asset_disp_income",   "direct", "asset_disp_income",       "million_cny", False),
    ("non_oper_income",     "direct", "non_oper_income",         "million_cny", False),
    ("non_oper_exp",        "direct", "non_oper_exp",            "million_cny", False),
    ("effective_tax_rate",  "tax",    None,                       "ratio",       True),
    ("other_fin_exp_abs",   "yaml",   None,                       "million_cny", False),
    # —— 旧稿里同样有历史序列、必须随年度更新补全的标准观测行(读旧稿全文发现 fetcher 首版漏取)——
    ("gpm_history",         "gpm",    None,                       "ratio",       False),  # 整体毛利率历史观测 = (revenue-oper_cost)/revenue
    ("minority_ratio",      "minority", None,                     "ratio",       False),  # 少数股东损益率 = minority_gain/n_income
    ("finan_exp_total",     "direct", "fin_exp",                  "million_cny", False),  # 财务费用合计(历史照搬;注意是 fin_exp 非 finan_exp)
    # 派生观测行(旧稿"历史观测·照搬·供核对"段,引擎算但历史照搬要全)
    ("operate_profit_obs",  "direct", "operate_profit",           "million_cny", False),
    ("total_profit_obs",    "direct", "total_profit",             "million_cny", False),
    ("income_tax_obs",      "direct", "income_tax",               "million_cny", False),
    ("n_income_obs",        "direct", "n_income",                 "million_cny", False),
    ("n_income_attr_p_obs", "direct", "n_income_attr_p",          "million_cny", True),   # audit R2:归母净利是 headline,clean.py 已硬保证其存在,设 core 关闭"NULL净利静默放行"的洞
    ("nincome_margin",      "nincome_margin", None,               "ratio",       False),  # 归母净利率 = n_income_attr_p/revenue
]


# 旧稿 knobs 块 anchor(中文)↔ fetcher 标准 key 映射(与 STANDARD_LINES 同源)。
# 偏离诊断用:读旧稿 knobs 块预测值,对齐到 fetcher 真实值。
# 收入 leaf 因子(销量yoy/吨价yoy/收入yoy)不在此表——它们是 B 类量价原子,走第3步估算,非真实 vs 预测。
_ANCHOR_TO_KEY: dict[str, tuple[str, str]] = {
    "#整体毛利率": ("gpm_history", "pct"),
    "#销售费用": ("sell_exp_rate", "pct"),
    "#管理费用": ("admin_exp_rate", "pct"),
    "#研发费用": ("rd_exp_rate", "pct"),
    "#营业税金及附加": ("biz_tax_surchg_rate", "pct"),
    "#有效税率": ("effective_tax_rate", "pct"),
    "#少数股东损益": ("minority_ratio", "pct"),
    "#资产减值损失": ("assets_impair_loss", "abs"),
    "#信用减值损失": ("credit_impa_loss", "abs"),
    "#其他收益": ("oth_income", "abs"),
    "#投资净收益": ("invest_income", "abs"),
    "#公允价值变动净收益": ("fv_value_chg_gain", "abs"),
    "#资产处置收益": ("asset_disp_income", "abs"),
    "#营业外收入": ("non_oper_income", "abs"),
    "#营业外支出": ("non_oper_exp", "abs"),
}


def find_db(ticker: str) -> Path:
    """Locate companies/*_{code}/Agent/data.db."""
    try:
        return find_db_path(ticker, COMPANIES_DIR)
    except FileNotFoundError:
        sys.exit(f"No Agent/data.db found for {ticker} in {COMPANIES_DIR}")


def load_other_fin_exp(company_dir: Path, periods: list[str]) -> dict[str, float | None]:
    """从 financial_expense.yaml 取各年 other_fin_exp_abs(clean_annual 无此字段)。"""
    out: dict[str, float | None] = {}
    fe_path = financial_expense_path(company_dir)
    if not fe_path.exists():
        return {y: None for y in periods}
    doc = yaml.safe_load(fe_path.read_text(encoding="utf-8")) or {}
    per = doc.get("periods") or {}
    for y in periods:
        derived = (per.get(y) or {}).get("derived") or {}
        out[y] = derived.get("other_fin_exp_abs")
    return out


def _emit(result: dict, out: str | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"written: {out}", file=sys.stderr)
    else:
        print(text)


def _emit_deviation_md(result: dict, forecast_md: str) -> str | None:
    """读旧稿 knobs 块预测值,和 fetcher 真实值对比,输出偏离诊断 md。

    knobs 块是旧稿末尾的机器自报清单(结构化 YAML,值与正文一字不差)。
    只覆盖 _ANCHOR_TO_KEY 里的标准旋钮(费用率/税率/below-OP/gpm/少数)。
    收入 leaf 量价因子不在其中(走第3步估算,非真实 vs 预测)。
    输出到 companies/{公司}/Agent/Logs/annual_update_deviation_{YYYYMMDD}_{A}.md。
    """
    import re, datetime
    try:
        text = Path(forecast_md).read_text(encoding="utf-8")
    except OSError as e:
        print(f"[deviation] 读旧稿失败 {forecast_md}: {e}", file=sys.stderr)
        return None
    m = re.search(r"```knobs\n(.*?)```", text, re.DOTALL)
    if not m:
        print(f"[deviation] knobs 块未找到于 {forecast_md},跳过偏离 md", file=sys.stderr)
        return None
    try:
        doc = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        print(f"[deviation] knobs 块解析失败: {e}", file=sys.stderr)
        return None
    horizon = [str(y) for y in (doc.get("horizon") or [])]
    knobs = doc.get("knobs") or []
    new_periods = result["new_periods"]
    N = len(new_periods)
    aligned = horizon[:N] == new_periods

    preds: dict[str, dict] = {}
    for k in knobs:
        anc = k.get("anchor")
        if anc in _ANCHOR_TO_KEY:
            key, utype = _ANCHOR_TO_KEY[anc]
            preds[key] = {"utype": utype, "values": (k.get("values") or [])[:N], "anchor": anc}

    today = datetime.date.today().strftime("%Y%m%d")
    A = result["data_end"]
    out_dir = agent_logs_dir(Path(result["company_dir"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"annual_update_deviation_{today}_{A}.md"

    L: list[str] = []
    L.append(f"# 年度更新偏离诊断 · {result['ticker']} · 滚到 {A} 年报")
    L.append("")
    L.append(f"> 旧稿: `{forecast_md}`")
    L.append(f"> 产出: {datetime.date.today().isoformat()}  |  滚 {N} 年: {result['history_end']} → {A}  |  新期: {new_periods}")
    if not aligned:
        L.append(f"> ⚠️ knobs 块 horizon 前缀 {horizon[:N]} ≠ new_periods {new_periods},预测值可能错位,需人工核")
    L.append("")
    L.append("> 真实值来自 clean_annual(fetcher);预测值来自旧稿 knobs 块。比率类单位 %,绝对值类单位 百万元。偏离 = 真实 − 预测。")
    L.append("")

    def _row(key: str, fmt_real, fmt_pred, fmt_diff) -> str:
        rv = [result["lines"].get(key, {}).get("values", {}).get(y) for y in new_periods]
        pv = preds.get(key, {}).get("values", [])
        cells = [preds.get(key, {}).get("anchor", key)]
        for v in rv:
            cells.append(fmt_real(v) if v is not None else "—")
        for v in pv:
            cells.append(fmt_pred(v))
        for i in range(N):
            if i < len(rv) and rv[i] is not None and i < len(pv):
                cells.append(fmt_diff(rv[i], pv[i]))
            else:
                cells.append("—")
        return "| " + " | ".join(cells) + " |"

    def _hdr() -> list[str]:
        return ["指标"] + [f"{y} 真实" for y in new_periods] + [f"{y} 预测" for y in new_periods] + [f"{y} 偏离" for y in new_periods]

    pct_order = ["gpm_history", "sell_exp_rate", "admin_exp_rate", "rd_exp_rate",
                 "biz_tax_surchg_rate", "effective_tax_rate", "minority_ratio"]
    pct_keys = [k for k in pct_order if k in preds]
    if pct_keys:
        L.append("## 比率类(%)")
        L.append("")
        h = _hdr()
        L.append("| " + " | ".join(h) + " |")
        L.append("|" + "---|" * len(h))
        for key in pct_keys:
            L.append(_row(key, lambda v: f"{v*100:.2f}", lambda v: f"{v:.2f}", lambda r, p: f"{r*100-p:+.2f}"))
        L.append("")

    abs_order = ["assets_impair_loss", "credit_impa_loss", "oth_income", "invest_income",
                 "fv_value_chg_gain", "asset_disp_income", "non_oper_income", "non_oper_exp"]
    abs_keys = [k for k in abs_order if k in preds]
    if abs_keys:
        L.append("## 绝对值类(百万元)")
        L.append("")
        h = _hdr()
        L.append("| " + " | ".join(h) + " |")
        L.append("|" + "---|" * len(h))
        for key in abs_keys:
            L.append(_row(key, lambda v: f"{v:.2f}", lambda v: f"{v:.2f}", lambda r, p: f"{r-p:+.2f}"))
        L.append("")

    ofe = result["lines"].get("other_fin_exp_abs", {}).get("values", {})
    L.append("## 其他")
    L.append("")
    ofe_str = " / ".join(f"{y}={ofe.get(y)}" for y in new_periods)
    L.append(f"- `other_fin_exp_abs`: {ofe_str}  (旧稿维持年报口径平推不写 knob;真实来自 financial_expense.yaml,null 走年报附注 fallback)")
    L.append("")
    L.append("> 完整真实值 JSON 见 fetcher stdout / --out。收入 leaf 量价因子(销量yoy/吨价yoy)不在本表——走第3步声明式估算,非真实 vs 预测。")
    L.append("")

    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"[deviation] written: {out_path}", file=sys.stderr)
    return str(out_path)


def main(argv: list[str] | None = None) -> int:
    # 中文路径走 stdout 需要 UTF-8(CLAUDE.md 编码约定)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    p = argparse.ArgumentParser(
        description="年度更新器·标准线财务数据取数:从 clean_annual + financial_expense.yaml 取 (H,A] 实际值。"
    )
    p.add_argument("--ticker", required=True, help="A 股 ticker,如 002946.SZ")
    p.add_argument("--history-end", required=True, type=int, help="H,旧稿历史末年(如 2024)")
    p.add_argument("--db", default=None, help="data.db 路径(省略则自动定位)")
    p.add_argument("--out", default=None, help="输出 JSON 路径(省略则 stdout)")
    p.add_argument("--extra-fields", default="",
                   help="逗号分隔的 clean_annual 额外字段名(TuShare 官方名)。用于旧稿有、默认 19 条未覆盖的行"
                        "(典型:BS 科目如营运资本/资本开支、行业特有指标)。按 direct 取,core=False 不阻塞。"
                        "带点列名(如 income.xxx)原样传入即可。")
    p.add_argument("--forecast-md", default=None,
                   help="旧核心假设.md 路径。提供则顺带读末尾 knobs 块预测值,和真实值对比,"
                        "输出偏离诊断 md 到 companies/{公司}/Agent/Logs/annual_update_deviation_{YYYYMMDD}_{A}.md")
    args = p.parse_args(argv)

    db = Path(args.db) if args.db else find_db(args.ticker)
    company_dir = company_dir_from_db_path(db)
    con = sqlite3.connect(db)

    # A = clean_annual 最新年(period 列为 TEXT '2024',转 INT 比较)
    row = con.execute("SELECT MAX(CAST(period AS INTEGER)) FROM clean_annual").fetchone()
    A = row[0]
    if A is None:
        _emit({"ticker": args.ticker, "company_dir": str(company_dir), "status": "gap",
               "reason": "clean_annual 为空,先跑 /init + clean.py"}, args.out)
        return 2

    H = args.history_end
    N = A - H
    if N <= 0:
        _emit({"ticker": args.ticker, "company_dir": str(company_dir),
               "history_end": H, "data_end": A, "span_years": 0, "new_periods": [],
               "status": "noop", "reason": f"数据到 {A},旧稿到 {H},已最新无需更新"}, args.out)
        return 0

    new_periods = [str(y) for y in range(H + 1, A + 1)]
    other_fin = load_other_fin_exp(company_dir, new_periods)

    lines: dict[str, dict] = {}
    gaps: list[dict] = []

    for key, kind, field, unit, core in STANDARD_LINES:
        values: dict[str, float | None] = {}
        for y in new_periods:
            if kind == "yaml":
                values[y] = other_fin.get(y)
                if values[y] is None and core:
                    gaps.append({"period": y, "line": key,
                                 "reason": f"financial_expense.yaml 缺 {y} 的 other_fin_exp_abs"})
                continue

            if kind == "tax":
                r = con.execute(
                    "SELECT income_tax, total_profit FROM clean_annual WHERE period=?", (y,)
                ).fetchone()
                it, tp = (r or (None, None))
                if it is None or tp in (None, 0):
                    values[y] = None
                    if core:
                        gaps.append({"period": y, "line": key,
                                     "reason": "income_tax 或 total_profit 缺失/利润总额为 0"})
                else:
                    values[y] = it / tp
                continue

            if kind in ("gpm", "minority", "nincome_margin"):
                if kind == "gpm":
                    r = con.execute(
                        "SELECT revenue, oper_cost FROM clean_annual WHERE period=?", (y,)
                    ).fetchone()
                    rev, oc = (r or (None, None))
                    if rev in (None, 0) or oc is None:
                        values[y] = None
                        if core:
                            gaps.append({"period": y, "line": key, "reason": "revenue 或 oper_cost 缺失"})
                    else:
                        values[y] = (rev - oc) / rev
                elif kind == "minority":
                    r = con.execute(
                        "SELECT minority_gain, n_income FROM clean_annual WHERE period=?", (y,)
                    ).fetchone()
                    mg, ni = (r or (None, None))
                    if mg is None or ni in (None, 0):
                        values[y] = None
                        if core:
                            gaps.append({"period": y, "line": key, "reason": "minority_gain 或 n_income 缺失"})
                    else:
                        values[y] = mg / ni
                else:  # nincome_margin
                    r = con.execute(
                        "SELECT n_income_attr_p, revenue FROM clean_annual WHERE period=?", (y,)
                    ).fetchone()
                    nip, rev = (r or (None, None))
                    if nip is None or rev in (None, 0):
                        values[y] = None
                        if core:
                            gaps.append({"period": y, "line": key, "reason": "n_income_attr_p 或 revenue 缺失"})
                    else:
                        values[y] = nip / rev
                continue

            # direct / ratio:带点列名(如 income.credit_impa_loss)用双引号包
            col = f'"{field}"'
            r = con.execute(
                f"SELECT {col}, revenue FROM clean_annual WHERE period=?", (y,)
            ).fetchone()
            v, rev = (r or (None, None))

            if kind == "direct":
                values[y] = v
                if v is None and core:
                    gaps.append({"period": y, "line": key, "reason": f"{field} 为空"})
            else:  # ratio
                if v is None or rev in (None, 0):
                    values[y] = None
                    if core:
                        gaps.append({"period": y, "line": key,
                                     "reason": f"{field} 或 revenue 为空"})
                else:
                    values[y] = v / rev

        entry: dict = {"unit": unit, "values": values}
        if kind == "ratio":
            entry["formula"] = f"{field}/revenue"
        elif kind == "tax":
            entry["formula"] = "income_tax/total_profit"
        elif kind == "gpm":
            entry["formula"] = "(revenue-oper_cost)/revenue"
        elif kind == "minority":
            entry["formula"] = "minority_gain/n_income"
        elif kind == "nincome_margin":
            entry["formula"] = "n_income_attr_p/revenue"
        elif kind == "yaml":
            entry["source"] = "financial_expense.yaml"
        if field and "." in field:
            entry["field"] = field
        lines[key] = entry

    # 按需扩展:旧稿有、默认 19 条未覆盖的行(典型 BS 科目/行业指标),skill 传字段名统一取
    for fld in args.extra_fields.split(","):
        fld = fld.strip()
        if not fld:
            continue
        values = {}
        for y in new_periods:
            col = f'"{fld}"'
            r = con.execute(f"SELECT {col} FROM clean_annual WHERE period=?", (y,)).fetchone()
            v = (r or (None,))[0]
            values[y] = v
            if v is None:
                gaps.append({"period": y, "line": fld,
                             "reason": f"{fld} 为空(按需扩展字段,非核心不阻塞)"})
        lines[f"extra:{fld}"] = {"unit": "million_cny", "values": values,
                                 "field": fld, "source": "clean_annual(extra)"}

    con.close()

    status = "gap" if gaps else "ok"
    result = {
        "ticker": args.ticker,
        "company_dir": str(company_dir),
        "history_end": H,
        "data_end": A,
        "span_years": N,
        "new_periods": new_periods,
        "status": status,
        "lines": lines,
    }
    if gaps:
        result["gaps"] = gaps
    if args.forecast_md and new_periods:
        _emit_deviation_md(result, args.forecast_md)
    _emit(result, args.out)
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
