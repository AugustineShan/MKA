from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_annual_update_launcher_uses_shared_sources_and_no_generator_modify_refs():
    text = _read(".claude/skills/annual-update/SKILL.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "完整继承核心纪律 A1-A7" in text
    assert "核心假设源语言的过表顺序" in text
    assert "来源与裁决" in text
    assert "不是 `/adj incremental` 的通用补丁" in text
    assert "年度更新独有条款" in text
    assert "见第4步加载约定" in text
    assert "第98步" not in text
    assert "滚后时间轴确认门" in text
    assert "分析师未确认前" in text
    assert "不得进入估算、不得重定未来、不得写新日期核心假设" in text
    assert "年度更新的人机段要像复盘会，不像滚表日志" in text
    assert "这轮重拨范围你认吗" in text
    assert "生成器 modify" not in text
    assert "→生成器" not in text
    assert "生成器§" not in text


def test_annual_update_editor_refs_shared_sources_and_local_specialization():
    text = _read("skills/年度更新器_skill_v1.md")

    assert "核心纪律_skill_v*.md" in text
    assert "核心假设源语言_skill_v*.md" in text
    assert "完整继承核心纪律 A1-A7" in text
    assert "不是 `/ka`，也不是 `/adj incremental`" in text
    assert "旧稿只读，绝不覆写" in text
    assert "声明式估算三法" in text
    assert "估算·待校准" in text
    assert "收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 中期/terminal" in text
    assert "来源与裁决" in text
    assert "结构性变化" in text
    assert "转 `/adj incremental`" in text
    assert "滚后时间轴确认门" in text
    assert "terminal.fade.target_growth" in text
    assert "按 `/ka` 自动 fade profile 纪律重算" in text
    assert "分析师未确认前，不得估算拿不到的实际" in text
    assert "新稿抬头、进入中期/terminal 前的二次核对" in text
    assert "人机段是年度复盘会，不是滚表日志" in text
    assert "我先对滚后边界和真实偏离" in text
    assert "每个需要重定的块，聊天里只给会议 memo" in text
    assert "生成器 modify" not in text
    assert "→生成器" not in text
    assert "生成器§" not in text
