# Ocean SST & Marine Heatwaves — Design Spec

**Lane:** Lane 1 (see `docs/conductor-lanes/01-ocean-sst-marine-heatwaves.md`)
**Date:** 2026-04-20
**Branch:** `andrewzp/ocean-sst-lane`
**Status:** Design approved, ready for implementation plan

---

## Mission

Add NOAA OISST-derived global mean sea surface temperature as a new data
source for @theheat. Fire tweets when the global ocean posts consecutive
days above the archive record for the calendar day-of-year. Editorial bar:
genuinely extreme only — "400th consecutive day" style signal, not daily
anomaly reporting.

This plugs the largest gap in current coverage: the ocean stores most of
the excess planetary warming, yet we track only atmospheric land extremes
and wave heights. Kalmus' verified-viral ocean-record material in
`brand/EXEMPLARS.md` is the exemplar for this signal.

---

## Ratified decisions (from brainstorming)

The design below is scoped by four decisions made during brainstorming.
Each was chosen over alternatives for reasons captured in the
"Choices & rationale" section at the end of this document.

1. **Detection scope: global-mean only, archive-high streak.** No basin
   means, no Hobday 90th-percentile flagging in the MVP.
2. **Fire cadence: first-fire + milestones, with a 5-day MHW-style
   confirmation window.** First tweet fires at day 5 of a streak above
   the archive record; subsequent tweets only at milestone days.
3. **Data source: ClimateReanalyzer (University of Maine) JSON.** Single
   fetch gives today's global-mean SST plus the full 1981→present archive
   for computing the day-of-year max. NOAA PSL documented as secondary
   source for a future hardening pass.
4. **Bootstrap: silent seed + fire on next natural milestone.** On first
   deploy, observe current streak state without tweeting. Future runs
   fire at the next milestone the streak crosses naturally — avoids the
   dishonest framing of retroactively announcing a streak we didn't
   observe in real time.

---

## Architecture

New source slots into `run_alerts` alongside the existing `ocean` (waves)
source. Fetch + detection live in a single stateless module. Streak
lifecycle bookkeeping lives in `state.py`, mirroring the existing
`update_record_streak` pattern.

```
ClimateReanalyzer JSON (primary source)
        │
        ▼
  fetch_global_sst() ──► GlobalSSTObservation
        │
        ▼
  detect_streak_milestone(obs, prior_streak_state)
        │
        ├─► None  (silent seed, routine extension, or already-fired milestone)
        └─► MarineHeatwaveStreakEvent  (kind: first | milestone)
        │
        ▼
  score_marine_heatwave  (threshold 78)
        │
        ▼
  generator.generate_marine_heatwave_tweet
        │
        ▼
  approval: suggested_auto / 90min delay
        │
        ▼
  _save_generated_draft → Gist state
```

**Boundary discipline:**

- `src/data/ocean_sst.py`: pure fetch + pure detection. No state mutation.
  Fetch derives today's reading *and* the current streak from the
  ClimateReanalyzer payload. Detection takes the prior (minimal) streak
  state as input and returns a new state plus an optional event.
- `src/state.py`: owns the persisted `ocean_sst_streak` dict (two fields:
  `seeded`, `last_milestone_fired`) and provides
  `update_ocean_sst_streak(state, new_state)` — isolates state shape
  from detection logic.
- `src/main.py::run_alerts`: orchestrates fetch → detect → score →
  generate → save, plus `_record_source_run` telemetry.

**Why streak is derived from data, not state:** ClimateReanalyzer returns
the full current-year daily array in one fetch, so we can walk backward
from today to compute the authoritative streak length on every run. This
keeps the "Nth consecutive day" claim factually defensible even if our
own cron has outages — the data source is the source of truth, and we
never accumulate drift between our counter and reality.

---

## File plan

**New files:**

- `src/data/ocean_sst.py` — fetch + detection (stateless)
- `tests/test_ocean_sst.py` — module tests

**Edits:**

- `src/state.py`
  - Add `ocean_sst_streak` to `DEFAULT_STATE`
  - Merge in `_merge_state` (always take incoming, like `record_streaks`)
  - Add `update_ocean_sst_streak(state, streak_dict)` helper
- `src/editorial/scoring.py`
  - Add `score_marine_heatwave(days, peak_anomaly_c, years_of_data)` with
    threshold 78
