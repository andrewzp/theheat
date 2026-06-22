# Claim & Warrant Model — Design Brief + Session Kickoff

**Created:** 2026-06-16 · **Owner:** Andrew · **Status:** problem stated; design NOT yet done.
**Type:** software DESIGN problem — not a bug fix.

> **If this was pasted to you as a prompt:** this is your starting context, not a
> document to summarize. `cd /Users/andrewpuschel/Documents/Claude/theheat` first.
> Your FIRST move is to invoke the **`superpowers:brainstorming`** skill on the
> claim/warrant model described below — explore intent, requirements, and design
> before any code. The output of this session is a **reviewed design doc + an
> implementation plan, NOT merged code.** Do not jump to fixes or validation
> layers; that is the exact mistake this brief exists to correct.

---

## Where this came from (the incident)

On 2026-06-16, three `precipitation_extreme` drafts reached the human review queue
asserting records that do not exist:

- Barrow, Alaska — "427.5 mm in 7 days, 127.5 mm above the previous 7-day record of 300.0 mm"
- Amsterdam — "above a previous record of 300.0 mm" (the *same* 300.0, for a different city)
- Barrow — "the previous daily record was 0.0 mm"

427.5 mm in a week is roughly four times Barrow's *annual* precipitation. It is
physically impossible. All three drafts are well-written; they passed safety,
fact-check, and the critic. Only a human eye caught them.

## What it actually is (the reframe — read this twice)

This is **not a precip bug to be patched with validation.** The first instinct
(and the first wrong answer in the session that produced this brief) was to trace
the bug and add six layers of defense-in-depth. The tell that this is wrong: when
the proposed fix is "add six validators to catch a bad bundle," the design is
letting you *build* the bad bundle. Defense-in-depth is what you reach for when you
cannot change the model. Here we own the model.

**It is a software design defect, and every source shares it.**

## The data-flow trace (verified, with file:line)

```
_detect_rolling_accumulations (src/data/gpm_imerg.py:1090)   ← "300.0" originates here
   thresholds = {3: 150.0, 7: 300.0}                          it is a TRIGGER LEVEL
   if sum(last 7 days) >= 300:
     emit PrecipExtremeEvent(kind="multi_day_accumulation",
        previous_record_mm = threshold_mm,    # 300.0 — a threshold stuffed into a "record" field
        previous_record_year = None,          # the ONLY signal it is not a record
        deviation_from_record_mm = total - threshold_mm)   # 427.5 - 300 = 127.5
        │
        ▼  build_precipitation_bundle (src/two_bot/intern/precipitation.py:27,57)
   bundle carries previous_record_mm=300.0, previous_record_year=None
   (NOTE: snow bundles carry years_of_archive at line 84; precip carries NONE)
        │
        ▼  evidence_contract.audit_story_bundle()  → checks fields EXIST, not whether real → PASS
        ▼  writer (sees previous_record_mm: 300.0) → "above the previous 7-day record of 300.0 mm"
        ▼  fact_check (tweet 300.0 == bundle 300.0) → MATCH → PASS
        ▼  critic (well-written, astounding-if-true) → PASS
        ▼  review queue
```

The 0.0 daily "record" is the same shape on the other detector: `detect_precip_records`
(`src/data/gpm_imerg.py:528-540`) reads a baseline from `precip_daily_records`,
which `update_precip_tracking` (`src/data/gpm_imerg.py:572`) seeds from the data's
own first/zero reading. Dry first day → baseline 0.0 → next wet day "breaks the
record."

## Five whys → the architectural root

1. **Why does the draft claim a false record?** The writer was handed
   `previous_record_mm` values that are not records (300.0 is a threshold; 0.0 is a
   cold baseline) and cited them verbatim.
2. **Why was a threshold passed in a field named `previous_record_mm`?** The
   `multi_day_accumulation` detector overloads the record dataclass to carry a
   threshold and sets `previous_record_year=None`. Every downstream consumer treats
   that field as a real record. The one disambiguator (`previous_record_year is
   None`) is carried but **read by no one**.
3. **Why is there no distinction between a threshold-crossing and a real record,
   and no archive-depth guard?** Precip was built as a threshold/accumulation
   detector, not a climatological-record detector. It has no concept of minimum
   archive depth. Snow carries `years_of_archive`; precip carries none.
4. **Why did precip ship without record-rigor when temp/snow have it?** It was a
   rushed supply-pressure unlock (the gpm datapool migration, 0.9.15.0, 2026-06-06)
   to end a 19-day no-draft drought. The goal was "make precip fire," not "make
   precip's records true." It reused a record-shaped dataclass with threshold
   semantics.
5. **Why can a draft built on unvalidated data reach publish at all? (THE ROOT)**
   Every integrity gate validates *internal consistency*, never *external
   plausibility or warrant*. Fact-check confirms tweet matches bundle; the evidence
   contract confirms fields are present; the critic confirms prose quality. **None
   asks "is this bundle true, and is this actually a record?"** The StoryBundle is
   trusted as ground truth, so any detector bug becomes a publishable falsehood.

## The design problem, stated plainly

**The domain has no concept of a *claim* or its *warrant*.** Everything an extreme
could be — an observation, a baseline, a broken record, a threshold-crossing, an
anomaly — is flattened into one untyped event dataclass (per source) with nullable,
loosely-coupled fields associated *by convention, not by construction*. So
**illegal states are representable**: a record with no baseline, a threshold in the
record field, a zero baseline. The bad drafts are the design faithfully emitting
what it permits. Because every source shares this shape, it is systemic.

## Design direction to EXPLORE (a sketch, not the answer — pressure-test it)

