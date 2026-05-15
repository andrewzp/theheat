# Lane 15 — Threshold Registry (Centralize Magic Numbers in scoring.py)

**Branch:** `hygiene/threshold-registry`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (NOT in scope → Threshold registry)
**Scope:** Move all ~25 score-gate thresholds out of inline `_build_score(...)` calls and into a centralized registry
**Estimated time:** 2-3 hours CC, single PR
**Parallel-safety:** **Conflicts with Lane 12, 13, 14 (any source-add lane touches `scoring.py`).** Run after all Plans D, E, F land. Parallel-safe with Lane 16 (main.py refactor — different file).

## Why this lane exists

[/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/scoring.py](/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/scoring.py) currently holds ~25 distinct `threshold=N` values inline inside `score_*` functions. Examples:

```python
# inline magic numbers, scattered across 30+ score_* functions
threshold=72,   # score_record_event
threshold=82,   # score_country_record
threshold=64,   # score_fire_event
threshold=74,   # score_anomaly (was 76 before PR #96)
threshold=76,   # score_monthly_record
threshold=78,   # score_marine_heatwave / score_ice_mass_record / score_simultaneous_records
threshold=80,   # score_all_time_record
threshold=82,   # score_synthesis_fire_drought_heat / score_country_record
# ... etc
```

This is calibration friction:
- PR #96 was a one-number tune (anomaly 76→74). Every future tune is the same one-line ceremony with no place to compare values across categories.
- No central place to see "all current category thresholds" at once.
- No A/B testing or rollback safety — every change is a hand-edit to a literal.
- New sources (Plan B+C+D+E+F) each pick a threshold independently; no consistency check across categories.

A registry turns ~25 magic numbers into one configuration table. Calibration becomes data-driven.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/scoring.py](/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/scoring.py) — full file. Every `_build_score(threshold=N, ...)` call is a candidate.
2. [/Users/andrewpuschel/Documents/Claude/theheat/tests/test_editorial_scoring.py](/Users/andrewpuschel/Documents/Claude/theheat/tests/test_editorial_scoring.py) — these tests will catch behavior regressions. Should pass before and after.

## The change

### Step 1 — Build the registry

Create [/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/thresholds.py](/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/thresholds.py):

```python
"""Centralized editorial score-gate thresholds.

One source of truth for every `score_*` function's pass/fail threshold.
Calibration changes happen here, not inline in scoring.py.

Each entry includes:
- category: matches the `category` field on the EditorialScore returned by
  the corresponding score_* function
- threshold: integer 0-100; events scoring below this are suppressed at
  the score_gate stage
- rationale: a one-line note on WHY this value, including any historical
  change (e.g., "anomaly lowered 76→74 in PR #96 — 11-14°C deviations
  are real news, see CHANGELOG 0.6.0.1")
"""

from dataclasses import dataclass

@dataclass(frozen=True)
class ThresholdEntry:
    category: str
    threshold: int
    rationale: str

THRESHOLDS: dict[str, ThresholdEntry] = {
    "record": ThresholdEntry("record", 72, "..."),
    "country_high": ThresholdEntry("country_high", 82, "..."),
    "country_low": ThresholdEntry("country_low", 82, "..."),
    "record_low": ThresholdEntry("record_low", 72, "..."),
    "fire": ThresholdEntry("fire", 64, "..."),
    "fire_footprint": ThresholdEntry("fire_footprint", 72, "..."),
    "co2_milestone": ThresholdEntry("co2_milestone", 58, "..."),
    "severe_weather": ThresholdEntry("severe_weather", 58, "..."),
    "global_disaster": ThresholdEntry("global_disaster", 62, "..."),
    "sea_ice_record": ThresholdEntry("sea_ice_record", 60, "..."),
    "ice_mass_record": ThresholdEntry("ice_mass_record", 78, "..."),
    "drought": ThresholdEntry("drought", 62, "..."),
    "enso": ThresholdEntry("enso", 56, "..."),
    "extreme_wave": ThresholdEntry("extreme_wave", 62, "..."),
    "marine_heatwave": ThresholdEntry("marine_heatwave", 78, "..."),
    "storm_surge": ThresholdEntry("storm_surge", 60, "..."),
    "river_flood": ThresholdEntry("river_flood", 62, "..."),
    "all_time_record": ThresholdEntry("all_time_record", 80, "..."),
    "monthly_record": ThresholdEntry("monthly_record", 76, "..."),
    "anomaly": ThresholdEntry("anomaly", 74, "lowered 76→74 in PR #96 — 11-14°C deviations are real news"),
    "record_streak": ThresholdEntry("record_streak", 74, "..."),
    "simultaneous_records": ThresholdEntry("simultaneous_records", 78, "..."),
    "hot10": ThresholdEntry("hot10", 56, "..."),
    "synthesis_fire_drought_heat": ThresholdEntry("synthesis_fire_drought_heat", 82, "..."),
}

def get_threshold(category: str) -> int:
    """Return the configured threshold for a category. Raises KeyError if missing."""
    return THRESHOLDS[category].threshold
```