- `src/editorial/approval.py`
  - Add `marine_heatwave` branch: `suggested_auto`, 90-min delay
- `src/editorial/candidates.py`
  - Add `CATEGORY_HINTS["marine_heatwave"] = ("ocean", "record", "consecutive")`
- `src/voice/templates.py`
  - Add `marine_heatwave_template(kind, days, today_c, archive_max_c,
    archive_max_year, years_of_data)`
- `src/voice/generator.py`
  - Add `generate_marine_heatwave_tweet(...)` using `generate_tweet` with
    category `"marine_heatwave"` and the fallback template
- `src/main.py`
  - Add `run_alerts` section between `ocean` (waves) and `water_levels`
- `tests/test_main.py`
  - Integration test: mocked fetch produces a day-5 crossing → one draft
    saved under category `marine_heatwave`
- `BRIEFING.md`
  - Add source to data-source list; add threshold 78 to scoring table
- `PIPELINE.md`
  - Add node to the Mermaid flow diagram under RAW sources

---

## Data contracts

```python
# src/data/ocean_sst.py

@dataclass(frozen=True)
class GlobalSSTObservation:
    date: str                  # "YYYY-MM-DD" — the day this observation represents
    day_of_year: int           # 1-366
    today_c: float             # global-mean SST, degrees Celsius
    archive_max_c: float       # prior max for today's day-of-year, 1982 → last-full-year
    archive_max_year: int      # year the prior max was set
    years_of_data: int         # archive span for honest framing (e.g., 44)

    # Streak is computed from the ClimateReanalyzer payload itself — not
    # from our observation cadence — by walking backward from today's
    # day-of-year and counting consecutive days where that day's current-
    # year value strictly exceeds the archive max for that day-of-year.
    # This makes the "Nth consecutive day" claim factually defensible
    # regardless of cron gaps on our side.
    streak_days: int                  # 0 if today is not above record
    streak_start_date: str | None     # date of the first day in the current streak
    streak_peak_anomaly_c: float      # max (value - archive_max) over the streak

@dataclass(frozen=True)
class MarineHeatwaveStreakEvent:
    kind: str                  # "first" | "milestone"
    days: int                  # milestone day count being announced (e.g., 5, 25, 400)
    peak_anomaly_c: float      # max anomaly seen across the current streak
    today_c: float
    archive_max_c: float
    archive_max_year: int
    years_of_data: int
    date: str                  # observation date
    event_id: str              # "marine_heatwave_streak_{days}_{date}"
```

### State shape

New top-level key in `DEFAULT_STATE`:

```python
"ocean_sst_streak": {
    "seeded": False,                # flips True after first successful observation
    "last_milestone_fired": None,   # last milestone day already tweeted, or None
}
```

Rationale for this minimal shape:

- Streak length, start date, and peak anomaly are all **computed from
  the ClimateReanalyzer payload** on every run. Persisting them would
  risk drift between our copy and the source of truth.
- State only retains the two things we cannot recompute: whether we've
  ever run before (`seeded`) and which milestone we most recently
  tweeted (`last_milestone_fired`), for idempotency.
- `last_milestone_fired` resets to `None` when the observation shows the
  streak has broken (`streak_days == 0`).

`_merge_state` treats `ocean_sst_streak` like `record_streaks` — take
the incoming (most recent) dict.

---

## Detection logic

### Milestone ladder

```python
MILESTONES = (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)
# After 400: every +50 (450, 500, 550, ...).

def _milestones_up_to(days: int) -> tuple[int, ...]:
    """All milestone thresholds <= days, in ascending order.

    Day 47 → (5, 10, 25). Day 450 → (5, 10, 25, 50, 100, 150, 200,
    250, 300, 365, 400, 450). Used to pick the largest unfired
    milestone (see emission rule below).
    """
```

### Streak derivation inside `fetch_global_sst`

After locating today's `day_of_year` and the current-year array, the
fetcher walks backward to compute `streak_days`:

