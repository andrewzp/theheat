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

*Anything else gets parked here when it's worth remembering but not worth
building now. Keep entries tight — problem, why not now, what would change.*