### Step 2 — Refactor scoring.py to use the registry

Replace every inline `threshold=N` in `score_*` functions with `threshold=get_threshold("<category>")`. Example:

```python
# before
return _build_score(
    "anomaly",
    severity=72 + min(abs_anomaly - 15, 10) * 3,
    novelty=82,
    ...
    threshold=74,
    reasons=reasons,
)

# after
return _build_score(
    "anomaly",
    severity=72 + min(abs_anomaly - 15, 10) * 3,
    novelty=82,
    ...
    threshold=get_threshold("anomaly"),
    reasons=reasons,
)
```

### Step 3 — Add registry tests

[/Users/andrewpuschel/Documents/Claude/theheat/tests/test_thresholds.py](/Users/andrewpuschel/Documents/Claude/theheat/tests/test_thresholds.py) (new):

- Every category in `THRESHOLDS` has a corresponding `score_*` function in `scoring.py`
- Every `score_*` function references a category that exists in `THRESHOLDS`
- `get_threshold` raises `KeyError` for unknown categories
- Threshold values are integers in `[0, 100]`
- Every entry has a non-empty rationale

### Step 4 — Existing test suite passes unchanged

All ~30 tests in [/Users/andrewpuschel/Documents/Claude/theheat/tests/test_editorial_scoring.py](/Users/andrewpuschel/Documents/Claude/theheat/tests/test_editorial_scoring.py) must pass without modification. The behavior contract is: same threshold values, same scoring math, just centralized.

## Files

- `src/editorial/thresholds.py` (new) — the registry
- `src/editorial/scoring.py` — refactor every `threshold=N` callsite
- `tests/test_thresholds.py` (new) — registry consistency tests
- `tests/test_editorial_scoring.py` — should pass without modification

## Constraints

- **Behavior-preserving refactor.** All thresholds remain at their current values. The point is centralization, not retuning.
- **No new dependencies.**
- **Rationales aren't optional.** Each entry's rationale must be substantive — a one-line explanation, ideally citing the PR or session where the value was set. For pre-existing thresholds with unknown rationale, write "historical value, not retuned in this refactor" rather than leaving blank.
- **Subagent model floor:** Sonnet 4.6.

## Acceptance

- mypy clean, ruff clean
- Full suite passes (no test modifications expected)
- Registry has 1 entry per `score_*` function in `scoring.py`
- `python -c "from src.editorial.thresholds import THRESHOLDS; print(len(THRESHOLDS))"` returns the expected count (~25)

## Branch / PR sequence

1. Branch `hygiene/threshold-registry` from `main` (after Plans D, E, F all land).
2. Build registry → refactor scoring.py → add tests → run full suite.
3. PR → CI green → Claude merges.

Done. ~2-3 hours CC.
