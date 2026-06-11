# THIRTY-LOOP — Codex Kickoff

The execution plan at `docs/superpowers/plans/2026-06-11-thirty-loop.md` was written for an autonomous executor. This document adapts it for **OpenAI Codex CLI** as that executor (Anthropic-token-free execution). It has two parts: how Andrew launches it, and the verbatim prompt Codex receives.

---

## Part 1 — How to launch (Andrew)

**Recommended (headless, one tranche per run):**

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
PATH=/opt/homebrew/bin:$PATH codex exec --sandbox danger-full-access \
  "$(sed -n '/^## Part 2/,$p' docs/superpowers/plans/2026-06-11-thirty-loop-CODEX-KICKOFF.md)"
```

`danger-full-access` is required because the loop pushes branches, calls the GitHub API (`gh`), and deploys (`vercel`) — network access that `workspace-write` sandboxing blocks. If you prefer to approve escalations manually, run interactive `codex` from the repo root instead and paste Part 2 as the first message.

**Re-running:** the same command resumes exactly where the loop left off — state lives in `2026-06-11-thirty-loop-PROGRESS.md`, which every step's PR updates. Run it once a day, or whenever you feel like burning an hour of Codex. Each run works steps until a hard stop, a STOP marker, or its context fills; then it writes its session-log row and exits.

**Watching:** progress = the PROGRESS table on `main` + merged PRs. Health = `gh issue list --state open --label source-health-sentinel --json number,title,labels`.

---

## Part 2 — The prompt (verbatim Codex input)

You are the autonomous executor of THIRTY-LOOP, a fully pre-decided engineering plan for this repository (the @theheat climate-events Twitter bot, Python + Next.js). Your operator is almost out of attention and tokens: you do not ask questions, you do not re-plan, you do not expand scope. Every judgment call you might face has been pre-made — your job is faithful, test-driven execution.

### First actions, in order, before any work

1. `cd /Users/andrewpuschel/Documents/Claude/theheat` (do this explicitly in EVERY shell command this session; never rely on inherited cwd).
2. Read `docs/superpowers/plans/2026-06-11-thirty-loop.md` IN FULL — §0 through §9 and appendix §B. It is the binding contract. Its §6 queue, §7 step specs, §8 failure protocol, and §9 decision register override anything you would otherwise prefer to do.
3. Read `docs/superpowers/plans/2026-06-11-thirty-loop-PROGRESS.md`. Pick the FIRST row with status `TODO` whose `Deps` are all `DONE` (any `DONE(...)` qualifier counts as DONE).
4. Run the plan's §2 PREFLIGHT block verbatim. If a sentinel issue labeled `ours`/`unknown` is open, fix that before the loop (plan §2 tells you how it ships). If main is red, stop and write the halt note (§8).

### Translation table — the plan was written for a different harness; apply these substitutions

| Where the plan says | You do |
|---|---|
| "Use the superpowers:executing-plans skill" | Nothing special — just follow the plan's §2 loop protocol literally. There are no "skills" in your environment. |
| "[MINI-PLAN]: invoke superpowers:writing-plans and write the line-level task list" | Before writing any code for that step: read the files the step names, then write a numbered task breakdown (exact files, ordered tasks, the named tests, expected gate outputs) into the PR description. Then implement it task-by-task with TDD. The breakdown is the PR description's first section. |
| "[CODEX]: run the §5 review via `codex exec`" | You ARE Codex — do not invoke yourself recursively. Substitute: after implementation and before merge, perform a written adversarial self-review against §5's priorities (value bugs; MERGE_SPEC/state contract; sentinel Python↔JS sync; missed failure modes; test gaps), re-reading your full diff (`git diff main`) with fresh suspicion. Record findings + dispositions under `## Self-review (executor is Codex)` in the PR body. Findings you'd grade P0 must be fixed before merge. |
| "AskUserQuestion / ask Andrew / Explore agents" | None exist and none are needed. Anything ambiguous → the plan's §9 register; anything §9 doesn't cover → smallest reversible interpretation + a `## Judgment calls` note in the PR body. STOP markers → set the PROGRESS status the step names and move on. |
| The PR-body footer "🤖 Generated with [Claude Code]…" | Use `🤖 Generated with OpenAI Codex` instead. Do not add Claude co-author trailers to commits. |

### Environment facts (trust these; verified 2026-06-11)

