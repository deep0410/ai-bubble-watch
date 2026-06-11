"""Slip-based catalyst model: the crash is a computed band, not a date.

Core mechanic (from the thesis design):
- The crash is downstream of a chain of catalysts. The crash band is computed
  from catalyst dates, so when a catalyst slips later, the band slips with it;
  when one fires early/hot, the band pulls forward.
- Slip logic is allowed to push the band out indefinitely.

Catalysts:
  C1 SpaceX lockup        baseline: first window 2026-08, full expiry 2026-12
  C2 Fed rate direction   early cuts (no crash) push band LATER; holds with
                          stress hold/pull it FORWARD
  C3 Anthropic/OpenAI     baseline listing 2026-11; lockup = listing + 180d
     IPO lockups          (baseline expiry 2027-05) - the "second wave"
  C4 SaaS earnings cracks baseline 2027-04 (Q1'27 reports). Confirmation
                          signal only - does NOT move the band; a miss flags
                          the timeline as STRETCHING (+12mo to next check)
  C5 Unemployment         4.3% baseline. Confirmed uptrend pulls band forward
                          and marks it recession-flavored; flat = valuation
                          reset (historically shallower, faster recovery)

Band formula (encoding choices documented in README):
  band_start = C1_full_expiry + 1mo + C2_net - (2mo if C5 uptrend)
  band_end   = C3_lockup_expiry + 3mo + C2_net
Baseline output: 2027-01 .. 2027-08 (~Q1-Q3 2027), matching the thesis.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# ---------------------------------------------------------------- baselines

BASELINES: dict[str, dict[str, Any]] = {
    "c1": {
        "name": "SpaceX lockup",
        "first_window": "2026-08",
        "full_expiry": "2026-12",
    },
    "c2": {"name": "Fed rate direction", "net_months": 0},
    "c3": {
        "name": "Anthropic/OpenAI IPO lockups",
        "listing_baseline": "2026-11",
        "lockup_days": 180,
        "lockup_baseline": "2027-05",
    },
    "c4": {"name": "SaaS earnings cracks", "baseline": "2027-04"},
    "c5": {"name": "Unemployment / consumer", "baseline_rate": 4.3, "crack_level": 5.0},
}

BASELINE_BAND = ("2027-01", "2027-08")


# ---------------------------------------------------------------- month math

def _ym(s: str) -> tuple[int, int]:
    y, m = s.split("-")[:2]
    return int(y), int(m)


def add_months(ym: str, n: int) -> str:
    y, m = _ym(ym)
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def months_between(earlier: str, later: str) -> int:
    y1, m1 = _ym(earlier)
    y2, m2 = _ym(later)
    return (y2 * 12 + m2) - (y1 * 12 + m1)


def _this_month(today: date) -> str:
    return f"{today.year:04d}-{today.month:02d}"


# ------------------------------------------------------------ slip updates

def update_catalysts(
    state_catalysts: dict[str, Any],
    research: dict[str, Any],
    unemployment: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Merge this run's research + UNRATE data into catalyst state with slip deltas."""
    cat = {k: dict(v) for k, v in (state_catalysts or {}).items()}
    now = _this_month(today)

    # --- C1 SpaceX ---
    c1 = cat.setdefault("c1", {"slip_months": 0, "status": "pending"})
    r1 = research.get("c1_spacex", {})
    if r1.get("ipo_listed") and r1.get("listing_date"):
        listing = r1["listing_date"][:7]
        c1.update(
            status="fired",
            listing_date=listing,
            first_window=add_months(listing, 3),
            full_expiry=add_months(listing, 6),
        )
        c1["slip_months"] = months_between(
            BASELINES["c1"]["full_expiry"], c1["full_expiry"]
        )
    elif months_between(BASELINES["c1"]["first_window"], now) > 0:
        # Past the baseline first window with no IPO: sequence is running late.
        c1["slip_months"] = months_between(BASELINES["c1"]["first_window"], now)
        c1["status"] = "slipping"
    c1["insider_selling"] = bool(r1.get("insider_selling_news"))
    c1["evidence"] = r1.get("evidence", c1.get("evidence", ""))

    # --- C2 Fed ---
    c2 = cat.setdefault("c2", {"net_months": 0, "status": "tracking"})
    r2 = research.get("c2_fed", {})
    decision = (r2.get("last_decision") or "").lower()
    decision_date = r2.get("decision_date", "")
    if decision and decision_date and decision_date != c2.get("last_counted_date"):
        stress = bool(r2.get("market_stress"))
        if decision == "cut" and not stress:
            c2["net_months"] = c2.get("net_months", 0) + 1  # cuts are fuel -> later
        elif decision == "hold" and stress:
            c2["net_months"] = c2.get("net_months", 0) - 1  # spring tightening -> forward
        c2["last_counted_date"] = decision_date
    c2["last_decision"] = decision or c2.get("last_decision", "")
    c2["evidence"] = r2.get("evidence", c2.get("evidence", ""))

    # --- C3 second wave ---
    c3 = cat.setdefault("c3", {"slip_months": 0, "status": "pending"})
    r3 = research.get("c3_second_wave", {})
    listed = [
        x for x in (r3.get("listings") or [])
        if x.get("listed") and x.get("listing_date")
    ]
    if listed:
        # Anchor on the LATEST listing: band can't resolve until both clear.
        latest = max(x["listing_date"][:7] for x in listed)
        c3.update(
            status="anchored",
            latest_listing=latest,
            lockup_expiry=add_months(latest, 6),  # ~180 days
        )
        c3["slip_months"] = months_between(
            BASELINES["c3"]["lockup_baseline"], c3["lockup_expiry"]
        )
    elif months_between(BASELINES["c3"]["listing_baseline"], now) > 0:
        c3["slip_months"] = months_between(BASELINES["c3"]["listing_baseline"], now)
        c3["status"] = "slipping"
        c3["lockup_expiry"] = add_months(
            BASELINES["c3"]["lockup_baseline"], c3["slip_months"]
        )
    c3["evidence"] = r3.get("evidence", c3.get("evidence", ""))

    # --- C4 SaaS cracks (confirmation only) ---
    c4 = cat.setdefault("c4", {"status": "pending", "stretch_warnings": 0})
    r4 = research.get("c4_saas", {})
    if r4.get("guidance_cuts_confirmed"):
        c4["status"] = "confirmed"
        c4["confirmed_date"] = now
    elif months_between(BASELINES["c4"]["baseline"], now) > 2 and c4["status"] != "confirmed":
        # Reports for the expected cycle are in and no cracks: thesis is
        # STRETCHING (not sliding) - a real warning, checked again next cycle.
        expected_next = add_months(
            BASELINES["c4"]["baseline"], 12 * (c4.get("stretch_warnings", 0) + 1)
        )
        if months_between(expected_next, now) <= 0:
            c4["status"] = "stretched"
    c4["evidence"] = r4.get("evidence", c4.get("evidence", ""))

    # --- C5 unemployment (from FRED UNRATE, not LLM) ---
    c5 = cat.setdefault("c5", {"status": "flat"})
    c5.update(
        rate=unemployment.get("rate"),
        trend=unemployment.get("trend"),
        status="uptrend" if unemployment.get("uptrend_confirmed") else "flat",
        evidence=unemployment.get("evidence", ""),
    )

    return cat


