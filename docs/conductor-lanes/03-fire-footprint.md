# Lane 3 — Fire Footprint / Acreage (GWIS)

## Mission

Upgrade our wildfire detection from "point detections" (NASA FIRMS — is
there a fire burning at lat/lon?) to "footprint detections" (GWIS — how
many hectares has this specific fire complex burned over its lifetime?).
Fire size is the viral story; current FIRMS output gives us the detection
moment but not the scale.

## Why this matters

Viral wildfire tweets are about **acreage**: "The Camp Fire burned 153K
acres in 17 days," "This year's Siberian fires have burned an area
larger than [country]." Our FIRMS integration tweets individual MW
readings ("a 1200 MW fire in Siberia"), which is a proxy for intensity
but not size. Readers grasp acres/hectares instantly. They do not grasp
MW.

This lane adds a higher-order signal: "Fire X has burned N hectares,
which is Y% of [relatable area]."

## Data source — GWIS

- **Product:** EFFIS GWIS (Global Wildfire Information System) — Active
  Fires Viewer, burn-area statistics, perimeter/polygon exports
- **Access:** https://gwis.jrc.ec.europa.eu/ — largely free; check for
  API tokens, rate limits, and terms before large-scale pulls
- **Outputs to consider:**
  - **Monthly burned-area statistics** (by country, by month) — clean
    totals, good for "[country] has had its largest wildfire year on
    record"
  - **Active fire polygons** — actual perimeters, good for computing
    per-fire acreage when a single fire complex is the story
  - **Historical record (1985–present)** for baseline comparisons

Alternative source if GWIS is painful to integrate:
- **EFFIS** (European Forest Fire Information System) for EU coverage
- **NIFC** (National Interagency Fire Center, US) for US large-fire
  incidents with daily acreage updates

## Editorial bar

- Only tweet fires ≥ **threshold acreage** (propose 50,000 acres / 20K
  hectares as MVP floor; tune after observation).
- **Or** tweet annual-basis cumulative milestones per country when a
  country exceeds its prior-year-on-this-date total by a meaningful
  margin (e.g., YTD burn area > 95th percentile of the 1985–present
  historical record for this day-of-year).
- Dedup per fire complex: once we've tweeted "fire X at 60K acres," we
  don't tweet again until it crosses a meaningful next threshold
  (e.g., doubled, or reached 100K acres). GDACS intensity-tier pattern
  applies — see `src/data/gdacs.py` for reference.
- Honest framing: "the largest N-hectare single-fire complex of 2026"
  not "the largest ever." Archive window (1985–present for GWIS =
  ~41 years) stated explicitly when relevant.

## Scope

1. **New data module:** `src/data/fire_footprint.py`
   - Dataclasses: `FireComplex(name, country, region, hectares, start,
     event_id, tier)`, `CountryYtdBurnArea(country, hectares_ytd,
     historical_pct, event_id)`.
   - `fetch_active_fire_perimeters()` — returns major active fire
     complexes with cumulative acreage.
   - `detect_large_fire_complex_threshold_crossing(complexes, state)` —
     emits when a fire complex crosses a new size tier.
   - `detect_country_ytd_record(stats, state)` — emits when country YTD
     exceeds historical percentile.
2. **State additions:**
   - `fire_complex_tiers: {complex_id: last_tier_notified}` — prevents
     re-tweeting the same fire at every update.
   - Optional: `country_ytd_burn: {country: hectares}` for trend detect.
3. **Scoring:** `score_fire_footprint` in `src/editorial/scoring.py`.
   Threshold 72. Out-of-season multiplier (inherits pattern from
   existing `score_fire_event`).
4. **Template:** `fire_footprint_template` in `src/voice/templates.py`.
5. **Generator:** `generate_fire_footprint_tweet` in `src/voice/generator.py`.
6. **Approval policy:** `src/editorial/approval.py` — `manual_only` per
   existing fire policy. Fires have human-impact risk; keep humans in
   the loop.
7. **Category hint.**
8. **Main orchestrator:** New section alongside existing `firms`. Fetch
   is likely once per day, not every 4 hours — gate accordingly
   (analogous to drought's Fridays-only pattern).
9. **Tests:** fetch, detection (including tier-dedup), scoring,
   run_alerts integration.

## Key voice rules

- Lead with acreage, concrete scale. "The Dixie Complex has burned
  213,000 hectares. That's larger than [X]."
- Avoid "ravaging," "destroying," "raging" — meta-commentary banned
  elsewhere should also be banned here. Let the number do the work.
- When a fire complex has a name (Dixie, Camp, Black Summer), use it.
  Easier for readers to mentally index.

## Definition of Done

- [ ] Fetch works on a real GWIS endpoint. Document the endpoint URL
      and any auth in BRIEFING's Secrets section.
- [ ] Tier dedup prevents re-tweeting the same fire complex at every
      update.
- [ ] Country-YTD detector (if implemented) fires only on genuine
      percentile-crossing signals, not small deltas.
- [ ] Full suite green.
- [ ] Pipeline diagram and scoring table updated.

## Non-goals

- **Don't** tweet every new active fire. FIRMS already handles
  detection; this lane is about scale-crossing.
- **Don't** try to compute burn areas from FIRMS point detections
  yourself. Many academic papers have tried; GWIS does it properly.
  Use their product.
- **Don't** merge this with the FIRMS integration. Two distinct
  signals: detection (FIRMS) vs. footprint (GWIS). Different stories.

## Budget expectations

- ~6–10 hours. GWIS endpoint mapping may eat 1–2 hours.
- If EFFIS/NIFC fallback is needed (GWIS access proves painful),
  expect +3 hours.
