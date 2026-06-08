# SST anomaly / regional marine heatwave — implementation plan

> **Revision 4: folded Codex data-layer review (2026-06-08) — supersedes Revision 3.**
>
> **Revision 3: gridded global SST source — supersedes Revision 2 ClimateReanalyzer 6-region approach per eng-review 2026-06-08.**
>
> Changes vs. Revision 2: (1) **DATA LAYER REDESIGNED for GLOBAL coverage.** The Revision 2 ClimateReanalyzer per-region JSON source (`oisst2.1_{slug}_sst_day.json`) is **SUPERSEDED** — it only publishes 6 Atlantic/Gulf/ENSO regions and can never cover the Pacific Blob, Mediterranean, Tasman, Indian Ocean, Coral Triangle, or the Great Barrier Reef. (2) New source is the **NOAA Coral Reef Watch (CRW) Daily Global 5km SST Anomaly** product served via **NOAA CoastWatch ERDDAP griddap** — a true global 0.05° gridded field, **published anomaly** (no self-built climatology), subset by lat/lon box, **no auth**. VERIFIED returning live data 2026-06-08 (see STEP 0). (3) Region set expanded from 6 to **13 global marquee basins** with explicit lat/lon bounding boxes. (4) Fetch computes an **area-weighted (cos-latitude) mean anomaly** over each region box. (5) The ClimateReanalyzer JSON helpers (`_normalise_series_payload`, `_current_year_series`, the `prior_arrs` climatology reconstruction) **no longer apply** — the source format changed from a year-keyed JSON time series to ERDDAP gridded CSV.
>
> **Unchanged from Revision 2 (downstream machinery — deliberately preserved):** scoring fn `score_regional_sst_anomaly`, threshold `regional_sst_anomaly`=76, intern `build_regional_sst_anomaly_bundle`, approval `manual_only` branch, annual-key tier-reset (`{YYYY}/{slug}`), the new `regional_sst_anomaly` category, tiered **absolute** anomaly (+2.5/+3.5/+4.5°C, NOT Hobday) for v1, event_id scheme `sst_anom_<slug>_tier<N>_<date>`. The named-basin shareability bump in the scorer is **updated to the new marquee slugs**.
>
> Carried forward from Revision 2: "marine heatwave" naming is still avoided throughout — the signal is "regional SST anomaly"; Hobday duration/percentile is NOT implemented.

Add per-region SST anomaly detection to @theheat: detect when a monitored ocean basin enters or intensifies a regional SST anomaly event (tiered absolute anomaly ≥ +2.5 / +3.5 / +4.5°C), distinct from the existing global-mean streak signal. **v1 covers 13 global basins worldwide**, not just the North Atlantic / Gulf.

---

## Background

**What exists today:**
`src/data/ocean_sst.py` fetches the ClimateReanalyzer JSON endpoint (`oisst2.1_world2_sst_day.json`) which carries the **global-mean** daily SST (area-weighted, 60°S–60°N) as a single scalar time series. The detection is a **streak signal**: how many consecutive days today's global mean exceeds every prior year's value on the same calendar day. Events fire at milestone day-counts (5, 10, 25, 50, … 400+). The `event_id` pattern is `marine_heatwave_streak_<days>_<date>`. **This existing global-mean signal is unchanged by this plan.**

`src/data/coral_dhw.py` already integrates NOAA Coral Reef Watch — but via the per-station **virtual-station text files** at `coralreefwatch.noaa.gov/product/vs/`, parsed with regex. That is a different CRW product (DHW per virtual station) and a different access path from the gridded ERDDAP product this plan uses. The shared lesson from `coral_dhw.py`: CRW data is publicly reachable over plain HTTP with a simple User-Agent, no auth.

**What this adds:**
Per-region / per-basin SST anomaly detection across the world's marquee ocean basins — e.g. the North Atlantic 2023 anomaly spike, the NE-Pacific "Blob," the 2022 Mediterranean marine heat event, recurring Tasman Sea and Great Barrier Reef heat. These are a qualitatively different story from the global-mean streak: they are **geographically specific, ecologically consequential at the local level** (fisheries, coral DHW amplification, atmospheric moisture anomalies), and the public has named references for them ("the Blob," "North Atlantic heat"). The global-mean streak signal is muted on any single basin event; the per-region signal fires directly.

The two signals use different event IDs, different categories, and separate dedup keys and can co-fire without collision.

**Important: this is NOT a Hobday MHW implementation.** Hobday et al. 2016 defines marine heatwave categories (I–IV) relative to the 90th percentile of a daily SST climatology at a given location. That requires a per-DOY 90th-percentile baseline built from a 30-year reference period. This is deferred to v2. v1 ships **tiered absolute anomaly** only. Because the CRW product publishes anomaly **relative to its own 1985–2012-derived daily climatology**, v1 does not build or store any climatology of its own. All copy, bundle fields, scoring, and test names use "regional SST anomaly" — never "marine heatwave" — to avoid overclaiming Hobday compliance.

---

## STEP 0 — Verify the gridded source endpoint (BLOCKING pre-step)

This step MUST be completed before writing any code. Unlike Revision 2 (which verified a list of JSON slugs), the new blocking pre-step is: **confirm the CRW ERDDAP griddap endpoint returns a lat/lon/time anomaly subset, with no auth, at acceptable data lag.**

### ✅ VERIFIED 2026-06-08 — endpoint returns live data

**Dataset:** *Sea Surface Temperature Anomaly, NOAA Coral Reef Watch Daily Global 5km Satellite SST Anomaly, 1985-present, Daily*
**ERDDAP dataset ID:** `noaacrwsstanomalyDaily`
**Host:** NOAA CoastWatch ERDDAP — `https://coastwatch.noaa.gov/erddap/`
**Info page:** `https://coastwatch.noaa.gov/erddap/info/noaacrwsstanomalyDaily/index.html`

