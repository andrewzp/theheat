# Phase B — Decouple the Ship Gate

**Status:** Plan (light) · drafted 2026-06-16 · outside review pending
**Sequence:** A → B → C → D. This is **B** (lands after A).
**Depends on:** Phase A (critic pass-rate + shadow slate to watch what ships).
**Owner decision needed:** do you trust critic-PASS as the ship signal, and which
categories are eligible (see Open decisions). This is the taste call.

## Problem

Posting is operationally `manual_only` (`docs/handoffs/2026-06-16.md:20`). The
documented resume bar is *sustained >50% A-rate* (`docs/QUALITY_TREND.md:7`);
peak ever was 21%, cumulative 17% (`docs/IMPROVEMENT_PLAN.md:15`), so it is never
cleared. Worse, the A-rate grader was the external daily-plan routine, **dead
since 2026-05-26** (`ROUTINE_BEACON` frozen at "no-fresh-drafts"). The ship gate
is bolted to a dead instrument.

Meanwhile drafts bake in real-time framing, sit in the queue, and go stale; even
A- drafts get rejected for staleness (`docs/QUALITY_TREND.md:225`: *"four of
these were A- grades — they would have shipped if posting weren't paused AND if
they were still timely"*). **The pause guarantees the staleness that disqualifies
the very drafts that would lift the rate above the pause.** No tweets ship → no
engagement data → the performance-eval flywheel `FUTURE_STATE` wants can never
start.

## Goal / Non-goals

**Goal:** restart shipping with a self-contained, in-pipeline ship signal that
does not depend on the dead grader, without flooding the feed with mediocrity.

**Non-goals:** auto-shipping human-impact categories (fire / disaster / flood /
severe weather / cyclone stay `manual_only`); building a new LLM letter-grader;
changing the writer/critic quality bar.

## Approach — critic-PASS as the ship signal

The F3 critic is already the editorial gate, instructed *"Default to KILL. Most
drafts that survive fact-check should still die here"* (`src/two_bot/prompts/
critic_prompt.py:23`). A critic **PASS is therefore already a high-bar editorial
endorsement** — the in-pipeline equivalent of "good enough to ship." Reuse it
instead of waiting on a dead external grade.

1. **Scope to low-sensitivity categories only.** The existing `armed_auto` +
   `suggested_auto` set in `src/editorial/approval.py` (hot10, co2/ch4,
   oscillation_*, record/record_low/sea_ice/enso, marine_heatwave). All
   `manual_only` human-impact categories stay exactly as they are.

2. **Auto-ship eligible critic-passed drafts** after their existing
   `recommended_delay_minutes`. Today `suggested_auto` only auto-posts if a human
   sets `approval_mode="auto"` (`src/orchestrator/posting.py:333`). Under a new
   flag `THEHEAT_AUTOSHIP_ON_CRITIC_PASS=1`, set `approval_mode="auto"` at
   `draft_save` time for eligible (low-sensitivity + critic-PASS) drafts.

3. **Freshness guard** before auto-post: if the bundle `tweet_date` is older than
   `THEHEAT_AUTOSHIP_MAX_AGE_H` (default 36h) or the text carries a now-stale
   absolute date, block auto-post and leave it manual. This kills the staleness
   spiral directly. Lives in `src/orchestrator/posting.py` next to the existing
   `_PUBLISH_INTENT_TTL` logic.

```
 draft → critic PASS? ──no──► manual (unchanged)
              │yes
              ▼
   low-sensitivity category? ──no──► manual_only (unchanged)
              │yes
              ▼
   fresh (tweet_date ≤ 36h)? ──no──► hold manual
              │yes
              ▼
   approval_mode=auto → existing delay → existing double-gate safety re-run → POST
```

## Files touched

- `src/orchestrator/draft_save.py` — set `approval_mode="auto"` for eligible
  critic-passed low-sensitivity drafts under the flag (needs the critic verdict
  threaded here).
- `src/orchestrator/posting.py` — freshness guard before auto-post; honor flag.
- `src/editorial/approval.py` — `is_low_sensitivity(tweet_type)` helper.
- pipeline path carrying the critic verdict (PASS vs fact-check-only) to draft_save.
- tests.

## Test plan

- Unit: low-sensitivity + critic-PASS + fresh → `approval_mode=auto`, posts after
  delay; human-impact category → stays manual regardless; stale draft → blocked
  even if eligible; flag OFF → byte-for-byte current behavior.
- Integration: a graded cycle ships the eligible draft and holds the others;
  double-gate safety re-run still fires before post.

## Risks & rollback

Higher blast radius than A — this **actually publishes to @theheat**.
Mitigations: (1) flag-gated, default OFF; (2) scoped to low-sensitivity only;
(3) freshness guard; (4) existing double-gate safety re-run before post still
applies; (5) phase the rollout — start with `armed_auto` (hot10/co2) before
extending to `suggested_auto`. **Rollback:** `THEHEAT_AUTOSHIP_ON_CRITIC_PASS=0`
(repo variable, no deploy).

## Open decisions (Andrew's taste call)

1. Trust critic-PASS as the ship signal, or insist on a revived/inline letter
   grade gating ship? **Recommend** critic-PASS — the grader is dead and the
   critic already is the bar.
2. Eligible set: start with `armed_auto` only (hot10/co2), or the full
   low-sensitivity set? **Recommend** start narrow, widen after a week of Phase A
   data.
3. Freshness threshold: 24h vs 36h. **Recommend** 36h.
4. Retire the `>50% A-rate` doc bar, or keep it as a separate human-review signal?

## Hand-off / dependencies

Reads Phase A's `critic_pass_rate` + shadow slate to verify it ships the right
things, and starts the engagement-data accrual that C and D ultimately need.
Lands after A so the effect is measurable.

---

## Outside review — codex gpt-5.5 (2026-06-16): SHIP WITH CHANGES

"Viable as a narrow, fail-closed canary, but not as written." This is the live-
posting phase, so these are safety-critical.

**Must-fix before building:**
1. **The mechanism is incomplete.** `approval_mode="auto"` alone does NOT schedule
   a post: `process_due_drafts()` only considers drafts with a DUE `auto_approve_at`,
   then allows `suggested_auto` only if `approval_mode=="auto"`
   (`posting.py:297/330`). `save_draft` sets `auto_approve_at` only for `armed_auto`
   today (`draft_save.py:207`). The plan must set BOTH `approval_mode="auto"` AND a
   delayed `auto_approve_at` for eligible `suggested_auto` drafts.
2. **Do NOT infer "low-sensitivity" from policy mode / `can_auto_approve`.** Actual
   `suggested_auto` includes country records, ozone, ice mass, marine heatwave,
   generic `synthesis_*`, and the unknown/default fallback (`approval.py:122/209/218`).
   Use a hard, explicit allowlist of `tweet_type`s.
3. **Add posting-time freshness + idempotency gates** inside `process_due_drafts()`
   after policy acceptance, before safety/post (`posting.py:336/344`). Block
   auto-retry when an old publish intent exists without a tweet id — the current 2h
   stale-intent clear (`posting.py:87`) can REOPEN an unknown-success post →
   double-post.

**Key finding (changes the design):** critic-PASS currently **assumes a human
backstop** — the critic prompt says the draft goes to the human dashboard and may
"lean PASS" on missing geography "because the human gate can fix it"
(`critic_prompt.py:22/63`). Auto-shipping changes that contract, so Phase B must
ALSO tighten the critic prompt (remove the human-backstop assumption) OR keep the
allowlist tiny. And **fail closed when critic metadata is absent** (critic is
env-disablable, `pipeline.py:45`) — no critic verdict ⇒ manual, never
fact-check-only autoship.

**Net:** first rollout = `armed_auto` / a tiny allowlist only, with Phase A shadow
accounting, then widen on evidence. Codex affirmed using the existing due-draft
path (not a second publisher) and keeping human-impact categories `manual_only`.
