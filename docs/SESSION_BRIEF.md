# Session Brief

Handoff doc for picking up @theheat work. Read after `BRIEFING.md`. Newest section at top.

---

# 2026-04-26 → 2026-04-29 — Voice engine v3 + research grounding + posting paused

## Where we landed

`main` is on the voice engine v3 ship commit. **566 tests passing** (was 522 at session start). Posting paused since 2026-04-12 — deliberate quality bar set 2026-04-26: posting resumes when majority of corpus-graded drafts earn A grades. Currently 0% A-rate (Apr 29). Daily plan-refinement agent runs 15:00 UTC, refining `docs/IMPROVEMENT_PLAN.md`.

## The big shifts this session

1. **Posting bar made explicit.** "Resume posting when majority A" — pinned in BRIEFING. Applies to all future cycles. Stale drafts can't ship even when shippable; window expires.
2. **Humor research grounded the voice work.** New doc `brand/HUMOR_RESEARCH.md` (270 lines) covers the four humor theories (Kant/Schopenhauer incongruity, McGraw & Warren benign violation, relief, superiority), joke construction, comic triple, brevity + specificity, deadpan tradition (Steven Wright, Mitch Hedberg, Bob Newhart), British humor (Wodehouse rule), and Shifman meme theory. Gives every voice mechanic a name and a corpus example. **Wodehouse rule named as the most predictive principle:** the voice should never sound like it's trying to be funny.
3. **Era anchors parked at 1-in-10.** Three consecutive corpus cycles (Apr 25, 27, 29) showed 100% era-anchor deployment on records. User direction Apr 29: park at no more than 1-in-10 tweets. Voice engine v3 ships the structural gate (`_era_anchor_should_fire`, deterministic by city+year+date seed). 90% of record drafts get explicit "parked, use other vehicles" steer-away; 10% get curated content framed as "your 1-in-10 turn."
4. **Addendum-mismatch bug fixed.** `generate_all_time_record_tweet` was using `category="all_time_record"` but addenda were keyed `all_time_high`/`all_time_low` — addenda had been DORMANT. Fixed to `category=f"all_time_{kind}"`. Same for monthly. Added missing `monthly_low`, `country_low`, `record_low` addenda. The voice work that went into those addenda has now actually started applying.
5. **Daily plan-refinement agent created.** `trig_016PGeHZgEYWmeQhx1xGmYg6`, fires 15:00 UTC daily. Reads framework docs, grades drafts, refines `docs/IMPROVEMENT_PLAN.md`, opens a PR. Plan-only — does NOT implement code/prompts. User reviews, we implement together.
6. **Anchor curation cleaned.** Pruned 43 entries from `data/era_anchors.json` (politically-charged: Trump, Brexit, Capitol riot, Elon/Twitter, MeToo; mass tragedies as scaffolding: 9/11, Katrina, Hurricane Sandy, Indian Ocean tsunami; US-only sports: Cubs, Red Sox; etc). Now 205 anchors / 31 years / 6.6 avg per year, all globally legible and politically neutral.
7. **Two-bot architecture conversation opened.** User raised: separate Data Organizer (gathers + structures signals into "story bundles") from Writer (takes bundles, writes voice with great voice). Cleaner than current Gemini-generates-then-Sonnet-rewrites. Brainstorm pending.
8. **Cost reality update.** "Free tier" Gemini claim was outdated. `gemini-flash-latest` aliases to a paid preview model at $0.30/$2.50 per MTok. Current Gemini spend: ~$5–10/mo. Pin `GEMINI_MODEL=gemini-2.5-flash` to return to free tier.

User also clarified important nuances:

- **"not everything has to be a joke"** — humor mechanics are tools, not mandates. Pure data delivery is valid when the number is striking enough.
- **"the era anchor can't be used every time. it gets so old and lame"** — drove the 1-in-10 parking decision.
- **"we paused posting because the tweets sucked"** — explained the 0-pending state. Posting is a deliberate quality pause, not an operational gap.
- **"we can't post those because they aren't real time"** — drafts have time-baked content, expire fast. 14 stale pending bulk-rejected 2026-04-26.
- **"keep building and refine an improvement plan, then i can review it and we can implement together"** — sets the agent autonomy boundary. Daily agent refines plan; human + Claude implement.

