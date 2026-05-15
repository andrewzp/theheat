# Main Python Refactor Map

Lane 16 decomposes three large modules without changing behavior:

- `src/main.py` becomes the CLI and compatibility facade.
- `src/orchestrator/` owns alert orchestration, source runners, draft saving,
  posting, suppression logging, and per-cycle pruning.
- `src/editorial/scoring/` owns category-specific score functions with
  `src.editorial.scoring` re-exporting the existing public API.
- `src/two_bot/intern/` owns category-specific bundle builders with
  `src.two_bot.intern` re-exporting the existing public API.

## `src/main.py` Responsibilities

| Current lines | Responsibility | Target module | Public surface |
| --- | --- | --- | --- |
| 1-76 | Imports, process constants | `src/orchestrator/*` and `src/main.py` facade | `MAX_DRAFTS`, imported data modules for legacy patch paths |
| 79-113 | UTC parsing and draft lookup | `src/orchestrator/finalize.py` | `_utc_now`, `_utc_now_iso`, `_utc_after_minutes_iso`, `_parse_iso_utc`, `_find_draft` |
| 115-243 | Run telemetry, GHCN source classification, source fetch wrappers | `src/orchestrator/finalize.py` | `_record_source_run`, `_fetch_strict`, `_classify_ghcn_source_status` |
| 187-339 | Suppression context and near-miss capture | `src/orchestrator/finalize.py` | `_suppression_context`, `_activate_suppression_ctx`, `_clear_suppression_ctx`, `_record_suppression` |
| 341-521 | Draft gate, generated-result unwrap, review-context facts, draft touch helpers | `src/orchestrator/pipeline_routing.py` | `_should_draft`, `_unwrap_generated_result`, `_evaluator_metadata_from_bundle`, `_fact`, `_review_context`, `_touch_draft` |
| 523-577 | Annual source caps | `src/orchestrator/pipeline_routing.py` | `_co2_annual_cap_reached`, `_ch4_annual_cap_reached`, `_coral_dhw_annual_cap_reached`, `_ice_annual_cap_reached`, increment helpers |
| 579-807 | Tropical-cyclone scoring, bundle dispatch, and per-source processing | `src/orchestrator/sources/cyclones.py` | `_process_cyclone_source` plus cyclone-specific helpers |
| 809-1185 | Duplicate guards, draft persistence, and two-bot routing | `src/orchestrator/pipeline_routing.py` | `save_draft`, `_save_generated_draft`, `_two_bot_bundle_for_extreme_signal`, `_try_two_bot_draft`, `_maybe_shadow_two_bot` |
| 1187-1211 | Approved-post publish primitive | `src/orchestrator/posting.py` | `post_approved` |
| 1213-1255 | `run_alerts` setup and city loading | `src/orchestrator/run_alerts.py` | `run_alerts` |
| 1257-1941 | Extreme temperature/GHCN/Open-Meteo/country-record source | `src/orchestrator/sources/open_meteo.py` | `run_extreme_signals` |
| 1943-2111 | FIRMS and NIFC fire footprint source sections | `src/orchestrator/sources/firms.py`, `src/orchestrator/sources/nifc.py` | `run_firms`, `run_fire_footprint` |
| 2113-2238 | CO2 and methane milestones | `src/orchestrator/sources/co2.py`, `src/orchestrator/sources/methane.py` | `run_co2`, `run_methane` |
| 2240-2429 | NWS, GDACS, Copernicus EMS, NHC/JTWC cyclone sections | `src/orchestrator/sources/nws_alerts.py`, `gdacs.py`, `copernicus_ems.py`, `cyclones.py` | source runner functions |
| 2431-2900 | Sea ice, drought, ENSO, ocean waves, SST, coral DHW, CO-OPS, river gauges | `src/orchestrator/sources/*.py` | source runner functions |
| 2902-3191 | GRACE ice mass and cross-source synthesis | `src/orchestrator/sources/ice_mass.py`, `synthesis.py` | source runner functions |
| 3193-3257 | Per-cycle draft cap pruning | `src/orchestrator/finalize.py` | `_prune_weakest_cycle_drafts` |
| 3259-3473 | Hot 10 leaderboard and manual tweet mode | `src/orchestrator/hot10.py`, `src/orchestrator/posting.py` | `run_leaderboard`, `run_manual_tweet` |
| 3475-3551 | Auto-publish queue | `src/orchestrator/posting.py` | `process_due_drafts` |
| 3553-3603 | CLI dispatch and final state write | `src/main.py` | `main` |

## `src/editorial/scoring.py` Responsibilities

| Current lines | Responsibility | Target module |
| --- | --- | --- |
| 1-133 | Score dataclass and shared helpers | `src/editorial/scoring/_shared.py` |
| 135-245, 789-903 | Temperature records, anomalies, streaks, simultaneous records | `src/editorial/scoring/temperature.py` |
| 246-317 | FIRMS and fire-footprint scoring | `src/editorial/scoring/fire.py` |
| 319-365, 688-705 | CO2, methane, and ENSO scoring | `src/editorial/scoring/atmospheric.py` |
| 367-585, 707-753 | Marine, coral, sea-ice, ice-mass, wave, and marine-heatwave scoring | `src/editorial/scoring/marine.py` |
| 393-563, 755-787 | Severe weather, disasters, floods, cyclones, surge, river flood | `src/editorial/scoring/disasters.py` |
| 652-686 | Drought scoring | `src/editorial/scoring/drought.py` |
| 905-921 | Hot 10 scoring | `src/editorial/scoring/hot10.py` |
| 923-964 | Cross-source synthesis scoring | `src/editorial/scoring/synthesis.py` |

## `src/two_bot/intern.py` Responsibilities

| Current lines | Responsibility | Target module |
| --- | --- | --- |
| 1-218 | Shared bundle helpers and constants | `src/two_bot/intern/_shared.py` |
| 220-260, 662-709 | Fire and fire-footprint bundles | `src/two_bot/intern/fire.py` |
| 262-415, 451-660, 1313-1349 | Temperature, country, record, anomaly, simultaneous, Hot 10 bundles | `src/two_bot/intern/temperature.py` |
| 417-449, 812-1020, 1122-1189, 1191-1244 | Severe weather, GDACS, Copernicus floods, cyclones, rivers, storm surge | `src/two_bot/intern/disasters.py` |
| 711-772, 1281-1311 | CO2, methane, and ENSO bundles | `src/two_bot/intern/atmospheric.py` |
| 774-810, 1022-1120, 1217-1244 | Coral, sea ice, ice mass, marine heatwave, and wave bundles | `src/two_bot/intern/marine.py` |
| 1246-1279 | Drought bundle | `src/two_bot/intern/drought.py` |
| 1351-1379 | Cross-source synthesis bundle | `src/two_bot/intern/synthesis.py` |

## Compatibility Notes

Existing tests and operational scripts patch `src.main.*` heavily. The new
`src/main.py` keeps those names as a facade and syncs patched facade objects
into orchestrator implementation modules before dispatching public run modes.
That preserves the existing regression surface while still moving the actual
implementation out of the entrypoint module.
