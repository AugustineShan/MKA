"""dump_secondary_metrics.py — 从 OfficialBreakdowns 提取副拆分收入/毛利率/同比成 yaml 片段。

供 /comp 翻译副拆分时注入 yaml1 stash，让前端副拆分渲染"收入/毛利率/同比"3 行。
- 毛利率：年报 major_business_profitability.gross_margin_pct（直接拿，不算）
- 同比：年报 revenue_composition.revenue_yoy_pct（直接拿，不算）
- 收入：revenue_composition.revenue_yuan → 百万元

用法：py scripts/dump_secondary_metrics.py "companies/{公司名}_{代码}"
输出 yaml 片段到 stdout。无 breakdown CSV 时 stderr 提示、stdout 空。
"""
import csv
import os
import sys

DIM_CN = {
    "region": "地区",
    "sales_model": "渠道",
    "product": "产品",
    "industry": "行业",
}


def main(argv):
    if len(argv) < 2:
        print("usage: py scripts/dump_secondary_metrics.py <company_dir>", file=sys.stderr)
        return 1
    company_dir = argv[1]
    csv_path = os.path.join(company_dir, "Agent", "OfficialBreakdowns", "business_revenue_breakdown.csv")
    if not os.path.exists(csv_path):
        print(f"# no breakdown csv: {csv_path}", file=sys.stderr)
        return 0  # 不算错，该公司无副拆分数据，comp 自然缺

    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    # data[dim][item] = {revenue:{y:v}, yoy:{y:v}, margin:{y:v}}
    data: dict[str, dict[str, dict]] = {}
    for r in rows:
        dim = r.get("dimension", "")
        if dim not in DIM_CN:
            continue
        item = r.get("item_name", "")
        yr = r.get("year", "")
        if not item or not yr:
            continue
        d = data.setdefault(dim, {}).setdefault(item, {"revenue": {}, "yoy": {}, "margin": {}})
        src = r.get("source_table", "")
        if src == "revenue_composition":
            rev = r.get("revenue_yuan")
            if rev:
                try:
                    d["revenue"][yr] = float(rev) / 1e6
                except ValueError:
                    pass
            yoy = r.get("revenue_yoy_pct")
            if yoy:
                try:
                    d["yoy"][yr] = float(yoy) / 100.0
                except ValueError:
                    pass
        elif src == "major_business_profitability":
            gm = r.get("gross_margin_pct")
            if gm:
                try:
                    d["margin"][yr] = float(gm) / 100.0
                except ValueError:
                    pass

    lines: list[str] = []
    for dim in DIM_CN:  # 固定顺序
        items = data.get(dim)
        if not items:
            continue
        # 只输出有收入数据的 item（毛利率/同比可能缺）
        rev_items = {it: m for it, m in items.items() if m["revenue"]}
        if not rev_items:
            continue
        lines.append(f"副拆分_按{DIM_CN[dim]}:")
        lines.append('  note: "来源年报 revenue_composition + major_business_profitability；不参与营收计算。')
        lines.append('        毛利率/同比由 scripts/dump_secondary_metrics.py 自动提取；年报未披露 major 毛利率的 item 自动缺。"')
        lines.append('  unit: "百万元"')
        lines.append("  series:")
        for it, m in rev_items.items():
            s = ", ".join(f"{y}: {v:.2f}" for y, v in sorted(m["revenue"].items()))
            lines.append(f"    {it}: {{ {s} }}")
        gm_items = {it: m for it, m in rev_items.items() if m["margin"]}
        if gm_items:
            lines.append("  毛利率:")
            lines.append("    series:")
            for it, m in gm_items.items():
                s = ", ".join(f"{y}: {v:.4f}" for y, v in sorted(m["margin"].items()))
                lines.append(f"      {it}: {{ {s} }}")
        yoy_items = {it: m for it, m in rev_items.items() if m["yoy"]}
        if yoy_items:
            lines.append("  同比:")
            lines.append("    series:")
            for it, m in yoy_items.items():
                s = ", ".join(f"{y}: {v:.4f}" for y, v in sorted(m["yoy"].items()))
                lines.append(f"      {it}: {{ {s} }}")
        lines.append("")

    sys.stdout.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
