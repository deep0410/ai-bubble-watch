"""Benner Cycle (Samuel Benner, 1875) position + conformance tracker.

The chart has three repeating lines:
  A. Panic years            (16-18-20 cadence): ... 1999, 2019, 2035
  B. Good times / high prices / time to SELL (8-9-10): ... 1999, 2007, 2018(*), 2026, 2034
  C. Hard times / low prices / time to BUY  (9-7-11): ... 2005, 2012, 2023, 2032

This is deterministic context, NOT a timing signal on its own. The tracker
answers two questions each run:
  1. Where are we on the chart right now?
  2. Is the market actually following it? (conformance via drawdown data)

2026 is a Benner SELL-peak year with a decline into a 2032 BUY bottom -
which happens to align with the thesis crash band. Conformance rules:
  - In/after a SELL year, new all-time highs deep into the following year
    = DIVERGING BULLISH (chart says peak passed; market disagrees).
  - 10%+ off peak after the SELL year = CONFORMING.
  - 30%+ drawdown on the way to the BUY-bottom year = STRONGLY CONFORMING.
"""

from __future__ import annotations

from datetime import date
from typing import Any

PANIC_YEARS = [1999, 2019, 2035, 2053]
SELL_PEAK_YEARS = [1999, 2007, 2018, 2026, 2034, 2043]
BUY_BOTTOM_YEARS = [2005, 2012, 2023, 2032, 2042]


def _next_after(years: list[int], y: int) -> int | None:
    return next((x for x in years if x >= y), None)


def benner_position(today: date, sp_drawdown_pct: float | None,
                    at_or_near_ath: bool | None) -> dict[str, Any]:
    y = today.year
    next_sell = _next_after(SELL_PEAK_YEARS, y)
    next_buy = _next_after(BUY_BOTTOM_YEARS, y)
    next_panic = _next_after(PANIC_YEARS, y)

    if y in SELL_PEAK_YEARS:
        phase = f"{y} = SELL-peak year (good times, high prices)"
    elif y in BUY_BOTTOM_YEARS:
        phase = f"{y} = BUY-bottom year (hard times, low prices)"
    else:
        last_sell = max((x for x in SELL_PEAK_YEARS if x < y), default=None)
        if last_sell and next_buy and last_sell < y < next_buy:
            phase = f"between {last_sell} SELL-peak and {next_buy} BUY-bottom (chart says: declining)"
        else:
            phase = f"advancing toward {next_sell} SELL-peak"

    # Conformance
    conformance = "unknown (no price data)"
    dd = sp_drawdown_pct
    last_sell = max((x for x in SELL_PEAK_YEARS if x <= y), default=None)
    if dd is not None:
        in_decline_window = last_sell is not None and y >= last_sell
        if in_decline_window:
            if dd <= -30:
                conformance = "STRONGLY CONFORMING (30%+ drawdown in the post-peak window)"
            elif dd <= -10:
                conformance = "CONFORMING (10%+ off peak after the SELL year)"
            elif y > last_sell and (at_or_near_ath or dd > -3):
                conformance = (
                    f"DIVERGING BULLISH (new/near highs {y - last_sell}yr past the "
                    f"{last_sell} SELL-peak - chart says decline, market disagrees)"
                )
            elif y == last_sell:
                conformance = (
                    "in the SELL-peak year itself - too early to score; "
                    "the test is what happens from here into next year"
                )
            else:
                conformance = f"AMBIGUOUS (drawdown {dd}% - between conforming and diverging)"

    return {
        "phase": phase,
        "next_sell_peak": next_sell,
        "next_buy_bottom": next_buy,
        "next_panic_year": next_panic,
        "conformance": conformance,
    }


def format_benner_section(b: dict[str, Any]) -> str:
    return (
        f"BENNER CYCLE: {b['phase']}\n"
        f"  Next: BUY-bottom {b['next_buy_bottom']}, panic-line year {b['next_panic_year']}\n"
        f"  Conformance: {b['conformance']}\n"
        f"  (Context only - a 150-year-old chart is a rhyme, not a timing signal.)"
    )
