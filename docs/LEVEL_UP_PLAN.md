# Level-Up Plan — revised 2026-04-25

Supersedes the 2026-04-24 first pass. The original ranked
"post-publish analytics" as Tier 1; that was wrong. We post ~1 tweet
per day on average, so analytics measures noise. **Quality-side work
is the Tier 1.** Analytics is demoted to Tier 2 — we'll need it once
post volume is non-trivial, but not before.

Cost figures throughout this doc are calibrated against the verified
2026-04-24 spend ($25–45/mo for the Sonnet 4.6 evaluator), not the
stale $60–90/mo BRIEFING figure that appeared in the first-pass plan.

Read with: `docs/DRAFT_CORPUS.md` (what's actually shipping) and
`docs/VOICE_FAILURE_ANALYSIS.md` (named failure modes).

---

## 1. Where the ceiling is right now

**Voice engine v2 (commit `827a891`, 2026-04-24) plus this session's
work has measurably lifted draft quality.** The 2026-04-25 corpus
section in `DRAFT_CORPUS.md` shows 86% shippable (6 of 7) vs 20% (7
of 35) on Apr 24. Era anchors, geocoder fixes, the FRP floor, and the
per-category prompt addenda are doing the work the original plan said
they would.

That said, three structural ceilings remain:

1. **Single-model candidate generation.** Gemini Flash (now via
   `gemini-flash-latest`) is one model's voice with one set of
   training biases. The evaluator rewrites when it fails, but the
   candidate pool stays narrow.
2. **No feedback loop.** Tweets post, then we stop watching. There's
   no engagement signal feeding back into anything. The evaluator
   judges "does this read viral?" not "does this actually get
   shared?"
3. **Voice rules vs the genre we're in.** The @extremetemps
   observation from 2026-04-24 stands: our voice spec is optimized
   for breakout-viral aspiration (Thunberg-tier cultural moments)
   when the actual successful account in our genre uses ALL CAPS,
   editorial heat, and multi-station data dumps. Voice engine v2
   partly addresses this; deeper iteration is open.

Every Tier-1 intervention below targets ceiling #3. Tier 2 attacks
ceiling #2. Tier 3 attacks ceiling #1.

---

## 2. Intervention menu

### Tier 1 — Quality-side work (where the ceiling actually breaks)

#### 2.1 Era-anchor database — **SHIPPED 2026-04-25, then PARKED at 1-in-10 on 2026-04-29**

Pre-computed cultural anchors keyed by year (1995–2025). Generators
that have an `old_record_year` get a seeded sample of 4 anchors as
part of the prompt data. Replaces Gemini's invented anchors, which
sometimes hallucinate.

**Files:** `data/era_anchors.json`, `src/voice/era_anchors.py`,
threaded into 5 record-type generators.

**Verdict (post-corpus, three cycles):** the hint over-deployed.
Apr 25 / Apr 27 / Apr 29 corpora all showed 100% era-anchor
deployment on records. User direction Apr 29: park at 1-in-10. Voice
engine v3 (commit on 2026-04-29) ships:

- `_era_anchor_should_fire(seed_key, rate=0.1)` deterministic gate.
- `_era_anchor_hint` rewritten — 90% of calls return explicit
  steer-away naming alternative specificity vehicles; 10% return
  curated content framed as "your 1-in-10 turn."
- 43-entry curation prune (political, US-centric, mass-tragedy
  scaffolding entries removed).
- Addendum-mismatch fix (`all_time_record`/`monthly_record` category
  strings now use `kind`, matching `all_time_high/low` /
  `monthly_high/low` addendum keys which had been dormant).

**Status:** structural fix shipped. Empirical signal: next 3 cycles
should drop era-anchor deployment to ~10% on records. If yes, P1
moves to Resolved. If not, deeper intervention needed.

---

#### 2.2 Multi-station roll-call format — **SHIPPED 2026-04-25**

When 5+ cities break daily records the same day AND a same-country
cluster has elevation spread ≥800m, the bot can now emit a
per-station roll-call ("Janakpur 99.5F 80m / Dhankuta 84.6F 1192m")
instead of the flat summary. Roll-call is one option among formats —
flat summary is still the default. Routing lives in
`src/editorial/simultaneous_format.py`.

**Files:** new module + 19 tests, plus changes to `src/main.py`
(richer per-station data), `src/voice/generator.py` (new generator
function + per-category prompt addendum). Codex-reviewed; 4 P2 fixes
applied (city/country tuple keying, blank-country skip, deterministic
tie-break, altitude endpoint pinning).

**Verdict:** also pending the next post-cycle. Routing is
intentionally restrictive (3+ stations same country + 800m spread);
calibration can loosen once we observe how often it qualifies.

---

#### 2.3 Regenerate-and-compare corpus

The 2026-04-25 corpus is the first eval baseline under voice engine
v2. As more drafts accumulate, periodically re-run the SAME prompts
against the SAME signals (replay from `docs/DRAFT_CORPUS.md`'s
preserved texts) under the current generator config. Compare grade
distribution before and after each prompt change.

**Why it matters:** without this, every prompt iteration is "feels
better" rather than "measurably better." The corpus IS the eval
harness.

**Scope:** ~3–4 hours. Add a `regenerate_corpus.py` script that takes
a date and replays the events, plus a `corpus_diff.py` that
side-by-sides old vs new outputs. Manual grade re-assignment, but the
mechanical work disappears.

**Cost:** ~$1–2 per regeneration cycle (Gemini Flash). $0 for the
script.

---

#### 2.4 Voice rules vs @extremetemps — deeper rethink

Three @extremetemps tweets shared 2026-04-24 break almost every voice
rule we've codified. ALL CAPS, "EXTRAORDINARY", multi-station data
dumps, threading. The account has 106K followers in our exact genre.
Voice engine v2 partly relaxed our rules (allows earned editorial
heat, e.g., "HOT season has barely started" in the 2026-04-25 corpus)
but the deeper question is open: are our hard bans correctly
calibrated, or are they suppressing voice moves the genre actually
rewards?

**What:** Audit each hard-ban rule in `brand/VOICE.md` against the
@extremetemps corpus. For each rule, classify:
- "Genuinely required" (no preaching, no moralizing, no political)
- "Genre-mismatched" (over-tight for a data-ticker account)
- "Tunable" (the rule is right but the implementation is too strict)

Then update `brand/VOICE.md` and the per-category prompt addenda
where calibration shifts.

**Scope:** ~1–2 hours. Doc + prompt iteration. Output: a revised
`brand/VOICE.md` plus targeted prompt-addendum updates.

**Cost:** $0.

---

#### 2.5 Per-failure-mode prompt iteration (ongoing)

Voice engine v2 codified five named failure modes in
`docs/VOICE_FAILURE_ANALYSIS.md`. As new corpus cycles surface new
failure modes, add them. Each new entry produces:
- A regex addition to `_STOCK_FORMULA_PATTERNS` if mechanical.
- A per-category prompt addendum if pattern-level.
- An entry in `docs/DRAFT_CORPUS.md` flagging the regression.

**This is the work that has the most leverage per hour spent.** Voice
engine v2 → v3 → v4 are incremental but compound. The 2026-04-25
corpus already surfaced one new ban candidate ("A [fire] in [LOCATION]
right now is radiating..." opener returned in the Mali dup).

**Scope:** ongoing, ~30 min per failure-mode codification.

**Cost:** $0.

---

### Tier 2 — Measurement & feedback (do once post volume is non-trivial)

#### 2.6 Post-publish analytics loop — **DEMOTED from Tier 1**

After a draft posts, wait 24–72 hours, pull X metrics (impressions,
likes, retweets, bookmarks, replies) via the X API. Store per-draft
in state as an `engagement` dict. Build a top-20 / bottom-20 / median
report by signal type.

**Why it matters (eventually):** the evaluator currently judges "does
this read viral?" not "does this actually get shared?" A real
engagement signal would let us A/B prompt iterations against
performance, not vibes.

**Why it's NOT Tier 1 anymore:** We post ~1–3 tweets per day. Across
30 days that's at most ~90 tweets. With 5+ signal types, that's
fewer than 18 tweets per signal type per month. Statistically the
signal-to-noise is bad — engagement variance dwarfs prompt variance
at that volume.

**Un-park signal:** average daily post volume crosses ~5/day for
3+ weeks. Until then, prompt iteration is faster + cheaper than
data collection.

**Scope:** ~4–6 hours. New module `src/posting/metrics.py`. New state
field `engagement_metrics`. New cron mode `metrics_refresh` running
once daily. Optional dashboard section.

**Cost:** $0 — X API free tier allows metrics reads.

---

### Tier 3 — Model swaps (real but timing-sensitive)

#### 2.7 Generator model swap: Gemini Flash → Claude Haiku 4.7

**Context:** current architecture = "Gemini generates 4 candidates,
Sonnet evaluates + rewrites." Could swap to Haiku as generator.

**Arguments for:**
- Haiku 4.7 voice is typically sharper than Gemini Flash for
  short-form English copy.
- Anthropic's small-model voice has the deadpan/punchy register the
  account is going for.
- One-vendor stack simplifies billing and observability.

**Arguments against:**
- Cost: Haiku 4.7 generator at our volume probably $80–120/mo vs $0
  on Gemini's free tier. Real money on a "utility, not business"
  project.
- Latency: Gemini Flash is still genuinely fast; alert cycles could
  grow from ~30 min to ~40+.
- Loss of 4-candidate diversity: Anthropic models tend to converge;
  Gemini diverges. We lose some "pick best of 4" optionality.

**Verdict:** A/B in production for 2 weeks once analytics (Tier 2.6)
is in place. Without engagement data, we have no honest way to
declare a winner. Until then, stay on Gemini.

**Scope:** ~4 hours once analytics is in place. Mostly a config flag.

#### 2.8 Generator model swap: Sonnet 4.6 generator (collapse the two-model architecture)

**Context:** Sonnet 4.6 is already doing the rewrites we ship. Could
collapse generator + evaluator into one model.

**Arguments for:**
- Sonnet's voice is measurably better than Gemini for this style.
- One model, one voice, fewer seams.
- Prompt caching on Sonnet would cap cost growth.

**Arguments against:**
- Cost: probably $200–400/mo for Sonnet generator at our volume.
  6–10× current spend.
- Loss of 4-candidate diversity (Sonnet converges).
- Loss of the "evaluator independence" property — if generator and
  evaluator are the same model, the evaluator can no longer catch
  the generator's blind spots.

**Verdict:** user explicitly rejected this Apr 24 — "we don't want
to give up our generator and evaluator model." Two-model
architecture is invariant. Don't revisit without explicit ask.

#### 2.9 Evaluator model upgrade: Sonnet 4.6 → Sonnet 4.7

**Sonnet 4.7:** incremental. ~30% better reasoning per published
evals. Probably lands as a quiet win at similar cost. **Trivial swap;
do whenever.**

#### 2.10 Evaluator model upgrade: Sonnet 4.6 → Opus 4.7

**Opus 4.7:** substantially more capable. Evaluator role benefits
because the rubric balances 5 dimensions. At our volume —
50–100 evaluator calls per day — this lands at ~$50/mo (verified
2026-04-24). NOT 5× cost; only ~2× current Sonnet spend.

**Verdict:** Sonnet 4.7 first (free incremental win). Opus only if
the corpus shows evaluator verdicts diverge from human grading on
the regenerate-and-compare cycle (Tier 1.3). User said "no Opus, no
Haiku for now" Apr 24 — respect the pin until corpus data justifies
revisiting.

#### 2.11 Open-weights for the safety LLM check

The Layer-2 safety LLM (currently Gemini) is a binary "does this
mock human suffering?" check. Quality bar is low. Could route to
Groq + Llama 4 / Qwen 3 cheaply.

**Verdict:** worth doing IF Gemini becomes a dependency problem
(rate limit, deprecation, voice bleed-through). Not urgent.

---

### Tier 4 — Content/distribution levers

#### 2.12 Visual cards

From `brand/VOICE.md` and Apr 24 user feedback: "revisit once fact
quality proves out." Voice engine v2 + roll-call + era anchors are
proving it out. The next corpus cycle is the verdict.

**What:** Generate a house-style card per posted tweet. Text +
location + one chart element. Post as image instead of text-only.

**Research anchor:** 28× engagement for climate content with images
(`brand/VIRALITY_RESEARCH.md`).

**Scope:** ~1–2 weeks. New `dashboard/` page for card preview, new
`src/visual/cards.py` renderer (Pillow or matplotlib), pipeline
integration. User said maps are "easy to add, hard part is the text"
— most of the difficulty is design quality, not engineering.

**Cost:** $0 recurring.

**Un-park signal:** voice quality plateaus AND posting volume crosses
the analytics-justifies-itself threshold.

#### 2.13 RSS / news-collision enrichment

From `brand/EXEMPLARS.md`: the consistent viral-climate pattern is
**climate × non-climate news collision**. Pure climate almost never
goes breakout-viral; a climate signal converging with a top-news-cycle
story does.

**What:** Add Carbon Brief / Reuters / AP feeds. When a climate event
co-occurs with a major news story, surface the fusion in the
generator prompt.

**Scope:** ~1 week. New `src/data/news.py` with RSS parsing, "news
context" added to synthesis rules.

**Risk:** edges toward editorialization. Needs tight rules to stay
on the "utility, not business" side. The set-and-forget invariant
plus the "no preaching, no political" voice rules already constrain
this; the rules survive contact with news context with care.

#### 2.14 Timing optimization

X algo rewards first-30–60-min engagement. We post when the cron
fires. Records and Hot 10 could shift toward US/EU overlap (~15:00
UTC). Trivial config in `approval.py` once analytics shows it
matters.

---

### Tier 5 — Rebuilds / big swings

#### 2.15 Engagement-fed evaluator

After analytics (2.6) runs for 30+ days: train a small classifier
(logistic regression on tweet features → engagement bucket) and use
it as a *third* pre-publish filter alongside the Sonnet evaluator.

**Scope:** ~2–3 weeks, mostly waiting for data.

#### 2.16 Ensemble generation

Generate with Gemini AND Haiku AND a third provider. Feed all
candidates into the evaluator. Ship the overall winner. Cost
multiplies but candidate diversity grows.

**Gate:** only justifiable if analytics shows the current ceiling is
genuinely capped by candidate-pool diversity, not by prompt quality
or by evaluator calibration.

#### 2.17 Genre-specific fine-tune (the differentiated bet)

Fine-tune Gemma 4 / Qwen 3.5 / Llama 4 on the @extremetemps corpus +
`brand/EXEMPLARS.md` + our A/B drafts from `DRAFT_CORPUS.md`. ~1
week of work, ~$100–300 compute. No other climate Twitter account is
doing genre-specific fine-tuning.

**Parked in `docs/IDEAS.md`** as the most differentiated future
move. Run after the prompt-iteration ceiling is hit.

#### 2.18 Human-in-the-loop for viral candidates — **rejected**

From `brand/EXEMPLARS.md`: breakout viral requires human-shaped
moments. Could ping a user for 15-min polish on exceptional drafts.

**Conflict:** directly violates the set-and-forget invariant. User
has rejected this twice. **Listed for completeness, not
recommended.**

---

## 3. Recommended sequence (revised)

1. **Tier 1 quality work (in-flight).** Era anchors and roll-call
   format SHIPPED 2026-04-25. Voice rules vs @extremetemps audit
   (2.4) and per-failure-mode iteration (2.5) are the next 1–2 hours
   of leverage.
2. **Regenerate-and-compare corpus (2.3).** Set up the eval harness
   so future prompt changes are measurably better, not just
   feelings-better. ~3–4 hours.
3. **Sonnet 4.7 evaluator swap (2.9).** Free incremental win.
   Trivial. Do whenever.
4. **Wait for post volume.** Until average daily posts cross ~5/day
   for 3+ weeks, analytics measures noise. Tier-1 prompt work has
   higher leverage per hour.
5. **Then 2.6 analytics loop.** Builds the foundation every later
   model-swap or content-lever decision rests on.
6. **Tier 3/4 evaluations only with real engagement data.** Haiku
   A/B, Opus eval upgrade, visuals, RSS — all of these become real
   choices once we can actually measure.

**Deliberately NOT in the first pass:**
- Sonnet generator swap (user-rejected; two-model architecture is invariant)
- Ensemble generation (premature — ceiling not proven to be candidate diversity)
- Human-in-the-loop (set-and-forget invariant)
- Genre-specific fine-tune (parked; revisit after prompt ceiling is hit)

---

## 4. Model landscape quick reference (as of 2026-04-25)

| Model | Role fit | $/mo at our volume | Notes |
|---|---|---|---|
| **Gemini Flash (latest)** | Generator (current) | $0 (free tier) | Fast, diverges well, voice mid. Currently `gemini-flash-latest`. |
| **Gemini 3 Pro** | Generator alternative | unclear pricing | Higher quality than Flash, probably slower. Verify pricing. |
| **Claude Haiku 4.7** | Generator candidate | ~$80–120 | Sharper voice than Flash. A/B candidate for Tier 3. |
| **Claude Sonnet 4.6** | Evaluator (current) | $25–45 | Verified spend. Used for evaluation + rewrite. |
| **Claude Sonnet 4.7** | Evaluator upgrade | $25–45 | Trivial swap, incremental win. |
| **Claude Opus 4.7** | Evaluator upgrade | ~$50 | Verified at our volume. ~2× Sonnet, not 5×. Real option. |
| **GPT-5** | Unclear | unclear | Claude generally wins on voice; no specific case to swap. |
| **DeepSeek R1 / Qwen 3 / Llama 4** | Safety LLM only | $0–20 | Voice bar too high for generator/evaluator; fine for binary safety. |

**Pricing caveat:** verified 2026-04-24 against console.anthropic.com.
Other providers: extrapolated from public pricing pages — verify
before committing to a swap.

---

## 5. What NOT to do (kept honestly)

- **Don't swap the generator without analytics first.** Trading an
  unknown for an unknown. Wait for engagement data.
- **Don't collapse to a single-model architecture.** User-rejected;
  two-model independence is invariant.
- **Don't add ensemble generation yet.** Premature; candidate-pool
  diversity isn't proven to be the ceiling.
- **Don't reintroduce human-in-the-loop.** Set-and-forget is a
  feature, not a limitation.
- **Don't broaden detection further.** Signal side is rich enough
  (14 sources, 613 cities, synthesis lanes). Voice is the bottleneck.
- **Don't chase breakout viral.** `brand/EXEMPLARS.md` ceiling is
  "data-ticker excellence" (the @extremetemps model). Voice engine
  v2 + v3 can lift quality within that genre without trying to beat
  Hausfather.
- **Don't optimize for cost prematurely.** User said "do it right
  for now" with the Sonnet evaluator. The kill switch
  (`EVALUATOR_ENABLED=false`) exists if circumstances change.

---

## 6. How to use this doc

- Read before any voice / architecture decision.
- Update tier placements when reality shifts (a Tier-3 lever might
  jump to Tier 1 if a specific failure mode emerges).
- When a Tier intervention ships, mark it **SHIPPED YYYY-MM-DD**
  inline (see 2.1 and 2.2 above for format) and note the commit. Build
  the cause-and-effect record so future plan revisions can read what
  worked and what didn't.
- Cost figures should be re-verified against console.anthropic.com
  whenever a model is swapped or volume changes meaningfully.
