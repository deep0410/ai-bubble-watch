"""Indicator 1: noise-tolerant capex bearish scoring."""

from __future__ import annotations

RISING_WORDS = (
    "raise",
    "raised",
    "raising",
    "increase",
    "increasing",
    "soar",
    "soaring",
    "approach or exceed",
    "above $1",
    "exceed",
    "escalat",
)
CUTTING_WORDS = (
    "cut",
    "cutting",
    "trim",
    "trimmed",
    "lower",
    "lowered",
    "reduce",
    "reducing",
    "scale back",
    "scaled back",
    "pause",
    "cancel",
)


def capex_bearish(new_val: float, prev_val: float, evidence_text: str) -> bool:
    """Bearish only on a material (>5%) drop confirmed by cutting language, not rising narrative."""
    if prev_val <= 0:
        return False
    ev = evidence_text.lower()
    rising = any(w in ev for w in RISING_WORDS)
    cutting = any(w in ev for w in CUTTING_WORDS)
    material_drop = (prev_val - new_val) / prev_val > 0.05
    return material_drop and cutting and not rising
