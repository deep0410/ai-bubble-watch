"""Indicator 6: trusted news scan with escalate-only status override."""

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

NEWS_PROMPT = """You are a markets news analyst. Today is {today}; the previous run was {last_run}.
Using Google Search, find the most MATERIAL developments published BETWEEN {last_run} AND {today}
about the AI data-center capex / compute-demand / AI-financing thesis.

ONLY use these trusted sources: company IR pages, SEC filings, earnings-call transcripts, Reuters,
Bloomberg, CNBC, Wall Street Journal, Financial Times, Associated Press, The Information, Nikkei,
and named analyst notes (Goldman, Morgan Stanley, BofA, Evercore, JPMorgan, Jefferies, UBS) as
reported by those outlets. IGNORE Medium/Substack opinion, Reddit, X/Twitter rumor, and SEO blogs.

For each item set direction (bearish/bullish/neutral) and severity (low/medium/high). A "high"
severity requires TWO OR MORE independent trusted sources; if only one source exists, cap severity
at "medium" and set unconfirmed=true. Examples of material bearish events: a hyperscaler cutting
capex guidance or cancelling data-center builds; an AI lab funding stall/down-round/insolvency or a
withdrawn compute commitment; a circular-financing deal reversed/written down/probed; a model
efficiency shock; a large enterprise cutting AI spend; an AI-infra credit downgrade or failed debt
raise; regulatory/antitrust action on the capex/circular structure; a major Nvidia/hyperscaler
earnings miss with a sharp negative stock move.

Use plain ASCII in all strings (no emoji).
Return the top 5 items (fewer if little happened). Output ONLY this JSON, no prose:
{{
  "items": [
    {{"headline": str, "date": "YYYY-MM-DD", "sources": [str, ...], "summary": str,
      "direction": "bearish"|"bullish"|"neutral", "severity": "low"|"medium"|"high",
      "unconfirmed": bool}}
  ],
  "net_read": str
}}
"""

_ORDER = {"STABLE": 0, "WATCH": 1, "ELEVATED": 2}
_NAME = {0: "STABLE", 1: "WATCH", 2: "ELEVATED"}
_VALID_DIRECTIONS = frozenset({"bearish", "bullish", "neutral"})
_VALID_SEVERITIES = frozenset({"low", "medium", "high"})


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


def _parse_news_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("News response is not a JSON object")
    if "items" not in data or "net_read" not in data:
        raise ValueError("News response missing items or net_read")
    items = data["items"]
    if not isinstance(items, list):
        raise ValueError("News items must be a list")
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"News item {i} is not an object")
        for field in ("headline", "date", "sources", "summary", "direction", "severity"):
            if field not in it:
                raise ValueError(f"News item {i} missing {field}")
        if it["direction"] not in _VALID_DIRECTIONS:
            raise ValueError(f"News item {i} invalid direction")
        if it["severity"] not in _VALID_SEVERITIES:
            raise ValueError(f"News item {i} invalid severity")
        if "unconfirmed" not in it:
            it["unconfirmed"] = len(it.get("sources") or []) < 2
    return data


def apply_news_override(numeric_status: str, news_items: list[dict[str, Any]]) -> str:
    """Escalate-only: news can raise status, never lower it."""
    level = _ORDER.get(numeric_status, 0)
    for it in news_items:
        if it.get("direction") != "bearish":
            continue
        sev = it.get("severity")
        unconfirmed = it.get("unconfirmed", False)
        if sev == "high" and not unconfirmed:
            level = max(level, _ORDER["ELEVATED"])
        elif sev in ("high", "medium"):
            level = max(level, _ORDER["WATCH"])
    return _NAME[level]


def format_news_section(news: dict[str, Any]) -> str:
    items = news.get("items") or []
    if not items:
        lines = ["- No material events since last run."]
    else:
        lines = []
        for it in items:
            sources = ", ".join(it.get("sources") or [])[:120]
            suffix = " [unconfirmed]" if it.get("unconfirmed") else ""
            lines.append(
                f"- [{it['severity'].upper()}/{it['direction']}] {it['headline']} "
                f"({sources}, {it['date']}){suffix}"
            )
    net = news.get("net_read", "")
    return "\n".join(lines), net


def _call_gemini(client: genai.Client, model: str, prompt: str) -> str:
    logger.info(
        "News scan: waiting on %s + Google Search (often 1-2 minutes)...",
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
        raise RuntimeError(f"Empty news response from {model}")
    logger.info("News scan: received %d chars from %s", len(text), model)
    return text


def run_news_scan(today: str, last_run: str) -> dict[str, Any]:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = NEWS_PROMPT.format(today=today, last_run=last_run)
    models = [config.GEMINI_NEWS_MODEL, config.GEMINI_FALLBACK]

    last_err: Exception | None = None
    for i, model in enumerate(models):
        try:
            text = _call_gemini(client, model, prompt)
            data = _parse_news_json(text)
            logger.info("News scan: %d items, net_read=%s", len(data["items"]), data["net_read"][:80])
            for j, it in enumerate(data["items"]):
                logger.info(
                    "  news[%d]: %s/%s %s",
                    j,
                    it["severity"],
                    it["direction"],
                    (it.get("headline") or "")[:60],
                )
            return data
        except json.JSONDecodeError as err:
            last_err = err
            logger.warning("News JSON parse failed for %s: %s", model, err)
            raise
        except Exception as err:
            last_err = err
            logger.warning("News scan %s failed: %s", model, err)
            if i == 0 and _is_rate_limit(err):
                logger.info("News rate limited; trying %s", models[1])
                continue
            raise

    raise RuntimeError(f"News scan failed: {last_err}") from last_err