## What shipped this session (chronological)

- Voice engine v2.5 (era anchors + multi-station roll-call + recalibrated rules + opener-formula ban + earned editorial heat permission) — pre-session leftover
- BRIEFING resumption-bar pin + `docs/QUALITY_TREND.md` (A-rate trend + rejection log)
- Bulk-reject 4 D-range fires + 14 stale pending drafts (queue zeroed for clean baseline)
- `brand/HUMOR_RESEARCH.md` (270 lines, sibling to VIRALITY_RESEARCH)
- Apr 27 corpus humor-lens evaluation + Apr 24 corpus re-grades (#3, #4 demoted on grammatical-referent issue)
- `data/era_anchors.json` audit + 43-entry prune
- `docs/CLAUDE_DESIGN_BRIEF.md` + `docs/claude-design-handoff/` folder (3-direction brand identity request)
- `docs/IDEAS.md` NVIDIA NIM entry (dev-only A/B harness)
- `docs/IMPROVEMENT_PLAN.md` (living plan refined daily by autonomous agent)
- Daily recurring schedule `trig_016PGeHZgEYWmeQhx1xGmYg6` for plan refinement
- Apr 29 corpus grading (3 drafts, 0% A-rate)
- **Voice engine v3 (this commit):** era-anchor 1-in-10 gate + addendum-mismatch fix + 5 record-type addenda rewrite to 6-vehicle menu + SYSTEM_PROMPT #1 vehicle-agnostic rewrite + 3 new bad-examples + 5 new gate tests

## What's pinned mid-implementation

1. **Two-bot architecture redesign.** User raised 2026-04-29; we sketched the shape (Data Organizer outputs structured story bundles; Writer takes bundles + voice). Brainstorm not yet held. Bigger lift than P1-P6 — architectural.
2. **Prompts inventory doc.** User asked for a single doc listing all bot prompts (system + per-category + helpers + safety + evaluator) with content + locations. Half-built; abandoned mid-stride when the architecture conversation opened.

## Other open threads

- **Voice rules vs @extremetemps:** the voice spec is over-engineered for breakout-viral aspiration when our genre uses ALL CAPS / editorial heat / multi-station data dumps. Voice engine v2.5 partially addresses; deeper rethink still possible.
- **`evaluator_pass=null`** on all 3 Apr 29 drafts. Either evaluator isn't writing verdict to draft state, or `EVALUATOR_ENABLED` got set false. Worth investigating.
- **Daily plan-refinement agent's first run** is tomorrow morning. Should observe the empirical effect of the v3 era-anchor gate.

## Numbers

- Tests: 522 → 566 (+44 across the session)
- Commits pushed to `main`: 12+ (era_anchors prune, HUMOR_RESEARCH, corpus updates, design brief, IDEAS, BRIEFING, QUALITY_TREND, IMPROVEMENT_PLAN, voice engine v3 — final commit pending in this session)
- Era-anchor inventory: 248 → 205 (43 pruned)
- Pending drafts: 0 (paused; would-be drafts get graded but not posted)
- API spend: $30–55/mo total stack
- Posting cadence: 0 (last post Apr 12; resumption bar majority-A not yet cleared)

## When picking up in the next session

Read in order:
1. `BRIEFING.md` (current state)
2. This file's top section (Apr 26-29 — what just happened)
3. `docs/NEXT_SESSION.md` (action menu, invariants, common commands)
4. `docs/IMPROVEMENT_PLAN.md` (living plan, P1 SHIPPED + P4-P6 active)
5. `docs/QUALITY_TREND.md` (A-rate trend)
6. `docs/DRAFT_CORPUS.md` Apr 29 + Apr 27 sections (lens evaluations + re-grades)
7. `brand/HUMOR_RESEARCH.md` (the framework)

Pull pending drafts. If new corpus needs grading, append to `DRAFT_CORPUS.md`. Then pick a menu item from `NEXT_SESSION.md` — likely either continue the voice work (P4 Wodehouse top-of-prompt), open the two-bot architecture brainstorm, or finish the prompts inventory.

---

# Session Brief — April 24, 2026

Handoff doc for picking up @theheat work. Read after `BRIEFING.md`.

## Where we landed

`main` is at `1573d15`. **522 tests passing.** Single longest session
yet — combined the fire geocoder fix, FRP floor raise, voice engine
v2 (per-category prompts + stock-formula rejector), Gemini model
upgrade to `gemini-flash-latest`, full draft-quality audit of 35
pending drafts, bulk-rejection of all 35 with full inventory archived
to `docs/DRAFT_CORPUS.md`, and an ongoing model conversation that
ended with "do it right for now, keep Sonnet."

## The big shift this session

User reviewed pending drafts and grade-distributed them honestly: 7
A/B-grade out of 35, mostly records (Sevilla, Chicago, Jacobabad,
Kathmandu, Ipoh, Medan, Hawaii). 27 fires, all formulaic. Then user
showed three @extremetemps tweets — the actual successful account in
our genre, 106K followers — which break almost every voice rule we've
codified: ALL CAPS openers, "EXTRAORDINARY" / "Mind blowing"
editorial heat, multi-station data dumps, threading.

**This is the architectural insight to preserve:** our voice spec is
optimized for *breakout-viral aspiration* (Thunberg, Hausfather,
Kalmus). The data-ticker genre we're actually in uses different
tactics. We've banned the very tools the genre leader uses. Voice
engine v2 prompt addenda partially address this — they're more
permissive of editorial heat earned by the data — but the deeper
question (multi-station roll-call format, threading, lighter telling)
is still mostly TBD.

User also clarified important nuances:

- "We don't always want to roll-call though" — but don't preclude it
  in the data structure. Roll-call should be a callable generator
  format, not the only output.
- "Maps are easy to add. The hard part is the text." → maps are
  table-stakes-but-not-the-engine; voice work is the real lever.
- "We don't want to give up our generator and evaluator model" →
  keep two-model architecture. Don't collapse to single-pass Opus.
- "I'm unemployed!" → cost matters. But: "let's do it right for now"
  → keep Sonnet 4.6 evaluator running ($25-45/mo); don't switch to
  Opus; don't switch to Haiku; just have the kill switch ready.

## What shipped this session (chronological)

1. **`22cbc8e`** — Fire reverse-geocoder upgrade. `firms.py::
   reverse_geocode_simple` was returning continent-level labels
   ("somewhere in Asia"). Replaced with a 70+ entry bounding-box
   lookup ordered most-specific to least-specific. "Eastern Siberia,
   Russia" / "Patagonia, Argentina" / "the Kazakhstan steppe" / "the
   Northern Territory, Australia" — properly named regions globally.
   `_lat_lon_to_region` and `_lat_lon_to_country` retained as thin
   wrappers for backward compat.

2. **`023c3ed`** — FRP floor raised 100 → 250 MW. Sub-200 MW fires
   produced weak copy ("a coal plant runs at 150 MW, this is one of
   those") because the math was forced. 250 MW is closer to the
   "this reads as a real incident" threshold. Plus
   `docs/VOICE_FAILURE_ANALYSIS.md` added — names five Gemini ruts
   from the corpus with concrete intervention sketches.

3. **`d99ffe4`** — `docs/DRAFT_CORPUS.md` added with 2026-04-24
   section: full inventory of all 35 pending drafts including text,
   grade, and commentary. Then bulk-rejected all 35 via direct Gist
   PATCH. Pending queue cleared. The texts remain preserved in
   the doc as the longitudinal-corpus baseline.

4. **`827a891`** — Voice engine v2: per-signal-type prompt
   addendums + stock-formula rejector. Universal prompt updated to
   explicitly ban "powers N homes," generic power-plant comparisons,
   "no name yet" closers, continent-only locations. Per-category
   addenda for fire, all_time_high/low, monthly_high, anomaly_hot,
   country_high/low, record, co2_milestone, marine_heatwave,
   ice_mass_record, fire_footprint, synthesis. Regex rejector at
   parse time as last-line defense. Removed stale Siberia
   power-plant exemplar that was teaching Gemini the bad pattern.

5. **`d0977af`** — `docs/LEVEL_UP_PLAN.md` added. **Tier ordering
   was wrong on first pass** — I had Tier 1 = "post-publish analytics
   loop" until user pointed out we don't post enough for analytics
   to mean anything. Should re-read with quality work as Tier 1 and
   analytics as Tier 2-3. Worth a revision.

6. **`e25d0f0` then `b33d4a8`** — Gemini 2.5 Flash → 3.x model upgrade.
   First attempt pinned `gemini-3.1-flash-lite-preview` (user
   correctly flagged Lite is wrong for voice work). Second iteration
   switched to the `gemini-flash-latest` alias which Google rolls to
   whatever the current best Flash is. `GEMINI_MODEL` env var lets
   prod swap to a pinned snapshot or fall back to 2.5 instantly.

7. **`fa768a4`** — Two future-lane parking entries in `docs/IDEAS.md`:
   - Grok 4 A/B as candidate generator (xAI is the only frontier
     model trained on Twitter/X data — most ideologically aligned
     with our publishing platform).
   - Fine-tune Gemma 4 / Qwen 3.5 / Llama 4 on the @extremetemps
     corpus + EXEMPLARS + our A/B drafts. The differentiated bet —
     no other climate Twitter account is doing genre-specific
     fine-tuning. ~1 week of work, ~$100-300 compute.

8. **`4f07d50`** — BRIEFING cost figure corrected $60-90 → $25-45/mo.
   Previous figure was inherited from a prior session and never
   recalibrated. Real spend verified against console.anthropic.com.

9. **`1573d15`** — Added `EVALUATOR_ENABLED` env var kill switch
   (default `true` so no behavior change). Set to `false` to skip
   the Sonnet evaluator pass and drop Anthropic spend to ~$0/mo.
   Documented in BRIEFING secrets table.

## What's pinned mid-implementation

1. **Multi-station roll-call format for `simultaneous_records`.** The
   signal currently triggers on 5+ cities globally same day but the
   generator emits a flat summary ("5 cities broke records today")
   instead of a per-station list ("26.8 Janakpur / 24.1 Dang 663m /
   20.4 Dhankuta 1192m"). User saw this gap and said do it but keep
   roll-call as one *option* among formats — not the only output.
   Implementation pinned when user redirected to models conversation.

2. **Elevation surfacing in record/anomaly generators.** Elevation
   column added to cities.csv (this session) but the generator
   prompts don't yet pull it through. Tropical-night-in-the-highlands
   stories ("never happened above 1200m") need this data in the
   prompt context.

3. **13 cities missing elevation values.** Bulk fetch hit a 429 on
   the last batch. Trivial retry — just rerun the fetch script for
   the rows where `elevation_m` is empty.

## Other open threads

- **Voice rules still over-engineered for the wrong genre.** Voice
  engine v2 helped (allows some editorial heat earned by data) but
  the @extremetemps comparison shows we may still be too prim. Worth
  another voice-prompt iteration after observing what the new model
  + new prompt produce in the next draft cycle.
- **`docs/LEVEL_UP_PLAN.md` Tier ordering is wrong.** Tier 1 should
  be quality-side (era-anchor database, regenerate-corpus, prompt
  iteration), not analytics. Worth a revision.
- **Fine-tune lane** is the most differentiated future move. Real
  data sitting unused. Parked for now per user's "do it right for
  now" pace.

## Numbers

- Tests: 501 → 522 across the session (+21)
- Commits pushed: 9 to `main`
- API spend: $25 since April 7 (~$1.50/day) — verified
- Cities tracked: 613 across 179 countries with elevation
- Pending drafts: 0 (cleared after corpus archival)

## When picking up in the next session

1. Read `BRIEFING.md` (project state)
2. Read `docs/DRAFT_CORPUS.md` 2026-04-24 section (the corpus that
   informed every voice change today)
3. Read `docs/VOICE_FAILURE_ANALYSIS.md` (named patterns)
4. Read this `SESSION_BRIEF.md` (what just happened)
5. Read `docs/NEXT_SESSION.md` (action menu for the new session)
6. Pull current pending drafts from the Gist — see whether the next
   alerts cycle output reflects voice engine v2 quality lift
