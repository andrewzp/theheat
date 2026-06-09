# Source-To-Writer Evidence Contract

This document describes what The Heat's writer can actually see. Source API
payloads do not reach the writer automatically. A fact is available for a tweet
only if a source runner or intern builder preserves it in `StoryBundle`, and
the writer then receives that bundle alongside `MemorySlice`.

When adding or changing a source, update the row for that source family and add
or update at least one representative bundle test. The writer only sees
`StoryBundle` plus `MemorySlice`; any fact needed for a safe tweet must be
present in those objects before generation.

## Current Flow

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

## Writer Inputs

The writer prompt gets two JSON objects:

- `bundle_json`: the serialized `StoryBundle`.
- `memory_json`: the serialized `MemorySlice`.

`StoryBundle` carries source evidence:

- `signal_kind`
- `where`
- `when`
- `event_id`
- `headline_metric`
- `current_facts`
- `historical_context`
- `raw_signal_dump`

`MemorySlice` carries prior output context:

- recent tweets for the same country
- recent tweets for the same event
- ongoing event context
- previously used era anchors
- previously used peer comparisons
- previously used framings
- shipped tweet texts
- recent categories

## Where Raw Data Disappears

Raw provider responses are transformed before generation. Once a source runner
has selected an event and an intern builder has produced `StoryBundle`, the
writer cannot inspect the original provider payload unless the builder copied
the relevant fields into the bundle.

The most important boundary is:

```text
raw provider payload -> selected event -> StoryBundle -> writer prompt
```

If a detail matters for factual safety, it belongs in `current_facts`,
`historical_context`, `headline_metric`, or `raw_signal_dump`.

## Source Matrix

