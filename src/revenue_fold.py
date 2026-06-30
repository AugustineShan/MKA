"""Single source of truth for yaml1 revenue projection.

Both the deterministic forecast path (:mod:`src.yaml1_cleaner`) and the
in-memory workbench preview (:mod:`src.workbench`) fold a yaml1
``income.revenue`` decomposition into per-leaf and total revenue series. They
used to carry **two independent implementations** of the per-family math, which
silently diverged on long-tail company shapes (formula leaves, unknown
families, mis-lengthed knob series, margin-derived gpm). This module holds the
one engine both call.

It is deliberately I/O-free and deterministic: no DB, no LLM, no valuation. It
only knows how to turn a revenue node + horizon into numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.yaml1_formula import FormulaError, FormulaResult
from src.yaml2_schema import plain_value


class Yaml1CleanError(RuntimeError):
    """Raised when yaml1 cannot be folded deterministically.

    Defined here (not in :mod:`src.yaml1_cleaner`) so the fold engine has no
    dependency on the cleaner. ``yaml1_cleaner`` re-exports it, so existing
    ``from src.yaml1_cleaner import Yaml1CleanError`` callers are unaffected.
    """


# ── revenue family registry (single source; see #3) ────────────────────────
# Adding a family means editing this set ONCE. Validators
# (yaml1_fidelity_check, ka_assumption_lint), the exporter
# (company_excel_export) and the workbench preview all import from here.
VOL_PRICE_FAMILIES = frozenset({"vol_price", "vol_price_margin"})
FACTOR_FAMILIES = frozenset({"factor_product", "driver_rate"})
MARGIN_REQUIRED_FAMILIES = frozenset({"vol_price_margin"})
# Families a leaf may declare via ``revenue_family``. ``formula`` is NOT here:
# formula leaves use ``kind: formula`` + ``formula_ref`` instead.
REVENUE_FAMILIES = frozenset(
    {"factor_product", "driver_rate", "vol_price", "vol_price_margin", "growth", "abs"}
)


@dataclass
class LeafProjection:
    """Per-leaf projection result, consumed by both fold callers."""

    name: str
    family: str
    unit_factor: float
    base_revenue: float
    revenue_by_year: dict[int, float]
    volume_by_year: dict[int, float] = field(default_factory=dict)
    margin: list[float] | None = None
    base_volume: float | None = None
    base_price: float | None = None


# ── primitive helpers (moved verbatim from yaml1_cleaner) ───────────────────
def to_float(value: Any, default: float = 0.0) -> float:
    value = plain_value(value)
    if value is None or value == "":
        return default
    try:
        if value != value:  # NaN
            return default
    except TypeError:
        return default
    return float(value)


def product(values: list[float]) -> float:
    out = 1.0
    for value in values:
        out *= value
    return out


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Yaml1CleanError(f"{label} must be a mapping")
    return value


def year_values(values: Any, horizon: list[int], path: str) -> list[float]:
    values = plain_value(values)
    if not isinstance(values, list):
        raise Yaml1CleanError(f"{path} must be a list")
    if len(values) != len(horizon):
        raise Yaml1CleanError(f"{path} length {len(values)} != horizon length {len(horizon)}")
    return [to_float(value) for value in values]


def projection_values(factor: dict[str, Any], horizon: list[int], path: str) -> list[float]:
    base = to_float(factor.get("base"))
    projection_any = factor.get("projection", {"kind": "constant"})
    projection = require_mapping(projection_any, f"{path}.projection")
    kind = str(projection.get("kind", "constant"))

    if kind == "yoy":
        yoy = year_values(projection.get("values"), horizon, f"{path}.projection.values")
        current = base
        values: list[float] = []
        for value in yoy:
            current *= 1.0 + value
            values.append(current)
        return values
    if kind == "abs":
        return year_values(projection.get("values"), horizon, f"{path}.projection.values")
    if kind in {"constant", "hold"}:
        return [base for _ in horizon]
    raise Yaml1CleanError(
        f"Unsupported factor projection at {path}: {kind}. "
        "Supported projection kinds: yoy, abs, constant."
    )


def margin_values(
    segment: dict[str, Any],
    horizon: list[int],
    path: str,
    *,
    required: bool = False,
) -> list[float] | None:
    knobs = segment.get("knobs")
    margin_any: Any = None
    if isinstance(knobs, dict) and "margin" in knobs:
        margin_any = knobs["margin"]
    elif "margin" in segment:
        margin_any = segment["margin"]

    if margin_any is None:
        if required:
            raise Yaml1CleanError(f"{path} uses a margin family but is missing knobs.margin")
        return None
    if isinstance(margin_any, dict):
        if "values" in margin_any:
            margin_any = margin_any["values"]
        else:
            raise Yaml1CleanError(f"{path}.margin must be a list or a mapping with values")
    return year_values(margin_any, horizon, f"{path}.margin")


def _infer_unit_factor_from_text(text: str, warnings: list[dict[str, Any]], path: str) -> float | None:
    match = re.search(r"(?:÷|/)\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    factor = float(match.group(1))
    warnings.append({"stage": "fold", "path": path, "message": f"unit_factor 从文本推断: {factor:g}"})
    return factor


def unit_factor(
    segment: dict[str, Any],
    inherited_note: str,
    path: str,
    warnings: list[dict[str, Any]],
    *,
    default: float | None = None,
) -> float:
    base = require_mapping(segment.get("base"), f"{path}.base")
    if "unit_factor_to_million_cny" in base:
        return to_float(base["unit_factor_to_million_cny"])
    if "unit_factor_to_million_cny" in segment:
        return to_float(segment["unit_factor_to_million_cny"])
    text = "\n".join(str(part) for part in [segment.get("note", ""), inherited_note] if part)
    inferred = _infer_unit_factor_from_text(text, warnings, path)
    if inferred is not None:
        return inferred
    if default is not None:
        # Presentation tolerance: the workbench preview falls back to a default
        # (1.0) so a leaf missing unit_factor still renders. The forecast fold
        # passes no default and raises — forecast must never guess units.
        return default
    raise Yaml1CleanError(f"{path} missing structured unit_factor_to_million_cny")


def _unsupported_revenue_family(path: str, family: Any) -> Yaml1CleanError:
    if family == "formula":
        return Yaml1CleanError(
            f"revenue_family=formula at {path} is not a valid formula shape. "
            "Use kind: formula with formula_ref, and define the node under formulas.nodes."
        )
    return Yaml1CleanError(
        f"Unsupported revenue_family at {path}: {family}. "
        f"Supported families: {', '.join(sorted(REVENUE_FAMILIES))}. "
        "For Formula/DAG use kind: formula with formula_ref."
    )


# ── tree predicates (single source) ────────────────────────────────────────
def is_decomposition_node(node: Any) -> bool:
    """A node sums child segments rather than declaring its own family."""
    if not isinstance(node, dict):
        return False
    if node.get("kind") == "decomposition":
        return True
    return node.get("kind") is None and "segments" in node and "revenue_family" not in node


def iter_leaves(segments: dict[str, Any], prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Flatten a (possibly nested) segments mapping into leaf (name, payload) pairs."""
    leaves: list[tuple[str, dict[str, Any]]] = []
    for key, payload in segments.items():
        if not isinstance(payload, dict):
            continue
        name = f"{prefix}.{key}" if prefix else str(key)
        child_segments = payload.get("segments")
        if is_decomposition_node(payload) and isinstance(child_segments, dict):
            leaves.extend(iter_leaves(child_segments, name))
        else:
            leaves.append((name, payload))
    return leaves


