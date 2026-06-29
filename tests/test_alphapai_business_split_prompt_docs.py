from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read() -> str:
    return (ROOT / "docs/Alphapai/Alphapai业务拆分抓取器.md").read_text(encoding="utf-8")


def test_alphapai_business_split_prompt_is_factpack_not_forecast():
    text = _read()

    assert "模式：`alphapai-business-split`" in text
    assert "状态：`factpack/reference`" in text
    assert "只抓历史事实、口径桥和缺口" in text
    assert "## 待 /ka 裁决清单" in text
    assert "只列口径、缺口、可信度和下一步取证/裁决事项" in text
    assert "禁止写预测、目标价、评级、DCF、terminal、knobs" in text
    assert "禁止: 预测、knobs、DCF、目标价、评级" in text
    assert "没有 `knobs` fenced block" in text
    assert "没有 `horizon`、`terminal`、`perpetual_growth`" in text
    assert "没有未来年份预测候选" in text


def test_alphapai_business_split_prompt_locks_user_main_split():
    text = _read()

    assert "用户指定主拆分或定向取数表必须锁定为事实底稿主轴" in text
    assert "不得把主拆分改成官方披露口径" in text
    assert "官方口径作为副拆分或 sanity check" in text
    assert "行轴必须使用用户指定主拆分" in text
    assert "最近 5 年 × 3 条线就应尝试 15 行" in text


def test_alphapai_business_split_prompt_supports_targeted_leaf_fetch_mode():
    text = _read()

    assert "定向取数模式：按用户 leaf 表逐项找历史" in text
    assert "当用户直接给出一张拆分表" in text
    assert "`部`、`leaf`、`2025-2031 yoy`" in text
    assert "严格按用户表里的 `部` / `leaf` 层级和顺序取数" in text
    assert "未来 yoy、abs、flat 等列只用于识别用户想建模的 leaf" in text
    assert "不得评价、修正或续写这些预测" in text
    assert "主表行轴必须是用户给的 leaf" in text


def test_alphapai_business_split_prompt_requires_bridge_and_full_history_matrix():
    text = _read()

    assert "官方披露 -> 用户主拆分桥表" in text
    assert "公式必须能读懂" in text
    assert "能回勾总量时写清回勾公式" in text
    assert "用户主拆分历史总表" in text
    assert "最近 5 年是完整性重点" in text
    assert "早于最近 5 年的数据不要求齐全" in text
    assert "有意义、有参考价值" in text
    assert "某列未披露就写 `未披露`" in text
    assert "缺哪一年、缺哪条线、缺收入/销量/ASP 哪一项" in text


def test_alphapai_business_split_prompt_makes_auxiliary_splits_optional_and_useful():
    text = _read()

    assert "高价值辅助拆分历史表（可选）" in text
    assert "一个深度、完整、可回勾的主拆分方式" in text
    assert "强于很多种泛泛的辅助拆分" in text
    assert "没有高价值辅助拆分时，可以不写" in text
    assert "不强行展开泛泛副拆分" in text
    assert "产品/价格带/品牌" in text
    assert "地区" in text
    assert "渠道/客户/门店/用户/订单" in text
    assert "口径冲突与裁决备忘" in text
    assert "待 /ka 裁决清单" in text
    assert "缺口写到具体年份、线、指标、来源" in text
