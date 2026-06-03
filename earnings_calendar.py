"""Map run date to the most recent big-tech / Nvidia earnings cycle."""

from __future__ import annotations

from datetime import date


def earnings_cycle_label(today: date) -> str:
    """Return the earnings season label relevant for capex/capacity/Nvidia freshness."""
    y = today.year
    m = today.month
    d = today.day

    if m > 10 or (m == 10 and d >= 21):
        return (
            f"Q3 {y} big-tech (reported late Oct {y}); "
            f"Nvidia Q3 FY (late Nov {y})"
        )
    if m > 7 or (m == 7 and d >= 21):
        return (
            f"Q2 {y} big-tech (reported late July {y}); "
            f"Nvidia Q2 FY (late Aug {y})"
        )
    if m > 4 or (m == 4 and d >= 21):
        return (
            f"Q1 {y} big-tech (reported late April {y}); "
            f"Nvidia Q1 FY (late May {y})"
        )
    if m > 1 or (m == 1 and d >= 25) or m == 2:
        return (
            f"Q4 {y - 1} big-tech (reported late Jan-Feb {y}); "
            f"Nvidia Q4 FY (late Feb {y})"
        )
    return (
        f"Q3 {y - 1} big-tech (reported late Oct {y - 1}); "
        f"Nvidia Q3 FY (late Nov {y - 1})"
    )
