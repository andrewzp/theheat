# Claim & Warrant Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** plan only — NO code written in the session that produced this. Execution is a future session, gated on Andrew resolving the two open tunables (below).
**Design doc (source of truth):** [/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-22-claim-warrant-model-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-22-claim-warrant-model-design.md)
**Brief:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-claim-warrant-model.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-claim-warrant-model.md)

**Goal:** Give the bot a typed model of a *claim* and its *warrant* so a false "record" (a threshold or empty baseline cited as a record) is unconstructable at the source→writer boundary, across all source types.

**Architecture:** A claim is the *reference it cannot exist without* (Record↔Baseline, ThresholdExceedance↔Threshold, Anomaly↔Climatology, Milestone↔MonotonicSeries, Categorical↔Authority, Magnitude↔Observation-only). Builders construct the strongest claim whose reference is real via one `claim_from_warrants` factory (downgrade, never kill). The writer sees only the claim's projection; raw event evidence stays on a non-writer channel for fact-check/memory. Additive `claim` field, dark-launched per the Phase-D `related_signals` pattern; precip migrates first.

**Tech Stack:** Python 3.11+, frozen dataclasses, pytest. No new runtime dependencies.

## Global Constraints

- **Python ≥ 3.11**, frozen dataclasses, `from __future__ import annotations`. Match existing `src/data/*` and `src/two_bot/*` style.
- **Additive, dark by default.** When `bundle.claim is None`, every writer-visible byte is identical to today. No flag-day; no behavior change until a source is migrated.
- **Stage only your own files; never `git add -A`** (standing repo rule).
- **No detector rewrites in this plan.** Construction lives at the `src/two_bot/intern/` builder boundary.
- **The two open tunables are inputs, not code:** `MIN_RECORD_ARCHIVE_YEARS` (design §6, default ≥10) and the B5 `RegionalSSTAnomalyEvent` mapping (design §9.2). Phase 0 uses the ≥10 default behind `warrant_policy`; Phase 2 RecordEvent/SST tasks read Andrew's final call.
- **Test runner:** `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest <path> -q` (matches CI's `-m "not voice_replay"`).
- **Tests are first-class** (design §5g): incident regression fixtures, per-type `WarrantError` invariants, byte-identity golden, verifier-channel.

---

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `src/two_bot/claims.py` (create) | The domain: `Observation`, `Baseline`, `Threshold`, `Climatology`, `MonotonicSeries`, `WarrantError`, the 6 `Claim` types + `CompoundClaim`, each with `.observation`, `.licenses()`, `.to_writer_projection()` | 0 |
| `src/two_bot/warrant_policy.py` (create) | `MIN_RECORD_ARCHIVE_YEARS` + per-source overrides + `record_admissible(...)` | 0 |
| `src/two_bot/claim_factory.py` (create) | `claim_from_warrants(observation, intent, *, baseline=…, threshold=…, climatology=…, series=…, authority=…)` — the one downgrade ladder | 0 |
| `src/two_bot/types.py` (modify) | Add `claim: "Claim | None" = None` to `StoryBundle`; add `to_writer_dict()` | 0 |
| `src/two_bot/writer.py` (modify `_bundle_json`, :82-83) | Route the writer through `to_writer_dict()` | 0 |
| `src/two_bot/licensing.py` (create) | `comparative_language_violation(tweet, claim)` — deterministic post-gen check from `claim.licenses()` | 0 |
| `src/two_bot/pipeline.py` (modify) | Wire the license check as a thin gate alongside the existing two | 0 |
| `src/two_bot/intern/precipitation.py` (modify) | `build_precipitation_bundle` constructs a claim via the factory | 1 |
| `tests/test_claims.py`, `tests/test_claim_factory.py`, `tests/test_warrant_policy.py`, `tests/test_claim_projection.py`, `tests/test_precip_claim_regression.py` (create) | Coverage per §5g | 0–1 |

---

## Phase 0 — The claim model spine

The novel, load-bearing work. Build it fully before any source migrates. Order: domain types → policy → factory → bundle projection → writer routing → license gate.

### Task 0.1: Claim domain types + warrant invariants

**Files:**
- Create: `src/two_bot/claims.py`
- Test: `tests/test_claims.py`

**Interfaces:**
- Produces: `WarrantError(ValueError)`; frozen dataclasses `Observation(value: float, unit: str, where: str, when: str, evidence_grade: str = "observed")`, `Baseline(value: float, established_year: int, archive_span_years: int)`, `Threshold(value: float, name: str, provenance: str)`, `Climatology(normal: float, dispersion: float, reference_period: str)`, `MonotonicSeries(series_id: str, first_crossing: bool)`. Claim types: `Record(observation, baseline)`, `ThresholdExceedance(observation, threshold)`, `Anomaly(observation, climatology)`, `Milestone(observation, series)`, `Categorical(observation, authority_body: str, designation: str)`, `Magnitude(observation)`, `CompoundClaim(primary, related: tuple)`. Each claim exposes `.observation`, `.licenses() -> frozenset[str]`, `.to_writer_projection() -> dict`.
- Consumes: nothing (leaf module).

- [ ] **Step 1: Write the failing tests** (`tests/test_claims.py`)

```python
import pytest
from src.two_bot.claims import (
    Observation, Baseline, Record, ThresholdExceedance, Anomaly, Milestone,
    Magnitude, Categorical, Threshold, Climatology, MonotonicSeries, WarrantError,
)

OBS = Observation(value=427.5, unit="mm", where="Barrow, US", when="2026-06-16")

def test_record_requires_dated_baseline():
    with pytest.raises(WarrantError):
        Record(OBS, Baseline(value=300.0, established_year=None, archive_span_years=40))  # type: ignore[arg-type]

def test_magnitude_licenses_nothing_comparative():
    assert Magnitude(OBS).licenses() == frozenset({"magnitude"})

def test_record_licenses_record_language_and_projects_baseline():
    rec = Record(OBS, Baseline(value=300.0, established_year=1999, archive_span_years=40))
    assert "record" in rec.licenses()
    proj = rec.to_writer_projection()
    assert proj["baseline"]["value"] == 300.0 and proj["baseline"]["established_year"] == 1999
    assert "previous_record_mm" not in proj  # never the leaky legacy label

def test_threshold_projection_labels_a_threshold_not_a_record():
    te = ThresholdExceedance(OBS, Threshold(value=300.0, name="7-day heavy-rain", provenance="GPM detector"))
    proj = te.to_writer_projection()
    assert proj["threshold"]["name"] == "7-day heavy-rain"
    assert "record" not in te.licenses() and "previous_record_mm" not in proj
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claims.py -q`
Expected: FAIL (ImportError: cannot import name 'Observation').

- [ ] **Step 3: Implement `src/two_bot/claims.py`**

```python
"""Typed claims and their warrants. A claim is the reference it cannot exist
without; the type IS the warrant. See docs/plans/2026-06-22-claim-warrant-model-design.md."""
from __future__ import annotations
from dataclasses import dataclass


class WarrantError(ValueError):
    """A claim was constructed without the reference its type requires."""


@dataclass(frozen=True)
class Observation:
    value: float
    unit: str
    where: str
    when: str
    evidence_grade: str = "observed"  # observed | model_estimated | model_fallback


@dataclass(frozen=True)
class Baseline:
    value: float
    established_year: int
    archive_span_years: int

    def __post_init__(self) -> None:
        if self.established_year is None:
            raise WarrantError("Baseline requires a dated prior extreme (established_year)")


@dataclass(frozen=True)
class Threshold:
    value: float
    name: str
    provenance: str


@dataclass(frozen=True)
class Climatology:
    normal: float
    dispersion: float
    reference_period: str


@dataclass(frozen=True)
class MonotonicSeries:
    series_id: str
    first_crossing: bool


def _obs_projection(o: Observation) -> dict:
    return {"value": o.value, "unit": o.unit, "where": o.where, "when": o.when,
            "evidence_grade": o.evidence_grade}


@dataclass(frozen=True)
class Record:
    observation: Observation
    baseline: Baseline

    def licenses(self) -> frozenset[str]:
        return frozenset({"magnitude", "record"})

    def to_writer_projection(self) -> dict:
        return {"claim_type": "record", "observation": _obs_projection(self.observation),
                "baseline": {"value": self.baseline.value,
                             "established_year": self.baseline.established_year,
                             "archive_span_years": self.baseline.archive_span_years}}


@dataclass(frozen=True)
class ThresholdExceedance:
    observation: Observation
    threshold: Threshold

    def licenses(self) -> frozenset[str]:
        return frozenset({"magnitude", "threshold"})

    def to_writer_projection(self) -> dict:
        return {"claim_type": "threshold_exceedance", "observation": _obs_projection(self.observation),
                "threshold": {"value": self.threshold.value, "name": self.threshold.name,
                              "provenance": self.threshold.provenance}}


@dataclass(frozen=True)
class Anomaly:
    observation: Observation
    climatology: Climatology

    def licenses(self) -> frozenset[str]:
        return frozenset({"magnitude", "anomaly"})

    def to_writer_projection(self) -> dict:
        return {"claim_type": "anomaly", "observation": _obs_projection(self.observation),
                "climatology": {"normal": self.climatology.normal, "dispersion": self.climatology.dispersion,
                                "reference_period": self.climatology.reference_period}}


@dataclass(frozen=True)
class Milestone:
    observation: Observation
    series: MonotonicSeries

    def __post_init__(self) -> None:
        if not self.series.first_crossing:
            raise WarrantError("Milestone requires a first-ever crossing of its monotonic series")

    def licenses(self) -> frozenset[str]:
        return frozenset({"magnitude", "milestone"})

    def to_writer_projection(self) -> dict:
        return {"claim_type": "milestone", "observation": _obs_projection(self.observation),
                "series_id": self.series.series_id}


@dataclass(frozen=True)
class Categorical:
    observation: Observation
    authority_body: str
    designation: str

    def licenses(self) -> frozenset[str]:
        return frozenset({"magnitude", "authority"})

    def to_writer_projection(self) -> dict:
        return {"claim_type": "categorical", "observation": _obs_projection(self.observation),
                "authority_body": self.authority_body, "designation": self.designation}


@dataclass(frozen=True)
class Magnitude:
    observation: Observation

    def licenses(self) -> frozenset[str]:
        return frozenset({"magnitude"})

    def to_writer_projection(self) -> dict:
        return {"claim_type": "magnitude", "observation": _obs_projection(self.observation)}


@dataclass(frozen=True)
class CompoundClaim:
    primary: object          # a Claim
    related: tuple           # tuple of Claim — enumeration only; NO relation field exists

    def licenses(self) -> frozenset[str]:
        return self.primary.licenses()  # the relation is unwriteable: there is no slot for it

    def to_writer_projection(self) -> dict:
        return {"claim_type": "compound",
                "primary": self.primary.to_writer_projection(),
                "related": [c.to_writer_projection() for c in self.related]}
```

- [ ] **Step 4: Run to verify pass**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claims.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/claims.py tests/test_claims.py
git commit -m "feat(claims): typed claim/warrant domain — illegal states unconstructable"
```

### Task 0.2: Warrant policy (minimum-admissibility floor)

**Files:**
- Create: `src/two_bot/warrant_policy.py`
- Test: `tests/test_warrant_policy.py`

**Interfaces:**
- Produces: `MIN_RECORD_ARCHIVE_YEARS: int` (default 10 — Andrew's tunable, design §6), `SOURCE_ARCHIVE_OVERRIDES: dict[str, int]`, `record_admissible(archive_span_years: int, *, source: str | None = None) -> bool`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test** (`tests/test_warrant_policy.py`)

```python
from src.two_bot.warrant_policy import record_admissible, MIN_RECORD_ARCHIVE_YEARS

def test_self_seeded_days_deep_baseline_is_inadmissible():
    assert record_admissible(0, source="gpm_precip") is False        # precip 0.0/days-deep
    assert record_admissible(MIN_RECORD_ARCHIVE_YEARS - 1) is False

def test_deep_archive_is_admissible():
    assert record_admissible(40, source="open_meteo") is True        # temp archive
```

- [ ] **Step 2: Run to verify it fails**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_warrant_policy.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `src/two_bot/warrant_policy.py`**

```python
"""Editorial admissibility for warrants. The minimum below which a Record is
not REPRESENTABLE (not a record-strength judgment). Per-source overrides expected.
Design §6. MIN_RECORD_ARCHIVE_YEARS is Andrew's tunable."""
from __future__ import annotations

MIN_RECORD_ARCHIVE_YEARS: int = 10  # TODO(Andrew): confirm the floor (design §6 open tunable)

# Per-source overrides. A 1978-onward sea-ice series and a 3-year probe should
# not share one bar. Keys are source identifiers used by the builders.
SOURCE_ARCHIVE_OVERRIDES: dict[str, int] = {}


def record_admissible(archive_span_years: int, *, source: str | None = None) -> bool:
    floor = SOURCE_ARCHIVE_OVERRIDES.get(source or "", MIN_RECORD_ARCHIVE_YEARS)
    return isinstance(archive_span_years, int) and archive_span_years >= floor
```

- [ ] **Step 4: Run to verify pass**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_warrant_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/warrant_policy.py tests/test_warrant_policy.py
git commit -m "feat(warrant): minimum-admissibility floor for Record baselines"
```

### Task 0.3: The one downgrade factory

**Files:**
- Create: `src/two_bot/claim_factory.py`
- Test: `tests/test_claim_factory.py`

**Interfaces:**
- Consumes: `claims.*`, `warrant_policy.record_admissible`.
- Produces: `claim_from_warrants(observation, intent: str, *, source=None, baseline=None, threshold=None, climatology=None, series=None, authority=None) -> Claim`. `intent ∈ {"record","threshold","anomaly","milestone","categorical","magnitude"}`. Walks the design §2b ladder for that intent and returns the strongest VALID claim.

- [ ] **Step 1: Write the failing tests** (`tests/test_claim_factory.py`)

```python
from src.two_bot.claims import Observation, Baseline, Threshold, MonotonicSeries, Record, ThresholdExceedance, Milestone, Magnitude
from src.two_bot.claim_factory import claim_from_warrants

OBS = Observation(427.5, "mm", "Barrow, US", "2026-06-16")

def test_record_intent_downgrades_to_threshold_when_baseline_inadmissible():
    # precip multi_day_accumulation: baseline absent, threshold present
    c = claim_from_warrants(OBS, "record", source="gpm_precip",
                            threshold=Threshold(300.0, "7-day heavy-rain", "GPM detector"))
    assert isinstance(c, ThresholdExceedance)

def test_record_intent_downgrades_to_magnitude_when_baseline_shallow_and_no_threshold():
    c = claim_from_warrants(OBS, "record", source="gpm_precip",
                            baseline=Baseline(0.0, 2026, archive_span_years=0))  # 0.0 self-seed
    assert isinstance(c, Magnitude)

def test_record_intent_builds_record_when_admissible():
    c = claim_from_warrants(OBS, "record", source="open_meteo",
                            baseline=Baseline(300.0, 1999, archive_span_years=40))
    assert isinstance(c, Record)

def test_milestone_downgrades_to_magnitude_not_threshold():
    # design §2b correction: a milestone must NOT imply a recurring bar
    c = claim_from_warrants(OBS, "milestone",
                            series=MonotonicSeries("co2_ppm", first_crossing=False),
                            threshold=Threshold(420.0, "ppm", "Mauna Loa"))
    assert isinstance(c, Magnitude)
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claim_factory.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `src/two_bot/claim_factory.py`**

```python
"""The single downgrade ladder (design §2b/§5b). Builders declare intent +
supply candidate warrants; this returns the strongest VALID claim. No builder
re-implements the ladder."""
from __future__ import annotations

from src.two_bot.claims import (
    Observation, Baseline, Threshold, Climatology, MonotonicSeries,
    Record, ThresholdExceedance, Anomaly, Milestone, Categorical, Magnitude, WarrantError,
)
from src.two_bot.warrant_policy import record_admissible


def claim_from_warrants(observation: Observation, intent: str, *, source: str | None = None,
                        baseline: Baseline | None = None, threshold: Threshold | None = None,
                        climatology: Climatology | None = None, series: MonotonicSeries | None = None,
                        authority: tuple[str, str] | None = None):
    if intent == "record":
        if baseline is not None and record_admissible(baseline.archive_span_years, source=source):
            try:
                return Record(observation, baseline)
            except WarrantError:
                pass
        if threshold is not None:
            return ThresholdExceedance(observation, threshold)
        return Magnitude(observation)

    if intent == "milestone":
        if series is not None:
            try:
                return Milestone(observation, series)
            except WarrantError:
                pass
        # §2b: do NOT fall to ThresholdExceedance unless a named recurring threshold is explicit
        return Magnitude(observation)

    if intent == "anomaly":
        return Anomaly(observation, climatology) if climatology is not None else Magnitude(observation)

    if intent == "threshold":
        return ThresholdExceedance(observation, threshold) if threshold is not None else Magnitude(observation)

    if intent == "categorical":
        if authority is not None:
            return Categorical(observation, authority[0], authority[1])
        return Magnitude(observation)

    return Magnitude(observation)
```

- [ ] **Step 4: Run to verify pass**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claim_factory.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/claim_factory.py tests/test_claim_factory.py
git commit -m "feat(claims): single intent-aware downgrade factory (never kill)"
```

### Task 0.4: `StoryBundle.claim` + writer projection

**Files:**
- Modify: `src/two_bot/types.py` (StoryBundle, around :36-77)
- Test: `tests/test_claim_projection.py`

**Interfaces:**
- Consumes: `claims.Claim` (the union).
- Produces: `StoryBundle.claim: Claim | None = None`; `StoryBundle.to_writer_dict() -> dict` — when `claim is None`, returns exactly `to_dict()` (byte-identical); when present, returns the claim projection envelope and OMITS `raw_signal_dump`. `to_dict()` is unchanged (full, with `raw_signal_dump`).

- [ ] **Step 1: Write the failing tests** (`tests/test_claim_projection.py`)

```python
from src.two_bot.types import StoryBundle
from src.two_bot.claims import Observation, ThresholdExceedance, Threshold

def _precip_bundle(claim=None):
    return StoryBundle(
        signal_kind="precipitation_extreme", where="Barrow, US", when="2026-06-16",
        event_id="x", headline_metric={"label": "rainfall_mm", "value": 427.5, "unit": "mm"},
        current_facts=[{"label": "previous_record_mm", "value": 300.0}],
        raw_signal_dump={"previous_record_mm": 300.0, "kind": "multi_day_accumulation"},
        claim=claim,
    )

def test_no_claim_is_byte_identical_to_to_dict():
    b = _precip_bundle()
    assert b.to_writer_dict() == b.to_dict()      # dark-launch inert when off

def test_claim_projection_omits_raw_signal_dump_and_threshold_label():
    claim = ThresholdExceedance(Observation(427.5, "mm", "Barrow, US", "2026-06-16"),
                                Threshold(300.0, "7-day heavy-rain", "GPM detector"))
    b = _precip_bundle(claim=claim)
    wd = b.to_writer_dict()
    assert "raw_signal_dump" not in wd                       # the leak is closed
    assert "previous_record_mm" not in repr(wd)              # no record affordance
    assert wd["claim"]["threshold"]["name"] == "7-day heavy-rain"

def test_factcheck_still_sees_raw_via_to_dict():
    b = _precip_bundle(claim=ThresholdExceedance(Observation(1, "mm", "x", "y"), Threshold(1, "t", "p")))
    assert b.to_dict()["raw_signal_dump"]["previous_record_mm"] == 300.0  # verifier channel intact
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claim_projection.py -q`
Expected: FAIL (StoryBundle has no `claim` / no `to_writer_dict`).

- [ ] **Step 3: Implement** — in `src/two_bot/types.py`, add the field after `related_signals` and the method after `to_dict`:

```python
    # Typed claim (design §5). Additive + dark: None => to_writer_dict() == to_dict().
    claim: "object | None" = None  # a src.two_bot.claims Claim; object to avoid import cycle

    def to_writer_dict(self) -> dict:
        """Writer-visible serialization. When a claim is present the writer sees
        ONLY the claim projection (no raw_signal_dump); fact-check/memory keep
        to_dict(). When absent, byte-identical to to_dict() (design §5f)."""
        if self.claim is None:
            return self.to_dict()
        data: dict = {
            "signal_kind": self.signal_kind, "where": self.where, "when": self.when,
            "event_id": self.event_id,
            "claim": self.claim.to_writer_projection(),  # licensed facts only
        }
        if self.country:
            data["country"] = self.country
        if self.related_signals:
            data["related_signals"] = [r.to_dict() for r in self.related_signals]
        return data
```

Note: `headline_metric`/`current_facts`/`historical_context`/`raw_signal_dump` are intentionally absent from the writer projection — the claim carries the headline observation. (If a follow-up finds the writer needs a non-comparative `current_facts` subset, derive it from the claim, never from the event.)

- [ ] **Step 4: Run to verify pass**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claim_projection.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/types.py tests/test_claim_projection.py
git commit -m "feat(types): additive claim field + writer projection (closes raw_signal_dump leak)"
```

### Task 0.5: Route the writer through the projection

**Files:**
- Modify: `src/two_bot/writer.py:82-83` (`_bundle_json`)
- Test: extend `tests/test_claim_projection.py`

**Interfaces:**
- Consumes: `StoryBundle.to_writer_dict()`.
- Produces: writer prompt now built from the projection; fact-check (`fact_check.py:141`) is **unchanged** (still `to_dict()`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_claim_projection.py`)

