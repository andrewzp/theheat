> **STATUS: REVISION 3 — BUILD-READY pending Step 0 backfill (2026-06-08).** Supersedes R2 (which supersedes R1/DEFERRED). After the R2 hardening, a **Codex cross-model outside-voice** review (read-only, code-grounded) caught **4 real P0s** the single-model passes missed — all verified against the code and folded; **2 product forks decided by Andrew**. **See "## Revision 3 deltas" below — the R2 notes that follow still apply except where the deltas supersede them.** _[R2 summary:]_ A 4-agent hardening pass (3 risk-resolvers + adversarial gap-hunt, grounded in the live code + live API) resolved all 3 open risks and fixed 4 P1 build-blockers + 8 P2/P3 issues. Remaining gate before merge: run `scripts/build_climatology_cache.py` (Step 0) and commit the cache. Still **build-LAST** of the @extremetemps lane (after Wave 1 + SST) and **launches `manual_only`, env-gated OFF**.
>
> **What changed vs Revision 1 (all grounded in live code / live API, 2026-06-08):**
> - **Risk 1 (fan-out) RESOLVED:** the Open-Meteo ARCHIVE endpoint accepts comma-separated multi-coord lists (live-verified: 50 coords / 7 days in **2.72s**). The 30–90 sequential calls/cycle collapse to **ONE** batched request. `bot_state["_reganom_live_cache"]` guards same-cycle retries.
> - **Risk 2 (backfill) RESOLVED + 30× smaller:** the "~1,500 requests" figure was WRONG — a single archive request spans **1991-01-01 → 2020-12-31 (10,958 rows, 76ms, zero nulls)**. Backfill is **~50 requests (~2 min)**, not 1,500 (~30 min). Adds a 429-aware backoff wrapper (`fetch_with_retry` does NOT retry 429) + atomic per-point checkpointing.
> - **Risk 3 (honesty) RESOLVED with 4-layer defense:** bundle `where`/`forbidden_claims` → writer-prompt ban → fact-check UNVERIFIABLE rule → blocking `safety.py` regex, each tested.
> - **P1 fixes:** (a) reganom is a **STANDALONE runner** (gpm_imerg pattern) — it does NOT touch `ExtremeSignalBundle`, `check_extreme_signals_for_cities`, `run_extreme_signals`, or `_two_bot_bundle_for_extreme_signal`; (b) `COUNTRY_SAMPLE_COORDS` derives from **`data/cities.csv`** (repo root) using the CSV's real country strings (`"US"` not `"United States"`); (c) the **annual cap is dropped for v1** (onset guard + `manual_only` + editorial bar gate volume — matches the wet-bulb plan); (d) **onset dedup** replaced with a country-scoped `reganom_last_fired` guard (date-keyed `event_id` alone re-fires daily).
> - **P2/P3 fixes:** scorer takes `sensitivity=10` (was a `TypeError`) + corrected calibration (minimal event totals **78**, not "~76"); `tests/test_thresholds.py` registry edit added; fact-check labels `g)`/`h)` (not the already-used `f)`); approval `manual_only` test added; `THEHEAT_REGANOM_ENABLED` defaults **OFF**; `load_daily_climatology` gets a default arg; cache-miss defensive lookups + leap-day `02-29→02-28` fallback; `SourceSkipped` handling; `date_range_days=12` to clear the ~5-day ERA5 archive lag.

# Reanalysis anomaly (regional/country scale) — implementation plan [HARDENED v3]

Detect when a *whole region's sampled cities* averaged far above climatological normal for ≥3 consecutive days. Single-city detection systematically misses "the entire Sahel is running 8°C above normal." Uses the existing Open-Meteo ERA5 archive + a one-time, checked-in daily climatology cache.

## Revision 3 deltas (Codex outside-voice + Andrew decisions, 2026-06-08)

These supersede the R1/R2 sections below where they overlap. Verified against live code; the codex artifacts are at `/tmp/partb_risk*.md` and the run output at the eng-review.