```
# Pseudocode inside fetch_global_sst — runs once per fetch
current_year_arr = payload[str(current_year)]
prior_year_arrs = [payload[str(y)] for y in range(1982, current_year)]

def archive_max_for_doy(doy: int) -> tuple[float, int] | None:
    vals = [(arr[doy - 1], 1982 + i)
            for i, arr in enumerate(prior_year_arrs)
            if 0 <= doy - 1 < len(arr) and arr[doy - 1] is not None]
    return max(vals) if vals else None  # (value, year)

streak_days = 0
streak_start_doy = None
streak_peak = 0.0

for doy in range(today_doy, 0, -1):
    v = current_year_arr[doy - 1]
    amax = archive_max_for_doy(doy)
    if v is None or amax is None:
        break
    if v > amax[0]:
        streak_days += 1
        streak_start_doy = doy
        streak_peak = max(streak_peak, v - amax[0])
    else:
        break
# (If streak spans across Jan 1 into prior calendar year, extend walk
#  into current_year - 1 array. Edge case; see spec below.)
```

Today's `archive_max_c` / `archive_max_year` come from
`archive_max_for_doy(today_doy)`.

### Per-run emission rule

```
obs = fetch_global_sst()
prior = state["ocean_sst_streak"]  # {"seeded": bool, "last_milestone_fired": int | None}

if obs is None:
    return None  # fetch failure — no state change, logged by caller

# 1. Silent seed on first-ever observation
if not prior["seeded"]:
    new_state = {"seeded": True,
                 "last_milestone_fired": None}
    return (new_state, None)

# 2. Streak broken → clear last_milestone_fired, no event
if obs.streak_days == 0:
    new_state = {"seeded": True, "last_milestone_fired": None}
    return (new_state, None)

# 3. Below the first-fire threshold
if obs.streak_days < 5:
    # Preserve prior last_milestone_fired — we're in a new streak that
    # hasn't yet earned a tweet, but the prior one might still be
    # remembered. Normally prior is None here anyway.
    return (prior, None)

# 4. Find the largest milestone that has not yet fired this streak
already_fired = prior["last_milestone_fired"] or 0
crossed = max(
    (m for m in _milestones_up_to(obs.streak_days) if m > already_fired),
    default=None,
)
if crossed is None:
    return (prior, None)  # streak continuing but no new milestone

event = MarineHeatwaveStreakEvent(
    kind="first" if crossed == 5 and already_fired == 0 else "milestone",
    days=crossed,
    peak_anomaly_c=obs.streak_peak_anomaly_c,
    today_c=obs.today_c,
    archive_max_c=obs.archive_max_c,
    archive_max_year=obs.archive_max_year,
    years_of_data=obs.years_of_data,
    date=obs.date,
    event_id=f"marine_heatwave_streak_{crossed}_{obs.date}",
)
new_state = {"seeded": True, "last_milestone_fired": crossed}
return (new_state, event)
```

Key properties:

- **No backfill tweets.** Bootstrap (`seeded == False`) is silent.
- **No duplicate fires.** `last_milestone_fired` + the global
  `posted_events` dedup (500-event window) both guard against repeats.
- **Streak break resets cleanly.** Next streak starts fresh at day 5.
- **Missed milestones don't double-fire.** If cron misses several runs
  and we re-enter at day 47, we fire day 25 (next unfired milestone),
  not both day 10 and day 25.

### Edge cases

| Case | Behavior |
|---|---|
| First-ever run | Silent seed. `seeded: True`, no tweet, `last_milestone_fired: None`. |
| Same-day re-run (cron overlap) | Fetch returns the same `streak_days`. If no new milestone crossed vs. `last_milestone_fired`, no event. Idempotent. |
| Data source returns 5xx / malformed JSON | `fetch_global_sst` returns `None`. Run logs error via `state.log_error`, skips cleanly. No state change. |
| Archive max equals today (tie) | Not above record. Streak break. Template requires strict new high. |
| 1-day blip (day 1, then drops) | No tweet — needs ≥5 days. Blip breaks → `last_milestone_fired` stays `None`. |
| Cron outage during an active streak | Irrelevant. Streak is derived from the payload on every run; a 7-day gap still reports the correct current streak. |
| Streak continues past day 400 | Milestones every +50 (450, 500, ...). |
| Streak spans New Year | Backward walk continues into the previous year's array when today's year runs out. Spec tests cover this. |
| Leap year day 366 on non-leap years | Archive max for doy 366 uses only the four leap years' doy-366 values; if fewer than 3 years, fall back to doy 365. Validation flag logged for transparency. |
| Payload today-value missing (null) | Use the most recent non-null current-year index as "today". Log a 1-day lag note for transparency. |

---

## Fetch details