```python
import json
from src.two_bot.writer import _bundle_json

def test_writer_bundle_json_uses_projection_when_claim_present():
    from src.two_bot.claims import Observation, ThresholdExceedance, Threshold
    b = _precip_bundle(claim=ThresholdExceedance(Observation(427.5, "mm", "Barrow, US", "2026-06-16"),
                                                 Threshold(300.0, "7-day heavy-rain", "GPM detector")))
    payload = json.loads(_bundle_json(b))
    assert "raw_signal_dump" not in payload and "previous_record_mm" not in _bundle_json(b)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claim_projection.py::test_writer_bundle_json_uses_projection_when_claim_present -q`
Expected: FAIL (raw_signal_dump still present — `_bundle_json` uses `to_dict()`).

- [ ] **Step 3: Implement** — change `src/two_bot/writer.py:83`:

```python
def _bundle_json(bundle: StoryBundle) -> str:
    return json.dumps(bundle.to_writer_dict(), sort_keys=True, default=_json_default)
```

- [ ] **Step 4: Run the writer + fact-check + byte-identity tests**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_claim_projection.py tests/test_writer.py tests/test_fact_check.py -q`
Expected: PASS. (Byte-identity test from 0.4 proves OFF behavior unchanged; fact-check tests prove the verifier channel is intact.)

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/writer.py tests/test_claim_projection.py
git commit -m "feat(writer): writer reads claim projection; fact-check keeps raw evidence"
```