| Source family | Source runner | Raw ingest | Detection and organization | Writer-facing bundle | Strong evidence already present | Main risk to close |
|---|---|---|---|---|---|---|
| Temperature records | `src/orchestrator/sources/open_meteo.py` | Weather and climate record data assembled into city, country, date, temperature, baseline, archive facts | Record, all-time record, monthly high, anomaly, country record, streak, simultaneous-record routing | `temperature.build_record_bundle`, `build_all_time_record_bundle`, `build_monthly_high_bundle`, `build_anomaly_bundle`, `build_country_record_bundle`, `build_record_streak_bundle`, `build_simultaneous_records_bundle` | Rich current facts, archive years, prior record, margin, units, calendar scope, forbidden claims for all-time records | Many builder variants need shared assertions so one path cannot silently lose archive context or date scope |
| Hot 10 | `src/orchestrator/hot10.py` | Ranked anomaly candidates | Leaderboard selection | `temperature.build_hot10_bundle` | Ranking, anomaly, sample cities | Writer may overstate representativeness unless the bundle keeps leaderboard scope explicit |
| Fire hotspots | `src/orchestrator/sources/firms.py` | FIRMS fire pixels and FRP values | Threshold/tier selection around location and country | `fire.build_fire_bundle` | FRP, FRP tier, country/region, lat/lon, climate facts | Empty historical context is acceptable only if raw location/source anchors are strong and audited |
| Fire footprint | `src/orchestrator/sources/nifc.py` | Incident footprint and acreage data | Complex/incident area thresholding | `fire.build_fire_footprint_bundle` | Hectares, tier, complex, region, country, start date | Burned-area units and incident identity must survive into prompt |
| CO2 | `src/orchestrator/sources/co2.py` | Atmospheric CO2 measurement | Milestone crossing | `atmospheric.build_co2_milestone_bundle` | PPM, measurement date, preindustrial baseline | Milestone threshold and actual measurement must both be present |
| Methane | `src/orchestrator/sources/methane.py` | Atmospheric CH4 measurement | Milestone crossing | `atmospheric.build_ch4_milestone_bundle` | PPB crossed, actual PPB, source, preindustrial baseline | Milestone threshold and actual measurement must both be present |
| ENSO | `src/orchestrator/sources/enso.py` | ONI/status data | Status transition and duration | `atmospheric.build_enso_bundle` | Season, status from/to, ONI value, previous duration | Prompt must not confuse observed status transition with forecast |
| Climate indices | `src/orchestrator/sources/climate_indices.py` | Oscillation index values and sigma comparisons | Transition, extreme, or alignment event | `atmospheric.build_oscillation_bundle` | Index values, sigma, comparison year, scope | Branching builder has multiple evidence shapes and needs branch-specific tests |
| Ozone hole | `src/orchestrator/sources/ozone_hole.py` | Ozone hole area and comparison data | Seasonal area comparison or record framing | `atmospheric.build_ozone_hole_bundle` | Area, previous-year area, record/trailing mean context | Larger than previous year is not a long-term record unless record context exists |
| Drought | `src/orchestrator/sources/drought.py` | USDM weekly drought categories | State count and severe drought extent | `drought.build_drought_bundle` | State count, worst state, D3/D4 coverage, weekly scope | Weekly scope and category definitions must stay visible |
| GPM precipitation | `src/orchestrator/sources/gpm_imerg.py` | IMERG precipitation estimates | Rainfall total and deviation selection | `precipitation.build_precipitation_bundle` | Rainfall, period, previous value, deviation, cities, lat/lon | Satellite-estimate/source caveat should be explicit in bundle evidence |
| Snow water equivalent | `src/orchestrator/sources/nsidc_snow.py` | NSIDC/SNOTEL-style snow and SWE observations | SWE/deviation/consecutive-day event selection | `precipitation.build_snow_extreme_bundle`, `build_seasonal_snow_bundle` | Station, date, SWE, deviation, previous, archive/elevation/lat/lon | Station identity and archive scope must stay intact |
| Sea ice | `src/orchestrator/sources/sea_ice.py` | Sea ice extent data | Record-low or record-high extent framing | `marine.build_sea_ice_bundle` | Extent, record type, previous extent/year, satellite archive scope | Hemisphere/region identity must be present in `where` and raw dump |
| Ice mass | `src/orchestrator/sources/ice_mass.py` | Ice mass monthly/current values | Threshold or record/worst comparison | `marine.build_ice_mass_bundle` | Current mass, monthly value, archive years, previous worst, threshold | Negative mass and units must be preserved without sign confusion |
| Ocean SST | `src/orchestrator/sources/ocean_sst.py` | Sea-surface temperature anomaly/streak data | Marine heatwave or SST anomaly selection | `marine.build_marine_heatwave_bundle` | Streak days, current anomaly, peak anomaly, archive framing | Regional or global scope must be explicit |
| Regional SST anomaly | `src/orchestrator/sources/ocean_sst_anomaly.py` | NOAA Coral Reef Watch gridded SST anomaly via ERDDAP | Basin tier crossing by cos-lat area-weighted mean anomaly | `marine.build_regional_sst_anomaly_bundle` wrapped in `TriageCandidateBundle` | Region, date, anomaly, tier, cells used, CRW source, non-Hobday signal note | Writer must frame as regional SST anomaly, not Hobday marine-heatwave category |
| Marine waves | `src/orchestrator/sources/marine.py` | Ocean wave height data | Extreme wave threshold | `marine.build_extreme_wave_bundle` | Wave height and ocean/region | Empty historical context needs source and threshold anchors |
| Coral DHW | `src/orchestrator/sources/coral_dhw.py` | Coral Reef Watch-style degree heating weeks | Bleaching stress tier selection | `marine.build_coral_bleaching_bundle` wrapped in `TriageCandidateBundle` | DHW, tier, stress level, source, lat/lon, thresholds | This is the queued triage model to copy after evidence audit is stable |
| NWS alerts | `src/orchestrator/sources/nws_alerts.py` | NWS alert feed | Severe alert type/severity filter | `disasters.build_severe_weather_bundle` | Event type, area, severity, wind/hail/tornado/description/sender | Description is source text, not inferred impact |
| GDACS | `src/orchestrator/sources/gdacs.py` | GDACS disaster feed | Alert severity/score filter | `disasters.build_global_disaster_bundle` | Disaster type/name/country/severity/score/population/description | Alert score must not be treated as measured physical severity |
| Copernicus EMS | `src/orchestrator/sources/copernicus_ems.py` | Copernicus EMS activation/feed | Activation and flood/impact selection | `disasters.build_global_flood_bundle` | Activation name, population, area, lat/lon, URL/context | URL/context must survive in raw dump for attribution |
| River gauges | `src/orchestrator/sources/river_gauges.py` | Gauge height and flood stage data | Above-stage flood selection | `disasters.build_river_flood_bundle` | Gauge, current stage, flood stage, above-by feet | Empty historical context needs gauge/source anchors and local scope |
| Storm surge | `src/orchestrator/sources/co_ops.py` | CO-OPS water level observations | Observed versus predicted surge anomaly | `disasters.build_storm_surge_bundle` | Observed, predicted, anomaly, station/area | Anomaly sign and station identity must remain explicit |
| Cyclones | Cyclone helpers in `src/orchestrator/common.py` | Storm track/intensity data | Rapid intensification, tier crossing, landfall, basin record | `disasters.build_cyclone_rapid_intensification_bundle`, `build_cyclone_tier_crossing_bundle`, `build_cyclone_landfall_bundle`, `build_cyclone_basin_record_bundle` | Storm identity, basin, wind values, category/tier, record context where relevant | Each cyclone story type must keep its comparison basis |
| Synthesis | `src/orchestrator/sources/synthesis.py` | Cross-source components already detected elsewhere | Components combined by region/topic | `synthesis.build_synthesis_bundle` | Region, synthesis kind, component count, component facts | Synthesis can cite only included components and must not invent connecting claims |

## High-Risk Evidence Gaps

- Empty historical context is common and must be distinguished from missing source facts.
- Direct `_try_two_bot_draft` calls still bypass the queued triage model used by coral DHW.
- Branchy builders can lose context in one branch while tests cover another.
- Synthesis bundles need strict component grounding.
- Numeric metrics need explicit units and scope.

## Enforcement

`src/two_bot/evidence_contract.py` audits bundles before generation. Errors
block the writer call. Warnings report weak evidence while preserving current
generation behavior.

Required error coverage:

- missing `signal_kind`
- missing `where`
- missing `when`
- missing `event_id`
- missing `headline_metric`
- missing `headline_metric.label`
- missing `headline_metric.value`
- empty `current_facts`
- empty `raw_signal_dump`

Required warning coverage:

- empty `historical_context`
- sparse `raw_signal_dump`
- missing source-like anchor
- numeric headline without unit signal
- malformed fact dictionaries
