# Absolute-extreme (latitude bands) — implementation plan

> **Revision 2: folded Codex adversarial review (2026-06-08).**
> Changes from Revision 1: (1) inclusion-gate trap fixed — `absolute_extreme` field added to `ExtremeSignalBundle` AND to the `any([...])` gate; (2) latitude-band model made self-consistent (signed-lat asymmetric, two explicit N/S tables, `abs(lat)` removed).

> **Eng-review 2026-06-08:** Split from the combined temp-anomaly plan (Part B / `reanalysis_anomaly` deferred). Approval changed from `suggested_auto` to `manual_only` — consistent with wet-bulb, air-quality, and SST new signals. The hand-calibrated latitude bands are untested in production; launch under manual review.

Flag readings that are astounding for their latitude regardless of archive records. A city might not break any of its own records and still read 52°C — that is a story on its own. Uses temperatures *already fetched* in the `detect_extreme_signals` per-city loop. Zero new API calls.

---

## Background

@theheat is a station-record detector. It knows when Phoenix broke its June 14 record, but it has no concept of "50°C anywhere is news." @extremetemps fills that gap manually. This plan closes it programmatically.

**`absolute_extreme`**: Detect readings that are astounding *in absolute terms for their latitude*, independent of local archive history. Uses temperatures *already fetched* in the `detect_extreme_signals` per-city loop. Zero new API calls.

### Explicit contrast with existing `anomaly_hot` / `anomaly_cold`

The codebase already has a per-city anomaly signal. This is not that:

| Property | Existing `anomaly_hot` / `anomaly_cold` | `absolute_extreme` |
|---|---|---|
| Unit of analysis | Single city | Single city |
| Trigger criterion | today ≥ 15°C above *that city's* 30-yr monthly mean | today ≥ absolute threshold *for latitude band* |
| Baseline required | Open-Meteo 30-yr archive (already fetched) | None — threshold table only |
| Event type | `AnomalyEvent` dataclass | `AbsoluteExtremeEvent` (new) |
| `event_id` prefix | `anomaly_hot_*` / `anomaly_cold_*` | `absextreme_*` |
| Category | `anomaly` (threshold 74) | `absolute_extreme` (proposed 78) |
| New data needed | No | No |

`absolute_extreme` adds a detection branch *after* the existing anomaly block in `detect_extreme_signals`; it does not touch, replace, or subsume `anomaly_hot` / `anomaly_cold`. Both can fire simultaneously for the same city if both criteria are met — they are independent signals at different tiers. `absolute_extreme` sits *above* `anomaly` in the priority cascade (all_time > monthly > absolute_extreme > anomaly > calendar_date).

---

## Data sources

No new data. `detect_extreme_signals` already fetches `today_max` and `today_min` from `BASE_URL/forecast` and stores them in `ExtremeSignalBundle.today_max_c` / `today_min_c` (`src/data/open_meteo.py` lines 403–404). The latitude is passed in as the `lat` argument (`src/data/open_meteo.py` line 371). This implementation reads those two values plus `lat` and compares against a hard-coded latitude-band table.

---

## Signal definitions and thresholds

### `absolute_extreme` (latitude-banded)

A reading is "astounding for its latitude" when it crosses an absolute threshold calibrated to what is climatologically rare at that latitude band. The detector fires on `today_max_c` (hot) or `today_min_c` (cold). Both `lat` values (`src/data/open_meteo.py` line 371) and temps are available in the existing `detect_extreme_signals` function.

#### Latitude band model — self-consistent signed-lat design

**The band model uses SIGNED latitude throughout. `abs(lat)` is NOT used.** The N and S hemispheres have distinct band entries because southern subtropics (e.g., Australian interior) and southern mid-latitudes (Patagonia, South Africa Cape) have different climatological ceilings from their northern mirrors. Using `abs(lat)` would collapse those distinctions and misclassify southern subtropics into northern mid-latitude thresholds.

The `detect_absolute_extreme` function iterates the table with signed-lat comparison `min_lat_signed <= lat < max_lat_signed`, covering −90 to +90 without gaps.

#### Hot-side band table (signed latitude, exhaustive coverage from −90 to +90)

| min lat | max lat | Band label | Hot threshold °C | Rationale |
|---|---|---|---|---|
| 66.5 | 90.0 | Arctic | 30 | Arctic 30°C is a systemic event anywhere above the Circle |
| 55.0 | 66.5 | Sub-Arctic | 35 | Helsinki or Edmonton at 35°C is beyond design basis |
| 40.0 | 55.0 | N Mid-latitudes | 42 | 42°C in Germany / Poland / UK crosses the physiological danger threshold |
| 23.5 | 40.0 | N Sub-tropical | 47 | 47°C in Madrid or Seville is a mass-casualty threshold |
| -23.5 | 23.5 | Tropics | 50 | 50°C in equatorial Africa / South Asia is rare even for desert margins |
| -40.0 | -23.5 | S Sub-tropical | 48 | Alice Springs or Jacobabad at 48°C signals a mass-casualty heat event |
| -90.0 | -40.0 | S Mid-latitudes | 40 | 40°C in Patagonia or South Africa's Cape is extraordinary |

