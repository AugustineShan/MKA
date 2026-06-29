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
    assert "docs\\MKA规则导航图.md" in text
    assert "不作为裁决证据" in text
    assert "## 3b. 人工筛选门" in text
    assert "看见 markdown 不等于必须吸收" in text
    assert "其他材料只有在用户明确说“这份材料进入本轮判断”时才可读取" in text
    assert "KA 目录顶层全部 markdown" in text
    assert "顶层 `*.md` 就是明确给 `/ka` 看的人工筛选材料" in text
    assert "其他 markdown 按信息指引读取" in text
    assert "## 6b. 读取 KA 目录 markdown 并执行门禁" in text
    assert r"KA（ALPHAPAI拆出来的东西放在这里）\*.md" in text
    assert "reference 候选：文件名以 `核心假设参考` 开头" in text
    assert "信息指引：KA 目录中其他顶层 markdown" in text
    assert "至少具备 BRKD 产物、已完成 LOAD 产物或 KA 目录任一顶层 markdown 之一" in text
    assert "人工筛选门只管入口，不削弱收纳区" in text
    assert "未入模但有复盘价值的信息进入收纳区/stash" in text
    assert "docs/核心假设源语言语法规范.md" in text
    assert "reference 裁决回执" in text
    assert "主导方向" in text
    assert "py -m src.ka_prepare" in text
    assert "最高权重材料-放Agent最应对齐的材料" in text
    assert "markdown存储区" in text
    assert "公司判断和最新观点.md" in text
    assert "重要文件" in text
    assert "凡读公司判断" in text
    assert "当前没有已完成 LOAD 产物、没有 BRKD 产物 Agent业务讨论.md，也没有可读 KA 目录 markdown" in text
    assert "Agent业务讨论.md" in text
    assert "核心假设参考load_*.md" in text
    assert "核心假设参考brkd_*.md" in text
    assert "模式: alphapai-load" in text
    assert "Agent\\Load\\` 沙箱副本" in text
    assert "模式: load" in text
    assert "没有末尾 ` ```knobs`" in text
    assert "## 待 /ka 裁决清单" in text
    assert "缺待 /ka 裁决清单" in text
    assert "采纳入 official / 收纳 / 缺口待补 / 丢弃并说明理由" in text
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


def test_ka_launcher_hands_off_adjudication_to_editor_runbook():
    # 薄启动器：裁决流程（时间轴/接缝/骨架/数值门/防静默/收口）交回编辑器 runbook，
    # launcher 不重复。钉 handoff 指针 + 落盘路径，不钉已在编辑器测试里覆盖的裁决细节。
    text = _read(".claude/skills/ka/SKILL.md")

    assert "进入 `核心假设编辑器_skill_v*.md` 走裁决流程" in text
    # 各裁决步骤的 handoff 索引
    assert "时间轴四数 + 自动 fade profile" in text
    assert "接缝总账" in text
    assert "骨架门（family 必须落在源语言 §B4 可执行集合内，不得自创）" in text
    assert "数值门" in text
    assert "防静默 passthrough" in text
    assert "收口核对与落盘" in text
    # 落盘路径与归档（铁律 1）
    assert r"companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md" in text
    assert "py scripts/ka_archive.py" in text
    assert "禁止原地覆盖" in text
    # 范围/分红率/family/memo 细节已移到编辑器 runbook（见 test_core_assumption_editor_*），launcher 不复述
    assert "利润表 + 业务层盈利模型裁决器" not in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" not in text
    assert "分红率硬例外" not in text
    assert "`balance_sheet.dividend_payout`" not in text
    assert "必须强制检测" not in text
    assert "人工注入例外" not in text
    assert "BS/营运资本/现金流人工覆盖" not in text
    assert "像投资委员会开会，不像机器审表" not in text


def test_ka_launcher_does_not_load_algorithm_contract():
    # /ka 减负：不把 docs/yaml1算法模板契约.md 放进必读的 fenced 加载块；硬规则从源语言 §B4 拿。
    text = _read(".claude/skills/ka/SKILL.md")
    # 只检查 ## 0 下的 ```text 加载块，不拦 §0 散文里的"/comp 读"指针
    sec0 = text.split("## 0. 共享真源", 1)[1].split("## 1.", 1)[0]
    fenced = sec0.split("```text", 1)[1].split("```", 1)[0]
    assert "yaml1算法模板契约" not in fenced
    # 但 family 硬规则指针仍在（指向源语言 §B4）
    assert "源语言 §B4 可执行集合内" in text
    # 契约仅作为"/comp 读"的指针出现一次（散文指针，不进加载块）
    assert text.count("docs/yaml1算法模板契约.md") == 1


