from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_core_discipline_defines_cross_cutting_rules():
    text = _read("skills/核心纪律_skill_v1.md")

    assert "横切纪律单一真源" in text
    assert "library/include" in text
    assert "docs/MKA规则导航图.md" in text
    assert "索引，不是新纪律" in text
    assert "人工筛选门优先于材料吞吐" in text
    assert "看见 markdown 不等于必须吸收" in text
    assert "KA 目录顶层 markdown" in text
    assert "该目录顶层所有 `*.md` 都是 `/ka` 人工筛选入口" in text
    assert "其他 markdown 按信息指引读取" in text
    assert "入口窄，收纳宽" in text
    assert "人工筛选门只限制读取范围，不削弱 A1/A2" in text
    assert "有复盘价值但暂不入模的信息宁可进收纳区/stash" in text
    assert "A0. 操作分流" in text
    assert "A1. 历史基年神圣 + 历史保全" in text
    assert "A2. 接缝铁律" in text
    assert "A3. 对账不是算账" in text
    assert "A4. 押不等于落盘 + 分段停止点" in text
    assert "A5. 参数化先于数值 + 自洽不过定 + 毛利耦合门" in text
    assert "A6. 旋钮值精确完整逐年可机读 + knobs 同源回声" in text
    assert "A7. 派生量预测序列不手算，交引擎" in text
    assert "/brkd" in text
    assert "/load" in text
    assert "/ka" in text
    assert "/annual-update" in text
    assert "来源与裁决" in text
    assert "白名单不可加宽" in text
    assert "核心假设.md` 是 canonical" in text
    assert "yaml1 是派生缓存" in text
    assert "md 赢" in text
    assert "像分析师开会，不像机器审表" in text
    assert "会议 memo" in text
    assert "聊天为人读，文件为机器读" in text
    assert "terminal.fade.target_growth" in text
    assert "reference 晋升路径只有一条" in text
    assert "## 待 /ka 裁决清单" in text


def test_core_source_language_defines_shared_comp_grammar():
    text = _read("skills/核心假设源语言_skill_v1.md")

    assert "共享语法单一真源" in text
    assert "library/include" in text
    assert "docs/核心假设源语言语法规范.md" in text
    assert "docs/MKA规则导航图.md" in text
    assert "reference 裁决回执" in text
    assert "范围边界：默认利润表 + 业务层盈利模型" in text
    assert "BRKD、LOAD、KA 默认收窄" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "不在 `/brkd` 或 `/ka` 中主动裁决" in text
    assert "衰减交接增速: x% / none" in text
    assert "人工注入例外" in text
    assert "BS/营运资本/现金流人工覆盖" in text
    assert "balance_sheet.revenue_pct.*" in text
    assert "balance_sheet.cogs_days.*" in text
    assert "重资产排程优先 `/da`" in text
    assert "BS/现金/债务派生的 `financial expense` 不写" in text
    assert "可选 BS/营运资本/现金流人工覆盖 -> 中期/terminal" in text
    assert "上挂: 营业收入" in text
    assert "compiler: factor_product/growth/abs/formula" in text
    assert "compiler: bs_revenue_pct/bs_cogs_days/bs_scalar_pct" in text
    assert "三件套" in text
    assert "受限 formula" in text
    assert "formula 只在这些情况可建议" in text
    assert "举手共探" in text
    assert "待回测验证" in text
    assert "formula未采用/待补" in text
    assert "同构 passthrough" in text
    assert "```knobs" in text
    assert "target_growth: 0.055" in text
    assert "不写 yaml1 path" in text
    assert "`状态: reference`、`状态: draft`、`状态: model-extracted` 或 `状态: factpack/reference`" in text
    assert "待 /ka 裁决清单" in text
