# Lane 05 — Plan A Lane A: Source-Health Foundation + Restore + Degraded Fix

**Branch:** `plan-a/source-health-foundation`
**Plan-of-record:** `docs/PLAN_A.md` (in-repo)
**Total scope:** Phases 1 + 2 + 3 (sequential within this lane — they share `src/main.py` so can't parallelize)
**Estimated time:** 9-12 hours CC across 3 PRs

## Why this lane exists

A health audit of @theheat's data layer (state.json over 8 alerts crons in the 28h window
state retains) found:

| Source | Success rate | Status |
|---|---|---|
| `ocean_sst` | 0/8 | Hard-dead. ClimateReanalyzer JSON endpoint returns non-JSON. Marine heatwaves offline. |
| `open_meteo_extreme_signals` | 2/8 success, 6/8 degraded | Main engine running degraded 75% of cycles. |
| `firms` | 7/8 | Transient `HTTPSConnectionPool` timeouts. No retry hardening. |
| `river_gauges` | 8/8 "success" | Lies — heights flow, flood-stage flag dead (USGS endpoint retired). |

Plus: `data_source_failures` in state is `{}`. `run_history` caps at 20 entries (~28h). Once the buffer flushes, all source-health data is lost.

This lane fixes the data layer AND adds persistent source-health surveillance so the next silent failure is caught on day one, not in week three.

## Read first (in order)

1. `docs/PLAN_A.md` — full Plan A doc (5 phases, file inventory, failure modes, risk register).
2. `PIPELINE.md` (repo root) — current flow.
3. `BRIEFING.md` (repo root) — pipeline conventions, state shape, approval policies.
4. `docs/conductor-lanes/00-README.md` — lane conventions (note: parts of this README are outdated re: voice/templates, ignore those bits).
5. The four files this lane touches most: `src/main.py:1555-1614`, `src/state.py`, `src/state_schema.py`, `src/data/source_status.py`.

## Phase 1 — Source-health platform (first PR)

**Goal:** every subsequent fix plugs into a shared observability layer.

**Files:**
- `src/state.py` — add `source_health` operations:
  - `record_source_health(state, source, status, error=None) -> None` — append-only rolling 7-day per-source counter (success / degraded / failed / skipped counts + `last_success_ts`, `last_error`, `last_error_ts`).
  - Existing `increment_data_source_failure` / `reset_data_source_failure` (at `src/main.py:1604,1614`) stay untouched; new function lives alongside.
- `src/state_schema.py` — add `SourceHealth` TypedDict; add `source_health: dict[str, SourceHealth]` to `BotState`. Mirror with `DEFAULT_STATE` in `src/state.py:19` per the repo's documented duplication rule.
- `src/data/source_status.py` — extend beyond the two exception classes:
  - `assert_response_schema(payload, required_fields, source_name) -> None` — raises `SourceFetchError` listing the missing keys. Use this at the top of every source's parse step.
- `src/data/_freshness.py` (new) — `assert_freshness(data_date, source_name, max_age_days) -> None` — raises `SourceFetchError` if the source's most-recent data point is older than expected.
- `src/main.py:1567-1614` — wire `state.record_source_health(bot_state, source, status, error)` next to the existing `data_source_failures` writes. Three call sites per source path (success, degraded, failed).
- `tests/test_source_health.py` (new) — coverage:
  - Rolling 7-day counter: increment, prune-by-age, multi-day aggregation
  - Schema-drift assertion: valid payload passes; missing required field fails with a clear message; extra fields don't fail
  - Freshness assertion: fresh data passes; stale data fails; tolerance window honored

**Acceptance:**
- mypy clean.
- `python -m pytest tests/ -q -m "not voice_replay"` passes 925+ tests (currently 910 + 15 new).
- After deploy, first cron writes `state.source_health` with rows for every source that ran.
- Schema-drift triggers on a synthetic test payload.

**Don't do in Phase 1:**
- Don't restore ocean_sst yet (Phase 2).
- Don't change open_meteo degraded trigger (Phase 3).
- Don't build the dashboard view (separate lane).

## Phase 2 — Restore broken sources (second PR)

Starts after Phase 1 merges. Three sub-fixes in one PR (small, related, ship together).

### 2a — ocean_sst

**First commit:** investigate. Run `curl -A "(theheat-bot, contact@theheat.app)" -i https://climatereanalyzer.org/clim/sst_daily/json/oisst2.1_world_sst_day.json | head -50`. Capture status code + first 200 chars of body. Two outcomes:

- **Endpoint returns HTML or empty:** Permanently dead. Two replacement paths:
  - Option A: Switch source to NOAA OISST direct NetCDF. Heavier integration (NetCDF parsing, new dep). Authoritative.
  - Option B: Pivot purpose to NOAA Coral Reef Watch's Degree Heating Weeks (DHW) per-region. More useful editorially than global-mean SST; pairs with Plan B (Coral DHW) cleanly.
  - Pick A if "global-mean SST anomaly streak" is editorially load-bearing. Pick B if you'd rather get regional marine-heat detection right and drop the global-mean angle. Make the call based on the live `curl` data + a 10-minute look at how `MarineHeatwaveStreakEvent` is used downstream (writer, fact-check entity surface).

- **Endpoint returns intermittent garbage:** Wrap fetch in retry helper from sub-task 2c. Add `assert_response_schema(json, ["temps_jra55"], "ocean_sst")` from Phase 1. Keep current endpoint.

**Files:** `src/data/ocean_sst.py` (replace fetch path), `tests/test_ocean_sst.py` (update fixtures to match).

### 2b — river_gauges flood-stage

USGS WaterWatch flood-stage endpoint is retired. Gauge heights still flow via the existing path; only the "above flood stage?" flag is lost.

