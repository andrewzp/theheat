# Source-To-Triage-To-Writer Simplification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Implemented locally on `codex/source-triage-writer-gateway` after `/plan-eng-review` on 2026-05-19.

**Goal:** Make the data path elegant and simple: every source collects facts, every candidate goes through deterministic triage, and the writer only sees a small, neat, audited evidence packet after global ranking.

**One rule:** ordinary source runners are not allowed to call the writer path. They only submit candidates.

```text
Sources collect facts.
Triage chooses what matters.
StoryBundle organizes the chosen facts.
Writer writes.
Validators check.
Publisher publishes.
```

## Target Architecture

Do not invent a parallel writer-brief system in the first pass. The existing `StoryBundle` is already the writer brief, and the evidence-contract work already made it auditable. The simplification is to make the existing queue the only door into the writer.

```text
raw APIs / files / feeds
        |
        v
source runners
  - fetch data
  - detect events
  - compute score
  - build StoryBundle
  - enqueue candidate
        |
        v
transient triage queue
  - audit bundle before enqueue
  - hold score, source, review context, side-effect callback
        |
        v
select_survivors()
  - global ranking
  - per-category cap
  - global draft cap
  - triage suppression ledger
        |
        v
_drain_and_write_triage_queue()
  - only survivors call _try_two_bot_draft()
  - source telemetry credited here
  - success-only side effects fire here
        |
        v
generate_draft()
  - evidence contract defense-in-depth
  - MemorySlice
  - writer
  - safety
  - claim extractor
  - fact-check
  - critic
        |
        v
draft saved for human approval
```

## Step 0 Scope Challenge

### What Already Exists

| Existing piece | File | Reuse decision |
|---|---|---|
| `StoryBundle` | `src/two_bot/types.py` | Reuse as the writer brief. Do not add `WriterBrief` yet. |
| `TriageCandidateBundle` | `src/two_bot/types.py` | Reuse as the queue item. It already carries bundle, score, source, review context, cooldown data, and success callback. |
| `_enqueue_candidate()` | `src/orchestrator/common.py` | Keep as the low-level append helper. Add one higher-level helper around it so sources do not repeat dataclass plumbing. |
| `_drain_and_write_triage_queue()` | `src/orchestrator/common.py` | Reuse as the only writer gateway. Strengthen telemetry and invalid-bundle behavior. |
| `select_survivors()` | `src/orchestrator/triage.py` | Reuse deterministic ranking and caps. |
| `evidence_contract.py` | `src/two_bot/evidence_contract.py` | Reuse to audit bundles before enqueue and again before writer. |
| Coral DHW migration | `src/orchestrator/sources/coral_dhw.py` | Treat as the reference implementation for source migration and success-only side effects. |
| Triage tests | `tests/test_triage.py`, `tests/test_main.py`, `tests/test_coral_dhw.py` | Extend rather than rewrite. |

### Minimum Complete Change

The minimum complete version is:

1. Add one explicit queue helper in `src/orchestrator/common.py`.
2. Migrate all source runners away from direct `_try_two_bot_draft()` calls.
3. Preserve source-specific side effects by moving draft-only effects into `on_draft_success`.
4. Add a static regression test that fails if a source calls `_try_two_bot_draft()` again.
5. Add source-run telemetry for `triaged_in`, `triaged_out`, `writer_attempted`, and `drafted`.
6. Add GPM IMERG fail-fast for auth/provider-class repeated failures.

That is more than eight files, which is normally a smell. Here it is justified because the issue is architectural drift across many small source modules. The way to keep it simple is not a new framework. It is one helper, one invariant, and mostly mechanical source edits.

### Search Check

No new external infrastructure, queue provider, scheduler, or framework pattern is needed. This is **[Layer 1]** work: use the existing in-process transient queue and Python dataclasses. An external queue would be strictly worse right now because candidates are per-cron, non-persistent by design, and must not replay next cycle.

### TODOS Cross-Reference

No repo `TODOS.md` exists. This plan should not create deferred TODOs for the core invariant. The direct source-to-writer path is the problem. Deferring that invariant would preserve the bug-shaped architecture.

### Completeness Check

Complete version: migrate every ordinary source into the queue and enforce it with a test.

Shortcut version: migrate only the noisy sources. Reject this. It saves little implementation time with Codex and leaves the architecture ambiguous. Ambiguous architecture is how we got here.

### Distribution Check

No new artifact type is introduced. No package, binary, container, or release pipeline changes are required.

## Architecture Review

### 1. Direct source-to-writer calls bypass the intended decision point

