# Source-To-Writer Evidence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make The Heat's path from raw source data to writer prompt explicit, testable, and hard to accidentally weaken. After this work, every source family should have a documented evidence shape, representative bundle tests, and a lightweight audit that answers: "What did we ingest, how did we organize it, and what exactly can the writer use?"

**Architecture:** Keep the existing two-bot pipeline. Add an evidence-contract layer beside the current intern builders, not inside the writer. Sources continue to fetch and detect events, intern builders continue to produce `StoryBundle`, triage can continue to wrap candidates in `TriageCandidateBundle`, and the writer continues to receive `bundle_json` plus `memory_json`. The new layer audits those bundles before they reach generation and gives maintainers a source-by-source matrix for context quality.

**Tech Stack:** Python, pytest, current `src/two_bot` dataclasses, existing `src/two_bot/intern/*` builder modules, current orchestrator source modules, markdown docs.

---

## Current Data Flow

The live path is:

```text
raw source API/files
  -> source runner in src/orchestrator/sources/*
  -> source-specific detection/scoring logic
  -> intern builder in src/two_bot/intern/*
  -> StoryBundle
  -> optional TriageCandidateBundle queue
  -> _try_two_bot_draft
  -> generate_draft
  -> build_memory_slice
  -> writer prompt with bundle_json and memory_json
  -> safety, claim extraction, fact-check, critic
  -> shipped tweet and memory record
```

The writer does not see raw API responses unless a source copied the important pieces into `StoryBundle.current_facts`, `StoryBundle.historical_context`, `StoryBundle.headline_metric`, or `StoryBundle.raw_signal_dump`.

The main contract today is `src/two_bot/types.py`:

- `StoryBundle` is the evidence packet the writer sees.
- `MemorySlice` is historical shipped-tweet context added after bundle creation.
- `TriageCandidateBundle` wraps a `StoryBundle` with source, score, review context, cooldown metadata, and optional success callbacks.

The writer prompt currently receives two JSON objects:

- `bundle_json`: from `StoryBundle`.
- `memory_json`: from `MemorySlice`.

This plan should preserve that shape while making the evidence contents auditable.

## Scope

In scope:

- Document every source family from ingest to writer-facing bundle.
- Add a small bundle audit module that classifies missing or weak evidence before generation.
- Add representative tests for each intern family and high-risk source path.
- Add one durable matrix that future source work must update.
- Keep prompt changes minimal and only make them when the audit proves the writer lacks a field it needs.

Out of scope for this plan:

- Rewriting all source runners.
- Changing posting, approval, or dashboard storage.
- Migrating every direct writer call to queued triage.
- Changing source thresholds or editorial taste.
- Adding new external data providers.

## Source-To-Writer Matrix

Use this matrix as the implementation checklist. A source is considered covered when its row has a representative fixture test and the audit can explain whether its bundle is prompt-ready.

