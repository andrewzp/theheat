# World Threshold Cache — design

**Status:** design v2 (post-codex-review) · **Date:** 2026-06-26 · **Author:** Claude (Opus 4.8) with Andrew

> **Revision note (v2):** A codex `exec -s read-only` cross-model review of v1 returned
> 2 P0 + 4 P1 + 2 P2 findings (verdict: "directionally right, not plan-ready yet"). This
> revision incorporates all eight. The two findings I'd independently reached (merge
> semantics, calendar_date coupling) are folded in; the four codex added — shared rate
> budget, country-record bootstrap, stale-threshold re-fire, vague failure surfacing —
> reshaped the design materially (a real rate-budget subsystem + per-fire provisional
> thresholds). Owner decisions confirmed: separate cache store; calendar/streak/
> simultaneous become US-only for the world in v1.

## Problem

`provider=both` (PR #332) runs the heat detector worldwide by handing ~595 non-US
cities to `detect_extreme_signals`, which does a **live 30-year Open-Meteo archive
pull per city, every run**. Open-Meteo's free archive endpoint is weight-limited
(~600 weight/min; a 30-year daily pull ≈ 43 weight), so it 429s after ~12–14 cities.
The first `both` production run observed `world[readings:12 failures:584]` — ~98% of
the world unobserved, with failures recorded only as a silent internal counter.

Root cause is an **architectural asymmetry**: the US/GHCN half is backed by a
precomputed threshold cache (`scripts/build_station_thresholds.py` → SQLite); the
world half recomputes 30 years of history live every run. Full diagnosis +
reproduction: PR #337 / handoff 2026-06-25. PR #337 shipped an interim cap
(`select_world_budget_cities`, budget 10, urgent-first). This spec is the proper fix.

## Goals / non-goals

**Goals:** restore daily record detection across all ~595 non-US cities; $0, no new
secrets; per-run Open-Meteo usage provably under the free-tier limits **including the
Hot 10 leaderboard's shared usage**; a run becomes a cheap forecast compare, not a
live archive pull; world-half saturation becomes a **surfaced** failure.

**Non-goals:** no paid Open-Meteo key (none free exists); no change to the US/GHCN
half; no growth of the main state gist (already over its 800 KB warning).

## Decisions (confirmed)

1. **Population: in-run incremental warmer.** Each run refreshes the N stalest/missing
   cities' archives; the cache warms over time and self-refreshes on a staleness TTL.
2. **Storage: a separate cache store, out of `state.json`.** The main state gist is
   already ~895 KB (over the 800 KB `STATE_SIZE_WARNING_BYTES`). The threshold cache
   is derived/regenerable, so it lives in its **own file in the existing gist**
   (`world_threshold_cache.json`, reusing the gist id + token; a dedicated gist is an
   easy swap if preferred). `state.json` is untouched. *(codex P2 #8)*
3. **Signal scope (world v1): `calendar_date`, `record_streak`, and
   `simultaneous_records` become US-only.** `calendar_date_high` feeds both streaks
   and the simultaneous-records roll-call (`open_meteo.py` orchestrator lines ~269 /
   ~455). Caching it needs all 365 dates/city (gist-prohibitive). v1 drops all three
   for the world and **explicitly updates tests, the dashboard event-log expectations,
   and the coverage observation set**; a rolling-window calendar cache is a documented
   future option. *(codex P1 #3)*

## Architecture

Split today's monolithic `detect_extreme_signals` (fetch archive + compute) into two
paths sharing one cache, governed by a shared rate budget.

### Cache schema (typed; per non-US city)
Stored in the separate cache store, keyed by city, behind typed records (not the bare
`{temp_c, year}` `CityRecord`): *(codex P2 #7)*
- `all_time_max/min` → `{temp_c, year, as_of, years_of_data}`
- `monthly_max/min[MM]` → `{temp_c, year, as_of, years_of_data}` (12 months)
- `monthly_mean[MM]` → `{mean_high_c, mean_low_c, sample_count, as_of}` — anomaly basis;
  `sample_count` lets the hot path reject sparse-data means.
- `wetbulb_max` → `{tw_c, year, as_of, years_of_data}`
- `as_of` = the archive pull date; `archive_start/end` retained for provenance.

### Open-Meteo rate budget (new subsystem) — *codex P0 #2*
A shared accountant tracks weight spent in the rolling **minute / hour / day** across
**every** Open-Meteo caller (alerts world half, the warmer, and the Hot 10 leaderboard
`fetch_all_city_temps`, ~638 cities). It reserves headroom for the leaderboard and
retries. Rules:
- Weight is **per-location** (multi-location batching cuts HTTP round-trips, not
  weight). Forecast (1 day, ≤3 vars) ≈ 1 weight/city; 30-yr archive ≈ ~43 weight/city.
- Hot path issues **paced multi-location forecast batches** sized so the rolling
  minute stays under a safe ceiling (< 600 with reserved headroom). Runs already take
  minutes, so ~595 forecast weight paced across the run is feasible.
- If a run genuinely can't cover all cached cities under budget, it **rotates**
  (oldest-evaluated-first) so coverage completes across the day's runs; the chosen
  cities and the skipped count are logged (never a silent cap).
- The warm path consumes only leftover budget after the hot path + reserved headroom.
- Pacing is **fake-clock tested** (no real sleeps in tests).

### Warm path (paced archive refresh)
Select up to `WORLD_WARM_BUDGET` cities whose `as_of` is missing or older than
`WORLD_CACHE_TTL_DAYS`, **urgent-first** (reuse the interim's `URGENT_WORLD_HEAT_CITIES`
ordering so Europe/perennials cache first). Pull each 30-yr archive once, compute all
thresholds in one pass (existing loop at `open_meteo.py:651`), write to the cache.
Best-effort: a warm failure never breaks a run.

### Hot path (cheap daily compare + anti-re-fire)
For each **cached** city in the run's budgeted/rotated set, fetch today's forecast and
compare against cached thresholds to emit signals — no archive call. Un-cached cities
are skipped (except `absolute_extreme`, band-based, no cache).

**Provisional threshold on fire (anti-re-fire) — *codex P0/P1 #5*:** when a run emits an
all_time/monthly/country record, it **immediately writes the new value into the cache**
(provisional, `as_of=today`) and flags the city for priority re-warm. Without this, a
city that broke its all-time record yesterday would compare today's forecast against the
up-to-30-day-stale old record and re-fire the same "hottest ever" every run — exactly
the false-record class the claim/warrant work targets. (Today's all-time path has no
same-year suppression — `open_meteo.py:751`.)

### Country records during bootstrap — *codex P1 #4*
`detect_country_records` aggregates across sampled cities (≥2/country). With a partial
cache, the sampled set is a partial country subset → a false "national record" from one
city, or a missed true peak. v1 requires a **per-country cache-coverage floor** (all
configured cities for that country cached/forecast-read) before emitting a country
record, and includes `eligible` / `cached` / `forecast_read` counts in the
`CountryRecord` facts.

## Failure surfacing — *codex P1 #6*
The `both` world half emits explicit per-run metrics: `world_total`, `cached_count`,
`forecast_attempted`, `forecast_failures`, `warm_attempted`, `warm_failures`,
`coverage_ratio`. Source-health degraded rules (independent of whether a draft was
created):
- **Bootstrap** (`cached_count < world_total`): healthy while `cached_count` climbs and
  warm failures are low; **degraded** if `cached_count` stalls across runs or warm
  failures spike.
- **Steady-state** (cache warmed): **degraded** if `coverage_ratio` drops below a floor
  or forecast failures spike — i.e. a return of the original silent-saturation mode is
  now loud. Integrates with the existing source-health + coverage-watch surfaces.

## Persistence & merge — *codex P0 #1*
The cache store has its own read/write with a **union-by-`as_of` merge** (a cache run
loads, mutates its slice, and on write merges against the current cache): per city/month
key, keep the record with the newest `as_of`; on equal `as_of`, keep the more extreme
threshold. This is NOT `_strat_take_incoming` (which replaces the whole dict and would
let an older run erase a newer run's warmed cities). Explicit concurrent-merge tests.

## Components
- `src/data/open_meteo.py` — split `detect_extreme_signals` into
  `compute_city_thresholds(archive) -> CityThresholdCache` (warm) and
  `evaluate_city(forecast, cached) -> ExtremeSignalBundle` (hot); multi-location
  forecast fetch; keep the monolith as a thin wrapper for the legacy `open_meteo`
  provider mode + existing tests.
- `src/data/openmeteo_budget.py` (new) — the rate-budget accountant (pure, fake-clock
  tested).
- `src/orchestrator/world_cache.py` (new) — cache store read/write + union-by-`as_of`
  merge + staleness selection + provisional-on-fire writer.
- `src/orchestrator/sources/open_meteo.py` — `both` world half: warm(stale slice) +
  hot(budgeted/rotated cached cities); remove `select_world_budget_cities` once warm;
  emit the failure-surfacing metrics; gate country records on the coverage floor;
  drop calendar/streak/simultaneous for the world path.
- Typed cache records (new dataclasses); dashboard + tests updated for the dropped
  world signals.

## Testing (TDD)
- `compute_city_thresholds`: all-time/monthly/mean(+sample_count)/wetbulb from a
  synthetic archive; `as_of` stamped.
- `evaluate_city`: each kept signal fires/doesn't vs cached thresholds (table-driven);
  absolute_extreme still works with no cache; sparse-mean rejection.
- Provisional-on-fire: after an all-time record, the next run does NOT re-fire.
- Country floor: no country record below coverage floor; counts present.
- Rate budget: paced batches stay under the minute ceiling on a fake clock; rotation
  covers all cities across N runs; leaderboard headroom respected.
- Cache merge: concurrent runs union by `as_of`; no warmed city lost.
- Orchestrator `both`: warm writes cache; hot reads it; un-cached skipped; US half
  untouched; dropped world signals absent; full suite green + ruff clean.

## Rollout
1. Land cache + split behind `both`; warm active, hot evaluates cached cities; the #337
   interim cap stays (its urgent ordering doubles as the warm priority).
2. Watch the cache warm (cached_count climbs, `coverage_log` diversifies, no 429s,
   budget metrics within limits).
3. Once warmed, remove the interim cap (hot path covers the budgeted/rotated full set).

## Open questions (for review)
1. **Starting tunables** — `WORLD_WARM_BUDGET`, `WORLD_CACHE_TTL_DAYS`, the rate-budget
   minute/hour/day ceilings + leaderboard reservation, hot-path batch size + rotation
   threshold. Set against measured weight in the plan; tunable post-warm.
2. **Cache store form** — separate file in the existing gist (default, least plumbing)
   vs a dedicated gist. Either keeps `state.json` lean.
3. **Future:** rolling-window calendar cache to restore world streaks/simultaneous if
   the loss is felt.
