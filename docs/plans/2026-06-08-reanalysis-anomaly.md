> **STATUS: DEFERRED (eng-review 2026-06-08).** Split out of the temp-anomaly plan; Part A (absolute-extreme) ships first. This plan is NOT yet eng-reviewed in full — when picked up, run /plan-eng-review on it. Key open risks flagged by eng-review: (1) per-run archive fan-out (~30-90 archive calls every alerts cycle across ~10-15 countries × sample coords) needs a load/caching design; (2) the climatology backfill (~1,500 one-time archive requests) needs rate-limit handling; (3) point-index-vs-area-weighted honesty must hold in the writer + fact-check.

# Reanalysis anomaly (regional/country scale) — implementation plan [DEFERRED]

Detect when a *whole country or region's sampled cities* averaged far above climatological normal for 3+ consecutive days. Single-city detection systematically misses "the entire Sahel is running 8°C above normal." Requires a new data source and a pre-computed daily climatology baseline.

**Build after Part A (`absolute_extreme`) is running in production and the climatology design is settled (see Step 0 below).**

---

## Background

@theheat is a station-record detector. It knows when Phoenix broke its June 14 record, but it has no concept of "France just had its warmest 5-day stretch ever averaged nationally." @extremetemps fills that gap manually. This plan closes it programmatically for regional/country-scale sustained anomalies.

### Explicit contrast with existing `anomaly_hot` / `anomaly_cold` and Part A

| Property | Existing `anomaly_hot` / `anomaly_cold` | Part A `absolute_extreme` | Part B `reanalysis_anomaly` |
|---|---|---|---|
| Unit of analysis | Single city | Single city | Country / region (N sampled cities) |
| Trigger criterion | today ≥ 15°C above *that city's* 30-yr monthly mean | today ≥ absolute threshold *for latitude band* | sampled-city mean T2m ≥ +6°C above daily climatology for ≥3 days |
| Baseline required | Open-Meteo 30-yr archive (already fetched) | None — threshold table only | Self-built daily ERA5 climatology from `ARCHIVE_URL` |
| Event type | `AnomalyEvent` dataclass | `AbsoluteExtremeEvent` (new, shipped) | `RegionalAnomalyEvent` (new, this plan) |
| `event_id` prefix | `anomaly_hot_*` / `anomaly_cold_*` | `absextreme_*` | `reganom_*` |
| Category | `anomaly` (threshold 74) | `absolute_extreme` (78) | `regional_anomaly` (proposed 76) |
| New data needed | No | No | Yes — one-time climatology backfill |

---

## Data sources

### Climatology source decision (VERIFIED 2026-06-08)

#### NASA POWER ruled out for daily normals

> **Verified via live API call to `https://power.larc.nasa.gov/api/temporal/climatology/point`:**
> The NASA POWER climatology endpoint returns **monthly** values only (keys JAN–DEC + ANN). The period is a **20-year window (2001–2020)**, not the canonical 1991–2020 30-year normal. No standard deviation is returned. There is no daily climatology endpoint. Comparing a daily T2m reading to a monthly normal creates season-boundary artifacts (early-June vs. late-June readings both compared to the same June mean), which will distort anomaly detection at month transitions. NASA POWER is therefore **not suitable** as the daily baseline source.

#### Recommended approach: self-built DAILY ERA5 climatology via `ARCHIVE_URL` (already wired)

`ARCHIVE_URL = "https://archive-api.open-meteo.com/v1"` is already defined at `src/data/open_meteo.py` line 14. The Open-Meteo ERA5 archive exposes `temperature_2m_max` and `temperature_2m_min` at daily granularity back to 1940, making it straightforward to build a 1991–2020 daily normal + σ per sample point.

**One-time backfill job**: for each country sample point, fetch 30 years of ERA5 daily T2m, compute per-calendar-day mean and σ for the 1991–2020 period, cache as `data/climatology_daily_cache.json`. The job runs once (or whenever sample points change) and is checked into the repo. The daily detection then does: `anomaly = today_t2m - daily_normal_c`.

