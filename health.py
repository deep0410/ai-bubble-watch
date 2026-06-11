"""Market health score: one number, 0-10.

10 = fully stable. 1 = crashing. 0 = crashed (the 30%+ event happened).
Drawdown is ground truth and dominates; indicators, unemployment, and news
adjust around it.

Penalties (clamped 1..10 unless crashed):
  S&P drawdown   >-3% : 0   -3..-7%: 1   -7..-12%: 2   -12..-20%: 4   -20..-30%: 6
                 <=-30%: score = 0 (CRASHED)   <=-25%: capped at 1 (CRASHING)
  Bearish health indicators (0-5): -1 each, capped at -3
  Headline unemployment uptrend confirmed: -1
  White-collar AI-mechanism firing: -1
  News/status escalated to ELEVATED: -1
"""

from __future__ import annotations

from typing import Any

LABELS = {
    (8, 10): "stable",
    (5, 7): "strained",
    (2, 4): "deteriorating",
    (1, 1): "crashing",
    (0, 0): "crashed",
}


def _dd_penalty(dd: float) -> int:
    if dd > -3:
        return 0
    if dd > -7:
        return 1
    if dd > -12:
        return 2
    if dd > -20:
        return 4
    return 6


def health_score(
    sp_drawdown_pct: float,
    bearish_count: int,
    unemployment: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    if sp_drawdown_pct <= -30:
        return {"score": 0, "label": "crashed"}

    score = 10
    score -= _dd_penalty(sp_drawdown_pct)
    score -= min(bearish_count, 3)
    if unemployment.get("uptrend_confirmed"):
        score -= 1
    if unemployment.get("mechanism_firing"):
        score -= 1
    if final_status == "ELEVATED":
        score -= 1

    score = max(score, 1)
    if sp_drawdown_pct <= -25:
        score = 1

    label = next(lab for (lo, hi), lab in LABELS.items() if lo <= score <= hi)
    return {"score": score, "label": label}