- **§A — Geo model: curated `REGION_WATCHLIST`, NOT auto-derived `COUNTRY_SAMPLE_COORDS` (DECISION T1, fixes the scale P0).** Auto-deriving from `data/cities.csv` gives **62 countries / 493 points** (verified) — 10× the ~50 verified scale, and "France" is a political bucket, not a climate region. Replace it with a hand-curated `REGION_WATCHLIST: tuple[RegionDef, ...]` of ~12–18 named entries, each with a display name + 4–8 representative `(lat, lon)` points — a mix of true regions ("Sahel": Niamey/Khartoum/N'Djamena/Agadez/Timbuktu) and countries ("France": Paris/Lyon/Marseille/Toulouse). Bounds total to ~80–120 points (so the "~50 batched coords / ~50 backfill requests" claims hold), mirrors the SST plan's 13-marquee-basin precedent, gives better signal from representative cities, and makes "across the Sahel" honest. `event_id = reganom_<region_slug>_<date>`. Keep the startup ≥3-points assertion. Curate from `data/cities.csv` + domain knowledge; do NOT iterate every CSV country.
- **§B — Trigger: σ floor + fraction-of-points support (DECISION T2 + codex #8).** Fire only when ALL hold: (a) point-mean anomaly ≥ **+6°C absolute**; (b) mean **z-score ≥ ~2.0** using the per-`MM-DD` σ already in the cache; (c) **≥ ~50% of the region's points individually exceed +6°C** (so one scorching city can't drag the mean over). The tweet still leads with the absolute °C; σ and fraction are gates + writer context. A flat +6°C is huge in the low-variance Sahel and unremarkable in high-variance continental winter — the σ floor makes the signal mean the same thing everywhere.
- **§C — Dated fetch (codex P0).** `fetch_all_reganom_t2m(all_points, date_range_days=12)` must return **dated rows** `{(lat,lon): list[(date_iso, temp_max)]}` — read `daily.time` beside the temps (pattern: `open_meteo.py:427`). `detect_regional_anomaly` aligns each `date → MM-DD` to the climatology and scans the most-recent N **complete** days, skipping the null/missing recent days created by the ~5-day ERA5 archive lag. Bare float lists (R2) can't do this.
- **§D — Attempt-time suppression (codex P0).** The R2 onset guard wrote `reganom_last_fired` only in `on_draft_success`, which fires only after a draft SAVES — so writer/safety/fact-check/triage kills re-enter the same event every day (repeated LLM spend). Fix: write the suppression marker (`reganom_last_fired[region] = window_start`) at **enqueue/attempt time**, not just on success. If `_enqueue_story_candidate` has no attempt-time hook, write it inline immediately before the enqueue call. Skip a region whose current `window_start ≤` its recorded value; a genuinely new event needs a later `window_start` (anomaly dropped below threshold then re-crossed). Persist via `_merge_state` (max-ISO-per-region).
- **§E — SQLite persistence direction CORRECTED (codex P1, verified).** `_METADATA_JSON_KEYS` (`sqlite_store.py:108`) is an **INCLUSION** list — keys in it persist; `_triage_queue` is excluded by **absence** (line 155). So: **ADD `reganom_last_fired`** to `_METADATA_JSON_KEYS` (it must persist), and **do NOT add `_reganom_live_cache`** (transient — leave it absent). R2's "add the live cache to the exclusion list" was backwards. Add a persistence test: `reganom_last_fired` survives save/load; `_reganom_live_cache` does not.
- **§F — Deterministic honesty gate = new Layer 0 (codex P1).** The R2 "4-layer honesty" leaned on prompt text + a deliberately permissive fact-checker ("when in doubt, ACCEPT"). Add a **deterministic, bundle-aware** check that runs BEFORE fact-check: for `signal_kind == "regional_anomaly"`, reject any draft whose text contains any `historical_context.forbidden_claims` substring (case-insensitive). This is now the **load-bearing** layer; the prompt rules + safety regex are backstops. Test it rejects each banned form and passes the correct "N sampled cities in X" form.
- **§G — Threshold is ranking, not gating (codex P1 — honesty).** The minimal qualifying event scores **78 > the 76 threshold**, so the score never rejects a detected event. State plainly: the **detection gate** (§B: ≥+6°C AND ≥2σ AND ≥50% point support, over ≥3 consecutive complete days, ≥3 points) is the noise filter; the 76 threshold + score are **ranking only**. The detection gate is strong, so this is acceptable for v1; revisit the threshold after the first live runs if marginal events slip through.

---

## Background

@theheat is a station-record detector. It knows when Phoenix broke its June 14 record, but it has no concept of "France just had its warmest sustained stretch averaged across its cities." @extremetemps fills that gap manually; this plan closes it programmatically — **honestly framed as a point index over N sampled cities, never an area-weighted national mean.**

### Contrast with existing signals

| Property | `anomaly_hot`/`anomaly_cold` | Part A `absolute_extreme` | Part B `reanalysis_anomaly` |
|---|---|---|---|
| Unit | Single city | Single city | Country / region (N sampled cities) |
| Trigger | today ≥ 15°C above *that city's* monthly mean | today ≥ absolute threshold for latitude band | sampled-city mean T2m ≥ +6°C above **daily** ERA5 normal for ≥3 days |
| Baseline | Open-Meteo 30-yr archive (live) | None | **Self-built daily ERA5 climatology cache** |
| `event_id` | `anomaly_hot_*` | `absextreme_*` | `reganom_*` |
| Category | `anomaly` (74) | `absolute_extreme` (78) | `regional_anomaly` (76) |
| New data | No | No | Yes — one-time climatology backfill |
| Integration | per-city extreme-signal loop | per-city extreme-signal loop | **standalone runner (gpm_imerg pattern)** |

---

## Integration architecture (READ FIRST — P1 fix)

**`reanalysis_anomaly` is a STANDALONE source runner**, structurally identical to `src/orchestrator/sources/gpm_imerg.py` (verified: it loads its data, detects, builds a bundle inline, and calls `_enqueue_story_candidate`). It is **NOT** part of the per-city extreme-signal machinery. It does **NOT** touch, and MUST NOT touch:

- `ExtremeSignalBundle` (no new field)
- `check_extreme_signals_for_cities` (no inclusion-gate edit)
- `run_extreme_signals` (no priority-cascade branch)
- `_two_bot_bundle_for_extreme_signal` at `src/orchestrator/common.py:1107-1142` (**no dispatch branch** — that path is only for per-city `strongest_type` bundles; a reganom branch there is dead code)

The only `common.py` edits are: import `score_regional_anomaly` from `src.editorial.scoring` and add it to `__all__` so the runner's `from src.orchestrator.common import *` resolves the bare `score_regional_anomaly(...)` call.

### Data flow

```
ONE-TIME (Step 0 GATE)                         PER ALERTS CYCLE (env-gated OFF)
──────────────────────                         ───────────────────────────────
build_climatology_cache.py                     run_reanalysis_anomaly(bot_state)
  │ ~50 reqs, 1991-2020/point                    │
  │ MM-DD mean+std, atomic ckpt                   ├─ THEHEAT_REGANOM_ENABLED != 1 ──► return 0
  ▼                                               ├─ load_daily_climatology() ─ absent ─► SourceSkipped→status=skipped
data/climatology_daily_cache.json  ────read───►  ├─ _reganom_live_cache[today]? ─ hit ─► reuse (no API)
  {country:{city:{days:{MM-DD:{mean_c,std_c}}}}}  │                              └ miss ─► fetch_all_reganom_t2m(ALL coords)
                                                  │                                         │ ONE batched archive req (~2.7s/50)
                                                  │                                         └ {} (total fail) ─► status=degraded, return 0
                                                  ▼
                                   for country in COUNTRY_SAMPLE_COORDS:   (per-country try/except — one gap ≠ abort all)
                                     detect_regional_anomaly(... live_temps ...)
                                       │ <3 valid coords / country|MM-DD cache miss ─► None (skip)
                                       │ 02-29 ─► fall back to 02-28
                                       ▼ ≥min_days consecutive ≥+6°C
                                     RegionalAnomalyEvent
                                       │ window_start ≤ reganom_last_fired[country] ─► skip (same ongoing event)  ◄── ONSET GUARD
                                       │ is_duplicate(event_id) ─► skip
                                       │ score < 76 ─► skip
                                       ▼
                                     build_regional_anomaly_bundle (4-layer honesty)
                                       ▼
                                     _enqueue_story_candidate(on_draft_success=set reganom_last_fired[country]=window_start)
                                       ▼ (manual_only) writer → safety regex → fact-check g)/h) → human review
```

Recommend embedding this diagram (and the onset-guard state transition) as comments in `src/orchestrator/sources/reanalysis_anomaly.py` and `src/data/reanalysis_anomaly.py`.

---

## Data sources

### Climatology: self-built DAILY ERA5 cache via `ARCHIVE_URL`

`ARCHIVE_URL = "https://archive-api.open-meteo.com/v1"` (`src/data/open_meteo.py:14`) exposes ERA5 `temperature_2m_max`/`_min` at daily granularity back to 1940. We build a 1991–2020 per-calendar-day mean + σ per sample point, cached as `data/climatology_daily_cache.json` (checked in).

**NASA POWER ruled out (verified 2026-06-08):** its climatology endpoint returns **monthly** values only (2001–2020, no σ, no daily). A daily reading vs a monthly normal creates month-boundary artifacts. Not suitable.

**Scale (CORRECTED — verified 2026-06-08):** a single archive request with `start_date=1991-01-01&end_date=2020-12-31` returns **all 10,958 daily rows in one response** (zero nulls, ~76ms). The backfill is therefore **~50 requests (one per sample point), ~2 min total** — NOT the ~1,500 requests / 15–30 min claimed in Revision 1. No year-chunking.

**Live detection fetch (Risk 1 RESOLVED):** the Open-Meteo ARCHIVE endpoint accepts comma-separated `latitude`/`longitude` lists and returns a JSON list in coord order — confirmed live (15 coords 0.62s; 50 coords 2.72s), identical to the Air-Quality API behavior. **All sample coords for all countries are fetched in ONE archive request per cycle.** No per-country fan-out.

Alternatives (out of scope for v1): Copernicus CDS ERA5 gridded (true area-weighted means; needs `CDS_API_KEY`+`cdsapi`) is the future authoritative upgrade.

---

## Signal definition & thresholds

Fires when a country's sampled cities averaged ≥ threshold above their daily ERA5 normal for ≥`min_days` consecutive days.

**Honest framing (non-negotiable):** a POINT INDEX over N sampled cities — never "[Country] averaged +X°C." Enforced at four layers (see Honesty section).

| Parameter | Value | Notes |
|---|---|---|
| Anomaly threshold | +6.0°C above 1991–2020 daily ERA5 normal | primary noise filter |
| Extreme threshold | +8.0°C | elite |
| Sustained window (`min_days`) | 3 | heat-wave minimum |
| Min sample cities | 3 | below 3 the mean is too noisy to claim |
| `date_range_days` (fetch) | **12** | covers `min_days` (3) + ~5-day ERA5 archive lag + margin; scan the most-recent N *complete* days, not calendar "today" |

**event_id:** `reganom_<region_slug>_<YYYY-MM-DD>` (`region_slug = name.replace(" ", "_")`), e.g. `reganom_India_2026-06-14`. The date is the window's last complete day.

**Category / threshold:** `regional_anomaly` → **76**. NOTE: the **3-day-consecutive + 6.0°C** gate in `detect_regional_anomaly` is the *primary* noise filter; the 76 threshold mainly screens degenerate near-6°C/3-day cases (see corrected calibration in Scoring).

---

## Onset dedup (P1 fix — date-keyed `event_id` is insufficient)

`event_id` embeds the date, so day-2 of a sustained event produces a *different* id (`reganom_India_2026-06-15`) and `posted_events` only records on draft success — so a 5-day heat wave would re-enter the writer pipeline **every day** (and never dedup if day-1's draft is killed). Fix: a country-scoped onset guard.

- New state key `reganom_last_fired: dict[str, str]` → `{country: window_start_date}`.
- On draft success (via `on_draft_success` callback), set `reganom_last_fired[country] = ev.window_start`.
- In the runner, **skip a country if its current consecutive window's `window_start` ≤ the recorded `reganom_last_fired[country]`** (same ongoing event). A genuinely new event fires only after the anomaly drops below threshold and re-crosses (new, later `window_start`).
- Persist in `DEFAULT_STATE` (`{}`) **and** add a `_merge_state` block taking the **max ISO date per country** (else concurrent gist/sqlite merges drop it).

**Annual cap: dropped for v1.** Revision 1 named `REGANOM_ANNUAL_CAP=12` but never wired it (it requires 4 coordinated edits). The onset guard + `manual_only` human gate + the editorial bar already cap volume hard (country-scale +6°C/3-day events are genuinely rare). This matches the wet-bulb plan's "no annual cap in v1; monitor first month." Add a cap post-calibration only if volume warrants.

---

## Files to create / modify

### New files

1. **`data/climatology_daily_cache.json`** (produced by backfill, checked in). Structure: `{country: {city_key: {"lat": f, "lon": f, "days": {"MM-DD": {"mean_c": f, "std_c": f, "mean_min_c": f}}}}}`.
2. **`scripts/build_climatology_cache.py`** — one-time backfill (see Step 0). Single 1991–2020 request per point; 429+5xx+transport backoff with full jitter; atomic per-point checkpoint; `--countries`/`--all`/`--delay-ms`/`--dry-run`/`--cache-path`; idempotent (skips already-cached points).
3. **`src/data/reanalysis_anomaly.py`** — `RegionalAnomalyEvent`, `COUNTRY_SAMPLE_COORDS: dict[str, dict[str, tuple[float, float]]]`, `load_daily_climatology(cache_path: str = "data/climatology_daily_cache.json")`, `fetch_all_reganom_t2m(all_coords, date_range_days=12)`, `detect_regional_anomaly(country, coords, climatology, live_temps, *, min_anomaly_c=6.0, min_days=3)`. Re-exports `ARCHIVE_URL` from `open_meteo`.
4. **`src/orchestrator/sources/reanalysis_anomaly.py`** — `run_reanalysis_anomaly(bot_state, current_run)` (standalone, gpm_imerg pattern).
5. **`tests/test_reanalysis_anomaly.py`**, **`tests/test_safety.py`** additions, **`tests/two_bot/test_intern.py`** additions, **`tests/test_editorial_approval.py`** addition.

### Modifications (verified anchors)

- `src/editorial/thresholds.py` — add `"regional_anomaly"` `ThresholdEntry(... , 76, ...)`.
- `src/editorial/scoring/temperature.py` — add `score_regional_anomaly` (with `sensitivity=10`).
- `src/editorial/scoring/__init__.py` — export `score_regional_anomaly`.
- **`tests/test_thresholds.py`** — add `"score_regional_anomaly": {"regional_anomaly"}` to `EXPECTED_THRESHOLD_KEYS_BY_FUNCTION` (the suite enforces a bidirectional registry contract — omitting this fails CI). `score_regional_anomaly` must call `get_threshold("regional_anomaly")` with a **string literal** (AST test requirement).
- `src/orchestrator/common.py` — import `score_regional_anomaly` + add to `__all__` (NO dispatch branch — see Integration architecture).
- `src/two_bot/intern/temperature.py` — add `build_regional_anomaly_bundle` (see Honesty section for the exact body).
- `src/two_bot/intern/__init__.py` — export `build_regional_anomaly_bundle`.
- `src/two_bot/prompts/writer_prompt.py` — add the `regional_anomaly` framing rules (THE BUNDLE) + a WHAT NEVER SHIPS bullet.
- `src/two_bot/prompts/fact_check_prompt.py` — add WORLD_KNOWLEDGE subsection **`g)`** + UNVERIFIABLE subsection **`h)`** (the `f)` label is already taken in both lists).
- `src/voice/safety.py` — append two narrow bare-country-aggregate regexes to `BANNED_PATTERNS`.
- `src/state.py` — add `reganom_last_fired: {}` to `DEFAULT_STATE` + a max-ISO-per-country `_merge_state` block.
- `src/orchestrator/run_alerts.py` — call `run_reanalysis_anomaly(bot_state, current_run)`, **env-gated OFF** by default.
- `src/storage/sqlite_store.py` — add `"_reganom_live_cache"` to `_METADATA_JSON_KEYS` exclusion (transient, like `_triage_queue`).
- `src/editorial/approval.py` — add `"regional_anomaly"` to the `manual_only` set (lines 164–190).

---

## Step-by-step implementation

### Step 0 (GATE) — backfill the climatology cache

Write `scripts/build_climatology_cache.py` and run it **before** writing detection logic; the cache must exist + spot-check before Steps 10–14.

Key elements (full spec verified 2026-06-08):

```python
def _fetch_archive_with_backoff(url, params, *, max_attempts=5, backoff_base=2.0):
    """fetch_with_retry does NOT retry 429; this wrapper does. Full jitter."""
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, params=params, timeout=60,
                                headers={"User-Agent": "(theheat-bot, contact@theheat.app)"})
            if resp.status_code == 429 or (500 <= resp.status_code < 600):
                if attempt < max_attempts - 1:
                    time.sleep(random.uniform(0, backoff_base * (2 ** attempt))); continue
            resp.raise_for_status(); return resp
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= max_attempts - 1: raise
            time.sleep(random.uniform(0, backoff_base * (2 ** attempt)))
    raise RuntimeError("backoff exhausted")
```

- **One request per point** spanning `1991-01-01..2020-12-31` (daily=`temperature_2m_max,temperature_2m_min`); group by `MM-DD`, compute `mean_c`/`std_c` (and `mean_min_c` for future cold-anomaly use — zero extra cost).
- **Atomic per-point checkpoint** (tmp-write→`replace`, pattern from `scripts/fill_missing_elevations.py:119-124`) after each point → crash-safe resume.
- **Skip detection:** `if country in cache and city_key in cache[country]: continue`.
- `--delay-ms` default **250** (240 req/min = 40% of the 600/min published forecast limit; archive limit undocumented but 3 rapid live tests showed no throttling).
- Spot-check: Paris July `mean_c` should be ~24–25°C (if ~13–15°C, you fetched `_min` not `_max`).
- **Completeness assertion:** verify each cached point has **365 (or 366) `MM-DD` keys** including `02-29` — a missing day KeyErrors at runtime (see cache-miss handling).

Run for 3 countries first, spot-check, then `--all` (10–15 launch countries).

### Step 10 — `src/data/reanalysis_anomaly.py`

**`COUNTRY_SAMPLE_COORDS` (P1 fix):** derive from **`data/cities.csv`** (repo root — `src/data/cities.csv` does NOT exist; the CSV has `city,country,lat,lon,elevation_m`, 638 rows; `open_meteo.load_cities()` is the canonical loader — reuse it). The CSV's country strings are authoritative: use **`"US"`** (42 cities), not `"United States"` (0). Type is `dict[str, dict[str, tuple[float, float]]]` (country → {city_key: (lat, lon)}) for backfill skip detection. **Startup assertion:** every key resolves to ≥3 CSV rows, else skip that country with a logged warning. Verified counts: France 3, Spain 7, Canada 8, India 17, Australia 17, China 24, Russia 14, Brazil 14, Pakistan 12; 50 countries have ≥4 cities. (Replace the Revision-1 "6 sampled cities in France" example — France has exactly 3 — with India/China.)

**`fetch_all_reganom_t2m(all_coords, date_range_days=12)`** — ONE batched archive request for all coords; returns `{(lat, lon): list[float] | None}`; `{}` on total failure. (Implementation per Risk 1 concrete design: comma-joined lat/lon, parse the JSON list in coord order, `temperature_2m_max` per coord.)

**`detect_regional_anomaly(country, coords, climatology, live_temps, *, min_anomaly_c=6.0, min_days=3)`** — for each sample point, `anomaly = today_t2m - climatology[country][city_key]["days"][mmdd]["mean_c"]`; average across points; require ≥`min_days` consecutive complete days ≥ `min_anomaly_c`. **Defensive lookups (P2 fix):** `climatology.get(country)` → return `None` if absent; `day_map.get(mmdd)` → skip that day if absent; handle `02-29` by falling back to `02-28`. Anchor the consecutive scan on the most-recent N **complete** days (ERA5 archive lags ~5 days).

### Step 11 — `src/orchestrator/sources/reanalysis_anomaly.py` (standalone)

Mirror `gpm_imerg.py`. Key points:

```python
def run_reanalysis_anomaly(bot_state: BotState, current_run: dict | None) -> int:
    source_drafted = 0
    if os.environ.get("THEHEAT_REGANOM_ENABLED", "0") != "1":   # P2: default OFF
        return 0
    start = time.perf_counter(); source_promoted = 0; country_timings = []
    try:
        from src.data.reanalysis_anomaly import (
            detect_regional_anomaly, COUNTRY_SAMPLE_COORDS,
            load_daily_climatology, fetch_all_reganom_t2m,
        )
        clim = load_daily_climatology()                 # may raise SourceSkipped if cache absent
        today = date.today().isoformat()
        state_dict = cast(dict, bot_state)
        cache = state_dict.get("_reganom_live_cache", {})
        if not (isinstance(cache, dict) and cache.get("date") == today and cache.get("results")):
            all_coords = [(lat, lon) for c in COUNTRY_SAMPLE_COORDS
                          for (lat, lon) in COUNTRY_SAMPLE_COORDS[c].values()]
            batch = fetch_all_reganom_t2m(all_coords)
            if not batch:                                # total failure → degraded, no crash
                _record_source_run(current_run, bot_state, "reanalysis_anomaly", start, status="degraded")
                return 0
            state_dict["_reganom_live_cache"] = {"date": today,
                "results": {f"{la},{lo}": v for (la, lo), v in batch.items() if v is not None}}
            cache = state_dict["_reganom_live_cache"]
        last_fired = state_dict.get("reganom_last_fired", {})
        for country, city_map in COUNTRY_SAMPLE_COORDS.items():
            try:
                live = {ck: cache["results"].get(f"{la},{lo}")
                        for ck, (la, lo) in city_map.items()}
                ev = detect_regional_anomaly(country, city_map, clim, live)
                if ev is None: continue
                if ev.window_start <= last_fired.get(country, ""): continue   # onset guard
                if state.is_duplicate(bot_state, ev.event_id): continue
                score = score_regional_anomaly(ev.mean_anomaly_c, ev.sustained_days, ev.cities_sampled)
                if not _should_draft(score, ev.event_id): continue
                source_promoted += 1
                from src.two_bot.intern import build_regional_anomaly_bundle
                bundle = build_regional_anomaly_bundle(ev)
                _enqueue_story_candidate(
                    bot_state, bundle=bundle, score=score, source="reanalysis_anomaly",
                    legacy_type="regional_anomaly", event_id=ev.event_id,
                    review_context=_review_context(...), cooldown_exempt=True,
                    on_draft_success=lambda c=country, ws=ev.window_start:
                        state.set_reganom_last_fired(bot_state, c, ws),   # onset guard write
                )
            except Exception as ce:
                print(f"[alerts] reganom {country} skipped: {ce}")        # one country's gap ≠ abort all
        _record_source_run(current_run, bot_state, "reanalysis_anomaly", start,
                           status="success", promoted=source_promoted,
                           details={"country_timings": country_timings})
    except SourceSkipped as s:
        _record_source_run(..., status="skipped", error=str(s))           # P3: cache-absent ≠ hard fail
    except Exception as e:
        state.log_error(bot_state, "reanalysis_anomaly", str(e))
        _record_source_run(..., status="failed", error=str(e))
    return source_drafted
```

`load_daily_climatology` raises `SourceSkipped` (exported from `common.py`) when the cache file is absent so a not-yet-backfilled deploy records `skipped`, not `failed`.

### Step 12 — wire into `run_alerts.py`

Call `run_reanalysis_anomaly(bot_state, current_run)` after the standalone-source calls. The default-OFF env gate (`THEHEAT_REGANOM_ENABLED`) makes the land a zero-change-on-land; the operator backfills + commits the cache, verifies, **then** sets `THEHEAT_REGANOM_ENABLED=1`.

### Step 13 — scoring / thresholds / approval

```python
def score_regional_anomaly(mean_anomaly_c, sustained_days, cities_sampled) -> EditorialScore:
    return _build_score(
        category="regional_anomaly",
        severity=72 + min(mean_anomaly_c - 6.0, 8) * 3 + min(sustained_days - 3, 7) * 2,
        novelty=84, timeliness=90,
        confidence=72 + min(cities_sampled, 8) * 1.5,
        shareability=80 + min(mean_anomaly_c - 6.0, 6) * 2,
        sensitivity=10,                                  # P2 FIX: was missing → TypeError
        threshold=get_threshold("regional_anomaly"),     # string literal (AST test)
        reasons=[...],
    )
```

**Corrected calibration (real `_shared` weights 0.28/0.24/0.16/0.16/0.16, −0.20·sensitivity):** minimal 6°C/3-day/3-city → total **78** (clears 76 by +2); elite 8°C/7-day/6-city → total **83**. (Revision 1's "~76 just clearing" was wrong.) Add a scoring unit test asserting these exact totals.

- `thresholds.py`: `"regional_anomaly": ThresholdEntry("regional_anomaly", 76, "Sampled-city regional anomaly from ERA5 daily climatology; point index, model-derived, manual-only at launch.")`
- `approval.py`: add `"regional_anomaly"` to the `manual_only` set. **Without this edit it defaults to `suggested_auto`+auto-approve** — the exact opposite of intent; guarded by the new approval test below.

### Step 14 — tests (expanded; eng-review R2 added the orchestrator/backfill/eval gaps)

- `tests/test_reanalysis_anomaly.py`: detection (fires 6°C/3-day, not 5°C, not 2-day, defensive cache-miss returns None, `02-29` fallback, `<3` valid coords → None) + `fetch_all_reganom_t2m` branches (**total failure → `{}`**, partial coord → `None`, coord-order mapping) + `load_daily_climatology` (default path, **missing file → `SourceSkipped`**) + `TestBuildRegionalAnomalyBundle` (where-contains-sampled, where≠bare-country, headline carries `cities_sampled`, rounding, `data_kind`, `forbidden_claims`).
- **`tests/test_reanalysis_anomaly_orchestrator.py` (NEW — every sibling source has one; the runner has the most branching):** env-gate OFF → no enqueue; **onset guard** (same `window_start` → skipped, later `window_start` → fires); `is_duplicate` skip; **degraded** (batch `{}` → status=degraded, 0 drafts, no crash); **SourceSkipped** (no cache → status=skipped, not failed); `on_draft_success` sets `reganom_last_fired[country]`; live-cache hit skips the fetch.
- **`tests/test_build_climatology_cache.py` (NEW):** `_fetch_one_point` MM-DD grouping + mean/std + `02-29` presence; skip-detection (already-cached point not re-fetched); `_fetch_archive_with_backoff` retries 429/5xx then succeeds (mock).
- `tests/two_bot/test_intern.py`: `test_build_regional_anomaly_bundle_where_contains_sampled_qualifier` (regression guard against the primary leak).
- `tests/test_safety.py`: `TestRegionalAnomalySafetyGate` — bare-country-averaged rejected (2 variants), sampled-cities form passes.
- `tests/test_editorial_approval.py`: assert `recommend_approval_policy("regional_anomaly", ...).mode == "manual_only"` and `can_auto_approve is False` (mirrors `test_precipitation_and_snow_require_manual_review`).
- `tests/test_thresholds.py`: the `EXPECTED_THRESHOLD_KEYS_BY_FUNCTION` edit (above) keeps the registry contract green.
- `tests/test_state.py`: `reganom_last_fired` survives `_merge_state` (max-ISO-per-country).
- **`[→EVAL]` REQUIRED (not optional):** a `voice_regression` fixture for `regional_anomaly` carrying the banned bare-country phrasing → assert fact-check/safety REJECT, and the correct sampled-cities phrasing → assert PASS. The writer-prompt + fact-check-prompt edits are LLM-prompt changes; layers 2–3 of the honesty defense are only verified by an eval, not a unit test. Without it, prompt drift silently re-opens the primary leak.

### Test coverage map (eng-review R2)

```
CODE PATHS                                                        COVERAGE
[+] src/data/reanalysis_anomaly.py
  ├── fetch_all_reganom_t2m()  ── batch ok / {} / partial-None     [★★★ planned: test_reanalysis_anomaly.py]
  ├── detect_regional_anomaly() ─ fire / 5°C / 2-day / <3 / miss / 02-29  [★★★ planned]
  └── load_daily_climatology()  ─ default path / missing→Skipped   [★★★ planned]
[+] src/orchestrator/sources/reanalysis_anomaly.py
  └── run_reanalysis_anomaly()  ─ env-gate / onset / dup / degraded / Skipped / on_success / cache-hit  [★★★ planned: NEW orchestrator test]
[+] src/editorial/scoring/temperature.py  score_regional_anomaly()  ─ exact totals 78/83   [★★★ planned]
[+] src/two_bot/intern/temperature.py     build_regional_anomaly_bundle()  ─ 4-layer honesty fields  [★★★ planned]
[+] src/voice/safety.py                   bare-country regex             ─ reject×2 / pass / city-pass  [★★★ planned]
[+] src/editorial/approval.py             regional_anomaly → manual_only  [★★★ planned]
[+] scripts/build_climatology_cache.py    _fetch_one_point / skip / backoff  [★★★ planned: NEW]
[+] src/two_bot/prompts/{writer,fact_check}_prompt.py  honesty layers 2-3  [→EVAL REQUIRED: voice_regression fixture]

COVERAGE: all planned-code branches have a planned test. Honesty layers 2-3 (prompts) covered by EVAL, not unit test.
```

---

## Honesty: point-index framing (4-layer defense — Risk 3 RESOLVED)

The signal is a mean over N sampled cities. Four leak paths exist (bare `where`; bare `current_facts.country`; bare `headline_metric`; the generous fact-checker). Defense at four independent layers:

**Layer 1 — bundle builder** (`build_regional_anomaly_bundle`, after `build_absolute_extreme_bundle`):
- `where = f"{ev.cities_sampled} sampled cities in {ev.country}"` — **never** bare `ev.country` (the `build_country_record_bundle` `where=cr.country` pattern is the wrong model here).
- `headline_metric.label = "sampled_city_mean_anomaly_c"` and carries `cities_sampled` so the writer can name N without touching `current_facts`.
- `current_facts` includes `data_kind: "point_index_not_area_weighted"`; `country` is retained **only** for `_audience_unit_facts` lookup (writer prompt forbids citing it alone).
- `historical_context.forbidden_claims = ["{country} averaged", "{country}'s average", "national mean", "area-weighted", "country-wide average", ...]` (same pattern as `build_all_time_record_bundle:244`).

**Layer 2 — writer prompt** (`writer_prompt.py`): a HARD `signal_kind == "regional_anomaly"` rules block in THE BUNDLE (always name N; never "[Country] averaged X°C"; `forbidden_claims` is a kill list) + a WHAT NEVER SHIPS bullet ("Bare country aggregate temperature for regional_anomaly bundles").

**Layer 3 — fact-check** (`fact_check_prompt.py`, the load-bearing bundle-aware gate): WORLD_KNOWLEDGE **`g)`** (mean_anomaly_c BUNDLE_FACT ±0.5°C, cities_sampled exact; bare-country-aggregate = UNVERIFIABLE) + UNVERIFIABLE **`h)`** (check the tweet against every `historical_context.forbidden_claims` entry; match = fail even if numbers are right). Use `g)`/`h)` — `f)` is already taken in both lists.

**Layer 4 — `safety.py` regex (BLOCKING, bundle-blind backstop):** two narrow patterns catching `"[Country] averaged +X°C"` / `"[Country]'s temperatures averaged X"`. Runs before fact-check (saves the LLM call, surfaces `stage="safety"`). Blocking — a bare-country aggregate is a factual misrepresentation, not a style nit, so it must NOT reach the manual-review queue even under `manual_only`.

(Full builder body, prompt text, and regex are in the hardening artifacts at `/tmp/partb_risk3_honesty.md`; the tests above pin all four layers.)

---

## State / caps / cooldowns

- **Dedup:** `state.is_duplicate` on `event_id` **plus** the `reganom_last_fired[country]` onset guard (the date-keyed id alone re-fires daily — see Onset dedup).
- **No per-city cooldown** (country signal); `cooldown_exempt=True`.
- **No annual cap in v1** (dropped — see Onset dedup).
- New state: `reganom_last_fired: dict[str, str]` in `DEFAULT_STATE` + max-ISO-per-country `_merge_state` block. Transient `_reganom_live_cache` excluded from SQLite persistence.

## Approval

`manual_only` at launch (ERA5 cache is new, the anomaly computation is the most complex signal, point-index framing needs editorial judgment). Escalate to `suggested_auto` only after 5+ clean approved drafts.

---

## What already exists (reused, not rebuilt)

- `ARCHIVE_URL` + the ERA5 archive integration (`open_meteo.py:14`) — reused for both backfill and live fetch; no new host.
- `open_meteo.load_cities()` — the canonical `data/cities.csv` loader; `COUNTRY_SAMPLE_COORDS` derives from it, not a re-parse.
- The standalone-runner shape (`gpm_imerg.py`), `_enqueue_story_candidate` + `on_draft_success`, `_record_source_run`, `SourceSkipped`, `is_duplicate` — all reused.
- `forbidden_claims` bundle pattern (`build_all_time_record_bundle`), `_audience_unit_facts`, the blocking voice/safety + fact-check gates — reused for the honesty defense.
- `fetch_with_retry` — reused where it fits (5xx); the backfill adds a 429-aware wrapper only because `fetch_with_retry` doesn't retry 429.

## NOT in scope (deferred, with rationale)

- **Gridded area-weighted national means (Copernicus CDS ERA5)** — the authoritative upgrade; needs `CDS_API_KEY` + `cdsapi`. v1 is honest point-index instead.
- **Annual cap** — dropped for v1; onset guard + `manual_only` + editorial bar gate volume (re-add post-calibration if needed).
- **Sub-national regions** ("US Southwest") — needs custom region geometry; country-level only for v1.
- **Sigma-based triggers (≥2.5σ)** — the cache stores σ, but v1 uses absolute +6°C (easier to fact-check); add later.
- **Cold-anomaly detection** — the cache stores `mean_min_c` at zero extra cost, but no detector wired in v1.

## Risks / open questions (post-hardening)

- **Risk 1 (fan-out): RESOLVED** by single batched request. *Residual:* the archive API has no published rate limit; under concurrent cron load it could 429/timeout → `fetch_all_reganom_t2m` returns `{}` → status `degraded`, no crash. `THEHEAT_REGANOM_ENABLED=0` is the kill-switch.
- **Risk 2 (backfill): RESOLVED** — ~50 requests, 429-aware backoff, atomic checkpoint resume. *Residual:* archive rate limit for sustained load is undocumented; at ~50 requests / 250ms pacing this stays well under any plausible threshold; partial-failure resumes on re-run.
- **Risk 3 (honesty): RESOLVED** with the 4-layer defense + tests. *Residual:* the bundle-blind safety regex can't condition on `signal_kind` (narrow by design to avoid false-positives on `"Paris averaged…"`); paraphrases that dodge the regex are caught by the bundle-aware fact-check `h)` rule. Add the voice-regression fixture so prompt drift is caught.
- **Cache staleness:** if `COUNTRY_SAMPLE_COORDS` gains a country without a cache entry, the startup assertion + per-country try/except degrade gracefully (that country skipped, logged); the rest run.

---

## Verification

```bash
source .venv/bin/activate
python -m mypy src/
python -m pytest tests/ -q -m "not voice_replay"
python -m ruff check src/data/reanalysis_anomaly.py src/orchestrator/sources/reanalysis_anomaly.py scripts/build_climatology_cache.py
# After backfill — coverage + per-day completeness:
python -c "
from src.data.reanalysis_anomaly import COUNTRY_SAMPLE_COORDS, load_daily_climatology
clim = load_daily_climatology()
for c in COUNTRY_SAMPLE_COORDS:
    assert c in clim, f'missing cache: {c}'
    for ck, pt in clim[c].items():
        assert len(pt['days']) >= 365, f'{c}/{ck} has {len(pt[\"days\"])} day-keys'
print('cache OK:', len(clim), 'countries')
"
```

---

## GSTACK REVIEW REPORT

| Review | Trigger | Runs | Status | Findings |
|--------|---------|------|--------|----------|
| Eng Review (R1) | `/plan-eng-review` | 1 | issues_found | 3 open risks flagged (fan-out, backfill, honesty); plan DEFERRED |
| Hardening pass (R2) | 4-agent workflow (3 risk-resolvers + adversarial gap-hunt), live code + live API | 1 | needs-rework → resolved | 3 risks RESOLVED (2 better than assumed); 4 P1 + 8 P2/P3 folded into R2 |
| Eng Review (R3) | `/plan-eng-review` (4-section + test map + diagram) | 1 | issues_found → folded | Sections clean post-R2; added test gaps (orchestrator/backfill/REQUIRED eval) + a data-flow ASCII diagram |
| Outside voice (R3) | Codex `codex exec` (read-only, high reasoning — cross-model) | 1 | issues_found → folded | 4 verified P0s + design issues the single-model passes missed; all folded into Rev 3 |

- **R2 folded:** standalone runner (no dispatch/ExtremeSignalBundle); cities.csv/`"US"`; annual cap dropped; onset guard; `sensitivity=10` + calibration; registry/approval/threshold tests; `THEHEAT_REGANOM_ENABLED` default OFF; cache-miss defenses + `02-29`; `date_range_days=12`.
- **R3 / CODEX (cross-model, all verified vs code):** P0 dated fetch (§C); P0 attempt-time suppression (§D); P0 geo scale → curated watchlists (§A); P1 SQLite direction corrected (§E); P1 threshold-is-ranking honesty (§G); P1 deterministic `forbidden_claims` gate (§F, new Layer 0). R3 test map added: orchestrator test, backfill-script test, REQUIRED honesty eval.
- **DECISIONS (Andrew, 2026-06-08):** T1 curated `REGION_WATCHLIST` (not country buckets); T2 σ/z-score floor + fraction-of-points support (§B).
- **CROSS-MODEL:** R2 (4-agent) and R3 (Codex) agreed the integration/state machinery was sound after R2. Codex's net-new catches — dated-fetch, attempt-time suppression, SQLite-direction-backwards, geo-scale 10×-off — were flagged by NEITHER single-model pass. The outside voice was load-bearing; keep it in the loop for high-stakes plans.
- **UNRESOLVED:** none — both forks decided, all P0/P1s folded.
- **VERDICT:** BUILD-READY pending Step 0 backfill, **after the §A `REGION_WATCHLIST` is curated**. Build **LAST** of the @extremetemps lane (Wave 1 = LANDED 2026-06-08; SST = Wave 2; this = after SST). Launches `manual_only`, env-gated OFF. The build agent MUST implement the Revision 3 deltas (§A–§G), not just the R1/R2 body.
