"""Push monitor summary via ntfy (swappable for other providers)."""

from __future__ import annotations

import logging

import requests

import config

logger = logging.getLogger(__name__)

_PRIORITY = {"STABLE": "default", "WATCH": "high", "ELEVATED": "urgent"}


def _require_topic() -> str:
    topic = config.NTFY_TOPIC.strip()
    if not topic:
        raise ValueError("Missing required env var: NTFY_TOPIC")
    return topic


def to_ntfy_safe(text: str) -> str:
    """ASCII-only text for ntfy (no emoji, no smart punctuation)."""
    text = (
        text.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    return text.encode("ascii", "ignore").decode("ascii")


def send_notification(title: str, body: str, status: str) -> None:
    topic = _require_topic()
    safe_title = to_ntfy_safe(title)
    safe_body = to_ntfy_safe(body)
    logger.info("POST ntfy (priority=%s, body=%d bytes)", _PRIORITY[status], len(safe_body))
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=safe_body.encode("ascii"),
        headers={
            "Title": safe_title,
            "Priority": _PRIORITY[status],
        },
        timeout=20,
    )
    resp.raise_for_status()
    logger.info("ntfy response: HTTP %s", resp.status_code)