Scale check: 50 sample points × 365 days × 30 years ≈ 547,500 daily rows. A one-time batch fetch of ~1,500 year-point requests (50 points × 30 years), each returning 365 rows, is fully within Open-Meteo's free tier. Runtime ~15–30 min one-time; cached forever.

**OPEN RISK (from eng-review):** The backfill (~1,500 archive requests) needs explicit rate-limit handling. The backfill script must implement backoff/retry and ideally checkpoint progress so a mid-run failure can be resumed without re-fetching already-completed points.

**Alternative (Option B — month-aware monthly normals)**: if the backfill job is deferred, the minimum viable approach is to use the Open-Meteo 30-year archive to compute monthly means per sample point (already done implicitly in the existing `anomaly_hot` path for per-city means). The comparison must then be month-aware: for a reading on June 3, compare against the June monthly mean. Season-boundary artifacts are then bounded to 30 days, not eliminated. Document this limitation explicitly in the bundle. Only use this as a temporary stopgap; the daily ERA5 cache is the target state.

**Option C (Copernicus CDS ERA5 gridded)**: true area-weighted country means. Authoritative. Requires `CDS_API_KEY` env var, `cdsapi` dependency, latency of minutes. Out of scope for this PR; future upgrade path.

**Decision**: implement **Option A** (daily ERA5 climatology cache). Step 0 below is a GATE — do not write detection logic until the cache file exists and is verified for at least 3 countries.

---

## Signal definitions and thresholds

### `reanalysis_anomaly` (country / regional scale)

Fires when a set of sampled cities across a country averaged ≥ threshold above daily ERA5 climatological normal for ≥ `min_days` consecutive days.

**Honest framing**: this is a POINT INDEX over N sampled cities — NOT an area-weighted national mean. The bundle `where` field, writer framing, and fact-checker instructions must all reflect this. "Across N sampled cities in [Country]" — never "[Country] averaged +8°C" unless a real gridded mean is computed.

#### Trigger parameters

| Parameter | Recommended value | Notes |
|---|---|---|
| Anomaly threshold (moderate) | +6°C above 1991–2020 daily ERA5 normal | Captures sustained "sampled cities cooking" events |
| Anomaly threshold (extreme) | +8°C above normal | Elite threshold; country-wide +8°C across N sampled cities is a top-10 historical event |
| Sustained window | 3 days | Below 3 days risks single-hot-day noise; 3 is the meteorological "heat wave" minimum |
| Minimum sample cities per country | 3 | Below 3, the mean is too noisy for any honest claim |
| Sigma alternative | +2.5σ | If daily σ is available from the ERA5 cache, this is the sigma equivalent of ~+6°C for most temperate countries |

**Recommendation**: Use `anomaly_c ≥ 6.0` (absolute degrees above daily normal) as the primary trigger and optionally compute sigma for the writer bundle context. Absolute degrees are easier to fact-check than sigma.

#### event_id scheme

```
reganom_<region_slug>_<YYYY-MM-DD>
reganom_France_2026-06-14
reganom_Sahel_2026-06-14
```

`region_slug = region_name.replace(" ", "_")`.

#### Category and threshold

Proposed category: `regional_anomaly`. Proposed threshold: **76**.

Rationale: Matches `monthly_record` (76). A sustained sampled-city anomaly is a genuine historical event but depends on a pre-computed ERA5 cache rather than live station observations. 76 admits clear events while filtering noise from marginal anomalies at the 3-day minimum.

---

## Files to create / modify

### New files

**New: `data/climatology_daily_cache.json`** (produced by backfill job, checked in)

JSON structure: `{country: {city_key: {"lat": f, "lon": f, "days": {"MM-DD": {"mean_c": f, "std_c": f}}}}}`. The backfill script produces this file; the daily runner reads it.