The principle: **the warrant must be inseparable from the claim.** A `Record` should
be a type you cannot construct without a real, dated, deep-enough baseline. A
threshold-crossing is a different type that licenses different language. An anomaly
exists only relative to a climatology, so without a climatology you structurally
cannot assert an extreme (which is why "physical plausibility" is not a bolt-on
gate — it is a consequence of defining "extreme" relative to a model you must hold).

```
Observation   { value, unit, source, evidence_grade }
Baseline      { value, established_year, archive_span }   // optional; ABSENCE is meaningful
Claim =
   Record(observation, baseline)        // uninstantiable without a valid Baseline
 | ThresholdCrossing(observation, threshold)
 | Anomaly(observation, climatology)
 | Magnitude(observation)               // a big number, no record language
```

The writer consumes a `Claim`; the claim's type *is* its warrant. Most of the six
defense-in-depth layers then collapse into one: get the type right at the
source→writer boundary and the writer has nothing false to say. Runtime sanity
checks still exist, but they become thin *outputs* of the model (you cannot build a
`Record` with a null baseline) rather than validators racing to catch a falsehood
after it exists.

## Scope and non-negotiables

- **All source types, not just precip.** Map every existing detector/event onto the
  claim taxonomy; precip is just where it surfaced first.
- **Right-sized.** The change lives at the source→writer boundary — the "evidence
  contract" evolves from a *completeness* checker into a *claim/warrant* model. This
  is not a from-scratch rewrite.
- **Make illegal states unrepresentable.** Do not lead with validation layers.
- **Do not weaken the editorial bar or the existing gates;** this strengthens them.

## Relationship to in-flight work (coordinate)

A parallel autonomous session is building the four-phase **Throughput Initiative**
([2026-06-16-throughput-initiative-EXECUTION.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-throughput-initiative-EXECUTION.md)).
This design **reshapes Phase D** (the multi-signal writer's "deterministic honesty
gate" that codex demanded is really a special case of claim/warrant typing) and
**supersedes the evidence-contract's completeness-only posture**
([source-to-writer-evidence-contract.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/source-to-writer-evidence-contract.md)).
**Update — the four phases have now SHIPPED DARK** (PRs #297-#300 merged to `main`,
all behind default-OFF flags; activation runbook at
`docs/2026-06-16_throughput-activation-runbook.md`). So Phase D's `related_signals`
field and whatever honesty gate it built are REAL CODE on `main` now, not a plan.
READ the shipped Phase D and the current evidence contract, and design the
claim/warrant model to SUBSUME and refactor them — do not assume the pre-Phase-D
shape. Stage only your own files (never `git add -A`); land doc changes as their own PR.

## Open design questions for the brainstorm

- How do the ~10 existing event dataclasses (temp records, fire, coral DHW, SST
  anomaly, ice mass, snow, cyclone, etc.) map onto the claim taxonomy? Which break?
- Where does climatology come from (a table, a source, derived)? What is the minimum
  to define "anomaly/extreme relative to normal" without a heavy new dependency?
- Migration path: does `StoryBundle` gain a typed `claim` while keeping current
  fields for backward compatibility, or is it a clean cutover? How does the writer
  prompt consume a `Claim`?
- What is the minimum archive depth / baseline rule per claim type, and who owns it?
- How does this absorb Phase D's honesty gate so we build it once, not twice?

## The process — do it in THIS order (no code until step 6)

0. **Housekeeping:** the design-sweep docs (this file + the handoff, evidence-contract,
   and PIPELINE edits) are staged-uncommitted on a clean `main`. Land them as a docs
   PR first (`git switch -c docs/claim-warrant-brief`, stage only those files, PR,
   squash-merge, pull main) so the tree is clean before you design.
1. **`superpowers:brainstorming`** on the claim/warrant model. THIS IS YOUR FIRST SUBSTANTIVE MOVE.
2. Map every existing detector/event type onto the taxonomy; surface what breaks.
3. Decide the migration path (bundle compatibility, writer consumption, contract evolution).
4. Write the design doc (`superpowers:writing-plans`).
5. Cross-review: a `codex exec -s read-only` outside review **and** `/plan-eng-review`.
6. Only then produce the implementation plan. **No code is written this session.**

---

## KICKOFF PROMPT (paste this to start the new session)

> Pick up an in-progress design thread for the @theheat climate-tweet bot,
> autonomously. `cd /Users/andrewpuschel/Documents/Claude/theheat` and read
> `docs/plans/2026-06-16-claim-warrant-model.md` in full — it is your complete
> context (a verified data-flow trace, a five-whys root cause, and the design
> reframe). Do not re-derive it.
>
> This is a software DESIGN problem, not a bug. The system has no model of a *claim*
> or its *warrant*, so it can construct and publish "records" that are really
> thresholds or empty baselines. Your job is to design the claim/warrant model that
> makes those illegal states unrepresentable across ALL source types, and into which
> the evidence contract evolves.
>
> Your FIRST move is to invoke the `superpowers:brainstorming` skill on this model —
> explore intent, requirements, and the design before any code. Then map the
> existing event/detector types onto the taxonomy, decide the migration path, write
> the design as a doc (`superpowers:writing-plans`), and get BOTH a `codex exec -s
> read-only` outside review and a `/plan-eng-review` on it. The deliverable of this
> session is a reviewed design doc plus an implementation plan — NOT merged code. Do
> not reach for defense-in-depth validation layers as the primary solution; model
> the domain so the falsehood cannot be expressed.
>
> A parallel session is building the four-phase Throughput Initiative in the same
> repo; this design reshapes its Phase D and the evidence contract, so account for
> that and coordinate. Stage only your own files (never `git add -A`); land any doc
> changes as their own PR. Work autonomously; only stop for a genuine fork the brief
> does not resolve.
