# Lane 2 — Ice Mass (GRACE-FO) — Design

**Status:** Design, pending implementation plan
**Author:** Andrew Puschel (with Claude)
**Date:** 2026-04-20
**Origin:** `docs/conductor-lanes/02-ice-events.md`

## Goal

Detect and tweet extreme ice-mass-loss events for Greenland and Antarctica
using the NASA GRACE-FO mission's Level-4 mascon mass anomaly time series.
Fire a signal at most ~8 times/year, only at clear editorial milestones:
a new largest-ever monthly loss, or a cumulative-loss threshold crossing.

## Scope (MVP)

- Greenland + Antarctica. **Not** global glaciers (no clean single PODAAC
  product; deferred).
- Two detectors: monthly-loss record + cumulative-loss milestone.
- One Gemini-generated tweet category: `ice_mass_record`.
- Earthdata Login plumbing via bearer token — first authenticated upstream
  in the project.

## Non-goals

- GLIMS glacier outlines (deferred).
- NSIDC daily melt area (contradicts editorial bar).
- Individual glacier tracking (Thwaites, Pine Island).
- Conflating mass loss with sea-level rise in the same tweet.

## Data source

**PODAAC Level-4 mass anomaly time series (ASCII):**
- Greenland: `GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4`
- Antarctica: latest RL06.3 Antarctica time series (exact URL pinned as
  a constant; update in one place when the product version bumps)

Files are plain-text, 1 row per month, columns roughly
`time_decimal_year mass_gt uncertainty_gt`. Monthly cadence, ~1-2 month
publication lag. Parser derives `YYYY-MM` from decimal year via
`int((decimal - year) * 12)`.

**Auth:** Earthdata Login bearer token.
- Env var: `EARTHDATA_TOKEN` (user-generated app token from
  urs.earthdata.nasa.gov).
- Fetcher sends `Authorization: Bearer <token>` header.
- 401/403 or missing token → `fetch_grace_mass` returns `[]` and logs
  a friendly "Earthdata token not configured" message, mirroring the
  `GIST_ID`/`GITHUB_TOKEN` pattern in `src/state.py`.
- `BRIEFING.md` gets a "Required secrets" update.

## Architecture

### New data module: `src/data/ice_mass.py`

Dataclasses:

```python
@dataclass
class IceMassReading:
    region: str              # "greenland" | "antarctica"
    month: str               # "YYYY-MM"
    mass_gt: float           # mass anomaly vs mission baseline (negative = below)
    uncertainty_gt: float
    event_id: str            # f"ice_mass_{region}_{month}"

@dataclass
class IceMassRecord:
    region: str
    kind: str                # "monthly_loss_record" | "cumulative_milestone"
    # Monthly record fields (populated when kind == "monthly_loss_record"):
    month: str | None
    monthly_delta_gt: float | None   # month-over-month change (negative = loss)
    previous_worst_gt: float | None
    previous_worst_month: str | None
    # Cumulative milestone fields (populated when kind == "cumulative_milestone"):
    threshold_gt: float | None       # e.g. -5000.0
    current_mass_gt: float | None
    event_id: str
```

Functions:
- `fetch_grace_mass(region: str) -> list[IceMassReading]` — sorted oldest → newest.
- `detect_monthly_record(readings, state) -> IceMassRecord | None` — computes month-over-month delta for the **latest** reading and compares against `state["ice_mass_max_loss"][region]["gt"]`. Fires on a more-negative delta.
- `detect_cumulative_milestone(readings, state) -> IceMassRecord | None` — fires when the latest cumulative anomaly crosses the next `-1000` Gt floor below the last-fired threshold for that region.

**Monthly record definition:** absolute archive-wide record, not calendar-month-specific. Rationale: the iconic headline is "largest monthly loss ever recorded," and melt is seasonally concentrated enough that records naturally land in July/August without needing calendar-month comparison.

**Milestone step size:** `-1000` Gt for both regions. Greenland crosses one every ~2-3 years; Antarctica ~4-5. Rare enough that the 8/year cap isn't under pressure from milestones alone.

### State additions — `src/state.py`

New `DEFAULT_STATE` keys:

```python
"ice_mass_max_loss": {},      # {region: {"gt": float, "month": "YYYY-MM"}}
                              # `gt` is the month-over-month delta (negative = loss).
                              # Worst = most-negative value ever observed.
"ice_mass_last_milestone": {},# {region: float}  e.g. {"greenland": -5000}
                              # Last cumulative threshold fired; next milestone
                              # is 1000 Gt further negative.
"ice_mass_last_seen": {},     # {region: "YYYY-MM"}  — short-circuit key
"ice_annual_count": {},       # {year: int}  — cap 8/yr (both kinds combined)
```

`_merge_state` additions (same spirit as `co2_annual_count`):
- `ice_mass_max_loss` — per region, keep the entry with the more-negative `gt`.
- `ice_mass_last_milestone` — per region, take the lower (more-negative) threshold.
- `ice_mass_last_seen` — per region, take the lexicographically-later `YYYY-MM`.
- `ice_annual_count` — per year, take the max (identical to co2).

Rationale: under concurrent writes, last-writer-wins would lose state. Taking the extreme in each direction preserves the invariant that once we've seen a record, it stays seen.

### Scoring — `src/editorial/scoring.py`

```python
def score_ice_mass_event(
    region: str,
    kind: str,
    *,
    monthly_delta_gt: float | None = None,
    previous_worst_gt: float | None = None,
    threshold_gt: float | None = None,
) -> EditorialScore:
```

**Threshold:** 78.

Monthly-loss record dimensions:
- severity: `72 + (|delta| - 300) * 0.15`, floor 60
- novelty: 90
- timeliness: 64
- confidence: 96
- shareability: `78 + margin_over_previous * 0.1`
- sensitivity: 8

Cumulative milestone dimensions:
- severity: `76 + |threshold| / 1000 * 2`
- novelty: 82
- timeliness: 60
- confidence: 96
- shareability: 84
- sensitivity: 8

Reasons (3 shown in UI):
- Monthly: `"largest monthly loss since GRACE began (N yrs)"`, `"previous worst: X Gt in YYYY-MM"`, `"GRACE-FO gravimetry"`.
- Milestone: `"cumulative loss crosses -X Gt"`, `"region: greenland|antarctica"`, `"GRACE-FO gravimetry"`.

### Template — `src/voice/templates.py`

```python
def ice_mass_template(
    region: str,
    kind: str,
    *,
    month: str | None = None,
    monthly_delta_gt: float | None = None,
    years_of_record: int | None = None,
    threshold_gt: float | None = None,
) -> str
```

Monthly variants:
- `"{Region} lost {loss} gigatons in {Month Year}. The largest monthly loss in {N} years of GRACE observations."`
- `"{Region}: {loss} Gt of ice gone in {Month Year} alone. That's the worst single-month loss in the {N}-year GRACE record."`

Milestone variants:
- `"{Region} has now lost more than {X} gigatons of ice since 2002, per GRACE. A threshold first crossed this month."`
- `"Cumulative ice loss from {Region} passes {X} Gt. GRACE has been watching since 2002."`

No personification ("dying", "suffering"). No scale anchors in the fallback (Gemini may attempt them).

### Generator — `src/voice/generator.py`

`generate_ice_mass_tweet(region, kind, *, month, monthly_delta_gt, previous_worst_gt, previous_worst_month, threshold_gt, current_mass_gt, years_of_record, return_bundle=False)`

Builds a data string with region, kind, month, delta, previous record + year, GRACE start year (2002), years-of-record window. Calls `generate_tweet(category="ice_mass_record", fallback_fn=templates.ice_mass_template, fallback_args=...)` — same shape as `generate_sea_ice_record_tweet`.

### Category hint — `src/editorial/candidates.py`

```python
"ice_mass_record": ("GRACE", "gigatons", "ice"),
```

Single category covers both kinds — they share voice rules and facts.

### Approval policy — `src/editorial/approval.py`

```python
if tweet_type == "ice_mass_record":
    return ApprovalPolicy(
        key="ice_mass_review",
        mode="suggested_auto",
        recommended_delay_minutes=105,
        can_auto_approve=True,
        reason="GRACE ice-mass milestone — rare, elite signal. Mid-length review window for framing polish.",
    )
```

105 min sits between co2 (90) and country_record (120), matching the spec's 90-120 range.

### Main orchestrator — `src/main.py`

New constants:
```python
ICE_ANNUAL_CAP = 8
```

New helpers (mirroring co2):
- `_ice_annual_cap_reached(bot_state, cap=ICE_ANNUAL_CAP) -> bool`
- `_increment_ice_annual_count(bot_state) -> None`

