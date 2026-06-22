"""从 field_registry 生成 docs/数据格式参考.md。

registry 是唯一真源后,本文档由它派生(不再从 clean.py 字典 + TuShare 官方文档拼),
彻底消除 stale drift。字段按会计序(registry.field_order)列出。

运行:python -m scripts.gen_field_reference
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import clean  # noqa: E402
from src import field_registry as fr  # noqa: E402

OUT = _ROOT / "docs" / "数据格式参考.md"

# registry 顶层 key → (中文报表名, TuShare endpoint, 表内字段数)
STATEMENTS = [
    ("income", "利润表", "income", 86),
    ("balancesheet", "资产负债表", "balancesheet", 150),
    ("cashflow", "现金流量表", "cashflow", 89),
]

# 6 个 QA plug 字段(clean 审计字段,非 TuShare 官方,不在 registry)。
QA_PLUG_ROWS = [
    ("qa_bs_current_asset_plug", "流动资产 bucket 小计残差", "BS 2.1"),
    ("qa_bs_noncurrent_asset_plug", "非流动资产 bucket 小计残差", "BS 2.2"),
    ("qa_bs_current_liab_plug", "流动负债 bucket 小计残差", "BS 3.1"),
    ("qa_bs_noncurrent_liab_plug", "非流动负债 bucket 小计残差", "BS 3.2"),
    ("qa_bs_equity_plug", "权益 bucket 小计残差", "BS 4.1"),
    ("qa_cf_cash_reconcile_plug", "期初期末现金桥接残差", "CF 5.5"),
]


def main() -> None:
    lines: list[str] = []
    lines.append("# MKA clean 数据字段参考")
    lines.append("")
    lines.append("> 本文件由 `scripts/gen_field_reference.py` 从 `src/field_registry.yaml`(全程序会计科目唯一真源)派生。")
    lines.append("> 列出 `clean_annual` / `clean_quarterly` 宽表中全部 325 个官方 TuShare 字段 + 6 个 QA plug 字段的映射关系。")
    lines.append("> 金额单位为**百万元**；总股本/流通股本单位为**百万股**；百分比字段(如 roe)已转换为**小数**。")
    lines.append("")
    lines.append("## 字段统计")
    lines.append("")
    lines.append("| 报表 | 官方字段数 | clean 分类字段数 | 交集 |")
    lines.append("|------|------------|------------------|------|")
    total = 0
    for _key, cn, _ep, n in STATEMENTS:
        lines.append(f"| {cn} | {n} | {n} | {n} |")
        total += n
    lines.append("")
    lines.append("---")
    lines.append("")

    for key, cn, ep, n in STATEMENTS:
        stmt = fr.get_statement(key)
        lines.append(f"## {cn}（{ep}）")
        lines.append("")
        lines.append(f"- 官方文档字段数：{n}")
        lines.append(f"- clean 分类字段数：{n}")
        lines.append(f"- 字段交集：{n}")
        lines.append("")
        lines.append("字段按会计准则序排列(field_registry.field_order):")
        lines.append("")
        lines.append("| 字段名 | 中文科目 | clean 分类 | 分类说明 |")
        lines.append("|--------|----------|------------|----------|")
        for f in stmt.fields:
            cat = f["category"]
            cat_label = stmt.category_labels.get(cat, cat)
            lines.append(f"| `{f['field']}` | {f['label']} | `{cat}` | {cat_label} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 跨端点同名字段
    lines.append("## 跨端点同名字段（pivot 时加前缀消歧）")
    lines.append("")
    lines.append("`credit_impa_loss` 同时存在于 income 和 cashflow,值可能不同,pivot 时拆为两列:")
    lines.append("")
    lines.append("| clean 宽表字段名 | 来源端点 | clean 分类 | 说明 |")
    lines.append("|-------------------|----------|------------|------|")
    is_stmt = fr.get_statement("income")
    cf_stmt = fr.get_statement("cashflow")
    lines.append(f"| `income.credit_impa_loss` | income | `{is_stmt.field_categories['credit_impa_loss']}` | 利润表中的信用减值损失 |")
    lines.append(f"| `cashflow.credit_impa_loss` | cashflow | `{cf_stmt.field_categories['credit_impa_loss']}` | 现金流量表间接法附注中的信用减值损失 |")
    lines.append("")

    # QA plug
    lines.append("## QA plug 字段（clean 阶段审计字段，非 TuShare 官方字段）")
    lines.append("")
    lines.append("季度披露不完整时,`clean.py` 用以下 6 个字段显式收纳残差,确保宽表仍然配平:")
    lines.append("")
    lines.append("| 字段名 | 用途 | 参与校验 |")
    lines.append("|--------|------|----------|")
    for field, use, check in QA_PLUG_ROWS:
        lines.append(f"| `{field}` | {use} | {check} |")
    lines.append("")
    lines.append("年度模式下这些字段正常为 0；季度模式下若不为 0，会在 `clean_warnings` 中留下公式级说明。")
    lines.append("")

    # 宽表列数说明
    lines.append("## 宽表列数说明")
    lines.append("")
    lines.append("`clean_annual` / `clean_quarterly` 宽表的列构成如下：")
    lines.append("")
    lines.append("| 组成 | 数量 | 说明 |")
    lines.append("|------|------|------|")
    lines.append("| `period` | 1 | 期间索引：年度为 `YYYY`，季度为 `YYYYQn` |")
    lines.append(f"| TuShare 官方字段 | {total} | 324 个唯一官方字段中，`credit_impa_loss` 因跨端点同时存在于 `income` 和 `cashflow`，被拆为 `income.credit_impa_loss` 和 `cashflow.credit_impa_loss` 两列，因此官方相关列为 {total} |")
    lines.append("| QA plug 字段 | 6 | 见上一节 |")
    lines.append(f"| **合计** | **{1 + total + 6}** | `period + {total} + 6` |")
    lines.append("")
    lines.append(f"因此，`clean_annual` / `clean_quarterly` 实际输出 **{1 + total + 6} 列**。任何公司某字段历史上全为 0 也会保留该列，确保下游模型可使用统一特征集。")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({total} official fields + 6 QA plugs)")


if __name__ == "__main__":
    main()
