"""Top-level alerts orchestration."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *
from src.orchestrator.finalize import _prune_weakest_cycle_drafts
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
from src.orchestrator.sources.air_quality import run_air_quality
from src.orchestrator.sources.ozone_hole import run_ozone_hole
from src.orchestrator.sources.open_meteo import run_extreme_signals
from src.orchestrator.sources.river_gauges import run_river_gauges
from src.orchestrator.sources.sea_ice import run_sea_ice
from src.orchestrator.sources.synthesis import run_synthesis


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
    drafted = 0
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

    drafted += run_extreme_signals(
        bot_state,
        current_run,
        cities,
        us_city_state_map,
        city_elevations,
    )
    drafted += run_firms(bot_state, current_run)
    drafted += run_fire_footprint(bot_state, current_run)
    drafted += run_co2(bot_state, current_run)
    drafted += run_methane(bot_state, current_run)
    drafted += run_nws_alerts(bot_state, current_run)
    drafted += run_gdacs(bot_state, current_run)
    drafted += run_copernicus_ems(bot_state, current_run)
    drafted += _process_cyclone_source(
        bot_state,
        current_run,
        source_key="nhc",
        source_label="NHC",
        fetch_fn=nhc.fetch_active_cyclones,
        detect_module=nhc,
    )
    drafted += _process_cyclone_source(
        bot_state,
        current_run,
        source_key="jtwc",
        source_label="JTWC",
        fetch_fn=jtwc.fetch_active_cyclones,
        detect_module=jtwc,
    )
    drafted += run_sea_ice(bot_state, current_run)
    drafted += run_drought(bot_state, current_run)
    drafted += run_enso(bot_state, current_run)
    drafted += run_climate_indices(bot_state, current_run)
    drafted += run_ocean(bot_state, current_run)
    drafted += run_ocean_sst(bot_state, current_run)
    drafted += run_air_quality(bot_state, current_run, cities)
    drafted += run_coral_dhw(bot_state, current_run)
    drafted += run_water_levels(bot_state, current_run)
    drafted += run_river_gauges(bot_state, current_run)
    drafted += run_ice_mass(bot_state, current_run)
    drafted += run_gpm_imerg(bot_state, current_run, cities)
    drafted += run_nsidc_snow(bot_state, current_run)
    drafted += run_ozone_hole(bot_state, current_run)
    drafted += run_synthesis(bot_state, current_run)

    # Drain the triage queue: rank + cap survivors, then call writer for each.
    # Source runners enqueue StoryBundle candidates; this is the only writer
    # gateway for ordinary alert sources.
    drafted += _drain_and_write_triage_queue(bot_state, current_run)

    drafted = _prune_weakest_cycle_drafts(
        bot_state, drafts_before, current_run, drafted,
    )
    print(f"[alerts] Done. Saved {drafted} drafts.")
    return bot_state
