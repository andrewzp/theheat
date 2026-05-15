# Lane 11 — F2: Bundle Enrichment for System Clauses

**Branch:** `f2/bundle-enrichment-helper`
**Plan-of-record:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) (NOT in scope → F2 deferred)
**Scope:** Add a curated geographic-climate context helper so the writer's system-clause language passes fact-check
**Estimated time:** 4-6 hours CC, single PR (most of the time is climate-science curation, not code)
**Parallel-safety:** **Conflicts with Lane 08 (coral/methane), Lane 09 (cyclones)** — touches `src/two_bot/intern.py`. Parallel-safe with Phase 3 (touches main.py degraded trigger + ghcn.py, not intern.py). Parallel-safe with Lane 10 (docs only).

**Strategic note:** ship this BEFORE Lane 08 / Lane 09 if possible. Once `local_climate_context()` exists, new bundle builders (coral DHW, cyclones) can call it from the start instead of being retrofit later.

## Why this lane exists

The writer prompt (Sonnet 4.6) likes to produce **system clauses** — single-sentence framings that tie the data point to the climate system around it:

- "the western Pacific warm pool" (Chuuk monthly high)
- "the Androscoggin Valley funnels cold air off the White Mountains" (Bethel ME monthly low)
- "the eastern steppe" (Mongolia fire)
- "the Sahel dry season" (Niger anomaly)

These are exactly the @theheat voice goal: Attenborough-grade, system-aware, teaches without winking. But the **fact-checker rejects them as UNVERIFIABLE** because the bundle the fact-checker validates against doesn't carry that geographic-climate context. From the 2026-05-14 audit, ~18 fact_check kills/24h are this exact failure mode.

The fix: put the system context INTO the bundle so the fact-checker can verify it.

## Architectural shape (already locked by F2 discussion)

A new helper `local_climate_context(lat, lon, category) -> dict` that returns:

```python
{
    "region_climate_system": "western Pacific warm pool",
    "local_topography_note": None,  # only when applicable
    "season_context": "northern hemisphere dry season",  # only when applicable
}
```

