# Phase A — Funnel Instrumentation

**Status:** Plan (light) · drafted 2026-06-16 · outside review pending
**Sequence:** A → B → C → D. This is **A** (first; unblocks the rest).
**Depends on:** nothing upstream.
**Owner decision needed:** where to store the shadow slate (see Open decisions).

## Problem

The handoffs conclude "most no-draft days are editorial SUPPLY, not outages"
(`docs/handoffs/2026-06-13.md:16`) on a kill-accounting that explains only
**200 of the ~26,000 candidates** lost per week (135 triage-cap + 65 quality).
The dashboard surfaces `stage_counts` (raw counts) at
`dashboard/app/api/suppressions/route.js:73` but **no per-stage kill *rate*** and
**no critic pass-rate** — critic PASSes are never counted, only KILLs are recorded
as suppressions. So today we cannot answer:

- Is the critic over-killing, or is supply genuinely thin? (no pass-rate)
- On a no-draft day, did 3–5 great distinct events exist and die, or not exist?
- Where does the ~26k→6 collapse actually happen? (dedup/cooldown deaths are
  largely uninstrumented as "kills")

We are tuning a funnel we can't see. This phase builds the gauge before any knob
gets turned in B/C/D.

## Goal / Non-goals

**Goal:** one daily artifact that answers, for each cycle: how many distinct
events we saw, what the top events scored, where each died, and what fraction
each stage killed against what it was handed.

**Non-goals:** changing any pipeline behavior (pure observability); reviving the
external grader; building a full dashboard UI beyond a minimal rates panel.

## Approach

The per-source counters already exist — `_record_source_run(... observed,
promoted, triaged_in, triaged_out, writer_attempted, drafted ...)` in
`src/orchestrator/telemetry.py:12`. The work is aggregation + two missing
counters + a slate.

1. **Funnel rollup.** Aggregate the existing per-source counters into one
   per-run funnel object on `current_run`, plus a 7-day rolling rollup in state.
   Read-side only.

   ```
   observed → promoted → triaged_in → triaged_out → writer_attempted → drafted
        + kills by terminal stage: score_gate | dedup | city_cooldown |
          same_day_superseded | triage_cap | writer | fact_check | critic
   ```

2. **Critic / fact_check / writer pass counters.** In `src/two_bot/pipeline.py`,
   where `critic_review` / `fact_check` / writer run, record an *attempt* and a
   *pass* alongside the existing kill suppression. Then
   `critic_pass_rate = passes / (passes + kills)` becomes computable. This is the
   single most important missing metric.

3. **Per-stage kill-rate view.** Extend the suppressions route (and/or a new
   `/api/funnel` route) to emit each stage's kills as a rate against what it was
   handed, not just a raw count.

4. **Daily shadow slate.** At end of cycle, emit a compact record of the top ~10
   distinct candidates by score: `event_id`, `type`, `score.total`, terminal
   stage, one-line summary. Persist last 7 days, TTL'd. This is what lets you
   (and a future grader) SEE whether good events existed and where they died.

## Files touched

- `src/orchestrator/telemetry.py` — funnel rollup helper.
- `src/orchestrator/finalize.py` / `common.py` — assemble funnel + shadow slate
  at end of cycle.
- `src/two_bot/pipeline.py` — attempt/pass counters for critic, fact_check, writer.
- `src/state.py` — rolling rollup + shadow-slate storage + TTL.
- `dashboard/app/api/suppressions/route.js` (+ optional `/api/funnel`) — rates view.
- minimal dashboard panel; tests.

## Test plan

- Unit: funnel rollup sums per-source counters correctly; critic pass-rate
  computes from attempts/passes/kills; shadow slate captures terminal stage per
  candidate **including silent dedup/cooldown deaths**; TTL prunes old slates;
  rollup is zero-safe on empty runs.
- Integration: a synthetic cycle with known kills produces the expected funnel
  totals and slate entries.

## Risks & rollback

Near-zero blast radius (observability only). **Risk:** state bloat near the
~928KB gist cliff (`src/state.py:33` warns at 800KB). **Mitigation:** tight TTL
(7d) + cap slate to top-10 + compact encoding, or write the slate to a *separate*
gist file. **Rollback:** `THEHEAT_FUNNEL_TELEMETRY` flag (default on); off reverts
to current counts-only.

## Open decisions (for reviewer + Andrew)

1. Shadow-slate storage: in `state.json` (simple, costs gist bytes) vs separate
   gist file (dodges the cliff) vs dashboard-only ephemeral. **Recommend** separate
   gist file.
2. Backfill rates from existing suppression history, or start fresh? **Recommend**
   start fresh — history lacks attempt counts, so rates would be wrong.

## Hand-off to next phase

B reads `critic_pass_rate` + the shadow slate to confirm it ships the right
drafts. C reads the funnel to confirm refill raises `drafted` without dropping
`critic_pass_rate`. D reads the pass-rate as the A-rate proxy to confirm
multi-signal context lifts it. Nothing in B/C/D is verifiable without A.

---

## Outside review — codex gpt-5.5 (2026-06-16): SHIP WITH CHANGES

Codex verified the core claims: per-source counters exist (`telemetry.py:12/37/57`),
critic PASSes are uncounted (`pipeline.py:294` kill→suppression vs `pipeline.py:313`
PASS→draft-metadata only), dashboard `stage_counts` has no denominator
(`route.js:52/64`).

**Must-fix before building:**
1. **Define exact stage denominators.** `writer_attempted` = "survivor sent to
   pipeline," NOT writer LLM-sample count; multi-sample, slate-critic, REVISE,
   disabled-critic, safety/honesty, and exceptions each need explicit
   attempt/pass/kill rules or the rates lie.
2. **Build the 7-day funnel from finalized `run_history`, not `source_health`.**
   Drain-time bumps (triaged_in/out, writer_attempted, drafted) update only
   `current_run`; the source-health row was already written with `drafted=0`, so a
   source_health rollup undercounts.
3. **Capture the shadow slate BEFORE the triage queue is popped**
   (`triage_queue.py:166`) — end-of-cycle is too late to reconstruct it.

**Corrections to this plan:**
- "dedup/cooldown deaths largely uninstrumented" is **wrong**: `save_draft` records
  `duplicate_draft / same_day_posted / same_day_dedup / same_day_superseded /
  city_cooldown` suppressions (`draft_save.py:77/90/143`). The real blindness is
  that `suppressions` is **capped at 100** (`state.py:32/446`), so weekly volume is
  invisible — the fix is a durable rolling counter, not new kill-recording.
- New durable state keys need `DEFAULT_STATE` + `MERGE_SPEC` + schema +
  SQLite/dashboard allowlists (`state.py:47`, `sqlite_store.py:157`) — more surface
  than implied; prefer the separate-gist-file option with a hard byte budget.