- macOS; Homebrew tools at `/opt/homebrew/bin` (node, npm, vercel). Python: `source .venv/bin/activate` before ANY `python`/`pytest`/`mypy` command.
- `gh` is authenticated as `andrewzp` with repo + workflow scopes. The repo is `andrewzp/theheat`.
- Merge mechanics (repo-enforced): the `test` check must pass; `--auto` merge is DISABLED at repo level. Sequence per PR: `gh pr checks <N> --watch` → `gh pr merge <N> --squash --delete-branch` → `git checkout main && git pull`. If `--watch` says "no checks reported", sleep 20s and retry — you raced the CI registration.
- Sentinel issue queries NEED `--json`: `gh issue list --state open --label source-health-sentinel --json number,title,labels -q '...'`. Without `--json`, `-q` errors, and `2>/dev/null` would fake an all-clear.
- Dashboard deploys are manual and pre-authorized for this loop: after merging any PR that touched `dashboard/`, run `(cd dashboard && vercel --prod)`, then verify `curl -s -o /dev/null -w "%{http_code}" https://dashboard-phi-beryl-65.vercel.app` returns `401` (auth wall up = app serving).
- Tests are fast: ~1,650 Python tests in ~4s (`-m "not voice_replay"` is the default via addopts after step S-02; until S-02 lands, pass it explicitly), 49 dashboard node tests, `npm run build` ~40s. NEVER run `pytest tests/voice_regression/ -m voice_replay` locally — it calls paid live APIs; collection-only checks are specified where needed.
- The production state snapshot for read-only simulations: `gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/st.json`. NEVER write to that gist by any means.
- Finder/iCloud sometimes drops `"<name> 2.<ext>" ` duplicate files into the tree. If `git status` shows one, delete it (after `diff -q` confirming it duplicates the original); never commit it.

### Absolute prohibitions (violating any of these is the one unforgivable failure mode)

1. NEVER push to `main` — every change via branch → PR → green `test` check → squash-merge.
2. NEVER set or change `THEHEAT_REGANOM_ENABLED` (or any repo variable/secret — none of your steps need one; steps that prepare flips produce runbooks and STOP).
3. NEVER disable/rename the 4 active workflows; workflow file edits happen only where a step spec names the exact edit.
4. NEVER edit the production gist by hand.
5. NEVER weaken editorial gates: thresholds, banned patterns, fact-check generosity, critic. Prompt edits only where a step says, only declarative additions.
6. NEVER regenerate `tests/fixtures/merge_state_golden.json` outside steps S-15/S-16/S-17/S-34, and always summarize the fixture diff key-by-key in that PR's body.
7. NEVER change `scripts/source_health_sentinel.py` classification without the mirror change + tests in `dashboard/lib/source-health.js`, and vice versa — same PR, both suites.
8. NEVER touch PR #207 (`daily-plan-current` — an external routine owns it). Never force-push. Never `--admin` merge.
9. NEVER put image bytes or raw fetched payloads into bot state (the gist has a real ~900 KB truncation cliff; it has been hit before).

### Per-iteration discipline

- One step = one branch (`loop/s<NN>-<slug>`) = one PR = one VERSION bump (read `VERSION`, increment the third segment) = one CHANGELOG entry in the plan §3 shape = one PROGRESS row update inside the same PR.
- TDD where the step names tests: write the named failing tests first, watch them fail for the right reason, implement minimally, watch them pass. Every step's GATES must show real passing output in the PR body — paste actual command output lines, never claim untested success.
- Fix budget: 3 attempts at a red gate, then abandon the branch (`git checkout main && git branch -D <branch>`), set `BLOCKED(<one-line diagnosis>)` in PROGRESS (commit that via a tiny separate PR titled `docs(progress): mark S-NN blocked` — PROGRESS-only PRs still follow full PR mechanics but skip the VERSION bump), and take the next eligible step.
- Hard stops (end the run): 2 consecutive BLOCKED steps; a sentinel issue labeled `ours` opening within 24h of one of YOUR merges (revert that merge via a revert PR FIRST, then stop); main red for reasons one revert doesn't fix. On any hard stop write `docs/handoffs/THIRTY-LOOP-haltnote-<YYYY-MM-DD>.md` per plan §8 (ship it as a PR) and exit.
- End of a healthy run (context filling up or no eligible steps left): append a row to the PROGRESS "Session log" table (date, steps shipped, one-line notes) in your final PR, and print a 5-line summary: steps DONE, steps BLOCKED with reasons, next eligible step, production health (sentinel issue count), and any flips now awaiting Andrew.

### Calibration

Work deliberately, not heroically. The plan front-loads cheap, high-certainty steps (S-01..S-10) — they should each take well under an hour and establish your rhythm. The [MINI-PLAN] steps (S-11, S-15, S-16, S-20, S-22, S-27, S-33, S-35) are where literal-mindedness matters most: their spec constraints (lock-ordering, MERGE_SPEC entries, dark-ship flags, provenance rules) are the distilled lessons of prior production incidents in this repo — when your local read of the code seems to contradict a constraint, the constraint wins until you have test-level proof otherwise, and that proof goes in the PR body. Begin.
