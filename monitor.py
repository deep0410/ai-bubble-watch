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
from benner import benner_position, format_benner_section
from capex import capex_bearish
from catalyst_research import format_cape_line, format_trap_section, run_catalyst_research
from catalysts import compute_band, format_catalyst_section, update_catalysts
from drawdown import (
    falsification_check,
    fetch_drawdowns,
    fetch_unemployment,
    format_falsification_section,
)
from earnings_calendar import earnings_cycle_label
from indicators import run_research, score
from news import apply_news_override, format_news_section, run_news_scan
from notify import send_notification, to_ntfy_safe
from prosecution import run_prosecution
from rates import fetch_10y_and_signal

logger = logging.getLogger(__name__)


def _arrow(new: Any, old: Any) -> str:
    if old is None or new is None or new == old:
        return "="
    if isinstance(new, (int, float)) and isinstance(old, (int, float)):
        return "+" if new > old else "-"
    return "="


def _flag_block(block: dict[str, Any]) -> str:
    if block.get("is_stale"):
        return "stale"
    return "BEAR" if block.get("bearish") else "ok"


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
    sp_dd = dd["sp500"]["drawdown_pct"]

    # 3. Catalyst research
    logger.info("Step 3/7: catalyst research (model=%s)", config.GEMINI_MODEL)
    cat_research = _with_retry(
        "Catalyst research", lambda: run_catalyst_research(today, previous_run)
    )

    # 4. Slip update -> band; Benner; falsification
    logger.info("Step 4/7: slip update + crash band + Benner + falsification")
    catalysts = update_catalysts(state.get("catalysts") or {}, cat_research, unemployment, today_d)
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
    news_lines, net_read = format_news_section(news)

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

    body = to_ntfy_safe(
        f"""AI Bubble Monitor - {today} (prev {previous_run})

{format_catalyst_section(catalysts, band)}

{format_falsification_section(falsification, dd)}

{format_benner_section(benner)}

HEALTH INDICATORS: {n}/5 bearish ({numeric_status})
1. Capex 2027: ${cur['capex_2027_guidance_usd_bn']}B {_arrow(cur['capex_2027_guidance_usd_bn'], prev['capex_2027_guidance_usd_bn'])} {_flag_block(research['capex'])}
2. Capacity: {cur['capacity_language']} {_flag_block(research['capacity'])}
3. Nvidia: DC YoY {cur['nvidia_dc_yoy_growth_pct']}%, raised={cur['nvidia_next_q_guidance_raised']} {_flag_block(research['nvidia'])}
4. ROI: {cur['roi_no_return_pct']}% {_arrow(cur['roi_no_return_pct'], prev['roi_no_return_pct'])} {_flag_block(roi_block)}
5. 10y: {cur['treasury_10y_yield_pct']}% {_flag_block(rates)}

{format_trap_section(cat_research)}
{format_cape_line(cat_research)}

NEWS: {net_read}
{news_lines}

PROSECUTION (the case against, this run):
{counter_case}

NET STATUS: {final_status}"""
    )

    print(body)
    logger.info("Step 7/7: sending ntfy notification")
    send_notification(
        f"Bubble Monitor {final_status} | band {band['start']}..{band['end']} | S&P {sp_dd}%",
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
            "unemployment": unemployment["rate"],
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
