# Ideas Parking Lot

Non-urgent ideas we've explicitly decided *not* to build yet. Each entry should
capture what the idea is, why it's parked, and the smallest signal that would
un-park it.

---

## Geographic spread as per-cycle tiebreaker

**What:** When the per-cycle cap (currently `MAX_DRAFTS_PER_CYCLE = 3`)
selects top drafts by signal score, add a continent/region tiebreaker so
three signals from the same region lose to a mix spanning multiple regions
when scores are within some threshold.

**Why parked (April 2026):** We shipped same-city-same-day dedup and a 3-day
per-city cooldown first. Those solve the visible problem (one heatwave
monopolizing the feed). Per-cycle geographic balancing is a second-order
polish — the per-cycle cap only fires on the three highest-signal events in a
given 4-hour window, and clustering is more of a cross-cycle problem than a
single-cycle one. The cooldown already spreads the feed across days.

**Un-park signal:**
- We see a cycle produce 3 high-signal drafts from the same continent
  (e.g., three Southeast Asian cities) and the feed feels regional on that day.
- OR the cooldown starts causing too many rejections and we want a different
  diversity lever instead.

**Sketch of implementation:**
- Add `continent` or `region` field to the city CSV (or infer from lat/lon).
- In the per-cycle selection (`run_alerts` end-of-cycle pruning), when two
  candidates are within N points of each other on signal score, prefer the
  one from an underrepresented region in the current batch.
- Configurable N (proposed default: 8 points).

---

## Voice engine upgrade

**What:** Rewrite the Gemini system prompt or tighten the Sonnet
evaluator so automated drafts clear a higher voice bar, not just a
factual/safety bar. Current output is "data-ticker competent" — honest,
accurate, structurally clean, but not scroll-stopping.

**Why parked (April 2026):** User reviewed drafts after the 4-lane
merge and said *"they are ok. neither is going to go viral by any
stretch."* That's a real observation. `brand/EXEMPLARS.md` is honest
that breakout viral (Thunberg, Hausfather, Kalmus) requires
human-shaped moments automation can't reliably produce. But the
pipeline's floor quality can still move up without chasing breakout —
the lift is real, just not infinite.

**Candidate interventions (pick one to start):**

1. **"Lead with the stake" rewrite pass.** Add a pre-evaluator stage
   that reorders tweets so the first 5–7 words carry the surprise/
   stake, not the place-and-number. Example: "Cotonou forecast 92.7F.
   If it holds, this is the hottest April in 30 years. The old record
   was from LAST YEAR" → "Cotonou's 30-year April record lasted 12
   months before it fell again."
2. **Tighter evaluator threshold.** Current Sonnet evaluator passes
   at 7+ on 4 of 5 dimensions. Raise to 8+ on 4 of 5, or require 9+
   on at least one dimension. Trade-off: more drafts die, feed thins.
3. **Generator prompt rewrite** with explicit "first 5–7 words" rule,
   historical-human anchor requirement, and pattern-avoidance list
   ("enough to power N homes", "location unknown", etc.).
4. **Per-signal-type prompts.** Currently one system prompt for all
   signal types. Per-type prompts could encode "marine heatwave tweets
   should anchor to X," "fire tweets should lead with named complex
   or ecosystem scale," etc.

**Un-park signal:** User wants to lift the floor on routine drafts.

---

## Fire reverse-geocoder regional precision

**What:** Replace `src/data/firms.py::reverse_geocode_simple` (and
`_lat_lon_to_country`) with something that resolves fire coordinates
to specific regions/countries rather than continent-level buckets.

**Why parked (April 2026):** Observed in production after the FIRMS
letter-confidence fix unblocked the source. Drafts started including
"somewhere in Asia" / "location unknown" / bare continent labels —
which the Gemini generator faithfully incorporates into tweet copy.
These drafts are weak because the location is the story, and the
location is abstract.

**Candidate implementations:**

1. **Bounding boxes per country/region** — static dict, ~200 entries,
   offline, no deps. Mirrors the `_lat_lon_to_region` function we
   already have but granular. Same pattern Lane 4 used for US states.
2. **Bundled country polygons (shapely)** — accurate point-in-polygon,
   adds shapely + ~500KB data file. Higher fidelity, bigger lift.
3. **Reverse-geocoding API** — network dependency, rate limits, fails
   closed on outage. Probably not worth it for this use case.

**Un-park signal:** The next time fire drafts start showing up in
review and "somewhere in Asia" is the reason we reject any of them.

---

## Grok 4 as a candidate-generator A/B

**What:** Wire xAI's Grok 4 alongside the existing Gemini path so we
can A/B the same data descriptions through both models for a week and
compare voice quality side-by-side.

