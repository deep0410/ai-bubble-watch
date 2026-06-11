"""Drawdown from all-time high (S&P 500, Nasdaq) + unemployment trend + falsification.

All numeric, all from FRED - no LLM. This is the module that measures the bet:
  - Falsification criterion (stated 2026-06-05): thesis is WRONG if the S&P
    has NOT seen a 30%+ drawdown by 2028-06-05.
  - C5 unemployment: confirmed uptrend = 3mo avg rises 0.2pp+ over the prior
    3mo avg (a mini Sahm-rule), or rate reaches 5.0%+.

FRED series: SP500 and NASDAQCOM provide ~10 years of daily closes, which is
plenty - the relevant ATHs are recent.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"

BET_DATE = date(2026, 6, 5)
FALSIFICATION_DEADLINE = date(2028, 6, 5)
CRASH_THRESHOLD_PCT = -30.0


def _fred_series(series_id: str, limit: int) -> list[tuple[str, float]]:
    if not config.FRED_API_KEY:
        raise ValueError("FRED_API_KEY is not set")
    resp = requests.get(
        _FRED_OBS_URL,
        params={
            "series_id": series_id,
            "api_key": config.FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        },
        timeout=20,
    )
    resp.raise_for_status()
    out: list[tuple[str, float]] = []
    for obs in resp.json().get("observations") or []:
        raw = obs.get("value", "")
        if raw in (".", "", None):
            continue
        out.append((obs["date"], float(raw)))
    if not out:
        raise RuntimeError(f"FRED returned no usable {series_id} observations")
    return out  # newest first


def fetch_drawdowns() -> dict[str, Any]:
    """Current S&P/Nasdaq level, ATH over available window, and drawdown %."""
    result: dict[str, Any] = {}
    for key, series in (("sp500", "SP500"), ("nasdaq", "NASDAQCOM")):
        obs = _fred_series(series, limit=2600)  # ~10 years of trading days
        latest_date, latest = obs[0]
        ath_date, ath = max(obs, key=lambda o: o[1])
        dd = round((latest / ath - 1.0) * 100, 2)
        result[key] = {
            "level": latest,
            "date": latest_date,
            "ath": ath,
            "ath_date": ath_date,
            "drawdown_pct": dd,
            "near_ath": dd > -3.0,
        }
        logger.info("%s: %s on %s, ATH %s (%s), drawdown %s%%",
                    series, latest, latest_date, ath, ath_date, dd)
    return result


def fetch_unemployment() -> dict[str, Any]:
    """UNRATE with a confirmed-uptrend test (C5)."""
    obs = _fred_series("UNRATE", limit=8)  # 8 months
    rates = [v for _, v in obs]  # newest first
    rate = rates[0]
    avg_recent = sum(rates[0:3]) / 3 if len(rates) >= 3 else rate
    avg_prior = sum(rates[3:6]) / 3 if len(rates) >= 6 else avg_recent
    uptrend = (avg_recent - avg_prior) >= 0.2 or rate >= 5.0
    trend = f"3mo avg {round(avg_recent, 2)} vs prior {round(avg_prior, 2)}"
    return {
        "rate": rate,
        "data_date": obs[0][0],
        "trend": trend,
        "uptrend_confirmed": uptrend,
        "evidence": f"UNRATE {rate}% ({obs[0][0]}); {trend}; "
        + ("UPTREND CONFIRMED" if uptrend else "flat"),
    }


def falsification_check(
    sp_drawdown_pct: float, state: dict[str, Any], today: date
) -> dict[str, Any]:
    """Track the bet: 30%+ S&P drawdown by 2028-06-05, or the thesis is wrong."""
    f = dict(state.get("falsification") or {})
    f.setdefault("bet_date", BET_DATE.isoformat())
    f.setdefault("deadline", FALSIFICATION_DEADLINE.isoformat())
    f.setdefault("criterion", "S&P 500 drawdown of 30%+ from ATH")
    f.setdefault("max_drawdown_seen_pct", 0.0)
    f.setdefault("status", "PENDING")

    if sp_drawdown_pct < f["max_drawdown_seen_pct"]:
        f["max_drawdown_seen_pct"] = sp_drawdown_pct
        f["max_drawdown_date"] = today.isoformat()

    months_left = (FALSIFICATION_DEADLINE.year - today.year) * 12 + (
        FALSIFICATION_DEADLINE.month - today.month
    )
    f["months_left"] = max(months_left, 0)

    if f["max_drawdown_seen_pct"] <= CRASH_THRESHOLD_PCT:
        f["status"] = "HIT"
    elif today > FALSIFICATION_DEADLINE:
        f["status"] = "MISSED - thesis falsified by its own stated criterion"
    return f


def format_falsification_section(f: dict[str, Any], dd: dict[str, Any]) -> str:
    sp, nq = dd["sp500"], dd["nasdaq"]
    lines = [
        f"DRAWDOWN: S&P {sp['drawdown_pct']}% from ATH ({sp['ath_date']}); "
        f"Nasdaq {nq['drawdown_pct']}%",
        f"FALSIFICATION: {f['criterion']} by {f['deadline']} - "
        f"{f['months_left']}mo left | status: {f['status']} | "
        f"deepest so far: {f['max_drawdown_seen_pct']}%",
    ]
    if f["status"] == "HIT":
        lines.append(
            "ATTRIBUTION CHECK DUE: did this happen for the STATED catalysts "
            "(lockups/Fed/SaaS/unemployment) or something off-list (war, credit "
            "event)? A hit for off-list reasons = timeline hit, thesis missed."
        )
    return "\n".join(lines)
