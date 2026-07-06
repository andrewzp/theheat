# @theheat Three-Pillar Upgrade Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement the fully-specified tasks
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is the PROGRAM
> plan VISION.md mandated: the leverage-ordered roadmap across all three pillars, with
> the first PR-sized move of each pillar specified to execution granularity. Bet A's
> full multi-phase task plan gets its own plan doc after Andrew reviews the design spec
> (per the brainstorming→writing-plans gate).

**Goal:** Upgrade @theheat from "honest data ticker with silent failure modes" to the
VISION.md bar: editorially excellent, anecdote-carrying, globally newsworthy — on a
system that fails loudly instead of silently.

**Architecture:** Three workstreams sharing one discipline (default-OFF flags, codex-xhigh
on gate-touching diffs, live dispatch verification, honesty gates only ever strengthened).
Pillar 3 ships first (cheap, independent, sharpest user signal); Pillar 2 (Bet A) is the
root-cause product fix and **delivers Pillar 1's anecdote path as a by-product** (they
share the grounded-retrieval/citation core — build it once); Pillar 1's residual
voice-floor work iterates last on the proven reganom pattern.

**Tech Stack:** Python 3.12 (repo/CI target per `pyproject.toml`; a local `.venv` may
run newer — write 3.12-compatible code), GitHub Actions cron + `gh`, Gist state,
Sonnet writer / Gemini Flash fact-check / Gemini 2.5 Pro critic, Next.js dashboard
(Vercel).

## Global Constraints

- CI gate = `test` job: `ruff check src/ tests/` AND `mypy src/` AND `pytest` AND dashboard build. Run ruff + mypy before every push.
- codex-xhigh (`< /dev/null`, looped to clean APPROVE) on any diff touching editorial gates / posting / state / storage.
- Never weaken honesty gates (fact-check rules, §F deterministic gate, critic, safety bans). Every new figure: real cited retrieval, never model imagination.
- Ship behavior changes behind default-OFF repo variables; verify live (dispatch-harness pattern); then flip on. Read-only sentinel watches follow the unflagged advisory-issue precedent (yield/coverage watch).
- Stage only your own files; docs land as their own PR; Andrew never merges (Claude merges on green after `gh pr checks <N> --watch`).
- Python/JS mirrors (sentinel ↔ `dashboard/lib/source-health.js`) must change together, with mirror tests.
- The writer is the **metered Anthropic API** — new LLM work states its per-cycle call budget.

---

## The leverage-ordered PR queue (the plan at a glance)

