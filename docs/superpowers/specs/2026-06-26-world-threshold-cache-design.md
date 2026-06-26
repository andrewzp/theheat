# World Threshold Cache — design

**Status:** design (awaiting review) · **Date:** 2026-06-26 · **Author:** Claude (Opus 4.8) with Andrew

## Problem

`provider=both` (PR #332) runs the heat detector worldwide by handing ~595 non-US
cities to `detect_extreme_signals`, which does a **live 30-year Open-Meteo archive
pull per city, every run**. Open-Meteo's free archive endpoint enforces a
weight-based minutely limit (~600 weight/min; a 30-year daily pull is ~43 weight),
so it 429s after ~12–14 cities. The first `both`-mode production run observed
`world[readings:12 failures:584]` — ~98% of the world unobserved, and the failures
were a silent internal counter, never a source failure, so monitoring stayed green.

Root cause is an **architectural asymmetry**: the US/GHCN half is backed by a
precomputed threshold cache (`scripts/build_station_thresholds.py` → SQLite), so a
run is a cheap comparison; the world half recomputes 30 years of history live every
run. Full diagnosis + reproduction: PR #337 / handoff 2026-06-25.

PR #337 shipped an **interim cap** (`select_world_budget_cities`, `WORLD_FETCH_BUDGET=10`,
urgent-first) so the acute event is observed instead of starved. This spec is the
**proper fix** that removes the cap and restores full ~595-city coverage.

## Goals / non-goals

**Goals**
- Restore daily record detection across all ~595 non-US cities, $0, no new secrets.
- Per-run Open-Meteo usage stays under the free-tier limits (600/min, 5k/hr, 10k/day).
- Mirror the GHCN cached-threshold model: a run is a cheap forecast compare, not a
  live archive pull.
- Make world-half fetch saturation a **surfaced** failure, not a silent counter.

**Non-goals**
- No paid Open-Meteo key (no free key exists; keeps the $0 stack).
- Not changing the US/GHCN half (it already works this way).
- Not building a separate cache artifact/store — reuse the existing state keys.

## Decisions (confirmed)

1. **Population: in-run incremental warmer.** Each `both` run refreshes the N
   stalest/missing cities' archives (N under the minutely wall); the cache warms
   over ~10 days and self-refreshes on a monthly staleness horizon. Zero new infra.
2. **Storage: reuse the state-gist `city_*` dicts.** Populate the currently-empty
   `city_all_time_max/min` and `city_monthly_max/min` keys (already wired through
   `state_schema.py`, `DEFAULT_STATE`, `MERGE_SPEC`, and SQLite `_METADATA_JSON_KEYS`),
   plus two small new keys for anomaly means and wet-bulb maxima (same plumbing).

## Architecture

Split today's monolithic `detect_extreme_signals` (fetch archive + compute signals)
into two paths sharing one cache:

### Cache schema (per non-US city)
Stored under the city name key:
- `city_all_time_max/min[city]` → `{temp_c, year, as_of}` — 30yr overall extreme.
- `city_monthly_max/min[city][MM]` → `{temp_c, year, as_of}` — per calendar month.
- **(new)** `city_monthly_mean[city][MM]` → `{mean_high_c, mean_low_c, as_of}` — for anomaly.
- **(new)** `city_wetbulb_max[city]` → `{tw_c, year, as_of}` — all-time max wet-bulb.

`as_of` is the date the archive was last pulled. ~51 numbers/city × 595 ≈ ~30k
values (~100–200 KB gist growth on the current ~895 KB). A `CityThresholdCache`
typed shape captures this (extends the existing `CityRecord`).

### Warm path (paced archive refresh)
Each run, select up to `WORLD_WARM_BUDGET` cities whose cached `as_of` is missing or
older than `WORLD_CACHE_TTL_DAYS` (30), **urgent-first** (reuse the interim's
`URGENT_WORLD_HEAT_CITIES` ordering so Europe/perennials cache on the first runs).
For each, pull the 30-year archive once, compute all thresholds in one pass (the
existing loop at `open_meteo.py:651`), and write them to the cache. Best-effort: a
warm failure never breaks a run; cities just stay un-cached and retry next run.

