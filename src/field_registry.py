"""field_registry —— 全程序会计科目与排序的唯一真源 loader。

真源数据:``src/field_registry.yaml``(由 scripts/gen_field_registry.py 一次性生成,
之后人工维护即为真源)。本模块在 import 时解析一次并缓存,向 clean.py(校验分类)与
workbench.py(展示排序/标签)暴露统一接口。

设计见 docs/plans/2026-06-22-field-registry-design.md。day-1 契约:本 loader 派生的
分类/排序/标签与改版前 clean.py、workbench.py 现状逐字段等价(由 tests/test_field_registry_equiv 守)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PATH = Path(__file__).resolve().parent / "field_registry.yaml"
_VERSION = 1

if not _PATH.exists():
    raise RuntimeError(
        f"field_registry 真源缺失: {_PATH}。"
        "请先运行 `python -m scripts.gen_field_registry` 生成。"
    )

_RAW: dict[str, Any] = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
if not isinstance(_RAW, dict) or _RAW.get("version") != _VERSION:
    raise RuntimeError(
        f"field_registry 版本不匹配:期望 version={_VERSION},实际 {_RAW.get('version')!r}"
    )

_STATEMENTS_RAW: dict[str, Any] = _RAW["statements"]


class Statement:
    """单张报表的解析视图。"""

    __slots__ = ("key", "name", "unit", "fields", "field_categories",
                 "field_order", "labels", "category_order", "category_labels",
                 "sub_resolve", "combo_resolve", "total_fields")

    def __init__(self, key: str, raw: dict[str, Any]) -> None:
        self.key = key
        self.name = raw["name"]
        self.unit = raw["unit"]
        # 字段记录(保留全部属性,供 workbench 直接迭代渲染)
        self.fields: list[dict[str, Any]] = raw["fields"]
        self.field_categories: dict[str, str] = {}
        self.field_order: list[str] = []
        self.labels: dict[str, str] = {}
        self.sub_resolve: dict[str, list[str]] = {}
        self.combo_resolve: dict[str, tuple[list[str], str]] = {}
        self.total_fields: set[str] = set()

        for f in self.fields:
            field = f["field"]
            category = f["category"]
            if field in self.field_categories:
                raise RuntimeError(f"字段重复定义: {key}.{field}")
            if "label" not in f or "category" not in f:
                raise RuntimeError(f"字段缺 label/category: {key}.{field}")
            self.field_categories[field] = category
            self.field_order.append(field)
            self.labels[field] = f["label"]
            if "resolve_children" in f:
                self.sub_resolve[field] = list(f["resolve_children"])
            if "combo_of" in f:
                splits = list(f["combo_of"])
                # combo 拆分项共享同一 bucket,取首项的 category 即可。
                first_cat = self.field_categories.get(splits[0])
                if first_cat is None:
                    raise RuntimeError(
                        f"combo {field} 的拆分项 {splits[0]} 未在 {key} 中定义")
                self.combo_resolve[field] = (splits, first_cat)
            if f.get("role") == "total":
                self.total_fields.add(field)

        self.category_order: list[str] = list(raw["category_order"])
        self.category_labels: dict[str, str] = dict(raw["category_labels"])


_INCOME = Statement("income", _STATEMENTS_RAW["income"])
_BALANCESHEET = Statement("balancesheet", _STATEMENTS_RAW["balancesheet"])
_CASHFLOW = Statement("cashflow", _STATEMENTS_RAW["cashflow"])

_BY_KEY: dict[str, Statement] = {
    "income": _INCOME,
    "balancesheet": _BALANCESHEET,
    "cashflow": _CASHFLOW,
}

# ── clean.py 兼容接口(逐字段复刻改版前的模块级常量名) ──────────────
IS_FIELD_CATEGORIES: dict[str, str] = _INCOME.field_categories
BS_FIELD_CATEGORIES: dict[str, str] = _BALANCESHEET.field_categories
CF_FIELD_CATEGORIES: dict[str, str] = _CASHFLOW.field_categories

IS_SUB_RESOLVE: dict[str, list[str]] = _INCOME.sub_resolve
CF_SUB_RESOLVE: dict[str, list[str]] = _CASHFLOW.sub_resolve
COMBO_RESOLVE: dict[str, tuple[list[str], str]] = _BALANCESHEET.combo_resolve

SIGN_QUESTIONABLE_IS_FIELDS: set[str] = {
    f["field"] for f in _INCOME.fields if f.get("sign") == "questionable"
}

# ── workbench.py 兼容接口 ──────────────────────────────────────────
def get_statement(key: str) -> Statement:
    """key ∈ {'is','bs','cf'} 或 {'income','balancesheet','cashflow'}。"""
    if key in _BY_KEY:
        return _BY_KEY[key]
    _ALIAS = {"is": "income", "bs": "balancesheet", "cf": "cashflow"}
    if key in _ALIAS:
        return _BY_KEY[_ALIAS[key]]
    raise KeyError(f"未知报表 key: {key}")


def field_label(field: str, default: str | None = None) -> str:
    """全表字段 → 中文标签(展示层)。找不到返回 default 或字段名本身。"""
    for stmt in _BY_KEY.values():
        if field in stmt.labels:
            return stmt.labels[field]
    return default if default is not None else field


# 全字段标签索引(三表合并,供展示层非报表场景中文化)。
LABELS: dict[str, str] = {}
for _stmt in _BY_KEY.values():
    LABELS.update(_stmt.labels)

# 前端特判为粗体总计的三个 BS 字段。
TOTAL_FIELDS: set[str] = _BALANCESHEET.total_fields


def statement_meta_for_table(table_name: str) -> Statement | None:
    """forecast_is.csv/full_is.csv → income Statement;未知名返回 None。"""
    _TABLE_TO_KEY = {
        "forecast_is.csv": "income", "full_is.csv": "income",
        "forecast_bs.csv": "balancesheet", "full_bs.csv": "balancesheet",
        "forecast_cf.csv": "cashflow", "full_cf.csv": "cashflow",
    }
    key = _TABLE_TO_KEY.get(table_name)
    return _BY_KEY[key] if key else None
