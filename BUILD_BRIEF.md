# @theheat — Build Brief

**Project:** Fully automatic climate awareness bot on Twitter/X
**Handle:** @theheat (owned)
**Goal:** Profitable. $0/month operating cost. Fully automatic after deploy.
**Audience:** Doomscrollers. The FlightRadar24 crowd. Weather nerds. Disaster watchers.
**Differentiator:** The voice. Dark humor, dry wit, cynical weatherman energy. Data is fuel, personality is why people follow.

---

## Architecture

```
GitHub Actions (single workflow, two cron schedules)
  |
  |-- Daily leaderboard job (12:00 UTC / ~8 AM ET)
  |     |-- Fetch current temps for 150 cities via Open-Meteo (free, no auth)
  |     |-- Compare against pre-computed normals (normals.csv in repo)
  |     |-- Rank top 10 by anomaly (current minus normal)
  |     |-- Generate Hot 10 tweet via Gemini Flash
  |     |-- Run through safety pipeline (regex gate → LLM check)
  |     |-- Post to X + Bluesky
  |
  |-- Alert polling job (every 4 hours, 6x/day)
  |     |-- Fetch Open-Meteo historical to detect likely broken records
  |     |-- Fetch NOAA ACIS for US record confirmations (24-72h lag)
  |     |-- Fetch NASA FIRMS active fires (confidence>=80%, FRP>=100MW)
  |     |-- Fetch Mauna Loa CO2 daily (post on new integer PPM milestone)
  |     |-- Deduplicate against state (GitHub Gist)
  |     |-- If new events: generate tweet → safety check → post
  |     |-- If API errors: log, skip source, retry next cycle
  |
  v
Gemini Flash API (free tier, 1,500 req/day)
  |-- Generate tweet with @theheat voice
  |-- Voice calibrated via VOICE.md + golden set examples
  |-- If Gemini fails: fall back to template-based tweet
  |
  v
Safety Pipeline (two layers)
  |-- Layer 1 (deterministic): Regex gate
  |     Reject if: emojis, hashtags, "BREAKING:", exclamation marks,
  |     >280 chars, climate policy opinions, banned phrases
  |-- Layer 2 (LLM): Gemini safety check
  |     "Does this tweet mock human suffering or cross from dark
  |      humor into cruelty? YES/NO"
  |-- If rejected: regenerate (up to 3x), then template fallback
  |
  v
Post to X API (free tier, 1,500 tweets/month)
  |-- Cross-post identical content to Bluesky via AT Protocol
  |
  v
Update state via GitHub Gist API (read/write JSON, same GitHub token)
```

## Tech Stack

| Component | Tool | Cost |
|-----------|------|------|
| Runtime | GitHub Actions (public repo) | $0 |
| Language | Python 3.12+ | $0 |
| AI | Google Gemini Flash API (free tier) | $0 |
| Posting (X) | tweepy library | $0 |
| Posting (Bluesky) | atproto library | $0 |
| State | GitHub Gist (JSON via API) | $0 |
| Landing page | GitHub Pages (static HTML) | $0 |
| Newsletter | Beehiiv (free tier, up to 2,500 subs) | $0 |
| Data | Open-Meteo, NOAA ACIS, NASA FIRMS, NOAA GML | $0 |

## Data Sources

| Source | What | Freshness | Auth | Used For |
|--------|------|-----------|------|----------|
| Open-Meteo Forecast API | Current day high temps, 150 cities | Real-time | None | Hot 10 leaderboard |
| Open-Meteo Historical API | Historical daily highs since 1940+ | On-demand | None | Record detection (global) |
| NOAA ACIS (RCC web services) | Pre-computed broken/tied records (US) | 24-72h lag | None | US record confirmation (delayed follow-up tweets) |
| NASA FIRMS | Active fire detections, global | ~3 hours | Free account | Wildfire alerts |
| NOAA GML (Mauna Loa) | Daily CO2 reading (ppm) | ~1 day | None (public CSV) | CO2 milestone posts |
| normals.csv (in repo) | 30-year climatological normals per city/month | Static, pre-computed once | N/A | Hot 10 anomaly calculation |
| cities.csv (in repo) | 150 cities: name, country, lat, lon | Static | N/A | City list for Hot 10 |

