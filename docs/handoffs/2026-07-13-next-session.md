# Handoff — 2026-07-13 · billing outage + the 25% economics plan are the open threads

> Wraps the 2026-07-10→13 session (writer-voice realignment shipped; Missouri-flood miss diagnosed;
> billing outage diagnosed; economics deep dive → plan).
> **`main` @ `11ba90a`, v`0.9.100.0`, tree clean.** Everything below is MERGED unless marked **OPEN**.

## 🔴 THE URGENT THING — production drafting is DOWN (billing) (OPEN, Andrew-gated first step)

The Anthropic API balance hit $0 ~2026-07-11. **No draft has been written since
2026-07-11T06:24Z** — `bot.yml` stays green through writer failures (sources fetch, candidates
queue, zero drafts), so the only loud signal is `voice-regression` red (39×
`BudgetExhaustedError: credit balance is too low`). Judge drafting health by the latest draft
`created_at` in the state gist, never by workflow color (memory: `reference_theheat_drafting_health`).

1. **Andrew: top up credits** (or set auto-reload + cap) at platform.claude.com → Plans & Billing.
2. Then verify recovery: `gh workflow run voice-regression.yml` → green; next bot cycles produce
   drafts (`gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json` → max `drafts[*].created_at`
   advances past the top-up time).
3. Self-heal cannot fix this class; it correctly opened no PRs.

## ★ THE OPEN THREAD — execute the 25% plan (OPEN; P0 ready to build)

Andrew's mandate: *Claude stays the writer; everything else can move; quality same or better; cost
≤25% of today.* The measured run-rate is **~$53–73/month** (nightly 40-draft regression suite ~$30 +
writer at samples=2 ~$15–25 + daily unpinned self-heal agent ~$5–15 + evaluator ~$3 — the test suite
outspends the product ~2:1). The plan lands at **~$9–12/month (~15–18%)** with the Sonnet voice
untouched.

**Canonical plan (SUPERSEDES the 25% plan — reconciled against the external cross-model audit,
every claim code-verified 2026-07-13):**
[docs/superpowers/plans/economics/PLAN-ECONOMICS-MASTER-v3.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/economics/PLAN-ECONOMICS-MASTER-v3.md)

- **P0** (stop-loss): `THEHEAT_WRITER_SAMPLES=1` **paired with** `THEHEAT_CRITIC_REVISE_ENABLED=0`
  (samples=1 alone ACTIVATES the revise rewrite lane — never split the pair); cycle-level billing
  circuit breaker (07-13 fired 6 paid attempts after the first billing error); `max_retries=0` on
  the writer's Anthropic client (one retry owner); voice-regression nightly→auto PR gate on
  prompt/writer paths + 3-fixture daily canary (red on billing = the outage tripwire) + weekly
  full; self-heal keyless red-gate (gate job writes the beacon) + Haiku pin; ledger MVP in state;
  Console auto-reload/cap (Andrew).
- **P1**: ledger dashboard + caps/alerts; DELETE the dead legacy pipeline (evaluator has zero live
  callers — it was never costing $3/mo; removing it is hygiene, not savings).
- **P2**: Batch API writer lane (50% off, stacks with caching, kills the ~$10/mo rewarm floor;
  autoship freshness guard) + structured outputs for the JSON-parse lane.
- **P3**: frozen replay corpus — the gate for ANY future taste-bearing experiment.
- Held levers (OFF): Haiku tiering, Sonnet 5 challenger, per-signal prompt compilation.

## What happened this session (all MERGED unless noted)

