# Row 5 — `cyclone_land_threat`: the Bavi gap (#375)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans, task-by-task. Read
> [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
> §Standing rules first. **New state key + new editorial surface → codex-xhigh MANDATORY**
> (Task 10). Issue: [#375](https://github.com/andrewzp/theheat/issues/375).

**Goal:** A warned storm whose OFFICIAL FORECAST track brings its center within N
nautical miles of a named landmass within M hours produces exactly ONE `manual_only`
draftable event per (storm, landmass) pair, written in forecast tense — so a Bavi-class
super typhoon bearing down on Taiwan can never again go silent at peak newsworthiness.

**Architecture:** Parse forecast track points from advisory text the bot ALREADY stores
(JTWC warning products carry structured `12 HRS, VALID AT:` forecast sections verbatim in
`advisory_text` — `src/data/jtwc.py:158-172` stores up to 8000 chars unparsed) plus a new
NHC Forecast/Advisory (TCM) fetch via the `CurrentStorms.json` product links. Landmass
resolution v1 = nearest populated place in `data/cities.csv` (638 curated cities) within
the radius → that city's country is the named landmass; per-(storm, landmass) one-shot
dedup mirrors the `fire_complex_tiers` scaffolding with an `on_draft_success` callback.
Center-distance only in v1 — no wind-radii claims (the tweet cites the forecast center
approach; the 34kt-radius upgrade is a noted fast-follow).

**Tech Stack:** existing only. No new dependencies. One new HTTP fetch per active NHC
storm (the TCM text), zero new LLM calls until a candidate drafts.

## Global Constraints

All of [INDEX.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/front-page-parity/INDEX.md)
§Standing rules, plus:
- **Forecast-tense only, ever.** The event is a forecast, not an observation. The writer
  may never state arrival as fact ("will hit", "is hitting", "makes landfall Tuesday");
  the paired fact-check rule kills present/certain-tense arrival claims. The existing
  cyclone alarmism bans (no "catastrophic", "life-threatening", "BREAKING") apply
  unchanged.
- **`manual_only` by construction:** the tweet_type string starts with `cyclone_`, which
  `src/editorial/approval.py:254` already forces manual — do not add an autoship path.
- Tunables live as module constants with the values below; Andrew's calls, changeable
  without redesign: `LAND_THREAT_MAX_NM = 150.0`, `LAND_THREAT_MAX_HOURS = 72`,
  `LAND_THREAT_MIN_WIND_KT = 64` (current intensity ≥ Cat 1 — tropical-storm-strength
  threats are routine, not extraordinary).

## File map (whole PR)

- Modify: `src/data/cyclones.py` (ForecastPoint, forecast-text parser, LandThreatEvent, detector)
- Modify: `src/data/nhc.py` (TCM fetch), `src/data/jtwc.py` (thread parsed forecast points)
- Create: `src/data/land_threat_geo.py` (nearest-landmass resolution)
- Modify: `src/state.py`, `src/state_schema.py` (drafted-pairs state + MERGE_SPEC)
- Modify: `src/editorial/scoring/disasters.py`, `src/editorial/scoring/__init__.py`, `src/editorial/thresholds.py`
- Modify: `src/two_bot/intern/disasters.py`, `src/two_bot/intern/__init__.py`
- Modify: `src/two_bot/memory.py` (category map), `src/editorial/approval.py` (comment only)
- Modify: `src/two_bot/prompts/writer_prompt.py`, `src/two_bot/prompts/fact_check_prompt.py`
- Modify: `src/orchestrator/cyclones.py` (dispatch + wiring)
- Modify: `scripts/writer_dryrun.py`, `.github/workflows/writer-dryrun.yml` (`--type cyclone_land_threat`)
- Modify: `VERSION`, `CHANGELOG.md`
- Test: `tests/test_cyclones.py` (or the existing cyclone test module found via `grep -rln "detect_rapid_intensification" tests/`), `tests/test_land_threat_geo.py`, `tests/two_bot/test_intern.py`, `tests/two_bot/test_prompts.py`, `tests/test_writer_dryrun.py`, the MERGE_SPEC contract test

Branch: `git checkout main && git pull && git checkout -b feat/cyclone-land-threat`

---

### Task 0: Verify the feed contract LIVE before writing code (the A0 NIFC lesson)

The parsers below assume specific text formats. Verify against live products FIRST;
if the formats differ, adjust the regexes in Task 1 and say so in the PR body. This
task is read-only.

- [ ] **Step 1: NHC.** `curl -s https://www.nhc.noaa.gov/CurrentStorms.json | python3 -m json.tool | head -60` — confirm each active storm object carries a forecast-advisory product link (key name typically `forecastAdvisory` with a `url`; record the EXACT key). If no storms are active (quiet Atlantic), fetch the sample archive instead: any recent TCM text at `https://www.nhc.noaa.gov/archive/2026/` — confirm the TCM body contains repeated blocks shaped like `FORECAST VALID 08/0000Z 24.5N 122.0W` followed by `MAX WIND 105 KT...GUSTS 130 KT`.
- [ ] **Step 2: JTWC.** `curl -s "https://www.metoc.navy.mil/jtwc/rss/jtwc.rss?layout=enhanced" | grep -o 'https[^"<]*\.txt' | head -3` then fetch one warning `.txt` and confirm it contains forecast blocks shaped like `12 HRS, VALID AT:` / `120600Z --- 24.3N 123.8E` / `MAX SUSTAINED WINDS - 120 KT, GUSTS 145 KT` (taus 12/24/36/48/72). If no active WestPac storm, use any archived JTWC warning text; the format is stable.
- [ ] **Step 3: cities.csv covers the live test case.** `grep -i "taipei\|kaohsiung\|taiwan" data/cities.csv` — at least one Taiwanese city must exist for the Bavi case to resolve. If none: add the missing anchor cities to `data/cities.csv` as part of Task 2 (one line each, real coordinates, and note it in the PR).
- [ ] **Step 4:** Record findings (exact JSON key for the TCM url; confirmed regex-able lines; cities coverage) in a `docs/plans/`-style note or directly in the PR body. Do not proceed to Task 1 until formats are confirmed or the regexes are adjusted to the observed reality.

### Task 1: Forecast-point parsing (`ForecastPoint` + both feed legs)

**Files:**
- Modify: `src/data/cyclones.py` (dataclass + `parse_forecast_sections`)
- Modify: `src/data/jtwc.py` (populate `forecast_points` in `parse_warning_text`)
- Modify: `src/data/nhc.py` (fetch + parse the TCM product)
- Test: the existing cyclone test module (find with `grep -rln "parse_warning_text" tests/`)

**Interfaces:**
- Produces: `ForecastPoint` frozen dataclass `{tau_h: int | None, valid_at: str, lat: float, lon: float, max_wind_kt: int | None}`; `CycloneAdvisory.forecast_points: tuple[ForecastPoint, ...] = ()` (appended field — all construction in this repo is keyword-style, verified, so appending with a default is safe); `parse_jtwc_forecast_sections(text: str) -> tuple[ForecastPoint, ...]` and `parse_nhc_forecast_advisory(text: str) -> tuple[ForecastPoint, ...]` in `src/data/cyclones.py`.
- Consumes: `advisory_text` already stored by both feeds; `CurrentStorms.json` storm objects (NHC leg fetches the TCM url found in Task 0).

- [ ] **Step 1: Write the failing parser tests** with VERBATIM fixture text (adjust only
if Task 0 observed a different shape — then update BOTH fixture and regex together):

```python
_JTWC_WARNING_FIXTURE = """\
SUPER TYPHOON 05W (BAVI) WARNING NR 024
...
WARNING POSITION:
060600Z --- NEAR 21.8N 126.9E
MOVEMENT PAST SIX HOURS - 310 DEGREES AT 08 KTS
MAX SUSTAINED WINDS - 135 KT, GUSTS 165 KT
...
FORECASTS:
12 HRS, VALID AT:
070000Z --- 22.9N 125.7E
MAX SUSTAINED WINDS - 130 KT, GUSTS 160 KT
...
24 HRS, VALID AT:
071200Z --- 23.9N 124.2E
MAX SUSTAINED WINDS - 120 KT, GUSTS 145 KT
...
48 HRS, VALID AT:
081200Z --- 25.4N 121.6E
MAX SUSTAINED WINDS - 95 KT, GUSTS 115 KT
"""


def test_parse_jtwc_forecast_sections_extracts_tau_position_wind():
    points = parse_jtwc_forecast_sections(_JTWC_WARNING_FIXTURE)
    assert [p.tau_h for p in points] == [12, 24, 48]
    assert points[0].lat == 22.9 and points[0].lon == 125.7
    assert points[0].max_wind_kt == 130
    # valid_at keeps the raw DDHHMMZ token; consumers resolve it against
    # the advisory's issued_at month/year (Task 3).
    assert points[0].valid_at == "070000Z"
    assert points[2].lat == 25.4 and points[2].lon == 121.6


def test_parse_jtwc_forecast_sections_west_longitudes_negative():
    text = "FORECASTS:\n12 HRS, VALID AT:\n070000Z --- 22.9N 125.7W\nMAX SUSTAINED WINDS - 040 KT, GUSTS 050 KT\n"
    (p,) = parse_jtwc_forecast_sections(text)
    assert p.lon == -125.7


def test_parse_jtwc_forecast_sections_empty_on_no_forecast_block():
    assert parse_jtwc_forecast_sections("MAX SUSTAINED WINDS - 135 KT") == ()


_NHC_TCM_FIXTURE = """\
FORECAST VALID 08/0000Z 24.5N 122.0W
MAX WIND 105 KT...GUSTS 130 KT.

FORECAST VALID 08/1200Z 25.6N 123.4W
MAX WIND  95 KT...GUSTS 115 KT.
"""


def test_parse_nhc_forecast_advisory_extracts_points():
    points = parse_nhc_forecast_advisory(_NHC_TCM_FIXTURE)
    assert len(points) == 2
    assert points[0].valid_at == "08/0000Z"
    assert points[0].lat == 24.5 and points[0].lon == -122.0
    assert points[0].max_wind_kt == 105
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/ -k "forecast_sections or forecast_advisory" -v` → FAIL (functions not defined).

- [ ] **Step 3: Implement in `src/data/cyclones.py`** (near `CycloneAdvisory`):

```python
@dataclass(frozen=True)
class ForecastPoint:
    """One official forecast position from a warning/forecast-advisory product.

    ``valid_at`` is the RAW time token as printed by the product (JTWC
    ``DDHHMMZ``; NHC ``DD/HHMMZ``) — resolving it to an absolute datetime
    needs the advisory's issued_at month/year and is done at detection time,
    never here (parsers stay pure text→fields).
    """
    valid_at: str
    lat: float
    lon: float
    max_wind_kt: int | None = None
    tau_h: int | None = None


_JTWC_TAU_RE = re.compile(r"^\s*(\d{2,3})\s+HRS?,\s*VALID\s+AT:", re.MULTILINE)
_JTWC_POINT_RE = re.compile(
    r"(\d{6}Z)\s*-{1,3}\s*(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])"
)
_JTWC_FCST_WIND_RE = re.compile(r"MAX\s+SUSTAINED\s+WINDS\s*-\s*(\d+)\s*KT")


def parse_jtwc_forecast_sections(text: str) -> tuple[ForecastPoint, ...]:
    """Extract forecast positions from a JTWC warning product's FORECASTS
    block. Returns () when the text carries no forecast sections — a
    warning without forecasts simply produces no land-threat signal."""
    marker = text.find("FORECASTS:")
    if marker < 0:
        return ()
    body = text[marker:]
    points: list[ForecastPoint] = []
    taus = list(_JTWC_TAU_RE.finditer(body))
    for i, tau_match in enumerate(taus):
        seg_end = taus[i + 1].start() if i + 1 < len(taus) else len(body)
        segment = body[tau_match.start():seg_end]
        pos = _JTWC_POINT_RE.search(segment)
        if not pos:
            continue
        wind = _JTWC_FCST_WIND_RE.search(segment)
        lat = float(pos.group(2)) * (1 if pos.group(3) == "N" else -1)
        lon = float(pos.group(4)) * (1 if pos.group(5) == "E" else -1)
        points.append(ForecastPoint(
            valid_at=pos.group(1),
            lat=lat,
            lon=lon,
            max_wind_kt=int(wind.group(1)) if wind else None,
            tau_h=int(tau_match.group(1)),
        ))
    return tuple(points)


_NHC_FCST_RE = re.compile(
    r"FORECAST\s+VALID\s+(\d{2}/\d{4}Z)\s+(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])"
    r"(?:\s*\nMAX\s+WIND\s+(\d+)\s*KT)?",
)


def parse_nhc_forecast_advisory(text: str) -> tuple[ForecastPoint, ...]:
    """Extract forecast positions from an NHC Forecast/Advisory (TCM) text."""
    points: list[ForecastPoint] = []
    for m in _NHC_FCST_RE.finditer(text):
        lat = float(m.group(2)) * (1 if m.group(3) == "N" else -1)
        lon = float(m.group(4)) * (1 if m.group(5) == "E" else -1)
        points.append(ForecastPoint(
            valid_at=m.group(1),
            lat=lat,
            lon=lon,
            max_wind_kt=int(m.group(6)) if m.group(6) else None,
        ))
    return tuple(points)
```

Append to `CycloneAdvisory` (after `source_leg`): `forecast_points: tuple[ForecastPoint, ...] = ()`.

- [ ] **Step 4: Thread the JTWC leg** — in `src/data/jtwc.py` `parse_warning_text`
(line ~158-172), add to the returned `CycloneAdvisory(...)`:
`forecast_points=parse_forecast := parse_jtwc_forecast_sections(clean)` — concretely:

```python
        forecast_points=parse_jtwc_forecast_sections(clean),
```

(import `parse_jtwc_forecast_sections` from `src.data.cyclones`).

- [ ] **Step 5: Thread the NHC leg** — in `src/data/nhc.py` `_parse_active_storm`: read
the TCM product url from the storm object using the key confirmed in Task 0
(`_first_present(raw, "forecastAdvisory", ...)` then its `"url"`), fetch it with the
existing `_fetch_advisory_text` helper, and set
`forecast_points=parse_nhc_forecast_advisory(tcm_text)` (empty tuple when the url is
absent or the fetch fails — the storm still parses; the land-threat signal just doesn't
fire from this feed). One extra HTTP fetch per active storm per cycle.

- [ ] **Step 6: Run** — parser tests PASS; then the full cyclone module:
`.venv/bin/python -m pytest tests/ -k "cyclone or jtwc or nhc" -q` → PASS.

- [ ] **Step 7: Commit** — `git add src/data/cyclones.py src/data/jtwc.py src/data/nhc.py tests/ && git commit -m "feat(cyclone): parse official forecast track points from JTWC warnings + NHC TCM (#375 data half)"`

### Task 2: Landmass resolution (`src/data/land_threat_geo.py`)

**Files:**
- Create: `src/data/land_threat_geo.py`
- Test: `tests/test_land_threat_geo.py`

**Interfaces:**
- Consumes: `load_cities` (`src/data/open_meteo.py:218-220`, reads `data/cities.csv`: columns `city,country,lat,lon,elevation_m`, 638 rows); `_haversine_km` (`src/editorial/_regions.py:127-135`).
- Produces: `NearestLandmass` frozen dataclass `{country: str, city: str, distance_nm: float}`; `nearest_landmass(lat: float, lon: float, cities: list[dict]) -> NearestLandmass | None`; constant `NM_PER_KM = 1 / 1.852`.

- [ ] **Step 1: Write the failing tests**

```python
from src.data.land_threat_geo import NearestLandmass, nearest_landmass

_CITIES = [
    {"city": "Taipei", "country": "Taiwan", "lat": "25.03", "lon": "121.57", "elevation_m": "9"},
    {"city": "Manila", "country": "Philippines", "lat": "14.60", "lon": "120.98", "elevation_m": "16"},
]


def test_nearest_landmass_picks_the_closest_city_and_converts_to_nm():
    # A point ~1 degree east of Taipei (~59 NM at this latitude).
    result = nearest_landmass(25.03, 122.57, _CITIES)
    assert result is not None
    assert result.country == "Taiwan"
    assert result.city == "Taipei"
    assert 50 < result.distance_nm < 60


def test_nearest_landmass_none_on_empty_cities():
    assert nearest_landmass(25.0, 122.0, []) is None
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/test_land_threat_geo.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
"""Nearest-named-landmass resolution for the cyclone land-threat signal.

v1 approximates "named landmass" as the nearest populated place in the
curated data/cities.csv (638 cities) — the landmass NAME is that city's
country, and the tweet may say "near <city>". This is deliberately coarse
and conservative: a forecast point within LAND_THREAT_MAX_NM of a curated
city is unambiguously approaching land a reader can name. A true
coastline-geometry check is a noted fast-follow; no coastline dataset
exists in this repo today.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.editorial._regions import _haversine_km

NM_PER_KM = 1 / 1.852


@dataclass(frozen=True)
class NearestLandmass:
    country: str
    city: str
    distance_nm: float


def nearest_landmass(lat: float, lon: float, cities: list[dict]) -> NearestLandmass | None:
    best: NearestLandmass | None = None
    for row in cities:
        try:
            c_lat = float(row["lat"])
            c_lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        distance_nm = _haversine_km(lat, lon, c_lat, c_lon) * NM_PER_KM
        if best is None or distance_nm < best.distance_nm:
            best = NearestLandmass(
                country=str(row.get("country") or "").strip(),
                city=str(row.get("city") or "").strip(),
                distance_nm=round(distance_nm, 1),
            )
    return best
```

- [ ] **Step 4: Run** → PASS. If Task 0 Step 3 found cities.csv missing the Taiwan
anchors, add them to `data/cities.csv` now (real coordinates, one commit line each).

- [ ] **Step 5: Commit** — `git add src/data/land_threat_geo.py tests/test_land_threat_geo.py data/cities.csv && git commit -m "feat(cyclone): nearest-landmass resolution over curated cities (#375 geo half)"`

### Task 3: The detector (`detect_land_threats`)

**Files:**
- Modify: `src/data/cyclones.py`
- Test: the cyclone test module

**Interfaces:**
- Consumes: `CycloneAdvisory.forecast_points` (Task 1), `nearest_landmass` (Task 2), the existing `event_key` helper (`src/data/cyclones.py:137-139`) and `tracking_key`.
- Produces: `LandThreatEvent` frozen dataclass `{source, storm_id, storm_name, basin, advisory_number, issued_at, current_wind_kt, landmass_country, nearest_city, min_distance_nm, closest_valid_at, closest_tau_h: int | None, forecast_wind_kt_at_closest: int | None, event_id}`; `detect_land_threats(advisories, drafted_pairs, cities, *, now) -> list[LandThreatEvent]`; constants `LAND_THREAT_MAX_NM = 150.0`, `LAND_THREAT_MAX_HOURS = 72`, `LAND_THREAT_MIN_WIND_KT = 64`.

**Time resolution rule (spell it out in code comments):** `valid_at` tokens are
day-of-month + time. Resolve each against the advisory's `issued_at` (ISO string):
same month/year when the token's day ≥ issued day, else roll to the next month. Skip
any point that resolves to more than `LAND_THREAT_MAX_HOURS` after `now`. Prefer
`tau_h` when present (JTWC): `eta = issued_at + tau_h hours` — simpler and immune to
month-roll bugs; fall back to token resolution only for NHC points (no tau).

- [ ] **Step 1: Write the failing tests** (dates TODAY-RELATIVE — build `issued_at`
from `datetime.now(timezone.utc)`, never a literal date, per the canary rule):

```python
def _advisory_with_forecast(points, *, wind_kt=135, storm_id="05W", name="BAVI"):
    now = datetime.now(timezone.utc)
    return CycloneAdvisory(
        source="jtwc", storm_id=storm_id, storm_name=name, basin="WP",
        advisory_number="024", issued_at=now.isoformat(), wind_kt=wind_kt,
        lat=21.8, lon=126.9, forecast_points=tuple(points),
    )

_TAIPEI = [{"city": "Taipei", "country": "Taiwan", "lat": "25.03", "lon": "121.57", "elevation_m": "9"}]


def test_land_threat_fires_when_forecast_point_near_landmass():
    adv = _advisory_with_forecast([
        ForecastPoint(valid_at="ignored", lat=25.4, lon=121.6, max_wind_kt=95, tau_h=48),
    ])
    events = detect_land_threats([adv], drafted_pairs={}, cities=_TAIPEI,
                                 now=datetime.now(timezone.utc))
    assert len(events) == 1
    ev = events[0]
    assert ev.landmass_country == "Taiwan"
    assert ev.nearest_city == "Taipei"
    assert ev.min_distance_nm < 30
    assert ev.closest_tau_h == 48
    assert ev.forecast_wind_kt_at_closest == 95
    assert ev.event_id == event_key("jtwc", "land_threat", "05W", "024", "taiwan")


def test_land_threat_skips_weak_storms():
    adv = _advisory_with_forecast(
        [ForecastPoint(valid_at="x", lat=25.4, lon=121.6, tau_h=24)], wind_kt=45)
    assert detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(timezone.utc)) == []


def test_land_threat_skips_far_or_late_points():
    adv = _advisory_with_forecast([
        ForecastPoint(valid_at="x", lat=5.0, lon=150.0, tau_h=24),   # far (> MAX_NM)
        ForecastPoint(valid_at="x", lat=25.4, lon=121.6, tau_h=96),  # late (> MAX_HOURS)
    ])
    assert detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(timezone.utc)) == []


def test_land_threat_one_shot_per_storm_landmass_pair():
    adv = _advisory_with_forecast(
        [ForecastPoint(valid_at="x", lat=25.4, lon=121.6, tau_h=48)])
    drafted = {"jtwc:05w": ["taiwan"]}
    assert detect_land_threats([adv], drafted, _TAIPEI, now=datetime.now(timezone.utc)) == []


def test_land_threat_picks_the_closest_qualifying_point():
    adv = _advisory_with_forecast([
        ForecastPoint(valid_at="x", lat=23.9, lon=124.2, max_wind_kt=120, tau_h=24),
        ForecastPoint(valid_at="x", lat=25.4, lon=121.6, max_wind_kt=95, tau_h=48),
    ])
    (ev,) = detect_land_threats([adv], {}, _TAIPEI, now=datetime.now(timezone.utc))
    assert ev.closest_tau_h == 48  # 25.4N/121.6E is nearer Taipei
```

- [ ] **Step 2: Run to verify failure** → FAIL (names not defined).

- [ ] **Step 3: Implement in `src/data/cyclones.py`:**

```python
LAND_THREAT_MAX_NM = 150.0
LAND_THREAT_MAX_HOURS = 72
LAND_THREAT_MIN_WIND_KT = 64  # current intensity >= Cat 1; TS threats are routine


def _landmass_slug(country: str) -> str:
    return country.strip().lower().replace(" ", "_")


def detect_land_threats(
    advisories: list[CycloneAdvisory],
    drafted_pairs: dict[str, list[str]],
    cities: list[dict],
    *,
    now: datetime,
) -> list[LandThreatEvent]:
    """A warned storm whose official forecast brings its CENTER within
    LAND_THREAT_MAX_NM of a curated populated place within
    LAND_THREAT_MAX_HOURS → one event per (storm, landmass) pair, ever.

    Pure: reads drafted_pairs, never writes it — the caller records the
    pair only after a draft is successfully saved (the fire_complex_tiers
    callback pattern).
    """
    events: list[LandThreatEvent] = []
    for adv in advisories:
        if adv.wind_kt < LAND_THREAT_MIN_WIND_KT or not adv.forecast_points:
            continue
        already = {s.lower() for s in drafted_pairs.get(adv.tracking_key, [])}
        best: tuple[NearestLandmass, ForecastPoint] | None = None
        for point in adv.forecast_points:
            eta_h = point.tau_h
            if eta_h is not None and eta_h > LAND_THREAT_MAX_HOURS:
                continue
            if eta_h is None and not _valid_at_within_hours(
                point.valid_at, adv.issued_at, now, LAND_THREAT_MAX_HOURS
            ):
                continue
            near = nearest_landmass(point.lat, point.lon, cities)
            if near is None or near.distance_nm > LAND_THREAT_MAX_NM:
                continue
            if _landmass_slug(near.country) in already:
                continue
            if best is None or near.distance_nm < best[0].distance_nm:
                best = (near, point)
        if best is None:
            continue
        near, point = best
        slug = _landmass_slug(near.country)
        events.append(LandThreatEvent(
            source=adv.source, storm_id=adv.storm_id, storm_name=adv.storm_name,
            basin=adv.basin, advisory_number=adv.advisory_number,
            issued_at=adv.issued_at, current_wind_kt=adv.wind_kt,
            landmass_country=near.country, nearest_city=near.city,
            min_distance_nm=near.distance_nm, closest_valid_at=point.valid_at,
            closest_tau_h=point.tau_h,
            forecast_wind_kt_at_closest=point.max_wind_kt,
            event_id=event_key(adv.source, "land_threat", adv.storm_id,
                               adv.advisory_number, slug),
        ))
    return events
```

with the `LandThreatEvent` frozen dataclass (fields exactly as the Interfaces block) and
`_valid_at_within_hours(token, issued_at_iso, now, max_hours) -> bool` — parse
`DDHHMMZ` / `DD/HHMMZ` against issued_at's month/year with next-month rollover when the
token's day < issued day; return False on any parse failure (fail-closed: an unparsable
time never mints an event). Import `nearest_landmass`/`NearestLandmass` from
`src.data.land_threat_geo` and `datetime` as needed.

- [ ] **Step 4: Run** → all Task 3 tests PASS.
- [ ] **Step 5: Commit** — `git add src/data/cyclones.py tests/ && git commit -m "feat(cyclone): detect_land_threats — forecast-track proximity, one shot per storm-landmass pair (#375)"`

### Task 4: The drafted-pairs state key (+ MERGE_SPEC, the contract test)

**Files:**
- Modify: `src/state.py`, `src/state_schema.py`
- Test: wherever the MERGE_SPEC contract test lives (`grep -rln "MERGE_SPEC" tests/` — it fails collection if a DEFAULT_STATE key lacks a MERGE_SPEC entry; run it to find the exact expectations)

**Interfaces:**
- Produces: `DEFAULT_STATE["cyclone_land_threat_pairs"] = {}` (`dict[str, list[str]]`, tracking_key → drafted landmass slugs); `record_land_threat_pair(state, tracking_key: str, landmass_slug: str) -> BotState`; MERGE_SPEC entry `_merge_land_threat_pairs` (per-key list union, sorted, deduped); TTL via the `_TIER_TTLS_DAYS` mechanism, 30 days (match `cyclone_tiers`).

- [ ] **Step 1: Failing tests**

```python
def test_record_land_threat_pair_appends_once():
    s = deepcopy(DEFAULT_STATE)
    record_land_threat_pair(s, "jtwc:05w", "taiwan")
    record_land_threat_pair(s, "jtwc:05w", "taiwan")
    record_land_threat_pair(s, "jtwc:05w", "philippines")
    assert s["cyclone_land_threat_pairs"]["jtwc:05w"] == ["philippines", "taiwan"]


def test_merge_land_threat_pairs_unions_per_key():
    ours = {"jtwc:05w": ["taiwan"]}
    theirs = {"jtwc:05w": ["philippines"], "nhc:al032026": ["mexico"]}
    merged = _merge_land_threat_pairs(ours, theirs)
    assert merged == {"jtwc:05w": ["philippines", "taiwan"], "nhc:al032026": ["mexico"]}
```

- [ ] **Step 2: Verify failure**, including the MERGE_SPEC contract test failing once
the DEFAULT_STATE key exists without its MERGE_SPEC entry (add the key first, run the
contract test, watch it fail — that failure is the guardrail working).

- [ ] **Step 3: Implement** — DEFAULT_STATE entry beside the other cyclone keys
(`src/state.py:179-184`) with a comment; `state_schema.py` field
`cyclone_land_threat_pairs: dict[str, list[str]]` beside the cyclone fields
(`src/state_schema.py:270-272`); setter mirroring `update_fire_complex_tier`'s shape
(`src/state.py:1946-1956`) with `_touch_tier(state, "cyclone_land_threat_pairs", tracking_key)`
and `_TIER_TTLS_DAYS["cyclone_land_threat_pairs"] = 30`; merge helper:

```python
def _merge_land_threat_pairs(
    ours: dict[str, list[str]], theirs: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Per-storm union of drafted landmass slugs — a pair recorded by either
    concurrent run stays recorded (one-shot dedup must never regress)."""
    merged: dict[str, list[str]] = {}
    for key in set(ours) | set(theirs):
        merged[key] = sorted(set(ours.get(key, [])) | set(theirs.get(key, [])))
    return merged
```

wired as `"cyclone_land_threat_pairs": _merge_land_threat_pairs` in MERGE_SPEC
(`src/state.py:1818-1820` block).

- [ ] **Step 4: Run** — the new tests AND the MERGE_SPEC contract test PASS.
- [ ] **Step 5: Commit** — `git add src/state.py src/state_schema.py tests/ && git commit -m "feat(state): cyclone_land_threat_pairs — one-shot dedup with union merge + 30d TTL"`

### Task 5: Scoring + threshold + category map

**Files:**
- Modify: `src/editorial/scoring/disasters.py`, `src/editorial/scoring/__init__.py`, `src/editorial/thresholds.py`, `src/two_bot/memory.py`, `src/editorial/approval.py` (comment only)
- Test: `tests/test_thresholds.py` (the registry test maps scoring fns → categories — extend it), plus a scoring unit test beside the other cyclone scoring tests

**Interfaces:**
- Produces: `score_cyclone_land_threat(*, current_wind_kt: int, min_distance_nm: float, closest_tau_h: int | None, landmass_country: str) -> EditorialScore` in `disasters.py`, proxied through `scoring/__init__.py` exactly like `score_regional_anomaly` (`src/editorial/scoring/__init__.py:80-82` pattern + `__all__`); `ThresholdEntry("cyclone_land_threat", 70, "Warned storm forecast within 150 NM of a named landmass — landfall-grade newsworthiness, forecast-tense, manual_only")` in `THRESHOLDS` beside the other cyclone entries (`src/editorial/thresholds.py:72-91`); `"cyclone_land_threat": "cyclone"` in `_SIGNAL_KIND_TO_CATEGORY` (`src/two_bot/memory.py:58-61`); one line added to the approval exclusion COMMENT (`src/editorial/approval.py:22-29`) noting the type (the `startswith("cyclone_")` rule at `:254` already forces manual — no logic change).
- Scoring recipe (keep the house `_shared` composition — severity/novelty/timeliness/confidence/shareability/sensitivity): severity scales with `current_wind_kt` (64 kt → ~60, 135 kt → ~95, linear clamp); timeliness scales inversely with `closest_tau_h` (≤24h → 95, 72h → 70, None → 75); confidence 90 (official agency forecast); novelty 80 (one-shot by construction); shareability 85 when `min_distance_nm ≤ 60` else 75; sensitivity 40 (life-safety adjacent — same posture as landfall).

- [ ] Steps: failing scoring test (assert a Bavi-class input `current_wind_kt=135,
min_distance_nm=25, closest_tau_h=48` clears 70; a marginal `65 kt / 140 NM / 72h` does
not) → implement → registry/threshold tests green → commit
`"feat(editorial): cyclone_land_threat scoring + threshold 70 + category map"`.

### Task 6: Intern bundle + prompt conventions (paired)

**Files:**
- Modify: `src/two_bot/intern/disasters.py`, `src/two_bot/intern/__init__.py`
- Modify: `src/two_bot/prompts/writer_prompt.py`, `src/two_bot/prompts/fact_check_prompt.py`
- Test: `tests/two_bot/test_intern.py`, `tests/two_bot/test_prompts.py`

**Interfaces:**
- Produces: `build_cyclone_land_threat_bundle(ev: LandThreatEvent) -> StoryBundle` with `signal_kind="cyclone_land_threat"`; `current_facts` labels exactly: `storm_name`, `basin`, `current_wind_kt`, `saffir_simpson_category` (from the existing helper), `landmass_country`, `nearest_city`, `min_distance_nm`, `closest_tau_h`, `forecast_wind_kt_at_closest`, `advisory_number`, `forecast_basis` = `"official forecast track (JTWC/NHC)"`; `raw_signal_dump` includes `storm_id` and `source` (these are in the evidence contract's source-like anchor tokens, `src/two_bot/evidence_contract.py:34-44` — a missing anchor is only a WARNING there, but include them anyway: they also feed auditability and the fact-checker's raw view); `historical_context={}`.
- Writer prompt: a compact convention block (row 11 upgrades it to full four-moves later) added to the cyclone bundle conventions:

```markdown
- **Land-threat bundles (`signal_kind = "cyclone_land_threat"`)** are FORECASTS, not
  observations. Every arrival claim rides forecast tense anchored to the official
  track: "forecast to pass within about 25 NM of Taipei within 48 hours, per the
  official track" — never "will hit", "is hitting", "makes landfall Tuesday", and
  never a certainty the forecast itself doesn't carry. Cite `min_distance_nm` with
  "about"; `closest_tau_h` as "within N hours"; the current intensity
  (`current_wind_kt`, category) is the observed anchor and leads. All standing
  cyclone bans (no alarmism, no BREAKING, no category-bait opener) apply.
```

- Fact-check pairing appended after the file's current last lettered rule (letter it to
  follow whatever the file ends at when this PR lands — rows 4/5/7 merge in any order;
  the tests pin the phrase, never the letter):

