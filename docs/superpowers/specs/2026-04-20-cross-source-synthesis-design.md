# Cross-Source Story Synthesis — Design

**Date:** 2026-04-20
**Branch:** `andrewzp/synthesis-lane`
**Source brief:** `docs/conductor-lanes/04-cross-source-synthesis.md`

## 1. Mission

Add a meta-detection layer that fires a signal when three independent
per-source signals converge on the same US state within a 14-day window:
**D4 drought AND a qualifying wildfire AND a qualifying heat record.**
The compound story — "California is in exceptional drought, on fire, and
breaking heat records" — is more viral and more editorially valuable
than any of the three underlying tweets on its own.

This spec covers the **scaffolding** (state, regions, scoring, approval,
generator, orchestrator) plus **one rule** (`fire_drought_heat`). Later
rules (Marine×Coastal, Hurricane×Surge×Flood) plug into the same
scaffolding via separate PRs.

## 2. Key decisions

| # | Decision | Value |
|---|---|---|
| 1 | MVP scope | Scaffolding + `fire_drought_heat` only. Hurricane rule deferred (can't be validated outside season). Marine rule blocked on Lane 1. |
| 2 | Region matching | Static US state bounding boxes + disambiguation fallback (closest centroid; drop if ambiguous). Offline, zero deps, precise enough at the state level. |
| 3 | Cooldown | `bot_state["synthesis_cooldown"][rule_name][region] = last_fired_at`. 14-day cooldown per (rule, state). |
| 4 | Gate definitions | Drought = state appears in USDM snapshot (already pre-filtered to d3+d4 ≥ 10%) AND `d4_pct ≥ 1`. Fire = standalone `score_fire_event` passed within last 14 days. Heat = any of all-time, monthly, calendar-date record OR `abs(anomaly_c) ≥ 10` within last 14 days. |
| 5 | 14-day history | Rolling buffer in `bot_state["synthesis_components"]` with per-state lists for fires and heat events. Appended when per-source events pass their standalone gates. Expires items > 14 days old. |
| 6 | Drought source | Cache the last Friday USDM snapshot in `bot_state["synthesis_components"]["drought_snapshot"]`. Updated each Friday; read every cycle. |
| 7 | Event_id scheme | `synthesis_fdh_{state_key}_{iso_week}` — one unique id per (rule, state, ISO week). |
| 8 | Generation pipeline | Full existing pipeline: 4 Gemini candidates → safety (regex + LLM) → heuristic ranking → Sonnet evaluator → rewrite validation. No shortcuts. |
| 9 | Score threshold | 82. Synthesis is elite by definition — same tier as country records. |
| 10 | Approval policy | `suggested_auto`, 120-min delay. New policy key `synthesis_review`. |
| 11 | Per-cycle cap | Synthesis drafts count against the cap of 3. Being elite, they usually earn a slot. |
| 12 | Per-source suppression | None. Per-source tweets still ship (subject to city cooldown). Synthesis adds a story, doesn't replace. |
| 13 | Voice | Period-separated cadence. No invented causality. Time-range honesty ("in the last 14 days"). |

## 3. Architecture

```
run_alerts cycle
├── each per-source section (open_meteo, firms, …)
│   └── on passing its standalone editorial gate, ALSO:
│       └── state.record_synthesis_component(bot_state, state_name, component)
│           └── appends to bot_state["synthesis_components"][kind][state]
├── drought section (Fridays)
│   └── state.record_synthesis_drought_snapshot(bot_state, updates)
│       └── writes bot_state["synthesis_components"]["drought_snapshot"]
└── NEW: synthesis stage (last, after all sources)
    └── for each rule in rules:
        ├── detect() → list[SynthesisSignal]
        ├── for each signal:
        │   ├── dedup via event_id + cooldown check
        │   ├── score_synthesis_fire_drought_heat(...)
        │   ├── _should_draft(score, event_id)
        │   ├── generate_synthesis_fire_drought_heat_tweet(...)
        │   └── _save_generated_draft(...)  → suggested_auto, 120-min delay
        └── record_synthesis_fired(bot_state, rule_name, region)
    └── state.prune_stale_synthesis_components(bot_state)
```

The synthesis stage is **pure** over the rolling buffer + cached drought
snapshot. It does not re-fetch any external data. This isolates the
synthesis layer from all per-source fetch failures and keeps it
deterministic in tests.

## 4. Module layout

### New files

- `src/editorial/synthesis.py`
  - `@dataclass(frozen=True) class SynthesisSignal`
    - `rule_name: str` — e.g., `"fire_drought_heat"`
    - `region: str` — canonical state name, e.g., `"California"`
    - `event_id: str`
    - `headline: str` — for dashboard + review context
    - `components: dict` — structured facts for generator + scoring
    - `qualifying_window_days: int`
  - `detect_fire_drought_heat(bot_state) -> list[SynthesisSignal]`
    - Reads rolling buffer + drought snapshot from `bot_state`.
    - If `drought_snapshot` is missing or its `updated_at` is > 14 days
      old, return `[]` immediately.
    - For each state with `d4_pct ≥ 1.0` in the snapshot:
      - Collect fires for that state within last 14 days.
      - Collect heat events for that state within last 14 days.
      - Skip if either bucket is empty.
      - Skip if `is_synthesis_on_cooldown("fire_drought_heat", state)`.
      - Otherwise emit one `SynthesisSignal` summarising peak fire FRP,
        D4 pct, peak heat kind/value, and component counts.
    - Returns the list in no particular order — caller loops all.

- `src/editorial/_regions.py`
  - `STATE_BOUNDING_BOXES: dict[str, tuple[float, float, float, float]]`
    — `(min_lat, max_lat, min_lon, max_lon)` for each of 50 states + DC.
  - `STATE_CENTROIDS: dict[str, tuple[float, float]]` — `(lat, lon)`.
  - `lat_lon_to_state(lat: float, lon: float) -> str | None`
    - Returns canonical state name, or `None` if outside US or ambiguous
      without a clear centroid winner.
    - Disambiguation: if 2+ boxes match, pick the state whose centroid
      is closest; if the closest centroid is > 500 km from the point,
      return `None`.

- `tests/test_synthesis.py` — unit tests for `detect_fire_drought_heat`.
- `tests/test_regions.py` — unit tests for `lat_lon_to_state`.
- `tests/test_state_synthesis.py` — unit tests for state helpers.

### Modified files

- `src/editorial/scoring.py`
  - New: `score_synthesis_fire_drought_heat(drought_d4_pct, fire_peak_frp, heat_peak_anomaly_c, component_count, heat_kind) -> EditorialScore`
  - Threshold 82. Category `"synthesis_fire_drought_heat"`.
  - Factor weights (see §7 below).

- `src/editorial/approval.py`
  - `recommend_approval_policy`: add case for `tweet_type ==
    "synthesis_fire_drought_heat"` → `synthesis_review`,
    `suggested_auto`, 120-min delay.

- `src/voice/templates.py`
  - `SYNTHESIS_SYSTEM_PROMPT` — extends base system prompt with:
    - "Use period-separated short beats, not comma chains."
    - "Do not invent causality between the three components."
    - "Use specific windows — 'in the last 14 days' or exact dates."
    - "Anchor to one state. Name it. Make it the subject."

- `src/voice/generator.py`
  - `generate_synthesis_fire_drought_heat_tweet(*, state, drought_d4_pct, fire_peak_frp, fire_peak_region, heat_peak_city, heat_peak_kind, heat_peak_value_c, window_days, return_bundle=True)`
  - Builds a structured data description, passes through existing
    4-candidate generation + safety + ranking + evaluator.
  - Template fallback: hand-written single string if Gemini fails 3×.

- `src/state.py`
  - Helpers:
    - `record_synthesis_component(state, *, kind, region, event_id, metadata, timestamp)` — kinds `"fire"`, `"heat"`.
    - `get_synthesis_components(state, *, kind, region, since) -> list`
    - `record_synthesis_drought_snapshot(state, updates) -> None`
    - `get_synthesis_drought_snapshot(state) -> list[dict]`
    - `is_synthesis_on_cooldown(state, rule_name, region, days=14) -> bool`
    - `record_synthesis_fired(state, rule_name, region, timestamp) -> None`
    - `prune_stale_synthesis_components(state, ttl_days=14) -> None`
  - New keys in `bot_state`:
    ```json
    {
      "synthesis_components": {
        "fires":   { "California": [ {"event_id","frp","region","at"}, ... ] },
        "heats":   { "California": [ {"event_id","kind","city","value_c","at"}, ... ] },
        "drought_snapshot": {
          "updated_at": "2026-04-17",
          "entries": [ {"state","d3_pct","d4_pct","total_drought_pct"}, ... ]
        }
      },
      "synthesis_cooldown": {
        "fire_drought_heat": { "California": "2026-04-20T14:00:00Z" }
      }
    }
    ```

- `src/main.py`
  - At each per-source section that produces a draft:
    - After `state.record_event(...)`, additionally call
      `state.record_synthesis_component(...)` for fires and
      heat-record types (only for US states).
  - In the drought section (Fridays):
    - After building drafts, call
      `state.record_synthesis_drought_snapshot(bot_state, drought_updates)`.
  - **New section 12**: synthesis stage at the end of `run_alerts`.
    - `synthesis_start = time.perf_counter()`
    - `signals = synthesis.detect_fire_drought_heat(bot_state)`
    - For each signal: dedup, score, draft, record.
    - `state.prune_stale_synthesis_components(bot_state)`
    - `_record_source_run(current_run, "synthesis_fire_drought_heat", …)`

- `docs/PIPELINE.md` — add a new stage between per-source sections and
  State Write describing the synthesis layer and its rules.

- `BRIEFING.md` — one paragraph mentioning that the pipeline now has a
  cross-source synthesis layer.

## 5. Data flow

**Per-source contribution (today):**

1. Open-Meteo processes a city bundle; a calendar-date record for
   Sacramento passes `score_record_event`.
2. `_save_generated_draft` stores the draft.
3. `state.record_event(bot_state, ev.event_id)` marks posted.
4. **New:** `state.record_synthesis_component(bot_state, kind="heat",
   region="California", event_id=ev.event_id, metadata={"kind":
   "calendar", "city": "Sacramento", "value_c": ev.new_temp_c},
   timestamp=now)` — because Sacramento is in California.

**Drought Friday:**

1. `drought.fetch_drought_data()` returns per-state drought %.
2. Existing drought-summary tweet is generated as today.
3. **New:** `state.record_synthesis_drought_snapshot(bot_state,
   updates)` — stores the full snapshot for synthesis reads over the
   next 7 days.

**Synthesis stage (every alerts cycle):**

1. Read `drought_snapshot` → filter states with `d4_pct >= 1.0`.
2. For each such state, read `synthesis_components.fires[state]` and
   `synthesis_components.heats[state]`, filtered to last 14 days.
3. If both non-empty AND cooldown not active → emit `SynthesisSignal`.
4. Score, draft, approve → same pipeline as any other draft.

## 6. Region matching

`lat_lon_to_state(lat, lon)`:

1. Collect all states whose bounding box contains the point.
2. Zero matches → return `None`.
3. One match → return that state.
4. 2+ matches → compute great-circle distance from the point to each
   candidate's centroid. Return the closest. If the closest is > 500 km
   (the point is not actually in any state), return `None`.

The `STATE_BOUNDING_BOXES` constants are derived from public Census
Bureau state extents, hardcoded as floats with 2-decimal precision. We
deliberately **do not** ship a GeoJSON file. The inherent imprecision is
acceptable because the rule is state-level, not county-level, and a fire
on the Nevada-California border assigned to one or the other does not
change the editorial story.

For Open-Meteo heat records, per-record `CityBundle` / event objects
carry `city` + `country` but not lat/lon. We build a per-cycle map
`cities_to_state_map(cities) -> {city_name: state_name}` once in
`run_alerts` (using `lat_lon_to_state` over each US entry's coordinates
from `load_cities`). Each per-source recording call looks up the
pre-computed state. Non-US cities are absent from the map, so the
recording call is a no-op.

## 7. Scoring

```python
def score_synthesis_fire_drought_heat(
    *, drought_d4_pct: float,      # 0–100
    fire_peak_frp: float,          # MW
    heat_peak_anomaly_c: float,    # °C above mean (fallback to record gap)
    component_count: dict,         # {"fires": int, "heats": int}
    heat_kind: str,                # "all_time" | "monthly" | "calendar" | "anomaly"
) -> EditorialScore:
```

Factor design:

| Factor | Value | Reason |
|---|---|---|
| severity | `60 + d4_pct*0.3 + min(frp,1500)/25 + min(anom,15)*1.8` | All three severities matter. D4 in 10% of state + 1000 MW fire + 10 °C anomaly → ~90. |
| novelty | `88 + (6 if heat_kind == "all_time" else 0)` | Synthesis is inherently novel; all-time record bumps it. |
| timeliness | `90` | All 3 components within 14 days. |
| confidence | `78` | Three independent data sources agreeing is strong corroboration. |
| shareability | `82 + (4 if fires.count >= 2 else 0) + (4 if heats.count >= 2 else 0)` | Multiple fires / records per state reads as "the whole state is in it." |
| sensitivity | `28` | Fires affect people; moderate restraint. |

Threshold: **82**. Reasons list: the top 3 of "`{d4_pct}% of {state} in
exceptional drought", "{frp:.0f} MW fire near {region}", "{city} broke
{kind} heat record", "three independent signals converged".

## 8. Voice and tweet generation

`SYNTHESIS_SYSTEM_PROMPT` (extends base `SYSTEM_PROMPT`):

```
This is a cross-source synthesis tweet. Three independent signals have
converged on a single US state within the last 14 days:
1. The US Drought Monitor says {D4_PCT}% of {STATE} is in exceptional drought.
2. NASA FIRMS has flagged a wildfire: {FRP} MW near {FIRE_REGION}.
3. Open-Meteo recorded a {HEAT_KIND} heat {EVENT} at {HEAT_CITY} ({VALUE}).

Rules:
- Anchor the tweet to {STATE}. Name it. It is the subject.
- Use period-separated short beats. "Drought. Fire. Record heat. All in
  California. All this month." NOT commas-and-ands chaining.
- Do NOT invent causality. Do not say the heat caused the fire or the
  drought caused the fire. Say the three things co-occur.
- Use the honest time range: "in the last 14 days" or specific dates.
  Never "recently" or "now."
- Do not lecture about climate change. Show the three signals. Let the
  reader connect them.
```

Generator wiring: `generate_synthesis_fire_drought_heat_tweet` is a thin
wrapper that builds the data description, calls the shared
`_generate_with_candidates` helper (same infrastructure every other
tweet type uses), and returns a bundle with candidates + chosen + safety
report + eval report.

## 9. Orchestrator integration

At the start of `run_alerts`, declare:

```python
synthesis_start = time.perf_counter()   # placed at the end of run_alerts
```

Per-source mutations needed (small, localized):

- **Open-Meteo extreme signals loop** — after `state.record_event(...)`
  for each of `record`, `all_time_high`, `monthly_high`, `anomaly_hot`,
  call `state.record_synthesis_component` if the city's state resolves.
  Country records are already whole-country, so we record them against
  the peak city's state.
- **FIRMS** — after `state.record_event(fire.event_id)`, call
  `state.record_synthesis_component(kind="fire", region=<state>, ...)`
  if `lat_lon_to_state(fire.lat, fire.lon)` is non-None.
- **Drought (Fridays)** — after drought-summary draft handling, call
  `state.record_synthesis_drought_snapshot`.

At the very end of `run_alerts` (before Hot 10, which runs separately):

```python
print("[alerts] Running cross-source synthesis…")
try:
    signals = synthesis.detect_fire_drought_heat(bot_state)
    for sig in signals:
        if state.is_duplicate(bot_state, sig.event_id):
            continue
        if state.is_synthesis_on_cooldown(bot_state, sig.rule_name, sig.region):
            continue
        score = score_synthesis_fire_drought_heat(...sig.components...)
        if not _should_draft(score, sig.event_id):
            continue
        generated = generator.generate_synthesis_fire_drought_heat_tweet(...)
        ctx = _review_context(...)
        if _save_generated_draft(generated, bot_state,
            "synthesis_fire_drought_heat", sig.event_id, score,
            review_context=ctx):
            state.record_event(bot_state, sig.event_id)
            state.record_synthesis_fired(bot_state, sig.rule_name, sig.region)
            drafted += 1
    state.prune_stale_synthesis_components(bot_state)
    _record_source_run(current_run, "synthesis_fire_drought_heat", synthesis_start,
        status="success", observed=len(signals), promoted=...)
except Exception as e:
    print(f"[alerts] Synthesis error: {e}")
    state.log_error(bot_state, "synthesis_fire_drought_heat", str(e))
    _record_source_run(current_run, "synthesis_fire_drought_heat", synthesis_start,
        status="failed", error=str(e))
```

The synthesis stage is wrapped in try/except so a bug here cannot break
the rest of the alerts cycle.

## 10. Error handling and edge cases

| Case | Behavior |
|---|---|
| City outside US (Open-Meteo) | `lat_lon_to_state` returns `None`; `record_synthesis_component` is skipped. Synthesis only fires on US states. |
| Fire lat/lon ambiguous (2+ state boxes, no clear centroid) | `lat_lon_to_state` returns `None`; skip. |
| Drought snapshot older than 14 days (e.g., fetch has been failing) | Treat as missing. Synthesis emits no signals. Log note in source run. |
| Cooldown active but condition still true | Silent skip. Next eligible date is `last_fired_at + 14d`. |
| Two rules both fire for same state on same day | Each emits separately; per-cycle cap of 3 still applies. (Only one rule in MVP, so not a current concern.) |
| `bot_state["synthesis_components"]` missing (fresh state) | Helpers auto-create empty structure on first write. |
| Signal passes scoring but Gemini fails 3× on safety | Template fallback — a deterministic, hand-written compound string using the structured facts. |

## 11. Testing plan

### `tests/test_regions.py`

- Interior points → correct state (LA, Sacramento, Austin, Miami, Anchorage).
- Border points where one state clearly wins via centroid distance
  (e.g., Lake Tahoe → California over Nevada).
- Non-US points return `None` (Mexico City, London, Pacific Ocean).
- Far-from-any-centroid return `None`.

### `tests/test_state_synthesis.py`

- `record_synthesis_component` appends and preserves fields.
- `get_synthesis_components(since=7_days_ago)` filters correctly.
- `prune_stale_synthesis_components` removes items > 14 days old.
- `is_synthesis_on_cooldown` returns `True` within 14 days, `False`
  outside.
- `record_synthesis_drought_snapshot` stores the full list.

### `tests/test_synthesis.py`

- **Happy path:** populate state with D4 drought entry for California,
  one fire in California in last 7 days, one calendar-date heat record
  in Sacramento in last 3 days. Assert `detect_fire_drought_heat`
  returns one signal with `region == "California"`.
- **Missing drought:** same state minus drought → no signal.
- **Missing fire:** same state minus fire → no signal.
- **Missing heat:** same state minus heat record → no signal.
- **Region mismatch:** fire in California, heat record in Arizona, D4
  in California → no signal (Arizona lacks fires, California lacks
  heat).
- **Stale fire:** fire 20 days old → pruned/ignored; no signal.
- **Cooldown:** after signal fires, calling again same day → no
  signal.
- **Cooldown expiry:** fast-forward 15 days, re-qualify → new signal.
- **Drought snapshot stale:** drought_snapshot older than 14 days →
  no signal.

### `tests/test_editorial_scoring.py` (existing file — add cases)

- Min-viable synthesis (D4 1%, FRP 200 MW, anomaly 4 °C, single fire,
  single heat) — expect score just above threshold.
- Elite synthesis (D4 40%, FRP 1500 MW, all-time record) — expect
  score in the mid-90s.

### Full-suite green

`pytest` must pass in its entirety. The synthesis stage must not affect
any existing test's outcome.

## 12. Rollout

- Default to `suggested_auto` with 120-min delay. First ~10 synthesis
  drafts reviewed manually on the dashboard before anyone hits "auto".
- Manual rollback: set `bot_state["synthesis_enabled"] = False` and
  `detect_*` returns `[]` without reading anything. A one-line toggle
  in case the rule produces bad output in the wild.

## 13. Definition of Done

- [ ] `src/editorial/synthesis.py` + `src/editorial/_regions.py`
      implemented.
- [ ] `score_synthesis_fire_drought_heat` in `scoring.py`.
- [ ] Approval policy case in `approval.py`.
- [ ] Generator + template additions.
- [ ] State helpers + new `bot_state` keys.
- [ ] `run_alerts` wires per-source contributions and runs synthesis at
      end.
- [ ] All three test files green.
- [ ] `pytest` full suite green.
- [ ] `BRIEFING.md` updated; `docs/PIPELINE.md` updated with synthesis
      stage.
- [ ] PR description includes: one example of a rule-fired test payload
      rendered through the generator (Gemini output or fallback).

## 14. Non-goals

- No general LLM-driven synthesis layer (this is named-rules-only).
- No re-fetching external data in the synthesis stage.
- No additional rules in this PR beyond `fire_drought_heat`.
- No suppression of per-source tweets when synthesis fires.
- No support for non-US regions in this rule (US Drought Monitor is
  US-only; the rule is structurally US-bound).

## 15. Budget

Reasoning complexity > data-source complexity, per the lane brief.
Expected effort: ~6 hours coding, ~2 hours tests, ~1 hour docs/PR.
Total: ~9 hours for the first rule.
