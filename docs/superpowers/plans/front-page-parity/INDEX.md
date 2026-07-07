# Front-Page Parity — implementation plan index

> Per-row executable plans for the
> [front-page parity program plan](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-07-06-front-page-parity-plan.md).
> Each plan is self-contained for a zero-context implementer:
> **REQUIRED SUB-SKILL** per plan: superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans. Global constraints from the program plan apply to every
> task in every plan (CI gates, codex-xhigh on editorial/state diffs, honesty gates only
> tighten, default-OFF flags, env-only dispatch inputs, docs as own PRs, Claude merges).

## Execution order and status

| Row | Plan doc | Status | Blocked on |
|---|---|---|---|
| 1–2 | [track-0-runbook.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/track-0-runbook.md) — flip + live-verify Bet A | **A0 master LIVE 2026-07-07 12:59Z** (first-light GREEN; citation hand-check on next cycles). Enrich gate GREEN (#387) — flip after A0 verifies, with Andrew's go; boost after that | A0 verify → Andrew |
| 3 | [row-03-corpus-merge-and-staleness.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-03-corpus-merge-and-staleness.md) | **MERGED 2026-07-07** (#384 + #385; codex r1 P1 → sweep is provenance-aware) | — |
| 4 | [row-04-voice-ptier-pdust.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-04-voice-ptier-pdust.md) | **MERGED 2026-07-07** (#386; watch air-quality coverage ≥90% for 2 cycles) | — |
| 5 | [row-05-cyclone-land-threat.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-05-cyclone-land-threat.md) | **MERGED 2026-07-07** (#388, closes #375; codex r1 2×P1 real → fixed + persistence contract test; Bavi = live verify case) | — |
| 6 | [row-06-editor-brief.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-06-editor-brief.md) | READY | row 3 recommended first |
| 7 | [row-07-precip-four-moves.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-07-precip-four-moves.md) | READY | row 4 pattern |
| 8 | [row-08-fpp-weekly-rollup.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-08-fpp-weekly-rollup.md) | READY to build; live data needs master flip | row 1 for live verify |
| 9 | [row-09-engagement-capture.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-09-engagement-capture.md) | READY | Andrew confirms X API tier |
| 10 | [row-10-boost-beyond-fire.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-10-boost-beyond-fire.md) | Mechanics spec'd; finalize after A2 live | rows 1–2 live |
| 11 | [row-11-marine-cyclone-four-moves.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-11-marine-cyclone-four-moves.md) | READY | row 7 first (pattern cadence) |
| 12 | [row-12-a3-new-coverage-trigger.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-12-a3-new-coverage-trigger.md) | GATED design skeleton — do NOT build until the evidence checklist passes | 2–4 weeks of gap-flag data |
| 13 | [row-13-heat-dome-spike.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-13-heat-dome-spike.md) | Spike protocol (read-only investigation) | — |
| 14 | [row-14-geocode-and-spread.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/row-14-geocode-and-spread.md) | READY (two independent small PRs) | — |

## Standing rules for every implementer (verbatim, non-negotiable)

- `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH` on
  EVERY Bash command; Python is `.venv/bin/python`; repo `andrewzp/theheat`.
- Before every push: `ruff check src/ tests/` AND `mypy src/` AND the local canary
  `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` — all green. Fixture dates
  today-relative, never hardcoded.
- codex-xhigh review, looped to clean APPROVE (zero P0/P1/P2), on any diff touching
  editorial gates / posting / state / storage:
  `cd /Users/andrewpuschel/Documents/Claude/theheat && codex exec -c model_reasoning_effort='"xhigh"' "<review prompt>" < /dev/null`
  run in background, ONE backgrounding layer, and the LAST round must START after the
  LAST code edit.
- Merge: `gh pr checks <N> --repo andrewzp/theheat --watch` → green → `gh pr merge <N>
  --repo andrewzp/theheat --squash --delete-branch` → then VERIFY the squash landed:
  `git fetch origin && git log origin/main --oneline -1` shows your PR. Never trust the
  watch exit code alone.
- One PR per plan (or per task where a plan says so). Stage only files your plan names.
  VERSION bump + CHANGELOG `[Unreleased]` entry ride the code PR; docs/handoff updates
  are their own PR.
- Never weaken an honesty gate. Every impact figure needs source+url+as_of. Every new
  citable number is a pre-computed bundle value (the `value_f` / `value_rounded_c` /
  `area_km2_approx` pattern) — the writer never converts or rounds.
- New workflow_dispatch inputs reach shells via `INPUT_*` env vars only (#380 pattern).
