# Lane 2 — Ice Mass (GRACE-FO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Greenland + Antarctica GRACE-FO ice-mass-loss lane to the alerts pipeline with two detectors (monthly-loss record, cumulative-loss milestone), scoring, voice, approval policy, orchestrator integration, and tests.

**Architecture:** A new `src/data/ice_mass.py` module parses PODAAC Level-4 mascon ASCII time series (one per region) via Earthdata bearer-token auth. Two detectors consume the readings and the bot's durable state; records are scored, drafted through the existing Gemini generator + fallback template, gated by an 8/year cap, and queued under a `suggested_auto` policy. The orchestrator runs the lane once per week (Mondays) with a per-region short-circuit so each published month is processed exactly once.

**Tech Stack:** Python 3.11+, `requests`, `responses` (HTTP mocking), `pytest`, the existing Gemini client in `src/voice/generator.py`.

---

## Spec

The governing spec is `docs/superpowers/specs/2026-04-20-ice-mass-grace-design.md`. Read that first — this plan implements it.

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/data/ice_mass.py` | Fetcher, parsing, `IceMassReading` / `IceMassRecord`, `detect_monthly_record`, `detect_cumulative_milestone` |
| Modify | `src/state.py` | Add 4 default-state keys + 4 merge rules |
| Modify | `src/editorial/scoring.py` | `score_ice_mass_event` |
| Modify | `src/voice/templates.py` | `ice_mass_template` fallback |
| Modify | `src/voice/generator.py` | `generate_ice_mass_tweet` |
| Modify | `src/editorial/candidates.py` | One entry in `CATEGORY_HINTS` |
| Modify | `src/editorial/approval.py` | `ice_mass_record` policy branch |
| Modify | `src/main.py` | `ICE_ANNUAL_CAP`, `_ice_annual_cap_reached`, `_increment_ice_annual_count`, new `run_alerts` section, import update |
| Create | `tests/test_ice_mass.py` | Fetch + detection + short-circuit tests |
| Modify | `tests/test_editorial_scoring.py` | `score_ice_mass_event` cases |
| Modify | `tests/test_editorial_approval.py` | `ice_mass_record` policy case |
| Modify | `tests/test_generator.py` | `generate_ice_mass_tweet` fallback case |
| Modify | `tests/test_state.py` | `_merge_state` cases for new keys |
| Modify | `tests/test_main.py` | `run_alerts` Monday + skip integration cases |
| Modify | `BRIEFING.md` | Document `EARTHDATA_TOKEN` + Lane 2 |
| Modify | `PIPELINE.md` | Mention ice_mass lane in weekly section |

Each task is self-contained and commits after the test is green.

---

## Task 1: Data module scaffold (`src/data/ice_mass.py`)

**Files:**
- Create: `src/data/ice_mass.py`
- Create: `tests/test_ice_mass.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ice_mass.py` with:

```python
"""Tests for NASA GRACE-FO ice mass data."""

from src.data.ice_mass import (
    IceMassReading,
    IceMassRecord,
    fetch_grace_mass,
    detect_monthly_record,
    detect_cumulative_milestone,
)


