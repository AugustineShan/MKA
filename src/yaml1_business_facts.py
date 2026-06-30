"""Canonical business fact matrix for yaml1 workbench display.

yaml1 remains flexible and source-shaped. This module is the boundary where
revenue splits, stash splits, history facts, and editable drivers become a
typed view the frontend can render without business-specific guessing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


REGISTRY_PATH = Path(__file__).with_name("business_metric_registry.yaml")
SCHEMA_VERSION = 1
YEAR_RE = re.compile(r"^\d{4}$")
ATTR_YEAR_RE = re.compile(r"^(\d{4})[_-]?(.*)$")
SOURCE_PRIORITY = {"custom": 0, "fallback": 1, "forecast": 2, "derived": 3, "direct": 4}
FORMAT_BY_UNIT = {"ratio": "percent1", "pct": "percent1", "%": "percent1", "physical": "volume", "price": "num2"}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g}"
    return str(value)


def _normalize(value: Any) -> str:
    return re.sub(r"[（）()及与和、/\\\s·_\-:：%]", "", str(value)).lower()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _is_year_key(key: Any) -> bool:
    text = str(key)
    return bool(YEAR_RE.fullmatch(text)) and 1900 < int(text) < 2100


def numeric_year_series(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    out: dict[str, float] = {}
    for year, value in values.items():
        if not _is_year_key(year):
            continue
        numeric = _as_float(value)
        if numeric is not None:
            out[str(year)] = numeric
    return out


def numeric_history_series_map(*sources: Any) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, values in source.items():
            metric = str(key)
            if metric in out:
                continue
            series = numeric_year_series(values)
            if series:
                out[metric] = series
    return out


def _load_metric_registry() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for key, payload in data.items():
        if not isinstance(payload, dict):
            continue
        metric = str(key)
        aliases = [str(item) for item in payload.get("aliases", []) if item is not None]
        registry[metric] = {
            **payload,
            "key": metric,
            "label": _cell(payload.get("label")) or metric,
            "aliases": aliases,
            "format": _cell(payload.get("format")) or FORMAT_BY_UNIT.get(_cell(payload.get("unit")), "num2"),
        }
    return registry


METRIC_REGISTRY = _load_metric_registry()
ALIAS_TO_METRIC = {
    _normalize(alias): key
    for key, payload in METRIC_REGISTRY.items()
    for alias in [key, *(payload.get("aliases") or [])]
    if _normalize(alias)
}


def metric_def_for(raw: Any, warnings: list[dict[str, Any]] | None = None, path: str | None = None) -> tuple[str, dict[str, Any]]:
    text = str(raw)
    if text.startswith("custom:"):
        return text, {
            "key": text,
            "label": text.removeprefix("custom:") or text,
            "aliases": [],
            "unit": None,
            "format": "num2",
            "canonical_priority": "direct",
        }
    normalized = _normalize(text)
    key = ALIAS_TO_METRIC.get(normalized)
    if key:
        return key, METRIC_REGISTRY[key]
    metric = f"custom:{normalized or text}"
    if warnings is not None:
        warnings.append({
            "code": "unknown_metric",
            "message": f"Unrecognized business metric '{text}', kept as {metric}",
            "path": path,
            "severity": "warning",
        })
    return metric, {
        "key": metric,
        "label": text,
        "aliases": [],
        "unit": None,
        "format": "num2",
        "canonical_priority": "direct",
    }


def derived_margin_series(revenue: dict[str, float], cost: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for year, revenue_value in revenue.items():
        cost_value = cost.get(year)
        if cost_value is None or abs(revenue_value) < 1e-9:
            continue
        out[year] = (revenue_value - cost_value) / revenue_value
    return out


def canonical_gross_margin_history(
    history_series: dict[str, dict[str, float]],
    revenue: dict[str, float],
    cost: dict[str, float],
    source_path: str = "history.series",
) -> tuple[dict[str, float], dict[str, Any] | None]:
    direct_key = next((key for key in ("margin", "gross_margin", "gpm") if history_series.get(key)), None)
    direct = history_series.get(direct_key, {}) if direct_key else {}
    derived = derived_margin_series(revenue, cost)
    if direct:
        warnings: list[str] = []
        for year in sorted(set(direct) & set(derived)):
            if abs(direct[year] - derived[year]) > 0.0005:
                warnings.append(f"{year}: direct={direct[year]:.6g}, derived_from_cost={derived[year]:.6g}")
        metric: dict[str, Any] = {
            "values": direct,
            "source": f"{source_path}.{direct_key}",
            "canonical": True,
        }
        if warnings:
            metric["warnings"] = warnings
        return direct, metric
    if derived:
        return derived, {
            "values": derived,
            "source": "derived_from_history_revenue_cost",
            "canonical": True,
            "fallback": True,
        }
    return {}, None


def _empty_view() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "blocks": [], "warnings": []}


def _display_blocks_by_path(display_contract: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    blocks = display_contract.get("blocks") if isinstance(display_contract, dict) else []
    if not isinstance(blocks, list):
        return {}
    return {str(block.get("path")): block for block in blocks if isinstance(block, dict) and block.get("path")}


def _display_for_path(display_blocks: dict[str, dict[str, Any]], path: str) -> dict[str, Any] | None:
    return display_blocks.get(path)


def _role(value: Any, default: str = "reference") -> str:
    text = _cell(value)
    if text in {"primary_model", "primary_attachment", "secondary_split", "reference", "deprecated", "technical"}:
        return text
    if text == "check_only":
        return "reference"
    return default


def _placement(value: Any, default: str = "reference_tab") -> str:
    text = _cell(value)
    if text in {"model_table", "secondary_table", "reference_tab", "technical_tab"}:
        return text
    return default


def _dimension(value: Any, default: str = "other") -> str:
    text = _cell(value)
    if text in {"business_line", "product", "region", "channel", "customer", "metric", "other"}:
        return text
    if text == "subsidiary":
        return "other"
    return default


def _block_shell(path: str, title: str, display: dict[str, Any] | None, *, role: str, placement: str, dimension: str) -> dict[str, Any]:
    return {
        "id": path,
        "path": path,
        "title": _cell((display or {}).get("title")) or title,
        "role": _role((display or {}).get("role"), role),
        "placement": _placement((display or {}).get("placement"), placement),
        "dimension": _dimension((display or {}).get("dimension"), dimension),
        "rows": [],
    }


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("entity_key")), str(row.get("metric"))


def _add_row(block: dict[str, Any], row: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    incoming_values = row.get("values") if isinstance(row.get("values"), dict) else {}
    for existing in block["rows"]:
        if _row_key(existing) != _row_key(row):
            continue
        existing_values = existing.get("values") if isinstance(existing.get("values"), dict) else {}
        conflicts = []
        for year, incoming_value in incoming_values.items():
            current = existing_values.get(year)
            if isinstance(current, (int, float)) and isinstance(incoming_value, (int, float)) and abs(float(current) - float(incoming_value)) > 1e-9:
                conflicts.append(year)
        if conflicts:
            warnings.append({
                "code": "business_fact_conflict",
                "message": f"{block['path']} {row['entity_label']} {row['metric']} has conflicting values for {', '.join(conflicts)}; canonical source kept",
                "path": row.get("source_path"),
                "severity": "warning",
            })
        if SOURCE_PRIORITY.get(str(row.get("value_source")), 0) > SOURCE_PRIORITY.get(str(existing.get("value_source")), 0):
            existing.update(row)
        else:
            for year, value in incoming_values.items():
                existing_values.setdefault(year, value)
            existing["values"] = existing_values
            if row.get("editable_path") and not existing.get("editable_path"):
                existing["editable_path"] = row["editable_path"]
        return
    block["rows"].append(row)


# 价格因子的展示词随 leaf 声明的 base.unit.price 变（件/吨/ARPU/客单价），
# 不再焊死成大宗品口径"吨价"。镜像 volume 侧的单位感知；未声明时回退 registry 默认"单价"。
_PRICE_UNIT_WORD: dict[str, str] = {
    "cny_per_unit": "单价",
    "yuan_per_unit": "单价",
    "cny_per_ton": "吨价",
    "yuan_per_ton": "吨价",
    "arpu": "ARPU",
    "aov": "客单价",
}


def _price_metric_label(metric_key: str, price_unit: str | None) -> str | None:
    """price/price_yoy 按 leaf 声明的价格单位覆盖展示词；其余 metric 返回 None（用 registry 默认）。"""
    if metric_key not in ("price", "price_yoy"):
        return None
    word = _PRICE_UNIT_WORD.get(_cell(price_unit) or "")
    if not word:
        return None
    return f"{word}增长" if metric_key == "price_yoy" else word


def _fact_row(
    *,
    entity_key: str,
    entity_label: str,
    metric: str,
    values: dict[str, float | int | None],
    source_path: str,
    value_source: str,
    editable_path: str | None = None,
    note: str | None = None,
    price_unit: str | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metric_key, metric_def = metric_def_for(metric, warnings, source_path)
    return {
        "entity_key": entity_key,
        "entity_label": entity_label,
        "metric": metric_key,
        "metric_label": _price_metric_label(metric_key, price_unit) or metric_def["label"],
        "values": {str(year): value for year, value in values.items()},
        "unit": metric_def.get("unit"),
        "format": metric_def.get("format") or "num2",
        "source_path": source_path,
        "value_source": value_source,
        "editable_path": editable_path,
        "note": note,
    }


def _editable_rows_by_path(editable_assumptions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("path")): row for row in editable_assumptions if isinstance(row, dict) and row.get("path")}


def _editable_values(row: dict[str, Any] | None) -> dict[str, float]:
    if not row:
        return {}
    out: dict[str, float] = {}
    cells = row.get("cells")
    if not isinstance(cells, list):
        return out
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        year = str(cell.get("year"))
        value = _as_float(cell.get("value"))
        if _is_year_key(year) and value is not None:
            out[year] = value
    return out


def _yoy(values: dict[str, float]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    ordered = sorted(values)
    for year in ordered:
        prev = str(int(year) - 1)
        previous = values.get(prev)
        current = values.get(year)
        denominator = abs(previous) if previous is not None and previous < 0 else previous
        out[year] = (current - previous) / denominator if current is not None and denominator not in (None, 0) else None
    return out


def _compound_absolute(
    history: dict[str, Any],
    growth: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, float]:
    """从历史末值按增长率复利出预测绝对值（销量/单价）。existing 已有的年份保留并作为链上基准。"""
    existing = existing or {}
    out: dict[str, float] = {}
    hist = {
        int(y): float(v)
        for y, v in history.items()
        if _is_year_key(str(y)) and isinstance(v, (int, float))
    }
    if not hist:
        return out
    prev: float | None = hist[max(hist)]
    for y in sorted(int(y) for y in growth if _is_year_key(str(y))):
        ys = str(y)
        if ys in existing or ys in out:
            val = existing.get(ys, out.get(ys))
            if isinstance(val, (int, float)):
                prev = float(val)
            continue
        rate = growth.get(ys)
        if isinstance(rate, (int, float)) and prev is not None:
            prev = prev * (1.0 + float(rate))
            out[ys] = prev
    return out


def _revenue_driver_key(path: str, segment_key: str) -> str:
    prefix = f"income.revenue.{segment_key}."
    return path[len(prefix):] if path.startswith(prefix) else path.rsplit(".", 1)[-1]


def _add_revenue_block(
    blocks: list[dict[str, Any]],
    data: dict[str, Any],
    revenue_view: dict[str, Any] | None,
    display_blocks: dict[str, dict[str, Any]],
    editable_assumptions: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    if not isinstance(revenue_view, dict) or not isinstance(revenue_view.get("segments"), list):
        return
    display = _display_for_path(display_blocks, "income.revenue")
    block = _block_shell("income.revenue", "主拆分 · 业务线", display, role="primary_model", placement="model_table", dimension="business_line")
    editable_by_path = _editable_rows_by_path(editable_assumptions)

    for segment in revenue_view.get("segments", []):
        if not isinstance(segment, dict):
            continue
        key = str(segment.get("key") or segment.get("name") or "")
        label = str(segment.get("name") or key)
        leaf_path = f"income.revenue.segments.{key}"
        history_revenue = segment.get("history_revenues") if isinstance(segment.get("history_revenues"), dict) else {}
        forecast_revenue = segment.get("revenues") if isinstance(segment.get("revenues"), dict) else {}
        revenue_values = {**history_revenue, **forecast_revenue}
        if revenue_values:
            revenue_driver = editable_by_path.get(f"income.revenue.{key}.revenue_abs")
            _add_row(block, _fact_row(
                entity_key=key,
                entity_label=label,
                metric="revenue",
                values=revenue_values,
                source_path=f"{leaf_path}.history.series.revenue",
                value_source="derived",
                editable_path=revenue_driver.get("path") if revenue_driver else None,
                note=_cell(segment.get("note")) or None,
                warnings=warnings,
            ), warnings)

        yoy_driver = editable_by_path.get(f"income.revenue.{key}.revenue_yoy")
        history_numeric = {year: value for year, value in history_revenue.items() if isinstance(value, (int, float))}
        yoy_values = {**_yoy(history_numeric), **(segment.get("yoys") if isinstance(segment.get("yoys"), dict) else {})}
        yoy_values.update(_editable_values(yoy_driver))
        if any(value is not None for value in yoy_values.values()):
            _add_row(block, _fact_row(
                entity_key=key,
                entity_label=label,
                metric="revenue_yoy",
                values=yoy_values,
                source_path=f"{leaf_path}.history.series.revenue",
                value_source="derived",
                editable_path=yoy_driver.get("path") if yoy_driver else None,
                warnings=warnings,
            ), warnings)

        history_cost = segment.get("history_costs") if isinstance(segment.get("history_costs"), dict) else {}
        if history_cost:
            _add_row(block, _fact_row(
                entity_key=key,
                entity_label=label,
                metric="cost",
                values=history_cost,
                source_path=f"{leaf_path}.history.series.cost",
                value_source="direct",
                warnings=warnings,
            ), warnings)

        margin_driver = editable_by_path.get(f"income.revenue.{key}.margin")
        gross_margin_values = {}
        metrics = segment.get("history_metrics") if isinstance(segment.get("history_metrics"), dict) else {}
        gross_margin = metrics.get("gross_margin") if isinstance(metrics.get("gross_margin"), dict) else {}
        if isinstance(gross_margin.get("values"), dict):
            gross_margin_values.update(gross_margin["values"])
            for message in gross_margin.get("warnings") or []:
                warnings.append({
                    "code": "business_fact_conflict",
                    "message": f"{label} gross_margin conflict: {message}; direct margin kept",
                    "path": _cell(gross_margin.get("source")) or f"{leaf_path}.history.series.margin",
                    "severity": "warning",
                })
        elif isinstance(segment.get("history_margins"), dict):
            gross_margin_values.update(segment["history_margins"])
        gross_margin_values.update(_editable_values(margin_driver))
        if gross_margin_values:
            _add_row(block, _fact_row(
                entity_key=key,
                entity_label=label,
                metric="gross_margin",
                values=gross_margin_values,
                source_path=_cell(gross_margin.get("source")) or f"{leaf_path}.history.series.margin",
                value_source="direct" if not gross_margin.get("fallback") else "fallback",
                editable_path=margin_driver.get("path") if margin_driver else None,
                warnings=warnings,
            ), warnings)

        history_series = segment.get("history_series") if isinstance(segment.get("history_series"), dict) else {}
        # 销量/单价：绝对值行（历史 + 预测复利）+ 增长率 _yoy 行（可编辑）。
        # factor_product 的 driver 路径是 ...volume/...price（family=yoy 增长率），
        # vol_price 的是 ...volume_yoy/...price_yoy；两者都路由到 _yoy metric，避免和绝对值历史合并。
        for metric_key in ("volume", "price"):
            driver = editable_by_path.get(f"income.revenue.{key}.{metric_key}") or editable_by_path.get(f"income.revenue.{key}.{metric_key}_yoy")
            growth = _editable_values(driver) if (driver and driver.get("family") == "yoy") else {}
            history = history_series.get(metric_key) if isinstance(history_series.get(metric_key), dict) else {}
            if metric_key == "volume" and isinstance(segment.get("history_volumes"), dict):
                history = {**segment["history_volumes"], **history}
            abs_values: dict[str, Any] = {}
            abs_values.update(history)
            if metric_key == "volume" and isinstance(segment.get("volumes"), dict):
                abs_values.update(segment["volumes"])
            if growth:
                abs_values.update(_compound_absolute(history, growth, abs_values))
            if abs_values:
                _add_row(block, _fact_row(
                    entity_key=key,
                    entity_label=label,
                    metric=metric_key,
                    values=abs_values,
                    source_path=f"{leaf_path}.history.series.{metric_key}",
                    value_source="derived",
                    editable_path=None,
                    price_unit=_cell(segment.get("price_unit")) or None,
                    warnings=warnings,
                ), warnings)
            if growth:
                _add_row(block, _fact_row(
                    entity_key=key,
                    entity_label=label,
                    metric=f"{metric_key}_yoy",
                    values=growth,
                    source_path=(driver.get("path") if driver else None) or f"{leaf_path}.knobs.{metric_key}",
                    value_source="forecast",
                    editable_path=driver.get("path") if driver else None,
                    price_unit=_cell(segment.get("price_unit")) or None,
                    warnings=warnings,
                ), warnings)

        represented_metrics = {"revenue", "revenue_yoy", "cost", "gross_margin", "volume", "price", "volume_yoy", "price_yoy"}
        for raw_metric, values in history_series.items():
            metric_key, _metric_def = metric_def_for(raw_metric, warnings, f"{leaf_path}.history.series.{raw_metric}")
            if metric_key in represented_metrics:
                continue
            if not isinstance(values, dict):
                continue
            _add_row(block, _fact_row(
                entity_key=key,
                entity_label=label,
                metric=metric_key,
                values=values,
                source_path=f"{leaf_path}.history.series.{raw_metric}",
                value_source="direct" if not metric_key.startswith("custom:") else "custom",
                warnings=warnings,
            ), warnings)

    represented = {str(row.get("editable_path")) for row in block["rows"] if row.get("editable_path")}
    for editable in editable_assumptions:
        path = str(editable.get("path") or "")
        if editable.get("group") != "revenue_driver" or path in represented:
            continue
        parts = path.split(".")
        if len(parts) < 4:
            continue
        segment_key = parts[2]
        segment_label = segment_key
        for segment in revenue_view.get("segments", []):
            if isinstance(segment, dict) and str(segment.get("key")) == segment_key:
                segment_label = str(segment.get("name") or segment_key)
                break
        driver = _revenue_driver_key(path, segment_key)
        # 增长率 driver（family=yoy）路由到 _yoy metric，避免和绝对值历史行（volume/price）合并混单位
        if editable.get("family") == "yoy" and not driver.endswith("_yoy"):
            driver = f"{driver}_yoy"
        _add_row(block, _fact_row(
            entity_key=segment_key,
            entity_label=segment_label,
            metric=driver,
            values=_editable_values(editable),
            source_path=path,
            value_source="forecast",
            editable_path=path,
            note=_cell(editable.get("note")) or None,
            warnings=warnings,
        ), warnings)

    if block["rows"]:
        blocks.append(block)


def _series_items(block: dict[str, Any]) -> list[dict[str, Any]]:
    items = block.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("values"), dict)]


def _metric_for_stash_source(source: dict[str, Any], display: dict[str, Any] | None, warnings: list[dict[str, Any]]) -> str:
    display_metric = _cell(display.get("metric")) if display else ""
    if display and display_metric and display_metric != "mixed":
        return str(display["metric"])
    if display and isinstance(display.get("metrics"), list) and "revenue" in display["metrics"] and _cell(source.get("path")) == _cell(display.get("path")):
        return "revenue"
    if display and display.get("role") == "secondary_split" and _cell(source.get("path")) == _cell(display.get("path")):
        return "revenue"
    return metric_def_for(source.get("name"), warnings, _cell(source.get("path")))[0]


def _parse_attr_key(key: str, warnings: list[dict[str, Any]], path: str) -> tuple[str | None, str]:
    match = ATTR_YEAR_RE.match(key)
    if not match:
        return None, metric_def_for(key, warnings, path)[0]
    year, metric_part = match.groups()
    metric = metric_part or "amount"
    return year, metric_def_for(metric, warnings, path)[0]


def _add_stash_source_rows(
    block: dict[str, Any],
    source: dict[str, Any],
    display: dict[str, Any] | None,
    warnings: list[dict[str, Any]],
) -> None:
    if source.get("type") == "attr_table":
        by_entity_metric: dict[tuple[str, str, str], dict[str, float | None]] = {}
        for item in _series_items(source):
            entity_key = str(item.get("key") or item.get("label") or "")
            entity_label = str(item.get("label") or entity_key)
            for raw_key, raw_value in item.get("values", {}).items():
                year, metric = _parse_attr_key(str(raw_key), warnings, _cell(source.get("path")) or block["path"])
                if not year:
                    continue
                value = _as_float(raw_value)
                by_entity_metric.setdefault((entity_key, entity_label, metric), {})[year] = value
        for (entity_key, entity_label, metric), values in by_entity_metric.items():
            _add_row(block, _fact_row(
                entity_key=entity_key,
                entity_label=entity_label,
                metric=metric,
                values=values,
                source_path=_cell(source.get("path")) or block["path"],
                value_source="direct",
                note=_cell(source.get("note")) or None,
                warnings=warnings,
            ), warnings)
        return

    metric = _metric_for_stash_source(source, display, warnings)
    for item in _series_items(source):
        values = {year: _as_float(value) for year, value in item.get("values", {}).items() if _is_year_key(year)}
        if not values:
            continue
        _add_row(block, _fact_row(
            entity_key=str(item.get("key") or item.get("label") or ""),
            entity_label=str(item.get("label") or item.get("key") or ""),
            metric=metric,
            values=values,
            source_path=_cell(source.get("path")) or block["path"],
            value_source="direct",
            note="\n".join(filter(None, [_cell(source.get("note")), _cell(item.get("note"))])) or None,
            warnings=warnings,
        ), warnings)


def _add_stash_blocks(
    blocks: list[dict[str, Any]],
    stash_view: list[dict[str, Any]],
    display_blocks: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    for stash in stash_view:
        if not isinstance(stash, dict):
            continue
        path = _cell(stash.get("path"))
        if not path:
            continue
        display = _display_for_path(display_blocks, path)
        role = "reference"
        placement = "reference_tab"
        dimension = "other"
        if display:
            role = _role(display.get("role"), role)
            placement = _placement(display.get("placement"), placement)
            dimension = _dimension(display.get("dimension"), dimension)
        block = _block_shell(path, _cell(stash.get("name")) or path, display, role=role, placement=placement, dimension=dimension)
        _add_stash_source_rows(block, stash, display, warnings)
        extras = stash.get("extras")
        if isinstance(extras, list):
            for extra in extras:
                if isinstance(extra, dict):
                    extra_display = _display_for_path(display_blocks, _cell(extra.get("path"))) or display
                    _add_stash_source_rows(block, extra, extra_display, warnings)
        if block["rows"]:
            blocks.append(block)


def _warn_missing_display_metrics(blocks: list[dict[str, Any]], display_contract: dict[str, Any] | None, warnings: list[dict[str, Any]]) -> None:
    display_blocks = display_contract.get("blocks") if isinstance(display_contract, dict) else []
    if not isinstance(display_blocks, list):
        return
    rows_by_path = {block["path"]: block["rows"] for block in blocks}
    for display in display_blocks:
        if not isinstance(display, dict):
            continue
        path = _cell(display.get("path"))
        if not path:
            continue
        metrics = []
        if display.get("metric") and str(display.get("metric")) != "mixed":
            metrics.append(str(display["metric"]))
        if isinstance(display.get("metrics"), list):
            metrics.extend(str(item) for item in display["metrics"] if str(item) != "mixed")
        if not metrics:
            continue
        row_metrics = {row.get("metric") for row in rows_by_path.get(path, [])}
        for metric in metrics:
            metric_key, _metric_def = metric_def_for(metric)
            if row_metrics and metric_key in row_metrics:
                continue
            warnings.append({
                "code": "display_metric_missing",
                "message": f"display declares metric '{metric}' for {path}, but no business fact row was extracted",
                "path": path,
                "severity": "warning",
            })


def build_business_fact_view(
    data: dict[str, Any],
    *,
    revenue_view: dict[str, Any] | None = None,
    stash_view: list[dict[str, Any]] | None = None,
    display_contract: dict[str, Any] | None = None,
    editable_assumptions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_view()
    warnings: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    display_blocks = _display_blocks_by_path(display_contract)
    _add_revenue_block(blocks, data, revenue_view, display_blocks, editable_assumptions or [], warnings)
    _add_stash_blocks(blocks, stash_view or [], display_blocks, warnings)
    _warn_missing_display_metrics(blocks, display_contract, warnings)
    return {"schema_version": SCHEMA_VERSION, "blocks": blocks, "warnings": warnings}
