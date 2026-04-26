# @theheat — Project Briefing

**Last updated:** April 22, 2026
**Status:** Live on GitHub Actions. Four detection lanes merged (Ocean SST, GRACE ice mass, Fire Footprint/NIFC, Cross-Source Synthesis). Post-Codex-review bugs fixed. Feed now includes marine heatwave streaks, monthly ice-mass records, named US fire complexes crossing acreage tiers, and compound Fire×Drought×Heat synthesis signals.
**Latest commit:** `0be88fc` on `main`
**Tests:** 501 passing
**Cost:** ~$25–45/month for Anthropic API (Sonnet evaluator). Verified against console.anthropic.com 2026-04-24 — earlier "$60-90" estimate in this doc was inherited and never recalibrated against real usage. Everything else free tier (Gemini Flash, all data sources).

---

## What is this?

@theheat is an automated climate data bot for X (Twitter). It monitors free public data sources for extreme climate signals — all-time heat records, monthly records, temperature anomalies, record-breaking streaks, simultaneous events across cities, wildfires, floods, storm surge, CO2 milestones, sea ice loss, drought, ocean waves, ENSO shifts, severe weather — then generates tweets and queues them for review.

**Core principle (session-hardened):** It's a utility that surfaces astounding climate facts. Not a growth startup. Astounding data → clean presentation. The DATA is the product. If the facts are lame, no voice trick, visual, or meme template saves it.

