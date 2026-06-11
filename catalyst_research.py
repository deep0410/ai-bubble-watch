"""Gemini + Google Search pass for catalyst status (C1-C4), CAPE, and the
institutional-trap signal (mega-cap secondary offerings / insider selling)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import config

logger = logging.getLogger(__name__)

PROMPT = """You are a market-structure research agent. Today is {today}; previous run {last_run}.
Use Google Search to answer ONLY the questions below with the most recent facts. Cite the
publication date and source for everything. Prefer primary sources (SEC filings, company IR,
Fed statements) and Reuters/Bloomberg/CNBC/WSJ/FT. Plain ASCII only.

QUESTIONS:
1. c1_spacex: Has SpaceX completed an IPO? If yes: listing date, any announced lockup
   schedule, and any reported meaningful insider selling. If no IPO: latest credible
   reporting on IPO timing.
2. c2_fed: The MOST RECENT FOMC decision: date and outcome (cut/hold/hike). Was the market
   under visible stress around that meeting (5%+ S&P pullback, yield spike, credit stress)?
3. c3_second_wave: Have Anthropic and/or OpenAI announced or completed IPOs? For each:
   announced (bool), listed (bool), listing_date if listed, expected timing if announced.
4. c4_saas: In the MOST RECENT earnings cycle, did multiple major SaaS companies
   (e.g. Salesforce, Workday, ServiceNow, HubSpot, Adobe) cut or disappoint on guidance
   in ways attributed to AI disruption/substitution? Cuts for OTHER reasons do not count.
5. cape: The current Shiller CAPE ratio for the S&P 500 (latest available value).
6. trap: Since {last_run}, any NEW mega-cap (Mag 7 / hyperscaler) secondary share
   offerings, large new equity raises, or unusually large insider/founder selling.
   These are "smart money selling equity to the public at peak prices" events.

Output ONLY this JSON (no markdown, no prose):
{{
  "c1_spacex": {{"ipo_listed": bool, "listing_date": "YYYY-MM-DD"|null,
                 "insider_selling_news": bool, "evidence": str}},
  "c2_fed": {{"last_decision": "cut"|"hold"|"hike", "decision_date": "YYYY-MM-DD",
              "market_stress": bool, "evidence": str}},
  "c3_second_wave": {{"listings": [{{"company": str, "announced": bool, "listed": bool,
                       "listing_date": "YYYY-MM-DD"|null}}], "evidence": str}},
  "c4_saas": {{"guidance_cuts_confirmed": bool, "examples": [str], "evidence": str}},
  "cape": {{"value": number, "data_date": "YYYY-MM", "source": str}},
  "trap": {{"events": [{{"company": str, "type": str, "size": str, "date": "YYYY-MM-DD"}}],
            "evidence": str}}
}}
"""

_KEYS = ("c1_spacex", "c2_fed", "c3_second_wave", "c4_saas", "cape", "trap")


def _extract_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if t:
                return str(t).strip()
    return ""


def _is_rate_limit(err: Exception) -> bool:
    if isinstance(err, genai_errors.ClientError) and getattr(err, "code", None) == 429:
        return True
    msg = str(err).lower()
    return "429" in msg or "rate" in msg or "quota" in msg or "resource_exhausted" in msg


def _parse(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Catalyst response is not a JSON object")
    for key in _KEYS:
        if key not in data:
            raise ValueError(f"Catalyst response missing {key}")
    return data


def run_catalyst_research(today: str, last_run: str) -> dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = PROMPT.format(today=today, last_run=last_run)
    models = [config.GEMINI_MODEL, config.GEMINI_FALLBACK]

    last_err: Exception | None = None
    for i, model in enumerate(models):
        try:
            logger.info("Catalyst research: waiting on %s + Google Search...", model)
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.0,
                ),
            )
            text = _extract_text(resp)
            if not text:
                raise RuntimeError(f"Empty catalyst response from {model}")
            data = _parse(text)
            logger.info(
                "Catalyst research: spacex_listed=%s fed=%s saas_cracks=%s cape=%s trap_events=%d",
                data["c1_spacex"].get("ipo_listed"),
                data["c2_fed"].get("last_decision"),
                data["c4_saas"].get("guidance_cuts_confirmed"),
                data["cape"].get("value"),
                len(data["trap"].get("events") or []),
            )
            return data
        except json.JSONDecodeError as err:
            last_err = err
            logger.warning("Catalyst JSON parse failed for %s: %s", model, err)
            raise
        except Exception as err:
            last_err = err
            logger.warning("Catalyst research %s failed: %s", model, err)
            if i == 0 and _is_rate_limit(err):
                logger.info("Rate limited; trying %s", models[1])
                continue
            raise
    raise RuntimeError(f"Catalyst research failed: {last_err}") from last_err


def format_trap_section(research: dict[str, Any]) -> str:
    trap = research.get("trap", {})
    events = trap.get("events") or []
    if not events:
        return "INSTITUTIONAL TRAP: no new mega-cap equity raises / insider exits this run."
    lines = ["INSTITUTIONAL TRAP (exit behavior at highs):"]
    for e in events[:4]:
        lines.append(f"- {e.get('company')}: {e.get('type')} {e.get('size')} ({e.get('date')})")
    return "\n".join(lines)


def format_cape_line(research: dict[str, Any]) -> str:
    cape = research.get("cape", {})
    v = cape.get("value")
    if v is None:
        return "CAPE: unavailable this run."
    return (
        f"CAPE: {v} ({cape.get('data_date', '?')}). Context only - CAPE has been "
        f"'screaming crash' for years; it predicts muted long-run returns, not dates."
    )
