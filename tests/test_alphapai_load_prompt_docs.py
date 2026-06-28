from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    return (ROOT / "docs/Alphapai/Alphapai-load核心假设参考提示词.md").read_text(encoding="utf-8")


def test_alphapai_load_prompt_keeps_reference_boundary_and_time_axis_discipline():
    text = _read()

    assert "模式：`alphapai-load`" in text
    assert "状态：`reference`" in text
    assert "不可直接编译" in text
    assert "先会议 memo，后完整参考稿" in text
    assert "不要第一轮直接输出完整 `核心假设参考.md`" in text
    assert "像分析师开会一样" in text
    assert "这个理解方向可以吗？确认后我再输出完整 `核心假设参考.md`" in text
    assert "时间轴四数是参考候选，不是拍板结果" in text
    assert "显式期不能机械默认 5 年" in text
    assert "总览只是导读，不能替代后面 4.4-4.9 的结构化候选" in text
    assert "建议衰减期至: {YYYY / 待裁决}" in text
    assert "永续增长候选: {x% / 待裁决}" in text
    assert "可用于 /ka 建模的业务拆分历史" in text
    assert "第一轮只输出会议 memo 并等待确认" in text
    assert "用户确认后，第二轮直接输出完整 `核心假设参考.md`" in text


def test_alphapai_load_prompt_keeps_bs_cf_and_knobs_boundaries():
    text = _read()

    assert "BS/CF 硬边界" in text
    assert "不得自行判断它们是核心 thesis" in text
    assert "本节只收纳，不预测，不给逐年候选，不进 `knobs`" in text
    assert "可能的 BS/CF thesis，待人工判断是否走 /da 或专门流程" in text
    assert "`family` 在这里是语义标签，不是 YAML1 path" in text
    assert "只允许以下保守 family" in text
    assert "`bs_revenue_pct`" not in text
    assert "`bs_cogs_days`" not in text
    assert "`bs_scalar_pct`" not in text
    assert "示例年份和值没有被照抄" in text
    assert "不得照抄年份和值" in text


def test_alphapai_load_prompt_prioritizes_business_split_history_for_ka():
    text = _read()

    assert "Alphapai业务拆分抓取器" in text
    assert "模式: alphapai-business-split" in text
    assert "状态: factpack/reference" in text
    assert "必须优先承接该 factpack 的主拆分、桥表、副拆分和缺口" in text
    assert "不得重新发明业务口径" in text
    assert "用户指定主拆分" in text
    assert "不得降级成官方更容易披露的口径" in text
    assert "## 2.1 本稿最稀缺资产：业务拆分历史" in text
    assert "非标准业务拆分的历史数值" in text
    assert "最近 5 年是完整性重点" in text
    assert "早于最近 5 年的数据不要求齐全" in text
    assert "产品、品牌、价格带、地区、渠道、客户、门店、用户、订单、产能、销量、吨价/客单价/ARPU" in text
    assert "主建模拆分历史总表" in text
    assert "官方披露到建模线的桥" in text
    assert "一个深度完整的主拆分方式强于多张浅表辅助拆分" in text
    assert "业务拆分历史比财务率历史更细" in text
    assert "毛利率/费用率历史保持精简" in text


def test_alphapai_load_prompt_consumes_business_split_factpack_without_soft_downgrade():
    text = _read()

    assert "## 0.2 与 Alphapai业务拆分抓取器的分工" in text
    assert "Alphapai业务拆分抓取器` 是上游 factpack，只抓历史业务拆分，不写预测" in text
    assert "本 Alphapai-load 是下游 reference 稿" in text
    assert "必须把 factpack 的 `用户指定主拆分` 或定向 leaf 表作为 4.4 收入拆分候选的主轴" in text
    assert "如果 factpack 是定向取数模式" in text
    assert "未来 yoy 列只作为用户建模意图上下文" in text
    assert "可以把更稳健的官方两分法或其他披露口径放入“来源与裁决”或 sanity check" in text
    assert "不能替代用户指定主拆分" in text
    assert "factpack 的桥表、主拆分历史总表、高价值辅助拆分和缺口已被承接" in text
    assert "没有为了凑数量强行写泛泛副拆分" in text


def test_rating_report_distiller_collects_business_split_appendix_for_ka():
    text = (ROOT / "docs/Alphapai/评级报告Alphapai蒸馏器.md").read_text(encoding="utf-8")

    assert "供 /ka 建模的业务拆分事实底稿" in text
    assert "非标准业务拆分历史数值" in text
    assert "二点五、/ka 建模业务拆分历史附录" in text
    assert "主建模拆分历史总表" in text
    assert "官方披露到建模线的口径桥" in text
    assert "高价值辅助拆分历史表" in text
    assert "利润表毛利率、销售/管理/研发费用率等财务率历史只需最近一年" in text
