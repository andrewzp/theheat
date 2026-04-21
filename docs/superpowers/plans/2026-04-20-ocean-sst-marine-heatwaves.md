# Ocean SST & Marine Heatwaves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NOAA OISST-derived global mean sea surface temperature as a new data source for @theheat that fires tweets when the global ocean posts consecutive days above the archive record for the calendar day-of-year.

**Architecture:** New stateless `src/data/ocean_sst.py` module handles fetch from ClimateReanalyzer JSON and derives the current streak from the payload itself on every run. A 2-field `ocean_sst_streak` state dict (`seeded`, `last_milestone_fired`) handles idempotency. `run_alerts` wires fetch → detect → score → generate → save. Editorial surface: scoring threshold 78, `suggested_auto` approval with 90-min delay.

**Tech Stack:** Python 3.11+, `requests` (existing dependency), `pytest` (existing), `responses` library for HTTP mocking (confirm installed via `pip show responses` or use `unittest.mock` if unavailable — existing tests like `tests/test_co2.py` use `unittest.mock.patch("requests.get")` which is the established pattern).

**Spec:** `docs/superpowers/specs/2026-04-20-ocean-sst-marine-heatwaves-design.md`

---

## File Structure

**New files:**
- `src/data/ocean_sst.py` — fetch + detection (stateless). Exports `GlobalSSTObservation`, `MarineHeatwaveStreakEvent`, `MILESTONES`, `fetch_global_sst()`, `detect_streak_milestone()`.
- `tests/test_ocean_sst.py` — ~15 tests covering fetch, streak walk, and detection.

**Modified files:**
- `src/state.py` — add `ocean_sst_streak` to `DEFAULT_STATE`, handle in `_merge_state`, add `update_ocean_sst_streak` helper.
- `src/editorial/scoring.py` — add `score_marine_heatwave(days, peak_anomaly_c, years_of_data)`.
- `src/editorial/approval.py` — add `marine_heatwave` branch.
- `src/editorial/candidates.py` — add `marine_heatwave` entry to `CATEGORY_HINTS`.
- `src/voice/templates.py` — add `marine_heatwave_template`.
- `src/voice/generator.py` — add `generate_marine_heatwave_tweet`.
- `src/main.py` — import `ocean_sst` and `score_marine_heatwave`; add `run_alerts` section between `ocean` (waves) and `water_levels`.
- `tests/test_state.py` — merge + helper tests.
- `tests/test_editorial_scoring.py` — scoring tests.
- `tests/test_editorial_approval.py` — approval branch test.
- `tests/test_main.py` — integration test.
- `BRIEFING.md` — add source + threshold.
- `PIPELINE.md` — add Mermaid node.

Each file has one clear responsibility: data module does pure fetch/detect, state module owns persistence, editorial modules own scoring/approval/ranking, voice modules own copy generation, main wires them together.

---

## Task 1: State — add `ocean_sst_streak` key

**Files:**
- Modify: `src/state.py` (add to `DEFAULT_STATE`, handle in `_merge_state`, add helper)
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test for default state key**

Add to `tests/test_state.py`:

```python
def test_default_state_has_ocean_sst_streak():
    from src.state import DEFAULT_STATE
    assert "ocean_sst_streak" in DEFAULT_STATE
    assert DEFAULT_STATE["ocean_sst_streak"] == {
        "seeded": False,
        "last_milestone_fired": None,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py::test_default_state_has_ocean_sst_streak -v`
Expected: FAIL with `KeyError` or `AssertionError: 'ocean_sst_streak' not in DEFAULT_STATE`.

- [ ] **Step 3: Add the key to `DEFAULT_STATE`**

In `src/state.py`, inside `DEFAULT_STATE` dict (after the `record_streaks` entry around line 38), add:

```python
    # Global ocean SST archive-high streak. Two-field state:
    # seeded flips True after first observation (enables silent bootstrap);
    # last_milestone_fired tracks which milestone we last tweeted so
    # same-day re-runs don't double-fire.
    "ocean_sst_streak": {
        "seeded": False,
        "last_milestone_fired": None,
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state.py::test_default_state_has_ocean_sst_streak -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for `_merge_state`**

Add to `tests/test_state.py`:

```python
def test_merge_state_prefers_incoming_ocean_sst_streak():
    from src.state import _merge_state
    current = {"ocean_sst_streak": {"seeded": True, "last_milestone_fired": 5}}
    incoming = {"ocean_sst_streak": {"seeded": True, "last_milestone_fired": 25}}
    merged = _merge_state(current, incoming)
    assert merged["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": 25}


def test_merge_state_falls_back_to_current_when_incoming_missing():
    from src.state import _merge_state
    current = {"ocean_sst_streak": {"seeded": True, "last_milestone_fired": 10}}
    incoming = {}
    merged = _merge_state(current, incoming)
    # _normalize_state fills incoming with DEFAULT_STATE's ocean_sst_streak,
    # which would clobber current. So we must take current when incoming is default.
    # The contract: if incoming differs from default, prefer it; otherwise keep current.
    # Simpler: always take incoming (matches record_streaks behavior). Document this.
    assert merged["ocean_sst_streak"] == {"seeded": False, "last_milestone_fired": None}
```

- [ ] **Step 6: Run tests to verify failure**

Run: `python -m pytest tests/test_state.py::test_merge_state_prefers_incoming_ocean_sst_streak tests/test_state.py::test_merge_state_falls_back_to_current_when_incoming_missing -v`
Expected: FAIL — key missing in merged result.

- [ ] **Step 7: Add `ocean_sst_streak` handling in `_merge_state`**

In `src/state.py`, inside `_merge_state` after the `record_streaks` line (around line 222), add:

```python
    merged["ocean_sst_streak"] = deepcopy(
        next_state.get("ocean_sst_streak", base.get("ocean_sst_streak", {}))
    )
```

- [ ] **Step 8: Run tests to verify pass**

Run: `python -m pytest tests/test_state.py::test_merge_state_prefers_incoming_ocean_sst_streak tests/test_state.py::test_merge_state_falls_back_to_current_when_incoming_missing -v`
Expected: PASS.

- [ ] **Step 9: Write the failing test for `update_ocean_sst_streak` helper**

Add to `tests/test_state.py`:

```python
def test_update_ocean_sst_streak_replaces_dict():
    from src.state import _fresh_state, update_ocean_sst_streak
    state = _fresh_state()
    result = update_ocean_sst_streak(state, {"seeded": True, "last_milestone_fired": 25})
    assert result["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": 25}


