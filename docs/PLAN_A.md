# Plan A — @theheat data layer soundness

**STATUS: ALL 5 PHASES SHIPPED (2026-05-15).** See [/Users/andrewpuschel/Documents/Claude/theheat/CHANGELOG.md](/Users/andrewpuschel/Documents/Claude/theheat/CHANGELOG.md) 0.7.0.0. PRs: #98 (Phase 4), #99 (Phase 1), #101 + #103 (Phase 5), #102 (Phase 2), #105 (Phase 3). Kept in-repo for handoff continuity and as a reference pattern for multi-phase plans.

---

**Date:** 2026-05-14
**Scope:** Make the bot's data layer sound + know when it breaks
**Estimated total CC time:** 12-16 hours, phased across 5 PRs
**Actual:** ~3 hours wall-clock at ~23 min/lane Conductor pace
**Posture per Andrew:** coverage-first, "tackle EVERYTHING"

## Context

While reviewing the @theheat pipeline against "data flows and tech stack," an empirical audit of state.json (`run_history` last 28h, 8 alerts cycles) revealed the data layer is in worse shape than the handoff suggested:

| Source | Success rate (8 runs) | Status |
|---|---|---|
| `ocean_sst` | **0/8** | Hard-dead. ClimateReanalyzer endpoint returns non-JSON. Marine heatwave detection completely offline. |
| `open_meteo_extreme_signals` | 2/8 success, 6/8 degraded | Main engine running in degraded mode 75% of cycles. Triggered by `diff_dates_missing > 0`. |
| `firms` | 7/8 | Occasional `HTTPSConnectionPool` timeouts. No retry hardening. |
| `river_gauges` | 8/8 "success" | **Lies** — heights flow, but flood-stage flag is dead (USGS endpoint retired). Status code masks real capability loss. |
| 7 other sources | 8/8 | Healthy |
| 7 cadence-gated | n/a | Correctly skipped (Mondays/Fridays/monthly) |

Plus three structural problems exposed by the audit itself:

- `data_source_failures` in state is literally `{}`. The system has no persistent source-health record — `run_history` caps at 20 entries (~28 hours), then the data is lost forever.
- No schema-drift detection. `ocean_sst` silently changed error mode (redirect-loop → JSON-parse) and the pipeline kept reporting "failed" without anyone noticing the failure mode was different.
- state.json is 958 KB on a 900 KB Gist API cap (49% of which is 158 rejected drafts hoarding `review_context`). PR #87 made reads survive truncation; writes are still at risk.

**North star this serves:** before adding new sources (Plan B: cyclones, Plan C: coral DHW, etc.), the existing 14 must be confirmed working AND failure surveillance must exist. Otherwise we're stacking new sources on a foundation that silently rots.

## Phased PR plan

Phasing trades elapsed time for reviewability and rollback safety. Each phase ships its own PR.

### Phase 1 — Source-health observability platform (foundation)

**Goal:** every subsequent phase plugs into this. No restore work before this lands.

**Files:**
- `src/state.py` + `src/state_schema.py` — add `source_health` key: rolling 7-day per-source success/failure/skipped counters + `last_success_ts`, `last_error`, `last_error_ts`. Backfilled to `{}` on existing state.
- `src/data/source_status.py` — extend beyond exception classes. Add `assert_response_schema(payload, required_fields, source_name) -> None` raising `SourceFetchError` on missing keys.
- `src/data/_freshness.py` (new) — `assert_freshness(data_date, source_name, max_age_days) -> None` for cadence-gated sources.
- `src/main.py:1567-1614` — wire `state.record_source_health(...)` next to existing `data_source_failures` writes. Three call sites per source (success / degraded / failed paths).
- `tests/test_source_health.py` (new) — unit tests for the rolling-7d counter, schema-drift assertion, and freshness checks.

