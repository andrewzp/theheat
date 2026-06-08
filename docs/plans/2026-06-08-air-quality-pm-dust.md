# Air quality: PM2.5/smoke + dust — implementation plan

> **Revision 2: folded Codex adversarial review (2026-06-08).**

**Goal:** Add a single `air_quality` source that detects two categories — hazardous PM2.5/smoke events and major dust events — using the Open-Meteo Air Quality API (CAMS-backed, no key), queues `manual_only` drafts, and opens the synthesis lane for a future FIRMS×PM2.5 compound-event story.

---

## 1 Background

The codebase has no air-quality signal today. The FIRMS source (`src/data/firms.py`, `src/orchestrator/sources/firms.py`) detects active fires by radiative power but says nothing about what the smoke is doing downstream. Adding PM2.5/dust from CAMS creates a standalone category now and a natural synthesis partner with FIRMS later (smoke plume traced to a specific active fire).

The Open-Meteo Air Quality API is a **new host** not yet imported anywhere in `src/`. The existing `open_meteo.py` hits `api.open-meteo.com` and `archive-api.open-meteo.com`; the air-quality endpoint lives at `air-quality-api.open-meteo.com`. These are separate services with separate URL constants.

---

## 2 Data source

**Base URL:** `https://air-quality-api.open-meteo.com/v1/air-quality`

**Authentication:** None required for non-commercial use.

**Backing model:** Copernicus Atmosphere Monitoring Service (CAMS).
- Global model: 0.4° resolution (~45 km), updates every 12 h, 5-day forecast; historical global forecasts from October 2023.
- European model: 0.1° resolution (~11 km); historical reanalysis from 2013 onward.

**Hourly variables (relevant subset):**

| Variable | Description | Unit |
|---|---|---|
| `pm2_5` | PM2.5 concentration | μg/m³ |
| `pm10` | PM10 concentration | μg/m³ |
| `dust` | Saharan/mineral dust particles | μg/m³ |
| `aerosol_optical_depth` | 550 nm haze proxy | dimensionless |
| `us_aqi` | US AQI composite | index |
| `european_aqi` | European AQI composite | index |

**Query shape — batched (multiple cities per call, confirmed supported):**

The Air Quality API accepts comma-separated latitude/longitude pairs in a single request (confirmed from API docs: `&latitude=52.52,48.85&longitude=13.41,2.35`). When multiple coordinates are supplied the JSON response changes to a **list of objects** — one element per coordinate, in the same order as the request. CSV/XLSX add a `location_id` column.

```
GET https://air-quality-api.open-meteo.com/v1/air-quality
  ?latitude=31.5,23.8,12.4,...   # comma-separated, up to chunk_size cities
  &longitude=74.3,90.4,15.6,...  # same length list, same order
  &hourly=pm2_5,dust,aerosol_optical_depth,us_aqi
  &timezone=auto
  &forecast_days=1
  &past_days=1
```

**Chunk size:** Use `CHUNK_SIZE = 50` cities per request. At 638 cities / 50 = 13 HTTP calls instead of 638 — a ~50× reduction in call count and wall time. The `THEHEAT_AQ_CHUNK_SIZE` env var overrides for testing. See the fetch-helper design in Step 2.

**24-hour mean vs. hourly peak (Fix P1 — averaging window):** The plan uses **24-hour mean PM2.5**, not daily-max. The WHO 24-hour guideline (15 µg/m³, 2021 revision) and US EPA NAAQS are both defined on a 24-hour arithmetic mean, not a 1-hour spike. Using a 1-hour spike would misrepresent the tier as a 24-hour-average exceedance. Therefore:
- Compute `daily_mean = mean(v for v in values if v is not None)` over the 24-hour UTC window for PM2.5.
- Keep `daily_max` for **dust** — dust tiers are not defined against a 24-hour average standard; peak is the editorially appropriate metric for plume intensity.
- Signal definition, thresholds, writer framing, and the bundle fact label all use `pm25_24h_mean` (not `pm25_daily_max`). See §3a and Step 2.

**City list:** Reuse the 638-city CSV already loaded in `run_alerts` via `open_meteo.load_cities()` — see `src/data/open_meteo.py:169`, `src/orchestrator/run_alerts.py:49`. The `cities` list is passed into `run_extreme_signals`; the new runner receives the same list (or a filtered subset — see design fork in §12).

**Evidence-grade note for the fact-checker:** CAMS global model data is a gridded model output at 0.4° (~45 km) resolution, updated every 12 h (surfaced as hourly values by Open-Meteo interpolation). City-level PM2.5 and dust numbers are **model estimates**, not ground-station measurements. The fact-check prompt must treat them as WORLD_KNOWLEDGE grade. Ground-station corroboration via OpenAQ is a future enhancement (§14).

---

## 3 Signal definition and thresholds

### 3a PM2.5 hazard (`air_quality_hazard`)

Anchor to **24-hour mean PM2.5 μg/m³** (arithmetic mean of all non-null hourly values in the UTC day). This directly corresponds to both the US EPA NAAQS and the WHO 2021 24-hour mean guideline, which are defined on a 24-hour average, not an hourly peak. Using daily-max against 24-hour breakpoints would misrepresent a 1-hour spike as a 24-hour-average exceedance.

**WHO 2021 PM2.5 24-hour mean guideline: 15 µg/m³** (confirmed, Wikipedia citing the WHO 2021 Global Air Quality Guidelines document; same value as US EPA NAAQS 24-hour primary standard of 9 µg/m³ is the 2024 tightened value — we use the WHO 2021 figure of 15 µg/m³ for international framing).

| Tier | PM2.5 24h-mean threshold | WHO 24h guideline multiple | Signal fires? |
|---|---|---|---|
| 1 | ≥ 150 μg/m³ | 10× WHO 15 μg/m³ | Yes |
| 2 | ≥ 250 μg/m³ | ~17× WHO | Yes (upgrade) |
| 3 | ≥ 350 μg/m³ | ~23× WHO | Yes (upgrade) |

**event_id scheme:** `pm25_<city_slug>_<date>_tier<N>` where `city_slug = city.lower().replace(" ", "_")`.

**Tier-dedup logic:** The same city can upgrade tiers within a day; re-fire only when the new tier > the last-fired tier. No re-fire on the same tier. State key: `"air_quality_pm25_tiers"` → `{city_slug: {"tier": int, "date": "YYYY-MM-DD"}}`.

### 3b Dust event (`dust_event`)

Use **daily-max `dust` μg/m³** as primary signal; `aerosol_optical_depth` (AOD) is a supporting fact in the bundle (not a trigger, due to interpretability issues in the fact-check).

| Tier | Dust daily-max | Rationale |
|---|---|---|
| 1 | ≥ 500 μg/m³ | Significant regional plume; US AQI "Unhealthy for Sensitive" band for coarse particles |
| 2 | ≥ 2000 μg/m³ | Major Saharan / Haboob event; visibility impact | 
| 3 | ≥ 5000 μg/m³ | Extreme storm (rare; Xinjiang / Saharan haboob scale) |

**event_id scheme:** `dust_<city_slug>_<date>_tier<N>`.

**State key:** `"air_quality_dust_tiers"` → `{city_slug: {"tier": int, "date": "YYYY-MM-DD"}}`.

### Score comparison context

For reference, existing thresholds in `src/editorial/thresholds.py`:
- `fire` → 64, `global_disaster` → 62, `fire_footprint` → 72, `precipitation_extreme` → 70.

Proposed:
- `air_quality_hazard` → **68** (mid-band; PM2.5 is high-confidence when extreme, but CAMS model has ~45 km spatial smearing that reduces precision vs. station readings).
- `dust_event` → **66** (similar band; dust plumes are large-scale and visible, but harder to attribute to a single city).

---

## 4 Files to create / modify

### New files

| File | Purpose |
|---|---|
| `src/data/air_quality.py` | Fetch fn + two detector dataclasses + detection logic |
| `src/orchestrator/sources/air_quality.py` | `run_air_quality(bot_state, current_run, cities)` |
| `src/editorial/scoring/air_quality.py` | `score_pm25_hazard` + `score_dust_event` |
| `src/two_bot/intern/air_quality.py` | `build_pm25_hazard_bundle` + `build_dust_event_bundle` |
| `tests/test_air_quality.py` | Unit tests for data layer |
| `tests/test_air_quality_orchestrator.py` | Orchestrator integration tests |
| `tests/two_bot/test_air_quality_intern.py` | Bundle builder tests |