**What the account is NOT:**
- Not a "cynical weatherman" voice account (this framing was killed in April 2026 — it was too mannered)
- Not a breakout-viral content machine (research confirms breakout climate viral requires human timing/register-break)
- Not a competitor to @extremetemps (it's a utility, not a business)

**Target audience:** Data people. Weather nerds. Climate-aware people who want the signal without the preaching.

---

## Architecture

```
CRON (GitHub Actions free tier, 6x/day alerts + hourly auto-approval)
│
├── Fetch from data sources (14 sources — 9 always-on, 5 day-gated)
│   ├── Open-Meteo ──────── city temps + archive (613 cities, 179 countries, all records)
│   ├── NASA FIRMS ────────── satellite wildfire detections (VIIRS_SNPP_NRT)
│   ├── NIFC WFIGS ────────── US fire-complex cumulative burn area (daily, tier-crossing only)
│   ├── NOAA GML ──────────── Mauna Loa CO2 (daily PPM, capped at 12 tweets/year)
│   ├── NWS Alerts ────────── US severe weather — Tornado Emergency, Flash Flood
│   │                          Emergency, Hurricane, Storm Surge, Extreme Wind,
│   │                          Blizzard, Ice Storm, Extreme Cold, Extreme Heat.
│   ├── GDACS ──────────────── Red-tier global disasters only
│   ├── NSIDC ──────────────── Arctic/Antarctic sea ice (Mondays only)
│   ├── GRACE-FO (PODAAC) ─── Greenland + Antarctica monthly ice mass (Mondays only,
│   │                          Earthdata Login required, capped at 8 tweets/year)
│   ├── US Drought Monitor ── state drought intensity (Fridays only)
│   ├── NOAA CPC ──────────── ENSO transitions (1st of month)
│   ├── Open-Meteo Marine ── ocean wave heights (16 points, location-aware thresholds)
│   ├── NOAA CO-OPS ────────── coastal tide gauge storm surge (12 stations)
│   ├── USGS Water ────────── river flood stages (12 gauges)
│   └── NOAA OISST v2.1 ──── global-mean sea surface temperature via ClimateReanalyzer.
│                              Fires on archive-record streaks of 5+ days (day-5 first-fire,
│                              then milestones at 10, 25, 50, 100, 150, 200, 250, 300, 365,
│                              400, +50 thereafter). Threshold: 78. Approval: suggested_auto,
│                              90-min delay.
│
├── Detect extreme signals per city (unified bundle)
│   ├── All-time records (hottest/coldest in ~30yr archive) — elite
│   ├── Country records (country-wide archive peak across all sampled
│   │   cities in that country — the biggest single story)
│   ├── Monthly records (hottest April ever, etc.) — strong
│   ├── Anomaly records (15°C+ above/below monthly mean) — strong
│   ├── Calendar-date records (legacy) — strong if big margin/old record
│   ├── Record streaks (3+ consecutive daily records per city)
│   └── Simultaneous events (5+ cities same day → one summary signal)
│   Picks strongest signal per city; one tweet per bundle max.
│
├── Cross-source synthesis (meta-layer, fires after per-source sections)
│   └── Fire × Drought × Heat (US state, 14-day window, per-state cooldown)
│
├── Score events (editorial scoring — 22+ scoring functions, thresholds 56-82)
│
├── Deduplicate against state (last 500 event IDs)
│
├── Generate tweet candidates (Gemini 2.5 Flash, 4 per event)
│
├── Safety pipeline (40+ regex + LLM check)
│   ├── Press-release opener ban (NWS/NOAA/GDACS...)
│   ├── Weather-service boilerplate ban (HURRICANE-FORCE, catastrophic,
│   │   life-threatening, EXTREME force, dangerous conditions)
│   ├── Tell-don't-show ban (THIS IS SERIOUS, pay attention, you should
│   │   be worried, this is rare)
│   ├── Label:value ban (Severity: Severe, Alert level: Red)
│   ├── Explainer ban (highest severity level GDACS issues)
│   ├── Tier explainer ban (the highest alert tier)
│   ├── Month-repetition check (catches "April 10. It's April.")
│   ├── Truncated temp check (rejects "1F forecast" bugs)
│   ├── Bureaucratic suffix ban (-26, -2026)
│   └── LLM harm check (Gemini)
│
├── Heuristic ranking (clarity/context/voice/punch)
│
├── Virality evaluator — Claude Sonnet 4.6
│   ├── Scores 5 dimensions: awe, comparison, social currency, opener, show-not-tell
│   ├── Passes if 7+ on 4 of 5
│   ├── Fails → provides rewrite
│   ├── Rewrite runs through safety + score-regression check
│   └── Evaluator FAIL with no usable rewrite = kills the draft entirely
│
├── Per-cycle cap (max 3 drafts, top by signal score)
│
├── Save drafts to GitHub Gist (state.json)
│
├── AUTO-APPROVAL QUEUE (hourly cron)
│   ├── Low-sensitivity + high-scoring drafts auto-post after timed delay
│   └── Safety pipeline re-runs before every auto-post (double-gate)
│
└── DASHBOARD (Next.js 15 on Vercel, auth-protected)
    ├── Human reviews pending drafts
    ├── Posts to X via Tweepy + cross-posts to Bluesky
    └── Bulk-reject below threshold API (for cleaning backlogs)
```

---

## Codebase

```
theheat/
├── src/                              ~7,179 lines Python
│   ├── main.py                       Orchestrator (1,610 lines)
│   ├── state.py                      GitHub Gist state + record-streak helpers (540 lines)
│   ├── data/                         Data source modules
│   │   ├── open_meteo.py             Unified extreme signal detection + country aggregation
│   │   ├── firms.py                  NASA FIRMS wildfires (VIIRS letter-confidence aware)
│   │   ├── fire_footprint.py         NIFC WFIGS named fire complexes, acreage tier dedup
│   │   ├── co2.py                    Mauna Loa CO2 milestones (12/yr cap)
│   │   ├── nws_alerts.py             NWS — 9 extreme-tier event types
│   │   ├── gdacs.py                  GDACS — Red-tier only, intensity-tier dedup
│   │   ├── sea_ice.py                Arctic/Antarctic sea ice
│   │   ├── ice_mass.py               GRACE-FO Greenland + Antarctica (Mondays, Earthdata)
│   │   ├── ocean_sst.py              NOAA OISST v2.1 global-mean streaks
│   │   ├── drought.py                US Drought Monitor
│   │   ├── enso.py                   ENSO transitions
│   │   ├── ocean.py                  Extreme waves (location-aware thresholds)
│   │   ├── water_levels.py           NOAA CO-OPS storm surge
│   │   └── river_gauges.py           USGS river flood stages
│   ├── editorial/
│   │   ├── scoring.py                22+ signal-scoring functions
│   │   ├── candidates.py             Heuristic ranking (clarity/context/voice/punch)
│   │   ├── approval.py               3-tier approval policy
│   │   ├── evaluator.py              Claude Sonnet 4.6 virality evaluator
│   │   ├── synthesis.py              Cross-source synthesis rules (fire×drought×heat)
│   │   ├── regions.py                Lat/lon → US state + city → state helpers
│   │   └── _util.py                  Shared clamp utility
│   ├── voice/
│   │   ├── generator.py              Gemini Flash generation + 19 generator fns (880 lines)
│   │   ├── templates.py              Fallback templates (no AI needed)
│   │   └── safety.py                 Two-layer safety pipeline (179 lines)
│   ├── posting/
│   │   ├── twitter.py                Tweepy (rate-limit aware)
│   │   └── bluesky.py                AT Protocol cross-posting
│   └── storage/
│       └── sqlite_store.py           SQLite backend (exists but unused in prod)
│
├── tests/                            500+ tests across signal, scoring,
│                                     generator, safety, state, synthesis,
│                                     and integration suites
│
├── dashboard/                        Next.js 15 + React 19 on Vercel
│   └── app/
│       ├── page.js                   Control panel UI (dark terminal theme)
│       ├── layout.js                 
│       └── api/
│           ├── state/route.js        Read Gist state
│           ├── drafts/route.js       Draft management + bulk-reject-below
│           ├── generate/route.js     Trigger GitHub Actions
│           ├── post/route.js         Post approved tweet
│           └── trigger/route.js      Trigger specific run modes
│
├── brand/
│   ├── VOICE.md                      Voice spec (moved from root in April 2026)
│   ├── MESSAGING_ARCHITECTURE.md     Positioning
│   ├── VIRALITY_RESEARCH.md          Research reference (Part 1 content-first, Part 2 platform mechanics)
│   ├── EXEMPLARS.md                  Verified viral climate tweets with real engagement data
│   └── VOICE_PATTERNS.md             Voice pattern reference (labeled honestly: not proven-viral)
│
├── data/
│   ├── cities.csv                    613 cities across 179 countries
│   └── normals.csv                   Climatological normals
│
├── BRIEFING.md                       This file — session entry point
├── PIPELINE.md                       Manufacturing-style flow diagram
├── docs/
│   ├── DESIGN.md                     Architecture decisions
│   ├── BUILD_BRIEF.md                Product scope
│   ├── FUTURE_STATE.md               Aspirational future
│   ├── SESSION_BRIEF.md              Latest session context (see for current thinking)
│   └── mockups/                      Dashboard mockups (HTML)
└── requirements.txt                  tweepy, atproto, google-genai, anthropic, requests, pytest, pytest-mock, responses
```

---

## Data Flow: Alert Cycle (updated)

Every 4 hours, GitHub Actions runs `python -m src.main alerts`:

1. **Read state** from GitHub Gist
2. **Fetch data** from all sources (each wrapped in try/catch)
3. **Detect extreme signals per city** (NEW unified handler):
   - One archive fetch per city (257 priority-ordered) yields ALL signal types
   - Bundle includes: all_time_high/low, monthly_high/low, anomaly_hot/cold, calendar_date_high/low
   - Handler picks strongest signal per city (all-time > monthly > anomaly > calendar-date)
   - Monthly records whose prior record was set in the current calendar year are suppressed (confusing framing — "hottest April, old record set in 2026" reads as nonsense)
   - Country-level aggregation runs after the per-city loop: for each country with ≥2 sampled cities, compare today's peak vs the archive-wide peak across the same cities. Emits a `country_high` / `country_low` signal when today exceeds the archive. Threshold 82, elite by default.
4. **Score events** — editorial scoring with per-category thresholds (62-80). Elite events pass.
5. **Deduplicate** against posted_events (last 500)
6. **Generate 4 candidates** via Gemini 2.5 Flash, ranked by copy score
7. **Safety check** — regex gate (40+ patterns), then LLM ("mocks suffering?")
8. **Virality evaluator** — Sonnet scores 5 dimensions, rewrites on fail. Rewrite must pass safety AND score higher than original on heuristic. Otherwise draft dies.
9. **Streak tracking** — if a city broke a daily record, update `record_streaks`. If 3+ consecutive days, emit a streak signal as a bonus draft.
10. **Simultaneous detection** — if 5+ cities broke records today, emit ONE summary signal
11. **Per-cycle cap** — max 3 drafts, keep top by signal score, reject the rest
12. **Same-city-same-day dedup** — highest signal score wins per `(city, YYYY-MM-DD)`. A stronger signal that arrives later supersedes a still-pending weaker draft; a weaker one is dropped. If a tweet for that `(city, date)` is already posted, the new one is skipped.
13. **City cooldown (3 days)** — after we post about a city, drafts for that city are skipped for 3 days unless the signal is *elite* (all-time record, anomaly ≥18°C, record streak) OR the copy itself is exceptional (`candidate_score.total ≥ 95`). Scoped to Open-Meteo extreme-temperature signals; fires/disasters/CO2/etc. bypass.
14. **Assign approval policy** (armed_auto / suggested_auto / manual_only)
15. **Save drafts** to Gist with full metadata

## Data Flow: Auto-Approval (hourly)

Every hour, `python -m src.main auto_publish_due`:
1. Scan for drafts with elapsed `auto_approve_at`
2. Verify `armed_auto` mode — block if policy not armed
3. **Re-run safety pipeline** (double-gate)
4. Post to X (Tweepy) + cross-post to Bluesky
5. On rate-limit (429): keep draft pending for retry

## Data Flow: Manual Posting
Dashboard → approve → workflow_dispatch with DRAFT_ID → Actions posts via Tweepy → marked "posted" → Bluesky cross-post.

## Data Flow: Leaderboard
Daily at 12:00 UTC, `python -m src.main both`:
1. Fetch temps for 257 cities
2. Compute anomalies vs climatological normals
3. Rank top 10 by anomaly
4. Generate Hot 10 tweet

---

## Schedule

| UTC   | Cron             | Mode              | What runs                                  |
|-------|------------------|-------------------|--------------------------------------------|
| :30   | `30 * * * *`     | auto_publish_due  | Hourly auto-approval queue                 |
| 00:00 | `0 0 * * *`      | alerts            | All sources                                |
| 04:00 | `0 4 * * *`      | alerts            | All sources                                |
| 08:00 | `0 8 * * *`      | alerts            | All sources                                |
| 12:00 | `0 12 * * *`     | both              | Leaderboard + all sources                  |
| 16:00 | `0 16 * * *`     | alerts            | All sources                                |
| 20:00 | `0 20 * * *`     | alerts            | All sources                                |

Source-specific gates: sea ice (Mondays), drought (Fridays), ENSO (1st of month), CO2 milestones (max 1/day), CO2 weekly (Sundays).

---

## Editorial System

### Signal Scoring (`src/editorial/scoring.py`)

Signal types and thresholds:
- **synthesis_fire_drought_heat** — threshold 82 (compound story, elite by design)
- **country_record** (archive peak across all sampled cities in a country) — 82 (elite)
- **all_time_record** — 80 (elite by default)
- **simultaneous_records** — 78
- **marine_heatwave** (global-mean SST streak ≥5 days above archive) — 78
- **monthly_record** — 76
- **anomaly** — 76
- **record_streak** — 74 (fires at 3+ days)
- **fire_footprint** — 72 (named US fire complex crossing acreage tier; manual_only)
- **ice_mass_record** (GRACE-FO monthly loss record / cumulative milestone) — varies, elite-tier
- **record** (calendar-date) — 72
- **record_low** — 72
- **fire** — 64 (NASA FIRMS point detections)
- **co2_milestone** — 58 (capped at 12 tweets/year via `co2_annual_count`)
- **severe_weather** — 58
- **global_disaster** — 62
- **sea_ice_record** — 60
- **drought** — 62
- **enso** — 56
- **extreme_wave** — 62
- **storm_surge** — 60
- **river_flood** — 62
- **hot10** — 56

### Copy Ranking (`candidates.py`)
Gemini produces 4 candidates. Each scored on clarity/context/voice/punch. Best selected.

### Virality Evaluator (`evaluator.py`) — Claude Sonnet 4.6
5 dimensions: awe, concrete comparison, social currency, scroll-stopping opener, show-not-tell.
Passes if 7+ on 4 of 5. Fails → rewrite provided. Rewrite must pass safety AND beat original heuristic score. If no viable rewrite → draft dies.

### Approval Policies (`approval.py`)
- **armed_auto** — Auto-posts after timed delay (Hot 10, CO2 milestones)
- **suggested_auto** — Dashboard suggests auto, requires human (records, ice, ENSO)
- **manual_only** — Human required (fires, fire footprints, severe weather, disasters, storm surge, floods, drought)

### Cross-source synthesis

A meta-detection layer fires a single high-confidence tweet when three
independent signals converge on the same US state within 14 days:
exceptional (D4) drought from USDM, a qualifying wildfire from NASA
FIRMS, and a qualifying heat record from Open-Meteo. The first rule is
`fire_drought_heat`; additional rules (marine heatwave × coastal heat
dome; hurricane × storm surge × river flood) plug into the same
scaffolding.

Synthesis tweets use `suggested_auto` approval with a 120-minute review
window because compound claims are factually more brittle. The
synthesis layer never replaces the per-source tweets — it adds a
compound story on top.

---

## Voice Rules (current)

**Prompt orientation:** astounding data + clean presentation. NOT "cynical weatherman" (killed in session). NOT "personified heat character" (rejected after Karl the Fog research). The bot reports, doesn't narrate.

**Hard bans (safety pipeline):**
- Emojis, hashtags, exclamation marks
- Press-release openers (NWS, NOAA, GDACS, etc. at start of tweet)
- Weather-service boilerplate (HURRICANE-FORCE, catastrophic, life-threatening, EXTREME force, dangerous conditions)
- Tell-don't-show meta-commentary (THIS IS SERIOUS, this is rare, pay attention, you should be worried)
- Label:value format (Severity: Severe, Alert level: Red)
- Tier explainers (the highest alert tier)
- Month repetition (same month twice in adjacent sentences)
- Truncated temperatures (bugs like "1F forecast")
- Bureaucratic suffixes (-26, -2026 in storm names)

**Positive principles (from evaluator + virality research):**
- First 5-7 words must surprise or pattern-break
- Historical-human anchors beat physical metaphors ("last time Buenos Aires was this hot, the Great Depression hadn't started")
- Leave gaps for the reader to complete
- Specific numbers beat round numbers
- One idea per tweet

**Framing honesty (key rule from session):**
- Archive goes back ~30 years, not "all time"
- All-time record tweets must say "hottest in 30 years of archive data" or "hottest since 1995" — NEVER "hottest ever"

---

## Safety Pipeline (40+ regex + LLM)

**Layer 1 — Regex (deterministic):** 40+ patterns covering all the bans above, plus length check (280 chars), month-repetition structural check, and truncated-temperature check.

**Layer 2 — LLM (Gemini Flash):**
Asks: "Does this tweet mock human suffering, trivialize death, or cross from dark humor into cruelty?" Fails logged; tweet passes on LLM unavailability (regex already caught the mechanical stuff).

**Fallback chain:** Gemini generation (4 candidates) → 3 retries on safety rejection → template-based fallback → None (skip event).

**Double-gate on auto-publish:** Safety pipeline runs at generation time AND again before every auto-post.

---

## State Management

Single JSON file in GitHub Gist, read/written via GitHub API each run.

```json
{
  "last_hot10":    { "date": "...", "cities": [...] },
  "streaks":       { "Miami": { "consecutive_days": 14, "last_seen": "..." } },
  "posted_events": [ "record_PHX_20260407", ... ],
  "daily_tweet_count": { "2026-04-18": 3 },
  "co2_annual_count": { "2026": 2 },
  "drafts": [ ... full draft records with score, candidates, approval_policy, review_context, evaluator_pass ... ],
  "run_history": [ { "id": "...", "mode": "alerts", "sources": [...] } ],
  "errors": [ ... ],
  "city_all_time_max": { "Phoenix": {"temp_c": 48.2, "year": 2018} },
  "city_all_time_min": { ... },
  "city_monthly_max": { "Phoenix": { "4": {"temp_c": 44.0, "year": 2024} } },
  "city_monthly_min": { ... },
  "record_streaks":   { "Phoenix": { "days": 11, "start_date": "...", "last_date": "...", "peak_temp_c": 45.0 } }
}
```

**Caps:** 500 event IDs, 200 drafts (pruned oldest non-pending), 50 errors, 10 tweets/day, 3 drafts/cycle.

---

## Dashboard

Next.js 15 + React 19 on Vercel. Auth-protected. Dark terminal aesthetic.

Sections:
- **Drafts to Review** — pending tweets with approve/edit/delete, editorial scores, approval policy, review context
- **Generate Drafts** — trigger alerts, leaderboard, or both via workflow_dispatch
- **Compose Tweet** — manual composition with Gemini generation
- **Stats, Hot 10, Streaks, Recent Runs, Recent Errors**

API routes: bulk_reject_below (for threshold cleanups), approve, reject, edit, auto_approve, select_candidate.

**URL:** https://dashboard-phi-beryl-65.vercel.app

---

## Dependencies

```
tweepy>=4.14,<5       # X API posting
atproto>=0.0.61       # Bluesky cross-posting
google-genai>=1.0     # Gemini 2.5 Flash (generation + safety LLM)
anthropic>=0.42       # Claude Sonnet 4.6 (virality evaluator)
requests>=2.31        # HTTP for data sources
pytest>=8.0
pytest-mock>=3.12
responses>=0.25
```

---

## Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET` | X API |
| `GEMINI_API_KEY` | Google AI Studio API key for Gemini |
| `GEMINI_MODEL` | (Optional) Model ID for the candidate generator. Default `gemini-flash-latest` — the alias Google rolls to whatever the current best Flash is (currently `gemini-3-flash-preview`, $0.30/$2.50 per MTok). Override with `gemini-3-pro-preview`, a pinned snapshot like `gemini-3-flash-preview`, or fallback `gemini-2.5-flash` without redeploying. |
| `GEMINI_SAFETY_MODEL` | (Optional) Separate model ID for the LLM safety layer. Defaults to whatever `GEMINI_MODEL` is. |
| `EVALUATOR_ENABLED` | (Optional) Set to `false` to skip the Sonnet 4.6 virality-evaluator pass and save ~$25-45/mo. Defaults to `true`. Drafts then flow Gemini → safety → ranking → dashboard with no second-pass rewrites or kills. |
| `ANTHROPIC_API_KEY` | Claude Sonnet 4.6 evaluator |
| `GIST_ID` | State storage (`06c02c97ffc0d11458687f1ed998d9e5`) |
| `GH_GIST_TOKEN` | PAT with `gist` scope for state writes |
| `NASA_FIRMS_API_KEY` | NASA fire satellite detection |
| `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | Bluesky cross-post |
| `EARTHDATA_TOKEN` | NASA Earthdata Login bearer token, used by the GRACE-FO ice-mass lane. Generate at https://urs.earthdata.nasa.gov/ (profile → "Generate Token"). Optional: if unset the ice_mass lane short-circuits to skipped and the rest of the pipeline runs normally. |

### Fire footprint source (no secret required)

- **Source:** NIFC WFIGS (Wildland Fire Interagency Geospatial Services) — `services3.arcgis.com/T4QMspbfLg3qTGWY/.../WFIGS_Incident_Locations_Current`
- **Auth:** None (public ArcGIS FeatureServer).
- **Coverage:** US only.
- **Rationale for NIFC over GWIS:** GWIS (EU Joint Research Centre) was the original target — it provides global coverage — but as of 2026-04-20 GWIS publishes only WMS map layers, no JSON/GeoJSON API. Pivoted to NIFC per the plan's explicit fallback. Revisit GWIS if they publish a JSON endpoint.
- **Fallback if NIFC degrades:** no secondary source implemented; the orchestrator catches fetch failures and logs them without blocking other sources.

---

## Known Issues & Growth Levers

### Issues
1. **Sequential API calls** — 613 cities checked sequentially. Alert cycle ~30 min.
2. **Dashboard deployment** — may be behind latest main.
3. **Archive span** — Open-Meteo only goes back ~30 years reliably. "All-time" framing must say "in 30 years of records." Enforced in the generator system prompt.
4. **SQLite store** — lane-added keys now round-trip correctly via the metadata table (fixed 2026-04-22). Still not the default prod backend (Gist is), but no longer silently lossy if enabled.
5. **Fire reverse-geocoder is continent-only** — `firms.py::reverse_geocode_simple` produces "somewhere in Asia" / "somewhere in Australia" labels, which generates weak fire drafts. First-class fix noted in Growth Levers.
6. **Stray worktree artifact** — `theheat/theheat/` duplicate subdir from a Conductor worktree; untracked, safe to `rm -rf` when convenient. Causes `ImportPathMismatchError` on repo-root pytest.

### Growth levers (deferred by session owner)
1. **Visual cards** — research says images 28× engagement. User rejected: "not if the facts are lame." Revisit once fact quality is proven.
2. **Voice engine upgrade** — see `docs/IDEAS.md`. Data-ticker tweets are "ok, not breakout-viral." Generator prompt, evaluator calibration, or a dedicated lead-with-the-stake rewrite pass are the three candidate interventions.
3. **Fire geocoder regional precision** — `firms.py::reverse_geocode_simple` returns continent-only labels ("somewhere in Asia"), which produces weak fire drafts. Candidates: bounding boxes per country/region, or a bundled country polygon dataset.
4. **RSS enrichment** — Carbon Brief, Climate Central feeds.
5. **GWIS global fire footprint** — currently NIFC (US only). Revisit GWIS if they publish a JSON/GeoJSON API.
6. **Additional synthesis rules** — marine heatwave × coastal heat dome (blocked until OISST has fired enough); hurricane × surge × flood (waits for hurricane season so the rule can be observed firing before we trust it).

---

## Repo

- **GitHub:** `github.com/andrewzp/theheat`
- **Branch:** `main` (latest: `0be88fc`)
- **Gist ID:** `06c02c97ffc0d11458687f1ed998d9e5`
- **Dashboard:** https://dashboard-phi-beryl-65.vercel.app
- **X:** @theheat (Premium tier — 4x/2x algo boost already active)