Replacement: NWS AHPS forecast feed at `https://water.weather.gov/ahps2/forecasts.php?type=feed` (RSS). Each forecast point carries `nws_lid`, `category` (action / minor / moderate / major / record), and `observed_value` / `forecast_value`.

**First commit:** WebFetch the AHPS feed; confirm schema. The lane spec assumes RSS/XML — if it's switched to JSON, adjust parser shape.

**Files:** `src/data/river_gauges.py` (parser update), `tests/test_river_gauges.py` (fixture from real AHPS response).

### 2c — FIRMS retry hardening

Transient `HTTPSConnectionPool` timeouts to `firms.modaps.eosdis.nasa.gov` happen ~12% of crons.

Build a shared `src/data/_http.py` retry helper:

```python
def fetch_with_retry(url, *, headers=None, timeout=30, attempts=3, backoff_base=1.0):
    """Fetch with exponential backoff on transient failures.

    Retries on requests.ConnectionError, requests.Timeout, and 5xx.
    Does NOT retry on 4xx or schema-drift errors (those are deterministic).
    """
```

Wire FIRMS at `src/data/firms.py:85` to use it. Wire ocean_sst's new fetch (2a) to use it too. Other sources can adopt later.

**Files:** `src/data/_http.py` (new), `src/data/firms.py`, `tests/test_firms.py` (retry-on-transient using the `responses` library already in deps).

### Phase 2 acceptance

- 3 consecutive alerts crons show `ocean_sst: success` (or `success` via fallback if 2a chose option B), `river_gauges: success` with flood flag present in event records, `firms: success` with retry-recovery visible in logs but no failures escalated.
- `state.source_health.ocean_sst.last_success_ts` < 2h old.
- Voice-regression cron passes (`gh workflow run voice-regression.yml`).

## Phase 3 — open_meteo "degraded" diagnosis + fix (third PR)

Starts after Phase 2 merges.

`source_status = "degraded"` is triggered at `src/main.py:1572` when GHCN provider has `diff_dates_missing > 0`. The lane's first commit is investigation:

```bash
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json | jq '
  .run_history // [] |
  map(select(.status == "partial_failure" and .mode == "alerts")) |
  map(.sources // [] | map(select(.source == "open_meteo_extreme_signals" and .status == "degraded"))) |
  flatten |
  map(.details.pipeline_metrics.diff_dates_missing)' | head -10
```

Look at the actual `diff_dates_missing` list. Three hypotheses:

- **A**: Recent dates are not yet available upstream (e.g., today-1 isn't published yet at the cron time). Fix: raise trigger from `> 0` to `> 1`, OR add a retry on missing dates before declaring degraded.
- **B**: Specific stations consistently flake. The 3,985-of-11,982 station gap (33% reporting) suggests many configured stations are decommissioned upstream. Fix: prune stale-station list. Audit by sampling 100 stations not in `stations_with_obs` and confirming they're decommissioned upstream (not just flaking).
- **C**: A real partial outage. Fix: keep degraded status but improve diagnostic logging so the next investigator sees the cause faster.

The fix shape depends on the actual `diff_dates_missing` pattern. Don't pre-commit; investigate first.

**Files:** `src/main.py` (degraded trigger), `src/data/ghcn.py` (station list refresh if needed), `tests/test_main.py`, `tests/test_ghcn.py`.

**Acceptance:** 3 consecutive alerts crons show `open_meteo_extreme_signals: success` (not degraded). 24h with zero degraded rows.

## Shared constraints (every commit on this lane)

Memory notes from Andrew that apply to every PR:

- **Verify the wire, not just the code.** For boundary-layer changes (JSON serialization, SDK bodies, DB/Gist writes), verify the bytes that cross the boundary — not just the in-process value.
- **Generalize fixes.** When a bug surfaces through one example (one source, one error mode), fix the class — don't hardcode the example.
- **Vital cwd rule, theheat variant.** Bash cwd defaults to `/Users/andrewpuschel/Documents/Claude`. Always `cd /Users/andrewpuschel/Documents/Claude/theheat &&` before project commands, or use absolute paths, to avoid stray files at the Claude root.
- **Subagent model floor.** Never Haiku for Agent dispatches if you spawn parallel subagents. Sonnet for routine, Opus for high-risk. Pass `model` explicitly.
- **Post-ship flow.** After each phase's `/ship`: confirm CI green; do not auto-merge (Andrew merges). Don't push to main.

## Test conventions

```bash
source .venv/bin/activate && python -m pytest tests/ -q -m "not voice_replay"
python -m mypy src/
```

Full suite is **910 passing today**, mypy clean. Each phase adds tests; final count after Phase 3 should be 935+ passing.

## Per-phase commit / PR sequence

1. Branch `plan-a/source-health-foundation` from `main`.
2. Phase 1 commits → PR → CI green → Andrew merges. Pull main into branch (or re-branch).
3. Phase 2 commits (2a + 2b + 2c, three commits, one PR) → CI green → Andrew merges.
4. Phase 3 commits (investigation commit first, then fix) → CI green → Andrew merges.

Each PR is reviewable in 15-20 min. Don't bundle phases — bundling means longer review cycles and harder rollback.

## Rollback safety

- Phase 1: if `record_source_health` writes corrupt state, the next cron reads from the pre-corruption raw_url (PR #87 fallback) and overwrites. Roll back is safe.
- Phase 2a: if ocean_sst replacement returns garbage data, the schema-drift assertion (Phase 1) catches it; source goes to "failed" status and pipeline continues. No bad draft escapes.
- Phase 2c: if retry helper bugs out, FIRMS falls back to its prior behavior (single-attempt + propagate error). Safe.
- Phase 3: if a degraded-trigger threshold change misfires, the next cron's status report shows it. Revert the threshold constant; ship.