`src/orchestrator/run_alerts.py` already documents the mixed state: unmigrated sources call `_try_two_bot_draft()` directly, bypass triage, then later count against `MAX_DRAFTS_PER_CYCLE` through pruning.

**Recommendation:** remove direct calls from source modules. Only `src/orchestrator/common.py` should call `_try_two_bot_draft()`, inside `_drain_and_write_triage_queue()`.

**Tradeoff:** this touches many source files, but the edits are mechanical and make the architecture much easier to reason about.

### 2. Side-effect timing is the main migration risk

Some state changes mean "we observed this data." Other state changes mean "we drafted this story." Those cannot be treated the same.

```text
safe before draft success:
  - source health
  - fetch status
  - observation history
  - raw data tracking that should reflect ingestion

must wait for draft success:
  - state.record_event()
  - annual drafted counters
  - tier/cooldown state that would suppress future redetection
  - any "last drafted" marker
```

**Recommendation:** each source migration must classify side effects explicitly. Use `on_draft_success` for draft-only side effects. Leave pure ingestion tracking in the source runner.

### 3. Bad bundles should not consume survivor slots

The pipeline already audits bundles before spending writer tokens. That is good defense-in-depth. But if audit happens only after triage, a broken bundle can win a top-three slot and then die before writer, wasting that slot.

**Recommendation:** the new queue helper should audit before enqueue. Error bundles should record an `evidence_contract` suppression and not enter the queue. Keep the pipeline audit as the second line of defense.

### 4. Do not add `WriterBrief` yet

The user goal is "triaged and presented neatly to the writer." The tempting move is a new `WriterBrief` class. Do not do that in this PR. `StoryBundle` already is the brief, and a second near-identical object would create sync bugs.

**Recommendation:** make `StoryBundle` cleaner by ensuring only triage survivors reach it, not by adding another brief layer.

## Code Quality Review

### 1. Add one helper to remove source-level boilerplate

Every migrated source needs to build a `TriageCandidateBundle` with the same fields. Duplicating that in 20 files invites field drift.

Add a small helper in `src/orchestrator/common.py`:

```python
def _enqueue_story_candidate(
    bot_state: BotState,
    *,
    bundle: StoryBundle,
    score: EditorialScore,
    source: str,
    legacy_type: str,
    event_id: str,
    review_context: dict,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
    on_draft_success: Callable[[], None] | None = None,
) -> bool:
    ...
```

Return `True` when the candidate entered the queue, `False` when the candidate was rejected before enqueue.

Keep `_enqueue_candidate()` as the low-level primitive for tests and unusual cases.

### 2. Add a regression test for the architecture boundary

Add a test that walks source files and fails on direct calls to `_try_two_bot_draft()` outside the allowed gateway.

Allowed:

- `src/orchestrator/common.py`, definition and drain call
- tests that deliberately patch the gateway

Not allowed:

- `src/orchestrator/sources/*.py`
- `src/orchestrator/hot10.py`
- source helper paths that run inside alert collection

This is the cheap insurance policy.

### 3. Keep migration commits grouped by source complexity

Do not migrate `open_meteo` first. It has multiple sub-signals and synthesis/streak side effects. Start with small, single-event sources so the helper and tests settle before the hardest file.

## Test Review

### Existing Coverage

```text
CODE PATH COVERAGE
==================
[+] triage selection
    |-- [3-star TESTED] rank + per-category/global caps - tests/test_triage.py
    |-- [3-star TESTED] triage exception falls through and clears queue - tests/test_triage.py
    `-- [2-star TESTED] suppression attribution for triage spills - tests/test_triage.py

[+] queue drain
    |-- [3-star TESTED] drain calls writer for survivors only - tests/test_main.py
    |-- [2-star TESTED] triage disabled writes all queued candidates - tests/test_main.py
    `-- [GAP] invalid bundle rejected before consuming survivor slot

[+] source migration pattern
    |-- [3-star TESTED] coral enqueues instead of drafting - tests/test_coral_dhw.py
    |-- [3-star TESTED] coral success callback fires only after draft success - tests/test_coral_dhw.py
    `-- [GAP] every other source still needs source-specific migration coverage

[+] writer pipeline
    |-- [3-star TESTED] evidence contract blocks writer before token spend - tests/two_bot/test_pipeline.py
    |-- [3-star TESTED] writer/fact-check/critic kill stages - tests/two_bot/test_pipeline.py
    `-- [GAP] queue helper should audit before enqueue, not only in pipeline

USER/OPERATOR FLOW COVERAGE
===========================
[+] scheduled alert run
    |-- [2-star TESTED] run_alerts drains queue after sources - tests/test_main.py
    |-- [GAP] all migrated sources contribute to global triage before writer
    `-- [GAP] source telemetry shows promoted vs triaged vs attempted vs drafted

