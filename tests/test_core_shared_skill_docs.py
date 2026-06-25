from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_core_discipline_defines_cross_cutting_rules():
    text = _read("skills/核心纪律_skill_v1.md")

    assert "横切纪律单一真源" in text
    assert "library/include" in text
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


def test_core_source_language_defines_shared_comp_grammar():
    text = _read("skills/核心假设源语言_skill_v1.md")

    assert "共享语法单一真源" in text
    assert "library/include" in text
    assert "时间轴/本轮判断锚点 -> 收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 中期/terminal" in text
    assert "上挂: 营业收入" in text
    assert "compiler: factor_product/growth/abs/formula" in text
    assert "三件套" in text
    assert "受限 formula" in text
    assert "formula 只在这些情况可建议" in text
    assert "举手共探" in text
    assert "待回测验证" in text
    assert "formula未采用/待补" in text
    assert "同构 passthrough" in text
    assert "```knobs" in text
    assert "不写 yaml1 path" in text