New section in `run_alerts`, inserted after the drought block. Runs **Mondays only** (weekly gate — same pattern as sea ice). Per-region loop with short-circuit and cap check:

```
For region in ("greenland", "antarctica"):
  If cap reached → skip
  Fetch readings. Empty → mark success/observed=0
  latest_month = readings[-1].month
  If state["ice_mass_last_seen"][region] == latest_month → skip (already processed)
  detect_monthly_record → if None, detect_cumulative_milestone
  If record and not duplicate:
    score → _should_draft → generate → _save_generated_draft
    On success: record_event, _increment_ice_annual_count
    Update state["ice_mass_max_loss"][region] or state["ice_mass_last_milestone"][region]
  Always: update state["ice_mass_last_seen"][region] = latest_month
```

The short-circuit prevents re-processing the same month every Monday until new data drops.

Mondays only matches sea ice and is more than enough for a monthly-cadence source.

## Data flow

```
run_alerts (Monday)
  ├── for region in (greenland, antarctica):
  │     ├── fetch_grace_mass → [IceMassReading...]  (or [] on auth/network fail)
  │     ├── latest_month short-circuit
  │     ├── detect_monthly_record(readings, state) → IceMassRecord | None
  │     ├── detect_cumulative_milestone(readings, state) → IceMassRecord | None
  │     ├── score_ice_mass_event → EditorialScore
  │     ├── generate_ice_mass_tweet → CandidateBundle
  │     ├── recommend_approval_policy("ice_mass_record") → ApprovalPolicy
  │     └── _save_generated_draft → drafts[] + state updates
  └── state.persist
```

## Testing

New `tests/test_ice_mass.py`:
1. **Fetch** (5 cases): happy Greenland, happy Antarctica, malformed rows skipped, 401 returns [], missing token returns [].
2. **Monthly record** (4): fires on new record, no-fire when not record, seeds state on first run, single-reading edge case.
3. **Cumulative milestone** (4): fires on -5000 crossing, no re-fire at -5100 once -5000 fired, subsequent -6000 fires, no fire if already beyond last-fired.
4. **Short-circuit** (1): `ice_mass_last_seen` prevents re-evaluation within same month.

Additions to existing test files:
- `test_editorial_scoring.py` — 3 cases for `score_ice_mass_event`.
- `test_editorial_approval.py` — 1 case for `ice_mass_review` policy.
- `test_generator.py` — 1 case for `generate_ice_mass_tweet` with responses mock + fallback.
- `test_main.py` — integration test: Monday + fixture → draft + state updated; non-Monday → skipped.
- `test_state.py` — 2 cases: `_merge_state` preserves most-negative `ice_mass_max_loss` and `ice_mass_last_milestone` per region.

## Definition of Done

- [ ] Real GRACE-FO endpoint probed with a live Earthdata token; fetch works on live data.
- [ ] Detection handles the "no newer month yet" case (latest month already processed).
- [ ] Full test suite green including new integration test.
- [ ] `BRIEFING.md` + `PIPELINE.md` updated.
- [ ] `EARTHDATA_TOKEN` secret documented.

## Open decisions — resolved

| Decision | Choice | Why |
|---|---|---|
| Data source | PODAAC GRACE-FO L4 mascon + Earthdata bearer token | Spec's preferred source; consistent format across regions; reusable auth plumbing |
| Region scope | Greenland + Antarctica only for MVP | No clean single PODAAC product for "global_glaciers"; defer |
| Auth mechanism | Bearer token via `EARTHDATA_TOKEN` env var | Simpler than OAuth password flow; matches existing token pattern |
| Record dataclass | Single `IceMassRecord` with `kind` discriminator | Simpler orchestrator loop; matches spec |
| Monthly record definition | Absolute archive-wide (not calendar-month) | Iconic headline is "largest ever"; melt seasonality makes this natural |
| Milestone step | -1000 Gt for both regions | Rare enough to preserve annual cap headroom |
| Annual cap | 8 across both event types combined | Matches spec |
| Scoring threshold | 78 | Matches spec |
| Approval | `suggested_auto`, 105 min delay | Middle of spec's 90-120 range |
| Run cadence | Mondays only in `run_alerts` | Matches sea-ice pattern; short-circuit prevents reprocessing same month |
| Category | Single `ice_mass_record` | Both kinds share voice rules and facts |

## Estimated budget

Per the source spec: ~4-6 hours for MVP. Earthdata setup adds ~1 hour.