[+] production debugging
    |-- [2-star TESTED] source health records triage errors - tests/test_triage.py
    `-- [GAP] GPM auth/provider failure fails fast instead of looping through 75 cities

----------------------------------------
COVERAGE: existing core queue is covered, migration invariant is not
CRITICAL GAPS: 4
  1. source-level direct-call guard
  2. per-source migration tests
  3. pre-enqueue invalid-bundle rejection
  4. GPM fail-fast regression test
----------------------------------------
```

### Required Test Additions

- [ ] Add `tests/test_source_triage_migration.py`.
- [ ] Test that source modules do not call `_try_two_bot_draft()` directly.
- [ ] Test `_enqueue_story_candidate()` enqueues a valid bundle and returns `True`.
- [ ] Test `_enqueue_story_candidate()` rejects an invalid bundle, returns `False`, records an `evidence_contract` suppression, and does not consume a triage slot.
- [ ] Test `_drain_and_write_triage_queue()` records `triaged_in`, `triaged_out`, `writer_attempted`, and `drafted` per source.
- [ ] For each migrated simple source, add one source-runner test asserting a passing event enqueues and does not call `_try_two_bot_draft()`.
- [ ] For sources with success-only side effects, add one callback test asserting the side effect fires only when the drain saves a draft.
- [ ] Add `tests/test_gpm_imerg.py` coverage for strict fail-fast on `401`/`403` and repeated identical provider errors.
- [ ] No LLM eval is required for this plan because the writer prompt does not change. If the memory payload is changed later, run `tests/voice_regression/` as a separate eval decision.

## Performance Review

### 1. LLM token burn

Current behavior lets many source candidates enter writer/fact-check/critic before global pruning. That is backwards for efficiency.

**Target behavior:** one cron may observe many signals, but only triage survivors enter `generate_draft()`.

Expected impact:

- Fewer writer calls on noisy days.
- Fewer claim extraction/fact-check/critic calls.
- More predictable cost because `MAX_DRAFTS_PER_CYCLE` becomes a pre-writer cap, not just a post-draft cap.

### 2. GPM IMERG runtime waste

GPM currently can keep looping after auth-class failures. Recent production logs showed 75 HTTP 401 failures costing about 72 seconds before the source failed.

**Target behavior:** in strict production fetches, fail immediately on 401/403 and after a small number of identical provider-class errors.

### 3. Memory payload size

`MemorySlice.shipped_tweet_texts` currently sends up to 100 full shipped tweets to the writer. This is a real token target, but it touches voice quality.

**Recommendation:** defer to a separate prompt/memory pass. Do not combine prompt-context reduction with source migration.

### 4. Scheduled CI cost

The scheduled bot workflow still runs full tests on most schedule events. That costs runtime, not writer tokens.

**Recommendation:** defer. First fix the source-to-writer architecture. CI split is operational cleanup, not the core data-flow defect.

## Implementation Tasks

### Phase 1: Add The Single Queue Helper

- [ ] Add `_enqueue_story_candidate()` to `src/orchestrator/common.py`.
- [ ] Inside the helper, call `audit_story_bundle(bundle)` before enqueue.
- [ ] If audit errors exist, record an `evidence_contract` suppression and return `False`.
- [ ] If audit passes, build `TriageCandidateBundle` and call `_enqueue_candidate()`.
- [ ] Keep `generate_draft()` evidence audit unchanged as defense-in-depth.
- [ ] Add generic source-run telemetry bump helper, for example `_bump_source_field_in_run(current_run, source, field, amount=1)`.
- [ ] Keep `_bump_source_drafted_in_run()` as a wrapper or compatibility shim.

### Phase 2: Strengthen Drain Telemetry

- [ ] In `_drain_and_write_triage_queue()`, count queued candidates by source before selection.
- [ ] Count survivors by source after selection.
- [ ] For every queued source, write:
  - `triaged_in`
  - `triaged_out`
  - `writer_attempted`
  - `drafted`
- [ ] Preserve existing `drafted` behavior for dashboard compatibility.
- [ ] Ensure triage exception fallback still clears the queue and marks triage degraded.

### Phase 3: Migrate Simple Sources

Use this source pattern:

```text
fetch readings
  -> detect events
  -> duplicate/cap gates
  -> score
  -> _should_draft()
  -> build review_context
  -> build StoryBundle
  -> _enqueue_story_candidate()
  -> record source run with drafted=0
```

