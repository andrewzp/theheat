# Lane 1 — Ocean SST & Marine Heatwaves

## Mission

Detect and tweet marine heatwave events — stretches where ocean surface
temperatures are anomalously high for that location and time of year. Add
NOAA OISST (Optimum Interpolation Sea Surface Temperature) as a new data
source. Fire events when the signal is genuinely extreme, not routine
warmth.

## Why this matters

We currently track atmospheric extremes on land (257→613 cities) and
ocean wave heights, but we completely miss ocean heat — which is where
most of the excess planetary warming actually goes. Marine heatwaves have
become the most-cited example of accelerating climate change
("the ocean set a daily record for the 400th consecutive day"). Without
ocean SST we're missing the most shareable story in the space.

The verified-viral exemplars in `brand/EXEMPLARS.md` include Kalmus'
ocean-record material. This lane plugs that gap.

## Data source — NOAA OISST

- **Product:** NOAA 1/4° Daily OISST v2.1
- **Access:** Free, no auth. Public ERDDAP / THREDDS endpoints and a CSV
  mirror hosted by NOAA PSL. Explore at
  https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html and
  the live ERDDAP at https://coastwatch.pfeg.noaa.gov/erddap/griddap/
- **Update cadence:** daily, ~1-day lag
- **Resolution:** 0.25° × 0.25° global grid
- **Good aggregate products to pull (avoid fetching the full grid):**
  - **Global mean SST** (one number per day) — for "ocean has been above
    daily record for N consecutive days" streak signals
  - **Regional basin means** (North Atlantic, Tropical Pacific, Indian
    Ocean, Mediterranean, Gulf of Mexico) — each with its own climatology
  - **Marine Heatwave flag** (Hobday et al. 2016 definition: SST > 90th
    percentile of the 1991–2020 climatology for ≥5 days). NOAA provides
    derived MHW products via the Marine Heatwave Tracker
    (https://www.marineheatwaves.org) — check if there's a free JSON/CSV
    feed before building the detection logic ourselves.

If you can't find a prebuilt MHW product, the MVP is:

1. Fetch the daily global mean SST anomaly from NOAA PSL (CSV or time-series endpoint).
2. Compare against the 1991–2020 climatology for today's day-of-year.
3. Track a **streak** of consecutive days where global mean SST anomaly
   is > the prior archive high for that day-of-year. This is the
   "400th consecutive day" style signal that actually goes viral.

## Editorial bar

- **Only tweet when the signal is genuinely extreme.** Pick bar ≥ 78.
- **Honest framing.** Archive window (typically 1982-present for OISST =
  ~44 years) must be stated. "Hottest global ocean SST in 44 years of
  satellite records." NOT "hottest ever."
- **Do not fire on short-lived anomalies.** The MHW definition requires
  ≥5 days. Use something similar — no day-1-of-the-spike tweets.
- **Cap frequency.** Ocean temperature changes slowly. If this source
  starts producing >2 tweets/week, the cap is wrong.

## Scope (what to build)

1. **New data module:** `src/data/ocean_sst.py`
   - Dataclasses: `OceanSSTReading`, `MarineHeatwaveEvent` (or similar).
   - `fetch_global_sst()` — returns latest available daily reading + the
     relevant climatology value for that day-of-year.
   - `detect_global_sst_record()` — compares today to the archive max
     for today's day-of-year; emits an event when exceeded.
   - If implementing MHW detection locally (not via a prebuilt feed):
     streak-tracking helper in state.
2. **State additions** (if streak tracking):
   - `ocean_sst_streak: {"days": int, "start_date": "...", "peak_anomaly_c": float}`
   - Update in `state.py` DEFAULT_STATE and `_merge_state`.
3. **Scoring:** `score_marine_heatwave` in `src/editorial/scoring.py`,
   threshold 78.
4. **Template:** `marine_heatwave_template` in `src/voice/templates.py`.
5. **Generator:** `generate_marine_heatwave_tweet` in
   `src/voice/generator.py`.
6. **Approval policy:** Add `marine_heatwave` branch in
   `src/editorial/approval.py`. Treat as suggested_auto / 90min delay
   (low human-impact risk, high accuracy).
7. **Category hint:** Add to `CATEGORY_HINTS` in
   `src/editorial/candidates.py`.
8. **Main orchestrator:** New section in `run_alerts` alongside the
   existing `ocean` (waves) source. Suggested ordering: fetch → detect →
   score → generate → save, with `_record_source_run`.
9. **Tests:**
   - `tests/test_ocean_sst.py` — fetch mocks, detection edge cases
     (positive streak, streak break, no data).
   - Scoring tests for threshold behavior.
   - A `run_alerts` mock in `tests/test_main.py` confirming the new path
     fires and drafts.

## Key voice rules for this signal

- Lead with the stake: **"The global ocean just posted its hottest
  daily SST in 44 years of records."** Not "NOAA's OISST data shows..."
- Social currency comes from the specific: *Nth consecutive day above
  record*, or *anomaly in °C*, or *equivalent energy content* if you
  can source it.
- Avoid the word "unprecedented." Banned in spirit if not in regex.

## Definition of Done

- [ ] Fetch verified against live NOAA endpoint (manual test note in PR).
- [ ] Detection fires on test fixtures; suppresses when data is within
      climatology noise.
- [ ] Generator produces text passing the existing safety pipeline.
- [ ] At least one test in `tests/test_main.py` wires the full path.
- [ ] Full suite green: `python -m pytest`.
- [ ] `BRIEFING.md` updated: source added to the pipeline diagram;
      scoring threshold listed.
- [ ] If NASA_OISST requires an API key / account, document in the
      "Secrets" section of `BRIEFING.md` and mirror to GitHub Actions
      secrets template.

## Non-goals

- **Don't** pull the full 0.25° global grid on every alerts cycle.
  That's gigabytes per fetch. Use aggregate products or spatial means.
- **Don't** tweet individual-buoy readings. Too local, too noisy.
- **Don't** add a daily "here's today's SST anomaly" tweet. That's the
  CO2-weekly trap. Record-breaking or streak-milestone only.
- **Don't** conflate ocean SST with marine ecosystem events (coral
  bleaching, fish die-offs). Those are downstream stories worth deferring.

## Budget expectations

- 1 new file + 1 new test file + 6 edits to existing files.
- ~4–8 hours focused work.
- Requires one real API probe to confirm endpoints return usable data.
