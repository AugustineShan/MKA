from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_load_launcher_is_thin_and_hands_off_to_runbook():
    # 薄启动器：启动机械内联，理解流程（边界/Excel读法/overview/源语言写法/停止条件）交回 runbook。
    # /load 止于核心假设参考 markdown，不编译 yaml1、不跑 DCF。
    text = _read(".claude/skills/load/SKILL.md")

    # 启动机械
    assert "LOAD外部EXCEL模型理解器（一次最多一个）" in text
    assert "核心假设参考load_{运行YYYYMMDD}.md" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "完整继承核心纪律 A1-A7" in text
    assert 'py -m src.model_load prepare "{公司}" --overwrite' in text
    assert "主产物写 KA 参考稿区" in text
    assert r"companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\核心假设参考load_{运行YYYYMMDD}.md" in text
    # handoff：理解流程交给 runbook
    assert "模型装载器_skill_v*.md" in text
    assert "理解流程" in text
    assert "主导方向" in text
    # 细节已移到 runbook（见 test_model_loader_v3_*），launcher 不复述
    assert "像分析师开会，不像机器审表" not in text
    assert "这四个数字至少落在三处" not in text
    assert "禁止为了补 DCF 去读取或导出 `Model-BS` / `DCF`" not in text
    # /load 止于 markdown：不编译、不跑 DCF
    assert "yaml1_load" not in text
    assert "沙箱 DCF" not in text
    assert "model_load dcf" not in text


def test_model_loader_v3_refs_shared_sources_and_extracts_excel_formula_layer():
    text = _read("skills/模型装载器_skill_v3.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "外部 Excel 模型 -> 核心假设源语言(load-vintage)" in text
    assert "-> /comp -> yaml1_load" not in text
    assert "不生成完整 `model_assumption_schema.json`" in text
    assert "companies/{公司}/Skills素材包/KA（ALPHAPAI拆出来的东西放在这里）/核心假设参考load_{运行YYYYMMDD}.md" in text
    assert "Agent/Load/{load_id}/核心假设参考load_{运行YYYYMMDD}.md" in text
    assert "openpyxl(data_only=False)" in text
    assert "如果 Excel 里有名为 `年度和半年度` 的 sheet，默认只看这个 sheet" in text
    assert "只有 `年度和半年度` 明确缺失关键结构时" in text
    assert "禁止因为利润表已经读完，就继续说“还需要 Model-BS/DCF 驱动因素”" in text
    assert "`/load` 不读取、不导出、不预测" in text
    assert "才由 `/ka` 开人工覆盖闸" in text
    assert "重资产 DA/capex 排程优先走 `/da`" in text
    assert "不包括纯 `Model-BS` / `DCF` 驱动表" in text
    assert "只对利润表和业务层盈利模型的重要线识别五件事" in text
    assert "若模型内已经有业务拆分历史或副拆分，必须按 load-vintage 保真搬运" in text
    assert "收入、销量/件数、ASP/价格、单位、口径、source range" in text
    assert "`/load` 不像 BRKD/Alphapai 那样外部补齐 2-3 种副拆分" in text
    assert "模型内业务拆分历史" in text
    assert "不要打开 DCF 表抽 WACC、股本、FCFF 终值、DA、CAPEX、CWC" in text
    assert "显式 thesis 才由 /ka 人工覆盖或 /da 处理" in text
    assert "history_end_year" in text
    assert "forecast_start_year" in text
    assert "时间轴四数至少落在三处" in text
    assert "不默认、不平推、不等分析师自己说" in text
    assert "像分析师开会，不像机器审表" in text
    assert "不要在确认阶段整段倾倒完整 markdown" in text
    assert "### 聊天确认稿 vs 落盘稿" in text
    assert "会议 memo" in text
    assert "用户明确要看完整底稿时" in text
    assert "衰减期: YYYY / N年 / 模型未给" in text
    assert "永续增长: x% / 模型未给" in text
    assert "A1 历史保全" in text
    assert "如果模型直接给了业务历史表，必须保留可供 `/ka` 复盘的关键原子" in text
    assert "### 待 /ka 裁决清单" in text
    assert "模型理解晋升到 official 前的会议议程" in text
    assert "BS/CF/DCF 线索若出现，只能写成“收纳/分流建议”" in text
    assert "A2 接缝铁律" in text
    assert "A5 参数化先于数值" in text
    assert "load-vintage 隔离" in text
    assert "主产物写 KA 参考稿区" in text
    assert "沙箱副本写 `Agent/Load/{load_id}/`" in text
    assert "不写正式 `Agent/forecast/`" in text
    # /load 止于核心假设参考 markdown，不编译 yaml1、不跑 DCF
    assert "不编译 `yaml1`、不跑 DCF" in text
    assert "compiler audit" not in text
    assert "audit_clean" not in text
    assert "model_load dcf" not in text
    # 从 launcher 移交过来的纪律钉点（launcher 瘦身后由 runbook 单详源持有）
    assert "forbidden_materials 沙箱" in text
    assert "同权重判断材料（公司判断和最新观点 + 重要文件）不得覆盖模型时间轴" in text
    assert "凡读公司判断必须等权重看" in text
    assert "model_boundary.*" in text
    assert "时间轴 -> 收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期" in text
    assert "保真装载业务结构与历史，不是搬运预测" in text