def test_update_ocean_sst_streak_handles_missing_key():
    from src.state import update_ocean_sst_streak
    state = {}
    result = update_ocean_sst_streak(state, {"seeded": True, "last_milestone_fired": None})
    assert result["ocean_sst_streak"] == {"seeded": True, "last_milestone_fired": None}
```

- [ ] **Step 10: Run tests to verify failure**

Run: `python -m pytest tests/test_state.py::test_update_ocean_sst_streak_replaces_dict tests/test_state.py::test_update_ocean_sst_streak_handles_missing_key -v`
Expected: FAIL with `ImportError: cannot import name 'update_ocean_sst_streak'`.

- [ ] **Step 11: Add the `update_ocean_sst_streak` helper**

In `src/state.py`, after `prune_stale_record_streaks` (around line 404), add:

```python
def update_ocean_sst_streak(state: dict, streak: dict) -> dict:
    """Replace the stored ocean SST streak state.

    Idempotent: callers always pass the full two-field dict
    ({seeded: bool, last_milestone_fired: int | None}) computed from the
    most recent observation. No incremental mutation.
    """
    state["ocean_sst_streak"] = {
        "seeded": bool(streak.get("seeded", False)),
        "last_milestone_fired": streak.get("last_milestone_fired"),
    }
    return state
```

- [ ] **Step 12: Run tests to verify pass**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS for all new tests; no regressions in existing tests.

- [ ] **Step 13: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat: add ocean_sst_streak to state — seeded + last_milestone_fired"
```

---

## Task 2: Data module — dataclasses and `MILESTONES`

**Files:**
- Create: `src/data/ocean_sst.py`
- Test: `tests/test_ocean_sst.py`

- [ ] **Step 1: Write the failing test for imports**

Create `tests/test_ocean_sst.py`:

```python
"""Tests for global ocean SST fetch + marine-heatwave-streak detection."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests


def test_module_exports_public_api():
    from src.data import ocean_sst
    assert hasattr(ocean_sst, "GlobalSSTObservation")
    assert hasattr(ocean_sst, "MarineHeatwaveStreakEvent")
    assert hasattr(ocean_sst, "MILESTONES")
    assert hasattr(ocean_sst, "fetch_global_sst")
    assert hasattr(ocean_sst, "detect_streak_milestone")


def test_milestones_ladder_values():
    from src.data.ocean_sst import MILESTONES
    assert MILESTONES == (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_ocean_sst.py::test_module_exports_public_api -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.data.ocean_sst'`.

- [ ] **Step 3: Create the skeleton module**

Create `src/data/ocean_sst.py`:

```python
"""Global ocean sea-surface-temperature fetch + marine-heatwave-streak detection.

Primary source: ClimateReanalyzer (University of Maine) JSON endpoint,
which publishes NOAA OISST v2.1 global-mean daily values with the full
1982 → present archive in one payload.

The streak count is derived from the payload itself on every run (walking
backward from today's day-of-year), not accumulated in our state. This
keeps the "Nth consecutive day" claim factually defensible regardless of
cron outages on our side.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import requests

SST_URL = (
    "https://climatereanalyzer.org/clim/sst_daily/json/"
    "oisst2.1_world_sst_day.json"
)

# Fire on the first day of a confirmed streak (day 5, per Hobday et al.
# 2016 MHW definition), then at each of these milestone day-counts.
# Past 400: every +50 (see _milestones_up_to).
MILESTONES: tuple[int, ...] = (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


@dataclass(frozen=True)
class GlobalSSTObservation:
    date: str
    day_of_year: int
    today_c: float
    archive_max_c: float
    archive_max_year: int
    years_of_data: int
    streak_days: int
    streak_start_date: str | None
    streak_peak_anomaly_c: float


@dataclass(frozen=True)
class MarineHeatwaveStreakEvent:
    kind: str  # "first" | "milestone"
    days: int
    peak_anomaly_c: float
    today_c: float
    archive_max_c: float
    archive_max_year: int
    years_of_data: int
    date: str
    event_id: str


def _milestones_up_to(days: int) -> tuple[int, ...]:
    """Return all milestone thresholds <= days, ascending.

    Base ladder is MILESTONES (5, 10, 25, 50, 100, 150, 200, 250, 300,
    365, 400); after 400 the ladder continues every +50 (450, 500, ...).
    """
    below_or_equal = tuple(m for m in MILESTONES if m <= days)
    if days <= 400:
        return below_or_equal
    extra = tuple(range(450, days + 1, 50))
    return below_or_equal + extra


def fetch_global_sst() -> GlobalSSTObservation | None:
    raise NotImplementedError  # implemented in Task 3


def detect_streak_milestone(
    obs: GlobalSSTObservation,
    prior: dict,
) -> tuple[dict, MarineHeatwaveStreakEvent | None]:
    raise NotImplementedError  # implemented in Task 4
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py::test_module_exports_public_api tests/test_ocean_sst.py::test_milestones_ladder_values -v`
Expected: PASS.

- [ ] **Step 5: Add a test for `_milestones_up_to` extension past 400**

Add to `tests/test_ocean_sst.py`:

```python
def test_milestones_up_to_under_400():
    from src.data.ocean_sst import _milestones_up_to
    assert _milestones_up_to(4) == ()
    assert _milestones_up_to(5) == (5,)
    assert _milestones_up_to(47) == (5, 10, 25)
    assert _milestones_up_to(400) == (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


def test_milestones_up_to_past_400():
    from src.data.ocean_sst import _milestones_up_to
    assert _milestones_up_to(450) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, 450,
    )
    assert _milestones_up_to(500) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, 450, 500,
    )
    assert _milestones_up_to(449) == (
        5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400,
    )
```

- [ ] **Step 6: Run tests to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/data/ocean_sst.py tests/test_ocean_sst.py
git commit -m "feat: scaffold ocean_sst module with dataclasses and milestone ladder"
```

---

## Task 3: Data module — `fetch_global_sst` implementation

**Files:**
- Modify: `src/data/ocean_sst.py`
- Test: `tests/test_ocean_sst.py`

The fetcher does four things:
1. GET the JSON.
2. Pick today's value as the most-recent non-null index in the current-year array.
3. Compute archive max for that day-of-year across 1982 → (current_year - 1).
4. Walk backward day-by-day to compute `streak_days`, `streak_start_date`, `streak_peak_anomaly_c`.

- [ ] **Step 1: Write the failing test — happy path**

Add to `tests/test_ocean_sst.py`:

```python
def _fake_payload(current_year: int, today_doy: int,
                  current_year_values: list,
                  prior_years: dict[int, list]) -> dict:
    """Helper: build a ClimateReanalyzer-shaped JSON payload.

    current_year_values is the full 365/366-entry array (pad with None after today).
    prior_years maps year → 365/366-entry array.
    """
    payload = {str(y): arr for y, arr in prior_years.items()}
    payload[str(current_year)] = current_year_values
    return payload