Source: **curated lookup table**, NOT LLM-generated (the whole point is that the fact-checker rejects LLM hallucinations; we can't fix one LLM's hallucinations with another LLM's hallucinations).

The lookup table is the actual work. Climate-science curation:

- ~30-50 high-priority climate regions mapped to lat/lon bounding boxes
- Sourced from IPCC AR6 regional definitions, Köppen climate zones, NOAA region IDs, and Wikipedia articles with citation backing
- Each entry has 2-4 fact-checkable assertions (region name + 1-2 mechanism phrases)
- Topography callouts for prominent valleys, mountain rain shadows, sea breezes, lake-effect zones

## Read first

1. [/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/PLAN_A.md) — F2 section in NOT-in-scope
2. [/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern.py](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern.py) — current bundle builders. Note the existing `_ghcn_observation_facts` at line ~68 and `_audience_unit_facts` at line ~148 — those are the helper pattern this lane mirrors.
3. [/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/fact_check.py](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/fact_check.py) — read the fact-check contract; understand what "entity claim verifiable against bundle" means in practice.
4. [/Users/andrewpuschel/Documents/Claude/theheat/brand/MESSAGING_ARCHITECTURE.md](/Users/andrewpuschel/Documents/Claude/theheat/brand/MESSAGING_ARCHITECTURE.md) — voice rules about system clauses ("system clause second — name the mechanism, consequence, or rate behind the data when one exists").
5. **Reference for curation sources:**
   - IPCC AR6 Working Group I Atlas regions
   - Köppen-Geiger climate classification
   - NOAA's National Centers for Environmental Information (NCEI) regional definitions

## The work

### Sub-task 11a — Build the helper

**Files:**
- `src/data/_climate_context.py` (new) — defines:
  - `local_climate_context(lat: float, lon: float, category: str | None = None) -> ClimateContext | None`
  - `ClimateContext` dataclass with the fields above
  - The lookup table itself as module-level data (or load from a YAML/JSON file)
- `tests/test_climate_context.py` (new) — unit tests for each table entry: known-lat-lon returns expected region, out-of-table returns None, edge cases at bounding-box boundaries

The lookup interface should be simple. Bundle builders call:

```python
ctx = local_climate_context(lat=ev.lat, lon=ev.lon, category="heat")
if ctx:
    current_facts.append({"label": "region_climate_system", "value": ctx.region_climate_system})
    if ctx.local_topography_note:
        current_facts.append({"label": "local_topography_note", "value": ctx.local_topography_note})
```

### Sub-task 11b — Curate the lookup table

**Initial priority list** (~30 regions to seed, leaving room to add as the bot encounters new failures):

| Region | lat/lon bbox | Climate system | Notes |
|---|---|---|---|
| Western Pacific Warm Pool | 0-15N, 120-160E | "the western Pacific warm pool" | persistently >28°C SST |
| Sahel | 12-18N, -18-30E | "the Sahel dry season" / "Sahel monsoon" | sharp wet/dry transition |
| Mongolian eastern steppe | 45-48N, 110-120E | "the eastern Mongolian steppe" | continental dry climate |
| Atlantic ITCZ | 5-10N, -50-0W | "the Atlantic ITCZ" | tropical convergence |
| Mediterranean basin | 30-45N, -10-40E | "the Mediterranean basin" | summer-dry climate |
| Australian outback | -30 to -20S, 120-145E | "the Australian outback" | continental arid |
| Amazon basin | -10 to 5N, -75-50W | "the Amazon basin" | tropical rainforest |
| Hindu Kush rain shadow | 30-37N, 65-75E | "the Hindu Kush rain shadow" | mountain leeward dryness |
| Pacific Northwest | 42-49N, -125 to -120W | "the Pacific Northwest marine layer" | summer fog regime |
| Florida sea breeze zone | 25-31N, -82 to -80W | "the Florida sea breeze zone" | afternoon convection |
| Andean rain shadow (Patagonia) | -45 to -35S, -75 to -65W | "the Andean rain shadow" | extreme leeward dryness |
| ... [continue to ~30] | | | |

**Curation rules:**

- Every region name must be **publicly verifiable** — Wikipedia article exists, IPCC region defined, NOAA region defined. The fact-checker can verify "western Pacific warm pool" against geography references; it cannot verify "the breezy coastal zone."
- **Bounding boxes overlap intentionally.** A point in (latitude 12N, longitude -10E) might match Sahel AND West African coast — return the most specific match or the first one found, document the rule.
- **Topography notes are sparser.** Only add when the topography is famously the mechanism (Cascade rain shadow, Andean rain shadow, lake-effect zones around Great Lakes, cold-air drainage valleys like the Androscoggin). ~10-15 of these total.
- **Test every entry.** Each region in the table needs at least one test case confirming lookup returns the right context for a representative lat/lon.

### Sub-task 11c — Wire into bundle builders

**Files:** [/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern.py](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/intern.py)

For each bundle builder that has lat/lon available, call `local_climate_context()` and append the result to `current_facts`. Start with the highest-impact:

- `build_fire_bundle` — fire events have lat/lon from FIRMS
- `build_record_bundle` / `build_monthly_high_bundle` / `build_monthly_low_bundle` / `build_anomaly_bundle` / `build_all_time_record_bundle` — GHCN station coordinates
- `build_coral_bleaching_bundle` (if Lane 08 hasn't shipped yet, leave this for Lane 08 to wire)
- `build_cyclone_*_bundle` (if Lane 09 hasn't shipped yet, leave this for Lane 09 to wire)

**Don't change bundle schema** beyond adding new `current_facts` entries. The fact-checker reads `current_facts` for entity verification, so this slots in cleanly.

### Sub-task 11d — Validate end-to-end

After wiring, manually trigger a test cron and watch for fact-check rejections. The categories of past rejections to verify are now caught:

- Mongolia fire writer output → bundle now has `eastern Mongolian steppe` → fact-check passes
- Bethel ME monthly low → bundle now has `Androscoggin Valley` topography note → fact-check passes
- Chuuk monthly high → bundle now has `western Pacific warm pool` → fact-check passes

If a writer-produced system clause still fails fact-check, the lookup table is missing that region. Add it. This is expected to iterate.

## Acceptance

- mypy clean
- Full suite passes with ~30+ new tests (one per region entry + boundary cases + integration tests in bundle builders)
- After deploy: 3 consecutive alerts crons show **lower** `fact_check` UNVERIFIABLE rate compared to pre-deploy baseline (~18/24h). Measure via:

  ```bash
  gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json | jq '
    .suppressions // [] |
    map(select(.stage == "fact_check" and .ts > "<deploy-ts>")) |
    map(select(.reasons | map(test("UNVERIFIABLE")) | any)) |
    length'
  ```

- Drafts containing system clauses for the curated regions reach `pending` without fact-check kill.

## Constraints

- **NO LLM-generated entries in the lookup table.** Every region name must trace to an authoritative source (IPCC AR6, Köppen, NOAA NCEI, Wikipedia with citation). The whole point is fact-check-passing claims. Document the source per entry in a comment or sidecar.
- **No re-architecture of bundles.** Add to `current_facts`, don't reshape.
- **Subagent model floor:** Sonnet 4.6 for code; consider Opus for the curation pass if the lane wants — climate-science research benefits from the better reasoning.
- **Verify the wire.** After deploy, look at fact-check rejections in state.json suppressions — the rate should drop measurably.

## Branch / PR sequence

1. Branch `f2/bundle-enrichment-helper` from `main`.
2. Sub-task 11a — helper + tests (1 commit).
3. Sub-task 11b — curated table (1-2 commits, one per regional cluster).
4. Sub-task 11c — wire into intern.py bundle builders (1 commit).
5. Run mypy + pytest + manual alerts cron + check fact-check rate.
6. PR → CI green → Claude merges per the standing rule.

Done. ~4-6 hours CC end-to-end. Most of the time is climate-science curation, not code.
