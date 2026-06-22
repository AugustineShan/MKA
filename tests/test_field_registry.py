"""field_registry 内部一致性守卫。

改版后 registry 是全程序会计科目唯一真源(clean.py 校验 + workbench 渲染 + 数据格式参考.md
都消费它)。本测试锁定其结构不变量,防止日后手改 YAML 引入悬空引用/缺标签/字段数漂移。
"""
from __future__ import annotations

from src import field_registry as fr


def test_statement_counts_match_official():
    """三表字段数 = TuShare 官方数值字段数(income 86 / balancesheet 150 / cashflow 89)。"""
    assert len(fr.IS_FIELD_CATEGORIES) == 86
    assert len(fr.BS_FIELD_CATEGORIES) == 150
    assert len(fr.CF_FIELD_CATEGORIES) == 89


def test_every_field_has_label_and_category():
    for key in ("income", "balancesheet", "cashflow"):
        stmt = fr.get_statement(key)
        for f in stmt.fields:
            assert f["field"] in stmt.labels, f"{key}.{f['field']} 缺 label"
            assert f["category"] in stmt.category_labels, (
                f"{key}.{f['field']} category={f['category']} 不在 category_labels")


def test_resolve_children_reference_real_fields():
    for key in ("income", "balancesheet", "cashflow"):
        stmt = fr.get_statement(key)
        for parent, children in stmt.sub_resolve.items():
            assert parent in stmt.field_categories, f"{key}: resolve parent {parent} 未定义"
            for child in children:
                assert child in stmt.field_categories, (
                    f"{key}: resolve child {child} 未定义")


def test_combo_of_splits_exist_and_share_bucket():
    stmt = fr.get_statement("balancesheet")
    for combo, (splits, bucket) in stmt.combo_resolve.items():
        assert combo in stmt.field_categories, f"combo {combo} 未定义"
        assert stmt.field_categories[combo] == "combo", f"{combo} 非 combo 类"
        for s in splits:
            assert s in stmt.field_categories, f"combo {combo} 拆分项 {s} 未定义"
            assert stmt.field_categories[s] == bucket, (
                f"combo {combo} 拆分项 {s} bucket {stmt.field_categories[s]} ≠ {bucket}")


def test_total_fields_are_subtotals():
    stmt = fr.get_statement("balancesheet")
    assert stmt.total_fields == {"total_assets", "total_liab", "total_liab_hldr_eqy"}
    for f in stmt.total_fields:
        assert stmt.field_categories[f] == "subtotal", f"{f} 非 subtotal"


def test_sign_questionable_subset_of_is():
    assert fr.SIGN_QUESTIONABLE_IS_FIELDS <= set(fr.IS_FIELD_CATEGORIES)
    # 三个减值类科目(符号已带会计含义)
    assert fr.SIGN_QUESTIONABLE_IS_FIELDS == {
        "assets_impair_loss", "credit_impa_loss", "oth_impair_loss_assets"}


def test_credit_impa_loss_drift_fixed():
    """改版前 stale 文档把 credit_impa_loss 归 cost_item;clean.py 真值是 operating_adjustment。
    registry 必须与 clean.py 一致(operating_adjustment),且标签带'减:'前缀。"""
    assert fr.IS_FIELD_CATEGORIES["credit_impa_loss"] == "operating_adjustment"
    assert fr.LABELS["credit_impa_loss"] == "减:信用减值损失"
    # CF 间接法附注里同名科目归 supplementary
    assert fr.CF_FIELD_CATEGORIES["credit_impa_loss"] == "supplementary"


def test_field_order_covers_all_fields():
    """field_order 必须覆盖该报表全部字段,无遗漏无重复。"""
    for key in ("income", "balancesheet", "cashflow"):
        stmt = fr.get_statement(key)
        assert len(stmt.field_order) == len(set(stmt.field_order)), f"{key}: field_order 有重复"
        assert set(stmt.field_order) == set(stmt.field_categories), (
            f"{key}: field_order 与 field_categories 字段集不一致")


def test_category_order_is_display_buckets_without_subtotal():
    """category_order 是展示桶序,不含 subtotal(subtotal 是内联小计,非展示桶)。"""
    for key in ("income", "balancesheet", "cashflow"):
        stmt = fr.get_statement(key)
        assert "subtotal" not in stmt.category_order, f"{key}: subtotal 不该在 category_order"
