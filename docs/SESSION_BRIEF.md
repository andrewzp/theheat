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
