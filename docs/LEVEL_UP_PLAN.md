# Level-Up Plan — April 24, 2026

> **Annotated 2026-04-24:** the original Tier 1 ranking below put
> "post-publish analytics loop" first. **That was wrong** — user
> correctly pointed out we have ~1 posted tweet ever, so analytics
> would be measuring noise. Quality-side work IS the Tier 1. Read the
> tiers below with this correction in mind: era-anchor database and
> historical-corpus regenerate-and-compare are the actual Tier 1.
> Analytics is Tier 2 once posting volume is non-trivial.
>
> Also: cost figures throughout this doc were written against the stale
> "$60-90/mo" BRIEFING figure. Real spend is $25-45/mo on Sonnet 4.6
> evaluator (verified 2026-04-24). All "Opus would be too expensive"
> framing is wrong — Opus 4.7 evaluator at our volume would be ~$50/mo.
> User chose to keep Sonnet 4.6 anyway ("do it right for now").
>
> Also: @extremetemps observation from session — our voice spec is
> over-engineered for breakout-viral aspiration when the actual
> successful account in our genre uses ALL CAPS openers, multi-station
> roll-calls, and editorial heat. Voice engine v2 partly addresses;
> deeper rethink may be warranted.

Written after: four-lane merge, Codex cleanup, fire geocoder upgrade,
FRP floor raise, and voice engine v2 (per-category prompts + stock-
formula rejector).

