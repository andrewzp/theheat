# Declarative `MERGE_SPEC` — design spec (2026-06-09, rev 2 post-Codex)

**Status:** revised after Codex adversarial review → pending Andrew approval → writing-plans.
**Target:** `src/state.py` `_merge_state` (lines 603–916) + `TestMergeStateContract` in `tests/test_state.py`.
**Type:** behavior-preserving internal refactor. No caller, backend, or helper behavior changes.

## Problem

`_merge_state(current, incoming)` reconciles two snapshots of durable state on every `write_state`
(gist read-modify-write + SQLite path). It hand-codes the merge for all **54** top-level `DEFAULT_STATE`
keys imperatively — ~314 lines, **20 near-identical per-key `max`/`min` loops**.

Failure mode this retires: **add a key to `DEFAULT_STATE`, forget the branch in `_merge_state` → the key
silently resets to default on every write.** Happened 3× (`air_quality_*_tiers` #194, `data_source_failures`).
The current probe-based contract test (`tests/test_state.py:384`) catches *absence* of a handler but, per
its own docstring, cannot prove a handler *preserves* data, and leans on a probe heuristic + allowlist.

## Goal / non-goals

**Goal:** Replace the imperative body with a declarative `MERGE_SPEC: dict[str, Strategy]` + a ~6-line
driver, so coverage is total by construction and the contract becomes `assert set(MERGE_SPEC) == set(DEFAULT_STATE)`.

**Non-goals:** no merge-semantics change (see equivalence contract below); no change to the 15 extracted
helpers; no change to `_normalize_state` / `read_state` / `write_state` / backends / callers; not touching
the Python-sentinel / dashboard-JS classifier (different surface).

## Equivalence contract (added per Codex)

**The contract is: byte-identical serialized output for every *schema-valid* state** — i.e. every state the
bot's writers can actually produce (counts and tiers are `int`, date-keys are ISO `str`, milestones are
`int`/`float`, etc., as the `BotState` TypedDict + the `increment_*`/`update_*` writers guarantee).

