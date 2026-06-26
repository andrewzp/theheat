# World Threshold Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the world half's live 30-year-archive-per-city-per-run with a cached-threshold model (mirroring the GHCN half) so all ~595 non-US cities get daily record detection without tripping Open-Meteo's rate limit.

**Architecture:** Split `detect_extreme_signals` into a **warm path** (`compute_city_thresholds`) and a **hot path** (`evaluate_city` vs cached thresholds). A separate gist-file cache store holds thresholds; its merge is **field/month-wise** (newest `as_of` wins per entry; equal `as_of` keeps the more-extreme value per field), so concurrent same-day writes never erase each other. A **process-level Open-Meteo weight budget** paces the alerts run, and **Open-Meteo 429s become a first-class, surfaced, run-stopping condition** (the silent-429 root cause + the only honest cross-process backstop, since alerts and leaderboard are separate processes). Records write a provisional threshold on fire (anti-re-fire). Country records gate on a per-country coverage floor and carry `eligible/cached/forecast_read` counts. calendar/streak/simultaneous become US-only for the world.

**Tech Stack:** Python 3.x, `requests`, `pytest`, `responses` (HTTP mocking), `ruff`. State persists to a GitHub Gist (`GIST_ID`/`GITHUB_TOKEN`).

**Spec:** `docs/superpowers/specs/2026-06-26-world-threshold-cache-design.md` (v2). **This plan is v2 — it incorporates a codex plan-review (2 P0 + 4 P1 + 2 P2). Each fix is tagged `[codex N]` at the task it lands in.**

## Global Constraints

- **ruff-clean:** no compact one-liners; no multi-import on one line; no unused locals. Run `.venv/bin/ruff check src/ tests/` before every commit.
- **Python via `.venv/bin/python`**; every Bash command prefixed `cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH`.
- **TDD:** failing test first, watch it fail, minimal code, watch it pass, commit. Stage only your own files (never `git add -A`).
- **No real sleeps in tests** — clock and sleep are injected; pacing is fake-clock tested.
- **Weight model (verified):** per-location; forecast (1 day, ≤3 vars) ≈ 1 weight/city; 30-yr daily archive ≈ ~43 weight/city. Free tier: 600/min, 5 000/hr, 10 000/day. Batching cuts HTTP round-trips, NOT weight.
- **Process reality:** `run_alerts` and `run_leaderboard` are **separate CLI modes / processes** (`src/main.py:79-95`). They cannot share an in-memory budget; they share only the server-side per-IP limit. The budget paces *within* the alerts process; **429-handling is the cross-process backstop.** The leaderboard (`hot10.py fetch_all_city_temps`, ~638 sequential forecasts) is out of scope here beyond reserving headroom.
- **Cache store is a separate gist file** (`world_threshold_cache.json`); `state.json` is never touched by cache writes. The cache file gets its own size guard + truncation handling.
- Branch `feat/world-threshold-cache` (holds spec + plan). One PR at the end.

## File Structure

- `src/data/world_thresholds.py` (NEW) — typed `CityThresholds` + `compute_city_thresholds` (warm) + `evaluate_city` (hot) + `MIN_MEAN_SAMPLES`. Pure.
- `src/data/openmeteo_budget.py` (NEW) — `OpenMeteoBudget` weight accountant + pacing primitive; `OpenMeteoSaturated` exception. Pure (injected clock+sleep).
- `src/orchestrator/world_cache.py` (NEW) — cache store: gist-file read/write (+size guard), field/month-wise merge, staleness selection, provisional-on-fire, progress `_meta`, `classify_world_status`.
- `src/data/open_meteo.py` (MODIFY) — `fetch_forecasts_batch` (multi-location, 429→`OpenMeteoSaturated`); `_fetch_city_archive` (extract); `detect_country_records` gains `country_eligibility`/counts; keep `detect_extreme_signals` as a thin wrapper for the legacy `open_meteo` provider + existing tests.
- `src/orchestrator/sources/open_meteo.py` (MODIFY) — `both` world half → warm+hot+budget+429-stop; drops calendar/streak/simultaneous; emits failure metrics; country eligibility.
- `dashboard/` + `tests/` (MODIFY) — expectations for dropped world signals.

Tests: `tests/test_world_thresholds.py`, `tests/test_openmeteo_budget.py`, `tests/test_world_cache.py`, additions to `tests/test_open_meteo.py` / `tests/test_open_meteo_orchestrator.py`.

**Cache entry invariant (load-bearing for the merge):** every write — warm OR provisional — produces a **complete** city entry (all fields present, `as_of=today`). Warm computes from archive; provisional loads the current entry, bumps the fired field, keeps the rest. This invariant is what makes the equal-`as_of` field-wise merge correct.

---

## Phase 1 — Cache foundation

### Task 1: Typed cache records `[codex P2 schema]`

**Files:** Create `src/data/world_thresholds.py`; Test `tests/test_world_thresholds.py`

**Interfaces — Produces:** `CityThresholds` dataclass + `to_dict()`/`from_dict()`; `MIN_MEAN_SAMPLES = 30` constant. Fields: `city`, `as_of` (ISO), `years_of_data`, `all_time_max/min: tuple[float,int]|None` (temp_c, year), `monthly_max/min: dict[str,tuple[float,int]]` ("01".."12"), `monthly_mean: dict[str,tuple[float,float,int]]` (mean_high_c, mean_low_c, sample_count), `wetbulb_max: tuple[float,int]|None`.

