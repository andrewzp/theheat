"""Top-level alerts orchestration."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *
from src.orchestrator.finalize import _fire_surviving_draft_callbacks, _prune_weakest_cycle_drafts
from src.orchestrator.scheduler import SourceRunner, concurrent_sources_enabled, run_stage1_then_synthesis
from src.orchestrator.sources.co2 import run_co2
from src.orchestrator.sources.co_ops import run_water_levels
from src.orchestrator.sources.climate_indices import run_climate_indices
from src.orchestrator.sources.copernicus_ems import run_copernicus_ems
from src.orchestrator.sources.coral_dhw import run_coral_dhw
from src.orchestrator.sources.drought import run_drought
from src.orchestrator.sources.enso import run_enso
from src.orchestrator.sources.firms import run_firms
from src.orchestrator.sources.gdacs import run_gdacs
from src.orchestrator.sources.gpm_imerg import run_gpm_imerg
from src.orchestrator.sources.ice_mass import run_ice_mass
from src.orchestrator.sources.marine import run_ocean
from src.orchestrator.sources.methane import run_methane
from src.orchestrator.sources.nifc import run_fire_footprint
from src.orchestrator.sources.nws_alerts import run_nws_alerts
from src.orchestrator.sources.nsidc_snow import run_nsidc_snow
from src.orchestrator.sources.ocean_sst import run_ocean_sst
from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly
from src.orchestrator.sources.air_quality import run_air_quality
from src.orchestrator.sources.ozone_hole import run_ozone_hole
from src.orchestrator.sources.open_meteo import run_extreme_signals
from src.orchestrator.sources.reanalysis_anomaly import run_reanalysis_anomaly
from src.orchestrator.sources.river_gauges import run_river_gauges
from src.orchestrator.sources.sea_ice import run_sea_ice
from src.orchestrator.sources.synthesis import run_synthesis
from src.orchestrator.sources.usgs_quakes import run_usgs_quakes


def run_alerts(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Check all alert data sources and save drafts."""
    _activate_suppression_ctx(
        bot_state,
        source="alerts",
        run_id=(current_run or {}).get("id"),
    )
    # Guard: drop any stale triage queue from a crashed prior cron. This MUST
    # run before any source runners so the queue starts fresh each cycle.
    # (Two-guard pattern: this clears on entry; sqlite_store skips on persist.)
    # Cast to plain dict: _triage_queue is a transient key not declared in BotState.
    cast(dict, bot_state).pop("_triage_queue", None)

    # Phase A funnel telemetry (default OFF). Attach the sink BEFORE any source
    # runner so score-gate kills during the run are counted live. finalize_funnel
    # pops it after the cycle-cap prune. Transient — never persisted.
    from src.orchestrator import funnel as _funnel

    cast(dict, bot_state).pop("_funnel_sink", None)
    funnel_sink = _funnel.new_funnel() if _funnel.funnel_telemetry_enabled() else None
    _funnel.attach_sink(bot_state, funnel_sink)

    drafts_before = len(bot_state.get("drafts", []))
    us_city_state_map: dict[str, str] = {}
    cities_start = time.perf_counter()
    try:
        cities = open_meteo.load_cities()
        us_city_state_map = cities_to_state_map(cities)
        _record_source_run(
            current_run, bot_state, "load_cities", cities_start,
            status="success", observed=len(cities), promoted=len(cities)
        )
    except Exception as e:
        print(f"[alerts] Failed to load cities: {e}")
        state.log_error(bot_state, "load_cities", str(e))
        cities = []
        _record_source_run(
            current_run, bot_state, "load_cities", cities_start,
            status="failed", error=str(e)
        )

    # (city, country) → elevation lookup for downstream prompt enrichment
    # (notably the simultaneous_records roll-call format, which surfaces
    # stations spanning low and high altitudes). Keyed by the pair because
    # cities.csv has duplicate city names across countries (Hyderabad in
    # India and Pakistan, Barcelona in Spain and Venezuela, etc.) — keying
    # by city alone silently inherits the wrong country's elevation. Rows
    # where elevation_m is empty are silently skipped.
    city_elevations: dict[tuple[str, str], int] = {}
    for c in cities:
        raw = (c.get("elevation_m") or "").strip()
        if not raw:
            continue
        try:
            city_elevations[(c["city"], c["country"])] = int(float(raw))
        except (ValueError, TypeError):
            continue

    if concurrent_sources_enabled():
        run_stage1_then_synthesis(
            bot_state,
            current_run,
            serial_runners=[
                SourceRunner(
                    "open_meteo_extreme_signals",
                    lambda: run_extreme_signals(
                        bot_state,
                        current_run,
                        cities,
                        us_city_state_map,
                        city_elevations,
                    ),
                ),
                SourceRunner("firms", lambda: run_firms(bot_state, current_run)),
                SourceRunner("drought", lambda: run_drought(bot_state, current_run)),
            ],
            concurrent_runners=[
                SourceRunner("fire_footprint", lambda: run_fire_footprint(bot_state, current_run)),
                SourceRunner("co2", lambda: run_co2(bot_state, current_run)),
                SourceRunner("ch4_milestone", lambda: run_methane(bot_state, current_run)),
                SourceRunner("nws_alerts", lambda: run_nws_alerts(bot_state, current_run)),
                SourceRunner("gdacs", lambda: run_gdacs(bot_state, current_run)),
                SourceRunner("usgs_quakes", lambda: run_usgs_quakes(bot_state, current_run)),
                SourceRunner("copernicus_ems", lambda: run_copernicus_ems(bot_state, current_run)),
                SourceRunner(
                    "nhc",
                    lambda: _process_cyclone_source(
                        bot_state,
                        current_run,
                        source_key="nhc",
                        source_label="NHC",
                        fetch_fn=nhc.fetch_active_cyclones,
                        detect_module=nhc,
                    ),
                ),
                SourceRunner(
                    "jtwc",
                    lambda: _process_cyclone_source(
                        bot_state,
                        current_run,
                        source_key="jtwc",
                        source_label="JTWC",
                        fetch_fn=jtwc.fetch_active_cyclones,
                        detect_module=jtwc,
                    ),
                ),
                SourceRunner(
                    "sea_ice",
                    lambda: run_sea_ice(bot_state, current_run),
                    health_sources=("sea_ice_arctic", "sea_ice_antarctic"),
                ),
                SourceRunner("enso", lambda: run_enso(bot_state, current_run)),
                SourceRunner(
                    "climate_indices",
                    lambda: run_climate_indices(bot_state, current_run),
                    health_sources=("nao", "ao", "pdo", "nao_ao_alignment"),
                ),
                SourceRunner("ocean", lambda: run_ocean(bot_state, current_run)),
                SourceRunner("ocean_sst", lambda: run_ocean_sst(bot_state, current_run)),
                SourceRunner("ocean_sst_anomaly", lambda: run_ocean_sst_anomaly(bot_state, current_run)),
                SourceRunner("air_quality", lambda: run_air_quality(bot_state, current_run, cities)),
                SourceRunner("coral_dhw", lambda: run_coral_dhw(bot_state, current_run)),
                SourceRunner("water_levels", lambda: run_water_levels(bot_state, current_run)),
                SourceRunner("river_gauges", lambda: run_river_gauges(bot_state, current_run)),
                SourceRunner(
                    "ice_mass",
                    lambda: run_ice_mass(bot_state, current_run),
                    health_sources=("ice_mass_greenland", "ice_mass_antarctica"),
                ),
                SourceRunner("gpm_imerg", lambda: run_gpm_imerg(bot_state, current_run, cities)),
                SourceRunner("nsidc_snow", lambda: run_nsidc_snow(bot_state, current_run)),
                SourceRunner("ozone_hole", lambda: run_ozone_hole(bot_state, current_run)),
                SourceRunner("reanalysis_anomaly", lambda: run_reanalysis_anomaly(bot_state, current_run)),
            ],
            synthesis_runner=SourceRunner(
                "synthesis_fire_drought_heat",
                lambda: run_synthesis(bot_state, current_run),
            ),
        )
    else:
        run_extreme_signals(
            bot_state,
            current_run,
            cities,
            us_city_state_map,
            city_elevations,
        )
        run_firms(bot_state, current_run)
        run_fire_footprint(bot_state, current_run)
        run_co2(bot_state, current_run)
        run_methane(bot_state, current_run)
        run_nws_alerts(bot_state, current_run)
        run_gdacs(bot_state, current_run)
        run_usgs_quakes(bot_state, current_run)
        run_copernicus_ems(bot_state, current_run)
        _process_cyclone_source(
            bot_state,
            current_run,
            source_key="nhc",
            source_label="NHC",
            fetch_fn=nhc.fetch_active_cyclones,
            detect_module=nhc,
        )
        _process_cyclone_source(
            bot_state,
            current_run,
            source_key="jtwc",
            source_label="JTWC",
            fetch_fn=jtwc.fetch_active_cyclones,
            detect_module=jtwc,
        )
        run_sea_ice(bot_state, current_run)
        run_drought(bot_state, current_run)
        run_enso(bot_state, current_run)
        run_climate_indices(bot_state, current_run)
        run_ocean(bot_state, current_run)
        run_ocean_sst(bot_state, current_run)
        run_ocean_sst_anomaly(bot_state, current_run)
        run_air_quality(bot_state, current_run, cities)
        run_coral_dhw(bot_state, current_run)
        run_water_levels(bot_state, current_run)
        run_river_gauges(bot_state, current_run)
        run_ice_mass(bot_state, current_run)
        run_gpm_imerg(bot_state, current_run, cities)
        run_nsidc_snow(bot_state, current_run)
        run_ozone_hole(bot_state, current_run)
        run_reanalysis_anomaly(bot_state, current_run)
        run_synthesis(bot_state, current_run)

    # Drain the triage queue: rank + cap survivors, then call writer for each.
    # Source runners enqueue StoryBundle candidates; this is the only writer
    # gateway for ordinary alert sources.
    # Defer on_draft_success callbacks past the cycle-cap prune (Codex #5): a draft
    # that gets pruned must NOT consume dedup/cap state (annual counts, tiers).
    # Phase A funnel telemetry (default OFF). The drain accumulates writer/
    # fact_check/critic passes + captures the shadow slate into the sink created
    # above; finalize freezes the complete funnel onto current_run AFTER the
    # cycle-cap prune, so cycle_cap reclassification is included.
    pending_callbacks: list = []
    drafted = _drain_and_write_triage_queue(
        bot_state, current_run, defer_callbacks=pending_callbacks, funnel_sink=funnel_sink
    )

    pruned_event_ids: set = set()
    drafted = _prune_weakest_cycle_drafts(
        bot_state, drafts_before, current_run, drafted,
        pruned_ids_out=pruned_event_ids,
    )
    _fire_surviving_draft_callbacks(pending_callbacks, pruned_event_ids)

    if funnel_sink is not None and current_run is not None:
        _funnel.finalize_funnel(
            funnel_sink, current_run, bot_state, pruned_event_ids=pruned_event_ids,
        )

    print(f"[alerts] Done. Saved {drafted} drafts.")
    return bot_state
