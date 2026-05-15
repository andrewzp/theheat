# Lane 08 — Plan B: Coral Reef Watch DHW + CH4 Methane

**Branch:** `plan-b/coral-dhw-and-methane`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (Out-of-scope reminders → Plan B)
**Scope:** Add two new data sources — coral bleaching DHW (NOAA Coral Reef Watch) + atmospheric methane (NOAA GML)
**Estimated time:** 4-5 hours CC, single PR
**Parallel-safety:** **Conflicts with Lane 09 (cyclones), Lane 11 (F2 bundle enrichment)** — all touch `src/two_bot/intern.py`, `src/editorial/scoring.py`, `src/main.py`. Must run sequentially with those. Parallel-safe with Lane 10 (docs cleanup, pure `docs/`).

## Why this lane exists

@theheat currently has zero coverage of:

- **Coral bleaching** — the canonical climate-change-on-marine-systems metric. NOAA's Degree Heating Weeks (DHW) is *the* metric oceanographers cite. 2024 Great Barrier Reef bleaching event invisible to the bot.
- **Atmospheric methane (CH4)** — fastest-rising greenhouse gas in the current data. Bot only talks CO2.

Both pair naturally with the marine-warming story class. Both are NOAA-published (same trust posture as the existing CO2 source). Both are simple polled JSON endpoints — low integration cost, high editorial unlock.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — see "Plan B: Bucket 2" reference
2. [/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md](/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md) — full pipeline flow
3. [/Users/andrewpuschel/Documents/Claude/theheat/BRIEFING.md](/Users/andrewpuschel/Documents/Claude/theheat/BRIEFING.md) — pipeline conventions
4. **Reference patterns to follow:**
   - [/Users/andrewpuschel/Documents/Claude/theheat/src/data/co2.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/co2.py) — NOAA-published, milestone-capped (12/year). CH4 will mirror this pattern almost exactly.
   - [/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py) — annual-cap pattern, NOAA source.
   - [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_http.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_http.py) — retry helper (use this for both new sources)
   - [/Users/andrewpuschel/Documents/Claude/theheat/src/data/source_status.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/source_status.py) — `assert_response_schema` (use at top of each fetch)
   - [/Users/andrewpuschel/Documents/Claude/theheat/src/data/_freshness.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/_freshness.py) — freshness assertions

## Sub-task 8a — NOAA Coral Reef Watch DHW

**Source:** NOAA Coral Reef Watch Degree Heating Weeks per-region time series.
- API: `https://coralreefwatch.noaa.gov/product/5km/v3.1/dhw/` — published daily, GeoTIFF + accompanying CSV summaries per region
- Alternative JSON endpoint to investigate: `https://coralreefwatch.noaa.gov/satellite/bleaching5km/` (check first via curl what the JSON shape looks like)
- Free, no token required

**Detection rule:** Fire when a coral reef region's DHW crosses a bleaching threshold:
- DHW ≥ 4 °C-weeks → onset of bleaching stress (warning level)
- DHW ≥ 8 °C-weeks → mass bleaching expected (alert level)
- DHW ≥ 12 °C-weeks → mortality expected (critical level)

Use a tier-dedup pattern like fire_footprint or GDACS — once a region crosses the 4-threshold, don't re-fire until it crosses the 8-threshold. Each region × tier = one event.

**Files:**
- `src/data/coral_dhw.py` (new) — `CoralBleachingEvent` dataclass + `fetch_coral_dhw()` + `detect_dhw_thresholds()`
- `src/editorial/scoring.py` — add `score_coral_bleaching(dhw_value, tier, region)` with threshold around 72 (similar to other event-driven sources)
- `src/two_bot/intern.py` — add `build_coral_bleaching_bundle(event: CoralBleachingEvent)`
- `src/editorial/approval.py` — add coral_bleaching → `manual_only` approval (sensitive subject; human approves)
- `src/main.py::run_alerts` — wire the new section in the standard order
- `src/state.py` + `src/state_schema.py` — add `coral_dhw_last_tier: dict[str, int]` (region_id → last-fired tier) for dedup
- `tests/test_coral_dhw.py` (new) — detector tests (DHW thresholds, tier dedup) + scoring tests + integration test in `run_alerts`