- [ ] **Step 1 — failing test**

```python
# tests/test_world_thresholds.py
from src.data.world_thresholds import CityThresholds, MIN_MEAN_SAMPLES


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
    assert MIN_MEAN_SAMPLES >= 1
```

- [ ] **Step 2 — run, expect FAIL** `ModuleNotFoundError: No module named 'src.data.world_thresholds'`
  Run: `.venv/bin/python -m pytest tests/test_world_thresholds.py -q`

- [ ] **Step 3 — implement**

```python
# src/data/world_thresholds.py
from __future__ import annotations

from dataclasses import dataclass, field

MIN_MEAN_SAMPLES = 30  # below this, a monthly mean is too sparse to fire an anomaly


@dataclass
class CityThresholds:
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
            "city": self.city, "as_of": self.as_of, "years_of_data": self.years_of_data,
            "all_time_max": list(self.all_time_max) if self.all_time_max else None,
            "all_time_min": list(self.all_time_min) if self.all_time_min else None,
            "monthly_max": {k: list(v) for k, v in self.monthly_max.items()},
            "monthly_min": {k: list(v) for k, v in self.monthly_min.items()},
            "monthly_mean": {k: list(v) for k, v in self.monthly_mean.items()},
            "wetbulb_max": list(self.wetbulb_max) if self.wetbulb_max else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityThresholds":
        def pair(v):
            return tuple(v) if v else None
        return cls(
            city=d["city"], as_of=d["as_of"], years_of_data=int(d.get("years_of_data", 0)),
            all_time_max=pair(d.get("all_time_max")), all_time_min=pair(d.get("all_time_min")),
            monthly_max={k: tuple(v) for k, v in (d.get("monthly_max") or {}).items()},
            monthly_min={k: tuple(v) for k, v in (d.get("monthly_min") or {}).items()},
            monthly_mean={k: tuple(v) for k, v in (d.get("monthly_mean") or {}).items()},
            wetbulb_max=pair(d.get("wetbulb_max")),
        )
```

- [ ] **Step 4 — run, expect PASS** · `.venv/bin/python -m pytest tests/test_world_thresholds.py -q`
- [ ] **Step 5 — commit** `git add src/data/world_thresholds.py tests/test_world_thresholds.py && git commit -m "feat: typed CityThresholds + MIN_MEAN_SAMPLES"`

### Task 2: `compute_city_thresholds` — faithful means `[codex P1 mean-count]`

**Files:** Modify `src/data/world_thresholds.py`; Test `tests/test_world_thresholds.py`

**Interfaces — Produces:** `compute_city_thresholds(city, archive_daily, *, as_of, years_of_data=30) -> CityThresholds`. **Fix vs the first draft:** keep **separate high and low counts** for monthly means (the legacy detector builds `this_month_highs`/`this_month_lows` independently — `open_meteo.py:648,797`). Dividing the low-sum by the high-count corrupts cold means when missingness differs.

- [ ] **Step 1 — failing test (incl. a missing-low fixture)**

```python
# tests/test_world_thresholds.py (append)
from src.data.world_thresholds import compute_city_thresholds


def test_compute_means_use_independent_high_low_counts():
    archive = {
        "time": ["1996-06-01", "1996-06-02", "1996-06-03"],
        "temperature_2m_max": [40.0, 42.0, 41.0],   # 3 highs -> mean 41.0
        "temperature_2m_min": [10.0, None, 12.0],   # 2 lows  -> mean 11.0 (NOT /3)
        "wet_bulb_temperature_2m_max": [24.0, 25.0, 26.0],
    }
    t = compute_city_thresholds("T", archive, as_of="2026-06-26")
    mh, ml, n = t.monthly_mean["06"]
    assert mh == 41.0
    assert ml == 11.0          # 22/2, not 22/3
    assert n == 3              # sample_count = high-day count (paired-record basis)
    assert t.all_time_max[0] == 42.0 and t.all_time_min[0] == 10.0
    assert t.wetbulb_max[0] == 26.0
```

- [ ] **Step 2 — run, expect FAIL** `ImportError: cannot import name 'compute_city_thresholds'`
- [ ] **Step 3 — implement** (separate `high_counts`/`low_counts`; `sample_count` = high-day count for stability with the all-time/monthly basis)

```python
# src/data/world_thresholds.py (append)
from datetime import date


def compute_city_thresholds(city, archive_daily, *, as_of, years_of_data=30):
    dates = archive_daily.get("time", []) or []
    highs = archive_daily.get("temperature_2m_max", []) or []
    lows = archive_daily.get("temperature_2m_min", []) or []
    tws = archive_daily.get("wet_bulb_temperature_2m_max", []) or []

    at_max = at_min = None
    m_max: dict[str, tuple[float, int]] = {}
    m_min: dict[str, tuple[float, int]] = {}
    hi_sum: dict[str, float] = {}
    lo_sum: dict[str, float] = {}
    hi_n: dict[str, int] = {}
    lo_n: dict[str, int] = {}

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
            hi_sum[mm] = hi_sum.get(mm, 0.0) + hi
            hi_n[mm] = hi_n.get(mm, 0) + 1
        if lo is not None:
            if at_min is None or lo < at_min[0]:
                at_min = (lo, d.year)
            if mm not in m_min or lo < m_min[mm][0]:
                m_min[mm] = (lo, d.year)
            lo_sum[mm] = lo_sum.get(mm, 0.0) + lo
            lo_n[mm] = lo_n.get(mm, 0) + 1

    m_mean: dict[str, tuple[float, float, int]] = {}
    for mm in set(hi_n) | set(lo_n):
        h = hi_n.get(mm, 0)
        lo_count = lo_n.get(mm, 0)
        mean_hi = round(hi_sum.get(mm, 0.0) / h, 2) if h else 0.0
        mean_lo = round(lo_sum.get(mm, 0.0) / lo_count, 2) if lo_count else 0.0
        m_mean[mm] = (mean_hi, mean_lo, h)

    wb_max = None
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
        monthly_max=m_max, monthly_min=m_min, monthly_mean=m_mean, wetbulb_max=wb_max,
    )
```