**Primary source:**
`https://climatereanalyzer.org/clim/sst_daily/json/oisst2.1_world_sst_day.json`

Response shape (confirmed in spec): an object keyed by year-string
(e.g., `"1982"`, `"1983"`, ..., `"2026"`), each mapping to an array of
daily global-mean SST values (length 365 or 366 for leap years). Values
may be null for dates beyond "today" in the current year.

Client-side derivation:

1. Find the **most recent non-null** index in the current year's array →
   that index is today's `day_of_year - 1`; the value is `today_c`; the
   observation `date` is derived by adding that offset to Jan 1 of the
   current year.
2. For every prior year 1982 → (current_year - 1), read the value at the
   same day-of-year index. Drop nulls. Take max → `archive_max_c`,
   `archive_max_year`.
3. `years_of_data = current_year - 1982` (OISST v2.1 starts Sep 1981;
   1982 is the first full year).

Validation helper rejects: missing current-year key, all-null current
year, archive years < 30, obvious unit mismatch (e.g., values outside
[-2, 40]°C). On any validation failure → return `None`.

**Secondary (deferred to a future PR):** NOAA PSL precomputed global-mean
SST CSV from `psl.noaa.gov/data/correlation/`. Same contract. Documented
here so the hardening pass has a known target; not built in this lane.

---

## Scoring

```python
# src/editorial/scoring.py

def score_marine_heatwave(
    days: int,
    peak_anomaly_c: float,
    years_of_data: int,
) -> EditorialScore:
    reasons = [
        f"{days}-day streak above the daily archive record",
        f"peak {peak_anomaly_c:+.2f}°C above prior daily max",
        f"{years_of_data}-year satellite record",
    ]
    if days >= 100:
        reasons.append("triple-digit consecutive-day streak")
    if peak_anomaly_c >= 0.5:
        reasons.append("half-degree anomaly on a global mean")

    return _build_score(
        "marine_heatwave",
        severity=72 + min(days / 4.0, 22) + min(peak_anomaly_c * 10, 10),
        novelty=80 + min(days / 10.0, 10),
        timeliness=86,
        confidence=92,     # single well-known dataset, low ambiguity
        shareability=80 + min(days / 20.0, 12),
        sensitivity=6,     # low human-harm — ecological framing only
        threshold=78,
        reasons=reasons,
    )
```

**Threshold 78** matches the spec and lands between `simultaneous_records`
(78) and `all_time_record` (80). At day 5, peak anomaly ~0.2°C, the score
lands ~80-82 — comfortably passing. At day 100, ~90 — elite.

---

## Voice & approval

### Template

```python
# src/voice/templates.py

def marine_heatwave_template(
    kind: str,        # "first" | "milestone"
    days: int,
    today_c: float,
    archive_max_c: float,
    archive_max_year: int,
    years_of_data: int,
) -> str:
    if kind == "first":
        variants = [
            f"The global ocean has now been above the daily record for "
            f"{days} straight days in {years_of_data} years of satellite "
            f"data. Today: {today_c:.2f}°C. Prior daily max: "
            f"{archive_max_c:.2f}°C, set {archive_max_year}.",
            f"Five consecutive days of record-breaking global ocean "
            f"surface temps. Today's mean: {today_c:.2f}°C. The previous "
            f"record for this date was {archive_max_c:.2f}°C in "
            f"{archive_max_year}. Archive goes back {years_of_data} years.",
        ]
    else:
        variants = [
            f"The global ocean just posted its {days}th consecutive day "
            f"above the daily record in {years_of_data} years of "
            f"satellite data. Today: {today_c:.2f}°C.",
            f"{days} consecutive days and counting. Global mean SST "
            f"today: {today_c:.2f}°C. Old record for this date: "
            f"{archive_max_c:.2f}°C ({archive_max_year}). "
            f"{years_of_data}-year archive.",
        ]
    return random.choice(variants)
```

**Voice rules honored:**

- Leads with the stake, not the agency.
- States archive window explicitly (`{years_of_data} years of satellite
  data`). No "ever" / "all-time."
- Specific numbers; avoids "unprecedented."
- No press-release opener, no meta-commentary.

### Generator