**Editorial constraints:**
- DHW values must be cited with units ("8 °C-weeks", "DHW 8")
- Region naming: use NOAA's region IDs (e.g., "Great Barrier Reef Northern Section") — don't invent regional names
- Annual cap: 16 tweets/year across all reef regions (bleaching events are real news but should not dominate the feed)

## Sub-task 8b — NOAA CH4 methane (Mauna Loa)

**Source:** NOAA Global Monitoring Lab CH4 monthly mean.
- API: `https://gml.noaa.gov/webdata/ccgg/trends/ch4/ch4_mm_gl.txt` (matches the CO2 pattern at `co2.py`)
- Free, no token

**Detection rule:** Fire when CH4 crosses a new integer ppb milestone. CH4 is currently around 1928 ppb (May 2025); rising ~12 ppb/year. So milestones at 1930, 1940, 1950, etc.

Mirror the CO2 milestone pattern exactly. Use the same dedup approach (state.ch4_annual_count + state.ch4_last_milestone).

**Files:**
- `src/data/methane.py` (new) — `MethaneMilestone` dataclass + `fetch_ch4_milestones()`. Mirror `src/data/co2.py` shape line-by-line.
- `src/editorial/scoring.py` — add `score_ch4_milestone(ppb_crossed, actual_ppb)` mirroring `score_co2_milestone` (threshold ~58)
- `src/two_bot/intern.py` — add `build_ch4_milestone_bundle(milestone: MethaneMilestone)` mirroring `build_co2_milestone_bundle`
- `src/editorial/approval.py` — add ch4_milestone → `armed_auto` (matches CO2 behavior — high-confidence NOAA data, low blast radius)
- `src/main.py::run_alerts` — wire next to the CO2 section
- `src/state.py` + `src/state_schema.py` — add `ch4_annual_count: int`, `ch4_last_milestone: int`
- `tests/test_methane.py` (new) — milestone detection, annual cap, integration test

**Editorial constraints:**
- CH4 milestones cite both the crossed integer and the actual value: "CH4 just crossed 1940 ppb — sitting at 1942.3"
- Pre-industrial baseline (722 ppb) is the era anchor. Use it when the framing earns it; don't shoehorn it into every tweet.
- Annual cap: 12 tweets/year (same as CO2)

## Sub-task 8c — voice + fact-check coverage

Once both sources ship signals, the fact-checker will see new entity claims. Verify:
- `CoralBleachingEvent` bundles carry `region_id`, `region_full_name`, `dhw_value`, `dhw_tier`, `bleaching_level` — fact-checker can verify each
- `MethaneMilestone` bundles carry `ppb_crossed`, `actual_ppb`, `source_name` — fact-checker can verify each

Add at least one voice-regression scenario for each new source if the voice-regression workflow includes a "happy path per source" expectation (check [/Users/andrewpuschel/Documents/Claude/theheat/.github/workflows/voice-regression.yml](/Users/andrewpuschel/Documents/Claude/theheat/.github/workflows/voice-regression.yml) first).

## Acceptance

- mypy clean
- Full suite passes with ~20+ new tests added
- Run a manual test cron: `gh workflow run bot.yml -f mode=alerts && gh run watch`. New alerts cycle should observe at least one DHW reading (if any reef region is in stress) and one CH4 reading.
- After deploy: 3 consecutive crons show `coral_dhw: success/skipped` and `ch4_milestone: success/skipped` in run_history.

## Constraints (all sub-tasks)

- **No new dependencies.** Use `requests`, `requests` retry helper from `_http.py`, and stdlib parsing.
- **Schema-drift assertions on every fetch.** Required from Phase 1; use them.
- **Freshness assertions on every fetch.** DHW updates daily; CH4 monthly. Stale-data tolerance windows accordingly.
- **Subagent model floor:** Sonnet 4.6 default, never Haiku.
- **Verify the wire.** After deploy, confirm new sources show up in `/api/source-health` dashboard view.

## Branch / PR sequence

1. Branch `plan-b/coral-dhw-and-methane` from `main`.
2. Build 8a + 8b in parallel commits within the same branch.
3. Run mypy + pytest + `gh workflow run bot.yml`.
4. PR → CI green → Claude merges per the standing rule.

Done. ~4-5 hours CC for both new sources end-to-end.