### Task 0.6: Deterministic licensed-language gate

**Files:**
- Create: `src/two_bot/licensing.py`
- Modify: `src/two_bot/pipeline.py` (add the gate alongside `_forbidden_claim_violation` / `_cross_signal_violation`)
- Test: `tests/test_licensing.py`

**Interfaces:**
- Consumes: `bundle.claim.licenses()`.
- Produces: `comparative_language_violation(tweet: str, claim) -> str | None` — returns the offending word class when the tweet uses comparative language the claim does not license (e.g. "record"/"previous record" against a Magnitude/ThresholdExceedance claim), else None. Wired as a thin gate that only fires when `bundle.claim is not None`.

- [ ] **Step 1: Write the failing tests** (`tests/test_licensing.py`)

```python
from src.two_bot.claims import Observation, Magnitude, Record, Baseline
from src.two_bot.licensing import comparative_language_violation

OBS = Observation(427.5, "mm", "Barrow, US", "2026-06-16")

def test_magnitude_may_not_say_record():
    assert comparative_language_violation("a record 427 mm fell", Magnitude(OBS)) is not None

def test_record_may_say_record():
    rec = Record(OBS, Baseline(300.0, 1999, 40))
    assert comparative_language_violation("broke the previous record of 300 mm", rec) is None

def test_magnitude_plain_statement_is_clean():
    assert comparative_language_violation("427 mm fell in a week at Barrow", Magnitude(OBS)) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_licensing.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `src/two_bot/licensing.py`**

```python
"""Deterministic post-generation honesty gate driven by claim.licenses().
The writer is stochastic; even handed a Magnitude it can emit 'record'. This
rejects comparative language the claim does not license. Design §5d. The word
sets here are the same family the §F/Phase-D denylists used, but keyed to the
TYPE, not the signal_kind string."""
from __future__ import annotations

