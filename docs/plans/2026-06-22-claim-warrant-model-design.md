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
| **Milestone** | `MonotonicSeries {first_crossing: True, series_id}` | "first time ever above X" | ThresholdExceedance → Magnitude |
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
constructs the *strongest claim whose reference is real*, walking down the ladder
(Record → ThresholdExceedance → Magnitude; Milestone → ThresholdExceedance →
Magnitude). **Magnitude is the universal floor** — any genuine observation can be
stated as a value in a place at a time with no comparative language. This is
deliberate: the Throughput Initiative (PRs #297–#300) just shipped to end a 19-day
drought, so the model forbids the *lie*, not the *draft*. A kill only happens when
even a Magnitude observation is unsound (e.g., no value), which the completeness
contract already catches.

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
typed Event → `StoryBundle`. The builder reads the event and constructs the strongest
claim whose reference is real (catching `WarrantError` to downgrade). Detectors stay
unchanged in phase 1 — the builder un-tangles the overloaded fields (e.g.
`previous_record_year is None` ⇒ not a Record). Precip's fix lives entirely here.
(A later phase may push typed claims up into detectors; out of scope now.)

### 5c. The evidence contract evolves from completeness → warrant
`audit_story_bundle` ([evidence_contract.py:65](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/evidence_contract.py)) keeps its completeness checks for
unmigrated bundles. When `bundle.claim` is present, it additionally asserts the
claim's warrant is intact (it is, by construction — so this is a cheap defense-in-depth
*consequence*, not the primary mechanism) and that the bundle's legacy
`current_facts`/`historical_context` were *derived from* the claim, not hand-stuffed.
The contract never re-validates plausibility by racing — the type already did.

### 5d. The writer consumes a `Claim`
Today the writer gets raw `bundle_json` and the prompt is "the editorial bar," the
code gate "the safety net" ([writer_prompt.py:268](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/prompts/writer_prompt.py)). With a claim, the bundle
serializes the claim and the prompt gains per-type **licensed-language** rules driven
by `claim.licenses()`: a Magnitude says "state the value; do NOT use
record/threshold/normal/first-ever language"; a Record provides the baseline and
licenses "broke the previous record of {value} set in {year}." The writer has nothing
false to cite because `claim.to_bundle_facts()` never exposes a threshold as a record.

### 5e. Absorbing Phase D's honesty gate so it's built once
`related_signals` (`RelatedSignal`, [types.py:9](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/types.py)) become the `related` components of a
`CompoundClaim`, each a fully-warranted `Claim`. The "no causation" rule is enforced
structurally (no relation field exists), making `_cross_signal_violation`'s denylist a
backstop. Phase D's `multisignal.attach_related_signals` keeps selecting/ranking the
same signals; it just attaches typed claims. Likewise §F `regional_anomaly` folds into
the Anomaly type (5b). **One honesty mechanism, not three.**

## 6. Minimum archive-depth policy (the one tunable to flag for review)

A `Record` requires `Baseline.archive_span_years ≥ MIN_RECORD_ARCHIVE_YEARS`. Default
proposal: **≥ 10 years**, with per-source override owned by a single
`warrant_policy` module (so the editorial bar lives in one place, like thresholds do).
Rationale: temp (30–100 yr), snow (`years_of_archive`), SST (~42 yr, since 1982), sea
ice (since 1978), ozone (since 1979) all clear 10 comfortably; precip's self-seeded
days fail it. The architecture is invariant to the exact number — `Baseline` carries
`archive_span_years` and the constructor enforces a minimum regardless of value — so
this is **tunable policy, not a structural fork.** Flagged explicitly for codex /
plan-eng-review / Andrew to set the bar (10 vs 20 vs 30, and any per-source overrides).

## 7. Non-goals (YAGNI)

- No new climatology service/dependency — anomaly sources already carry their
  normal+dispersion; sources without one simply cannot make an Anomaly claim.
- No detector rewrite in phase 1 — construction lives at the builder boundary.
- No clean cutover — additive `claim` field, per-source migration.
- No new types beyond the 6 — streak/transition/evidence_grade are qualifiers, not
  types (they modify a claim, they don't define a new reference).
- Does not touch source fetching, scheduling, the dashboard, or memory.

## 8. Decisions resolved (not forks) and why

| Decision | Choice | Resolved by |
|---|---|---|
| Taxonomy size | 6 types (added Milestone, Categorical) | brief's "pressure-test it" + §4 mapping forces it |
| Construction site | builder (`intern/`), phase 1 | brief: "source→writer boundary" |
| Compat vs cutover | additive dark-launched `claim` | repo precedent (Phase D `related_signals`) |
| Warrant absent | downgrade to strongest true claim | brief's Magnitude floor + throughput context |
| Climatology source | reuse what anomaly sources already carry | §4; avoids a heavy dependency |
| Scope of honesty-gate subsumption | Phase D **and** §F | §2c finding |

**No architectural fork requires Andrew's input before the cross-reviews.** The
single editorial tunable (min archive depth, §6) has a defensible default and is
flagged for the reviews, which the brief designed as the checkpoints.

## 9. Open questions for the cross-reviews (codex + plan-eng-review)

1. **Min archive-depth bar (§6)** — is ≥10 yr right? Per-source overrides for which
   sources? Who owns `warrant_policy`?
2. **B5 `RegionalSSTAnomalyEvent`** — present as ThresholdExceedance (tiers) or Anomaly
   (vs CRW climatology)? It is genuinely both; which licenses the better tweet?
3. **Single honesty check vs typed backstops** — once claims are typed, do we *delete*
   the `_cross_signal_violation`/`_forbidden_claim_violation` denylists or keep them as
   thin backstops during migration? (Recommend: keep as backstop until all sources
   migrate, then delete.)
4. **`Categorical` language discipline** — how tightly do we bound "per {authority}"
   phrasing so a curated-feed draft can't drift into an unwarranted comparative?
5. **Phasing** — precip-first (proves the model on the incident source) then migrate
   the rest, vs land all types then migrate? (Recommend: precip-first vertical slice.)
6. **Streak/transition as qualifiers vs types** — confirm they don't warrant their own
   type (recommend qualifier; pressure-test against MHW which is Record+streak+milestone).

---

*Process: this doc is Step 4 of the brief. Next: codex `exec -s read-only` outside
review + `/plan-eng-review` (Step 5), revise, then the implementation plan (Step 6).
No code is written this session.*