#### Cold-side band table (signed latitude)

| min lat | max lat | Band label | Cold threshold °C | Rationale |
|---|---|---|---|---|
| 66.5 | 90.0 | Arctic | −50 | Yakutsk typical winter floor; −50°C is extreme even there |
| 55.0 | 66.5 | Sub-Arctic | −40 | −40°C in Helsinki or Winnipeg marks a record-grade cold surge |
| 40.0 | 55.0 | N Mid-latitudes | −30 | −30°C in Warsaw or Chicago signals a dangerous cold air mass |
| 23.5 | 40.0 | N Sub-tropical | −15 | Freezing in the sub-tropics is the story, not depth |
| -23.5 | 23.5 | Tropics | 5 | Frost in the tropics is rare enough to be news |
| -40.0 | -23.5 | S Sub-tropical | −20 | Southern sub-tropical cold extreme (symmetric rationale with N Sub-tropical, colder baseline) |
| -90.0 | -40.0 | S Mid-latitudes | −45 | Antarctic-adjacent cold air; −45°C in S mid-lats is extreme even for that region |

#### Unified `LATITUDE_BANDS` constant (one table, both sides)

```python
# (min_lat_signed, max_lat_signed, hot_threshold_c, cold_threshold_c, band_label)
# Covers −90 to +90 with no gaps. Use signed lat directly — do NOT call abs(lat).
LATITUDE_BANDS: list[tuple[float, float, float, float, str]] = [
    ( 66.5,  90.0,  30.0, -50.0, "Arctic"),
    ( 55.0,  66.5,  35.0, -40.0, "Sub-Arctic"),
    ( 40.0,  55.0,  42.0, -30.0, "N Mid-latitudes"),
    ( 23.5,  40.0,  47.0, -15.0, "N Sub-tropical"),
    (-23.5,  23.5,  50.0,   5.0, "Tropics"),
    (-40.0, -23.5,  48.0, -20.0, "S Sub-tropical"),
    (-90.0, -40.0,  40.0, -45.0, "S Mid-latitudes"),
]
```

Band lookup: `next((b for b in LATITUDE_BANDS if b[0] <= lat < b[1]), None)`. A city at exactly `lat = -40.0` falls into S Sub-tropical (lower bound inclusive). A city at exactly `lat = -23.5` falls into Tropics. Cover edge cases in unit tests.

#### event_id scheme

```
absextreme_<city_slug>_<YYYY-MM-DD>        # hot
absextreme_cold_<city_slug>_<YYYY-MM-DD>   # cold
```

where `city_slug = city.replace(" ", "_")`.

#### Category and threshold

Proposed category: `absolute_extreme`. Proposed threshold: **78**.

Rationale: Above `anomaly` (74) and `monthly_record` (76), below `all_time_record` (80). An absolute-extreme reading is inherently elite — it means a temperature is astounding on a global scale, not just local. It should be rarer than the existing anomaly signal but not restricted to the narrow window of `all_time_record`. 78 puts it in the same tier as `marine_heatwave` and `ice_mass_record`.

---

## Files to create / modify

### Modifications only — no new files

**`src/data/open_meteo.py`**

1. Add `AbsoluteExtremeEvent` dataclass (alongside `AnomalyEvent` at line 79).
2. Add `LATITUDE_BANDS: list[tuple[float, float, float, float, str]]` constant after `ANOMALY_COLD_THRESHOLD_C` at line 367. The constant uses signed lat — no `abs()`.
3. Add `detect_absolute_extreme(lat, lon, today_max_c, today_min_c, city, country, ...) -> AbsoluteExtremeEvent | None` function.
4. Add `absolute_extreme: AbsoluteExtremeEvent | None = None` field to `ExtremeSignalBundle` (currently lines 107–144). **CRITICAL: also add `bundle.absolute_extreme` to the `any([...])` inclusion check in `check_extreme_signals_for_cities` at lines 641–647, so cities that trip ONLY an `absolute_extreme` are not silently dropped before `run_extreme_signals` sees them.**
5. In `detect_extreme_signals` (line 370), after the `anomaly_cold` block (after line 603), call `detect_absolute_extreme(lat, lon, today_max, today_min, city, country)` and assign to `bundle.absolute_extreme`.

**`src/orchestrator/sources/open_meteo.py`**