# ── the one per-leaf projector ──────────────────────────────────────────────
def project_leaf(
    name: str,
    segment: dict[str, Any],
    path: str,
    inherited_note: str,
    horizon: list[int],
    warnings: list[dict[str, Any]],
    formula_result: FormulaResult | None = None,
    *,
    default_unit_factor: float | None = None,
) -> LeafProjection:
    """Project one revenue leaf across the horizon. Single source for all families.

    Raises on unknown family, mis-lengthed knob series, and formula leaves with
    no evaluated graph — i.e. it never silently produces wrong numbers.
    ``default_unit_factor`` is a presentation tolerance (see :func:`unit_factor`):
    the forecast fold leaves it None (strict); the preview passes 1.0.
    """
    kind = segment.get("kind")
    if kind == "formula":
        if formula_result is None:
            raise Yaml1CleanError(f"formula revenue node at {path} has no evaluated formula graph")
        forbidden = [key for key in ["revenue_family", "factors"] if key in segment]
        knobs = segment.get("knobs")
        if isinstance(knobs, dict):
            forbidden.extend(key for key in ["revenue_yoy", "revenue_abs", "volume_yoy", "price_yoy"] if key in knobs)
        if forbidden:
            raise Yaml1CleanError(f"formula revenue node at {path} is over-determined by {forbidden}")
        formula_ref = segment.get("formula_ref")
        if not isinstance(formula_ref, str) or not formula_ref:
            raise Yaml1CleanError(f"{path}.formula_ref is required for formula revenue leaf")
        factor = unit_factor(segment, inherited_note, path, warnings, default=default_unit_factor)
        base = require_mapping(segment.get("base"), f"{path}.base")
        base_revenue = to_float(base.get("revenue")) / factor
        try:
            values = formula_result.values(formula_ref)
        except FormulaError as exc:
            raise Yaml1CleanError(str(exc)) from exc
        series = {year: values[idx] / factor for idx, year in enumerate(horizon)}
        formula_result.targets[path] = formula_ref
        return LeafProjection(
            name=name,
            family="formula",
            unit_factor=factor,
            base_revenue=base_revenue,
            revenue_by_year=series,
            margin=margin_values(segment, horizon, path),
        )
    if kind in {"mix_allocation", "allocation"}:
        raise Yaml1CleanError(
            f"{path} uses {kind}, but mix/allocation nodes are not implemented. "
            "Use decomposition sum leaves for now."
        )

    family = segment.get("revenue_family")
    factor = unit_factor(segment, inherited_note, path, warnings, default=default_unit_factor)
    base = require_mapping(segment.get("base"), f"{path}.base")
    series: dict[int, float] = {}
    volume_by_year: dict[int, float] = {}
    margin_required = False
    base_volume: float | None = None
    base_price: float | None = None

    if family in VOL_PRICE_FAMILIES:
        margin_required = family in MARGIN_REQUIRED_FAMILIES
        volume = to_float(base.get("volume"))
        price = to_float(base.get("price"))
        base_volume = volume
        base_price = price
        base_revenue = volume * price / factor
        knobs = require_mapping(segment.get("knobs"), f"{path}.knobs")
        volume_yoy = year_values(knobs.get("volume_yoy"), horizon, f"{path}.knobs.volume_yoy")
        price_yoy = year_values(knobs.get("price_yoy"), horizon, f"{path}.knobs.price_yoy")
        for idx, year in enumerate(horizon):
            volume *= 1.0 + volume_yoy[idx]
            price *= 1.0 + price_yoy[idx]
            volume_by_year[year] = volume
            series[year] = volume * price / factor
    elif family in FACTOR_FAMILIES:
        factors_any = segment.get("factors")
        if not isinstance(factors_any, list) or not factors_any:
            raise Yaml1CleanError(f"{path}.factors must be a non-empty list")
        factor_bases: list[float] = []
        factor_series: list[list[float]] = []
        for index, factor_any in enumerate(factors_any):
            factor_path = f"{path}.factors[{index}]"
            factor_node = require_mapping(factor_any, factor_path)
            factor_bases.append(to_float(factor_node.get("base")))
            factor_series.append(projection_values(factor_node, horizon, factor_path))
        base_revenue = product(factor_bases) / factor
        for idx, year in enumerate(horizon):
            series[year] = product([values[idx] for values in factor_series]) / factor
    elif family == "growth":
        revenue = to_float(base.get("revenue"))
        base_revenue = revenue / factor
        knobs = require_mapping(segment.get("knobs"), f"{path}.knobs")
        revenue_yoy = year_values(knobs.get("revenue_yoy"), horizon, f"{path}.knobs.revenue_yoy")
        for idx, year in enumerate(horizon):
            revenue *= 1.0 + revenue_yoy[idx]
            series[year] = revenue / factor
    elif family == "abs":
        revenue = to_float(base.get("revenue"))
        base_revenue = revenue / factor
        knobs = require_mapping(segment.get("knobs"), f"{path}.knobs")
        revenue_abs = year_values(knobs.get("revenue_abs"), horizon, f"{path}.knobs.revenue_abs")
        for idx, year in enumerate(horizon):
            series[year] = revenue_abs[idx] / factor
    else:
        raise _unsupported_revenue_family(path, family)

    return LeafProjection(
        name=name,
        family=str(family),
        unit_factor=factor,
        base_revenue=base_revenue,
        revenue_by_year=series,
        volume_by_year=volume_by_year,
        margin=margin_values(segment, horizon, path, required=margin_required),
        base_volume=base_volume,
        base_price=base_price,
    )