**Why it's worth a real test (and not a drop-in replacement of other
models):** Grok is the one frontier LLM explicitly trained on
Twitter/X data — the platform we publish to. Every other model
(Gemini, Claude, GPT, Llama, Qwen) trains on a generic web corpus.
Grok's training distribution natively matches @theheat's distribution
target. If voice is the limiter, the X-native model is the obvious
experiment we haven't tried.

**Scope when we do it:**
- New `src/voice/grok_generator.py` paralleling the Gemini path,
  using xAI's API client. xAI exposes a Claude-like REST API.
- Run BOTH generators on the same `data_description` for ~1 week.
  Save both outputs into the draft as `candidates_gemini` and
  `candidates_grok`. Don't ship — just observe.
- Manual review: for each event, which model's top candidate would I
  ship? Grade across ~50 events.
- If Grok wins by margin: switch generator to Grok, keep Sonnet
  evaluator. If Gemini wins: kill the experiment, save the wiring.

**Why parked (April 2026):** We just upgraded Gemini 2.5 Flash to the
`gemini-flash-latest` alias (currently `gemini-3-flash-preview`).
Voice engine v2 prompt + geocoder fix + FRP floor + stock-formula
rejector all just shipped. Want to see what the current stack
produces in the wild before swapping a major component. The next
draft corpus (next session) will tell us whether the work-in-flight
moved the needle. If yes, Grok experiment is lower priority. If no,
Grok experiment moves to Tier 1.

**Un-park signal:** Next session's draft corpus shows the same
template fatigue and bland voice as 2026-04-24's, despite all the
v2 work shipped today.

---

## Fine-tune a small open-weights model on the @theheat corpus

**What:** LoRA fine-tune of a small open-weights model (Gemma 4 9B,
Qwen 3.5 7B, or Llama 4 8B) on a curated 200-example training set
drawn from the @extremetemps corpus, `brand/EXEMPLARS.md`, our 7
A/B-grade drafts, and the rejected drafts as negative examples.

**Why parked:** Real work — ~1 week of training-data curation +
model selection + LoRA training + hosted inference setup. Nontrivial
~$100-300 compute spend for the one-shot fine-tune. Worth doing
ONLY if neither (a) the current voice engine v2 stack on
`gemini-flash-latest` nor (b) a Grok A/B move the voice quality
needle.

**The differentiator:** every other climate Twitter account uses
general-purpose frontier models. Nobody fine-tunes for the
data-ticker climate voice specifically. We have the corpus to do it
and would be first.

**Un-park signal:** Both prior interventions (current stack;
Grok A/B) ship and the voice still feels mid.

---

## NVIDIA NIM as the dev-only A/B harness for generator candidates

**What:** NVIDIA hosts ~80 open-weights models behind one OpenAI-compatible
endpoint at `integrate.api.nvidia.com/v1` — Llama 4, Qwen 3, DeepSeek 3.2,
GPT-OSS-120B, Kimi 2.5, GLM 5.1, MiniMax M2.7, Mistral variants. One API
key, one base URL, model swaps via the `model` parameter. Free tier is
40 requests/minute with 1,000 starter credits (expandable to 5,000 on
request).

**Why this is interesting (and what it's NOT):** NVIDIA explicitly
positions this as **trial / prototyping / evaluation** infrastructure.
For production use, expended credits → pay-as-you-go pricing kicks in.
At @theheat's volume (6 cycles/day × ~25-50 LLM calls per cycle on busy
days), the free tier would burn out in days. **This is not a Gemini Flash
production replacement.** Anyone framing it as "free inference for
production" is selling hype.

But it IS useful — specifically as the **A/B testing harness** for the
two parked model-swap lanes above:

1. The Grok-vs-Gemini A/B already lives here (above). NVIDIA NIM lets
   us also throw Llama 4, Qwen 3, DeepSeek into the same A/B during
   *development* — same `data_description`, same prompt, observe voice
   quality side-by-side. Pure dev-time use, fits the trial terms cleanly.
2. The fine-tune lane (above) needs us to first know which base model
   has the strongest starting voice on our prompts before committing
   $100-300 compute to a LoRA. NVIDIA NIM is the cheapest way to test
   8+ candidate base models without standing up local GPU inference.

**Why parked (April 2026):** Voice engine v2.5 just shipped (era anchors,
multi-station roll-call, recalibrated rules, opener-formula ban). The
next draft corpus is the verdict. If v2.5 lifts quality enough, the A/B
becomes lower-priority. Also: tiny risk of getting drawn into the hype —
"free inference!" tweets are everywhere, and the trial-tier nature is
under-acknowledged.

**Un-park signal:** EITHER of the two lanes above un-parks (corpus shows
voice ceiling on current stack), and we're ready to compare candidates
before committing engineering time. NVIDIA NIM is then the harness — not
the destination.

**Concrete first step when un-parked:**
- Add `src/voice/nvidia_generator.py` paralleling the Gemini path
- Run all candidate models against ~10 representative `data_description`s
  pulled from `docs/DRAFT_CORPUS.md`
