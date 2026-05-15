# Lane 16 — Monolith Decomposition (main.py + scoring.py + intern.py)

**Branch:** `hygiene/monolith-decomposition`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (NOT in scope → main.py monolith)
**Scope:** Decompose **three** monolithic files — [/Users/andrewpuschel/Documents/Claude/theheat/src/main.py](/Users/andrewpuschel/Documents/Claude/theheat/src/main.py), [/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/scoring.py](/Users/andrewpuschel/Documents/Claude/theheat/src/editorial/scoring.py), and [/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern.py](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern.py) — into per-source / per-category modules. Behavior-preserving refactor.
**Estimated time:** 4-6 hours CC, single PR (or possibly ~30-45 min at observed Conductor pace)
**Parallel-safety:** **Conflicts with every source-add lane.** Run sequentially.

## 🚨 PRIORITY UPDATE 2026-05-15

**Run this lane NEXT, immediately after Plan D (Lane 12) merges.** Not last.

**Why the reorder:** every source-add lane (Plans D, E, F) appends to the end of `main.py` + `scoring.py` + `intern.py`. Two lanes running in parallel = guaranteed merge conflicts on the final line of all three files. By decomposing those three files first, future source-adds touch their OWN files and run truly in parallel.

**New queue order:**

```
1. Plan D (in flight)        → ~23 min
2. THIS LANE (decomposition) → ~30-45 min  ← unblocks parallelism
3. Plans E + F + Lane 15     → ~23 min in 3 concurrent workspaces
                                 (was: ~70 min serial)
```

Total wall-clock savings: ~45 min, plus every future source-add (Plan G+) lands clean.

## Why this lane exists

`src/main.py` is **3,070 lines**. It does:
- CLI entrypoint dispatch (alerts mode, hot10 mode, posting mode, etc.)
- Source-by-source orchestration in `run_alerts` (one big sequential function with sections per source)
- Source-status telemetry capture
- State writes / finalize_run
- Suppression ledger writes
- Per-source bundle assembly + retry routing into the two_bot pipeline

When a new lane wants to add a source, it has to find the right section of a 3,070-line file. When something goes wrong, the same. Every Plan A phase touched this file. Every source-add lane will continue to touch it. The file is the single biggest source of merge conflict and cognitive load in the codebase.

This refactor is behavior-preserving — no logic changes. Just structural.

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/src/main.py](/Users/andrewpuschel/Documents/Claude/theheat/src/main.py) — full file. Map the sections before writing any code.
2. [/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md](/Users/andrewpuschel/Documents/Claude/theheat/PIPELINE.md) — pipeline conceptual map. This refactor should make the code mirror the pipeline.
3. [/Users/andrewpuschel/Documents/Claude/theheat/tests/test_main.py](/Users/andrewpuschel/Documents/Claude/theheat/tests/test_main.py) — these tests are the regression spec. Should pass before and after.

## Proposed target structure

### main.py decomposition

```
src/
  main.py                        ← entrypoint only (~50 lines)
                                    parses CLI args, dispatches to orchestrator
  orchestrator/
    __init__.py
    run_alerts.py                ← the run_alerts main loop, top-level
                                    sequencing only — imports per-source
                                    runners and calls them in order
    sources/                     ← per-source runner files (parallelism unlock)
      __init__.py
      open_meteo.py              ← _run_open_meteo()
      firms.py                   ← _run_firms()
      nifc.py                    ← _run_nifc_fire_footprint()
      gdacs.py                   ← _run_gdacs()
      nws_alerts.py
      co2.py
      sea_ice.py
      ice_mass.py
      drought.py
      enso.py
      marine.py
      co_ops.py
      river_gauges.py
      ocean_sst.py
      nhc.py
      jtwc.py
      coral_dhw.py
      methane.py
      copernicus_ems.py          ← (added by Plan D)
      synthesis.py
    finalize.py                  ← finalize_run + state-write + source-health
                                    persistence + suppression ledger writes
    pipeline_routing.py          ← per-event two_bot routing helper:
                                    score → intern → writer → claim_extractor →
                                    fact_check → memory → cap → save
    hot10.py                     ← run_hot10 mode
    posting.py                   ← run_post mode + auto_publish_due
```

### scoring.py decomposition

```
src/editorial/
  scoring/
    __init__.py                  ← re-export all score_* functions for
                                    backward compatibility — existing imports
                                    `from src.editorial.scoring import score_X`
                                    continue to work
    _shared.py                   ← EditorialScore dataclass, _label, _compute_total,
                                    _build_score (used by every category)
    temperature.py               ← score_record_event, score_country_record,
                                    score_record_low_event, score_all_time_record,
                                    score_monthly_record, score_anomaly,
                                    score_record_streak, score_simultaneous_records
    fire.py                      ← score_fire_event, score_fire_footprint
    atmospheric.py               ← score_co2_milestone, score_ch4_milestone (added
                                    by Plan B), score_oscillation_* (Plan F),
                                    score_ozone_hole_peak (Plan F)
    disasters.py                 ← score_severe_weather, score_global_disaster,
                                    score_storm_surge, score_river_flood,
                                    score_global_flood (Plan D),
                                    score_cyclone_* (Plan C)
    marine.py                    ← score_sea_ice_record, score_ice_mass_event,
                                    score_marine_heatwave, score_extreme_wave,
                                    score_coral_bleaching (Plan B)
    precipitation.py             ← score_precipitation_extreme (Plan E),
                                    score_snow_extreme (Plan E),
                                    score_seasonal_snow_record (Plan E)
    drought.py                   ← score_drought
    synthesis.py                 ← score_synthesis_fire_drought_heat
    hot10.py                     ← score_hot10
```