Purpose: surface the next tier of improvements honestly — including
model swaps — and give a recommended sequence. Not execution. Start by
reading `docs/DRAFT_CORPUS.md` (what's actually shipping) and
`docs/VOICE_FAILURE_ANALYSIS.md` (why).

---

## 1. Where the ceiling actually is right now

**Floor-raising work from this session was real but mechanical.** The
stock-formula rejector, per-category prompts, and geocoder fix all
attack specific production failures observed in the corpus. They
remove the worst drafts from the feed.

**They do NOT produce *better* drafts than we've already seen.** The
A/B-grade tweets in the 2026-04-24 corpus (Sevilla, Chicago,
Jacobabad, Kathmandu, Ipoh, Medan, Hawaii) are the ceiling of what the
current architecture can produce. Three factors set that ceiling:

1. **Single-model candidate generation.** Gemini 2.5 Flash is what it
   is. The evaluator rewrites when it fails, but the candidate pool
   is one model's voice with one set of training biases.
2. **No feedback loop.** We have zero data on which tweets actually
   performed on X. Tweets post, then we stop watching. There's no
   eval signal being fed back into anything.
3. **No historical-anchor database.** Era anchors ("the year the euro
   entered circulation") are invented per-draft by Gemini. When it
   works, it's lucky. When it fails, it produces stock anchors
   ("it's been a while"). Reliable anchors need to be pre-computed
   and injected.

Every intervention below targets one of these three.

---

## 2. Intervention menu

### Tier 1 — Highest leverage (do these first)

#### 2.1 Post-publish analytics loop

**The biggest blind spot.** We post tweets, we don't measure. No
feedback, no learning signal.

**What:** After a draft posts, wait 24–72 hours, then pull X metrics
(impressions, likes, retweets, bookmarks, replies) via the X API.
Store per-draft in state as an `engagement` dict. Build a simple
report: our top-20 performers across the last 30 days, bottom-20,
plus median by signal type.

**Why it unlocks everything else:**
- Changes the evaluator from "does this read viral?" to "does this
  pattern *actually* get shared?"
- Gives us a real A/B surface for future prompt iterations
- Surfaces which signal types genuinely perform (marine heatwave
  might be a sleeper; fires might underperform despite good copy)
- Builds the @theheat-specific viral set promised in
  `brand/EXEMPLARS.md` ("When a tweet earns 9+ it gets promoted to
  Tier 4"). Right now Tier 4 is empty.

**Scope:** ~4–6 hours. New module `src/posting/metrics.py`. New state
field `engagement_metrics`. New cron mode `metrics_refresh` running
once daily. New dashboard section showing top/bottom performers.

**Cost:** $0 — X API free tier allows metrics reads.

**Un-park signal:** it's unblocking every subsequent decision.

---

#### 2.2 Era-anchor database

**What:** Pre-compute a lookup of human-recognizable events keyed by
year. When a record was set in year Y, the generator is handed *that
year's* cultural anchor as part of the prompt data, rather than
asking Gemini to invent one.

Example schema:
```json
{
  "1998": [
    "Google was founded that year",
    "Titanic was the highest-grossing film",
    "the euro was about to launch",
    "Apple had just released the first iMac"
  ],
  "2002": [
    "the euro entered circulation",
    "the Winter Olympics were in Salt Lake City",
    "Yahoo was still the default search engine"
  ]
}
```

Prompt addition: "The previous record was set in 2002. Here are
era-appropriate anchors you may use (pick one or write your own):
[anchors]."

**Why it helps:**
- Eliminates hallucinated anchors. Gemini sometimes gets an anchor
  wrong (wrong year, wrong detail). A curated set is factual.
- Produces variety. Gemini currently defaults to the same ~5 anchors
  across similar years. A bank of 8+ anchors per year rotates.
- Covers the honest framing window. The Open-Meteo archive is ~30
  years, so we need 1995–2025. GRACE is 2002+, OISST is 1982+ —
  cover those windows well.

**Scope:** ~6–8 hours. One-shot offline generation (ChatGPT or Claude
prompted with "list era-specific cultural anchors for 1995-2025, 8+
per year"), manual review for factual accuracy, commit as a JSON
file, plumb into the record / all-time / monthly generators.

**Cost:** $0 after the one-time generation.

---

### Tier 2 — Model swaps (real but consider timing)

#### 2.3 Generator model swap: Gemini 2.5 Flash → Claude Sonnet 4.6 (or Haiku 4.7)

**Context:** current architecture = "Gemini generates 4 candidates,
Sonnet evaluates + rewrites." Could collapse to "Sonnet does both."

**Arguments for:**
- Sonnet's voice is measurably better for this style (short, deadpan,
  punchy) — it's already doing the rewrites we ship.
- One model, one voice, fewer seams.
- Prompt caching on Sonnet would cap cost growth.

**Arguments against:**
- Cost: Sonnet generator would bring us from ~$60–90/mo to probably
  $200–400/mo at current cycle volume. Not trivial on a "utility, not
  business" project.
- Gemini 2.5 Flash is genuinely fast. Sonnet is slower per call; alert
  cycles grow from ~30 min to 45+.
- Loss of 4-candidate diversity. Sonnet tends to converge; Gemini
  diverges more. We lose the "pick the best of 4" selection lever.

**Cheaper alternative: Claude Haiku 4.7 as generator.** Haiku
specifically targets the cost+latency envelope Flash occupies.
Anthropic's small-model voice is typically sharper than Google's.
Likely $80–120/mo at our volume. Worth testing before the Sonnet
jump.

**Best path:** A/B in production for 2 weeks. Generate with both
Gemini AND Haiku for the same events; feed both into the evaluator;
track which sources the winning rewrite more often; measure
engagement difference (requires Tier 1 analytics loop to be in
place).

**Scope:** ~4 hours once analytics is in place. Mostly a config flag.

#### 2.4 Evaluator model upgrade: Sonnet 4.6 → Sonnet 4.7 or Opus 4.7

**Sonnet 4.7:** incremental. ~30% better reasoning per the published
evals. Probably lands as a quiet win. **Swap whenever, trivial.**

**Opus 4.7:** substantially more capable. Evaluator role benefits
because it has to balance 5 dimensions under one rubric. But Opus
is ~5x the cost per token. At our volume — probably 50-100 evaluator
calls per day — that's ~$300–500/mo for evaluator alone.

**Verdict:** Sonnet 4.7 now. Opus only if the 2.1 analytics loop
shows evaluator verdicts diverge from actual engagement.

#### 2.5 Consider DeepSeek / Qwen / open-weights alternatives

**Context:** strong reasoning models from the open side (DeepSeek R1,
Qwen 3, Llama 4) are essentially free if run on commodity inference
providers (Fireworks, Together, Groq).

**Honest take:** these models are strong at reasoning benchmarks but
their voice for short-form English copy is not yet proven. @theheat
is a voice-first product. Swapping a voice-trained model for a
reasoning-trained one is probably a net loss.

**Exception:** the safety LLM check (currently Gemini) could be any
strong open-weights model cheaply. Low quality bar — it's a binary
"does this mock suffering?" check. **Worth routing to Groq+Llama 4
for cost if Gemini ever becomes a dependency problem. Not urgent.**

---

### Tier 3 — Content/distribution levers

#### 2.6 Visual cards

From `brand/VOICE.md` and user feedback: "revisit once fact quality
proves out." Data quality *is* proving out — 7 A/B tweets per 35
drafts is a real baseline.

**What:** Generate a house-style card for each posted tweet. Text +
location + one chart element. Post as image tweet instead of text-only.

**Research anchor:** images documented at 28× engagement for climate
content (`brand/VIRALITY_RESEARCH.md`).

**Scope:** ~1-2 weeks. New `dashboard/` page for card preview, new
`src/visual/cards.py` renderer (Pillow or matplotlib), pipeline
integration.

**Cost:** minimal if using matplotlib + static templates. $0
recurring.

**Un-park signal:** one genuinely-strong draft lands but gets low
engagement; we want to test if image tweets convert better.

#### 2.7 RSS / news-collision enrichment

From `brand/EXEMPLARS.md`: the consistent viral-climate pattern is
**climate × non-climate news collision**. Thunberg × Tate. LA fires ×
everyone's phone. Hausfather × actual scientist cursing. Pure climate
almost never goes breakout-viral.

**What:** Add Carbon Brief / Reuters / AP climate-adjacent feeds.
When a climate event we detect co-occurs with a top-news-cycle story,
surface the fusion in the generator prompt. "LA in record drought AND
the Oscars are tomorrow AND the fire is 3 miles from the Dolby
Theatre" is a viral setup the current pipeline can't produce.

**Scope:** ~1 week. New `src/data/news.py` with RSS feed parsing, a
"news context" section added to synthesis rules.

**Risk:** news-collision tweets edge toward editorialization. Needs
tight rules to stay on the "utility, not business" side.

#### 2.8 Timing optimization

X algo rewards first-30–60-min engagement. We post whenever the cron
produces a draft. Data-heavy posts (records, Hot 10) could be timed
to peak US/EU overlap (~15:00 UTC). Takes ~30 min of config work in
`approval.py`.

**Scope:** trivial once analytics proves it matters.

---

### Tier 4 — Rebuilds / big swings

#### 2.9 Engagement-fed evaluator

After Tier 1 analytics loop runs for 30 days: we have hundreds of
tweets with engagement data. Train a small classifier (logistic
regression on tweet features → engagement bucket) and use it as
a *third* pre-publish filter alongside the Sonnet evaluator.

**Scope:** ~2-3 weeks, much of it waiting for data to accumulate.

#### 2.10 Ensemble generation (expensive but powerful)

Generate with Gemini AND Sonnet AND a third provider. Feed all
candidates into the evaluator. Ship the overall winner. Cost
multiplies but diversity of voice probably produces breakout tweets
we can't currently get.

**Gate:** only justifiable if Tier 1 analytics shows the current
ceiling is genuinely capped by candidate pool diversity.

#### 2.11 Human-in-the-loop for viral candidates

From `brand/EXEMPLARS.md`: breakout viral (Thunberg, Hausfather)
requires human-shaped moments. Pure automation is a known ceiling.
Could add an opt-in "human polish" flow where exceptional drafts
(signal ≥ 85, copy ≥ 92, or synthesis signals) ping a user for
15-minute polish before auto-post.

**Conflict:** directly violates the set-and-forget invariant. User
has rejected this twice in prior sessions. **Listed for
completeness, not recommended.**

---

## 3. Recommended sequence

1. **Tier 1.1 — Analytics loop.** No other intervention is fairly
   measurable without this. 4–6 hours of work for a foundation every
   other decision rests on.
2. **Let it run for 2 weeks.** Accumulate engagement data across 50+
   shipped tweets under voice engine v2. Build a real @theheat
   ceiling baseline.
3. **Tier 1.2 — Era-anchor database.** Independent of analytics but
   a reliable quality lift across every record-type draft. Do in
   parallel with step 2 waiting period.
4. **Evaluate Tier 2 swaps with real data.** Sonnet 4.7 evaluator
   swap (trivial, do it). Haiku 4.7 generator A/B (needs analytics).
5. **Only then consider Tier 3.** Visuals or RSS depending on what
   the analytics reveal as the ceiling.

**Deliberately NOT in the first pass:**
- Opus 4.7 evaluator (wait for data to justify the cost)
- Ensemble generation (premature)
- Human-in-the-loop (set-and-forget invariant)
- Open-weights experimentation (voice bar too high)

---

## 4. Model landscape quick reference (as of April 2026)

| Model | Role fit | $/mo at our volume | Notes |
|---|---|---|---|
| **Gemini 2.5 Flash** | Generator (current) | $0 (free tier) | Fast, diverges well, voice is mid. Our baseline. |
| **Gemini 3.0 Pro** | ? | Unclear pricing | If available; check Google AI Studio. Higher-quality than Flash, probably slower. |
| **Claude Haiku 4.7** | Generator candidate | ~$80-120 | Small-model voice typically sharper than Gemini. A/B test candidate. |
| **Claude Sonnet 4.6** | Evaluator (current) | ~$60-90 | Good. Works. Used to rewrite. |
| **Claude Sonnet 4.7** | Evaluator upgrade | ~$60-90 | Likely incremental quality win. Trivial swap. |
| **Claude Opus 4.7** | Evaluator upgrade | ~$300-500 | Strong but expensive. Needs analytics justification. |
| **GPT-5** | Unclear | Unclear | OpenAI's latest. Claude generally wins on voice; doesn't seem worth the swap unless something specific emerges. |
| **DeepSeek R1 / Qwen 3 / Llama 4** | Safety LLM only | ~$0-20 | Cheap reasoning. Voice bar too high for generator or evaluator. Route the binary safety check here if Gemini ever flakes. |

**Pricing caveat:** I'm extrapolating from what I know of the April
2026 model landscape. Actual prices may differ; verify in each
provider's current docs before committing. The *direction* of the
recommendations (Sonnet 4.7 ≈ Sonnet 4.6 cost, Opus ~5x, Haiku ≈
Flash, open-weights cheap for safety) holds regardless of exact
numbers.

---

## 5. What NOT to do (kept honestly)

- **Don't swap the generator without analytics first.** We'd be
  trading an unknown for an unknown.
- **Don't add ensemble generation yet.** Premature optimization; the
  candidate-pool diversity isn't proven to be the ceiling.
- **Don't reintroduce human-in-the-loop.** The set-and-forget
  invariant is a feature, not a limitation. Preserved across every
  session since April 18.
- **Don't broaden detection further.** The signal side is already
  rich (14 sources, 613 cities, 4 derived synthesis lanes). The
  bottleneck is not data — it's voice quality and distribution.
- **Don't chase breakout viral.** `brand/EXEMPLARS.md` is right:
  automation ceilings out at "data-ticker excellence" (the
  @extremetemps model). Voice engine v2 can still lift that ceiling
  within its genre without trying to beat Hausfather.

---

## 6. How to use this doc

- Read before any voice / architecture decision.
- Update tier placements when reality shifts (a tier-3 lever might
  jump to tier-1 if a specific failure mode emerges).
- When a Tier intervention ships, note which actual corpus
  observation or engagement data triggered it — build the
  cause-and-effect record for future plan revisions.
