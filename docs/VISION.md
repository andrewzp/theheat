# @theheat — Vision & Upgrade Brief

> **The north star AND the mandate — read this first.** It says what "good" means, names the
> failure we are organized around, and hands the next session the assignment: step back,
> assess the *whole* @theheat project, and produce a detailed, prioritized plan to upgrade it.
> Don't just patch the next bug — see the whole system and plan its upgrade.

## The mission

@theheat surfaces the most significant climate and extreme-weather events on Earth, in real
time, as tweets a climate-literate reader stops scrolling for and sends to a friend. **The
data is the product; the voice is the chassis it rides in.**

## What "good" looks like — three bars we are NOT yet clearing

1. **Editorially excellent.** Every tweet should be genuinely well-written — the quality of a
   sharp news story or an Economist paragraph, not a data-ticker readout. Honest and accurate
   is the floor, not the goal.
2. **Carries interesting anecdotes, like a good news story.** The best coverage carries the
   human and concrete detail — the death toll, the firefighters killed, "buses crashed,
   drivers passed out," the record that fell for the second straight year. A number without a
   human stake is a stat; a number *with* one is a story. Every such detail must be **sourced,
   cited, and real — never invented.**
3. **Global coverage.** We cover the whole planet, not the loudest sensor. The biggest story
   *anywhere* on Earth should reach the feed — not just where a single sensor spikes highest.

## The failure that proves the gap

In late June 2026, a heat wave killed **more than 1,200 people across Europe** (the WHO
counted **1,300+ excess deaths**; ~1,000 in France alone) — one of the deadliest weather
events of the year. **@theheat missed it ENTIRELY.** Not "covered it weakly" — the death toll
never had *any path* into the bot.

The same days, the bot **posted** a remote 1,468 MW fire in the Congo Basin, DR Congo, while
**suppressing** the deadly Colorado/Utah wildfire outbreak — 3 firefighters killed, 79 fires
across 10 states, the lead of the Washington Post — because its sensor score fell *one point*
below a cutoff (62 < 64). **It surfaced the biggest NUMBER and missed the biggest STORY.**
Twice, in one week, on the two deadliest weather events on Earth.

**Root cause:** the bot ranks signals by **raw sensor magnitude** (megawatts, °C anomaly) and
is **blind to newsworthiness and human stakes.** It sees disaggregated sensor pixels, not
events; it has no sense of what is actually happening in the world, and no way to carry the
human toll of what it does detect.

## Your assignment (the next session)