| # | PR-sized move | Pillar | Effort | Risk | Depends on |
|---|---|---|---|---|---|
| 1 | `fix/reganom-stakes-attribution` — **MERGED this session (#361)** | 1 | XS | Low | — |
| 2 | **R1: writer-down / credits-low watch** — **BUILT this session (#362)** | 3 | S | Low (read-only) | — |
| 3 | **R2: manual-queue age watch** — **BUILT (#364; fired live 2026-07-06, issue #368)** | 3 | S | Low (read-only) | — |
| 4 | **R3: time-travel canary** (behavioral, superseded the grep guard) — **BUILT (#365; 5 live bombs defused)** | 3 | M | Low | — |
| 5 | **A0: Bet A phase 0** — **BUILT, SHIPPED DARK (#366; activation = Andrew's flag flip)** | 2 | M | Low (zero editorial surface) | Andrew approved 2026-07-03 ("follow your own recommendations") |
| 6 | **A1: Bet A enrich** — `human_impact` on bundles + writer/fact-check/§F gates + forced manual_only | 2→1 | L | Med (editorial-gate diffs; codex mandatory) | A0 live-verified |
| 7 | **A2: Bet A boost** — capped rescue at the fire score gate | 2 | M | Med | A0; A1 recommended first |
| 8 | **E1: voice-floor iteration** — generalize the reganom four-moves + dryrun-harness pattern to the next signal type (fires) | 1 | M | Med | A1 (impact-carrying fire tweets are the richest test) |
| 9 | R4: self-heal completion — `SELFHEAL_PAT` (operator: Andrew) + verify | 3 | XS (Andrew) | Low | — |
| 10 | A3 (v2): new-coverage-trigger for sensor-less stories — gated on gap-flag evidence | 2 | L | High | A0-A2 live + gap-flag data |

Rationale for the order: R1-R3 are independent, cheap, and close the exact silent
failures that burned the last two weeks (writer down 2026-07-03; time-bomb main CI
2026-07-03; unwatched queue 2026-06-29→07-03). A0 is next because it is zero-risk
scaffolding that starts collecting gap-flag evidence immediately. A1 before A2 because
sourced anecdotes are the bigger editorial lift and Pillar 1's core deliverable; A2's
rescue then rides infrastructure A1 proved. E1 last because its best material exists
only after A1.

---

## Pillar 3 — Reliability: the system fails loudly (FIRST)

**Wrong today:** the system stays green while producing wrong or no output. Evidence:
Anthropic credits exhausted → writer drafted nothing for hours while runs reported
`success` (graceful `BudgetExhaustedError`); a hardcoded-date test rotted and broke
`main` CI for every PR; good drafts died in an unwatched manual queue; the heat
detector ran US-only for 7 weeks green-by-every-metric (now watched, #333); a
world-eval gating defect produced `cov:0.0` for ~2 weeks (fixed #345). Self-heal
(#306/#307) exists but is PAT-gated (#309, unset).

**Good looks like:** every known "green but wrong" path has a watcher that opens a
loud, auto-closing GitHub issue (the proven sentinel grammar), mirrored on the
dashboard; no test can rot with the calendar; self-heal is armed.

**Sequenced steps:** R1 (writer watch) → R2 (queue watch) → R3 (time-bomb sweep +
guard) → R4 (SELFHEAL_PAT, Andrew) → continuing: extend coverage-watch classes per
source as geography becomes clean (Future per its design).

**Effort/risk:** S/S/M each, all low-risk (read-only watchers; test-only sweep). The
watchers deliberately reuse the sentinel's issue plan/apply machinery — no new infra,
no flags (advisory-issue precedent), sentinel already runs every 4h with `gh` + state.

### Task R1: writer-down / credits-low watch (first PR — fully specified)

> **STATUS: BUILT 2026-07-03, same session as this plan** — PR #362
> (`feat/sentinel-writer-watch`), codex-xhigh looped to clean (r1 found lexical-ts
> and dead-mirror P2s; fixed). The task text below is kept as the as-built record;
> its TDD steps have all been executed (the "expected FAIL" steps read historically).

**Files:**
- Modify: `scripts/source_health_sentinel.py` (new watch block after the coverage-watch block, ~line 738; new wiring in `main()` after the coverage-watch wiring, ~line 878)
- Modify: `dashboard/lib/source-health.js` (JS mirror, alongside the coverage-watch mirror)
- Test: `tests/test_source_health_sentinel.py` (new class), dashboard test suite (mirror test)

**Interfaces:**
- Consumes: `state["suppressions"]` rows (`{ts: ISO-8601 Z string, stage: str, ...}`) and `state["run_history"]` (existing `_bot_is_drafting`).
- Produces: `writer_watch(suppressions, run_history, *, now) -> list[dict]` findings `{kind: "budget_exhausted", count: int, last_ts: str}`; `build_writer_watch_body(findings) -> str`; `plan_writer_watch_action(findings, open_issue) -> dict|None` — same action grammar as the coverage watch (`create_writer_watch` / `update_writer_watch` / `close_writer_watch`). JS: `writerWatch(suppressions, runHistory, now)` with identical findings (the drafting gate needs `run_history` on both sides).

- [ ] **Step 1: Write the failing Python tests**

```python
class TestWriterWatch:
    def _supp(self, ts, stage="budget_exhausted"):
        return {"id": f"supp_{ts}", "ts": ts, "stage": stage}

    def test_flags_recent_budget_exhausted(self):
        now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
        supps = [self._supp("2026-07-04T10:00:00Z"), self._supp("2026-07-04T11:00:00Z")]
        findings = writer_watch(supps, [{"mode": "alerts"}], now=now)
        assert findings == [{
            "kind": "budget_exhausted", "count": 2, "last_ts": "2026-07-04T11:00:00Z",
        }]

    def test_ignores_old_rows_and_other_stages(self):
        now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
        supps = [
            self._supp("2026-07-02T10:00:00Z"),               # outside 24h window
            self._supp("2026-07-04T10:00:00Z", stage="critic"),  # different stage
        ]
        assert writer_watch(supps, [{"mode": "alerts"}], now=now) == []

    def test_silent_when_not_drafting(self):
        # a paused bot must not false-alarm on stale rows
        now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
        supps = [self._supp("2026-07-04T10:00:00Z")]
        assert writer_watch(supps, [], now=now) == []

    def test_body_names_the_failure_and_the_fix(self):
        body = build_writer_watch_body(
            [{"kind": "budget_exhausted", "count": 2, "last_ts": "2026-07-04T11:00:00Z"}]
        )
        assert WRITER_WATCH_MARKER in body
        assert "Anthropic" in body and "credit" in body.lower()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/test_source_health_sentinel.py -k WriterWatch -v` → FAIL (`writer_watch` not defined)

- [ ] **Step 3: Implement in the sentinel** (after the coverage-watch block; mirrors its shape exactly)

```python
WRITER_WATCH_WINDOW_HOURS = 24
WRITER_WATCH_TITLE = "Writer watch: the Anthropic writer is down (budget exhausted)"
WRITER_WATCH_MARKER = "<!-- source-health-writer-watch -->"


def writer_watch(
    suppressions: list[dict] | None,
    run_history: list[dict] | None,
    *,
    now: datetime,
) -> list[dict]:
    """Flag recent budget_exhausted kills — the writer silently down while runs stay green.

    The 2026-07-03 incident class: Anthropic credits hit zero, every draft died with a
    graceful BudgetExhaustedError, bot runs kept reporting success, nothing alerted.
    """
    if not _bot_is_drafting(run_history):
        return []
    cutoff = (now - timedelta(hours=WRITER_WATCH_WINDOW_HOURS)).isoformat().replace("+00:00", "Z")
    rows = [
        r for r in (suppressions or [])
        if isinstance(r, Mapping)
        and r.get("stage") == "budget_exhausted"
        and str(r.get("ts") or "") >= cutoff
    ]
    if not rows:
        return []
    return [{
        "kind": "budget_exhausted",
        "count": len(rows),
        "last_ts": max(str(r.get("ts") or "") for r in rows),
    }]


def build_writer_watch_body(findings: list[dict]) -> str:
    f = findings[0]
    return "\n".join([
        WRITER_WATCH_MARKER,
        "**The writer is down: Anthropic credit balance is exhausted.**",
        "",
        f"{f['count']} draft(s) died with `budget_exhausted` in the last "
        f"{WRITER_WATCH_WINDOW_HOURS}h (latest {f['last_ts']}). Bot runs keep reporting "
        "success while NOTHING drafts — this issue is the loud version.",
        "",
        "**Fix:** top up Anthropic API credits (the writer is the metered API, separate "
        "from the Claude Code Max plan), then confirm voice-regression goes green.",
        "",
        "_Auto-maintained by the source-health sentinel writer watch._",
    ])
```

Plus `_open_writer_watch_issue()` / `plan_writer_watch_action()` / `_create_/_update_/_close_writer_watch_issue()` — copy the coverage-watch quartet verbatim with the writer constants (same auto-close rule: findings empty → close). Wire in `main()` after the coverage block:

```python
    ww = writer_watch(
        state.get("suppressions"),
        state.get("run_history"),
        now=datetime.now(timezone.utc),
    )
    ww_action = plan_writer_watch_action(ww, _open_writer_watch_issue())
    if ww_action:
        if ww_action["action"] == "create_writer_watch":
            _create_writer_watch_issue(ww_action)
        elif ww_action["action"] == "update_writer_watch":
            _update_writer_watch_issue(ww_action)
        else:
            _close_writer_watch_issue(ww_action["number"])
```

- [ ] **Step 4: Run tests** — same command → PASS; then `ruff check scripts/ tests/` + `mypy src/` clean.

- [ ] **Step 5: JS mirror + test** — `writerWatch(suppressions, runHistory, now)` in `dashboard/lib/source-health.js` (same window constant, same finding shape and drafting gate, following the file's coverage-watch mirror block). Ship the **parity mirror + tests only** — the coverage-watch precedent: `buildSourceHealthPayload` exposes findings but no page renders them yet (codex-verified: AutomationStrip has no watch slot); a UI slot is a separate small follow-up if wanted. Mirror test replays the 2026-07-03 incident shape (2 recent `budget_exhausted` rows → finding; empty → none). Run: `cd dashboard && npm test` → PASS. **Deploy note:** dashboard deploy is manual `vercel --prod` after merge.

- [ ] **Step 6: Fixture replay of the real incident** — add one test loading a `suppressions` list shaped like 2026-07-03 (N `budget_exhausted` rows over 3h, `run_history` showing green alerts runs) → exactly one finding. This is the regression test for the incident that motivated the pillar.

- [ ] **Step 7: Commit** — `git add scripts/source_health_sentinel.py dashboard/lib/source-health.js tests/test_source_health_sentinel.py dashboard/<test file>` → `git commit -m "feat(sentinel): writer watch — loud issue when the Anthropic writer dies with budget_exhausted"` → PR → codex-xhigh (state-reading watcher; cheap pass) → merge on green → live-verify on the next 4h sentinel run.

### Task R2: manual-queue age watch (second PR, same shape as R1)

Pure function `queue_watch(drafts, now)` in the sentinel: pending drafts with
`approval_policy == "manual_only"` older than `QUEUE_WATCH_HOURS = 24` → finding
`{kind: "stale_reviews", count, oldest_age_h, types}`; ≥1 finding → advisory issue
(`QUEUE_WATCH_TITLE = "Review-queue watch: manual drafts are aging unreviewed"`,
marker `<!-- source-health-queue-watch -->`, same create/update/auto-close plan
helpers, dashboard mirror + tests). Kills the "is anyone reviewing?" gap that let the
Prudhoe Bay draft sit 8h and the France draft die stale — and becomes load-bearing for
Bet A's forced-manual impact tweets, where a stuck draft is a missed story.

### Task R3: time-bomb sweep + calendar-rot guard (third PR)

1. Sweep: `grep -rn "2026-" tests/` (980 hits) — triage the subset where a hardcoded
   date is COMPARED against wall-clock now (`date.today()`, `datetime.now`,
   freshness/window assertions). Convert each to relative dates built from
   `date.today()` (the #136/#356 pattern) or a frozen `now` passed explicitly.
2. Guard: new `tests/test_no_calendar_rot.py` meta-test that fails when a test module
   both (a) matches `date\.today\(\)|datetime\.now\(` and (b) contains a hardcoded
   `20\d\d-\d\d-\d\d` literal on a comparison line, unless the module is in an
   explicit reviewed allowlist. Crude but it makes the 2026-07-03 class (a rotting
   fixture silently arming itself weeks after merge) impossible to reintroduce
   unreviewed. Effort M: the sweep is the work; the guard is ~60 lines.

### Task R4: SELFHEAL_PAT (operator — Andrew, one action)

Create a fine-grained PAT (repo: andrewzp/theheat; permissions: Actions read/write,
Contents read/write, Issues read/write) → `gh secret set SELFHEAL_PAT --repo
andrewzp/theheat` → next hourly workflow-health run verifies (#309 auto-closes). This
arms the already-merged red-workflow auto-fixer — with it, the voice-regression
billing-red on 2026-07-03 would have been surfaced within the hour.

---

## Pillar 2 — Bet A: global newsworthy coverage (ROOT CAUSE)

**Wrong today / good / design:** fully specified in the completed spec —
[docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md).
One retrieval lane (NIFC feed + grounded search, verification ladder, deterministic
source/url/as_of floor) feeding three consumers: capped **rescue boost** (Colorado
62<64 clears; hard floor threshold−8; source-required; provenance in `score.reasons`),
**enrich** (`human_impact[]` on bundles; writer cites only with attribution;
fact-check + §F kill unsourced impact; impact-citing drafts forced `manual_only`
regardless of type), and the read-only **gap flag** (world-reported event matched
nothing → advisory issue; the IDEAS #9 miss-detector at zero editorial risk).

**Sequenced steps:** A0 (lane + state + gap flag, master flag OFF → flip master on
alone: zero editorial surface, collect evidence) → A1 (enrich, flag OFF → live
dispatch verify → flip) → A2 (boost, flag OFF → verify → flip) → A3 (v2
new-coverage-trigger, only with gap-flag evidence). Flags:
`THEHEAT_NEWSWORTHINESS_ENABLED` (master), `THEHEAT_NEWS_ENRICH_ENABLED`,
`THEHEAT_NEWS_BOOST_ENABLED` — all default `0`.

**Effort/risk:** A0 M/low; A1 L/medium (touches writer prompt, fact-check prompt,
evidence contract, approval policy — codex-xhigh mandatory, live dispatch harness
extended to a fire fixture); A2 M/medium (score-gate seam, fire-first). Cost envelope:
≤5 LLM calls/cycle (~30/day), no Anthropic tokens until a rescued/enriched candidate
drafts.

**Gate:** A0 starts after Andrew reviews the spec (decisions 4 and 5 are flagged
adopted-from-recommendation). The full A0-A2 task-by-task TDD plan is written as its
own plan doc at that point; A0's shape is already concrete:

### Task A0 sketch (first Bet A PR, ~1 session)

- Create `src/data/newsworthiness.py`: `fetch_news_events(now) -> list[NewsEvent]`
  (NIFC leg: structured fields → `confidence="structured"`; grounded leg: one Gemini
  `google_search` call, parse → `confidence="unverified"`; verify step promotes to
  `"verified"` or drops, ≤3 URL fetches/cycle; parse-time drop of any impact entry
  missing `source_name`/`url`/`as_of`; ≤10 events kept).
- State: `news_events` key in `DEFAULT_STATE` + **`MERGE_SPEC` entry** (append +
  prune 7d + dedup on `(kind, headline, window_start)`) — the MERGE_SPEC contract
  test fails collection if forgotten.
- Source-health row `newsworthiness` (success/degraded/failed like any source; a
  failed retrieval degrades, never blocks the cycle).
- `candidates_log` rolling state list (`{event_id, category, country, date}`
  recorded at `_enqueue_story_candidate`, 7-day prune, MERGE_SPEC entry) — the gap
  flag's "what did we detect?" side; there is no durable candidate registry today.
- Gap flag in the sentinel: `news_gap_watch(news_events, drafts, posted_events,
  candidates_log)` → advisory issue, marker `<!-- source-health-news-gap-watch -->`,
  same plan/apply grammar as R1/R2.
- Wire behind `THEHEAT_NEWSWORTHINESS_ENABLED` (bot.yml passthrough like reganom's).
- Tests: normalization, verification promotion/drop, merge, gap-flag on the Europe
  fixture (WHO event, no matching candidate → finding).

---

## Pillar 1 — Editorial excellence + sourced anecdotes

**Wrong today:** tweets are honest and clean but "data-ticker competent" — a number
and a place, no human story; there is no path for sourced anecdotes at all. The
writing engine itself is proven good when pointed at the right event with the right
prompt shape (the shipped Prudhoe Bay draft; the reganom four-moves upgrade #349).

**Good looks like:** every tweet reads like a sharp news story; where the event has
human stakes, it carries a **cited** anecdote ("Three firefighters were killed
Saturday on the Knowles and Gore fires… per NIFC").

**The structural insight: Pillar 1's anecdote path IS Bet A's enrich output.** IDEAS
#10 (sourced anecdotes) and #9 (newsworthiness) share one retrieval/citation core —
the spec builds it once. So Pillar 1's first two moves are already queued above:
merge the reganom stakes fix (PR #1 in the queue, in flight), then A1 delivers the
anecdote capability. What remains pillar-specific:

### E1: voice-floor iteration, one signal type at a time (after A1)

The reganom voice upgrade established the repeatable pattern: (1) name the type's
four moves in its writer-prompt section (lead with significance, weave attribution,
scale words over raw units, name the stakes the data can see); (2) pair every
loosening with a fact-check rule so honesty tightens in the same PR; (3) iterate on
the **offline dispatch harness** (`reganom_writer_dryrun.py` + workflow_dispatch —
generalize to `writer_dryrun.py --type fire` with per-type fixtures) so voice work
costs zero prod resets; (4) exemplars teach only gate-passing phrasings (this
session's codex loop showed even didactic prose bleeds into drafts). Run the pattern
on **fires next** (E1: FRP tier scale-words + named complex/ecosystem + the A1 impact
citation), then precip/marine. Effort M per type; risk medium (prompt+gate diffs;
codex each).

### E2 (continuing): grade what ships

The critic + voice-regression already gate quality; the A-rate instrument (daily-plan
grading routine) grades drafts. As autoship volume grows post-#352, add the shipped
tweets' engagement to the grading corpus (FUTURE_STATE's "eval set from actual
performance") — data-gathering only until there's enough posting history.

---

## Verification & rollout standards (all pillars)

1. Behavior changes: default-OFF repo variable → merge → live dispatch harness run on
   the real chain (writer→safety→§F→fact-check→critic) → flip one flag → watch one
   full cron cycle → next flag. One-flip rollback documented per flag.
2. Watches (read-only): merge → next 4h sentinel run is the live verify (issue
   appears/absent as fixtures predicted); dashboard deploy is MANUAL `vercel --prod`.
3. codex-xhigh looped to clean APPROVE on: A1, A2, E1 (editorial gates), any state
   schema change (A0's MERGE_SPEC entry).
4. Rollout watches carried from this week: #352 autoship (auto count going nonzero),
   #345 `cov:` climbing, and post-R1 the writer watch itself.

## Decisions Andrew owns (the plan's only blocking inputs)

1. **Bet A spec review** — especially decision 4 (impact tweets forced `manual_only`
   by content) and decision 5 (NIFC + grounded search as MVP sources). Unblocks A0.
2. **SELFHEAL_PAT** (R4) — one PAT + `gh secret set`. Unblocks armed self-heal.
3. (Standing, unchanged:) claim/warrant #324 review; #346 dup-city alias direction.