```markdown
**<next letter>) Cyclone land-threat drafts are forecast-tense-or-fail.** For
`cyclone_land_threat` bundles: distance/time claims must match
`min_distance_nm`/`closest_tau_h` (BUNDLE_FACT, "about" marker fine); ANY
present/certain-tense arrival claim ("is making landfall", "will hit", a named
arrival day stated as fact) is a FAILURE — the bundle carries a forecast, and the
only honest tense is forecast tense attributed to the official track.
```

- [ ] Steps: failing intern test (all labels above present; `signal_kind`; `storm_id`
in raw dump; evidence contract `prompt_ready`) + failing prompt tests (pin
`cyclone_land_threat` in WRITER_SYSTEM_PROMPT, `"forecast-tense-or-fail"` in
FACT_CHECK_SYSTEM_PROMPT) → run FAIL → implement → PASS → commit
`"feat(cyclone): land-threat bundle + forecast-tense prompt conventions, paired (#375)"`.

### Task 7: Orchestrator wiring

**Files:**
- Modify: `src/orchestrator/cyclones.py`
- Test: the orchestrator cyclone tests (`grep -rln "_process_cyclone_source" tests/`)

**Interfaces:**
- Consumes: `detect_land_threats` (Task 3), `record_land_threat_pair` (Task 4), `score_cyclone_land_threat` (Task 5), `build_cyclone_land_threat_bundle` (Task 6), `load_cities` (`src/data/open_meteo.py:218`), the existing `isinstance` dispatch in `_score_cyclone_event` (`src/orchestrator/cyclones.py:72-93`) and `_bundle_for_cyclone_event` (`:96-112`), `_enqueue_story_candidate` + `on_draft_success` (the `src/orchestrator/sources/nifc.py:88-104` pattern), `state.is_duplicate`.
- Behavior: inside `_process_cyclone_source` (after the landfall block) — exact shape,
with the closure deriving its keys from the event (neither `tracking_key` nor `slug`
rides `LandThreatEvent`; derive both, bound as defaults, the `nifc.py:88-93` pattern):

