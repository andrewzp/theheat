# Lane 16 — main.py Refactor (Split 3,070-Line Monolith by Domain)

**Branch:** `hygiene/main-refactor`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (NOT in scope → main.py monolith)
**Scope:** Decompose [/Users/andrewpuschel/Documents/Claude/theheat/src/main.py](/Users/andrewpuschel/Documents/Claude/theheat/src/main.py) into a small entrypoint + domain modules
**Estimated time:** 3-4 hours CC, single PR
**Parallel-safety:** **Conflicts with EVERY other lane that touches `src/main.py`.** Must be the LAST lane in this wave. Run after Plans D, E, F, threshold registry all land. Parallel-safe with nothing else that adds new sources.

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

```
src/
  main.py                        ← entrypoint only (~50 lines)
                                    parses CLI args, dispatches to orchestrator
  orchestrator/
    __init__.py
    run_alerts.py                ← the run_alerts main loop, top-level
                                    sequencing only — calls source runners,
                                    finalizes the run
    source_runners.py            ← per-source run functions:
                                    _run_open_meteo, _run_firms, _run_nifc,
                                    _run_gdacs, _run_nws_alerts, _run_co2,
                                    _run_sea_ice, _run_ice_mass, _run_drought,
                                    _run_enso, _run_marine, _run_co_ops,
                                    _run_river_gauges, _run_ocean_sst,
                                    _run_nhc, _run_jtwc, ... (one per source)
    finalize.py                  ← finalize_run + state-write + source-health
                                    persistence + suppression ledger writes
    pipeline_routing.py          ← per-event routing into two_bot:
                                    score → intern → writer → claim_extractor →
                                    fact_check → memory recording → cap → save
    hot10.py                     ← run_hot10 mode
    posting.py                   ← run_post mode + auto_publish_due
```

This is a directory move, not a logic change. Every existing function moves into its semantic home; imports update; nothing else changes.

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

1. Branch `hygiene/main-refactor` from `main` (after Plans D, E, F, threshold registry all land).
2. Step 1: section map commit.
3. Step 2: skeleton commit.
4. Steps 3-4: one commit per functional group, tests passing at each.
5. PR → CI green → Claude merges.

Done. ~3-4 hours CC.
