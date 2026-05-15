# Lane 13 — Plan E: Precipitation + Snow Extremes (GPM-IMERG + NSIDC Snow)

**Branch:** `plan-e/precip-and-snow`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (Bucket 5: precip + snow)
**Scope:** Add precipitation extreme detection (NASA GPM-IMERG) + snow extreme detection (NSIDC Snow Today / MODIS)
**Estimated time:** 5-7 hours CC, single PR
**Parallel-safety:** **Conflicts with Lane 12 (floods), Lane 14 (climate indices), Lane 15 (threshold registry).** Sequential with those.

## Why this lane exists

@theheat currently has no precipitation or snow coverage. "Highest 24-hour rainfall ever recorded" (Pakistan monsoon, Hawaiian atmospheric river), record snowfall events (Buffalo 2022, Sapporo blizzards) are completely invisible. Both are core diary-of-a-warming-planet stories — extreme precip becomes more extreme in a warming atmosphere (Clausius-Clapeyron), and high-impact snow events still matter editorially.

This lane adds two independent but parallel-themed sources.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — Bucket 5
2. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py) — NSIDC pattern (existing); reuse the auth/fetch model for the snow source.
3. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/co2.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/co2.py) — NOAA cadence-gated pattern; snow updates daily but the editorial bar fires only on records.
4. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_climate_context.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_climate_context.py) — F2 helper. Wire for both precip + snow bundles.

## Sub-task 13a — GPM-IMERG precipitation extremes

**Source:** NASA Global Precipitation Measurement, Integrated Multi-satellitE Retrievals for GPM.
- Daily aggregated precip totals (mm) per 0.1° grid cell, global
- API: `https://gpm.nasa.gov/data` (HTML index) → underlying THREDDS / OPeNDAP endpoints
- Requires NASA EarthData token (free with registration; same pattern as GRACE-FO already on the pipeline — see `src/data/ice_mass.py`)
- Alternative: `https://giovanni.gsfc.nasa.gov/giovanni/` time-series query API for point/region queries (simpler than full grid)

**Detection rules:**

1. **Daily total record per city** (mirror Open-Meteo pattern): compare today's precip total at city coordinates against the multi-year daily record for that calendar day. Fire when today beats archive record by ≥20mm.
2. **Multi-day rainfall accumulation milestone:** 3-day, 7-day rolling totals crossing extreme thresholds (e.g., 7-day total > 300mm at a city = atmospheric-river-scale event).
3. **Country-wide event:** ≥10 cities in a country see record-breaking precip on the same day → simultaneous-event signal (mirror existing `score_simultaneous_records`).

**Files:**
- `src/data/gpm_imerg.py` (new) — `PrecipExtremeEvent` dataclass + `fetch_daily_precip()` + `detect_precip_records()`. Use EARTHDATA_TOKEN env var (same as ice_mass.py).
- Pre-built city list: reuse the existing 638-city list (`src/cities/*` or wherever it lives — find via `grep -r "638 cities"`).

## Sub-task 13b — NSIDC Snow Today / snow extremes

**Source:** NSIDC publishes daily snow water equivalent (SWE) and snow depth time series.
- API: `https://nsidc.org/api/snow-today` or similar; investigate as first commit
- Free, may require NSIDC user token (same pattern as sea_ice.py)

**Detection rules:**

1. **Single-day snowfall record:** city sees 24-hour accumulation that beats the archive record (where the data supports per-city archive — may need to narrow to high-quality station network).
2. **Multi-day blizzard events:** ≥3 consecutive days of heavy snow at a single location.
3. **Seasonal snowfall total record:** end-of-season cumulative breaks the archive (mirror sea-ice annual-cap pattern; 8 tweets/year max).

**Files:**
- `src/data/nsidc_snow.py` (new) — mirror sea_ice.py shape with snow-specific parsing.

## Sub-task 13c — Shared scoring + bundle + orchestrator

- `src/editorial/scoring.py` — `score_precipitation_extreme(mm_total, period_days, deviation_from_record, region)` + `score_snow_extreme(mm_swe, deviation_from_record, region)` + `score_seasonal_snow_record(total_mm, years_of_archive, region)`
- `src/two_bot/intern.py` — `build_precipitation_bundle(event)` + `build_snow_extreme_bundle(event)` + `build_seasonal_snow_bundle(event)`. All call `local_climate_context()`.
- `src/editorial/approval.py` — precip + snow events → `manual_only` (subjective severity; human approves)
- `src/main.py::run_alerts` — wire both sections
- `src/state.py` + `src/state_schema.py` — `snow_annual_count`, `seasonal_snow_records: dict[str, dict]`
- `tests/test_gpm_imerg.py` + `tests/test_nsidc_snow.py` — detector, scoring, integration tests

## Editorial constraints

- **Quantification first.** Precip events cite mm + period ("147mm in 6 hours"). Snow events cite cm + period.
- **Geographic anchoring via F2.** When the event location matches a curated climate region, the bundle's `region_climate_system` field activates ("the Sahel monsoon", "the Pacific Northwest atmospheric river belt").
- **No "biblical" / "epic" / "catastrophic" framing.** Banned by safety pipeline.

## Acceptance

- mypy clean, ruff clean
- Full suite passes with ~30+ new tests
- Live source smoke for both: GPM-IMERG `fetch_daily_precip(strict=True)` + NSIDC `fetch_snow_today(strict=True)` return data
- Manual workflow dispatch run passes

## Constraints

- **NASA EarthData token required for GPM.** Add `EARTHDATA_TOKEN` env var docs to `.env.example` if it exists; add to GitHub Actions secret notes in `.github/workflows/bot.yml` if needed.
- **Investigation-first commit.** Live curl both endpoints, capture schemas.
- **Subagent model floor:** Sonnet 4.6.

## Branch / PR sequence

1. Branch `plan-e/precip-and-snow` from `main`.
2. Investigation commits (curl GPM + NSIDC, doc schemas).
3. Implementation commits per sub-task.
4. PR → CI green → Claude merges.

Done. ~5-7 hours CC.
