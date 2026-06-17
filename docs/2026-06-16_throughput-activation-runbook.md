# Throughput Initiative — Activation Runbook

**Created:** 2026-06-16 · **For:** Andrew · **Status:** all four phases shipped
DARK (default-OFF) on `main`. This doc is how you turn them on, in safe order,
what to watch, and the one-variable rollback for each.

The whole initiative shipped behind repo variables that default OFF, so `main`
today behaves exactly as it did before — **nothing auto-activates.** You flip the
flags, one at a time, watching the dashboard between steps. Every rollback is a
single repo-variable flip (`gh variable set NAME --body 0`) with **no deploy**.

## What shipped (all dark)

| Phase | PR | Flag (default) | What ON does |
|---|---|---|---|
| A — funnel instrumentation | [#297](https://github.com/andrewzp/theheat/pull/297) | `THEHEAT_FUNNEL_TELEMETRY` (OFF) | Freezes a per-run funnel + top-10 shadow slate onto `run_history`; new `GET /api/funnel` rolls up 7 days incl. `critic_pass_rate`. |
| B — decouple ship gate | [#298](https://github.com/andrewzp/theheat/pull/298) | `THEHEAT_AUTOSHIP_ON_CRITIC_PASS` (OFF) | Auto-ships critic-PASSED, fresh, low-sensitivity allowlist drafts (`hot10`, `co2_milestone`, `ch4_milestone`). |
| C — refill loop | [#299](https://github.com/andrewzp/theheat/pull/299) | `THEHEAT_REFILL_ENABLED` (OFF) + `THEHEAT_DRAFTS_TARGET_PER_CYCLE` (3) | Generate-and-select: keeps attempting ranked distinct candidates until N succeed. |
| D — multi-signal writer | [#300](https://github.com/andrewzp/theheat/pull/300) | `THEHEAT_MULTISIGNAL_CONTEXT` (OFF) | Gives the writer optional verifiable cross-signal context (same country, same week). |

**Activate strictly A → B → C → D.** Each phase is the instrument or the
prerequisite for the next: A measures, B ships, C generates many, D makes them
outstanding. Do not skip ahead — without A live you are flying blind on B/C/D.

---

## Step 1 — A: turn on the gauge first

```
gh variable set THEHEAT_FUNNEL_TELEMETRY --body 1
```

- **Watch:** the dashboard **Funnel** panel (`GET /api/funnel`). After the next
  alerts cycle (the `0 0,4,8,16,20` cron), confirm it renders: stage volumes
  (observed → … → drafted), `critic_pass_rate`, per-stage kills, and a recent
  **shadow slate** with terminal stages. The first cycle after flip-on is the
  first run with a `funnel` block in `run_history`.
- **Success:** `critic_pass_rate` is a real number (not null) and the shadow
  slate lists candidates with terminal stages (drafted / triage_cap / critic / …).
- **Let it run a few days** before Step 2 — you want a baseline `critic_pass_rate`
  and a feel for where the funnel collapses.
- **Rollback:** `gh variable set THEHEAT_FUNNEL_TELEMETRY --body 0` (pure
  observability; nothing else depends on it being on, but B/C/D are unverifiable
  without it).

## Step 2 — B: restart shipping, tiny

```
gh variable set THEHEAT_AUTOSHIP_ON_CRITIC_PASS --body 1
```

- **Scope:** the hard allowlist only — `hot10`, `co2_milestone`, `ch4_milestone`.
  A draft auto-ships only if it earned a real **critic PASS**, is **fresh**
  (`THEHEAT_AUTOSHIP_MAX_AGE_H`, default 36h, over queue age AND source date), and
  its event isn't already posted. Human-impact categories stay `manual_only`.
- **Watch:** the live **@theheat** feed + the dashboard **Drafts** queue. The
  first auto-shipped tweets should be CO2/CH4 milestones or the Hot-10 leaderboard.
  Confirm the freshness gate is demoting anything stale to manual (look for
  `post_error: "Autoship blocked: stale framing…"`).
- **Idempotency:** an auto-ship that doesn't cleanly confirm "posted" is handed to
  a human (`approval_mode` → manual), never blind-retried — so a failed attempt is
  safe, just look for it in the queue.
- **Rollback:** `gh variable set THEHEAT_AUTOSHIP_ON_CRITIC_PASS --body 0`.
  Stops auto-shipping immediately, including any already-armed drafts.

## Step 3 — C: generate more, same target

```
gh variable set THEHEAT_REFILL_ENABLED --body 1
```

- Leave `THEHEAT_DRAFTS_TARGET_PER_CYCLE` at **3** for now (behavior-preserving;
  the win is that a failed top candidate no longer yields nothing — the loop
  reaches the next-best distinct candidate).
- **Watch:** the **Funnel** panel — `drafted` should rise (or hold on thin days)
  **while `critic_pass_rate` stays flat**. If `critic_pass_rate` drops, the loop
  is reaching below genuine supply; that's the signal to NOT raise the target.
- **Only then** consider raising the target:
  `gh variable set THEHEAT_DRAFTS_TARGET_PER_CYCLE --body 5` (watch
  `critic_pass_rate` again after the bump).
- **Rollback:** `gh variable set THEHEAT_REFILL_ENABLED --body 0` (reverts to
  top-3-once).

## Step 4 — D: make them outstanding

```
gh variable set THEHEAT_MULTISIGNAL_CONTEXT --body 1
```

- The writer now gets up to 2 same-country, same-week related signals and may
  write a synthesis tweet — but only as **bare enumeration**; a deterministic gate
  kills any causal / "global pattern" framing.
- **Watch (most important here):** the **voice-regression replay** and the
  **`critic_pass_rate` on synthesis drafts** in the Funnel panel. Phase D's
  honesty gate is a deterministic first layer; the critic + voice-regression are
  the backstops, so this is the phase to watch the regression corpus closely.
  `critic_pass_rate` should go **up, not down** — if it drops, the synthesis
  framing isn't landing.
- **Reading `voice-regression` correctly (changed 2026-06-17, PR #304):** a
  writer **KILL is no longer a failure** in this suite. The writer's own rule is
  "killing is the default; a mediocre tweet is worse than silence," so the
  replay now only goes **red when the writer SHIPS bad copy** (>280 chars,
  banned patterns, fabricated context, dishonest regional framing) or fails to
  decline an out-of-scope signal. Green = "never shipped anything bad." If it
  goes red, that is a genuine voice regression worth stopping for. "Is the
  writer too quiet?" is now answered by the **Phase-A Funnel** (live pass/kill
  rates), not by this corpus. (This replaced the old contract that hard-asserted
  "the model always emits a tweet," which flaked red for five days when the
  writer correctly declined a bare-earthquake and a length-tight bundle.)
- **Rollback:** `gh variable set THEHEAT_MULTISIGNAL_CONTEXT --body 0` (reverts to
  the single-event writer, byte-identical).

---

## If anything looks wrong

Every phase is independently reversible with one repo-variable flip and no deploy.
Flip the offending phase's flag to `0`; the others keep their state. Because each
phase is byte-for-byte the prior behavior when OFF, a rollback can never make
things worse than before the initiative. When in doubt, roll back the most recent
flip and re-check the Funnel panel.