Migrate these first:

- [ ] `src/orchestrator/sources/nws_alerts.py`
- [ ] `src/orchestrator/sources/gdacs.py`
- [ ] `src/orchestrator/sources/copernicus_ems.py`
- [ ] `src/orchestrator/sources/river_gauges.py`
- [ ] `src/orchestrator/sources/co_ops.py`
- [ ] `src/orchestrator/sources/marine.py`
- [ ] `src/orchestrator/sources/ocean_sst.py`
- [ ] `src/orchestrator/sources/sea_ice.py`
- [ ] `src/orchestrator/sources/drought.py`
- [ ] `src/orchestrator/sources/enso.py`
- [ ] `src/orchestrator/sources/co2.py`
- [ ] `src/orchestrator/sources/methane.py`
- [ ] `src/orchestrator/sources/ozone_hole.py`
- [ ] `src/orchestrator/sources/gpm_imerg.py`
- [ ] `src/orchestrator/sources/nsidc_snow.py`
- [ ] `src/orchestrator/sources/nifc.py`
- [ ] `src/orchestrator/sources/ice_mass.py`
- [ ] `src/orchestrator/sources/climate_indices.py`
- [ ] `src/orchestrator/sources/synthesis.py`
- [ ] `src/orchestrator/hot10.py`

For every source:

- [ ] Remove direct `_try_two_bot_draft()` call.
- [ ] Replace with `_enqueue_story_candidate()`.
- [ ] Keep `source_promoted` as "passed deterministic gates."
- [ ] Set local `source_drafted = 0`; drain credits actual drafts.
- [ ] Move draft-only side effects into `on_draft_success`.
- [ ] Keep ingestion tracking outside the callback when it reflects observed data, not drafted data.

### Phase 4: Migrate Complex Shared Paths

- [ ] Migrate cyclone helper calls in `src/orchestrator/common.py` without breaking NHC/JTWC source attribution.
- [ ] Migrate `src/orchestrator/sources/open_meteo.py` last.
- [ ] For `open_meteo`, handle each sub-signal separately:
  - strongest city record/anomaly
  - record streak
  - country record
  - simultaneous records
- [ ] Keep synthesis-component recording behavior explicit. If a component is meant to exist even without a tweet, leave it before draft success. If it means "drafted this story", move it into success callback.

### Phase 5: Add The Boundary Guard

- [ ] Add a static test that fails if `_try_two_bot_draft(` appears in source modules.
- [ ] Allow only:
  - definition in `src/orchestrator/common.py`
  - call inside `_drain_and_write_triage_queue()`
  - tests and comments that intentionally describe the invariant
- [ ] Update `src/orchestrator/run_alerts.py` comment once migration is complete. It should say all ordinary sources enqueue candidates and only the drain writes.

### Phase 6: GPM IMERG Fail-Fast

- [ ] In `src/data/gpm_imerg.py`, detect `requests.HTTPError` statuses.
- [ ] In strict mode, raise immediately for `401` and `403`.
- [ ] In strict mode, stop after a small number of identical provider-class failures.
- [ ] Preserve non-strict skip behavior for local runs.
- [ ] Keep the first failure diagnostic in the error message.

## Failure Modes

| New or changed path | Real production failure | Test required | Error handling target | User/operator impact |
|---|---|---|---|---|
| `_enqueue_story_candidate()` | Builder returns an invalid bundle | invalid bundle test | suppression stage `evidence_contract`; no enqueue | Dashboard shows source problem, writer slot preserved |
| source migration | `state.record_event()` fires before triage and suppresses future redetection | per-source callback test | draft-only effects inside `on_draft_success` | No silent loss of future valid candidates |
| drain telemetry | Source row missing when drain credits drafted | telemetry no-op test | no crash; best-effort counters | Dashboard may miss counter, cron still succeeds |
| triage exception fallback | `select_survivors()` raises | existing tests plus telemetry assertion | degraded triage health, clear queue, legacy passthrough | Output preserved, issue visible |
| GPM fail-fast | Earthdata token invalid | 401/403 strict test | raise `SourceFetchError` immediately | Run fails fast with useful diagnosis |
| open_meteo migration | synthesis component moved behind draft success by mistake | open_meteo-specific regression test | explicit side-effect classification | Synthesis does not silently lose source facts |

Critical gap to close before implementation is considered done: no source-level direct-call guard exists today.

## NOT In Scope

