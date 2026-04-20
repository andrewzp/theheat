# Lane 2 — Ice Events (Glaciers & Ice Mass)

## Mission

Detect and tweet extreme ice-loss events beyond sea ice (which we already
track). Two candidate sources: **GLIMS** (Global Land Ice Measurements
from Space, glaciers) and **NASA GRACE-FO** (Gravity Recovery mission
— measures ice mass loss for Greenland, Antarctica, and major glacier
systems). Fire signals when ice mass or glacier-area loss crosses
genuinely newsworthy thresholds.

## Why this matters

We already track Arctic and Antarctic sea ice extent via NSIDC. We do
NOT track:
- Glacier retreat (GLIMS)
- Ice sheet mass balance (GRACE-FO) — Greenland + Antarctica combined
  lose ~420 Gt/year; individual monthly anomalies are the news hook
- Iconic individual glaciers (Thwaites, Pine Island, Jakobshavn, etc.)

The iconic "chart with a dramatic shape" for climate viral content is
almost always ice mass loss. Ed Hawkins' warming stripes are #1 for
climate viral imagery; Greenland cumulative mass loss from GRACE is #2.
We're missing it.

## Data sources

### GRACE-FO Mascon (preferred for MVP)

- **Product:** JPL GRACE-FO Mascon Monthly Ice Mass Anomaly
- **Access:** https://grace.jpl.nasa.gov/data/grace-month-listing/
  CSV/ASCII via https://podaac.jpl.nasa.gov (free, may need a free
  Earthdata Login account — verify before starting)
- **Update cadence:** monthly, ~1–2 month lag
- **Use:** Fire a signal on new monthly anomaly records for
  Greenland / Antarctica / Global Glaciers. e.g. "Greenland lost
  423 Gt in August 2026 — the largest monthly loss in the 24-year
  GRACE record."

### GLIMS (optional, secondary)

- **Product:** Glacier outlines and change metrics
- **Access:** https://www.glims.org/ free
- **Use:** Less frequent — major glacier retreat milestones. Likely not
  worth MVP effort; focus on GRACE-FO first.

### NSIDC IMS (optional, secondary)

- Alternative if GRACE access is painful: NSIDC's Interactive Multisensor
  Snow and Ice Mapping System or Greenland Ice Sheet Today product page
  has daily melt-extent data. Lower fidelity than GRACE but also lower
  friction.

**Start with one source.** GRACE-FO gives the most iconic "cumulative
mass loss" storylines.

## Editorial bar

- **Only tweet at clear milestones.** New monthly record, or cumulative
  threshold crossed (e.g., Greenland cumulative loss passes -5000 Gt for
  the first time).
- **Honest framing.** GRACE record starts 2002 → "largest monthly loss
  in 24 years of GRACE observations," not "ever."
- **Cap:** no more than ~8 ice-mass tweets per year. Monthly cadence of
  source + record-only threshold should make this natural, but add
  explicit cap to state (analogous to `co2_annual_count`) if needed.

## Scope

1. **New data module:** `src/data/ice_mass.py`
   - Dataclasses: `IceMassReading(region, month, mass_gt, anomaly_gt,
     event_id)`, `IceMassRecord(region, kind, new_value, old_value,
     old_year, event_id, ...)`.
   - `fetch_grace_mass(region: str)` where region is one of
     {"greenland", "antarctica", "global_glaciers"}.
   - `detect_monthly_record(readings, state)` — compare latest monthly
     anomaly to archive; emit record events.
   - `detect_cumulative_milestone(readings)` — optional second detector
     for cumulative thresholds (every −1000 Gt step, for instance).
2. **State additions:**
   - `ice_mass_max_loss: {region: {"gt": float, "month": "YYYY-MM"}}`
     — track worst monthly loss per region.
   - `ice_annual_count: {year: int}` — analogous to CO2 cap; default 8.
3. **Scoring:** `score_ice_mass_event` in `src/editorial/scoring.py`.
   Threshold 78. Elite-tier when region is Greenland or Antarctica.
4. **Template:** `ice_mass_template` in `src/voice/templates.py`.
5. **Generator:** `generate_ice_mass_tweet` in `src/voice/generator.py`.
6. **Approval policy:** `src/editorial/approval.py` — suggested_auto,
   90-120min delay.
7. **Category hint:** Add to `CATEGORY_HINTS`.
8. **Main orchestrator:** New section in `run_alerts`. Gate to run once
   per cycle but dedup within the month; data updates monthly so fetching
   every 4 hours is wasteful but harmless. Consider adding a "last fetch
   was in this month, skip" short-circuit.
9. **Tests:** detection tests, scoring tests, run_alerts integration.

## Key voice rules

- Lead with the quantity: *"Greenland lost 423 gigatons in August. The
  largest monthly loss in 24 years of GRACE observations."*
- Do not personify ice ("the ice is suffering", "the glacier is dying").
  Banned in voice.
- Concrete scale anchors help: "423 Gt = roughly the weight of X" is
  powerful IF X is instantly understandable (not 10^15 kg).

## Definition of Done

- [ ] Real endpoint probed; fetch works on live data.
- [ ] Detection handles the case where a newer month's data hasn't
      been published yet (source updates monthly, with lag).
- [ ] Tests: full suite green, including new integration test.
- [ ] `BRIEFING.md` + `PIPELINE.md` updated.
- [ ] Secrets documented if Earthdata login is required.

## Non-goals

- **Don't** pull daily melt-area data and tweet daily. That's routine.
  Monthly cadence is the right rhythm for this source.
- **Don't** add Thwaites / Pine Island individual glacier tracking.
  Interesting but requires structured long-term monitoring datasets
  we don't have. Defer.
- **Don't** conflate GRACE mass-loss numbers with sea-level-rise claims
  in the same tweet. Separate stories.

## Budget expectations

- Single source, MVP scope: ~4–6 hours.
- Earthdata login friction could eat an hour if needed.
- If both GRACE + GLIMS get shipped: ~10 hours.
