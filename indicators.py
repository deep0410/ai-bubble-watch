"""Gemini research (indicators 1-4) with Google Search; rates handled in rates.py."""

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

PROMPT = """You are a financial-signals research agent. Today's date is {today}.
The most recent major-tech earnings cycle relevant to this run is: {earnings_cycle}.
Previous monitor run date: {previous_run}.

Use Google Search to find the MOST RECENT data for indicators 1-4 below. For EVERY figure
you report, you MUST include the date it was published and the source name. RECENCY RULES:
- Reject any figure published before {earnings_cycle}. If only older data exists, reuse the
  PREVIOUS value, set bearish=false, and set "is_stale": true.
- Prefer primary sources (earnings calls, SEC filings, company IR) and major outlets
  (CNBC, Reuters, Bloomberg) or named analyst notes (Evercore, BofA, Goldman, Jefferies).

PREVIOUS VALUES (from last run on {previous_run}):
{previous_json}

INDICATORS:
1. capex_2027_guidance_usd_bn: The SUMMED calendar-year-2027 capex guidance/estimate across
   Amazon, Alphabet, Meta, Microsoft, and Oracle, in USD billions. If companies have not
   given formal 2027 guidance, use the latest post-earnings ANALYST CONSENSUS (Evercore/BofA/
   Goldman). SANITY CHECK: the 2027 figure must be >= the current 2026 figure (~{capex_2026_floor}).
   If a candidate number is lower than 2026, it is stale or mislabeled -> discard it and search
   again. Treat the previous value as a fuzzy analyst aggregate, not a hard target. Do NOT mark
   bearish for a drop smaller than 5%, and do NOT mark bearish if reporting describes capex as
   rising, raised, soaring, or approaching/exceeding a level. Mark bearish only when sources
   explicitly describe a cut, trim, pause, or cancellation. (Final bearish flag is recomputed in code.)
2. capacity_language: From the MOST RECENT quarter's hyperscaler/Nvidia earnings calls, is the
   tone "supply-constrained" or "ample-capacity"? bearish=true ONLY if TWO OR MORE major
   players state capacity has caught up / they are no longer constrained.
3. nvidia: From Nvidia's MOST RECENT earnings only — did they RAISE next-quarter revenue
   guidance vs the quarter just reported (next_q_guidance_raised: bool), and data-center
   revenue YoY growth % (dc_yoy_growth_pct)? bearish=true if guidance NOT raised OR
   dc_yoy_growth_pct < 40.
4. roi: Track ONLY this survey: "{roi_survey_name}" measuring "{roi_metric}".
   Last known edition date in state: {roi_last_edition}. Report its latest published value
   (roi_value_pct). If no NEW edition of THIS survey has appeared since {previous_run}, reuse
   the previous roi value and set bearish=false and is_stale=true. bearish=true ONLY if a NEW
   edition shows the value moved in the worse direction vs the previous edition.
   Do NOT substitute a different survey (e.g. MIT NANDA vs PwC) — different questions drift.

Use plain ASCII in all evidence strings (no emoji, no unicode symbols).
Output ONLY this JSON (no markdown, no prose). Every block needs data_date + source:
{{
  "capex":   {{"value_usd_bn": number, "bearish": bool, "is_stale": bool, "data_date": "YYYY-MM", "source": str, "evidence": str}},
  "capacity":{{"value": "supply-constrained"|"ample-capacity", "bearish": bool, "is_stale": bool, "data_date": "YYYY-MM", "source": str, "evidence": str}},
  "nvidia":  {{"next_q_guidance_raised": bool, "dc_yoy_growth_pct": number, "bearish": bool, "is_stale": bool, "data_date": "YYYY-MM", "source": str, "evidence": str}},
  "roi":     {{"roi_value_pct": number, "bearish": bool, "is_stale": bool, "data_date": "YYYY-MM", "source": str, "evidence": str}}
}}
"""

_LLM_KEYS = ("capex", "capacity", "nvidia", "roi")
_BLOCK_FIELDS = ("bearish", "is_stale", "data_date", "source", "evidence")


def _extract_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if t:
                return str(t).strip()
    return ""


def _is_rate_limit(err: Exception) -> bool:
    if isinstance(err, genai_errors.ClientError):
        if getattr(err, "code", None) == 429:
            return True
    msg = str(err).lower()
    return "429" in msg or "rate" in msg or "quota" in msg or "resource_exhausted" in msg


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Response is not a JSON object")
    for key in _LLM_KEYS:
        if key not in data:
            raise ValueError(f"Missing key: {key}")
        block = data[key]
        if not isinstance(block, dict):
            raise ValueError(f"Invalid block for {key}")
        for field in _BLOCK_FIELDS:
            if field not in block:
                raise ValueError(f"Missing {field} in {key}")
    return data


def _call_gemini(client: genai.Client, model: str, prompt: str) -> str:
    logger.info(
        "Waiting on %s + Google Search (multiple searches possible; please wait)...",
        model,
    )
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
        raise RuntimeError(f"Empty response from {model}")
    logger.info("Received %d chars from %s", len(text), model)
    return text


def run_research(
    today: str,
    previous_run: str,
    previous: dict,
    earnings_cycle: str,
    roi_last_edition: str,
) -> dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = PROMPT.format(
        today=today,
        previous_run=previous_run,
        earnings_cycle=earnings_cycle,
        previous_json=json.dumps(previous, indent=2),
        roi_survey_name=config.ROI_SURVEY_NAME,
        roi_metric=config.ROI_METRIC,
        roi_last_edition=roi_last_edition or "unknown",
        capex_2026_floor=config.CAPEX_2026_FLOOR_USD_BN,
    )
    models = [config.GEMINI_MODEL, config.GEMINI_FALLBACK]

    logger.info("Prompt ready (%d chars); starting model loop", len(prompt))

    last_err: Exception | None = None
    for i, model in enumerate(models):
        try:
            text = _call_gemini(client, model, prompt)
            logger.info("Parsing JSON response from %s", model)
            data = _parse_json(text)
            for key in _LLM_KEYS:
                block = data[key]
                logger.info(
                    "  %s: bearish=%s stale=%s date=%s source=%s",
                    key,
                    block.get("bearish"),
                    block.get("is_stale"),
                    block.get("data_date"),
                    block.get("source", "")[:40],
                )
            return data
        except json.JSONDecodeError as err:
            last_err = err
            logger.warning("JSON parse failed for %s: %s", model, err)
            raise
        except Exception as err:
            last_err = err
            logger.warning("Gemini %s failed: %s", model, err)
            if i == 0 and _is_rate_limit(err):
                logger.info("Rate limited; trying fallback %s", models[1])
                continue
            raise

    raise RuntimeError(f"Gemini failed: {last_err}") from last_err


def score(research: dict[str, Any], rates: dict[str, Any]) -> tuple[int, str]:
    blocks = [
        research["capex"],
        research["capacity"],
        research["nvidia"],
        research["roi"],
        rates,
    ]
    n = sum(1 for b in blocks if b.get("bearish") and not b.get("is_stale"))
    status = "STABLE" if n <= 1 else "WATCH" if n <= 3 else "ELEVATED"
    return n, status