- New `WriterBrief` class. `StoryBundle` is the writer brief for this pass.
- Writer prompt rewrite.
- Memory payload reduction from 100 shipped tweets.
- New external queue or persistent candidate table.
- Editorial threshold changes.
- Posting, approval, or publisher changes.
- Dashboard redesign.
- CI workflow split between push and schedule.
- Local `data/` cleanup or GHCN bootstrap tooling.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|---|---|---|
| Common queue helper and telemetry | `src/orchestrator/common.py`, `tests/test_triage.py`, `tests/test_main.py` | - |
| Simple disaster/marine/atmospheric source migrations | `src/orchestrator/sources/`, source tests | Common helper |
| GPM fail-fast | `src/data/gpm_imerg.py`, data tests | - |
| Complex `open_meteo` and cyclone migration | `src/orchestrator/sources/open_meteo.py`, `src/orchestrator/common.py`, tests | Common helper, simple migrations |
| Boundary guard and docs | tests, `src/orchestrator/run_alerts.py`, docs | All migrations |

Parallel lanes:

```text
Lane A: common helper + telemetry -> boundary guard
Lane B: GPM fail-fast
Lane C: simple source migrations, after Lane A helper lands
Lane D: open_meteo/cyclone migration, after Lane C proves the pattern
```

Execution order:

1. Land Lane A and Lane B together or sequentially.
2. Launch simple source migrations in batches if using multiple worktrees, but keep each batch source-family scoped.
3. Merge simple migrations.
4. Do `open_meteo` and cyclone last.
5. Turn on the boundary guard once the final direct call is gone.

Conflict flags:

- Lane A and cyclone migration both touch `src/orchestrator/common.py`; keep cyclone after the helper lands.
- Multiple workers touching `src/orchestrator/sources/open_meteo.py` is not worth it. Do that file sequentially.

## Verification Commands

Run targeted tests first:

```bash
./.venv/bin/python -m pytest tests/test_triage.py tests/test_main.py tests/test_coral_dhw.py tests/two_bot/test_pipeline.py -q
```

Run new migration tests:

```bash
./.venv/bin/python -m pytest tests/test_source_triage_migration.py tests/test_gpm_imerg.py -q
```

Run the repo-standard non-voice suite:

```bash
./.venv/bin/python -m pytest tests/ -q -m "not voice_replay"
ruff check src/ tests/
mypy src/
```

If prompt or memory payload changes are later added, also run the voice replay suite intentionally. Do not sneak prompt changes into this migration.

## Acceptance Criteria

- [ ] `rg "_try_two_bot_draft\\(" src/orchestrator` shows no ordinary source direct calls.
- [ ] Only `_drain_and_write_triage_queue()` calls `_try_two_bot_draft()` in production code.
- [ ] Every source that passes deterministic gates enqueues a `TriageCandidateBundle`.
- [ ] Triage survivors are the only candidates that enter `generate_draft()`.
- [ ] Invalid bundles are rejected before enqueue and do not consume survivor slots.
- [ ] Draft-only side effects fire only after a saved draft.
- [ ] Source telemetry separates observed, promoted, triaged, attempted, and drafted.
- [ ] GPM auth/provider failures fail fast in strict production mode.
- [ ] Full non-voice test suite, ruff, and mypy pass.

## Completion Summary

- Step 0: Scope Challenge - complete migration accepted despite touching many files because it removes one architectural ambiguity instead of adding new infrastructure.
- Architecture Review: 4 issues found.
- Code Quality Review: 3 issues found.
- Test Review: diagram produced, 4 critical gaps identified.
- Performance Review: 4 issues found.
- NOT in scope: written.
- What already exists: written.
- TODOS.md updates: 0 items proposed because no `TODOS.md` exists and the core work should not be deferred.
- Failure modes: 1 critical gap flagged, the missing source-level direct-call guard.
- Outside voice: skipped for now.
- Parallelization: 4 lanes, 2 initial parallel lanes, then sequential migration hardening.
- Lake Score: 1/1 recommendation chose the complete option.

## Implementation Completion

- Added the single `_enqueue_story_candidate()` source boundary and pre-enqueue evidence audit.
- Migrated ordinary alert sources, Hot 10, cyclone handling, and Open-Meteo sub-signals so they enqueue candidates instead of calling the writer directly.
- Moved draft-only state mutations into `on_draft_success` callbacks while leaving ingestion tracking in source runners.
- Added source-run telemetry for `triaged_in`, `triaged_out`, `writer_attempted`, and drain-credited `drafted`.
- Added the static source-to-writer boundary guard, enqueue helper tests, drain telemetry coverage, GPM fail-fast tests, and source callback regressions.
- Verified with full non-voice Python tests, ruff, mypy, dashboard tests, and dashboard production build.
