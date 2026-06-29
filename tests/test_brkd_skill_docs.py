from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_brkd_launcher_is_thin_and_hands_off_to_runbook():
    # 薄启动器：启动机械内联，理解流程（范围/输入/模式/输出/纪律/memo）交回 runbook。
    text = _read(".claude/skills/brkd/SKILL.md")

    # 启动机械
    assert "BRKD业务理解器（研报和纪要放在这里）" in text
    assert "py -m src.brkd_prepare" in text
    assert "py -m src.ka_prepare" in text
    assert "markdown存储区" in text
    assert "人工放入本轮的源文件" in text
    assert "只读本次 BRKD markdown 存储区" in text
    assert "不主动扩读其他 markdown cache" in text
    assert "重要文件" in text
    assert "AI 不直接读取这些源文件" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "A1/A2/A3/A7" in text
    assert "Agent业务讨论.md" in text
    assert "核心假设参考brkd_{运行YYYYMMDD}.md" in text
    assert r"KA（ALPHAPAI拆出来的东西放在这里）" in text
    assert "不得命名为普通 `*_核心假设.md`" in text
    assert "年报是 X 光片" in text
    # handoff：理解流程交给 runbook，launcher 不再内联复述
    assert "业务预理解器_skill_v*.md" in text
    assert "理解流程" in text
    assert "主导方向" in text
    # 范围/纪律细节已移到 runbook（见 test_business_preunderstanding_v3_*），launcher 不复述
    assert "利润表 + 业务层盈利模型理解器" not in text
    assert "不编造量价原子" not in text
    assert "是否升格为 `/ka` 的人工 BS/CF 覆盖，只能由最高权重材料或分析师明示触发" not in text


def test_business_preunderstanding_v3_outputs_comp_style_draft():
    text = _read("skills/业务预理解器_skill_v3.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "docs/核心假设源语言语法规范.md" in text
    assert "markdown存储区" in text
    assert "`核心假设.md` 的半成品" in text
    assert "核心假设参考brkd_{运行YYYYMMDD}.md" in text
    assert "draft" in text
    assert "不锁定最终时间轴" in text
    assert "第一幕 overview 必须先报这些时间线索" in text
    assert "时间线索：材料年份、历史事实区间、建议 horizon" in text
    assert "像分析师开会，不像机器审表" in text
    assert "业务理解会议 memo" in text
    assert "确认后，文件里仍按下面模板写全历史事实" in text
    assert "headline 财务事实" in text
    assert "Agent/OfficialBreakdowns" in text
    assert "标准财务率历史少写，业务拆分历史多写" in text
    assert "产品、品牌、价格带、地区、渠道、客户、门店、用户、订单、产能、销量、吨价/客单价/ARPU" in text
    assert "主建模拆分必须有历史表" in text
    assert "官方披露 -> 建模拆分" in text
    assert "只保留已筛选材料中确有信息量的副拆分历史表" in text
    assert "不为了凑数量主动外扩材料" in text
    assert "主建模拆分历史总表" in text
    assert "官方披露到建模线的桥" in text
    assert "标准财务率历史来自 /init，本节只做 headline 校验" in text
    assert "忠实记录人工放入本轮 BRKD 素材包的业务材料，不是做预测" in text
    assert "不主动扩读其他 markdown cache" in text
    assert "不允许静默忽略" in text
    assert "利润表 + 业务层盈利模型理解器" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "不在 BRKD 中裁决" in text
    assert "同权重判断材料" in text
    assert "凡读公司判断" in text
    assert "factor_product" in text
    assert "growth" in text
    assert "abs below-OP" in text
    assert "BS/现金/债务派生的 `financial expense` 不写" in text
    assert "other_fin_exp_abs" in text
    assert "待 /ka 拍板" in text
    assert "## 待 /ka 裁决清单" in text
    assert "BRKD 交给 `/ka` 的晋升议程" in text
    assert "| 事项 | 候选值/方向 | 证据 | 分歧/缺口 | 建议处理 |" in text
    assert "```knobs" in text
    # 从 launcher 移交过来的纪律钉点（launcher 瘦身后由 runbook 单详源持有）
    assert "不编造量价原子" in text
    assert "不生成 YAML1、DCF 或完整 `model_assumption_schema.json`" in text