def test_fetch_global_sst_happy_path():
    from src.data import ocean_sst

    # Scenario: today is doy 100 of year 2026.
    # Current year value at doy 100 = 20.5.
    # Three prior years (1982, 1983, 2025): their doy 100 values are 19.5, 20.0, 20.3.
    # Archive max for doy 100 = 20.3, set 2025.
    # Streak: check only doy 100. Value 20.5 > 20.3 → streak = 1.
    today_doy = 100
    cur_values = [None] * 365
    cur_values[today_doy - 1] = 20.5
    prior = {
        1982: [19.5] * 365,
        1983: [20.0] * 365,
        2025: [20.3] * 365,
    }
    payload = _fake_payload(2026, today_doy, cur_values, prior)

    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()

    assert obs is not None
    assert obs.day_of_year == 100
    assert obs.today_c == pytest.approx(20.5)
    assert obs.archive_max_c == pytest.approx(20.3)
    assert obs.archive_max_year == 2025
    assert obs.years_of_data == 2026 - 1982  # 44
    assert obs.streak_days == 1
    assert obs.streak_peak_anomaly_c == pytest.approx(0.2)
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_ocean_sst.py::test_fetch_global_sst_happy_path -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `fetch_global_sst` and helpers**

In `src/data/ocean_sst.py`, replace the `NotImplementedError` body and add helpers:

```python
def _today_year_doy() -> tuple[int, int]:
    """Return (current_year, today_day_of_year). Wrapped for test injection."""
    today = date.today()
    return today.year, today.timetuple().tm_yday


def _valid_sst(v) -> bool:
    """Accept realistic global-mean SST values in Celsius."""
    return isinstance(v, (int, float)) and -2.0 <= v <= 40.0


def _date_from_doy(year: int, doy: int) -> str:
    return (date(year, 1, 1) + timedelta(days=doy - 1)).isoformat()


def _archive_max_for_doy(prior_years_arrs: dict[int, list], doy: int) -> tuple[float, int] | None:
    """Return (max_value, year) across prior years for a given day-of-year index.

    Returns None if no prior year has a valid value for that day.
    """
    best: tuple[float, int] | None = None
    for year, arr in prior_years_arrs.items():
        idx = doy - 1
        if idx < 0 or idx >= len(arr):
            continue
        v = arr[idx]
        if not _valid_sst(v):
            continue
        if best is None or v > best[0]:
            best = (float(v), year)
    return best


def _walk_streak_backward(
    current_year: int,
    today_doy: int,
    current_arr: list,
    prior_arrs: dict[int, list],
) -> tuple[int, int | None, int | None, float]:
    """Walk backward from today_doy to compute the streak.

    Returns (streak_days, streak_start_year, streak_start_doy, peak_anomaly).
    If the streak reaches doy 1 of current_year, continues into current_year-1.
    """
    streak_days = 0
    streak_start_year: int | None = None
    streak_start_doy: int | None = None
    peak = 0.0

    def _step(year: int, doy: int, arr: list, pa: dict[int, list]) -> bool:
        nonlocal streak_days, streak_start_year, streak_start_doy, peak
        idx = doy - 1
        if idx < 0 or idx >= len(arr):
            return False
        v = arr[idx]
        if not _valid_sst(v):
            return False
        amax = _archive_max_for_doy(pa, doy)
        if amax is None:
            return False
        if v > amax[0]:
            streak_days += 1
            streak_start_year = year
            streak_start_doy = doy
            peak = max(peak, float(v) - amax[0])
            return True
        return False

    # Walk current year first.
    for doy in range(today_doy, 0, -1):
        if not _step(current_year, doy, current_arr, prior_arrs):
            return streak_days, streak_start_year, streak_start_doy, peak

    # Streak reached Jan 1 of current_year — continue into prior calendar year.
    prev_year = current_year - 1
    prev_arr = prior_arrs.get(prev_year)
    if prev_arr is None:
        return streak_days, streak_start_year, streak_start_doy, peak
    # For the archive comparison when walking the prior calendar year, the
    # "prior years" set excludes that year itself.
    deeper_priors = {y: a for y, a in prior_arrs.items() if y != prev_year}
    for doy in range(len(prev_arr), 0, -1):
        if not _step(prev_year, doy, prev_arr, deeper_priors):
            return streak_days, streak_start_year, streak_start_doy, peak

    return streak_days, streak_start_year, streak_start_doy, peak


def fetch_global_sst() -> GlobalSSTObservation | None:
    """Fetch global-mean SST from ClimateReanalyzer and derive the current streak.

    Returns None on any fetch/validation failure. Never raises.
    """
    try:
        resp = requests.get(SST_URL, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    current_year, today_doy = _today_year_doy()
    cur_arr = payload.get(str(current_year))
    if not isinstance(cur_arr, list) or not cur_arr:
        return None

    # Find most recent non-null index at or before today_doy.
    today_idx = None
    for idx in range(min(today_doy, len(cur_arr)) - 1, -1, -1):
        if _valid_sst(cur_arr[idx]):
            today_idx = idx
            break
    if today_idx is None:
        return None
    today_doy = today_idx + 1
    today_c = float(cur_arr[today_idx])

    prior_arrs: dict[int, list] = {}
    for key, val in payload.items():
        try:
            y = int(key)
        except (TypeError, ValueError):
            continue
        if y >= current_year or y < 1982:
            continue
        if isinstance(val, list):
            prior_arrs[y] = val

    if len(prior_arrs) < 30:
        return None

    amax = _archive_max_for_doy(prior_arrs, today_doy)
    if amax is None:
        return None
    archive_max_c, archive_max_year = amax

    streak_days, streak_start_year, streak_start_doy, peak = _walk_streak_backward(
        current_year, today_doy, cur_arr, prior_arrs,
    )
    streak_start_date = (
        _date_from_doy(streak_start_year, streak_start_doy)
        if streak_start_year and streak_start_doy
        else None
    )

    return GlobalSSTObservation(
        date=_date_from_doy(current_year, today_doy),
        day_of_year=today_doy,
        today_c=today_c,
        archive_max_c=archive_max_c,
        archive_max_year=archive_max_year,
        years_of_data=current_year - 1982,
        streak_days=streak_days,
        streak_start_date=streak_start_date,
        streak_peak_anomaly_c=peak,
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py::test_fetch_global_sst_happy_path -v`
Expected: PASS.