**Confirmed dataset metadata (from `.das`):**
- **Anomaly variable:** `sea_surface_temperature_anomaly` (units `degree_C`, long_name "sea surface temperature anomaly"). **This is a PUBLISHED anomaly — no climatology build needed.**
- Also present: `mask` (pixel-classification flag) — usable later to exclude ice/land if desired; v1 ignores it.
- **Dimensions (order):** `[time][latitude][longitude]`.
- **Grid:** 0.05° (≈5 km). Latitude `actual_range` −89.975 → 89.975 (stored **descending**: 89.975 first). Longitude convention **−180 → 180** (`actual_range` −179.975 → 179.975).
- **time units:** `seconds since 1970-01-01T00:00:00Z`. ERDDAP accepts ISO time stamps and the literal `(last)`.
- **Data lag:** latest available timestamp on 2026-06-08 was `2026-06-06T12:00:00Z` → **~2-day lag.** `testOutOfDate` threshold is 3 days. Use `_MAX_DATA_LAG_DAYS = 5` for the freshness assertion (matches `coral_dhw`'s default).
- **Auth:** NONE. A plain `curl` with no headers and no cookie returned HTTP 200 `text/csv`; no `WWW-Authenticate`. $0-stack compliant. (Send the existing `_REQUEST_HEADERS` User-Agent anyway, as a courtesy / for parity with other sources.)

### ✅ Subset mechanism — VERIFIED working (griddap CSV)

Request URL shape (griddap, `.csv` filetype):

```
https://coastwatch.noaa.gov/erddap/griddap/noaacrwsstanomalyDaily.csv
  ?sea_surface_temperature_anomaly[(TIME)][(latN):STRIDE:(latS)][(lonW):STRIDE:(lonE)]
```

- `TIME` = `last` for the most recent grid, or an ISO stamp like `2026-06-06T12:00:00Z`.
- **Latitude must be given NORTH→SOUTH** (`(latN):(latS)`) to match the descending grid. (ERDDAP tolerated ascending order in testing, but specify descending to be safe.)
- **Longitude in −180/180**, `(lonW):(lonE)` with `lonW ≤ lonE`.
- `STRIDE` downsamples — see "area-weighting + stride" below. **This is mandatory**, not optional (see payload note).
- Brackets/parens must be URL-encoded in raw curl (`%5B %5D`), but Python `requests` with a `params` dict (or a pre-encoded URL string) handles this.

**Verified probes (2026-06-08):**

| probe | result |
|-------|--------|
| Niño-3.4-ish box `[(last)][(5):(0)][(-170):(-160)]` `.csv` | HTTP 200, returns rows `time,latitude,longitude,sea_surface_temperature_anomaly` with real values (~+1.5°C). |
| No-auth header check (`-I` on `.das`) | `HTTP/1.1 200`, `Content-Type text/csv` (for `.csv`); no `WWW-Authenticate`, no required cookie. |
| Explicit past date `[(2026-06-01T12:00:00Z)]…` | HTTP 200, rows stamped `2026-06-01T12:00:00Z` → time subsetting works. |
| North Atlantic box `[(60):(40)][(-50):(-20)]` **no stride** | HTTP 200 but **241,003 rows** (full 0.05° grid). Confirms the payload-size risk. |
| Same box **stride 20** `[(60):20:(40)][(-50):20:(-20)]` | HTTP 200, **653 rows** (≈1° effective grid). Confirms stride solves payload size. |
| End-to-end cos-lat area-weighted mean over the strided NA box | computed cleanly = **−0.311 °C** (651 valid cells; 2 land/NaN cells auto-omitted by ERDDAP CSV). |

**Land / NaN handling (verified):** CRW grid cells over land (and masked cells) come back as `NaN`, and **ERDDAP omits NaN rows from CSV output entirely**. So CSV land-masking is automatic — the fetch simply gets fewer rows and the area-weighted mean is over valid ocean cells only. The code must still defensively skip any `NaN` token in case a future filetype includes them.

**Payload note (the real risk, mitigated):** at full 0.05° resolution a single marquee box can be 240k+ rows (≈10 MB CSV). A 13-region full-res pull would be enormous and slow. **Mitigation: always request with a stride** chosen per box to target ≈1° effective resolution (stride 20 on the 0.05° grid). A 1°-effective field is more than adequate for a basin-mean anomaly and keeps each region under ~1–2k rows. See "Fetch design" for the stride formula.

### Anti-fabrication note

The endpoint above was confirmed by live HTTP probes on 2026-06-08, including a real numeric subset and an end-to-end area-weighted mean. This is a genuine working endpoint, not an assumed one. **If a future builder finds it down or changed, treat that as OPEN QUESTION 1 and re-verify before coding — do not silently substitute an unverified URL.**

### Rejected / fallback sources

- **NOAA OISST v2.1 via CoastWatch ERDDAP (`ncdcOisst21Agg` on `coastwatch.pfeg.noaa.gov`).** This is the documented fallback. It is global 0.25° daily and reachable via griddap, BUT its variables are `sst`/`err`/`ice`/`anom`; the `anom` variable on the aggregate is referenced to a **1971–2000** climatology and on some mirrors is absent, forcing a self-built 1991–2020 per-DOY climatology. That is exactly the climatology-build complexity CRW lets us avoid. Also note `ncdcOisst21Agg` is **404 on the `coastwatch.noaa.gov` host** — it lives on `coastwatch.pfeg.noaa.gov`, a different ERDDAP node — so it is NOT a drop-in host swap. Keep it as the documented fallback only.
- **ClimateReanalyzer per-region JSON (Revision 2 source).** SUPERSEDED. Only 6 Atlantic/Gulf/ENSO regions exist; cannot go global.
- **CMEMS (Copernicus Marine Service).** Requires account + API token. Out of scope for the $0 stack.

---

## Data source

**Primary (VERIFIED): NOAA Coral Reef Watch Daily Global 5km SST Anomaly via NOAA CoastWatch ERDDAP griddap.**

- Dataset ID `noaacrwsstanomalyDaily`, variable `sea_surface_temperature_anomaly` (`degree_C`), global 0.05° daily, anomaly **pre-computed and published** by CRW.
- Subset per region by lat/lon/time box using griddap `.csv` (see STEP 0 for the exact URL shape and stride requirement).
- No authentication; $0 stack.

**Decision: use the CRW gridded anomaly product.** Rationale:
1. **Truly global** — covers every basin in the region set, including the Pacific Blob, Mediterranean, Tasman, Indian Ocean, Coral Triangle, GBR — none of which ClimateReanalyzer offers.
2. **Published anomaly** — no climatology file to build, backfill, cache, or keep current. Eliminates the entire self-climatology code path and its accuracy risk.
3. **No new auth** — plain HTTPS, $0. @theheat already trusts the CRW domain family (`coral_dhw.py`).
4. **Clean region-box subset** — griddap lat/lon/time slicing is exactly the access pattern we need; stride keeps payloads small.

**Climatology base:** N/A for the fetch — CRW publishes the anomaly. (For transparency, CRW's SSTA is referenced to its own daily climatology derived from the 1985–2012 record; the bundle records this as provenance text, but the bot computes nothing.) This **removes** Revision 2's 1982–2010 self-climatology and OPEN QUESTION 2 about the climatology period. There is no longer a climatology-period fork in v1.

**Format note — helpers that NO LONGER APPLY:** because the source is now ERDDAP gridded CSV (not year-keyed JSON), the following `src/data/ocean_sst.py` helpers are **not reused** by this signal: `_normalise_series_payload`, `_current_year_series`, `_archive_max_for_doy`, the `prior_arrs` reconstruction, and the streak/DOY machinery. Only `_REQUEST_HEADERS` (User-Agent) and `src/data/_http.fetch_with_retry` carry over. A new CSV parser + area-weighting live in the new data module.

---

## Signal definition & thresholds

### Region list (v1 — 13 global marquee basins)

Each region is an axis-aligned lat/lon bounding box in **decimal degrees, −180/180 longitude, latitudes north-positive**. Boxes are intentionally generous (basin-scale) since the signal is a basin-mean anomaly. All boxes stay within −180/180 without crossing the dateline (see antimeridian note). Slugs are lower-snake and stable; they appear in `event_id`s and state keys.

| slug | display_name | lat S | lat N | lon W | lon E | notes |
|------|-------------|------:|------:|------:|------:|-------|
| `north_atlantic` | North Atlantic | 0 | 60 | −80 | 0 | basin-wide N Atlantic |
| `subpolar_n_atlantic` | Subpolar North Atlantic | 45 | 60 | −45 | −20 | 2023 anomaly core |
| `ne_pacific_blob` | NE Pacific ("the Blob") | 40 | 55 | −150 | −125 | Gulf of Alaska / Blob region |
| `mediterranean` | Mediterranean Sea | 30 | 46 | −5 | 36 | enclosed basin |
| `tasman_sea` | Tasman Sea | −45 | −30 | 150 | 175 | E of Australia / W of NZ |
| `gulf_of_mexico` | Gulf of Mexico | 18 | 30 | −98 | −80 | |
| `caribbean` | Caribbean Sea | 9 | 22 | −88 | −60 | |
| `western_indian_ocean` | Western Indian Ocean | −10 | 10 | 45 | 75 | |
| `bay_of_bengal` | Bay of Bengal | 5 | 22 | 80 | 95 | |
| `coral_triangle` | Coral Triangle | −10 | 10 | 120 | 150 | reef biodiversity core |
| `great_barrier_reef` | Great Barrier Reef | −24 | −10 | 142 | 154 | GBR shelf |
| `california_current` | California Current | 30 | 42 | −127 | −116 | upwelling system |
| `nino34` | Niño 3.4 | −5 | 5 | −170 | −120 | ENSO index region |

13 regions. (The existing global-mean streak signal uses the `world2` ClimateReanalyzer series and is **not** part of this registry.)

**Antimeridian note:** every box above is expressible with `lonW ≤ lonE` in −180/180, so no dateline split is needed. **If a future region must cross the dateline** (e.g. a Bering/NW-Pacific box spanning 165°E→−170°), it must be **split into two sub-boxes** (e.g. 165→180 and −180→−170) and the area-weighted mean computed over the union — ERDDAP silently clamps a `(lonW>lonE)` request to one side and returns wrong coverage (verified failure mode 2026-06-08). Encode this as a per-region optional list of boxes if/when needed; v1's 13 boxes do not require it.

**[P2-2] Fail-fast on dateline crossing:** `_build_url` raises `ValueError` immediately when `lon_w > lon_e`, rather than silently passing the bad bbox to ERDDAP (which clamps it and returns wrong coverage with no error signal). Future split-box support is out of scope for v1 — see Fork 3.

### Fetch design (per region)

For each region box:
1. Build a griddap `.csv` URL: `…/noaacrwsstanomalyDaily.csv?sea_surface_temperature_anomaly[(last)][(latN):STRIDE:(latS)][(lonW):STRIDE:(lonE)]`.
2. **Stride** = the integer nearest `round(TARGET_DEG / 0.05)` clamped to ≥1, where `TARGET_DEG ≈ 1.0°` → stride ≈ 20. This targets ≈1° effective resolution and keeps each region to ~hundreds–~2k rows. (Tunable per region if a small box needs finer sampling; v1 uses a single global `_GRID_STRIDE = 20`.)
3. Parse the CSV: skip the 2 header lines (`names`, then `units`), read `latitude` (col 1) and `sea_surface_temperature_anomaly` (col 3). Skip blank lines, non-finite tokens (`NaN`, empty), `_FillValue` (−327.68), and values outside valid_range [−15, +15] °C (see P1-4 filter in `_parse_griddap_csv`).
4. **[P2-1 — COVERAGE SAFEGUARD]** After parsing, check that the cell list meets a minimum valid-cell count (or coverage ratio) before tiering. Coastal and narrow boxes (Great Barrier Reef: 12°lat × 12°lon; California Current: 12°lat × 11°lon) can lose many cells to land-masking after stride-20 sampling — leaving only a handful of ocean points that may bias the mean. Define a per-region floor (default `_MIN_VALID_CELLS = 10`; tunable) and if `len(cells) < _MIN_VALID_CELLS`, log a warning and return `None` (do not tier). Note `cells_used` on `RegionalSSTReading` for diagnostics. Add a test: a narrow-box CSV that yields fewer than the floor after fill/land filtering returns `None` without tiering.
5. **Area-weight by cos(latitude):** `anomaly_mean = Σ(valueᵢ · cos(latᵢ)) / Σ cos(latᵢ)`, latitude in radians. (Each CSV cell is one grid point; cos-lat weighting corrects for grid cells shrinking toward the poles.)
6. Read the grid timestamp from any data row (col 0) → `date` = its `YYYY-MM-DD`. Assert freshness vs. `_MAX_DATA_LAG_DAYS`.
6. Detect tier from the area-weighted mean anomaly; return a `RegionalSSTReading` (or `None` if below the tier-1 floor or on fetch/parse failure when `strict=False`).

Rationale for area-weighted (not naive) mean: high-latitude boxes (Subpolar N Atlantic, NE-Pacific Blob, Tasman) span enough latitude that equal-weighting over-counts poleward rows; cos-lat weighting is the standard correction and is cheap to compute from the returned `latitude` column.

### Anomaly tiers

Tiered **absolute** area-weighted-mean anomaly (°C) as published by CRW. These are NOT Hobday MHW categories.

| tier | threshold | label |
|------|-----------|-------|
| 1 | ≥ +2.5°C | `sst_anom_t1` |
| 2 | ≥ +3.5°C | `sst_anom_t2` |
| 3 | ≥ +4.5°C | `sst_anom_t3` |

Tier 3 at +4.5°C **basin-mean** is "Wait, what?" territory — a +4.5°C average over an entire basin is extraordinary. Tier 1 at +2.5°C is anomalous but requires the editorial score to confirm it's worth tweeting (score formula calibrated to barely clear the threshold at tier 1 for marquee basins).

**Hobday MHW categories are NOT implemented in v1.** Deferred to v2. See Forks section.

### event_id scheme

```
sst_anom_<region_slug>_tier<N>_<YYYY-MM-DD>
```

Examples:
- `sst_anom_north_atlantic_tier2_2026-06-08`
- `sst_anom_ne_pacific_blob_tier1_2026-06-08`
- `sst_anom_nino34_tier1_2026-06-08`

The prefix `sst_anom_` guarantees no collision with the existing global-mean event_id pattern `marine_heatwave_streak_<days>_<date>`. These occupy completely separate namespaces in `state.is_duplicate` / `posted_events`.

Tier-dedup rule: a higher-tier crossing for the same region fires a NEW event_id (different `tier<N>` suffix), so it passes `state.is_duplicate`. The runner stores `last_tier_fired` per `{year}/{slug}` key (see State section) so a tier-2 won't re-fire once a tier-3 has been posted. The tier key resets annually.

### Category

**New category: `regional_sst_anomaly`.** Do NOT reuse `marine_heatwave`.

Rationale for split:
1. The global-mean streak signal (`marine_heatwave`, threshold 78) measures consecutive days the **global** mean exceeds every prior year. The regional signal measures a tiered **absolute** area-weighted anomaly vs CRW climatology in a specific basin. They are structurally different signals with different data sources and scoring functions — conflating them under one category creates confusion in the approval dashboard and score reasoning.
2. Using `legacy_type="marine_heatwave"` in `_enqueue_story_candidate` would route regional drafts through the existing `marine_heatwave` approval branch — masking them from any future per-category analytics or policy differentiation.
3. The new category needs its own `manual_only` approval gate (see Approval section). The existing `marine_heatwave` branch is `suggested_auto` — not the right posture for a new, unproven signal.
4. Adding a new category requires: one new entry in `thresholds.py`, one new branch in `approval.py`, one export in `scoring/__init__.py`, new test fixtures. This is the correct cost for a distinct signal.

The `event_id` prefix `sst_anom_` already ensures no collision in `posted_events` regardless of category.

---

## Files to create / modify

### Create
1. `src/data/ocean_sst_anomaly.py` — **gridded data layer**: region registry (13 boxes), griddap CSV fetch per region box, CSV parse, **cos-latitude area-weighted mean**, tier detection, reading + event dataclasses. (No climatology file — CRW publishes anomaly.)
2. `src/orchestrator/sources/ocean_sst_anomaly.py` — source runner: `run_ocean_sst_anomaly(bot_state, current_run)`.
3. `tests/test_ocean_sst_anomaly.py` — data layer tests (mock HTTP returning griddap CSV).
4. `tests/test_ocean_sst_anomaly_orchestrator.py` — orchestrator runner tests.

> **No climatology-cache file or backfill script is created** — that was only needed on the OISST-raw fallback path. The CRW path publishes anomaly, so there is nothing to backfill. (If the project ever switches to the OISST fallback, add `src/data/sst_climatology_1991_2020.json` + a one-time `scripts/build_sst_climatology.py` here.)

### Modify
5. `src/editorial/scoring/marine.py` — add `score_regional_sst_anomaly(region_slug, anomaly_c, tier)` after `score_marine_heatwave` (def at line 144). **Update the named-basin shareability bump to the new marquee slugs.**
6. `src/editorial/scoring/__init__.py` — add `score_regional_sst_anomaly` proxy and export.
7. `src/editorial/thresholds.py` — add `"regional_sst_anomaly"` entry to the `THRESHOLDS` dict (def at line 15).
8. `src/editorial/approval.py` — add a `"regional_sst_anomaly"` branch (manual_only) before the `marine_heatwave` branch (line 151).
9. `src/orchestrator/common.py` — add `ocean_sst_anomaly` to the `from src.data import …` line, add `score_regional_sst_anomaly` import, add `SST_ANOM_ANNUAL_CAP` constant + `_sst_anom_annual_cap_reached` helper, add all to `__all__`.
10. `src/two_bot/intern/marine.py` — add `build_regional_sst_anomaly_bundle(event)` after `build_marine_heatwave_bundle` (def at line 125).
11. `src/two_bot/intern/__init__.py` — add `build_regional_sst_anomaly_bundle` import and export.
12. `src/state_schema.py` — add `sst_anom_last_tier: dict[str, int]` and `sst_anom_annual_count: dict[str, int]` to `BotState`.
13. `src/state.py` — **(P1 — three sub-steps, all required):**
    - (a) Add `"sst_anom_last_tier": {}` and `"sst_anom_annual_count": {}` to `DEFAULT_STATE`.
    - (b) Add `update_sst_anom_tier` and `increment_sst_anom_annual_count` state functions (see State section).
    - (c) **[P1-1 — STATE PERSISTENCE — HIGHEST PRIORITY]** Add both new keys to `_merge_state()` (currently at ~line 574). `_merge_state` rebuilds state by explicitly merging every known key; any key not listed there is DROPPED on write. Without this step, `sst_anom_last_tier` and `sst_anom_annual_count` will silently vanish on the first concurrent state merge, causing tier dedup and annual cap to fail permanently. Mirror the pattern used for `coral_dhw_last_tier` (~line 747) — use max-per-key semantics so a tier bump on one concurrent run is never lost to a stale run.
14. `src/orchestrator/run_alerts.py` — import and call `run_ocean_sst_anomaly` after `run_ocean_sst`.

**Helpers that are intentionally NOT touched / NOT reused** (source changed): `src/data/ocean_sst.py`'s `_normalise_series_payload`, `_current_year_series`, `_archive_max_for_doy`, `_today_year_doy`, and the streak/DOY machinery. They remain in service of the existing global-mean signal only; the gridded regional signal does not import them.

---

## Step-by-step implementation (TDD order)

**Step 1: Data layer tests (write first)**

In `tests/test_ocean_sst_anomaly.py`:
- Test `REGION_REGISTRY` exports: correct count (**13**), each entry has `slug`, `display_name`, and a 4-tuple bbox with `lat_s < lat_n` and `lon_w <= lon_e`, no dateline-crossing boxes, slugs unique.
- Test `_area_weighted_mean(rows)` — given synthetic `(lat, anomaly)` rows, returns the cos-lat-weighted mean; verify it differs from the naive mean for a high-latitude spread, and equals the simple value for a single-latitude set.
- Test `_parse_griddap_csv(text)` — given a CRW-format CSV string (2 header lines + data rows), returns `(date, list[(lat, anomaly)])`; skips `NaN` tokens and blank lines.
- Test `_detect_tier(anomaly_c)` returns correct tier (1/2/3) or None at all boundaries.
- Test `fetch_region_sst(region)` with mocked HTTP returning griddap CSV: returns `RegionalSSTReading | None` with correct area-weighted anomaly + tier; `None` when below tier-1 floor; `None` on HTTP error when `strict=False`, raises `SourceFetchError` when `strict=True`.
- Test `detect_regional_sst_anomaly_events(readings, last_tiers)` returns events only when tier > last_tier for that region; event_id format `sst_anom_<slug>_tier<N>_<date>`.
- Use a `_fake_griddap_csv(date_iso, cells)` helper that emits the exact 2-header-line CRW CSV shape; mock `src.data._http.fetch_with_retry`.

**Step 2: Create `src/data/ocean_sst_anomaly.py`**

```python
"""Per-region SST anomaly detection via NOAA Coral Reef Watch gridded anomaly.

Source: NOAA Coral Reef Watch "Daily Global 5km Satellite SST Anomaly" served
by NOAA CoastWatch ERDDAP griddap (dataset id ``noaacrwsstanomalyDaily``,
variable ``sea_surface_temperature_anomaly``, degree_C, 0.05deg global, ~2-day
lag, NO AUTH). VERIFIED returning live lat/lon/time subsets on 2026-06-08.

The anomaly is PUBLISHED by CRW (referenced to its own daily climatology) — this
module does NOT build or store any climatology. For each region box we fetch a
strided griddap CSV subset and compute the cos-latitude AREA-WEIGHTED mean
anomaly over the box.

This is NOT a Hobday marine-heatwave implementation. Tiers are absolute anomaly,
NOT 90th-percentile-based. Use "regional SST anomaly" in all copy — never
"marine heatwave".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from collections.abc import Mapping

import requests

from src.data._freshness import assert_freshness
from src.data._http import fetch_with_retry
from src.data.ocean_sst import _REQUEST_HEADERS  # User-Agent courtesy only
from src.data.source_status import SourceFetchError, assert_response_schema

# ERDDAP griddap CSV endpoint. {var}[(time)][(latN):s:(latS)][(lonW):s:(lonE)]
_ERDDAP_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacrwsstanomalyDaily.csv"
_SST_ANOM_VAR = "sea_surface_temperature_anomaly"
_GRID_DEG = 0.05          # native CRW grid resolution
_TARGET_DEG = 1.0         # effective sampling target for basin-mean
_GRID_STRIDE = max(1, round(_TARGET_DEG / _GRID_DEG))  # = 20
_MAX_DATA_LAG_DAYS = 5

# Absolute anomaly tiers (degC above CRW published climatology). NOT Hobday.
ANOMALY_TIERS: tuple[tuple[int, float], ...] = (
    (3, 4.5),
    (2, 3.5),
    (1, 2.5),
)


@dataclass(frozen=True)
class RegionDef:
    slug: str
    display_name: str
    lat_s: float
    lat_n: float
    lon_w: float
    lon_e: float


# 13 global marquee basins. Boxes are -180/180 lon, north-positive lat, and do
# NOT cross the dateline (lon_w <= lon_e). Verified box list 2026-06-08.
REGION_REGISTRY: tuple[RegionDef, ...] = (
    RegionDef("north_atlantic",      "North Atlantic",            0,  60, -80,   0),
    RegionDef("subpolar_n_atlantic", "Subpolar North Atlantic",  45,  60, -45, -20),
    RegionDef("ne_pacific_blob",     "NE Pacific (the Blob)",     40,  55,-150,-125),
    RegionDef("mediterranean",       "Mediterranean Sea",         30,  46,  -5,  36),
    RegionDef("tasman_sea",          "Tasman Sea",               -45, -30, 150, 175),
    RegionDef("gulf_of_mexico",      "Gulf of Mexico",            18,  30, -98, -80),
    RegionDef("caribbean",           "Caribbean Sea",              9,  22, -88, -60),
    RegionDef("western_indian_ocean","Western Indian Ocean",     -10,  10,  45,  75),
    RegionDef("bay_of_bengal",       "Bay of Bengal",              5,  22,  80,  95),
    RegionDef("coral_triangle",      "Coral Triangle",           -10,  10, 120, 150),
    RegionDef("great_barrier_reef",  "Great Barrier Reef",       -24, -10, 142, 154),
    RegionDef("california_current",  "California Current",         30,  42,-127,-116),
    RegionDef("nino34",              "Niño 3.4",                  -5,   5,-170,-120),
)


@dataclass(frozen=True)
class RegionalSSTReading:
    region_slug: str
    region_display_name: str
    date: str
    anomaly_c: float       # cos-lat area-weighted mean published anomaly
    tier: int              # 1, 2, or 3
    cells_used: int        # valid ocean grid cells in the area-weighted mean


@dataclass(frozen=True)
class RegionalSSTAnomalyEvent:
    region_slug: str
    region_display_name: str
    date: str
    anomaly_c: float
    tier: int
    cells_used: int
    event_id: str          # sst_anom_<slug>_tier<N>_<YYYY-MM-DD>
```

Key functions:

```python
def _build_url(region: RegionDef, *, time_token: str = "last") -> str:
    s = _GRID_STRIDE
    # [P2-2] Fail-fast on dateline-crossing regions. The registry type is single-bbox
    # only; lon_w > lon_e is a dateline crossing that ERDDAP silently clamps to one
    # side, returning wrong coverage. Raise immediately rather than silently miscompute.
    # Future split-box support (Fork 3) is out of scope for v1.
    if region.lon_w > region.lon_e:
        raise ValueError(
            f"Region '{region.slug}' has lon_w ({region.lon_w}) > lon_e ({region.lon_e}): "
            "dateline-crossing bboxes are not supported in v1. Split into two sub-boxes "
            "and union the area-weighted means (see Fork 3 in the plan)."
        )
    # latitude NORTH->SOUTH to match the descending grid
    return (
        f"{_ERDDAP_BASE}?{_SST_ANOM_VAR}"
        f"[({time_token})]"
        f"[({region.lat_n}):{s}:({region.lat_s})]"
        f"[({region.lon_w}):{s}:({region.lon_e})]"
    )

_FILL_VALUE = -327.68        # NOAA CRW _FillValue per dataset metadata
_VALID_RANGE = (-15.0, 15.0) # valid_range per NOAA metadata (degree_C)

def _parse_griddap_csv(text: str) -> tuple[str | None, list[tuple[float, float]]]:
    """Return (iso_date, [(lat, anomaly), ...]) from CRW griddap CSV.

    Line 0 = column names, line 1 = units, remaining = data
    (time,latitude,longitude,sea_surface_temperature_anomaly).
    Skips blank lines and non-finite anomaly tokens (NaN/empty).

    [P1-4] Also filters out _FillValue (-327.68) and values outside the
    valid_range (-15..15 °C) per NOAA CRW dataset metadata.  A stray fill or
    land cell can otherwise dominate the area-weighted mean.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return None, []
    iso_date: str | None = None
    cells: list[tuple[float, float]] = []
    for line in lines[2:]:
        parts = line.split(",")
        if len(parts) < 4:
            continue
        if iso_date is None:
            iso_date = parts[0][:10]  # YYYY-MM-DD from the timestamp
        try:
            lat = float(parts[1]); val = float(parts[3])
        except ValueError:
            continue
        if not math.isfinite(val):
            continue
        if val == _FILL_VALUE:           # explicit fill — treat as land/ice
            continue
        if not (_VALID_RANGE[0] <= val <= _VALID_RANGE[1]):  # out-of-range
            continue
        cells.append((lat, val))
    return iso_date, cells

def _area_weighted_mean(cells: list[tuple[float, float]]) -> float | None:
    num = den = 0.0
    for lat, val in cells:
        w = math.cos(math.radians(lat))
        num += val * w; den += w
    return (num / den) if den else None

def _detect_tier(anomaly_c: float) -> int | None:
    for tier, threshold in ANOMALY_TIERS:
        if anomaly_c >= threshold:
            return tier
    return None

def fetch_region_sst(region: RegionDef, *, strict: bool = False) -> RegionalSSTReading | None:
    url = _build_url(region)
    try:
        resp = fetch_with_retry(url, timeout=30, headers=_REQUEST_HEADERS, attempts=3)
        text = resp.text
        assert_response_schema({"body": text}, ["body"], "ocean_sst_anomaly")
        iso_date, cells = _parse_griddap_csv(text)
        if iso_date is None or not cells:
            raise SourceFetchError(f"ocean_sst_anomaly/{region.slug}: empty grid")
        assert_freshness(date.fromisoformat(iso_date), "ocean_sst_anomaly", _MAX_DATA_LAG_DAYS)
        mean = _area_weighted_mean(cells)
        if mean is None:
            raise SourceFetchError(f"ocean_sst_anomaly/{region.slug}: no valid cells")
        tier = _detect_tier(mean)
        if tier is None:
            return None  # below tier-1 floor — not an anomaly event
        return RegionalSSTReading(
            region_slug=region.slug,
            region_display_name=region.display_name,
            date=iso_date,
            anomaly_c=round(mean, 2),
            tier=tier,
            cells_used=len(cells),
        )
    except (requests.RequestException, ValueError, SourceFetchError) as exc:
        if strict:
            raise SourceFetchError(f"ocean_sst_anomaly/{region.slug} fetch failed: {exc}") from exc
        return None

def fetch_all_regions(*, strict: bool = False) -> list[RegionalSSTReading]:
    """Fetch all 13 region boxes. ThreadPoolExecutor(max_workers<=4) — mirrors
    coral_dhw.py concurrency. Strided payloads keep each region small (~hundreds
    of rows).

    [P1-3 — PARTIAL DEGRADATION] Default strict=False: a single region's ERDDAP
    failure is skipped (logged, not raised); successful regions are returned.
    Only fails the source entirely when ALL regions fail (i.e. caller gets an
    empty list and can decide) OR when the schema/global source is broken.
    strict=True raises SourceFetchError on the FIRST per-region failure — for
    use in explicit end-to-end integration tests only.

    The runner MUST NOT call this via _fetch_strict(), which would fail the whole
    source on a single region error. The runner calls fetch_all_regions() directly
    (strict=False) and treats an empty result list as source failure."""
    ...

def detect_regional_sst_anomaly_events(
    readings: list[RegionalSSTReading],
    last_tiers: Mapping[str, int] | None = None,
) -> list[RegionalSSTAnomalyEvent]:
    """Return events where current tier exceeds last_tiers[region_slug].
    last_tiers keys are bare slugs for the CURRENT year (the runner pre-filters
    the annual "{YYYY}/{slug}" state down to this). Sort desc by anomaly_c."""
    ...
    # event_id: f"sst_anom_{reading.region_slug}_tier{tier}_{reading.date}"
```

**Step 3: Scoring**

In `src/editorial/thresholds.py`, add to `THRESHOLDS`:
```python
"regional_sst_anomaly": ThresholdEntry(
    "regional_sst_anomaly",
    76,
    "Per-region NOAA Coral Reef Watch published SST anomaly (gridded 5km), "
    "cos-lat area-weighted basin mean; absolute tiers, NOT Hobday MHW. "
    "New signal in manual_only review posture.",
),
```

Threshold 76 (not 78 like `marine_heatwave`) — deliberately 2 points lower because the new signal starts in `manual_only` review and basin-mean anomaly is a fresh, unproven editorial product. Score formula calibrated to clear 76 at tier 1 only for the highest-profile basins, and at tier 2 for all basins.

In `src/editorial/scoring/marine.py`, add after `score_marine_heatwave`:

```python
# Marquee basins with the strongest reader recognition / shareability.
# Updated for the gridded-global region set (Revision 3).
_NAMED_BASIN_SLUGS = {
    "north_atlantic",
    "subpolar_n_atlantic",
    "ne_pacific_blob",
    "mediterranean",
    "great_barrier_reef",
}

def score_regional_sst_anomaly(
    region_slug: str,
    anomaly_c: float,
    tier: int,
) -> EditorialScore:
    """Score a per-region SST anomaly event.

    NOT a Hobday MHW score — tiers are absolute cos-lat area-weighted basin-mean
    anomaly as published by NOAA Coral Reef Watch. Category:
    "regional_sst_anomaly" (distinct from "marine_heatwave").
    """
    reasons = [
        f"+{anomaly_c:.2f}°C area-weighted basin-mean SST anomaly (NOAA CRW)",
        f"tier {tier} regional SST anomaly (threshold: {[2.5, 3.5, 4.5][tier - 1]:+.1f}°C)",
        "NOAA Coral Reef Watch 5km published anomaly (gridded)",
    ]
    if tier == 3:
        reasons.append("extreme: +4.5°C basin-mean threshold crossed")
    # Named-basin shareability bump (Blob / N Atlantic / Med / GBR are the most
    # reader-familiar marine-heat stories).
    named_basin_bump = 6 if region_slug in _NAMED_BASIN_SLUGS else 0
    return _build_score(
        "regional_sst_anomaly",
        severity=68 + tier * 4 + min((anomaly_c - 2.5) * 3, 10),
        novelty=76 + tier * 3,
        timeliness=86,
        confidence=86,
        shareability=72 + tier * 3 + named_basin_bump,
        sensitivity=6,
        threshold=get_threshold("regional_sst_anomaly"),
        reasons=reasons,
    )
```

Score calibration — **[P1-5] RECOMPUTED using actual `_compute_total` weights** (from `src/editorial/scoring/_shared.py` ~line 35: 0.28 sev + 0.24 nov + 0.16 time + 0.16 conf + 0.16 share − 0.20 sens, clamped and rounded):

| Scenario | sev | nov | time | conf | share | sens | raw | total | passes (≥76) |
|---|---|---|---|---|---|---|---|---|---|
| Tier 1, +2.5°C, non-marquee (e.g. `bay_of_bengal`) | 72 | 79 | 86 | 86 | 75 | 6 | ~76.9 | **77** | YES |
| Tier 1, +2.5°C, marquee (`north_atlantic`) | 72 | 79 | 86 | 86 | 81 | 6 | ~77.8 | **78** | YES |
| Tier 2, +3.5°C, any basin | 76 | 82 | 86 | 86 | 78 | 6 | ~80.1 | **80** | YES |
| Tier 3, +4.5°C, any basin | 80 | 85 | 86 | 86 | 81 | 6 | ~83.0 | **83** | YES |

**[P1-5 — CALIBRATION REVISION]:** With the real weighting, a tier-1 +2.5°C non-marquee total is ~77 — which PASSES threshold 76. The original plan's "minor-basin tier-1 fails" intent is NOT achievable at the current formula/threshold combination without retuning. **The simpler honest path: accept that tier-1 fires for all basins.** The `manual_only` approval gate + data-driven calibration (run `fetch_all_regions()` over recent dates to inspect real anomaly distribution) already catch any noise. The named-basin shareability bump (6 pts) still makes marquee basins score 1–2 points higher.

**Tier floors + threshold are PROVISIONAL** pending the data-driven calibration already in OPEN QUESTION 2. After observing real anomaly distributions, raise the threshold or tier floor if tier-1 fires too frequently.

Confidence lower than the global-mean signal (86 vs. 92) because a basin-mean over a generous box (and at 1°-effective sampling) is a coarser statistic than the curated global mean.

> **All score-test assertions MUST reference real `score_regional_sst_anomaly(...).total` behavior, not hand arithmetic.** Verify with actual test runs before treating any calibration number as fixed.

**Step 4: Approval**

In `src/editorial/approval.py`, add a branch **before** the `marine_heatwave` branch (line 151):

```python
if tweet_type == "regional_sst_anomaly":
    return ApprovalPolicy(
        key="regional_sst_anomaly_manual",
        mode="manual_only",
        recommended_delay_minutes=None,
        can_auto_approve=False,
        reason=(
            "New per-region SST anomaly signal (NOAA CRW gridded) in manual-"
            "review posture. Verify basin, area-weighted anomaly magnitude, and "
            "grid freshness before posting. Upgrade to suggested_auto after 10+ "
            "live runs confirm scoring is calibrated."
        ),
    )
```

The `marine_heatwave` branch at line 151 is unchanged. The two branches handle completely different `tweet_type` / `legacy_type` values.

**Step 5: State functions (annual tier-reset)**

Key the tier state as `"{YYYY}/{slug}"` so a new calendar year produces a fresh key — a tier-3 event in year N does not permanently suppress tier-1/tier-2 events in year N+1.

In `src/state.py`, add to `DEFAULT_STATE`:
```python
"sst_anom_last_tier": {},    # {"{YYYY}/{slug}": int} highest tier that produced a draft
"sst_anom_annual_count": {}, # {year_str: int} annual cap counter
```

In `src/state_schema.py` `BotState`:
```python
sst_anom_last_tier: dict[str, int]
sst_anom_annual_count: dict[str, int]
```

In `src/state.py` — state functions (**[P1-2]: derive year from the reading/event date, NOT `date.today()`**, to avoid the ~2-day CRW lag mis-keying a Dec 30/31 reading into the new year):
```python
def update_sst_anom_tier(
    state: BotState, region_slug: str, tier: int, reading_date: str
) -> BotState:
    """Record the highest tier fired for a region in the reading's calendar year.
    Key "{YYYY}/{slug}" gives a free annual reset.

    IMPORTANT: use reading_date (the CRW grid timestamp's YYYY-MM-DD), NOT
    date.today() — CRW data lags ~2 days, so near Jan 1 a Dec 30/31 reading
    would mis-key into the new year and poison current-year tiers + annual cap.
    """
    year = reading_date[:4]   # YYYY from "YYYY-MM-DD"
    key = f"{year}/{region_slug}"
    tiers = state.setdefault("sst_anom_last_tier", {})
    if tier > int(tiers.get(key, 0)):
        tiers[key] = int(tier)
    return state

def increment_sst_anom_annual_count(state: BotState, reading_date: str) -> BotState:
    """Increment the annual cap counter using the reading's year (not today's).
    See update_sst_anom_tier docstring for why reading_date is required."""
    year = reading_date[:4]   # YYYY from "YYYY-MM-DD"
    counts = state.setdefault("sst_anom_annual_count", {})
    counts[year] = int(counts.get(year, 0)) + 1
    return state
```

**[P1-1 — STATE PERSISTENCE — HIGHEST PRIORITY]** In `_merge_state()` (~line 574 of `src/state.py`), add both new keys after the `coral_dhw_annual_count` block, mirroring the `coral_dhw_last_tier` pattern (max-per-key semantics so a tier bump on one concurrent run is never lost to a stale run):
```python
# Take max tier per "{YYYY}/{slug}" key — same monotonic semantics as coral_dhw_last_tier.
merged["sst_anom_last_tier"] = {}
for region_key in set(
    list(base.get("sst_anom_last_tier", {}).keys())
    + list(next_state.get("sst_anom_last_tier", {}).keys())
):
    merged["sst_anom_last_tier"][region_key] = max(
        int(base.get("sst_anom_last_tier", {}).get(region_key, 0)),
        int(next_state.get("sst_anom_last_tier", {}).get(region_key, 0)),
    )
merged["sst_anom_annual_count"] = {}
for year in set(
    list(base.get("sst_anom_annual_count", {}).keys())
    + list(next_state.get("sst_anom_annual_count", {}).keys())
):
    merged["sst_anom_annual_count"][year] = max(
        base.get("sst_anom_annual_count", {}).get(year, 0),
        next_state.get("sst_anom_annual_count", {}).get(year, 0),
    )
```
Without this block, both keys are silently dropped on every state merge, breaking tier dedup and annual cap permanently.

The runner pre-filters the annual state down to bare slugs for the current year before calling `detect_regional_sst_anomaly_events` (see Step 7). **[P1-2]** The runner's year-filter must also derive year from the reading date, not `date.today()`:
```python
# WRONG — uses today's date; near Jan 1 a Dec 30/31 reading mis-keys:
# year = str(date.today().year)

# CORRECT — use the reading date from the most recent event or reading:
# (The runner can extract year from the first reading's .date field, or
#  pass a reading_year parameter derived from the fetched grid timestamp.)
reading_year = readings[0].date[:4] if readings else str(date.today().year)
prefix = f"{reading_year}/"
last_tiers = {
    key[len(prefix):]: tier
    for key, tier in bot_state.get("sst_anom_last_tier", {}).items()
    if key.startswith(prefix)
}
```

**Step 6: Bundle builder**

In `src/two_bot/intern/marine.py`, add after `build_marine_heatwave_bundle` (def at line 125):

```python
def build_regional_sst_anomaly_bundle(event: RegionalSSTAnomalyEvent) -> StoryBundle:
    """A per-region SST anomaly event bundle.

    signal_kind is "regional_sst_anomaly" (NOT "marine_heatwave") — the writer
    must not frame this as a Hobday MHW. The anomaly is a cos-lat area-weighted
    basin mean of NOAA CRW's PUBLISHED 5km anomaly.
    """
    return StoryBundle(
        signal_kind="regional_sst_anomaly",
        where=event.region_display_name,
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "sst_anomaly_c",
            "value": round(event.anomaly_c, 2),
            "unit": "°C",
        },
        current_facts=[
            {"label": "region_slug", "value": event.region_slug},
            {"label": "region_display_name", "value": event.region_display_name},
            {"label": "anomaly_c", "value": round(event.anomaly_c, 2), "unit": "°C"},
            {"label": "tier", "value": event.tier},
            {"label": "tier_threshold_c", "value": [2.5, 3.5, 4.5][event.tier - 1]},
            {"label": "spatial_aggregation", "value": "cos-latitude area-weighted basin mean"},
            {"label": "grid_cells_used", "value": event.cells_used},
            {"label": "anomaly_basis", "value": "NOAA CRW published 5km SST anomaly"},
            {
                "label": "signal_note",
                "value": (
                    "Absolute area-weighted-mean anomaly vs CRW climatology. "
                    "NOT a Hobday duration/percentile MHW classification."
                ),
            },
        ],
        historical_context={
            "scope": "noaa_crw_regional_sst_anomaly",
            "source": "NOAA Coral Reef Watch Daily Global 5km SST Anomaly (ERDDAP noaacrwsstanomalyDaily)",
            "spatial_aggregation": "cos-latitude area-weighted basin mean",
            "tier_thresholds": [2.5, 3.5, 4.5],
        },
        raw_signal_dump=asdict(event),
    )
```

Add `RegionalSSTAnomalyEvent` import from `src.data.ocean_sst_anomaly` at the top of `marine.py`.

**Step 7: Source runner**

Create `src/orchestrator/sources/ocean_sst_anomaly.py`:

```python
"""Source runner for per-region SST anomaly detection (NOAA CRW gridded)."""
from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *

SST_ANOM_ANNUAL_CAP = 10  # tweets/year across all 13 regions (new signal; conservative)


def run_ocean_sst_anomaly(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    print("[alerts] Checking per-region SST anomaly...")
    start = time.perf_counter()
    try:
        from src.data import ocean_sst_anomaly
        from src.two_bot.intern import build_regional_sst_anomaly_bundle

        # [P1-3] Call directly (not via _fetch_strict) — degrade per region,
        # not per source. A single ERDDAP failure skips that region; the source
        # only fails if ALL regions return nothing (empty list treated as error).
        readings = ocean_sst_anomaly.fetch_all_regions(strict=False)
        if not readings:
            raise SourceFetchError("ocean_sst_anomaly: all regions failed or returned no data")

        # [P1-2] Annual-keyed state -> bare slugs for the current year only.
        # Derive year from the READING date (CRW lags ~2 days; near Jan 1,
        # date.today() would mis-key a Dec 30/31 reading into the new year).
        reading_year = readings[0].date[:4] if readings else str(date.today().year)
        prefix = f"{reading_year}/"
        last_tiers = {
            key[len(prefix):]: tier
            for key, tier in bot_state.get("sst_anom_last_tier", {}).items()
            if key.startswith(prefix)
        }

        events = ocean_sst_anomaly.detect_regional_sst_anomaly_events(readings, last_tiers)
        source_promoted = 0

        for event in events:
            if state.is_duplicate(bot_state, event.event_id):
                state.update_sst_anom_tier(bot_state, event.region_slug, event.tier)
                continue
            if _sst_anom_annual_cap_reached(bot_state):
                break

            score = score_regional_sst_anomaly(event.region_slug, event.anomaly_c, event.tier)
            if not _should_draft(score, event.event_id):
                continue

            source_promoted += 1
            review_context = _review_context(
                source="NOAA Coral Reef Watch 5km SST anomaly (gridded)",
                source_key="ocean_sst_anomaly",
                headline=(
                    f"{event.region_display_name} SST anomaly: "
                    f"+{event.anomaly_c:.2f}°C tier {event.tier}"
                ),
                current_run=current_run,
                facts=[
                    _fact("Region", event.region_display_name),
                    _fact("Area-weighted anomaly", f"+{event.anomaly_c:.2f}°C"),
                    _fact("Tier", str(event.tier)),
                    _fact("Grid cells", str(event.cells_used)),
                    _fact("Signal type", "Area-weighted basin-mean anomaly (NOT Hobday MHW)"),
                ],
            )
            bundle = build_regional_sst_anomaly_bundle(event)

            _region_slug = event.region_slug
            _tier = event.tier
            _reading_date = event.date  # [P1-2] pass reading date, not date.today()

            def _on_success(
                _bs: BotState = bot_state,
                _slug: str = _region_slug,
                _t: int = _tier,
                _d: str = _reading_date,
            ) -> None:
                state.update_sst_anom_tier(_bs, _slug, _t, _d)
                state.increment_sst_anom_annual_count(_bs, _d)

            _enqueue_story_candidate(
                bot_state,
                bundle=bundle,
                score=score,
                source="ocean_sst_anomaly",
                legacy_type="regional_sst_anomaly",  # NEW category — not marine_heatwave
                event_id=event.event_id,
                review_context=review_context,
                cooldown_exempt=False,
                on_draft_success=_on_success,
            )

        _record_source_run(
            current_run, bot_state, "ocean_sst_anomaly", start,
            status="success", observed=len(readings),
            promoted=source_promoted, drafted=0,
        )
    except Exception as e:
        print(f"[alerts] ocean_sst_anomaly error: {e}")
        state.log_error(bot_state, "ocean_sst_anomaly", str(e))
        _record_source_run(
            current_run, bot_state, "ocean_sst_anomaly", start,
            status="failed", error=str(e),
        )
    return drafted
```

**Step 8: Wire into orchestrator**

In `src/orchestrator/run_alerts.py`, after the `run_ocean_sst` import:
```python
from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly
```
After `drafted += run_ocean_sst(bot_state, current_run)`:
```python
drafted += run_ocean_sst_anomaly(bot_state, current_run)
```

**Step 9: common.py wiring**

In `src/orchestrator/common.py`:
- Add `ocean_sst_anomaly` to the `from src.data import …` statement.
- Add `score_regional_sst_anomaly` to the scoring imports (after `score_marine_heatwave`).
- Add constant + helper (after `SNOW_ANNUAL_CAP`):
```python
SST_ANOM_ANNUAL_CAP = 10

def _sst_anom_annual_cap_reached(bot_state: BotState, cap: int = SST_ANOM_ANNUAL_CAP) -> bool:
    year_key = str(date.today().year)
    count = bot_state.get("sst_anom_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[sst_anom] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False
```
- Add both to `__all__`.

---

## Bundle + writer-prompt changes

**Writer framing discipline:** The bundle `signal_kind` is `"regional_sst_anomaly"`. The writer must frame this as a regional SST anomaly — not a "marine heatwave" in the Hobday sense. The `current_facts` list includes a `"signal_note"` field flagging this. The writer prompt already says "the bundle is source of truth; cite its values verbatim." No prompt surgery needed beyond the `signal_note` constraint.

**Allowed writer framings:**
- "The [Region] is running [+X°C] above its long-term average for this time of year"
- "Sea surface temperatures across the [Region] are averaging [X°C] above normal this week"
- "The [Region] has crossed [threshold]°C above its climatological baseline"

**Disallowed writer framings:**
- "marine heatwave Category [N]" (Hobday classification — not implemented)
- "marine heatwave" as a standalone descriptor without "regional SST anomaly" qualification
- Implying a single point/spot value — the figure is a **basin-area-weighted mean**

---

## Scoring + threshold

| function | file | category | threshold |
|----------|------|----------|-----------|
| `score_regional_sst_anomaly(region_slug, anomaly_c, tier)` | `src/editorial/scoring/marine.py` | `regional_sst_anomaly` | 76 (new entry in thresholds.py) |

Score formula intent — **[P1-5] updated to real computed totals** (see Step 3 calibration table):
- Tier 1, +2.5°C, non-marquee basin: total ≈ 77 — PASSES (threshold 76). Tier-1 fires for all basins; `manual_only` gate + data-driven calibration manage noise.
- Tier 1, +2.5°C, marquee basin: total ≈ 78 — passes; named-basin bump adds ~1–2 pts.
- Tier 2, +3.5°C, any basin: total ≈ 80 — solid pass.
- Tier 3, +4.5°C, any basin: total ≈ 83 — elite.
- **Thresholds are PROVISIONAL** pending `fetch_all_regions()` calibration run over recent dates (OPEN QUESTION 2).

Sensitivity stays at 6 (same as global MHW — no human-harm pathway for a basin SST anomaly; ecological harm is indirect).

---

## State / caps / cooldowns

**State keys (new):**
- `sst_anom_last_tier: dict[str, int]` — keyed by `"{YYYY}/{slug}"`. Annual rotation = free annual reset.
- `sst_anom_annual_count: dict[str, int]` — keyed by year string.

**Annual cap:** 10 tweets/year across all 13 regions (`SST_ANOM_ANNUAL_CAP = 10`). Conservative for a new signal; raise after live observation.

**Tier dedup (within a year):** Once a tier-2 fires for a region in year Y, a tier-1 won't re-fire that year. A tier-3 fires on top of a prior tier-2 (different event_id). Tier state resets on Jan 1 via key rotation.

**City cooldown:** N/A — no `city` field; `cooldown_exempt=False` is passed but `city=""` so the city-cooldown gate is a no-op.

**No same-day dedup** with the global-streak signal — distinct event_ids (`marine_heatwave_streak_*` vs. `sst_anom_*`) and distinct `source` keys (`ocean_sst` vs. `ocean_sst_anomaly`).

---

## Approval policy

In `src/editorial/approval.py`, add a branch **before** the `marine_heatwave` block (line 151):

```python
if tweet_type == "regional_sst_anomaly":
    return ApprovalPolicy(
        key="regional_sst_anomaly_manual",
        mode="manual_only",
        recommended_delay_minutes=None,
        can_auto_approve=False,
        reason=(
            "New per-region SST anomaly signal (NOAA CRW gridded) — manual "
            "review required until scoring calibration is confirmed against live "
            "data. Upgrade to suggested_auto after 10+ real events pass the bar."
        ),
    )
```

The `marine_heatwave` branch at line 151 (`suggested_auto`, 90 min) is unchanged.

---

## Test plan

### `tests/test_ocean_sst_anomaly.py`

All HTTP mocked via `unittest.mock.patch` on `src.data._http.fetch_with_retry`.

```python
def _fake_griddap_csv(date_iso, cells):
    """CRW ERDDAP griddap CSV: 2 header lines then data rows.
    cells = [(lat, lon, anomaly), ...]."""
    head = (
        "time,latitude,longitude,sea_surface_temperature_anomaly\n"
        "UTC,degrees_north,degrees_east,degree_C\n"
    )
    body = "".join(
        f"{date_iso}T12:00:00Z,{lat},{lon},{val}\n" for lat, lon, val in cells
    )
    return head + body

def test_region_registry_length():
    assert len(REGION_REGISTRY) == 13

def test_region_registry_boxes_valid():
    slugs = [r.slug for r in REGION_REGISTRY]
    assert len(slugs) == len(set(slugs))            # unique
    for r in REGION_REGISTRY:
        assert r.lat_s < r.lat_n
        assert r.lon_w <= r.lon_e, (  # [P2-2] no dateline crossing in v1 registry
            f"{r.slug}: lon_w ({r.lon_w}) > lon_e ({r.lon_e}) — dateline crossing not supported; "
            "split into two sub-boxes"
        )
        assert -90 <= r.lat_s and r.lat_n <= 90
        assert -180 <= r.lon_w and r.lon_e <= 180

def test_build_url_raises_on_dateline_crossing():
    """[P2-2] _build_url must raise ValueError for lon_w > lon_e, not silently clamp."""
    from src.data.ocean_sst_anomaly import RegionDef, _build_url
    bad = RegionDef("test_bad", "Bad Region", -10, 10, 170, -170)  # crosses dateline
    with pytest.raises(ValueError, match="dateline-crossing"):
        _build_url(bad)

def test_region_registry_has_marquee_basins():
    slugs = {r.slug for r in REGION_REGISTRY}
    for s in ("north_atlantic","subpolar_n_atlantic","ne_pacific_blob",
              "mediterranean","tasman_sea","gulf_of_mexico","caribbean",
              "western_indian_ocean","bay_of_bengal","coral_triangle",
              "great_barrier_reef","california_current","nino34"):
        assert s in slugs

def test_area_weighted_mean_equals_simple_for_single_latitude():
    cells = [(10.0, 3.0), (10.0, 5.0)]
    assert abs(_area_weighted_mean(cells) - 4.0) < 1e-9

def test_area_weighted_mean_downweights_high_latitude():
    # A hot low-lat row + cold high-lat row: weighted mean tilts toward low-lat.
    cells = [(0.0, 4.0), (60.0, 0.0)]
    naive = 2.0
    assert _area_weighted_mean(cells) > naive

def test_parse_griddap_csv_skips_nan_and_blanks():
    text = _fake_griddap_csv("2026-06-06", [(5.0,-160.0,1.5),(5.0,-159.95,float("nan"))])
    iso, cells = _parse_griddap_csv(text)
    assert iso == "2026-06-06"
    assert cells == [(5.0, -160.0, 1.5)]            # NaN row dropped

# [P1-4] Fill-value and out-of-valid-range filtering
def test_parse_griddap_csv_rejects_fill_value():
    """_FillValue -327.68 must not reach the area-weighted mean."""
    text = _fake_griddap_csv("2026-06-06", [(5.0,-160.0,3.0),(5.0,-159.95,-327.68)])
    _, cells = _parse_griddap_csv(text)
    assert all(v != -327.68 for _, v in cells), "fill value leaked into cell list"
    assert len(cells) == 1

def test_parse_griddap_csv_rejects_out_of_valid_range():
    """Values outside [-15, 15] °C per NOAA metadata must be dropped."""
    text = _fake_griddap_csv("2026-06-06", [(5.0,-160.0,3.0),(5.0,-159.95,20.0),(5.0,-159.9,-20.0)])
    _, cells = _parse_griddap_csv(text)
    assert len(cells) == 1
    assert cells[0][1] == 3.0

def test_detect_tier_boundaries():
    assert _detect_tier(2.4) is None
    assert _detect_tier(2.5) == 1
    assert _detect_tier(3.5) == 2
    assert _detect_tier(4.5) == 3
    assert _detect_tier(5.1) == 3

def test_fetch_region_sst_success_tier2():
    # All cells +3.6 at one latitude -> area-weighted mean +3.6 -> tier 2
    ...

def test_fetch_region_sst_below_floor_returns_none():
    # mean +1.0 -> below tier-1 -> None
    ...

def test_fetch_region_sst_http_failure_returns_none():
    # fetch_with_retry raises -> None when strict=False
    ...

def test_fetch_region_sst_http_failure_strict_raises():
    # strict=True -> SourceFetchError
    ...

def test_detect_events_fires_on_tier_increase():
    ...

def test_detect_events_skips_same_or_lower_tier():
    ...

def test_detect_events_event_id_format():
    # 'sst_anom_<slug>_tier<N>_<date>'
    ...

def test_annual_tier_key_rotation():
    from src import state
    bs = deepcopy(DEFAULT_STATE)
    state.update_sst_anom_tier(bs, "north_atlantic", 3)
    year = str(date.today().year)
    assert f"{year}/north_atlantic" in bs["sst_anom_last_tier"]
    assert f"{int(year)+1}/north_atlantic" not in bs["sst_anom_last_tier"]
```

### `tests/test_ocean_sst_anomaly_orchestrator.py`

```python
def test_run_ocean_sst_anomaly_fires_and_enqueues(fake_bot_state): ...   # one tier-2 reading -> queue has legacy_type="regional_sst_anomaly"
def test_run_ocean_sst_anomaly_annual_cap_stops_after_N(fake_bot_state): ...
def test_run_ocean_sst_anomaly_duplicate_skips(fake_bot_state): ...
def test_run_ocean_sst_anomaly_on_draft_success_updates_tier(fake_bot_state): ...  # annual-keyed tier + annual count
def test_run_ocean_sst_anomaly_legacy_type_is_regional(fake_bot_state): ...
def test_run_ocean_sst_anomaly_annual_state_filtered_to_current_year(fake_bot_state): ...  # prior-year keys ignored
```

### `tests/test_editorial_scoring.py` (extend existing)

```python
def test_score_regional_sst_anomaly_tier1_marquee_basin_passes():
    # [P1-5] marquee basin tier-1 passes; named-basin bump adds ~1-2 pts over non-marquee
    s = score_regional_sst_anomaly("north_atlantic", 2.6, 1)
    assert s.passes
    assert s.total >= 76

def test_score_regional_sst_anomaly_tier1_non_marquee_basin_also_passes():
    # [P1-5] REVISED — real weights yield ~77 for non-marquee tier-1; "minor fails" intent
    # was based on hand arithmetic that didn't match _compute_total. Tier-1 fires for all
    # basins; manual_only gate + data-calibration manage noise. PROVISIONAL: re-evaluate
    # after running fetch_all_regions() over recent dates (OPEN QUESTION 2).
    s = score_regional_sst_anomaly("bay_of_bengal", 2.5, 1)
    assert s.passes   # CHANGED from "assert not s.passes"
    # marquee bump makes north_atlantic score higher than bay_of_bengal at same tier
    assert score_regional_sst_anomaly("north_atlantic", 2.5, 1).total > s.total

def test_score_regional_sst_anomaly_tier2_any_basin_passes():
    s = score_regional_sst_anomaly("bay_of_bengal", 3.6, 2)
    assert s.passes
    assert s.total >= 79

def test_score_regional_sst_anomaly_tier3_elite():
    assert score_regional_sst_anomaly("gulf_of_mexico", 4.8, 3).total >= 82

def test_score_regional_sst_anomaly_blob_named_bump():
    # the Blob is a marquee basin -> gets the shareability bump over non-marquee at same tier
    blob = score_regional_sst_anomaly("ne_pacific_blob", 2.6, 1)
    bob  = score_regional_sst_anomaly("western_indian_ocean", 2.6, 1)
    assert blob.passes
    assert blob.total > bob.total

def test_score_regional_sst_anomaly_category():
    s = score_regional_sst_anomaly("subpolar_n_atlantic", 3.6, 2)
    assert s.category == "regional_sst_anomaly"
    assert s.category != "marine_heatwave"
```

### `tests/test_editorial_approval.py` (extend existing)

```python
def test_regional_sst_anomaly_approval_is_manual_only():
    p = recommend_approval_policy("regional_sst_anomaly", signal_total=80)
    assert p.mode == "manual_only"
    assert p.can_auto_approve is False

def test_marine_heatwave_approval_unchanged():
    p = recommend_approval_policy("marine_heatwave", signal_total=80)
    assert p.mode == "suggested_auto"
    assert p.can_auto_approve is True
```

---

## Risks / open questions / design forks

> **Build-gating note:** the **gridded fetch, the cos-lat area-weighting, and the griddap CSV/stride contract are the riskiest parts of this plan.** They were verified by live probes on 2026-06-08 (real subset returned; area-weighted mean computed end-to-end), but the production code path (ThreadPool over 13 regions, freshness assertion, error handling, score calibration) has not been exercised. **Run a focused verification / Codex pass on `src/data/ocean_sst_anomaly.py` + the scorer calibration before wiring into `run_alerts.py`.** Specifically re-confirm: (a) the endpoint still returns data, (b) stride/payload sizes per region, (c) `score_regional_sst_anomaly(...).total` actually lands where the calibration table claims.

### OPEN QUESTION 1 (#1 — endpoint durability): CRW ERDDAP availability & lag
**Status: VERIFIED working 2026-06-08**, but it is a live third-party ERDDAP node and the single point of failure for the whole signal. Risks: (a) the node goes down or rate-limits a 13-region burst; (b) the dataset ID `noaacrwsstanomalyDaily` is renamed/retired; (c) lag exceeds 5 days during an outage. Mitigations: `_MAX_DATA_LAG_DAYS=5` + `assert_freshness` already gate stale data; `strict=False` per region degrades gracefully (a down region yields no event rather than a crash); the documented fallback is OISST `ncdcOisst21Agg` on `coastwatch.pfeg.noaa.gov` (different host, requires self-built 1991–2020 climatology — a larger change). **Before building, re-probe the endpoint; if it is down or renamed, resolve this question first — do NOT substitute an unverified URL.**

### OPEN QUESTION 2 (MEDIUM — region box calibration): are basin-mean thresholds right?
A +2.5°C **basin-mean** over a generous box is a high bar — much of a large box may be near-normal even during a notable local heat event, pulling the area-weighted mean down. Two sub-questions: (a) are the boxes too large (diluting real events)? e.g. `north_atlantic` 0–60°N/−80–0 is huge; a tighter sub-box might better capture the 2023 signal. (b) Are the absolute tiers (+2.5/+3.5/+4.5°C on a basin mean) calibrated to fire at a sane rate? **Recommended pre-build check:** run `fetch_all_regions()` against live data for several recent dates and inspect the distribution of area-weighted means per box; tune box extents and/or tier floors before shipping. This is a data-driven calibration, not a code risk.

### OPEN QUESTION 3 (LOW — resolved by annual key): tier reset on recovery
The annual `"{YYYY}/{slug}"` key gives a free cross-year reset. Within a year the tier only increases (avoids re-firing lesser events in the same season). If intra-season reset is desired (a basin recovers then re-anomalizes as a genuinely new event), add a recovery path: store `sst_anom_last_reading_c` per region; if anomaly drops below ~1.5°C, reset that region's tier key. Deferred to v2.

### FORK 1: Hobday MHW categories (deferred to v2)
v1 ships absolute tiers only. v2 can layer Hobday categories (I–IV vs the 90th-percentile of a per-DOY climatology). CRW does **not** publish the 90th-percentile field, so v2 would need a precomputed per-DOY percentile baseline per region (e.g. via the `marineHeatWaves`/`heatwaveR` library over OISST history) — a substantial add. When v2 ships Hobday, use a distinct category (`regional_sst_anomaly_hobday`); do not overload the v1 threshold/scorer.

### FORK 2: full-res vs strided sampling
v1 uses a global `_GRID_STRIDE=20` (≈1° effective). This is the deliberate payload mitigation (verified: 241k rows → 653 rows on a marquee box). Forks: (a) per-region stride for small boxes (e.g. GBR, California Current) that benefit from finer sampling; (b) request `.nc` (netCDF) instead of `.csv` for smaller transfer if payloads ever matter — but CSV keeps the parser trivial and is verified working. Stick with CSV + stride 20 for v1.

### FORK 3: dateline-crossing regions
v1's 13 boxes all satisfy `lon_w ≤ lon_e` in −180/180, so none cross the dateline. Adding a Bering/NW-Pacific or full-Pacific box later requires splitting into two sub-boxes and unioning the area-weighted means (ERDDAP silently clamps `lon_w>lon_e` to one side — verified wrong-coverage failure 2026-06-08). Encode `RegionDef` with an optional `extra_box` then, not now.

---

## Verification

After all steps are complete:

```bash
# Type check
python -m mypy src/data/ocean_sst_anomaly.py \
               src/orchestrator/sources/ocean_sst_anomaly.py \
               src/editorial/scoring/marine.py \
               src/editorial/thresholds.py \
               src/editorial/approval.py \
               src/two_bot/intern/marine.py \
               src/state.py \
               src/state_schema.py

# Full suite (excluding voice replay which needs live API)
python -m pytest tests/ -q -m "not voice_replay"

# Target tests
python -m pytest tests/test_ocean_sst_anomaly.py \
                 tests/test_ocean_sst_anomaly_orchestrator.py \
                 tests/test_editorial_scoring.py \
                 tests/test_editorial_approval.py \
                 tests/test_state.py -v

# Lint changed files
python -m ruff check src/data/ocean_sst_anomaly.py \
                     src/orchestrator/sources/ocean_sst_anomaly.py \
                     src/editorial/scoring/marine.py \
                     src/editorial/thresholds.py \
                     src/editorial/approval.py \
                     src/two_bot/intern/marine.py \
                     src/orchestrator/common.py \
                     src/orchestrator/run_alerts.py \
                     src/state.py \
                     src/state_schema.py \
                     src/two_bot/intern/__init__.py \
                     src/editorial/scoring/__init__.py

# Confirm event_id namespace does not collide with the global-mean signal
python -c "
from src.data.ocean_sst_anomaly import REGION_REGISTRY
import re
pat = re.compile(r'^sst_anom_')
for r in REGION_REGISTRY:
    eid = f'sst_anom_{r.slug}_tier2_2026-06-08'
    assert pat.match(eid), eid
    assert 'marine_heatwave_streak' not in eid, eid
print('event_id namespace OK; regions =', len(REGION_REGISTRY))
"

# LIVE endpoint smoke (optional, network) — re-confirm the verified source before shipping
python -c "
from src.data import ocean_sst_anomaly as m
rs = m.fetch_all_regions()
print('regions returning a tier>=1 anomaly today:', [(r.region_slug, r.anomaly_c, r.tier) for r in rs])
"
```

The `tests/test_main.py` integration test should also pass — verify it doesn't assert on the exact set of source runner imports.

---

## Out of scope / future

- **Coral DHW cross-reference:** when a `RegionalSSTAnomalyEvent` fires for a basin at the same time as a `CoralBleachingEvent` in the same area (e.g. GBR, Coral Triangle, Caribbean), the synthesis layer could flag a compound event. Deferred; see `src/editorial/synthesis.py`. (Both signals now share the CRW family, making cross-reference natural.)
- **Hobday percentile climatology (v2):** see Fork 1. Requires a per-DOY 90th-percentile baseline per region.
- **Per-patch / sub-basin SST anomaly (v3):** a basin-mean misses localized extreme patches. A max-anomaly-cell or contiguous-hot-patch detector over the same griddap field would catch these, at the cost of more grid handling. The gridded source already supports it (full 0.05° available); v1 deliberately averages.
- **SST trend (rate of change):** rate detection needs a rolling `anomaly_history` per region. Deferred.
- **Dateline / additional regions:** add Bering, NW Pacific, Southern Ocean, etc. via the Fork-3 split-box mechanism after confirming each box's behavior and calibrating tiers.
- **OISST fallback path:** if CRW ERDDAP becomes unreliable, implement the `ncdcOisst21Agg` path (different host, self-built 1991–2020 per-DOY climatology + cache file + backfill script). Documented in Data source / Rejected sources.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 2 | clean | Rev 2 fixes folded (slugs/naming/suppressor/category). Rev 3 gridded data layer re-reviewed by Codex (5 P1 + 2 P2), all folded (Rev 4). |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | Rev 4: 5 P1 + 2 P2 from Codex data-layer review folded; plan is internally consistent and build-ready pending the two documented pre-build calibration steps. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run |

- **CODEX (Rev 4):** All 7 Codex findings from the Rev 3 gridded data-layer review have been folded into the plan: [P1-1] `_merge_state()` state-persistence fix; [P1-2] lag-aware year key (reading date, not `date.today()`); [P1-3] partial degradation (`fetch_all_regions` defaults `strict=False`, runner no longer uses `_fetch_strict`); [P1-4] fill-value/valid-range filter in `_parse_griddap_csv` + tests; [P1-5] score calibration table corrected to real `_compute_total` weights — tier-1 fires for all basins, thresholds marked PROVISIONAL, test assertions updated; [P2-1] min-valid-cell coverage safeguard before tiering; [P2-2] dateline fail-fast in `_build_url`.
- **Remaining pre-build steps (documented, not blockers to starting build):** (1) re-probe the `noaacrwsstanomalyDaily` ERDDAP endpoint before coding (OPEN QUESTION 1); (2) run `fetch_all_regions()` over recent dates to calibrate basin boxes and tier floors against real anomaly distributions, then fix final thresholds (OPEN QUESTION 2). These are data-driven calibration steps, not design changes.
- **VERDICT:** ENG CLEARED — build-ready. Remaining pre-build steps (documented, consistent with the other plans' gates): re-probe the ERDDAP endpoint, and run the data-driven tier/box calibration before fixing final thresholds.
