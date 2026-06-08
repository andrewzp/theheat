# Wet-bulb extremes — implementation plan

**Revision 2: folded Codex adversarial review (2026-06-08) — see changes in Background.**

**Goal:** detect globally dangerous wet-bulb temperature events via Open-Meteo daily data and queue `manual_only` drafts for human review.

---

## Background

@theheat's `@extremetemps`-adjacent heat lane already covers dry-air records (calendar-date, all-time, monthly archive highs), anomaly deviations, and record streaks. What it does **not** cover is heat-stress lethality — the combined temperature+humidity signal that determines whether the human body can cool itself by sweating. Wet-bulb temperature (TW) is the decisive metric: it is a physiological ceiling, not a weather record. A city with a TW of 33°C may have set no air-temp record at all, yet the event is life-threatening.

The new `wet_bulb_extreme` signal is structurally distinct from every existing temperature signal: it fires on an **absolute threshold**, not on a record-break. It belongs to the same Open-Meteo fetch cycle (no new source) but requires a separate data variable, a new event dataclass, dedicated scoring, and a new bundle builder.

**Revision 2 changes (Codex adversarial review, 2026-06-08):**

1. **[P1] Daily wet-bulb max exists — hourly-fetch premise was false.** Open-Meteo exposes `wet_bulb_temperature_2m_max` as a native daily variable (verified against live docs at https://open-meteo.com/en/docs, "Additional Daily Variables"). The original plan's claim that "wet_bulb_temperature_2m is hourly-only" was incorrect. The Data source section, detect function, and all fetch code have been rewritten to use the daily variable on the EXISTING forecast/archive request. The 262k-values-per-city backfill concern is eliminated.

2. **[P1] Inclusion-gate trap fixed.** `check_extreme_signals_for_cities()` at `src/data/open_meteo.py:641` filters bundles with `any([bundle.calendar_date_high, ..., bundle.anomaly_cold])`. A wet-bulb-only city (no air-temp record) would be dropped before `run_extreme_signals()` sees it. Fix: add `wet_bulb_extreme` field to `ExtremeSignalBundle` (line 107) and add it to the `any([...])` guard at line 641. Alternatively — and more cleanly — run wet-bulb detection as a separate post-loop pass over all cities (not just bundle survivors), avoiding the gate entirely. This plan adopts the separate-pass approach (Step 10 unchanged) but also requires the field addition for completeness and future-proofing.

3. **[P1] Tier dedup via `on_draft_success` — timing corrected.** `state.record_event()` is called at `src/orchestrator/common.py:1454`, inside `_drain_and_write_triage_queue()`, only after a draft succeeds. The tier-stamped `event_id` scheme (`wetbulb_{city}_{date}_tier{N}`) rides this existing mechanism: same-tier re-fires are blocked by the recorded event_id; tier upgrades fire because the higher-tier event_id is new. The `already_seen_tiers` parameter in `detect_wet_bulb_extremes()` is therefore redundant with the existing dedup and has been removed from the function signature. The State/dedup section reflects this.

4. **[P1] Fact-check / evidence safety — "survivability limit" and "hottest in N years" constraints.** The original plan named the tier-3 label `survivability_limit` and permitted "hottest wet-bulb in N years" framing. Both are unsafe when the underlying data is a forecast model output with no archive comparison. The writer-prompt and fact-check sections now: (a) prohibit "survivability limit" as a direct tweet claim — the tier label is bundle-internal only; (b) prohibit "hottest in N years" unless `historical_context` is non-empty and carries an explicit `archive_max_tw_c`; (c) require the draft to label TW values as "forecast model values" not observed readings; (d) add an evidence-grade note in the fact-check section.

5. **[P2] Single API call — no separate wet-bulb request.** The wet-bulb daily max is fetched by adding `wet_bulb_temperature_2m_max` to the existing `daily` param string in `detect_extreme_signals()`. No new HTTP call per city. The separate-pass orchestrator loop (Step 10) calls `detect_extreme_signals()` directly and reads `bundle.wet_bulb_extreme` from the returned bundle.

---

## Data source

Open-Meteo exposes `wet_bulb_temperature_2m_max` as a native **daily** variable (verified against live docs: https://open-meteo.com/en/docs, "Additional Daily Variables"). No hourly fetch, no client-side `max()` computation.

**Fetch strategy: extend the EXISTING request, no new HTTP call.**

`detect_extreme_signals()` (`src/data/open_meteo.py:370`) already issues:

1. A **forecast request** to `BASE_URL/forecast` with `daily=temperature_2m_max,temperature_2m_min`
2. An **archive request** to `ARCHIVE_URL/archive` with `daily=temperature_2m_max,temperature_2m_min` over the prior `archive_years`

Add `wet_bulb_temperature_2m_max` to the `daily` param string of BOTH requests. No new API calls, no new HTTP round-trips per city.

Both host constants already exist in `src/data/open_meteo.py`:

```python
# src/data/open_meteo.py:13-14
BASE_URL = "https://api.open-meteo.com/v1"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1"
```

No API key required for non-commercial use. The 638-city list loaded by `load_cities()` (line 169) is reused without change.

**Key data shape (daily, confirmed):**

```python
resp.json()["daily"]["wet_bulb_temperature_2m_max"]   # list of N daily values
resp.json()["daily"]["time"]                          # list of ISO date strings
```

The forecast request returns 1 value (today's forecast-peak TW). The archive request returns `archive_years × ~365` daily values — small, already fetched for air-temp records. No 262k-values-per-city concern.

---

## Signal definition & thresholds

### Tiers

| Tier | TW threshold | Internal label | Rationale |
|------|-------------|-------|-----------|
| 2 | ≥ 33°C | `extreme` | Even fit, acclimatized individuals face serious risk during prolonged exposure |
| 3 | ≥ 35°C | `tier_3` | Physiological ceiling where resting adults can no longer shed heat faster than they produce it; globally rare. Label is bundle-internal — do NOT use "survivability limit" in tweets (evidence-safety rule; see fact-check section). |

*(Tier 1 / ≥31°C / "danger" was cut — see NOT-in-scope. Floor is 33°C.)*

### Trigger condition

A signal fires when a city's **forecast daily-max TW** crosses into a tier. Only the highest tier crossed on a given date fires (same "strongest signal wins" logic as existing extreme-signal loop).

### Event ID scheme

Tier-based so a worsening event re-fires at a higher tier but not within the same tier:

```
wetbulb_{city_slug}_{YYYY-MM-DD}_tier{N}
```

Example: `wetbulb_Jacobabad_2026-07-12_tier2`. If tomorrow Jacobabad crosses tier 3, `wetbulb_Jacobabad_2026-07-13_tier3` fires; the tier-2 event is in `posted_events` and does not re-fire.

The pattern mirrors `fire_complex_tiers` in `src/data/fire_footprint.py` (line 28) and the cyclone `TierCrossingEvent` pattern in `src/data/cyclones.py` (line 65+), both of which use integer tier indices to prevent re-firing at the same level.

### Category and proposed threshold

```
category: "wet_bulb_extreme"
threshold: 78
```

Rationale: tier-3 events (TW ≥ 35°C) are globally rare and require no additional scoring boost — the bare tier-detection is inherently elite. A threshold of 78 sits between `marine_heatwave` (78) and `all_time_record` (80), which is appropriate: TW extremes are not record-breaks but they are genuinely high-impact. The scoring formula (see Section 8) must ensure:

- Tier 3 (≥ 35°C) always passes (total ≥ 78)
- Tier 2 (≥ 33°C) admits the killer edge — usually passes (total ≈ 76–82), with marginal cases self-filtering

*(Tier 1 / 31°C was cut; the floor is now tier 2 at 33°C, so no tier-1 self-filtering concern applies.)*

### Distinction from existing signals

| Property | Existing records | Wet-bulb extreme |
|---|---|---|
| Trigger | Beats archive max | Crosses absolute TW threshold |
| Variable | Air temperature (TMAX) | Combined heat+humidity (TW) |
| Framing | "Hottest in N years" | "Dangerous to human thermoregulation" |
| Context | Comparative | Physiological |
| Fires in humid tropics w/ no air-temp record? | No | Yes |
| Fires in dry heat wave w/ low humidity? | Possibly | No |

---

## Files to create / modify

### Create

1. **`src/editorial/scoring/wetbulb.py`** — `score_wet_bulb_extreme(tw_c, tier)` scorer
2. **`src/two_bot/intern/wetbulb.py`** — `build_wet_bulb_bundle(ev: WetBulbEvent)` builder
3. **`tests/test_wetbulb.py`** — unit tests for `detect_wet_bulb_extremes()` and scorer
4. **`tests/two_bot/test_wetbulb_intern.py`** — unit tests for `build_wet_bulb_bundle()`

### Modify

5. **`src/data/open_meteo.py`** — add `WetBulbEvent` dataclass; extend `detect_extreme_signals()` to fetch `wet_bulb_temperature_2m_max`; add `wet_bulb_extreme: WetBulbEvent | None` field to `ExtremeSignalBundle`; add `wet_bulb_extreme` to the `any([...])` inclusion guard at line 641
   - Verified: `BASE_URL`, `ARCHIVE_URL` at lines 13–14; `ExtremeSignalBundle` at lines 107–144; `check_extreme_signals_for_cities()` inclusion guard at line 641; `detect_extreme_signals()` at line 370
6. **`src/orchestrator/sources/open_meteo.py`** — extend the per-city loop in `run_extreme_signals()` to detect and process wet-bulb events
   - Verified: `run_extreme_signals()` at line 9; per-city bundle loop at line 47; `_two_bot_bundle_for_extreme_signal()` dispatch at line 338 (defined in `common.py` at line 1104)
7. **`src/orchestrator/common.py`** — import `score_wet_bulb_extreme` and add to `__all__` (line 1471+). No dispatch branch in `_two_bot_bundle_for_extreme_signal()` — the wet-bulb pass calls `_enqueue_story_candidate()` directly and is not in that function's call path.
8. **`src/editorial/scoring/__init__.py`** — add `score_wet_bulb_extreme` wrapper following the `_sync_date()` pattern (verified at lines 33–210); add to `__all__` (line 213+)
9. **`src/editorial/thresholds.py`** — add `ThresholdEntry` for `wet_bulb_extreme` (verified: `THRESHOLDS` dict at line 15; `ThresholdEntry` dataclass at line 8)
10. **`src/editorial/approval.py`** — add `wet_bulb_extreme` to the `manual_only` set (verified: manual block at line 164–187)
11. **`src/two_bot/intern/__init__.py`** — import and export `build_wet_bulb_bundle` (verified: file at line 1–52)
12. **`src/two_bot/prompts/writer_prompt.py`** — add `wet_bulb_extreme` framing block to `WRITER_SYSTEM_PROMPT`
13. **`src/two_bot/prompts/fact_check_prompt.py`** — add wet-bulb WORLD_KNOWLEDGE guidance

---

## Step-by-step implementation (TDD order)

### Step 0 — Verify archive support for `wet_bulb_temperature_2m_max` (BLOCKING pre-step)

**Do this before wiring the variable into the archive request.** The Open-Meteo ARCHIVE endpoint (`https://archive-api.open-meteo.com/v1/archive`) is ERA5-backed and may not expose the same daily variables as the forecast API. A 400 from the archive endpoint would break core air-temp record detection for all cities.

**Smoke-test (one-off, run before implementing Step 1c archive wiring):**

```bash
python -c "
import requests, json
r = requests.get('https://archive-api.open-meteo.com/v1/archive', params={
    'latitude': 24.0, 'longitude': 68.0,
    'start_date': '2024-07-01', 'end_date': '2024-07-03',
    'daily': 'temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max',
    'timezone': 'auto',
})
print('STATUS:', r.status_code)
d = r.json().get('daily', {})
print('Fields returned:', list(d.keys()))
print('wet_bulb values:', d.get('wet_bulb_temperature_2m_max'))
"
```

**Pass criteria:**
- HTTP 200
- `daily.wet_bulb_temperature_2m_max` field is present and contains floats (not all-None)
- `daily.temperature_2m_max` and `daily.temperature_2m_min` are STILL present (regression check — the new var must not displace core fields)

**If the archive endpoint returns 400 or the field is absent:**  Fall back to forecast-only. Drop `wet_bulb_temperature_2m_max` from the archive `daily` param string. Set `archive_max_tw_c = None` unconditionally (the `historical_context` block degrades gracefully when archive fields are absent — see Step 7 bundle builder). The forecast-only path still emits the event; it just won't carry archive-comparison context.

### Step 1 — Add `WetBulbEvent` dataclass, extend `ExtremeSignalBundle`, and extend `detect_extreme_signals()` in the data layer

**File:** `src/data/open_meteo.py`

**1a. Add `WETBULB_TIERS` and `WetBulbEvent` after the existing `RecordStreakEvent` dataclass (after line 103):**

```python
# Wet-bulb extreme tiers (TW thresholds in °C)
WETBULB_TIERS: list[tuple[int, float, str]] = [
    # (tier_index, tw_threshold_c, tier_label)
    # Tier 1 (31°C / "danger") is NOT emitted — floor is 33°C (tier 2).
    (3, 35.0, "tier_3"),
    (2, 33.0, "extreme"),
]

@dataclass
class WetBulbEvent:
    city: str
    country: str
    daily_max_tw_c: float           # forecast-model daily-max TW (Open-Meteo wet_bulb_temperature_2m_max)
    tier: int                       # 1, 2, or 3
    tier_label: str                 # "danger" | "extreme" | "tier_3"
    tier_threshold_c: float         # the threshold crossed (31, 33, or 35)
    event_id: str                   # "wetbulb_{city_slug}_{date}_tier{N}"
    signal_date: date | None = None
    lat: float | None = None
    lon: float | None = None
    # Optional: archive historical max TW — only populated if archive data was fetched
    archive_max_tw_c: float | None = None
    archive_max_year: int | None = None
    archive_years: int | None = None
```

Note: tier-3 label is `"tier_3"` not `"survivability_limit"`. The physiological-limit framing is supplied only in the `tw_explainer` bundle fact; it must not appear as a tweet-facing tier label (evidence-safety constraint — see fact-check section).

**1b. Add `wet_bulb_extreme` field to `ExtremeSignalBundle` (at line 107, after the last existing optional field at line 144):**

```python
# Wet-bulb signal (optional — populated by detect_extreme_signals when TW data available)
wet_bulb_extreme: "WetBulbEvent | None" = None
```

This is the inclusion-gate fix. The `any([...])` guard at line 641 must also include `bundle.wet_bulb_extreme`:

```python
# src/data/open_meteo.py:641 — existing guard, add wet_bulb_extreme
if any([
    bundle.calendar_date_high, bundle.calendar_date_low,
    bundle.all_time_high, bundle.all_time_low,
    bundle.monthly_high, bundle.monthly_low,
    bundle.anomaly_hot, bundle.anomaly_cold,
    bundle.wet_bulb_extreme,   # ← ADD: wet-bulb-only cities must not be dropped
]):
    bundles.append(bundle)
```

Without this, a city that hits a TW threshold but sets no air-temp record is silently filtered before `run_extreme_signals()` sees it.

**Inclusion-gate downstream blast-radius check (verify before merging Step 1b):** Adding `wet_bulb_extreme` to the `any([...])` guard at line 641 increases the set of bundles that reach `run_extreme_signals()`. Confirm that this does NOT perturb country-record aggregation or simultaneous-records detection. Simultaneous-records detection counts only `calendar_date_high` events (verified: it reads `bundle.calendar_date_high`, not the full gate-survivor list), so wet-bulb-only bundles should not affect it. Add a regression assertion to the orchestrator test: a bundle with only `wet_bulb_extreme` set must NOT appear in the country_records aggregation or the simultaneous-records output.

**1c. Extend `detect_extreme_signals()` (line 370) to fetch `wet_bulb_temperature_2m_max`:**

Add `wet_bulb_temperature_2m_max` to the `daily` param string of BOTH existing requests (no new HTTP calls):

```python
# Forecast request (around line 395) — was:
"daily": "temperature_2m_max,temperature_2m_min",
# Becomes:
"daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
```

```python
# Archive request (around line 419) — was:
"daily": "temperature_2m_max,temperature_2m_min",
# Becomes:
"daily": "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max",
```

After reading the returned daily data, compute the wet-bulb extreme:

```python
# After existing bundle construction (around line 438), before the historical-stats loop:
today_tw_max = (today_data.get("wet_bulb_temperature_2m_max") or [None])[0]
hist_tw_values = hist_data.get("wet_bulb_temperature_2m_max", [])

if today_tw_max is not None:
    # Find highest tier crossed
    wb_event = None
    for tier_index, threshold_c, tier_label in WETBULB_TIERS:
        if today_tw_max >= threshold_c:
            today_iso = today.isoformat()
            city_slug = city.replace(" ", "_")
            # Archive historical max TW (for optional context framing)
            valid_hist_tw = [(v, d) for v, d in zip(hist_tw_values, dates) if v is not None]
            arch_max_tw = None
            arch_max_year = None
            if valid_hist_tw:
                arch_max_tw, arch_max_date = max(valid_hist_tw, key=lambda x: x[0])
                arch_max_year = int(arch_max_date[:4])
            wb_event = WetBulbEvent(
                city=city,
                country=country,
                daily_max_tw_c=today_tw_max,
                tier=tier_index,
                tier_label=tier_label,
                tier_threshold_c=threshold_c,
                event_id=f"wetbulb_{city_slug}_{today_iso}_tier{tier_index}",
                signal_date=today,
                lat=lat,
                lon=lon,
                archive_max_tw_c=arch_max_tw,
                archive_max_year=arch_max_year,
                archive_years=archive_years,
            )
            break  # WETBULB_TIERS is sorted highest-first; stop at highest crossed
    bundle.wet_bulb_extreme = wb_event
```

This approach uses the already-fetched `hist_data` to populate `archive_max_tw_c` and `archive_max_year` at zero extra cost — enabling "highest forecast TW vs. archive max" comparisons in the bundle without a separate archive call. The writer must still label the today value as a forecast-model reading (see fact-check section).

### Step 2 — Write unit tests for the wet-bulb logic inside `detect_extreme_signals()` (`tests/test_wetbulb.py`)

Because wet-bulb detection is now folded into `detect_extreme_signals()`, tests mock the two-request response shape (forecast + archive daily). Test these cases:

- `detect_extreme_signals()` with mocked forecast returning `wet_bulb_temperature_2m_max=[35.5]` → `bundle.wet_bulb_extreme.tier == 3`
- `wet_bulb_temperature_2m_max=[33.2]` → tier 2
- `wet_bulb_temperature_2m_max=[31.0]` → `bundle.wet_bulb_extreme is None` (tier 1 not emitted — test name: `test_tier1_not_emitted`)
- `wet_bulb_temperature_2m_max=[32.9]` → `bundle.wet_bulb_extreme is None` (below tier-2 floor of 33°C)
- `wet_bulb_temperature_2m_max=[None]` → `bundle.wet_bulb_extreme is None`
- `wet_bulb_temperature_2m_max` key absent from response → `bundle.wet_bulb_extreme is None` (no crash)
- Archive provides historical TW values → `bundle.wet_bulb_extreme.archive_max_tw_c` populated
- Archive provides no TW values → `archive_max_tw_c is None`, event still fires

Mock pattern (mirror `test_open_meteo.py` style using `unittest.mock.patch`):

```python
@patch("src.data.open_meteo.requests.get")
def test_tier3_wb_fires(mock_get):
    forecast_resp = MagicMock()
    forecast_resp.json.return_value = {
        "daily": {
            "temperature_2m_max": [38.0], "temperature_2m_min": [28.0],
            "wet_bulb_temperature_2m_max": [35.5],
            "time": [date.today().isoformat()],
        }
    }
    forecast_resp.raise_for_status = lambda: None
    archive_resp = MagicMock()
    archive_resp.json.return_value = {
        "daily": {
            "temperature_2m_max": [40.0], "temperature_2m_min": [29.0],
            "wet_bulb_temperature_2m_max": [34.8],
            "time": ["2023-06-15"],
        }
    }
    archive_resp.raise_for_status = lambda: None
    mock_get.side_effect = [forecast_resp, archive_resp]
    bundle = detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan")
    assert bundle is not None
    assert bundle.wet_bulb_extreme is not None
    assert bundle.wet_bulb_extreme.tier == 3
    assert bundle.wet_bulb_extreme.daily_max_tw_c == 35.5
    assert bundle.wet_bulb_extreme.archive_max_tw_c == 34.8
    assert bundle.wet_bulb_extreme.archive_max_year == 2023
    assert bundle.wet_bulb_extreme.event_id == f"wetbulb_Jacobabad_{date.today().isoformat()}_tier3"
```

Also add a test verifying the inclusion-gate fix: a bundle with only `wet_bulb_extreme` set (all air-temp signals None) must appear in the `bundles` list returned by `check_extreme_signals_for_cities()`.

### Step 3 — Add `ThresholdEntry` to `src/editorial/thresholds.py`

At line 206 (before the closing `}`), add:

```python
"wet_bulb_extreme": ThresholdEntry(
    "wet_bulb_extreme",
    78,
    "Absolute heat-stress danger (TW ≥ 31–35°C). Threshold 78 sits between "
    "marine_heatwave (78) and all_time_record (80); tier-3 events always pass, "
    "tier-1 events self-filter via the scoring formula.",
),
```

### Step 4 — Write `score_wet_bulb_extreme()` in `src/editorial/scoring/wetbulb.py`

```python
"""Wet-bulb extreme editorial scoring."""
from __future__ import annotations

from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold

# Tier-indexed base-severity boosts (additive over the TW absolute level)
# NOTE: tier 1 keys are present for defensive clamping only — tier 1 is never emitted
# by WETBULB_TIERS (floor is tier 2 / 33°C). Do not rely on {1: ...} values in tests.
_TIER_SEVERITY_BOOST = {1: 0, 2: 8, 3: 20}
_TIER_NOVELTY_BOOST  = {1: 0, 2: 6, 3: 14}
_TIER_SHARE_BOOST    = {1: 0, 2: 6, 3: 16}


def score_wet_bulb_extreme(
    tw_c: float,
    tier: int,
) -> EditorialScore:
    """Score a wet-bulb extreme event.

    Severity baseline is anchored to the absolute TW value plus a tier bonus.
    Tier 3 (≥35°C) is physiologically singular and should always pass.
    Tier 2 (≥33°C) admits the killer edge; marginal cases self-filter.
    """
    tier = max(1, min(3, tier))  # defensive clamp
    tier_boost = _TIER_SEVERITY_BOOST[tier]
    novelty_boost = _TIER_NOVELTY_BOOST[tier]
    share_boost = _TIER_SHARE_BOOST[tier]

    # TW of 31°C → severity ~66; TW of 35°C → severity ~90+
    severity    = 60 + (tw_c - 31.0) * 3.5 + tier_boost
    novelty     = 74 + novelty_boost
    timeliness  = 94   # forecast data, same-day
    confidence  = 80   # model-derived, not station-observed
    shareability = 74 + share_boost

    reasons = [
        f"wet-bulb tier {tier}: TW {tw_c:.1f}°C",
    ]
    if tier == 3:
        reasons.append("tier-3 threshold (≥35°C TW) — globally rare")
    if tier >= 2 and tw_c >= 33.0:
        reasons.append("sustained exposure dangerous even for fit adults")

    return _build_score(
        "wet_bulb_extreme",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=10,   # human-safety adjacent; keep manual review
        threshold=get_threshold("wet_bulb_extreme"),
        reasons=reasons,
    )
```

**Verify the math at key anchor points:**

- TW=33.0 (tier 2): `severity=60+(2.0)×3.5+8=75`, `novelty=80`, `total≈(0.28×75+0.24×80+0.16×94+0.16×80+0.16×80)−2 = (21+19.2+15+12.8+12.8)−2 = 78.8` → total ≈ **79** (passes — admits killer edge; marginal tier-2 values self-filter)
- TW=35.0 (tier 3): `severity=60+(4.0)×3.5+20=94`, `novelty=88`, `total≈(0.28×94+0.24×88+0.16×94+0.16×80+0.16×90)−2 = (26.3+21.1+15+12.8+14.4)−2 = 87.6` → total ≈ **88** (easily passes — correct)

*(Tier-1 anchor math removed — tier 1 is not emitted.)*

(All values use `_clamp()` at 0–100 per `src/editorial/scoring/_shared.py:4`.)

### Step 5 — Write tests for `score_wet_bulb_extreme()` (in `tests/test_wetbulb.py` or `tests/test_editorial_scoring.py`)

```python
def test_tier3_always_passes():
    score = score_wet_bulb_extreme(35.0, tier=3)
    assert score.passes
    assert score.total >= 78

def test_tier2_passes():
    score = score_wet_bulb_extreme(33.0, tier=2)
    assert score.passes

def test_tier1_not_emitted():
    # Tier 1 (31°C) is not emitted by WETBULB_TIERS; assert detect produces None
    # (scorer test: verifying a tier=1 score would fail, but detection never reaches it)
    bundle = detect_extreme_signals(...)  # mock returns wet_bulb_temperature_2m_max=[31.0]
    assert bundle.wet_bulb_extreme is None

def test_category_label():
    score = score_wet_bulb_extreme(35.0, tier=3)
    assert score.category == "wet_bulb_extreme"
```

### Step 6 — Add `score_wet_bulb_extreme` to `src/editorial/scoring/__init__.py`

Following the exact pattern at lines 33–35:

```python
from . import wetbulb as _wetbulb

def score_wet_bulb_extreme(*args: Any, **kwargs: Any) -> EditorialScore:
    return _wetbulb.score_wet_bulb_extreme(*args, **kwargs)
```

Add `"score_wet_bulb_extreme"` to `__all__` (line 213+).

### Step 7 — Build `build_wet_bulb_bundle()` in `src/two_bot/intern/wetbulb.py`

```python
"""Wet-bulb extreme two-bot intern builder."""
from __future__ import annotations

from dataclasses import asdict
from src.data.open_meteo import WetBulbEvent
from src.two_bot.types import StoryBundle
from ._shared import _audience_unit_facts, _c_to_f, _climate_context_facts, _resolve_when


_TIER_LABEL_DISPLAY = {
    1: "danger (≥31°C wet-bulb)",
    2: "extreme (≥33°C wet-bulb)",
    3: "≥35°C wet-bulb (tier 3)",
}


def build_wet_bulb_bundle(ev: WetBulbEvent) -> StoryBundle:
    """Assemble a StoryBundle for a wet-bulb extreme signal."""
    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    tw_f = _c_to_f(ev.daily_max_tw_c)
    threshold_f = _c_to_f(ev.tier_threshold_c)

    current_facts = [
        {"label": "city", "value": ev.city},
        {"label": "country", "value": ev.country},
        {"label": "daily_max_tw_c", "value": ev.daily_max_tw_c},
        {"label": "daily_max_tw_f", "value": tw_f},
        {"label": "tier", "value": ev.tier},
        {"label": "tier_label", "value": ev.tier_label},
        {"label": "tier_threshold_c", "value": ev.tier_threshold_c},
        {"label": "tier_threshold_f", "value": threshold_f},
        {"label": "tier_display", "value": _TIER_LABEL_DISPLAY.get(ev.tier, ev.tier_label)},
        # Human-physiology context facts for writer
        {"label": "tw_explainer", "value": (
            "Wet-bulb temperature measures the body's ability to cool by sweating. "
            "Above ~35°C TW, even healthy adults in shade cannot shed heat faster "
            "than they produce it; core temperature rises without limit."
        )},
        *_audience_unit_facts(ev.country),
        *_climate_context_facts(ev.lat, ev.lon, category="high"),
    ]

    historical_context: dict = {}
    if ev.archive_max_tw_c is not None and ev.archive_years is not None:
        historical_context = {
            "archive_max_tw_c": ev.archive_max_tw_c,
            "archive_max_year": ev.archive_max_year,
            "archive_years": ev.archive_years,
            "scope": "wet_bulb_archive_max",
        }

    return StoryBundle(
        signal_kind="wet_bulb_extreme",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": "daily_max_tw_c",
            "value": ev.daily_max_tw_c,
            "unit": "C_wetbulb",
            "value_f": tw_f,
        },
        current_facts=current_facts,
        historical_context=historical_context,
        raw_signal_dump=asdict(ev),
    )
```

### Step 8 — Write tests for `build_wet_bulb_bundle()` (`tests/two_bot/test_wetbulb_intern.py`)

```python
def test_build_wet_bulb_bundle_tier3():
    ev = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=35.5,
        tier=3,
        tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
        signal_date=date(2026, 7, 12),
    )
    bundle = build_wet_bulb_bundle(ev)
    assert bundle.signal_kind == "wet_bulb_extreme"
    assert bundle.headline_metric["value"] == 35.5
    assert bundle.headline_metric["unit"] == "C_wetbulb"
    assert any(f["label"] == "tier" and f["value"] == 3 for f in bundle.current_facts)
    assert any(f["label"] == "tw_explainer" for f in bundle.current_facts)
    assert bundle.historical_context == {}  # no archive data supplied

def test_build_wet_bulb_bundle_with_archive():
    ev = WetBulbEvent(
        city="Jacobabad", country="Pakistan",
        daily_max_tw_c=35.5, tier=3, tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
        archive_max_tw_c=34.8, archive_max_year=2023, archive_years=30,
    )
    bundle = build_wet_bulb_bundle(ev)
    assert bundle.historical_context["archive_max_tw_c"] == 34.8
    assert bundle.historical_context["archive_years"] == 30
```

### Step 9 — Export from `src/two_bot/intern/__init__.py`

Add to the import line at line 6 (new import from `wetbulb.py`):

```python
from .wetbulb import build_wet_bulb_bundle
```

Add `"build_wet_bulb_bundle"` to `__all__` (line 15+).

### Step 10 — Wire into `src/orchestrator/sources/open_meteo.py`

The wet-bulb scan runs as a **second pass** over the same `bundles` list already returned by `check_extreme_signals_for_cities()`. Because `wet_bulb_extreme` is now a field on `ExtremeSignalBundle` (Step 1b), and the inclusion guard now allows wet-bulb-only bundles (Step 1b), no additional HTTP calls are needed. Add a loop immediately after the existing bundle loop and before the simultaneous-records detection block (after line ~466):

```python
# --- Wet-bulb extreme pass ---
# Reads bundle.wet_bulb_extreme populated by detect_extreme_signals().
# No additional HTTP calls — wet_bulb_temperature_2m_max was already
# fetched as part of the same daily request in Step 1c.
# Only fires when THEHEAT_WETBULB_ENABLED=1 to allow phased rollout.
if os.environ.get("THEHEAT_WETBULB_ENABLED", "1") == "1":
    from src.two_bot.intern.wetbulb import build_wet_bulb_bundle
    from src.editorial.scoring import score_wet_bulb_extreme

    for bundle in bundles:
        wb_ev = bundle.wet_bulb_extreme
        if wb_ev is None:
            continue
        if state.is_duplicate(bot_state, wb_ev.event_id):
            continue
        wb_score = score_wet_bulb_extreme(wb_ev.daily_max_tw_c, wb_ev.tier)  # no city param
        if not _should_draft(wb_score, wb_ev.event_id):
            continue
        wb_bundle = build_wet_bulb_bundle(wb_ev)
        wb_headline = (
            f"{wb_ev.city}: forecast wet-bulb max {wb_ev.daily_max_tw_c:.1f}°C "
            f"(tier {wb_ev.tier})"
        )
        wb_ctx = _review_context(
            source="Open-Meteo daily (wet_bulb_temperature_2m_max)",
            source_key="wetbulb_extreme",
            headline=wb_headline,
            current_run=current_run,
            facts=[
                _fact("City", wb_ev.city),
                _fact("Country", wb_ev.country),
                _fact("Daily-max TW (forecast)", f"{wb_ev.daily_max_tw_c:.1f}°C"),
                _fact("Tier", str(wb_ev.tier)),
                _fact("Tier threshold", f"≥{wb_ev.tier_threshold_c:.0f}°C TW"),
                _fact("Archive max TW", f"{wb_ev.archive_max_tw_c:.1f}°C ({wb_ev.archive_max_year})"
                      if wb_ev.archive_max_tw_c is not None else "n/a"),
            ],
        )
        _enqueue_story_candidate(
            bot_state,
            bundle=wb_bundle,
            score=wb_score,
            source="wetbulb_extreme",
            legacy_type="wet_bulb_extreme",
            event_id=wb_ev.event_id,
            review_context=wb_ctx,
            city=wb_ev.city,
            tweet_date=date.today().isoformat(),
            cooldown_exempt=(wb_ev.tier >= 3),  # tier-3 bypasses city cooldown
        )
```

**Why iterate `bundles` not `all_readings`:** `bundles` already went through the inclusion guard (now including `wet_bulb_extreme`), so it contains the complete set of cities with any signal. `all_readings` would include cities with no signals at all, which is wasteful.

**Dual-candidate-per-city:** A city that sets an air-temperature record AND crosses a wet-bulb tier in the same cycle will emit TWO triage candidates — one from the main extreme-signal loop (air-temp record) and one from this wet-bulb pass. This is intentional: they are distinct signal categories and distinct story types. Both are bounded by the per-category and global triage caps, so neither floods the queue.

### Step 11 — Import `score_wet_bulb_extreme` in `src/orchestrator/common.py`

Add `score_wet_bulb_extreme` to the imports at line 44+ and to `__all__` at line 1471+.

**No dispatch branch needed.** The wet-bulb scan (Step 10) calls `_enqueue_story_candidate()` directly — it is NOT routed through `_two_bot_bundle_for_extreme_signal()` at line 1104. Adding a `"wet_bulb_extreme"` branch there would be dead code: the path `detect → bundle → _two_bot_bundle_for_extreme_signal()` is never taken for wet-bulb events (YAGNI; adding it now creates misleading indirection). If a future refactor merges the wet-bulb pass into the main extreme-signal loop, add the branch then.

### Step 12 — Add `manual_only` approval policy

In `src/editorial/approval.py`, add `"wet_bulb_extreme"` to the `manual_only` set at line 164–187:

```python
if (
    tweet_type in {
        "fire",
        "fire_footprint",
        ...
        "wet_bulb_extreme",   # ← add here
    }
    or tweet_type.startswith("cyclone_")
):
    return ApprovalPolicy(
        key="manual_only",
        mode="manual_only",
        recommended_delay_minutes=None,
        can_auto_approve=False,
        reason="Potential human-impact event. Keep explicit human approval in the loop.",
    )
```

---

## Bundle + writer-prompt changes

### `build_wet_bulb_bundle` shape (summary)

```
StoryBundle(
  signal_kind = "wet_bulb_extreme"
  where       = "Jacobabad, Pakistan"
  when        = "2026-07-12"
  event_id    = "wetbulb_Jacobabad_2026-07-12_tier3"
  headline_metric = {
      "label": "daily_max_tw_c",
      "value": 35.5,          # exact from Open-Meteo daily max — cite verbatim
      "unit": "C_wetbulb",
      "value_f": 96,          # _c_to_f(35.5) = round(95.9) = 96
  }
  current_facts = [
      {"label": "city", ...},
      {"label": "country", ...},
      {"label": "daily_max_tw_c", "value": 35.5},
      {"label": "daily_max_tw_f", "value": 96},
      {"label": "tier", "value": 3},
      {"label": "tier_label", "value": "tier_3"},
      {"label": "tier_threshold_c", "value": 35.0},
      {"label": "tier_threshold_f", "value": 95},
      {"label": "tier_display", "value": "≥35°C wet-bulb (tier 3)"},
      {"label": "tw_explainer", "value": "Wet-bulb temperature measures..."},
      {"label": "audience_unit", "value": "celsius_first"},   # or fahrenheit_first for US
      # optional climate_context facts from _climate_context_facts()
  ]
  historical_context = {
      # present when archive returns wet_bulb_temperature_2m_max values
      "archive_max_tw_c": 34.8,
      "archive_max_year": 2023,
      "archive_years": 30,
      "scope": "wet_bulb_archive_max",
  }
)
```

### `src/two_bot/intern/__init__.py` export

```python
from .wetbulb import build_wet_bulb_bundle
# add "build_wet_bulb_bundle" to __all__
```

### `_two_bot_bundle_for_extreme_signal()` wiring

Not required. The wet-bulb loop (Step 10) builds and submits the bundle directly via `_enqueue_story_candidate()`. The dispatch function is not in the call path and no branch is added (YAGNI — see Step 11).

### Writer-prompt additions (`src/two_bot/prompts/writer_prompt.py`)

Add a new `wet_bulb_extreme` block to the `WRITER_SYSTEM_PROMPT` (in the `signal_kind` / `current_facts` conventions section, before the `# APPROVED EXEMPLARS` heading):

```
## Wet-bulb extreme bundles (signal_kind = "wet_bulb_extreme")

**What wet-bulb temperature is (explain this to the reader, plainly):** Wet-bulb temperature (TW) is what a thermometer reads when its bulb is wrapped in a wet cloth and exposed to airflow. It measures the air's ability to cool a sweating surface. The body cools itself by evaporating sweat; if TW is high, evaporation slows or stops. The physiological ceiling where a healthy resting adult in shade can no longer shed body heat faster than they produce it is approximately 35°C TW. Above that, core temperature rises — not because it's "hot", but because the air is saturated enough that sweat cannot evaporate.

**Key bundle fields:**
- `daily_max_tw_c` — the Open-Meteo MODEL forecast of peak TW for the day. This is a model output, NOT a station observation. CITE VERBATIM. Do not round, convert, or recompute. You MUST write "forecast" or "model" when referencing this value — e.g., "forecast wet-bulb peak of 35.5°C".
- `daily_max_tw_f` — pre-computed Fahrenheit, integer. Use verbatim for US-audience tweets.
- `tier` — 1 (danger, ≥31°C), 2 (extreme, ≥33°C), 3 (≥35°C). The tier-3 `tier_label` field is bundle-internal only. DO NOT use the words "survivability limit" in a tweet. Write "the point where sweat evaporation fails" or reference the `tw_explainer` field.
- `tier_threshold_c` — the specific threshold crossed. Cite verbatim if using in tweet.
- `tw_explainer` — supplied physiological framing. You may paraphrase; do not invent new physiology.
- `archive_max_tw_c` / `archive_years` / `archive_max_year` — if present in `historical_context`, you may write "the highest wet-bulb reading in the {archive_years}-year model archive" or "above the {archive_years}-year maximum of {archive_max_tw_c}°C". If `historical_context` is empty `{}`, do NOT claim any record — write "forecast model peak TW of X°C" only.

**Voice discipline:** explain the mechanism plainly (the sweat-evaporation ceiling), give the number, stop. Do not moralize. Do not alarm. The data is alarming enough on its own. Never use "lethal," "death," "deadly," "kill," "fatal," or "survivability limit" — these editorialize and exceed what the bundle data establishes. The mechanism speaks for itself.

**Evidence discipline:** the `daily_max_tw_c` value is a forecast model output. It is not an observed station reading. Do not frame it as a confirmed observation. Always use "forecast" or "model" when citing it. The archive comparison (if present) is also model-derived — phrase as "in {archive_years} years of model data", not "in recorded history."
```

### Fact-checker additions (`src/two_bot/prompts/fact_check_prompt.py`)

Add to the WORLD_KNOWLEDGE section (after the existing bullet d on basic oceanographic mechanism):

```
**f) Wet-bulb physiology (established threshold science).** The ~35°C TW physiological ceiling for healthy adults is documented in Sherwood & Huber (2010, PNAS) and subsequent literature (Raymond et al. 2020, Science Advances). ACCEPT: "above the point where the body can cool by sweating," "the evaporative cooling limit," "where heat dissipation fails." Do NOT accept specific numbers for mortality time-windows, LD50 figures, or specific-population claims (children, elderly, athletes) — these are population-specific and not in the bundle. The bundle-supplied `tw_explainer` field IS BUNDLE_FACT and must match verbatim if quoted; paraphrase is WORLD_KNOWLEDGE.

**g) Wet-bulb evidence grade — FORECAST MODEL, not observation.** The `daily_max_tw_c` in wet-bulb extreme bundles is Open-Meteo's `wet_bulb_temperature_2m_max` daily variable — a numerical weather model output, NOT a station-observed reading. REJECT any draft that: (a) frames the TW value as a station observation or confirmed measurement; (b) uses the phrase "survivability limit" as a factual claim; (c) claims "hottest wet-bulb in N years" without `historical_context` carrying `archive_max_tw_c` and `archive_years`; (d) states any human-health conclusion (fatality, incapacitation, time-to-heat-stroke) beyond what the `tw_explainer` field asserts — the bundle does not carry population-health outcome data. The `archive_max_tw_c` is also model-derived (ERA5/Open-Meteo archive); frame as "in the model archive" or "over the {archive_years}-year record", not "ever observed."
```

---

## Scoring + threshold

### Score function signature

```python
# src/editorial/scoring/wetbulb.py
def score_wet_bulb_extreme(
    tw_c: float,
    tier: int,
) -> EditorialScore:
```

*(The `city: str = ""` reserved param was removed — tier-1 city-weighting was cut along with tier 1. No city param needed for tier-2/3 scoring.)*

### Factor reasoning

| Factor | Value range | Rationale |
|--------|------------|-----------|
| `severity` | 60–100 | Anchored to TW absolute value; tier bonus lifts tier-3 into elite range |
| `novelty` | 74–88 | High: absolutely new signal type; tier-3 events are globally rare |
| `timeliness` | 94 | Forecast data, same-day |
| `confidence` | 80 | Open-Meteo model-derived TW (not station-observed); slightly lower than archive-confirmed readings |
| `shareability` | 74–90 | Survivability-limit tier has maximum viral potential; tier-1 is merely informative |
| `sensitivity` | 10 | Human-safety adjacent; same sensitivity as `score_anomaly()` and cyclone events |

### THRESHOLDS entry

```python
# src/editorial/thresholds.py — append before closing brace
"wet_bulb_extreme": ThresholdEntry(
    "wet_bulb_extreme",
    78,
    "Absolute heat-stress danger (TW ≥ 31–35°C). Threshold 78 sits between "
    "marine_heatwave (78) and all_time_record (80); tier-3 events always pass, "
    "tier-1 events self-filter via the scoring formula.",
),
```

---

## State / caps / cooldowns

### Deduplication

Uses the existing `state.is_duplicate(bot_state, event_id)` / `state.record_event(bot_state, event_id)` mechanism (verified: `src/state.py:1055` and `:1059`). `state.record_event()` is called at `src/orchestrator/common.py:1454` inside `_drain_and_write_triage_queue()`, only after a draft actually succeeds — dedup is recorded post-draft-success, not at detection time.

The tier-stamped `event_id` scheme (`wetbulb_{city}_{date}_tier{N}`) ensures:

- Same city, same date, same tier → duplicate suppressed (event_id already in `posted_events`)
- Same city, same date, higher tier → fires (new event_id with higher tier index)
- Same city, next day → fires (new date in event_id)
- Failed-writer candidates: `state.record_event()` never fires → event_id not recorded → will retry on next cycle (correct behaviour; no ghost suppression)

There is no `already_seen_tiers` parameter on `detect_extreme_signals()`. Tier-level dedup is handled entirely by the event_id + `posted_events` mechanism. The function is not aware of what has been drafted.

### Annual cap

No annual cap in v1. Wet-bulb tier-3 events are genuinely rare (single digits globally per year); tier-1/2 in tropical cities are more frequent but geographically concentrated. Monitor the first month of production; add a cap if noise warrants.

### City cooldown

Tier-1 and tier-2 events: subject to the standard `CITY_COOLDOWN_DAYS=3` gate (verified: `src/orchestrator/common.py:93`). Set `cooldown_exempt=False`.

Tier-3 events: `cooldown_exempt=True` — any city hitting the survivability limit should always fire regardless of recent posting history, matching the `all_time_high`/`all_time_low` elite-bypass pattern (verified: `src/orchestrator/sources/open_meteo.py:323`).

### No `DEFAULT_STATE` additions required

Wet-bulb deduplication rides `posted_events` (existing). No new state key is needed in `src/state.py` for v1.

### Env-var kill switch

`THEHEAT_WETBULB_ENABLED=0` silences the entire scan without removing code. Default is `1` (on). `THEHEAT_WETBULB_MAX_CITIES=50` limits the per-cycle city count to cap latency (50 cities × ~1 HTTP call = ~50 seconds at 1 s/call).

---

## Approval policy

`wet_bulb_extreme` → `manual_only`. Set in `src/editorial/approval.py` (line 164–187). No auto-approve under any condition because:

1. The event is life-safety adjacent (like cyclone, fire, flood).
2. The data is model-derived, not station-observed — worth human review before posting.
3. The writer's wet-bulb framing is new and unproven at scale; human oversight catches voice drift.

The approval policy is set via `recommend_approval_policy()` called in `save_draft()` at `src/orchestrator/common.py:1058`. The `tweet_type` passed is `legacy_type="wet_bulb_extreme"` — it must match the string in `approval.py`'s `manual_only` set exactly.

---

## Test plan

### Unit tests (`tests/test_wetbulb.py`)

All HTTP mocked with `unittest.mock.patch("src.data.open_meteo.requests.get")`.

1. **Tier detection (all 4 tiers including below-floor)** — see Step 2 above
2. **Inclusion-gate fix** — bundle with only `wet_bulb_extreme` set, all air-temp fields None → appears in `bundles` list from `check_extreme_signals_for_cities()` (test name: `test_wb_only_bundle_not_dropped`)
3. **API error tolerance** — `requests.RequestException` → `bundle.wet_bulb_extreme is None`, no crash, air-temp signals unaffected
4. **All-None daily TW values** → `bundle.wet_bulb_extreme is None`
5. **`wet_bulb_temperature_2m_max` key absent from response** → `bundle.wet_bulb_extreme is None` (graceful degradation, no KeyError)
6. **`event_id` format** — verify `wetbulb_{city_slug}_{date}_tier{N}` exactly
7. **Archive max TW populated from archive response** — when archive returns `wet_bulb_temperature_2m_max` values, `bundle.wet_bulb_extreme.archive_max_tw_c` and `archive_max_year` are set
8. **Archive max TW absent** — when archive returns empty or None TW list, event still fires with `archive_max_tw_c is None`

### Scorer tests (`tests/test_wetbulb.py` or `tests/test_editorial_scoring.py`)

8. Tier-3 score always passes (total ≥ 78)
9. Tier-2 score passes (TW=33.0)
10. Tier-1 score fails (TW=31.0, total < 78)
11. `score.category == "wet_bulb_extreme"`
12. `score.threshold == 78`
13. Sensitivity = 10 (confirm penalty applied)

### Bundle tests (`tests/two_bot/test_wetbulb_intern.py`)

14. `signal_kind == "wet_bulb_extreme"`
15. `headline_metric["unit"] == "C_wetbulb"`
16. `tw_explainer` fact present in `current_facts`
17. `audience_unit` fact present
18. `historical_context == {}` when no archive data
19. `historical_context` populated when archive fields set
20. `where` is `"city, country"` format

### Orchestrator integration test (add to `tests/test_open_meteo_orchestrator.py`)

21. Mock `detect_extreme_signals()` to return a bundle with `wet_bulb_extreme` set to a tier-3 `WetBulbEvent`; verify `_triage_queue` receives one `TriageCandidateBundle` with `legacy_type="wet_bulb_extreme"` and `cooldown_exempt=True`
22. Mock bundle with `wet_bulb_extreme=None`; verify no wet-bulb candidate queued
23. `THEHEAT_WETBULB_ENABLED=0` env → no wet-bulb candidates queued even when `wet_bulb_extreme` is set on bundle

### Threshold test (add assertion to `tests/test_thresholds.py`)

24. `get_threshold("wet_bulb_extreme") == 78`

### Approval test (add to `tests/test_editorial_approval.py`)

25. `recommend_approval_policy("wet_bulb_extreme", ...)` returns `mode == "manual_only"`

---

## Risks / open questions / design forks

### ~~Fork 1 — Archive fetch: hourly resolution is prohibitive~~ (RESOLVED — eliminated)

This fork is eliminated. `wet_bulb_temperature_2m_max` is a native daily variable, not hourly. Both the forecast and archive values are fetched at zero additional cost by extending the existing `daily` param string in `detect_extreme_signals()`. The `historical_context` block in the bundle is populated from the archive data already returned — no separate API call, no 262k-values concern. See Step 1c.

### ~~Fork 2 — Should tier-1 exist?~~ (RESOLVED — cut)

Tier-1 (TW ≥ 31°C / "danger") is removed. The floor is 33°C (tier 2). A tier-1 event in Mumbai during July monsoon is not extraordinary; it would fire too frequently and dilute the feed. The scoring math confirmed tier-1 would fail threshold 78 anyway (total ≈ 72). See NOT-in-scope.

The tier values that remain (33/35°C) are based on published literature (Sherwood & Huber 2010, Raymond et al. 2020). A review of recent global observations suggests:

- TW ≥ 35°C has been measured only a handful of times (Jacobabad, Pakistan, 2005 and 2010; parts of the Persian Gulf coast). Tier-3 is genuinely elite.
- TW ≥ 33°C is "rare but not exceptional" in the Persian Gulf and South Asia during peak monsoon.

### Fork 3 — Apparent temperature as secondary bundle fact

Open-Meteo also exposes `apparent_temperature` (daily max available) — the "feels like" reading combining heat + humidity + wind. This is consumer-friendly (everyone understands "feels like 115°F") but scientifically distinct from TW. Including it as a secondary bundle fact (`apparent_temperature_c`, `apparent_temperature_f`) lets the writer add human-scale context ("the air felt like 52°C / 126°F") without conflating it with the wet-bulb mechanism.

**Risk:** writer might lead with apparent_temperature (which sounds more dramatic) and bury the TW (which is the actual signal). The bundle-field naming and writer-prompt guidance must prevent this.

### Fork 4 — Fact-checker TW number classification and evidence grade

The exact TW value (`daily_max_tw_c`) is Open-Meteo forecast model output — not an observed station reading. This distinction matters for tweet framing. The fact-checker classification:

- `"forecast wet-bulb peak of 35.5°C"` → BUNDLE_FACT (value must match exactly; "forecast" label required)
- `"35.5°C TW"` with no "forecast"/"model" qualifier → REJECT (missing evidence grade)
- `"above the evaporative cooling limit"` → WORLD_KNOWLEDGE (accept)
- `"above the point where sweat evaporation fails"` → WORLD_KNOWLEDGE (accept)
- `"survivability limit"` as a factual claim → REJECT (not in bundle; exceeds evidence grade)
- `"the highest wet-bulb in Jacobabad's history"` → UNVERIFIABLE (no station data)
- `"highest in the 30-year model archive"` → BUNDLE_FACT if `historical_context.archive_years == 30` and `archive_max_tw_c` present; REJECT if `historical_context` is `{}`
- `"hottest wet-bulb in N years"` with no archive context → REJECT (see fact-check bullet g)

The fact-checker addition in the writer-prompt section (bullet g above) makes these constraints explicit and blocking.

### Fork 5 — Per-city cooldown for high-humidity cities

During monsoon season, cities like Dhaka or Mumbai may hit tier-1 TW repeatedly across many consecutive days. The 3-day city cooldown would suppress these. Is that correct? Options:

A. Standard cooldown applies to all tiers (current plan for tier-1/2, with tier-3 exempt).
B. Cooldown suppresses only same-tier events (different from the event_id scheme, which already handles this naturally via the date component).
C. No cooldown for any TW event (could flood the feed during peak monsoon).

**Recommendation:** A (current plan). The date component of `event_id` already prevents same-day same-tier re-fire; the 3-day cooldown prevents same-city flooding across consecutive days.

### Fork 6 — Co-condition requirements

Should the signal require a minimum air temperature (e.g. T ≥ 25°C) alongside TW ≥ 31°C? In principle, a very high TW at low air temperature is theoretically possible but physically rare. Adding the co-condition would:

- Prevent edge-case false positives from model artifacts
- Add complexity and a second API call (or inclusion of `temperature_2m_max` in the same hourly call)

Since `wet_bulb_temperature_2m` already incorporates air temperature and humidity, a dangerously high TW inherently implies a significant ambient temperature. **Recommendation:** no co-condition in v1; monitor first-month production data.

---

## Verification

After all files are created/modified, verify with:

```bash
# Type checking — all new type annotations must pass
python -m mypy src/data/open_meteo.py \
               src/editorial/scoring/wetbulb.py \
               src/editorial/thresholds.py \
               src/two_bot/intern/wetbulb.py \
               src/two_bot/intern/__init__.py \
               src/orchestrator/common.py

# Full test suite (skip voice regression which requires live API keys)
python -m pytest tests/ -q -m "not voice_replay"

# Targeted new tests
python -m pytest tests/test_wetbulb.py tests/two_bot/test_wetbulb_intern.py -v

# Verify inclusion-gate fix specifically: a bundle with only wet_bulb_extreme set
# must not be dropped by check_extreme_signals_for_cities()
python -m pytest tests/test_wetbulb.py::test_wb_only_bundle_not_dropped -v

# Lint all changed files
python -m ruff check \
    src/data/open_meteo.py \
    src/editorial/scoring/wetbulb.py \
    src/editorial/scoring/__init__.py \
    src/editorial/thresholds.py \
    src/editorial/approval.py \
    src/two_bot/intern/wetbulb.py \
    src/two_bot/intern/__init__.py \
    src/orchestrator/common.py \
    src/orchestrator/sources/open_meteo.py \
    src/two_bot/prompts/writer_prompt.py \
    src/two_bot/prompts/fact_check_prompt.py
```

**Expected outcome:** all green. The new scorer unit tests specifically verify the scoring math at all three tier boundaries. The orchestrator test verifies the triage queue is populated from the wet-bulb pass over `bundles`. The intern test verifies the `StoryBundle` shape matches the `evidence_contract` audit. The inclusion-gate test confirms a wet-bulb-only city (no air-temp record) survives `check_extreme_signals_for_cities()`.

**Smoke-test the FORECAST daily variable existence** before wiring (one-off check, not a CI test):

```bash
python -c "
import requests, json
r = requests.get('https://api.open-meteo.com/v1/forecast', params={
    'latitude': 24.0, 'longitude': 68.0,
    'daily': 'wet_bulb_temperature_2m_max',
    'timezone': 'auto', 'forecast_days': 1
})
print(r.status_code, json.dumps(r.json().get('daily', {}), indent=2))
"
```

Expected: HTTP 200, `daily.wet_bulb_temperature_2m_max` is a list with one float value.

**Smoke-test the ARCHIVE endpoint** (Step 0 — BLOCKING; run before wiring archive `daily` param):

```bash
python -c "
import requests, json
r = requests.get('https://archive-api.open-meteo.com/v1/archive', params={
    'latitude': 24.0, 'longitude': 68.0,
    'start_date': '2024-07-01', 'end_date': '2024-07-03',
    'daily': 'temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max',
    'timezone': 'auto',
})
print('STATUS:', r.status_code)
d = r.json().get('daily', {})
print('Fields:', list(d.keys()))
print('wet_bulb sample:', d.get('wet_bulb_temperature_2m_max'))
print('air_temp sample:', d.get('temperature_2m_max'))
"
```

Expected: HTTP 200; `daily.wet_bulb_temperature_2m_max` present with floats; `daily.temperature_2m_max` and `daily.temperature_2m_min` still present (regression check). If 400 or field absent → fall back to forecast-only per Step 0.

**Regression assertion (add to orchestrator integration test):** A bundle with only `wet_bulb_extreme` set (all air-temp signal fields None) must NOT appear in `country_records` aggregation or `simultaneous_records` output. Verify `bundle.calendar_date_high is None` gate is respected by those aggregation paths.

---

## Out of scope / future

- **~~Tier-1 (31°C / "danger"):~~** RESOLVED — cut. Floor is tier 2 (33°C). Tier-1 fired too frequently in tropical cities during monsoon season and produced scores below threshold 78. `WETBULB_TIERS` does not include the `(1, 31.0, "danger")` entry. The `1:` keys in `_TIER_SEVERITY_BOOST` / `_TIER_NOVELTY_BOOST` / `_TIER_SHARE_BOOST` are harmless defensive guards, never reached in practice.
- **~~Archive TW fetch:~~** RESOLVED — `wet_bulb_temperature_2m_max` is a native daily variable; archive data is already returned by the existing archive request at zero additional cost.
- **Tier-3 label review:** the bundle uses `tier_label="tier_3"` as a neutral internal identifier. A future pass may introduce a more descriptive label once writer/fact-checker guardrails are proven at scale. "Survivability limit" is reserved for `tw_explainer` framing only — not the tier_label string.
- **Apparent temperature secondary fact:** adding `apparent_temperature` as a bundle secondary fact (Design Fork 3) for consumer-friendly "feels like" framing.
- **Global TW climatology layer:** precomputed monthly mean/max TW per city for writer context framing without per-run API overhead.
- **GHCN path:** once GHCN covers TW station observations, a GHCN-path `WetBulbEvent` builder would provide station-confirmed (not model-derived) readings — higher confidence, different score factors. This would unlock "observed" (not "forecast model") framing and higher confidence scores.
- **Humidex / WBGT alternatives:** Humidex (Canada) and Wet Bulb Globe Temperature (outdoor workers, military) are related metrics. Out of scope; TW is the cleanest scalar for the tweet format.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | 5 P1s caught, all folded (Revision 2) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | Step 0 trim (tier-1 + dead branch); 1 arch P1 (archive-var verify-first, 1B); 3 code-quality folds; tests ~90% |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run |

- **CODEX:** 5 P1s (daily-var-exists, inclusion-gate trap, tier-state timing, evidence safety, single-call) folded in Revision 2.
- **UNRESOLVED:** none.
- **VERDICT:** ENG CLEARED — ready to implement. Scope: tier-2/3 only; archive var gated on a blocking smoke-test.
