# AI Bubble Monitor

**Weekly slip-based crash-band model + AI-spend crash-risk signals — Gemini + live web search, push to your phone. $0 to run.**

The crash is **not a fixed date — it's a computed band** that recalculates as catalysts fire early or slip late. Each run the job: updates five catalyst trackers and recomputes the crash band, measures S&P/Nasdaq drawdown from ATH against the falsification deadline, places today on the Benner Cycle and scores conformance, checks five numeric health indicators plus a trusted-news scan, hunts for institutional-trap events (mega-cap equity raises / insider exits), runs a **prosecution pass** (the strongest case AGAINST the thesis from this run's data), and sends it all via [ntfy](https://ntfy.sh).

## The slip-band model

| Catalyst | Baseline | Slip rule |
| -------- | -------- | --------- |
| C1 SpaceX lockup | first window 2026-08, full expiry 2026-12 | No IPO past baseline → sequence runs late by that gap. Listed → expiry = listing + 6mo |
| C2 Fed direction | tracking | Early cut w/o stress → band +1mo later (cuts are fuel). Hold under stress → band −1mo (spring tightens) |
| C3 Anthropic/OpenAI lockups | listing 2026-11, lockup = listing + 180d (≈2027-05) | Band can't resolve until the second wave clears; listing date anchors everything downstream |
| C4 SaaS earnings cracks | Q1'27 reports (2027-04) | Confirmation only — never moves the band. A missed cycle = timeline **stretching** (+12mo warning), not sliding |
| C5 Unemployment (FRED UNRATE) | 4.3% | Confirmed uptrend (3mo avg +0.2pp, or ≥5.0%) → band pulls forward 2mo, recession-flavored. Flat → valuation reset (shallower) |

**Band formula:** start = C1 full expiry + 1mo + Fed net (−2mo if C5 uptrend); end = C3 lockup expiry + 3mo + Fed net. Baseline output: **2027-01 → 2027-08 (Q1–Q3 2027)**. Slip logic may push the band out indefinitely — by design: a model that can only pull the crash closer is just impatience with a spreadsheet.

**Falsification (stated 2026-06-05):** no S&P drawdown ≥30% by **2028-06-05** → thesis is wrong by its own criterion. Tracked numerically every run (FRED SP500/NASDAQCOM). If it HITS, the monitor demands an attribution answer: did it crash for the *stated* catalysts, or something off-list (war, credit event)? Off-list = timeline hit, thesis missed.

**Benner Cycle:** 2026 = SELL-peak year, 2032 = BUY-bottom, 2035 = panic-line year. Each run reports where we are on the chart and whether the market is conforming (10%+ off peak post-2026) or diverging bullish (new highs deep into 2027+). Context only — a 150-year-old chart is a rhyme, not a timing signal.

**Prosecution pass:** every notification ends with the naysayer's case — which of this run's "confirmations" are just noise, plus the observation that would most weaken and most strengthen the thesis this month, stated in advance.

Health indicators 1-4 use Gemini + Google Search with earnings-cycle freshness rules; Treasury, drawdowns, and unemployment use **FRED** directly (DGS10, SP500, NASDAQCOM, UNRATE).

**Where it runs:** [GitHub Actions](https://github.com/features/actions) executes the job (install deps, run `monitor.py`, commit `state.json`). **When it runs:** a free online cron service triggers the workflow — not GitHub's built-in schedule (that cron is often disabled or delayed).

*Example notification — values change each run.*

```
AI Bubble Monitor - 2026-06-11 (prev 2026-06-03)

CRASH BAND: 2027-01 -> 2027-08 (baseline 2027-01..2027-08, net slip +0mo)
Flavor: valuation reset (historically shallower, faster recovery)
C1 SpaceX lockup [pending] full expiry 2026-12 (on baseline)
...
FALSIFICATION: S&P 500 drawdown of 30%+ from ATH by 2028-06-05 - 24mo left | status: PENDING
BENNER CYCLE: 2026 = SELL-peak year (good times, high prices)
HEALTH INDICATORS: 1/5 bearish (STABLE)
...
PROSECUTION (the case against, this run): ...
NET STATUS: STABLE
```

**Cost:** Gemini API usage on a weekly schedule, GitHub Actions minutes when triggered, ntfy (free), [cron-job.org](https://cron-job.org/en/) (free).

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

### 5. GitHub repo + Actions secrets

Push this repo to GitHub (include seeded `state.json`).

| Secret | Purpose |
| ------ | ------- |
| `GEMINI_API_KEY` | Gemini API (indicators 1-4 + news) |
| `FRED_API_KEY` | 10-year Treasury (DGS10) |
| `NTFY_TOPIC` | ntfy topic |

Repo → **Settings → Secrets and variables → Actions** → add all three.

### 6. Verify the workflow (manual)

Actions → **ai-bubble-monitor** → **Run workflow** → **Run workflow** (`workflow_dispatch`).

Confirm: ntfy notification arrives; workflow commits `monitor run YYYY-MM-DD` if `state.json` changed.

### 7. Schedule with crontab.guru + cron-job.org

GitHub Actions **`schedule` cron is not used** — it is unreliable (repos go idle, runs skipped or delayed). Use free online cron instead:

| Tool | Role |
| ---- | ---- |
| [crontab.guru](https://crontab.guru/) | Build and verify the cron expression (editor only; does not run jobs) |
| [cron-job.org](https://cron-job.org/en/) | Free scheduler that calls GitHub on your timetable |

**Recommended:** every **Monday 12:00 UTC** — on crontab.guru that is:

```text
0 12 * * 1
```

**A. GitHub token for cron-job.org**

Create a [fine-grained personal access token](https://github.com/settings/tokens?type=beta) (or classic PAT) for this repo with **Actions: Read and write** (or classic `repo` scope). Store it only in cron-job.org, not in the repo.

**B. cron-job.org job**

1. Sign up at [cron-job.org](https://cron-job.org/en/).
2. **Create cronjob** → enable **Custom schedule** and paste the expression from crontab.guru (e.g. `0 12 * * 1`).
3. **URL** (replace `OWNER` / `REPO`):

   `https://api.github.com/repos/OWNER/REPO/actions/workflows/monitor.yml/dispatches`

4. **Request method:** `POST`
5. **Headers:**

   | Header | Value |
   | ------ | ----- |
   | `Accept` | `application/vnd.github+json` |
   | `Authorization` | `Bearer YOUR_GITHUB_TOKEN` |
   | `X-GitHub-Api-Version` | `2022-11-28` |

6. **Body** (raw JSON):

   ```json
   {"ref":"main"}
   ```

7. Save and use **Test run** once; check GitHub **Actions** for a new **ai-bubble-monitor** run.

**C. Change cadence**

Edit the expression on [crontab.guru](https://crontab.guru/) (e.g. `0 12 1 * *` = 12:00 UTC on the 1st of each month), then update the same expression in cron-job.org.

**Manual run anytime:** GitHub Actions → **Run workflow**, or trigger the same POST from cron-job.org's test button.

## Gotchas

- **Stale data:** Figures older than the current earnings cycle are marked `stale` and do not count toward the risk score.
- **Capex sanity:** 2027 total must be &ge; ~$725B (2026 floor); bearish only on &gt;5% drop plus cut language (ignores round-number noise vs seed).
- **ROI survey lock:** Only the configured PwC survey is tracked; swapping surveys caused false jumps (e.g. 56% vs 71%).
- **Treasury:** FRED close, not LLM; first run is neutral; bearish only on +25 bps vs prior or 3-month average.
- **ntfy text:** Notifications are ASCII-only (no emoji in title, body, or tags).
- **News scan:** Second Gemini call per run; high bearish needs 2+ trusted sources or stays medium/unconfirmed.
- **Google Search + JSON:** Fences stripped; one retry on parse failure.
- **Do not use GitHub `schedule`:** Use cron-job.org; keep the workflow as `workflow_dispatch` only.
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
└── .github/workflows/monitor.yml   # workflow_dispatch only (no schedule)
```
