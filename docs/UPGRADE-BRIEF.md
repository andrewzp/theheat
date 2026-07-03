# Upgrade Brief — assess @theheat & produce a whole-project upgrade plan

> **For the next session (Fable 5).** Andrew's ask: *step back, assess the entire @theheat
> project, and come up with a detailed, prioritized plan to upgrade the whole thing.* This
> brief is your starting point — not a plan to execute, but the context and the mandate to
> produce one. Don't just patch the next bug; see the whole system and plan its upgrade.

## Your assignment

Produce a **detailed, prioritized upgrade plan** across three pillars (below). For each:
what's wrong today, what "good" looks like, the sequenced steps to get there, effort/risk,
and the first concrete move. Assess first (read the pointers, read the code), then plan via
`superpowers:brainstorming` → `superpowers:writing-plans` → codex-xhigh review of the plan
→ incremental build behind default-OFF flags → live verify → flip on. Sequence by leverage;
don't boil the ocean in one PR.

## Read first (in order)

1. **[docs/VISION.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/VISION.md)** — the north star: what "good" means, and the failure we're organized around.
2. **[docs/handoffs/2026-07-03.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-07-03.md)** — the latest session record + live operational state (credits restored, what shipped, open branches).
3. **[BRIEFING.md](/Users/andrewpuschel/Documents/Claude/theheat/BRIEFING.md)** + **[PIPELINE.md](/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md)** — how the system actually works today (sources → detect → score/triage → writer → safety → fact-check → critic → autoship/manual → post; state in a GitHub Gist; a Vercel dashboard; CI in GitHub Actions).
4. **[docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md)** — Bet A (Pillar 2), brainstorm in progress, 3 decisions locked.
5. **[docs/superpowers/specs/2026-06-25-coverage-monitor-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-06-25-coverage-monitor-design.md)** — a coverage-gap sibling design (Pillars 2+3), codex-reviewed, unbuilt.
6. **[docs/FUTURE_STATE.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/FUTURE_STATE.md)** + **[docs/IDEAS.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/IDEAS.md)** — forward architecture + parked/requested ideas.

## What works today (don't rebuild these)

The pipeline runs end-to-end and the writing engine, pointed at the right event, is good
(e.g. the shipped Prudhoe Bay all-time-high draft). The honesty gates are strong (fact-check,
critic, the deterministic §F gate, the claim/warrant principle). Recent ships: reganom
voice upgrade (#349), autoship of verifiable records (#352). The bot posts autonomously with
a human review queue for sensitive types.

## The three pillars to upgrade

### Pillar 1 — Editorial excellence + sourced anecdotes
**Today:** tweets are "data-ticker competent" — honest, accurate, clean — but rarely
scroll-stopping. They carry a number and a place, not a human story. There is **no path for
sourced anecdotes** (death tolls, "buses crashed, drivers passed out," a record that fell
for the second straight year) — the concrete human detail that makes a good news story.
**Good:** every tweet reads like a sharp news story or Economist paragraph and, where the
event has human stakes, carries a **cited** anecdote. **Constraint:** every anecdote comes
from real sourced retrieval, never the model's imagination (IDEAS.md item #10).

### Pillar 2 — Global newsworthy coverage (Bet A)
**Today:** the bot ranks by raw sensor magnitude and is **blind to newsworthiness + human
stakes.** It **missed the European heat wave that killed 1,200+ people ENTIRELY**, and the
same week posted a remote Congo Basin fire while suppressing the deadly Colorado fire (62<64).
It covers the loudest sensor, not the biggest story. **Good:** a sourced sense of what's
happening in the world re-ranks selection (Colorado beats Congo) and surfaces events it's
blind to; global, not US-centric. **Direction chosen:** Bet A (design in brainstorm — 3
decisions locked: hybrid feeds+grounded-search source; v1 = re-rank + enrich; boost =
rescue-capped). Resume that brainstorm; fold in the coverage-monitor design.

### Pillar 3 — Reliability: things must stop failing (NEW — first-class)
**The pattern that has to end: the system fails SILENTLY.** It stays "green" while producing
wrong or no output, and only a human noticing the feed catches it. Evidence from recent
weeks:
- **Anthropic credits silently exhausted** → the writer stopped drafting for hours; bot runs
  still reported `success` (graceful `BudgetExhaustedError`); nothing alerted. Only an empty
  feed + voice-regression going red surfaced it. *No alert on low balance / writer-down.*
- **CI time-bombs** — a test hard-coded a date that rotted past a 21-day window and began
  failing `main` CI on every PR (2026-07-03, CO2 last-good test). *Class: time-dependent
  tests/fixtures/data that rot with the calendar.*
- **Good drafts silently stuck** — records piled up unposted in an unwatched manual queue
  (autoship allowlist too narrow; fixed for records in #352, but the "is anyone reviewing?"
  gap and the 23-draft backlog remain).
- **Coverage blindness** — the heat detector ran **US-only for ~7 weeks**, blind to a European
  heatwave, green by every liveness metric (coverage-monitor design addresses this; unbuilt).
- **Silent detection bugs** — a world-eval gating defect produced `cov:0.0` (zero record
  detection) for ~2 weeks, invisible until instrumented (fixed #345).
- **Recurring outages** — weekend source outages, source-health gaps; self-heal exists
  (#306+) but is PAT-gated and partial.

**Good:** the system **fails loudly and recovers** — alerting on writer-down / credits-low /
coverage-gap / queue-backup / CI-red; no time-bombs (tests use relative time); self-heal
where safe; every "green but wrong" path instrumented so it can't hide. Treat observability
+ alerting + robustness as a product feature, not an afterthought. This pillar is the one
Andrew flagged most sharply: *"things need to stop failing."*

## Constraints that never bend

- **No false claims, ever.** Every figure — record, death toll, anecdote — from real cited
  retrieval, never the model's imagination. A hallucinated death toll is the one unforgivable
  error. The honesty gates (fact-check, critic, §F, claim/warrant) stay; upgrades strengthen
  the bar, never weaken it.
- **Standing rules** (see the handoff): CI = ruff + mypy + pytest + dashboard build; codex-
  xhigh review anything touching editorial gates / posting / state / storage, looped to clean;
  docs as their own PR; Andrew never merges (Claude merges on green); ship behind default-OFF
  repo variables and verify live before flipping on. The writer is the **metered Anthropic
  API** (not the Max plan) — a low balance silently stops drafting.

## Open threads to fold into the plan (not lose)

- Bet A brainstorm (resume from Q4); the reganom stakes-attribution branch (needs codex + PR
  — fixes a fact-check-failing exemplar on `main`); the 23-draft manual backlog (approve/reject
  by hand once); #346 dup-city (held); the hand-sourced heat/fire drafts ready to post. All
  detailed in the 2026-07-03 handoff.

## What to hand back

A prioritized, sequenced upgrade plan across the three pillars — with the first PR-sized step
for each — that Andrew can approve and we can execute incrementally. Lead with the pillar of
highest leverage; make the reliability work concrete (specific alerts, specific self-heal,
specific de-risking), not aspirational.
