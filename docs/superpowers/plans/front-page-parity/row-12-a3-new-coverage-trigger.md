# Row 12 — A3 (Bet A v2): the new-coverage trigger — GATED design skeleton

> **⛔ DO NOT BUILD YET.** This row is evidence-gated by design (the Bet A spec's §Out:
> "The gap flag collects the evidence for whether/when to build it"). This doc exists so
> the evidence review is mechanical and the eventual plan doesn't start from zero. When
> the checklist below passes, this skeleton goes through the FULL pipeline:
> superpowers:brainstorming (with Andrew) → superpowers:writing-plans → codex-xhigh on
> the plan → build. It is the highest-risk row in the program: a drafting path whose
> ONLY source is news retrieval.

**What it is:** drafting a story the sensors never saw — the pure death-toll tweet (the
Europe-heatwave class: WHO-reported 1,300+ excess deaths, zero sensor path). A verified
`NewsEvent` itself originates a `manual_only` draft.

## The evidence gate (all four must hold before brainstorming starts)

1. **≥21 days of gap-flag data** with the master flag live (track-0 step 1 sets the
   clock).
2. **≥3 distinct verified `missed`-stage events** (row 8's FPP rollups are the ledger)
   in a single vertical — the vertical A3 v1 would cover. Fewer means boost+enrich are
   absorbing the misses and A3 can wait.
3. **The misses are structural, not tunable:** for each, write one line on why no
   existing knob (boost floor, thresholds, a new sensor class like row 5/13) would have
   caught it. A miss a threshold tweak fixes is not A3 evidence.
4. **Andrew picks the vertical(s)** and confirms the risk posture (this is the
   classifier's call — a news-originated drafting path is a genuinely new trust
   surface).

## Design constraints already locked (do not re-litigate at brainstorm time)

- **The iron constraint, doubled:** every figure in a news-originated draft must trace
  to a verified impact entry (source+url+as_of). There is no bundle-of-sensor-facts to
  lean on — the evidence contract for the new `signal_kind="news_report"` must require
  ≥1 verified impact entry and reject any headline_metric not backed by one.
- **`manual_only`, hard-coded** — not by type-prefix convention but explicitly, plus
  decision-4's citation forcing (which will fire anyway: every such draft cites
  impact).
- **Writer sees projections, not raw retrieval** — the claim/warrant principle (#324):
  the bundle carries the verified entries and NOTHING the writer could mistake for a
  sensor fact. If #324 has shipped by then, `ImpactFact` is a claim kind and this
  falls out; if not, the bundle builder enforces it manually.
- **Rate-capped:** ≤1 news-originated draft per cycle, per-vertical annual-cap
  consideration at brainstorm time.
- **Dedup against the sensor lanes:** a news event that ALSO matches a sensor
  candidate must never draft twice (the matcher's stage function, row 8, is the
  guard: only `missed`-stage events are A3-eligible).

## Pre-work that pays off regardless (fold into other rows, not a new PR)

- Row 8 already archives per-event stages weekly — that IS the evidence ledger.
- Row 10's WHO EURO feed leg, if built, becomes A3's structured source for the heat
  vertical — contract-first there means A3 inherits a verified feed.

**When the gate passes:** open the brainstorm with this doc + the FPP issues for the
evidence weeks + the Bet A spec §Out, and write the real implementation plan as
`row-12-a3-implementation.md` beside this file.
