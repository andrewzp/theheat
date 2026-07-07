# Row 3 — Reconnect the quality instrument: corpus merge + forecast-elapsed sweep

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans, task-by-task. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. Task 2 touches draft state transitions → codex-xhigh MANDATORY.

**Goal:** (a) The grading corpus (A-rate history, failure-mode evidence) lives on `main`
again after 29 cycles marooned on `origin/daily-plan-current`; (b) the staleness rule the
grading routine has been unable to execute for 38 consecutive cycles (no gist write path)
becomes code-native: pending drafts whose FORECAST date has elapsed are auto-rejected
every cycle, deterministically.

**Architecture:** Two independent PRs. PR-A is a verified-clean docs merge (zero code).
PR-B adds a forecast-elapsed sibling to `apply_pending_ttl_sweep` — the existing sweep
keys on `created_at` (7d/21d age) and never reads `tweet_date`, which is exactly why the
Basrah/Doha class sits pending at 48–56h with an already-passed forecast date. Scoped to
forecast-based types only, so observed records (GHCN, with their legitimate 2–4 day lag)
are untouched.

**Tech Stack:** git + existing Python only.

## Global Constraints

All of [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
§Standing rules, plus:
- The sweep REJECTS (recoverable — the operator can re-approve from the rejected pile,
  same contract as the TTL sweep's docstring); it never deletes.
- Forecast-elapsed applies ONLY to the type allowlist below. A blanket `tweet_date`
  sweep would kill observed-record drafts that are allowed to age in manual review.

---

## PR-A (Task 1): merge the corpus to main

Verified facts (2026-07-06): the branch diff vs main is exactly three docs files —
`docs/DRAFT_CORPUS.md` (+3872), `docs/IMPROVEMENT_PLAN.md` (+735/−106),
`docs/QUALITY_TREND.md` (+255) — no `src/**` or `tests/**` changes, and
`git merge-tree` reports a clean three-way merge (main's copies are a strict subset;
main hasn't touched these files since the 2026-07-04 merge-base `8440f3a`).

- [ ] **Step 1:** `git fetch origin daily-plan-current && git checkout main && git pull`
- [ ] **Step 2:** Re-verify cleanliness NOW (state may have moved since 2026-07-06):

```bash
git diff --name-status main...origin/daily-plan-current
git merge-tree $(git merge-base main origin/daily-plan-current) main origin/daily-plan-current | grep -c "^<<<<<<<" || true
```

Expected: only the three docs files; conflict count 0. If ANY non-docs file appears or
conflicts exist, STOP and report — do not force the merge.

- [ ] **Step 3:** Branch + merge + PR:

```bash
git checkout -b docs/merge-daily-plan-corpus
git merge origin/daily-plan-current -m "docs: merge the daily-plan grading corpus to main (29 cycles: 2026-06-08..2026-07-06)

The A-rate history, DRAFT_CORPUS grades, and IMPROVEMENT_PLAN failure-mode
evidence (P_tier/P_dust/P_close/P9/P_compound) lived only on
daily-plan-current since 2026-06-08. main's copies were stale throughout —
including the Jun 29 bar-clearing 80% cycle. Docs-only, merge-tree-verified
clean.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin docs/merge-daily-plan-corpus
gh pr create --repo andrewzp/theheat --title "docs: merge the daily-plan grading corpus to main" --body "Docs-only. Three files, +4862/−106, merge-tree-verified conflict-free. Reconnects the quality instrument (A-rate trend, failure-mode evidence) to main so voice PRs can cite it. The daily-plan routine keeps writing to its branch; a maintainer (or the next session) re-merges periodically — cheap now that the first big merge has landed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 4:** Merge on green + verify squash per INDEX rules. NOTE: use a MERGE
commit or squash — either is fine for docs; squash keeps main linear (house default).

## PR-B (Tasks 2–4): the forecast-elapsed sweep

### Task 2: `apply_forecast_elapsed_sweep`

**Files:**
- Modify: `src/orchestrator/triage.py`
- Test: `tests/test_triage.py` (append to/beside `TestPendingTtlSweep`, lines ~646-849)

**Interfaces:**
- Consumes: draft dicts in `bot_state["drafts"]` — keys `status` ("pending"), `type`,
  `tweet_date` (ISO date the tweet's claim is anchored to; set at
  `src/orchestrator/draft_save.py:256` when provided), `created_at`.
- Produces: `apply_forecast_elapsed_sweep(bot_state, *, now=None) -> int` (count newly
  rejected); constants `FORECAST_TENSE_TYPES = frozenset({"absolute_extreme", "wet_bulb_extreme"})`
  and `FORECAST_ELAPSED_GRACE_DAYS = 1` (env override `THEHEAT_FORECAST_ELAPSED_GRACE_DAYS`).
- Semantics: a PENDING draft whose `type` is in the allowlist and whose `tweet_date` is
  more than GRACE days in the past gets `status="rejected"`,
  `rejected_reason=f"forecast_elapsed_{tweet_date}"`, `rejected_at=now`. Grace of 1 day
  means a July 5 forecast survives through July 6 and rejects July 7+ — same-day and
  next-day review remain possible; the Basrah class (forecast July 4, still pending
  July 6) rejects.

- [ ] **Step 1: Failing tests** (mirror `TestPendingTtlSweep`'s style — today-relative
dates ONLY, built from `datetime.now(UTC)`):

```python
class TestForecastElapsedSweep:
    def _draft(self, *, dtype="absolute_extreme", tweet_date_days_ago=2,
               status="pending"):
        now = datetime.now(UTC)
        return {
            "id": f"draft_{dtype}_{tweet_date_days_ago}",
            "status": status,
            "type": dtype,
            "created_at": (now - timedelta(hours=50)).isoformat().replace("+00:00", "Z"),
            "tweet_date": (now - timedelta(days=tweet_date_days_ago)).date().isoformat(),
            "text": "x",
        }

    def test_rejects_elapsed_forecast_types(self):
        state = {"drafts": [self._draft(tweet_date_days_ago=2)]}
        assert apply_forecast_elapsed_sweep(state) == 1
        d = state["drafts"][0]
        assert d["status"] == "rejected"
        assert d["rejected_reason"].startswith("forecast_elapsed_")

    def test_grace_day_survives(self):
        state = {"drafts": [self._draft(tweet_date_days_ago=1)]}
        assert apply_forecast_elapsed_sweep(state) == 0

    def test_observed_record_types_untouched(self):
        # GHCN records legitimately age 2-4 days in manual review — never swept.
        state = {"drafts": [self._draft(dtype="all_time_high", tweet_date_days_ago=4)]}
        assert apply_forecast_elapsed_sweep(state) == 0

    def test_non_pending_and_missing_tweet_date_untouched(self):
        posted = self._draft(tweet_date_days_ago=3, status="posted")
        no_date = self._draft(tweet_date_days_ago=3)
        del no_date["tweet_date"]
        state = {"drafts": [posted, no_date]}
        assert apply_forecast_elapsed_sweep(state) == 0
```

- [ ] **Step 2:** Run → FAIL (function undefined).
- [ ] **Step 3: Implement** in `src/orchestrator/triage.py`, directly below
`apply_pending_ttl_sweep` (so the two sweeps read as siblings):

```python
# Forecast-tense signal types: the tweet's claim is anchored to a FUTURE
# date (Open-Meteo forecast paths). Once that date has fully elapsed,
# posting would misstate an already-passed forecast as current — the exact
# class the daily-plan grader has flagged since 2026-07-01 (Basrah/Doha)
# but could never reject (no gist write path from its environment).
# Observed-record types are deliberately NOT here: a GHCN record's
# tweet_date is an observation date and may legitimately age in review.
FORECAST_TENSE_TYPES = frozenset({"absolute_extreme", "wet_bulb_extreme"})
FORECAST_ELAPSED_GRACE_DAYS_DEFAULT = 1


def _forecast_elapsed_grace_days() -> int:
    raw = os.environ.get("THEHEAT_FORECAST_ELAPSED_GRACE_DAYS", "")
    try:
        return max(0, int(raw)) if raw else FORECAST_ELAPSED_GRACE_DAYS_DEFAULT
    except ValueError:
        return FORECAST_ELAPSED_GRACE_DAYS_DEFAULT


def apply_forecast_elapsed_sweep(
    bot_state: Any,
    *,
    now: datetime | None = None,
) -> int:
    """Reject pending forecast-tense drafts whose forecast date has elapsed.

    Sibling of apply_pending_ttl_sweep: that sweep keys on created_at (age);
    this one keys on tweet_date (the claim's anchor). Recoverable — the
    operator can re-approve from the rejected pile. Mutates in place;
    returns the count newly rejected.
    """
    if now is None:
        now = datetime.now(UTC)
    grace = _forecast_elapsed_grace_days()
    cutoff = (now - timedelta(days=grace)).date().isoformat()
    now_iso = now.isoformat().replace("+00:00", "Z")
    rejected = 0
    for d in bot_state.get("drafts", []) or []:
        if not isinstance(d, dict) or d.get("status") != "pending":
            continue
        if str(d.get("type") or "") not in FORECAST_TENSE_TYPES:
            continue
        tweet_date = d.get("tweet_date")
        if not isinstance(tweet_date, str) or not tweet_date:
            continue
        # ISO dates compare lexicographically; strictly BEFORE the cutoff
        # date means the grace day has fully passed.
        if tweet_date >= cutoff:
            continue
        d["status"] = "rejected"
        d["rejected_reason"] = f"forecast_elapsed_{tweet_date}"
        d["rejected_at"] = now_iso
        rejected += 1
    return rejected
```

- [ ] **Step 4:** Run → PASS. **Step 5:** Commit
`"feat(triage): forecast-elapsed sweep — elapsed-forecast drafts auto-reject (the Basrah class)"`.

### Task 3: Wire it beside the TTL sweep

**Files:** Modify `src/orchestrator/triage_queue.py` (the single call site of
`apply_pending_ttl_sweep`, line ~355, inside `_drain_and_write_triage_queue`, gated by
`if triage_enabled or refill_enabled:` at ~348). Test: the existing sweep-wiring test
(`grep -n "apply_pending_ttl_sweep" tests/test_triage.py` → the kill-switch test at
~233-252 shows the gating expectations).

- [ ] **Step 1: Failing test** — mirror `test_kill_switch_disables_pending_ttl_sweep`
with the new function: sweep runs when triage enabled, skipped when both switches off.
- [ ] **Step 2:** Implement — immediately after the `apply_pending_ttl_sweep(bot_state)`
call, same guard, same error isolation the file uses (a sweep failure must not block
the cycle — copy the surrounding try/except shape exactly):

```python
            swept_forecast = apply_forecast_elapsed_sweep(bot_state)
            if swept_forecast:
                print(f"[triage] forecast-elapsed sweep rejected {swept_forecast} draft(s)")
```

- [ ] **Step 3:** Run the triage suite → PASS. Commit
`"feat(triage): run the forecast-elapsed sweep at the drain step"`.

### Task 4: Version, changelog, gates, PR, codex

- [ ] VERSION minor bump + CHANGELOG `[Unreleased]` entry (name the Basrah/Doha class,
the 38-skip history, the type allowlist, the grace knob).
- [ ] Full gates (ruff / mypy / 90-day canary) → green.
- [ ] PR + codex-xhigh loop (state transitions — mandatory). Ask codex to attack: the
type allowlist (any forecast-tense type missed? any observed type wrongly included?),
timezone edges (tweet_date is a bare date; now is UTC — is the grace comparison right at
day boundaries?), interaction with the queue watch (#364 — rejected drafts leave its
scope, intended), and whether the routine's OTHER rule half ("real-time-baked" text like
"today") needs code too (v1 answer: no — text heuristics are the follow-up; say so).
- [ ] Merge on green + verify squash.
- [ ] **Live verify:** after the next alerts cycle, any pending `absolute_extreme` draft
with an elapsed forecast date shows `rejected_reason=forecast_elapsed_*` in the
dashboard's rejected pile; the daily-plan routine's next cycle should report 0 strict
staleness candidates.

**Success criteria:** the grading corpus is on main and stays there (re-merge is a
one-command routine now); the Basrah class can never sit pending 3 days again; the
routine's write-skip counter stops mattering (the rule runs in the bot).
