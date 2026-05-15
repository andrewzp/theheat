# Lane 14 — Plan F: Climate Indices (NAO/AO/PDO + Antarctic Ozone Hole)

**Branch:** `plan-f/climate-indices`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (Bucket 6: climate indices)
**Scope:** Add long-arc climate-mode signals — NAO, AO, PDO oscillations + Antarctic ozone hole seasonal
**Estimated time:** 3-4 hours CC, single PR
**Parallel-safety:** **Conflicts with Lane 12 (floods), Lane 13 (precip/snow), Lane 15 (threshold registry).** Sequential.

## Why this lane exists

Long-cycle climate signals are invisible to @theheat today. ENSO is on the pipeline already (`src/data/enso.py`) but the parallel cousins — North Atlantic Oscillation, Arctic Oscillation, Pacific Decadal Oscillation — are all canonical climate-mode indices that publish monthly and shift weather patterns regionally. Plus the Antarctic ozone hole, which is a seasonal climate-system story (recovery is one of the genuine planetary-scale good-news stories of the late 20th century).

All four signals are NOAA/NASA-published, low-volume (1-12 events/year each), and editorially valuable for "the planet keeps its own record" framing.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — Bucket 6
2. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/enso.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/enso.py) — closest precedent. ENSO is the same shape: monthly NOAA text file, phase-transition detector, annual cap. NAO/AO/PDO follow identical patterns.
3. [/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py) — annual-seasonal pattern. Ozone hole is similar: seasonal peak detection, once-a-year fire.

## Sub-task 14a — NAO/AO/PDO indices (combined module)

**Sources** (all NOAA NCEI, free, monthly text files):
- NAO: `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/nao.txt`
- AO: `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ao.txt`
- PDO: `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/pdo.txt`
- (Verify current URLs via curl first; NOAA has reorganized index file paths in the past.)

**Detection rules:**

1. **Phase transition:** NAO/AO crosses zero with duration ≥3 months in the prior phase. Mirror `score_enso_transition` shape.
2. **Extreme excursion:** monthly value > 2σ from the long-term mean. PDO transitions are particularly newsworthy because the PDO regime can persist for decades.
3. **Multi-index alignment:** when NAO + AO are both extreme negative (winter blocking pattern), fire a synthesis-style signal.

**Files:**
- `src/data/climate_indices.py` (new) — `OscillationTransition`, `OscillationExtremeEvent` dataclasses + `fetch_nao()`, `fetch_ao()`, `fetch_pdo()` + detector functions. Single module is fine since all three sources share parsing shape.
- Annual caps: NAO 6/year, AO 6/year, PDO 3/year (decadal cycle — rare events).

## Sub-task 14b — Antarctic ozone hole

**Source:** NASA Ozone Watch.
- API: `https://ozonewatch.gsfc.nasa.gov/data/` (CSV time series of daily ozone measurements)
- Daily during austral spring (Aug-Nov); annual peak around mid-September

**Detection rules:**

1. **Annual peak:** when the seasonal hole reaches its maximum area for the year. One tweet/year per pole.
2. **Multi-year comparison:** the annual peak relative to the long-term recovery trend. The story is the planet's recovery from CFC bans — situate the data.
3. **Anomalous year:** any year where the hole grows larger than the previous year despite the long-term recovery trend.

**Files:**
- `src/data/ozone_hole.py` (new) — `OzoneHoleSeasonalEvent` dataclass + `fetch_ozone_hole_data()` + `detect_seasonal_peak()`.
- Annual cap: 2 tweets/year (peak event + retrospective comparison).

## Sub-task 14c — Shared scoring + bundle + orchestrator

- `src/editorial/scoring.py`:
  - `score_oscillation_transition(index_name, value, prev_duration_months)` — mirror `score_enso_transition`
  - `score_oscillation_extreme(index_name, sigma_excursion)`
  - `score_ozone_hole_peak(area_msqkm, vs_record_year)` — high novelty for recovery framing
- `src/two_bot/intern.py`:
  - `build_oscillation_bundle(event)` — carry index_name, value, prev_phase_duration, anchor_year for long-arc
  - `build_ozone_hole_bundle(event)` — carry area_msqkm, peak_date, comparison_year, comparison_area
- `src/editorial/approval.py` — oscillation transitions → `armed_auto` (high-confidence NOAA, low blast radius); ozone hole → `suggested_auto`
- `src/main.py::run_alerts` — wire sections. Run on first-of-month gates for NAO/AO/PDO; daily during Aug-Nov for ozone hole.
- `src/state.py` + `src/state_schema.py`:
  - `nao_annual_count`, `ao_annual_count`, `pdo_annual_count`
  - `nao_last_phase`, `ao_last_phase`, `pdo_last_phase` (for transition detection)
  - `ozone_hole_last_peak: dict[str, dict]` (year → peak_area)

## Editorial constraints

- **Index nomenclature.** Use full names on first use ("the North Atlantic Oscillation flipped to its negative phase") then the abbreviation ("NAO −1.8 by month-end"). Don't lead with "NAO is −1.8" — readers don't have the unit cached.
- **Era anchors for long-cycle signals.** "Last time PDO was this strongly negative: 1973." Pull comparison year from the bundle, never invent.
- **Ozone framing.** The story is recovery, not panic. "The hole reached 22 million sq km this September — smaller than the 2000 peak of 29.9, larger than last year's 18.6. The Montreal Protocol is working but slowly." Honor the systems frame.

## Acceptance

- mypy clean, ruff clean
- Full suite passes with ~25+ new tests
- Live source smoke: all four fetchers return data
- Manual workflow dispatch passes

## Constraints

- **Investigation-first commit.** Curl all four sources, document current URL + schema, flag any URL drift from this brief.
- **Subagent model floor:** Sonnet 4.6.

## Branch / PR sequence

1. Branch `plan-f/climate-indices` from `main`.
2. Investigation commit.
3. Implementation per sub-task.
4. PR → CI green → Claude merges.

Done. ~3-4 hours CC.
