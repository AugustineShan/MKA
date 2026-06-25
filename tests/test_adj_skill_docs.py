from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_adj_launcher_defines_quick_and_incremental_modes():
    text = _read(".claude/skills/adj/SKILL.md")

    assert "quick" in text
    assert "incremental" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "只拨动已经存在的 knobs 数值" in text
    assert "定点 patch 最新 yaml1" in text
    assert "白名单不可加宽" in text
    assert "核心假设.md` 是 canonical" in text
    assert "yaml1 是派生缓存" in text
    assert "不直接改 yaml1" in text
    assert "py -m src.adj_prepare" in text
    assert "ADJ增量信息（用来改模型的边际信息）" in text
    assert "markdown存储区" in text
    assert "这个不能在 quick 模式直接拨" in text
    assert "py -m src.forecast --yaml1" in text


def test_adj_editor_skill_keeps_quick_narrow_and_incremental_compiled():
    text = _read("skills/核心假设调整器_skill_v1.md")

    assert "/adj quick       = 已有 knobs 的快速数值调整" in text
    assert "/adj incremental = 新增量信息驱动的系统性核心假设更新" in text
    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "用户请求必须能映射到这个清单中的某一项或多项" in text
    assert "白名单不可加宽" in text
    assert "未确认前不写文件" in text
    assert "三处同源" in text
    assert "md 赢" in text
    assert "禁止" in text
    assert "terminal.fade.to_year" in text
    assert "py -m src.adj_prepare" in text
    assert "必须走 `/comp`，不直接 patch yaml1" in text
    assert "unsupported" in text


def test_frontend_edit_routes_structural_changes_to_adj_incremental():
    text = _read(".claude/skills/frontend-edit/SKILL.md")

    assert "/adj incremental + /comp" in text
    assert "请走 /adj incremental 流程" in text
    assert "白名单不可加宽" in text
    assert "核心假设.md` 是 canonical" in text
    assert "md 赢" in text
    assert "必须逐字使用 prompt 给出的路径" in text
    assert "要求前端/用户刷新工作台" in text
    assert "old_value 前置核对" in text
    assert "不是最新" in text
    assert "/ka modify" not in text
