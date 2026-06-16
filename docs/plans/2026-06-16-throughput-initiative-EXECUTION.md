# Throughput Initiative — Execution Brief & Autonomous Kickoff Prompt

**Created:** 2026-06-16 · **Owner:** Andrew · **Executor:** an autonomous Claude Code session

> **If this doc was pasted to you as a prompt: it is your instruction set, not a
> document to read back or summarize. Execute it now, autonomously, to completion.
> First `cd /Users/andrewpuschel/Documents/Claude/theheat` and read the four linked
> phase plans (A–D) — their codex must-fixes are binding — then start at Step 0 and
> do not stop until all four phases are merged to `main` behind dark (default-OFF)
> flags with a new handoff and an activation runbook. Merge green PRs without asking.
> Do NOT flip production flags, set repo variables, or post to live X/Bluesky — that
> is Andrew's activation step. Use the test-driven-development and systematic-
> debugging skills; solve your own problems. Only stop for something genuinely
> destructive the brief does not already rule on.**

This doc is two things at once:
1. The **index + execution brief** for the four-phase Throughput Initiative.
2. A **self-contained kickoff prompt** (last section) you can paste into a fresh
   Claude Code session, or run via `/loop`, to execute A->B->C->D to completion
   without hand-holding.

Everything the executor needs is here or in the four linked plans. Read this whole
doc before touching code.

---

## Mission

Move @theheat from **~6 drafts/week** toward **3-5 outstanding tweets/day**.

The guiding thesis (Andrew): *"if a smart person could look at 50,000 climate
signals a day, they could write 3-5 outstanding tweets a day from them."*

The load-bearing reframe from the 2026-06-16 `/plan-eng-review`: **the bot already
observes ~132,000 signals/day** (7-day audit: 924,425 observed -> 26,161 promoted
-> 6 drafted). So input breadth is NOT the constraint. The collapse to ~6/week is:

1. **One-shot-per-event architecture.** Each cycle selects <=3 survivors, gives each
   one writer attempt, and a kill yields nothing. There is no "those died, try the
   next-best events" loop. The selection unit is the single event, not the day's
   slate.
2. **Silence-by-default caps.** `MAX_DRAFTS_PER_CYCLE=3`, `pending_type_cap=3`,
   `city_cooldown=3d`, annual caps, plus a critic told to "Default to KILL."
3. **A posting deadlock.** Posting is paused until a sustained `>50%` A-rate that is
   never hit (peak 21%), graded by a routine that is dead since 2026-05-26; A-grade
   drafts then go stale in the queue before they could lift the rate.

The four phases turn the bot into the generate-many-then-select-best, synthesis-
capable engine the thesis describes: **A measures, B ships, C generates many, D
makes them outstanding.**

---

## The four phases (build strictly in this order)

Each plan carries its own `## Outside review (codex gpt-5.5, 2026-06-16)` section.
**Those reviews are binding.** All four are SHIP WITH CHANGES; incorporate every
must-fix. Do not re-litigate the reviews — they are done.

| Phase | Plan | codex verdict | One-line goal | Headline must-fixes (full list in each plan) |
|---|---|---|---|---|
| **A** | [phaseA-funnel-instrumentation.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-phaseA-funnel-instrumentation.md) | SHIP w/ changes | Per-stage kill-RATES + critic pass-rate + daily shadow-slate | Build rollup from `run_history` not `source_health`; define exact stage denominators; capture slate BEFORE the triage queue is popped; `suppressions` cap is 100 so add a durable rolling counter |
| **B** | [phaseB-decouple-ship-gate.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-phaseB-decouple-ship-gate.md) | SHIP w/ changes | Auto-ship critic-PASSED low-sensitivity drafts (fresh) instead of waiting on the dead grader | `approval_mode="auto"` alone does not post — also set delayed `auto_approve_at`; use a HARD allowlist not policy-mode inference; fail-closed when critic metadata absent; freshness + idempotency gate inside `process_due_drafts()` |
| **C** | [phaseC-refill-loop.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-phaseC-refill-loop.md) | SHIP w/ changes | Generate-and-select: keep attempting ranked distinct candidates until N succeed; cooldown/dedup pre-writer | Cap accounting must be SUCCESS-aware (caps are spent at selection today); reconcile `TARGET_N` with `MAX_DRAFTS_PER_CYCLE`/prune; re-check annual caps at admit time |
| **D** | [phaseD-multisignal-writer.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-phaseD-multisignal-writer.md) | SHIP w/ changes | Optional verifiable cross-signal context so the writer can earn synthesis tweets | Add a DETERMINISTIC honesty gate (prompt-only is not enough vs a permissive fact-checker); add geo fields + a concrete window; mind writer-prompt cache byte-stability |

---

## What "go to completion on your own" means here — READ THIS

The standing constraints forbid flipping production flags, setting repo variables,
or posting to live Twitter without Andrew. Every phase is **flag-gated default-OFF**,
so this is not a blocker — it defines the finish line:

- **Your definition of done = all four phases CODED, TESTED, codex-CROSS-CHECKED,
  and MERGED to `main` behind dark (default-OFF) flags, with `CHANGELOG.md` + docs
  updated, plus a final activation runbook for Andrew.** You ship the machinery
  dark. Andrew does the activation (flips flags, watches the dashboard, approves
  going live).
- **Never, as part of this build:** flip any `THEHEAT_*` repo variable, post to live
  X/Bluesky, enable `reganom`, raise `MAX_DRAFTS_PER_CYCLE`, disable a workflow, or
  edit the production gist by hand.
- **Reserved decisions — pick the SAFE conservative default, build it dark, leave a
  one-paragraph note for Andrew in the PR, do NOT block waiting on him:**
  - Phase B: ship the mechanism behind `THEHEAT_AUTOSHIP_ON_CRITIC_PASS` (default
    OFF) scoped to the SMALLEST allowlist (`armed_auto` types only: `hot10`,
    `co2_milestone`, `ch4_milestone`). Fail-closed everywhere. Do NOT widen the
    allowlist or loosen the critic. Flag stays OFF in `bot.yml`.
  - Phase C: `THEHEAT_DRAFTS_TARGET_PER_CYCLE` default = 3 (behavior-preserving).
    The success-aware cap refactor is the real work; raising the target is Andrew's
    later flip.
  - Phase D: default window = same country (exact match) AND same 7-day window, max
    2 related signals; flag `THEHEAT_MULTISIGNAL_CONTEXT` default OFF. Build the
    deterministic honesty gate; do not loosen the fact-checker.

If you hit a genuine taste fork the plans did not settle, choose the most
conservative option that keeps the flag OFF and the editorial gates intact, and
record the choice in the PR. The cost of a wrong conservative default is one later
flag flip; the cost of a wrong aggressive default is a bad live tweet.

---

## Operating rules (theheat rails — non-negotiable)

- **Branch -> PR -> green required `test` check -> squash merge.** No push to `main`.
  `--auto` is disabled at the repo level; use `gh pr checks <N> --watch` then
  `gh pr merge <N> --squash --delete-branch`. After merge: `git checkout main &&
  git pull`.
- **One PR per phase.** Do not bundle phases. They land in order.
- **Shell hygiene:** prefix commands with `PATH=/opt/homebrew/bin:$PATH` and `cd
  /Users/andrewpuschel/Documents/Claude/theheat` explicitly (background shells reset
  cwd). Activate the venv: `source .venv/bin/activate`.
- **Gates that must pass before every PR:**
  ```bash
  cd /Users/andrewpuschel/Documents/Claude/theheat && source .venv/bin/activate
  python -m pytest -m "not voice_replay" -q
  python -m mypy src/
  ruff check .
  # if the PR touches dashboard/:
  (cd dashboard && PATH=/opt/homebrew/bin:$PATH npm test && PATH=/opt/homebrew/bin:$PATH npm run build)
  ```
- **Never run `pytest tests/voice_regression/ -m voice_replay` locally** — it calls
  paid live APIs.
- **New durable state keys** require `DEFAULT_STATE`, `BotState` (TypedDict),
  `MERGE_SPEC`, the SQLite allowlist (`sqlite_store._METADATA_JSON_KEYS`), the
  dashboard allowlist, and tests. (Relevant to Phase A's rolling counter / shadow
  slate and Phase D's `related_signals` if persisted.) Prefer NOT growing
  `state.json` near the ~928KB gist cliff — use a separate gist file or
  `current_run`/`run_history` where the plan says so.
- **Keep `scripts/source_health_sentinel.py` and `dashboard/lib/source-health.js`
  classifier behavior in sync** in the same PR if you touch either.
- **Do not weaken editorial gates** (thresholds, banned patterns, fact-check,
  critic). Phase B/D ADD gates; they never loosen.
- **Cross-model check is available.** codex was repaired 2026-06-16 (removed the
  invalid `service_tier` line from `~/.codex/config.toml`). Use it read-only:
  `PATH=/opt/homebrew/bin:$PATH codex exec -s read-only "<review prompt>"`.

---

## Step 0 (once, before Phase A): land the plan-of-record

The doc sweep that created these plans (the five `docs/plans/2026-06-16-*` files
plus edits to `PIPELINE.md`, `README.md`, `docs/FUTURE_STATE.md`,
`docs/IMPROVEMENT_PLAN.md`, `docs/handoffs/2026-06-16.md`) is staged in the working
tree, uncommitted. Land it as the **first PR** (docs only, `test` check should pass
untouched) so `main` is the plan-of-record and every phase branch starts clean:

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
git switch -c docs/throughput-initiative-plans
git add docs/plans/2026-06-16-*.md PIPELINE.md README.md docs/FUTURE_STATE.md docs/IMPROVEMENT_PLAN.md docs/handoffs/2026-06-16.md
git commit  # docs: throughput initiative plan-of-record (A-D + execution brief)
# open PR, gh pr checks --watch, squash merge --delete-branch, then git checkout main && git pull
```

## Per-phase workflow (apply to A, then B, then C, then D)

1. **Read** the phase plan in full, including its `## Outside review` section.
2. **Branch** off fresh `main`: `git switch -c feat/throughput-phaseX-<slug>`.
3. **TDD** (use the test-driven-development skill): write failing tests for the
   phase's behavior FIRST. Include the codex must-fix edge cases as explicit tests
   (e.g. Phase C: assert a cooldown'd top candidate is skipped with zero writer
   calls; Phase B: assert flag-OFF is byte-for-byte current behavior, and that a
   missing critic verdict stays manual).
4. **Implement** behind a default-OFF flag, incorporating every must-fix. Keep the
   diff right-sized; do not refactor unrelated code.
5. **Green gates** (the block above). Fix until clean. Use the systematic-debugging
   skill on any failure; do not paper over it.
6. **Cross-model review** of the diff:
   `PATH=/opt/homebrew/bin:$PATH codex exec -s read-only "Review the staged diff for
   <phase> against <plan path>. Verify the must-fixes are addressed, hunt for
   correctness/safety regressions and any weakening of editorial or publishing
   gates. Cite file:line."` Address real findings; note any you reject and why.
7. **Self-review** (requesting-code-review skill) + run the verification-before-
   completion skill (evidence before claims). Update `CHANGELOG.md` and any doc the
   change makes stale.
8. **PR -> merge** per the rails. Then `git checkout main && git pull`.
9. **Validate** via Phase A's instrumentation once A is merged (e.g. confirm Phase C
   raises `drafted` without dropping `critic_pass_rate` in a synthetic run). Local
   validation is tests + dashboard build; real prod validation happens after Andrew
   activates.

