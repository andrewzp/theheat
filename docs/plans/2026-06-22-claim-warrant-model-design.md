# Claim & Warrant Model — Design Doc

**Created:** 2026-06-22 · **Owner:** Andrew · **Status:** design for review (codex + plan-eng-review)
**Type:** software DESIGN. No code is written this session; deliverable is this doc + an implementation plan.
**Brief / context:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-claim-warrant-model.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-claim-warrant-model.md)
 (verified data-flow trace, five-whys, reframe — not re-derived here).

---

## 1. Problem & intent (condensed; see brief for the full trace)

The system trusts `StoryBundle` as ground truth and has **no type for what kind of
assertion a bundle makes or what reference licenses it.** A comparative claim
("above the previous record of 300 mm") can carry a **fake or absent reference** — a
detection threshold, or a 0.0 self-seeded baseline — and every gate downstream
(completeness contract, fact-check, critic) validates *internal consistency*, never
*warrant or plausibility*. The 2026-06-16 precip drafts are the design **faithfully
emitting what it permits.** Because every source shares the untyped shape, it is
systemic, not a precip bug.

**Intent of this design:** make the *reference inseparable from the claim*, so a
false framing is **unconstructable** at the source→writer boundary — across all
source types — and so the existing post-hoc honesty gates collapse into the type
instead of racing to catch a falsehood after it exists.

**Non-negotiables (from brief):** make illegal states unrepresentable (do NOT lead
with validation layers); right-sized at the source→writer boundary (not a rewrite);
do not weaken the editorial bar or existing gates — strengthen them; cover all
sources.

## 2. The core reframe: a claim type **is** "what is the reference?"

Every extreme the bot publishes is one of a few *kinds of assertion*, and each kind
is defined by **the reference object it cannot exist without.** Strip the reference
and the comparative language becomes a lie; so the type carries the reference, and
the reference is constructible only when real.

| Claim type | Reference it REQUIRES (uninstantiable without) | Licenses language like | Downgrades to (if reference absent/insufficient) |
|---|---|---|---|
| **Record** | `Baseline {value, established_year, archive_span_years ≥ MIN}` | "broke the previous record of X, set in YYYY" | ThresholdExceedance → Magnitude |
| **ThresholdExceedance** | `Threshold {value, name, provenance}` | "past the X level", "N× the WHO guideline" | Magnitude |
| **Anomaly** | `Climatology {normal, dispersion, reference_period}` | "Nσ above normal", "+X vs the 1991–2020 average" | Magnitude |
| **Milestone** | `MonotonicSeries {first_crossing: True, series_id}` | "first time ever above X" | **Magnitude** (NOT ThresholdExceedance — see §2b) |
| **Categorical** | `Authority {body, designation}` | "USGS classifies this M7.1 as significant" | — (already the floor for curated feeds) |
| **Magnitude** | `Observation` only | value + place + time; **no comparative words** | — (universal safe floor) |