```python
# src/voice/generator.py

def generate_marine_heatwave_tweet(
    kind: str,
    days: int,
    today_c: float,
    archive_max_c: float,
    archive_max_year: int,
    years_of_data: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    data = (
        f"Global-mean sea surface temperature is at {today_c:.2f}°C today. "
        f"That's above the daily record for this calendar day ({archive_max_c:.2f}°C, "
        f"set in {archive_max_year}) and it's the {days}th consecutive day this has been true. "
        f"Archive goes back {years_of_data} years (NOAA OISST v2.1). "
        f"Today's date: {date.today().strftime('%B %d, %Y')}."
    )
    return generate_tweet(
        data,
        category="marine_heatwave",
        return_bundle=return_bundle,
        fallback_fn=templates.marine_heatwave_template,
        fallback_args={
            "kind": kind, "days": days, "today_c": today_c,
            "archive_max_c": archive_max_c,
            "archive_max_year": archive_max_year,
            "years_of_data": years_of_data,
        },
    )
```

### Approval

```python
# src/editorial/approval.py
if tweet_type == "marine_heatwave":
    return ApprovalPolicy(
        key="marine_heatwave_review",
        mode="suggested_auto",
        recommended_delay_minutes=90,
        can_auto_approve=True,
        reason="Ocean-SST streak signal — low human-harm risk, high "
               "accuracy from a single well-known dataset. Short review "
               "window lets a human polish framing before auto-post.",
    )
```

---

## `run_alerts` integration

New section inserted between `ocean` (waves, currently step 9) and
`water_levels` (step 10). Runs every cycle.

```python
# main.py pseudocode
print("[alerts] Checking global ocean SST...")
sst_start = time.perf_counter()
try:
    obs = ocean_sst.fetch_global_sst()
    source_promoted = 0
    source_drafted = 0
    if obs is not None:
        prior_streak = bot_state.get("ocean_sst_streak", state.DEFAULT_STATE["ocean_sst_streak"])
        result = ocean_sst.detect_streak_milestone(obs, prior_streak)
        if result is not None:
            new_streak, event = result
            state.update_ocean_sst_streak(bot_state, new_streak)
        else:
            event = None

        if event and not state.is_duplicate(bot_state, event.event_id):
            score = score_marine_heatwave(event.days, event.peak_anomaly_c, event.years_of_data)
            if _should_draft(score, event.event_id):
                source_promoted = 1
                generated = generator.generate_marine_heatwave_tweet(
                    kind=event.kind,
                    days=event.days,
                    today_c=event.today_c,
                    archive_max_c=event.archive_max_c,
                    archive_max_year=event.archive_max_year,
                    years_of_data=event.years_of_data,
                    return_bundle=True,
                )
                review_context = _review_context(
                    source="NOAA OISST v2.1 (ClimateReanalyzer)",
                    source_key="ocean_sst",
                    headline=f"Global ocean SST streak: day {event.days}",
                    current_run=current_run,
                    facts=[
                        _fact("Streak length", f"{event.days} consecutive days above record"),
                        _fact("Today's global-mean SST", f"{event.today_c:.2f}°C"),
                        _fact("Prior daily max", f"{event.archive_max_c:.2f}°C ({event.archive_max_year})"),
                        _fact("Peak anomaly during streak", f"{event.peak_anomaly_c:+.2f}°C"),
                        _fact("Archive span", f"{event.years_of_data} years"),
                    ],
                )
                if _save_generated_draft(generated, bot_state, "marine_heatwave",
                                         event.event_id, score,
                                         review_context=review_context):
                    state.record_event(bot_state, event.event_id)
                    drafted += 1
                    source_drafted = 1
    _record_source_run(
        current_run, "ocean_sst", sst_start,
        status="success",
        observed=1 if obs is not None else 0,
        promoted=source_promoted,
        drafted=source_drafted,
    )
except Exception as e:
    print(f"[alerts] Ocean SST error: {e}")
    state.log_error(bot_state, "ocean_sst", str(e))
    _record_source_run(
        current_run, "ocean_sst", sst_start,
        status="failed", error=str(e),
    )
```

---

## Tests

### `tests/test_ocean_sst.py`

- `test_fetch_global_sst_happy_path` — fixture JSON with 3 prior years +
  current year populated through April. Asserts correct `today_c`,
  `day_of_year`, `archive_max_c`, `archive_max_year`, `years_of_data`,
  `streak_days`, `streak_peak_anomaly_c`.
- `test_fetch_global_sst_streak_stops_at_first_non_exceedance` — current
  year exceeds archive for 3 days then a 4th day does not → `streak_days=3`.
