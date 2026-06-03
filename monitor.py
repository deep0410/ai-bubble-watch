"""Entrypoint: research indicators, score risk, notify, persist state."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import config
from capex import capex_bearish
from earnings_calendar import earnings_cycle_label
from indicators import run_research, score
from news import apply_news_override, format_news_section, run_news_scan
from notify import send_notification, to_ntfy_safe
from rates import fetch_10y_and_signal

logger = logging.getLogger(__name__)


def _arrow(new: Any, old: Any) -> str:
    if old is None or new is None:
        return "="
    if new == old:
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


def _news_with_retry(today: str, last_run: str) -> dict:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            logger.info("News scan attempt %d/2", attempt + 1)
            return run_news_scan(today, last_run)
        except Exception as err:
            last_err = err
            logger.warning("News scan attempt %d failed: %s", attempt + 1, err)
    raise RuntimeError(f"News scan failed after retry: {last_err}") from last_err


def _research_with_retry(
    today: str,
    previous_run: str,
    prev: dict,
    earnings_cycle: str,
    roi_last_edition: str,
) -> dict:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            logger.info("Gemini research attempt %d/2", attempt + 1)
            return run_research(
                today, previous_run, prev, earnings_cycle, roi_last_edition
            )
        except Exception as err:
            last_err = err
            logger.warning("Research attempt %d failed: %s", attempt + 1, err)
    raise RuntimeError(f"Research failed after retry: {last_err}") from last_err


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("google", "google_genai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    _configure_logging()
    logger.info("=== AI Bubble Monitor starting ===")

    logger.info("Loading state from %s", config.STATE_PATH)
    state = _load_state()
    prev = state["indicators"]
    today = date.today().isoformat()
    previous_run = state.get("last_run") or today
    earnings_cycle = earnings_cycle_label(date.today())
    roi_meta = dict(
        state.get("roi_survey")
        or {
            "name": config.ROI_SURVEY_NAME,
            "metric": config.ROI_METRIC,
            "last_edition_date": "",
        }
    )
    roi_last_edition = roi_meta.get("last_edition_date", "")

    logger.info("Run date: %s | Previous run: %s", today, previous_run)
    logger.info("Earnings cycle: %s", earnings_cycle)
    logger.info("ROI survey: %s (last edition: %s)", config.ROI_SURVEY_NAME, roi_last_edition or "none")

    logger.info(
        "Step 1/5: Gemini + Google Search for indicators 1-4 "
        "(model=%s; often 1-3 minutes)",
        config.GEMINI_MODEL,
    )
    research = _research_with_retry(
        today, previous_run, prev, earnings_cycle, roi_last_edition
    )
    logger.info("Step 1/5 complete: Gemini research finished")

    prev_capex = prev.get("capex_2027_prev_reading") or prev.get("capex_2027_guidance_usd_bn")
    model_capex_bearish = research["capex"]["bearish"]
    research["capex"]["bearish"] = capex_bearish(
        research["capex"]["value_usd_bn"],
        prev_capex,
        research["capex"]["evidence"],
    )
    logger.info(
        "Capex bearish: model=%s adjusted=%s (prev=%s new=%s)",
        model_capex_bearish,
        research["capex"]["bearish"],
        prev_capex,
        research["capex"]["value_usd_bn"],
    )

    logger.info("Step 2/5: Fetching 10y Treasury from FRED (DGS10)")
    rates = fetch_10y_and_signal(prev.get("treasury_10y_yield_pct"))
    logger.info("Step 2/5 complete: 10y=%s%% bearish=%s", rates["treasury_10y_yield_pct"], rates["bearish"])

    n, numeric_status = score(research, rates)
    logger.info("Step 3/5: Numeric score %d/5 (%s)", n, numeric_status)

    logger.info(
        "Step 4/5: News scan (model=%s; second Gemini call)",
        config.GEMINI_NEWS_MODEL,
    )
    news = _news_with_retry(today, previous_run)
    final_status = apply_news_override(numeric_status, news["items"])
    if final_status != numeric_status:
        logger.info("News override: %s -> %s", numeric_status, final_status)
    else:
        logger.info("Step 4/5 complete: no news escalation (stays %s)", numeric_status)
    news_lines, net_read = format_news_section(news)

    roi_block = research["roi"]
    roi_pct = roi_block["roi_value_pct"]
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
        "roi_no_return_pct": roi_pct,
        "treasury_10y_yield_pct": rates["treasury_10y_yield_pct"],
    }

    treasury = cur["treasury_10y_yield_pct"]
    treasury_line = f"{treasury}%"

    body = to_ntfy_safe(
        f"""AI Bubble Monitor - {today}
Previous run: {previous_run}
Earnings cycle: {earnings_cycle}
Numeric score: {n}/5 ({numeric_status})

1. 2027 capex guidance: ${cur['capex_2027_guidance_usd_bn']}B {_arrow(cur['capex_2027_guidance_usd_bn'], prev['capex_2027_guidance_usd_bn'])} {_flag_block(research['capex'])}
   {research['capex']['evidence']}
2. Capacity language: {cur['capacity_language']} {_flag_block(research['capacity'])}
   {research['capacity']['evidence']}
3. Nvidia: DC YoY {cur['nvidia_dc_yoy_growth_pct']}%, guidance raised={cur['nvidia_next_q_guidance_raised']} {_flag_block(research['nvidia'])}
   {research['nvidia']['evidence']}
4. ROI ({config.ROI_SURVEY_NAME}): {cur['roi_no_return_pct']}% {_arrow(cur['roi_no_return_pct'], prev['roi_no_return_pct'])} {_flag_block(roi_block)}
   {roi_block['evidence']}
5. 10y Treasury: {treasury_line} {_flag_block(rates)}
   {rates['evidence']}

Read: {n} of 5 numeric cracks active. {'Thesis intact.' if n <= 1 else 'Watch closely.' if n <= 3 else 'Correction conditions aligning.'}

NET STATUS (incl. news): {final_status}
News read: {net_read}
Top events:
{news_lines}"""
    )

    print(body)
    logger.info("Step 5/5: Sending ntfy notification")
    send_notification(f"AI Monitor {n}/5 + news - {final_status}", body, final_status)
    logger.info("Notification sent")

    logger.info("Saving state to %s", config.STATE_PATH)
    state.update(
        {
            "last_run": today,
            "indicators": cur,
            "score": n,
            "numeric_status": numeric_status,
            "status": final_status,
            "roi_survey": roi_meta,
            "news_last_run": news,
        }
    )
    state.setdefault("history", []).append(
        {
            "date": today,
            "score": n,
            "numeric_status": numeric_status,
            "status": final_status,
            "indicators": cur,
            "news": news,
        }
    )
    _save_state(state)
    logger.info("=== Done (numeric %d/5 %s, net %s) ===", n, numeric_status, final_status)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:
        logger.error("%s", err)
        raise SystemExit(1) from err