### Modified files (verified anchors)

| File | Change | Verified anchor |
|---|---|---|
| `src/orchestrator/run_alerts.py` | Add import + call `run_air_quality(...)` | Line 24: `from src.orchestrator.sources.ocean_sst import run_ocean_sst` (pattern); line 116: `drafted += run_ocean_sst(bot_state, current_run)` (call site) |
| `src/orchestrator/common.py` | Add `air_quality` to data-module import line; add `score_pm25_hazard` + `score_dust_event` to scoring imports and `__all__` | Line 26: `from src.data import open_meteo, ghcn, firms, ...`; line 43: `from src.editorial.scoring import (` |
| `src/editorial/scoring/__init__.py` | Add `score_pm25_hazard` + `score_dust_event` to public API + `__all__` | Line 1–11: module-level imports |
| `src/editorial/thresholds.py` | Add two `ThresholdEntry` rows | Line 15: `THRESHOLDS: dict[str, ThresholdEntry] = {` |
| `src/two_bot/intern/__init__.py` | Export `build_pm25_hazard_bundle` + `build_dust_event_bundle` | Line 1–52: current exports |
| `src/editorial/approval.py` | Add `"air_quality_hazard"` and `"dust_event"` to the `manual_only` branch | Line 163–187: the existing `manual_only` set |
| `src/state.py` | Add `"air_quality_pm25_tiers"` and `"air_quality_dust_tiers"` to `DEFAULT_STATE` | Line 35: `DEFAULT_STATE: BotState = {` |

---

## 5 Step-by-step implementation (ordered, TDD)

### Step 0 — Calibrate tier cutoffs (BLOCKING)

**This step must complete before the source is enabled in production.** Run a one-off sample of real CAMS output for representative cities to confirm the PM2.5 24h-mean tiers (150/250/350) and dust daily-max tiers (500/2000/5000) actually separate signal from noise at CAMS's 0.4°/~45 km resolution. The gridded model can differ ~2× from nearby ground stations — so tiers calibrated against station data may fire too early or too late against CAMS values.

**Cities to sample:**
- Known-dirty (PM2.5): Lahore, Delhi
- Known-clean (PM2.5): Reykjavik, Auckland
- Known-dusty (dust): Khartoum, Niamey

Run the snippet below and print `pm25_24h_mean` and `dust_daily_max` for each city. Compare against the proposed tier floors. Adjust `PM25_TIERS` and/or `DUST_TIERS` constants in `src/data/air_quality.py` if the sample shows mis-calibration (e.g. clean cities near tier 1, or known-dirty cities well below it).

```python
# One-off calibration script — run before enabling the source.
# Requires no API key. Prints pm2_5 24h-mean and dust daily-max for each city.
import requests
from statistics import mean

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

CALIBRATION_CITIES = [
    {"name": "Lahore",      "lat": 31.5,  "lon": 74.3},   # known-dirty (PM2.5)
    {"name": "Delhi",       "lat": 28.6,  "lon": 77.2},   # known-dirty (PM2.5)
    {"name": "Reykjavik",   "lat": 64.1,  "lon": -21.9},  # known-clean
    {"name": "Auckland",    "lat": -36.9, "lon": 174.8},  # known-clean
    {"name": "Khartoum",    "lat": 15.6,  "lon": 32.5},   # known-dusty
    {"name": "Niamey",      "lat": 13.5,  "lon": 2.1},    # known-dusty
]

lats = ",".join(str(c["lat"]) for c in CALIBRATION_CITIES)
lons = ",".join(str(c["lon"]) for c in CALIBRATION_CITIES)

resp = requests.get(AQ_URL, params={
    "latitude": lats, "longitude": lons,
    "hourly": "pm2_5,dust",
    "timezone": "auto", "forecast_days": 1, "past_days": 1,
}, timeout=30)
resp.raise_for_status()
payload = resp.json()

for city, loc in zip(CALIBRATION_CITIES, payload):
    pm25_vals = [v for v in loc["hourly"].get("pm2_5", []) if v is not None]
    dust_vals  = [v for v in loc["hourly"].get("dust", [])  if v is not None]
    pm25_mean  = round(mean(pm25_vals), 1) if pm25_vals else None
    dust_max   = round(max(dust_vals),  1) if dust_vals  else None
    print(f"{city['name']:12s}  pm25_24h_mean={pm25_mean}  dust_daily_max={dust_max}")
```

**Pass criteria:** Known-dirty cities should show PM2.5 24h-mean meaningfully above the tier-1 floor (150 μg/m³) on bad-air days, or this calibration confirms the floor is conservative. Known-clean cities should show well below 50 μg/m³. Known-dusty cities should show dust daily-max in the hundreds to thousands on active dust days.

> **The tier constants (150/250/350 for PM2.5; 500/2000/5000 for dust) are PROVISIONAL until this calibration passes.** Adjust them if the sample reveals systematic bias between CAMS model output and the expected separation of signal from noise.

### Step 1 — Write failing tests for the data layer

Create `tests/test_air_quality.py` first. Tests to write before any implementation:

```python
# tests/test_air_quality.py
import pytest
from unittest.mock import patch, MagicMock
from src.data.air_quality import (
    AQ_URL,
    WHO_24H_GUIDELINE,
    fetch_batch_air_quality,
    detect_pm25_hazard,
    detect_dust_event,
    PM25HazardEvent,
    DustEvent,
)

# Batch response shape: list of location objects (confirmed API behaviour).
SAMPLE_BATCH_RESPONSE = [
    {
        "latitude": 31.5,
        "longitude": 74.3,
        "hourly": {
            "time": ["2026-06-08T00:00", "2026-06-08T01:00", ...],  # 24 values
            "pm2_5": [155.0, 200.0, 180.0, ...],   # 24h-mean ~178 μg/m³
            "dust": [None, 600.0, 800.0, ...],      # daily-max = 800.0
            "aerosol_optical_depth": [0.4, 0.6, ...],
            "us_aqi": [None, 210, 240, ...],
        }
    }
]

def test_fetch_24h_mean_pm25():
    """pm25_24h_mean = arithmetic mean of non-None hourly PM2.5 values."""
    ...

def test_fetch_dust_daily_max():
    """dust_daily_max = max of non-None hourly dust values (not mean)."""
    ...

def test_pm25_tier_1_fires_at_150():
    # 24h-mean ≥ 150 → tier 1
    ...

def test_pm25_tier_2_fires_at_250():
    ...

def test_pm25_below_threshold_returns_none():
    # 24h-mean 149.9 → None
    ...

def test_dust_tier_1_fires_at_500():
    ...

def test_dust_below_threshold_returns_none():
    ...

def test_batch_fetch_chunk_splits():
    """638 cities → multiple HTTP calls of ≤50 each; list response parsed correctly."""
    ...

def test_batch_fetch_list_response_parsed():
    """API returns list → each element mapped to correct city."""
    ...

def test_batch_fetch_partial_chunk_failure():
    """One chunk raises RequestException → that chunk's cities are None, others parsed."""
    ...

def test_event_id_scheme_pm25():
    # event_id = f"pm25_lahore_2026-06-08_tier1"
    ...

def test_event_id_scheme_dust():
    # event_id = f"dust_khartoum_2026-06-08_tier2"
    ...

def test_who_multiple_uses_15():
    # who_multiple = pm25_24h_mean / 15.0 (not 25.0)
    # 150 / 15.0 = 10.0
    assert WHO_24H_GUIDELINE == 15.0
    ...
```

### Step 2 — Implement `src/data/air_quality.py`

Key changes vs. original draft (Revision 2 fixes):
- PM2.5 uses **24-hour mean** (not daily-max) — matches the 24h-average basis of WHO/EPA breakpoints.
- Dust retains **daily-max** — plume intensity; no 24h-average standard applies.
- `fetch_batch_air_quality` replaces the single-city function: accepts a list of city dicts, chunks them, and issues one HTTP call per chunk of `CHUNK_SIZE=50`. Returns a list of `CityAirQuality` (one per city, `None` on fetch failure).
- `WHO_24H_GUIDELINE = 15.0` — the WHO 2021 24-hour mean PM2.5 guideline (confirmed).

