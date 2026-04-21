# Cross-Source Story Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Fire × Drought × Heat cross-source synthesis rule plus the scaffolding that later synthesis rules will reuse.

**Architecture:** Per-source sections of `run_alerts` append into a rolling 14-day `synthesis_components` buffer in `bot_state` whenever events pass their standalone editorial gates. The weekly USDM snapshot is cached. A new synthesis stage runs at the end of `run_alerts`, detects the Fire×Drought×Heat convergence per US state, scores it (threshold 82), generates a compound-framing tweet through the full existing pipeline (Gemini → safety → ranking → evaluator → rewrite validation), and stores it as a `suggested_auto` draft with a 120-minute review delay. Region matching uses static US state bounding boxes with a closest-centroid disambiguation fallback — no new external dependencies.

**Tech Stack:** Python 3.11, pytest, pure stdlib for bounding-box math, existing Gemini 2.5 Flash + Claude Sonnet pipeline.

**Spec:** `docs/superpowers/specs/2026-04-20-cross-source-synthesis-design.md`

---

## File structure

### New files

| Path | Purpose |
|---|---|
| `src/editorial/_regions.py` | `STATE_BOUNDING_BOXES`, `STATE_CENTROIDS`, `lat_lon_to_state`, `cities_to_state_map`. Pure geometry + data. |
| `src/editorial/synthesis.py` | `SynthesisSignal` dataclass + `detect_fire_drought_heat` rule. Pure function of `bot_state`. |
| `tests/test_regions.py` | Unit tests for region lookup. |
| `tests/test_state_synthesis.py` | Unit tests for the new state helpers. |
| `tests/test_synthesis.py` | Unit tests for the detection rule. |

### Modified files

| Path | Change |
|---|---|
| `src/state.py` | Add `synthesis_components` / `synthesis_cooldown` to `DEFAULT_STATE`; add 7 new helpers. |
| `src/editorial/scoring.py` | Add `score_synthesis_fire_drought_heat`. |
| `src/editorial/approval.py` | Add `synthesis_fire_drought_heat` case → `suggested_auto`, 120-min delay. |
| `src/voice/templates.py` | Add `SYNTHESIS_FIRE_DROUGHT_HEAT_SYSTEM_PROMPT`. |
| `src/voice/generator.py` | Add `generate_synthesis_fire_drought_heat_tweet` wrapper + `_synthesis_fdh_template` fallback. |
| `src/main.py` | Wire `cities_to_state_map` + per-source contributions + new synthesis stage at end of `run_alerts`. |
| `tests/test_editorial_scoring.py` | Add cases for synthesis scoring. |
| `tests/test_editorial_approval.py` | Add case for synthesis policy. |
| `tests/test_generator.py` | Add template-fallback + Gemini-mock cases for synthesis. |
| `tests/test_main.py` | Add integration smoke test for synthesis stage. |
| `BRIEFING.md` | One paragraph mentioning cross-source synthesis. |
| `PIPELINE.md` | New stage block in the mermaid flow + glossary entry. |

---

## Task 1: State bounding boxes and `lat_lon_to_state`

**Files:**
- Create: `src/editorial/_regions.py`
- Create: `tests/test_regions.py`

- [ ] **Step 1: Write the failing test for interior state points**

Create `tests/test_regions.py`:

```python
"""Tests for lat/lon → US state lookup."""

from src.editorial._regions import lat_lon_to_state


class TestLatLonToState:
    def test_interior_california(self):
        # Sacramento
        assert lat_lon_to_state(38.58, -121.49) == "California"

    def test_interior_texas(self):
        # Austin
        assert lat_lon_to_state(30.27, -97.74) == "Texas"

    def test_interior_florida(self):
        # Miami
        assert lat_lon_to_state(25.76, -80.19) == "Florida"

    def test_interior_alaska(self):
        # Anchorage
        assert lat_lon_to_state(61.22, -149.90) == "Alaska"

    def test_interior_new_york(self):
        # NYC
        assert lat_lon_to_state(40.71, -74.01) == "New York"

    def test_outside_us_mexico(self):
        # Mexico City
        assert lat_lon_to_state(19.43, -99.13) is None

    def test_outside_us_london(self):
        assert lat_lon_to_state(51.51, -0.13) is None

    def test_outside_us_pacific(self):
        assert lat_lon_to_state(0.0, -150.0) is None

    def test_border_lake_tahoe_picks_one(self):
        # Lake Tahoe is on the CA/NV border; disambiguation must pick one.
        result = lat_lon_to_state(39.10, -120.04)
        assert result in {"California", "Nevada"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_regions.py -v`
Expected: all FAIL with `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement `_regions.py`**

Create `src/editorial/_regions.py`:

```python
"""US state geographic lookup — bounding boxes plus closest-centroid disambiguation.

Precision is state-level, which matches the scope of every synthesis rule
that uses this module. County-level precision is out of scope; if a point
falls inside two adjacent states' bounding boxes, we pick the state whose
centroid is closest. If no state centroid is within 500 km, we return None
(the point isn't in the US).
"""

from __future__ import annotations

from math import radians, sin, cos, asin, sqrt

# (min_lat, max_lat, min_lon, max_lon) per state.
# Derived from public Census Bureau state extents, rounded to 2 decimals.
STATE_BOUNDING_BOXES: dict[str, tuple[float, float, float, float]] = {
    "Alabama":        (30.14, 35.01, -88.47, -84.89),
    "Alaska":         (51.21, 71.44, -179.15, 179.78),
    "Arizona":        (31.33, 37.01, -114.82, -109.05),
    "Arkansas":       (33.00, 36.50, -94.62, -89.64),
    "California":     (32.53, 42.01, -124.41, -114.13),
    "Colorado":       (36.99, 41.00, -109.06, -102.04),
    "Connecticut":    (40.98, 42.05, -73.73, -71.79),
    "Delaware":       (38.45, 39.84, -75.79, -75.05),
    "District of Columbia": (38.79, 38.99, -77.12, -76.91),
    "Florida":        (24.52, 31.00, -87.63, -80.03),
    "Georgia":        (30.36, 35.00, -85.61, -80.84),
    "Hawaii":         (18.91, 28.40, -178.33, -154.81),
    "Idaho":          (41.99, 49.00, -117.24, -111.04),
    "Illinois":       (36.97, 42.51, -91.51, -87.01),
    "Indiana":        (37.77, 41.76, -88.10, -84.78),
    "Iowa":           (40.38, 43.50, -96.64, -90.14),
    "Kansas":         (36.99, 40.00, -102.05, -94.59),
    "Kentucky":       (36.50, 39.15, -89.57, -81.96),
    "Louisiana":      (28.93, 33.02, -94.04, -88.82),
    "Maine":          (43.06, 47.46, -71.08, -66.95),
    "Maryland":       (37.89, 39.72, -79.49, -75.05),
    "Massachusetts":  (41.19, 42.89, -73.51, -69.93),
    "Michigan":       (41.70, 48.31, -90.42, -82.13),
    "Minnesota":      (43.50, 49.38, -97.24, -89.49),
    "Mississippi":    (30.17, 34.99, -91.66, -88.10),
    "Missouri":       (35.99, 40.61, -95.77, -89.10),
    "Montana":        (44.36, 49.00, -116.05, -104.04),
    "Nebraska":       (40.00, 43.00, -104.05, -95.31),
    "Nevada":         (35.00, 42.00, -120.01, -114.04),
    "New Hampshire":  (42.70, 45.31, -72.56, -70.61),
    "New Jersey":     (38.93, 41.36, -75.56, -73.89),
    "New Mexico":     (31.33, 37.00, -109.05, -103.00),
    "New York":       (40.50, 45.02, -79.76, -71.86),
    "North Carolina": (33.84, 36.59, -84.32, -75.46),
    "North Dakota":   (45.94, 49.00, -104.05, -96.55),
    "Ohio":           (38.40, 42.33, -84.82, -80.52),
    "Oklahoma":       (33.62, 37.00, -103.00, -94.43),
    "Oregon":         (41.99, 46.29, -124.57, -116.46),
    "Pennsylvania":   (39.72, 42.27, -80.52, -74.69),
    "Rhode Island":   (41.15, 42.02, -71.91, -71.12),
    "South Carolina": (32.03, 35.22, -83.35, -78.54),
    "South Dakota":   (42.48, 45.95, -104.06, -96.44),
    "Tennessee":      (34.98, 36.68, -90.31, -81.65),
    "Texas":          (25.84, 36.50, -106.65, -93.51),
    "Utah":           (36.99, 42.00, -114.05, -109.04),
    "Vermont":        (42.73, 45.02, -73.44, -71.47),
    "Virginia":       (36.54, 39.47, -83.68, -75.24),
    "Washington":     (45.54, 49.00, -124.85, -116.92),
    "West Virginia":  (37.20, 40.64, -82.64, -77.72),
    "Wisconsin":      (42.49, 47.08, -92.89, -86.77),
    "Wyoming":        (40.99, 45.01, -111.06, -104.05),
}

STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "Alabama":        (32.81, -86.79),
    "Alaska":         (64.20, -149.49),
    "Arizona":        (34.87, -111.76),
    "Arkansas":       (34.75, -92.44),
    "California":     (37.18, -119.47),
    "Colorado":       (39.00, -105.55),
    "Connecticut":    (41.60, -72.76),
    "Delaware":       (39.00, -75.50),
    "District of Columbia": (38.90, -77.02),
    "Florida":        (28.63, -82.45),
    "Georgia":        (32.65, -83.44),
    "Hawaii":         (20.29, -156.37),
    "Idaho":          (44.39, -114.61),
    "Illinois":       (40.04, -89.20),
    "Indiana":        (39.90, -86.28),
    "Iowa":           (42.07, -93.50),
    "Kansas":         (38.50, -98.38),
    "Kentucky":       (37.53, -85.30),
    "Louisiana":      (31.06, -92.01),
    "Maine":          (45.37, -69.24),
    "Maryland":       (39.06, -76.80),
    "Massachusetts":  (42.26, -71.81),
    "Michigan":       (44.94, -86.00),
    "Minnesota":      (46.28, -94.30),
    "Mississippi":    (32.74, -89.68),
    "Missouri":       (38.36, -92.46),
    "Montana":        (46.97, -109.53),
    "Nebraska":       (41.53, -99.79),
    "Nevada":         (39.33, -116.63),
    "New Hampshire":  (43.68, -71.58),
    "New Jersey":     (40.19, -74.67),
    "New Mexico":     (34.42, -106.11),
    "New York":       (42.95, -75.53),
    "North Carolina": (35.55, -79.39),
    "North Dakota":   (47.45, -100.47),
    "Ohio":           (40.29, -82.79),
    "Oklahoma":       (35.59, -97.49),
    "Oregon":         (44.13, -120.55),
    "Pennsylvania":   (40.87, -77.80),
    "Rhode Island":   (41.68, -71.56),
    "South Carolina": (33.91, -80.89),
    "South Dakota":   (44.44, -100.23),
    "Tennessee":      (35.86, -86.36),
    "Texas":          (31.48, -99.33),
    "Utah":           (39.32, -111.67),
    "Vermont":        (44.07, -72.67),
    "Virginia":       (37.52, -78.86),
    "Washington":     (47.38, -120.45),
    "West Virginia":  (38.64, -80.62),
    "Wisconsin":      (44.62, -89.99),
    "Wyoming":        (42.99, -107.55),
}

