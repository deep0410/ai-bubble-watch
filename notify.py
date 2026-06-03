"""Push monitor summary via ntfy (swappable for other providers)."""

from __future__ import annotations

import requests

import config

_PRIORITY = {"STABLE": "default", "WATCH": "high", "ELEVATED": "urgent"}
_TAGS = {"STABLE": "green_circle", "WATCH": "yellow_circle", "ELEVATED": "red_circle"}


def _require_topic() -> str:
    topic = config.NTFY_TOPIC.strip()
    if not topic:
        raise ValueError("Missing required env var: NTFY_TOPIC")
    return topic


def send_notification(title: str, body: str, status: str) -> None:
    topic = _require_topic()
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": _PRIORITY[status],
            "Tags": _TAGS[status],
        },
        timeout=20,
    )
    resp.raise_for_status()
