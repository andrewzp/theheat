# Workflow self-heal — design

**Date:** 2026-06-17 · **Branch:** `workflow-self-heal` · **Base:** `main` @ `f991029`

## Problem

`voice-regression` ran red for five straight days (06-12 → 06-16) and nobody
knew until Andrew happened to open the dashboard. There is no proactive surfacing
of scheduled-workflow failures, so Andrew is effectively the monitor — which he
explicitly does not want to be.

**Key reframe (Andrew, 2026-06-17):** he already *gets* GitHub's failure emails.
That does not help — it routes the work *to him*. The fix is not another
notification; it is to route a red workflow to **an autonomous agent that fixes
it**, so no human is in the detection path. *"The solution has to be you seeing a
problem and then fixing it on your own — not me getting emails or texts."*

## Goal

A failing scheduled workflow (`theheat-bot`, `voice-regression`,
`refresh-thresholds`, `source-health-sentinel`) is detected and **fixed
autonomously** by a scheduled agent, with the dashboard as a loud human-glance
backstop — without Andrew having to notice or act.

## Root causes (in code today)

1. **Dashboard renders a failed run as a small YELLOW dot, not red.**
   `dashboard/app/components/AutomationStrip.js` `dotColorForWorkflow` →
   `conclusion === "failure"` returns `"yellow"`. No banner. Easy to miss.
2. **`source-health-sentinel` is not monitored on the dashboard.**
   `dashboard/lib/automation.js` `WORKFLOWS` lists only 3 of 4.
3. **Only `bot.yml` self-files an issue on failure.** `voice-regression`,
   `refresh-thresholds`, and the sentinel have zero failure alerting — the one
   workflow that rotted had no coverage.

GitHub Issues is already a trusted, watched alert lane in this repo (the
source-health sentinel auto-files/auto-closes labeled issues). We reuse it.

## Design — three layers + a meta-guard

### Layer 1 — Detection substrate (`scripts/workflow_health.py`, TDD)

A pure, unit-tested observer modeled on `scripts/source_health_sentinel.py`:

- **Monitors all four** scheduled workflows via the GitHub **Actions API**
  (`gh api repos/{repo}/actions/workflows/{file}/runs?branch=main`).
- `select_latest_decisive_run(runs)` — picks the most recent run whose conclusion
  is decisive (`success` | `failure` | `timed_out` | `startup_failure`),
  skipping `cancelled` / in-progress / `neutral` noise.
- `classify_workflow_run(...)` → `failing` when the latest decisive conclusion is
  in `FAILING_CONCLUSIONS`, `healthy` on `success`, `unknown` when there is no
  decisive run. **One red run trips it** — no "wait for two in a row"; that delay
  is the bug being killed.
- `plan_workflow_issue_actions(failing, open_issues)` — mirrors the sentinel's
  create / update / **auto-close** / de-dupe reconcile, keyed by workflow name.
  One labeled `workflow-health` issue per red workflow, title
  `Workflow failing: <name>`, body with the red-run URL, consecutive-failure
  count, and last-green run. Auto-closes when green.
- Runs in the **hourly** `source-health-sentinel.yml` (add `actions: read`
  permission) as a second step — detection is hourly, free, no model.

### Layer 2 — Loud dashboard backstop

- `dashboard/lib/automation.js`: add the 4th workflow (`source-health-sentinel`).
- New plain-JS module `dashboard/lib/automation-status.js` (no JSX, so it is
  unit-testable under `node --test`): exports `FAILING_CONCLUSIONS`,
  `dotColorForWorkflow` (failure/timed_out/startup_failure → **red**), and
  `failingWorkflows(status)`.
- `dashboard/app/components/AutomationStrip.js` imports those helpers and renders
  a **loud red banner** (`role="alert"`) above the strip when any workflow is
  red: `⚠ N workflow(s) failing: voice-regression — self-heal will attempt a fix`.
- `.automation-banner` CSS (full-width, loud red).
- Tests: `automation.test.js` workflow count 3 → 4; new
  `automation-status.test.js` covering colors + banner-list + the known-red runs.

### Layer 3 — The self-heal agent (centerpiece)

A **daily** scheduled cloud agent (Routine via `/schedule`, bound to
`andrewzp/theheat`), driven by committed runbook
`docs/runbooks/workflow-self-heal.md`:

- Reads the signal (open `workflow-health` issues + live `gh run list`).
- For each red workflow runs the investigate → TDD fix → green gates → branch →
  PR → watch CI loop.
- **Autonomy split:** *mechanical* (infra/deps/test-contract/flaky/non-determinism)
  → squash-merge autonomously, pull main; *judgment / taste / destructive* (e.g.
  the writer's editorial contract) → fix on a branch, open a PR, and **stop** —
  that PR is the only thing Andrew sees.
- Independent of the sentinel, so it also catches a **dead sentinel**.
- Writes a `SELFHEAL_BEACON` repo variable at the end of every run (mirrors the
  existing `ROUTINE_BEACON`): `{run_at, outcome, checked, failing, fixed}`.

### Meta-guard — the watcher cannot silently die

The reason the daily-plan routine rotted for weeks is that nothing watched the
watcher. So:

- `scripts/workflow_health.py` reads `SELFHEAL_BEACON` and, **only if the beacon
  exists but is older than 26h**, files a `workflow-health` liveness issue
  (`_selfheal_liveness`). A never-set beacon (clean 404) files nothing — avoids
  rollout chicken-and-egg and token-scope false alarms while still catching the
  real "ran for weeks then went silent" failure mode.
- The dashboard shows a self-heal freshness dot (mirrors the routine dot).

## Autonomy boundary (explicit)

| Failure class | Agent action |
|---|---|
| Infra / deps / cache / network flake | fix → CI green → **squash-merge** |
| Test-contract / non-determinism (the voice-regression class) | fix → CI green → **squash-merge** |
| Voice / editorial contract semantics | fix on branch → **open PR → STOP** |
| Schema/data migration, deletes prod data, destructive | **open PR → STOP** |
| Stuck after 2 fix attempts on one workflow | leave the open issue, do not thrash |

## Verification plan

- Unit-test `classify_workflow_run` against fixtures built from the **real
  known-red runs** (voice-regression `27624430282`/`27556694852`/`27497526866`/
  `27465295748`) → `failing`; and a `success` fixture → `healthy`.
- Live dry-run of `workflow_health.py` against today's all-green state → 0 failing.
- Dashboard: `npm test` + `npm run build`; render check the banner + red dot.
- Routine: dispatch once, confirm "all green, nothing to do" + beacon written.

## Packaging

One PR for Layers 1 + 2 + meta-guard (the testable code) with the Layer-3 runbook
committed in the same PR. The Routine itself is created via `/schedule` after the
PR merges + the dashboard deploys (so the runbook exists on `main` for the
routine to reference).

## Green gates

`.venv/bin/python -m pytest -q` (deselects `voice_replay`), `mypy src/`,
`ruff check .`, and `cd dashboard && npm test && npm run build`.