**Record detection pattern (two-part):**
1. Open-Meteo detects likely record in real-time → tweet: "Phoenix appears to have broken its April record."
2. NOAA ACIS confirms 24-72h later → tweet: "NOAA confirms: Phoenix officially broke the April record."

## State Management

State lives in a **GitHub Gist** (JSON file), not in the git repo. One API call to read, one to write. Same GITHUB_TOKEN. No branch pollution, no merge conflicts.

```json
{
  "last_hot10": {
    "date": "2026-04-07",
    "cities": ["Miami", "Baghdad", "Delhi", "Phoenix", "Lagos", ...]
  },
  "streaks": {
    "Miami": {"consecutive_days": 14, "last_seen": "2026-04-07"},
    "Phoenix": {"consecutive_days": 52, "last_seen": "2026-04-07"}
  },
  "posted_events": [
    "record_PHX_20260407",
    "firms_fire_12345",
    "co2_429ppm",
    "noaa_confirm_PHX_20260407"
  ],
  "daily_tweet_count": {"2026-04-07": 5},
  "pending_confirmations": [
    {"event_id": "record_PHX_20260407", "detected": "2026-04-07", "source": "open-meteo"}
  ]
}
```

**Daily tweet cap:** Max 10 tweets/day. Tracked in state. Prevents runaway posting on high-event days.

## File Structure

```
theheat/
  .github/
    workflows/
      bot.yml                    # Single workflow, two cron triggers
  src/
    data/
      open_meteo.py              # Current temps + historical records
      noaa_acis.py               # US record confirmations
      firms.py                   # NASA FIRMS fire alerts
      co2.py                     # Mauna Loa CO2 milestones
    voice/
      generator.py               # Gemini Flash tweet generation
      safety.py                  # Regex gate + LLM safety check
      templates.py               # Fallback templates (no AI)
    posting/
      twitter.py                 # X API via tweepy
      bluesky.py                 # Bluesky via atproto
    state.py                     # GitHub Gist read/write
    main.py                      # Entry point / orchestrator
  data/
    cities.csv                   # 150 cities (name, country, lat, lon)
    normals.csv                  # Pre-computed monthly normals
  VOICE.md                       # Voice specification
  requirements.txt               # Python dependencies
  tests/
    test_open_meteo.py           # Mocked API tests
    test_noaa_acis.py
    test_firms.py
    test_co2.py
    test_generator.py            # Voice eval tests
    test_safety.py               # Safety pipeline tests
    test_state.py                # State management tests
    test_posting.py              # Mocked posting tests
    test_main.py                 # Integration tests
    conftest.py                  # Shared fixtures
  README.md
```

## Voice Specification

**Character:** @theheat is a cynical weatherman who's seen too much. Dry, dark, occasionally funny. Never preachy. Never uses hashtags or emojis. Sounds exhausted by the data, not angry about politics.

**Tone:** 70% dry observation, 20% dark humor, 10% genuine awe at the data.

**Seed examples (illustrative, build a 30-tweet golden set before implementation):**
- "Phoenix. Again. 119F. New record. The old one was set... last year."
- "Day 47 above 110 in Phoenix. At this point the streak has its own personality."
- "Congratulations to Miami for making the Hot 10 for the first time. Nobody asked for this."
- "CO2 hit 428 ppm today. For context, it was 280 ppm for the entire history of human civilization. We're speed-running this."
- "New wildfire detected in Northern California. Satellite confidence: HIGH. 0% contained. It's April."
- "Miami just knocked Baghdad off the #1 spot on the Hot 10. This is not the competition anyone wanted."
- "NOAA confirms: Phoenix officially broke the April record. Congratulations to no one."

