# @theheat — Project Briefing

**Last updated:** April 9, 2026
**Status:** Live on GitHub Actions. Drafts generating. Gist auth working. 200 tests green.
**Latest commit:** `7994d4b` on `main`
**Cost:** $0/month (all free tiers)

---

## What is this?

@theheat is an automated climate data bot for X (Twitter). It monitors 13 free public data sources for extreme weather events — record temperatures, wildfires, floods, storm surge, CO2 milestones, sea ice loss, drought, ocean waves, ENSO shifts, and severe weather alerts — then generates tweets with personality and queues them for human review.

The differentiator is not the data (it's all public). It's the voice: a cynical weatherman who's seen too much. Dry wit, deadpan context, zero preaching. The data is already extraordinary; the bot just frames it so people feel the weight of the numbers.

**Target audience:** Data people. The FlightRadar24 crowd. Weather nerds. People who want to be informed but unfollow anyone who lectures them.

---

## Architecture

```
CRON (GitHub Actions free tier, 6x/day alerts + hourly auto-approval)
│
├── Fetch from 13 free data sources
│   ├── Open-Meteo ──────── record highs, record lows, city temps
│   ├── NOAA ACIS ────────── US record confirmations (24-72h delayed)
│   ├── NASA FIRMS ────────── satellite wildfire detections
│   ├── NOAA GML ──────────── Mauna Loa CO2 (daily PPM)
│   ├── NWS Alerts ────────── US severe weather (tornado, flood, winter)
│   ├── GDACS ──────────────── global disasters (cyclones, quakes, floods)
│   ├── NSIDC ──────────────── Arctic/Antarctic sea ice extent
│   ├── US Drought Monitor ── state-level drought severity
│   ├── NOAA CPC ──────────── ENSO (El Nino / La Nina) status
│   ├── Open-Meteo Marine ── ocean wave heights (16 points)
│   ├── NOAA CO-OPS ────────── coastal tide gauge anomalies (12 stations)
│   └── USGS Water ────────── river flood stages (12 gauges)
│
├── Score events (editorial scoring: severity, novelty, timeliness, confidence, shareability, sensitivity)
│
├── Deduplicate against state (last 500 event IDs)
│
├── Generate tweets via Gemini 2.5 Flash (4 candidates ranked per event)
│   ├── System prompt enforces voice rules + structure variety
│   ├── Safety pipeline: 38 regex patterns + LLM semantic check
│   └── Fallback: template-based tweets if Gemini fails
│
├── Assign approval policy (armed_auto / suggested_auto / manual_only)
│
├── Save drafts to GitHub Gist (state.json)
│
├── AUTO-APPROVAL QUEUE (hourly cron)
│   ├── Low-sensitivity + high-scoring drafts auto-post after timed delay
│   └── Safety pipeline re-runs before every auto-post
│
└── DASHBOARD (Next.js 15 on Vercel) ── human reviews remaining drafts
    └── Posts to X via Tweepy + cross-posts to Bluesky
```

---

## Codebase

```
theheat/
├── src/                              ~5,575 lines Python
│   ├── main.py                       Orchestrator (1,386 lines)
│   ├── state.py                      GitHub Gist state management
│   ├── data/                         12 data source modules
│   │   ├── open_meteo.py             Temperature records + leaderboard + anomalies
│   │   ├── firms.py                  NASA FIRMS wildfires
│   │   ├── co2.py                    Mauna Loa CO2 daily + weekly comparison
│   │   ├── noaa_acis.py              NOAA record confirmation (US, 24-72h delayed)
│   │   ├── nws_alerts.py             NWS severe weather alerts
│   │   ├── gdacs.py                  Global disasters (cyclones, quakes, floods)
│   │   ├── sea_ice.py                Arctic/Antarctic ice extent vs records
│   │   ├── drought.py                US Drought Monitor state-level
│   │   ├── enso.py                   El Nino / La Nina transitions
│   │   ├── ocean.py                  Extreme ocean waves (16 monitoring points)
│   │   ├── water_levels.py           NOAA CO-OPS tide gauge storm surge
│   │   └── river_gauges.py           USGS river flood stages
│   ├── editorial/                    Scoring + ranking + approval policies
│   │   ├── scoring.py                14 hand-tuned scoring functions (signal score)
│   │   ├── candidates.py             Multi-candidate ranking (copy score)
│   │   ├── approval.py               3-tier approval policy engine
│   │   └── _util.py                  Shared clamp utility
│   ├── voice/
│   │   ├── generator.py              Gemini Flash + 14 generator functions + 4-candidate ranking
│   │   ├── templates.py              Fallback templates (no AI needed)
│   │   └── safety.py                 Two-layer safety pipeline (38 regex + LLM)
│   ├── posting/
│   │   ├── twitter.py                X API via Tweepy (rate-limit aware)
│   │   └── bluesky.py                AT Protocol cross-posting
│   └── storage/
│       └── sqlite_store.py           SQLite backend (exists but unused — ephemeral CI)
│
├── tests/                            20 test files, 200 tests
│   ├── test_main.py                  Orchestrator: alerts, leaderboard, manual post, auto-approval, save_draft
│   ├── test_posting.py               Twitter posting, rate limit handling
│   ├── test_safety.py                Regex patterns + LLM safety fallback
│   ├── test_open_meteo.py            Record detection, anomaly calculation
│   ├── test_co2.py                   CO2 milestone + weekly comparison
│   ├── test_firms.py                 Fire detection parsing
│   ├── test_nws_alerts.py            Severe weather alert parsing
│   ├── test_gdacs.py                 Global disaster detection
│   ├── test_sea_ice.py               Sea ice record detection
│   ├── test_drought.py               Drought severity parsing
│   ├── test_enso.py                  ENSO transition detection
│   ├── test_ocean.py                 Wave height detection
│   ├── test_water_levels.py          Storm surge detection
│   └── test_river_gauges.py          River flood stage detection
│
├── dashboard/                        Next.js 15 + React 19 (Vercel free tier)
│   └── app/
│       ├── page.js                   Full control panel UI
│       ├── layout.js                 Dark terminal theme
│       └── api/
│           ├── state/route.js        Read Gist state
│           ├── drafts/route.js       Draft management
│           ├── generate/route.js     Trigger GitHub Actions workflow_dispatch
│           ├── post/route.js         Post approved tweet via workflow_dispatch
│           └── trigger/route.js      Trigger specific run modes
│
├── data/
│   ├── cities.csv                    257 cities with lat/lon
│   └── normals.csv                   Climatological normals by city/month
│
├── brand/
│   └── MESSAGING_ARCHITECTURE.md     Positioning, voice spec, messaging framework
│
├── .github/workflows/bot.yml        CI (pytest gates deployment) + cron automation
├── DESIGN.md                         Architecture decisions
├── VOICE.md                          Brand voice spec
├── BUILD_BRIEF.md                    Product scope
└── requirements.txt                  7 deps (tweepy, atproto, google-genai, requests, pytest, pytest-mock, responses)
```

---

## Data Flow: Alert Cycle

Every 4 hours, GitHub Actions runs `python -m src.main alerts`:

1. **Read state** from GitHub Gist (event IDs, drafts, daily counts, errors, run history)
2. **Fetch data** from all 13 sources (each wrapped in try/catch — failures don't block others)
3. **Score events** — editorial scoring evaluates severity, novelty, timeliness, confidence, shareability, and sensitivity. Events below threshold are suppressed.
4. **Deduplicate** — skip any event already in `posted_events` (last 500)
5. **Generate 4 candidates** — call the source-specific generator which sends structured data + system prompt to Gemini 2.5 Flash, then rank by copy score
6. **Safety check** — regex gate (38 patterns: emojis, hashtags, exclamation marks, policy language, killed phrases), then LLM check ("does this mock human suffering?")
7. **Assign approval policy** — `armed_auto` (will auto-post after delay), `suggested_auto` (suggests auto but requires human), or `manual_only` (human required)
8. **Save draft** — append to `state.drafts[]` with status "pending", editorial metadata, and auto-approve timestamp if armed_auto
9. **Write state** back to Gist (with retry on failure)
10. **Record run telemetry** — per-source timing, observed/promoted/drafted counts, errors

## Data Flow: Auto-Approval (hourly)

Every hour, GitHub Actions runs `python -m src.main auto_publish_due`:

1. Scan drafts for `auto_approve_at` timestamps that have elapsed
2. Verify `armed_auto` mode — block if policy isn't actually armed
3. Re-run safety pipeline — catch anything the initial check missed
4. Post to X via Tweepy, cross-post to Bluesky
5. On rate-limit (429): keep draft pending for retry next hour

## Data Flow: Manual Posting

Human opens dashboard -> sees pending drafts -> approves -> dashboard triggers `workflow_dispatch` with `mode=manual_tweet`, `DRAFT_ID`, and `PUBLISH_INTENT_ID` -> GitHub Actions posts via Tweepy -> draft marked as "posted" -> cross-posts to Bluesky.

## Data Flow: Leaderboard

Daily at 12:00 UTC, `python -m src.main both`:

1. Fetch temps for 257 cities from Open-Meteo
2. Compute anomalies vs historical normals (climatological averages by city/month)
3. Rank top 10 by anomaly (how far above normal)
4. Track position changes from yesterday, update streaks
5. Generate Hot 10 tweet via Gemini (with template fallback)
6. Save as draft with hot10 editorial score

---

## Schedule

| UTC   | Cron             | Mode              | What runs                                  |
|-------|------------------|-------------------|--------------------------------------------|
| :30   | `30 * * * *`     | auto_publish_due  | Process auto-approval queue (hourly)       |
| 00:00 | `0 0 * * *`      | alerts            | All 13 sources                             |
| 04:00 | `0 4 * * *`      | alerts            | All 13 sources                             |
| 08:00 | `0 8 * * *`      | alerts            | All 13 sources                             |
| 12:00 | `0 12 * * *`     | both              | Leaderboard + all 13 sources               |
| 16:00 | `0 16 * * *`     | alerts            | All 13 sources                             |
| 20:00 | `0 20 * * *`     | alerts            | All 13 sources                             |

**Source-specific gates:**
- Sea ice: Mondays only
- Drought: Fridays only
- ENSO: 1st of month only
- CO2 milestone: Max once per day
- CO2 weekly comparison: Sundays only

---

## Editorial System

### Signal Scoring (`src/editorial/scoring.py`)

Every event gets a signal score (0-100) based on weighted factors:
- **Severity** (28%) — how extreme is the reading
- **Novelty** (24%) — how rare / record-breaking
- **Timeliness** (16%) — how fresh
- **Confidence** (16%) — data source reliability
- **Shareability** (16%) — viral potential
- **Sensitivity** (-20% penalty) — human-harm risk

Labels: `elite` (85+), `strong` (72+), `borderline` (60+), `weak` (<60).
Events below threshold are suppressed before generation.

14 scoring functions cover every event type: records, fires, CO2, severe weather, disasters, sea ice, drought, ENSO, waves, storm surge, river floods, NOAA confirmations, Hot 10.

### Copy Scoring (`src/editorial/candidates.py`)

Gemini generates 4 candidate tweets per event. Each is scored on:
- Data density (numbers, units, years)
- Voice compliance (caps usage, structure patterns)
- Category-specific keyword presence
- Length optimization

Best candidate is selected automatically.

### Approval Policies (`src/editorial/approval.py`)

Three tiers based on event type + score quality:

| Mode | Behavior | Used for |
|------|----------|----------|
| `armed_auto` | Auto-posts after timed delay (20-90 min) | Hot 10, CO2, NOAA confirmations — only if both signal and copy scores are strong |
| `suggested_auto` | Suggests auto-post but won't actually do it | Records, sea ice, ENSO, extreme waves |
| `manual_only` | Requires human approval | Fires, severe weather, disasters, storm surge, river floods, drought |

---

## Voice

**Character:** A cynical weatherman who's seen too much.
**Tone:** 70% dry observation, 20% dark humor, 10% genuine awe.

Example tweets (from the system prompt — each uses a different structure):

> Phoenix just dropped 121F. NEW RECORD. The old one was from last year.

> Buenos Aires hit 42.1C. That broke a 97-year record set in 1929.

> 36-foot waves in Drake Passage today. 11 meters. That's a three-story building made of ocean.

> CO2 this week at Mauna Loa: 436.2 ppm. Same week last year: 433.8. We added 2.4 ppm in a year. That used to take a decade.

> Mississippi at Baton Rouge: 42.3ft. Flood stage is 35ft. The river doesn't care what month it is.

> New wildfire in Northern California. Satellite confidence: HIGH. 0% contained. It's April.

> Satellite picked up a 1,200 MW fire in Siberia. For reference, a large power plant is about 1,000 MW. Except it's a forest.

**Voice rules enforced by safety pipeline:**
- Under 280 chars, no exceptions
- No emojis, hashtags, or exclamation marks
- CAPS for emphasis, sparingly
- Vary structure — the "Word. Word. Word." pattern is ONE tool, not the default (max once per 10 tweets)
- Never preach, never political, never moralize
- Never mock human suffering
- No sports metaphors, gaming slang, or forced catchphrases
- Personality comes from *framing*, not vocabulary

---

## Safety Pipeline

**Layer 1 — Regex (deterministic, always runs):**
- Length check (280 chars)
- 38 banned patterns: emoji Unicode ranges, `#hashtags`, `BREAKING:`, `!`, policy language ("we need to", "governments must"), killed voice patterns ("career high", "cooked", "rekt", "nobody asked")

**Layer 2 — LLM (Gemini Flash):**
- Asks: "Does this tweet mock human suffering, trivialize death, or cross from dark humor into cruelty?"
- If Gemini unavailable, tweet passes (regex already caught the mechanical stuff)
- Failures logged: `[safety] LLM safety check failed, falling back to regex only: {e}`

**Fallback chain:** Gemini generation (4 candidates) -> 3 retries on safety rejection -> template-based fallback -> None (skip event)

**Double-gate on auto-publish:** Safety pipeline runs at generation time AND again before every auto-post.

---

## State Management

Single JSON file stored in a GitHub Gist, read/written via GitHub API each run.

```json
{
  "last_hot10":    { "date": "...", "cities": [...] },
  "streaks":       { "Miami": { "consecutive_days": 14, "last_seen": "..." } },
  "posted_events": [ "record_PHX_20260407", "firms_fire_12345", ... ],
  "daily_tweet_count": { "2026-04-09": 3 },
  "pending_confirmations": [ { "event_id": "...", "detected": "...", "city": "..." } ],
  "drafts": [
    {
      "id": "draft_20260409_120000_0",
      "text": "Phoenix just dropped 121F...",
      "type": "record",
      "event_id": "record_PHX_20260409",
      "status": "pending",
      "score": { "total": 82, "category": "strong", ... },
      "candidates": [ ... ],
      "candidate_score": { "total": 78, ... },
      "approval_policy": { "mode": "suggested_auto", "can_auto_approve": true, ... },
      "review_context": { "source": "Open-Meteo", "headline": "...", "facts": [...] },
      "auto_approve_at": "2026-04-09T12:20:00Z",
      "created_at": "2026-04-09T12:00:00Z",
      "updated_at": "2026-04-09T12:00:00Z"
    }
  ],
  "run_history": [ { "id": "...", "mode": "alerts", "started_at": "...", "sources": [...] } ],
  "errors": [ { "source": "...", "ts": "...", "msg": "..." } ]
}
```

**Caps:** 500 event IDs, 200 drafts (pruned oldest non-pending), 50 errors, 10 tweets/day.
**State write:** Retries once on failure. Logs error if both writes fail.

---

## Dashboard

Next.js 15 + React 19 app on Vercel free tier. Dark terminal aesthetic.

**Sections:**
- **Drafts to Review** — pending tweets with approve/edit/delete, editorial scores, approval policy, review context
- **Generate Drafts** — trigger alerts, leaderboard, or both via workflow_dispatch
- **Compose Tweet** — manual composition with Gemini generation
- **Stats** — tweets today (of 10 cap), last Hot 10 date
- **Hot 10 Leaderboard** — last ranking with anomaly values
- **Streaks** — consecutive days in Hot 10
- **Recent Runs** — GitHub Actions history with status, timing, per-source results
- **Recent Errors** — last 10 errors from state

**API routes:** All proxy through Vercel to the GitHub Gist API and GitHub Actions workflow_dispatch.

---

## Test Coverage

200 tests across 20 files. Every data source module, the generator, safety pipeline, state management, editorial scoring, candidate ranking, approval policies, auto-publish flow, and main orchestrator have unit tests. Mocks use `responses` for HTTP and `pytest-mock` for dependency injection.

CI runs `pytest` before every bot job (except hourly auto-approval cron) — broken tests block deployment.

Key test areas:
- `test_main.py` — orchestrator flows, draft saving with score/candidate/policy metadata, auto-approval safety gates, rate-limit retry, manual posting validation
- `test_posting.py` — rate-limit sentinel detection, auth failure handling
- `test_safety.py` — all 38 regex patterns, LLM fallback behavior
- Data source tests — response parsing, edge cases, deduplication

---

## Dependencies

```
tweepy>=4.14,<5       # X API posting
atproto>=0.0.61       # Bluesky cross-posting
google-genai>=1.0     # Gemini 2.5 Flash (generation + safety LLM)
requests>=2.31        # HTTP for all data sources
pytest>=8.0           # Tests
pytest-mock>=3.12     # Mocking
responses>=0.25       # HTTP response mocking
```

No heavyweight ML libraries. No databases in production. No servers beyond Vercel free tier.

---

## Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `TWITTER_API_KEY`, `TWITTER_API_SECRET` | X API app credentials |
| `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET` | X API user credentials |
| `GEMINI_API_KEY` | Google Gemini 2.5 Flash |
| `GIST_ID` | State storage (`06c02c97ffc0d11458687f1ed998d9e5`) |
| `GH_GIST_TOKEN` | PAT with `gist` scope for Gist read/write |
| `NASA_FIRMS_API_KEY` | NASA fire satellite detection |
| `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | Bluesky cross-posting |

**Note:** The default `GITHUB_TOKEN` in Actions only has read permissions. A separate PAT (`GH_GIST_TOKEN`) with `gist` scope is required for state writes.

---

## Known Issues & Next Steps

### Issues
1. **Sequential API calls** — Ocean monitoring hits 16 endpoints one at a time (up to 160s). City temps fetch 257 cities sequentially. Total alert cycle ~13 minutes. Not a blocker (Actions has 6-hour limit) but slow.
2. **Dashboard behind** — Vercel deployment is from an older commit. Needs redeploy to pick up Codex's dashboard overhaul and latest changes.
3. **SQLite store unused** — `src/storage/sqlite_store.py` exists (356 lines) but is dormant. Ephemeral GitHub Actions runners mean the DB is lost each run, and the write path never syncs back to Gist. Could be removed or repurposed for local dev.

### Biggest growth levers (not yet built)
1. **Image generation** — Text-only tweets right now. @extremetemps (100K followers) posts maps and visual cards. Hot 10 cards, record cards, fire maps are the single biggest engagement unlock.
2. **X profile** — Bio, banner, and icon need finalization for @theheat.
3. **Thread support** — Multi-tweet threads for complex events (e.g. weekly CO2 + context).

---

## Repo

- **GitHub:** `github.com/andrewzp/theheat`
- **Branch:** `main` (all code merged, latest: `7994d4b`)
- **Gist ID:** `06c02c97ffc0d11458687f1ed998d9e5`
- **Dashboard:** Vercel (theheat dashboard project)
- **X:** @theheat