**New: `scripts/build_climatology_cache.py`** (one-time backfill, not in alerts path)

Fetches 1991–2020 ERA5 daily T2m for each sample point via `ARCHIVE_URL`, computes per-calendar-day mean and σ, writes `data/climatology_daily_cache.json`. Should be idempotent (skip points already cached). Add a `--countries` flag to backfill a subset. Runtime ~15–30 min for 50 points. Must implement rate-limit backoff and checkpointing.

**New: `src/data/reanalysis_anomaly.py`**

Contains:
- `RegionalAnomalyEvent` dataclass
- `load_daily_climatology(cache_path: str) -> dict` — loads `data/climatology_daily_cache.json`
- `fetch_country_daily_t2m(country: str, sample_coords: list[tuple[float, float]], date_range_days: int = 7) -> dict[tuple, list[float]] | None` — uses `ARCHIVE_URL` (same integration, no new base URL)
- `detect_regional_anomaly(country: str, sample_coords: list[tuple[float, float]], climatology: dict, *, min_anomaly_c: float = 6.0, min_days: int = 3) -> RegionalAnomalyEvent | None`
- `COUNTRY_SAMPLE_COORDS: dict[str, list[tuple[float, float]]]` — hard-coded dict of country → representative lat/lon pairs drawn from `data/cities.csv`

**New: `src/orchestrator/sources/reanalysis_anomaly.py`**

Contains:
- `run_reanalysis_anomaly(bot_state, current_run) -> int`
- Uses `from src.orchestrator.common import *` pattern
- Loads climatology cache at runner startup (cached in module-level `_CLIMATOLOGY` after first load)
- Calls `detect_regional_anomaly` for each country in `COUNTRY_SAMPLE_COORDS`
- Calls `score_regional_anomaly`, checks `_should_draft`, calls `_enqueue_story_candidate`

**OPEN RISK (from eng-review):** Per-run archive fan-out is ~30-90 archive calls every alerts cycle (10-15 countries × sample coords). This needs a dedicated caching design — the module-level `_CLIMATOLOGY` cache avoids re-reading the JSON file, but the live `fetch_country_daily_t2m` calls still hit the ARCHIVE_URL every cycle. Consider: (a) caching today's fetch results in `bot_state["_reganom_live_cache"]` keyed by date, so retry runs don't re-fetch; (b) adding the country loop latency to the alerts-cycle budget calculation.

### Modifications

- `src/editorial/thresholds.py`: add `"regional_anomaly"` entry
- `src/editorial/scoring/temperature.py`: add `score_regional_anomaly`
- `src/editorial/scoring/__init__.py`: export `score_regional_anomaly`
- `src/orchestrator/common.py`: import + export `score_regional_anomaly`; add `reanalysis_anomaly` to `_two_bot_bundle_for_extreme_signal` dispatch
- `src/two_bot/intern/temperature.py`: add `build_regional_anomaly_bundle`
- `src/two_bot/intern/__init__.py`: export `build_regional_anomaly_bundle`
- `src/orchestrator/sources/__init__.py`: import and expose `run_reanalysis_anomaly` if that pattern is used (check if `__init__.py` re-exports runners — it appears not to, based on codebase pattern)
- `src/orchestrator/run_alerts.py`: call `run_reanalysis_anomaly(bot_state, current_run)` in the alerts run, guarded by `THEHEAT_REGANOM_ENABLED` env var
- `src/editorial/approval.py`: add `"regional_anomaly"` → `manual_only` policy (new signal, reanalysis source, warrants human review at launch)

---

## Step-by-step implementation

### Step 0 (GATE) — Climatology design decision and backfill

Before writing any detection code, the daily climatology cache must exist and be spot-checked.

