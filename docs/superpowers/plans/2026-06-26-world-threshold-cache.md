# World Threshold Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the world half's live 30-year-archive-per-city-per-run with a cached-threshold model (mirroring the GHCN half) so all ~595 non-US cities get daily record detection without tripping Open-Meteo's rate limit.

**Architecture:** Split `detect_extreme_signals` into a **warm path** (`compute_city_thresholds`: pull a city's 30-yr archive once, store derived thresholds) and a **hot path** (`evaluate_city`: cheap daily forecast vs cached thresholds). A separate gist-file cache store holds thresholds with a union-by-`as_of` merge. A shared Open-Meteo weight accountant paces all callers under the free-tier limits. Records write a provisional threshold on fire (anti-re-fire). Country records gate on a per-country coverage floor. calendar/streak/simultaneous become US-only for the world.

**Tech Stack:** Python 3.x, `requests`, `pytest`, `responses` (HTTP mocking), `ruff`. State persists to a GitHub Gist (`GIST_ID`/`GITHUB_TOKEN`).

**Spec:** `docs/superpowers/specs/2026-06-26-world-threshold-cache-design.md` (v2, post-codex).

## Global Constraints

- **ruff-clean:** no compact one-liners (`if x: return y` → expand; no multi-import on one line). Run `.venv/bin/ruff check src/ tests/` before every commit.
- **Python via `.venv/bin/python`**; every Bash command prefixed `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH`.
- **TDD:** failing test first, watch it fail, minimal code, watch it pass, commit. Stage only your own files (never `git add -A`).
- **No real sleeps in tests** — pacing/clock is injected and fake-clock tested.
- **Weight model (verified from Open-Meteo docs):** weight is **per-location**; forecast (1 day, ≤3 vars) ≈ 1 weight/city; 30-yr daily archive ≈ ~43 weight/city. Free tier: 600/min, 5 000/hr, 10 000/day. Multi-location batching cuts HTTP round-trips, NOT weight.
- **The Hot 10 leaderboard (`src/orchestrator/hot10.py`, `fetch_all_city_temps`, ~638 cities) shares the per-IP budget** — reserve headroom for it.
- **Cache store is a separate gist file** (`world_threshold_cache.json`); `state.json` is never touched by cache writes.
- Branch: `feat/world-threshold-cache` (already exists, holds the spec). One PR at the end.

## File Structure

- `src/data/world_thresholds.py` (NEW) — typed cache records + `compute_city_thresholds` (warm) + `evaluate_city` (hot). Pure; no I/O.
- `src/data/openmeteo_budget.py` (NEW) — `OpenMeteoBudget` weight accountant (pure, injected clock).
- `src/orchestrator/world_cache.py` (NEW) — cache store: gist-file read/write, union-by-`as_of` merge, staleness selection, provisional-on-fire writer.
- `src/data/open_meteo.py` (MODIFY) — add `fetch_forecasts_batch` (multi-location); keep `detect_extreme_signals` as a thin wrapper for the legacy `open_meteo` provider + existing tests.
- `src/orchestrator/sources/open_meteo.py` (MODIFY) — `both` world half rewires to warm+hot+budget; drops calendar/streak/simultaneous for world; emits failure metrics; gates country records.
- `dashboard/` + `tests/` (MODIFY) — update expectations for the dropped world signals.

Tests live beside existing suites: `tests/test_world_thresholds.py`, `tests/test_openmeteo_budget.py`, `tests/test_world_cache.py`, additions to `tests/test_open_meteo.py` and `tests/test_open_meteo_orchestrator.py`.

---

## Phase 1 — Cache foundation

### Task 1: Typed cache records

**Files:**
- Create: `src/data/world_thresholds.py`
- Test: `tests/test_world_thresholds.py`

**Interfaces:**
- Produces: `CityThresholds` dataclass with `to_dict()`/`from_dict()`; fields:
  `city: str`, `as_of: str` (ISO date), `years_of_data: int`,
  `all_time_max: tuple[float,int]|None` (temp_c, year), `all_time_min`,
  `monthly_max: dict[str, tuple[float,int]]` (key "01".."12"), `monthly_min`,
  `monthly_mean: dict[str, tuple[float,float,int]]` (mean_high_c, mean_low_c, sample_count),
  `wetbulb_max: tuple[float,int]|None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_thresholds.py
from src.data.world_thresholds import CityThresholds


def test_city_thresholds_roundtrips_through_dict():
    t = CityThresholds(
        city="Madrid", as_of="2026-06-26", years_of_data=30,
        all_time_max=(44.1, 2023), all_time_min=(-4.2, 2001),
        monthly_max={"06": (43.0, 2019)}, monthly_min={"06": (8.0, 1997)},
        monthly_mean={"06": (32.4, 17.1, 900)}, wetbulb_max=(26.0, 2022),
    )
    again = CityThresholds.from_dict(t.to_dict())
    assert again == t
    assert again.monthly_max["06"] == (43.0, 2019)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py::test_city_thresholds_roundtrips_through_dict -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.world_thresholds'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/world_thresholds.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CityThresholds:
    """Archive-derived thresholds for one non-US city (the warm-path output).

    Tuples are JSON-serialized as lists; from_dict restores them to tuples so
    equality and comparisons are stable.
    """
    city: str
    as_of: str
    years_of_data: int
    all_time_max: tuple[float, int] | None = None
    all_time_min: tuple[float, int] | None = None
    monthly_max: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_min: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_mean: dict[str, tuple[float, float, int]] = field(default_factory=dict)
    wetbulb_max: tuple[float, int] | None = None

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "as_of": self.as_of,
            "years_of_data": self.years_of_data,
            "all_time_max": list(self.all_time_max) if self.all_time_max else None,
            "all_time_min": list(self.all_time_min) if self.all_time_min else None,
            "monthly_max": {k: list(v) for k, v in self.monthly_max.items()},
            "monthly_min": {k: list(v) for k, v in self.monthly_min.items()},
            "monthly_mean": {k: list(v) for k, v in self.monthly_mean.items()},
            "wetbulb_max": list(self.wetbulb_max) if self.wetbulb_max else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityThresholds":
        def _pair(v):
            return tuple(v) if v else None
        return cls(
            city=d["city"],
            as_of=d["as_of"],
            years_of_data=int(d.get("years_of_data", 0)),
            all_time_max=_pair(d.get("all_time_max")),
            all_time_min=_pair(d.get("all_time_min")),
            monthly_max={k: tuple(v) for k, v in (d.get("monthly_max") or {}).items()},
            monthly_min={k: tuple(v) for k, v in (d.get("monthly_min") or {}).items()},
            monthly_mean={k: tuple(v) for k, v in (d.get("monthly_mean") or {}).items()},
            wetbulb_max=_pair(d.get("wetbulb_max")),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/world_thresholds.py tests/test_world_thresholds.py
git commit -m "feat: typed CityThresholds cache record"
```

### Task 2: `compute_city_thresholds` (warm computation)

**Files:**
- Modify: `src/data/world_thresholds.py`
- Test: `tests/test_world_thresholds.py`

**Interfaces:**
- Consumes: an Open-Meteo archive `daily` dict: `{"time": [iso...], "temperature_2m_max": [...], "temperature_2m_min": [...], "wet_bulb_temperature_2m_max": [...]}`.
- Produces: `compute_city_thresholds(city: str, archive_daily: dict, *, as_of: str, years_of_data: int = 30) -> CityThresholds`. Mirrors the one-pass loop at `src/data/open_meteo.py:651-727` but emits per-month max/min/mean + all-time + wetbulb (NOT calendar-date).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_thresholds.py (append)
from src.data.world_thresholds import compute_city_thresholds


def test_compute_city_thresholds_derives_all_time_monthly_mean_wetbulb():
    archive = {
        "time": ["1996-06-01", "1996-06-02", "1996-07-01", "2005-06-01"],
        "temperature_2m_max": [40.0, 42.0, 45.0, 41.0],
        "temperature_2m_min": [10.0, 9.0, 20.0, 11.0],
        "wet_bulb_temperature_2m_max": [24.0, 25.0, 26.0, 23.0],
    }
    t = compute_city_thresholds("Testville", archive, as_of="2026-06-26", years_of_data=30)
    assert t.all_time_max == (45.0, 2005) or t.all_time_max == (45.0, 1996)  # 45.0 is July 1996
    assert t.all_time_max[0] == 45.0
    assert t.all_time_min == (9.0, 1996)
    assert t.monthly_max["06"][0] == 42.0     # hottest June day across 1996+2005
    assert t.monthly_min["06"][0] == 9.0
    # June mean of highs over [40,42,41] = 41.0 ; sample_count = 3
    assert t.monthly_mean["06"][0] == 41.0
    assert t.monthly_mean["06"][2] == 3
    assert t.wetbulb_max[0] == 26.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py::test_compute_city_thresholds_derives_all_time_monthly_mean_wetbulb -q`
Expected: FAIL — `ImportError: cannot import name 'compute_city_thresholds'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/world_thresholds.py (append)
from datetime import date


def compute_city_thresholds(
    city: str,
    archive_daily: dict,
    *,
    as_of: str,
    years_of_data: int = 30,
) -> CityThresholds:
    dates = archive_daily.get("time", []) or []
    highs = archive_daily.get("temperature_2m_max", []) or []
    lows = archive_daily.get("temperature_2m_min", []) or []
    tws = archive_daily.get("wet_bulb_temperature_2m_max", []) or []

    at_max: tuple[float, int] | None = None
    at_min: tuple[float, int] | None = None
    m_max: dict[str, tuple[float, int]] = {}
    m_min: dict[str, tuple[float, int]] = {}
    high_sums: dict[str, float] = {}
    low_sums: dict[str, float] = {}
    counts: dict[str, int] = {}

    for i, d_str in enumerate(dates):
        try:
            d = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue
        mm = f"{d.month:02d}"
        hi = highs[i] if i < len(highs) else None
        lo = lows[i] if i < len(lows) else None
        if hi is not None:
            if at_max is None or hi > at_max[0]:
                at_max = (hi, d.year)
            if mm not in m_max or hi > m_max[mm][0]:
                m_max[mm] = (hi, d.year)
            high_sums[mm] = high_sums.get(mm, 0.0) + hi
            counts[mm] = counts.get(mm, 0) + 1
        if lo is not None:
            if at_min is None or lo < at_min[0]:
                at_min = (lo, d.year)
            if mm not in m_min or lo < m_min[mm][0]:
                m_min[mm] = (lo, d.year)
            low_sums[mm] = low_sums.get(mm, 0.0) + lo

    m_mean: dict[str, tuple[float, float, int]] = {}
    for mm, n in counts.items():
        if n <= 0:
            continue
        m_mean[mm] = (
            round(high_sums.get(mm, 0.0) / n, 2),
            round(low_sums.get(mm, 0.0) / n, 2),
            n,
        )

    wb_max: tuple[float, int] | None = None
    for i, tw in enumerate(tws):
        if tw is None:
            continue
        try:
            yr = date.fromisoformat(dates[i]).year
        except (ValueError, TypeError, IndexError):
            continue
        if wb_max is None or tw > wb_max[0]:
            wb_max = (tw, yr)

    return CityThresholds(
        city=city, as_of=as_of, years_of_data=years_of_data,
        all_time_max=at_max, all_time_min=at_min,
        monthly_max=m_max, monthly_min=m_min, monthly_mean=m_mean,
        wetbulb_max=wb_max,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py -q` → PASS
(Note: in the fixture, the all-time max 45.0 falls on 1996-07-01 → assert checks `[0] == 45.0`.)

- [ ] **Step 5: Commit**

```bash
git add src/data/world_thresholds.py tests/test_world_thresholds.py
git commit -m "feat: compute_city_thresholds warm-path derivation"
```

### Task 3: Cache store — read/write/merge/staleness

**Files:**
- Create: `src/orchestrator/world_cache.py`
- Test: `tests/test_world_cache.py`

**Interfaces:**
- Produces:
  - `merge_caches(base: dict, nxt: dict) -> dict` — union by city, newest `as_of` wins; tie → keep the one with the more extreme `all_time_max` (defensive). Pure.
  - `select_stale_cities(cache: dict, world_cities: list[dict], *, ttl_days: int, budget: int, today: str, urgent_order: list[str]) -> list[dict]` — missing-or-older-than-ttl cities, urgent-first then oldest `as_of`, capped at `budget`. Pure.
  - `WORLD_CACHE_FILENAME = "world_threshold_cache.json"`.
  - (gist read/write `read_cache()/write_cache(cache)` mirror `_read_gist_state`/`_write_gist_state` but for `WORLD_CACHE_FILENAME`; covered by Task 11 integration, unit-tested via the pure functions here.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_cache.py
from src.orchestrator.world_cache import merge_caches, select_stale_cities


def test_merge_keeps_newest_as_of_per_city_and_unions():
    base = {"Madrid": {"city": "Madrid", "as_of": "2026-06-01"},
            "Lyon": {"city": "Lyon", "as_of": "2026-06-20"}}
    nxt = {"Madrid": {"city": "Madrid", "as_of": "2026-06-25"},  # newer -> wins
           "Paris": {"city": "Paris", "as_of": "2026-06-25"}}    # new city -> added
    out = merge_caches(base, nxt)
    assert out["Madrid"]["as_of"] == "2026-06-25"
    assert out["Lyon"]["as_of"] == "2026-06-20"   # base-only survives (NOT clobbered)
    assert out["Paris"]["as_of"] == "2026-06-25"


def test_select_stale_prefers_urgent_then_oldest_and_caps():
    world = [{"city": c, "country": "X", "lat": "0", "lon": "0"}
             for c in ["Madrid", "Lyon", "Zzz", "Aaa"]]
    cache = {"Madrid": {"as_of": "2026-06-25"},   # fresh
             "Lyon": {"as_of": "2026-04-01"},     # stale
             "Aaa": {"as_of": "2026-04-01"}}      # stale; Zzz missing
    out = select_stale_cities(
        cache, world, ttl_days=30, budget=2, today="2026-06-26",
        urgent_order=["Lyon", "Madrid"],
    )
    names = [c["city"] for c in out]
    assert "Lyon" in names                # urgent + stale -> first
    assert "Madrid" not in names          # fresh -> excluded
    assert len(out) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_world_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.orchestrator.world_cache'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/world_cache.py
from __future__ import annotations

from datetime import date, timedelta

WORLD_CACHE_FILENAME = "world_threshold_cache.json"


def _as_of(entry: dict) -> str:
    return str((entry or {}).get("as_of") or "")


def merge_caches(base: dict, nxt: dict) -> dict:
    """Union by city; newest as_of wins. Never clobbers a city present on only
    one side (the bug _strat_take_incoming would cause)."""
    base = base or {}
    nxt = nxt or {}
    out: dict = {}
    for city in sorted(set(base) | set(nxt)):
        b = base.get(city)
        n = nxt.get(city)
        if b is None:
            out[city] = n
        elif n is None:
            out[city] = b
        elif _as_of(n) >= _as_of(b):
            out[city] = n
        else:
            out[city] = b
    return out


def _is_stale(entry: dict | None, *, ttl_days: int, today: str) -> bool:
    if not entry or not entry.get("as_of"):
        return True
    try:
        return date.fromisoformat(entry["as_of"]) < date.fromisoformat(today) - timedelta(days=ttl_days)
    except (ValueError, TypeError):
        return True


def select_stale_cities(
    cache: dict,
    world_cities: list[dict],
    *,
    ttl_days: int,
    budget: int,
    today: str,
    urgent_order: list[str],
) -> list[dict]:
    by_name: dict[str, dict] = {}
    for c in world_cities:
        by_name.setdefault(c.get("city"), c)

    stale = [c for c in world_cities if _is_stale(cache.get(c.get("city")), ttl_days=ttl_days, today=today)]
    rank = {name: i for i, name in enumerate(urgent_order)}

    def sort_key(c: dict):
        name = c.get("city")
        urgent_rank = rank.get(name, len(urgent_order))
        as_of = _as_of(cache.get(name))  # "" (missing) sorts first -> oldest first
        return (urgent_rank, as_of, name)

    stale.sort(key=sort_key)
    # dedup by name, cap at budget
    out: list[dict] = []
    seen: set[str] = set()
    for c in stale:
        name = c.get("city")
        if name in seen:
            continue
        seen.add(name)
        out.append(c)
        if len(out) >= budget:
            break
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_world_cache.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/world_cache.py tests/test_world_cache.py
git commit -m "feat: world cache merge (union-by-as_of) + staleness selection"
```

---

## Phase 2 — Hot path

### Task 4: Multi-location forecast fetch

**Files:**
- Modify: `src/data/open_meteo.py`
- Test: `tests/test_open_meteo.py`

**Interfaces:**
- Produces: `fetch_forecasts_batch(cities: list[dict]) -> dict[str, dict]` mapping `city name -> {"max_c","min_c","tw_max_c"}`. Issues ONE multi-location forecast call (comma-separated lat/lon); Open-Meteo returns a list of per-location dicts in input order. Returns `{}` on failure (best-effort).

- [ ] **Step 1: Write the failing test** (mock the HTTP with `responses`)

```python
# tests/test_open_meteo.py (append; `responses` already imported at top)
@responses.activate
def test_fetch_forecasts_batch_maps_cities_to_today_values():
    responses.add(
        responses.GET, "https://api.open-meteo.com/v1/forecast",
        json=[
            {"daily": {"temperature_2m_max": [44.0], "temperature_2m_min": [20.0],
                       "wet_bulb_temperature_2m_max": [26.0]}},
            {"daily": {"temperature_2m_max": [39.0], "temperature_2m_min": [18.0],
                       "wet_bulb_temperature_2m_max": [24.0]}},
        ],
        status=200,
    )
    cities = [
        {"city": "Madrid", "lat": "40.4", "lon": "-3.7"},
        {"city": "Lyon", "lat": "45.7", "lon": "4.8"},
    ]
    out = _open_meteo_module.fetch_forecasts_batch(cities)
    assert out["Madrid"]["max_c"] == 44.0
    assert out["Lyon"]["min_c"] == 18.0
    assert out["Madrid"]["tw_max_c"] == 26.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_open_meteo.py::test_fetch_forecasts_batch_maps_cities_to_today_values -q`
Expected: FAIL — `AttributeError: module 'src.data.open_meteo' has no attribute 'fetch_forecasts_batch'`

- [ ] **Step 3: Write minimal implementation** (add near `fetch_all_city_temps`)

```python
# src/data/open_meteo.py (append a new function)
def fetch_forecasts_batch(cities: list[dict]) -> dict[str, dict]:
    """One multi-location forecast call -> {city: {max_c,min_c,tw_max_c}}.

    Open-Meteo accepts comma-separated coordinates and returns a list of
    per-location daily blocks in input order. Best-effort: returns {} on any
    failure (the caller treats missing cities as "not evaluated this run").
    """
    if not cities:
        return {}
    lats = ",".join(str(c["lat"]) for c in cities)
    lons = ",".join(str(c["lon"]) for c in cities)
    try:
        resp = fetch_with_retry(
            f"{BASE_URL}/forecast",
            params={
                "latitude": lats,
                "longitude": lons,
                "daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return {}
    blocks = payload if isinstance(payload, list) else [payload]
    out: dict[str, dict] = {}
    for city, block in zip(cities, blocks):
        daily = (block or {}).get("daily", {}) or {}
        out[city["city"]] = {
            "max_c": (daily.get("temperature_2m_max") or [None])[0],
            "min_c": (daily.get("temperature_2m_min") or [None])[0],
            "tw_max_c": (daily.get("wet_bulb_temperature_2m_max") or [None])[0],
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_open_meteo.py::test_fetch_forecasts_batch_maps_cities_to_today_values -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/open_meteo.py tests/test_open_meteo.py
git commit -m "feat: multi-location fetch_forecasts_batch"
```

### Task 5: `evaluate_city` (hot comparison)

**Files:**
- Modify: `src/data/world_thresholds.py`
- Test: `tests/test_world_thresholds.py`

**Interfaces:**
- Consumes: `CityThresholds`; a forecast `{"max_c","min_c","tw_max_c"}`; `country`, `lat`, `lon`, `today: date`.
- Produces: `evaluate_city(city, country, forecast, cached, *, lat, lon, today) -> ExtremeSignalBundle`. Emits `all_time_high/low`, `monthly_high/low`, `anomaly_hot/cold`, `wet_bulb_extreme`, and populates `today_*`/`archive_*` for country aggregation. Does NOT emit `calendar_date_*` (world drops it). Reuses the event dataclasses + `WETBULB_TIERS`/`ANOMALY_*_THRESHOLD_C` from `open_meteo.py`. `absolute_extreme` is added by the orchestrator via the existing `detect_absolute_extreme` (band-based, no cache).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_thresholds.py (append)
from datetime import date as _date
from src.data.world_thresholds import evaluate_city, CityThresholds


def _cached():
    return CityThresholds(
        city="Madrid", as_of="2026-06-01", years_of_data=30,
        all_time_max=(44.0, 2023), all_time_min=(-4.0, 2001),
        monthly_max={"06": (43.0, 2019)}, monthly_min={"06": (8.0, 1997)},
        monthly_mean={"06": (32.0, 17.0, 900)}, wetbulb_max=(26.0, 2022),
    )


def test_evaluate_emits_all_time_high_when_forecast_exceeds_cached():
    b = evaluate_city(
        "Madrid", "Spain", {"max_c": 45.5, "min_c": 22.0, "tw_max_c": 24.0},
        _cached(), lat=40.4, lon=-3.7, today=_date(2026, 6, 26),
    )
    assert b.all_time_high is not None
    assert b.all_time_high.new_temp_c == 45.5
    assert b.all_time_high.old_record_c == 44.0
    assert b.calendar_date_high is None   # world drops calendar-date


def test_evaluate_emits_anomaly_hot_vs_cached_mean():
    b = evaluate_city(
        "Madrid", "Spain", {"max_c": 48.0, "min_c": 20.0, "tw_max_c": 24.0},
        _cached(), lat=40.4, lon=-3.7, today=_date(2026, 6, 26),
    )
    # 48 - mean 32 = 16 >= ANOMALY_HOT_THRESHOLD_C (15)
    assert b.anomaly_hot is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py::test_evaluate_emits_all_time_high_when_forecast_exceeds_cached -q`
Expected: FAIL — `ImportError: cannot import name 'evaluate_city'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/world_thresholds.py (append)
from src.data.open_meteo import (
    AllTimeRecord, MonthlyRecord, AnomalyEvent, WetBulbEvent, ExtremeSignalBundle,
    WETBULB_TIERS, ANOMALY_HOT_THRESHOLD_C, ANOMALY_COLD_THRESHOLD_C,
)


def evaluate_city(
    city: str, country: str, forecast: dict, cached: CityThresholds,
    *, lat: float, lon: float, today,
) -> ExtremeSignalBundle:
    today_max = forecast.get("max_c")
    today_min = forecast.get("min_c")
    tw_max = forecast.get("tw_max_c")
    iso = today.isoformat()
    key = city.replace(" ", "_")
    mm = f"{today.month:02d}"
    yrs = cached.years_of_data

    b = ExtremeSignalBundle(city=city, country=country, today_max_c=today_max, today_min_c=today_min)
    if cached.all_time_max is not None:
        b.archive_max_c, b.archive_max_year = cached.all_time_max
    if cached.all_time_min is not None:
        b.archive_min_c, b.archive_min_year = cached.all_time_min

    if today_max is not None and cached.all_time_max is not None and today_max > cached.all_time_max[0]:
        b.all_time_high = AllTimeRecord(
            city=city, country=country, kind="high", new_temp_c=today_max,
            old_record_c=cached.all_time_max[0], old_record_year=cached.all_time_max[1],
            years_of_data=yrs, event_id=f"alltime_high_{key}_{iso}", lat=lat, lon=lon,
        )
    if today_min is not None and cached.all_time_min is not None and today_min < cached.all_time_min[0]:
        b.all_time_low = AllTimeRecord(
            city=city, country=country, kind="low", new_temp_c=today_min,
            old_record_c=cached.all_time_min[0], old_record_year=cached.all_time_min[1],
            years_of_data=yrs, event_id=f"alltime_low_{key}_{iso}", lat=lat, lon=lon,
        )

    mhi = cached.monthly_max.get(mm)
    if today_max is not None and mhi is not None and today_max > mhi[0]:
        b.monthly_high = MonthlyRecord(
            city=city, country=country, kind="high", month=today.month, new_temp_c=today_max,
            old_record_c=mhi[0], old_record_year=mhi[1], years_of_data=yrs,
            event_id=f"monthly_high_{key}_{today.year}_{today.month:02d}", lat=lat, lon=lon,
        )
    mlo = cached.monthly_min.get(mm)
    if today_min is not None and mlo is not None and today_min < mlo[0]:
        b.monthly_low = MonthlyRecord(
            city=city, country=country, kind="low", month=today.month, new_temp_c=today_min,
            old_record_c=mlo[0], old_record_year=mlo[1], years_of_data=yrs,
            event_id=f"monthly_low_{key}_{today.year}_{today.month:02d}", lat=lat, lon=lon,
        )

    mean = cached.monthly_mean.get(mm)
    if today_max is not None and mean is not None:
        anom = today_max - mean[0]
        if anom >= ANOMALY_HOT_THRESHOLD_C:
            b.anomaly_hot = AnomalyEvent(
                city=city, country=country, today_temp_c=today_max, historical_mean_c=mean[0],
                anomaly_c=anom, years_of_data=yrs, event_id=f"anomaly_hot_{key}_{iso}", lat=lat, lon=lon,
            )
    if today_min is not None and mean is not None:
        anom = today_min - mean[1]
        if anom <= -ANOMALY_COLD_THRESHOLD_C:
            b.anomaly_cold = AnomalyEvent(
                city=city, country=country, today_temp_c=today_min, historical_mean_c=mean[1],
                anomaly_c=anom, years_of_data=yrs, event_id=f"anomaly_cold_{key}_{iso}", lat=lat, lon=lon,
            )

    if tw_max is not None:
        for tier_index, threshold_c, tier_label in WETBULB_TIERS:
            if tw_max < threshold_c:
                continue
            amx = cached.wetbulb_max
            b.wet_bulb_extreme = WetBulbEvent(
                city=city, country=country, daily_max_tw_c=tw_max, tier=tier_index,
                tier_label=tier_label, tier_threshold_c=threshold_c,
                event_id=f"wetbulb_{key}_{iso}_tier{tier_index}", signal_date=today, lat=lat, lon=lon,
                archive_max_tw_c=(amx[0] if amx else None),
                archive_max_year=(amx[1] if amx else None), archive_years=yrs,
            )
            break
    return b
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/world_thresholds.py tests/test_world_thresholds.py
git commit -m "feat: evaluate_city hot-path comparison (no calendar-date)"
```

### Task 6: Provisional-on-fire writer (anti-re-fire)

**Files:**
- Modify: `src/orchestrator/world_cache.py`
- Test: `tests/test_world_cache.py`

**Interfaces:**
- Produces: `apply_provisional(cache: dict, bundle: ExtremeSignalBundle, *, today: str) -> None` — mutates `cache[city]` in place so a fired all-time/monthly record's new value becomes the cached threshold (`as_of=today`), so the next run does NOT re-fire the same record. Creates the city entry if absent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_cache.py (append)
from datetime import date as _date
from src.orchestrator.world_cache import apply_provisional
from src.data.world_thresholds import evaluate_city, CityThresholds


def test_provisional_threshold_prevents_re_fire_next_run():
    cache_obj = CityThresholds(
        city="Madrid", as_of="2026-06-01", years_of_data=30,
        all_time_max=(44.0, 2023), monthly_max={"06": (43.0, 2019)},
    )
    cache = {"Madrid": cache_obj.to_dict()}
    fc = {"max_c": 45.5, "min_c": 20.0, "tw_max_c": 10.0}
    b1 = evaluate_city("Madrid", "Spain", fc, CityThresholds.from_dict(cache["Madrid"]),
                       lat=40.4, lon=-3.7, today=_date(2026, 6, 26))
    assert b1.all_time_high is not None         # fires once
    apply_provisional(cache, b1, today="2026-06-26")
    b2 = evaluate_city("Madrid", "Spain", fc, CityThresholds.from_dict(cache["Madrid"]),
                       lat=40.4, lon=-3.7, today=_date(2026, 6, 27))
    assert b2.all_time_high is None             # does NOT re-fire
    assert cache["Madrid"]["all_time_max"][0] == 45.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_world_cache.py::test_provisional_threshold_prevents_re_fire_next_run -q`
Expected: FAIL — `ImportError: cannot import name 'apply_provisional'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/world_cache.py (append)
from src.data.world_thresholds import CityThresholds


def apply_provisional(cache: dict, bundle, *, today: str) -> None:
    city = bundle.city
    entry = cache.get(city)
    t = CityThresholds.from_dict(entry) if entry else CityThresholds(city=city, as_of=today, years_of_data=0)
    if bundle.all_time_high is not None:
        t.all_time_max = (bundle.all_time_high.new_temp_c, today_year(today))
    if bundle.all_time_low is not None:
        t.all_time_min = (bundle.all_time_low.new_temp_c, today_year(today))
    if bundle.monthly_high is not None:
        t.monthly_max[f"{bundle.monthly_high.month:02d}"] = (bundle.monthly_high.new_temp_c, today_year(today))
    if bundle.monthly_low is not None:
        t.monthly_min[f"{bundle.monthly_low.month:02d}"] = (bundle.monthly_low.new_temp_c, today_year(today))
    t.as_of = today
    cache[city] = t.to_dict()


def today_year(today: str) -> int:
    return date.fromisoformat(today).year
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_world_cache.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/world_cache.py tests/test_world_cache.py
git commit -m "feat: provisional-on-fire cache write (anti-re-fire)"
```

---

## Phase 3 — Rate budget

### Task 7: Open-Meteo weight accountant

**Files:**
- Create: `src/data/openmeteo_budget.py`
- Test: `tests/test_openmeteo_budget.py`

**Interfaces:**
- Produces: `OpenMeteoBudget(*, per_minute, per_hour, per_day, reserve, clock)` where `clock() -> float` (monotonic seconds, injected). Methods: `can_spend(weight) -> bool` (against minute/hour/day rolling windows minus `reserve`), `spend(weight)`, `forecast_batch_size(remaining_cities) -> int` (largest batch that fits the current minute headroom at weight 1/city). Pure; fake-clock tested (no real time).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openmeteo_budget.py
from src.data.openmeteo_budget import OpenMeteoBudget


def test_minute_window_caps_then_recovers():
    now = {"t": 0.0}
    b = OpenMeteoBudget(per_minute=100, per_hour=10_000, per_day=100_000, reserve=0, clock=lambda: now["t"])
    assert b.forecast_batch_size(500) == 100      # full minute budget
    b.spend(100)
    assert b.can_spend(1) is False                # minute exhausted
    now["t"] = 61.0                               # minute rolls
    assert b.can_spend(1) is True
    assert b.forecast_batch_size(500) == 100


def test_reserve_is_held_back():
    b = OpenMeteoBudget(per_minute=100, per_hour=10_000, per_day=100_000, reserve=40, clock=lambda: 0.0)
    assert b.forecast_batch_size(500) == 60       # 100 - 40 reserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_openmeteo_budget.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.openmeteo_budget'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/openmeteo_budget.py
from __future__ import annotations

from collections import deque
from collections.abc import Callable


class OpenMeteoBudget:
    """Rolling weight accountant shared by every Open-Meteo caller.

    Weight is per-location. `reserve` is headroom held back from the minute
    window (e.g. for the Hot 10 leaderboard / retries). `clock` is injected
    monotonic seconds so pacing is fake-clock testable.
    """

    def __init__(self, *, per_minute: int, per_hour: int, per_day: int, reserve: int, clock: Callable[[], float]):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day
        self.reserve = reserve
        self._clock = clock
        self._events: deque[tuple[float, int]] = deque()  # (timestamp, weight)

    def _spent_within(self, seconds: float) -> int:
        cutoff = self._clock() - seconds
        return sum(w for t, w in self._events if t >= cutoff)

    def _prune(self) -> None:
        cutoff = self._clock() - 86_400
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def remaining_minute(self) -> int:
        return max(0, self.per_minute - self.reserve - self._spent_within(60))

    def can_spend(self, weight: int) -> bool:
        return (
            self._spent_within(60) + weight <= self.per_minute - self.reserve
            and self._spent_within(3600) + weight <= self.per_hour
            and self._spent_within(86_400) + weight <= self.per_day
        )

    def spend(self, weight: int) -> None:
        self._prune()
        self._events.append((self._clock(), weight))

    def forecast_batch_size(self, remaining_cities: int) -> int:
        return max(0, min(remaining_cities, self.remaining_minute()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_openmeteo_budget.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/openmeteo_budget.py tests/test_openmeteo_budget.py
git commit -m "feat: OpenMeteoBudget rolling weight accountant"
```

---

## Phase 4 — Correctness & safety

### Task 8: Country-record coverage floor

**Files:**
- Modify: `src/data/open_meteo.py` (`detect_country_records`, ~line 822)
- Test: `tests/test_open_meteo.py`

**Interfaces:**
- Modify `detect_country_records(readings, *, archive_years=30, min_cities_per_country=2, country_eligibility: dict[str,int] | None = None)` — when `country_eligibility` is provided, require the number of sampled cities for a country to equal its eligible (configured) count before emitting a `CountryRecord`; record `cities_sampled` already exists on `CountryRecord`. Default `None` preserves current behavior (keeps existing tests green).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_open_meteo.py (append)
def test_country_records_suppressed_below_coverage_floor():
    from src.data.open_meteo import detect_country_records, ExtremeSignalBundle
    # Spain has 3 configured cities but only 1 sampled this run.
    readings = [ExtremeSignalBundle(city="Madrid", country="Spain", today_max_c=48.0, archive_max_c=44.0, archive_max_year=2023)]
    out = detect_country_records(readings, country_eligibility={"Spain": 3})
    assert out == []   # 1 of 3 -> below floor -> no false national record
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_open_meteo.py::test_country_records_suppressed_below_coverage_floor -q`
Expected: FAIL — `TypeError: detect_country_records() got an unexpected keyword argument 'country_eligibility'`

- [ ] **Step 3: Write minimal implementation** — add the kwarg and, inside the per-country loop (after computing `cities_sampled` for the country), `continue` when `country_eligibility is not None and cities_sampled < country_eligibility.get(country, cities_sampled)`. Read the existing body at `src/data/open_meteo.py:822-905` and insert the guard where a `CountryRecord` is about to be appended.

- [ ] **Step 4: Run test to verify it passes** (and the existing country-record tests still pass)

Run: `.venv/bin/python -m pytest tests/test_open_meteo.py -k country -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/data/open_meteo.py tests/test_open_meteo.py
git commit -m "feat: country-record per-country coverage floor"
```

### Task 9: Failure-surfacing metrics

**Files:**
- Modify: `src/orchestrator/sources/open_meteo.py` (the `both` world metrics + status)
- Test: `tests/test_open_meteo_orchestrator.py`

**Interfaces:**
- The world half populates `open_meteo_pipeline_metrics` with: `world_total`, `cached_count`, `forecast_attempted`, `forecast_failures`, `warm_attempted`, `warm_failures`, `coverage_ratio`. A pure helper `classify_world_status(metrics) -> "success"|"degraded"` (in `src/orchestrator/world_cache.py`) returns `degraded` when steady-state `coverage_ratio` < floor OR warm/forecast failures spike; bootstrap (`cached_count < world_total` and climbing) stays `success`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_open_meteo_orchestrator.py (append)
def test_classify_world_status_degrades_on_low_coverage():
    from src.orchestrator.world_cache import classify_world_status
    assert classify_world_status({"world_total": 595, "cached_count": 595,
                                  "coverage_ratio": 0.2, "forecast_failures": 0,
                                  "warm_failures": 0}) == "degraded"
    assert classify_world_status({"world_total": 595, "cached_count": 595,
                                  "coverage_ratio": 0.98, "forecast_failures": 0,
                                  "warm_failures": 0}) == "success"
    # bootstrap: not yet warmed, low coverage is expected -> success
    assert classify_world_status({"world_total": 595, "cached_count": 40,
                                  "coverage_ratio": 0.07, "forecast_failures": 0,
                                  "warm_failures": 0}) == "success"
```

- [ ] **Step 2: Run test to verify it fails** → `ImportError: cannot import name 'classify_world_status'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/orchestrator/world_cache.py (append)
WORLD_COVERAGE_FLOOR = 0.85
WORLD_WARM_FAILURE_FLOOR = 0.5


def classify_world_status(m: dict) -> str:
    total = int(m.get("world_total", 0) or 0)
    cached = int(m.get("cached_count", 0) or 0)
    warm_attempted = int(m.get("warm_attempted", 0) or 0)
    warm_failures = int(m.get("warm_failures", 0) or 0)
    if total > 0 and cached >= total:  # steady-state
        if float(m.get("coverage_ratio", 1.0)) < WORLD_COVERAGE_FLOOR:
            return "degraded"
    if warm_attempted > 0 and warm_failures / warm_attempted > WORLD_WARM_FAILURE_FLOOR:
        return "degraded"
    return "success"
```

- [ ] **Step 4: Run test to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/world_cache.py tests/test_open_meteo_orchestrator.py
git commit -m "feat: world-half failure-surfacing classifier"
```

### Task 10: Drop calendar/streak/simultaneous for the world path

**Files:**
- Modify: `src/orchestrator/sources/open_meteo.py`
- Modify: `dashboard/` event-log expectation (grep `simultaneous`/`streak` in `dashboard/lib`), `tests/` that assert world streak/simultaneous.
- Test: `tests/test_open_meteo_orchestrator.py`

**Note:** With Task 11, the world half iterates `evaluate_city` bundles which never set `calendar_date_*`, so streak (`open_meteo.py:459` guard `bundle.calendar_date_high`) and simultaneous (the calendar block ~269) naturally do not fire for world cities. This task makes that explicit + updates any test/dashboard asserting otherwise.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_open_meteo_orchestrator.py (append)
def test_world_path_emits_no_calendar_streak_or_simultaneous(monkeypatch):
    """World evaluate_city bundles never carry calendar_date_high, so streak +
    simultaneous lanes stay empty for non-US cities."""
    from src.data.world_thresholds import evaluate_city, CityThresholds
    from datetime import date
    cached = CityThresholds(city="Lyon", as_of="2026-06-01", years_of_data=30,
                            all_time_max=(40.0, 2019), monthly_max={"06": (39.0, 2019)})
    b = evaluate_city("Lyon", "France", {"max_c": 45.0, "min_c": 20.0, "tw_max_c": 10.0},
                      cached, lat=45.7, lon=4.8, today=date(2026, 6, 26))
    assert b.calendar_date_high is None and b.calendar_date_low is None
```

- [ ] **Step 2: Run test to verify it fails/passes** — this asserts the Task-5 contract; run and confirm PASS (it documents the dropped capability). If any existing test asserts world streak/simultaneous, it will FAIL — update it to expect US-only.

- [ ] **Step 3: Implementation** — grep and update: `grep -rn "simultaneous\|streak" dashboard/lib tests/ | grep -i world`; adjust expectations + add a code comment at the streak/simultaneous blocks noting world cities never reach them (calendar-date is GHCN-only now).

- [ ] **Step 4: Run the affected suites** → green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_open_meteo_orchestrator.py dashboard/ src/orchestrator/sources/open_meteo.py
git commit -m "feat: declare calendar/streak/simultaneous US-only for the world half"
```

---

## Phase 5 — Orchestrator wiring

### Task 11: Wire `both` world half to warm + hot + budget

**Files:**
- Modify: `src/orchestrator/sources/open_meteo.py` (the `both` branch, lines ~53-70)
- Modify: `src/orchestrator/world_cache.py` (add `read_cache`/`write_cache` gist helpers mirroring `_read_gist_state`/`_write_gist_state` for `WORLD_CACHE_FILENAME`)
- Test: `tests/test_open_meteo_orchestrator.py`

**Interfaces:**
- Consumes: `read_cache()`, `write_cache(merge_caches(read_cache(), local))`, `select_stale_cities`, `compute_city_thresholds`, `fetch_forecasts_batch`, `evaluate_city`, `apply_provisional`, `OpenMeteoBudget`, `classify_world_status`.
- Replaces the live `_check_city_extreme_signals(world_cities, ...)` call. The interim `select_world_budget_cities` cap is REMOVED here (the warm/hot path + budget now bound load); the urgent order is passed to `select_stale_cities` so Europe/perennials warm first.

**Flow (the `both` branch):**
1. `world_cities = [c for c in cities if not is_us_location(c.get("country"))]`
2. `cache = read_cache()`
3. **Warm:** `stale = select_stale_cities(cache, world_cities, ttl_days=WORLD_CACHE_TTL_DAYS, budget=WORLD_WARM_BUDGET, today=iso, urgent_order=URGENT_WORLD_HEAT_CITIES)`; for each (budget-gated via `OpenMeteoBudget`), pull archive (existing `detect_extreme_signals` archive fetch path, or a thin `fetch_city_archive`), `compute_city_thresholds`, merge into `cache`. Count `warm_attempted/warm_failures`.
4. **Hot:** for cached cities, in `forecast_batch_size`-paced batches, `fetch_forecasts_batch`; `evaluate_city` each; collect bundles; `apply_provisional` on fired records. Count `forecast_attempted/forecast_failures/cached_count`; `coverage_ratio = evaluated / world_total`.
5. Add `detect_absolute_extreme` per evaluated city (band-based).
6. Build `country_eligibility` (count of configured world cities per country) → pass to `detect_country_records`.
7. `write_cache(merge_caches(read_cache(), cache))` (re-read to honor concurrent warms).
8. Set source status via `classify_world_status(metrics)`.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_open_meteo_orchestrator.py (append)
def test_both_world_half_uses_cache_warm_and_hot(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner
    from src.orchestrator import world_cache

    cache_store = {}
    monkeypatch.setattr(world_cache, "read_cache", lambda: dict(cache_store))
    monkeypatch.setattr(world_cache, "write_cache", lambda c: cache_store.update(c) or True)
    # one world city; archive fetch returns a fixed 30-yr block; forecast sets a record
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations", lambda metrics_out: ([], []))
    monkeypatch.setattr(runner, "_fetch_city_archive", lambda c: {
        "time": ["1996-06-01"], "temperature_2m_max": [40.0],
        "temperature_2m_min": [10.0], "wet_bulb_temperature_2m_max": [24.0]})
    monkeypatch.setattr("src.data.open_meteo.fetch_forecasts_batch",
                        lambda cities: {c["city"]: {"max_c": 46.0, "min_c": 12.0, "tw_max_c": 10.0} for c in cities})
    cities = [{"city": "Madrid", "country": "Spain", "lat": "40.4", "lon": "-3.7"}]
    current_run = {"id": "r", "mode": "alerts", "started_at": "2026-06-26T00:00:00Z", "sources": []}
    runner.run_extreme_signals(runner._fresh_state() if hasattr(runner, "_fresh_state") else __import__("src.state", fromlist=["_fresh_state"])._fresh_state(),
                               current_run, cities, {}, {})
    # Madrid warmed into the cache, and the 46.0 forecast fired an all-time high
    assert "Madrid" in cache_store
```

- [ ] **Step 2: Run test to verify it fails** — FAIL (the `both` branch still calls `select_world_budget_cities` + `_check_city_extreme_signals`).

- [ ] **Step 3: Implement the wiring** — rewrite the `else` (`both`) world half per the Flow above; add `_fetch_city_archive(city)` (extract the archive GET from `detect_extreme_signals:600-621`) and `read_cache`/`write_cache` in `world_cache.py` (mirror `_read_gist_state`/`_write_gist_state`, file `WORLD_CACHE_FILENAME`, with the same truncation handling). Keep `WORLD_WARM_BUDGET`, `WORLD_CACHE_TTL_DAYS`, budget ceilings as module constants (start: `WORLD_WARM_BUDGET=8`, `WORLD_CACHE_TTL_DAYS=30`, budget `per_minute=480` (600 − 120 reserve for leaderboard), `per_hour=4000`, `per_day=8000`).

- [ ] **Step 4: Run the full suite** → `.venv/bin/python -m pytest -q` green; `.venv/bin/ruff check src/ tests/` clean.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/sources/open_meteo.py src/orchestrator/world_cache.py tests/test_open_meteo_orchestrator.py
git commit -m "feat: wire both world half to cached warm+hot+budget; remove interim cap"
```

---

## Rollout (post-merge, operational — not code tasks)

1. Merge; the interim cap is gone but the warm/hot+budget bounds load. First runs warm `WORLD_WARM_BUDGET` cities each, urgent-first.
2. Watch ~10 days: `cached_count` climbs to `world_total`; `coverage_log` diversifies (Europe/Asia appear); no 429s; budget metrics under ceilings; `classify_world_status` stays `success`.
3. Tune `WORLD_WARM_BUDGET` / budget ceilings against observed weight if warm is too slow or the minute ceiling is brushed.

## Self-review checklist (run before handoff)

- Spec coverage: cache schema (T1), warm (T2), store+merge (T3), hot fetch (T4), evaluate (T5), anti-re-fire (T6), budget (T7), country floor (T8), failure surfacing (T9), dropped signals (T10), wiring + cap removal + separate gist file (T11). ✓
- Placeholder scan: every code step shows real code or an exact existing-line reference to modify. Tasks 8/10/11 reference exact lines to edit rather than transcribing large existing blocks — the implementer reads those lines.
- Type consistency: `CityThresholds` fields + `to_dict/from_dict` are stable across T1/T2/T5/T6; `evaluate_city` and `apply_provisional` agree on tuple shapes; `OpenMeteoBudget` method names match T11 usage.