The `__init__.py` re-exports every score function so existing callsites in main.py / orchestrator and tests don't need import changes (just module path).

### intern.py decomposition

```
src/two_bot/
  intern/
    __init__.py                  ← re-export all build_*_bundle functions
    _shared.py                   ← _resolve_when, _format_where, _c_to_f,
                                    _is_us_country, _audience_unit_facts,
                                    _ghcn_observation_facts, _headline_temp_label,
                                    _frp_tier
    temperature.py               ← build_record_bundle, build_monthly_high/low,
                                    build_all_time_record, build_anomaly,
                                    build_country_record, build_record_streak,
                                    build_simultaneous_records, build_hot10
    fire.py                      ← build_fire_bundle, build_fire_footprint
    atmospheric.py               ← build_co2_milestone, build_ch4_milestone,
                                    build_oscillation, build_ozone_hole
    disasters.py                 ← build_severe_weather, build_global_disaster,
                                    build_storm_surge, build_river_flood,
                                    build_global_flood, build_cyclone_*
    marine.py                    ← build_sea_ice, build_ice_mass,
                                    build_marine_heatwave, build_extreme_wave,
                                    build_coral_bleaching
    precipitation.py             ← build_precipitation, build_snow_extreme,
                                    build_seasonal_snow
    drought.py                   ← build_drought
    synthesis.py                 ← build_synthesis_bundle
```

Same `__init__.py` re-export pattern — existing imports `from src.two_bot.intern import build_X_bundle` continue to work.

## Why this decomposition unlocks parallelism

After this lane lands:

- A new source (Plan G, H, future) adds a NEW file in `src/orchestrator/sources/`. No conflict.
- A new score function adds to a category file in `src/editorial/scoring/`. Two lanes adding sources in different categories never touch the same file.
- A new bundle builder adds to the matching category file in `src/two_bot/intern/`. Same.

Even Plans E + F + Lane 15 (immediately after Lane 16) target different category files (Plan E touches `precipitation.py`; Plan F touches `atmospheric.py`; Lane 15 touches `_shared.py` + new `thresholds.py`). Zero collisions. Truly parallel.

This is a directory move, not a logic change. Every existing function moves into its semantic home; imports update via the `__init__.py` re-exports; nothing else changes.

## The plan

### Step 1 — Map the current file

First commit: produce a section map of `main.py`. For each ~100-line block:
- What is this block's responsibility?
- Which target module does it belong to?
- What's its public interface (what calls it from outside)?

Commit the map as `docs/main-py-refactor-map.md`. This is the basis for the actual move.

### Step 2 — Create the orchestrator package + skeleton

- Create `src/orchestrator/__init__.py` (empty)
- Create the target files as empty stubs with type signatures
- Don't move logic yet — just stand up the structure

### Step 3 — Move logic in functional groups

Move ONE group at a time, committing after each. Order:

1. **finalize.py group:** state-write + source-health-persistence + finalize_run + suppression ledger writes
2. **pipeline_routing.py group:** the per-event two_bot routing (score → intern → writer → fact-check)
3. **source_runners.py group:** the per-source run functions. Move them in source-alphabetical order.
4. **run_alerts.py group:** the top-level run_alerts function — now thin because it just calls the source runners and finalize
5. **hot10.py / posting.py groups:** the non-alerts modes
6. **main.py reduces** to the CLI entrypoint only

After each commit, run the full test suite. Tests must pass at every commit.

### Step 4 — Update test imports

`tests/test_main.py` imports from `src.main`. Some imports will move. Update the imports; don't change test logic. If a test asserts internal behavior of a moved function, it follows the function to wherever it landed.

## Constraints

- **Pure refactor, ZERO logic changes.** If you find a bug, fix it in a separate PR.
- **Tests pass at every commit.** Run `python -m pytest -q tests/test_main.py` after each move; full suite at the end.
- **Preserve git history with `git mv` where possible** for module-level moves. For partial moves (some functions stay, some go), use copy + delete with a commit message that explains.
- **Imports across the codebase update.** Run `grep -rn "from src.main import" src/ tests/` after the refactor; every callsite must use the new module path.
- **No new dependencies.** Pure stdlib reorganization.
- **No new test files.** Use existing test_main.py + add tests/test_orchestrator/ subdirectory if test-file decomposition makes sense.
- **Subagent model floor:** Sonnet 4.6 default. Refactor work doesn't need Opus.

## Acceptance

- mypy clean, ruff clean
- Full suite passes (no test logic changes; just import path updates)
- `wc -l src/main.py` reports under 100 lines (was 3,070)
- `wc -l src/orchestrator/*.py` total approximates the old main.py line count (allowing for slight increase due to import headers)
- `grep -rn "from src.main import" src/ tests/` returns only entrypoint-level imports (e.g., `from src.main import main`)

## Branch / PR sequence

1. Branch `hygiene/monolith-decomposition` from `main` (immediately after Plan D / Lane 12 merges).
2. Step 1: section map commit (across all three files).
3. Step 2: skeleton commit (create the three packages + `__init__.py` re-exports).
4. Steps 3-4: one commit per functional group, tests passing at each.
5. PR → CI green → Claude merges.

Done. ~4-6 hours CC. After this lands, Plans E + F + Lane 15 spawn concurrently in 3 separate workspaces.