---

## Definition of done

**Per phase:** plan + outside-review must-fixes implemented; failing-first tests now
green; `pytest`/`mypy`/`ruff` (+ dashboard test/build if touched) clean; codex
cross-check clean or findings addressed; flag verified default-OFF in `bot.yml`;
`CHANGELOG.md` bumped; PR squash-merged to `main`; `main` pulled.

**Overall:** all four phases merged dark; `PIPELINE.md` / `FUTURE_STATE.md` /
the handoff reflect shipped state; and a new handoff
`docs/handoffs/<date>.md` plus an **activation runbook** exist (next section).

---

## Final deliverable — activation runbook (write this at the end)

A short doc telling Andrew exactly how to turn it on, in safe order, with what to
watch and how to roll back. Shape:

1. **A first:** set `THEHEAT_FUNNEL_TELEMETRY=1`; watch one cycle; confirm the
   funnel + shadow-slate render on the dashboard. Rollback: set to 0.
2. **B next, tiny:** with A live, set `THEHEAT_AUTOSHIP_ON_CRITIC_PASS=1` (armed_auto
   allowlist only). Watch the first auto-shipped tweets + the freshness gate.
   Rollback: set to 0 (repo variable, no deploy).
3. **C:** set `THEHEAT_REFILL_ENABLED=1` (target still 3); watch `drafted` vs
   `critic_pass_rate`. Only then consider raising `THEHEAT_DRAFTS_TARGET_PER_CYCLE`.
   Rollback: set to 0.
4. **D:** set `THEHEAT_MULTISIGNAL_CONTEXT=1`; watch voice-regression + the critic
   pass-rate on synthesis drafts. Rollback: set to 0.

Each step names the dashboard panel to watch and the single repo-variable rollback.

---

## Skills to use

`test-driven-development`, `systematic-debugging`, `verification-before-completion`,
`requesting-code-review`, `finishing-a-development-branch` (superpowers); codex for
the cross-model pass; the theheat merge mechanics above. Mark each phase's todos
complete individually as you go.

---

## KICKOFF PROMPT (paste this to start an autonomous session)

> Execute the @theheat Throughput Initiative to completion, autonomously. Read
> `/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-throughput-initiative-EXECUTION.md`
> in full first — it is the execution brief, and it links the four phase plans
> (A->B->C->D), each with a binding codex outside-review section whose must-fixes
> you must implement.
>
> Build the four phases strictly in order, one PR per phase, each behind a
> default-OFF flag, following the per-phase workflow in the brief: TDD first, green
> `pytest -m "not voice_replay"` / `mypy` / `ruff` (+ dashboard test/build if
> touched), a `codex exec -s read-only` cross-check of the diff, then branch -> PR
> -> `gh pr checks --watch` -> `gh pr merge --squash --delete-branch` -> pull main.
> Honor every theheat rail in the brief.
>
> "Completion" = all four phases coded, tested, codex-checked, and merged to `main`
> behind dark flags, with `CHANGELOG.md`/docs updated, a new handoff, and an
> activation runbook for Andrew. Do NOT flip any production flag, post to live
> Twitter, set repo variables, or touch reganom/`MAX_DRAFTS`/the prod gist — that is
> Andrew's activation step. For any unsettled taste fork, choose the most
> conservative option that keeps the flag OFF and the editorial gates intact, record
> it in the PR, and keep going. Solve your own problems; use the systematic-debugging
> skill on failures rather than working around them. Only stop to ask Andrew if you
> hit something genuinely destructive or irreversible that the brief does not already
> rule on.