- Manual grade outputs against the same A-F rubric
- Pick winner; either ship A/B in production (hitting paid tier) or
  proceed to fine-tune the chosen base

---

---

# ⭐ Requested — wanted, NOT parked

> Added 2026-06-29 at the user's explicit request ("we need that"), after @theheat
> missed two major deadly events in real time: the European heatwave (1,300+ excess
> deaths per WHO; ~1,000 in France) and the Western US wildfire outbreak (3 firefighters
> — Sydney Watson, Nick Hutcherson, Emily Barker — killed on the Knowles/Gore fires at
> the CO–UT border; 100+ new fires in 72h; national Preparedness Level 4). Smoking gun:
> the bot POSTED "1,468 MW in the Congo Basin, DR Congo" while SUPPRESSING the Colorado
> fires (scored 62 < the 64 cutoff) the same evening. Root cause: editorial selection
> ranks by raw sensor MAGNITUDE and is blind to newsworthiness + human stakes. These two
> items fix that. They are priorities, not parking-lot ideas. The two share one grounded
> retrieval + citation + verify-against-source core — build it once.

## Weather-news scanner — "are we missing an obvious event?"

**What:** A recurring job that scans weather/climate news for the biggest current events
(heat death tolls, multi-state fire outbreaks, record landfalls…) and cross-checks them
against what @theheat has actually detected/posted — then flags any "obvious event we're
missing." A miss-detector / newsworthiness safety net.

**Why needed:** The bot is structurally blind to newsworthiness — it suppressed the
front-page Colorado fire (62<64) and posted a remote Congo Basin megawatt reading the
same evening, and has no path to the 1,300 European heat deaths. Magnitude ≠ newsworthy.

**Acceptance (working when):**
- On a day with a major, widely-reported climate event, the scanner surfaces it
  (dashboard banner and/or a GitHub issue) within a cycle or two, with the source.
- It cross-references recent shipped tweets + detected signals, so it flags only
  GENUINE gaps, not events already covered.
- v2: the gap signal BOOSTS the matching internal signal's score (so the Colorado fire
  clears the cutoff because the world says it matters), not just alerts.

**Sketch:**
- New lane `src/data/news_scan.py` / `src/editorial/newsworthiness.py`: query a
  weather-news source → structured {event, where, when, magnitude/impact, source_url, as_of}.
- Source of truth (decide first; same infra as the anecdotes entry): grounded search
  (Gemini google_search grounding, already in-stack — broad but noisy) vs authoritative
  feeds (NIFC fire, WHO/Santé publique France, NWS/NHC — clean but narrow). Likely both:
  feeds for the big verticals + grounded search for the long tail.
- Gap check: fuzzy-match scanned events vs `state.shipped_tweets` + the cycle's detected
  signals (place + category + window); unmatched high-impact event → flag.
- Surface via the existing auto-open/close source-health issue + dashboard machinery
  (reuse it). Hourly / per-cycle.
- Guard: never auto-POST from the scanner; it informs selection + alerts. Any text still
  goes through writer → fact-check → critic → human gate.

## Sourced anecdotes / human-impact with citations

**What:** Let tweets carry real human-impact detail — death tolls, firefighter
fatalities, "buses crashed, drivers passed out" — attached to a climate signal, each
fact carrying a citation. So a France heat tweet can say "≥1,300 excess deaths across
Europe, per WHO," and a Western-fire tweet can name the firefighters killed.

**THE IRON CONSTRAINT:** every anecdote/impact figure MUST come from real, cited
retrieval (grounded search / a named source), NEVER the model's imagination. Current news
is past the writer model's knowledge cutoff, so an invented death toll is the one
unforgivable error — far worse than a boring tweet. Citation + verify-against-source +
human gate are non-negotiable.

**Acceptance (working when):**
- For a qualifying event the writer can cite a sourced impact fact WITH attribution
  ("per WHO," "reported by NIFC"); the fact-checker verifies it against the attached
  source and KILLS any impact claim with no source attached.
- Hand-sourced proof-of-target tweets already drafted this session (heat deaths;
  Knowles/Gore firefighter deaths) — the build automates producing those.

**Sketch:**
- Add optional `human_impact: [{claim, value, source_name, url, as_of}]` to StoryBundle,
  populated by the same grounded-retrieval lane as the scanner.
- Writer prompt: a section permitting impact citation ONLY from `bundle.human_impact`,
  ONLY with attribution, never self-supplied; past-tense + as_of honesty like reganom.
- Fact-check: a rule that an impact claim must match a `human_impact` entry and verify
  against its source (fetch + compare); deterministic gate requires source+as_of; no
  source → kill.
- Editorial: life-safety-adjacent (like cyclones) — keep the human dashboard gate as the
  final backstop; no alarmism, state the sourced figure plainly.

---

*Anything else gets parked here when it's worth remembering but not worth
building now. Keep entries tight — problem, why not now, what would change.*