**Banned patterns (enforced by regex gate):**
- No emojis
- No hashtags
- No "BREAKING:" prefix
- No exclamation points
- No climate policy opinions ("we need to act", "governments must", etc.)
- No "we need to act now" messaging
- Let the data be the outrage

**Gemini prompt structure:**
```
You are @theheat, a climate data bot with the personality of a cynical
weatherman who's seen too much. You are dry, darkly funny, and exhausted
by the relentless data. You never preach. You never use hashtags or emojis.
You never take political positions. You just report the numbers with a
tone that makes people feel the weight of them.

Write a single tweet (under 280 characters) about this data:
{structured_data_here}

Rules:
- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- Sound tired, not angry. Dry, not dramatic.
- If this is a record, note when the old one was set.
- If this is a streak, note how long it's been going.

Here are examples of the voice (match this tone exactly):
{golden_set_examples}
```

## Content Types

### Hot 10 Daily Leaderboard (Phase 1B)
Cities ranked by anomaly (how much hotter than historical normal), not absolute temp.
- Post daily at ~8 AM ET
- Track position changes ("Miami UP 3 spots")
- Track streaks ("Day 14 in the Hot 10")
- Format as 1-2 tweet thread

### Heat Record Alerts (Phase 1A)
- Open-Meteo detects likely records in real-time
- NOAA ACIS confirms US records 24-72h later
- Two-part content: "appears to have broken" → "NOAA confirms"

### Wildfire Alerts (Phase 1A)
- NASA FIRMS fires filtered to confidence>=80%, FRP>=100MW
- Reverse-geocode fire lat/lon to nearest city name
- Skip small agricultural burns and low-confidence detections

### CO2 Milestones (Phase 1A)
- Post when daily Mauna Loa reading crosses new integer PPM (e.g., first reading at 429 ppm)
- Weekly comparison: this week's average vs same week last year

### Weekly Review (Phase 1A)
- Sunday thread summarizing the week
- Records broken, fires detected, CO2 trend, Hot 10 highlights
- Streak updates

## Build Order

### Phase 1A: Alerts + Voice Validation (ship in 3-4 days)
1. Set up repo, GitHub Actions workflow, requirements.txt
2. Build state.py (GitHub Gist read/write)
3. Build data fetchers: open_meteo.py (historical records), firms.py, co2.py
4. Build voice/generator.py + voice/safety.py + voice/templates.py
5. Build posting/twitter.py + posting/bluesky.py
6. Build main.py orchestrator (alerts only)
7. Write tests (mocked APIs, pure logic, voice eval)
8. Configure GitHub Secrets (X API keys, Gemini API key, Gist ID)
9. Deploy. Bot starts posting.

### Voice Validation (1 week)
- Run Phase 1A for a week
- Monitor tweet quality. Refine prompts.
- Tune the golden set examples
- Check engagement: are people following? Sharing?

### Phase 1B: Hot 10 Leaderboard (after voice is validated)
1. Pre-compute normals.csv (offline task, half a day)
2. Curate cities.csv (150 cities, global coverage)
3. Add open_meteo.py: current temp fetching (sequential, ~45 seconds for 150 cities)
4. Add anomaly calculation + ranking logic
5. Add streak tracking to state management
6. Add daily leaderboard cron trigger to workflow
7. Add leaderboard-specific voice templates and prompts
8. Tests for anomaly calc, streak tracking, ranking
9. Add normals sanity check: anomaly > 30C flags as likely data error, skip city

### Phase 1C: Monetization Infrastructure
1. Landing page (GitHub Pages, static HTML): today's Hot 10, newsletter signup
2. Beehiiv newsletter setup (free tier)
3. Weekly "Week in Review" email digest
4. X bio: link to landing page + newsletter

## Rate Limit Budget