This is the whole model in one idea. The precip incident in this frame: the detector
emitted claim-type **Record** while the reference was a **Threshold** (300 mm) or a
**days-deep self-seed** (0.0 mm). Under the model, `Baseline` is unconstructable from
either, so the builder is *forced* to emit **ThresholdExceedance** ("a 7-day total
past the heavy-rain threshold") or **Magnitude** ("427 mm in a week at Barrow") —
both **true**. The draft still ships; only the false framing dies.

### 2a. Two added types vs the brief's sketch (Record/ThresholdCrossing/Anomaly/Magnitude)

The brief invited pressure-testing. Mapping against all 32 real event dataclasses
(§4) forced two additions; collapsing either re-enables a real falsehood:

- **Milestone** — CO2/CH4 `ppm_crossed`/`ppb_crossed`, ice-mass −1000 Gt steps, SST
  "first day above archive max." A milestone is *first-ever and permanent*; a
  threshold *recurs* (coral DHW every season). Different warrant (a monotonic series
  vs a fixed bar), different language ("first time" vs "crossed"). Without the type,
  nothing stops "first time" when it isn't.
- **Categorical** — USGS significant quakes, GDACS red alerts, Copernicus
  activations, ENSO state, cyclone basin records. The warrant is *an external
  authority's designation*, not a numeric comparison the bot holds. The failure mode
  is overstating beyond what the authority said; the type carries the attribution and
  licenses only it. Forcing these into a comparative type (Record/Anomaly) would
  manufacture a baseline the bot does not possess — the precip mistake again.

### 2b. The downgrade ladder (not a kill switch)

A missing warrant **weakens the claim; it does not drop the draft.** The builder
constructs the *strongest claim whose reference is real*, walking down the ladder:

- **Record → ThresholdExceedance → Magnitude** — a missing/insufficient baseline
  falls to a named threshold if one exists, else to a bare magnitude.
- **Milestone → Magnitude** (NOT → ThresholdExceedance). *Correction from the codex
  outside-review:* a milestone is first-ever and permanent; downgrading it to a
  threshold-crossing would imply a *recurring bar* the monotonic series does not
  warrant ("crossed the 420 ppm level" reads as a line that can be re-crossed). A
  Milestone may only downgrade to ThresholdExceedance if the source carries an
  explicitly named recurring threshold with provenance; otherwise it falls straight
  to Magnitude.

**Magnitude is the universal floor** — any genuine observation can be stated as a
value in a place at a time with no comparative language. This is deliberate: the
Throughput Initiative (PRs #297–#300) just shipped to end a 19-day drought, so the
model forbids the *lie*, not the *draft*. A kill only happens when even a Magnitude
observation is unsound (e.g., no value), which the completeness contract already
catches. The ladder lives in **one factory** (`claim_from_warrants(...)`, §5b), not
re-implemented across the ~30 builders.

### 2c. Compound claims subsume BOTH existing honesty gates (scope finding)

The repo has **two** `signal_kind`-keyed post-hoc text denylists, not one — both the
same anti-pattern (let the writer write, then scan the tweet for banned phrases,
because nothing types what the warrant licenses):

- **Phase D** `_cross_signal_violation` ([pipeline.py:88](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/pipeline.py)) — when `related_signals` are present, ban ~80 causal/synthesis word-stems.
- **§F** `_forbidden_claim_violation` ([pipeline.py:20](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/pipeline.py)) — for `regional_anomaly`, ban a curated `forbidden_claims` list (in-code: *"the LOAD-BEARING honesty layer"*).

The model dissolves both into the type:

- A **CompoundClaim** = a list of independently-warranted component `Claim`s exposing
  **only an enumeration view** — there is *no field* for a relation/cause/system, so
  causation is literally unwriteable. This subsumes Phase D's `related_signals`
  (cross-source) **and** `OscillationAlignmentEvent` (NAO+AO co-extreme — the same
  shape *within* one source).
- `regional_anomaly` becomes an **Anomaly** whose `where` is structurally *"16
  sampled cities in {region}"*. "The region's average" is not a citable fact on the
  claim, so the `forbidden_claims` list collapses into the type.

**This design therefore reshapes Phase D *and* §F — broader than the brief assumed,
which named only Phase D.** Both `pipeline.py` gates become thin backstops (or are
replaced by a single check: "does the draft's comparative language match the claim
type's licensed set?") rather than per-`signal_kind` special cases.

### 2d. Cross-cutting qualifiers (orthogonal to claim type)

These ride on any base claim, each with a constructor invariant; they are *not* new
types (YAGNI — they don't define a new reference, they modify an existing claim):

- **`evidence_grade`** ∈ {`observed`, `model_estimated`, `model_fallback`} — already
  exists in the codebase (precip R-03 Open-Meteo fallback at
  [precipitation.py:38](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern/precipitation.py); air-quality `model_estimated`). Part of the warrant: a model estimate
  cannot license "measured/observed/recorded."
- **`streak_days: int ≥ 1`** (verified consecutive) — SnowExtreme `consecutive_days`,
  RecordStreak, MHW `days`.
- **`transition: {from, to}`** — ENSO state change, cyclone TierCrossing, RI delta.

## 3. Domain types (sketch — Python dataclasses, frozen)

Illustrative shape, not final signatures (the implementation plan finalizes them).
Construction-time invariants (`__post_init__`) are what make illegal states
unrepresentable; the contract (§5) is then a thin *output* of the model, not a racing
validator.

```python
@dataclass(frozen=True)
class Observation:
    value: float
    unit: str
    where: str
    when: str
    evidence_grade: str = "observed"        # observed | model_estimated | model_fallback

@dataclass(frozen=True)
class Baseline:
    value: float
    established_year: int                    # NEVER None — absence is meaningful
    archive_span_years: int                  # must clear a per-claim minimum
    def __post_init__(self):
        if self.established_year is None:
            raise WarrantError("Record baseline requires a dated prior extreme")
        # archive_span_years ≥ MIN enforced by the Record constructor (policy in §6)

@dataclass(frozen=True)
class Threshold:
    value: float
    name: str                                # e.g. "WHO 24h PM2.5 guideline", "7-day heavy-rain"
    provenance: str                          # who defined it

@dataclass(frozen=True)
class Climatology:
    normal: float
    dispersion: float                        # stdev / IQR
    reference_period: str                    # e.g. "1991–2020"

# Claim = a tagged union (one dataclass per type, common .observation + .licenses())
Record(observation, baseline)                # uninstantiable without a valid Baseline
ThresholdExceedance(observation, threshold)
Anomaly(observation, climatology)
Milestone(observation, series_id, first_crossing=True)
Categorical(observation, authority_body, designation)
Magnitude(observation)                       # licenses no comparative language

CompoundClaim(primary: Claim, related: tuple[Claim, ...])   # enumeration-only view
```

Each `Claim` exposes:
- `.observation` — the headline fact.
- `.licenses()` — the set of comparative phrasings this type permits (drives the
  writer prompt and the single honesty check). A `Magnitude` returns the empty set.
- `.to_bundle_facts()` — the *only* facts the writer sees for the comparison; a
  threshold value is labeled a **threshold**, never `previous_record_mm`.

`WarrantError` is the single exception raised when a builder tries to construct a
claim whose reference is absent/insufficient; the builder catches it and downgrades.

## 4. Full taxonomy mapping — all 32 event dataclasses

Verified inventory (file:line confirmed by direct read for the load-bearing rows).
"Break" = where today's code mis-types or cannot warrant its claim.

### Record (warrant: dated Baseline, archive_span ≥ MIN)
| Event (file) | Today | Maps to | Break? |
|---|---|---|---|
| `AllTimeRecord` (open_meteo) | `old_record_year`,`years_of_data` | Record | clean |
| `MonthlyRecord` (open_meteo) | `old_record_year`,`years_of_data` | Record | clean |
| `RecordEvent` (open_meteo, calendar-date) | `old_record_year`, **no `years_of_data`** | Record | **B4: archive_span missing on this type** (sibling `AllTimeRecord` has it, line 54) |
| `CountryRecord` (open_meteo) | archive-wide peak | Record (aggregate) | clean |
| `SeaIceRecord` | `previous_extent`,`previous_year` (1978+) | Record | clean |
| `OzoneHoleSeasonalEvent` | `record_year`,`previous_year`,`trailing_10yr` | Record (+anomaly ctx) | clean |
| `SnowExtremeEvent` (record kinds) | `previous_record_*`,`years_of_archive` | Record (+streak) | clean — the reference model precip lacks |
| `IceMassRecord` (monthly kind) | `previous_worst_gt/month` (2002+) | Record | clean |
| `MarineHeatwaveStreakEvent` | `archive_max_c/year`,`years_of_data`,`days` | Record + streak (+milestone cadence) | clean |
| `PrecipExtremeEvent` kind=`daily_record` | self-seeded `previous_record_mm`, **no archive_span**, often 0.0 | **Record → downgrade** | **B1/B2 (the incident): baseline fails MIN → ThresholdExceedance/Magnitude** |

### ThresholdExceedance (warrant: named Threshold + provenance)
| Event | Maps to | Break? |
|---|---|---|
| `CoralBleachingEvent` (DHW tiers) | ThresholdExceedance | clean |
| `PM25HazardEvent` / `DustEvent` (tiers) | ThresholdExceedance | clean |
| `WetBulbEvent` (33/35°C) | ThresholdExceedance | clean |
| `ExtremeWaveEvent` (location thresholds) | ThresholdExceedance | clean |
| `AbsoluteExtremeEvent` (latitude band) | ThresholdExceedance | clean |
| `StormSurgeEvent` (≥0.5 m vs predicted) | ThresholdExceedance | clean |
| `FloodEvent` (NWPS flood stage) | ThresholdExceedance | clean |
| `RapidIntensificationEvent` (≥30 kt/24h) | ThresholdExceedance (+transition) | clean |
| `TierCrossingEvent` (Saffir-Simpson) | ThresholdExceedance (+transition) | clean |
| `DroughtUpdate` (D3+D4 ≥10%) | ThresholdExceedance | clean |
| `RegionalSSTAnomalyEvent` (tier on an anomaly) | ThresholdExceedance **or** Anomaly | **B5: hybrid — deliberate mapping needed (anomaly metric, threshold presentation)** |
| `PrecipExtremeEvent` kind=`multi_day_accumulation` | **mislabeled Record today** | **B1 (the incident): correctly ThresholdExceedance (150/300 mm bar)** |

### Anomaly (warrant: Climatology)
| Event | Maps to | Break? |
|---|---|---|
| `OscillationExtremeEvent` (σ vs 1991–2020) | Anomaly | clean — climatology already on the event |
| `RegionalAnomalyEvent` (z vs ERA5, 16 cities) | Anomaly; `where`="N sampled cities in {region}" | **B6 today handled by §F denylist → subsumed** |
| `AnomalyEvent` (open_meteo, vs month-mean) | Anomaly | clean |
| `OscillationAlignmentEvent` (NAO+AO both −2σ) | **CompoundClaim** of two Anomalies | **B6: compound — same shape as Phase D related_signals → subsumed** |

### Milestone (warrant: monotonic series, first-ever)
| Event | Maps to | Break? |
|---|---|---|
| `CO2Milestone` (`ppm_crossed`) | Milestone | clean |
| `MethaneMilestone` (`ppb_crossed`) | Milestone | clean |
| `IceMassRecord` kind=`cumulative` (−1000 Gt) | Milestone | clean |
| `MarineHeatwaveStreakEvent` kind=`milestone` | Milestone (streak-length) | clean |

### Categorical (warrant: external authority designation)
| Event | Maps to | Break? |
|---|---|---|
| `SignificantEarthquakeEvent` (USGS) | Categorical (+Magnitude for M) | clean |
| `GlobalDisasterEvent` (GDACS red) | Categorical | clean |
| `CopernicusFloodActivation` | Categorical | clean |
| `BasinRecordEvent` (cyclones) | **Categorical, NOT Record** | **B3: carries `record_label`/`record_scope` strings, no baseline value/year (verified cyclones.py:119–120) — the bot does not hold the baseline** |
| ENSO transition (`detect_transition` dict) | Categorical + transition | clean (not a formal dataclass today) |

### Magnitude (warrant: observation only; no comparative language)
| Event | Maps to | Break? |
|---|---|---|
| `FireEvent` (FRP ≥250 MW) | Magnitude (notability floor) | clean |
| `PrecipExtremeEvent` kind=`country_precip_event` | Magnitude (record fields all None) | clean |
| `LandfallEvent` (cyclones) | Magnitude / Categorical | clean |

**Headline breaks (7):** **B1** precip `multi_day_accumulation` threshold mislabeled
as a record; **B2** precip `daily_record` self-seeded/0.0 baseline cannot warrant a
Record; **B3** cyclone `BasinRecordEvent` is Categorical, not Record; **B4**
calendar-date `RecordEvent` lacks `years_of_data`; **B5** `RegionalSSTAnomalyEvent`
hybrid needs a deliberate mapping; **B6** `regional_anomaly` §F gate +
`OscillationAlignmentEvent` + Phase D `related_signals` all subsumed by
CompoundClaim/Anomaly; **B7** curated feeds (quake/GDACS/Copernicus) have no baseline
by nature — Categorical is essential or they'd be forced into a false comparative.

**Coverage result:** all 32 events map under 6 types; `PrecipExtremeEvent` alone spans
three (Record-but-fails / ThresholdExceedance / Magnitude) distinguished today only by
a `kind` string and nullable fields — the systemic shape in microcosm.

## 5. Migration path

### 5a. `StoryBundle` gains an additive, dark-launched `claim` (not a cutover)
The exact pattern Phase D used for `related_signals` ([types.py:58](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/types.py): default-empty,
omit-from-`to_dict`-when-absent, byte-identical when off). Add
`claim: Claim | None = None`; serialize it into the user prompt only when present.
Unmigrated sources keep working unchanged. **No flag-day.**

### 5b. The builder is the claim constructor (source→writer boundary)
Claims are constructed in `src/two_bot/intern/` builders, which already translate a
typed Event → `StoryBundle`. Detectors stay unchanged in phase 1 — the builder
un-tangles the overloaded fields (e.g. `previous_record_year is None` ⇒ not a Record).
Precip's fix lives entirely here. (A later phase may push typed claims up into
detectors; out of scope now.)

**One downgrade factory, not 30 (cross-review point #3).** Each builder declares the
*candidate* warrants it can supply (a baseline?, a threshold?, a climatology?, a
monotonic series?) and calls a single `claim_from_warrants(observation, *, baseline=…,
threshold=…, climatology=…, series=…)` factory that constructs the strongest claim
whose reference is valid, walking the §2b ladder and catching `WarrantError` internally.
The per-`(source, kind)` mapping (which warrants a given event can supply) stays in the
builder — that is irreducibly source-specific — but the *ladder logic* lives in one
place so ~30 builders cannot each drift their own downgrade rules.

### 5c. The evidence contract evolves from completeness → warrant
`audit_story_bundle` ([evidence_contract.py:65](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/evidence_contract.py)) keeps its completeness checks for
unmigrated bundles. When `bundle.claim` is present, it additionally asserts the
claim's warrant is intact (it is, by construction — so this is a cheap defense-in-depth
*consequence*, not the primary mechanism) and that the bundle's legacy
`current_facts`/`historical_context` were *derived from* the claim, not hand-stuffed.
The contract never re-validates plausibility by racing — the type already did.

### 5d. The writer consumes a `Claim`
Today the writer gets raw `bundle_json` and the prompt is "the editorial bar," the
code gate "the safety net" ([writer_prompt.py:268](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/prompts/writer_prompt.py)). With a claim, the writer sees the
claim's projection (§5f) and the prompt gains per-type **licensed-language** rules
driven by `claim.licenses()`: a Magnitude says "state the value; do NOT use
record/threshold/normal/first-ever language"; a Record provides the baseline and
licenses "broke the previous record of {value} set in {year}." The writer has nothing
false to cite because `claim.to_writer_projection()` never exposes a threshold as a
record.

**`claim.licenses()` drives two gates from one source (cross-review point #2).** The
writer is a non-deterministic LLM; even handed a Magnitude it *can* emit "record"
language. So the same license set feeds **both** the prompt (the editorial bar) **and**
a deterministic post-generation check that rejects a draft whose comparative language
exceeds the claim's licensed set. The honesty gate does not disappear — it gets thinner
and *type-driven* instead of `signal_kind`-special-cased. This is one mechanism (the
license set) with two uses, and it fits the existing posture where deterministic
honesty is the safety net and the prompt is the bar (writer_prompt.py:106, 271).

### 5e. Absorbing Phase D's honesty gate so it's built once
`related_signals` (`RelatedSignal`, [types.py:9](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/types.py)) become the `related` components of a
`CompoundClaim`, each a fully-warranted `Claim`. The "no causation" rule is enforced
structurally (no relation field exists), making `_cross_signal_violation`'s denylist a
backstop. Phase D's `multisignal.attach_related_signals` keeps selecting/ranking the
same signals; it just attaches typed claims. Likewise §F `regional_anomaly` folds into
the Anomaly type (5b). **One honesty mechanism, not three.**

### 5f. Writer projection vs verifier evidence (THE load-bearing fix — both reviewers, P0)

Both the codex outside-review and the eng-review independently converged on the same
hole in the first draft of this design: **adding a typed `claim` does not by itself
make the falsehood unrepresentable, because the writer sees more than the claim.**

The writer is handed the *entire* serialized bundle ([writer_prompt.py:258-260](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/prompts/writer_prompt.py): `{bundle_json}`),
and `StoryBundle.to_dict` ([types.py:60-77](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/types.py)) serializes **three** writer-visible surfaces
that today are populated straight from the raw event:

- `current_facts` — hand-built with `{"label": "previous_record_mm", "value": 300.0}` ([precipitation.py:27](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern/precipitation.py))
- `historical_context` — also carries `previous_record_mm` ([precipitation.py:57](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern/precipitation.py))
- `raw_signal_dump` — `asdict(event)`, the **whole event verbatim** including the
  threshold ([precipitation.py:61](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern/precipitation.py)). Codex counted **62** `raw_signal_dump=asdict(...)` callsites
  across the builders — this leak is systemic, every source.

So a typed claim could sit *beside* `raw_signal_dump.previous_record_mm = 300.0` and the
writer would still read and cite the threshold. **The false-record affordance survives
the typing unless the writer-visible surface is the claim and nothing but the claim.**

**The fix — separate the two channels the bundle conflates:**

1. **Writer projection.** When `bundle.claim` is present, the writer sees **only**
   `claim.to_writer_projection()` — the licensed facts of the typed claim, with a
   threshold labeled a *threshold*, never `previous_record_mm`. `current_facts` and
   `historical_context` become **projections of the claim** (single source of truth),
   not independent copies of the event; `raw_signal_dump` is **excluded from the
   writer's view** when a claim is present.
2. **Verifier / memory evidence.** `raw_signal_dump` is NOT only the writer's — it is
   also consumed by the **fact-checker** (writer_prompt.py:57 documents it as "the
   original event dict, used by the fact-checker") and by **memory**
   ([memory.py:118](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/memory.py): `bundle.raw_signal_dump.get("country")`). Those consumers legitimately
   need the raw event. So raw evidence stays available to fact-check and memory via a
   **non-writer channel** (a field the writer prompt does not serialize), rather than
   being deleted.

This is the difference between "we typed the claim" and "the writer cannot see a
falsehood." It is the spine of the whole design; the implementation plan sequences it
**first**, before any per-source migration. The deterministic post-generation check
(§5d, driven by `claim.licenses()`) is the backstop for the writer's stochasticity —
the existing pipeline already treats deterministic honesty as the safety net and the
prompt as the editorial bar (writer_prompt.py:106, 271), so this fits the grain of the
code.

```
            BEFORE (leaks)                         AFTER (5f)
   ┌───────────────────────────┐        ┌──────────────────────────────┐
   │ StoryBundle.to_dict()     │        │ claim.to_writer_projection() │──► WRITER
   │  ├─ current_facts ────────┼─►W     │  (licensed facts only)       │
   │  ├─ historical_context ───┼─►W     ├──────────────────────────────┤
   │  └─ raw_signal_dump ──────┼─►W     │ raw_signal_dump (verbatim) ──┼──► FACT-CHECK
   │     (asdict(event), incl. │  ▲     │                              │──► MEMORY
   │      previous_record_mm)  │  │      │   (non-writer channel)       │     (NOT writer)
   └───────────────────────────┘  │     └──────────────────────────────┘
        W = reaches the writer ────┘
```

### 5g. Test strategy — the model is born tested (cross-review point #4)

Both reviews flagged that "byte-identical unmigrated bundles" is necessary but not
sufficient coverage. The implementation plan must include, as first-class gates:

- **Incident regression tests (CRITICAL — iron rule).** The three real 2026-06-16
  drafts become fixtures: (a) Barrow 427.5 mm vs the 300 mm threshold, (b) Amsterdam
  vs 300, (c) Barrow 0.0-baseline daily "record." Each asserts that the **writer
  projection** (`claim.to_writer_projection()`, §5f) for that event contains **no**
  false-record framing — no `previous_record_mm` key, no baseline the warrant doesn't
  support — and that the constructed claim is ThresholdExceedance / Magnitude, never
  Record. These prove the falsehood is now unrepresentable on the exact inputs that
  produced it.
- **Per-claim-type constructor invariants.** For each of the 6 types, a test that
  `WarrantError` is raised when the reference is absent/insufficient: `Record` with
  `established_year=None`; `Record` with `archive_span_years < MIN`; `Baseline` at a
  0.0 self-seed; `Milestone` without a first-crossing proof; `Anomaly` without a
  climatology. The illegal state must be un-constructable, and the test proves it.
- **Downgrade-ladder tests.** `claim_from_warrants` returns the strongest valid claim:
  Record→ThresholdExceedance→Magnitude, and Milestone→Magnitude (NOT
  ThresholdExceedance — §2b), one test per rung.
- **Byte-identity golden (regression).** An OFF / unmigrated bundle serializes
  byte-identically to today's user prompt (mirrors the existing `related_signals`
  byte-identity test the additive pattern is modeled on). Proves the dark-launch is
  truly inert when off.
- **Verifier-channel tests.** With a claim present, the fact-checker and `memory`
  still receive the raw event evidence (§5f non-writer channel) — assert their inputs
  are unchanged so the projection split does not regress fact-check or memory.
- **Per-(source, kind) mapping tests.** Every event `kind` across the migrated
  sources maps to the expected claim type (or downgrades correctly). Start with
  precip's three kinds; extend per source as each migrates.

LLM-touching surfaces (writer prompt licensed-language rules, the deterministic
post-gen check) need an **eval** case, not just unit tests: a Magnitude-claim prompt
must not yield record language. Flag the writer prompt change for the repo's eval
suite per its `Prompt/LLM changes` convention.

## 6. Minimum archive-depth policy (the one tunable to flag for review)

A `Record` requires `Baseline.archive_span_years ≥ MIN_RECORD_ARCHIVE_YEARS`. Default
proposal: **≥ 10 years**, with per-source override owned by a single
`warrant_policy` module (so the editorial bar lives in one place, like thresholds do).
Rationale: temp (30–100 yr), snow (`years_of_archive`), SST (~42 yr, since 1982), sea
ice (since 1978), ozone (since 1979) all clear 10 comfortably; precip's self-seeded
days fail it. The architecture is invariant to the exact number — `Baseline` carries
`archive_span_years` and the constructor enforces a minimum regardless of value — so
this is **tunable policy, not a structural fork.**

**Framing correction (codex outside-review):** ≥10 yr is a **minimum-admissibility
floor**, not a "record-strength" claim. It is the bar below which a Record is *not
representable at all* (it catches the precip bug class: days-deep self-seeds, 0.0
baselines). It is NOT a statement that a 10-year record is editorially strong — that is
a separate, softer judgment the writer/critic already make. Per-source overrides are
**expected**, not exceptional (a 1978-onward sea-ice series and a 3-year regional probe
should not share one threshold). `warrant_policy` owns both the floor and the overrides.
Flagged for Andrew to set the bar; the reviews both endorse ≥10 as a defensible
dark-launch default.

## 7. Non-goals (YAGNI)

- No new climatology service/dependency — anomaly sources already carry their
  normal+dispersion; sources without one simply cannot make an Anomaly claim.
- No detector rewrite in phase 1 — construction lives at the builder boundary.
- No clean cutover — additive `claim` field, per-source migration.
- No new types beyond the 6 — streak/transition/evidence_grade are qualifiers, not
  types (they modify a claim, they don't define a new reference).
- No detector-side claim emission yet (phase-1 builds at the builder; pushing claims
  up into detectors is a later, separate phase).
- Does not change source fetching, scheduling, or the dashboard. Fact-check and memory
  keep their current logic — they retain raw-event access through §5f's non-writer
  channel; the projection split preserves those consumers, it does not rewrite them.

## 8. Decisions resolved (not forks) and why

| Decision | Choice | Resolved by |
|---|---|---|
| Taxonomy size | 6 types (added Milestone, Categorical) | brief's "pressure-test it" + §4 mapping forces it |
| Construction site | builder (`intern/`), phase 1 | brief: "source→writer boundary" |
| Compat vs cutover | additive dark-launched `claim` | repo precedent (Phase D `related_signals`) |
| Warrant absent | downgrade to strongest true claim | brief's Magnitude floor + throughput context |
| Climatology source | reuse what anomaly sources already carry | §4; avoids a heavy dependency |
| Scope of honesty-gate subsumption | Phase D **and** §F | §2c finding |
| **Writer surface** | writer sees `claim.to_writer_projection()` only; raw evidence to fact-check/memory via non-writer channel | **both reviews, P0 (§5f)** |
| **Milestone downgrade** | Milestone → **Magnitude** (not ThresholdExceedance) | codex review (§2b) — avoids implying recurrence |
| **Downgrade ladder** | one `claim_from_warrants` factory, not per-builder | both reviews (§5b) |
| **Honesty enforcement** | `claim.licenses()` drives prompt **and** deterministic post-gen check | both reviews (§5d) |

**No architectural fork requires Andrew's input.** The two cross-reviews (codex
read-only + plan-eng-review) ran and returned **REVISE**; every must-fix was a clear
hardening with one right answer, now folded in above. The single remaining editorial
tunable (min archive depth, §6) has a default both reviews endorse and is flagged for
Andrew to set.

## 9. Question status after the cross-reviews

**Resolved by the reviews (folded into the design above):**
- *Honesty backstop lifecycle* — keep `_cross_signal_violation` / `_forbidden_claim_violation`
  as thin backstops during migration, delete once all sources are typed. (§5d/§5e)
- *Phasing* — precip-first vertical slice, and §5f (the projection split) lands **before**
  any per-source migration. (§5g, §5f)
- *Streak / transition* — confirmed qualifiers, not types; MHW (Record + streak +
  milestone-cadence) is the stress case and it composes cleanly. (§2d)
- *Milestone downgrade* — → Magnitude, not ThresholdExceedance. (§2b)
- *Writer surface* — projection-only; raw evidence via non-writer channel. (§5f)

**Still genuinely open — for Andrew / the implementation plan:**
1. **Min archive-depth bar (§6).** Both reviews endorse ≥10 yr as a dark-launch
   admissibility floor; Andrew sets the final number + per-source overrides. Owner:
   `warrant_policy`.
2. **B5 `RegionalSSTAnomalyEvent`.** Present as ThresholdExceedance (tiers) or Anomaly
   (vs CRW climatology)? Genuinely both; pick the one that licenses the better tweet.
   Low-stakes (either is honest); defaults to ThresholdExceedance unless Andrew prefers
   the anomaly framing.
3. **`Categorical` language discipline.** How tightly to bound "per {authority}" phrasing
   so a curated-feed draft can't drift into an unwarranted comparative. Resolved enough
   to build (the type licenses only the attribution); the exact prompt wording is an
   implementation detail.

---

*Process: Steps 1–5 of the brief are complete — brainstorm, taxonomy mapping, migration
path, this design doc, and BOTH cross-reviews (codex `exec -s read-only` + `/plan-eng-review`),
which returned REVISE and whose must-fixes are folded in. Next is the implementation plan
(Step 6). No code is written this session. Review record: `## GSTACK REVIEW REPORT` below.*

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | REVISE → folded | 5 issues (1 P0/critical, 2 P2, 1 test-critical, 1 P3) — all incorporated |
| Outside Voice | `codex exec -s read-only` | Independent 2nd opinion (different model family) | 2 | REVISE → folded | Confirmed all 5; added Milestone-downgrade + admissibility-floor refinements |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run (design is engineering-scoped; brief owns strategy) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend domain model, no UI) |

**CODEX:** Two passes. Pass 1 (xhigh) read ~20 source files and independently flagged the
writer-visible `raw_signal_dump`/legacy-facts leak as the risk area, validating three of
the design's code claims (additive `related_signals`, completeness-only contract, the two
pipeline gates). Pass 2 (medium, findings inlined) confirmed all five eng-review findings,
elevated the leak to **P0** with the writer-projection / non-writer-evidence split as the
fix, corrected the Milestone downgrade (→ Magnitude), and reframed the ≥10 yr bar as an
admissibility floor. Verdict: **REVISE**.

**CROSS-MODEL:** Strong consensus. Both models independently converged on the same P0 (the
writer sees more than the claim) — the single most load-bearing fix, now §5f. No
cross-model tension: nothing where one reviewer argued against the other. The agreement on
the leak is the high-confidence signal in this review.

**VERDICT:** ENG + OUTSIDE-VOICE reviewed → **REVISE applied**. Design hardened; ready for
the implementation plan (Step 6). Not auto-merged — deliverable is a reviewed design +
plan, per the brief.

**UNRESOLVED DECISIONS:**
- Min archive-depth bar (§6) — Andrew sets the number (reviews endorse ≥10 yr default) + per-source overrides
- B5 `RegionalSSTAnomalyEvent` mapping (§9.2) — ThresholdExceedance vs Anomaly framing (defaults to ThresholdExceedance; low-stakes, either is honest)