```python
    land_threats = detect_land_threats(
        advisories,
        bot_state.get("cyclone_land_threat_pairs", {}),
        load_cities(),
        now=datetime.now(timezone.utc),
    )
    for lt in land_threats:
        if state.is_duplicate(bot_state, lt.event_id):
            continue
        lt_score = score_cyclone_land_threat(
            current_wind_kt=lt.current_wind_kt,
            min_distance_nm=lt.min_distance_nm,
            closest_tau_h=lt.closest_tau_h,
            landmass_country=lt.landmass_country,
        )
        if not _should_draft(lt_score, lt.event_id):
            continue
        lt_bundle = build_cyclone_land_threat_bundle(lt)
        _tk = tracking_key(lt.source, lt.storm_id)
        _slug = _landmass_slug(lt.landmass_country)

        def _on_success(_bs: BotState = bot_state, _k: str = _tk, _s: str = _slug) -> None:
            state.record_land_threat_pair(_bs, _k, _s)

        _enqueue_story_candidate(
            bot_state,
            bundle=lt_bundle,
            score=lt_score,
            source=source_key,               # "nhc" or "jtwc" — the feed this
                                             # _process_cyclone_source pass runs for;
                                             # telemetry attribution only bumps when
                                             # this matches the run's source entry
                                             # (src/orchestrator/telemetry.py:90)
            legacy_type="cyclone_land_threat",
            event_id=lt.event_id,
            review_context=_lt_review_context,
            on_draft_success=_on_success,
        )
```