```python
"""Open-Meteo Air Quality API fetch + PM2.5 hazard + dust event detection.

Host: air-quality-api.open-meteo.com (CAMS-backed; distinct from the
temperature/archive Open-Meteo hosts in src/data/open_meteo.py).
No API key required for non-commercial use.

Evidence grade: CAMS global model is gridded at 0.4° (~45 km), updated
every 12 h. City-level values are MODEL ESTIMATES, not station readings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from statistics import mean

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WHO 2021 PM2.5 24-hour mean guideline (μg/m³). Source: WHO Global Air
# Quality Guidelines 2021 — 24-hour mean level is 15 μg/m³.
WHO_24H_GUIDELINE: float = 15.0

# Batch chunk size: number of cities per HTTP call to the Air Quality API.
# Confirmed: the API accepts comma-separated lat/lon lists and returns a JSON
# list of structures (one element per coordinate, same order). Chunking at 50
# reduces 638 sequential calls to ~13 batched calls.
CHUNK_SIZE: int = int(os.environ.get("THEHEAT_AQ_CHUNK_SIZE", "50"))

# PM2.5 24h-mean tiers (μg/m³). Compared against the 24-hour arithmetic mean,
# consistent with WHO 2021 and US EPA NAAQS 24-hour average definitions.
# Tier 1 at 150 = 10× the WHO 24h guideline (15 μg/m³).
PM25_TIERS: tuple[int, ...] = (150, 250, 350)

# Dust daily-max tiers (μg/m³). Mineral dust from CAMS "dust" variable.
# No 24h-average standard applies; peak is the appropriate metric for plumes.
DUST_TIERS: tuple[int, ...] = (500, 2000, 5000)


@dataclass(frozen=True)
class CityAirQuality:
    city: str
    country: str
    lat: float
    lon: float
    date: str              # ISO date of the observation window
    pm25_24h_mean: float | None    # 24-hour arithmetic mean PM2.5 (μg/m³)
    dust_daily_max: float | None   # daily-max dust (μg/m³)
    aod_daily_max: float | None    # aerosol_optical_depth, for bundle context
    us_aqi_daily_max: int | None


@dataclass(frozen=True)
class PM25HazardEvent:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    pm25_24h_mean: float   # 24-hour arithmetic mean PM2.5 (μg/m³)
    tier: int              # 1, 2, or 3
    who_multiple: float    # pm25_24h_mean / 15.0 (WHO 2021 24h guideline)
    us_aqi_daily_max: int | None
    event_id: str          # e.g. "pm25_lahore_2026-06-08_tier1"


@dataclass(frozen=True)
class DustEvent:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    dust_daily_max: float
    tier: int
    aod_daily_max: float | None
    event_id: str          # e.g. "dust_khartoum_2026-06-08_tier2"


def _daily_mean(values: list) -> float | None:
    """Return arithmetic mean of non-None float values, or None if all null."""
    valid = [float(v) for v in values if isinstance(v, (int, float))]
    return mean(valid) if valid else None


def _daily_max(values: list) -> float | None:
    """Return max of non-None float values in a list, or None if all null."""
    valid = [float(v) for v in values if isinstance(v, (int, float))]
    return max(valid) if valid else None


def _daily_max_int(values: list) -> int | None:
    v = _daily_max(values)
    return int(round(v)) if v is not None else None


def _tier(value: float, tiers: tuple[int, ...]) -> int | None:
    """Return the highest tier whose threshold <= value, or None."""
    matched = [i + 1 for i, t in enumerate(tiers) if value >= t]
    return max(matched) if matched else None


def _parse_single_location(
    data: dict,
    city: str,
    country: str,
    lat: float,
    lon: float,
    today_str: str,
) -> CityAirQuality | None:
    """Parse one location's hourly dict (single or extracted from list response)."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return None

    # Slice to today's 24 UTC hours; fall back to full window.
    today_indices = [i for i, t in enumerate(times) if t.startswith(today_str)]
    if not today_indices:
        today_indices = list(range(len(times)))

    def _slice(key: str) -> list:
        vals = hourly.get(key, [])
        return [vals[i] for i in today_indices if i < len(vals)]

    return CityAirQuality(
        city=city,
        country=country,
        lat=lat,
        lon=lon,
        date=today_str,
        pm25_24h_mean=_daily_mean(_slice("pm2_5")),   # 24h mean for PM2.5
        dust_daily_max=_daily_max(_slice("dust")),     # peak for dust plumes
        aod_daily_max=_daily_max(_slice("aerosol_optical_depth")),
        us_aqi_daily_max=_daily_max_int(_slice("us_aqi")),
    )


def fetch_batch_air_quality(
    cities: list[dict],
    *,
    chunk_size: int = CHUNK_SIZE,
) -> list[CityAirQuality | None]:
    """Fetch air-quality data for a list of city dicts in batched HTTP calls.

    Each dict must have keys: city, country, lat, lon.
    Returns a list of the same length as `cities`. Entries are None where
    the city's data could not be fetched or parsed.

    Batch strategy: chunk `cities` into groups of `chunk_size`, issue one
    HTTP call per chunk with comma-separated lat/lon params. The API returns
    a JSON list in the same order as the request coordinates.
    """
    today_str = date.today().isoformat()
    results: list[CityAirQuality | None] = [None] * len(cities)

    for chunk_start in range(0, len(cities), chunk_size):
        chunk = cities[chunk_start : chunk_start + chunk_size]
        lats = ",".join(str(c["lat"]) for c in chunk)
        lons = ",".join(str(c["lon"]) for c in chunk)

        try:
            resp = fetch_with_retry(
                AQ_URL,
                timeout=30,
                params={
                    "latitude": lats,
                    "longitude": lons,
                    "hourly": "pm2_5,dust,aerosol_optical_depth,us_aqi",
                    "timezone": "auto",
                    "forecast_days": 1,
                    "past_days": 1,
                },
            )
            payload = resp.json()
        except (requests.RequestException, ValueError):
            # Entire chunk fails; leave results as None for all in chunk.
            continue

        # API returns a list when multiple coordinates are given.
        if isinstance(payload, list):
            location_list = payload
        else:
            # Single-coordinate fallback (should not happen with batching,
            # but defensively handle in case chunk_size=1).
            location_list = [payload]

        for i, loc_data in enumerate(location_list):
            if i >= len(chunk):
                break
            city_row = chunk[i]
            obs = _parse_single_location(
                loc_data,
                city=city_row["city"],
                country=city_row["country"],
                lat=float(city_row["lat"]),
                lon=float(city_row["lon"]),
                today_str=today_str,
            )
            results[chunk_start + i] = obs

    return results


def detect_pm25_hazard(obs: CityAirQuality) -> PM25HazardEvent | None:
    """Return a PM25HazardEvent if 24h-mean PM2.5 crosses tier 1+, else None."""
    if obs.pm25_24h_mean is None:
        return None
    tier = _tier(obs.pm25_24h_mean, PM25_TIERS)
    if tier is None:
        return None
    city_slug = obs.city.lower().replace(" ", "_").replace(",", "")
    return PM25HazardEvent(
        city=obs.city,
        country=obs.country,
        lat=obs.lat,
        lon=obs.lon,
        date=obs.date,
        pm25_24h_mean=obs.pm25_24h_mean,
        tier=tier,
        who_multiple=round(obs.pm25_24h_mean / WHO_24H_GUIDELINE, 1),
        us_aqi_daily_max=obs.us_aqi_daily_max,
        event_id=f"pm25_{city_slug}_{obs.date}_tier{tier}",
    )


def detect_dust_event(obs: CityAirQuality) -> DustEvent | None:
    """Return a DustEvent if dust daily-max crosses tier 1+ threshold, else None."""
    if obs.dust_daily_max is None:
        return None
    tier = _tier(obs.dust_daily_max, DUST_TIERS)
    if tier is None:
        return None
    city_slug = obs.city.lower().replace(" ", "_").replace(",", "")
    return DustEvent(
        city=obs.city,
        country=obs.country,
        lat=obs.lat,
        lon=obs.lon,
        date=obs.date,
        dust_daily_max=obs.dust_daily_max,
        tier=tier,
        aod_daily_max=obs.aod_daily_max,
        event_id=f"dust_{city_slug}_{obs.date}_tier{tier}",
    )
```

### Step 3 — Implement scoring module `src/editorial/scoring/air_quality.py`