**Acceptance:**
- Empty `state.source_health` is created on first run after deploy.
- After 1 alerts cron, every source has a row with last-success/last-error.
- Schema-drift triggers `SourceFetchError` on a synthetic test payload.
- Freshness check fails when `data_date` is older than `max_age_days`.

**Tests:** ~15 new tests, mypy clean, full suite green.

**Estimated CC time:** 4-5 hours.

### Phase 2 — Restore broken sources (uses Phase 1)

**Goal:** ocean_sst back online, river_gauges flood-flag restored, FIRMS retry hardening.

**Sub-task 2a — ocean_sst replacement:**
- Investigate live endpoint state via `curl` to confirm what the endpoint now returns (HTML? empty? error page?).
- Decision tree:
  - If transient (intermittent HTML 5xx): add proper retry + JSON-shape assertion + fallback. Keep current endpoint.
  - If permanently dead: switch to NOAA OISST direct (heavier integration) OR swap purpose to NOAA Coral Reef Watch DHW per-region (more useful editorially and pairs with Plan C anyway).
- Files: `src/data/ocean_sst.py` (replace) + add schema-drift + freshness assertions from Phase 1.

**Sub-task 2b — river_gauges flood-stage:**
- Replace retired USGS WaterWatch endpoint with NWS AHPS gauge JSON (`https://water.weather.gov/ahps2/forecasts.php?type=feed`).
- Files: `src/data/river_gauges.py` — endpoint swap + parser update.
- Add schema-drift assertion so next upstream change fails loud.

**Sub-task 2c — FIRMS retry hardening:**
- Wrap the `requests.get` at `src/data/firms.py:85` in a retry-with-backoff helper. 3 attempts, exponential backoff (1s, 2s, 4s), preserve existing 30s timeout per attempt.
- Files: `src/data/firms.py` + a shared `src/data/_http.py` retry helper (also wired to ocean_sst and any other transient-prone source).

**Tests:**
- `tests/test_ocean_sst.py` — update to match new behavior; add schema-drift test; add live-endpoint-mock for both "returns valid JSON" and "returns garbage HTML" cases.
- `tests/test_river_gauges.py` — re-verify against AHPS schema; add fixture from real AHPS response.
- `tests/test_firms.py` — retry-on-transient-failure test (uses `responses` library; already in deps).

**Acceptance:**
- 3 consecutive alerts crons show `ocean_sst: success`, `river_gauges: success with flood_flag`, `firms: success` (zero retries spent or visible-retry-then-success).
- `state.source_health.ocean_sst.last_success_ts` updates.

**Estimated CC time:** 3-4 hours.

### Phase 3 — Diagnose + fix open_meteo "degraded"

**Goal:** understand why the main engine fires degraded 75% of cycles. Either fix or reclassify.

**Investigation work** (Phase 3 starts as research, codifies as fix):
- Pull 5+ degraded runs from `run_history`, extract `diff_dates_missing` and `pipeline_metrics`. Find the actual pattern of missing dates.
- Hypotheses to test:
  - GHCN comparison dates fail for predictable reasons (recent dates not yet available upstream)
  - Some stations consistently flake in a way the diff_missing logic counts as a failure
  - The 3985-vs-11982 station gap is upstream availability, not a bug — but it might mean the configured station list is stale (stations decommissioned years ago)

