# Handoff — 2026-07-14 · economics P0+P1 SHIPPED; production stopped, restore is Andrew's word

> Wraps the 2026-07-14 session (billing recovery verified → economics master plan P0+P1 executed
> under codex-xhigh loops). **`main` @ `c1342dd`, v0.9.108.0, tree clean.**
> Everything below is MERGED unless marked OPEN.

## 🎯 THE ONE THING — production restore (OPEN, Andrew-gated)

Production has been STOPPED since [#441](https://github.com/andrewzp/theheat/pull/441) (Andrew,
2026-07-14: "stop automated activities right now until we streamline the costs… until economics
P0 lands"). **P0 and P1 have now landed.** The restore is deliberately left for Andrew's explicit
words because it resumes posting + spend:

1. `git revert 1dea65e` on a branch → PR → merge (restores the three bot.yml crons), and
2. `for w in voice-regression workflow-self-heal source-health-sentinel refresh-thresholds time-travel-canary; do gh workflow enable $w.yml --repo andrewzp/theheat; done`

Post-restore run-rate under the new economics: **~$18–23/month** (plan §4 "After P0") vs $50–70
before; P2 (Batch API lane) takes it to ~$11–17 ≈ 17–25%.

## What shipped this session (all MERGED)

| Item | PR | What it does |
|---|---|---|
| P0.1 | (flags) | `THEHEAT_WRITER_SAMPLES=1` + `THEHEAT_CRITIC_REVISE_ENABLED=0`, flipped as a pair 05:37Z |
| P0.2+3 | [#439](https://github.com/andrewzp/theheat/pull/439) | Cycle billing breaker (both drains + cycle-scoped latch + suppressions lock + `billing_aborted` funnel volume) + `max_retries=0` single transport-retry owner |
| P0.4 | [#443](https://github.com/andrewzp/theheat/pull/443) | voice-regression: nightly cron → writer-path PR gate + Mon–Sat 3-fixture billing canary (bounded re-sample) + weekly full; fork-PR guard; honest cost header |
| P0.5 | [#444](https://github.com/andrewzp/theheat/pull/444) | self-heal: keyless gate (decisive-conclusion + staleness + disabled checks, PR-event-filtered) owns the beacon; agent only on red, Haiku-pinned; `pending` beacon semantics + stuck-pending alarms (observer + dashboard) |
| P0.6 | [#445](https://github.com/andrewzp/theheat/pull/445) | usage ledger MVP: per-call writer usage → `state.llm_usage` (canonical-date keys, max-merge strategy, write_state-owned drain, 45-day prune) |
| P1.1 | [#447](https://github.com/andrewzp/theheat/pull/447) | budget watch: MTD + projection vs `THEHEAT_MONTHLY_BUDGET_USD` ($14 default); 70%/90% alerts via the `budget` source-health row (sentinel auto-issues); dashboard `GET /api/usage` |
| P1.2 | [#446](https://github.com/andrewzp/theheat/pull/446) | dead legacy pipeline DELETED (generator 1,745 + evaluator 308 + templates 298 lines + adapters); BRIEFING's dangerous `ANTHROPIC_API_KEY`="evaluator" mislabel fixed (it's the WRITER key) |

Billing recovery was verified first (kickoff order): voice-regression run 29308543415 green (39
paid replays) + drafts flowing again (06:17/06:19/14:01Z on 07-14, post-flag-flip) after the
07-11→14 outage gap. codex CLI was resurrected via `npm i -g @openai/codex@latest` (new failure
class: "model requires a newer version of Codex" — memory updated).

Every code PR went through codex-xhigh looped to clean APPROVE (12+ rounds total; last round
always started after the last edit; two rounds were infra-failures detected by missing verdict
sentinel and relaunched).

## Watch items (next session)

- **Funnel readout gate for P2**: the plan requires 48h of P0 funnel/drafts-per-day data before
  starting P2 (Batch API lane). Production is stopped, so the clock starts at restore. Readout:
  drafts/day + `critic` kill share from `run_history` funnels; re-enable trigger if approved
  drafts/day drops >20% for a week → flip `THEHEAT_CRITIC_REVISE_ENABLED=1` back first.
- **First scheduled runs after re-enable**: watch the voice-regression daily canary (Mon–Sat
  09:17Z) and the self-heal gate (13:00Z) behave as designed; the gate writes the beacon at $0.
- **Budget row**: after a few cycles, `GET /api/usage` + the `budget` source-health row should show
  real numbers; `THEHEAT_MONTHLY_BUDGET_USD` env-tunable (default $14).
- **NWS emergency-semantics fix**: parallel worktree `theheat-wt-nws-emergency` (branch
  `fix/nws-emergency-semantics`) exists from the spawned session (task_9776e21d) — check its state
  before touching `src/data/nws_alerts.py`.

## Andrew-gated (unchanged + new)

- **Production restore** (the one thing, above).
- P2 (Batch API writer lane + structured outputs): own session AFTER 48h post-restore funnel data;
  show the drafts/day readout first (kickoff contract).
- Console checks: usage-by-key (Vital on this account?); aistudio.google.com Gemini tier.
- records-cluster dryrun + `THEHEAT_RECORDS_CLUSTER_ENABLED` flip; #324 claim/warrant review;
  #346 dup-city (HELD); state-size watch (#390).
- Held levers stay OFF: Haiku tiering, Sonnet 5 challenger, prompt compilation.

## Standing rules — unchanged from 2026-07-13 handoff (cd prefix, venv binaries, ruff+mypy+pytest
green before push with REAL exit codes (never gate on `cmd | tail` — it swallowed a red suite once
this session), codex-xhigh loop on gate/posting/state/storage diffs, Claude merges after the
required `test` check reports SUCCESS (poll the check json — `--watch` can exit early), one PR per
unit, VERSION+CHANGELOG ride code PRs, never weaken an honesty gate, US-only off-brand, $/month
line on scheduled-workflow PRs.
