# Session Brief — April 18-19, 2026

Handoff doc for picking up @theheat work in a new session. Read after `BRIEFING.md`.

## Where we landed

The extreme signals detection shipped (commit `77ae1f0`). The pipeline now produces genuinely better drafts. The user explicitly confirmed: **"THESE ARE GENUINELY BETTER!!!!!!!!!!!!!"**

Proof-of-life drafts from this session:
- `monthly_high` signal fired for Bujumbura, Burundi at score 82: *"Bujumbura, Burundi forecast for 88.3F today. Hottest April in 30 years. The old record was 85.5F in 2005. That's nearly a 3-degree jump in less than two decades."*
- Calendar-date with era anchor: *"Medan, Indonesia forecast 92.3F today. That would beat a record from 1998. The year Google started."*
- Y2K-era anchor: *"Bujumbura, Burundi forecast 89.1F today. That beats an 83.1F record from 2000. The last time it was this hot on this date, we were still figuring out Y2K."*

These are shipping quality. Not viral-in-the-breakout-sense, but genuinely interesting in the data-ticker genre.

## The strategic pivot of this session

At the start we had been optimizing for "viral tweets" and creeping into growth-startup framing. **User reset hard: "this is not a business or startup. it's a utility."** Specifically:

- Not optimizing for follower growth or engagement metrics
- Not building visual cards (user: "i don't want to make visuals if the facts are lame")
- Not building a character voice (Karl-the-Fog-style personification was researched and rejected)
- Not building human-in-the-loop editorial (set-and-forget is non-negotiable)

**The goal:** surface astounding climate facts. The DATA is the product. If the data is lame, no voice/visual/character trick saves it.

**Voice anchor change:** "cynical weatherman who's seen too much" was the old framing from VOICE.md. User killed it explicitly ("no not cynical weatherman. omg."). Current framing: just let astounding data be astounding. Minimal framing, clean presentation.

## What shipped this session (commit order)

1. `77ae1f0` — **Expand signal detection** (the big one):
   - State schema: city_all_time_max/min, city_monthly_max/min, record_streaks
   - `detect_extreme_signals()` — unified bundle per city (one archive fetch → all signal types)
   - `check_extreme_signals_for_cities()` — replaces separate records + record_lows handlers
   - Scoring: score_all_time_record (80), score_monthly_record (76), score_anomaly (76), score_record_streak (74), score_simultaneous_records (78)
   - Generators with honest framing ("in 30 years of archive data" NOT "hottest ever")
   - Simultaneous event detection (5+ cities same day → one summary tweet)
   - Main.py: picks strongest signal per city (all-time > monthly > anomaly > calendar-date)
   - 310 tests passing

2. `4269550` — Replaced fabricated EXEMPLARS.md with verified viral climate tweets (real engagement data, sources cited)
   - Previous speculative file renamed to `brand/VOICE_PATTERNS.md`
   - New file is only tweets with documented virality (Greta "smalldickenergy", Hausfather "gobsmackingly bananas", Dessler "Hey assholes", Nakate "erased a continent", Kalmus "coolest summer", etc.)

3. `5158d27` — Built initial exemplar library (later replaced with verified version)

4. `05f299e` — Added PIPELINE.md with Mermaid flowchart

5. `393ddca` — Reorganized VIRALITY_RESEARCH.md by priority (Part 1 content first, Part 6 platform mechanics last, per user "content first, amplification last")

6. `0040284` — Expanded virality research (Part 2: algorithm mechanics, memetics, copywriting canon, tweet anatomy)

## What we considered and explicitly rejected

These came up during the session and were either researched or proposed, then rejected:

**Visual content / cards** — Research says +28× engagement (AJNR 2021). User: "not if the facts are lame." Deferred until data quality is proven. Reconsider later.

**Karl-the-Fog-style personification** — Researched thoroughly. Found no successful personified climate account exists. Academic research (Nature 2025) says personifying climate *reduces* engagement. Heat kills people; personification reads as glib during disasters. **Rejected.**

**Full autoplan scope expansion plan** — Original scope was 3 tiers across 3 weeks. Both CEO reviewers (Claude subagent + Codex) unanimously rejected it. User then reframed the goal as utility-not-business. We kept only Tier A (the core extreme-signals detection) and deferred everything else.

**Human-in-the-loop editorial lane** — Reviewers recommended, user rejected: set-and-forget is non-negotiable.