- [ ] **Step 4 — run, expect PASS**
- [ ] **Step 5 — commit** `git add -p` the two files; `git commit -m "feat: compute_city_thresholds with independent high/low mean counts"`

### Task 3: Cache merge (field/month-wise) + staleness `[codex P0 merge, P2 ruff]`

**Files:** Create `src/orchestrator/world_cache.py`; Test `tests/test_world_cache.py`

**Interfaces — Produces:**
- `merge_caches(base, nxt) -> dict` — per city: **newer `as_of` wins; on equal `as_of`, field/month-wise merge keeping the MORE EXTREME value** (max for highs, min for lows, higher `sample_count` for means). Cities present on only one side survive. Skips the `_meta` key (handled separately).
- `select_stale_cities(cache, world_cities, *, ttl_days, budget, today, urgent_order) -> list[dict]` — missing-or-stale, urgent-first then oldest `as_of`, capped. (No unused locals.)
- `WORLD_CACHE_FILENAME = "world_threshold_cache.json"`.

- [ ] **Step 1 — failing tests (incl. the concurrent-same-day case)**

```python
# tests/test_world_cache.py
from src.orchestrator.world_cache import merge_caches, select_stale_cities


def test_merge_equal_as_of_is_field_wise_more_extreme():
    # run A warmed Madrid fully; run B fired all_time_high (provisional), same day.
    a = {"Madrid": {"city": "Madrid", "as_of": "2026-06-26",
                    "all_time_max": [44.0, 2023], "monthly_min": {"06": [8.0, 1997]}}}
    b = {"Madrid": {"city": "Madrid", "as_of": "2026-06-26",
                    "all_time_max": [45.5, 2026], "monthly_min": {"06": [9.0, 2020]}}}
    out = merge_caches(a, b)
    assert out["Madrid"]["all_time_max"] == [45.5, 2026]   # hotter high wins
    assert out["Madrid"]["monthly_min"]["06"] == [8.0, 1997]  # colder low wins
    # neither run's field was erased (the P0 bug)


def test_merge_newer_as_of_wins_and_unions_cities():
    base = {"Lyon": {"city": "Lyon", "as_of": "2026-06-20", "all_time_max": [40.0, 2019]}}
    nxt = {"Lyon": {"city": "Lyon", "as_of": "2026-06-26", "all_time_max": [39.0, 2026]},
           "Paris": {"city": "Paris", "as_of": "2026-06-26"}}
    out = merge_caches(base, nxt)
    assert out["Lyon"]["as_of"] == "2026-06-26"          # newer wins wholesale
    assert out["Lyon"]["all_time_max"] == [39.0, 2026]
    assert "Paris" in out


def test_select_stale_prefers_urgent_then_oldest_and_caps():
    world = [{"city": c, "country": "X", "lat": "0", "lon": "0"} for c in ["Madrid", "Lyon", "Zzz", "Aaa"]]
    cache = {"Madrid": {"as_of": "2026-06-25"}, "Lyon": {"as_of": "2026-04-01"}, "Aaa": {"as_of": "2026-04-01"}}
    out = select_stale_cities(cache, world, ttl_days=30, budget=2, today="2026-06-26", urgent_order=["Lyon", "Madrid"])
    names = [c["city"] for c in out]
    assert "Lyon" in names and "Madrid" not in names and len(out) == 2
```

- [ ] **Step 2 — run, expect FAIL** `ModuleNotFoundError`
- [ ] **Step 3 — implement**

