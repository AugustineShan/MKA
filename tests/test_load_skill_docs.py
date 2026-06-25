from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_load_launcher_refs_shared_sources_and_keeps_vintage_boundary():
    text = _read(".claude/skills/load/SKILL.md")

    assert "LOAD外部EXCEL模型理解器（一次最多一个）" in text
    assert "{原Excel文件名}_核心假设.md" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "完整继承核心纪律 A1-A7" in text
    assert 'py -m src.model_load prepare "{公司}" --overwrite' in text
    assert "model_boundary.*" in text
    assert "forbidden_materials 沙箱" in text
    assert "公司判断和最新观点不得覆盖模型时间轴" in text
    assert "不做完整 `model_assumption_schema.json`" in text
    assert "主产物写公司根目录" in text
    assert r"companies\{公司}\{原Excel文件名}_核心假设.md" in text
    assert "同步副本写 `Agent/Load/{load_id}/{原Excel文件名}_核心假设.md`" in text
    assert "收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期" in text
    assert "compiler audit" in text
    assert "audit_clean" in text
    assert "不得**运行 `model_load dcf`" in text


def test_model_loader_v3_refs_shared_sources_and_extracts_excel_formula_layer():
    text = _read("skills/模型装载器_skill_v3.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "外部 Excel 模型 -> 核心假设源语言(load-vintage) -> /comp -> yaml1_load" in text
    assert "不生成完整 `model_assumption_schema.json`" in text
    assert "companies/{公司}/{原Excel文件名}_核心假设.md" in text
    assert "Agent/Load/{load_id}/{原Excel文件名}_核心假设.md" in text
    assert "openpyxl(data_only=False)" in text
    assert "history_end_year" in text
    assert "forecast_start_year" in text
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