def test_core_assumption_editor_is_slim_comp_source_editor():
    text = _read("skills/核心假设编辑器_skill_v1.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "docs/MKA规则导航图.md" in text
    assert "只用于分流和找真源" in text
    assert "原始 Excel 模型阅读，交给 `/load`" in text
    assert "原始研报/纪要/PDF/Word 阅读，交给 `/brkd`" in text
    assert "`model_assumption_schema.json`" in text
    assert "`/comp`" in text
    assert "利润表 + 业务层盈利模型裁决器" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "分红率硬例外" in text
    assert "`balance_sheet.dividend_payout`" in text
    assert "必须强制检测" in text
    assert "默认按接缝纪律标注“非本层范围”" in text
    assert "人工注入例外" in text
    assert "BS/营运资本/现金流人工覆盖" in text
    assert "所有人机确认点都继承核心纪律 A4 的会议 memo 风格" in text
    assert "聊天为人读，落盘稿为机器读" in text
    assert "最高权重材料 + BRKD/LOAD" in text
    assert "`重要文件/` 与公司判断同等权重" in text
    assert "和分析师裁决预测，同时保全已被人工筛选进入本轮的关键历史" in text
    assert "未进入人工筛选入口的材料不主动扩读" in text
    assert "KA 目录顶层全部 `*.md`" in text
    assert "KA 目录任一顶层 markdown" in text
    assert "其他顶层 `*.md`：信息指引" in text
    assert "信息指引 markdown 的文件数和主要线索" in text
    assert "入口窄不等于收纳窄" in text
    assert "未入模但有复盘价值的信息进入收纳区/stash" in text
    assert "markdown 存储区、`WEBCLAUDE` 包、`Agent/Load` 沙箱副本" in text
    assert "KA 目录 `核心假设参考load_*.md`" in text
    assert "`## 待 /ka 裁决清单` 是晋升前议程" in text
    assert "reference 晋升事项逐条处理完毕" in text
    assert "reference 裁决回执" in text
    assert "采纳：转成 official 正文判断" in text
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
    assert "### /init 快速查询索引" in text
    assert "`Agent/core_metrics_overview.{md,json,csv}`" in text
    assert "销售费用率、管理费用率、研发费用率" in text
    assert "`Agent/OfficialBreakdowns/business_revenue_breakdown.csv|jsonl`" in text
    assert "它只证明历史披露口径，不自动给预测" in text
    assert "不强制通读" in text
    assert "可用的 `/init` 快速查询索引" in text
    assert "## 4. 接缝总账" in text
    assert "旧稿有价值的历史、stash、风险提示不能静默丢掉" in text
    assert "出现时优先写入收纳区，确无复盘价值才写丢弃原因" in text
    assert "## 5. 骨架门" in text
    assert "毛利是分线派生还是整体手拍" in text
    assert "## 6. 数值门" in text
    assert "收入 -> 毛利/成本 -> 费用 -> below-OP、税、少数股东 -> 分红率强制检测 -> 可选 BS/营运资本/现金流人工覆盖 -> 中期/terminal" in text
    assert "不得主动新增 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "分红率必须单列去处" in text
    assert "分红率强制检测不等于默认开启人工 BS/CF 覆盖闸" in text
    assert "## 1.1 defaults 审计标识" in text
    assert "顶层 `review_flags`" in text
    assert "defaults 审计 memo" in text
    assert "defaults 为 0、样本不足、latest_outlier、missing_as_zero" in text
    assert "common_dividend_cash=max(c_pay_dist_dpcp_int_exp - fin_exp_int_exp - incl_dvd_profit_paid_sc_ms, 0)" in text
    assert "`family: bs_scalar_pct`、`sub: dividend_payout`、`unit: pct`" in text
    assert "已确认不是 fallback 漏数" in text
    assert "balance_sheet.revenue_pct.*" in text
    assert "重资产排程、转固时滞或资产 cohort，优先转 `/da`" in text
    assert "年报是 X 光片，不是主材料" in text
    assert "## 8. 防静默 passthrough" in text
    assert "不得整块静默变成 `official knobs`" in text
