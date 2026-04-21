# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0.0] - 2026-04-21

### Added

- **Fire footprint pipeline (Lane 3)** — the bot now tracks cumulative wildfire burn
  area and drafts a tweet each time a named or unnamed fire complex crosses one of
  six hectare thresholds: 20k, 50k, 100k, 250k, 500k, and 1M ha. Tier crossings are
  deduped by complex ID so a fire that grows through multiple tiers over days emits
  one tweet per threshold, not one per cron run.
- `src/data/fire_footprint.py` — fetches active fire perimeters from the NIFC WFIGS
  ArcGIS Feature Service (open API, no auth). Converts acres to hectares, filters
  child incident rows (`IsCpxChild`), orders by largest fires first, and warns when
  the 2,000-row result cap is hit.
- `detect_tier_crossings` — compares current burn area against stored tier state and
  returns only complexes that have crossed a new (higher) tier since the last run.
- `score_fire_footprint` — editorial scoring with named-complex and shoulder-season
  novelty multipliers; threshold 72, `manual_only` approval policy.
- `fire_footprint_template` / `generate_fire_footprint_tweet` — acreage-first tweet
  framing with named and unnamed fire complex variants and NIFC attribution.
- `fire_complex_tiers` and `fire_footprint_last_run` state keys with max-merge
  semantics to guard against concurrent cron writes.
- 59 new tests across `test_fire_footprint.py`, `test_state.py`, `test_editorial_scoring.py`,
  `test_editorial_approval.py`, `test_editorial_candidates.py`, `test_generator.py`,
  and `test_main.py` (370 total, all passing).

### Changed

- `src/main.py` — `run_alerts` inserts fire footprint as section 2b (between FIRMS
  and CO2). Each tier-crossing iteration runs in its own `try/except` so a transient
  Gemini error on one complex does not abort the remaining crossings for the day.
- `src/state.py` — `DEFAULT_STATE` extended with `fire_complex_tiers` and
  `fire_footprint_last_run`; `_merge_state` handles both with max semantics.
- `src/editorial/scoring.py` — off-by-one `reasons[:3]` slice removed from
  `_build_score`; `score_fire_footprint` added.
- `BRIEFING.md` / `PIPELINE.md` — pipeline diagram, scoring table, and NIFC source
  documentation updated to reflect the new lane.
- Data source pivoted from GWIS (no JSON API) to NIFC WFIGS ArcGIS Feature Service.
