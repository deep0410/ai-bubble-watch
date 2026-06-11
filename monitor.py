"""Entrypoint: slip-based crash-band model + health indicators + prosecution.

Run order:
  1. Indicator research (Gemini+Search): capex, capacity, Nvidia, ROI
  2. FRED direct: 10y Treasury, S&P/Nasdaq drawdown, unemployment (C5)
  3. Catalyst research (Gemini+Search): SpaceX/Fed/second-wave/SaaS + CAPE + trap
  4. Slip update -> recompute crash band; Benner position; falsification check
  5. News scan (Gemini+Search), escalate-only
  6. Prosecution pass (Gemini): strongest case AGAINST the thesis this run
  7. Notify + persist
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Callable

import config
from benner import benner_position
from capex import capex_bearish
from catalyst_research import run_catalyst_research
from catalysts import BASELINES, compute_band, update_catalysts
from drawdown import (
    falsification_check,
    fetch_drawdowns,
    fetch_inflation,
    fetch_unemployment,
)
from health import health_score
from earnings_calendar import earnings_cycle_label
from indicators import run_research, score
from news import apply_news_override, format_news_section, run_news_scan
from notify import send_notification, to_ntfy_safe
from prosecution import run_prosecution
from rates import fetch_10y_and_signal

logger = logging.getLogger(__name__)


def _load_state() -> dict:
    with open(config.STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    with open(config.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _with_retry(label: str, fn: Callable[[], Any]) -> Any:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            logger.info("%s attempt %d/2", label, attempt + 1)
            return fn()
        except Exception as err:
            last_err = err
            logger.warning("%s attempt %d failed: %s", label, attempt + 1, err)
    raise RuntimeError(f"{label} failed after retry: {last_err}") from last_err


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("google", "google_genai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _drawdown_escalation(status: str, sp_dd: float) -> str:
    """Drawdown is ground truth: deep drawdown escalates regardless of indicators."""
    order = {"STABLE": 0, "WATCH": 1, "ELEVATED": 2}
    name = {0: "STABLE", 1: "WATCH", 2: "ELEVATED"}
    level = order.get(status, 0)
    if sp_dd <= -20:
        level = max(level, 2)
    elif sp_dd <= -10:
        level = max(level, 1)
    return name[level]


def main() -> int:
    _configure_logging()
    logger.info("=== AI Bubble Monitor (slip-band model) starting ===")

    state = _load_state()
    prev = state["indicators"]
    today_d = date.today()
    today = today_d.isoformat()
    previous_run = state.get("last_run") or today
    earnings_cycle = earnings_cycle_label(today_d)
    roi_meta = dict(
        state.get("roi_survey")
        or {"name": config.ROI_SURVEY_NAME, "metric": config.ROI_METRIC, "last_edition_date": ""}
    )
    roi_last_edition = roi_meta.get("last_edition_date", "")

    logger.info("Run date: %s | Previous run: %s | Cycle: %s", today, previous_run, earnings_cycle)

    # 1. Indicator research
    logger.info("Step 1/7: indicator research (model=%s)", config.GEMINI_MODEL)
    research = _with_retry(
        "Indicator research",
        lambda: run_research(today, previous_run, prev, earnings_cycle, roi_last_edition),
    )
    prev_capex = prev.get("capex_2027_prev_reading") or prev.get("capex_2027_guidance_usd_bn")
    research["capex"]["bearish"] = capex_bearish(
        research["capex"]["value_usd_bn"], prev_capex, research["capex"]["evidence"]
    )

    # 2. FRED numerics
    logger.info("Step 2/7: FRED (DGS10, SP500, NASDAQCOM, UNRATE)")
    rates = fetch_10y_and_signal(prev.get("treasury_10y_yield_pct"))
    dd = _with_retry("Drawdowns", fetch_drawdowns)
    unemployment = _with_retry("Unemployment", fetch_unemployment)
    inflation = _with_retry("Inflation", fetch_inflation)
    sp_dd = dd["sp500"]["drawdown_pct"]

    # 3. Catalyst research
    logger.info("Step 3/7: catalyst research (model=%s)", config.GEMINI_MODEL)
    cat_research = _with_retry(
        "Catalyst research", lambda: run_catalyst_research(today, previous_run)
    )

    # 4. Slip update -> band; Benner; falsification
    logger.info("Step 4/7: slip update + crash band + Benner + falsification")
    catalysts = update_catalysts(
        state.get("catalysts") or {}, cat_research, unemployment, today_d, inflation
    )
    band = compute_band(catalysts, today_d)
    benner = benner_position(today_d, sp_dd, dd["sp500"]["near_ath"])
    falsification = falsification_check(sp_dd, state, today_d)
    logger.info(
        "Crash band: %s..%s (net slip %+dmo) | S&P dd %s%% | falsification %s",
        band["start"], band["end"], band["net_slip_months"], sp_dd, falsification["status"],
    )

    # 5. Score + news
    n, numeric_status = score(research, rates)
    logger.info("Step 5/7: numeric score %d/5 (%s); news scan", n, numeric_status)
    news = _with_retry("News scan", lambda: run_news_scan(today, previous_run))
    final_status = apply_news_override(numeric_status, news["items"])
    final_status = _drawdown_escalation(final_status, sp_dd)
    _, net_read = format_news_section(news)
    health = health_score(sp_dd, n, unemployment, final_status)

    # 6. Prosecution
    run_summary = json.dumps(
        {
            "numeric_score": f"{n}/5",
            "sp500_drawdown_pct": sp_dd,
            "nasdaq_drawdown_pct": dd["nasdaq"]["drawdown_pct"],
            "unemployment": unemployment["evidence"],
            "catalysts": {
                k: {kk: vv for kk, vv in v.items() if kk != "evidence"}
                for k, v in catalysts.items()
            },
            "crash_band": f"{band['start']}..{band['end']}",
            "cape": cat_research.get("cape", {}).get("value"),
            "trap_events": len(cat_research.get("trap", {}).get("events") or []),
            "news_net_read": net_read,
        },
        default=str,
    )
    logger.info("Step 6/7: prosecution pass")
    counter_case = _with_retry(
        "Prosecution", lambda: run_prosecution(today, band, run_summary)
    )

    # ROI bookkeeping
    roi_block = research["roi"]
    if not roi_block.get("is_stale") and roi_block.get("data_date"):
        roi_meta = {
            "name": config.ROI_SURVEY_NAME,
            "metric": config.ROI_METRIC,
            "last_edition_date": roi_block["data_date"],
        }

    cur = {
        "capex_2027_guidance_usd_bn": research["capex"]["value_usd_bn"],
        "capex_2027_prev_reading": prev.get("capex_2027_guidance_usd_bn"),
        "capacity_language": research["capacity"]["value"],
        "nvidia_next_q_guidance_raised": research["nvidia"]["next_q_guidance_raised"],
        "nvidia_dc_yoy_growth_pct": research["nvidia"]["dc_yoy_growth_pct"],
        "roi_no_return_pct": roi_block["roi_value_pct"],
        "treasury_10y_yield_pct": rates["treasury_10y_yield_pct"],
    }

    # Lean body: moving crash date on top, health /10, one line per concern.
    c1, c2 = catalysts.get("c1", {}), catalysts.get("c2", {})
    c3, c5 = catalysts.get("c3", {}), catalysts.get("c5", {})
    c4 = catalysts.get("c4", {})
    slip = band["net_slip_months"]
    slip_txt = "on schedule" if slip == 0 else f"slipped {'+' if slip > 0 else ''}{slip}mo"
    conformance_short = (
        "too early to score"
        if "too early" in benner["conformance"]
        else benner["conformance"].split("(")[0].split(";")[0].strip().rstrip("-").strip()
    )
    trap_events = cat_research.get("trap", {}).get("events") or []
    trap_txt = (
        "; ".join(f"{e.get('company')} {e.get('type')}" for e in trap_events[:2])
        if trap_events
        else "none"
    )
    wc = c5.get("white_collar_rate")
    wc_yoy = c5.get("white_collar_yoy_delta")
    wc_txt = (
        f", white-collar {wc}% ({'+' if (wc_yoy or 0) >= 0 else ''}{wc_yoy} YoY"
        + ("; AI MECHANISM FIRING" if c5.get("mechanism_firing") else "")
        + ")"
        if wc is not None
        else ""
    )
    flags = []
    if c1.get("insider_selling"):
        flags.append("SpaceX insider selling")
    if c4.get("status") == "stretched":
        flags.append("C4 timeline STRETCHING")
    if band.get("overdue"):
        flags.append("band OVERDUE - thesis slipping")
    if falsification["status"] != "PENDING":
        flags.append(f"BET {falsification['status']}")
    flags_line = ("\n! " + " | ".join(flags)) if flags else ""

    top_news = ""
    items = news.get("items") or []
    if items:
        it = items[0]
        top_news = f" - {it['headline'][:90]}"

    body = to_ntfy_safe(
        f"""CRASH: {band['start']} -> {band['end']} ({slip_txt})
