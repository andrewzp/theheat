# @theheat — Project Briefing

**Last updated:** April 8, 2026
**Status:** Live on GitHub Actions, generating drafts. Blocked on Gist auth token (state writes failing).
**Cost:** $0/month

---

## What is this?

@theheat is an automated climate data bot for X (Twitter). It monitors 13 free data sources for extreme weather events — record temperatures, wildfires, floods, storm surge, CO2 milestones, sea ice loss, drought, ocean waves, ENSO shifts, and severe weather alerts — then generates tweets with personality and queues them for human review.

The differentiator is not the data (it's all public). It's the voice: a cynical weatherman who's seen too much. Dry wit, deadpan context, zero preaching. The data is already extraordinary; the bot just frames it so people feel the weight of the numbers.

**Target audience:** Data people. The FlightRadar24 crowd. Weather nerds. People who want to be informed but unfollow anyone who lectures them.

---

## Architecture

```
CRON (GitHub Actions, 6x/day)
│
├── Fetch from 13 free data sources
│   ├── Open-Meteo ──── record highs, record lows, city temps
│   ├── NOAA ACIS ───── US record confirmations (24-72h delayed)
│   ├── NASA FIRMS ──── satellite wildfire detections
│   ├── NOAA GML ────── Mauna Loa CO2 (daily PPM)
│   ├── NWS Alerts ──── US severe weather (tornado, flood, winter)
│   ├── GDACS ───────── global disasters (cyclones, quakes, floods)
│   ├── NSIDC ───────── Arctic/Antarctic sea ice extent
│   ├── US Drought Monitor ── state-level drought severity
│   ├── NOAA CPC ────── ENSO (El Nino / La Nina) status
│   ├── Open-Meteo Marine ── ocean wave heights (16 points)
│   ├── NOAA CO-OPS ─── coastal tide gauge anomalies (12 stations)
│   └── USGS Water ──── river flood stages (12 gauges)
│
├── Deduplicate against state (last 500 event IDs)
│
├── Generate tweets via Gemini 2.5 Flash
│   ├── System prompt enforces voice rules
│   ├── Safety pipeline: 38 regex patterns + LLM check
│   └── Fallback: template-based tweets if Gemini fails
│
├── Save drafts to GitHub Gist (state.json)
│
└── DASHBOARD (Vercel) ── human reviews, approves, posts
    └── Posts to X via Tweepy
```

**Nothing auto-posts.** Every tweet goes to drafts first.

---

## Codebase

```
theheat/
├── src/                          ~5,000 lines Python
│   ├── main.py                   Orchestrator (525 lines)
│   ├── state.py                  GitHub Gist state management
│   ├── data/                     12 data source modules
│   │   ├── open_meteo.py         Temperature records + leaderboard
│   │   ├── firms.py              NASA FIRMS wildfires
│   │   ├── co2.py                Mauna Loa CO2
│   │   ├── noaa_acis.py          NOAA record confirmation (US)
│   │   ├── nws_alerts.py         NWS severe weather
│   │   ├── gdacs.py              Global disasters
│   │   ├── sea_ice.py            Arctic/Antarctic ice extent
│   │   ├── drought.py            US Drought Monitor
│   │   ├── enso.py               El Nino / La Nina
│   │   ├── ocean.py              Extreme ocean waves
│   │   ├── water_levels.py       NOAA tide gauge storm surge
│   │   └── river_gauges.py       USGS river flood stages
│   ├── voice/
│   │   ├── generator.py          Gemini Flash + 14 generator functions
│   │   ├── templates.py          Fallback templates (no AI needed)
│   │   └── safety.py             Two-layer safety pipeline
│   └── posting/
│       ├── twitter.py            X API via Tweepy
│       └── bluesky.py            AT Protocol cross-posting
│
├── tests/                        18 test files, 165 tests
├── dashboard/                    Next.js 15 + React 19 (Vercel)
│   └── app/
│       ├── page.js               Control panel UI (550 lines)
│       └── api/                  5 API routes (state, drafts, generate, post, trigger)
│
├── data/
│   ├── cities.csv                257 cities with lat/lon
│   └── normals.csv               Climatological normals by city/month
│
├── .github/workflows/bot.yml     CI (pytest) + cron automation
├── DESIGN.md                     Architecture decisions
├── VOICE.md                      Brand voice spec
├── BUILD_BRIEF.md                Product scope
└── brand/MESSAGING_ARCHITECTURE.md  Positioning & messaging
```

---

## Data Flow: Alert Cycle

Every 4 hours, GitHub Actions runs `python -m src.main alerts`:

1. **Read state** from GitHub Gist (event IDs, drafts, daily counts, errors)
2. **Fetch data** from all 13 sources (each wrapped in try/catch, failures don't block others)
3. **Deduplicate** — skip any event already in `posted_events`
4. **Generate tweet** — call the source-specific generator (e.g. `generate_record_tweet`), which sends structured data + the system prompt to Gemini 2.5 Flash
5. **Safety check** — regex gate (38 patterns: emojis, hashtags, exclamation marks, policy language, killed phrases), then LLM check ("does this mock human suffering?")
6. **Save draft** — append to `state.drafts[]` with status "pending"
7. **Write state** back to Gist

At 12:00 UTC, the leaderboard also runs: fetch temps for 257 cities, compute anomalies vs historical normals, rank top 10, generate Hot 10 tweet.

## Data Flow: Posting

Human opens dashboard → sees pending drafts → approves → dashboard triggers `workflow_dispatch` with `mode=manual_tweet` and `TWEET_TEXT` → GitHub Actions posts via Tweepy → draft marked as "posted" in state.

---

## Schedule

| UTC   | Mode      | What runs                                            |
|-------|-----------|------------------------------------------------------|
| 00:00 | alerts    | All 13 sources                                       |
| 04:00 | alerts    | All 13 sources                                       |
| 08:00 | alerts    | All 13 sources                                       |
| 12:00 | both      | Leaderboard + all 13 sources                         |
| 16:00 | alerts    | All 13 sources                                       |
| 20:00 | alerts    | All 13 sources                                       |

Some sources have additional gates:
- **Sea ice:** Mondays only
- **Drought:** Fridays only
- **ENSO:** 1st of month only
- **CO2 milestone:** Max once per day
- **CO2 weekly comparison:** Sundays only

---

## Voice

**Character:** A cynical weatherman who's seen too much.
**Tone:** 70% dry observation, 20% dark humor, 10% genuine awe.

Example tweets (from the system prompt):

> Phoenix just dropped 121F. NEW RECORD. The old one was from last year.

> Buenos Aires just put up 42.1C. That broke a 97-year record. Ninety. Seven. Years.

> Atmospheric CO2 at Mauna Loa: 433.24 ppm. First time above 433 in recorded history. Pre-industrial was 280.

> CO2 this week at Mauna Loa: 436.2 ppm. Same week last year: 433.8. We added 2.4 ppm in a year. That used to take a decade.

> New wildfire in Northern California. Satellite confidence: HIGH. 0% contained. It's April.

**Rules enforced by safety pipeline:**
- Under 280 chars, no exceptions
- No emojis, hashtags, or exclamation marks
- CAPS for emphasis, periods for deadpan
- Never preach, never political, never moralize
- Never mock human suffering
- No sports metaphors, no gaming slang, no forced catchphrases
- Personality comes from *framing*, not vocabulary

---

## Safety Pipeline

**Layer 1 — Regex (deterministic, always runs):**
- Length check (280 chars)
- 38 banned patterns: emoji Unicode ranges, `#hashtags`, `BREAKING:`, `!`, policy language ("we need to", "governments must"), killed voice patterns ("career high", "cooked", "rekt", "nobody asked")

**Layer 2 — LLM (Gemini Flash):**
- Asks: "Does this tweet mock human suffering, trivialize death, or cross from dark humor into cruelty?"
- If Gemini unavailable, tweet passes (regex already caught the mechanical stuff)

**Fallback chain:** Gemini generation → 3 retries on safety rejection → template-based fallback → None (skip this event)

---

## State Management

Single JSON file stored in a GitHub Gist, read/written via API each run.

```json
{
  "last_hot10":    { "date": "...", "cities": [...] },
  "streaks":       { "Miami": { "consecutive_days": 14, "last_seen": "..." } },
  "posted_events": [ "record_PHX_20260407", "firms_fire_12345", ... ],
  "daily_tweet_count": { "2026-04-08": 3 },
  "pending_confirmations": [ { "event_id": "...", "detected": "...", "city": "..." } ],
  "drafts":        [ { "id": "...", "text": "...", "type": "...", "status": "pending" } ],
  "errors":        [ { "source": "...", "ts": "...", "msg": "..." } ]
}
```

Caps: 500 event IDs, 200 drafts, 50 errors, 10 tweets/day.

---

## Dashboard

Next.js 15 app on Vercel free tier. Dark terminal aesthetic.

**Sections:**
- **Drafts to Review** — pending tweets with approve/edit/delete
- **Generate Drafts** — trigger alerts, leaderboard, or both
- **Compose Tweet** — manual composition with Gemini generation
- **Stats** — tweets today (of 10 cap), last Hot 10 date
- **Hot 10 Leaderboard** — last ranking with anomaly values
- **Streaks** — consecutive days in Hot 10
- **Recent Runs** — GitHub Actions history with status and log links
- **Recent Errors** — last 10 errors from state

---

## Test Coverage

165 tests across 18 files. Every data source module, the generator, safety pipeline, state management, and main orchestrator have unit tests. Mocks use `responses` for HTTP and `pytest-mock` for dependency injection.

CI runs `pytest` before the bot job — broken tests block deployment.

---

## Dependencies

```
tweepy>=4.14,<5       # X API
google-genai>=1.0     # Gemini 2.5 Flash
requests>=2.31        # HTTP
pytest>=8.0           # Tests
pytest-mock>=3.12     # Mocking
responses>=0.25       # HTTP response mocking
```

No heavyweight ML libraries. No databases. No servers.

---

## Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| TWITTER_API_KEY, TWITTER_API_SECRET | X API app credentials |
| TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET | X API user credentials |
| GEMINI_API_KEY | Google Gemini 2.5 Flash |
| GIST_ID | State storage (06c02c97ffc0d11458687f1ed998d9e5) |
| GITHUB_TOKEN | Gist read/write (currently broken — needs PAT with gist scope) |
| NASA_FIRMS_API_KEY | NASA fire detection |
| BLUESKY_HANDLE, BLUESKY_APP_PASSWORD | Bluesky cross-posting |

---

## Known Issues

1. **State write failing** — The default `GITHUB_TOKEN` in Actions has read-only permissions. Gist writes silently fail, losing all drafts. Fix: create a PAT with `gist` scope, store as a separate secret.

2. **Sequential API calls** — Ocean monitoring hits 16 endpoints one at a time (up to 160s). City temps fetch 257 cities sequentially. Total alert cycle takes ~13 minutes. Not a blocker (Actions has 6-hour limit) but slow.

3. **No images** — Text-only tweets. @extremetemps (100K followers) posts maps and visual cards. Image generation (Hot 10 card, record card) is the biggest growth lever not yet built.

4. **Vercel deployment behind** — Dashboard deployed from an older commit. Needs redeployment.

---

## Repo

**GitHub:** github.com/andrewzp/theheat
**Branch:** main (all code merged)
**Gist ID:** 06c02c97ffc0d11458687f1ed998d9e5
**Dashboard:** Vercel (theheat dashboard project)
