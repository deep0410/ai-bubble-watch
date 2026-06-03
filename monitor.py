"""Entrypoint: research indicators, score risk, notify, persist state."""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from typing import Any

import config
from indicators import run_research, score
from notify import send_notification

logger = logging.getLogger(__name__)


def _arrow(new: Any, old: Any) -> str:
    if old is None or new is None:
        return "→"
    if new == old:
        return "→"
    if isinstance(new, (int, float)) and isinstance(old, (int, float)):
        return "↑" if new > old else "↓"
    return "→"


def _load_state() -> dict:
    with open(config.STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    with open(config.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _research_with_retry(today: str, prev: dict) -> dict:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            return run_research(today, prev)
        except Exception as err:
            last_err = err
            logger.warning("Research attempt %d failed: %s", attempt + 1, err)
    raise RuntimeError(f"Research failed after retry: {last_err}") from last_err


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    state = _load_state()
    prev = state["indicators"]
    today = date.today().isoformat()

    r = _research_with_retry(today, prev)
    if prev.get("treasury_10y_yield_pct") is None:
        r["rates"]["bearish"] = False
    n, status = score(r)

    cur = {
        "capex_2027_guidance_usd_bn": r["capex"]["value_usd_bn"],
        "capacity_language": r["capacity"]["value"],
        "nvidia_next_q_guidance_raised": r["nvidia"]["next_q_guidance_raised"],
        "nvidia_dc_yoy_growth_pct": r["nvidia"]["dc_yoy_growth_pct"],
        "roi_no_return_pct": r["roi"]["no_return_pct"],
        "treasury_10y_yield_pct": r["rates"]["treasury_10y_yield_pct"],
    }

    treasury = cur["treasury_10y_yield_pct"]
    treasury_line = f"{treasury}%" if treasury is not None else "n/a"

    body = f"""AI Bubble Monitor — {today}
Risk score: {n}/5  ({status})

1. 2027 capex guidance: ${cur['capex_2027_guidance_usd_bn']}B {_arrow(cur['capex_2027_guidance_usd_bn'], prev['capex_2027_guidance_usd_bn'])} {'⚠️' if r['capex']['bearish'] else 'OK'}
   {r['capex']['evidence']}
2. Capacity language: {cur['capacity_language']} {'⚠️' if r['capacity']['bearish'] else 'OK'}
   {r['capacity']['evidence']}
3. Nvidia: DC YoY {cur['nvidia_dc_yoy_growth_pct']}%, guidance raised={cur['nvidia_next_q_guidance_raised']} {'⚠️' if r['nvidia']['bearish'] else 'OK'}
   {r['nvidia']['evidence']}
4. ROI 'no return' %: {cur['roi_no_return_pct']}% {_arrow(cur['roi_no_return_pct'], prev['roi_no_return_pct'])} {'⚠️' if r['roi']['bearish'] else 'OK'}
   {r['roi']['evidence']}
5. 10y Treasury: {treasury_line} {'⚠️' if r['rates']['bearish'] else 'OK'}
   {r['rates']['evidence']}

Read: {n} of 5 cracks active. {'Thesis intact.' if n <= 1 else 'Watch closely.' if n <= 3 else 'Correction conditions aligning.'}"""

    print(body)
    send_notification(f"AI Monitor {n}/5 — {status}", body, status)

    state.update({"last_run": today, "indicators": cur, "score": n, "status": status})
    state.setdefault("history", []).append(
        {"date": today, "score": n, "status": status, "indicators": cur}
    )
    _save_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:
        logger.error("%s", err)
        raise SystemExit(1) from err