| Source family | Source runner | Raw ingest | Detection and organization | Writer-facing bundle | Strong evidence already present | Main risk to close |
|---|---|---|---|---|---|---|
| Temperature records | `src/orchestrator/sources/open_meteo.py` | Weather and climate record data assembled into city, country, date, temperature, baseline, archive facts | Record, all-time record, monthly high, anomaly, country record, streak, simultaneous-record routing | `temperature.build_record_bundle`, `build_all_time_record_bundle`, `build_monthly_high_bundle`, `build_anomaly_bundle`, `build_country_record_bundle`, `build_record_streak_bundle`, `build_simultaneous_records_bundle` | Rich current facts, archive years, prior record, margin, units, calendar scope, forbidden claims for all-time records | Many builder variants need shared assertions so one path cannot silently lose archive context or date scope |
| Hot 10 | `src/orchestrator/hot10.py` | Ranked anomaly candidates | Leaderboard selection | `temperature.build_hot10_bundle` | Ranking, anomaly, sample cities | Writer may overstate representativeness unless the bundle keeps leaderboard scope explicit |
| Fire hotspots | `src/orchestrator/sources/firms.py` | FIRMS fire pixels and FRP values | Threshold/tier selection around location and country | `fire.build_fire_bundle` | FRP, FRP tier, country/region, lat/lon, climate facts | Empty historical context is acceptable only if raw location/source anchors are strong and audited |
| Fire footprint | `src/orchestrator/sources/nifc.py` | Incident footprint and acreage data | Complex/incident area thresholding | `fire.build_fire_footprint_bundle` | Hectares, tier, complex, region, country, start date | Needs tests that burned-area units and incident identity survive into prompt |
| CO2 | `src/orchestrator/sources/co2.py` | Atmospheric CO2 measurement | Milestone crossing | `atmospheric.build_co2_milestone_bundle` | PPM, measurement date, preindustrial baseline | Needs audit that milestone threshold and actual measurement are both present |
| Methane | `src/orchestrator/sources/methane.py` | Atmospheric CH4 measurement | Milestone crossing | `atmospheric.build_ch4_milestone_bundle` | PPB crossed, actual PPB, source, preindustrial baseline | Same milestone risk as CO2 |
| ENSO | `src/orchestrator/sources/enso.py` | ONI/status data | Status transition and duration | `atmospheric.build_enso_bundle` | Season, status from/to, ONI value, previous duration | Needs tests that the prompt cannot confuse status transition with forecast |
| Climate indices | `src/orchestrator/sources/climate_indices.py` | Oscillation index values and sigma comparisons | Transition, extreme, or alignment event | `atmospheric.build_oscillation_bundle` | Index values, sigma, comparison year, scope | Branching builder has multiple evidence shapes and needs branch-specific tests |
| Ozone hole | `src/orchestrator/sources/ozone_hole.py` | Ozone hole area and comparison data | Seasonal area comparison or record framing | `atmospheric.build_ozone_hole_bundle` | Area, previous-year area, record/trailing mean context | Needs audit that "larger than previous year" is not treated as long-term record unless record context exists |
| Drought | `src/orchestrator/sources/drought.py` | USDM weekly drought categories | State count and severe drought extent | `drought.build_drought_bundle` | State count, worst state, D3/D4 coverage, weekly scope | Needs prompt-ready checks for weekly scope and category definitions |
| GPM precipitation | `src/orchestrator/sources/gpm_imerg.py` | IMERG precipitation estimates | Rainfall total and deviation selection | `precipitation.build_precipitation_bundle` | Rainfall, period, previous value, deviation, cities, lat/lon | Needs explicit source/satellite-estimate caveat if absent from current facts |
| Snow water equivalent | `src/orchestrator/sources/nsidc_snow.py` | NSIDC/SNOTEL-style snow and SWE observations | SWE/deviation/consecutive-day event selection | `precipitation.build_snow_extreme_bundle`, `build_seasonal_snow_bundle` | Station, date, SWE, deviation, previous, archive/elevation/lat/lon | Needs tests around station identity and archive scope |
| Sea ice | `src/orchestrator/sources/sea_ice.py` | Sea ice extent data | Record-low or record-high extent framing | `marine.build_sea_ice_bundle` | Extent, record type, previous extent/year, satellite archive scope | Needs audit that hemisphere/region identity is always present in `where` and raw dump |
| Ice mass | `src/orchestrator/sources/ice_mass.py` | Ice mass monthly/current values | Threshold or record/worst comparison | `marine.build_ice_mass_bundle` | Current mass, monthly value, archive years, previous worst, threshold | Needs tests that negative mass and units are preserved without sign confusion |
| Ocean SST | `src/orchestrator/sources/ocean_sst.py` | Sea-surface temperature anomaly/streak data | Marine heatwave or SST anomaly selection | `marine.build_marine_heatwave_bundle` | Streak days, current anomaly, peak anomaly, archive framing | Needs explicit location/ocean basin scope so the writer does not globalize regional heat |
| Marine waves | `src/orchestrator/sources/marine.py` | Ocean wave height data | Extreme wave threshold | `marine.build_extreme_wave_bundle` | Wave height and ocean/region | Empty historical context needs source and threshold anchors |
| Coral DHW | `src/orchestrator/sources/coral_dhw.py` | Coral Reef Watch-style degree heating weeks | Bleaching stress tier selection | `marine.build_coral_bleaching_bundle` wrapped in `TriageCandidateBundle` | DHW, tier, stress level, source, lat/lon, thresholds | This is the queued triage model to copy after evidence audit is stable |
| NWS alerts | `src/orchestrator/sources/nws_alerts.py` | NWS alert feed | Severe alert type/severity filter | `disasters.build_severe_weather_bundle` | Event type, area, severity, wind/hail/tornado/description/sender | Needs tests that description is treated as source text, not inferred impact |
| GDACS | `src/orchestrator/sources/gdacs.py` | GDACS disaster feed | Alert severity/score filter | `disasters.build_global_disaster_bundle` | Disaster type/name/country/severity/score/population/description | Needs clear distinction between alert score and measured physical severity |
| Copernicus EMS | `src/orchestrator/sources/copernicus_ems.py` | Copernicus EMS activation/feed | Activation and flood/impact selection | `disasters.build_global_flood_bundle` | Activation name, population, area, lat/lon, URL/context | Needs audit that URL/context survives in raw dump for attribution |
| River gauges | `src/orchestrator/sources/river_gauges.py` | Gauge height and flood stage data | Above-stage flood selection | `disasters.build_river_flood_bundle` | Gauge, current stage, flood stage, above-by feet | Empty historical context needs gauge/source anchors and local scope |
| Storm surge | `src/orchestrator/sources/co_ops.py` | CO-OPS water level observations | Observed versus predicted surge anomaly | `disasters.build_storm_surge_bundle` | Observed, predicted, anomaly, station/area | Needs unit tests for anomaly sign and station identity |
| Cyclones | Cyclone helpers in `src/orchestrator/common.py` | Storm track/intensity data | Rapid intensification, tier crossing, landfall, basin record | `disasters.build_cyclone_rapid_intensification_bundle`, `build_cyclone_tier_crossing_bundle`, `build_cyclone_landfall_bundle`, `build_cyclone_basin_record_bundle` | Storm identity, basin, wind values, category/tier, record context where relevant | Shared helper needs branch coverage so each cyclone story type keeps its comparison basis |
| Synthesis | `src/orchestrator/sources/synthesis.py` | Cross-source components already detected elsewhere | Components combined by region/topic | `synthesis.build_synthesis_bundle` | Region, synthesis kind, component count, component facts | Needs guardrails that synthesis cites only included components and does not invent connecting claims |

