# Design — Heat coverage watch (geographic representativeness)

- **Date:** 2026-06-25
- **Status:** Proposed v2 (revised after codex adversarial review — awaiting Andrew's review)
- **Surface:** `src/state.py` + `src/orchestrator/sources/open_meteo.py` (record) ·
  `scripts/source_health_sentinel.py` + `dashboard/lib/source-health.js` (check)
- **Type:** Additive monitoring — no change to drafting/scoring behavior

## Problem

The heat detector silently ran US-only for ~7 weeks (GHCN cutover, PR #33) and was
blind to a deadly European heatwave — 21/21 heat events US. Every health check
measures **liveness** ("is the source up / yielding >0?"), never **coverage** ("does
output match the *global* mission?"). A US-only heat feed was green by every metric.
Fixed the symptom (PR #332, `provider=both`); this closes the *monitoring* gap so it
can't recur unseen.

## Decision log

- **v1 (shadow_slate proxy) REJECTED** after codex adversarial review (2026-06-25).
  Codex verified, and I confirmed: `run_history` is capped at **20 runs**
  (`_merge_run_history(max_items=20)`, state.py:404) ≈ a **<1.5-day window with ~4–7
  alert slates**, so a `MIN_EVENTS=15` per-class rule would have *skipped* the very
  incident it targets. And `shadow_slate.summary = bundle.where or city` (funnel.py:27)
  is **not** "City, Country" for non-heat classes (fire=`nearest_city`, quake=USGS
  `place`, cyclone=`"storm, basin"`), so parsing country from it fails → Unknown →
  silence. The proxy is a monitor that mostly wouldn't fire.
- **v2 (this doc):** record canonical per-event geography **at the source** (heat's
  clean `country`) into a **persistent rolling tally** decoupled from the run_history
  cap; **scope to heat only** (the class with reliable geography); add a **no-data
  alarm**. Other classes are deferred to per-source instrumentation (Future).

## Scope

**Heat only.** Heat events carry a clean `country` on the event object
(`ev.country` in run_extreme_signals). Fire/air_quality/precip/quake/ocean/disaster
do **not** expose per-event country uniformly today; watching them would false-positive
on physical geography (faults, reefs, basins, monsoons) and mostly parse to Unknown.
They are a Future item, instrumented one source at a time.

## Design

### 1. Persistent coverage tally (`coverage_log` in state)

A new append-only state list, pruned to a rolling window — **independent of the
20-run run_history cap**, which is what makes the window long enough to be reliable.

```
state["coverage_log"] = [
  { "cls": "heat", "event_id": "monthly_high_USC00092159_06_2026-06-20",
    "country": "United States", "continent": "North America", "date": "2026-06-25" },
  ...
]
```

- Pruned to `COVERAGE_WINDOW_DAYS = 21` on each write (and defensively on read).
- Merged via a dedicated merge-spec entry (append + prune + dedup on **`event_id`**,
  so concurrent gist writers / reruns don't double-count — but two *distinct* heat
  events in the same country on the same day correctly count as two).
- One record per surfaced heat event (see §2). At a few heat drafts/day this
  accumulates **dozens of events over 21 days** — comfortably above the minimum,
  unlike the <1.5-day run_history window.

### 2. Recording site (canonical geography, no parsing)

In `run_extreme_signals` (src/orchestrator/sources/open_meteo.py), at each point a
**heat** signal is enqueued (the per-city `strongest_signal` enqueue and the
`country_record` enqueue), call:

```
state.record_coverage_observation(bot_state, cls="heat",
    country=<ev.country>, continent=resolve_continent(ev.country), when=<signal_date>)
```

The country comes straight off the typed event — **no summary parsing, no Unknown
guessing.** The exact heat enqueue sites are enumerated in the plan; the recorded
`cls` is the literal `"heat"`, not a parsed type, so new heat *kinds*
(`monthly_high`, `all_time_high`, `absolute_extreme`, `anomaly_hot`, `country_high`,
`record_streak`, calendar records, …) all record uniformly.

### 3. Continent + country resolution

`data/country_continent.json` (committed, derived from cities.csv lat/lon by
`scripts/build_country_continent.py`) maps country → continent. `resolve_continent`:
US name-forms (`"United States"`, `"… [United States]"`, `"US"`) → `North America`;
else the map; else `Unknown`. Transcontinental countries (Russia, Turkey, …) get a
single best-effort continent — acceptable because the **country** is also recorded and
checked directly (below), so US-only is caught precisely even though it's inside
"North America".

### 4. The check — `coverage_watch(coverage_log, now)`

Over the heat records in the window (deduped):
- **No-data alarm:** if the bot has been drafting but heat coverage records are
  `< COVERAGE_DATA_FLOOR` (e.g. 5) → flag `coverage instrumentation may be broken`
  (do **not** silently skip — this is the codex "missing data = silence" fix).
- **Concentration:** flag if **either** a single **continent** holds
  `≥ COVERAGE_CONCENTRATION` of records **or** a single **country** holds
  `≥ COVERAGE_CONCENTRATION`, over `≥ COVERAGE_MIN_EVENTS` records. The country check
  catches "US-only" precisely; the continent check catches "all-Europe" drift.
- Below `MIN_EVENTS` (and above the data floor) → "insufficient data this window",
  reported as a soft note, not silent.

### 5. Tunables (validated against the real heat rate)

- `COVERAGE_WINDOW_DAYS = 21`
- `COVERAGE_MIN_EVENTS = 20`   (reachable: heat drafts multiple/day over 21 days)
- `COVERAGE_CONCENTRATION = 0.85`
- `COVERAGE_DATA_FLOOR = 5`

### 6. Output

One advisory issue (sibling to yield-watch): `COVERAGE_WATCH_TITLE`,
`COVERAGE_WATCH_MARKER`, body naming the dominant country/continent + share +
distribution + the no-data state, auto-closing when coverage diversifies. Codex flagged
advisory-may-be-ignored: the body leads with "the bot may be blind to a region" and the
issue is **not** auto-closed merely because the sample shrank (only when coverage is
actually diverse), so a real blind spot stays open.

## Wiring

- `src/state.py` — `coverage_log` in DEFAULT_STATE + merge-spec; `record_coverage_observation`; prune helper.
- `src/orchestrator/sources/open_meteo.py` — record at the two heat enqueue sites.
- `scripts/source_health_sentinel.py` — `coverage_watch` + issue reconciliation (mirrors yield-watch).
- `dashboard/lib/source-health.js` — read `coverage_log`, show the distribution + flag (mirror; thresholds shared via constants kept identical, with mirror tests).
- `data/country_continent.json` + `scripts/build_country_continent.py` — new.
- tests both sides.

## Testing (realistic, not toy)

- Replay a `coverage_log` shaped like the **actual incident** (≥20 heat records, ~100%
  `United States`) → **flags** (country-concentration). Regression for the outage.
- A diversified log (US, Spain, India, Australia, Brazil…) → **no flag**.
- Below `MIN_EVENTS` → "insufficient data" note, not silent, not flagged.
- Below `DATA_FLOOR` while the bot is drafting → **no-data alarm**.
- `resolve_continent`: US forms → North America; `"…, Spain"` → Europe; junk → Unknown.
- Prune drops records older than 21 days; merge dedups concurrent writers.

## How v2 addresses the codex P1s

| Codex P1 | v2 fix |
|---|---|
| 20-run window too short → skips the outage | persistent `coverage_log`, 21-day window, not run_history |
| shadow_slate = scored top-10 sample, not coverage | record **every** surfaced heat event at source |
| summary not "City, Country" for non-heat | record clean `ev.country`; **heat-only** scope |
| Unknown-majority skip = silence | no-data alarm + country recorded directly (not parsed) |
| broad watched set physically regional | scope to heat only; others deferred |
| continent too coarse (US vs NA) | also record + check **country** concentration |

## Future

Instrument fire/air_quality/precip/quake/ocean/disaster to call
`record_coverage_observation` with their own clean geography (from each bundle's facts),
extending the same tally + check per-class. One source at a time.
