"""The prosecution pass: every run, the strongest case AGAINST the crash thesis.

Mandated by the thesis owner ("from going forward... you're trying to be the
naysayer"). A theory that explains every outcome isn't being tested anymore -
it's absorbing whatever happens. This pass exists to stop the monitor from
flattering the thesis.
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import config

logger = logging.getLogger(__name__)

PROMPT = """You are the designated PROSECUTION against a market-crash thesis. Today is {today}.

The thesis: an AI-bubble-driven 30-40% S&P correction, crash band {band_start} to {band_end},
driven by these catalysts: SpaceX/Anthropic/OpenAI IPO lockup selling, Fed policy, SaaS
earnings cracks from AI disruption, rising unemployment. Falsification: no 30%+ drawdown
by 2028-06-05 means the thesis is wrong.

THIS RUN'S DATA:
{run_summary}

Your job is NOT to be balanced. Build the strongest case that the thesis is WRONG or that
this run's data does NOT support it. Rules:
- Attack confirmation bias directly: if every data point this run "fits the narrative",
  say which ones are actually just noise (normal volatility, sector rotation, base rates).
- Use the known weaknesses: overdetermined catalyst lists are stories assembled backwards;
  widely-known catalysts (published lockup calendars) are already priced in; CAPE has no
  short-term timing power; strong employment contradicts an imminent recession; markets
  stayed irrational 15 months past CAPE 40 in 1998-2000.
- If unemployment is flat and indices are near highs, say plainly: nothing in this run
  confirms the crash is approaching.
- End with one line: the single observation THIS MONTH that would most weaken the thesis
  if it appears, and one that would most strengthen it (so the test is stated in advance).

Plain ASCII. Maximum 130 words. No headers, no bullets - one tight paragraph plus the
final two-part line."""


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


def run_prosecution(today: str, band: dict[str, Any], run_summary: str) -> str:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = PROMPT.format(
        today=today,
        band_start=band["start"],
        band_end=band["end"],
        run_summary=run_summary,
    )
    models = [config.GEMINI_NEWS_MODEL, config.GEMINI_FALLBACK]
    last_err: Exception | None = None
    for i, model in enumerate(models):
        try:
            logger.info("Prosecution pass: waiting on %s...", model)
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2),
            )
            text = _extract_text(resp)
            if not text:
                raise RuntimeError(f"Empty prosecution response from {model}")
            logger.info("Prosecution pass: %d chars", len(text))
            return text
        except Exception as err:
            last_err = err
            logger.warning("Prosecution %s failed: %s", model, err)
            if i == 0 and _is_rate_limit(err):
                continue
            raise
    raise RuntimeError(f"Prosecution failed: {last_err}") from last_err
