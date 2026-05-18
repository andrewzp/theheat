# Code-First Triage — Design

**Date:** 2026-05-17
**Branch:** TBD (`fix/code-first-triage` or similar)
**Source brief:** Conversation 2026-05-17 — "use code (not LLMs) to organize input data so we don't have LLMs going crazy and burning through credits"

## 1. Mission

Insert a deterministic triage stage between bundle build (`intern`) and the writer so the bot's per-cycle LLM call volume is capped by code, not by how many events the sources happen to surface that day. The architectural target — picked by the user 2026-05-17 — is **source-growth-proof flat-line cost**: doubling the source count should not double the credit burn.

Today's pipeline calls the writer (Sonnet 4.6) per-bundle as each source runs. Per-cycle cap (`MAX_DRAFTS_PER_CYCLE = 3`) is enforced AFTER the writer has already paid for every draft, and the critic kills ~56% of writer outputs (22 of 39 in the last 200-suppression window). Both are credit burned for drafts that were going to be discarded anyway.

The triage stage flips that. Sources build candidate bundles, append them to a per-cycle queue, and the orchestrator applies ranking + per-category cap + global cap BEFORE any LLM stage runs. Only survivors reach the writer.

## 2. Key decisions

| # | Decision | Value |
|---|---|---|
| 1 | MVP scope | Triage stage with score ranking + per-category cap + global cap. Cross-source coalescing deferred to Phase 2 (not required when per-category cap is in place). |
| 2 | Where it slots | Between `intern` (bundle build) and `writer` (LLM tweet composition). Orchestrator-level, not source-level. |
| 3 | Global cap | `MAX_DRAFTS_PER_CYCLE = 3` (unchanged from today's post-writer prune). Enforced earlier. |
| 4 | Per-category cap | `PER_CATEGORY_TRIAGE_CAP = 2` (default). Max 2 candidates per `signal_kind` per cron. Configurable via env override `THEHEAT_PER_CATEGORY_CAP`. |
| 5 | Ranking key | `(EditorialScore.total DESC, created_at DESC)`. Existing per-category thresholds in `src/editorial/thresholds.py` remain the score-gate FLOOR; triage is the ceiling. |
| 6 | Spilled candidates | Recorded as `kill_stage="triage_cap"` in the suppression ledger so the dashboard surfaces them. Spilled candidates are NOT auto-queued for next cron — re-detection is the source's responsibility (most sources re-fire the same event for several cycles until cooldown). |
| 7 | Coalescing (Phase 2) | Deferred AND the rule definition needs work. Naive `(signal_kind, lat-1°-bucket, lon-1°-bucket, date)` would merge distinct reefs / fires / cities that just happen to be geographically adjacent. Correct rule: coalesce only when multiple sources surface the **same event** (e.g., GDACS flood + Copernicus EMS flood + Open-Meteo precip on the same Indonesian flood — same date, same admin region, three distinct sources). Bucket-by-coordinate alone is wrong. Phase 2 — ship only if production data shows real cross-source overlap pattern, and only with same-event semantics, not same-bucket semantics. |
| 8 | Backward compat | Existing source runners migrate one at a time. Source runners not yet migrated still call the writer directly (no behavior change). New `_try_two_bot_draft_deferred` helper is the migration target. |
| 9 | Kill-switch | `THEHEAT_TRIAGE_ENABLED=0` env var bypasses triage entirely and uses the legacy direct-writer path. Lets ops roll back without a deploy if triage over-suppresses. |
| 10 | Telemetry | Per-source `drafted` counter is unchanged — debit happens when writer actually fires for the source's survivor. Per-source `triaged_in` and `triaged_out` counters added for ops visibility. |
| 11 | Test coverage | New `src/orchestrator/triage.py` module gets its own test file. Unit tests for ranking, per-category cap, global cap, kill-switch, telemetry. Pipeline integration tests verify deferred candidates reach the writer in priority order. |
| 12 | Rollout | Ship triage module + kill-switch off by default (one PR). Migrate `coral_bleaching` source first (highest monoculture pressure: 9 of 15 pending today). Enable kill-switch ON. Watch one cycle. Migrate remaining sources lane by lane. |

## 3. Architecture

```
run_alerts cycle (post-triage)
├── Phase 1: SOURCES (parallel-eligible, no LLM)
│   ├── each source runner builds bundles, scores them,
│   │   passes _should_draft() (existing score gate)
│   └── INSTEAD of calling _try_two_bot_draft(): appends to
│       bot_state["_triage_queue"] via _try_two_bot_draft_deferred()
│
├── Phase 2: TRIAGE (deterministic, no LLM)            ← NEW
│   └── triage.select_survivors(bot_state, queue)
│       ├── coalesce (Phase 2 only — skip in MVP)
│       ├── rank by (score.total DESC, created_at DESC)
│       ├── enforce per-category cap (default 2)
│       ├── enforce global cap (MAX_DRAFTS_PER_CYCLE)
│       └── record spilled as kill_stage="triage_cap"
│   └── returns list[CandidateBundle] of survivors
│
└── Phase 3: WRITE (LLM, cost-bounded by Phase 2 output) ← UNCHANGED
    └── for each survivor:
        └── _try_two_bot_draft(survivor.bundle, ..., source=survivor.source)
            └── generate_draft() — full existing pipeline
                (writer → safety → claim → fact_check → critic → memory)
```

## 4. New types

In `src/two_bot/types.py`:

```python
@dataclass(frozen=True)
class CandidateBundle:
    """A scored bundle queued for the triage stage. Source runners build
    these and append to bot_state['_triage_queue']; the triage stage
    ranks/caps them and the survivors enter the writer pipeline.

    Carries all the arguments _try_two_bot_draft() needs so the writer
    call site stays unchanged.
    """
    bundle: StoryBundle
    score: EditorialScore
    event_id: str
    source: str                 # source_key for telemetry
    review_context: dict        # for save_draft
    city: str                   # for city cooldown
    tweet_date: str             # for same-day dedup
    cooldown_exempt: bool       # for elite-signal bypass
    legacy_type: str            # for save_draft type field
    created_at: str             # iso8601 — used as triage tiebreaker
```

## 5. Triage algorithm

In new file `src/orchestrator/triage.py`:

```python
from src.two_bot.types import CandidateBundle

PER_CATEGORY_TRIAGE_CAP_DEFAULT = 2

def _per_category_cap() -> int:
    raw = os.environ.get("THEHEAT_PER_CATEGORY_CAP", "")
    try:
        v = int(raw) if raw else PER_CATEGORY_TRIAGE_CAP_DEFAULT
        return max(v, 1)
    except (TypeError, ValueError):
        return PER_CATEGORY_TRIAGE_CAP_DEFAULT


def select_survivors(
    bot_state: BotState,
    queue: list[CandidateBundle],
    *,
    global_cap: int = MAX_DRAFTS_PER_CYCLE,
) -> list[CandidateBundle]:
    """Rank, apply per-category cap, apply global cap. Returns survivors
    in writer-call order. Records spilled candidates as kill_stage=
    'triage_cap' on bot_state."""
    if not queue:
        return []

    ranked = sorted(
        queue,
        key=lambda c: (c.score.total, c.created_at),
        reverse=True,
    )

    cap = _per_category_cap()
    by_category: dict[str, int] = {}
    survivors: list[CandidateBundle] = []
    spilled: list[CandidateBundle] = []

    for i, candidate in enumerate(ranked):
        category = candidate.bundle.signal_kind
        used = by_category.get(category, 0)
        if used >= cap:
            spilled.append(candidate)
            continue
        survivors.append(candidate)
        by_category[category] = used + 1
        if len(survivors) >= global_cap:
            # Global cap hit — everything after this index spills.
            spilled.extend(ranked[i + 1:])
            break

    for candidate in spilled:
        _record_triage_suppression(bot_state, candidate, cap=cap)

    return survivors
```

The `_record_triage_suppression` call sets `kill_stage="triage_cap"` and stores both the per-category cap and the candidate's score so the dashboard can render "9 coral_bleaching candidates this cycle, 2 promoted, 7 capped."

## 6. Source-runner migration

Per source, the change is ~6 lines. Before (existing pattern):

```python
if _try_two_bot_draft(
    bundle, bot_state, score,
    legacy_type="coral_bleaching",
    event_id=event_id,
    review_context=review_context,
    cooldown_exempt=False,
):
    state.record_event(bot_state, event.event_id)
    source_drafted += 1
```

After (deferred):

```python
_enqueue_candidate(
    bot_state,
    CandidateBundle(
        bundle=bundle, score=score, event_id=event_id,
        source="coral_dhw", review_context=review_context,
        city="", tweet_date=event.date,
        cooldown_exempt=False, legacy_type="coral_bleaching",
        created_at=_utc_now_iso(),
    ),
)
# state.record_event + source_drafted increment moved to writer call site
```

The triage queue lives in `bot_state["_triage_queue"]`. **The underscore prefix is NOT a transient convention in this codebase** — by default, anything in `bot_state` is persisted to the gist on the write step. Two explicit guards prevent stale-queue bugs:

1. **Clear on entry.** `run_alerts.py` does `bot_state.pop("_triage_queue", None)` at the very top, before any source runs. This drops any stale queue left behind by a crashed prior cron.
2. **Skip in persist.** Add `"_triage_queue"` to the skip list in `src/storage/sqlite_store.py::_METADATA_JSON_KEYS` (and the dashboard JS state-store allow-list, by NOT adding it). The gist-write step in `src/state.py` skips keys not in the allowed shape.

Both guards are required. Either alone leaves a failure mode: skip-only without clear-on-entry won't help if state-write fails mid-cycle; clear-on-entry without skip-in-persist leaks the queue to the gist between the drain step and the state-write at end of cycle.

A small helper `_drain_and_write_triage_queue(bot_state, current_run)` runs at the END of `run_alerts.py`, after all source runners have completed:

```python
queue = bot_state.pop("_triage_queue", [])
if _triage_enabled():
    survivors = triage.select_survivors(bot_state, queue)
else:
    survivors = queue  # kill-switch: write everything (legacy behavior)

for candidate in survivors:
    if _try_two_bot_draft(
        candidate.bundle, bot_state, candidate.score,
        legacy_type=candidate.legacy_type, event_id=candidate.event_id,
        review_context=candidate.review_context, city=candidate.city,
        tweet_date=candidate.tweet_date, cooldown_exempt=candidate.cooldown_exempt,
    ):
        state.record_event(bot_state, candidate.event_id)
        _bump_source_telemetry(current_run, candidate.source, "drafted", 1)
```

Sources not yet migrated continue calling `_try_two_bot_draft()` directly — those drafts bypass triage. As more sources migrate, more of the cron's draft volume flows through triage. Once all sources are migrated, the legacy direct-call path can be removed.

## 7. Edge cases

| Case | Handling |
|---|---|
| Empty queue (no sources fired) | `select_survivors([])` returns `[]`. No writer calls. |
| Single candidate | Returns the candidate. Per-category cap and global cap both inapplicable. |
| All candidates same category, fewer than cap | All survive. Cap doesn't fire. |
| Tie scores within category | Tiebreaker: `created_at DESC` (most recent wins). Deterministic given the queue order. |
| Spilled candidate had `cooldown_exempt=True` | Still spilled. Cooldown-exempt is a city-cooldown bypass, not a triage-cap bypass. (Elite signals can lose to even more elite signals.) |
| Source enqueues then own re-detection fires | Second `_enqueue_candidate` for same `event_id` is allowed at enqueue. Triage doesn't dedup by event_id — that's the writer-stage's existing duplicate_draft check. |
| Queue contains stale candidate from prior cycle | Should not happen — queue is `bot_state["_triage_queue"]` which the drain step `pop`s. Test guards against this. |
| `THEHEAT_TRIAGE_ENABLED=0` | Queue still gets populated (sources still use `_enqueue_candidate`). Drain step skips triage and writes everything in queue order. Same effective behavior as legacy. |
| Triage module raises | Drain step catches `Exception`, logs `[triage] error: ...`, falls through to legacy (writes everything). Triage MUST NOT take down the whole cron. |

## 8. Test plan

New file `tests/test_triage.py`:

- `test_empty_queue_returns_empty`
- `test_single_candidate_passes_through`
- `test_ranks_by_score_descending`
- `test_per_category_cap_enforced_when_default`
- `test_per_category_cap_respects_env_override`
- `test_global_cap_enforced`
- `test_spilled_candidates_record_triage_cap_suppression`
- `test_score_tie_broken_by_created_at_desc`
- `test_kill_switch_disables_triage`
- `test_triage_exception_falls_through_to_legacy`
- **`test_triage_exception_clears_queue_for_next_cron`** — verifies the queue gets popped from `bot_state` even when triage raises mid-execution. Without this guard, stale candidates re-process next cycle.
- **`test_per_source_triage_counters_updated_correctly`** — verifies `triaged_in` and `triaged_out` per-source counters update on both survival and spill paths. Catches drift between actual writer calls and dashboard attribution.

Pipeline integration tests in `tests/test_main.py`:

- `test_run_alerts_drains_triage_queue_after_sources`
- `test_run_alerts_only_calls_writer_for_survivors`
- `test_run_alerts_with_triage_disabled_writes_all_candidates`
- **`test_partial_migration_respects_global_cap`** — mixed cycle (some sources legacy, some migrated). Legacy sources can produce drafts that count against `MAX_DRAFTS_PER_CYCLE`; migrated sources defer to triage. Verifies total drafts ≤ cap even in mixed state. This is the steady-state during rollout, so it must work.
- **`test_run_alerts_pops_stale_queue_on_entry`** — verifies the `bot_state.pop("_triage_queue", None)` at the top of `run_alerts` correctly drops a queue left over from a crashed prior cron.

**State-persistence tests in `tests/test_state.py`:**

- **`test_sqlite_round_trip_drops_triage_queue`** — verifies the `_triage_queue` key is NOT persisted to SQLite even when present in `bot_state`. Mirrors the existing `test_sqlite_round_trip_preserves_*` pattern for state shapes that SHOULD persist.

## 9. Telemetry & observability

The suppression ledger gains stage `"triage_cap"`. Dashboard `/health` view should render:

- Per-cycle: `enqueued: N, survived: M, spilled (category cap): X, spilled (global cap): Y`
- Per-source: `triaged_in: N, triaged_out: M, drafted: K` (where K ≤ M ≤ N)

Add `"triage_cap"` to the kill_stage docstring at `src/orchestrator/common.py:296` (current list: `writer | safety | claim_extractor | fact_check | critic | budget_exhausted | pipeline_error | unknown`).

## 10. Rollout

Single PR (one branch):

1. New `src/orchestrator/triage.py` + `tests/test_triage.py` (pure logic, no integration).
2. New `CandidateBundle` type in `src/two_bot/types.py`.
3. New `_enqueue_candidate` + `_drain_and_write_triage_queue` helpers in `src/orchestrator/common.py`.
4. Updated `src/orchestrator/run_alerts.py` to call drain at end-of-cycle.
5. Kill-switch via `THEHEAT_TRIAGE_ENABLED` env var. Default OFF for first PR (sources not yet migrated).
6. Migrate `coral_dhw` source first (highest pressure). Enable kill-switch ON.
7. Watch one cycle. Confirm `enqueued: 9, survived: 2, spilled (category cap): 7`.
8. Follow-up PRs: migrate remaining sources one at a time.
9. Once all sources migrated, remove the legacy direct-call code path AND remove `_prune_weakest_cycle_drafts` from `src/orchestrator/finalize.py` (it becomes redundant — triage now enforces the same cap pre-writer instead of post-writer).

## 11. Non-goals

- Cross-source coalescing — deferred to Phase 2. Per-category cap is the dominant lever today; coalescing is a refinement.
- Cross-cycle queue (deferring spilled candidates to next cron) — sources re-detect; explicit queueing adds state-management cost without clear benefit at this stage.
- Tuning the critic kill rate — that's a prompt-side problem (or a Theme-6-style disposition discussion), not a triage-stage problem.
- Per-region/continent cap (`IDEAS.md` parking-lot idea) — separate lever; can stack on top of triage if needed later.
- Per-source rate caps — global + per-category is enough granularity for now.

## 12. Open questions for review

- **Default cap value (2 per category, 3 global)** — these are conservative. The user may want lower defaults during initial rollout to validate cost reduction before relaxing.
- **`created_at` as tiebreaker** — assumes more recent = more current. Could instead break ties on `event_id` lexicographic for full determinism. Either works; pick one for the implementation plan.
- **Kill-switch default** — proposed default OFF (legacy behavior). The first source migration would also flip the default to ON. Alternative: default ON, with the kill-switch as the rollback lever. Either works; lock at plan-eng-review time.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 3 architecture + 3 test gaps; all fixed inline |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run (infra refactor, no product/scope change) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | not run (no UI scope) |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | not run (skipped per session pace) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run (not a dev-facing product) |

**ENG REVIEW FINDINGS (all fixed inline):**

- **A1 — Queue persistence bug:** `bot_state["_triage_queue"]` is not actually transient (no underscore-prefix convention exists in `src/state.py` or `src/storage/`). Fixed in § 6 with explicit two-guard pattern (pop-at-entry + skip-in-persist) plus `test_sqlite_round_trip_drops_triage_queue` in § 8.
- **A2 — Coalescing rule over-broad:** Naive `(signal_kind, lat-1°-bucket, lon-1°-bucket, date)` would conflate distinct reefs / fires. Fixed in § 2, decision row 7 — coalescing must be same-event semantics (multiple sources surfacing the same incident), not same-bucket. Phase 2 remains deferred until production overlap data justifies it.
- **A3 — Alternative architecture re-examined:** Simpler "writer-budget counter" alternative considered but doesn't meet stated source-growth-proof goal (sources fire in deterministic order; first source always wins). Full deferred-execution triage is the right shape. No spec change.
- **T1 — Partial-migration test gap:** Mixed cycle (some sources legacy, some migrated) is the steady-state during rollout. Added `test_partial_migration_respects_global_cap`.
- **T2 — Queue cleanup on triage exception:** Fall-through to legacy must still clear the queue. Added `test_triage_exception_clears_queue_for_next_cron` + `test_run_alerts_pops_stale_queue_on_entry`.
- **T3 — Telemetry attribution test:** `triaged_in` and `triaged_out` counters need verification on both survival and spill paths. Added `test_per_source_triage_counters_updated_correctly`.

**Also clarified in § 10:** legacy `_prune_weakest_cycle_drafts` in `src/orchestrator/finalize.py` becomes redundant once all sources migrate — removal added to the rollout steps.

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement. Three "open questions" in § 12 are knobs for the implementation plan, not blockers (default cap values, tiebreaker, kill-switch default).
