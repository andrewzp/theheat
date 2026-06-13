# SOURCE-REDUNDANCY LANE — Codex Kickoff (GREENLIT 2026-06-13)

Andrew greenlit execution of the SOURCE-REDUNDANCY lane (`2026-06-13-source-redundancy-lane.md`) on 2026-06-13. This doc is how it gets executed: the launch command, and the verbatim, diligence-enforcing prompt the executor receives. Same model as the THIRTY-LOOP kickoff, tuned for higher rigor because every step here touches the live data path and the editorial-honesty contract.

---

## Part 1 — How to launch (Andrew)

**Recommended (headless, one tranche per run, Anthropic-token-free):**

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
PATH=/opt/homebrew/bin:$PATH codex exec --sandbox danger-full-access \
  "$(sed -n '/^## Part 2/,$p' docs/superpowers/plans/2026-06-13-source-redundancy-CODEX-KICKOFF.md)"
```

`danger-full-access` is required (the loop pushes branches, calls `gh`, and runs no deploys but reads the network for live verify-curls). Re-run the same command to resume — state lives in `2026-06-13-source-redundancy-PROGRESS.md`, which every step's PR updates. Each run works steps until a STOP, a hard stop, or its context fills, then writes its session-log row and exits.

**Watching:** progress = the PROGRESS table on `main` + merged PRs (titles `loop/r<NN>-…`). Health = `gh issue list --state open --label source-health-sentinel --json number,title,labels`. Because every step changes a live fetch path, **watch the next scheduled `theheat-bot` run after each merge** — a green source-health row for the touched source is the real proof, beyond CI.

---

## Part 2 — The prompt (verbatim Codex input)

You are the autonomous executor of the SOURCE-REDUNDANCY LANE — adding genuinely independent backup feeds to @theheat's chronically-flaky NASA/gov sources so a host outage stops being a no-draft day. Your operator is token-constrained and trusts the plan: you do not re-plan, re-scope, or improvise. Every judgment call is pre-decided in the plan. Your single job is faithful, test-driven, evidence-verified execution, one PR per step.

### First actions, in order, before any work

1. `cd /Users/andrewpuschel/Documents/Claude/theheat` (do this explicitly in EVERY shell command — the shell persists cwd between calls; a stray `cd dashboard` WILL leak into later commands and make you read nonexistent files).
2. Read `docs/superpowers/plans/2026-06-13-source-redundancy-lane.md` IN FULL — especially **§L0** (the grading ladder: which leg gets which `evidence_grade`) and **§L1** (pre-made decisions). It is the binding contract.
3. Read `docs/superpowers/plans/2026-06-11-thirty-loop.md` §0–§5 and §8 — this lane inherits its rails, shipping mechanics, prohibitions, and failure protocol verbatim. Read `2026-06-11-thirty-loop-CODEX-KICKOFF.md`'s translation table — you are Codex, so substitute a written adversarial self-review for the `[CODEX]` gates (no recursive codex calls), and use `🤖 Generated with OpenAI Codex` in PR footers.
4. Read `docs/superpowers/plans/2026-06-13-source-redundancy-PROGRESS.md`. Pick the FIRST row with status `TODO` whose `Deps` are all `DONE`. **R-00 is the mandatory foundation — nothing else may start until R-00 is DONE.**
5. Run the THIRTY-LOOP §2 PREFLIGHT verbatim (`git checkout main && git pull`; `source .venv/bin/activate`; mypy; pytest `-m "not voice_replay"`; dashboard `node --test`; sentinel `gh issue list … --json …`). If a sentinel issue labeled `ours`/`unknown` is open, fix it before the lane. If main is red, STOP and write the halt note.

### The diligent process — every step, no exceptions

This lane changes live fetch paths and the editorial-honesty contract; a sloppy step can put a false "observed" claim into a draft. So each step follows this exact loop:

1. **Branch:** `git checkout -b loop/r<NN>-<slug>`.
2. **Verify the feed is real, FIRST.** Before writing code, `curl` the step's endpoint live (with the User-Agent `(theheat-bot, contact@theheat.app)` and any required `appname`) and paste the actual response shape into the PR body. If the live shape differs from the spec, STOP with the evidence — do not code against a guessed shape. (Several steps say "verify live first; if it 403s/404s, STOP `BLOCKED(...)`" — obey that literally.)
3. **TDD — tests first.** Write the step's named tests as failing tests; run them; confirm they fail for the right reason. Only then implement. The plan lists the exact test names per step — write all of them. Always include the two honesty tests where the step has a `model_fallback` leg: (a) the witness reading carries the right `source_leg`/grade, and (b) a draft built from it that claims "observed/measured/recorded" is KILLED by the fact-check gate.
4. **Implement to the spec, minimally.** The witness lives INSIDE the existing public fetch function, returns the SAME object shape with `source_leg` set, fires only on `SourceFetchError`/`requests.RequestException` (NEVER `SourceSkipped`), and provenance reaches the writer ONLY by the bundle builder appending the correct `evidence_grade` fact to `current_facts` per the §L0 ladder. Do not change the public fetch return type. Do not store raw payloads in state.
5. **Run the gates and paste real output.** Every step lists GATES (§4 universal + per-step). Run each command; paste the ACTUAL output line into the PR body. Never write "tests pass" — write the line that proves it. Verification before completion is mandatory: evidence before assertion, always.
6. **Self-review (the `[CODEX]` substitute).** On `[CODEX]`-marked steps (R-00, R-03, R-05) — and on any step touching the sentinel↔dashboard sync or a `model_fallback` grade — re-read your full `git diff main` with fresh adversarial suspicion against the §5 priorities (value bugs; the same-shape/`source_leg` contract; sentinel Python↔JS parity; missed failure modes; the honesty grade). Record findings + dispositions under `## Self-review (executor is Codex)` in the PR body; fix anything you'd grade P0 before merging.
7. **Honesty checklist (§L4).** Confirm, in the PR body, each line: primary path byte-unchanged when healthy (a test proves the witness is never called on the happy path); same-shape return; correct grade per the ladder; coverage limits stated honestly (HMS = N. America only; GloFAS = largest-river + modeled-not-observed; ReliefWeb = lag backstop); no new `requirements.txt` entry.
8. **Ship one PR.** Bump VERSION (next patch), add the §3 CHANGELOG entry, update the PROGRESS row (status → DONE + PR #) in the SAME PR. Commit (§3 message shape), push, `gh pr checks <N> --watch`, then `gh pr merge <N> --squash --delete-branch`, then `git checkout main && git pull`.
9. **Watch the live proof.** After merge, the next scheduled `theheat-bot` run exercises the new leg only if the primary fails — but confirm the source still reports healthy on the happy path (no regression). Note it in the session log.

### Absolute prohibitions (one violation is the unforgivable failure)

1. NEVER push to `main` — every change via branch → PR → green `test` check → squash-merge.
2. NEVER set or change repo variables/secrets. **NEVER add a `requirements.txt` dependency** — R-05 (sea ice) STOPs and waits for Andrew on `netCDF4`/`pyhdf`; implement behind the dep, mark `AWAITING-ANDREW(dep:<name>)`, do not merge it.
3. NEVER disable/rename workflows; never edit the gist by hand.
4. NEVER weaken editorial gates (thresholds, banned patterns, fact-check generosity, critic). The grades you add are honesty markers, not loosenings.
5. NEVER let a witness draft claim an observation it didn't make — `model_fallback` MUST forbid "observed/measured/recorded"; a fact-check fixture must prove the kill.
6. NEVER change the public fetch return shape, and NEVER catch `SourceSkipped` in the witness path.
7. Keep the Python sentinel (`scripts/source_health_sentinel.py`) and dashboard JS classifier (`dashboard/lib/source-health.js`) in sync (R-01) — same PR, both test suites.
8. NEVER touch PR #207 (the grading routine). Never force-push, never `--admin` merge.

### Order & end-of-run

Work R-00 (foundation) → R-01 (dashboard/sentinel leg-visibility, the sync-contract pair) → **R-02, R-03, R-04, R-05** (the independent feeds — NOAA HMS, Open-Meteo precip, ReliefWeb, Open-Meteo Flood — these are the whole point: they stop host-outage no-draft days) → R-06, R-07 (same-provider product chains) → R-08 (optional supply) / R-09 (dep-gated, STOP for Andrew). A step may be taken once its deps are DONE.

Fix budget: 3 attempts at a red gate, then abandon the branch, set `BLOCKED(<one-line diagnosis>)` in PROGRESS (via a tiny PROGRESS-only PR, no VERSION bump), take the next eligible step. Hard stops (end the run, write `docs/handoffs/REDUNDANCY-haltnote-<date>.md`): 2 consecutive BLOCKED steps; a sentinel issue labeled `ours` opening within 24h of one of YOUR merges (revert that merge FIRST); main red that one revert doesn't fix.

End of each run: append the PROGRESS session-log row (date, steps shipped, notes) in your final PR, and print a 5-line summary — steps DONE / steps BLOCKED with reasons / next eligible step / open sentinel-issue count / anything `AWAITING-ANDREW` (the R-05 dependency, especially). Then exit. Begin with the preflight, then R-00.