```python
"""Air-quality editorial scoring: PM2.5 hazard + dust event."""

from __future__ import annotations

from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold


def score_pm25_hazard(pm25_24h_mean: float, tier: int, who_multiple: float) -> EditorialScore:
    """Score a PM2.5 hazard event.

    Tier 1 (≥150 μg/m³ = 10× WHO 2021 24h mean): borderline. Tier 2 (≥250): strong.
    Tier 3 (≥350): elite. Confidence is moderate because CAMS global
    model has ~45 km spatial resolution — individual-city precision is
    lower than a station reading. Values are model estimates (evidence_grade).
    """
    tier_bonus = (tier - 1) * 12  # 0 / 12 / 24
    reasons = [
        f"PM2.5 {pm25_24h_mean:.0f} μg/m³ 24h-mean ({who_multiple:.1f}× WHO 2021 24h guideline of 15 μg/m³)",
        f"tier {tier} of 3 ({['≥150', '≥250', '≥350'][tier - 1]} μg/m³ 24h-mean)",
        "CAMS global model 0.4° (~45 km), model estimate — not station-measured",
    ]
    return _build_score(
        "air_quality_hazard",
        severity=60 + tier_bonus,
        novelty=80,
        timeliness=88,
        confidence=78,   # model output, not station measurement
        shareability=72 + tier_bonus * 0.5,
        sensitivity=8,   # potential health-impact framing
        threshold=get_threshold("air_quality_hazard"),
        reasons=reasons,
    )


def score_dust_event(dust_daily_max: float, tier: int) -> EditorialScore:
    """Score a mineral dust event.

    Tier 1 (≥500 μg/m³): borderline. Tier 2 (≥2000): strong.
    Tier 3 (≥5000): elite / major haboob scale.
    Dust plumes are large-scale phenomena — spatial smearing from the
    model is less problematic than for local PM2.5 readings.
    """
    tier_bonus = (tier - 1) * 10
    reasons = [
        f"mineral dust {dust_daily_max:.0f} μg/m³ daily-max",
        f"tier {tier} of 3 ({['≥500', '≥2000', '≥5000'][tier - 1]} μg/m³)",
        "CAMS global model 0.4° (~45 km); Saharan + mineral dust variable; model estimate — not station-measured",
    ]
    return _build_score(
        "dust_event",
        severity=58 + tier_bonus,
        novelty=78,
        timeliness=86,
        confidence=76,
        shareability=68 + tier_bonus * 0.5,
        sensitivity=4,   # lower than PM2.5; dust is a natural phenomenon
        threshold=get_threshold("dust_event"),
        reasons=reasons,
    )
```

### Step 4 — Add thresholds to `src/editorial/thresholds.py`

Add two entries inside `THRESHOLDS` dict (alphabetically near `air`):

```python
    "air_quality_hazard": ThresholdEntry(
        "air_quality_hazard",
        68,
        "CAMS model PM2.5 hazard signal; tier 1 at ≥150 μg/m³ 24h-mean (10× WHO 2021 24h guideline of 15 μg/m³). "
        "68 sits between fire (64) and fire_footprint (72); "
        "moderate confidence because of 45 km grid resolution and model-estimate evidence grade.",
    ),
    "dust_event": ThresholdEntry(
        "dust_event",
        66,
        "CAMS model mineral dust event; tier 1 at ≥500 μg/m³. "
        "Slightly below air_quality_hazard: dust is a natural geophysical "
        "phenomenon with lower human-harm framing sensitivity.",
    ),
```

### Step 5 — Add state keys to `src/state.py`

Inside `DEFAULT_STATE` dict (around line 35), add after the `coral_dhw_*` block:

```python
    # Air quality tier dedup (PM2.5 hazard + dust event).
    # Prevents re-firing the same city at the same tier on repeated runs.
    # Per-city structure: {"tier": int, "date": "YYYY-MM-DD"}.
    # Reset automatically when a new date is detected in the runner.
    "air_quality_pm25_tiers": {},   # {city_slug: {"tier": int, "date": "YYYY-MM-DD"}}
    "air_quality_dust_tiers": {},   # {city_slug: {"tier": int, "date": "YYYY-MM-DD"}}
```

No schema migration is needed: SQLite serialises state as JSON; new keys with `{}` default are backward-compatible.

**CRITICAL — when to write tier state (Codex fix P1):** Tier state keys (`air_quality_pm25_tiers`, `air_quality_dust_tiers`) must be updated **only after a draft succeeds** — i.e., inside the `on_draft_success` callback that `_enqueue_story_candidate` in `src/orchestrator/common.py` exposes, NOT at detection time.

Reason: `posted_events` (the global dedup guard) is written only after triage + writer succeed. If tier state is written at detection time (before the pipeline completes), a subsequent run sees the tier as already fired and will suppress re-evaluation even though no draft was produced. Conversely, updating at the `_enqueue_story_candidate` call site (before the async pipeline) has the same bug.

**Implementation pattern:** Pass `on_success=lambda: _set_city_tier(...)` to `_enqueue_story_candidate` and have that callback fire when the story candidate is successfully drafted. Check how other sources with similar upgrade semantics (e.g. `run_coral_dhw`) wire this callback — mirror that pattern exactly. The call-site snippet in Step 10 must be revised to use this callback form.

### Step 6 — Implement bundle builders `src/two_bot/intern/air_quality.py`

```python
"""Air-quality two-bot intern builders."""

from __future__ import annotations

from dataclasses import asdict
from src.data.air_quality import PM25HazardEvent, DustEvent
from src.two_bot.types import StoryBundle


def build_pm25_hazard_bundle(event: PM25HazardEvent) -> StoryBundle:
    """Hazardous PM2.5 at a city — headline is 24h-mean μg/m³ + WHO multiple."""
    return StoryBundle(
        signal_kind="air_quality_hazard",
        where=f"{event.city}, {event.country}",
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "pm25_24h_mean_ug_m3",
            "value": round(event.pm25_24h_mean, 1),
            "unit": "μg/m³",
        },
        current_facts=[
            # pm25_24h_mean: 24-hour arithmetic mean PM2.5. This matches the
            # averaging window of the WHO 2021 24h guideline and US EPA NAAQS.
            # Do NOT describe this as a "peak" or "spike."
            {"label": "pm25_24h_mean_ug_m3", "value": round(event.pm25_24h_mean, 1)},
            {"label": "who_24h_guideline_ug_m3", "value": 15},   # WHO 2021 — 15 μg/m³
            {"label": "who_multiple", "value": event.who_multiple},
            {"label": "tier", "value": event.tier},
            {"label": "us_aqi_daily_max", "value": event.us_aqi_daily_max},
            {"label": "data_source", "value": "CAMS global model via Open-Meteo"},
            {"label": "model_resolution_km", "value": 45},
            {"label": "lat", "value": event.lat},
            {"label": "lon", "value": event.lon},
            # Evidence-grade: model estimate, not a ground-station measurement.
            # Writer must use "CAMS model data" or "satellite-derived model estimate"
            # — never "recorded," "measured at a station," or "observed."
            {"label": "evidence_grade", "value": "model_estimated"},
        ],
        historical_context={},   # No archive on first version; CAMS history from 2023 only
        raw_signal_dump=asdict(event),
    )


def build_dust_event_bundle(event: DustEvent) -> StoryBundle:
    """Major mineral dust event — headline is daily-max dust μg/m³."""
    return StoryBundle(
        signal_kind="dust_event",
        where=f"{event.city}, {event.country}",
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "dust_daily_max_ug_m3",
            "value": round(event.dust_daily_max, 0),
            "unit": "μg/m³",
        },
        current_facts=[
            {"label": "dust_daily_max_ug_m3", "value": round(event.dust_daily_max, 0)},
            {"label": "tier", "value": event.tier},
            {"label": "aerosol_optical_depth", "value": round(event.aod_daily_max, 2) if event.aod_daily_max is not None else None},
            {"label": "data_source", "value": "CAMS global model via Open-Meteo"},
            {"label": "model_resolution_km", "value": 45},
            {"label": "lat", "value": event.lat},
            {"label": "lon", "value": event.lon},
            {"label": "evidence_grade", "value": "model_estimated"},
        ],
        historical_context={},
        raw_signal_dump=asdict(event),
    )
```

### Step 7 — Export from `src/two_bot/intern/__init__.py`

Add to existing imports block (line 13 area, after `precipitation` imports):

```python
from .air_quality import build_pm25_hazard_bundle, build_dust_event_bundle
```

