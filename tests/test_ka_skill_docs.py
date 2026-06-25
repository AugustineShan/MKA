from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ka_launcher_loads_shared_sources_and_editor_before_materials():
    text = _read(".claude/skills/ka/SKILL.md")

    assert text.index("## 0. 共享真源") < text.index("## 3. 加载核心假设编辑器 skill")
    assert text.index("## 3. 加载核心假设编辑器 skill") < text.index("## 4. 读取最高权重材料")
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "利润表 + 业务层盈利模型裁决器" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "不纳入 `/ka` 数值门" in text
    assert "人工注入例外" in text
    assert "BS/营运资本/现金流人工覆盖" in text
    assert "像投资委员会开会，不像机器审表" in text
    assert "聊天里用会议 memo" in text
    assert "py -m src.ka_prepare" in text
    assert "最高权重材料-放Agent最应对齐的材料" in text
    assert "markdown存储区" in text
    assert "公司判断和最新观点.md" in text
    assert "至少具备 BRKD 产物、已完成 LOAD 产物或 root reference 候选之一" in text
    assert "Agent业务讨论.md" in text
    assert r"companies\{公司}\*_核心假设_load*.md" in text
    assert r"companies\{公司}\*核心假设参考*.md" in text
    assert r"companies\{公司}\*_核心假设_brkd*.md" in text
    assert "模式: alphapai-load" in text
    assert "Agent\\Load\\` 沙箱副本" in text
    assert "模式: load" in text
    assert "没有末尾 ` ```knobs`" in text
    assert "不要再把旧 v19" in text
    assert "当 `/ka` 主工作流" in text


def test_ka_launcher_removes_modify_and_routes_existing_official_draft():
    text = _read(".claude/skills/ka/SKILL.md")

    assert "## 2. 已有正式稿门禁" in text
    assert "/ka 现在不做 modify" in text
    assert "/frontend-edit 或 /adj quick" in text
    assert "/adj incremental" in text
    assert "/annual-update" in text
    assert "/ka 重建" in text
    assert "禁止原地覆盖" in text


def test_ka_launcher_has_time_axis_gate_skeleton_gate_and_passthrough_guard():
    text = _read(".claude/skills/ka/SKILL.md")

    assert "## 8. 三方时间边界对齐" in text
    assert "LOAD 的 vintage 边界不等于官方 horizon" in text
    assert "正常 vintage gap，不是报错、不是脏数据、不是 time-boundary 缺口" in text
    assert "旧预测 vs 新实际的复盘证据" in text
    assert "才举旗或硬停" in text
    assert "显式期必须覆盖所有已知拐点年" in text
    assert "不让分析师手填衰减交接增速" in text
    assert "### 8a. 自动 fade profile" in text
    assert "target_growth = perpetual_growth + 2~4pp" in text
    assert "g1` 显式期利润 CAGR、`g2` fade 期利润 CAGR、`gT` 永续增长" in text
    assert "target_basis: <auto_mature|auto_stable_brand|auto_long_runway|auto_cycle_repair>" in text
    assert "四数必须至少落在三处" in text
    assert "不默认、不平推、不等分析师自己说" in text
    assert "我先把三方时间边界摆一下" in text
    assert "我建议这版核心假设先搭成" in text
    assert "9a. 接缝总账" in text
    assert "9b. 骨架门" in text
    assert "9c. 数值门" in text
    assert "毛利是分线派生还是整体手拍" in text
    assert "## 10. 防静默 passthrough" in text
    assert "候选A" in text
    assert "未采用方去处" in text
    assert "LOAD 的 `knobs` 块和 BRKD 的 draft `knobs` 块" in text
    assert "没有被默认写进正式 knobs 或 `/ka` 待拍板项" in text
    assert "现有 defaults/yaml1 路径" in text


def test_core_assumption_editor_is_slim_comp_source_editor():
    text = _read("skills/核心假设编辑器_skill_v1.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "原始 Excel 模型阅读，交给 `/load`" in text
    assert "原始研报/纪要/PDF/Word 阅读，交给 `/brkd`" in text
    assert "`model_assumption_schema.json`" in text
    assert "`/comp`" in text
    assert "利润表 + 业务层盈利模型裁决器" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "默认按接缝纪律标注“非本层范围”" in text
    assert "人工注入例外" in text
    assert "BS/营运资本/现金流人工覆盖" in text
    assert "所有人机确认点都继承核心纪律 A4 的会议 memo 风格" in text
    assert "聊天为人读，落盘稿为机器读" in text
    assert "最高权重材料 + BRKD/LOAD" in text
    assert "公司根目录 `*_核心假设_load*.md`" in text
    assert "load-vintage" in text
    assert "```knobs" in text


def test_core_assumption_editor_carries_local_ka_decision_guards():
    text = _read("skills/核心假设编辑器_skill_v1.md")

    assert "## 2. 第零件事：锁时间轴四数" in text
    assert "显式期必须覆盖所有已知拐点年" in text
    assert "LOAD vintage gap" in text
    assert "历史模型装载的常态" in text
    assert "正式 KA 的 history_end 跟 `/init`" in text
    assert "## 2.1 自动 fade profile" in text
    assert "用户只负责拍板或要求换成保守/标准/乐观" in text
    assert "不拆第一/第二过渡期，只保留一个 linear fade" in text
    assert "四数至少落在三处" in text
    assert "不默认、不平推、不等分析师自己说" in text
    assert "我先把材料摆齐后的判断说一下" in text
    assert "数值门聊天输出默认压缩成" in text
    assert "## 4. 接缝总账" in text
    assert "旧稿有价值的历史、stash、风险提示不能静默丢掉" in text
    assert "## 5. 骨架门" in text
    assert "毛利是分线派生还是整体手拍" in text
    assert "## 6. 数值门" in text
    assert "收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 可选 BS/营运资本/现金流人工覆盖 -> 中期/terminal" in text
    assert "不得主动新增 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "balance_sheet.revenue_pct.*" in text
    assert "重资产排程、转固时滞或资产 cohort，优先转 `/da`" in text
    assert "年报是 X 光片，不是主材料" in text
    assert "## 8. 防静默 passthrough" in text
    assert "不得整块静默变成 `official knobs`" in text