HEALTH: {health['score']}/10 ({health['label']})
S&P {sp_dd}% off ATH | Nasdaq {dd['nasdaq']['drawdown_pct']}% | bet: 30% by 2028-06, {falsification['months_left']}mo left, deepest {falsification['max_drawdown_seen_pct']}%{flags_line}

C1 SpaceX: {c1.get('status', 'pending')}, full {c1.get('full_expiry', BASELINES['c1']['full_expiry'])}
C2 Fed: {c2.get('last_decision') or 'n/a'}, CPI {c2.get('cpi_yoy', '?')}% {c2.get('cpi_regime', '')}, net {'+' if c2.get('net_months', 0) > 0 else ''}{c2.get('net_months', 0)}mo
C3 2nd wave: {c3.get('status', 'pending')}, lockup {c3.get('lockup_expiry', BASELINES['c3']['lockup_baseline'])}
C4 SaaS cracks: {c4.get('status', 'pending')}
C5 Jobs: {c5.get('rate', '?')}% {c5.get('status', 'flat')}{wc_txt}

Benner: {benner['phase'].split('(')[0].strip()} - {conformance_short}
Signals: {n}/5 bear | trap: {trap_txt} | CAPE {cat_research.get('cape', {}).get('value', '?')}
News: {net_read[:110]}{top_news}