- `test_fetch_global_sst_streak_crosses_new_year` — today is Feb 3; Jan
  values and prior Dec values all above prior archive-max → streak spans
  both arrays and counts correctly.
- `test_fetch_global_sst_returns_none_on_empty_current_year` — current
  year array all nulls.
- `test_fetch_global_sst_returns_none_on_http_error` — `requests.get`
  raises.
- `test_fetch_global_sst_rejects_out_of_range_values` — value 100°C
  rejected.
- `test_fetch_global_sst_handles_today_null_uses_latest_non_null` —
  most recent non-null index becomes "today".
- `test_detect_first_run_silent_seed` — `seeded=False`; any observation
  returns state update with `seeded=True` and no event.
- `test_detect_streak_under_5_no_fire` — seeded, obs.streak_days=4 → no
  event.
- `test_detect_day_5_first_fire` — seeded, obs.streak_days=5 → event
  with `kind="first"`, `days=5`, state updated to `last_milestone_fired=5`.
- `test_detect_milestone_crossing` — prior `last_milestone_fired=25`,
  obs.streak_days=50 → event with `kind="milestone"`, `days=50`.
- `test_detect_no_refire_same_milestone` — prior `last_milestone_fired=50`,
  obs.streak_days=50 (same-day re-run) → no event.
- `test_detect_skip_missed_milestones` — prior `last_milestone_fired=5`,
  obs.streak_days=47 → event with `days=25` (next unfired milestone,
  highest ≤ 47).
- `test_detect_streak_break_clears_last_fired` — prior
  `last_milestone_fired=50`, obs.streak_days=0 → state updated with
  `last_milestone_fired=None`, no event.
- `test_detect_tie_is_not_above` — fetcher computes streak break when
  today equals archive max; detect returns no event.
- `test_detect_past_400_every_50` — prior `last_milestone_fired=400`,
  obs.streak_days=450 → event with `days=450`.

### `tests/test_editorial_scoring.py`

- `test_score_marine_heatwave_day_5_passes_threshold` — score.total ≥ 78.
- `test_score_marine_heatwave_day_100_is_elite` — score.total ≥ 85.

### `tests/test_editorial_approval.py`

- `test_marine_heatwave_suggested_auto_90min`.

### `tests/test_main.py`

- `test_run_alerts_ocean_sst_drafts_on_day_5` — mock `ocean_sst.fetch_global_sst`
  to return a day-5 crossing; mock generator; assert:
  - 1 draft saved with `tweet_type == "marine_heatwave"`.
  - Draft includes review context with streak day count.
  - `posted_events` records the event ID.
  - `_record_source_run` called with `ocean_sst` source, `drafted=1`.

---

## Definition of Done

- [ ] Fetch verified against live ClimateReanalyzer JSON endpoint
      (manual test note in PR).
- [ ] Detection fires on day-5 fixture; suppresses day-4 and under.
- [ ] Bootstrap first-run is silent.
- [ ] Milestone skip (missed cron) fires next unfired milestone only.
- [ ] Generator produces text passing existing safety pipeline.
- [ ] `run_alerts` integration test in `tests/test_main.py` wires the
      full path.
- [ ] Full suite green: `python -m pytest`.
- [ ] `BRIEFING.md` updated: source added, threshold listed.
- [ ] `PIPELINE.md` updated: new source node in flow diagram.
- [ ] No new secrets required (ClimateReanalyzer is public, no auth).

---

## Non-goals

- **No basin means** (North Atlantic, Tropical Pacific, etc.). Scoped out
  with the "global-only" decision; future lane can layer in.
- **No Hobday 90th-percentile MHW flag.** Archive-high streak is the
  viral story; the academic MHW definition is deferred.
- **No grid fetching.** ClimateReanalyzer returns an aggregate already.
- **No individual-buoy readings.**
- **No daily "today's anomaly" tweet.** CO2-weekly trap avoided.
- **No coral bleaching / fish die-off / ecosystem downstream stories.**
- **No streak-ended tweet.** Streak break is silent.

---

## Budget

- 1 new module (`src/data/ocean_sst.py`, ~200 LOC including dataclasses
  and detection helper).
- 1 new test file (`tests/test_ocean_sst.py`, ~12 tests).
- 8 edits to existing files (state, scoring, approval, candidates,
  templates, generator, main, test_main).