| Resource | Limit | Daily (worst case) | Monthly |
|----------|-------|--------------------|---------|
| X API tweets | 1,500/month | 10 (capped) | 300 (20%) |
| Gemini Flash | 1,500/day | 20 (tweet gen + safety checks) | 600 (1.3%) |
| Open-Meteo | Generous (no hard limit) | ~151 requests | ~4,530 |
| NOAA ACIS | No published limit | ~6 requests | ~180 |
| GitHub Gist API | 5,000/hour | ~14 read/write pairs | ~420 |

## Secrets (GitHub Actions Secrets)

```
TWITTER_API_KEY          # X API consumer key
TWITTER_API_SECRET       # X API consumer secret
TWITTER_ACCESS_TOKEN     # X API access token
TWITTER_ACCESS_SECRET    # X API access token secret
GEMINI_API_KEY           # Google Gemini API key
GIST_ID                  # GitHub Gist ID for state storage
BLUESKY_HANDLE           # Bluesky handle (e.g., theheat.bsky.social)
BLUESKY_APP_PASSWORD     # Bluesky app password
NASA_FIRMS_API_KEY       # NASA FIRMS API key (free account)
```

GITHUB_TOKEN is provided automatically by GitHub Actions.

## Test Strategy

Framework: **pytest + pytest-mock + responses** (HTTP mocking)

38 codepaths identified across all modules. Full coverage.

Key test categories:
- **Mocked API tests:** Each data fetcher tested with mocked HTTP responses (happy path, partial failure, total failure, malformed response)
- **Pure logic tests:** Anomaly calculation, dedup, streak tracking, daily cap, state management (no mocks needed)
- **Voice eval tests:** Compare Gemini output against golden set for tone/style. Test safety pipeline (pass, fail, retry, fallback)
- **Integration tests:** End-to-end pipeline with all mocks: fetch → generate → safety → post → save state

## Open Questions (resolve before starting)

1. **Domain name:** Check availability for theheat.com / theheat.xyz / theheat.co
2. **X API access:** Apply for X developer account if not already done. Need to verify free tier posting access.
3. **Gemini API key:** Set up at https://makersuite.google.com/app/apikey (free, no credit card)
4. **Bluesky handle:** Register theheat.bsky.social before someone else does
5. **NASA FIRMS account:** Register at https://firms.modaps.eosdis.nasa.gov/ (free)
6. **NOAA ACIS:** No auth needed, but test the API endpoints manually first to confirm data format

## Revenue Path

| Source | Threshold | Timing |
|--------|-----------|--------|
| X Creator Revenue | 500 followers + 5M impressions / 3 months | Month 3-6+ |
| Beehiiv newsletter ads | Built-in at scale | When subscriber base grows |
| Green brand sponsorships | 10K+ followers | Month 6+ |
| "theheat" merch | Whenever brand is established | Phase 2+ |

## Key Decisions Log

All decisions from /office-hours + /plan-eng-review sessions on 2026-04-07:

1. Gemini Flash (free tier) for AI tweet generation, not templates
2. Open-Meteo as primary data source (real-time temps + historical records)
3. NOAA ACIS for US record confirmation only (delayed 24-72h, used for follow-up tweets)
4. NOAA CDO dropped entirely
5. GitHub Gist for state storage (not git commits)
6. Sequential HTTP requests, no async (cron job, nobody waiting)
7. Two-layer safety: deterministic regex first, LLM check second
8. Phase 1A (alerts) ships first, Phase 1B (leaderboard) after voice validation
9. Full pytest test suite from day one (38 codepaths)
10. Public GitHub repo (MIT license), GitHub Actions free tier
11. Normals CSV pre-computed offline, committed to repo as static file
12. Daily tweet cap of 10 enforced in state
13. Bot must identify as bot in X bio (X compliance requirement)
14. Cross-post identical content to Bluesky (same text, no adaptation needed)
