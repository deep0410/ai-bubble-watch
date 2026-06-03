# AI Bubble Monitor

**Weekly AI-spend crash-risk signals — Gemini + live web search, push to your phone. $0 to run.**

Automated job that checks five numeric market indicators plus a trusted-news scan (hyperscaler capex, capacity language, Nvidia trajectory, enterprise ROI sentiment, Treasury yields), scores bearish flags, compares to the last run, and sends a summary via [ntfy](https://ntfy.sh). Indicators 1-4 use Gemini + Google Search with earnings-cycle freshness rules; indicator 5 uses the **FRED DGS10** API directly. Runs on GitHub Actions; no server to maintain.

*Example notification — values change each run.*

```
AI Bubble Monitor - 2026-06-03
Risk score: 1/5 (STABLE)

1. 2027 capex guidance: $1050B + ok
   ...
```

**Cost:** Gemini API usage on a weekly schedule, GitHub Actions (free tier), ntfy (free).

## Risk levels

| Score | Status | Meaning |
| ----- | ------ | ------- |
| 0–1 | STABLE | Thesis intact |
| 2–3 | WATCH | Cracks forming |
| 4–5 | ELEVATED | Correction conditions aligning |

## Indicators

| # | Signal | Bearish when |
| - | ------ | ------------ |
| 1 | 2027 hyperscaler capex guidance (AMZN, GOOG, META, MSFT, ORCL sum) | Material cut (>5%) with cutting language, not rising narrative |
| 2 | Capacity language (earnings commentary) | Two+ hyperscalers say ample capacity |
| 3 | Nvidia next-Q guidance + DC YoY growth | Guidance not raised, or DC YoY &lt; 40% |
| 4 | **PwC Global CEO Survey** only (% "nothing" from AI) | Worse vs prior edition only |
| 5 | US 10-year Treasury (FRED DGS10) | +25 bps vs last run or vs 3mo avg (neutral first run) |
| 6 | Trusted news since last run | Escalate-only: confirmed high bearish -> ELEVATED; medium bearish -> WATCH |

**Net status** = numeric score status, raised by news if needed (news never lowers status).

This is a **signal tracker, not financial advice.**

## Setup

### 1. Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Secrets (local)

```bash
cp .env.example .env
```

Fill in:

- `GEMINI_API_KEY` — [Google AI Studio](https://aistudio.google.com)
- `FRED_API_KEY` — free key from [FRED](https://fredaccount.stlouisfed.org)
- `NTFY_TOPIC` — long random topic string (treat like a password)

Optional: `GEMINI_MODEL`, `GEMINI_FALLBACK`, `GEMINI_NEWS_MODEL` (defaults to flash for the news pass), `ROI_SURVEY_NAME`, `ROI_METRIC`, `CAPEX_2026_FLOOR_USD_BN` (default 725).

### 3. ntfy

Install the [ntfy app](https://ntfy.sh), subscribe to your topic, set the same value in `.env`.

### 4. Test locally

```bash
python monitor.py
```

Expect: printed summary in the terminal, ntfy notification on your phone, updated `state.json` with a new `history` entry.

### 5. GitHub Actions secrets

| Secret | Purpose |
| ------ | ------- |
| `GEMINI_API_KEY` | Gemini API (indicators 1-4) |
| `FRED_API_KEY` | 10-year Treasury (DGS10) |
| `NTFY_TOPIC` | ntfy topic |

Repo → **Settings → Secrets and variables → Actions** → add both.

### 6. Deploy and verify CI

1. Push this repo to GitHub (include seeded `state.json`).
2. Actions → **ai-bubble-monitor** → **Run workflow** (`workflow_dispatch`).
3. Confirm: ntfy notification arrives; workflow commits `monitor run YYYY-MM-DD` if `state.json` changed.

## Schedule

Default: **every Monday, 12:00 UTC** (see `.github/workflows/monitor.yml`).

To change cadence, edit the cron in `monitor.yml` (e.g. `"0 12 1 * *"` for monthly on the 1st).

## Gotchas

- **Stale data:** Figures older than the current earnings cycle are marked `stale` and do not count toward the risk score.
- **Capex sanity:** 2027 total must be &ge; ~$725B (2026 floor); bearish only on &gt;5% drop plus cut language (ignores round-number noise vs seed).
- **ROI survey lock:** Only the configured PwC survey is tracked; swapping surveys caused false jumps (e.g. 56% vs 71%).
- **Treasury:** FRED close, not LLM; first run is neutral; bearish only on +25 bps vs prior or 3-month average.
- **ntfy text:** Notifications are ASCII-only (no emoji in title, body, or tags).
- **News scan:** Second Gemini call per run; high bearish needs 2+ trusted sources or stays medium/unconfirmed.
- **Google Search + JSON:** Fences stripped; one retry on parse failure.
- **Workflow disable:** GitHub may disable scheduled workflows after ~60 days with no repo activity. Weekly commit-back of `state.json` keeps the repo active.
- **Public repo:** `state.json` and `history` are committed — anyone with repo access sees past readings.
- **Model cost:** Set `GEMINI_MODEL=gemini-2.5-flash` in secrets/env if Pro is too expensive; Pro is better for multi-indicator research.

## Project layout

```
ai-bubble-watch/
├── monitor.py              # entrypoint
├── indicators.py           # Gemini + search (indicators 1-4)
├── rates.py                # FRED DGS10 (indicator 5)
├── earnings_calendar.py    # earnings-cycle label for prompt
├── capex.py                # indicator 1 tolerance + direction guard
├── news.py                 # indicator 6 news scan + status override
├── notify.py               # ntfy (swappable)
├── config.py               # env / dotenv
├── state.json              # rolling state (updated each run)
├── requirements.txt
├── .env.example
└── .github/workflows/monitor.yml
```