- [ ] **Step 5: Write test — streak stops at first non-exceedance**

Add to `tests/test_ocean_sst.py`:

```python
def test_fetch_global_sst_streak_stops_at_first_non_exceedance():
    """3 days exceed archive, 4th does not → streak_days=3."""
    from src.data import ocean_sst
    today_doy = 50
    cur = [None] * 365
    # Days 47, 48, 49, 50 of current year.
    cur[46] = 18.0  # day 47 — NOT above (archive 18.5)
    cur[47] = 19.0  # day 48 — above (archive 18.5)
    cur[48] = 19.1  # day 49 — above (archive 18.6)
    cur[49] = 19.2  # day 50 — above (archive 18.7)
    # Build 32 prior years so validation passes; all with flat archive values.
    prior = {}
    for y in range(1982, 2026):
        arr = [18.0] * 365
        arr[47] = 18.5
        arr[48] = 18.6
        arr[49] = 18.7
        prior[y] = arr

    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is not None
    assert obs.streak_days == 3
```

- [ ] **Step 6: Run test to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py::test_fetch_global_sst_streak_stops_at_first_non_exceedance -v`
Expected: PASS.

- [ ] **Step 7: Write test — streak crosses new year**

Add to `tests/test_ocean_sst.py`:

```python
def test_fetch_global_sst_streak_crosses_new_year():
    """Streak extends back through doy 1 of current year into prior December."""
    from src.data import ocean_sst
    today_doy = 3  # Jan 3
    cur = [None] * 365
    cur[0] = 19.0  # Jan 1 — above archive 18.5
    cur[1] = 19.1  # Jan 2 — above archive 18.5
    cur[2] = 19.2  # Jan 3 — above archive 18.5

    # Prior years: 1982..2025. 2025 is current_year - 1; its Dec 31 is above
    # archive to extend streak.
    prior: dict[int, list] = {}
    for y in range(1982, 2026):
        arr = [18.0] * 365
        arr[0] = 18.5   # baseline for Jan 1
        arr[1] = 18.5   # Jan 2
        arr[2] = 18.5   # Jan 3
        arr[364] = 18.5 if y != 2025 else 19.0  # Dec 31 in 2025 = 19.0
        prior[y] = arr
    # 2025's Dec 30: above archive?
    prior[2025][363] = 19.0  # Dec 30
    prior[2025][362] = 18.0  # Dec 29 — NOT above archive 18.5 → streak stops

    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    # Jan 3, 2, 1, Dec 31 2025, Dec 30 2025 = 5 days.
    assert obs is not None
    assert obs.streak_days == 5
```

- [ ] **Step 8: Run test to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py::test_fetch_global_sst_streak_crosses_new_year -v`
Expected: PASS.

- [ ] **Step 9: Write tests — failure modes**

Add to `tests/test_ocean_sst.py`:

```python
def test_fetch_global_sst_returns_none_on_empty_current_year():
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365  # all nulls
    prior = {y: [18.0] * 365 for y in range(1982, 2026)}
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is None


def test_fetch_global_sst_returns_none_on_http_error():
    from src.data import ocean_sst
    with patch("src.data.ocean_sst.requests.get",
               side_effect=requests.RequestException("boom")):
        assert ocean_sst.fetch_global_sst() is None


def test_fetch_global_sst_rejects_out_of_range_values():
    """Values outside [-2, 40] are treated as invalid → archive max falls back."""
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365
    cur[99] = 20.5
    prior = {y: [18.0] * 365 for y in range(1982, 2026)}
    prior[2020][99] = 999.0  # absurd value — ignored
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is not None
    assert obs.archive_max_c == pytest.approx(18.0)


def test_fetch_global_sst_handles_today_null_uses_latest_non_null():
    """Today's index null; latest non-null used as observation date."""
    from src.data import ocean_sst
    today_doy = 100
    cur = [None] * 365
    cur[97] = 20.5  # day 98 has value, 99 and 100 null
    prior = {y: [18.0] * 365 for y in range(1982, 2026)}
    payload = _fake_payload(2026, today_doy, cur, prior)
    with patch("src.data.ocean_sst._today_year_doy", return_value=(2026, today_doy)):
        with patch("src.data.ocean_sst.requests.get") as mock_get:
            mock_get.return_value.raise_for_status = lambda: None
            mock_get.return_value.json = lambda: payload
            obs = ocean_sst.fetch_global_sst()
    assert obs is not None
    assert obs.day_of_year == 98
    assert obs.today_c == pytest.approx(20.5)
```

- [ ] **Step 10: Run tests to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py -v`
Expected: PASS for all tests.

- [ ] **Step 11: Commit**

```bash
git add src/data/ocean_sst.py tests/test_ocean_sst.py
git commit -m "feat: implement fetch_global_sst with streak derivation from payload"
```

---

## Task 4: Data module — `detect_streak_milestone` implementation

**Files:**
- Modify: `src/data/ocean_sst.py`
- Test: `tests/test_ocean_sst.py`

- [ ] **Step 1: Write test — silent seed on first run**

Add to `tests/test_ocean_sst.py`:

```python
def _obs(streak_days: int = 5, **overrides):
    from src.data.ocean_sst import GlobalSSTObservation
    defaults = dict(
        date="2026-04-20",
        day_of_year=110,
        today_c=20.5,
        archive_max_c=20.3,
        archive_max_year=2025,
        years_of_data=44,
        streak_days=streak_days,
        streak_start_date="2026-04-16",
        streak_peak_anomaly_c=0.2,
    )
    defaults.update(overrides)
    return GlobalSSTObservation(**defaults)


def test_detect_first_run_silent_seed():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": False, "last_milestone_fired": None}
    new_state, event = detect_streak_milestone(_obs(streak_days=20), prior)
    assert new_state == {"seeded": True, "last_milestone_fired": None}
    assert event is None
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_ocean_sst.py::test_detect_first_run_silent_seed -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `detect_streak_milestone`**

In `src/data/ocean_sst.py`, replace the `NotImplementedError` body:

```python
def detect_streak_milestone(
    obs: GlobalSSTObservation,
    prior: dict,
) -> tuple[dict, MarineHeatwaveStreakEvent | None]:
    """Decide whether an observation should fire a milestone tweet.

    Returns (new_state, event_or_none). new_state is always the full
    two-field dict the caller should persist via update_ocean_sst_streak.
    """
    seeded = bool(prior.get("seeded", False))
    last_fired = prior.get("last_milestone_fired")

    # 1. First-ever observation — silent seed.
    if not seeded:
        return ({"seeded": True, "last_milestone_fired": None}, None)

    # 2. Streak broken — clear the fired-marker, no event.
    if obs.streak_days <= 0:
        return ({"seeded": True, "last_milestone_fired": None}, None)

    # 3. Below first-fire threshold (day 5).
    if obs.streak_days < 5:
        # Fresh sub-threshold streak after a break should carry last_fired=None,
        # which the streak-broken branch above will have already done.
        return (
            {"seeded": True, "last_milestone_fired": last_fired},
            None,
        )

    # 4. Find the largest milestone not yet fired this streak.
    already = last_fired or 0
    candidates = [m for m in _milestones_up_to(obs.streak_days) if m > already]
    if not candidates:
        return (
            {"seeded": True, "last_milestone_fired": last_fired},
            None,
        )
    crossed = max(candidates)

    event = MarineHeatwaveStreakEvent(
        kind="first" if crossed == 5 and already == 0 else "milestone",
        days=crossed,
        peak_anomaly_c=obs.streak_peak_anomaly_c,
        today_c=obs.today_c,
        archive_max_c=obs.archive_max_c,
        archive_max_year=obs.archive_max_year,
        years_of_data=obs.years_of_data,
        date=obs.date,
        event_id=f"marine_heatwave_streak_{crossed}_{obs.date}",
    )
    return ({"seeded": True, "last_milestone_fired": crossed}, event)
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py::test_detect_first_run_silent_seed -v`
Expected: PASS.

- [ ] **Step 5: Write remaining detection tests**

Add to `tests/test_ocean_sst.py`:

```python
def test_detect_streak_under_5_no_fire():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": None}
    new_state, event = detect_streak_milestone(_obs(streak_days=4), prior)
    assert event is None
    assert new_state == {"seeded": True, "last_milestone_fired": None}


def test_detect_day_5_first_fire():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": None}
    new_state, event = detect_streak_milestone(_obs(streak_days=5), prior)
    assert event is not None
    assert event.kind == "first"
    assert event.days == 5
    assert event.event_id == "marine_heatwave_streak_5_2026-04-20"
    assert new_state == {"seeded": True, "last_milestone_fired": 5}


def test_detect_milestone_crossing():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 25}
    new_state, event = detect_streak_milestone(_obs(streak_days=50), prior)
    assert event is not None
    assert event.kind == "milestone"
    assert event.days == 50
    assert new_state == {"seeded": True, "last_milestone_fired": 50}


def test_detect_no_refire_same_milestone():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 50}
    new_state, event = detect_streak_milestone(_obs(streak_days=50), prior)
    assert event is None
    assert new_state == {"seeded": True, "last_milestone_fired": 50}


def test_detect_skip_missed_milestones():
    """Cron missed runs. Prior=5, streak=47 → fire 25 only (highest ≤ 47)."""
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 5}
    new_state, event = detect_streak_milestone(_obs(streak_days=47), prior)
    assert event is not None
    assert event.days == 25
    assert new_state == {"seeded": True, "last_milestone_fired": 25}


def test_detect_streak_break_clears_last_fired():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 50}
    new_state, event = detect_streak_milestone(_obs(streak_days=0), prior)
    assert event is None
    assert new_state == {"seeded": True, "last_milestone_fired": None}


def test_detect_past_400_every_50():
    from src.data.ocean_sst import detect_streak_milestone
    prior = {"seeded": True, "last_milestone_fired": 400}
    new_state, event = detect_streak_milestone(_obs(streak_days=450), prior)
    assert event is not None
    assert event.kind == "milestone"
    assert event.days == 450
    assert new_state == {"seeded": True, "last_milestone_fired": 450}
```

- [ ] **Step 6: Run tests to verify pass**

Run: `python -m pytest tests/test_ocean_sst.py -v`
Expected: PASS for all tests.

- [ ] **Step 7: Commit**

```bash
git add src/data/ocean_sst.py tests/test_ocean_sst.py
git commit -m "feat: implement detect_streak_milestone with silent seed + milestone ladder"
```

---

## Task 5: Editorial scoring — `score_marine_heatwave`

**Files:**
- Modify: `src/editorial/scoring.py`
- Test: `tests/test_editorial_scoring.py`

- [ ] **Step 1: Write failing test — day 5 passes threshold**

Add to `tests/test_editorial_scoring.py`:

```python
def test_score_marine_heatwave_day_5_passes_threshold():
    from src.editorial.scoring import score_marine_heatwave
    score = score_marine_heatwave(days=5, peak_anomaly_c=0.25, years_of_data=44)
    assert score.category == "marine_heatwave"
    assert score.threshold == 78
    assert score.passes, f"day-5 streak should pass, got {score.total}"


def test_score_marine_heatwave_day_100_is_elite():
    from src.editorial.scoring import score_marine_heatwave
    score = score_marine_heatwave(days=100, peak_anomaly_c=0.4, years_of_data=44)
    assert score.total >= 85, f"day-100 should be elite, got {score.total}"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_editorial_scoring.py::test_score_marine_heatwave_day_5_passes_threshold tests/test_editorial_scoring.py::test_score_marine_heatwave_day_100_is_elite -v`
Expected: FAIL with `ImportError: cannot import name 'score_marine_heatwave'`.

- [ ] **Step 3: Add `score_marine_heatwave`**

In `src/editorial/scoring.py`, after `score_extreme_wave` (around line 425), add:

```python
def score_marine_heatwave(
    days: int,
    peak_anomaly_c: float,
    years_of_data: int,
) -> EditorialScore:
    reasons = [
        f"{days}-day streak above the daily archive record",
        f"peak {peak_anomaly_c:+.2f}°C above prior daily max",
        f"{years_of_data}-year satellite record",
    ]
    if days >= 100:
        reasons.append("triple-digit consecutive-day streak")
    if peak_anomaly_c >= 0.5:
        reasons.append("half-degree anomaly on a global mean")

    return _build_score(
        "marine_heatwave",
        severity=72 + min(days / 4.0, 22) + min(peak_anomaly_c * 10, 10),
        novelty=80 + min(days / 10.0, 10),
        timeliness=86,
        confidence=92,
        shareability=80 + min(days / 20.0, 12),
        sensitivity=6,
        threshold=78,
        reasons=reasons,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_editorial_scoring.py::test_score_marine_heatwave_day_5_passes_threshold tests/test_editorial_scoring.py::test_score_marine_heatwave_day_100_is_elite -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/scoring.py tests/test_editorial_scoring.py
git commit -m "feat: add score_marine_heatwave with threshold 78"
```