# Comparative-language markers, grouped by the license they REQUIRE.
_REQUIRES: dict[str, tuple[str, ...]] = {
    "record": ("record", "previous record", "all-time", "highest ever", "lowest ever",
               "never been", "first time in", "in recorded history"),
    "threshold": ("crossed the", "exceeded the", "past the", "above the .* threshold",
                  "× the", "times the who"),
    "anomaly": ("above normal", "below normal", "sigma", "σ", "standard deviation",
                "vs the .* average", "anomaly"),
    "milestone": ("first time ever", "for the first time", "milestone"),
}


def comparative_language_violation(tweet: str, claim) -> str | None:
    low = tweet.lower().replace("’", "'")
    licensed = claim.licenses()
    for need, markers in _REQUIRES.items():
        if need in licensed:
            continue
        for m in markers:
            if m in low:  # substring; design note: a thin backstop, not paraphrase-complete
                return f"{need}:{m}"
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_licensing.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Wire the gate into the pipeline** — in `src/two_bot/pipeline.py`, after the existing `_cross_signal_violation` check on the generated tweet, add (only fires when a claim is present):

```python
    if getattr(bundle, "claim", None) is not None:
        from src.two_bot.licensing import comparative_language_violation
        _viol = comparative_language_violation(tweet, bundle.claim)
        if _viol:
            # same posture as the existing deterministic gates: kill, don't ship
            return _record_kill("licensing", f"unlicensed comparative language ({_viol})")
```

