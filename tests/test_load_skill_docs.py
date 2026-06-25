from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_load_launcher_refs_shared_sources_and_keeps_vintage_boundary():
    text = _read(".claude/skills/load/SKILL.md")

    assert "LOAD外部EXCEL模型理解器（一次最多一个）" in text
    assert "{原Excel文件名}_核心假设_load{YYYYMMDD}.md" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "完整继承核心纪律 A1-A7" in text
    assert 'py -m src.model_load prepare "{公司}" --overwrite' in text
    assert "model_boundary.*" in text
    assert "forbidden_materials 沙箱" in text
    assert "公司判断和最新观点不得覆盖模型时间轴" in text
    assert "如果 Excel 里有名为 `年度和半年度` 的 sheet，默认只看这个 sheet" in text
    assert "装载范围只限利润表和业务层盈利模型" in text
    assert "禁止为了补 DCF 去读取或导出 `Model-BS` / `DCF`" in text
    assert "`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC`" in text
    assert "显式 thesis 才由 /ka 人工覆盖或 /da 处理" in text
    assert "不做完整 `model_assumption_schema.json`" in text
    assert "主产物写公司根目录" in text
    assert r"companies\{公司}\{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md" in text
    assert "同步副本写 `Agent/Load/{load_id}/{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md`" in text
    assert "时间轴 -> 收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期" in text
    assert "这四个数字至少落在三处" in text
    assert "不默认、不平推、不等分析师自己说" in text
    assert "像分析师开会，不像机器审表" in text
    assert "聊天里先给“口头 memo”，落盘时再写完整 `/comp` 源语言" in text
    assert "不在聊天确认阶段逐条展示 JSON/YAML 风格 `knobs`" in text
    assert "用户要求看完整底稿时可以展开" in text
    assert "compiler audit" in text
    assert "audit_clean" in text
    assert "不得**运行 `model_load dcf`" in text


def test_model_loader_v3_refs_shared_sources_and_extracts_excel_formula_layer():
    text = _read("skills/模型装载器_skill_v3.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "外部 Excel 模型 -> 核心假设源语言(load-vintage) -> /comp -> yaml1_load" in text
    assert "不生成完整 `model_assumption_schema.json`" in text
    assert "companies/{公司}/{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md" in text
    assert "Agent/Load/{load_id}/{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md" in text
    assert "openpyxl(data_only=False)" in text
    assert "如果 Excel 里有名为 `年度和半年度` 的 sheet，默认只看这个 sheet" in text
    assert "只有 `年度和半年度` 明确缺失关键结构时" in text
    assert "禁止因为利润表已经读完，就继续说“还需要 Model-BS/DCF 驱动因素”" in text
    assert "`/load` 不读取、不导出、不预测" in text
    assert "才由 `/ka` 开人工覆盖闸" in text
    assert "重资产 DA/capex 排程优先走 `/da`" in text
    assert "不包括纯 `Model-BS` / `DCF` 驱动表" in text
    assert "只对利润表和业务层盈利模型的重要线识别五件事" in text
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
    assert "A2 接缝铁律" in text
    assert "A5 参数化先于数值" in text
    assert "load-vintage 隔离" in text
    assert "主产物写公司根目录" in text
    assert "沙箱副本写 `Agent/Load/{load_id}/`" in text
    assert "不写正式 `Agent/forecast/`" in text
    assert "compiler audit" in text
    assert "audit_clean" in text
    assert "不得运行 `model_load dcf`" in text
