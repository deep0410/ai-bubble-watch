# AI Bubble Monitor

**Weekly AI-spend crash-risk signals — Gemini + live web search, push to your phone. $0 to run.**

Automated job that checks five market indicators (hyperscaler capex, capacity language, Nvidia trajectory, enterprise ROI sentiment, Treasury yields), scores bearish flags, compares to the last run, and sends a summary via [ntfy](https://ntfy.sh). Runs on GitHub Actions; no server to maintain.

*Example notification — values change each run.*

```
AI Bubble Monitor — 2026-06-03
Risk score: 1/5  (STABLE)

1. 2027 capex guidance: $1050B ↑ OK
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
| 1 | 2027 hyperscaler capex guidance (AMZN, GOOG, META, MSFT, ORCL sum) | Flat or lower vs last run |
| 2 | Capacity language (earnings commentary) | Flips to "ample-capacity" |
| 3 | Nvidia next-Q guidance + DC YoY growth | Guidance not raised, or DC YoY &lt; 40% |
| 4 | Enterprise "no ROI from AI" survey % | Rises vs last run |
| 5 | US 10-year Treasury yield | Up &gt;25 bps vs last run (neutral on first run until yield is stored) |

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
- `NTFY_TOPIC` — long random topic string (treat like a password)

Optional: `GEMINI_MODEL` (default `gemini-2.5-pro`), `GEMINI_FALLBACK` (default `gemini-2.5-flash`).

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
| `GEMINI_API_KEY` | Gemini API |
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

- **Google Search + JSON:** With search grounding enabled, structured JSON mode is not used. The model returns JSON text; fences are stripped and invalid JSON retries once in `monitor.py`.
- **First treasury reading:** Seed `state.json` has `treasury_10y_yield_pct: null`. Run 1 fills the yield; indicator #5 is neutral until run 2 can compare.
- **Workflow disable:** GitHub may disable scheduled workflows after ~60 days with no repo activity. Weekly commit-back of `state.json` keeps the repo active.
- **Public repo:** `state.json` and `history` are committed — anyone with repo access sees past readings.
- **Model cost:** Set `GEMINI_MODEL=gemini-2.5-flash` in secrets/env if Pro is too expensive; Pro is better for multi-indicator research.

## Project layout

```
ai-bubble-watch/
├── monitor.py              # entrypoint
├── indicators.py           # Gemini + search + scoring
├── notify.py               # ntfy (swappable)
├── config.py               # env / dotenv
├── state.json              # rolling state (updated each run)
├── requirements.txt
├── .env.example
└── .github/workflows/monitor.yml
```
