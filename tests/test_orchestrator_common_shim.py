from src.orchestrator import common


LEGACY_COMMON_ALL = [
    "Any",
    "AbsoluteExtremeEvent",
    "AllTimeRecord",
    "AnomalyEvent",
    "BasinRecordEvent",
    "BotState",
    "CH4_ANNUAL_CAP",
    "CO2_ANNUAL_CAP",
    "CORAL_DHW_ANNUAL_CAP",
    "CITY_COOLDOWN_DAYS",
    "CandidateBundle",
    "CycloneAdvisory",
    "ELITE_COPY_SCORE",
    "EditorialScore",
    "ICE_ANNUAL_CAP",
    "LandfallEvent",
    "MAX_DRAFTS",
    "MonthlyRecord",
    "RapidIntensificationEvent",
    "RecordEvent",
    "SNOW_ANNUAL_CAP",
    "SST_ANOM_ANNUAL_CAP",
    "SourceSkipped",
    "TierCrossingEvent",
    "WetBulbEvent",
    "_CURRENT_SUPPRESSION_CTX",
    "_activate_suppression_ctx",
    "_bundle_for_cyclone_event",
    "_ch4_annual_cap_reached",
    "_check_city_extreme_signals",
    "_classify_ghcn_source_status",
    "_clear_suppression_ctx",
    "_co2_annual_cap_reached",
    "_coral_dhw_annual_cap_reached",
    "_current_suppression_ctx",
    "_cyclone_history_advisories",
    "_cyclone_review_context",
    "_evaluator_metadata_from_bundle",
    "_fact",
    "_fetch_strict",
    "_find_draft",
    "_ice_annual_cap_reached",
    "_increment_co2_annual_count",
    "_increment_ice_annual_count",
    "_increment_snow_annual_count",
    "_maybe_shadow_two_bot",
    "_near_miss_gap",
    "_parse_iso_utc",
    "_posted_city_within_days",
    "_previous_drafts_for_event",
    "_process_cyclone_source",
    "_record_downstream_suppression",
    "_record_save_rejection",
    "_record_source_run",
    "_record_suppression",
    "_review_context",
    "_same_day_already_posted",
    "_same_day_pending_collision",
    "_save_generated_draft",
    "_score_cyclone_event",
    "_score_field",
    "_score_int",
    "_score_reasons",
    "_should_draft",
    "_snow_annual_cap_reached",
    "_sst_anom_annual_cap_reached",
    "_suppression_context",
    "_temp_pair_c",
    "_touch_draft",
    "_triage_enabled",
    "_enqueue_candidate",
    "_enqueue_story_candidate",
    "_bump_source_field_in_run",
    "_bump_run_drafted",
    "_drain_and_write_triage_queue",
    "_try_two_bot_draft",
    "_two_bot_bundle_for_extreme_signal",
    "_unwrap_generated_result",
    "_utc_after_minutes_iso",
    "_utc_now",
    "_utc_now_iso",
    "air_quality",
    "argparse",
    "cast",
    "cities_to_state_map",
    "co2",
    "climate_indices",
    "contextlib",
    "copernicus_ems",
    "coral_dhw",
    "date",
    "datetime",
    "drought",
    "enso",
    "firms",
    "fire_footprint",
    "gdacs",
    "generator",
    "ghcn",
    "gpm_imerg",
    "ice_mass",
    "jtwc",
    "latest_advisories_by_storm",
    "lat_lon_to_state",
    "methane",
    "nhc",
    "nsidc_snow",
    "nws_alerts",
    "ocean",
    "ocean_sst",
    "ocean_sst_anomaly",
    "open_meteo",
    "ozone_hole",
    "os",
    "post_to_bluesky",
    "post_tweet",
    "recommend_approval_policy",
    "river_gauges",
    "run_safety_pipeline",
    "save_draft",
    "score_all_time_record",
    "score_anomaly",
    "score_absolute_extreme",
    "score_ch4_milestone",
    "score_co2_milestone",
    "score_coral_bleaching",
    "score_country_record",
    "score_cyclone_basin_record",
    "score_cyclone_landfall",
    "score_cyclone_rapid_intensification",
    "score_cyclone_tier_crossing",
    "score_dust_event",
    "score_drought",
    "score_enso_transition",
    "score_oscillation_transition",
    "score_oscillation_extreme",
    "score_ozone_hole_peak",
    "score_extreme_wave",
    "score_fire_event",
    "score_fire_footprint",
    "score_global_disaster",
    "score_global_flood",
    "score_hot10",
    "score_ice_mass_event",
    "score_marine_heatwave",
    "score_regional_sst_anomaly",
    "score_monthly_record",
    "score_pm25_hazard",
    "score_precipitation_extreme",
    "score_record_event",
    "score_record_low_event",
    "score_record_streak",
    "score_river_flood",
    "score_sea_ice_record",
    "score_seasonal_snow_record",
    "score_regional_anomaly",
    "score_severe_weather",
    "score_simultaneous_records",
    "score_snow_extreme",
    "score_storm_surge",
    "score_synthesis_fire_drought_heat",
    "score_wet_bulb_extreme",
    "sea_ice",
    "secrets",
    "select_roll_call_subset",
    "state",
    "synthesis",
    "sys",
    "time",
    "timedelta",
    "water_levels",
]


def test_common_shim_exports_legacy_all():
    assert set(LEGACY_COMMON_ALL) <= set(common.__all__)


def test_common_shim_points_moved_symbols_at_split_modules():
    from src.orchestrator import (
        caps,
        cyclones,
        dedup,
        draft_save,
        suppression,
        telemetry,
        triage_queue,
        two_bot_dispatch,
    )

    assert common._co2_annual_cap_reached is caps._co2_annual_cap_reached
    assert common._should_draft is suppression._should_draft
    assert common._record_source_run is telemetry._record_source_run
    assert common._process_cyclone_source is cyclones._process_cyclone_source
    assert common._same_day_pending_collision is dedup._same_day_pending_collision
    assert common.save_draft is draft_save.save_draft
    assert common._try_two_bot_draft is two_bot_dispatch._try_two_bot_draft
    assert common._drain_and_write_triage_queue is triage_queue._drain_and_write_triage_queue


def test_main_sync_compat_globals_updates_split_modules(monkeypatch):
    import src.main as main
    from src.orchestrator import common as common_module
    from src.orchestrator import draft_save, two_bot_dispatch

    original_common_save = common_module.save_draft
    original_draft_save = draft_save.save_draft
    original_dispatch_save = two_bot_dispatch.save_draft

    def fake_save_draft(*args, **kwargs):
        return True

    try:
        monkeypatch.setattr(main, "save_draft", fake_save_draft)
        main._sync_compat_globals()

        assert draft_save.save_draft is fake_save_draft
        assert two_bot_dispatch.save_draft is fake_save_draft
    finally:
        common_module.save_draft = original_common_save
        draft_save.save_draft = original_draft_save
        two_bot_dispatch.save_draft = original_dispatch_save