- **[#429](https://github.com/andrewzp/theheat/pull/429)** — `heat_records_cluster` writer voice
  realigned to the house SIGNATURE MOVE (new move 4 = the SHIFT not the cause; house ✗/✓ example;
  docstring editing contract; fact-check rule `r)` unchanged). codex-xhigh clean APPROVE r1;
  **Andrew approved the before/after** ("objective improvements"). Squash `3cc28a8`, v0.9.100.0.
- **[#435](https://github.com/andrewzp/theheat/pull/435)** — docs close-out (handoff + INDEX row 414).
- **Standing rule logged** (memory `feedback_theheat_one_house_voice` + writer_prompt.py docstring):
  per-signal sections carry signal-SPECIFICS only + one move naming that signal's system clause;
  every example must survive the delete-the-system-clause test + machine-verify vs 280/safety/§F.
- **Missouri flood miss (2026-07-10) diagnosed — zero coverage, three independent holes:**
  (1) **BUG**: `src/data/nws_alerts.py` whitelists `"Flash Flood Emergency"`/`"Tornado Emergency"`
  as `event` values, but NWS emits emergencies as *Warning*-type events + `flashFloodDamageThreat:
  CATASTROPHIC` + EMERGENCY headline — both whitelist entries are dead code (verified against the
  live NWS API: two CATASTROPHIC alerts for Iron/Reynolds MO sailed past). **A fix session was
  spawned separately (task chip task_9776e21d)** — check whether it landed before touching
  nws_alerts.py. (2) IMERG precip lane samples fixed city points (nearest to the bullseye:
  St. Louis, 202 km). (3) river-gauges watches 12 major stations, no Ozark rivers;
  `flood_activation_tiers` has never fired. (2)+(3) are coverage-philosophy calls, not bugs.
- **Drafting-health lesson** → memory `reference_theheat_drafting_health` (see THE URGENT THING).
- **Economics deep dive** → the 25% plan above (live-sourced market + local research inlined in the
  plan doc's appendix).

## Andrew-gated (unchanged from before + new)

- **Credits top-up / auto-reload** (the urgent thing).
- Console checks: usage-by-key (does **Vital** bill this account?); **aistudio.google.com** Gemini
  tier (F3 critic = Gemini **Pro**, free tier ≈50 req/day — fits, little headroom).
- records-cluster: live dryrun sample + `THEHEAT_RECORDS_CLUSTER_ENABLED` flip (explicit words).
- Long-standing open PRs: #346 (dup-city, HELD), #324 (claim/warrant design review), #207 (rolling).
- State-size watch (#390): gist warns "approaching inline cliff" (~1.75MB) — worth a session soon.

## Standing rules (bind every session — verbatim)

- `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH` on EVERY Bash
  command **including codex and git** (fresh shells lose cwd — git exits 128, codex "not a trusted
  directory"; retry with the prefix). Python `.venv/bin/python`; ruff/mypy `.venv/bin/ruff` /
  `.venv/bin/mypy`.
- Before every push: `ruff check src/ tests/` AND `mypy src/` AND
  `THEHEAT_TIME_TRAVEL_DAYS=90 .venv/bin/python -m pytest -q` — all green (currently 2512).
- codex-xhigh on any diff touching editorial gates / posting / state / storage, looped to clean
  APPROVE (zero P0/P1/P2), LAST round STARTING after the LAST edit:
  `codex exec -c model_reasoning_effort='"xhigh"' "<prompt>" < /dev/null`.
- Merge: `gh pr checks <N> --repo andrewzp/theheat --watch` → verify the required `test` check
  passed → `gh pr merge <N> --squash --delete-branch` → confirm `git log origin/main`. **Claude merges.**
- One PR per unit; VERSION bump + CHANGELOG `[Unreleased]` ride code PRs; docs are their own PR.
  Never weaken an honesty gate. **US-only is off-brand.** New scheduled workflows carry a
  `cost/run × cadence = $/month` line in the PR.

---

## Paste-ready kickoff prompt for the next session

> Pick up @theheat. `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH`
> — that exact prefix on EVERY Bash command INCLUDING codex and git (fresh shells lose cwd; git exits
> 128, codex "not a trusted directory" — retry with the prefix). Python `.venv/bin/python` (ruff/mypy =
> `.venv/bin/ruff` / `.venv/bin/mypy`); repo `andrewzp/theheat`; `main` was `11ba90a` v0.9.100.0 at
> handoff — re-verify, a parallel NWS-fix session (task_9776e21d) may have landed.
>
> **READ FIRST, in order:** (1) `docs/handoffs/2026-07-13-next-session.md` — the open threads + full
> state. (2) `docs/superpowers/plans/economics/PLAN-ECONOMICS-MASTER-v3.md` — the reconciled master
> plan (supersedes PLAN-25-PERCENT.md; every claim code-verified).
> (3) `docs/superpowers/plans/front-page-parity/INDEX.md` §Standing rules. Also read the memories
> `reference_theheat_drafting_health` and `feedback_theheat_one_house_voice`.
>
> **FIRST — verify production is back** (I have topped up the Anthropic balance): rerun
> `gh workflow run voice-regression.yml` and confirm green; confirm new drafts appear in the state
> gist (latest `drafts[*].created_at` past the top-up). If the balance is still empty, STOP and tell me.
>
> **THEN — THE OPEN THREAD: execute the economics MASTER plan (v3). Pasting this prompt
> green-lights P0 and P1 as specified in PLAN-ECONOMICS-MASTER-v3.md §3.** Headlines, but the plan
> file is authoritative: P0 = (a) the PAIRED flag flip in one step —
> `gh variable set THEHEAT_WRITER_SAMPLES --body 1` AND
> `gh variable set THEHEAT_CRITIC_REVISE_ENABLED --body 0` (never one without the other; samples=1
> alone activates the critic-REVISE rewrite lane); (b) cycle-level billing circuit breaker in the
> refill drain + non-refill path; (c) `max_retries=0` on the writer's Anthropic client; (d)
> voice-regression: nightly cron → auto PR gate on `src/two_bot/prompts/**` + `writer.py`, plus a
> daily 3-fixture canary that fails RED on billing/auth errors, plus a weekly full run; (e)
> self-heal: keyless red-gate job that also writes SELFHEAL_BEACON, agent only on red, pinned
> `--model claude-haiku-4-5`; (f) ledger MVP (per-call `usage` → state). P1 = ledger dashboard +
> caps/alerts, and the dead-legacy-pipeline DELETE PR (generator/evaluator — zero live callers,
> verified; no instrumentation needed, it never runs). P2 (Batch API writer lane + structured
> outputs) is designed in the plan — its own session after 48h of P0 funnel data, show me the
> drafts/day readout first. Held levers (Haiku tiering, Sonnet 5 challenger, prompt compilation)
> stay OFF unless I say otherwise.
>
> **HOW (binds — INDEX §Standing rules):** the `cd … && PATH=…` prefix on every command; before every
> push ruff + mypy + `THEHEAT_TIME_TRAVEL_DAYS=90` pytest green; codex-xhigh on any diff touching
> editorial gates / posting / state / storage / workflows-that-post, looped to clean APPROVE, LAST
> round after LAST edit; Claude merges (checks green → squash → verify `git log origin/main`); one PR
> per unit; VERSION + CHANGELOG ride code PRs; docs are their own PR; never weaken an honesty gate;
> US-only is off-brand; every new/changed scheduled workflow's PR carries a `cost/run × cadence =
> $/month` line. Work autonomously; stop only for a real fork, a prod flag flip, or anything touching
> the writer's published voice (my taste domain — before/after required).
>
> **Also on the board (Andrew-gated, do NOT start unbidden):** records-cluster dryrun sample + flag
> flip; Console usage/Vital check; Gemini-tier check; #324 claim/warrant review; state-size (#390).