1. Write `scripts/build_climatology_cache.py`:
   - Accepts `--countries France,India,Australia` (subset) or `--all`
   - For each sample point, fetches 1991–2020 ERA5 daily T2m from `ARCHIVE_URL`
   - Computes per-calendar-day mean and σ across the 30 years
   - Writes `data/climatology_daily_cache.json` (append-safe — skip already-cached points)
   - Implements exponential backoff + per-point checkpointing for the ~1,500-request backfill
2. Run for 3 countries, spot-check a known hot month (e.g., Paris July mean should be ~24–25°C for T2m_max)
3. Verify the cache file is reasonable before proceeding to Steps 10–14

Do not gate the entire PR on full global backfill — start with the countries in `COUNTRY_SAMPLE_COORDS` (expected: 10–15 countries at launch, ~30 min total backfill).

### Step 10 — Create `src/data/reanalysis_anomaly.py`

Implement the data layer: `RegionalAnomalyEvent`, `load_daily_climatology`, `fetch_country_daily_t2m` (using `ARCHIVE_URL`, not NASA POWER), `detect_regional_anomaly`, `COUNTRY_SAMPLE_COORDS`.

`COUNTRY_SAMPLE_COORDS` should cover at minimum: France, Spain, India, Pakistan, Australia, United States, Canada, China, Russia, Brazil, Saudi Arabia, Nigeria, and any country with ≥ 4 cities in `data/cities.csv`. Derive coordinates from `data/cities.csv` at startup (do not hardcode if the CSV is available).

`detect_regional_anomaly` computes `daily_anomaly_c` for each sample point as `today_t2m - daily_normal_c` (from the cache keyed by `MM-DD`), then averages across all sample points to get `mean_daily_anomaly_c`. It checks for ≥ `min_days` consecutive days above `min_anomaly_c`.

### Step 11 — Create `src/orchestrator/sources/reanalysis_anomaly.py`

```python
"""Source runner for regional reanalysis anomaly detection."""
from __future__ import annotations
from src.orchestrator.common import *

_CLIMATOLOGY: dict | None = None  # module-level cache; loaded once per process

def run_reanalysis_anomaly(bot_state: BotState, current_run: dict | None) -> int:
    global _CLIMATOLOGY
    drafted = 0
    if not os.getenv("THEHEAT_REGANOM_ENABLED", "1") == "1":
        return 0
    print("[alerts] Checking regional reanalysis anomaly...")
    source_start = time.perf_counter()
    source_promoted = 0
    try:
        from src.data.reanalysis_anomaly import (
            detect_regional_anomaly, COUNTRY_SAMPLE_COORDS, load_daily_climatology,
        )
        if _CLIMATOLOGY is None:
            _CLIMATOLOGY = load_daily_climatology()
        for country, coords in COUNTRY_SAMPLE_COORDS.items():
            ev = detect_regional_anomaly(country, coords, _CLIMATOLOGY)
            if ev is None:
                continue
            if state.is_duplicate(bot_state, ev.event_id):
                continue
            score = score_regional_anomaly(
                ev.mean_anomaly_c, ev.sustained_days, ev.cities_sampled,
            )
            if not _should_draft(score, ev.event_id):
                continue
            source_promoted += 1
            from src.two_bot.intern import build_regional_anomaly_bundle
            bundle = build_regional_anomaly_bundle(ev)
            review_ctx = _review_context(
                source="Open-Meteo ERA5 daily climatology",
                source_key="reanalysis_anomaly",
                headline=(
                    f"{country}: +{ev.mean_anomaly_c:.1f}C above daily ERA5 normal "
                    f"across {ev.cities_sampled} sampled cities for {ev.sustained_days} days"
                ),
                current_run=current_run,
                facts=[
                    _fact("Country", country),
                    _fact("Mean anomaly", f"+{ev.mean_anomaly_c:.1f}C"),
                    _fact("Sustained days", ev.sustained_days),
                    _fact("Cities sampled", ev.cities_sampled),
                    _fact("Climatology", "ERA5 1991–2020 daily normals (self-built cache)"),
                ],
            )
            _enqueue_story_candidate(
                bot_state,
                bundle=bundle,
                score=score,
                source="reanalysis_anomaly",
                legacy_type="regional_anomaly",
                event_id=ev.event_id,
                review_context=review_ctx,
                cooldown_exempt=True,
            )
        _record_source_run(
            current_run, bot_state, "reanalysis_anomaly", source_start,
            status="success", promoted=source_promoted,
        )
    except Exception as e:
        print(f"[alerts] reanalysis_anomaly error: {e}")
        state.log_error(bot_state, "reanalysis_anomaly", str(e))
        _record_source_run(
            current_run, bot_state, "reanalysis_anomaly", source_start,
            status="failed", error=str(e),
        )
    return drafted
```

