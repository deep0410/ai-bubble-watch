"""Central config: env vars and model defaults."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ENV_FILE = _ROOT / ".env"


def _load_dotenv() -> None:
    if not _ENV_FILE.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE)
    except ImportError:
        pass


_load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_FALLBACK = os.getenv("GEMINI_FALLBACK", "gemini-2.5-flash")
GEMINI_NEWS_MODEL = os.getenv("GEMINI_NEWS_MODEL", GEMINI_FALLBACK)
ROI_SURVEY_NAME = os.getenv("ROI_SURVEY_NAME", "PwC Global CEO Survey")
ROI_METRIC = os.getenv(
    "ROI_METRIC",
    "% of CEOs reporting no value / 'nothing' from AI investment",
)
CAPEX_2026_FLOOR_USD_BN = int(os.getenv("CAPEX_2026_FLOOR_USD_BN", "725"))
STATE_PATH = _ROOT / "state.json"


def project_root() -> Path:
    return _ROOT