**Attribution rules (codex round 2 on this plan — do not improvise here):**
(a) `source=` must be the SAME `source_key` ("nhc"/"jtwc") this
`_process_cyclone_source` pass already uses for the RI/tier/landfall enqueues — read
the neighboring enqueue in this function and pass the identical variable; a made-up
key like "cyclones" silently loses triaged/drafted telemetry.
(b) `_lt_review_context` must be built EXACTLY the way the neighboring cyclone events
build theirs (there is an existing review-context construction beside the other
enqueues in this function — copy its shape, including the `source_key` entry that
`finalize.py`'s prune attribution reads for types without a static mapping).
(c) If the neighboring enqueues bump a promoted/observed counter for this source
(look for the counter calls beside them), bump it identically for an admitted
land-threat candidate.
(imports: `tracking_key`, `_landmass_slug`, `detect_land_threats` from
`src.data.cyclones`; `load_cities` from `src.data.open_meteo`;
`record_land_threat_pair` via the `state` module like the other setters. The pair
records ONLY on draft success, so a killed draft retries on the next advisory.)

- [ ] Steps: failing orchestrator test (fake advisories with forecast points near a
fake city → exactly one candidate enqueued; the pair NOT recorded when the fake
enqueue reports no success; recorded after success) → implement (add the two
`isinstance` branches + the detection block) → PASS → commit
`"feat(cyclone): wire land-threat detection into the cyclone source (#375)"`.

### Task 8: `writer_dryrun --type cyclone_land_threat` (self-contained)

**Files:** `scripts/writer_dryrun.py`, `.github/workflows/writer-dryrun.yml`,
`tests/test_writer_dryrun.py`.

- [ ] **Step 1: Failing fixture tests** (append to `tests/test_writer_dryrun.py`):

```python
class TestCycloneLandThreatFixture:
    def test_bundle_shape_and_evidence(self):
        bundle = _build_bundle(_args(type="cyclone_land_threat"))
        assert bundle.signal_kind == "cyclone_land_threat"
        facts = {f["label"]: f.get("value") for f in bundle.current_facts}
        assert facts["landmass_country"] == "Taiwan"
        assert facts["min_distance_nm"] == 25.0
        assert facts["closest_tau_h"] == 48
        audit = audit_story_bundle(bundle)
        assert audit.prompt_ready, [i.code for i in audit.issues if i.severity == "error"]

    def test_no_impact_on_cyclone_fixture(self):
        bundle = _build_bundle(_args(type="cyclone_land_threat"))
        assert not getattr(bundle, "human_impact", None)
```

- [ ] **Step 2:** Run → FAIL (`invalid choice`).
- [ ] **Step 3:** Implement in `scripts/writer_dryrun.py` — DEFAULTS additions:

```python
    # cyclone_land_threat (Bavi-class) knobs
    "storm_name": "BAVI",
    "storm_wind_kt": 135,
    "landmass": "Taiwan",
    "landmass_city": "Taipei",
    "distance_nm": 25.0,
    "tau_h": 48,
    "forecast_wind_kt": 95,
```

argparse: add `"cyclone_land_threat"` to the `--type` choices plus
`--storm-name/--storm-wind-kt/--landmass/--landmass-city/--distance-nm/--tau-h/--forecast-wind-kt`
(defaults from DEFAULTS). `_build_bundle` branch:

```python
    if args.type == "cyclone_land_threat":
        lt = LandThreatEvent(
            source="jtwc", storm_id="05W", storm_name=args.storm_name,
            basin="WP", advisory_number="024",
            issued_at=datetime.now(UTC).isoformat(),
            current_wind_kt=args.storm_wind_kt,
            landmass_country=args.landmass, nearest_city=args.landmass_city,
            min_distance_nm=args.distance_nm, closest_valid_at="dryrun",
            closest_tau_h=args.tau_h,
            forecast_wind_kt_at_closest=args.forecast_wind_kt,
            event_id="dryrun_land_threat_05w",
        )
        return build_cyclone_land_threat_bundle(lt)
```

(imports: `LandThreatEvent` from `src.data.cyclones`,
`build_cyclone_land_threat_bundle` from `src.two_bot.intern`). `_print_bundle` gets a
branch printing storm/landmass/distance/tau. Workflow: add `cyclone_land_threat` to the
`type` choice options (inputs stay env-only).

- [ ] **Step 4:** Tests PASS + no-keys smoke exits 2. **Step 5:** Commit
`"feat(dryrun): --type cyclone_land_threat — Bavi-class fixture"`.

### Task 9: Version, changelog, full gates

VERSION minor bump; CHANGELOG `[Unreleased]` entry naming: the class, the one-shot pair
dedup, forecast-tense pairing, tunables (150 NM / 72 h / ≥64 kt), and that Bavi is the
motivating case (#375). Then the full gate battery (ruff / mypy / 90-day canary) — all
green. Commit `"chore: bump + changelog for cyclone_land_threat"`.

### Task 10: Push, PR, codex-xhigh loop, merge, live verify

- [ ] PR body: link #375; state the tunables and that they are Andrew's coverage knobs;
include Task 0's contract findings verbatim.
- [ ] codex-xhigh loop (INDEX rules). Ask it specifically to attack: the `valid_at`
month-rollover resolution; W-longitude sign handling end-to-end (NHC Atlantic storms);
the one-shot-pair race (two cycles drafting before the first records — the
`is_duplicate` event_id guard plus pair-check both live, verify they compose); whether
any prompt loosening escapes rule (n); the extra per-storm TCM fetch's failure mode
(must degrade to no-forecast, never crash the source).
- [ ] Merge on green + verify squash (INDEX rules).
- [ ] **Live verify:** dispatch `writer-dryrun --type cyclone_land_threat` → the draft
must read forecast-tense and clear all gates. Then watch the next real warned storm
(check JTWC/NHC): the event should appear as a `manual_only` draft in the dashboard
within one cycle of a qualifying forecast, exactly once per landmass. If Bavi is still
a warned storm when this merges, it IS the live verify.

**Success criteria for the row:** the next Bavi-class approach produces a pending
forecast-tense draft while the threat is still forecast (not after landfall); zero
duplicate drafts per storm-landmass; #375 closes with a link to the first live draft.