- 2 doc edits (BRIEFING, PIPELINE).
- ~6-8 hours focused work.
- 1 live API probe required.

---

## Choices & rationale

Decisions made during brainstorming, with alternatives considered and why
each was rejected. Preserved here so future maintenance understands
*why* the design looks this way.

### 1. Detection scope — global-only archive-high streak

**Chosen over:**
- *Global + 5 basin means.* 6× climatologies, 6× streak states, 6×
  frequency-cap risk. Marginal novelty per basin relative to the global
  signal, which is the one with verified-viral precedent.
- *Global + Hobday 90th-percentile MHW flag.* Adds a second signal type
  (scoring, template, generator) for a definition that is more academic
  than viral. The global archive-record streak captures the same extreme
  with less code.

**Rationale:** The Kalmus exemplar in `brand/EXEMPLARS.md` and the viral
"Nth consecutive day" charts from 2023-2024 are all powered by the global
archive-record streak. One number per day, one streak state, one tweet
pattern. Matches the "utility, not business" and "extreme only" editorial
principles. Basins and MHW flagging remain available as future lanes.

### 2. Fire cadence — first-fire at day 5 + milestones, MHW-aligned

**Chosen over:**
- *Fire every day the streak extends.* Would flood the feed during long
  streaks and rely entirely on the 2-tweet/week cap to throttle. Brittle
  and cap-dependent.
- *Milestone-only (no day-5 first-fire).* Would bury the newsworthy
  "hottest daily global SST in 44 years" moment until day 25.

**Rationale:** The 5-day confirmation window follows Hobday et al. 2016's
MHW definition (SST above threshold for ≥5 consecutive days), giving
factual integrity: no single-day spikes firing as "records" before
reverting. Milestones afterward (5, 10, 25, 50, 100, 150, 200, 250, 300,
365, 400, then +50) naturally pace to well under 2 tweets/week even on
indefinite streaks.

### 3. Data source — ClimateReanalyzer JSON (primary), NOAA PSL (deferred fallback)

**Chosen over:**
- *NOAA PSL CSV only.* Would require maintaining a separate climatology
  file (ship `data/ocean_sst_archive_max.csv` with 366 rows, refreshed
  annually). More moving parts; brittle if climatology stale.
- *Build our own aggregator from the 0.25° OISST grid via ERDDAP.*
  Gigabytes per fetch. Explicitly rejected by the spec's non-goals.

**Rationale:** ClimateReanalyzer's endpoint is the canonical source for
this exact signal — it's the dataset behind the viral 2023-2024 charts.
Single fetch returns current year plus the full 1982→present archive, so
today's value and the day-of-year archive max come from one payload. No
climatology file to maintain, no auth required, no grid work. NOAA PSL is
documented as a future hardening target if ClimateReanalyzer's format
changes.

### 4. Bootstrap — silent seed + fire on next natural milestone

**Chosen over:**
- *Announce current state on first run.* Dishonest framing — we'd be
  tweeting about days we didn't observe in real time. Violates the
  honest-framing rule ("hottest in 30 years of records," not "hottest
  ever").
- *Silent seed + forward-only, no catch-up.* Would bury a legitimately
  ongoing record streak forever; first tweet might be days-away even if
  today is already day 187.

**Rationale:** Silent seed preserves honesty; firing at the next natural
milestone lets the compounding story surface without retroactive claims.
A one-line `seeded: bool` flag in state enforces the rule
deterministically — no ambiguity about whether a given run is the first.

### 5. State boundary — detection is stateless, streak is data-derived

**Chosen over:**
- *Putting streak mutation logic inside `ocean_sst.py`.* Same reasoning
  as existing `update_record_streak` in `state.py`: keeps the data
  module testable with pure fixtures.
- *Tracking streak length in state (days, start_date, last_date,
  peak_anomaly) across runs.* Brittle to cron outages — a 7-day gap
  would reset a legitimately-continuing streak. Also risks drift
  between our counter and what ClimateReanalyzer would say.

**Rationale:** The ClimateReanalyzer payload contains the full current-
year daily array, so the streak can be computed from the data on every
run. State only retains what we genuinely can't recompute: `seeded`
(first-run discrimination) and `last_milestone_fired` (idempotency).
This is a ~2-field state footprint, and the "Nth consecutive day" claim
stays factually defensible regardless of our own run cadence.
