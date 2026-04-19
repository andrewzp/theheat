# @theheat Pipeline — From Raw Data to Published Tweet

A manufacturing-style flowchart showing how climate data becomes a tweet.

Each stage has a specific job; failure at any stage kills the draft rather than compromising quality. "Quality over volume" is enforced at multiple stages.

---

## The Flow

```mermaid
flowchart TD
    classDef source fill:#1a3a5c,stroke:#2f6aa8,color:#fff
    classDef gate fill:#5c3a1a,stroke:#a86a2f,color:#fff
    classDef gen fill:#3a5c1a,stroke:#6aa82f,color:#fff
    classDef kill fill:#5c1a1a,stroke:#a82f2f,color:#fff
    classDef out fill:#3a1a5c,stroke:#6a2fa8,color:#fff
    classDef state fill:#2a2a2a,stroke:#888,color:#fff

    subgraph RAW["RAW MATERIALS — 13 free public data sources"]
        direction TB
        OM["Open-Meteo<br/>temperature records<br/>257 cities"]:::source
        FIRMS["NASA FIRMS<br/>satellite wildfires"]:::source
        NOAACO2["NOAA GML<br/>Mauna Loa CO2"]:::source
        ACIS["NOAA ACIS<br/>US confirmations"]:::source
        NWS["NWS Alerts<br/>severe weather<br/>emergency-tier only"]:::source
        GDACS["GDACS<br/>Red-tier disasters"]:::source
        NSIDC["NSIDC<br/>sea ice<br/>Mondays"]:::source
        DROUGHT["US Drought Monitor<br/>Fridays"]:::source
        ENSO["NOAA CPC<br/>1st of month"]:::source
        MARINE["Open-Meteo Marine<br/>wave heights"]:::source
        COOPS["NOAA CO-OPS<br/>tide gauges"]:::source
        USGS["USGS Water<br/>river floods"]:::source
    end

    RAW --> EXTRACT["Extreme Signals Extraction<br/>(per-city unified bundle)<br/>• all-time records<br/>• monthly records<br/>• anomaly (15°C+ above/below mean)<br/>• calendar-date records<br/>• record streaks (3+ consecutive days)<br/>• simultaneous events (5+ cities/day)<br/>Picks strongest signal per city"]:::gen

    EXTRACT --> DEDUP{"Deduplicate<br/>against last 500 events"}:::gate

    DEDUP -->|new event| SCORE["Editorial Signal Scoring<br/>severity × 0.28<br/>novelty × 0.24<br/>timeliness × 0.16<br/>confidence × 0.16<br/>shareability × 0.16<br/>minus sensitivity × 0.20"]:::gen

    DEDUP -.->|seen| SKIP1[/"Skip — already drafted"/]:::kill

    SCORE --> GATE1{"Signal score<br/>passes threshold?<br/>all-time: 80<br/>monthly: 76<br/>anomaly: 76<br/>streak: 74<br/>simultaneous: 78<br/>calendar-date: 72<br/>fires: 64<br/>disasters: 62"}:::gate

    GATE1 -.->|no| SKIP2[/"Suppress —<br/>not extraordinary enough"/]:::kill

    GATE1 -->|yes| CTX["Build data description<br/>+ pull previous drafts<br/>about this event<br/>(prevents repeated comparisons)"]:::gen

    CTX --> FLASH["Gemini 2.5 Flash<br/>Generate 4 candidates"]:::gen

    FLASH --> SAFETY1{"Safety Pipeline<br/>40+ regex patterns<br/>+ LLM harm check"}:::gate

    SAFETY1 -.->|fails 3×| FBACK["Template fallback<br/>hand-written per type"]:::gen

    SAFETY1 -->|passes| RANK["Heuristic Ranking<br/>clarity × 0.30<br/>context × 0.28<br/>voice × 0.22<br/>punch × 0.20"]:::gen

    FBACK --> RANK

    RANK --> SONNET["Claude Sonnet 4.6<br/>Virality Evaluator<br/>scores 0-10 on:<br/>• awe<br/>• comparison<br/>• social currency<br/>• opener<br/>• show-not-tell"]:::gen

    SONNET -->|PASS<br/>7+ on 4 of 5| CAP
    SONNET -->|FAIL<br/>no rewrite| KILL1[/"Kill draft<br/>not worth tweeting"/]:::kill
    SONNET -->|FAIL<br/>with rewrite| SAFETY2{"Rewrite passes<br/>safety pipeline?"}:::gate

    SAFETY2 -.->|no| KILL2[/"Kill draft<br/>rewrite unsafe"/]:::kill
    SAFETY2 -->|yes| REGRESS{"Rewrite scores<br/>higher than original?"}:::gate

    REGRESS -.->|no| KILL3[/"Kill draft<br/>rewrite is worse"/]:::kill
    REGRESS -->|yes| CAP

    CAP["Per-cycle cap<br/>max 3 drafts<br/>keep top by signal score"]:::gate

    CAP --> POLICY["Assign Approval Policy<br/>based on category + score"]:::gen

    POLICY --> STATE[("GitHub Gist<br/>state.json<br/>• drafts<br/>• posted_events<br/>• run_history")]:::state

    STATE --> BRANCH{"Approval mode"}:::gate

    BRANCH -->|armed_auto<br/>Hot 10, CO2, NOAA| QUEUE["Auto-Approval Queue<br/>hourly cron<br/>timed delay 20-90 min"]:::gen

    BRANCH -->|suggested_auto<br/>records, ice, ENSO| DASH["Dashboard Review<br/>Next.js on Vercel<br/>human approves"]:::out

    BRANCH -->|manual_only<br/>fires, disasters, floods| DASH

    QUEUE --> SAFETY3{"Safety Pipeline<br/>re-runs before post"}:::gate

    SAFETY3 -.->|fails| PENDING[/"Stay pending<br/>for manual review"/]:::kill
    SAFETY3 -->|passes| POST["Tweepy post to X<br/>+ cross-post to Bluesky"]:::out
    DASH -->|approve| POST

    POST --> X[("X / Twitter<br/>@theheat")]:::out
    POST --> BSKY[("Bluesky<br/>cross-post")]:::out
    POST --> DONE["Mark posted<br/>+ record event ID"]:::state
```

