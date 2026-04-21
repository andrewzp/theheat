# Codex Review Brief — 2026-04-21 Lanes Merge

## Scope

Review the four lanes that merged into `main` today, focusing on the
interactions between them and the conflict-resolution commits that
landed during rebase. Each lane passed its own tests in isolation; the
question is whether the integrated code behaves correctly together.

Target commits to review (all on `main`):

- **Lane 1 — Ocean SST / marine heatwaves** → PR #8 (`5431a18`)
- **Lane 2 — GRACE-FO ice mass** → PR #9 (`83c96f9`)
- **Lane 3 — Fire footprint (NIFC WFIGS)** → PR #10
- **Lane 4 — Cross-source synthesis** → PR #7

Prior baseline (pre-lane main): `694fcf2`.
Diff span: `git diff 694fcf2..HEAD`.

Each lane added its own test suite. Combined test count on `main`:
**485 passing** (baseline was 324; +161 tests across four lanes).

## Why this review

The four lanes were developed in parallel with no knowledge of each
other. I rebased three of them (2, 3, 4) onto `main` after Lane 1 had
already merged. Conflict resolution was additive — every lane touched
`src/state.py DEFAULT_STATE`, `_merge_state`, `src/editorial/approval.py`,
`src/editorial/candidates.py`, `src/voice/templates.py`,
`src/voice/generator.py`, `src/main.py` orchestrator, and the shared
test modules. I kept all contributions from each lane; no semantic
conflicts were expected, but a human-speed rebase is exactly where
integration bugs hide.

## Specific concerns — please prioritize

### High priority

1. **`src/state.py` `DEFAULT_STATE` + `_merge_state`**
   Four new top-level state keys in `DEFAULT_STATE`
   (`ocean_sst_streak`, `ice_mass_*` group, `fire_complex_tiers` + `fire_footprint_last_run`, `synthesis_components` + `synthesis_cooldown`).
   Each lane added custom merge semantics in `_merge_state`.
   Verify: (a) every new key has a corresponding entry in `_merge_state`;
   (b) merge semantics actually preserve the right side (extremes for ice
   mass, max tier for fires, always-take-incoming for ocean streak, time-
   based for synthesis); (c) sqlite_store.py mirrors the schema or at
   least doesn't explode on the new keys.

2. **`src/main.py::run_alerts`**
   Massive orchestrator function. Each lane added a section. New
   additions include:
   - Marine heatwave block (Lane 1)
   - GRACE-FO Monday-only block (Lane 2, with per-region short-circuit)
   - Fire footprint once-per-day block (Lane 3)
   - Cross-source synthesis at tail (Lane 4, uses per-source component
     recording throughout earlier sections)

   Verify: (a) `run_alerts` still returns the expected shape;
   (b) exceptions in any one block are caught and `log_error`'d without
   killing subsequent blocks; (c) the end-of-cycle per-cycle cap pruning
   (`MAX_DRAFTS_PER_CYCLE`) still correctly deduplicates across all new
   signal types; (d) `_record_source_run` telemetry is accurate.

3. **Synthesis component recording (Lane 4)**
   Lane 4 instruments the FIRMS + USDM + Open-Meteo sections with
   side-effect writes into `bot_state["synthesis_components"]` so the
   synthesis stage can read them later in the same cycle. These writes
   are spread through the run_alerts flow in the FIRMS block, the
   drought block, and the Open-Meteo block.

   Verify: (a) all three component writers actually fire under
   realistic conditions; (b) `state.record_synthesis_fired` actually
   updates the cooldown before the synthesis stage reads it again;
   (c) `prune_stale_synthesis_components` removes entries older than
   the 14-day window.

### Medium priority

4. **Generator module growth**
   `src/voice/generator.py` now exports ~7 distinct `generate_*_tweet`
   functions in addition to the base `generate_tweet` / `generate_tweet_bundle`.
   Verify: (a) all new generators fall back to their templates when
   `GEMINI_API_KEY` is empty; (b) the Claude Sonnet 4.6 evaluator path
   handles the new `category` strings (`marine_heatwave`,
   `ice_mass_record`, `fire_footprint`, `synthesis_fire_drought_heat`)
   without falling into a default that invalidates scoring; (c) any
   new category added to `CATEGORY_HINTS` has matching keywords that
   actually appear in a well-formed tweet.

5. **Approval policy branches**
   `src/editorial/approval.py` now has specific branches for
   `marine_heatwave`, `ice_mass_record`, `country_high/low`,
   `synthesis_fire_drought_heat`, and the fire_footprint type was
   added to the `manual_only` set. Verify there's no dead branch or
   fall-through that routes a category to the wrong policy.

6. **Annual caps**
   Two caps coexist now: `co2_annual_count` (12/year) and
   `ice_annual_count` (8/year). Confirm neither leaks into the other's
   logic, and that both are reset per calendar-year key without
   interference.

### Lower priority (quick checks)

7. **ocean_sst module** — verify climatology file handling (falls back
   gracefully if file missing; doesn't hard-crash on old-format CSVs).
8. **fire_footprint module** — verify the NIFC WFIGS parser handles
   missing optional fields (complex_name, start_date) without
   throwing.
9. **ice_mass module** — verify Earthdata Login fallback (no token →
   returns empty, doesn't crash).
10. **synthesis region matching** — `src/editorial/_regions.py`. The
    lat/lon → US-state bounding-box classifier is naive by design.
    Check: `lat_lon_to_state(0, 0)` returns None, not a false positive.

## What to look for in general

- **Bugs that only manifest when multiple lanes fire in the same cycle**
  (e.g., ice_mass on Monday + synthesis active simultaneously).
- **Silent drops** — a try/except that swallows real exceptions.
- **State bloat** — anything that grows unbounded (synthesis components
  buffer, fire complex tiers dict, per-region last-seen).
- **Off-by-one** on date/month arithmetic (especially ice_mass +
  synthesis both use datetime-heavy math).
- **Security-adjacent** — any new HTTP call that now sends auth
  headers, payload that includes secrets, etc. (shouldn't be, but
  confirm).

## What NOT to spend time on

- Voice/copy-quality review — that's a different skill set. Focus on
  correctness.
- Style / formatting — the project has its conventions; don't
  redistribute.
- Individual lane internals that only interact with their own test
  suite — all four pass in isolation.

## How to respond

Short structured write-up. For each high-priority concern either
"looks correct" with a one-line justification, or a specific file:line
reference with the bug and recommended fix. For the lower-priority
items, just flag anything material and skip the rest.

## Running context

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate

# Full diff
git diff 694fcf2..HEAD

# Run tests
python -m pytest tests/

# Targeted tests per lane
python -m pytest tests/test_ocean_sst.py tests/test_ice_mass.py \
                 tests/test_fire_footprint.py tests/test_synthesis.py \
                 tests/test_state_synthesis.py tests/test_regions.py

# Orchestrator integration
python -m pytest tests/test_main.py

# Merge semantics
python -m pytest tests/test_state.py
```

---

Compiled 2026-04-21 after merging PRs #8, #9, #10, #7.