(Match the surrounding kill-recording idiom; read the section around the existing `_cross_signal_violation` callsite for the exact signature.)

- [ ] **Step 6: Run pipeline tests + commit**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_pipeline.py tests/test_licensing.py -q`
Expected: PASS.

```bash
git add src/two_bot/licensing.py src/two_bot/pipeline.py tests/test_licensing.py
git commit -m "feat(pipeline): deterministic licensed-language gate from claim.licenses()"
```

---

## Phase 1 — Precip vertical slice (proves the model on the incident)

Migrate the one source where the incident surfaced. This is the proof the model closes the exact falsehoods, and the template every other source follows.

### Task 1.1: `build_precipitation_bundle` constructs a claim

**Files:**
- Modify: `src/two_bot/intern/precipitation.py:15-62`
- Test: `tests/test_precip_claim_regression.py`

**Interfaces:**
- Consumes: `claim_from_warrants`, `claims.*`, `PrecipExtremeEvent`.
- Produces: every precip bundle carries `claim`; the writer projection contains no false-record affordance for `multi_day_accumulation` / 0.0-baseline `daily_record`.

Mapping (from design §4): precip `kind` → factory `intent`:
- `multi_day_accumulation` → intent `record` with **no baseline**, threshold = `Threshold(previous_record_mm, "{period_days}-day heavy-rain", "GPM accumulation detector")` ⇒ ThresholdExceedance.
- `daily_record` → intent `record`, baseline = `Baseline(previous_record_mm, previous_record_year, archive_span_years=<computed>)`; the 0.0/days-deep self-seed fails admissibility ⇒ downgrades.
- `country_precip_event` → intent `magnitude` ⇒ Magnitude.

- [ ] **Step 1: Write the failing regression tests** (`tests/test_precip_claim_regression.py`) — the three real incident drafts:

```python
import json
from src.data.gpm_imerg import PrecipExtremeEvent
from src.two_bot.intern.precipitation import build_precipitation_bundle
from src.two_bot.writer import _bundle_json