---

## Stage Glossary

### Raw Materials (13 Sources)
Each source is fetched on a schedule (alerts every 4 hours, Hot 10 daily at 12:00 UTC). Each is wrapped in try/catch so one failure doesn't block the others.

### Deduplicate
Checks the event ID against the last 500 we've seen. Prevents drafting the same record twice. For evolving events like cyclones, the ID includes intensity tier so a Cat 3→Cat 4 strengthening produces a new event.

### Editorial Signal Scoring
Six weighted factors produce a 0–100 score. Each event type has a threshold (records: 72, fires: 64, disasters: 62, etc). Below threshold = suppressed before generation. This is the first quality gate.

### Build Data Description + Previous Drafts
Constructs the structured text the generator sees. For evolving events (cyclones, hurricanes), previous draft texts are included with explicit instructions NOT to repeat the same framing — prevents "Category 5 starts at 157" × 5 drafts.

### Gemini 2.5 Flash (Generator)
Fast, cheap, free tier. Produces 4 distinct tweet candidates from the data description. System prompt enforces voice rules, press-release bans, and the virality principles.

### Safety Pipeline
Two layers:
- **Regex:** 48+ banned patterns (emojis, hashtags, press-release openers, weather-service boilerplate, tell-don't-show meta-commentary, truncated temperatures, date repetition).
- **LLM:** Gemini Flash checks for mocking human suffering / crossing from dark humor into cruelty.

### Heuristic Ranking
Scores each surviving candidate on clarity/context/voice/punch. Orders them best-first.

### Claude Sonnet 4.6 (Virality Evaluator)
Second inference pass. Scores the top candidate 0–10 on five virality dimensions from the research:
- **Awe** — physical activation
- **Comparison** — concrete anchoring
- **Social currency** — makes the sharer look smart
- **Opener** — scroll-stopping first line
- **Show-not-tell** — no meta-commentary

Passes if 7+ on 4 of 5 dimensions. Fails otherwise. When failing, provides a rewrite.

### Rewrite Validation (3 gates)
The evaluator's rewrite must survive three checks to be accepted:
1. Pass the safety pipeline
2. Score higher than the original on the heuristic
3. No rewrite? Draft dies entirely.

**An evaluator FAIL with no usable rewrite kills the draft.** No more "evaluator said this isn't viral but we'll draft it anyway."

### Per-Cycle Cap
Max 3 drafts per alert cycle, ranked by signal score. Even on a hot day, only the top 3 survive. Forces quality over volume.

### State Write
All state lives in a single JSON file in a GitHub Gist. Read/written each run via GitHub API. Caps: 500 event IDs, 200 drafts, 50 errors, 10 tweets/day.

### Approval Policy
Three tiers determine what happens next:
- **armed_auto** — will auto-post after timed delay (Hot 10, CO2 milestones, NOAA confirmations with strong scores)
- **suggested_auto** — dashboard suggests auto, but requires human (records, ice, ENSO)
- **manual_only** — human approval required (fires, severe weather, disasters, storm surge, river floods, drought)

### Dashboard
Next.js 15 + React 19 on Vercel free tier. Dark terminal aesthetic. Shows pending drafts sorted by signal + candidate score. Human approves, edits, or rejects.

### Post
Tweepy posts to X. If successful, cross-posts to Bluesky via AT Protocol. On rate-limit (429), stays pending for retry next hour.

### Double-Gate on Auto-Publish
Safety pipeline runs at generation time **AND** again right before every auto-post. Catches anything that slipped through initially.

---

## What Gets Killed vs What Gets Shipped

A tweet can die at any of these stages:

| Stage | Kill reason |
|---|---|
| Deduplicate | Already drafted this event |
| Signal scoring | Below threshold — not extraordinary enough |
| Safety (regex) | Banned pattern (press-release opener, weather-service boilerplate, truncated temp, etc) |
| Safety (LLM) | Mocks suffering, crosses into cruelty |
| Evaluator | Not viral enough, no usable rewrite |
| Rewrite safety | Evaluator's rewrite has a banned pattern |
| Rewrite regression | Rewrite scores worse than original on heuristic |
| Per-cycle cap | Not in top 3 for this run |
| Double-gate | Failed safety again right before auto-post |

Only drafts that survive every stage become tweets. On a typical alert cycle, hundreds of events get observed, dozens get scored, a handful make it to the generator, and 3 or fewer become drafts.

*A great tweet plus strong distribution beats a great tweet alone. A mediocre tweet plus amplification is just amplified mediocrity.*