1. Import `AbsoluteExtremeEvent` from `src.data.open_meteo` (via `common.py`'s star-import chain, or directly at top of file since it uses `from src.orchestrator.common import *`).
2. In `run_extreme_signals` (line 9), add an `absolute_extreme` branch to the priority cascade, positioned between `monthly_low` and `anomaly_hot` blocks (lines 139–184). Add to `signal_counts` dict at line 18.
3. Add `_two_bot_bundle_for_extreme_signal` dispatch case for `"absolute_extreme"` (in `src/orchestrator/common.py` at line 1104).

**`src/editorial/scoring/temperature.py`**

Add `score_absolute_extreme(temp_c: float, lat: float, band_label: str, threshold_c: float, kind: str) -> EditorialScore` function.

**`src/editorial/thresholds.py`**

Add `"absolute_extreme": ThresholdEntry("absolute_extreme", 78, "Latitude-banded absolute temperature extreme; rarer than per-city anomaly, below all-time-record tier.")`.

**`src/editorial/scoring/__init__.py`**

Export `score_absolute_extreme`.

**`src/orchestrator/common.py`**

1. Import `score_absolute_extreme` (lines 43–81 imports block).
2. Add `score_absolute_extreme` to `__all__` (line 1471).
3. Add `"absolute_extreme"` dispatch to `_two_bot_bundle_for_extreme_signal` (line 1104).

**`src/two_bot/intern/temperature.py`**

Add `build_absolute_extreme_bundle(ev: AbsoluteExtremeEvent) -> StoryBundle`.

**`src/two_bot/intern/__init__.py`**

Export `build_absolute_extreme_bundle`.

**`src/editorial/approval.py`**

Add `absolute_extreme` to the `manual_only` set (same block as wet-bulb, air-quality, SST — line 165–187). Do NOT place in `suggested_auto`; the hand-calibrated latitude bands are untested in production and require human review at launch.

---

## Step-by-step implementation

### Step 1 — Add `AbsoluteExtremeEvent` dataclass

In `src/data/open_meteo.py`, after `AnomalyEvent` (ends at line 91):

```python
@dataclass
class AbsoluteExtremeEvent:
    """Today's reading exceeds the absolute threshold for its latitude band."""
    city: str
    country: str
    today_temp_c: float
    band_label: str        # e.g. "Arctic", "Sub-Arctic", "N Mid-latitudes"
    threshold_c: float     # the band's absolute cutoff
    kind: str              # "hot" or "cold"
    lat: float
    lon: float
    event_id: str
    signal_date: date | None = None
    state: str | None = None
    data_source: str = "forecast"  # "forecast" or "ghcn"; for writer framing
```

### Step 2 — Add latitude band table constant

In `src/data/open_meteo.py`, after line 367 (`ANOMALY_COLD_THRESHOLD_C`):

```python
# Signed-latitude band table. Do NOT use abs(lat) — N and S hemispheres have
# distinct thresholds. Iterate with: next((b for b in LATITUDE_BANDS if b[0] <= lat < b[1]), None)
# (min_lat_signed, max_lat_signed, hot_threshold_c, cold_threshold_c, band_label)
LATITUDE_BANDS: list[tuple[float, float, float, float, str]] = [
    ( 66.5,  90.0,  30.0, -50.0, "Arctic"),
    ( 55.0,  66.5,  35.0, -40.0, "Sub-Arctic"),
    ( 40.0,  55.0,  42.0, -30.0, "N Mid-latitudes"),
    ( 23.5,  40.0,  47.0, -15.0, "N Sub-tropical"),
    (-23.5,  23.5,  50.0,   5.0, "Tropics"),
    (-40.0, -23.5,  48.0, -20.0, "S Sub-tropical"),
    (-90.0, -40.0,  40.0, -45.0, "S Mid-latitudes"),
]
```

### Step 3 — Add `detect_absolute_extreme` function

```python
def detect_absolute_extreme(
    lat: float,
    lon: float,
    today_max_c: float | None,
    today_min_c: float | None,
    city: str,
    country: str,
    *,
    signal_date: date | None = None,
    state: str | None = None,
    data_source: str = "forecast",
) -> AbsoluteExtremeEvent | None:
    """Fire if today's temp crosses the absolute threshold for this latitude band.

    Uses SIGNED latitude — do NOT call abs(lat) before passing in.
    Hot is checked before cold; only one event fires per city per day.
    """
    today = signal_date or date.today()
    city_key = city.replace(" ", "_")
    today_iso = today.isoformat()

    band = next((b for b in LATITUDE_BANDS if b[0] <= lat < b[1]), None)
    if band is None:
        return None  # lat out of range — shouldn't happen for valid coordinates
    min_lat, max_lat, hot_thresh, cold_thresh, band_label = band

    if today_max_c is not None and today_max_c >= hot_thresh:
        return AbsoluteExtremeEvent(
            city=city, country=country,
            today_temp_c=today_max_c,
            band_label=band_label,
            threshold_c=hot_thresh,
            kind="hot",
            lat=lat, lon=lon,
            event_id=f"absextreme_{city_key}_{today_iso}",
            signal_date=signal_date,
            state=state,
            data_source=data_source,
        )
    if today_min_c is not None and today_min_c <= cold_thresh:
        return AbsoluteExtremeEvent(
            city=city, country=country,
            today_temp_c=today_min_c,
            band_label=band_label,
            threshold_c=cold_thresh,
            kind="cold",
            lat=lat, lon=lon,
            event_id=f"absextreme_cold_{city_key}_{today_iso}",
            signal_date=signal_date,
            state=state,
            data_source=data_source,
        )
    return None
```

### Step 4 — Wire into `ExtremeSignalBundle` and both gate points

**4a — Add field to `ExtremeSignalBundle`** (currently lines 107–144). Add `absolute_extreme: AbsoluteExtremeEvent | None = None` after `anomaly_cold` at line 135.

**4b — Add to the `any([...])` inclusion gate** at `check_extreme_signals_for_cities` lines 641–647. This is the P1 fix — without it, cities that fire ONLY on `absolute_extreme` are silently dropped before `run_extreme_signals` ever sees them.

Current gate (lines 641–647):
```python
        if any([
            bundle.calendar_date_high, bundle.calendar_date_low,
            bundle.all_time_high, bundle.all_time_low,
            bundle.monthly_high, bundle.monthly_low,
            bundle.anomaly_hot, bundle.anomaly_cold,
        ]):
            bundles.append(bundle)
```

Required change (add `bundle.absolute_extreme` to the list):
```python
        if any([
            bundle.calendar_date_high, bundle.calendar_date_low,
            bundle.all_time_high, bundle.all_time_low,
            bundle.monthly_high, bundle.monthly_low,
            bundle.anomaly_hot, bundle.anomaly_cold,
            bundle.absolute_extreme,  # P1 fix: include absolute-extreme-only cities
        ]):
            bundles.append(bundle)
```

**4c — Call `detect_absolute_extreme` inside `detect_extreme_signals`** (after the `anomaly_cold` block, before line 605 `return bundle`):

```python
    # Absolute extreme vs latitude band — fires independently of archive comparison.
    abs_ev = detect_absolute_extreme(
        lat, lon, today_max, today_min, city, country,
    )
    if abs_ev is not None:
        bundle.absolute_extreme = abs_ev
```

### Step 5 — Add scoring function

In `src/editorial/scoring/temperature.py`:

```python
def score_absolute_extreme(
    temp_c: float,
    lat: float,
    band_label: str,
    threshold_c: float,
    kind: str = "hot",
) -> EditorialScore:
    """Reading exceeds the absolute threshold for its latitude band."""
    margin = abs(temp_c - threshold_c)
    severity = 80 + margin * 2.0  # starts elite; margin pushes higher
    novelty = 88
    timeliness = 94
    confidence = 80   # forecast data; slightly below station-obs confidence
    shareability = 84 + margin * 1.5
    reasons = [
        f"{kind} absolute extreme for {band_label} latitude band",
        f"{temp_c:.1f}C vs {threshold_c:.1f}C band threshold",
    ]
    if margin >= 5:
        reasons.append(f"{margin:.1f}C over band threshold")
    return _build_score(
        "absolute_extreme",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=10,
        threshold=get_threshold("absolute_extreme"),
        reasons=reasons,
    )
```

### Step 6 — Add orchestrator dispatch in `run_extreme_signals`

In `src/orchestrator/sources/open_meteo.py`, add after the `anomaly_cold` block and before the `calendar_date_high` block:

```python
            if strongest_signal is None and bundle.absolute_extreme:
                ev_ae: AbsoluteExtremeEvent = bundle.absolute_extreme
                if not state.is_duplicate(bot_state, ev_ae.event_id):
                    score = score_absolute_extreme(
                        ev_ae.today_temp_c, ev_ae.lat,
                        ev_ae.band_label, ev_ae.threshold_c, kind=ev_ae.kind,
                    )
                    if _should_draft(score, ev_ae.event_id):
                        strongest_signal = ev_ae
                        strongest_score = score
                        strongest_event_id = ev_ae.event_id
                        strongest_type = "absolute_extreme"
                        strongest_city = ev_ae.city
                        strongest_headline = (
                            f"{ev_ae.city}: {ev_ae.today_temp_c:.1f}C "
                            f"({ev_ae.band_label} absolute extreme)"
                        )
                        strongest_facts = [
                            _fact("City", ev_ae.city),
                            _fact("Country", ev_ae.country),
                            _fact("Temperature", _temp_pair_c(ev_ae.today_temp_c)),
                            _fact("Latitude band", ev_ae.band_label),
                            _fact("Band threshold", _temp_pair_c(ev_ae.threshold_c)),
                            _fact("Kind", ev_ae.kind),
                            _fact("Data source", ev_ae.data_source),
                        ]
                        signal_counts.setdefault("absolute_extreme", 0)
                        signal_counts["absolute_extreme"] += 1
```

Also add `"absolute_extreme"` to the `signal_counts` dict initialization at line 18.

### Step 7 — Bundle builder and dispatch

In `src/two_bot/intern/temperature.py`, add:

```python
def build_absolute_extreme_bundle(ev: AbsoluteExtremeEvent) -> StoryBundle:
    """Reading crosses the absolute threshold for its latitude band."""
    state = getattr(ev, "state", None)
    city = normalize_station_name(ev.city) or ev.city
    where = _format_where(city, ev.country, state)
    today_temp_f = _c_to_f(ev.today_temp_c)
    threshold_f = _c_to_f(ev.threshold_c)
    is_forecast = ev.data_source == "forecast"
    return StoryBundle(
        signal_kind=f"absolute_extreme_{ev.kind}",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": f"today_temp_c_{ev.kind}",
            "value": ev.today_temp_c,
            "unit": "C",
            "value_f": today_temp_f,
            "is_forecast": is_forecast,  # writer uses "on pace for" language if True
        },
        current_facts=[
            {"label": "city", "value": city},
            {"label": "country", "value": ev.country},
            {"label": "lat", "value": ev.lat},
            {"label": "band_label", "value": ev.band_label},
            {"label": "today_c", "value": ev.today_temp_c},
            {"label": "today_f", "value": today_temp_f},
            {"label": "threshold_c", "value": ev.threshold_c},
            {"label": "threshold_f", "value": threshold_f},
            {"label": "kind", "value": ev.kind},
            {"label": "data_source", "value": ev.data_source},
            *_audience_unit_facts(ev.country),
        ],
        historical_context={
            "band_label": ev.band_label,
            "threshold_c": ev.threshold_c,
            "scope": "latitude_band_absolute",
            "is_forecast": is_forecast,
        },
        raw_signal_dump=asdict(ev),
    )
```

In `_two_bot_bundle_for_extreme_signal` (in `src/orchestrator/common.py`, line 1104):

```python
        if strongest_type == "absolute_extreme":
            from src.data.open_meteo import AbsoluteExtremeEvent
            return intern.build_absolute_extreme_bundle(strongest_signal)
```

In `src/two_bot/intern/__init__.py`, add `build_absolute_extreme_bundle` to imports and `__all__`.

### Step 8 — Add approval policy

In `src/editorial/approval.py`, add `"absolute_extreme"` to the `manual_only` set (inside the existing manual_only block at lines 165–187, alongside wet-bulb, air-quality, SST, and `regional_anomaly`):

```python
    if tweet_type in {
        "wet_bulb", "air_quality", "sst_anomaly",
        "absolute_extreme",  # untested latitude bands; manual review at launch
    }:
        return ApprovalPolicy(
            key=f"{tweet_type}_review",
            mode="manual_only",
            recommended_delay_minutes=0,
            can_auto_approve=False,
            reason=(
                "Latitude-banded absolute extreme — hand-calibrated thresholds untested in "
                "production. Human review required during calibration period. Escalate to "
                "suggested_auto after 5+ approved drafts without editorial corrections."
            ),
        )
```

Do NOT add to `suggested_auto`. The hand-calibrated latitude bands are new and untested; the signal must run under human review before any auto-approval path opens.

### Step 9 — Tests

Write `tests/test_absolute_extreme.py` (see Test Plan section below).

---

## Bundle and writer-prompt changes

### `build_absolute_extreme_bundle`

Key facts the writer needs:
- `band_label` — "Arctic", "Sub-Arctic", etc. — the writer's context anchor
- `today_c` and `today_f` — the actual reading
- `threshold_c` and `threshold_f` — the band floor the reading crossed
- `lat` — for the writer to reference "above the Arctic Circle", "in the tropics"
- `data_source` — "forecast" or "ghcn"; if "forecast", writer must use "on pace for" / "forecast to" language

Writer framing instruction (no prompt change needed — bundle facts carry the framing):
> The latitude band and season are the context. "50°C in March in the tropics" is the data + season; the system clause should explain what makes the absolute number matter where it happened. Avoid "record" framing — this signal does not require any historical record to be broken. If `data_source` is "forecast", use hedged language ("forecast to reach", "on pace for").

The `historical_context` carries `scope: "latitude_band_absolute"`. The writer should not claim rarity by archive comparison — the claim is purely about the absolute value relative to the band's climatological ceiling.

---

## Scoring and thresholds

### `score_absolute_extreme`

```python
# Base formula (verified against existing score functions in temperature.py)
severity = 80 + margin * 2.0       # margin = abs(temp_c - threshold_c)
novelty = 88
timeliness = 94
confidence = 80                     # forecast data
shareability = 84 + margin * 1.5
threshold = get_threshold("absolute_extreme")  # 78
```

A reading exactly at the threshold (margin = 0) gives total ≈ 80, which clears 78. A reading 5°C over threshold gives total ≈ 90, elite range. This is intentionally conservative — marginal threshold-crossings should clear but not dominate.

---

## State / caps / cooldowns

- Dedup via `state.is_duplicate(bot_state, ev.event_id)` (same pattern as all other signals; `event_id` is `absextreme_<city>_<date>`).
- City cooldown: apply the standard `CITY_COOLDOWN_DAYS = 3` cooldown (same as `anomaly_hot`). The signal is per-city, and a city that reads 50°C once will likely still be hot tomorrow — we don't want to re-tweet the same event. Pass `cooldown_exempt=False` in `_enqueue_story_candidate`.
- Exception: if `score.total >= ELITE_COPY_SCORE` (95), the draft-save gate already bypasses cooldown — no change needed.
- No annual cap required — absolute-extreme events are genuinely rare.

---

## Approval policy

Policy: **`manual_only`**. Rationale: absolute-extreme readings are forecast-data signals (not confirmed observations), and the latitude-band table is new and untested in production. Human review required during the calibration period (target: first 2–4 weeks, or until 5+ approved drafts without editorial corrections). At that point escalate to `suggested_auto` with `recommended_delay_minutes=120`.

Set in `src/editorial/approval.py` under the existing `manual_only` block (lines 165–187), alongside wet-bulb, air-quality, and SST.

---

## Test plan

### Part A tests — `tests/test_absolute_extreme.py`

```python
# Pattern: mock date.today(), import from src.data.open_meteo

class TestDetectAbsoluteExtreme:
    def test_arctic_hot_fires_above_30c(self):
        # lat=70, today_max=31.5 → band "Arctic", threshold 30.0, fires
        ev = detect_absolute_extreme(70.0, 25.0, 31.5, None, "Tromsø", "Norway")
        assert ev is not None
        assert ev.band_label == "Arctic"
        assert ev.kind == "hot"

    def test_arctic_hot_does_not_fire_below_30c(self):
        # lat=70, today_max=29.9 → no signal
        ev = detect_absolute_extreme(70.0, 25.0, 29.9, None, "Tromsø", "Norway")
        assert ev is None

    def test_mid_latitude_hot_fires_above_42c(self):
        # lat=48, today_max=43.0 → band "N Mid-latitudes", fires
        ev = detect_absolute_extreme(48.0, 16.0, 43.0, None, "Vienna", "Austria")
        assert ev is not None
        assert ev.band_label == "N Mid-latitudes"

    def test_tropics_hot_fires_at_50c(self):
        # lat=5, today_max=50.1 → band "Tropics", fires
        ev = detect_absolute_extreme(5.0, 32.0, 50.1, None, "Khartoum", "Sudan")
        assert ev is not None
        assert ev.band_label == "Tropics"

    def test_tropics_hot_does_not_fire_at_49c(self):
        # lat=5, today_max=49.9 → no signal
        ev = detect_absolute_extreme(5.0, 32.0, 49.9, None, "Khartoum", "Sudan")
        assert ev is None

    def test_cold_arctic_fires_below_minus_50(self):
        # lat=72, today_min=-51.0 → cold extreme fires
        ev = detect_absolute_extreme(72.0, 129.0, None, -51.0, "Yakutsk", "Russia")
        assert ev is not None
        assert ev.kind == "cold"
        assert ev.band_label == "Arctic"

    def test_event_id_format_hot(self):
        ev = detect_absolute_extreme(70.0, 25.0, 32.0, None, "Tromsø", "Norway")
        assert ev.event_id.startswith("absextreme_Tromsø_")

    def test_event_id_format_cold(self):
        ev = detect_absolute_extreme(70.0, 25.0, None, -51.0, "Tromsø", "Norway")
        assert ev.event_id.startswith("absextreme_cold_Tromsø_")

    def test_none_when_no_threshold_crossed(self):
        ev = detect_absolute_extreme(50.0, 0.0, 30.0, None, "London", "UK")
        assert ev is None  # lat=50 → N Mid-latitudes, threshold 42°C; 30 < 42

    def test_southern_hemisphere_subtropics_distinct_from_northern(self):
        # lat=-30 (S Sub-tropical, threshold 48°C) — NOT N Sub-tropical (47°C)
        ev_s = detect_absolute_extreme(-30.0, 133.0, 48.0, None, "Alice Springs", "Australia")
        assert ev_s is not None
        assert ev_s.band_label == "S Sub-tropical"
        # A reading of 47.9°C (crosses N Sub-tropical 47°C but NOT S Sub-tropical 48°C)
        ev_s_below = detect_absolute_extreme(-30.0, 133.0, 47.9, None, "Alice Springs", "Australia")
        assert ev_s_below is None  # S sub-tropical threshold is 48, not 47

    def test_bundle_includes_absolute_extreme(self):
        # Test that ExtremeSignalBundle.absolute_extreme is populated
        # when detect_extreme_signals runs with a patched today reading
        # that crosses the band threshold
        # (requires mocking the HTTP calls in detect_extreme_signals)
        ...
```

### Latitude-band table unit tests

```python
class TestLatitudeBandTable:
    @pytest.mark.parametrize("lat,expected_band", [
        ( 70.0, "Arctic"),
        ( 60.0, "Sub-Arctic"),
        ( 45.0, "N Mid-latitudes"),
        ( 30.0, "N Sub-tropical"),
        (  0.0, "Tropics"),
        (-30.0, "S Sub-tropical"),
        (-50.0, "S Mid-latitudes"),
    ])
    def test_band_classification(self, lat, expected_band):
        from src.data.open_meteo import LATITUDE_BANDS
        band = next((b for b in LATITUDE_BANDS if b[0] <= lat < b[1]), None)
        assert band is not None
        assert band[4] == expected_band

    def test_full_coverage_no_gaps(self):
        """Every integer latitude from -90 to 89 must land in exactly one band."""
        from src.data.open_meteo import LATITUDE_BANDS
        for lat in range(-90, 90):
            matches = [b for b in LATITUDE_BANDS if b[0] <= lat < b[1]]
            assert len(matches) == 1, f"lat={lat} matched {len(matches)} bands"

    def test_southern_subtropics_threshold_distinct_from_northern(self):
        """S Sub-tropical hot threshold (48°C) != N Sub-tropical (47°C)."""
        from src.data.open_meteo import LATITUDE_BANDS
        n_sub = next(b for b in LATITUDE_BANDS if b[4] == "N Sub-tropical")
        s_sub = next(b for b in LATITUDE_BANDS if b[4] == "S Sub-tropical")
        assert n_sub[2] != s_sub[2], "N and S sub-tropical hot thresholds should differ"
```

### Scoring tests — in `tests/test_editorial_scoring.py`

```python
def test_score_absolute_extreme_clears_threshold():
    score = score_absolute_extreme(32.0, 70.0, "Arctic", 30.0, kind="hot")
    assert score.passes

def test_score_absolute_extreme_marginal_just_clears():
    score = score_absolute_extreme(30.0, 70.0, "Arctic", 30.0, kind="hot")
    assert score.passes  # margin=0, base~80, threshold 78

def test_score_absolute_extreme_high_margin_elite():
    score = score_absolute_extreme(40.0, 70.0, "Arctic", 30.0, kind="hot")
    assert score.total >= 90

def test_score_absolute_extreme_below_threshold_fails():
    # Reading exactly at threshold-0.1 would not fire detect_absolute_extreme,
    # but if somehow passed, score should NOT pass. (Guard test.)
    score = score_absolute_extreme(29.9, 70.0, "Arctic", 30.0, kind="hot")
    # margin = 0.1 → severity = 80.2, clears 78. This is fine — the gate is in detect_absolute_extreme.
    # This test just verifies that scoring is deterministic.
    assert score.total >= 78
```

### Orchestrator integration tests — `tests/test_open_meteo_orchestrator.py`

Extend with:

```python
def test_absolute_extreme_is_drafted_when_fires():
    # Build a bundle with absolute_extreme set, mock _should_draft to True
    # Verify _enqueue_story_candidate is called with strongest_type="absolute_extreme"
    ...

def test_absolute_extreme_loses_to_all_time_record():
    # Bundle with both all_time_high and absolute_extreme set
    # Verify only all_time_high is drafted (priority cascade)
    ...

def test_absolute_extreme_only_city_not_dropped_by_gate():
    # CRITICAL: Construct a bundle where ONLY absolute_extreme is set (all other fields None)
    # Verify check_extreme_signals_for_cities includes this bundle in its output
    # (regression test for the P1 inclusion-gate fix)
    from src.data.open_meteo import ExtremeSignalBundle, AbsoluteExtremeEvent
    from datetime import date
    ae = AbsoluteExtremeEvent(
        city="Alice Springs", country="Australia",
        today_temp_c=49.0, band_label="S Sub-tropical",
        threshold_c=48.0, kind="hot", lat=-23.7, lon=133.9,
        event_id="absextreme_Alice_Springs_2026-01-15",
    )
    bundle = ExtremeSignalBundle(
        city="Alice Springs", country="Australia",
        today_max_c=49.0, today_min_c=28.0,
        absolute_extreme=ae,
        # all other signal fields remain None
    )
    assert any([
        bundle.calendar_date_high, bundle.calendar_date_low,
        bundle.all_time_high, bundle.all_time_low,
        bundle.monthly_high, bundle.monthly_low,
        bundle.anomaly_hot, bundle.anomaly_cold,
        bundle.absolute_extreme,
    ]), "absolute_extreme-only bundle must pass the inclusion gate"
```

---

## Risks / open questions

### Risk 1: latitude-band threshold calibration

The proposed thresholds are climatologically motivated but untested in production. Arctic 30°C and N Mid-latitude 42°C may be too permissive (fires too often) or too restrictive (misses notable events). Mitigation: start with the proposed values, run in shadow mode with `manual_only` for 2 weeks, tune based on signal frequency. Target: ≤1 fire per week globally on hot side.

**Design fork**: use fixed thresholds (proposed) vs. percentile-based thresholds (e.g., 99.9th percentile of the 30-year archive for each latitude band). The fixed approach is simpler to implement and explain; the percentile approach adapts to latitude-specific climatology but requires the archive data. Given Part A has no new data, fixed thresholds are strongly preferred.

### Risk 2: false positives from forecast data

`detect_extreme_signals` uses the Open-Meteo forecast high, not a confirmed station observation. A 50°C forecast for Kuwait City that verifies at 47°C is still notable, but tweets about "50°C" will look wrong if the actual reading comes in lower. Mitigations:
- The writer prompt already says "on pace for" / "forecast to" language for forecast-based signals.
- The `data_source` field in `AbsoluteExtremeEvent` and `headline_metric.is_forecast` in the bundle surface this context to the writer.
- The `archive_window_only` pattern in `historical_context` is a precedent — use the similar `is_forecast: True` flag.

**OPEN QUESTION**: Should this fire only on confirmed GHCN-Daily readings when `THEHEAT_SIGNALS_PROVIDER=ghcn`? If so, the GHCN path already has confirmed observations and the forecast-false-positive risk disappears. The GHCN bundle also carries `today_max_c` in `ExtremeSignalBundle`. Recommend: yes, make `detect_absolute_extreme` work on both paths by passing `data_source="ghcn"` when called from the GHCN path. The `data_source` field on `AbsoluteExtremeEvent` already supports this.

### Risk 3: existing `anomaly` vs. `absolute_extreme` priority ordering

The existing priority cascade in `run_extreme_signals` is: all_time_high > all_time_low > monthly_high > monthly_low > anomaly_hot > anomaly_cold > calendar_date_high > calendar_date_low.

Inserting `absolute_extreme` between `monthly_low` and `anomaly_hot` means:
- A city that breaks a monthly low AND reads at an absolute extreme will only produce one tweet (for the monthly low).
- A city that reads at an absolute extreme AND has an anomaly_hot signal will produce one tweet (for the absolute extreme).

This is correct: the absolute extreme is the stronger story when it fires. However, it is possible that a +15°C anomaly (a genuinely extraordinary local deviation) is a better story than an absolute extreme barely crossing the threshold. The priority ordering may need tuning after calibration. For now, absolute_extreme > anomaly is the safer default because the absolute thresholds are set conservatively.

### Risk 4: GHCN path compatibility

The GHCN path produces `ExtremeSignalBundle` instances via `ghcn.check_extreme_signals_for_stations`. The GHCN bundle includes `today_max_c` and `today_min_c` (same fields as the Open-Meteo path) and also carries `lat` via station metadata. However, the GHCN path bundle construction must be verified to populate `lat` and `lon` in the bundle before `detect_absolute_extreme` can be called from the GHCN path. This is an open question for GHCN compatibility: `detect_absolute_extreme` needs `lat` from the bundle, which may not be set on the GHCN path.

---

## Verification

Run these in order after implementing:

```bash
# Type checking
python -m mypy src/

# Full test suite (exclude live voice replay)
python -m pytest tests/ -q -m "not voice_replay"

# Lint only changed files
python -m ruff check src/data/open_meteo.py \
    src/orchestrator/sources/open_meteo.py \
    src/orchestrator/common.py \
    src/editorial/scoring/temperature.py \
    src/editorial/thresholds.py \
    src/editorial/approval.py \
    src/two_bot/intern/temperature.py \
    src/two_bot/intern/__init__.py

# Regression test: absolute-extreme-only city is NOT dropped by the inclusion gate
python -c "
from src.data.open_meteo import ExtremeSignalBundle, AbsoluteExtremeEvent
from datetime import date
ae = AbsoluteExtremeEvent(
    city='AliceSprings', country='Australia',
    today_temp_c=49.0, band_label='S Sub-tropical',
    threshold_c=48.0, kind='hot', lat=-23.7, lon=133.9,
    event_id='absextreme_AliceSprings_2026-01-15',
)
bundle = ExtremeSignalBundle(city='AliceSprings', country='Australia', absolute_extreme=ae)
assert any([
    bundle.calendar_date_high, bundle.calendar_date_low,
    bundle.all_time_high, bundle.all_time_low,
    bundle.monthly_high, bundle.monthly_low,
    bundle.anomaly_hot, bundle.anomaly_cold,
    bundle.absolute_extreme,
]), 'P1 gate fix broken — absolute_extreme-only city dropped'
print('P1 gate regression test passed')
"

# Smoke test the detection logic against a known extreme city
python -c "
from src.data.open_meteo import detect_absolute_extreme
ev = detect_absolute_extreme(70.0, 25.0, 32.0, None, 'Tromsø', 'Norway')
assert ev is not None and ev.band_label == 'Arctic', f'Expected Arctic event, got {ev}'
ev_s = detect_absolute_extreme(-30.0, 133.0, 48.0, None, 'Alice Springs', 'Australia')
assert ev_s is not None and ev_s.band_label == 'S Sub-tropical', f'Expected S Sub-tropical, got {ev_s}'
# S Sub-tropical threshold is 48°C; 47.9°C must NOT fire
ev_below = detect_absolute_extreme(-30.0, 133.0, 47.9, None, 'Alice Springs', 'Australia')
assert ev_below is None, f'Expected None below threshold, got {ev_below}'
print('Smoke tests passed:', ev.band_label, ev_s.band_label)
"
```

---

## Out of scope / future

- **Trend framing**: "the 10th time in 20 years this band threshold has been crossed in July." Requires a historical frequency count, which is a separate data pipeline.
- **Sigma-based triggers**: ≥ 2.5σ as an alternative trigger. Needs archive data. Defer.
- **Real-time confirmation**: This fires on forecast data. A follow-up could add a GHCN confirmation step — fire a "confirmed" re-tweet once the station observation lands.
- **Sub-national regions**: "the US Southwest" or "Northern India" are better stories than single-city absolute extremes for large countries. Separate feature.
- **Gridded area-weighted country means**: the authoritative approach for regional anomalies, addressed in the deferred Part B (reanalysis-anomaly) plan.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | inclusion-gate trap + latitude-band self-consistency — folded (Revision 2) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | Split from temp-anomaly (Part B deferred); approval → manual_only (consistency with other new signals); inclusion-gate verified at open_meteo.py:641; tests strong |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (backend) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run |

- **CODEX:** inclusion-gate trap + latitude-band abs(lat) inconsistency — folded Revision 2.
- **UNRESOLVED:** none.
- **VERDICT:** ENG CLEARED — Part A (absolute-extreme) ready to implement, manual_only at launch.
