from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    return (ROOT / "docs/技能简要分类.md").read_text(encoding="utf-8")


def test_skill_classification_doc_covers_active_entrypoints():
    text = _read()
    opening = text[:700]

    assert "STOP" in opening
    assert "先判斜杠路由，再选择任何外部技能" in opening
    assert "/ka 002568" in opening
    assert "即使公司名或股票代码像证券问题" in opening

    for skill in [
        "/init",
        "/brkd",
        "/load",
        "/webload",
        "/ka",
        "/comp",
        "/adj quick",
        "/adj incremental",
        "/frontend-edit",
        "/annual-update",
        "/da",
    ]:
        assert skill in text

    assert "Alphapai-load prompt" in text
    assert "Alphapai业务拆分抓取器" in text
    assert "docs/Alphapai/Alphapai业务拆分抓取器.md" in text
    assert "docs/Alphapai/Alphapai-load核心假设参考提示词.md" in text
    assert "不是本地启动器" in text
    assert "只抓历史 factpack" in text
    assert "不写预测、不写 knobs、不写 terminal" in text
    assert "定向 leaf 表" in text
    assert "最近 5 年完整性优先" in text
    assert "核心假设参考load_{YYYYMMDD}.md" in text
    assert "核心假设参考alphapai_{YYYYMMDD}.md" in text
    assert "核心假设.md 是判断源头" in text
    assert "yaml1" in text
    assert "Agent/forecast/" in text


def test_skill_classification_doc_names_shared_sources_and_boundaries():
    text = _read()

    assert "skills/核心纪律_skill_v1.md" in text
    assert "skills/核心假设源语言_skill_v1.md" in text
    assert "docs/核心假设源语言语法规范.md" in text
    assert "docs/核心假设翻译IR契约.md" in text
    assert "docs/MKA规则导航图.md" in text
    assert "规则导航图" in text
    assert "不替代真源" in text
    assert "斜杠词优先是 MKA 路由" in text
    assert "`/ka 百润股份`" in text
    assert "`/ka 002568`" in text
    assert "不是行情查询" in text
    assert "只有用户明确说“查行情/股价/涨停/分时/盘面/资金”" in text
    assert "人工筛选门" in text
    assert "markdown 存储区是 cache，不是证据入口" in text
    assert "看见 markdown 不等于必须吸收" in text
    assert "KA 目录顶层 markdown" in text
    assert "顶层所有 `*.md` 都会被 `/ka` 读取" in text
    assert "其他 markdown 按信息指引读取" in text
    assert "入口窄，收纳宽" in text
    assert "有复盘价值但暂不入模的信息宁可进收纳区/stash" in text
    assert "docs/knobs块契约.md" in text
    assert "skills/yaml1compiler_v5.md" in text
    assert "BS/CF/DCF" in text
    assert "重资产 DA/CAPEX" in text
    assert "时间轴" in text
    assert "knobs 同源" in text
