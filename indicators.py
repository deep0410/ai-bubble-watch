"""Gemini research with Google Search grounding and crash-risk scoring."""

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

PROMPT = """You are a financial-signals research agent. Today is {today}.
Use Google Search to find the MOST RECENT data for each of the 5 indicators below.
Compare each against the PREVIOUS values provided, then output ONLY a JSON object
(no markdown, no prose) matching the schema at the end.

PREVIOUS VALUES (from last run):
{previous_json}

INDICATORS:
1. capex_2027_guidance_usd_bn: Latest SUMMED 2027 capital-expenditure guidance across
   Amazon, Alphabet, Meta, Microsoft, Oracle, in USD billions. bearish=true if the new
   total is FLAT or LOWER than previous (guidance stopped rising).
2. capacity_language: Latest hyperscaler/Nvidia earnings language on data-center capacity.
   Return "supply-constrained" or "ample-capacity". bearish=true if it has flipped to
   "ample-capacity".
3. nvidia: From Nvidia's most recent earnings — did they RAISE next-quarter revenue
   guidance vs the prior quarter (next_q_guidance_raised: true/false), and data-center
   revenue YoY growth % (dc_yoy_growth_pct). bearish=true if guidance NOT raised OR
   dc_yoy_growth_pct < 40.
4. roi_no_return_pct: Most recent credible survey % of enterprises reporting NO measurable
   return / "nothing out of" their AI investment. bearish=true if higher than previous.
5. treasury_10y_yield_pct: Current US 10-year Treasury yield %. bearish=true if up more
   than 0.25 vs previous (or a clear sustained uptrend).

For each indicator include a one-sentence "evidence" with the source name and date.
If a fresh value can't be found, reuse the previous value and set bearish=false.

OUTPUT JSON SCHEMA:
{{
  "capex": {{"value_usd_bn": number, "bearish": bool, "evidence": str}},
  "capacity": {{"value": "supply-constrained"|"ample-capacity", "bearish": bool, "evidence": str}},
  "nvidia": {{"next_q_guidance_raised": bool, "dc_yoy_growth_pct": number, "bearish": bool, "evidence": str}},
  "roi": {{"no_return_pct": number, "bearish": bool, "evidence": str}},
  "rates": {{"treasury_10y_yield_pct": number, "bearish": bool, "evidence": str}}
}}
"""

_REQUIRED_KEYS = ("capex", "capacity", "nvidia", "roi", "rates")


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
    for key in _REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"Missing key: {key}")
        block = data[key]
        if not isinstance(block, dict) or "bearish" not in block or "evidence" not in block:
            raise ValueError(f"Invalid block for {key}")
    return data


def _call_gemini(client: genai.Client, model: str, prompt: str) -> str:
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
    return text


def run_research(today: str, previous: dict) -> dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = PROMPT.format(today=today, previous_json=json.dumps(previous, indent=2))
    models = [config.GEMINI_MODEL, config.GEMINI_FALLBACK]

    last_err: Exception | None = None
    for i, model in enumerate(models):
        try:
            text = _call_gemini(client, model, prompt)
            return _parse_json(text)
        except json.JSONDecodeError as err:
            last_err = err
            logger.warning("JSON parse failed for %s: %s", model, err)
            raise
        except Exception as err:
            last_err = err
            logger.warning("Gemini %s failed: %s", model, err)
            if i == 0 and _is_rate_limit(err):
                continue
            raise

    raise RuntimeError(f"Gemini failed: {last_err}") from last_err


def score(research: dict[str, Any]) -> tuple[int, str]:
    flags = [research[k]["bearish"] for k in _REQUIRED_KEYS]
    n = sum(bool(x) for x in flags)
    status = "STABLE" if n <= 1 else "WATCH" if n <= 3 else "ELEVATED"
    return n, status
