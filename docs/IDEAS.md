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

*Anything else gets parked here when it's worth remembering but not worth
building now. Keep entries tight — problem, why not now, what would change.*
