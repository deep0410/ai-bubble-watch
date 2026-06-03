"""US 10-year Treasury yield from FRED (DGS10) — not LLM-sourced."""

from __future__ import annotations

import logging
import statistics
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
_TRADING_DAYS_3MO = 63


def _fred_observations(limit: int) -> list[dict[str, Any]]:
    if not config.FRED_API_KEY:
        raise ValueError("FRED_API_KEY is not set")

    logger.info("FRED request: DGS10 (limit=%d)", limit)
    resp = requests.get(
        _FRED_OBS_URL,
        params={
            "series_id": "DGS10",
            "api_key": config.FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        },
        timeout=20,
    )
    resp.raise_for_status()
    observations = resp.json().get("observations") or []
    if not observations:
        raise RuntimeError("FRED returned no DGS10 observations")
    logger.info("FRED returned %d observations", len(observations))
    return observations


def _valid_yields(observations: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for obs in observations:
        raw = obs.get("value", "")
        if raw in (".", "", None):
            continue
        out.append(float(raw))
    return out


def fetch_10y_and_signal(prev_yield: float | None) -> dict[str, Any]:
    """Latest 10y yield and bearish flag (+25 bps vs prior or vs 3mo trailing avg)."""
    obs = _fred_observations(limit=_TRADING_DAYS_3MO)
    yields = _valid_yields(obs)
    if not yields:
        raise RuntimeError("No valid DGS10 values from FRED")

    y = yields[0]
    obs_date = obs[0].get("date", "unknown")
    avg3 = statistics.mean(yields) if yields else y

    if prev_yield is None:
        return {
            "treasury_10y_yield_pct": y,
            "bearish": False,
            "is_stale": False,
            "data_date": obs_date,
            "source": "FRED DGS10",
            "evidence": f"10y={y}% on {obs_date} (baseline, neutral)",
        }

    bearish = (y - prev_yield > 0.25) or (y - avg3 > 0.25)
    return {
        "treasury_10y_yield_pct": y,
        "bearish": bearish,
        "is_stale": False,
        "data_date": obs_date,
        "source": "FRED DGS10",
        "evidence": (
            f"10y={y}% on {obs_date} (prev {prev_yield}%, "
            f"3mo avg {round(avg3, 2)}%)"
        ),
    }