Add to `__all__`:
```python
    "build_pm25_hazard_bundle",
    "build_dust_event_bundle",
```

### Step 8 — Add scoring to `src/editorial/scoring/__init__.py`

Add a new import:
```python
from . import air_quality as _air_quality
```

Add two public wrappers (follow the existing pattern exactly):
```python
def score_pm25_hazard(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _air_quality.score_pm25_hazard(*args, **kwargs)

def score_dust_event(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _air_quality.score_dust_event(*args, **kwargs)
```

Add to `__all__`:
```python
    "score_pm25_hazard",
    "score_dust_event",
```

### Step 9 — Update `src/orchestrator/common.py`

**Data-module import** (line 26): add `air_quality` to the existing `from src.data import ...` line.

**Scoring import** (line 43 block): add `score_pm25_hazard, score_dust_event` to `from src.editorial.scoring import (`.

**`__all__`** (line 1471+): add `"air_quality"`, `"score_pm25_hazard"`, `"score_dust_event"`.

### Step 10 — Implement `src/orchestrator/sources/air_quality.py`

Key design changes vs. original draft (Revision 2 fixes):
- **Batched fetch:** calls `fetch_batch_air_quality(cities)` once, returning a list — no per-city loop over HTTP.
- **PM2.5 field:** `pm25_24h_mean` throughout (not `pm25_daily_max`).
- **Tier state timing:** `_set_city_tier` is wired via `on_draft_success` callback to `_enqueue_story_candidate`, NOT called at detection time. This ensures state is only written after the triage + writer pipeline succeeds (matching when `posted_events` is written). Mirror the exact callback pattern from `run_coral_dhw` or whichever existing source uses `on_draft_success`.

```python
"""Source runner for Open-Meteo Air Quality (PM2.5 hazard + dust event).

Fetch strategy: batched via fetch_batch_air_quality (50 cities/call).
638 cities → ~13 HTTP calls instead of 638.
"""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def _get_city_tier(bot_state: BotState, tier_key: str, city_slug: str) -> tuple[int, str | None]:
    """Return (last_fired_tier, last_fired_date) for a city, or (0, None) if unseen."""
    tiers = bot_state.get(tier_key, {})
    entry = tiers.get(city_slug)
    if not isinstance(entry, dict):
        return 0, None
    return int(entry.get("tier", 0)), entry.get("date")


def _set_city_tier(bot_state: BotState, tier_key: str, city_slug: str, tier: int, obs_date: str) -> None:
    """Record a successfully-drafted tier for a city.

    MUST be called only from an on_draft_success callback, not at detection
    time — see Step 5 state notes for the full rationale.
    """
    tiers = cast(dict, bot_state).setdefault(tier_key, {})
    tiers[city_slug] = {"tier": tier, "date": obs_date}


def run_air_quality(bot_state: BotState, current_run: dict | None, cities: list[dict]) -> int:
    """Check air quality for all cities; enqueue PM2.5 hazard and dust event candidates.

    Uses batched HTTP fetch (CHUNK_SIZE cities per call). Tier-dedup state
    is written via on_draft_success callbacks, not at detection time.
    """
    drafted = 0
    print("[alerts] Checking air quality (PM2.5 24h-mean / dust peak)...")
    aq_start = time.perf_counter()
    source_promoted = 0
    source_drafted = 0
    observed = 0
    failures = 0

    try:
        from src.data.air_quality import fetch_batch_air_quality, detect_pm25_hazard, detect_dust_event
        from src.two_bot.intern import build_pm25_hazard_bundle, build_dust_event_bundle

        # Single batched fetch for all cities (chunked internally at CHUNK_SIZE=50).
        observations = fetch_batch_air_quality(cities)

        for city_row, obs in zip(cities, observations):
            city_name = city_row["city"]
            country = city_row["country"]

            if obs is None:
                failures += 1
                continue
            observed += 1

            # --- PM2.5 hazard (24h-mean trigger) ---
            pm25_event = detect_pm25_hazard(obs)
            if pm25_event is not None:
                city_slug = pm25_event.city.lower().replace(" ", "_").replace(",", "")
                last_tier, last_date = _get_city_tier(bot_state, "air_quality_pm25_tiers", city_slug)
                new_day = last_date != pm25_event.date
                tier_upgrade = pm25_event.tier > last_tier
                if (new_day or tier_upgrade) and not state.is_duplicate(bot_state, pm25_event.event_id):
                    score = score_pm25_hazard(
                        pm25_event.pm25_24h_mean,
                        pm25_event.tier,
                        pm25_event.who_multiple,
                    )
                    if _should_draft(score, pm25_event.event_id):
                        source_promoted += 1
                        review_context = _review_context(
                            source="CAMS via Open-Meteo Air Quality API (model estimate)",
                            source_key="air_quality",
                            headline=(
                                f"PM2.5 hazard: {city_name} "
                                f"{pm25_event.pm25_24h_mean:.0f} μg/m³ 24h-mean "
                                f"({pm25_event.who_multiple:.1f}× WHO; tier {pm25_event.tier})"
                            ),
                            current_run=current_run,
                            facts=[
                                _fact("City", city_name),
                                _fact("Country", country),
                                _fact("PM2.5 24h-mean", f"{pm25_event.pm25_24h_mean:.1f} μg/m³"),
                                _fact("WHO 2021 24h multiple", f"{pm25_event.who_multiple:.1f}× (guideline 15 μg/m³)"),
                                _fact("Tier", f"{pm25_event.tier}/3"),
                                _fact("US AQI (daily-max)", str(pm25_event.us_aqi_daily_max) if pm25_event.us_aqi_daily_max else "—"),
                                _fact("Evidence grade", "model_estimated (CAMS 0.4°/~45 km, not station-measured)"),
                            ],
                        )
                        bundle = build_pm25_hazard_bundle(pm25_event)
                        # Tier state written ONLY after draft succeeds — see Step 5 notes.
                        # Default-arg binding (cs=, t=, d=) prevents the late-binding
                        # loop bug: without defaults, the lambda captures city_slug /
                        # pm25_event by reference and every callback fires with the
                        # LAST iteration's values after the loop completes.
                        _enqueue_story_candidate(
                            bot_state,
                            bundle=bundle,
                            score=score,
                            source="air_quality",
                            legacy_type="air_quality_hazard",
                            event_id=pm25_event.event_id,
                            review_context=review_context,
                            on_draft_success=lambda cs=city_slug, t=pm25_event.tier, d=pm25_event.date: _set_city_tier(
                                bot_state, "air_quality_pm25_tiers", cs, t, d,
                            ),
                        )

            # --- Dust event (daily-max trigger) ---
            dust_event = detect_dust_event(obs)
            if dust_event is not None:
                city_slug = dust_event.city.lower().replace(" ", "_").replace(",", "")
                last_tier, last_date = _get_city_tier(bot_state, "air_quality_dust_tiers", city_slug)
                new_day = last_date != dust_event.date
                tier_upgrade = dust_event.tier > last_tier
                if (new_day or tier_upgrade) and not state.is_duplicate(bot_state, dust_event.event_id):
                    score = score_dust_event(dust_event.dust_daily_max, dust_event.tier)
                    if _should_draft(score, dust_event.event_id):
                        source_promoted += 1
                        review_context = _review_context(
                            source="CAMS via Open-Meteo Air Quality API (model estimate)",
                            source_key="air_quality",
                            headline=(
                                f"Dust event: {city_name} "
                                f"{dust_event.dust_daily_max:.0f} μg/m³ daily-max "
                                f"(tier {dust_event.tier})"
                            ),
                            current_run=current_run,
                            facts=[
                                _fact("City", city_name),
                                _fact("Country", country),
                                _fact("Dust daily-max", f"{dust_event.dust_daily_max:.0f} μg/m³"),
                                _fact("Tier", f"{dust_event.tier}/3"),
                                _fact("AOD", f"{dust_event.aod_daily_max:.2f}" if dust_event.aod_daily_max else "—"),
                                _fact("Evidence grade", "model_estimated (CAMS 0.4°/~45 km, not station-measured)"),
                            ],
                        )
                        bundle = build_dust_event_bundle(dust_event)
                        # Default-arg binding (cs=, t=, d=) prevents the late-binding
                        # loop bug: without defaults, the lambda captures city_slug /
                        # dust_event by reference and every callback fires with the
                        # LAST iteration's values after the loop completes.
                        _enqueue_story_candidate(
                            bot_state,
                            bundle=bundle,
                            score=score,
                            source="air_quality",
                            legacy_type="dust_event",
                            event_id=dust_event.event_id,
                            review_context=review_context,
                            on_draft_success=lambda cs=city_slug, t=dust_event.tier, d=dust_event.date: _set_city_tier(
                                bot_state, "air_quality_dust_tiers", cs, t, d,
                            ),
                        )

        _record_source_run(
            current_run, bot_state, "air_quality", aq_start,
            status="success",
            observed=observed,
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as e:
        print(f"[alerts] Air quality error: {e}")
        state.log_error(bot_state, "air_quality", str(e))
        _record_source_run(
            current_run, bot_state, "air_quality", aq_start,
            status="failed", error=str(e),
        )
    return drafted
```

