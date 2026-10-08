# Source-To-Writer Evidence Contract

This document describes what The Heat's writer can actually see. Source API
payloads do not reach the writer automatically. A fact is available for a tweet
only if a source runner or intern builder preserves it in `StoryBundle`, and
the writer then receives that bundle alongside `MemorySlice`.

When adding or changing a source, update the row for that source family and add
or update at least one representative bundle test. The writer only sees
`StoryBundle` plus `MemorySlice`; any fact needed for a safe tweet must be
present in those objects before generation.

> **Known limitation + planned evolution (2026-06-16).** This contract validates
> structural *completeness* (is the fact present in the bundle?), not *warrant* (is
> the bundle's claim true and entitled to its words?). The 2026-06-16 precip
> false-record incident showed the model permits illegal claims — a "record" that is
> really a hardcoded threshold or a 0.0 baseline — which the writer cites faithfully
> because the field is named `previous_record_mm`. Planned redesign: a claim/warrant
> model where a `Record` is uninstantiable without a real dated baseline, into which
> this contract evolves. See
> [/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-claim-warrant-model.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/plans/2026-06-16-claim-warrant-model.md).

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

Backup-served source facts are carried through ordinary bundle fields plus
explicit provenance:

- `source_leg` on the selected event/reading tells the runner and builder that a
  non-primary leg served the data.
- `evidence_grade=observed_alt_host` means an alternate host/instrument supplied
  an observation.
- `evidence_grade=model_fallback` means a numerical model stood in for a
  measurement; the writer must not call it observed, measured, or recorded.

These grades are writer-facing facts, not decoration. If a source adds a new
witness leg, add/update the relevant bundle test so the grade reaches
`current_facts`.

`MemorySlice` carries prior output context:

- recent published tweets for the same country
- recent published tweets for the same event
- ongoing event context
- previously used era anchors
- previously used peer comparisons
- previously used framings
- shipped tweet texts
- recent categories

Generated, killed, rejected, or pending drafts do not count as coverage. The
publish-backed memory update happens only after a post succeeds.

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
| Fire hotspots | `src/orchestrator/sources/firms.py` | FIRMS fire pixels and FRP values, with NOAA HMS backup for North America and FIRMS product chain for product gaps | Threshold/tier selection around location and country | `fire.build_fire_bundle` | FRP, FRP tier, country/region, lat/lon, climate facts, `observed_alt_host` when NOAA HMS serves | Empty historical context is acceptable only if raw location/source anchors are strong and audited; HMS is alternate observed data, product-chain provenance is not a new evidence grade |
| Fire footprint | `src/orchestrator/sources/nifc.py` | Incident footprint and acreage data | Complex/incident area thresholding | `fire.build_fire_footprint_bundle` | Hectares, tier, complex, region, country, start date | Burned-area units and incident identity must survive into prompt |
| CO2 | `src/orchestrator/sources/co2.py` | Atmospheric CO2 measurement | Milestone crossing | `atmospheric.build_co2_milestone_bundle` | PPM, measurement date, preindustrial baseline | Milestone threshold and actual measurement must both be present |
| Methane | `src/orchestrator/sources/methane.py` | Atmospheric CH4 measurement | Milestone crossing | `atmospheric.build_ch4_milestone_bundle` | PPB crossed, actual PPB, source, preindustrial baseline | Milestone threshold and actual measurement must both be present |
| ENSO | `src/orchestrator/sources/enso.py` | ONI/status data | Status transition and duration | `atmospheric.build_enso_bundle` | Season, status from/to, ONI value, previous duration | Prompt must not confuse observed status transition with forecast |
| Climate indices | `src/orchestrator/sources/climate_indices.py` | Oscillation index values and sigma comparisons | Transition, extreme, or alignment event | `atmospheric.build_oscillation_bundle` | Index values, sigma, comparison year, scope | Branching builder has multiple evidence shapes and needs branch-specific tests |
| Ozone hole | `src/orchestrator/sources/ozone_hole.py` | Ozone hole area and comparison data | Seasonal area comparison or record framing | `atmospheric.build_ozone_hole_bundle` | Area, previous-year area, record/trailing mean context | Larger than previous year is not a long-term record unless record context exists |
| Drought | `src/orchestrator/sources/drought.py` | USDM weekly drought categories | State count and severe drought extent | `drought.build_drought_bundle` | State count, worst state, D3/D4 coverage, weekly scope | Weekly scope and category definitions must stay visible |
| GPM precipitation | `src/orchestrator/sources/gpm_imerg.py` | IMERG precipitation estimates, with Open-Meteo model fallback | Rainfall total and deviation selection | `precipitation.build_precipitation_bundle` | Rainfall, period, previous value, deviation, cities, lat/lon, `model_fallback` when Open-Meteo serves | Satellite-estimate/source caveat should be explicit; model fallback must never be phrased as observed/measured |
| Snow water equivalent | `src/orchestrator/sources/nsidc_snow.py` | NSIDC/SNOTEL-style snow and SWE observations | SWE/deviation/consecutive-day event selection | `precipitation.build_snow_extreme_bundle`, `build_seasonal_snow_bundle` | Station, date, SWE, deviation, previous, archive/elevation/lat/lon | Station identity and archive scope must stay intact |
| Sea ice | `src/orchestrator/sources/sea_ice.py` | Sea ice extent data, with OSI SAF concentration-grid fallback | Record-low or record-high extent framing | `marine.build_sea_ice_bundle` | Extent, record type, previous extent/year, satellite archive scope, `observed_alt_host` when OSI SAF serves | Hemisphere/region identity must be present in `where` and raw dump; OSI SAF values are independent observed-grid estimates, not NSIDC CSV values |
| Ice mass | `src/orchestrator/sources/ice_mass.py` | Ice mass monthly/current values | Threshold or record/worst comparison | `marine.build_ice_mass_bundle` | Current mass, monthly value, archive years, previous worst, threshold | Negative mass and units must be preserved without sign confusion |
| Ocean SST | `src/orchestrator/sources/ocean_sst.py` | Sea-surface temperature anomaly/streak data | Marine heatwave or SST anomaly selection | `marine.build_marine_heatwave_bundle` | Streak days, current anomaly, peak anomaly, archive framing | Regional or global scope must be explicit |
| Regional SST anomaly | `src/orchestrator/sources/ocean_sst_anomaly.py` | NOAA Coral Reef Watch gridded SST anomaly via ERDDAP, with NOAA STAR/CRW NetCDF fallback | Basin tier crossing by cos-lat area-weighted mean anomaly | `marine.build_regional_sst_anomaly_bundle` wrapped in `TriageCandidateBundle` | Region, date, anomaly, tier, cells used, CRW source, non-Hobday signal note, alternate-grid provenance when NOAA STAR serves | Writer must frame as regional SST anomaly, not Hobday marine-heatwave category; fallback fills regions from a latest global NetCDF grid |
| Marine waves | `src/orchestrator/sources/marine.py` | Ocean wave height data | Extreme wave threshold | `marine.build_extreme_wave_bundle` | Wave height and ocean/region | Empty historical context needs source and threshold anchors |
| Coral DHW | `src/orchestrator/sources/coral_dhw.py` | Coral Reef Watch-style degree heating weeks, with CRW ERDDAP grid fallback | Bleaching stress tier selection | `marine.build_coral_bleaching_bundle` wrapped in `TriageCandidateBundle` | DHW, tier, stress level, source, lat/lon, thresholds, `observed_alt_host` when ERDDAP serves | Station/grid mapping must stay pinned and tested so a reef does not inherit another reef's DHW |
| NWS alerts | `src/orchestrator/sources/nws_alerts.py` | NWS alert feed | Severe alert type/severity filter | `disasters.build_severe_weather_bundle` | Event type, area, severity, wind/hail/tornado/description/sender | Description is source text, not inferred impact |
| GDACS | `src/orchestrator/sources/gdacs.py` | GDACS disaster feed, with USGS/NHC/JTWC subtype witnesses during outages | Alert severity/score filter | `disasters.build_global_disaster_bundle` | Disaster type/name/country/severity/score/population/description, subtype-witness provenance | Alert score must not be treated as measured physical severity; subtype witnesses are degraded observations and should not mask the GDACS primary outage |
| USGS earthquakes | `src/orchestrator/sources/usgs_quakes.py` | USGS significant earthquake GeoJSON | Significant earthquake selection | `disasters.build_usgs_earthquake_bundle` | Magnitude, place, depth, PAGER alert, felt reports, ShakeMap intensity, tsunami flag, official URL | Separate source key; do not fold into GDACS health or duplicate GDACS stories |
| Copernicus EMS | `src/orchestrator/sources/copernicus_ems.py` | Copernicus EMS activation/feed, with frontend activations API fallback | Activation and flood/impact selection | `disasters.build_global_flood_bundle` | Activation name, population, area, lat/lon, URL/context, fallback provenance | URL/context must survive in raw dump for attribution; frontend fallback is conservative when impact stats are absent |
| River gauges | `src/orchestrator/sources/river_gauges.py` | Gauge height and flood stage data, with Open-Meteo Flood modeled discharge fallback | Above-stage flood selection or modeled high-discharge selection | `disasters.build_river_flood_bundle` | Gauge/current/flood-stage feet for primary; modeled discharge fields and `model_fallback` for Open-Meteo Flood | Model fallback must omit gauge-height/flood-stage feet and never masquerade as a gauge reading |
| Storm surge | `src/orchestrator/sources/co_ops.py` | CO-OPS water level observations | Observed versus predicted surge anomaly | `disasters.build_storm_surge_bundle` | Observed, predicted, anomaly, station/area | Anomaly sign and station identity must remain explicit |
| Cyclones | Cyclone helpers in `src/orchestrator/common.py` | Storm track/intensity data | Rapid intensification, tier crossing, landfall, basin record | `disasters.build_cyclone_rapid_intensification_bundle`, `build_cyclone_tier_crossing_bundle`, `build_cyclone_landfall_bundle`, `build_cyclone_basin_record_bundle` | Storm identity, basin, wind values, category/tier, record context where relevant | Each cyclone story type must keep its comparison basis |
| Synthesis | `src/orchestrator/sources/synthesis.py` | Existing cross-source inputs; marine pairs require complete qualified CRW source readings | Marine: bounded dated selection within each product family | `synthesis.build_synthesis_bundle` | Marine: both exact source receipts, individual dates/scopes, DHW metric, SST reference climate, explicit evaluation time | A regional association does not prove a shared footprint, simultaneous event, cause, marine heatwave, observed bleaching or mortality; legacy marine scalars remain held |

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

## Air-quality forecast windows

Air-quality collection requests an explicit local calendar day with `timezone=auto`
and `domains=auto`. Its date label comes from one UTC reference captured for the
whole batch; the retained timezone and calculated UTC bounds describe each city's
actual window. The [Open-Meteo air-quality contract](https://open-meteo.com/en/docs/air-quality-api)
describes hourly forecast samples and automatic model-domain selection. The
response does not identify an authoritative model run or universal resolution.

Only 24 ordered, unique hourly labels spanning a real 24-hour local day qualify.
Wrong-day, partial and daylight-saving 23/25-hour windows are withheld. A variable
needs 24 finite, nonnegative values in its documented unit to supply a daily
scalar. Nulls or invalid optional series remove their own scalar; complete dust
can survive unavailable PM10, without a PM10/WHO comparison. Zero remains data.

The versioned selected record retains requested and supplied grid coordinates,
timezone, UTC request/retrieval and window bounds, hourly values and per-variable
availability. Its canonical JSON is limited to 32 KiB. Its digest binds the
selected normalized record, not unavailable raw HTTP bytes or source authenticity.
The mean of hourly forecast samples is not a measured exposure; co-reported dust
and PM10 alone do not establish causality. Nearby station annotations do not turn
the model window into an observed full day.

Primary and related evidence must reproduce the event's aggregates, ratios,
identity and writer-facing projection before writer or required-check calls.
Legacy scalar-only evidence stays retained but cannot pass renewed qualification.
Place/day/tier IDs remain stable; exact evidence, checks and cache identities bind
the changed content. Source qualification does not grant posting approval or prove
live source recovery, lower bills or improved writing.

For primary or related air-quality evidence, a local language check withholds
recognizable causal links before paid checks. A forecast that co-reports dust and
PM10 cannot support wording such as dust "pushing" PM10 higher, or a modeled
concentration "causing" a visibility or health impact. Quotations and forecast
qualifiers do not supply the missing causal evidence.

The rule recognizes a finite set of causal predicates and nearby AQ/impact terms
within a sentence or semicolon-delimited clause. It preserves decimal PM labels,
normalizes Unicode only for scanning, and distinguishes immediate negation from
another affirmative predicate. A narrow standalone general-background form can
reach normal review; common words such as "as" and "due" alone are not causal
triggers. Bare co-reporting and numerical guideline comparisons still require
all usual checks. This is not complete semantic entailment: unrecognized wording,
pronoun-only links and surrounding clause ambiguity remain review limitations.
Exact text, complete source receipts and policy-bound approval identities remain
unchanged by the scan. Passing the local rule is never a factual or posting pass.

## Dated marine comparison evidence

Marine components retain the complete qualified SST or coral reading and source
receipt under a versioned, content-bound component ID, separate from the weekly
publication ID. New acquisitions have distinct IDs. Source runners record them
before individual-event deduplication and caps, including SST readings below the
standalone tier threshold but at or above the existing marine floor. No extra
source request is made. Existing 60-day marine posting cooldowns remain.

Selection uses a captured UTC evaluation time and each product's own valid date.
The 14-day comparison window is an upper bound: stricter source qualification
still applies, including primary regional coral freshness. Future acquisitions,
future/stale dates, altered hashes, legacy scalars and mismatched projections are
withheld. Different qualified values from one source family/region/date conflict
and that group cannot qualify. Identical reacquisitions remain separately bound;
latest acquisition breaks ties. Primary source families take precedence over
backups; within one family the largest retained eligible value is selected. This
is not an exhaustive maximum or a comparison of regional and point statistics.

A component is limited to8KiB and a region to128 stored rows. A pool at or above
capacity is withheld, because rejected insertions could leave it incomplete;
ordinary TTL pruning can make room. Fixed diagnostics report rejected inputs,
conflicting dates and capacity holds. These bounds do not make Gist transactional
or an immutable source archive. Python merge and dashboard preservation tests use
one shared, entirely invented source-shaped fixture.

The marine bundle carries both complete selected records, actual source dates,
regional/point sampling scopes and the SST reference climatology. Its `when` is
explicitly the evaluation date, not an asserted common observation date. Evidence
and direct scientific checks rebuild the full projection. Paired marine bundles
are excluded from scalar-only related-signal projection. Finite language guards
hold named shared-event/time/footprint/causal/impact claims, including derived coral
alert classes without the required source evidence. Conservative lexical guards
can also withhold negative/background phrasing; they are not complete semantic
entailment. All normal checks remain mandatory for eligible copy. No production
recovery, human preference, global recall or cost saving is established by these
offline fixtures.