def _writer_text(event):
    return _bundle_json(build_precipitation_bundle(event))

def test_barrow_multiday_threshold_is_not_a_record():
    # 427.5 mm/7d vs the 300 mm THRESHOLD — the headline incident draft
    ev = PrecipExtremeEvent(kind="multi_day_accumulation", location="Barrow", country="US",
        date="2026-06-16", mm_total=427.5, period_days=7, deviation_from_record_mm=127.5,
        previous_record_mm=300.0, previous_record_year=None, lat=71.0, lon=-156.0,
        city_count=None, sample_cities=[], event_id="e1")
    b = build_precipitation_bundle(ev)
    assert b.claim.licenses() == frozenset({"magnitude", "threshold"})  # NOT record
    payload = _writer_text(ev)
    assert "previous_record_mm" not in payload and "300.0" not in json.dumps(json.loads(payload).get("claim", {}).get("observation", {}))

def test_barrow_zero_baseline_daily_record_downgrades():
    ev = PrecipExtremeEvent(kind="daily_record", location="Barrow", country="US",
        date="2026-06-16", mm_total=12.0, period_days=1, deviation_from_record_mm=12.0,
        previous_record_mm=0.0, previous_record_year=2026, lat=71.0, lon=-156.0,
        city_count=None, sample_cities=[], event_id="e2")
    b = build_precipitation_bundle(ev)
    assert "record" not in b.claim.licenses()  # 0.0 self-seed cannot warrant a Record