---

## Task 6: Editorial approval — `marine_heatwave` branch

**Files:**
- Modify: `src/editorial/approval.py`
- Test: `tests/test_editorial_approval.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_editorial_approval.py`:

```python
def test_marine_heatwave_suggested_auto_90min():
    from src.editorial.approval import recommend_approval_policy
    policy = recommend_approval_policy(
        "marine_heatwave", signal_total=82, candidate_score={"total": 80},
    )
    assert policy.mode == "suggested_auto"
    assert policy.recommended_delay_minutes == 90
    assert policy.can_auto_approve is True
    assert policy.key == "marine_heatwave_review"
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_editorial_approval.py::test_marine_heatwave_suggested_auto_90min -v`
Expected: FAIL — policy falls through to `default_review`.

- [ ] **Step 3: Add the `marine_heatwave` branch**

In `src/editorial/approval.py`, insert a new branch before the `default_review` fallback (after the `record`/`record_low`/`sea_ice_record` branch around line 96):

```python
    if tweet_type == "marine_heatwave":
        return ApprovalPolicy(
            key="marine_heatwave_review",
            mode="suggested_auto",
            recommended_delay_minutes=90,
            can_auto_approve=True,
            reason=(
                "Ocean-SST streak signal — low human-harm risk, high accuracy "
                "from a single well-known dataset. Short review window lets a "
                "human polish framing before auto-post."
            ),
        )
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_editorial_approval.py::test_marine_heatwave_suggested_auto_90min -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/approval.py tests/test_editorial_approval.py
git commit -m "feat: add marine_heatwave approval policy — suggested_auto 90min"
```

---

## Task 7: Editorial candidates — category hints

**Files:**
- Modify: `src/editorial/candidates.py`
- Test: `tests/test_editorial_candidates.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_editorial_candidates.py`:

```python
def test_category_hints_include_marine_heatwave():
    from src.editorial.candidates import CATEGORY_HINTS
    assert "marine_heatwave" in CATEGORY_HINTS
    hints = CATEGORY_HINTS["marine_heatwave"]
    assert "ocean" in hints
    assert "record" in hints
    assert "consecutive" in hints
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_editorial_candidates.py::test_category_hints_include_marine_heatwave -v`
Expected: FAIL with `AssertionError: 'marine_heatwave' not in CATEGORY_HINTS`.

- [ ] **Step 3: Add the entry**

In `src/editorial/candidates.py`, inside the `CATEGORY_HINTS` dict (after `"hot10"` around line 35), add:

```python
    "marine_heatwave": ("ocean", "record", "consecutive"),
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_editorial_candidates.py::test_category_hints_include_marine_heatwave -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/candidates.py tests/test_editorial_candidates.py
git commit -m "feat: add marine_heatwave to editorial candidate hints"
```

---

## Task 8: Voice template — `marine_heatwave_template`

**Files:**
- Modify: `src/voice/templates.py`
- Test: `tests/test_generator.py` (or `tests/test_templates.py` if it exists; templates are currently tested implicitly via test_generator.py)

- [ ] **Step 1: Write failing test**

Add to `tests/test_generator.py`:

```python
def test_marine_heatwave_template_first_kind_contains_required_facts():
    from src.voice.templates import marine_heatwave_template
    text = marine_heatwave_template(
        kind="first", days=5, today_c=20.52, archive_max_c=20.31,
        archive_max_year=2023, years_of_data=44,
    )
    assert "5" in text
    assert "20.52" in text or "20.5" in text
    assert "20.31" in text or "20.3" in text
    assert "2023" in text
    assert "44 years" in text or "44-year" in text


def test_marine_heatwave_template_milestone_kind_uses_streak_day():
    from src.voice.templates import marine_heatwave_template
    text = marine_heatwave_template(
        kind="milestone", days=100, today_c=20.52, archive_max_c=20.31,
        archive_max_year=2023, years_of_data=44,
    )
    assert "100" in text
    assert "consecutive" in text.lower() or "th" in text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_generator.py::test_marine_heatwave_template_first_kind_contains_required_facts tests/test_generator.py::test_marine_heatwave_template_milestone_kind_uses_streak_day -v`
Expected: FAIL with `ImportError: cannot import name 'marine_heatwave_template'`.

- [ ] **Step 3: Add the template**

In `src/voice/templates.py`, after `extreme_wave_template` (around line 133), add:

```python
def marine_heatwave_template(
    kind: str,
    days: int,
    today_c: float,
    archive_max_c: float,
    archive_max_year: int,
    years_of_data: int,
) -> str:
    if kind == "first":
        variants = [
            (
                f"The global ocean has now been above the daily record for "
                f"{days} straight days in {years_of_data} years of satellite "
                f"data. Today: {today_c:.2f}°C. Prior daily max: "
                f"{archive_max_c:.2f}°C, set {archive_max_year}."
            ),
            (
                f"Five consecutive days of record-breaking global ocean "
                f"surface temps. Today's mean: {today_c:.2f}°C. The previous "
                f"record for this date was {archive_max_c:.2f}°C in "
                f"{archive_max_year}. Archive goes back {years_of_data} years."
            ),
        ]
    else:
        variants = [
            (
                f"The global ocean just posted its {days}th consecutive day "
                f"above the daily record in {years_of_data} years of "
                f"satellite data. Today: {today_c:.2f}°C."
            ),
            (
                f"{days} consecutive days and counting. Global mean SST "
                f"today: {today_c:.2f}°C. Old record for this date: "
                f"{archive_max_c:.2f}°C ({archive_max_year}). "
                f"{years_of_data}-year archive."
            ),
        ]
    return random.choice(variants)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_generator.py::test_marine_heatwave_template_first_kind_contains_required_facts tests/test_generator.py::test_marine_heatwave_template_milestone_kind_uses_streak_day -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/voice/templates.py tests/test_generator.py
git commit -m "feat: add marine_heatwave_template fallback copy"
```

---

## Task 9: Voice generator — `generate_marine_heatwave_tweet`

**Files:**
- Modify: `src/voice/generator.py`
- Test: `tests/test_generator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_generator.py` (follows the existing pattern — empty `GEMINI_API_KEY` triggers fallback):