MAX_CENTROID_KM = 500.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def lat_lon_to_state(lat: float, lon: float) -> str | None:
    """Return canonical US state name for a point, or None if outside the US.

    If multiple bounding boxes match, resolve by nearest centroid. If the
    nearest centroid is more than MAX_CENTROID_KM away, the point is
    treated as not-in-the-US.
    """
    matches = [
        name for name, (min_lat, max_lat, min_lon, max_lon) in STATE_BOUNDING_BOXES.items()
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    best_name = None
    best_dist = float("inf")
    for name in matches:
        c_lat, c_lon = STATE_CENTROIDS[name]
        dist = _haversine_km(lat, lon, c_lat, c_lon)
        if dist < best_dist:
            best_dist = dist
            best_name = name
    if best_dist > MAX_CENTROID_KM:
        return None
    return best_name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_regions.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/_regions.py tests/test_regions.py
git commit -m "feat(synthesis): add lat/lon → US state lookup"
```

---

## Task 2: `cities_to_state_map` helper

**Files:**
- Modify: `src/editorial/_regions.py` (append function)
- Modify: `tests/test_regions.py` (append test class)

- [ ] **Step 1: Add failing test**

Append to `tests/test_regions.py`:

```python
class TestCitiesToStateMap:
    def test_us_cities_mapped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [
            {"city": "Sacramento", "latitude": 38.58, "longitude": -121.49, "country": "United States"},
            {"city": "Austin",     "latitude": 30.27, "longitude": -97.74,  "country": "United States"},
        ]
        assert cities_to_state_map(cities) == {
            "Sacramento": "California",
            "Austin": "Texas",
        }

    def test_non_us_cities_skipped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [
            {"city": "Sacramento", "latitude": 38.58, "longitude": -121.49, "country": "United States"},
            {"city": "London",     "latitude": 51.51, "longitude": -0.13,   "country": "United Kingdom"},
        ]
        assert cities_to_state_map(cities) == {"Sacramento": "California"}

    def test_missing_coords_skipped(self):
        from src.editorial._regions import cities_to_state_map
        cities = [{"city": "Broken", "latitude": None, "longitude": None, "country": "United States"}]
        assert cities_to_state_map(cities) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_regions.py::TestCitiesToStateMap -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `cities_to_state_map`**

Append to `src/editorial/_regions.py`:

```python
def cities_to_state_map(cities: list[dict]) -> dict[str, str]:
    """Pre-compute city_name → US state for each US city with coords.

    Non-US cities and cities without coords are omitted from the result.
    The caller looks up `state = mapping.get(city_name)` and short-circuits
    recording when the lookup returns None.
    """
    mapping: dict[str, str] = {}
    for c in cities:
        if not isinstance(c, dict):
            continue
        name = c.get("city") or c.get("name")
        lat = c.get("latitude")
        lon = c.get("longitude")
        if not name or lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        state = lat_lon_to_state(lat_f, lon_f)
        if state is not None:
            mapping[name] = state
    return mapping
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_regions.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/_regions.py tests/test_regions.py
git commit -m "feat(synthesis): add cities_to_state_map helper"
```

---

## Task 3: Synthesis state helpers (rolling buffer + cooldown)

**Files:**
- Modify: `src/state.py`
- Create: `tests/test_state_synthesis.py`

- [ ] **Step 1: Write failing tests for rolling buffer helpers**

Create `tests/test_state_synthesis.py`:

```python
"""Tests for synthesis-layer state helpers."""

from copy import deepcopy
from datetime import date, datetime, timedelta, UTC

import pytest

from src.state import (
    DEFAULT_STATE,
    record_synthesis_component,
    get_synthesis_components,
    record_synthesis_drought_snapshot,
    get_synthesis_drought_snapshot,
    is_synthesis_on_cooldown,
    record_synthesis_fired,
    prune_stale_synthesis_components,
)


def _now_iso(offset_days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=offset_days)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def fresh_state():
    return deepcopy(DEFAULT_STATE)


class TestRecordSynthesisComponent:
    def test_fresh_state_creates_structure(self, fresh_state):
        record_synthesis_component(
            fresh_state, kind="fire", region="California",
            event_id="fire_abc", metadata={"frp": 1200.0},
            timestamp=_now_iso(),
        )
        fires = fresh_state["synthesis_components"]["fires"]["California"]
        assert len(fires) == 1
        assert fires[0]["event_id"] == "fire_abc"
        assert fires[0]["frp"] == 1200.0

    def test_multiple_components_same_state(self, fresh_state):
        record_synthesis_component(fresh_state, kind="heat", region="California",
            event_id="heat_1", metadata={"city": "Sacramento", "value_c": 42.0},
            timestamp=_now_iso())
        record_synthesis_component(fresh_state, kind="heat", region="California",
            event_id="heat_2", metadata={"city": "Fresno", "value_c": 43.5},
            timestamp=_now_iso())
        heats = fresh_state["synthesis_components"]["heats"]["California"]
        assert len(heats) == 2

    def test_duplicate_event_id_skipped(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="fire_abc", metadata={"frp": 1.0}, timestamp=_now_iso())
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="fire_abc", metadata={"frp": 999.0}, timestamp=_now_iso())
        assert len(fresh_state["synthesis_components"]["fires"]["California"]) == 1


class TestGetSynthesisComponents:
    def test_empty_state_returns_empty(self, fresh_state):
        assert get_synthesis_components(fresh_state, kind="fire", region="California") == []

    def test_filters_by_since(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="old", metadata={}, timestamp=_now_iso(offset_days=20))
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="new", metadata={}, timestamp=_now_iso(offset_days=3))
        since = (datetime.now(UTC) - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        result = get_synthesis_components(fresh_state, kind="fire", region="California", since=since)
        assert len(result) == 1
        assert result[0]["event_id"] == "new"


class TestPruneStaleSynthesisComponents:
    def test_removes_items_older_than_ttl(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="old", metadata={}, timestamp=_now_iso(offset_days=20))
        record_synthesis_component(fresh_state, kind="fire", region="California",
            event_id="new", metadata={}, timestamp=_now_iso(offset_days=5))
        prune_stale_synthesis_components(fresh_state, ttl_days=14)
        fires = fresh_state["synthesis_components"]["fires"]["California"]
        assert [f["event_id"] for f in fires] == ["new"]

    def test_removes_empty_region_keys(self, fresh_state):
        record_synthesis_component(fresh_state, kind="fire", region="Arizona",
            event_id="old", metadata={}, timestamp=_now_iso(offset_days=30))
        prune_stale_synthesis_components(fresh_state, ttl_days=14)
        assert "Arizona" not in fresh_state["synthesis_components"]["fires"]


class TestCooldown:
    def test_no_prior_fire_not_on_cooldown(self, fresh_state):
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "California") is False

    def test_within_14_days_on_cooldown(self, fresh_state):
        record_synthesis_fired(fresh_state, "fire_drought_heat", "California",
            timestamp=_now_iso(offset_days=5))
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "California") is True

    def test_after_14_days_not_on_cooldown(self, fresh_state):
        record_synthesis_fired(fresh_state, "fire_drought_heat", "California",
            timestamp=_now_iso(offset_days=16))
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "California") is False

    def test_cooldown_scoped_by_region(self, fresh_state):
        record_synthesis_fired(fresh_state, "fire_drought_heat", "California",
            timestamp=_now_iso(offset_days=1))
        assert is_synthesis_on_cooldown(fresh_state, "fire_drought_heat", "Arizona") is False


class TestDroughtSnapshot:
    def test_record_and_get(self, fresh_state):
        updates = [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
            {"state": "Arizona",    "d3_pct": 15.0, "d4_pct": 2.0,  "total_drought_pct": 60.0},
        ]
        record_synthesis_drought_snapshot(fresh_state, updates)
        snap = get_synthesis_drought_snapshot(fresh_state)
        assert snap is not None
        assert snap["entries"][0]["state"] == "California"

    def test_missing_returns_none(self, fresh_state):
        assert get_synthesis_drought_snapshot(fresh_state) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state_synthesis.py -v`
Expected: all FAIL with `ImportError`.

- [ ] **Step 3: Extend `DEFAULT_STATE` and add helpers**

In `src/state.py`, add to the `DEFAULT_STATE` dict (keep existing keys intact):

```python
    # Cross-source synthesis layer (src/editorial/synthesis.py).
    # "components" holds a 14-day rolling record of per-source events
    # that passed their standalone editorial gates — fires and heat
    # records, bucketed by US state. "drought_snapshot" caches the
    # last Friday USDM reading so synthesis rules have access to
    # current drought conditions on any day, not just Fridays.
    "synthesis_components": {
        "fires": {},              # {state: [{event_id, frp, region, at}]}
        "heats": {},              # {state: [{event_id, kind, city, value_c, at}]}
        "drought_snapshot": None, # {updated_at, entries: [...]}
    },
    # {rule_name: {region: last_fired_at_iso}}
    "synthesis_cooldown": {},
```

Append new helpers to the bottom of `src/state.py`:

```python
def record_synthesis_component(
    state: dict,
    *,
    kind: str,
    region: str,
    event_id: str,
    metadata: dict | None = None,
    timestamp: str | None = None,
) -> dict:
    """Append a per-source event to the synthesis rolling buffer.

    kind: "fire" or "heat". Stored under "fires" or "heats" respectively.
    region: canonical state name from src/editorial/_regions.py.
    event_id: the underlying per-source event id — used only for
      deduplication within this buffer; the buffer is not the durable
      posted_events log.
    """
    bucket_key = "fires" if kind == "fire" else "heats"
    components = state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    bucket = components.setdefault(bucket_key, {}).setdefault(region, [])
    if any(entry.get("event_id") == event_id for entry in bucket):
        return state
    entry = {
        "event_id": event_id,
        "at": timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if metadata:
        for k, v in metadata.items():
            entry[k] = v
    bucket.append(entry)
    return state


def get_synthesis_components(
    state: dict, *, kind: str, region: str, since: str | None = None,
) -> list[dict]:
    """Read synthesis-buffer entries for a (kind, region), optionally
    filtered to those with `at >= since`."""
    bucket_key = "fires" if kind == "fire" else "heats"
    components = state.get("synthesis_components") or {}
    entries = (components.get(bucket_key) or {}).get(region) or []
    if since is None:
        return list(entries)
    return [e for e in entries if e.get("at", "") >= since]


def record_synthesis_drought_snapshot(state: dict, updates) -> dict:
    """Cache the current USDM per-state snapshot for synthesis reads.

    `updates` may be dataclasses (from drought.fetch_drought_data) or
    dicts. We normalize to dicts with the fields synthesis needs.
    """
    entries = []
    for u in updates or []:
        if hasattr(u, "state"):
            entries.append({
                "state": u.state,
                "d3_pct": float(getattr(u, "d3_pct", 0) or 0),
                "d4_pct": float(getattr(u, "d4_pct", 0) or 0),
                "total_drought_pct": float(getattr(u, "total_drought_pct", 0) or 0),
            })
        elif isinstance(u, dict):
            entries.append({
                "state": u.get("state", ""),
                "d3_pct": float(u.get("d3_pct", 0) or 0),
                "d4_pct": float(u.get("d4_pct", 0) or 0),
                "total_drought_pct": float(u.get("total_drought_pct", 0) or 0),
            })
    components = state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    components["drought_snapshot"] = {
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }
    return state


def get_synthesis_drought_snapshot(state: dict) -> dict | None:
    components = state.get("synthesis_components") or {}
    return components.get("drought_snapshot")


def is_synthesis_on_cooldown(
    state: dict, rule_name: str, region: str, days: int = 14,
) -> bool:
    cooldowns = (state.get("synthesis_cooldown") or {}).get(rule_name) or {}
    last_fired = cooldowns.get(region)
    if not last_fired:
        return False
    try:
        last_dt = datetime.fromisoformat(last_fired.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (datetime.now(UTC) - last_dt) < timedelta(days=days)


def record_synthesis_fired(
    state: dict, rule_name: str, region: str, timestamp: str | None = None,
) -> dict:
    cooldowns = state.setdefault("synthesis_cooldown", {})
    per_rule = cooldowns.setdefault(rule_name, {})
    per_rule[region] = (
        timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    return state


def prune_stale_synthesis_components(state: dict, ttl_days: int = 14) -> dict:
    """Drop buffer entries older than ttl_days; drop regions that become empty."""
    cutoff = (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat().replace("+00:00", "Z")
    components = state.setdefault("synthesis_components", {
        "fires": {}, "heats": {}, "drought_snapshot": None
    })
    for bucket_key in ("fires", "heats"):
        bucket = components.setdefault(bucket_key, {})
        for region in list(bucket.keys()):
            fresh = [e for e in bucket[region] if e.get("at", "") >= cutoff]
            if fresh:
                bucket[region] = fresh
            else:
                del bucket[region]
    return state
```

Required import at the top of `src/state.py` (check if already present; add `timedelta` to the existing `datetime` import line if missing):

```python
from datetime import UTC, date, datetime, timedelta
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state_synthesis.py -v`
Expected: all PASS.

- [ ] **Step 5: Run full state suite to catch regressions**

Run: `pytest tests/test_state.py tests/test_state_synthesis.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/state.py tests/test_state_synthesis.py
git commit -m "feat(synthesis): add rolling-buffer and cooldown state helpers"
```

---

## Task 4: `SynthesisSignal` dataclass + `detect_fire_drought_heat`

**Files:**
- Create: `src/editorial/synthesis.py`
- Create: `tests/test_synthesis.py`

- [ ] **Step 1: Write failing tests for the detection rule**

Create `tests/test_synthesis.py`:

```python
"""Tests for cross-source synthesis rules."""

from copy import deepcopy
from datetime import datetime, timedelta, UTC

import pytest

from src.state import (
    DEFAULT_STATE,
    record_synthesis_component,
    record_synthesis_drought_snapshot,
    record_synthesis_fired,
)
from src.editorial.synthesis import detect_fire_drought_heat, SynthesisSignal


def _iso(offset_days: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=offset_days)).isoformat().replace("+00:00", "Z")


@pytest.fixture
def state_ca_all_three():
    s = deepcopy(DEFAULT_STATE)
    record_synthesis_drought_snapshot(s, [
        {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
    ])
    record_synthesis_component(s, kind="fire", region="California",
        event_id="fire_1", metadata={"frp": 1200.0, "region": "Sacramento"},
        timestamp=_iso(offset_days=2))
    record_synthesis_component(s, kind="heat", region="California",
        event_id="heat_1",
        metadata={"kind": "calendar", "city": "Sacramento", "value_c": 40.1},
        timestamp=_iso(offset_days=1))
    return s


class TestFireDroughtHeatHappyPath:
    def test_fires_one_signal(self, state_ca_all_three):
        signals = detect_fire_drought_heat(state_ca_all_three)
        assert len(signals) == 1
        sig = signals[0]
        assert isinstance(sig, SynthesisSignal)
        assert sig.rule_name == "fire_drought_heat"
        assert sig.region == "California"
        assert "california" in sig.event_id.lower()

    def test_components_populated(self, state_ca_all_three):
        sig = detect_fire_drought_heat(state_ca_all_three)[0]
        assert sig.components["drought_d4_pct"] == 10.0
        assert sig.components["fire_peak_frp"] == 1200.0
        assert sig.components["heat_peak_city"] == "Sacramento"


class TestFireDroughtHeatMissingComponents:
    def test_missing_drought_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["drought_snapshot"] = None
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_drought_below_1pct_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["drought_snapshot"]["entries"][0]["d4_pct"] = 0.5
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_missing_fire_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["fires"] = {}
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_missing_heat_no_signal(self, state_ca_all_three):
        state_ca_all_three["synthesis_components"]["heats"] = {}
        assert detect_fire_drought_heat(state_ca_all_three) == []


class TestFireDroughtHeatRegionMismatch:
    def test_fire_and_heat_different_states_no_signal(self):
        s = deepcopy(DEFAULT_STATE)
        record_synthesis_drought_snapshot(s, [
            {"state": "California", "d3_pct": 20.0, "d4_pct": 8.0, "total_drought_pct": 80.0},
            {"state": "Arizona",    "d3_pct": 30.0, "d4_pct": 5.0, "total_drought_pct": 70.0},
        ])
        # Fire in CA, heat in AZ — CA lacks heat, AZ lacks fire.
        record_synthesis_component(s, kind="fire", region="California",
            event_id="fire_1", metadata={"frp": 800.0}, timestamp=_iso(offset_days=1))
        record_synthesis_component(s, kind="heat", region="Arizona",
            event_id="heat_1", metadata={"city": "Phoenix", "value_c": 46.0},
            timestamp=_iso(offset_days=1))
        assert detect_fire_drought_heat(s) == []


class TestFireDroughtHeatStaleness:
    def test_stale_fire_ignored(self):
        s = deepcopy(DEFAULT_STATE)
        record_synthesis_drought_snapshot(s, [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
        ])
        record_synthesis_component(s, kind="fire", region="California",
            event_id="old", metadata={"frp": 1200.0}, timestamp=_iso(offset_days=20))
        record_synthesis_component(s, kind="heat", region="California",
            event_id="heat_1", metadata={"city": "Sacramento", "value_c": 40.0},
            timestamp=_iso(offset_days=1))
        assert detect_fire_drought_heat(s) == []

    def test_stale_drought_snapshot_no_signal(self, state_ca_all_three):
        # Make the snapshot 20 days old.
        state_ca_all_three["synthesis_components"]["drought_snapshot"]["updated_at"] = _iso(offset_days=20)
        assert detect_fire_drought_heat(state_ca_all_three) == []


class TestFireDroughtHeatCooldown:
    def test_within_cooldown_no_signal(self, state_ca_all_three):
        record_synthesis_fired(state_ca_all_three, "fire_drought_heat", "California",
            timestamp=_iso(offset_days=3))
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_after_cooldown_signal_fires(self, state_ca_all_three):
        record_synthesis_fired(state_ca_all_three, "fire_drought_heat", "California",
            timestamp=_iso(offset_days=20))
        assert len(detect_fire_drought_heat(state_ca_all_three)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_synthesis.py -v`
Expected: all FAIL with `ImportError`.

- [ ] **Step 3: Implement `synthesis.py`**

Create `src/editorial/synthesis.py`:

```python
"""Cross-source story synthesis — rules that fire when multiple per-source
signals converge on the same US state within a short window.

See docs/superpowers/specs/2026-04-20-cross-source-synthesis-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, UTC

from src.state import (
    get_synthesis_components,
    get_synthesis_drought_snapshot,
    is_synthesis_on_cooldown,
)

RULE_FIRE_DROUGHT_HEAT = "fire_drought_heat"
WINDOW_DAYS = 14
D4_PCT_MIN = 1.0
SNAPSHOT_TTL_DAYS = 14


@dataclass(frozen=True)
class SynthesisSignal:
    rule_name: str
    region: str
    event_id: str
    headline: str
    components: dict = field(default_factory=dict)
    qualifying_window_days: int = WINDOW_DAYS


def _state_key(region: str) -> str:
    return region.lower().replace(" ", "-")


def _iso_week(today: date | None = None) -> str:
    t = today or date.today()
    y, w, _ = t.isocalendar()
    return f"{y}-W{w:02d}"


def _snapshot_is_fresh(snapshot: dict, ttl_days: int = SNAPSHOT_TTL_DAYS) -> bool:
    updated_at = snapshot.get("updated_at") if snapshot else None
    if not updated_at:
        return False
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (datetime.now(UTC) - dt) < timedelta(days=ttl_days)


def detect_fire_drought_heat(bot_state: dict) -> list[SynthesisSignal]:
    """Emit one SynthesisSignal per US state where D4 drought, a qualifying
    fire, and a qualifying heat record all converge in the last 14 days and
    the rule isn't on cooldown for that state."""
    snapshot = get_synthesis_drought_snapshot(bot_state)
    if not snapshot or not _snapshot_is_fresh(snapshot):
        return []

    since = (datetime.now(UTC) - timedelta(days=WINDOW_DAYS)).isoformat().replace("+00:00", "Z")
    signals: list[SynthesisSignal] = []

    for entry in snapshot.get("entries", []):
        state_name = entry.get("state") or ""
        d4_pct = float(entry.get("d4_pct") or 0)
        if not state_name or d4_pct < D4_PCT_MIN:
            continue
        if is_synthesis_on_cooldown(bot_state, RULE_FIRE_DROUGHT_HEAT, state_name):
            continue

        fires = get_synthesis_components(bot_state, kind="fire", region=state_name, since=since)
        heats = get_synthesis_components(bot_state, kind="heat", region=state_name, since=since)
        if not fires or not heats:
            continue

        peak_fire = max(fires, key=lambda f: float(f.get("frp") or 0))
        peak_heat = max(heats, key=lambda h: abs(float(h.get("value_c") or 0)))

        event_id = f"synthesis_fdh_{_state_key(state_name)}_{_iso_week()}"
        headline = (
            f"{state_name}: D4 drought + {float(peak_fire.get('frp') or 0):.0f} MW fire "
            f"+ {peak_heat.get('city') or 'city'} heat record"
        )
        components = {
            "drought_d4_pct": d4_pct,
            "drought_d3_pct": float(entry.get("d3_pct") or 0),
            "fire_peak_frp": float(peak_fire.get("frp") or 0),
            "fire_peak_region": peak_fire.get("region") or "",
            "fire_count": len(fires),
            "heat_peak_kind": peak_heat.get("kind") or "record",
            "heat_peak_city": peak_heat.get("city") or "",
            "heat_peak_value_c": float(peak_heat.get("value_c") or 0),
            "heat_count": len(heats),
            "window_days": WINDOW_DAYS,
        }
        signals.append(SynthesisSignal(
            rule_name=RULE_FIRE_DROUGHT_HEAT,
            region=state_name,
            event_id=event_id,
            headline=headline,
            components=components,
        ))
    return signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_synthesis.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/synthesis.py tests/test_synthesis.py
git commit -m "feat(synthesis): add Fire×Drought×Heat detection rule"
```

---

## Task 5: `score_synthesis_fire_drought_heat`

**Files:**
- Modify: `src/editorial/scoring.py`
- Modify: `tests/test_editorial_scoring.py`

- [ ] **Step 1: Write failing tests for the scoring function**

Append to `tests/test_editorial_scoring.py`:

```python
class TestScoreSynthesisFireDroughtHeat:
    def test_min_viable_passes_threshold(self):
        from src.editorial.scoring import score_synthesis_fire_drought_heat
        score = score_synthesis_fire_drought_heat(
            drought_d4_pct=1.0,
            fire_peak_frp=250.0,
            heat_peak_anomaly_c=4.0,
            component_count={"fires": 1, "heats": 1},
            heat_kind="calendar",
        )
        assert score.threshold == 82
        assert score.category == "synthesis_fire_drought_heat"
        # Elite by definition — even min-viable should clear 82.
        assert score.total >= 82

    def test_elite_hits_mid_90s(self):
        from src.editorial.scoring import score_synthesis_fire_drought_heat
        score = score_synthesis_fire_drought_heat(
            drought_d4_pct=40.0,
            fire_peak_frp=1500.0,
            heat_peak_anomaly_c=14.0,
            component_count={"fires": 3, "heats": 4},
            heat_kind="all_time",
        )
        assert score.total >= 90
        assert score.passes is True

    def test_reasons_mention_state_of_story(self):
        from src.editorial.scoring import score_synthesis_fire_drought_heat
        score = score_synthesis_fire_drought_heat(
            drought_d4_pct=12.0,
            fire_peak_frp=900.0,
            heat_peak_anomaly_c=8.0,
            component_count={"fires": 2, "heats": 2},
            heat_kind="monthly",
        )
        joined = " ".join(score.reasons).lower()
        assert "drought" in joined or "d4" in joined
        assert "fire" in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_editorial_scoring.py::TestScoreSynthesisFireDroughtHeat -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `score_synthesis_fire_drought_heat`**

Append to `src/editorial/scoring.py`:

```python
def score_synthesis_fire_drought_heat(
    *,
    drought_d4_pct: float,
    fire_peak_frp: float,
    heat_peak_anomaly_c: float,
    component_count: dict,
    heat_kind: str,
) -> EditorialScore:
    """Score a Fire×Drought×Heat synthesis signal.

    Threshold 82 — synthesis is elite by definition. The minimum-viable
    case (1% D4, 250 MW fire, 4 °C anomaly, single fire + single heat)
    is still designed to clear the bar because merely _qualifying_ for
    the rule is itself a story; the scoring factor ranges above that
    reflect the amplification.
    """
    fires_n = int((component_count or {}).get("fires", 0) or 0)
    heats_n = int((component_count or {}).get("heats", 0) or 0)

    severity = 70 + drought_d4_pct * 0.3 + min(fire_peak_frp, 1500) / 25 + min(abs(heat_peak_anomaly_c), 15) * 1.8
    novelty = 88 + (6 if heat_kind == "all_time" else 0)
    timeliness = 90
    confidence = 78
    shareability = 82 + (4 if fires_n >= 2 else 0) + (4 if heats_n >= 2 else 0)
    sensitivity = 28

    reasons = [
        f"{drought_d4_pct:.0f}% in exceptional drought",
        f"peak fire {fire_peak_frp:.0f} MW",
        f"{heat_kind} heat record + {abs(heat_peak_anomaly_c):.1f}C above normal",
    ]
    return _build_score(
        "synthesis_fire_drought_heat",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=sensitivity,
        threshold=82,
        reasons=reasons,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_editorial_scoring.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/scoring.py tests/test_editorial_scoring.py
git commit -m "feat(synthesis): add score_synthesis_fire_drought_heat"
```

---

## Task 6: Approval policy for synthesis

**Files:**
- Modify: `src/editorial/approval.py`
- Modify: `tests/test_editorial_approval.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_editorial_approval.py`:

```python
class TestSynthesisPolicy:
    def test_fire_drought_heat_suggested_auto_120min(self):
        from src.editorial.approval import recommend_approval_policy
        policy = recommend_approval_policy(
            "synthesis_fire_drought_heat",
            signal_total=88,
            candidate_score={"total": 78},
        )
        assert policy.mode == "suggested_auto"
        assert policy.recommended_delay_minutes == 120
        assert policy.can_auto_approve is True
        assert policy.key == "synthesis_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_editorial_approval.py::TestSynthesisPolicy -v`
Expected: FAIL — returns `default_review` policy instead.

- [ ] **Step 3: Add the policy case**

In `src/editorial/approval.py`, insert a new branch before the final default return:

```python
    if tweet_type.startswith("synthesis_"):
        return ApprovalPolicy(
            key="synthesis_review",
            mode="suggested_auto",
            recommended_delay_minutes=120,
            can_auto_approve=True,
            reason="Cross-source synthesis claim — factually brittle by nature. Keep a 120-minute review window so a human can verify the framing before auto-post.",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_editorial_approval.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/approval.py tests/test_editorial_approval.py
git commit -m "feat(synthesis): wire suggested_auto policy with 120-min delay"
```

---

## Task 7: Template + generator for synthesis tweet

**Files:**
- Modify: `src/voice/templates.py`
- Modify: `src/voice/generator.py`
- Modify: `tests/test_generator.py`

- [ ] **Step 1: Write failing test for template fallback**

Append to `tests/test_generator.py`:

```python
class TestSynthesisGenerator:
    def test_template_fallback_no_api_key(self):
        from unittest.mock import patch
        from src.voice.generator import generate_synthesis_fire_drought_heat_tweet
        with patch("src.voice.generator.GEMINI_API_KEY", ""):
            tweet = generate_synthesis_fire_drought_heat_tweet(
                state="California",
                drought_d4_pct=10.0,
                fire_peak_frp=1200.0,
                fire_peak_region="Sacramento County",
                heat_peak_city="Sacramento",
                heat_peak_kind="calendar",
                heat_peak_value_c=40.1,
                window_days=14,
                return_bundle=False,
            )
            assert tweet is not None
            assert "California" in tweet
            # Period-separated cadence, no emojis, no hashtags.
            assert "#" not in tweet
            assert "🔥" not in tweet
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generator.py::TestSynthesisGenerator -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add synthesis prompt to templates.py**

Append to `src/voice/templates.py`:

```python
SYNTHESIS_FIRE_DROUGHT_HEAT_EXTRA = """\
This is a CROSS-SOURCE SYNTHESIS tweet. Three independent data sources \
have converged on a single US state within the last 14 days: the US \
Drought Monitor flagged exceptional (D4) drought, NASA FIRMS flagged a \
qualifying wildfire, and Open-Meteo flagged a qualifying heat record.

Rules for synthesis tweets:
- Anchor the tweet to the state. Name it. The state is the subject.
- Use period-separated short beats. "Drought. Fire. Record heat. All in \
{state}. All this month." NOT commas-and-ands chaining.
- Do NOT invent causality. Do not say the heat caused the fire or the \
drought caused the fire. Report co-occurrence, not causation.
- Use honest time ranges: "in the last 14 days" or specific dates. \
Never "recently" or "now."
- Do not lecture about climate change. Show the three signals. Let the \
reader connect them.
"""


def synthesis_fire_drought_heat_template(
    *, state: str, drought_d4_pct: float,
    fire_peak_frp: float, fire_peak_region: str,
    heat_peak_city: str, heat_peak_kind: str, heat_peak_value_c: float,
    window_days: int = 14,
) -> str:
    d4_round = round(drought_d4_pct)
    frp_round = round(fire_peak_frp)
    return (
        f"{state} in the last {window_days} days: "
        f"{d4_round}% in exceptional drought. "
        f"A {frp_round} MW wildfire flagged near {fire_peak_region or state}. "
        f"{heat_peak_city} on pace for a heat record at {heat_peak_value_c:.1f}C."
    )
```

- [ ] **Step 4: Add generator function to generator.py**

Append to `src/voice/generator.py`:

```python
def generate_synthesis_fire_drought_heat_tweet(
    *,
    state: str,
    drought_d4_pct: float,
    fire_peak_frp: float,
    fire_peak_region: str,
    heat_peak_city: str,
    heat_peak_kind: str,
    heat_peak_value_c: float,
    window_days: int = 14,
    return_bundle: bool = True,
):
    """Generate a Fire×Drought×Heat synthesis tweet through the full pipeline."""
    data_description = (
        f"State: {state}\n"
        f"Drought (US Drought Monitor): {drought_d4_pct:.1f}% of the state in "
        f"exceptional (D4) drought.\n"
        f"Wildfire (NASA FIRMS, last {window_days} days): peak radiative power "
        f"{fire_peak_frp:.0f} MW, nearest region {fire_peak_region or state}.\n"
        f"Heat (Open-Meteo, last {window_days} days): {heat_peak_kind} record at "
        f"{heat_peak_city}, value {heat_peak_value_c:.1f}C.\n"
        f"{templates.SYNTHESIS_FIRE_DROUGHT_HEAT_EXTRA}"
    )

    def fallback(**_kwargs):
        return templates.synthesis_fire_drought_heat_template(
            state=state,
            drought_d4_pct=drought_d4_pct,
            fire_peak_frp=fire_peak_frp,
            fire_peak_region=fire_peak_region,
            heat_peak_city=heat_peak_city,
            heat_peak_kind=heat_peak_kind,
            heat_peak_value_c=heat_peak_value_c,
            window_days=window_days,
        )

    if return_bundle:
        return generate_tweet_bundle(
            data_description,
            category="synthesis_fire_drought_heat",
            fallback_fn=fallback,
            fallback_args={},
        )
    return generate_tweet(
        data_description,
        fallback_fn=fallback,
        fallback_args={},
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_generator.py::TestSynthesisGenerator -v`
Expected: PASS.

- [ ] **Step 6: Run full generator suite to catch regressions**

Run: `pytest tests/test_generator.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/voice/templates.py src/voice/generator.py tests/test_generator.py
git commit -m "feat(synthesis): add compound-framing generator and fallback"
```

---

## Task 8: Wire per-source contributions in `run_alerts`

**Files:**
- Modify: `src/main.py`

This task modifies `run_alerts` to record synthesis components whenever a per-source event passes its standalone gate. Changes are surgical and touch only four sites: Open-Meteo extreme-signals loop, Open-Meteo country records, FIRMS, and the drought section.

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_main.py` (or create a new class if the file lacks one):

```python
class TestSynthesisRecording:
    def test_fire_in_us_records_component(self, monkeypatch):
        from unittest.mock import MagicMock
        from copy import deepcopy
        from src.state import DEFAULT_STATE
        from src import main
        from src.data import firms

        bot_state = deepcopy(DEFAULT_STATE)

        fake_fire = MagicMock(
            event_id="fire_38.58_-121.49_2026-04-20",
            lat=38.58, lon=-121.49,
            nearest_city="Sacramento", country="United States",
            confidence=95, frp=1500.0,
        )
        monkeypatch.setattr(firms, "fetch_fires", lambda: [fake_fire])
        monkeypatch.setattr(main, "_save_generated_draft", lambda *a, **kw: True)
        # Short-circuit open-meteo + others by emptying cities.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities",
                            lambda cities: ([], []))

        main.run_alerts(bot_state)

        fires = bot_state["synthesis_components"]["fires"].get("California", [])
        assert any(f["event_id"] == fake_fire.event_id for f in fires)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main.py::TestSynthesisRecording -v`
Expected: FAIL — fire is drafted but not recorded to synthesis buffer.

- [ ] **Step 3: Add a module-level cities-to-state map cache**

Near the top of `src/main.py` (below existing imports), add:

```python
from src.editorial._regions import cities_to_state_map, lat_lon_to_state
```

Inside `run_alerts`, after `cities = open_meteo.load_cities()` succeeds (around the existing `cities_start` block), build the map:

```python
    us_city_state_map = cities_to_state_map(cities)
```

If `cities` loading fails, default to `us_city_state_map = {}`.

- [ ] **Step 4: Record synthesis components for heat records**

Inside the Open-Meteo extreme-signals loop, at each of the four "strongest signal" branches (`all_time_high`, `monthly_high`, `anomaly_hot`, `calendar_date_high`), **after** the existing `state.record_event(bot_state, strongest_event_id)` call, add:

```python
                    syn_state = us_city_state_map.get(strongest_city)
                    if syn_state:
                        # Approximate anomaly/value_c — we use new_temp_c for
                        # record types and anomaly_c for anomaly events.
                        value_c = getattr(strongest_signal, "new_temp_c", None)
                        if value_c is None:
                            value_c = getattr(strongest_signal, "today_temp_c", 0.0)
                        kind_map = {
                            "all_time_high": "all_time",
                            "monthly_high": "monthly",
                            "anomaly_hot": "anomaly",
                            "record": "calendar",
                        }
                        state.record_synthesis_component(
                            bot_state,
                            kind="heat",
                            region=syn_state,
                            event_id=strongest_event_id,
                            metadata={
                                "kind": kind_map.get(strongest_type, "record"),
                                "city": strongest_city,
                                "value_c": float(value_c or 0),
                            },
                        )
```

For country records (the `for cr in country_records:` loop), **after** the existing `state.record_event(bot_state, cr.event_id)`, add:

```python
            syn_state = us_city_state_map.get(cr.peak_city)
            if syn_state:
                state.record_synthesis_component(
                    bot_state,
                    kind="heat",
                    region=syn_state,
                    event_id=cr.event_id,
                    metadata={
                        "kind": "all_time",
                        "city": cr.peak_city,
                        "value_c": float(cr.new_temp_c or 0),
                    },
                )
```

- [ ] **Step 5: Record synthesis components for fires**

In the FIRMS section, **after** the existing `state.record_event(bot_state, fire.event_id)`, add:

```python
            syn_state = lat_lon_to_state(fire.lat, fire.lon)
            if syn_state:
                state.record_synthesis_component(
                    bot_state,
                    kind="fire",
                    region=syn_state,
                    event_id=fire.event_id,
                    metadata={
                        "frp": float(fire.frp or 0),
                        "region": fire.nearest_city or "",
                    },
                )
```

- [ ] **Step 6: Cache the drought snapshot on Fridays**

In the drought section (around line 1106), **after** the existing drought draft handling completes (or the `if drought_updates:` block, whichever point is reached whenever `drought_updates` is a non-empty list), unconditionally cache the snapshot:

```python
            if drought_updates:
                state.record_synthesis_drought_snapshot(bot_state, drought_updates)
```

Place this immediately after the block that draft-handles `drought_updates`, so the cache is written even if the drought summary tweet doesn't pass its editorial gate.

- [ ] **Step 7: Run the integration test again**

Run: `pytest tests/test_main.py::TestSynthesisRecording -v`
Expected: PASS.

- [ ] **Step 8: Run the full main + synthesis + state suites**

Run: `pytest tests/test_main.py tests/test_state.py tests/test_state_synthesis.py tests/test_synthesis.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(synthesis): wire per-source contributions in run_alerts"
```

---

## Task 9: Wire the synthesis stage at the end of `run_alerts`

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_main.py`:

```python
class TestSynthesisStage:
    def test_synthesis_stage_creates_draft(self, monkeypatch):
        from copy import deepcopy
        from datetime import datetime, timedelta, UTC
        from src.state import (
            DEFAULT_STATE,
            record_synthesis_component,
            record_synthesis_drought_snapshot,
        )
        from src import main

        bot_state = deepcopy(DEFAULT_STATE)
        now = datetime.now(UTC)
        iso = lambda d: (now - timedelta(days=d)).isoformat().replace("+00:00", "Z")

        record_synthesis_drought_snapshot(bot_state, [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
        ])
        record_synthesis_component(bot_state, kind="fire", region="California",
            event_id="pre_fire", metadata={"frp": 1400.0, "region": "Sacramento"},
            timestamp=iso(2))
        record_synthesis_component(bot_state, kind="heat", region="California",
            event_id="pre_heat",
            metadata={"kind": "calendar", "city": "Sacramento", "value_c": 40.0},
            timestamp=iso(1))

        # Short-circuit every per-source fetch so only the synthesis stage runs.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities",
                            lambda cities: ([], []))
        monkeypatch.setattr(main.firms, "fetch_fires", lambda: [])
        # Force _save_generated_draft to return True so we see the synthesis call.
        captured = {}
        def fake_save(generated, state_, tweet_type, event_id, score, **kw):
            captured["tweet_type"] = tweet_type
            captured["event_id"] = event_id
            return True
        monkeypatch.setattr(main, "_save_generated_draft", fake_save)
        # Avoid real Gemini calls.
        monkeypatch.setattr(main.generator, "generate_synthesis_fire_drought_heat_tweet",
                            lambda **kwargs: "fake synthesis tweet")

        main.run_alerts(bot_state)

        assert captured.get("tweet_type") == "synthesis_fire_drought_heat"
        assert "california" in captured["event_id"]
        # Cooldown must have been recorded so a second cycle is suppressed.
        cooldown = bot_state["synthesis_cooldown"].get("fire_drought_heat") or {}
        assert "California" in cooldown
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main.py::TestSynthesisStage -v`
Expected: FAIL — synthesis stage not yet invoked.

- [ ] **Step 3: Add the synthesis stage to `run_alerts`**

Near the top of `src/main.py`, add to imports:

```python
from src.editorial import synthesis
from src.editorial.scoring import score_synthesis_fire_drought_heat
```

At the end of `run_alerts`, **before** the final return, add:

```python
    # --- Cross-source synthesis (runs after every per-source section) ---
    print("[alerts] Running cross-source synthesis...")
    synthesis_start = time.perf_counter()
    synthesis_observed = 0
    synthesis_promoted = 0
    synthesis_drafted = 0
    try:
        signals = synthesis.detect_fire_drought_heat(bot_state)
        synthesis_observed = len(signals)
        for sig in signals:
            if state.is_duplicate(bot_state, sig.event_id):
                continue
            if state.is_synthesis_on_cooldown(bot_state, sig.rule_name, sig.region):
                continue
            comps = sig.components
            score = score_synthesis_fire_drought_heat(
                drought_d4_pct=comps["drought_d4_pct"],
                fire_peak_frp=comps["fire_peak_frp"],
                heat_peak_anomaly_c=comps["heat_peak_value_c"],
                component_count={
                    "fires": comps["fire_count"],
                    "heats": comps["heat_count"],
                },
                heat_kind=comps["heat_peak_kind"],
            )
            synthesis_promoted += 1
            if not _should_draft(score, sig.event_id):
                continue
            generated = generator.generate_synthesis_fire_drought_heat_tweet(
                state=sig.region,
                drought_d4_pct=comps["drought_d4_pct"],
                fire_peak_frp=comps["fire_peak_frp"],
                fire_peak_region=comps["fire_peak_region"],
                heat_peak_city=comps["heat_peak_city"],
                heat_peak_kind=comps["heat_peak_kind"],
                heat_peak_value_c=comps["heat_peak_value_c"],
                window_days=comps["window_days"],
                return_bundle=True,
            )
            review_context = _review_context(
                source="Cross-source synthesis (FIRMS + USDM + Open-Meteo)",
                source_key="synthesis_fire_drought_heat",
                headline=sig.headline,
                current_run=current_run,
                facts=[
                    _fact("State", sig.region),
                    _fact("D4 drought %", f"{comps['drought_d4_pct']:.1f}"),
                    _fact("Peak fire FRP", f"{comps['fire_peak_frp']:.0f} MW"),
                    _fact("Peak heat city", comps["heat_peak_city"]),
                    _fact("Peak heat value", f"{comps['heat_peak_value_c']:.1f}C"),
                    _fact("Window", f"{comps['window_days']} days"),
                ],
            )
            if _save_generated_draft(
                generated, bot_state, "synthesis_fire_drought_heat",
                sig.event_id, score, review_context=review_context,
            ):
                state.record_event(bot_state, sig.event_id)
                state.record_synthesis_fired(bot_state, sig.rule_name, sig.region)
                drafted += 1
                synthesis_drafted += 1
        state.prune_stale_synthesis_components(bot_state)
        _record_source_run(
            current_run, "synthesis_fire_drought_heat", synthesis_start,
            status="success",
            observed=synthesis_observed,
            promoted=synthesis_promoted,
            drafted=synthesis_drafted,
        )
    except Exception as e:
        print(f"[alerts] Synthesis error: {e}")
        state.log_error(bot_state, "synthesis_fire_drought_heat", str(e))
        _record_source_run(
            current_run, "synthesis_fire_drought_heat", synthesis_start,
            status="failed", error=str(e),
        )
```

- [ ] **Step 4: Run the integration test again**

Run: `pytest tests/test_main.py::TestSynthesisStage -v`
Expected: PASS.

- [ ] **Step 5: Run the entire test suite**

Run: `pytest -v`
Expected: all PASS. Investigate any new failures — the synthesis stage must not change the behavior of any other test.

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(synthesis): run Fire×Drought×Heat stage at end of run_alerts"
```

---

## Task 10: Documentation updates

**Files:**
- Modify: `BRIEFING.md`
- Modify: `PIPELINE.md`

- [ ] **Step 1: Add a synthesis paragraph to BRIEFING.md**

Open `BRIEFING.md` and locate the section that summarizes data sources or pipeline capabilities. Append a paragraph like the following (adjust tone to match surrounding prose):

```
### Cross-source synthesis

A meta-detection layer fires a single high-confidence tweet when three
independent signals converge on the same US state within 14 days:
exceptional (D4) drought from USDM, a qualifying wildfire from NASA
FIRMS, and a qualifying heat record from Open-Meteo. The first rule is
`fire_drought_heat`; additional rules (marine heatwave × coastal heat
dome; hurricane × storm surge × river flood) plug into the same
scaffolding.

Synthesis tweets use `suggested_auto` approval with a 120-minute review
window because compound claims are factually more brittle. The
synthesis layer never replaces the per-source tweets — it adds a
compound story on top.
```

- [ ] **Step 2: Add a synthesis block to PIPELINE.md**

Open `PIPELINE.md`. In the mermaid flowchart, add a new node that runs after all per-source sections and before the `POLICY` node. Insert the following edges:

```
    CAP --> SYNTHESIS["Cross-Source Synthesis<br/>rules fire when multiple<br/>sources converge<br/>• fire×drought×heat (US state)<br/>• 14-day window + cooldown<br/>• threshold 82"]:::gen
    SYNTHESIS --> POLICY
```

And in the glossary (the `## Stage Glossary` section), add:

```
### Cross-Source Synthesis

Runs once per alerts cycle after all per-source sections. Each rule
reads from the 14-day rolling buffer in `bot_state["synthesis_components"]`
and the cached USDM snapshot. When a rule's convergence conditions are
met and the per-(rule, state) cooldown is not active, a compound-framing
draft is generated through the full pipeline (candidates → safety →
ranking → evaluator → rewrite validation) and stored with
`suggested_auto` approval and a 120-minute delay.
```

- [ ] **Step 3: Commit**

```bash
git add BRIEFING.md PIPELINE.md
git commit -m "docs(synthesis): document cross-source synthesis stage"
```

---

## Task 11: Final verification and PR prep

- [ ] **Step 1: Full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 2: Manual rule-fire rehearsal**

Open a Python REPL at the repo root and exercise the rule end-to-end:

```python
from copy import deepcopy
from datetime import datetime, timedelta, UTC
from src.state import (DEFAULT_STATE, record_synthesis_component,
    record_synthesis_drought_snapshot)
from src.editorial.synthesis import detect_fire_drought_heat
from src.voice.generator import generate_synthesis_fire_drought_heat_tweet

s = deepcopy(DEFAULT_STATE)
record_synthesis_drought_snapshot(s, [
    {"state": "California", "d3_pct": 28.0, "d4_pct": 12.0, "total_drought_pct": 90.0},
])
now = datetime.now(UTC)
record_synthesis_component(s, kind="fire", region="California",
    event_id="fire_demo", metadata={"frp": 1400.0, "region": "Sacramento"},
    timestamp=(now - timedelta(days=2)).isoformat().replace("+00:00","Z"))
record_synthesis_component(s, kind="heat", region="California",
    event_id="heat_demo",
    metadata={"kind": "calendar", "city": "Sacramento", "value_c": 40.5},
    timestamp=(now - timedelta(days=1)).isoformat().replace("+00:00","Z"))

sigs = detect_fire_drought_heat(s)
print(sigs[0].headline)

c = sigs[0].components
tweet = generate_synthesis_fire_drought_heat_tweet(
    state=sigs[0].region,
    drought_d4_pct=c["drought_d4_pct"],
    fire_peak_frp=c["fire_peak_frp"],
    fire_peak_region=c["fire_peak_region"],
    heat_peak_city=c["heat_peak_city"],
    heat_peak_kind=c["heat_peak_kind"],
    heat_peak_value_c=c["heat_peak_value_c"],
    window_days=c["window_days"],
    return_bundle=False,
)
print(tweet)
```

Capture the printed `headline` and `tweet` for the PR description. Check the tweet satisfies the voice rules (period-separated, no causality invention, honest time range, no press-release opener).

- [ ] **Step 3: Open a draft PR**

Push the branch and open a draft PR:

```bash
git push -u origin andrewzp/synthesis-lane
gh pr create --draft --title "Cross-source synthesis: Fire × Drought × Heat (Lane 4)" --body "$(cat <<'EOF'
## Summary
- Adds a meta-detection layer for cross-source convergences (Lane 4).
- Ships the first rule — Fire × Drought × Heat — plus reusable scaffolding for later rules (marine × coastal, hurricane × surge × flood).
- Threshold 82; `suggested_auto` approval with 120-minute delay.

## Design
Full design: [`docs/superpowers/specs/2026-04-20-cross-source-synthesis-design.md`](../blob/andrewzp/synthesis-lane/docs/superpowers/specs/2026-04-20-cross-source-synthesis-design.md).
Plan: [`docs/superpowers/plans/2026-04-20-cross-source-synthesis.md`](../blob/andrewzp/synthesis-lane/docs/superpowers/plans/2026-04-20-cross-source-synthesis.md).

## Example rule-fire output
> [paste the headline + tweet captured in Task 11 Step 2]

## Test plan
- [x] `pytest tests/test_regions.py`
- [x] `pytest tests/test_state_synthesis.py`
- [x] `pytest tests/test_synthesis.py`
- [x] `pytest tests/test_editorial_scoring.py`
- [x] `pytest tests/test_editorial_approval.py`
- [x] `pytest tests/test_generator.py`
- [x] `pytest tests/test_main.py`
- [x] Full `pytest` suite green
- [x] Manual rule-fire rehearsal (Task 11 Step 2)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage (from `docs/superpowers/specs/2026-04-20-cross-source-synthesis-design.md`):**

| Spec section | Covered by task |
|---|---|
| §2.1 MVP scope | All tasks — only the Fire×Drought×Heat rule is implemented. |
| §2.2 Region matching | Task 1 (bounding boxes + centroid fallback), Task 2 (cities map). |
| §2.3 Cooldown | Task 3 (`is_synthesis_on_cooldown`, `record_synthesis_fired`). |
| §2.4 Gate definitions | Task 4 (`detect_fire_drought_heat` checks D4 ≥ 1, uses 14-day window). |
| §2.5 14-day history | Task 3 (`record_synthesis_component`, `get_synthesis_components`, `prune_stale_synthesis_components`). |
| §2.6 Drought source cache | Task 3 (`record_synthesis_drought_snapshot`), Task 8 (Friday cache write). |
| §2.7 Event_id scheme | Task 4 (`synthesis_fdh_{state_key}_{iso_week}`). |
| §2.8 Full generation pipeline | Task 7 (uses `generate_tweet_bundle` which runs safety + ranking + evaluator + rewrite). |
| §2.9 Threshold 82 | Task 5 (`score_synthesis_fire_drought_heat`, threshold=82). |
| §2.10 Approval policy | Task 6 (`synthesis_review`, `suggested_auto`, 120 min). |
| §2.11 Per-cycle cap | Inherited — Task 9 calls `_save_generated_draft`, which participates in the cap. |
| §2.12 No per-source suppression | No suppression code added — per-source sections remain unchanged beyond adding recording calls. |
| §2.13 Voice rules | Task 7 (`SYNTHESIS_FIRE_DROUGHT_HEAT_EXTRA`). |
| §3 Architecture diagram | Tasks 8 + 9 implement the described flow. |
| §4 Module layout | Task 1 (_regions.py), Task 4 (synthesis.py), Task 3 (state.py), Task 5 (scoring.py), Task 6 (approval.py), Task 7 (templates.py + generator.py), Tasks 8+9 (main.py). |
| §5 Data flow | Tasks 8 + 9 wire it. |
| §6 Region matching rules | Task 1 implementation. |
| §7 Scoring factor design | Task 5 implementation mirrors the spec's factor table. |
| §8 Voice and tweet generation | Task 7. |
| §9 Orchestrator integration | Tasks 8 + 9. |
| §10 Error handling and edge cases | Covered by Task 4 tests (region mismatch, stale, cooldown, missing) + Task 9 try/except. |
| §11 Testing plan | Tasks 1–9 all follow TDD. |
| §12 Rollout — `synthesis_enabled` toggle | **GAP — not in plan. Adding below.** |
| §13 Definition of Done | Task 11 verifies. |
| §14 Non-goals | Respected throughout. |
| §15 Budget | N/A — plan duration is informational. |

**Rollout toggle — added:**

## Task 8a (inserted between Task 8 and Task 9): Add `synthesis_enabled` kill-switch

**Files:** `src/editorial/synthesis.py`, `tests/test_synthesis.py`

- [ ] **Step 1: Failing test**

Append to `tests/test_synthesis.py`:

```python
class TestSynthesisEnabledToggle:
    def test_disabled_returns_empty(self, state_ca_all_three):
        state_ca_all_three["synthesis_enabled"] = False
        assert detect_fire_drought_heat(state_ca_all_three) == []

    def test_default_enabled(self, state_ca_all_three):
        # No synthesis_enabled key → default to enabled.
        assert "synthesis_enabled" not in state_ca_all_three
        assert len(detect_fire_drought_heat(state_ca_all_three)) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_synthesis.py::TestSynthesisEnabledToggle -v`
Expected: `test_disabled_returns_empty` FAILS.

- [ ] **Step 3: Implement toggle check**

In `src/editorial/synthesis.py`, at the very top of `detect_fire_drought_heat` (before the snapshot read), insert:

```python
    if bot_state.get("synthesis_enabled") is False:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_synthesis.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/synthesis.py tests/test_synthesis.py
git commit -m "feat(synthesis): add synthesis_enabled kill-switch"
```

---

**Placeholder scan:** No "TBD", "TODO", "implement later", "add appropriate error handling", or similar placeholders present. All code blocks are complete.

**Type consistency check:**

- `SynthesisSignal.event_id` is a `str` used as `event_id` throughout (Tasks 4, 9).
- `components` dict keys used by the scorer (`drought_d4_pct`, `fire_peak_frp`, `heat_peak_value_c`, `heat_peak_kind`, `fire_count`, `heat_count`, `fire_peak_region`, `heat_peak_city`, `window_days`) match between Task 4 (produced) and Tasks 5 + 7 + 9 (consumed). ✓
- `record_synthesis_component(kind="fire"|"heat", region, event_id, metadata, timestamp)` signature identical in Tasks 3, 4, 8. ✓
- `recommend_approval_policy("synthesis_fire_drought_heat", ...)` key matches Task 6 implementation and Task 9 tweet_type. ✓
- `score_synthesis_fire_drought_heat(drought_d4_pct=, fire_peak_frp=, heat_peak_anomaly_c=, component_count=, heat_kind=)` kwargs match between Tasks 5 and 9. ✓
- `generate_synthesis_fire_drought_heat_tweet(...)` kwargs match between Tasks 7 and 9. ✓

No inconsistencies found.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-cross-source-synthesis.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