class TestModuleSurface:
    def test_ice_mass_reading_dataclass(self):
        r = IceMassReading(
            region="greenland",
            month="2026-03",
            mass_gt=-5432.1,
            uncertainty_gt=120.0,
            event_id="ice_mass_greenland_2026-03",
        )
        assert r.region == "greenland"
        assert r.month == "2026-03"
        assert r.mass_gt == -5432.1
        assert r.uncertainty_gt == 120.0
        assert r.event_id == "ice_mass_greenland_2026-03"

    def test_ice_mass_record_dataclass(self):
        rec = IceMassRecord(
            region="greenland",
            kind="monthly_loss_record",
            month="2026-08",
            monthly_delta_gt=-423.0,
            previous_worst_gt=-350.0,
            previous_worst_month="2019-07",
            threshold_gt=None,
            current_mass_gt=None,
            event_id="ice_mass_record_greenland_monthly_2026-08",
        )
        assert rec.kind == "monthly_loss_record"
        assert rec.monthly_delta_gt == -423.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ice_mass.py -v`
Expected: FAIL with `ImportError: cannot import name 'IceMassReading' from 'src.data.ice_mass'` (or module not found).

- [ ] **Step 3: Create the module with dataclasses and stubs**

Create `src/data/ice_mass.py`:

```python
"""NASA GRACE-FO ice mass anomaly — Greenland + Antarctica.

Level-4 mascon time series from JPL, served via PO.DAAC. Monthly cadence
with a 1-2 month publication lag. Requires Earthdata Login — set
`EARTHDATA_TOKEN` to a user-generated app token from
https://urs.earthdata.nasa.gov/.

Records start 2002.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os

import requests

# Pinned product URLs. Update constants when the product version bumps.
GREENLAND_URL = (
    "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
    "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt"
)
ANTARCTICA_URL = (
    "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
    "RL06.3v03/mascon_CRI/ANT-ICE-MASS-anomaly-time-series.txt"
)

REGION_URLS = {"greenland": GREENLAND_URL, "antarctica": ANTARCTICA_URL}

GRACE_START_YEAR = 2002
MILESTONE_STEP_GT = 1000.0


@dataclass
class IceMassReading:
    region: str
    month: str             # "YYYY-MM"
    mass_gt: float         # mass anomaly vs mission baseline (negative = below)
    uncertainty_gt: float
    event_id: str


@dataclass
class IceMassRecord:
    region: str
    kind: str              # "monthly_loss_record" | "cumulative_milestone"
    month: str | None
    monthly_delta_gt: float | None
    previous_worst_gt: float | None
    previous_worst_month: str | None
    threshold_gt: float | None
    current_mass_gt: float | None
    event_id: str


def fetch_grace_mass(region: str) -> list[IceMassReading]:
    raise NotImplementedError


def detect_monthly_record(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    raise NotImplementedError


def detect_cumulative_milestone(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ice_mass.py -v`
Expected: PASS (2 cases).

- [ ] **Step 5: Commit**

```bash
git add src/data/ice_mass.py tests/test_ice_mass.py
git commit -m "Add ice_mass module scaffold with IceMassReading/IceMassRecord"
```

---

## Task 2: Decimal-year → YYYY-MM helper + constants

**Files:**
- Modify: `src/data/ice_mass.py`
- Modify: `tests/test_ice_mass.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ice_mass.py`:

```python
from src.data.ice_mass import _decimal_year_to_month


class TestDecimalYearToMonth:
    def test_january(self):
        assert _decimal_year_to_month(2026.04) == "2026-01"

    def test_august(self):
        # Aug = month index 7 (0-based). (7 + 0.5) / 12 ≈ 0.625
        assert _decimal_year_to_month(2026.625) == "2026-08"

    def test_december(self):
        assert _decimal_year_to_month(2026.96) == "2026-12"

    def test_exact_year_boundary(self):
        assert _decimal_year_to_month(2002.0) == "2002-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestDecimalYearToMonth -v`
Expected: FAIL with `ImportError` on `_decimal_year_to_month`.

- [ ] **Step 3: Implement the helper**

In `src/data/ice_mass.py`, after constants and before dataclasses:

```python
def _decimal_year_to_month(decimal_year: float) -> str:
    """Convert a decimal-year timestamp (e.g. 2026.625) to YYYY-MM.

    GRACE time series express time as decimal year; the integer part is
    the year and the fractional part is the position within the year.
    We bucket to month using 12 equal slots.
    """
    year = int(math.floor(decimal_year))
    frac = decimal_year - year
    month_idx = int(frac * 12)
    if month_idx < 0:
        month_idx = 0
    if month_idx > 11:
        month_idx = 11
    return f"{year}-{month_idx + 1:02d}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestDecimalYearToMonth -v`
Expected: PASS (4 cases).

- [ ] **Step 5: Commit**

```bash
git add src/data/ice_mass.py tests/test_ice_mass.py
git commit -m "Add decimal-year to YYYY-MM helper for ice_mass"
```

---

## Task 3: `fetch_grace_mass` — happy path with bearer token

**Files:**
- Modify: `src/data/ice_mass.py`
- Modify: `tests/test_ice_mass.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ice_mass.py`:

```python
from unittest.mock import patch
import responses


SAMPLE_GREENLAND = """HDR
HDR columns: time_decimal_year mass_gt uncertainty_gt
HDR
2002.0417   0.0    80.0
2019.541   -3200.0 100.0
2019.625   -3623.0 100.0
2026.208   -5400.0 120.0
2026.292   -5500.0 120.0
"""


class TestFetchGraceMass:
    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_happy_path_greenland(self, _env):
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            body=SAMPLE_GREENLAND,
            status=200,
        )
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 5
        assert all(isinstance(r, IceMassReading) for r in readings)
        assert readings[0].region == "greenland"
        assert readings[0].month == "2002-01"
        assert readings[0].mass_gt == 0.0
        assert readings[-1].month == "2026-04"
        assert readings[-1].mass_gt == -5500.0
        assert readings[-1].event_id == "ice_mass_greenland_2026-04"
        # Auth header must be set
        assert responses.calls[0].request.headers["Authorization"] == "Bearer fake-token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestFetchGraceMass::test_happy_path_greenland -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `fetch_grace_mass`**

Replace the `fetch_grace_mass` stub in `src/data/ice_mass.py`:

```python
def fetch_grace_mass(region: str) -> list[IceMassReading]:
    """Fetch the PODAAC Level-4 mass anomaly time series for a region.

    Returns readings sorted oldest → newest. Returns [] on any failure
    (missing token, HTTP error, parse error) so callers can treat the
    lane as skipped rather than crashing.
    """
    if region not in REGION_URLS:
        return []

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        print("[ice_mass] EARTHDATA_TOKEN not configured — skipping")
        return []

    try:
        resp = requests.get(
            REGION_URLS[region],
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ice_mass] {region} fetch error: {e}")
        return []

    readings: list[IceMassReading] = []
    for line in resp.text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("HDR") or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        try:
            decimal_year = float(parts[0])
            mass_gt = float(parts[1])
            uncertainty_gt = float(parts[2])
        except ValueError:
            continue
        month = _decimal_year_to_month(decimal_year)
        readings.append(IceMassReading(
            region=region,
            month=month,
            mass_gt=mass_gt,
            uncertainty_gt=uncertainty_gt,
            event_id=f"ice_mass_{region}_{month}",
        ))
    readings.sort(key=lambda r: r.month)
    return readings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestFetchGraceMass -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data/ice_mass.py tests/test_ice_mass.py
git commit -m "Implement fetch_grace_mass happy path with Earthdata bearer auth"
```

---

## Task 4: `fetch_grace_mass` — error paths

**Files:**
- Modify: `tests/test_ice_mass.py`

- [ ] **Step 1: Write the failing tests**

Append to `TestFetchGraceMass` in `tests/test_ice_mass.py`:

```python
    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_http_error_returns_empty(self, _env):
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            status=500,
        )
        assert fetch_grace_mass(region="greenland") == []

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_unauthorized_returns_empty(self, _env):
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            status=401,
        )
        assert fetch_grace_mass(region="greenland") == []

    @patch("src.data.ice_mass.os.environ.get", return_value="")
    def test_missing_token_returns_empty(self, _env):
        # No responses mock needed — must short-circuit before any HTTP call.
        assert fetch_grace_mass(region="greenland") == []

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_malformed_rows_skipped(self, _env):
        body = (
            "HDR columns: time mass unc\n"
            "2019.541   -3200.0   100.0\n"
            "not a number    bad    data\n"
            "2026.292   -5500.0   120.0\n"
        )
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            body=body,
            status=200,
        )
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 2
        assert readings[0].month == "2019-07"
        assert readings[-1].month == "2026-04"

    def test_unknown_region_returns_empty(self):
        assert fetch_grace_mass(region="mars") == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestFetchGraceMass -v`
Expected: PASS (5 new cases; implementation already handles all of them).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ice_mass.py
git commit -m "Cover ice_mass fetch error paths: HTTP, 401, missing token, bad rows, unknown region"
```

---

## Task 5: `detect_monthly_record`

**Files:**
- Modify: `src/data/ice_mass.py`
- Modify: `tests/test_ice_mass.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ice_mass.py`:

```python
def _reading(region: str, month: str, mass_gt: float) -> IceMassReading:
    return IceMassReading(
        region=region,
        month=month,
        mass_gt=mass_gt,
        uncertainty_gt=100.0,
        event_id=f"ice_mass_{region}_{month}",
    )


class TestDetectMonthlyRecord:
    def test_fires_new_record(self):
        readings = [
            _reading("greenland", "2024-07", -3200.0),
            _reading("greenland", "2024-08", -3550.0),   # delta -350 (old record)
            _reading("greenland", "2026-07", -5000.0),
            _reading("greenland", "2026-08", -5423.0),   # delta -423 → new record
        ]
        state = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -350.0, "month": "2024-08"},
            }
        }
        rec = detect_monthly_record(readings, state)
        assert rec is not None
        assert rec.kind == "monthly_loss_record"
        assert rec.region == "greenland"
        assert rec.month == "2026-08"
        assert rec.monthly_delta_gt == -423.0
        assert rec.previous_worst_gt == -350.0
        assert rec.previous_worst_month == "2024-08"
        assert rec.event_id == "ice_mass_record_greenland_monthly_2026-08"

    def test_no_fire_when_not_record(self):
        readings = [
            _reading("greenland", "2024-08", -3550.0),
            _reading("greenland", "2026-08", -5200.0),   # delta -200, weaker than stored -350
        ]
        # Seed prior reading for the delta calc:
        readings.insert(1, _reading("greenland", "2026-07", -5000.0))
        state = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -350.0, "month": "2024-08"},
            }
        }
        assert detect_monthly_record(readings, state) is None

    def test_seeds_state_on_first_run(self):
        # No prior record in state; first positive loss seeds the floor.
        readings = [
            _reading("greenland", "2026-07", -5000.0),
            _reading("greenland", "2026-08", -5423.0),
        ]
        state = {"ice_mass_max_loss": {}}
        rec = detect_monthly_record(readings, state)
        assert rec is not None
        assert rec.previous_worst_gt is None
        assert rec.previous_worst_month is None
        assert rec.monthly_delta_gt == -423.0

    def test_single_reading_returns_none(self):
        readings = [_reading("greenland", "2026-08", -5423.0)]
        assert detect_monthly_record(readings, {"ice_mass_max_loss": {}}) is None

    def test_positive_delta_no_fire(self):
        # Month-over-month gain (unusual but possible) must never fire.
        readings = [
            _reading("greenland", "2026-03", -5500.0),
            _reading("greenland", "2026-04", -5400.0),  # +100 gain
        ]
        state = {"ice_mass_max_loss": {}}
        assert detect_monthly_record(readings, state) is None

    def test_empty_readings_returns_none(self):
        assert detect_monthly_record([], {"ice_mass_max_loss": {}}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestDetectMonthlyRecord -v`
Expected: FAIL (NotImplementedError).

- [ ] **Step 3: Implement `detect_monthly_record`**

Replace the stub in `src/data/ice_mass.py`:

```python
def detect_monthly_record(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    """Fire when the latest month-over-month mass delta beats the stored record.

    - `state["ice_mass_max_loss"][region]` holds the worst (most-negative)
      month-over-month delta we've ever seen, keyed by region.
    - On the first run for a region the entry is absent; we still fire
      (the first observed loss is, by definition, a record) but report
      `previous_worst_gt=None` so the template can say "first on record".
    """
    if len(readings) < 2:
        return None

    latest = readings[-1]
    prior = readings[-2]
    region = latest.region
    delta = latest.mass_gt - prior.mass_gt
    if delta >= 0:
        return None  # net gain or unchanged — never a loss record

    stored = state.get("ice_mass_max_loss", {}).get(region)
    prev_gt = stored.get("gt") if isinstance(stored, dict) else None
    prev_month = stored.get("month") if isinstance(stored, dict) else None

    is_record = prev_gt is None or delta < prev_gt
    if not is_record:
        return None

    return IceMassRecord(
        region=region,
        kind="monthly_loss_record",
        month=latest.month,
        monthly_delta_gt=delta,
        previous_worst_gt=prev_gt,
        previous_worst_month=prev_month,
        threshold_gt=None,
        current_mass_gt=None,
        event_id=f"ice_mass_record_{region}_monthly_{latest.month}",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestDetectMonthlyRecord -v`
Expected: PASS (6 cases).

- [ ] **Step 5: Commit**

```bash
git add src/data/ice_mass.py tests/test_ice_mass.py
git commit -m "Implement detect_monthly_record for ice_mass"
```

---

## Task 6: `detect_cumulative_milestone`

**Files:**
- Modify: `src/data/ice_mass.py`
- Modify: `tests/test_ice_mass.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ice_mass.py`:

```python
class TestDetectCumulativeMilestone:
    def test_fires_on_first_crossing(self):
        readings = [
            _reading("greenland", "2026-03", -4900.0),
            _reading("greenland", "2026-04", -5050.0),   # crosses -5000
        ]
        state = {"ice_mass_last_milestone": {}}
        rec = detect_cumulative_milestone(readings, state)
        assert rec is not None
        assert rec.kind == "cumulative_milestone"
        assert rec.threshold_gt == -5000.0
        assert rec.current_mass_gt == -5050.0
        assert rec.event_id == "ice_mass_record_greenland_cumulative_-5000"

    def test_no_refire_once_fired(self):
        readings = [_reading("greenland", "2026-04", -5100.0)]
        state = {"ice_mass_last_milestone": {"greenland": -5000.0}}
        assert detect_cumulative_milestone(readings, state) is None

    def test_subsequent_milestone_fires(self):
        readings = [_reading("greenland", "2028-07", -6042.0)]
        state = {"ice_mass_last_milestone": {"greenland": -5000.0}}
        rec = detect_cumulative_milestone(readings, state)
        assert rec is not None
        assert rec.threshold_gt == -6000.0
        assert rec.current_mass_gt == -6042.0

    def test_no_fire_if_not_yet_crossed(self):
        readings = [_reading("greenland", "2026-04", -4850.0)]
        state = {"ice_mass_last_milestone": {}}
        assert detect_cumulative_milestone(readings, state) is None

    def test_empty_readings_returns_none(self):
        assert detect_cumulative_milestone([], {"ice_mass_last_milestone": {}}) is None

    def test_positive_mass_no_fire(self):
        # At mission start mass is near the baseline (≈0). No negative
        # threshold to report.
        readings = [_reading("greenland", "2002-04", 12.0)]
        state = {"ice_mass_last_milestone": {}}
        assert detect_cumulative_milestone(readings, state) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ice_mass.py::TestDetectCumulativeMilestone -v`
Expected: FAIL (NotImplementedError).

- [ ] **Step 3: Implement `detect_cumulative_milestone`**

Replace the stub in `src/data/ice_mass.py`:

```python
def detect_cumulative_milestone(
    readings: list[IceMassReading], state: dict
) -> IceMassRecord | None:
    """Fire when the latest cumulative mass anomaly crosses the next
    MILESTONE_STEP_GT floor (e.g. -5000, -6000, …) beyond the last fired
    threshold for that region.

    Stores `state["ice_mass_last_milestone"][region]` as the last fired
    threshold (negative number). Absent entry means no milestone ever
    fired for this region.
    """
    if not readings:
        return None

    latest = readings[-1]
    region = latest.region
    if latest.mass_gt >= 0:
        return None

    last_fired = state.get("ice_mass_last_milestone", {}).get(region)
    # Next threshold floor: the largest multiple of MILESTONE_STEP_GT that is
    # more negative than the last fired threshold (or -1000 if never fired).
    if last_fired is None:
        next_threshold = -MILESTONE_STEP_GT
    else:
        next_threshold = last_fired - MILESTONE_STEP_GT

    if latest.mass_gt > next_threshold:
        # Still above the next floor — no crossing yet.
        return None

    # The floor we crossed is the largest step that contains `latest.mass_gt`.
    crossed = math.floor(latest.mass_gt / MILESTONE_STEP_GT) * MILESTONE_STEP_GT
    # Never report above the last_fired floor.
    if last_fired is not None and crossed >= last_fired:
        return None

    return IceMassRecord(
        region=region,
        kind="cumulative_milestone",
        month=latest.month,
        monthly_delta_gt=None,
        previous_worst_gt=None,
        previous_worst_month=None,
        threshold_gt=float(crossed),
        current_mass_gt=latest.mass_gt,
        event_id=f"ice_mass_record_{region}_cumulative_{int(crossed)}",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ice_mass.py -v`
Expected: PASS (all cases so far — monthly + cumulative).

- [ ] **Step 5: Commit**

```bash
git add src/data/ice_mass.py tests/test_ice_mass.py
git commit -m "Implement detect_cumulative_milestone for ice_mass"
```

---

## Task 7: State additions — DEFAULT_STATE keys

**Files:**
- Modify: `src/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_state.py` and append:

```python
class TestIceMassDefaultState:
    def test_ice_mass_keys_in_default_state(self):
        from src.state import _fresh_state
        s = _fresh_state()
        assert s["ice_mass_max_loss"] == {}
        assert s["ice_mass_last_milestone"] == {}
        assert s["ice_mass_last_seen"] == {}
        assert s["ice_annual_count"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_state.py::TestIceMassDefaultState -v`
Expected: FAIL — `KeyError: 'ice_mass_max_loss'`.

- [ ] **Step 3: Add keys to `DEFAULT_STATE`**

In `src/state.py`, add to `DEFAULT_STATE` (after `"record_streaks": {}` on line 38, inside the closing `}` on line 39):

```python
    # GRACE-FO ice mass loss (Lane 2). See docs/conductor-lanes/02-ice-events.md.
    # Worst single-month mass-delta per region. `gt` is month-over-month
    # change in gigatons (negative = loss). More-negative = new record.
    "ice_mass_max_loss": {},  # {region: {"gt": float, "month": "YYYY-MM"}}
    # Last fired cumulative-loss milestone per region (negative threshold).
    # Next milestone fires at this value minus MILESTONE_STEP_GT.
    "ice_mass_last_milestone": {},  # {region: float}
    # Latest month we've successfully processed per region. Prevents re-eval
    # of the same month within a publication cycle.
    "ice_mass_last_seen": {},  # {region: "YYYY-MM"}
    # Running count of ice_mass tweets per calendar year (cap: 8/year).
    "ice_annual_count": {},  # {year_str: int}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_state.py::TestIceMassDefaultState -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "Add ice_mass state keys to DEFAULT_STATE"
```

---

## Task 8: State merge rules for ice_mass

**Files:**
- Modify: `src/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
class TestIceMassMerge:
    def test_max_loss_keeps_most_negative_per_region(self):
        from src.state import _merge_state
        base = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -400.0, "month": "2024-08"},
                "antarctica": {"gt": -200.0, "month": "2020-01"},
            }
        }
        incoming = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -350.0, "month": "2025-08"},  # weaker
                "antarctica": {"gt": -250.0, "month": "2026-01"}, # stronger
            }
        }
        merged = _merge_state(base, incoming)
        assert merged["ice_mass_max_loss"]["greenland"] == {"gt": -400.0, "month": "2024-08"}
        assert merged["ice_mass_max_loss"]["antarctica"] == {"gt": -250.0, "month": "2026-01"}

    def test_last_milestone_keeps_most_negative_per_region(self):
        from src.state import _merge_state
        base = {"ice_mass_last_milestone": {"greenland": -5000.0, "antarctica": -2000.0}}
        incoming = {"ice_mass_last_milestone": {"greenland": -6000.0, "antarctica": -1000.0}}
        merged = _merge_state(base, incoming)
        assert merged["ice_mass_last_milestone"]["greenland"] == -6000.0
        assert merged["ice_mass_last_milestone"]["antarctica"] == -2000.0

    def test_last_seen_takes_lexicographic_max_per_region(self):
        from src.state import _merge_state
        base = {"ice_mass_last_seen": {"greenland": "2026-02", "antarctica": "2026-04"}}
        incoming = {"ice_mass_last_seen": {"greenland": "2026-03", "antarctica": "2026-01"}}
        merged = _merge_state(base, incoming)
        assert merged["ice_mass_last_seen"]["greenland"] == "2026-03"
        assert merged["ice_mass_last_seen"]["antarctica"] == "2026-04"

    def test_ice_annual_count_takes_max_per_year(self):
        from src.state import _merge_state
        base = {"ice_annual_count": {"2026": 3, "2025": 7}}
        incoming = {"ice_annual_count": {"2026": 5, "2024": 2}}
        merged = _merge_state(base, incoming)
        assert merged["ice_annual_count"]["2026"] == 5
        assert merged["ice_annual_count"]["2025"] == 7
        assert merged["ice_annual_count"]["2024"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_state.py::TestIceMassMerge -v`
Expected: FAIL — merged dicts are empty because `_merge_state` doesn't know the keys yet.

- [ ] **Step 3: Extend `_merge_state`**

In `src/state.py`, inside `_merge_state` (after the `record_streaks` line at `merged["record_streaks"] = deepcopy(...)`), append:

```python
    # ice_mass: per-region keep the extreme to survive concurrent writers.
    merged["ice_mass_max_loss"] = {}
    for region in set(
        list(base.get("ice_mass_max_loss", {}).keys())
        + list(next_state.get("ice_mass_max_loss", {}).keys())
    ):
        a = base.get("ice_mass_max_loss", {}).get(region)
        b = next_state.get("ice_mass_max_loss", {}).get(region)
        if a is None:
            merged["ice_mass_max_loss"][region] = deepcopy(b)
        elif b is None:
            merged["ice_mass_max_loss"][region] = deepcopy(a)
        else:
            merged["ice_mass_max_loss"][region] = deepcopy(
                a if a.get("gt", 0.0) <= b.get("gt", 0.0) else b
            )
    merged["ice_mass_last_milestone"] = {}
    for region in set(
        list(base.get("ice_mass_last_milestone", {}).keys())
        + list(next_state.get("ice_mass_last_milestone", {}).keys())
    ):
        a = base.get("ice_mass_last_milestone", {}).get(region)
        b = next_state.get("ice_mass_last_milestone", {}).get(region)
        if a is None:
            merged["ice_mass_last_milestone"][region] = b
        elif b is None:
            merged["ice_mass_last_milestone"][region] = a
        else:
            merged["ice_mass_last_milestone"][region] = min(a, b)
    merged["ice_mass_last_seen"] = {}
    for region in set(
        list(base.get("ice_mass_last_seen", {}).keys())
        + list(next_state.get("ice_mass_last_seen", {}).keys())
    ):
        a = base.get("ice_mass_last_seen", {}).get(region, "")
        b = next_state.get("ice_mass_last_seen", {}).get(region, "")
        merged["ice_mass_last_seen"][region] = a if a >= b else b
    merged["ice_annual_count"] = {}
    for year in set(
        list(base.get("ice_annual_count", {}).keys())
        + list(next_state.get("ice_annual_count", {}).keys())
    ):
        merged["ice_annual_count"][year] = max(
            base.get("ice_annual_count", {}).get(year, 0),
            next_state.get("ice_annual_count", {}).get(year, 0),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: PASS (all existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "Add merge rules for ice_mass state keys (preserve extremes under concurrent writes)"
```

---

## Task 9: Scoring — `score_ice_mass_event`

**Files:**
- Modify: `src/editorial/scoring.py`
- Modify: `tests/test_editorial_scoring.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_editorial_scoring.py`:

```python
class TestScoreIceMassEvent:
    def test_monthly_record_passes_threshold(self):
        from src.editorial.scoring import score_ice_mass_event
        score = score_ice_mass_event(
            region="greenland",
            kind="monthly_loss_record",
            monthly_delta_gt=-423.0,
            previous_worst_gt=-350.0,
        )
        assert score.category == "ice_mass_record"
        assert score.threshold == 78
        assert score.passes is True
        assert score.confidence >= 95
        assert score.sensitivity <= 10
        assert any("GRACE" in r for r in score.reasons)

    def test_cumulative_milestone_passes_threshold(self):
        from src.editorial.scoring import score_ice_mass_event
        score = score_ice_mass_event(
            region="greenland",
            kind="cumulative_milestone",
            threshold_gt=-6000.0,
        )
        assert score.category == "ice_mass_record"
        assert score.threshold == 78
        assert score.passes is True
        assert any("6000" in r or "cumulative" in r.lower() for r in score.reasons)

    def test_tiny_monthly_margin_still_passes_by_design(self):
        # Even a modest monthly record crosses 78 — rarity + confidence + novelty
        # carry the total. The editorial cap is what limits volume, not this floor.
        from src.editorial.scoring import score_ice_mass_event
        score = score_ice_mass_event(
            region="antarctica",
            kind="monthly_loss_record",
            monthly_delta_gt=-120.0,
            previous_worst_gt=-115.0,
        )
        assert score.passes is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_editorial_scoring.py::TestScoreIceMassEvent -v`
Expected: FAIL — `ImportError: cannot import name 'score_ice_mass_event'`.

- [ ] **Step 3: Implement `score_ice_mass_event`**

Append to `src/editorial/scoring.py` (after `score_sea_ice_record`, before `score_drought`):

```python
def score_ice_mass_event(
    region: str,
    kind: str,
    *,
    monthly_delta_gt: float | None = None,
    previous_worst_gt: float | None = None,
    threshold_gt: float | None = None,
) -> EditorialScore:
    """Score a GRACE-FO ice-mass-loss event.

    Two kinds share one category + threshold:
    - "monthly_loss_record": new largest single-month loss in the record.
    - "cumulative_milestone": cumulative anomaly crosses next -1000 Gt floor.
    """
    if kind == "monthly_loss_record":
        loss = abs(monthly_delta_gt or 0.0)
        severity = max(60, 72 + (loss - 300.0) * 0.15)
        margin = 0.0
        if previous_worst_gt is not None and monthly_delta_gt is not None:
            margin = max(abs(monthly_delta_gt) - abs(previous_worst_gt), 0.0)
        shareability = 78 + margin * 0.1
        reasons = [
            "largest monthly loss in GRACE record",
            (
                f"previous worst: {abs(previous_worst_gt):.0f} Gt"
                if previous_worst_gt is not None
                else "first monthly record observed"
            ),
            "GRACE-FO gravimetry",
        ]
        return _build_score(
            "ice_mass_record",
            severity=severity,
            novelty=90,
            timeliness=64,
            confidence=96,
            shareability=shareability,
            sensitivity=8,
            threshold=78,
            reasons=reasons,
        )

    # cumulative_milestone
    threshold_abs = abs(threshold_gt or 0.0)
    severity = 76 + threshold_abs / 1000.0 * 2.0
    reasons = [
        f"cumulative loss crosses {threshold_abs:.0f} Gt",
        f"region: {region}",
        "GRACE-FO gravimetry",
    ]
    return _build_score(
        "ice_mass_record",
        severity=severity,
        novelty=82,
        timeliness=60,
        confidence=96,
        shareability=84,
        sensitivity=8,
        threshold=78,
        reasons=reasons,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_editorial_scoring.py::TestScoreIceMassEvent -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/scoring.py tests/test_editorial_scoring.py
git commit -m "Add score_ice_mass_event for monthly records and cumulative milestones"
```

---

## Task 10: Template — `ice_mass_template`

**Files:**
- Modify: `src/voice/templates.py`

- [ ] **Step 1: Write the template**

Append to `src/voice/templates.py`:

```python
def _month_label(month: str) -> str:
    """Render YYYY-MM as 'Month YYYY'."""
    try:
        year_str, mon_str = month.split("-")
        mon_idx = int(mon_str)
        names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        return f"{names[mon_idx - 1]} {year_str}"
    except (ValueError, IndexError):
        return month


def ice_mass_template(
    region: str,
    kind: str,
    *,
    month: str | None = None,
    monthly_delta_gt: float | None = None,
    years_of_record: int | None = None,
    threshold_gt: float | None = None,
) -> str:
    region_name = {"greenland": "Greenland", "antarctica": "Antarctica"}.get(
        region, region.title()
    )
    if kind == "monthly_loss_record":
        loss = abs(monthly_delta_gt or 0.0)
        month_name = _month_label(month or "")
        yrs = years_of_record or 0
        variants = [
            f"{region_name} lost {loss:.0f} gigatons in {month_name}. The largest monthly loss in {yrs} years of GRACE observations.",
            f"{region_name}: {loss:.0f} Gt of ice gone in {month_name} alone. That's the worst single-month loss in the {yrs}-year GRACE record.",
        ]
        return random.choice(variants)
    # cumulative_milestone
    threshold_abs = abs(int(threshold_gt or 0))
    variants = [
        f"{region_name} has now lost more than {threshold_abs:,} gigatons of ice since 2002, per GRACE. A threshold first crossed this month.",
        f"Cumulative ice loss from {region_name} passes {threshold_abs:,} Gt. GRACE has been watching since 2002.",
    ]
    return random.choice(variants)
```

- [ ] **Step 2: Smoke-test manually**

Run: `.venv/bin/python -c "from src.voice.templates import ice_mass_template; print(ice_mass_template('greenland', 'monthly_loss_record', month='2026-08', monthly_delta_gt=-423.0, years_of_record=24)); print(ice_mass_template('antarctica', 'cumulative_milestone', threshold_gt=-3000.0))"`

Expected: two lines printed matching one of the variants each.

- [ ] **Step 3: Commit**

```bash
git add src/voice/templates.py
git commit -m "Add ice_mass_template fallback for GRACE records"
```

---

## Task 11: Category hint

**Files:**
- Modify: `src/editorial/candidates.py`

- [ ] **Step 1: Add hint**

In `src/editorial/candidates.py`, update the `CATEGORY_HINTS` dict (lines 20-36). Add this line before the closing `}`, preserving existing entries:

```python
    "ice_mass_record": ("GRACE", "gigatons", "ice"),
```

Final dict block reads (only the last two entries shown for clarity — preserve everything above):

```python
    "hot10": ("today", "anomaly", "normal"),
    "ice_mass_record": ("GRACE", "gigatons", "ice"),
}
```

- [ ] **Step 2: Verify test suite still green**

Run: `.venv/bin/pytest tests/test_editorial_candidates.py -v`
Expected: PASS (unchanged).

- [ ] **Step 3: Commit**

```bash
git add src/editorial/candidates.py
git commit -m "Register ice_mass_record category hint"
```

---

## Task 12: Generator — `generate_ice_mass_tweet`

**Files:**
- Modify: `src/voice/generator.py`
- Modify: `tests/test_generator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generator.py`:

```python
class TestGenerateIceMassTweet:
    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_monthly_record_falls_back_to_template(self):
        from src.voice.generator import generate_ice_mass_tweet
        result = generate_ice_mass_tweet(
            region="greenland",
            kind="monthly_loss_record",
            month="2026-08",
            monthly_delta_gt=-423.0,
            previous_worst_gt=-350.0,
            previous_worst_month="2019-07",
            years_of_record=24,
        )
        assert result is not None
        assert "Greenland" in result
        assert "423" in result
        assert "GRACE" in result

    @patch("src.voice.generator.GEMINI_API_KEY", "")
    def test_cumulative_milestone_falls_back_to_template(self):
        from src.voice.generator import generate_ice_mass_tweet
        result = generate_ice_mass_tweet(
            region="antarctica",
            kind="cumulative_milestone",
            threshold_gt=-3000.0,
            current_mass_gt=-3042.0,
            years_of_record=24,
        )
        assert result is not None
        assert "Antarctica" in result
        assert "3,000" in result or "3000" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_generator.py::TestGenerateIceMassTweet -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `generate_ice_mass_tweet`**

In `src/voice/generator.py`, add after `generate_sea_ice_record_tweet` (so around line 720). The exact insertion point is: immediately after the closing `)` of `generate_sea_ice_record_tweet` and the blank line that follows it, before `def generate_drought_tweet(`.

```python
def generate_ice_mass_tweet(
    region: str,
    kind: str,
    *,
    month: str | None = None,
    monthly_delta_gt: float | None = None,
    previous_worst_gt: float | None = None,
    previous_worst_month: str | None = None,
    threshold_gt: float | None = None,
    current_mass_gt: float | None = None,
    years_of_record: int | None = None,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a GRACE-FO ice-mass event.

    `kind` is one of "monthly_loss_record" or "cumulative_milestone".
    """
    region_name = {"greenland": "Greenland", "antarctica": "Antarctica"}.get(
        region, region.title()
    )
    yrs = years_of_record or 0

    if kind == "monthly_loss_record":
        loss = abs(monthly_delta_gt or 0.0)
        prev_line = (
            f"Previous worst: {abs(previous_worst_gt):.0f} Gt in {previous_worst_month}."
            if previous_worst_gt is not None and previous_worst_month
            else "This is the first monthly record observed for this region."
        )
        data = (
            f"{region_name} lost {loss:.0f} gigatons of ice in {month}. "
            f"That is the largest single-month mass loss in {yrs} years of GRACE/GRACE-FO satellite gravimetry (records start 2002). "
            f"{prev_line} "
            f"Do not personify the ice ('dying', 'suffering'). Do not conflate with sea-level rise."
        )
    else:  # cumulative_milestone
        threshold_abs = abs(int(threshold_gt or 0))
        current_abs = abs(current_mass_gt or 0.0)
        data = (
            f"Cumulative ice mass loss from {region_name} has now crossed {threshold_abs:,} gigatons "
            f"since GRACE observations began in 2002. Current cumulative anomaly: {current_abs:,.0f} Gt below the 2002 baseline. "
            f"Do not personify the ice. Do not conflate with sea-level rise."
        )

    return generate_tweet(
        data,
        category="ice_mass_record",
        return_bundle=return_bundle,
        fallback_fn=templates.ice_mass_template,
        fallback_args={
            "region": region,
            "kind": kind,
            "month": month,
            "monthly_delta_gt": monthly_delta_gt,
            "years_of_record": years_of_record,
            "threshold_gt": threshold_gt,
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_generator.py::TestGenerateIceMassTweet -v`
Expected: PASS (2 cases).

- [ ] **Step 5: Commit**

```bash
git add src/voice/generator.py tests/test_generator.py
git commit -m "Add generate_ice_mass_tweet with Gemini prompt + template fallback"
```

---

## Task 13: Approval policy

**Files:**
- Modify: `src/editorial/approval.py`
- Modify: `tests/test_editorial_approval.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_editorial_approval.py`:

```python
class TestIceMassApproval:
    def test_ice_mass_record_policy(self):
        from src.editorial.approval import recommend_approval_policy
        policy = recommend_approval_policy(
            tweet_type="ice_mass_record",
            signal_total=84,
            candidate_score={"total": 78},
        )
        assert policy.key == "ice_mass_review"
        assert policy.mode == "suggested_auto"
        assert policy.recommended_delay_minutes == 105
        assert policy.can_auto_approve is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_editorial_approval.py::TestIceMassApproval -v`
Expected: FAIL — the default branch returns `default_review`.

- [ ] **Step 3: Add branch in `recommend_approval_policy`**

In `src/editorial/approval.py`, insert this block **before** the `if tweet_type in {"record", "record_low", ...}` check (around line 89):

```python
    if tweet_type == "ice_mass_record":
        return ApprovalPolicy(
            key="ice_mass_review",
            mode="suggested_auto",
            recommended_delay_minutes=105,
            can_auto_approve=True,
            reason="GRACE ice-mass milestone — rare, elite signal. Mid-length review window for framing polish.",
        )

```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_editorial_approval.py -v`
Expected: PASS (all existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/editorial/approval.py tests/test_editorial_approval.py
git commit -m "Add ice_mass_record approval policy (suggested_auto, 105 min)"
```

---

## Task 14: Orchestrator — cap helpers

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Add constants + helpers**

In `src/main.py`, near the existing CO2 helpers (around line 217), add:

```python
ICE_ANNUAL_CAP = 8


def _ice_annual_cap_reached(bot_state: dict, cap: int = ICE_ANNUAL_CAP) -> bool:
    """True if we've already drafted ICE_ANNUAL_CAP ice-mass tweets this year."""
    year_key = str(date.today().year)
    count = bot_state.get("ice_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[ice_mass] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False


def _increment_ice_annual_count(bot_state: dict) -> None:
    year_key = str(date.today().year)
    counts = bot_state.setdefault("ice_annual_count", {})
    counts[year_key] = counts.get(year_key, 0) + 1
```

- [ ] **Step 2: Import and score-function wiring**

In `src/main.py`, update the two import blocks:

1. Line 17 — add `ice_mass`:
   ```python
   from src.data import open_meteo, firms, co2, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges, ice_mass
   ```
2. Scoring import block (around line 37) — add `score_ice_mass_event`:
   ```python
       score_sea_ice_record,
       score_ice_mass_event,
   ```

- [ ] **Step 3: Run suite to verify nothing is broken**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: PASS (no behavior change yet — imports only).

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "Wire ice_mass imports + annual cap helpers"
```

---

## Task 15: Orchestrator — `run_alerts` ice_mass section

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_main.py`. (The file already mocks each data source with fixtures — follow the same pattern; a minimal test is given below.)

```python
class TestRunAlertsIceMass:
    def test_monday_with_record_drafts(self, monkeypatch):
        """On a Monday, a fresh monthly record for Greenland drafts a tweet
        and updates state (ice_mass_max_loss + ice_mass_last_seen + count)."""
        from src import main
        import datetime as _dt

        class FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 4, 20)  # a Monday

        monkeypatch.setattr(main, "date", FakeDate)

        # Monkeypatch ice_mass module: happy readings, fire a record
        from src.data import ice_mass as ice_mass_mod
        readings = [
            ice_mass_mod.IceMassReading("greenland", "2026-02", -5000.0, 100, "ice_mass_greenland_2026-02"),
            ice_mass_mod.IceMassReading("greenland", "2026-03", -5500.0, 100, "ice_mass_greenland_2026-03"),
        ]
        monkeypatch.setattr(ice_mass_mod, "fetch_grace_mass",
                            lambda region: readings if region == "greenland" else [])
        # Force every other data source to return empty / no-op
        for attr, func in [
            ("fetch_hot10", lambda *a, **k: []),
        ]:
            if hasattr(main.open_meteo, attr):
                monkeypatch.setattr(main.open_meteo, attr, func)
        # Simpler: short-circuit all other fetchers
        for mod_name in (
            "firms", "co2", "nws_alerts", "gdacs", "sea_ice", "drought", "enso",
            "ocean", "water_levels", "river_gauges",
        ):
            mod = getattr(main, mod_name)
            for fn in dir(mod):
                if fn.startswith("fetch_"):
                    monkeypatch.setattr(mod, fn, lambda *a, **k: [])

        # Stub the generator to avoid Gemini calls — return a bundle-like string
        monkeypatch.setattr(
            main.generator, "generate_ice_mass_tweet",
            lambda *a, **k: "Greenland lost 500 Gt. Largest monthly loss in GRACE record.",
        )

        bot_state = {
            "last_hot10": {"date": None, "cities": []},
            "streaks": {},
            "posted_events": [],
            "daily_tweet_count": {},
            "co2_annual_count": {},
            "drafts": [],
            "run_history": [],
            "errors": [],
            "city_all_time_max": {},
            "city_all_time_min": {},
            "city_monthly_max": {},
            "city_monthly_min": {},
            "record_streaks": {},
            "ice_mass_max_loss": {},
            "ice_mass_last_milestone": {},
            "ice_mass_last_seen": {},
            "ice_annual_count": {},
        }
        main.run_alerts(bot_state)

        assert bot_state["ice_mass_last_seen"].get("greenland") == "2026-03"
        assert bot_state["ice_mass_max_loss"].get("greenland", {}).get("gt") == -500.0
        assert bot_state["ice_annual_count"].get("2026", 0) >= 1
        # The event must be recorded
        assert any("ice_mass_record_greenland_monthly_2026-03" == e
                   for e in bot_state["posted_events"])

    def test_non_monday_records_skipped(self, monkeypatch):
        from src import main
        import datetime as _dt

        class FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 4, 21)  # a Tuesday

        monkeypatch.setattr(main, "date", FakeDate)

        from src.data import ice_mass as ice_mass_mod
        called = {"n": 0}

        def spy(region):
            called["n"] += 1
            return []

        monkeypatch.setattr(ice_mass_mod, "fetch_grace_mass", spy)
        # Short-circuit all other fetchers the same way.
        for mod_name in (
            "firms", "co2", "nws_alerts", "gdacs", "sea_ice", "drought", "enso",
            "ocean", "water_levels", "river_gauges",
        ):
            mod = getattr(main, mod_name)
            for fn in dir(mod):
                if fn.startswith("fetch_"):
                    monkeypatch.setattr(mod, fn, lambda *a, **k: [])

        bot_state = {
            "last_hot10": {"date": None, "cities": []}, "streaks": {},
            "posted_events": [], "daily_tweet_count": {}, "co2_annual_count": {},
            "drafts": [], "run_history": [], "errors": [],
            "city_all_time_max": {}, "city_all_time_min": {},
            "city_monthly_max": {}, "city_monthly_min": {},
            "record_streaks": {}, "ice_mass_max_loss": {},
            "ice_mass_last_milestone": {}, "ice_mass_last_seen": {},
            "ice_annual_count": {},
        }
        main.run_alerts(bot_state)
        assert called["n"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_main.py::TestRunAlertsIceMass -v`
Expected: FAIL — the lane doesn't exist yet.

- [ ] **Step 3: Add the `run_alerts` section**

In `src/main.py`, inside `run_alerts`, locate the end of the drought/ENSO block (search for `# 7. US Drought Monitor`, find its closing `except/_record_source_run` block — approximately line 1160). Insert this new section **after** the drought block and before whatever comes next (ENSO, ocean, etc.):

```python
    # 8. GRACE-FO ice mass (Greenland + Antarctica).
    # Monthly-cadence source with 1-2 month lag. Run once per week on
    # Mondays (matches sea ice). Per-region short-circuit via
    # ice_mass_last_seen prevents re-processing the same published month.
    # Annual cap: ICE_ANNUAL_CAP tweets/year across both regions + kinds.
    if date.today().weekday() == 0:
        print("[alerts] Checking GRACE ice mass...")
        for region in ("greenland", "antarctica"):
            region_key = f"ice_mass_{region}"
            im_start = time.perf_counter()
            try:
                if _ice_annual_cap_reached(bot_state):
                    _record_source_run(
                        current_run, region_key, im_start,
                        status="skipped", note="annual cap reached",
                    )
                    continue
                readings = ice_mass.fetch_grace_mass(region=region)
                if not readings:
                    _record_source_run(
                        current_run, region_key, im_start,
                        status="success", observed=0,
                    )
                    continue
                latest_month = readings[-1].month
                last_seen = bot_state.get("ice_mass_last_seen", {}).get(region)
                if last_seen == latest_month:
                    _record_source_run(
                        current_run, region_key, im_start,
                        status="skipped",
                        note=f"already processed {latest_month}",
                    )
                    continue

                record = ice_mass.detect_monthly_record(readings, bot_state)
                if record is None:
                    record = ice_mass.detect_cumulative_milestone(readings, bot_state)

                source_promoted = 0
                source_drafted = 0
                if record and not state.is_duplicate(bot_state, record.event_id):
                    score = score_ice_mass_event(
                        region=record.region,
                        kind=record.kind,
                        monthly_delta_gt=record.monthly_delta_gt,
                        previous_worst_gt=record.previous_worst_gt,
                        threshold_gt=record.threshold_gt,
                    )
                    if _should_draft(score, record.event_id):
                        source_promoted = 1
                        earliest = readings[0].month
                        earliest_year = int(earliest.split("-")[0])
                        years_of_record = date.today().year - earliest_year
                        generated = generator.generate_ice_mass_tweet(
                            region=record.region,
                            kind=record.kind,
                            month=record.month,
                            monthly_delta_gt=record.monthly_delta_gt,
                            previous_worst_gt=record.previous_worst_gt,
                            previous_worst_month=record.previous_worst_month,
                            threshold_gt=record.threshold_gt,
                            current_mass_gt=record.current_mass_gt,
                            years_of_record=years_of_record,
                            return_bundle=True,
                        )
                        headline = (
                            f"{record.region.title()}: largest monthly ice loss on record"
                            if record.kind == "monthly_loss_record"
                            else f"{record.region.title()}: cumulative loss crosses {abs(int(record.threshold_gt))} Gt"
                        )
                        facts = [
                            _fact("Region", record.region.title()),
                            _fact("Latest month", record.month or latest_month),
                        ]
                        if record.kind == "monthly_loss_record":
                            facts.append(_fact(
                                "Monthly loss",
                                f"{abs(record.monthly_delta_gt):.0f} Gt",
                            ))
                            if record.previous_worst_gt is not None:
                                facts.append(_fact(
                                    "Previous worst",
                                    f"{abs(record.previous_worst_gt):.0f} Gt "
                                    f"({record.previous_worst_month})",
                                ))
                        else:
                            facts.append(_fact(
                                "Cumulative threshold",
                                f"{abs(int(record.threshold_gt))} Gt",
                            ))
                            facts.append(_fact(
                                "Current anomaly",
                                f"{abs(record.current_mass_gt):.0f} Gt below 2002 baseline",
                            ))
                        review_context = _review_context(
                            source="NASA GRACE-FO / JPL PODAAC",
                            source_key=region_key,
                            headline=headline,
                            current_run=current_run,
                            facts=facts,
                        )
                        if _save_generated_draft(
                            generated, bot_state, "ice_mass_record",
                            record.event_id, score, review_context=review_context,
                        ):
                            state.record_event(bot_state, record.event_id)
                            _increment_ice_annual_count(bot_state)
                            drafted += 1
                            source_drafted = 1
                            # Update the extreme trackers on success.
                            if record.kind == "monthly_loss_record":
                                bot_state.setdefault("ice_mass_max_loss", {})[record.region] = {
                                    "gt": record.monthly_delta_gt,
                                    "month": record.month,
                                }
                            else:
                                bot_state.setdefault("ice_mass_last_milestone", {})[record.region] = record.threshold_gt

                # Always mark the month as seen so we don't reprocess until data updates.
                bot_state.setdefault("ice_mass_last_seen", {})[region] = latest_month
                _record_source_run(
                    current_run, region_key, im_start,
                    status="success", observed=len(readings),
                    promoted=source_promoted, drafted=source_drafted,
                )
            except Exception as e:
                print(f"[alerts] ice_mass {region} error: {e}")
                state.log_error(bot_state, region_key, str(e))
                _record_source_run(
                    current_run, region_key, im_start,
                    status="failed", error=str(e),
                )
    else:
        for region in ("greenland", "antarctica"):
            skipped_start = time.perf_counter()
            _record_source_run(
                current_run, f"ice_mass_{region}", skipped_start,
                status="skipped", note="Runs Mondays only",
            )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/test_main.py::TestRunAlertsIceMass -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite to catch regressions**

Run: `.venv/bin/pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "Integrate ice_mass lane into run_alerts with Monday cadence + per-region short-circuit"
```

---

## Task 16: Docs — `BRIEFING.md` + `PIPELINE.md`

**Files:**
- Modify: `BRIEFING.md`
- Modify: `PIPELINE.md`

- [ ] **Step 1: Update `BRIEFING.md`**

Locate the "Required secrets" / env vars section in `BRIEFING.md`. Add a line (preserve existing content):

```markdown
- `EARTHDATA_TOKEN` — NASA Earthdata Login bearer token, used by the
  GRACE-FO ice-mass lane. Generate at https://urs.earthdata.nasa.gov/
  (profile → "Generate Token"). Optional: if unset the ice_mass lane
  short-circuits to skipped and the rest of the pipeline runs normally.
```

If `BRIEFING.md` doesn't have a secrets section, add one near the top under a new heading `## Required secrets`.

- [ ] **Step 2: Update `PIPELINE.md`**

Locate the weekly/Monday section in `PIPELINE.md`. Add under the existing sea-ice entry:

```markdown
- **GRACE-FO ice mass (Mondays, Lane 2)** — JPL PODAAC Level-4 mascon
  time series for Greenland + Antarctica. Two detectors:
  *monthly loss record* (largest single-month mass delta in the GRACE
  record) and *cumulative milestone* (each -1000 Gt floor crossed).
  Capped at 8 tweets/year across both regions. Requires `EARTHDATA_TOKEN`.
```

- [ ] **Step 3: Commit**

```bash
git add BRIEFING.md PIPELINE.md
git commit -m "Document EARTHDATA_TOKEN + GRACE-FO ice_mass lane"
```

---

## Task 17: Full-suite verification

**Files:** none modified

- [ ] **Step 1: Run entire test suite**

Run: `.venv/bin/pytest -q`
Expected: all green, no warnings about new ice_mass paths.

- [ ] **Step 2: Run linter/formatter if the repo has one**

Run: `.venv/bin/ruff check src tests 2>/dev/null || echo "no ruff configured"`

Address any new warnings introduced by Lane 2 code only.

- [ ] **Step 3: Final sanity check**

Run: `git log --oneline $(git merge-base HEAD main)..HEAD`

Expected: one commit per task (~15-17 commits) with descriptive messages.

- [ ] **Step 4: Ready for PR**

At this point the branch is ready for review. Optional: run the lane manually against a live Earthdata token to confirm real-endpoint fetch works (Definition of Done item from the spec).

```bash
EARTHDATA_TOKEN=<your_token> .venv/bin/python -c "from src.data.ice_mass import fetch_grace_mass; r = fetch_grace_mass('greenland'); print(f'Got {len(r)} readings. Latest: {r[-1] if r else None}')"
```

Expected: a few hundred readings; the most recent is within ~2 months of today.