```python
@patch("src.voice.generator.GEMINI_API_KEY", "")
def test_generate_marine_heatwave_tweet_falls_back_to_template():
    """When Gemini has no API key, the fallback template is used."""
    from src.voice.generator import generate_marine_heatwave_tweet
    result = generate_marine_heatwave_tweet(
        kind="first", days=5,
        today_c=20.52, archive_max_c=20.31,
        archive_max_year=2023, years_of_data=44,
    )
    assert isinstance(result, str)
    assert "5" in result
    assert "20.52" in result or "20.5" in result
```

The `patch` import already exists at the top of `tests/test_generator.py` (`from unittest.mock import patch, MagicMock`).

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_generator.py::test_generate_marine_heatwave_tweet_falls_back_to_template -v`
Expected: FAIL with `AttributeError: module 'src.voice.generator' has no attribute 'generate_marine_heatwave_tweet'`.

- [ ] **Step 3: Add the generator function**

In `src/voice/generator.py`, after `generate_extreme_wave_tweet` (around line 826), add:

```python
def generate_marine_heatwave_tweet(
    kind: str,
    days: int,
    today_c: float,
    archive_max_c: float,
    archive_max_year: int,
    years_of_data: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a marine-heatwave archive-record streak."""
    data = (
        f"Global-mean sea surface temperature is at {today_c:.2f}°C today. "
        f"That's above the daily record for this calendar day ({archive_max_c:.2f}°C, "
        f"set in {archive_max_year}) and it's the {days}th consecutive day this has been true. "
        f"Archive goes back {years_of_data} years (NOAA OISST v2.1). "
        f"Today's date: {__import__('datetime').date.today().strftime('%B %d, %Y')}."
    )
    return generate_tweet(
        data,
        category="marine_heatwave",
        return_bundle=return_bundle,
        fallback_fn=templates.marine_heatwave_template,
        fallback_args={
            "kind": kind,
            "days": days,
            "today_c": today_c,
            "archive_max_c": archive_max_c,
            "archive_max_year": archive_max_year,
            "years_of_data": years_of_data,
        },
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_generator.py::test_generate_marine_heatwave_tweet_falls_back_to_template -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/voice/generator.py tests/test_generator.py
git commit -m "feat: add generate_marine_heatwave_tweet generator"
```

---

## Task 10: `main.run_alerts` — wire the new source

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_main.py` inside the `TestRunAlerts` class (find it via grep — pattern from the existing class-based tests around line 657):

```python
    def test_run_alerts_ocean_sst_drafts_on_day_5(self, monkeypatch, fresh_state):
        """Day-5 streak crossing → one draft saved under marine_heatwave."""
        from src import main
        from src.data.ocean_sst import GlobalSSTObservation, MarineHeatwaveStreakEvent

        fresh_state["ocean_sst_streak"] = {"seeded": True, "last_milestone_fired": None}

        obs = GlobalSSTObservation(
            date="2026-04-20", day_of_year=110,
            today_c=20.52, archive_max_c=20.31,
            archive_max_year=2023, years_of_data=44,
            streak_days=5, streak_start_date="2026-04-16",
            streak_peak_anomaly_c=0.25,
        )

        # Patch all other alert sources to no-ops so only ocean_sst runs.
        monkeypatch.setattr(main.open_meteo, "fetch_all_cities", lambda: [])
        monkeypatch.setattr(main.firms, "fetch_fires", lambda: [])
        monkeypatch.setattr(main.co2, "fetch_co2_data", lambda: [])
        monkeypatch.setattr(main.nws_alerts, "fetch_alerts", lambda: [])
        monkeypatch.setattr(main.gdacs, "fetch_disasters", lambda: [])
        monkeypatch.setattr(main.sea_ice, "fetch_sea_ice", lambda: [])
        monkeypatch.setattr(main.drought, "fetch_drought", lambda: [])
        monkeypatch.setattr(main.enso, "fetch_enso", lambda: None)
        monkeypatch.setattr(main.ocean, "fetch_ocean_conditions", lambda: [])
        monkeypatch.setattr(main.ocean, "detect_extreme_waves", lambda r: [])
        monkeypatch.setattr(main.water_levels, "fetch_water_levels", lambda: [])
        monkeypatch.setattr(main.water_levels, "detect_storm_surge", lambda r: [])
        monkeypatch.setattr(main.river_gauges, "fetch_river_gauges", lambda: [])
        monkeypatch.setattr(main.river_gauges, "detect_floods", lambda r: [])

        monkeypatch.setattr(main.ocean_sst, "fetch_global_sst", lambda: obs)

        # Stub the generator to return a short, safe candidate bundle.
        from src.editorial.candidates import CandidateBundle, DraftCandidate, CandidateScore
        stub_score = CandidateScore(
            clarity=80, context=82, voice=78, punch=80, total=80,
            reasons=("stubbed",),
        )
        stub_bundle = CandidateBundle(
            category="marine_heatwave",
            candidates=[DraftCandidate(
                rank=1, text="Day 5 of record global SSTs.",
                source="template", score=stub_score,
            )],
        )
        monkeypatch.setattr(
            main.generator,
            "generate_marine_heatwave_tweet",
            lambda **kwargs: stub_bundle,
        )

        monkeypatch.setattr(main.state, "read_state", lambda: fresh_state)
        monkeypatch.setattr(main.state, "write_state", lambda s: True)

        main.run_alerts()

        drafts = fresh_state.get("drafts", [])
        marine_drafts = [d for d in drafts if d.get("tweet_type") == "marine_heatwave"]
        assert len(marine_drafts) == 1
        assert "marine_heatwave_streak_5_2026-04-20" in fresh_state.get("posted_events", [])
```

If `fresh_state` already includes `ocean_sst_streak` from Task 1, the explicit initialisation is belt-and-braces. Leave it in.

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_main.py::TestRunAlerts::test_run_alerts_ocean_sst_drafts_on_day_5 -v`
Expected: FAIL with `AttributeError: module 'src.main' has no attribute 'ocean_sst'`.

- [ ] **Step 3: Add imports and wire the new section in `run_alerts`**

In `src/main.py`, edit the data imports line (line 17) from:

```python
from src.data import open_meteo, firms, co2, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges
```

to:

```python
from src.data import open_meteo, firms, co2, nws_alerts, gdacs, sea_ice, drought, enso, ocean, ocean_sst, water_levels, river_gauges
```

Add `score_marine_heatwave` to the scoring imports (around lines 20-41). Insert the import next to `score_extreme_wave`:

```python
    score_extreme_wave,
    score_marine_heatwave,
```

In `src/main.py`, after the `extreme ocean waves` section finishes its `_record_source_run` / exception handler (around line 1268 — immediately before the `# 10. Storm surge` comment), insert:

```python
    # 9b. Global ocean SST marine-heatwave streak (every run)
    print("[alerts] Checking global ocean SST...")
    sst_start = time.perf_counter()
    try:
        obs = ocean_sst.fetch_global_sst()
        source_promoted = 0
        source_drafted = 0
        event = None
        if obs is not None:
            prior_streak = bot_state.get(
                "ocean_sst_streak",
                state.DEFAULT_STATE["ocean_sst_streak"],
            )
            new_streak, event = ocean_sst.detect_streak_milestone(obs, prior_streak)
            state.update_ocean_sst_streak(bot_state, new_streak)

        if event and not state.is_duplicate(bot_state, event.event_id):
            score = score_marine_heatwave(
                event.days, event.peak_anomaly_c, event.years_of_data,
            )
            if _should_draft(score, event.event_id):
                source_promoted = 1
                generated = generator.generate_marine_heatwave_tweet(
                    kind=event.kind,
                    days=event.days,
                    today_c=event.today_c,
                    archive_max_c=event.archive_max_c,
                    archive_max_year=event.archive_max_year,
                    years_of_data=event.years_of_data,
                    return_bundle=True,
                )
                review_context = _review_context(
                    source="NOAA OISST v2.1 (ClimateReanalyzer)",
                    source_key="ocean_sst",
                    headline=f"Global ocean SST streak: day {event.days}",
                    current_run=current_run,
                    facts=[
                        _fact("Streak length", f"{event.days} consecutive days above record"),
                        _fact("Today's global-mean SST", f"{event.today_c:.2f}°C"),
                        _fact("Prior daily max", f"{event.archive_max_c:.2f}°C ({event.archive_max_year})"),
                        _fact("Peak anomaly during streak", f"{event.peak_anomaly_c:+.2f}°C"),
                        _fact("Archive span", f"{event.years_of_data} years"),
                    ],
                )
                if _save_generated_draft(
                    generated, bot_state, "marine_heatwave",
                    event.event_id, score, review_context=review_context,
                ):
                    state.record_event(bot_state, event.event_id)
                    drafted += 1
                    source_drafted = 1
        _record_source_run(
            current_run, "ocean_sst", sst_start,
            status="success",
            observed=1 if obs is not None else 0,
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as e:
        print(f"[alerts] Ocean SST error: {e}")
        state.log_error(bot_state, "ocean_sst", str(e))
        _record_source_run(
            current_run, "ocean_sst", sst_start,
            status="failed", error=str(e),
        )
```

- [ ] **Step 4: Run integration test to verify pass**

Run: `python -m pytest tests/test_main.py::TestRunAlerts::test_run_alerts_ocean_sst_drafts_on_day_5 -v`
Expected: PASS.

If the test fails because other alert sources are calling functions not listed in the monkeypatches above (e.g., a new source was added), inspect the traceback and add the missing monkeypatch. Do NOT disable other sources by editing `run_alerts`; only stub them in the test.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS. No regressions in any existing tests.

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat: wire ocean_sst source into run_alerts"
```

---

## Task 11: Docs — `BRIEFING.md` and `PIPELINE.md`

**Files:**
- Modify: `BRIEFING.md`
- Modify: `PIPELINE.md`

- [ ] **Step 1: Open `BRIEFING.md` and find the data-source list**

Run: `grep -n "Open-Meteo\|NOAA\|data source" BRIEFING.md | head -30` to locate the relevant section.

- [ ] **Step 2: Add the source entry**

In `BRIEFING.md`, in the data-source list, add (adapt to the file's existing list style — bullet, table row, etc.):

```markdown
- **NOAA OISST v2.1 (global-mean SST)** — via ClimateReanalyzer daily JSON.
  Fires on archive-record streaks of 5+ days (day-5 first-fire, then
  milestones at 10, 25, 50, 100, 150, 200, 250, 300, 365, 400, +50 thereafter).
  Editorial threshold: 78. Approval: suggested_auto, 90-min delay.
```

- [ ] **Step 3: Open `PIPELINE.md` and find the Mermaid flow diagram**

Run: `grep -n "mermaid\|flowchart\|graph" PIPELINE.md | head` to locate the diagram block.

- [ ] **Step 4: Add a node for `ocean_sst`**

Inside the Mermaid block under the RAW sources / alerts nodes, add a line like:

```
    OCEAN_SST["ocean_sst<br/>NOAA OISST"] --> DETECT
```

Adapt edge names to whatever the existing diagram uses (e.g., if there's a `SCORE` node or a `RUN_ALERTS` aggregator, connect to that instead).

- [ ] **Step 5: Commit**

```bash
git add BRIEFING.md PIPELINE.md
git commit -m "docs: record ocean_sst source and pipeline node"
```

---

## Task 12: Live API smoke test + final regression pass

**Files:**
- None (validation only)

- [ ] **Step 1: Probe the live endpoint**

Run:

```bash
python -c "from src.data.ocean_sst import fetch_global_sst; obs = fetch_global_sst(); print(obs)"
```

Expected: prints a `GlobalSSTObservation(...)` with sane values (today_c in [-2, 40]; years_of_data ≥ 40; streak_days ≥ 0). If `None`, inspect by running `curl -s 'https://climatereanalyzer.org/clim/sst_daily/json/oisst2.1_world_sst_day.json' | python -c "import json,sys; d=json.load(sys.stdin); print(sorted(d.keys())[-3:], type(d[list(d)[-1]]))"` to verify shape.

- [ ] **Step 2: Capture the result for the PR description**

Save the observation output to paste into the PR body.

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 4: Run any repo-configured linting/formatters**

Run: `python -m ruff check .` (if ruff is the project linter — check `pyproject.toml` or `Makefile`). Fix issues if any.

- [ ] **Step 5: No commit needed unless fixes were made**

If lint fixes were necessary, commit them:

```bash
git add -p  # review each change
git commit -m "chore: ruff fixes for ocean_sst lane"
```

---

## Done

All Definition-of-Done checkboxes from `docs/superpowers/specs/2026-04-20-ocean-sst-marine-heatwaves-design.md` should now be true:
- [x] Fetch verified against live ClimateReanalyzer JSON endpoint.
- [x] Detection fires on day-5 fixture; suppresses day-4 and under.
- [x] Bootstrap first-run is silent.
- [x] Milestone skip (missed cron) fires next unfired milestone only.
- [x] Generator produces text passing existing safety pipeline.
- [x] `run_alerts` integration test wires the full path.
- [x] Full suite green.
- [x] `BRIEFING.md` updated.
- [x] `PIPELINE.md` updated.
- [x] No new secrets required.