### Step 12 — Wire into `run_alerts`

In `src/orchestrator/run_alerts.py`, call `run_reanalysis_anomaly(bot_state, current_run)` after the `run_extreme_signals` call, guarded by `THEHEAT_REGANOM_ENABLED` (default 1).

### Step 13 — Scoring, thresholds, approval

- `score_regional_anomaly(mean_anomaly_c, sustained_days, cities_sampled) -> EditorialScore`
- Add `"regional_anomaly": ThresholdEntry("regional_anomaly", 76, "Sampled-city regional anomaly from ERA5 daily climatology; model-derived, requires manual review at launch.")`
- Approval policy: `"regional_anomaly"` → `"manual_only"` (ERA5 cache is new, signal is new, needs editorial calibration period)

### Step 14 — Tests

Write `tests/test_reanalysis_anomaly.py` (see Test Plan section below).

---

## Bundle and writer-prompt changes

### `build_regional_anomaly_bundle`

Key facts:
- `country` or `region_name`
- `cities_sampled` — the number of sample points (required for honest framing)
- `mean_anomaly_c` — the average departure from daily ERA5 climatological normal, rounded to 1 decimal
- `sustained_days` — how many consecutive days
- `window_start` and `window_end` dates
- `climatology_source` — "ERA5 1991–2020 daily normals (self-built cache)"

**Honest `where` framing**: the `where` field in `StoryBundle` must be `f"sample of {ev.cities_sampled} cities in {ev.country}"` — never just `ev.country`. This flows through to the writer prompt. The writer must say "across N sampled cities in [Country]", never "[Country] averaged +8°C above normal." The fact-checker validates against the bundle's `where` field.

Example correct writer output: "Across 6 sampled cities in France, temperatures averaged 7.2°C above their daily 30-year normal for five consecutive days."

Example INCORRECT output (banned): "France averaged +7°C above normal." — drops the point-index caveat.

### Fact-checker implications