```python
# src/orchestrator/world_cache.py
from __future__ import annotations

from datetime import date, timedelta

WORLD_CACHE_FILENAME = "world_threshold_cache.json"
_META_KEY = "_meta"


def _as_of(e):
    return str((e or {}).get("as_of") or "")


def _pick_pair(a, b, *, more_extreme_is_max):
    if a is None:
        return b
    if b is None:
        return a
    return (a if a[0] >= b[0] else b) if more_extreme_is_max else (a if a[0] <= b[0] else b)


def _merge_entry_fields(a: dict, b: dict) -> dict:
    """Equal-as_of field-wise merge: more-extreme per field; richer mean wins."""
    out = dict(a)
    out["all_time_max"] = _pick_pair(a.get("all_time_max"), b.get("all_time_max"), more_extreme_is_max=True)
    out["all_time_min"] = _pick_pair(a.get("all_time_min"), b.get("all_time_min"), more_extreme_is_max=False)
    out["wetbulb_max"] = _pick_pair(a.get("wetbulb_max"), b.get("wetbulb_max"), more_extreme_is_max=True)
    for key, is_max in (("monthly_max", True), ("monthly_min", False)):
        merged = dict(a.get(key) or {})
        for mm, v in (b.get(key) or {}).items():
            merged[mm] = _pick_pair(merged.get(mm), v, more_extreme_is_max=is_max)
        out[key] = merged
    mm_mean = dict(a.get("monthly_mean") or {})
    for mm, v in (b.get("monthly_mean") or {}).items():
        cur = mm_mean.get(mm)
        if cur is None or (v[2] > cur[2]):   # higher sample_count wins
            mm_mean[mm] = v
    out["monthly_mean"] = mm_mean
    return out


def merge_caches(base: dict, nxt: dict) -> dict:
    base = base or {}
    nxt = nxt or {}
    out: dict = {}
    for city in sorted((set(base) | set(nxt)) - {_META_KEY}):
        b = base.get(city)
        n = nxt.get(city)
        if b is None:
            out[city] = n
        elif n is None:
            out[city] = b
        elif _as_of(n) > _as_of(b):
            out[city] = n
        elif _as_of(b) > _as_of(n):
            out[city] = b
        else:
            out[city] = _merge_entry_fields(b, n)
    return out


def _is_stale(entry, *, ttl_days, today):
    if not entry or not entry.get("as_of"):
        return True
    try:
        return date.fromisoformat(entry["as_of"]) < date.fromisoformat(today) - timedelta(days=ttl_days)
    except (ValueError, TypeError):
        return True


def select_stale_cities(cache, world_cities, *, ttl_days, budget, today, urgent_order):
    rank = {name: i for i, name in enumerate(urgent_order)}
    stale = [c for c in world_cities if _is_stale(cache.get(c.get("city")), ttl_days=ttl_days, today=today)]
    stale.sort(key=lambda c: (rank.get(c.get("city"), len(urgent_order)), _as_of(cache.get(c.get("city"))), c.get("city")))
    out, seen = [], set()
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

- [ ] **Step 4 — run, expect PASS** · `.venv/bin/ruff check src/orchestrator/world_cache.py`
- [ ] **Step 5 — commit** `git commit -m "feat: field/month-wise cache merge + staleness selection"`

---

## Phase 2 — Hot path

### Task 4: Multi-location forecast fetch + 429 surfacing `[codex P0 budget-backstop]`

**Files:** Modify `src/data/open_meteo.py`, `src/data/openmeteo_budget.py` (new exception only); Test `tests/test_open_meteo.py`

**Interfaces — Produces:** `OpenMeteoSaturated(Exception)` (in `openmeteo_budget.py`); `fetch_forecasts_batch(cities) -> dict[str, dict]` — one multi-location call; on **HTTP 429** raises `OpenMeteoSaturated` (the hot loop catches it and stops). Other failures → `{}` (best-effort).

- [ ] **Step 1 — failing tests (success + 429)**

```python
# tests/test_open_meteo.py (append; `responses` imported at top)
import pytest
from src.data.openmeteo_budget import OpenMeteoSaturated


@responses.activate
def test_fetch_forecasts_batch_maps_cities():
    responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast",
        json=[{"daily": {"temperature_2m_max": [44.0], "temperature_2m_min": [20.0], "wet_bulb_temperature_2m_max": [26.0]}},
              {"daily": {"temperature_2m_max": [39.0], "temperature_2m_min": [18.0], "wet_bulb_temperature_2m_max": [24.0]}}], status=200)
    cities = [{"city": "Madrid", "lat": "40.4", "lon": "-3.7"}, {"city": "Lyon", "lat": "45.7", "lon": "4.8"}]
    out = _open_meteo_module.fetch_forecasts_batch(cities)
    assert out["Madrid"]["max_c"] == 44.0 and out["Lyon"]["min_c"] == 18.0


@responses.activate
def test_fetch_forecasts_batch_raises_saturated_on_429():
    responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast",
        json={"error": True, "reason": "Minutely API request limit exceeded"}, status=429)
    with pytest.raises(OpenMeteoSaturated):
        _open_meteo_module.fetch_forecasts_batch([{"city": "Madrid", "lat": "40.4", "lon": "-3.7"}])
```

- [ ] **Step 2 — run, expect FAIL** (`OpenMeteoSaturated` / `fetch_forecasts_batch` missing)
- [ ] **Step 3 — implement** — add `class OpenMeteoSaturated(Exception): pass` to `openmeteo_budget.py`; add `fetch_forecasts_batch` to `open_meteo.py`:

```python
# src/data/open_meteo.py (append)
from src.data.openmeteo_budget import OpenMeteoSaturated


def fetch_forecasts_batch(cities: list[dict]) -> dict[str, dict]:
    if not cities:
        return {}
    lats = ",".join(str(c["lat"]) for c in cities)
    lons = ",".join(str(c["lon"]) for c in cities)
    try:
        resp = fetch_with_retry(
            f"{BASE_URL}/forecast",
            params={"latitude": lats, "longitude": lons,
                    "daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
                    "timezone": "auto", "forecast_days": 1},
            timeout=30, attempts=3, backoff_base=1.0,
        )
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 429:
            raise OpenMeteoSaturated("forecast 429") from exc
        return {}
    except requests.RequestException:
        return {}
    try:
        payload = resp.json()
    except ValueError:
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

