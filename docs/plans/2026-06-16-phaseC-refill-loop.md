# Phase C — Generate-and-Select Refill Loop

**Status:** Plan (light) · drafted 2026-06-16 · outside review pending
**Sequence:** A → B → C → D. This is **C** (real build).
**Depends on:** Phase A (watch `drafted` up, `critic_pass_rate` flat); benefits
from Phase B (more drafts only matter if they can ship).
**Process:** this is a real build — run `/brainstorm → /write-plan →
/plan-eng-review + codex` before code, not straight to implementation.

## Problem

Each cycle selects ≤3 survivors (`select_survivors` global cap 3, enforced again
by `_prune_weakest_cycle_drafts`, `src/orchestrator/finalize.py:12`) and attempts
each **once**. A writer/fact_check/critic kill yields nothing — there is **no
"try the next-best distinct candidate"** loop (verified: no refill path in the
orchestrator). Worse, city cooldown + already-posted are checked in
`src/orchestrator/draft_save.py:143` **after** the 3 LLM calls have run, so
doomed candidates burn spend. **The selection unit is the single event, when it
should be the day's slate.** This caps output near ~1/day regardless of how many
great events exist — the core gap behind "why not 3–5 good drafts a day."

## Goal / Non-goals

**Goal:** turn the drain step into a generate-and-select loop that keeps
attempting ranked **distinct** candidates until it reaches a target of N
successful drafts (or the ranked queue is exhausted), and move the deterministic
cooldown/dedup checks to a **pre-writer** predicate so the loop never spends LLM
calls on candidates that can't be saved.

**Non-goals:** changing the editorial bar (writer/critic quality unchanged);
removing the per-category diversity cap; raising the daily *posting* cap (10/day).

## Approach

```
 BEFORE:  rank → take top 3 → attempt each once → prune to 3
 AFTER:   rank ALL (diversity-capped) → iterate in rank order:
            skip if can't_draft (cooldown / dup / superseded — deterministic, $0)
            attempt writer → fact_check → critic
            on success: drafted += 1
            stop when drafted == TARGET_N  OR  queue exhausted  OR  attempts == 2·N
```

1. **Pre-writer predicate.** Extract cooldown / already-posted /
   same-day-superseded / event_id-dup checks from `draft_save.py` into
   `can_draft_candidate(bot_state, candidate) -> (bool, reason)`. The drain loop
   (`_drain_and_write_triage_queue`, `src/orchestrator/triage_queue.py:114`) calls
   it before `_try_two_bot_draft`. `draft_save` keeps the checks too (defense in
   depth), but now they fire with **$0 LLM spent** and show in Phase A as
   "killed pre-writer."

2. **`select_survivors` returns the full ranked + diversity-capped list** rather
   than truncating to 3 (`src/orchestrator/triage.py`). The drain loop owns the
   stop condition.

3. **Stop condition.** `TARGET_N = THEHEAT_DRAFTS_TARGET_PER_CYCLE` (default = the
   current 3, so flip-off preserves behavior). Per-category cap still enforced for
   diversity. A `max_attempts = 2·N` bound caps cost on low-supply days.

4. **`_prune_weakest_cycle_drafts` becomes a safety net**, not the primary control
   — the loop already stops at N.

## Files touched

- `src/orchestrator/draft_save.py` — extract `can_draft_candidate` predicate.
- `src/orchestrator/triage.py` — `select_survivors` returns full ranked list; keep
  per-category + pending-type + annual caps.
- `src/orchestrator/triage_queue.py` — drain loop becomes refill loop with stop
  condition + pre-writer skip.
- `src/orchestrator/finalize.py` — prune as safety net.
- env: `THEHEAT_DRAFTS_TARGET_PER_CYCLE`, `THEHEAT_REFILL_MAX_ATTEMPTS`.
- tests.

## Test plan

- Unit: predicate returns False for cooldown/dup/superseded **without invoking the
  writer**; refill loop attempts down the ranked list until N successes; loop
  respects per-category cap and `max_attempts`; loop stops on queue exhaustion;
  killed candidates don't double-count cooldown/annual state; default flag
  preserves current top-3-once behavior.
- Integration: a cycle with 8 ranked candidates where the top 3 all critic-kill
  still produces N drafts by reaching deeper; a cooldown'd top candidate is
  skipped with $0 LLM spend (assert no writer call).

## Risks & rollback

Medium. **Risks:** (1) more LLM calls per cycle (cost — base is ~$1–3/day, large
headroom; bounded by `max_attempts`); (2) refill could lower average quality if N
is set above genuine supply — Phase A's `critic_pass_rate` is the guard;
(3) interaction with pending-type cap + annual caps (`src/orchestrator/caps.py`)
must still be honored. **Rollback:** `THEHEAT_DRAFTS_TARGET_PER_CYCLE=3` (or a
`THEHEAT_REFILL_ENABLED` flag default off) reverts to top-3-once.

## Open decisions (for reviewer + Andrew)

1. `TARGET_N` starting value — **recommend** 3, raise after Phase A shows
   `critic_pass_rate` holds.
2. `max_attempts` bound — **recommend** `2·N` to cap cost on thin days.
3. Per-category cap semantics in a refill world: per-cycle (current) vs per-day.
4. Should the on_draft_success / annual-counter callbacks (already deferred past
   the prune via `defer_callbacks`) need any change under refill? (Likely no —
   verify the deferral still fires only for kept drafts.)

## Hand-off / dependencies

Needs A (measurement) and pairs with B (shipping). This is the biggest structural
lever for 3–5/day. Hands D a real multi-draft slate to draw cross-signal context
from.

---

## Outside review — codex gpt-5.5 (2026-06-16): SHIP WITH CHANGES

**Must-fix before building:**
1. **Reconcile `THEHEAT_DRAFTS_TARGET_PER_CYCLE` with `MAX_DRAFTS_PER_CYCLE`.**
   Default `N=3` does NOT preserve current behavior, and `N>3` still gets pruned
   back to 3 unless `_prune_weakest_cycle_drafts` (`finalize.py:73/94`) is changed
   too. Make the target and the prune cap a single knob.
2. **Cap accounting must be success-aware.** Today `select_survivors` spends
   per-category and pending-type slots at SELECTION (`triage.py:251/276`), so failed
   writer attempts still consume slots and the loop won't actually reach deeper. The
   refill loop must count *successes*, not selections, against the caps.
3. **Re-check annual caps at admit time.** They're checked pre-enqueue and
   incremented via deferred success callbacks (`run_alerts.py:219`), so reaching
   deeper near a cap can overshoot in-cycle.

**Corrections to this plan:** the prune FUNCTION is `finalize.py:73` (line 12 is
just the env constant); durable posted-event dedup is `state.is_duplicate` used by
sources pre-enqueue, while `draft_save` handles event_id/city-date/cooldown — the
pre-writer predicate must cover BOTH layers.

**What codex affirmed:** the core waste is real (`two_bot_dispatch.py:118` runs the
full pipeline before `draft_save.py:143` rejects cooldown/dedup); defense-in-depth
is right; the true hazard is mutation-before-prune, not double-counting.
