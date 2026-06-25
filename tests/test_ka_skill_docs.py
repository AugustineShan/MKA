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
    assert "py -m src.ka_prepare" in text
    assert "最高权重材料-放Agent最应对齐的材料" in text
    assert "markdown存储区" in text
    assert "公司判断和最新观点.md" in text
    assert "至少具备 BRKD 产物或已完成 LOAD 产物之一" in text
    assert "Agent业务讨论.md" in text
    assert r"companies\{公司}\*_核心假设.md" in text
    assert "Agent\\Load\\` 沙箱副本" in text
    assert "模式: load" in text
    assert "没有末尾 ` ```knobs`" in text
    assert "不要再把旧 `04_核心假设生成修改器_skill_v*.md` 当 `/ka` 主工作流" in text


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
    assert "显式期必须覆盖所有已知拐点年" in text
    assert "9a. 接缝总账" in text
    assert "9b. 骨架门" in text
    assert "9c. 数值门" in text
    assert "毛利是分线派生还是整体手拍" in text
    assert "## 10. 防静默 passthrough" in text
    assert "候选A" in text
    assert "未采用方去处" in text
    assert "LOAD 的 `knobs` 块和 BRKD 的 draft `knobs` 块" in text


def test_core_assumption_editor_is_slim_comp_source_editor():
    text = _read("skills/核心假设编辑器_skill_v1.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "原始 Excel 模型阅读，交给 `/load`" in text
    assert "原始研报/纪要/PDF/Word 阅读，交给 `/brkd`" in text
    assert "`model_assumption_schema.json`" in text
    assert "`/comp`" in text
    assert "最高权重材料 + BRKD/LOAD" in text
    assert "公司根目录 `{原Excel文件名}_核心假设.md`" in text
    assert "load-vintage" in text
    assert "```knobs" in text


def test_core_assumption_editor_carries_local_ka_decision_guards():
    text = _read("skills/核心假设编辑器_skill_v1.md")

    assert "## 2. 第零件事：锁时间轴四数" in text
    assert "显式期必须覆盖所有已知拐点年" in text
    assert "## 4. 接缝总账" in text
    assert "旧稿有价值的历史、stash、风险提示不能静默丢掉" in text
    assert "## 5. 骨架门" in text
    assert "毛利是分线派生还是整体手拍" in text
    assert "## 6. 数值门" in text
    assert "收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 中期/terminal" in text
    assert "年报是 X 光片，不是主材料" in text
    assert "## 8. 防静默 passthrough" in text
    assert "不得整块静默变成 `official knobs`" in text