**Generator upgrade (DeepSeek / Groq / Sonnet as generator)** — User accepts Flash for generation. Premium-tier X account has Grok but UI-only (API costs extra).

**Framing lattice (5 forced intents)** — Codex's suggestion. Not implemented. User moved on to the data-detection work instead.

**Model upgrade** — User's stance: "models will get better over time. we want the challenge." Build infrastructure that's model-agnostic; swap models later as they improve.

## Deferred for future sessions

Each of these is a clear next step but the user hasn't greenlit them:

1. **Country-level records** — would require national-level aggregation from existing per-city data (France's hottest day ever, etc.)
2. **Ocean SST / marine heatwaves** — NOAA OISST integration (new source)
3. **Ice events** — GLIMS (glaciers), NASA GRACE (ice mass)
4. **Fire footprint (acreage)** — GWIS integration
5. **Cross-source story synthesis** — drought + fire + heat in same region → one narrative signal
6. **RSS enrichment** — Carbon Brief / Climate Central / Yale E360 / Grist feeds for context
7. **Visual card template** — if data quality proves out and user approves
8. **Global anomaly tracking** — GISTEMP monthly anomalies, "30th consecutive month above 1.5°C"
9. **Framing lattice** — Codex's 5-intent generator architecture

## Known issues to watch

- Alert cycle takes ~13 min (sequential API calls to 257 cities). Not blocking but slow.
- Dashboard deployment on Vercel may be behind latest main — check if new signal types render correctly.
- New signal types need calibration. Thresholds set reasonably based on signal semantics but may need tuning after a week of real traffic. Watch per-cycle volume.
- The `simultaneous_records` signal fires if 5+ cities broke records same day. This may be uncommon but is worth monitoring — if it fires weekly, threshold is right; if it never fires, consider lowering.

## Files layout (current, post-organization)

```
theheat/
├── BRIEFING.md                # Session entry point — read this first
├── PIPELINE.md                # Flow diagram (Mermaid)
├── requirements.txt
├── docs/
│   ├── DESIGN.md              # Architecture decisions
│   ├── BUILD_BRIEF.md         # Product scope
│   ├── FUTURE_STATE.md        # Aspirational future
│   ├── SESSION_BRIEF.md       # This file — latest session context
│   └── mockups/               # Dashboard HTML mockups
├── brand/
│   ├── VOICE.md               # Voice spec (moved from root)
│   ├── MESSAGING_ARCHITECTURE.md
│   ├── VIRALITY_RESEARCH.md   # Part 1 content, Part 6 platform
│   ├── EXEMPLARS.md           # Verified viral climate tweets with sources
│   └── VOICE_PATTERNS.md      # Voice patterns (not proven-viral, honest about it)
├── src/                       # Python (7,179 lines)
├── tests/                     # 310 tests across 22 files
├── dashboard/                 # Next.js 15 on Vercel
├── data/                      # cities.csv, normals.csv
├── scripts/                   # build_normals.py
└── .github/                   # Actions workflow
```

## Key decisions to respect in future sessions

1. **It's a utility, not a business.** Don't optimize for followers. Don't suggest growth hacks. Don't propose visual content unless data quality proves out first.

2. **Set-and-forget is non-negotiable.** No human-in-the-loop editorial layers. The bot must run autonomously.

3. **$0 additional cost is a hard constraint** unless explicitly relaxed. Current spend is ~$60-90/mo for Anthropic (Sonnet evaluator). Do not add paid services without asking.

4. **Honesty in framing.** Archive goes back ~30 years, not "all time." Say "in 30 years of records" — do not lie about data span.

5. **Voice is secondary to data.** If the data isn't astounding, no voice work makes the tweet viral. Focus first on the detection/data layer.

6. **Be brief.** User requested less text, more action. Propose, don't debate. Multiple paragraphs at a time is too much.

7. **No visuals until facts are proven astounding.** User was explicit: "i don't want to make visuals if the facts are lame."

## Current running state

- 310 tests passing
- 3 pending drafts in queue (all 74+ signal score) as of April 18 21:36 UTC
- Next alert cycle at top of next hour will produce more of the new signal types
- Latest commit on main: `77ae1f0`

## When picking up in a new session

1. Read `BRIEFING.md` first (full project state)
2. Read this `SESSION_BRIEF.md` for recent context
3. Check dashboard at https://dashboard-phi-beryl-65.vercel.app for current draft queue
4. Check `git log --oneline -10` to see what's landed since the brief was written
5. If user asks about a new direction, check the "rejected" list above to avoid re-proposing dead paths