The fact-checker (in `src/two_bot/prompts/fact_check_prompt.py`) is generous about `WORLD_KNOWLEDGE` claims. For this signal:
- `mean_anomaly_c` is a model-derived quantity rounded to 1 decimal. The fact-checker should classify it as `BUNDLE_FACT` (it comes from the bundle, not the writer's head) but should not demand sub-decimal precision.
- Add a note to the fact-check prompt's `WORLD_KNOWLEDGE` section:

```
**f) ERA5-derived regional sampled-city means.** When the bundle's signal_kind is `regional_anomaly`, the `mean_anomaly_c` and `mean_temp_c` values are averages of ERA5 reanalysis readings across N sampled cities (not a gridded area-weighted national mean). Treat these as BUNDLE_FACTs accurate to ±0.5°C. The writer is required to frame these as "across N sampled cities in [Country]" — flag any claim that drops the point-index framing (e.g., "[Country] averaged X°C above normal" without the "sampled cities" qualifier). Claims like "this is the hottest period in the country's history" are UNVERIFIABLE unless the bundle explicitly supplies a historical comparison.
```

Round `mean_anomaly_c` to 1 decimal in `build_regional_anomaly_bundle` before it reaches the writer.

---

## Scoring

### `score_regional_anomaly`

```python
severity = 72 + min(mean_anomaly_c - 6.0, 8) * 3 + min(sustained_days - 3, 7) * 2
novelty = 84
timeliness = 90
confidence = 72 + min(cities_sampled, 8) * 1.5   # more sample cities = more trustworthy
shareability = 80 + min(mean_anomaly_c - 6.0, 6) * 2
threshold = get_threshold("regional_anomaly")     # 76
```

A 6°C / 3-day / 3-city event scores ≈ 76, just clearing. An 8°C / 7-day / 6-city event scores ≈ 86, elite.

---

## State / caps / cooldowns

- Dedup via `state.is_duplicate`. `event_id` is `reganom_<country>_<date>`. The date component means a sustained 5-day event fires on day 1 and is deduped on days 2–5. This is intentional — the story is the onset, not each subsequent day.
- No per-city cooldown (country-level signal). Pass `cooldown_exempt=True`.
- **Annual cap consideration**: at launch, add `REGANOM_ANNUAL_CAP = 12` (one per month globally is already generous for a genuinely extraordinary signal). Implement via the same pattern as `co2_annual_count` in `state.py` / `common.py`.
- Sustained-window state: the `detect_regional_anomaly` function fetches the last N days itself and checks for consecutive anomaly. No additional bot_state key is needed.

---

## Approval policy

Policy: `"manual_only"` at launch. Rationale: ERA5 daily climatology cache is new, the anomaly computation is more complex than any existing signal, and the honest framing (sampled-city point index) requires editorial judgment. Human review at every trigger during the calibration period (first 4–6 weeks). Escalate to `"suggested_auto"` once the signal has produced 5+ approved drafts without editorial corrections.

Set in `src/editorial/approval.py` under the existing `manual_only` block (line 165–187).

---

## Test plan

### `tests/test_reanalysis_anomaly.py`

```python
import responses

class TestFetchCountryDailyT2m:
    @responses.activate
    def test_returns_daily_temps_for_sample_points(self):
        # Mock Open-Meteo ARCHIVE_URL response
        responses.add(responses.GET, "https://archive-api.open-meteo.com/v1/archive", ...)
        result = fetch_country_daily_t2m("France", [(48.85, 2.35)], date_range_days=5)
        assert result is not None
        assert len(result[(48.85, 2.35)]) == 5

    @responses.activate
    def test_returns_none_on_api_failure(self):
        responses.add(responses.GET, ..., status=500)
        result = fetch_country_daily_t2m("France", [(48.85, 2.35)], date_range_days=5)
        assert result is None

class TestDetectRegionalAnomaly:
    def test_fires_at_6c_sustained_3_days(self):
        # Mock fetch functions to return 6.5°C anomaly for 3 consecutive days
        ...

    def test_does_not_fire_at_5c(self):
        ...

    def test_does_not_fire_if_only_2_days(self):
        ...

    def test_event_id_format(self):
        ev = detect_regional_anomaly(...)
        assert ev.event_id.startswith("reganom_France_")

    def test_where_field_uses_sampled_city_framing(self):
        ev = detect_regional_anomaly("France", [(48.85, 2.35), (43.30, 5.37), (45.75, 4.85)], climatology)
        bundle = build_regional_anomaly_bundle(ev)
        assert "sampled" in bundle.where.lower()
        assert "France" in bundle.where
```

---

## Risks / open questions

### Risk 1: per-run archive fan-out (flagged by eng-review)

At 10–15 countries × 3–6 sample coords each, the daily detection calls `fetch_country_daily_t2m` 30–90 times per alerts cycle. Each call hits `ARCHIVE_URL` for the last 7 days of readings. This is the same order of latency as the existing `check_extreme_signals_for_cities` loop but adds to the total cycle budget.

Mitigation design (resolve before implementing):
- Cache today's live fetch in `bot_state["_reganom_live_cache"][country][date_str]` so retry runs in the same cycle don't re-fetch.
- Cap to 10 countries per cycle at launch; add more as latency data accumulates.
- Add per-country timing to `_record_source_run` for observability.

### Risk 2: climatology backfill rate-limit handling (flagged by eng-review)

~1,500 archive requests one-time. Open-Meteo's free tier has no documented rate limit, but rapid sequential requests may trigger throttling. The backfill script must implement:
- Exponential backoff with jitter on HTTP 429 or connection errors
- Per-point checkpointing (write cache after each country completes, not at the end)
- A `--delay-ms` flag (default 200ms) for pacing

### Risk 3: point-index-vs-area-weighted honesty (flagged by eng-review)

The writer and fact-checker must enforce the sampled-city framing throughout. This risk is structurally mitigated by the `where` field in `StoryBundle` and the fact-checker prompt addition, but it requires editorial vigilance during the calibration period. Any draft that says "[Country] averaged +X°C above normal" without the "sampled cities" qualifier must be caught and rejected.

### Risk 4: fact-checker exact-match tension

The existing fact-checker treats numbers as `BUNDLE_FACT` requiring exact match. A reanalysis-derived mean is inherently an estimate. Mitigation: round `mean_anomaly_c` to 1 decimal in `build_regional_anomaly_bundle` before the writer receives it. The fact-checker instruction explicitly tolerates ±0.5°C for ERA5-derived means.

### Risk 5: climatology cache staleness

The `data/climatology_daily_cache.json` file is a one-time artifact checked into the repo. If sample coordinates change or new countries are added to `COUNTRY_SAMPLE_COORDS`, the cache must be regenerated for those entries. Add a CI step or a `Makefile` target to check that all `COUNTRY_SAMPLE_COORDS` entries have corresponding cache entries before the alerts runner starts. If a cache miss occurs at runtime, `detect_regional_anomaly` should log a warning and return `None` (graceful degradation) rather than falling back to a monthly normal.

---

## Verification

Run these in order after implementing:

```bash
# Type checking
python -m mypy src/

# Full test suite (exclude live voice replay)
python -m pytest tests/ -q -m "not voice_replay"

# Lint only changed files
python -m ruff check src/data/reanalysis_anomaly.py \
    src/orchestrator/sources/reanalysis_anomaly.py \
    scripts/build_climatology_cache.py

# Part B: verify climatology cache covers all COUNTRY_SAMPLE_COORDS (run after backfill)
python -c "
from src.data.reanalysis_anomaly import COUNTRY_SAMPLE_COORDS, load_daily_climatology
clim = load_daily_climatology()
for country in COUNTRY_SAMPLE_COORDS:
    assert country in clim, f'Missing climatology cache for {country}'
print(f'Climatology cache covers all {len(COUNTRY_SAMPLE_COORDS)} countries')
"
```

---

## Out of scope / future

- **Gridded area-weighted country means** (Copernicus CDS ERA5): the authoritative approach. Requires `CDS_API_KEY` env var and `cdsapi` dependency. Future upgrade path once this signal is validated.
- **Sub-national regions**: "the US Southwest" or "Northern India" are better regional anomaly stories than country-wide sample means for large countries. Requires a custom region-geometry definition.
- **Sigma-based triggers**: ≥ 2.5σ as an alternative or complement to +6°C absolute. The daily ERA5 climatology cache includes σ per calendar-day. Can be added to `detect_regional_anomaly` as an optional parameter once the absolute-degree trigger is validated.
- **NASA POWER as a supplemental monthly-plausibility check**: NASA POWER's 2001–2020 monthly means could be used as a sanity-check against the ERA5 daily cache (e.g., do July mean T2m values agree within 1°C?). If they diverge, flag the cache as suspicious. Optional data-quality step, not a baseline substitute.