Against: {counter_case}

STATUS: {final_status}"""
    )

    print(body)
    logger.info("Step 7/7: sending ntfy notification")
    send_notification(
        f"Crash {band['start']}..{band['end']} | health {health['score']}/10 | {final_status}",
        body,
        final_status,
    )

    state.update(
        {
            "last_run": today,
            "indicators": cur,
            "score": n,
            "numeric_status": numeric_status,
            "status": final_status,
            "roi_survey": roi_meta,
            "news_last_run": news,
            "catalysts": catalysts,
            "crash_band": band,
            "falsification": falsification,
            "benner": benner,
            "drawdowns": {
                "sp500_pct": sp_dd,
                "nasdaq_pct": dd["nasdaq"]["drawdown_pct"],
                "date": dd["sp500"]["date"],
            },
            "health": health,
            "inflation": inflation,
            "unemployment": unemployment,
            "cape": cat_research.get("cape"),
            "trap_last_run": cat_research.get("trap"),
        }
    )
    state.setdefault("history", []).append(
        {
            "date": today,
            "score": n,
            "numeric_status": numeric_status,
            "status": final_status,
            "indicators": cur,
            "crash_band": {"start": band["start"], "end": band["end"],
                           "net_slip_months": band["net_slip_months"]},
            "sp500_drawdown_pct": sp_dd,
            "health_score": health["score"],
            "unemployment": unemployment["rate"],
            "white_collar_rate": unemployment.get("white_collar_rate"),
            "core_cpi_yoy_pct": inflation.get("core_cpi_yoy_pct"),
            "falsification_status": falsification["status"],
            "news": news,
            "prosecution": counter_case,
        }
    )
    _save_state(state)
    logger.info("=== Done (net %s, band %s..%s) ===", final_status, band["start"], band["end"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:
        logger.error("%s", err)
        raise SystemExit(1) from err
