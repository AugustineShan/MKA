"""Single source for knob unit conversion across the md ↔ yaml1 ↔ preview layers.

The same knob value is represented three ways (see frontend-edit skill + knobs
契约):
  - yaml1 / forecast engine / frontend preview : decimal   (0.38)
  - 核心假设.md 正文 + knobs block (unit: pct)   : percent   (38)
  - absolute-value knobs (unit: abs_mn)          : as-is, no scaling

The conversion direction used to be reimplemented per layer (fidelity check,
skill prose). Centralising it here means the convention lives once; change the
rule and every layer follows.
"""

from __future__ import annotations

# Canonical unit tokens carried by knobs-block entries.
UNIT_PCT = "pct"
UNIT_ABS = "abs_mn"

# Units whose stored value is a percentage that maps to a decimal by /100.
_PERCENT_UNITS = frozenset({UNIT_PCT})


def is_percent_unit(unit: str | None) -> bool:
    return unit in _PERCENT_UNITS


def to_decimal(value, unit: str | None):
    """Normalise a value declared with ``unit`` to the engine's decimal form.

    pct → value/100; everything else (abs_mn, bare numbers, non-numerics) is
    returned untouched.
    """
    if isinstance(value, (int, float)) and is_percent_unit(unit):
        return value / 100.0
    return value


def to_md_display(value, unit: str | None):
    """Inverse of :func:`to_decimal`: render a decimal as the md/knobs form."""
    if isinstance(value, (int, float)) and is_percent_unit(unit):
        return value * 100.0
    return value