# ------------------------------------------------------------- crash band

def compute_band(cat: dict[str, Any], today: date) -> dict[str, Any]:
    c1_full = cat.get("c1", {}).get("full_expiry") or add_months(
        BASELINES["c1"]["full_expiry"], cat.get("c1", {}).get("slip_months", 0)
    )
    c3_lockup = cat.get("c3", {}).get("lockup_expiry") or add_months(
        BASELINES["c3"]["lockup_baseline"], cat.get("c3", {}).get("slip_months", 0)
    )
    fed_net = cat.get("c2", {}).get("net_months", 0)
    uptrend = cat.get("c5", {}).get("status") == "uptrend"

    start = add_months(add_months(c1_full, 1), fed_net)
    if uptrend:
        start = add_months(start, -2)
    end = add_months(add_months(c3_lockup, 3), fed_net)
    if months_between(start, end) < 0:
        end = start

    now = _this_month(today)
    overdue = months_between(end, now) > 0
    net_slip = months_between(BASELINE_BAND[0], start)

    return {
        "start": start,
        "end": end,
        "baseline": f"{BASELINE_BAND[0]}..{BASELINE_BAND[1]}",
        "net_slip_months": net_slip,
        "flavor": "recession-flavored (deeper, slower recovery)"
        if uptrend
        else "valuation reset (historically shallower, faster recovery)",
        "overdue": overdue,
        "anchors": {"c1_full_expiry": c1_full, "c3_lockup_expiry": c3_lockup,
                    "fed_net_months": fed_net},
    }


def format_catalyst_section(cat: dict[str, Any], band: dict[str, Any]) -> str:
    def slip_tag(n: int) -> str:
        if not n:
            return "on baseline"
        return f"slip {'+' if n > 0 else ''}{n}mo"

    c1, c2 = cat.get("c1", {}), cat.get("c2", {})
    c3, c4, c5 = cat.get("c3", {}), cat.get("c4", {}), cat.get("c5", {})
    lines = [
        f"C1 SpaceX lockup [{c1.get('status', 'pending')}] "
        f"full expiry {c1.get('full_expiry', BASELINES['c1']['full_expiry'])} "
        f"({slip_tag(c1.get('slip_months', 0))})"
        + (" INSIDER SELLING SEEN" if c1.get("insider_selling") else ""),
        f"C2 Fed [{c2.get('last_decision') or 'n/a'}] net effect "
        f"{'+' if c2.get('net_months', 0) > 0 else ''}{c2.get('net_months', 0)}mo "
        f"(cuts push later, stressed holds pull forward)",
        f"C3 2nd-wave lockups [{c3.get('status', 'pending')}] expiry "
        f"{c3.get('lockup_expiry', BASELINES['c3']['lockup_baseline'])} "
        f"({slip_tag(c3.get('slip_months', 0))})",
        f"C4 SaaS cracks [{c4.get('status', 'pending')}] baseline "
        f"{BASELINES['c4']['baseline']} (confirmation only"
        + ("; TIMELINE STRETCHING" if c4.get("status") == "stretched" else "")
        + ")",
        f"C5 Unemployment {c5.get('rate', '?')}% [{c5.get('status', 'flat')}]",
    ]
    band_line = (
        f"CRASH BAND: {band['start']} -> {band['end']} "
        f"(baseline {band['baseline']}, net slip "
        f"{'+' if band['net_slip_months'] > 0 else ''}{band['net_slip_months']}mo)\n"
        f"Flavor: {band['flavor']}"
    )
    if band.get("overdue"):
        band_line += "\nNOTE: band end has passed without a crash - thesis is slipping, not just sliding."
    return band_line + "\n" + "\n".join(lines)