**Implementation note on `on_draft_success`:** `_enqueue_story_candidate` in `src/orchestrator/common.py` **does accept `on_draft_success`** — confirmed available at `src/orchestrator/common.py:1310`. No need to add it; mirror the existing pattern exactly.

**DRY note — extract `_city_slug` helper:** `city_slug = obs.city.lower().replace(" ", "_").replace(",", "")` appears in `detect_pm25_hazard`, `detect_dust_event`, and the runner loop. Extract a `_city_slug(name: str) -> str` helper in `src/data/air_quality.py` and call it in all three places.

**DRY note — `_process_aq_event` helper (optional):** The PM2.5 and dust runner blocks in Step 10 are near-identical (~40 lines each: detect → slug → tier-check → score → review_context → bundle → enqueue). A small `_process_aq_event(bot_state, obs, detect_fn, bundle_fn, score_fn, tier_key, ...)` helper could deduplicate them. Recommended but marked **optional**: the field/framing differences between PM2.5 and dust (different score signatures, different fact labels, different review-context strings) make some duplication acceptable; don't extract if the helper signature becomes unwieldy.

### Step 11 — Wire the runner into `src/orchestrator/run_alerts.py`

**Add import** (after line 24, alongside `run_ocean_sst`):
```python
from src.orchestrator.sources.air_quality import run_air_quality
```

**Add call site** (after line 116 `drafted += run_ocean_sst(bot_state, current_run)`):
```python
drafted += run_air_quality(bot_state, current_run, cities)
```

`cities` is already bound at line 49 (`cities = open_meteo.load_cities()`).

### Step 12 — Add `manual_only` policy to `src/editorial/approval.py`

In the existing `manual_only` set (line 163–187), add the two new types:

```python
    if (
        tweet_type in {
            "fire",
            "fire_footprint",
            "severe_weather",
            "global_disaster",
            "global_flood",
            "storm_surge",
            "river_flood",
            "drought",
            "coral_bleaching",
            "precipitation_extreme",
            "snow_extreme",
            "seasonal_snow_record",
            "air_quality_hazard",   # NEW
            "dust_event",           # NEW
        }
        or tweet_type.startswith("cyclone_")
    ):
```

---

## 6 Bundle + writer-prompt changes

### Builder shape

Both `build_pm25_hazard_bundle` and `build_dust_event_bundle` follow the established pattern (see `src/two_bot/intern/atmospheric.py` for the CO2/CH4 template, `src/two_bot/intern/fire.py` for a field-precision precedent):

- `signal_kind`: `"air_quality_hazard"` or `"dust_event"` — these are new values; no existing builder handles them.
- `historical_context`: intentionally `{}` for v1. CAMS global forecast history only goes to October 2023 — insufficient for "hottest in N years" framing. Leave empty; writer is instructed by the `WHEN historical_context IS EMPTY` section of the prompt to use geography/world-knowledge instead.
- `evidence_grade: "model_estimated"` in `current_facts` — a new fact label the writer prompt must be taught to respect.

### Writer prompt additions

Add a new entry in the `## Field conventions in current_facts` section of `src/two_bot/prompts/writer_prompt.py` (`WRITER_SYSTEM_PROMPT`):

```
- **`evidence_grade`** (air-quality bundles): `"model_estimated"` means the values come from a gridded atmospheric model (CAMS, ~45 km resolution), not a ground-station measurement. Do NOT write "measured," "recorded," or "observed at a station." Use: "CAMS model data," "satellite-derived model estimates," or simply quote the number without a source verb. The fact-checker will reject "recorded" or "observed" for model data.
- **`pm25_24h_mean_ug_m3`** (PM2.5 bundles): the 24-hour arithmetic mean PM2.5 — the same averaging window as the WHO 2021 24-hour guideline. Do NOT call this a "peak," "spike," or "hourly maximum." Correct framing: "a 24-hour mean of 220 μg/m³."
- **`who_multiple`** (PM2.5 bundles): the bundle's pre-computed ratio (pm25_24h_mean / 15.0). Cite verbatim. The WHO 2021 PM2.5 24-hour mean guideline is 15 μg/m³; `"who_24h_guideline_ug_m3": 15` is the canonical value in the bundle. Example framing: "a 24-hour average of 220 μg/m³ — nearly 15 times the WHO daily guideline of 15 μg/m³."
- **PM2.5 / dust signal-kind conventions**: No health-alarm language. No "dangerous," "deadly," "toxic," "life-threatening." State the fact and one system clause (regional climate mechanism, known dust corridor, seasonal dryness pattern). If the signal is co-located with an active FIRMS fire, you may state that — but only if the bundle includes a `co_located_fire` fact (it won't in v1; don't invent it).
```

Add `"air_quality_hazard"` and `"dust_event"` to the `signal_kind` list in the **`**`signal_kind`**`** bullet.

### Fact-check prompt additions

Add to `src/two_bot/prompts/fact_check_prompt.py` under the `# What counts as WORLD_KNOWLEDGE` section:

```
**f) Air quality / dust plume geography.** Well-established dust corridors, monsoon-driven PM2.5 accumulation basins, and seasonal patterns are WORLD_KNOWLEDGE and should be ACCEPTED:
   - "The Sahel is one of the world's primary mineral dust source regions."
   - "South Asian cities including Delhi, Lahore, and Dhaka experience PM2.5 spikes tied to agricultural burning and temperature inversions."
   - "Dust from the Sahara regularly crosses the Atlantic and reaches the Caribbean."
   - "The Gobi and Taklamakan deserts are the primary dust sources for East Asian haboob events."
   Reject if the writer claims specific facility emissions, specific storm dates not in the bundle, or specific percentile comparisons without bundle archive support.
```

Also add under `# What stays UNVERIFIABLE`:

```
**g) Model-estimated vs. station-measured.** When `current_facts` contains `evidence_grade: "model_estimated"`, claims that the value was "recorded," "measured at a station," or "observed by instruments on the ground" are UNVERIFIABLE (the bundle explicitly says it's a model estimate). Reject those phrasings.
```

---

## 7 Scoring + thresholds (summary table)

| Category | Proposed threshold | Score formula sketch | Comparison |
|---|---|---|---|
| `air_quality_hazard` | 68 | severity=60+tier_bonus(0/12/24); novelty=80; confidence=78; sensitivity=8 | fire=64, fire_footprint=72 |
| `dust_event` | 66 | severity=58+tier_bonus(0/10/20); novelty=78; confidence=76; sensitivity=4 | global_disaster=62 |

**Worked example — PM2.5 tier 1 (150 μg/m³ 24h-mean = 10× WHO):**

```
severity  = 60 + 0  = 60   (×0.28 = 16.8)
novelty   = 80            (×0.24 = 19.2)
timeliness = 88           (×0.16 = 14.1)
confidence = 78           (×0.16 = 12.5)
shareability = 72         (×0.16 = 11.5)
penalty   = sensitivity 8 × 0.20 = 1.6
total ≈ 16.8+19.2+14.1+12.5+11.5 − 1.6 = 72.5 → clamp → 72
threshold = 68 → PASSES
```

**Worked example — PM2.5 tier 1 (120 μg/m³ 24h-mean, below floor — NOT FIRED):**  
The detector returns `None` before scoring is reached.

**Worked example — Dust tier 1 (500 μg/m³):**