This is the honest contract: `_merge_state` only ever runs on states read back from the gist/SQLite that the
bot itself wrote. To honor it without rewriting stored values, **`max_by_key` compares raw values** (no
`int()`/`str()` coercion that could change a stored value's type) with a **membership sentinel** for absent
keys (`v if k in d else floor`, never `value or floor`). This:
- fixes the tier-`0` bug (Codex #1): `max_by_key(floor=-1)` keeps a legitimate `0` because absence, not
  falsiness, triggers the floor;
- matches current's raw `max`/comparison quirks on int/str data (Codex #3/#5/#6 are non-divergent under raw
  compare);
- is proven on the real 988 KB prod state by the golden harness (below).

## Strategy taxonomy (6 strategies, down from 8)

Each strategy is a callable `(base_value, next_value) -> merged_value` (both args exist; `_normalize_state`
backfills every top-level key before merge).

| Strategy | Semantics | deepcopy |
|---|---|---|
| `take_incoming` | `deepcopy(next)` — replace with newest | yes |
| `dict_overlay` | `{**deepcopy(base), **deepcopy(next)}` — per-key last-writer-wins | yes (Codex #2) |
| `ordered_unique(max_items)` | `_merge_ordered_unique(base, next, max_items)` | helper handles |
| `max_by_key(floor)` | per-key over `set(base)\|set(next)`: `max(v if k in d else floor …)`, **raw compare**, returns original value | n/a (primitives) |
| `reduce_by_key(reducer)` | per-key: `reducer(base.get(k), next.get(k))` (None = absent); deepcopy the chosen value | yes |
| `custom(fn)` | delegate to a named tested helper | helper handles |

Dropped from rev 1: `scalar_max` and `min_by_key` (Codex #4/#6 showed they diverge as generic factories) —
their keys move to named `custom` helpers / `reduce_by_key`.

## Driver (replaces ~314 lines)

```python
def _merge_state(current, incoming):
    base = _normalize_state(current)
    nxt = _normalize_state(incoming)
    merged = _fresh_state()
    for key, strategy in MERGE_SPEC.items():
        merged[key] = strategy(base.get(key), nxt.get(key))
    return cast(BotState, merged)
```

Codex confirmed **no cross-key dependency**, so `MERGE_SPEC` iteration order does not affect output.

## Full key → strategy mapping (all 54)

| # | Key | Current behavior (line) | Strategy |
|---|---|---|---|
| 1 | `last_hot10` | deepcopy next (607) | `take_incoming` |
| 2 | `streaks` | deepcopy next (608) | `take_incoming` |
| 3 | `posted_events` | `_merge_ordered_unique(…,500)` (609) | `ordered_unique(500)` |
| 4 | `daily_tweet_count` | `{**deepcopy(base), **deepcopy(next)}` (614) | `dict_overlay` |
| 5 | `co2_annual_count` | per-year raw `max`, `.get(_,0)` (620) | `max_by_key(0)` |
| 6 | `ch4_annual_count` | per-year raw `max`, `.get(_,0)` (629) | `max_by_key(0)` |
| 7 | `ch4_last_milestone` | None-passthrough; both→`max(int,int)` (638) | `custom(_merge_ch4_last_milestone)` |
| 8–11 | `nao/ao/pdo/ozone_hole_annual_count` | per-year `max(int(x or 0))`, `.get(_,0)` (647) | `max_by_key(0)` |
| 12–14 | `nao/ao/pdo_last_phase` | `next.get(k, base.get(k))` (660) | `take_incoming` |
| 15 | `ozone_hole_last_peak` | `_merge_ozone_hole_last_peak` (662) | `custom` |
| 16 | `drafts` | `_merge_drafts` (666) | `custom` |
| 17 | `run_history` | `_merge_run_history` (667) | `custom` |
| 18 | `errors` | `_merge_errors` (668) | `custom` |
| 19 | `suppressions` | `_merge_suppressions` (669) | `custom` |
| 20 | `memory` | `_merge_memory` (672) | `custom` |
| 21–24 | `city_all_time_max/min`, `city_monthly_max/min` | deepcopy next (675–678) | `take_incoming` |
| 25 | `record_streaks` | deepcopy next (679) | `take_incoming` |
| 26 | `source_health` | `_merge_source_health` (680) | `custom` |
| 27 | `ocean_sst_streak` | deepcopy next (685) | `take_incoming` |
| 28 | `ice_mass_max_loss` | per-region keep MIN `gt`, `<=` tie, None-aware, deepcopy (689) | `reduce_by_key(_keep_min_gt)` |
| 29 | `ice_mass_last_milestone` | per-region present-aware `min`, None→take-other (705) | `reduce_by_key(_present_min)` |
| 30 | `ice_mass_last_seen` | per-region raw `max` str, `.get(_,"")` (719) | `max_by_key("")` |
| 31 | `ice_annual_count` | per-year raw `max`, `.get(_,0)` (727) | `max_by_key(0)` |
| 32 | `precip_daily_records` | `_merge_max_mm_records` (736) | `custom` |
| 33 | `precip_recent_by_city` | `_merge_recent_mm_rows` (740) | `custom` |
| 34 | `snow_daily_swe_gain_records` | `_merge_max_mm_records` (744) | `custom` |
| 35 | `snow_recent_by_station` | `_merge_recent_mm_rows` (748) | `custom` |
| 36 | `snow_annual_count` | per-year raw `max`, `.get(_,0)` (752) | `max_by_key(0)` |
| 37 | `seasonal_snow_records` | `_merge_max_mm_records` (761) | `custom` |
| 38 | `fire_complex_tiers` | per-complex `max(int)`, `.get(_,-1)` (767) | `max_by_key(-1)` |
| 39 | `coral_dhw_last_tier` | per-region `max(int)`, `.get(_,0)` (776) | `max_by_key(0)` |
| 40 | `coral_dhw_annual_count` | per-year raw `max`, `.get(_,0)` (785) | `max_by_key(0)` |
| 41–42 | `air_quality_pm25_tiers`, `air_quality_dust_tiers` | per-city `_pick_newer_city_tier` (801) | `reduce_by_key(_pick_newer_city_tier)` |
| 43 | `data_source_failures` | next-authoritative reset-aware (821) | `custom(_merge_data_source_failures)` |
| 44 | `sst_anom_last_tier` | per-region `max(int)`, `.get(_,0)` (832) | `max_by_key(0)` |
| 45 | `sst_anom_annual_count` | per-year `max(int)`, `.get(_,0)` (841) | `max_by_key(0)` |
| 46 | `reganom_last_fired` | per-region raw `max` str, `.get(_,"")` (853) | `max_by_key("")` |
| 47 | `cyclone_tiers` | per-storm `max(int)`, `.get(_,-1)` (863) | `max_by_key(-1)` |
| 48 | `cyclone_wind_history` | `_merge_cyclone_wind_history` (872) | `custom` |
| 49 | `cyclone_annual_count` | per-year raw `max`, `.get(_,0)` (876) | `max_by_key(0)` |
| 50 | `flood_activation_tiers` | per-activation `_max_flood_severity` (885) | `reduce_by_key(_max_flood_severity)` |
| 51 | `flood_annual_count` | per-year raw `max`, `.get(_,0)` (894) | `max_by_key(0)` |
| 52 | `fire_footprint_last_run` | `max(base or "", next or "") or None` (904) | `custom(_merge_fire_footprint_last_run)` |
| 53 | `synthesis_components` | `_merge_synthesis_components` (908) | `custom` |
| 54 | `synthesis_cooldown` | `_merge_synthesis_cooldown` (912) | `custom` |

Tally: `max_by_key` 18 · `custom` 18 (15 existing helpers + `_merge_ch4_last_milestone` +
`_merge_fire_footprint_last_run` + `_merge_data_source_failures`) · `take_incoming` 11 · `reduce_by_key` 5 ·
`dict_overlay` 1 · `ordered_unique` 1 = 54.

`reduce_by_key` reducers (each None-aware, deepcopy chosen): `_keep_min_gt`, `_present_min`,
`_pick_newer_city_tier` (existing), `_max_flood_severity` (existing).

## Contract test upgrade (the prize)

Replace the probe test + `HANDLED_VIA_CUSTOM_HELPER` allowlist with the structural identity:

```python
def test_merge_spec_covers_exactly_default_state():
    from src.state import DEFAULT_STATE, MERGE_SPEC
    assert set(MERGE_SPEC) == set(DEFAULT_STATE)   # no missing key, no orphan strategy
```

Keep every existing per-key behavioral test (drafts/run_history/errors/suppressions/memory/aq-tiers/
data_source_failures/reganom/ice_mass/fire-tier-0/etc.) — the regression proof semantics didn't move.

## Safety / equivalence plan

1. **All existing `_merge_state` behavioral tests stay green** (1626-test suite; many target `_merge_state`,
   incl. the fire-tier-`0` case at `tests/test_state.py:1191` that Codex #1 would have regressed).
2. **Dev-time golden equivalence harness** (not committed): keep the old fn as `_merge_state_legacy`; assert
   `_merge_state(a,b) == _merge_state_legacy(a,b)` over (a) the real 988 KB prod gist `state.json`, (b)
   `state ⊗ state`, (c) `state ⊗ DEFAULT_STATE`, (d) synthetic concurrent-write pairs (incl. tier-0,
   one-sided, reset). Delete legacy only after deep-equal holds.
3. **New structural contract** (`set(MERGE_SPEC) == set(DEFAULT_STATE)`).
4. Preserve exact floors (`0` vs `-1`) via membership sentinel; raw compare per key.

## Codex adversarial review — findings + resolutions

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | `int(value or floor)` collapses tier `0`→`-1` for `fire_complex_tiers`/`cyclone_tiers` | **P1, valid data** | `max_by_key` uses membership sentinel + raw compare |
| 2 | `dict_overlay` `{**base,**next}` aliases vs current deepcopy | P1 (discipline) | `dict_overlay` deepcopies both sides |
| 3 | Raw annual counters coerced to `int` differ on string input | P1 (contract) | raw compare; equivalence contract = schema-valid |
| 4 | `scalar_max` factory diverges for ch4 vs fire_footprint | P1 | both → named `custom` helpers |
| 5 | `max_by_key(str)` lexicographic on int input | P1 (contract) | raw compare; schema-valid contract |
| 6 | `min_by_key` under-specified | P1 (contract) | → `reduce_by_key(_present_min)` |
| 7 | `data_source_failures` asymmetric | P1 | stays `custom(_merge_data_source_failures)` |
| — | take_incoming fallback / cross-key order / source_health | sound | confirmed |

## Open taste call (for Andrew)

1. **Strategy representation:** plain callables via factories (`max_by_key(-1)`, `take_incoming`, helpers by
   reference) vs strategy classes with `.merge()`. Recommend callables.
2. **Equivalence contract:** schema-valid (raw compare, recommended — clean + golden-proven on real state)
   vs bit-exact-for-arbitrary-input (would force preserving accidental quirks). Recommend schema-valid.
