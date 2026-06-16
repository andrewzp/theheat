# Handoff — Throughput Initiative shipped DARK (2026-06-16)

Follows [/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-16.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-06-16.md)
(which landed the plan-of-record). Production state outranks this snapshot when
they disagree.

## TL;DR

The four-phase **Throughput Initiative** (move @theheat from ~6 drafts/week
toward 3–5 outstanding/day) is **coded, tested, codex-cross-checked, and merged
to `main`** — every phase behind a **default-OFF** repo variable. `main` behaves
exactly as before; **nothing auto-activates.** Andrew turns it on via the
activation runbook:
[/Users/andrewpuschel/Documents/Claude/theheat/docs/2026-06-16_throughput-activation-runbook.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/2026-06-16_throughput-activation-runbook.md).

## What landed

| Phase | PR | Merge | Flag (default) |
|---|---|---|---|
| Plan-of-record (docs) | [#296](https://github.com/andrewzp/theheat/pull/296) | `d583a63` | — |
| A — funnel instrumentation | [#297](https://github.com/andrewzp/theheat/pull/297) | `edd39e7` | `THEHEAT_FUNNEL_TELEMETRY` (OFF) |
| B — decouple ship gate | [#298](https://github.com/andrewzp/theheat/pull/298) | `18be0fd` | `THEHEAT_AUTOSHIP_ON_CRITIC_PASS` (OFF) |
| C — refill loop | [#299](https://github.com/andrewzp/theheat/pull/299) | `7cb4aa7` | `THEHEAT_REFILL_ENABLED` (OFF), `THEHEAT_DRAFTS_TARGET_PER_CYCLE` (3) |
| D — multi-signal writer | [#300](https://github.com/andrewzp/theheat/pull/300) | `c4b5eb2` | `THEHEAT_MULTISIGNAL_CONTEXT` (OFF) |

- **A** — per-run funnel + top-10 shadow slate frozen onto `run_history`; new
  authenticated `GET /api/funnel` rolls up 7 days (built from `run_history`, not
  `source_health`) with `critic_pass_rate = passes/(passes+kills)`. Kills counted
  live (immune to the 100-row suppressions cap).
- **B** — auto-ships critic-PASSED, fresh, low-sensitivity allowlist drafts
  (`hot10`/`co2_milestone`/`ch4_milestone`) via the existing due-draft path, with
  flag-rollback / one-shot-idempotency / freshness / event-dedup guards.
  Fail-closed; human-impact categories stay `manual_only`.
- **C** — drain became a generate-and-select loop: ranked distinct candidates
  attempted until N succeed, success-aware caps, `$0` pre-writer cooldown/dedup
  predicate, admit-time annual-cap re-check via per-source closures; prune cap
  follows the target (one knob). Default target 3 = behavior-preserving.
- **D** — optional verifiable cross-signal context (`related_signals`, same
  country + 7-day window, max 2, global/coarse kinds excluded). Guidance rides
  the USER prompt (writer cache preserved). Deterministic cross-signal honesty
  gate rejects causal/synthesis framing; F3 critic + voice-regression are the
  activation backstops.

## State of the tree

- `main` suite: **2,931 → ~1,996 shown per phase run** — full `pytest -m "not
  voice_replay"` green; `mypy src/` clean; `ruff` clean; `next build`/dashboard
  tests green for the A dashboard route. (Per-phase counts in each PR.)
- CI `test` check green on every phase PR before squash-merge.
- All flags verified **absent from `.github/workflows/bot.yml`** (default OFF).

## Cross-model review

codex (gpt-5.5, read-only) reviewed every phase diff. It earned real findings on
A (3 P1s: triage_cap run_id, suppressions-cap kill freeze, REVISE double-count),
B (durability + freshness source-date + armed_auto guard-bypass + activation-window
hole + rate-limit consistency), C (static annual-cap map was wrong for SST /
insufficient for climate-index → replaced with per-source closures; snow cap
seasonal-only), and D (gate too literal → broadened to word-stems; global-kind
exclusion). All addressed; each phase ended codex-clean.

## Not done by design (Andrew's call)

- **Activation** — flipping any flag, posting live, raising `MAX_DRAFTS`, or
  touching the prod gist. Follow the runbook, in order A→B→C→D, watching the
  Funnel panel between steps.
- **voice-regression** was intentionally NOT run locally for D (paid live APIs);
  watch the replay when activating D.

## Open follow-ups (post-activation)

- After B runs a week with Phase-A data, consider widening B's allowlist beyond
  `armed_auto` types (a deliberate Andrew decision; keep it tiny until evidence).
- After C holds `critic_pass_rate` flat at target 3, raise
  `THEHEAT_DRAFTS_TARGET_PER_CYCLE`.
- D's cross-signal gate is a deterministic denylist (paraphrase-incomplete by
  nature); if voice-regression flags a synthesis miss the gate let through,
  tighten the stem list or lean harder on the critic.