```
severity  = 58 + 0 = 58   (×0.28 = 16.2)
novelty   = 78            (×0.24 = 18.7)
timeliness = 86           (×0.16 = 13.8)
confidence = 76           (×0.16 = 12.2)
shareability = 68         (×0.16 = 10.9)
penalty   = 4 × 0.20 = 0.8
total ≈ 16.2+18.7+13.8+12.2+10.9 − 0.8 = 71.0 → 71
threshold = 66 → PASSES
```

---

## 8 State / caps / cooldowns

### Tier-dedup state

Two new keys in `DEFAULT_STATE` (see Step 5):
- `"air_quality_pm25_tiers"`: `{city_slug: {"tier": int, "date": "YYYY-MM-DD"}}`
- `"air_quality_dust_tiers"`: same shape

**Per-run logic (implemented in the runner):**
1. Batch-fetch all cities in ~13 HTTP calls (50 cities/call).
2. For each city observation, read `(last_tier, last_date)` from state.
3. Enqueue event only if `new_day = True OR tier_upgrade = True`.
4. `is_duplicate(bot_state, event_id)` is the global dedup guard for the pipeline (fires if same `event_id` is already in `posted_events`).
5. **Tier state is written ONLY via `on_draft_success` callback** after triage + writer succeed — NOT at detection time or at the `_enqueue_story_candidate` call site. Writing at detection time causes suppression on the next run even if no draft was produced. See Step 5 for the full rationale. The callback lambda uses default-arg binding (`cs=city_slug, t=tier, d=date`) to avoid the late-binding loop bug: without defaults, every callback would fire with the final iteration's values.

### Cooldown / annual cap decision

**No per-city cooldown from `CITY_COOLDOWN_DAYS`** — the PM2.5/dust runner does not pass `city=` to `_enqueue_story_candidate`, so the city-cooldown gate in `save_draft` (line 1010–1023 of `common.py`) does not fire. Tier-dedup in state is the primary rate limiter.

**No annual cap** for v1 — air quality events are seasonal (monsoon burning seasons, Saharan dust spring–summer), so a hard annual cap would cut off coverage during peak seasons. If output volume proves too high in the first season, add an annual cap using the same pattern as `_co2_annual_cap_reached` (common.py:556).

**City selection rate limiter:** Batched fetch (50 cities/call) reduces 638 sequential calls to ~13 HTTP calls. The 3.5 h wall-time concern from the original draft is resolved. If rate-limit or timeout pressure still emerges on the batched path, fall back to the city-subset approach in §12 Fork A, but it is no longer the default recommendation.

---

## 9 Approval policy

Both types get `manual_only` (added in Step 12). From `src/editorial/approval.py`, `manual_only` returns:

```python
ApprovalPolicy(
    key="manual_only",
    mode="manual_only",
    recommended_delay_minutes=None,
    can_auto_approve=False,
    reason="Potential human-impact event. Keep explicit human approval in the loop.",
)
```

This matches the pattern for `fire`, `precipitation_extreme`, `severe_weather`. Air-quality hazard signals are health-impact adjacent; the same rationale applies.

**Where set:** `src/editorial/approval.py`, inside the `if tweet_type in {...}` block at line 163. Both `"air_quality_hazard"` and `"dust_event"` must be added to that set.

---

## 10 Test plan

### Unit tests — `tests/test_air_quality.py`

Mock `fetch_with_retry` using `unittest.mock.patch`. Follow the pattern in `tests/test_ocean_sst.py` and `tests/test_gpm_imerg.py`.

```python
# Cover all branches:
test_fetch_batch_success_single_city()          # happy path, 1 city → list of 1 obs; verify pm25_24h_mean
test_fetch_batch_success_two_cities()           # 2 cities → list of 2 obs; correct pairing
test_fetch_batch_chunk_split()                  # 51 cities with chunk_size=50 → 2 HTTP calls
test_fetch_batch_chunk_failure_partial()        # first chunk fails → first 50 obs are None, rest parsed
test_fetch_batch_all_null_pm25()               # all-None pm2_5 → obs.pm25_24h_mean = None
test_detect_pm25_hazard_tier1()                # 24h-mean 150 μg/m³ → tier 1
test_detect_pm25_hazard_tier2()                # 24h-mean 250 μg/m³ → tier 2
test_detect_pm25_hazard_tier3()                # 24h-mean 350 μg/m³ → tier 3
test_detect_pm25_hazard_boundary_below_tier1() # 24h-mean 149.9 → None
test_detect_pm25_hazard_none_obs()             # obs.pm25_24h_mean=None → None
test_detect_dust_event_tier1()                 # dust daily-max 500 μg/m³ → tier 1
test_detect_dust_event_boundary_below()        # 499 → None
test_event_id_format_pm25()                    # "pm25_lahore_2026-06-08_tier1"
test_event_id_format_dust()                    # "dust_khartoum_2026-06-08_tier2"
test_who_multiple_uses_15_guideline()          # 150 / 15.0 = 10.0 (not 25.0)
test_city_slug_special_chars()                 # "N'Djamena" → "n'djamena" or similar
```

### Unit tests — `tests/test_editorial_scoring.py` additions

Add to the existing scoring test file (follow the pattern for `score_precipitation_extreme`):

```python
test_score_pm25_hazard_tier1_passes_threshold()   # total >= 68
test_score_pm25_hazard_tier3_is_elite()           # total >= 85
test_score_dust_event_tier1_passes_threshold()     # total >= 66
test_score_dust_event_tier2_higher_than_tier1()   # tier2.total > tier1.total
```

### Unit tests — `tests/two_bot/test_air_quality_intern.py`

```python
test_build_pm25_hazard_bundle_fields()         # signal_kind, where, headline_metric.label == "pm25_24h_mean_ug_m3"
test_build_pm25_hazard_bundle_evidence_grade() # "model_estimated" present in current_facts
test_build_pm25_hazard_bundle_who_guideline()  # "who_24h_guideline_ug_m3" value is 15 (not 25)
test_build_dust_event_bundle_fields()
test_build_dust_event_bundle_aod_none()        # aod_daily_max=None → fact value is None (not crash)
```

### Orchestrator integration tests — `tests/test_air_quality_orchestrator.py`

```python
# Patch fetch_batch_air_quality to avoid real HTTP.
test_run_air_quality_enqueues_pm25_candidate()      # event enters _triage_queue
test_run_air_quality_tier_dedup_no_refire()         # same tier same day → not enqueued
test_run_air_quality_tier_upgrade_fires()            # tier 1 → tier 2 upgrade → new event enqueued
test_run_air_quality_new_day_resets_tier()          # old date in state → fires again
test_run_air_quality_is_duplicate_guard()           # event_id already in posted_events → skipped
test_run_air_quality_empty_city_list()              # cities=[] → success with observed=0
test_run_air_quality_all_cities_fail_http()         # all batch chunks fail → status="failed" logged
test_run_air_quality_tier_state_written_on_success()  # tier state NOT written until on_draft_success fires
test_run_air_quality_tier_state_not_written_on_failure()  # on_draft_success not called → state unchanged
test_multi_city_tier_state_each_recorded()          # 2+ cities fire PM2.5 events; assert EACH city's tier
                                                    # is recorded by its own on_draft_success callback
                                                    # (catches the late-binding closure bug: without default-
                                                    # arg binding every callback fires with the last city's values)
```

---

## 11 Risks / open questions / design forks

### FORK A — Which cities to scan (all 638 vs. subset)

**Original concern resolved:** Sequential HTTP at 20 s/city = 3.5 h was the original blocker. With batching (50 cities/call, ~13 total calls), the full 638-city list is feasible in well under 5 minutes even on slow connections.

**Remaining decision:** Whether to scan all 638 cities or a dust/PM2.5-prone subset. Full coverage catches surprise events (Siberian wildfire smoke, mid-latitude haboobs). A subset (MENA, Sahel, South Asia megacities, Central Asia, East Asia) is more economical.

**Recommendation (updated):** Scan all 638 cities by default using batching. If rate-limit pressure emerges, add `THEHEAT_AQ_MAX_CHECKS` env cap and a `PRIORITY_AQ_CITIES` constant as a fallback — but do not add these prematurely. Remove the old "Option 3 not available" note — **batching IS available** (confirmed from Open-Meteo API docs).

### FORK B — PM2.5 vs US AQI as primary trigger

The plan uses raw PM2.5 μg/m³ as the tier trigger. An alternative is `us_aqi` (≥200/300/400 = Tier 1/2/3). Arguments:

