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

*Anything else gets parked here when it's worth remembering but not worth
building now. Keep entries tight — problem, why not now, what would change.*