**Likely fixes** (one or more):
- Raise the "degraded" trigger from `diff_missing > 0` to `diff_missing > 5` (or % of expected) — accept small per-cycle drift without panic-status.
- Add retry-on-fetch for the specific missing diff dates before declaring degraded.
- Prune the stale-station list (drop stations that haven't reported in N days; rerun the audit).

**Files:** `src/main.py` (the degraded trigger logic), `src/data/ghcn.py` (station list refresh), `tests/test_main.py` + `tests/test_ghcn.py`.

**Acceptance:** 3 consecutive alerts crons show `open_meteo_extreme_signals: success` (not degraded). If we genuinely accept the drift, no "degraded" rows in the next 24h.

**Estimated CC time:** 2-3 hours.

### Phase 4 — State hygiene (the F1 finding)

**Goal:** state.json under 700 KB with headroom for growth.

**Files:**
- `src/state.py` — extend the draft-trim pass to drop rejected drafts with `created_at` older than 30 days. Keep all `pending` and all `posted` indefinitely.
- `tests/test_state.py` — add `test_rejected_drafts_older_than_30_days_are_trimmed` + `test_pending_drafts_never_trimmed` + `test_posted_drafts_never_trimmed`.

**Acceptance:**
- Local test produces a state with 200 mock drafts (mixed status/age), runs trim, confirms result.
- After deploy, next state write should drop ~155 rejected drafts older than 30 days, recovering ~400 KB. Confirm via `wc -c` on gist payload.

**Estimated CC time:** 1 hour.

### Phase 5 — Source-health dashboard view

**Goal:** Andrew sees source health without jq diving.

**Files:**
- `dashboard/` (Next.js) — new route/component reading `state.source_health` and rendering a grid: source name, 7-day success %, last-success timestamp, last-error (truncated). Sort by failure count desc.
- Add `Source Health` tab next to existing `Drafts` / `Suppressed`.

**Acceptance:** Open dashboard, see all 14 sources with their current health. Failing sources red-tagged.

**Estimated CC time:** 2-3 hours.

## Files affected (full inventory)

```
PHASE 1 — Platform                     PHASE 2 — Restore
  src/state.py                            src/data/ocean_sst.py
  src/state_schema.py                     src/data/river_gauges.py
  src/data/source_status.py               src/data/firms.py
  src/data/_freshness.py (new)            src/data/_http.py (new)
  src/main.py                             tests/test_ocean_sst.py
  tests/test_source_health.py (new)       tests/test_river_gauges.py
                                          tests/test_firms.py

PHASE 3 — Open-meteo degraded          PHASE 4 — State hygiene
  src/main.py                             src/state.py
  src/data/ghcn.py                        tests/test_state.py
  tests/test_main.py
  tests/test_ghcn.py                    PHASE 5 — Dashboard
                                          dashboard/app/health/page.tsx (new)
                                          dashboard/app/api/health/route.ts (new)
                                          dashboard/components/SourceHealthGrid.tsx (new)
```

~20 files touched across 5 PRs. No file structure rewrites; all additions and surgical edits.

## NOT in scope

Explicitly deferred to keep Plan A focused:

- **Adding new sources** (cyclones, coral DHW, methane, floods, precip, snow, climate indices). That's Plans B-F.
- **Bundle enrichment for system context** (the #1b lever for editorial system clauses). Separate plan; the F2 architectural shape is locked.
- **Second-pass editorial agent** (#1c). Deferred per Andrew: "we've tried Flash and it has no taste; let's not add models right now."
- **Threshold registry** (centralizing the ~25 magic numbers in scoring.py). Hygiene work; not blocking.
- **main.py monolith** (3,070 lines). Hygiene; refactor would touch this plan's work, so do AFTER Plan A lands.
- **docs/ handoff naming chaos** (root-level dated handoff files). Trivial; capture as a small cleanup PR anytime.
- **Refactoring 14 source modules to a common base class.** High churn, low payoff. Each module's quirks are real (NIFC tier dedup, GHCN normalization, etc.) and would leak through any abstraction. Schema-drift + freshness assertions (Phase 1) deliver the same observability without the rewrite.

## What already exists (reuse — don't rebuild)

- **`state.increment_data_source_failure` / `state.reset_data_source_failure`** at `src/main.py:1604,1614` — Phase 1 extends these rather than replacing.
- **`source_status` field in run records** at `src/main.py:1567-1614` — already records `success` / `degraded` / `failed`. Phase 1 persists this into `state.source_health` for the rolling 7-day view; doesn't replace the per-run record.
- **`responses` library in `requirements.txt`** — Phase 2c uses it for FIRMS retry-on-transient-failure tests (no new dep).
- **`_REQUEST_HEADERS` pattern** at `src/data/ocean_sst.py:30` and `src/data/nws_alerts.py` — Phase 2a + 2c follow this convention for the shared `_http.py` retry helper.
- **`SourceFetchError` / `SourceSkipped` at `src/data/source_status.py`** — Phase 1 extends rather than replaces.

## ASCII data flow with Phase 1 instrumentation

```
                        +------------------+
   raw source fetch --->| schema-drift     |---> SourceFetchError on shape mismatch
                        | assertion (P1)   |
                        +--------+---------+
                                 | shape OK
                                 v
                        +------------------+
                        | freshness        |---> SourceFetchError on stale data
                        | assertion (P1)   |
                        +--------+---------+
                                 | fresh
                                 v
                        +------------------+
                        | existing parse + |
                        | event extraction |
                        +--------+---------+
                                 v
                        +------------------+
                        | record_source_   |---> state.source_health[source]
                        | health(P1)       |     rolling 7d: success/failed/skipped
                        +------------------+     last_success_ts, last_error, last_error_ts
                                 v
                                ...existing pipeline (dedup → score → ...)...
```

## Verification end-to-end

### Per-phase acceptance criteria

| Phase | Pre-deploy check | Post-deploy check |
|---|---|---|
| 1 | mypy clean, 15+ new tests pass, full suite ≥925 pass | `gh gist view ... -f state.json \| jq '.source_health'` returns rows for all 14 sources after first cron |
| 2 | mypy clean, ocean_sst/river_gauges/firms tests pass with fixtures matching live responses | 3 consecutive alerts crons show `ocean_sst:success`, `river_gauges:success`, `firms:success`. `state.source_health.ocean_sst.last_success_ts` < 2h old. |
| 3 | mypy clean, ghcn diff_missing tests pass | 3 consecutive alerts crons show `open_meteo_extreme_signals:success` (not degraded). 24h with zero degraded rows in state. |
| 4 | mypy clean, state-trim tests pass | After first cron post-deploy: state.json size drops to ~500-550 KB. Confirm with `gh gist view ... -f state.json \| wc -c`. |
| 5 | Dashboard renders source-health grid locally; lint clean | Visit dashboard `/health` route on Vercel; all 14 sources visible with status colors. |

### Regression guards

- Run **voice-regression cron manually** after each phase merges: `gh workflow run voice-regression.yml`. Threshold change in PR #96 already passed; this plan touches no writer/prompt surface, so 12/12 should hold.
- After Phase 2 lands: verify the next alerts cron produces ≥1 new draft (signaling open_meteo + ocean_sst + firms all healthy). If draft volume drops to 0, roll back Phase 2 commit.

## Failure modes

For each new codepath:

| Codepath | Failure mode | Test? | Handler? | User-visible? |
|---|---|---|---|---|
| `record_source_health` | state write races on concurrent crons | yes | append-only counter, idempotent | no |
| `assert_response_schema` | upstream adds optional field (false positive) | yes — test with extra fields | passes (only checks required) | no |
| `assert_freshness` | clock skew between cron and source | yes | tolerance window | no |
| FIRMS retry helper | upstream returns 200 with empty body | yes | schema-drift catches it | yes — degraded status |
| ocean_sst replacement | upstream re-redirects in new way | yes — mock 3xx response | retry exhausts → failed status | yes — degraded then failed |
| state trim | edge case: 200 drafts all rejected >30d | yes | all dropped, keep newest 10 by created_at as a guardrail | no |
| AHPS parser | NWS feed schema changes | yes — schema-drift | fails loud | yes — flood reports stop |
| dashboard render | source_health is empty pre-Phase-1 deploy | yes | empty-state UI | yes — "no health data yet" |

**Critical-gap check** (no test AND no handler AND silent): none. Every new codepath has either a test, a handler, or both.

## Worktree parallelization strategy

Phases are mostly sequential because Phase 1 is foundation. Two parallelization opportunities:

| Phase | Modules touched | Depends on |
|---|---|---|
| P1 Platform | state, source_status, main.py wiring | — |
| P2 Restore | src/data/ocean_sst, river_gauges, firms | P1 (uses health API + schema assertion) |
| P3 Open-meteo degraded | main.py degraded trigger, ghcn.py | P1 |
| P4 State hygiene | state.py trim | — (independent) |
| P5 Dashboard | dashboard/ Next.js | P1 (reads source_health) |

**Lane A** (`docs/conductor-lanes/05-plan-a-foundation.md`): P1 → P2 → P3 (sequential, all share `src/main.py` and `src/data/`)
**Lane B** (`docs/conductor-lanes/06-plan-a-state-trim.md`): P4 (independent, ships anytime)
**Lane C**: P5 (waits for P1, then independent — touches `dashboard/` only; brief not yet authored)

**Recommended execution order:** Lane A and Lane B in parallel Conductor workspaces → merge both → Lane A continues P2 → P3 → Lane C launches.

## Open investigations (Phase 0 work, done as part of each phase)

These can't be resolved without live probing or deeper code reads; each becomes the first commit of its phase:

1. **What does ocean_sst's endpoint actually return now?** `curl -A "..." https://climatereanalyzer.org/clim/sst_daily/json/oisst2.1_world_sst_day.json -i` — see status code + first 200 chars of body. Decides Phase 2a's path.
2. **What's the diff_missing pattern in degraded open_meteo runs?** Pull 5 degraded run records, examine `details.pipeline_metrics.diff_dates_missing`. Decides Phase 3 fix shape.
3. **What's the NWS AHPS gauge feed schema?** WebFetch the AHPS XML/JSON feed, confirm flood-stage flag is in the response. Decides Phase 2b parser shape.
4. **Are the 11,982 GHCN stations all still reporting upstream?** Sample 100 stations not in last-day-with-obs and confirm they're decommissioned vs flaking. Decides whether Phase 3 includes a station-list prune.

## Risk register

- **Low**: schema-drift assertions too strict — might fire on optional-field additions upstream. Mitigation: assertions check `required` fields, not field count.
- **Low**: state.source_health write contention — runs are sequential by design (one cron at a time per GitHub Actions). Mitigation: idempotent counter updates.
- **Medium**: ocean_sst replacement endpoint also unreliable. Mitigation: include fallback source (NOAA OISST direct or skip-gracefully). The bot has lived without MHW signals for weeks; another cycle isn't catastrophic.
- **Medium**: open_meteo "degraded" turns out to be a real partial outage (33% station-reporting is suspicious). Mitigation: investigation in Phase 3 surfaces the real cause before the fix lands.
- **Low**: dashboard view shows scary "0/8 success" data on first deploy. Mitigation: empty-state UI for source-health key not yet populated.

## Out-of-scope reminders (for handoff continuity)

After Plan A lands, next plans in this initiative:
- Plan B: Bucket 2 (Coral Reef Watch DHW + CH4 methane) — pairs with restored ocean_sst infrastructure.
- Plan C: Bucket 3 (Tropical cyclones — NHC + JTWC). Atlantic season starts June 1; useful to land before.
- Plan D: Bucket 4 (global floods — Copernicus EMS).
- Plan E: Bucket 5 (precipitation + snow).
- Plan F: Bucket 6 (NAO/AO/PDO/ozone indices).

Plus the editorial-side work that's deferred but tracked:
- F2 bundle enrichment helper for system clauses (#1b)
- F3 second-pass editorial agent — not Flash (#1c, post-#1b)
- Threshold registry
- main.py monolith refactor