- **PM2.5 μg/m³**: more universally understood, aligns with WHO guideline framing in the tweet.
- **US AQI**: dimensionless index familiar to US readers but less meaningful internationally (and slightly politically loaded given EPA regulatory status).

**Recommendation:** PM2.5 μg/m³ primary + include `us_aqi` in the bundle as context. If the implementer finds AQI more editorially compelling, this is the fork point.

### FORK C — One runner with two detectors vs. two separate runners

Current plan: one runner `run_air_quality` with PM2.5 and dust detection inline. Alternative: `run_pm25_hazard` + `run_dust_event` as separate functions.

Arguments for one runner: cities are fetched once per city, not twice. Arguments for two: cleaner separation of concerns, easier to kill-switch one signal independently.

**Recommendation:** One runner, two detectors, each with its own env kill-switch `THEHEAT_AQ_PM25_ENABLED=1` and `THEHEAT_AQ_DUST_ENABLED=1` (default both 1).

### FORK D — Exact tier cutoffs

The proposed PM2.5 tiers (150/250/350) are conservative. The US EPA "Hazardous" AQI band starts at ~250 μg/m³ 24h; the "Unhealthy" band starts at ~55 μg/m³. Setting tier 1 at 150 targets only the worst events (roughly "Unhealthy for Everyone"). A lower tier 1 (e.g. 75 or 100) would fire more often but could include events that are common in some regions (Indo-Gangetic Plain in winter). The implementer should validate against a sample run of historical CAMS data before committing to final cutoffs.

### FORK E — CAMS history for rarity framing

CAMS global historical data starts October 2023 — too short for rarity claims ("worst in 30 years"). The writer prompt is explicitly told `historical_context = {}` and must not invent archive claims. If the Open-Meteo Air Quality API adds longer historical access, a future version can compute a daily-max archive and support "worst PM2.5 in N years of records" framing (analogous to how `detect_extreme_signals` in `open_meteo.py` uses the 30-year archive).

### Open question 1 — Evidence-grade + averaging-window language in writer/fact-check

Two related failure modes in the writer pipeline:

1. **Evidence-grade language:** The writer may default to "recorded," "measured," or "observed at a station" — all incorrect for model data. The fact-checker must reject these phrasings. Add a worked exemplar in the writer prompt.

2. **Averaging-window language:** The writer must describe the PM2.5 value as a "24-hour average" or "24-hour mean" — NOT as a "peak," "spike," or "hourly reading." The bundle label `pm25_24h_mean_ug_m3` is designed to force this framing, but the writer prompt must make it explicit. The fact-checker should flag "spike" or "peak PM2.5 of X μg/m³" as incorrect when the signal_kind is `air_quality_hazard` (which is 24h-mean triggered).

Both are **highest-risk points in the writer pipeline** and should be tested with a manual dry-run before activating the source in production.

### Open question 2 — FIRMS co-location

The most compelling PM2.5 tweets would state "this smoke plume traces to the active fire currently burning X km upwind." FIRMS already records fire events in `bot_state["synthesis_components"]["fires"]`. A simple heuristic: if a PM25HazardEvent city has a fire in state within 48 h at lat/lon within ~500 km, add a `co_located_fire` fact to the bundle. This is a **future enhancement** (see §14); do NOT add it in v1 to avoid bundle complexity before the baseline is validated.

### Open question 3 — Dust city selection

"Dust" from the CAMS `dust` variable is mineral aerosol sourced primarily from deserts. The signal is most relevant for cities near:
- Sahara/Sahel (Dakar, Bamako, Niamey, N'Djamena, Khartoum, Cairo)
- Arabian Peninsula (Riyadh, Kuwait City, Muscat, Dubai)
- Central Asia (Ashgabat, Dushanbe)
- Gobi / Taklamakan (Urumqi, Lanzhou, Beijing in spring)

With batching, running dust detection across all 638 cities is cheap (~13 HTTP calls). The implementer can choose to apply a `dust_prone` filter as an optimization, but it is not required to meet the wall-time constraint.

### Open question 4 — `on_draft_success` callback availability in `_enqueue_story_candidate` ✅ RESOLVED

**RESOLVED:** `_enqueue_story_candidate` in `src/orchestrator/common.py` already accepts `on_draft_success` — confirmed available at line 1310. No changes to `common.py` are needed for this feature. Mirror the existing pattern exactly; do not re-invent the callback contract.

---

## 12 Verification

After all files are written and tests pass:

```bash
# Type-check
python -m mypy src/data/air_quality.py \
               src/orchestrator/sources/air_quality.py \
               src/editorial/scoring/air_quality.py \
               src/two_bot/intern/air_quality.py

# Lint
python -m ruff check src/data/air_quality.py \
                     src/orchestrator/sources/air_quality.py \
                     src/editorial/scoring/air_quality.py \
                     src/two_bot/intern/air_quality.py \
                     src/editorial/thresholds.py \
                     src/state.py \
                     src/orchestrator/run_alerts.py \
                     src/editorial/approval.py \
                     src/two_bot/intern/__init__.py \
                     src/editorial/scoring/__init__.py

# Unit tests (excluding voice replay which requires real API keys)
python -m pytest tests/test_air_quality.py \
                 tests/test_air_quality_orchestrator.py \
                 tests/two_bot/test_air_quality_intern.py \
                 tests/test_thresholds.py \
                 tests/test_editorial_scoring.py \
                 -v -q -m "not voice_replay"

# Full non-voice suite (regression)
python -m pytest tests/ -q -m "not voice_replay"

# Smoke-test fetch against live API (two cities as a batch, no state side-effects)
# Confirms batch response is a list and pm25_24h_mean is computed (not daily-max).
python -c "
from src.data.air_quality import fetch_batch_air_quality, detect_pm25_hazard, detect_dust_event
cities = [
    {'city': 'Lahore', 'country': 'Pakistan', 'lat': 31.5, 'lon': 74.3},
    {'city': 'Khartoum', 'country': 'Sudan', 'lat': 15.6, 'lon': 32.5},
]
observations = fetch_batch_air_quality(cities, chunk_size=50)
for city_row, obs in zip(cities, observations):
    print(f'{city_row[\"city\"]}: obs={obs}')
    if obs:
        print('  PM2.5 event:', detect_pm25_hazard(obs))
        print('  Dust event:', detect_dust_event(obs))
"
```

---

## 13 Out of scope / future

- **FIRMS × PM2.5 synthesis pairing:** When a PM25HazardEvent city is within ~500 km of an active FIRMS fire recorded in `bot_state["synthesis_components"]["fires"]` within 48 h, a synthesis story can say "smoke from the [region] fire is reaching [city] — PM2.5 at Nx the WHO guideline." The synthesis layer is in `src/editorial/synthesis.py` and `src/orchestrator/sources/synthesis.py`. This is the natural next step after the baseline is validated.
- **OpenAQ ground-station evidence:** OpenAQ provides real-time station measurements and would upgrade the `evidence_grade` to "station_measured" for cities with local monitors. Use as a secondary cross-reference in the fact-check (not as the primary trigger). Requires an OpenAQ API key for bulk access.
- **Historical CAMS archive for rarity claims:** If Open-Meteo exposes multi-year air-quality archives, compute a per-city/per-DOY daily-max distribution and enable "worst PM2.5 since YYYY" framing (analogous to `detect_extreme_signals` in `open_meteo.py`).
- **WHO 2021 annual PM2.5 guideline (5 μg/m³):** The annual mean guideline is even stricter than the 24h guideline. Not suitable as a daily alert trigger but could be used in the system clause ("annual mean in this city regularly exceeds the 5 μg/m³ WHO annual guideline even without extreme events").
- **`data/cities.csv` `dust_prone` column:** Adding a boolean flag to the city CSV would let the runner filter efficiently without hardcoding a city list. Coordinate with however the CSV is generated/maintained.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | PM2.5 24h-mean vs 1h-spike, WHO=15 (not 25), multi-coordinate batching, evidence-grade — folded (Revision 2) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | Calibration gate (both categories kept); P1 late-binding closure fix; DRY helpers; multi-city tier test; tests strong |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run |

- **CODEX:** averaging-window error, WHO guideline, 638→13 batching, model-evidence-grade — folded Revision 2.
- **UNRESOLVED:** none.
- **VERDICT:** ENG CLEARED — ship PM2.5 hazard + dust event, gated on a blocking tier-calibration pre-step; closure bug fixed.