Note: `fetch_with_retry` calls `raise_for_status()`, which raises `requests.HTTPError` with `.response` set for a 429 (Open-Meteo isn't a WAF host, so it isn't retried — exactly the silent path we're now surfacing).

- [ ] **Step 4 — run, expect PASS**
- [ ] **Step 5 — commit** `git commit -m "feat: fetch_forecasts_batch + OpenMeteoSaturated on 429"`

### Task 5: `evaluate_city` (hot compare, sparse-mean guard) `[codex P1 sparse-mean]`

**Files:** Modify `src/data/world_thresholds.py`; Test `tests/test_world_thresholds.py`

**Interfaces — Produces:** `evaluate_city(city, country, forecast, cached, *, lat, lon, today) -> ExtremeSignalBundle`. Emits all_time/monthly/anomaly/wet_bulb; populates `today_*`/`archive_*` for country aggregation; **no calendar_date**. **Anomaly only fires when `monthly_mean[MM][2] >= MIN_MEAN_SAMPLES`** (a 1-sample mean must not fire a story).

- [ ] **Step 1 — failing tests**

```python
# tests/test_world_thresholds.py (append)
from datetime import date as _date
from src.data.world_thresholds import evaluate_city, CityThresholds


def _cached(mean_n=900):
    return CityThresholds(city="Madrid", as_of="2026-06-01", years_of_data=30,
        all_time_max=(44.0, 2023), all_time_min=(-4.0, 2001),
        monthly_max={"06": (43.0, 2019)}, monthly_min={"06": (8.0, 1997)},
        monthly_mean={"06": (32.0, 17.0, mean_n)}, wetbulb_max=(26.0, 2022))


def test_evaluate_emits_all_time_high_no_calendar():
    b = evaluate_city("Madrid", "Spain", {"max_c": 45.5, "min_c": 22.0, "tw_max_c": 24.0},
                      _cached(), lat=40.4, lon=-3.7, today=_date(2026, 6, 26))
    assert b.all_time_high is not None and b.all_time_high.old_record_c == 44.0
    assert b.calendar_date_high is None


def test_evaluate_skips_anomaly_when_mean_is_sparse():
    hot = {"max_c": 48.0, "min_c": 20.0, "tw_max_c": 10.0}
    assert evaluate_city("Madrid", "Spain", hot, _cached(900), lat=40.4, lon=-3.7, today=_date(2026, 6, 26)).anomaly_hot is not None
    assert evaluate_city("Madrid", "Spain", hot, _cached(5), lat=40.4, lon=-3.7, today=_date(2026, 6, 26)).anomaly_hot is None
```

- [ ] **Step 2 — run, expect FAIL**
- [ ] **Step 3 — implement** — same as the per-signal comparison cascade (all_time/monthly/wetbulb exactly as the legacy semantics), with the anomaly blocks guarded:

```python
# inside evaluate_city, the anomaly section:
mean = cached.monthly_mean.get(mm)
if today_max is not None and mean is not None and mean[2] >= MIN_MEAN_SAMPLES:
    anom = today_max - mean[0]
    if anom >= ANOMALY_HOT_THRESHOLD_C:
        b.anomaly_hot = AnomalyEvent(city=city, country=country, today_temp_c=today_max,
            historical_mean_c=mean[0], anomaly_c=anom, years_of_data=yrs,
            event_id=f"anomaly_hot_{key}_{iso}", lat=lat, lon=lon)
if today_min is not None and mean is not None and mean[2] >= MIN_MEAN_SAMPLES:
    anom = today_min - mean[1]
    if anom <= -ANOMALY_COLD_THRESHOLD_C:
        b.anomaly_cold = AnomalyEvent(city=city, country=country, today_temp_c=today_min,
            historical_mean_c=mean[1], anomaly_c=anom, years_of_data=yrs,
            event_id=f"anomaly_cold_{key}_{iso}", lat=lat, lon=lon)
```

(The all_time/monthly/wetbulb blocks and the imports `from src.data.open_meteo import AllTimeRecord, MonthlyRecord, AnomalyEvent, WetBulbEvent, ExtremeSignalBundle, WETBULB_TIERS, ANOMALY_HOT_THRESHOLD_C, ANOMALY_COLD_THRESHOLD_C` are as in the spec; reproduce the comparison semantics from `open_meteo.py:730-826` minus calendar-date. Populate `b.archive_max_c/_year` from `cached.all_time_max`, `b.archive_min_c/_year` from `cached.all_time_min`, and `b.today_max_c/today_min_c`.)

- [ ] **Step 4 — run, expect PASS**
- [ ] **Step 5 — commit** `git commit -m "feat: evaluate_city hot path with sparse-mean guard, no calendar-date"`

### Task 6: Provisional-on-fire (complete entry) `[codex P0 anti-re-fire+merge]`

**Files:** Modify `src/orchestrator/world_cache.py`; Test `tests/test_world_cache.py`

**Interfaces — Produces:** `apply_provisional(cache, bundle, *, today) -> None` — loads the city's current entry (or a fresh complete one), bumps any fired all_time/monthly field to the new value, sets `as_of=today`, writes back a **complete** entry. Prevents re-fire next run for all_time AND monthly. (Wet-bulb/anomaly are forecast-vs-static-threshold and re-fire is acceptable/desired daily; only record-type signals get provisional suppression.)

- [ ] **Step 1 — failing test** (all_time + monthly both suppressed next run)

```python
# tests/test_world_cache.py (append)
from datetime import date as _date
from src.orchestrator.world_cache import apply_provisional
from src.data.world_thresholds import evaluate_city, CityThresholds


def test_provisional_suppresses_all_time_and_monthly_re_fire():
    base = CityThresholds(city="Madrid", as_of="2026-06-01", years_of_data=30,
        all_time_max=(44.0, 2023), monthly_max={"06": (43.0, 2019)}).to_dict()
    cache = {"Madrid": base}
    fc = {"max_c": 45.5, "min_c": 20.0, "tw_max_c": 10.0}
    b1 = evaluate_city("Madrid", "Spain", fc, CityThresholds.from_dict(cache["Madrid"]), lat=40.4, lon=-3.7, today=_date(2026, 6, 26))
    assert b1.all_time_high and b1.monthly_high
    apply_provisional(cache, b1, today="2026-06-26")
    b2 = evaluate_city("Madrid", "Spain", fc, CityThresholds.from_dict(cache["Madrid"]), lat=40.4, lon=-3.7, today=_date(2026, 6, 27))
    assert b2.all_time_high is None and b2.monthly_high is None
    assert cache["Madrid"]["all_time_max"][0] == 45.5 and cache["Madrid"]["monthly_max"]["06"][0] == 45.5
```

- [ ] **Step 2 — run, expect FAIL**
- [ ] **Step 3 — implement**

```python
# src/orchestrator/world_cache.py (append)
from src.data.world_thresholds import CityThresholds


def _year(today: str) -> int:
    return date.fromisoformat(today).year


def apply_provisional(cache: dict, bundle, *, today: str) -> None:
    city = bundle.city
    entry = cache.get(city)
    t = CityThresholds.from_dict(entry) if entry else CityThresholds(city=city, as_of=today, years_of_data=0)
    if bundle.all_time_high is not None:
        t.all_time_max = (bundle.all_time_high.new_temp_c, _year(today))
    if bundle.all_time_low is not None:
        t.all_time_min = (bundle.all_time_low.new_temp_c, _year(today))
    if bundle.monthly_high is not None:
        t.monthly_max[f"{bundle.monthly_high.month:02d}"] = (bundle.monthly_high.new_temp_c, _year(today))
    if bundle.monthly_low is not None:
        t.monthly_min[f"{bundle.monthly_low.month:02d}"] = (bundle.monthly_low.new_temp_c, _year(today))
    t.as_of = today
    cache[city] = t.to_dict()
```

- [ ] **Step 4 — run, expect PASS** · **Step 5 — commit** `git commit -m "feat: provisional-on-fire complete-entry write (anti-re-fire)"`

---

## Phase 3 — Rate budget + pacing

### Task 7: `OpenMeteoBudget` + pacing primitive `[codex P0 budget, P1 pacing]`

**Files:** Modify `src/data/openmeteo_budget.py`; Test `tests/test_openmeteo_budget.py`

**Interfaces — Produces:** `OpenMeteoBudget(*, per_minute, per_hour, per_day, reserve, clock, sleep)`; methods `can_spend(weight)`, `spend(weight)`, `forecast_batch_size(remaining)`, **`next_available_delay(weight) -> float`** (seconds until `weight` fits, 0 if now), **`wait_until_can_spend(weight)`** (calls injected `sleep(next_available_delay)`; bounded — raises `OpenMeteoSaturated` if even an empty minute can't fit it, i.e. the hour/day ceiling is hit). Fake-clock + fake-sleep tested; **no real sleeps.**

- [ ] **Step 1 — failing tests (incl. a warm+595-forecast pacing run on a fake clock)**

```python
# tests/test_openmeteo_budget.py
import pytest
from src.data.openmeteo_budget import OpenMeteoBudget, OpenMeteoSaturated


def test_pacing_spends_595_forecasts_plus_warm_under_minute_ceiling():
    now = {"t": 0.0}
    slept = []
    def sleep(s):
        slept.append(s)
        now["t"] += s
    b = OpenMeteoBudget(per_minute=480, per_hour=5000, per_day=10000, reserve=120, clock=lambda: now["t"], sleep=sleep)
    spent = 0
    # 8 warm archives @43 + 595 forecasts @1, paced
    for w in [43] * 8 + [1] * 595:
        b.wait_until_can_spend(w)
        b.spend(w)
        spent += w
    assert spent == 8 * 43 + 595
    # never exceeded the minute ceiling (480-120 reserve = 360 usable/min)
    assert b._spent_within(60) <= 360


def test_wait_raises_when_daily_ceiling_blocks():
    b = OpenMeteoBudget(per_minute=600, per_hour=600, per_day=10, reserve=0, clock=lambda: 0.0, sleep=lambda s: None)
    b.spend(10)
    with pytest.raises(OpenMeteoSaturated):
        b.wait_until_can_spend(1)   # day exhausted; waiting can't help
```

- [ ] **Step 2 — run, expect FAIL**
- [ ] **Step 3 — implement** — add to the deque-based accountant: `next_available_delay` computes the soonest the rolling minute frees `weight` (the oldest in-window event's age-out time), and raises `OpenMeteoSaturated` if `per_hour`/`per_day` (minus current spend) can't fit `weight` at all. `wait_until_can_spend` loops: while not `can_spend`, `delay = next_available_delay`; if `delay` is unbounded → raise; else `sleep(delay)`. Cap iterations to avoid spins.

- [ ] **Step 4 — run, expect PASS** · **Step 5 — commit** `git commit -m "feat: OpenMeteoBudget pacing primitive (fake-clock tested)"`

---

## Phase 4 — Correctness & observability

### Task 8: Country-record coverage floor + counts `[codex P1 country]`

**Files:** Modify `src/data/open_meteo.py` (`CountryRecord` + `detect_country_records`); Test `tests/test_open_meteo.py`

**Interfaces — Produces:** add `eligible: int = 0`, `cached: int = 0`, `forecast_read: int = 0` to `CountryRecord`; `detect_country_records(readings, *, archive_years=30, min_cities_per_country=2, country_eligibility=None, country_forecast_read=None)` — suppress a country record when `country_eligibility` is provided and `cities_sampled < eligible[country]`; populate the three counts on emitted records. `None` defaults preserve current behavior + existing tests.

- [ ] **Step 1 — failing test**

```python
# tests/test_open_meteo.py (append)
def test_country_record_below_floor_suppressed_and_counts_populated():
    from src.data.open_meteo import detect_country_records, ExtremeSignalBundle
    r1 = [ExtremeSignalBundle(city="Madrid", country="Spain", today_max_c=48.0, archive_max_c=44.0, archive_max_year=2023)]
    assert detect_country_records(r1, country_eligibility={"Spain": 3}) == []   # 1 of 3
    r3 = [ExtremeSignalBundle(city=c, country="Spain", today_max_c=48.0, archive_max_c=44.0, archive_max_year=2023) for c in ["Madrid", "Sevilla", "Zaragoza"]]
    out = detect_country_records(r3, country_eligibility={"Spain": 3})
    assert out and out[0].eligible == 3 and out[0].cached == 3
```

- [ ] **Step 2 — run, expect FAIL** · **Step 3 — implement** (read `detect_country_records` at `open_meteo.py:822-905`; add the kwargs, the floor `continue`, and set the three count fields where `CountryRecord(...)` is built). · **Step 4 — `pytest -k country` PASS** · **Step 5 — commit** `git commit -m "feat: country-record coverage floor + eligible/cached/forecast_read counts"`

### Task 9: Failure surfacing with cross-run stall detection `[codex P1 failure]`

**Files:** Modify `src/orchestrator/world_cache.py`; Test `tests/test_open_meteo_orchestrator.py`

**Interfaces — Produces:** `classify_world_status(metrics, *, prev_cached_count) -> "success"|"degraded"`. Rules: **steady-state** (`cached_count >= world_total`) degrades if `coverage_ratio < WORLD_COVERAGE_FLOOR` OR `forecast_failures/forecast_attempted > WORLD_FORECAST_FAIL_FLOOR` OR `saturated`. **Bootstrap** degrades if `cached_count <= prev_cached_count` (cache stalled across runs — not climbing) while warm was attempted, OR warm-failure ratio is high. `prev_cached_count` is read from the cache file's `_meta.cached_count` and written each run.

- [ ] **Step 1 — failing tests**

```python
# tests/test_open_meteo_orchestrator.py (append)
def test_classify_world_status_rules():
    from src.orchestrator.world_cache import classify_world_status as cls
    base = {"world_total": 595, "forecast_attempted": 595, "forecast_failures": 0, "warm_attempted": 8, "warm_failures": 0, "saturated": False}
    assert cls({**base, "cached_count": 595, "coverage_ratio": 0.2}, prev_cached_count=595) == "degraded"   # steady low coverage
    assert cls({**base, "cached_count": 595, "coverage_ratio": 0.98}, prev_cached_count=595) == "success"
    assert cls({**base, "cached_count": 40, "coverage_ratio": 0.07}, prev_cached_count=20) == "success"      # bootstrap climbing
    assert cls({**base, "cached_count": 40, "coverage_ratio": 0.07}, prev_cached_count=40) == "degraded"     # bootstrap STALLED
    assert cls({**base, "cached_count": 595, "coverage_ratio": 0.98, "saturated": True}, prev_cached_count=595) == "degraded"
```

- [ ] **Step 2 — run, expect FAIL** · **Step 3 — implement** the rules + `WORLD_COVERAGE_FLOOR=0.85`, `WORLD_FORECAST_FAIL_FLOOR=0.25`, `WORLD_WARM_FAILURE_FLOOR=0.5`. · **Step 4 — PASS** · **Step 5 — commit** `git commit -m "feat: world status classifier with cross-run stall detection"`

### Task 10: Drop calendar/streak/simultaneous for the world `[codex P1 scope]`

(Unchanged from v1: the world half iterates `evaluate_city` bundles that never set `calendar_date_*`, so streak (`open_meteo.py:459`) and simultaneous (~269) naturally don't fire for world cities. Update any test/dashboard asserting world streak/simultaneous; add a code comment at those blocks. Test: `evaluate_city` bundle has `calendar_date_high is None`. Commit `git commit -m "feat: declare calendar/streak/simultaneous US-only for the world half"`.)

---

## Phase 5 — Wiring

### Task 11: Wire `both` world half + cache store I/O `[codex P0 budget-wiring, P1 failure-surface, P2 test]`

**Files:** Modify `src/orchestrator/sources/open_meteo.py`; Modify `src/orchestrator/world_cache.py` (add `read_cache`/`write_cache` + `_meta`); Test `tests/test_open_meteo_orchestrator.py`

**Interfaces — Consumes:** everything above. **Cache I/O** (`read_cache`/`write_cache`) mirror `_read_gist_state`/`_write_gist_state` (`state.py:1164/1214`) for `WORLD_CACHE_FILENAME`, including the truncation→`raw_url` handling and a size guard (warn + skip-grow if the cache file approaches the inline cliff). `write_cache` re-reads + `merge_caches` before PATCH (concurrent-warm safe). The `_meta` key carries `cached_count` + `as_of` (read as `prev_cached_count`).

**`both`-branch flow:**
1. `world_cities = [c for c in cities if not is_us_location(c.get("country"))]`; `cache = read_cache()`; `prev = (cache.get("_meta") or {}).get("cached_count", 0)`.
2. `budget = OpenMeteoBudget(per_minute=600, per_hour=5000, per_day=10000, reserve=WORLD_LEADERBOARD_RESERVE, clock=time.monotonic, sleep=time.sleep)`.
3. **Warm:** `select_stale_cities(...)`; for each, `budget.wait_until_can_spend(43)`; `_fetch_city_archive(c)`; on `OpenMeteoSaturated` set `saturated=True` and **stop warming**; else `compute_city_thresholds` → merge into `cache`; count `warm_attempted/failures`.
4. **Hot:** the cached cities, in `budget.forecast_batch_size(...)`-sized batches; before each batch `budget.wait_until_can_spend(len(batch))`; `fetch_forecasts_batch`; on `OpenMeteoSaturated` set `saturated=True` and **stop**; else `evaluate_city` each (+ `detect_absolute_extreme`), collect bundles, `apply_provisional` on fired records, count `forecast_attempted/failures/cached_count`, `coverage_ratio = evaluated/world_total`.
5. `country_eligibility = Counter(c["country"] for c in world_cities)`; pass to `detect_country_records`.
6. `cache["_meta"] = {"cached_count": cached_count, "as_of": iso}`; `write_cache(cache)`.
7. Source status = `classify_world_status(metrics, prev_cached_count=prev)`; attach full metrics to `current_run["sources"]` entry. **Remove the `select_world_budget_cities` cap.**

- [ ] **Step 1 — failing integration test** (cache warm + hot + metrics surfaced)

```python
# tests/test_open_meteo_orchestrator.py (append)
def test_both_world_half_warms_then_evaluates_and_surfaces_metrics(monkeypatch):
    from src.orchestrator.sources import open_meteo as runner
    from src.orchestrator import world_cache
    from src.state import _fresh_state
    store = {}
    monkeypatch.setattr(world_cache, "read_cache", lambda: dict(store))
    monkeypatch.setattr(world_cache, "write_cache", lambda c: store.update(c) or True)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations", lambda metrics_out: ([], []))
    monkeypatch.setattr(runner, "_fetch_city_archive", lambda c: {
        "time": ["1996-06-01"], "temperature_2m_max": [40.0], "temperature_2m_min": [10.0],
        "wet_bulb_temperature_2m_max": [24.0]}, raising=False)
    monkeypatch.setattr("src.data.open_meteo.fetch_forecasts_batch",
        lambda cities: {c["city"]: {"max_c": 46.0, "min_c": 12.0, "tw_max_c": 10.0} for c in cities})
    cities = [{"city": "Madrid", "country": "Spain", "lat": "40.4", "lon": "-3.7"}]
    run = {"id": "r", "mode": "alerts", "started_at": "2026-06-26T00:00:00Z", "sources": []}
    runner.run_extreme_signals(_fresh_state(), run, cities, {}, {})
    assert "Madrid" in store                       # warmed into cache
    src = [s for s in run["sources"] if s["source"] == "open_meteo_extreme_signals"][0]
    assert "coverage_ratio" in src and "cached_count" in src   # metrics surfaced
```

- [ ] **Step 2 — run, expect FAIL** (still uses `select_world_budget_cities` + `_check_city_extreme_signals`; `_fetch_city_archive`/`read_cache` absent — note `raising=False` per [codex P2]).
- [ ] **Step 3 — implement** — rewrite the `both` world half per the flow; add `_fetch_city_archive(c)` (extract the archive GET at `open_meteo.py:600-621`); add `read_cache`/`write_cache`/`_meta` to `world_cache.py`. Constants: `WORLD_WARM_BUDGET=8`, `WORLD_CACHE_TTL_DAYS=30`, `WORLD_LEADERBOARD_RESERVE=120`.
- [ ] **Step 4 — full suite + ruff** · `.venv/bin/python -m pytest -q` green; `.venv/bin/ruff check src/ tests/` clean.
- [ ] **Step 5 — commit** `git commit -m "feat: wire both world half to cached warm+hot+paced budget; remove interim cap"`

---

## Rollout (operational)
1. Merge; interim cap gone; warm/hot+budget+429-stop bound load. First runs warm 8 cities each, urgent-first.
2. ~10 days: `cached_count` climbs to `world_total`; `coverage_log` diversifies; no 429s; `classify_world_status` stays `success`; budget metrics under ceilings.
3. Tune `WORLD_WARM_BUDGET` / `WORLD_LEADERBOARD_RESERVE` against observed weight.

## Self-review checklist
- Spec coverage: schema(T1) · faithful means(T2) · field-wise merge(T3) · batch+429(T4) · evaluate+sparse(T5) · provisional(T6) · budget+pacing(T7) · country floor+counts(T8) · failure+stall(T9) · dropped signals(T10) · wiring+cap removal+separate file(T11). All 8 codex findings tagged to a task. ✓
- Placeholder scan: pure components show complete code; T5/T8/T11 reference exact existing lines to reproduce/modify. No "TODO/handle edge cases." ✓
- Type consistency: `CityThresholds` tuple shapes stable across T1/T2/T5/T6; merge operates on `to_dict()` shape; `OpenMeteoBudget` methods (`wait_until_can_spend`/`forecast_batch_size`) match T11 usage; `OpenMeteoSaturated` shared by T4/T7/T11; `classify_world_status(metrics, prev_cached_count=)` signature matches T9/T11. ✓