### Hot path (cheap daily compare)
Each run, for every **cached** city, fetch today's forecast (max/min/wet-bulb) and
compare against the cached thresholds to emit signals — no archive call. Forecasts
are issued via Open-Meteo **multi-location** batching (comma-separated coords) and
paced to stay under the minutely budget. Un-cached cities are skipped this run
(except `absolute_extreme`, which is latitude-band-based and needs no cache).

### Rate budget (per run)
- Hot path: ~595 cached cities × forecast (weight 1 each) = ~595 weight, batched
  into a handful of multi-location calls, paced under 600/min.
- Warm path: `WORLD_WARM_BUDGET` (≈8) × ~43 weight ≈ ~340 weight.
- Combined ≈ ~935 weight/run, sequenced/paced to respect 600/min; ~6 runs/day keeps
  daily usage (~5.6k + leaderboard) under 10k/day.

## Signal scope

Cacheable from the schema above: **all_time, monthly, anomaly, wet_bulb**
records, plus **absolute_extreme** (band-based, unchanged) and **country records**
(aggregate of cached all-time peaks).

**`calendar_date` records become US-only.** They need this-exact-month+day extremes
for all 365 dates (≈434k values for the world) — gist-prohibitive — and are the
weakest editorial tier ("hottest on this date"). The world half drops them; GHCN/US
keeps them unchanged. *(Flagged for review — see Open questions.)*

## Failure surfacing

The world half's saturation must not be silent. The hot/warm split is designed so a
healthy run makes ~0 failed archive calls (only `WORLD_WARM_BUDGET` archive calls,
all expected to succeed under the limit). If warm-path archive failures spike, or if
the cached-city count stalls below a floor while drafting, the run records a
**source-level** signal (degraded), not just an internal counter — so the existing
source-health / coverage-watch surfaces it. Exact thresholds set in the plan.

## Components

- `src/data/open_meteo.py` — split `detect_extreme_signals` into
  `compute_city_thresholds(archive) -> CityThresholdCache` (warm) and
  `evaluate_city(forecast, cached) -> ExtremeSignalBundle` (hot); add
  multi-location forecast fetch; keep the monolith as a thin wrapper for the legacy
  `open_meteo` provider mode + tests.
- `src/orchestrator/sources/open_meteo.py` — `both` world half calls warm(stale
  slice) + hot(cached cities); remove `select_world_budget_cities` cap once warm.
- `src/state.py` / `src/state_schema.py` / `src/storage/sqlite_store.py` — wire the
  two new cache keys (mirror the existing `city_*` plumbing).
- Cache read/write helpers (pure, unit-tested) for staleness selection + dedup.

## Testing (TDD)

- `compute_city_thresholds`: all-time/monthly/mean/wetbulb derived correctly from a
  synthetic archive; `as_of` stamped.
- `evaluate_city`: each signal fires/doesn't vs cached thresholds (table-driven);
  absolute_extreme still works with no cache.
- Staleness selection: picks missing + oldest `as_of`, urgent-first, caps at budget.
- Multi-location forecast parse: list-of-structures mapped back to cities.
- Orchestrator `both`: warm writes cache; hot reads it; un-cached skipped; US half
  untouched; full suite green + ruff clean.

## Rollout

1. Land the cache + split behind the existing `both` path; warm path active, hot
   path evaluates cached cities; `select_world_budget_cities` cap stays.
2. Watch the cache warm over ~10 days (cached-city count climbs, `coverage_log`
   diversifies, no 429s).
3. Once warmed, remove the interim cap (the hot path covers all cached cities).

## Open questions (for review)

1. **`calendar_date` → US-only** for the world half — confirm acceptable (recommended;
   weakest tier, gist-prohibitive to cache). Alternative: cache a ±3-day window per
   month (changes semantics) — not recommended.
2. **`WORLD_WARM_BUDGET` (≈8) and `WORLD_CACHE_TTL_DAYS` (30)** — starting values;
   tunable once we see real warm-rate vs the limit.
3. **Hot-path pacing** — multi-location batch size + inter-call spacing to stay under
   600/min; final values fixed in the plan against the observed weight.