## Implementation Tasks

### Task 1: Add a Prompt Evidence Audit Module

- [ ] Create `src/two_bot/evidence_contract.py`.
- [ ] Keep the module pure: no network, no disk writes, no LLM calls.
- [ ] Import only standard-library types and `StoryBundle`.
- [ ] Add dataclasses:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.two_bot.types import StoryBundle

EvidenceSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class EvidenceIssue:
    severity: EvidenceSeverity
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class EvidenceAudit:
    signal_kind: str
    event_id: str
    prompt_ready: bool
    issues: tuple[EvidenceIssue, ...]
```

- [ ] Add `audit_story_bundle(bundle: StoryBundle) -> EvidenceAudit`.
- [ ] Add `assert_prompt_ready(bundle: StoryBundle) -> None`.
- [ ] Required error checks:
  - Missing or blank `signal_kind`.
  - Missing or blank `where`.
  - Missing or blank `when`.
  - Missing or blank `event_id`.
  - Missing or non-dict `headline_metric`.
  - Missing `headline_metric.label`.
  - Missing `headline_metric.value`.
  - Empty `current_facts`.
  - Empty `raw_signal_dump`.
- [ ] Required warning checks:
  - Empty `historical_context`.
  - `raw_signal_dump` has fewer than two keys.
  - No source-like key in `raw_signal_dump` or `current_facts`.
  - No explicit unit key or unit-bearing label for numeric headline metrics.
  - `current_facts` contains a dict without a `label`.
  - `current_facts` contains a dict without a `value`.
  - `historical_context` contains a dict without a `label`.
  - `historical_context` contains a dict without a `value`.
- [ ] The audit should set `prompt_ready = False` only when there is at least one `error`. Warnings are allowed because several live sources intentionally have no historical archive.
- [ ] `assert_prompt_ready` should raise `ValueError` with a compact list of issue codes when `prompt_ready` is false.

### Task 2: Add Unit Tests For The Audit Contract

- [ ] Create `tests/two_bot/test_evidence_contract.py`.
- [ ] Add fixtures using real intern builders rather than hand-built dictionaries where possible.
- [ ] Cover these cases:
  - `temperature.build_record_bundle` passes with no errors.
  - `fire.build_fire_bundle` passes with no errors and warns on empty historical context.
  - A bundle with blank `event_id` fails.
  - A bundle with empty `current_facts` fails.
  - A bundle with empty `raw_signal_dump` fails.
  - A bundle whose numeric headline lacks any unit signal emits a warning.
  - `assert_prompt_ready` raises on an error bundle and does not raise on a valid bundle.
- [ ] Keep assertions on issue `code` values, not human prose.

### Task 3: Add Representative Builder Coverage By Source Family

- [ ] Extend or create tests under `tests/two_bot/` so each intern module has at least one prompt-ready bundle assertion.
- [ ] For `src/two_bot/intern/temperature.py`, cover:
  - `build_record_bundle`
  - `build_all_time_record_bundle`
  - `build_anomaly_bundle`
  - `build_simultaneous_records_bundle`
- [ ] For `src/two_bot/intern/fire.py`, cover:
  - `build_fire_bundle`
  - `build_fire_footprint_bundle`
- [ ] For `src/two_bot/intern/atmospheric.py`, cover:
  - `build_co2_milestone_bundle`
  - `build_ch4_milestone_bundle`
  - `build_enso_bundle`
  - one transition branch of `build_oscillation_bundle`
  - one extreme branch of `build_oscillation_bundle`
  - `build_ozone_hole_bundle`
- [ ] For `src/two_bot/intern/disasters.py`, cover:
  - `build_severe_weather_bundle`
  - `build_global_disaster_bundle`
  - `build_river_flood_bundle`
  - `build_storm_surge_bundle`
  - one cyclone builder with record context
- [ ] For `src/two_bot/intern/marine.py`, cover:
  - `build_coral_bleaching_bundle`
  - `build_sea_ice_bundle`
  - `build_ice_mass_bundle`
  - `build_marine_heatwave_bundle`
  - `build_extreme_wave_bundle`
- [ ] For `src/two_bot/intern/drought.py`, cover `build_drought_bundle`.
- [ ] For `src/two_bot/intern/precipitation.py`, cover:
  - `build_precipitation_bundle`
  - `build_snow_extreme_bundle`
  - `build_seasonal_snow_bundle`
- [ ] For `src/two_bot/intern/synthesis.py`, cover `build_synthesis_bundle`.
- [ ] Every representative test should call `audit_story_bundle` and assert `prompt_ready is True`.

### Task 4: Add Source Matrix Documentation For Maintainers

- [ ] Create `docs/source-to-writer-evidence-contract.md`.
- [ ] Copy the source matrix from this plan into that doc.
- [ ] Add a short maintainer rule:

```markdown
When adding or changing a source, update the row for that source family and add or update at least one representative bundle test. The writer only sees `StoryBundle` plus `MemorySlice`; any fact needed for a safe tweet must be present in those objects before generation.
```

- [ ] Add a "Writer Inputs" section with the exact two JSON inputs:
  - `bundle_json` from `StoryBundle`.
  - `memory_json` from `MemorySlice`.
- [ ] Add a "Where Raw Data Disappears" section explaining that source API payloads are not automatically available to the writer after builder conversion.
- [ ] Add a "High-Risk Evidence Gaps" section with these current risks:
  - Empty historical context is common and must be distinguished from missing source facts.
  - Direct `_try_two_bot_draft` calls still bypass the queued triage model used by coral DHW.
  - Branchy builders can lose context in one branch while tests cover another.
  - Synthesis bundles need strict component grounding.
  - Numeric metrics need explicit units and scope.

### Task 5: Wire Audit Into The Pipeline With Blocking Errors And Warning-Only Reporting

- [ ] In `src/two_bot/pipeline.py`, call `audit_story_bundle(bundle)` near the start of `generate_draft`.
- [ ] If `prompt_ready` is false, raise `ValueError` before the writer call. This prevents spending tokens on unusable evidence packets.
- [ ] If the audit has warnings only, keep generation behavior unchanged.
- [ ] Add the warning codes to existing logger output if a logger is already available in the module. If no logger is available, do not introduce a new logging framework; keep the audit callable and test-covered.
- [ ] Add or update pipeline tests so a missing required bundle field blocks writer invocation.

### Task 6: Preserve Writer Prompt Semantics

- [ ] Do not rewrite `src/two_bot/prompts/writer_prompt.py` during the audit module work unless a test proves a missing instruction.
- [ ] If a prompt edit is needed, keep it narrow:
  - State that `current_facts`, `historical_context`, and `raw_signal_dump` are the only source evidence the writer can use.
  - State that empty `historical_context` means "no archive comparison provided," not "there is no historical comparison in the real world."
  - State that raw API payloads outside `bundle_json` are unavailable to the writer.
- [ ] Add a prompt test only if the repo already has prompt snapshot or text-contract tests for writer prompts.

### Task 7: Verification Commands

- [ ] Run the focused tests:

```bash
pytest tests/two_bot/test_evidence_contract.py -q
```

- [ ] Run the broader two-bot tests:

```bash
pytest tests/two_bot -q
```

- [ ] Run the repository's standard Python test command if documented in `pyproject.toml`, `Makefile`, or existing CI scripts.
- [ ] Run formatting or lint commands only if the repo already documents them.

## Acceptance Criteria

- `docs/source-to-writer-evidence-contract.md` exists and names every active source family in the matrix above.
- `src/two_bot/evidence_contract.py` exists and is pure, deterministic, and unit-tested.
- Every intern module has at least one test that builds a real `StoryBundle` and runs `audit_story_bundle`.
- `generate_draft` refuses bundles with missing required evidence before making a writer call.
- Valid current source bundles keep generating exactly as before.
- Empty historical context remains allowed, but it is visible as an audit warning.
- Tests prove the writer is protected from bundles missing `event_id`, `current_facts`, or `raw_signal_dump`.

## Implementation Order

1. Add `src/two_bot/evidence_contract.py`.
2. Add `tests/two_bot/test_evidence_contract.py`.
3. Add representative intern-builder tests source family by source family.
4. Add `docs/source-to-writer-evidence-contract.md`.
5. Wire audit errors into `generate_draft`.
6. Run focused tests.
7. Run broader two-bot tests.
8. Inspect failures and tighten source builders only where tests show actual missing evidence.

## Notes For The Next Session

- Start at current `main` head `330a02b`.
- The worktree was clean when this plan was written.
- `src/orchestrator/sources/coral_dhw.py` is the clearest current example of queue-first triage with `TriageCandidateBundle`.
- Most other source runners still call `_try_two_bot_draft` directly.
- The immediate win is not reducing writer creativity. The win is making sure the writer always receives a complete, inspectable evidence packet before it spends tokens.