def test_country_event_is_magnitude():
    ev = PrecipExtremeEvent(kind="country_precip_event", location="US", country="US",
        date="2026-06-16", mm_total=200.0, period_days=1, deviation_from_record_mm=None,
        previous_record_mm=None, previous_record_year=None, lat=0.0, lon=0.0,
        city_count=10, sample_cities=["a"], event_id="e3")
    assert build_precipitation_bundle(ev).claim.licenses() == frozenset({"magnitude"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_precip_claim_regression.py -q`
Expected: FAIL (bundle has no `claim`).

- [ ] **Step 3: Implement** — in `build_precipitation_bundle`, construct the observation + claim and pass `claim=` to the `StoryBundle(...)`. Add near the top of the function:

```python
    from src.two_bot.claims import Observation, Baseline, Threshold
    from src.two_bot.claim_factory import claim_from_warrants

    obs = Observation(value=round(event.mm_total, 1), unit="mm", where=where, when=event.date,
                      evidence_grade=("model_fallback" if event.source_leg == "open_meteo" else "observed"))
    if event.kind == "multi_day_accumulation":
        claim = claim_from_warrants(obs, "record", source="gpm_precip",
            threshold=Threshold(event.previous_record_mm, f"{event.period_days}-day heavy-rain",
                                "GPM accumulation detector"))
    elif event.kind == "daily_record":
        baseline = (Baseline(event.previous_record_mm, event.previous_record_year, archive_span_years=0)
                    if event.previous_record_year is not None else None)
        claim = claim_from_warrants(obs, "record", source="gpm_precip", baseline=baseline)
    else:  # country_precip_event and any other aggregate
        claim = claim_from_warrants(obs, "magnitude", source="gpm_precip")
```

Then add `claim=claim` to the `return StoryBundle(...)` call. Leave the existing `current_facts`/`historical_context`/`raw_signal_dump` as-is — the projection (Task 0.4) already excludes them from the writer; fact-check/memory still use them.

Note: `archive_span_years=0` is the honest placeholder — precip tracking carries no real archive span today, so daily "records" correctly downgrade. A future task wires a real span if/when precip gets a climatological archive.

- [ ] **Step 4: Run regression + full precip + suite**

Run: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/test_precip_claim_regression.py tests/test_gpm_imerg.py -q`
Then the guard: `PATH=/opt/homebrew/bin:$PATH .venv/bin/python -m pytest tests/ -q -m "not voice_replay" --ignore="tests/test_scheduler 2.py"`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/two_bot/intern/precipitation.py tests/test_precip_claim_regression.py
git commit -m "feat(precip): construct typed claim; the three incident drafts are now unrepresentable"
```

---

## Phase 2+ — Cohort migration (templated; one cohort per PR)

With the spine proven on precip, every other source migrates by the **same three steps** as Task 1.1: (1) map each event `kind` → factory intent + warrants per the design §4 table, (2) write the per-source claim test (and a regression fixture for any source with a known false-claim risk), (3) pass `claim=` into the builder. No new spine code. Run cohorts as separate PRs by claim family so review stays bounded.

| Cohort | Sources (builders) | Intent mapping | Special note |
|---|---|---|---|
| **C1 Records** | open_meteo (RecordEvent/AllTimeRecord/MonthlyRecord/CountryRecord), sea_ice, snow, ozone_hole, ice_mass (monthly), ocean_sst (archive max) | `record` + Baseline | **B4:** `RecordEvent` lacks `years_of_data` — source `archive_span_years` from the detector's archive (design §9 / open_meteo.py:31). Per-source override likely. |
| **C2 Thresholds** | coral_dhw, air_quality (PM2.5/dust), open_meteo wet-bulb/absolute, ocean waves, water_levels, river_gauges, cyclones (RI/tier), drought, copernicus | `threshold` + Threshold | Each threshold needs a real `name`+`provenance`. |
| **C3 Anomalies** | climate_indices (oscillation), reanalysis_anomaly (regional), open_meteo AnomalyEvent | `anomaly` + Climatology | **§F fold-in:** `regional_anomaly` becomes Anomaly with `where`="N sampled cities in {region}"; retire `forbidden_claims` only after this lands. |
| **C4 Milestones** | co2, methane, ice_mass (cumulative), ocean_sst (streak milestone) | `milestone` + MonotonicSeries | Downgrade → Magnitude, never threshold (§2b). |
| **C5 Categorical** | usgs_quakes, gdacs, copernicus (activation), cyclones BasinRecord, enso transition | `categorical` + authority | **B3:** cyclone `BasinRecordEvent` is Categorical, NOT Record. |
| **C6 Compound** | Phase D `related_signals`; climate_indices `OscillationAlignmentEvent` | `CompoundClaim(primary, related=…)` | **Subsumes Phase D:** `attach_related_signals` attaches typed component claims; the no-causation rule is structural (no relation slot). |

### Task 2.x (template, per cohort)
**Files:** Modify the cohort's builder(s) in `src/two_bot/intern/`; create `tests/test_<source>_claim.py`.
- [ ] Map each `kind` → intent + warrants (design §4 row for that event).
- [ ] Write the per-`(source,kind)` claim test; add a regression fixture for any known false-claim shape.
- [ ] Pass `claim=` into the builder via `claim_from_warrants`.
- [ ] Run the source's existing test file + the full guard suite; commit.

### Task 3: Evidence contract evolves to warrant-aware (after ≥1 cohort)
**Files:** Modify `src/two_bot/evidence_contract.py` (`audit_story_bundle`).
- [ ] When `bundle.claim` is present, additionally assert the projection carries no legacy comparative label (`previous_record_mm` etc.) — a cheap defense-in-depth *output* of the model, not the primary mechanism. Keep completeness checks for unmigrated bundles. Add tests.

### Task 4: Retire the per-signal_kind denylists (LAST, after all sources migrate)
**Files:** Modify `src/two_bot/pipeline.py`.
- [ ] Once C3 lands, delete §F `_forbidden_claim_violation`; once C6 lands, delete Phase D `_cross_signal_violation`. The licensing gate (Task 0.6) + the structural compound-claim model replace them. Keep until then. Tests assert no migrated source relies on the deleted denylist.

---

## NOT in scope (deferred, with rationale)

- **Detector-side claim emission** — phase-1 builds at the builder; pushing typed claims up into detectors is a later, separate effort (design §7).
- **A real precip climatological archive** — precip daily "records" correctly downgrade today; wiring a deep archive so precip *can* make honest Records is its own project.
- **Deleting `raw_signal_dump`** — it stays as the verifier/memory channel (design §5f); only the writer stops seeing it.
- **Dashboard / scheduling / source fetch** — untouched.
- **Setting `MIN_RECORD_ARCHIVE_YEARS` and the B5 SST mapping** — Andrew's calls (design §6, §9.2); Phase 0 uses defaults.

## What already exists (reused, not rebuilt)

- **Additive dark-launch pattern** — `related_signals` (types.py:58) is the exact precedent for `claim`; reuse omit-when-empty + byte-identity.
- **`evidence_grade`** — already on the bundle (precipitation.py:38, air_quality `model_estimated`); fed into `Observation.evidence_grade`.
- **Deterministic-gate posture** — the licensing gate matches the existing `_forbidden_claim_violation` / `_cross_signal_violation` kill idiom (pipeline.py); it replaces, not adds.
- **`attach_related_signals`** (multisignal.py) — unchanged selection/ranking; it just attaches typed component claims in C6.

## Failure modes (per new codepath)

| Codepath | Realistic failure | Test? | Error handling | User-visible? |
|---|---|---|---|---|
| `claim_from_warrants` | a builder supplies a malformed warrant | yes (factory tests) | downgrades to Magnitude (never raises out) | no — safe floor |
| `to_writer_dict` | claim present but projection missing a field | yes (projection tests) | projection is total per type | no |
| licensing gate | writer emits record-language on a Magnitude | yes (licensing + incident regression) | deterministic kill | no (draft killed, not shipped) |
| precip mapping | a new precip `kind` appears | add a mapping test | falls to Magnitude (else branch) | no — safe floor |

No failure mode is both untested and silent. The only behavior change when OFF is *none* (byte-identity gate).

## Parallelization

- **Phase 0 is sequential** (0.1→0.6; each builds on the last) — one lane.
- **Phase 2 cohorts C1–C6 are independent** once Phase 0 lands — separate worktree lanes, one PR each (they touch disjoint builders). C3 must precede the §F deletion (Task 4); C6 must precede the Phase-D deletion (Task 4). Run: Phase 0 → {C1, C2, C3, C4, C5, C6 in parallel} → Task 3 → Task 4.