> **STATUS (2026-07-06): EXECUTED.** The assessment ran, the plan exists —
> [docs/superpowers/plans/2026-07-03-three-pillar-upgrade-plan.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-07-03-three-pillar-upgrade-plan.md)
> — and its rows 1–5 are merged (#361–#366: reganom fix, writer/queue watches,
> time-travel canary, Bet A phase 0 dark). The mission and bars above remain the
> north star; current state lives in the latest handoff. This section is kept as
> the record of the mandate.
>
> **STATUS (2026-07-07): rows 1–8 ALL MERGED (E1 fire voice floor closed the
> queue).** The mandate re-ran at Andrew's request as a whole-project audit against
> the three bars — verdict: not yet cleared (A-rate 20% vs >50%; queue-vs-world
> zero fire/cyclone drafts; Bet A still dark) — and produced the SUCCESSOR program:
> the **front-page-parity plan** + per-row implementation plans, awaiting Andrew's
> adoption in [PR #382](https://github.com/andrewzp/theheat/pull/382). Its two
> managed numbers (FPP + A-rate) are the bars above, made measurable.

Produce a **detailed, prioritized upgrade plan** across the three pillars below. For each:
what's wrong today, what "good" looks like, the sequenced steps to get there, effort/risk, and
the first PR-sized move. **Assess first** (read the pointers, read the code), **then plan** via
`superpowers:brainstorming` → `superpowers:writing-plans` → codex-xhigh review of the plan →
incremental build behind default-OFF flags → live verify → flip on. Sequence by leverage; lead
with the highest-leverage pillar; don't boil the ocean in one PR.

## The three pillars to upgrade

### Pillar 1 — Editorial excellence + sourced anecdotes
**Today:** tweets are "data-ticker competent" — honest, accurate, clean — but rarely
scroll-stopping; they carry a number and a place, not a human story. There is **no path for
sourced anecdotes** (death tolls, "buses crashed," a record falling two years running).
**Good:** every tweet reads like a sharp news story and, where the event has human stakes,
carries a **cited** anecdote. **Constraint:** every anecdote from real sourced retrieval,
never the model's imagination (see [docs/IDEAS.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/IDEAS.md) item #10).

### Pillar 2 — Global newsworthy coverage ("Bet A")
**Today:** ranks by raw sensor magnitude, blind to newsworthiness + human stakes — it missed
the European heat wave entirely and posted Congo over the deadly Colorado fire. **Good:** a
sourced sense of what's happening in the world re-ranks selection (Colorado beats Congo) and
surfaces events the sensors miss; global, not US-centric. **Direction chosen (Andrew): Bet A.**
Design in brainstorm — 3 decisions locked (hybrid feeds + grounded-search source; v1 = re-rank
+ enrich; boost = rescue-capped). Resume it:
[docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md);
fold in the coverage-gap sibling design
[docs/superpowers/specs/2026-06-25-coverage-monitor-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-06-25-coverage-monitor-design.md).

### Pillar 3 — Reliability: things must stop failing (first-class)
**The pattern that has to end: the system fails SILENTLY.** It stays "green" while producing
wrong or no output, and only a human noticing the feed catches it. Evidence from recent weeks:
- **Anthropic credits silently exhausted** → the writer stopped drafting for hours; bot runs
  still reported `success` (graceful `BudgetExhaustedError`); nothing alerted. *No alert on low
  balance / writer-down.* (The writer is the metered Anthropic API, not the Max plan.)
- **CI time-bombs** — a test hard-coded a date that rotted past a 21-day window and began
  failing `main` CI on every PR (2026-07-03, CO2 last-good). *Class: time-dependent
  tests/fixtures/data that rot with the calendar.*
- **Good drafts silently stuck** — records piled up unposted in an unwatched manual queue
  (autoship allowlist too narrow; fixed for records in #352, but the "is anyone reviewing?"
  gap and the draft backlog remain).
- **Coverage blindness** — the heat detector ran **US-only for ~7 weeks**, blind to a European
  heatwave, green by every liveness metric (coverage-monitor design addresses this; unbuilt).
- **Silent detection bugs** — a world-eval gating defect produced `cov:0.0` (zero record
  detection) for ~2 weeks, invisible until instrumented (fixed #345).
- **Recurring outages** — weekend source outages + source-health gaps; self-heal exists (#306+)
  but is PAT-gated and partial.

**Good:** the system **fails loudly and recovers** — alerting on writer-down / credits-low /
coverage-gap / queue-backup / CI-red; no time-bombs (tests use relative time); self-heal where
safe; every "green but wrong" path instrumented so it can't hide. Treat observability +
alerting + robustness as a product feature, not an afterthought. This is the pillar Andrew
flagged most sharply: *"things need to stop failing."*

## The non-negotiable constraint

**No false claims, ever.** Every figure — a record, a death toll, an anecdote — must come from
**real, cited retrieval, never the model's imagination.** Current news is past the writer
model's knowledge cutoff, so a hallucinated death toll is the one unforgivable error — worse
than a boring tweet, worse than a missed one. **Editorial excellence, anecdotes, and global
coverage are the goal; verifiable truth is the constraint that never bends.** The honesty gates
(fact-check, critic, the deterministic §F gate, the claim/warrant principle) stay; upgrades
strengthen the bar, never weaken it.

## Read first / how we work

- **Context to read before planning:** [docs/handoffs/2026-07-03.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/handoffs/2026-07-03.md)
  (latest session record + live state) · [BRIEFING.md](/Users/andrewpuschel/Documents/Claude/theheat/BRIEFING.md)
  + [PIPELINE.md](/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md) (how the system works today) ·
  [docs/FUTURE_STATE.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/FUTURE_STATE.md) (forward architecture) ·
  the two design docs linked under Pillar 2.
- **What already works (don't rebuild):** the pipeline runs end-to-end and the writing engine,
  pointed at the right event, is good (e.g. the shipped Prudhoe Bay all-time-high draft); the
  honesty gates are strong; records now auto-post (#352); reganom voice upgraded (#349).
- **Standing rules:** CI = ruff + mypy + pytest + dashboard build; codex-xhigh review anything
  touching editorial gates / posting / state / storage, looped to clean; docs as their own PR;
  Andrew never merges (Claude merges on green); ship behind default-OFF repo variables, verify
  live, then flip on.
- **Open threads not to lose** (detail in the 2026-07-03 handoff): Bet A brainstorm (resume
  from Q4); the `fix/reganom-stakes-attribution` branch (needs codex + PR — fixes a
  fact-check-failing exemplar on `main`); the manual draft backlog (approve/reject by hand
  once); #346 dup-city (held); hand-sourced heat/fire drafts ready to post.

## What to hand back

A prioritized, sequenced upgrade plan across the three pillars — with the first PR-sized step
for each — that Andrew can approve and we execute incrementally. Make the reliability work
concrete (specific alerts, specific self-heal, specific de-risking), not aspirational.
