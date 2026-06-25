# Design — Source-health coverage watch (geographic representativeness)

- **Date:** 2026-06-25
- **Status:** Proposed (awaiting Andrew's review)
- **Surface:** `scripts/source_health_sentinel.py` + `dashboard/lib/source-health.js`
- **Type:** Additive monitoring — no change to drafting/bot behavior

## Problem

On 2026-06-25 we found the heat detector had been **100% US-only for ~7 weeks**
(since the GHCN cutover, PR #33, 2026-05-05) — 21/21 heat events US — and was
structurally blind to every other continent. It only surfaced when a deadly
European heatwave made the gap obvious. Fixed the symptom in PR #332
(`THEHEAT_SIGNALS_PROVIDER=both`), but the *monitoring* blind spot remains.

**Root cause:** every health check measures **liveness** ("is the source up?
is it yielding >0 observations?"), never **coverage** ("does our output match
the mission of *global* climate awareness?"). A US-only heat feed was green by
every existing metric. Nothing watches the map.

## Goal

A representativeness check that would have caught this: alert when a source/signal
that is *supposed* to be global has gone **mono-regional** over the recent window.
Advisory (a human investigates), not a hard gate. Mirrors the existing yield-watch.

## Non-goals

- Not a hard failure / not a drafting gate — advisory only, like yield-watch.
- No change to the bot, the providers, or scoring.
- v1 does not instrument every source for raw observed geography (see Future).

## Design

### Data basis — `shadow_slate` (decided 2026-06-25)

Only the heat source writes per-event geography to `run_history`; the rest record
counts (`details: None`). The one **source-agnostic** geographic signal retained
across the window is **`shadow_slate`** — the top-scored events *per run*, each with
a `type` and a `summary` ending in the location (`"Mauna Loa, Hawaii, United States"`,
`"Riyadh, Saudi Arabia"`). The check therefore measures **coverage of what the bot
surfaced** — a strong proxy for true coverage, not every raw observation. The issue
body states this proxy nature plainly. (The fully-accurate raw-observed version is a
Future item.)

### Continent resolution

A committed `data/country_continent.json` maps country → continent, **derived from
`data/cities.csv`** lat/lon (each tracked country bucketed to its cities' continent;
generator `scripts/build_country_continent.py`, re-runnable). Python and the JS
mirror read the **same JSON** so they cannot drift.

Resolving a `shadow_slate` entry to a continent:
1. Parse the country = the substring after the last comma in `summary`.
2. If it reads as US (`"United States"`, `"… [United States]"`, `"US"`) → `North America`.
3. Else look it up in `country_continent.json` (full names match cities.csv for non-US).
4. Else (coord-only fire summaries like `"63.2N, 81.4E"`) → bucket by lat/lon.
5. Else → `Unknown`.

### Signal classes

`shadow_slate.type` maps to a signal **class** (`COVERAGE_CLASS_FOR_TYPE`):
`heat` (monthly/all_time high+low, absolute_extreme, calendar, anomaly, country, streak),
`fire`, `air_quality` (dust_event, air_quality_hazard, pm25), `precip`, `quake`,
`ocean` (sst_anomaly, coral), `disaster` (gdacs, copernicus_ems).

`COVERAGE_GLOBAL_CLASSES` (the opt-in declaration — the actual fix) = the classes
whose sources Andrew declared global-ambition: `heat, fire, air_quality, precip,
quake, ocean, disaster`. Only these are checked. Everything else (US-only
`nws_alerts`/drought/water sources, basin-scoped `nhc`/`jtwc`, polar ice/ozone) is
absent from the list and never flagged — false positives are excluded *by
construction*.

### The rule — `coverage_watch_classes(run_history)`

For each declared-global class, across all `shadow_slate` entries in the window
(**deduplicated by `event_id`** — a high-scoring event persists across consecutive
runs' slates and must count once, or concentration inflates):
- Resolve each entry to a continent; tally per class (`assessable` = entries that
  resolve to a real continent, i.e. excluding `Unknown`).
- **Skip** if `assessable < MIN_EVENTS` (too small a sample) or if `Unknown` is the
  majority (can't assess — e.g. ocean events at sea).
- **Flag** if any single continent holds `≥ CONCENTRATION_THRESHOLD` of the
  assessable events. Record the class, the dominant continent, its share, and the
  full distribution.

### Tunables (constants)

- `COVERAGE_MIN_EVENTS = 15`
- `COVERAGE_CONCENTRATION_THRESHOLD = 0.85`
- `COVERAGE_UNKNOWN_SKIP_FRACTION = 0.5`

### Output

One advisory issue, sibling to yield-watch:
- `COVERAGE_WATCH_TITLE = "Coverage watch: global sources gone mono-regional"`
- `COVERAGE_WATCH_MARKER = "<!-- source-health-coverage-watch -->"`
- Body lists each flagged class with its dominant continent + share + distribution,
  the proxy caveat, and an investigate hint. Labeled advisory (`source-health-sentinel`,
  `unknown`), auto-closes when no class is mono-regional. Same create/update/close
  reconciliation as `plan_yield_watch_action`.

### Wiring

- `scripts/source_health_sentinel.py`: add `coverage_watch_classes` + `build_coverage_watch_body`
  + `plan_coverage_watch_action` + `_open/_create/_update/_close_coverage_watch_issue`,
  reconciled in `main()` alongside yield-watch (it already has `run_history`).
- `dashboard/lib/source-health.js`: mirror `coverageWatchClasses` so the dashboard can
  surface it; keep Python/JS in sync (shared JSON + identical thresholds).

## Testing

Pure classifier, unit-tested both sides (`tests/test_source_health_sentinel.py` +
`dashboard/tests/source-health.test.js`):
- the heat-100%-US case **flags** (regression for the actual incident);
- a class spread across continents does **not** flag;
- a declared-regional source (`nws_alerts`) is never considered;
- below `MIN_EVENTS` → skipped; majority-`Unknown` → skipped;
- continent resolver: `"United States"`/territory/`"US"` → North America; `"…, Spain"`
  → Europe; coord-only → lat/lon bucket; junk → Unknown.

## Files touched

- `data/country_continent.json` — new (derived artifact)
- `scripts/build_country_continent.py` — new (generator)
- `scripts/source_health_sentinel.py` — coverage classifier + issue reconciliation
- `tests/test_source_health_sentinel.py` — coverage tests
- `dashboard/lib/source-health.js` — JS mirror
- `dashboard/tests/source-health.test.js` — JS mirror tests

## Rollout

Runs hourly inside the existing `source-health-sentinel` workflow (no new workflow,
no secrets). Advisory issue only. Rollback: remove the reconciliation call (the
classifier is pure and inert otherwise).

## Future

Option B — instrument fire/air_quality/precip/quake/ocean to write per-event
`country` into `run_history` (like heat), then check **raw observed** coverage
instead of the surfaced-output proxy. Higher fidelity; a separate multi-source change.
