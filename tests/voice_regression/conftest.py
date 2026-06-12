"""Bundle fixtures for the live writer-replay regression suite.

These fixtures construct realistic StoryBundle instances spanning the most
common signal_kinds. Tests in test_writer_replay.py call the real writer
(Sonnet) against each bundle and assert the output passes the safety
pipeline.

To add a new bundle: copy one of the existing `_*_bundle()` fixture
factories, adjust the fields, and parametrize it into the tests in
test_writer_replay.py.
"""

from __future__ import annotations

import pytest

from src.two_bot.types import MemorySlice, StoryBundle


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "voice_replay: live writer-replay test (calls real Anthropic API; "
        "skipped by default, run via the voice-regression workflow)",
    )


# ---------------------------------------------------------------------------
# Bundle fixtures — one per representative signal_kind
# ---------------------------------------------------------------------------


@pytest.fixture
def sissonville_monthly_low_bundle() -> StoryBundle:
    """US Fahrenheit-first, monthly_low, archive-window-only.

    Mirrors the actual Sissonville WV tweet shipped 2026-05-04. Exercises:
    Fahrenheit-first audience routing, archive_window_only language
    constraint, anti-fabrication on temporal/seasonal framing.
    """
    return StoryBundle(
        signal_kind="monthly_low",
        where="Sissonville, West Virginia",
        when="2026-05-04",
        event_id="ghcn_monthly_low_USW00013866_2026_05",
        headline_metric={
            "label": "observed_low_c",
            "value": -2.2,
            "unit": "C",
            "value_f": 28,
        },
        current_facts=[
            {"label": "city", "value": "Sissonville"},
            {"label": "country", "value": "US"},
            {"label": "state", "value": "West Virginia"},
            {"label": "month", "value": "May"},
            {"label": "kind", "value": "low"},
            {"label": "today_temp_c", "value": -2.2},
            {"label": "today_temp_f", "value": 28},
            {"label": "observation_kind", "value": "daily_minimum"},
            {"label": "audience_unit", "value": "fahrenheit_first"},
        ],
        historical_context={
            "prior_record_c": -1.7,
            "prior_record_f": 29,
            "prior_record_year": 2020,
            "archive_years": 16,
            "month": "May",
            "margin_c": -0.5,
            "margin_f": -1,
            "archive_window_only": True,
        },
        raw_signal_dump={
            "city": "Sissonville",
            "country": "US",
            "state": "West Virginia",
            "kind": "low",
            "month": 5,
            "new_temp_c": -2.2,
            "old_record_c": -1.7,
            "old_record_year": 2020,
            "years_of_data": 16,
        },
    )


@pytest.fixture
def dayton_monthly_low_bundle() -> StoryBundle:
    """The Dayton WY bundle that triggered two fact-check kills on 2026-05-08
    for invented temporal framing ("January reading", "three weeks into
    meteorological spring"). Replaying this regularly verifies the writer
    no longer fabricates context for cold-anomaly bundles in Wyoming.
    """
    return StoryBundle(
        signal_kind="monthly_low",
        where="Dayton, Wyoming",
        when="2026-05-05",
        event_id="ghcn_monthly_low_USC00482409_2026_05",
        headline_metric={
            "label": "observed_low_c",
            "value": -9.4,
            "unit": "C",
            "value_f": 15,
        },
        current_facts=[
            {"label": "city", "value": "Dayton"},
            {"label": "country", "value": "US"},
            {"label": "state", "value": "Wyoming"},
            {"label": "month", "value": "May"},
            {"label": "kind", "value": "low"},
            {"label": "today_temp_c", "value": -9.4},
            {"label": "today_temp_f", "value": 15},
            {"label": "observation_kind", "value": "daily_minimum"},
            {"label": "audience_unit", "value": "fahrenheit_first"},
        ],
        historical_context={
            "prior_record_c": -8.3,
            "prior_record_f": 17,
            "prior_record_year": 2010,
            "archive_years": 21,
            "month": "May",
            "margin_c": -1.1,
            "margin_f": -2,
            "archive_window_only": True,
        },
        raw_signal_dump={
            "city": "Dayton",
            "country": "US",
            "state": "Wyoming",
            "kind": "low",
            "month": 5,
            "new_temp_c": -9.4,
            "old_record_c": -8.3,
            "old_record_year": 2010,
            "years_of_data": 21,
        },
    )


@pytest.fixture
def verkhoyansk_monthly_high_bundle() -> StoryBundle:
    """Non-US Celsius-first, monthly_high, exotic place name.

    Exercises: geographic orientation rule (Verkhoyansk → "Verkhoyansk,
    Russia"), Celsius-first audience routing, non-US audience_unit.
    """
    return StoryBundle(
        signal_kind="monthly_high",
        where="Verkhoyansk, Russia",
        when="2026-04-29",
        event_id="meteo_monthly_high_Verkhoyansk_2026_04",
        headline_metric={
            "label": "forecast_high_c",
            "value": 14.8,
            "unit": "C",
            "value_f": 59,
        },
        current_facts=[
            {"label": "city", "value": "Verkhoyansk"},
            {"label": "country", "value": "RU"},
            {"label": "month", "value": "April"},
            {"label": "kind", "value": "high"},
            {"label": "today_temp_c", "value": 14.8},
            {"label": "today_temp_f", "value": 59},
            {"label": "audience_unit", "value": "celsius_first"},
        ],
        historical_context={
            "prior_record_c": 12.3,
            "prior_record_f": 54,
            "prior_record_year": 2018,
            "archive_years": 30,
            "month": "April",
            "margin_c": 2.5,
            "margin_f": 5,
            "archive_window_only": True,
        },
        raw_signal_dump={
            "city": "Verkhoyansk",
            "country": "RU",
            "kind": "high",
            "month": 4,
            "new_temp_c": 14.8,
            "old_record_c": 12.3,
            "old_record_year": 2018,
            "years_of_data": 30,
        },
    )


@pytest.fixture
def mali_fire_bundle() -> StoryBundle:
    """Fire signal with no historical_context. Exercises: writer obeying
    the "if historical_context is empty, do not invent rarity claims"
    rule, named-power-plant peer comparison rule.
    """
    return StoryBundle(
        signal_kind="fire",
        where="Mali",
        when="2026-04-30",
        event_id="fire_13.5_-4.2_2026-04-30",
        headline_metric={"label": "FRP", "value": 361.0, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": 95, "unit": "%"},
            {"label": "country", "value": "ML"},
            {"label": "nearest_region", "value": "Mali"},
            {"label": "lat", "value": 13.5},
            {"label": "lon", "value": -4.2},
        ],
        historical_context={},
        raw_signal_dump={
            "lat": 13.5,
            "lon": -4.2,
            "confidence": 95,
            "frp": 361.0,
            "nearest_city": "Mali",
            "country": "ML",
            "event_id": "fire_13.5_-4.2_2026-04-30",
        },
    )


@pytest.fixture
def cyclone_rapid_intensification_bundle() -> StoryBundle:
    """Cyclone RI: Cat 1 to Cat 4 in 24h, with Caribbean warm-pool context."""
    return StoryBundle(
        signal_kind="cyclone_rapid_intensification",
        where="Beryl, Atlantic",
        when="2026-07-02T00:00:00Z",
        event_id="nhc_ri_al012026_12_115",
        headline_metric={"label": "delta_kt_24h", "value": 40, "unit": "kt"},
        current_facts=[
            {"label": "source", "value": "NHC"},
            {"label": "storm_name", "value": "Beryl"},
            {"label": "basin", "value": "Atlantic"},
            {"label": "category", "value": 4},
            {"label": "wind_speed_kt", "value": 115, "unit": "kt"},
            {"label": "central_pressure_mb", "value": 950, "unit": "mb"},
            {"label": "lat", "value": 18.0},
            {"label": "lon", "value": -75.0},
            {"label": "advisory_number", "value": "12"},
            {"label": "public_advisory_url", "value": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
            {"label": "previous_wind_kt", "value": 75, "unit": "kt"},
            {"label": "previous_category", "value": 1},
            {"label": "delta_kt_24h", "value": 40, "unit": "kt"},
            {"label": "region_climate_system", "value": "the Caribbean warm pool"},
            {"label": "climate_mechanism_note", "value": "warm tropical waters feed humidity, heavy rain, and cyclone energy"},
            {"label": "season_context", "value": "Atlantic tropical warm-season regime"},
        ],
        historical_context={
            "window_hours": 24,
            "rapid_intensification_threshold_kt": 30,
        },
        raw_signal_dump={
            "storm_name": "Beryl",
            "basin": "Atlantic",
            "current_wind_kt": 115,
            "previous_wind_kt": 75,
            "delta_kt_24h": 40,
            "current_category": 4,
            "previous_category": 1,
        },
    )


@pytest.fixture
def cyclone_landfall_bundle() -> StoryBundle:
    """Major hurricane landfall, safety-sensitive and manual-only."""
    return StoryBundle(
        signal_kind="cyclone_landfall",
        where="Cedar Key, Florida",
        when="2026-07-02T00:00:00Z",
        event_id="nhc_landfall_al012026_12_cedar_key",
        headline_metric={"label": "category", "value": 3},
        current_facts=[
            {"label": "source", "value": "NHC"},
            {"label": "storm_name", "value": "Beryl"},
            {"label": "basin", "value": "Atlantic"},
            {"label": "category", "value": 3},
            {"label": "wind_speed_kt", "value": 100, "unit": "kt"},
            {"label": "central_pressure_mb", "value": 960, "unit": "mb"},
            {"label": "lat", "value": 29.1},
            {"label": "lon", "value": -83.0},
            {"label": "advisory_number", "value": "12"},
            {"label": "public_advisory_url", "value": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
            {"label": "landfall_location", "value": "Cedar Key, Florida"},
            {"label": "region_climate_system", "value": "the Gulf Coast humid subtropical belt"},
            {"label": "climate_mechanism_note", "value": "warm Gulf moisture feeds humid heat and heavy-rain setups"},
        ],
        historical_context={"scope": "major_hurricane_landfall"},
        raw_signal_dump={
            "storm_name": "Beryl",
            "basin": "Atlantic",
            "category": 3,
            "wind_kt": 100,
            "location": "Cedar Key, Florida",
        },
    )


@pytest.fixture
def cyclone_basin_record_bundle() -> StoryBundle:
    """Atlantic basin record fixture for archive-backed cyclone wording."""
    return StoryBundle(
        signal_kind="cyclone_basin_record",
        where="Beryl, Atlantic",
        when="2026-06-15T00:00:00Z",
        event_id="nhc_record_al012026_9_earliest_cat4",
        headline_metric={"label": "category", "value": 4},
        current_facts=[
            {"label": "source", "value": "NHC"},
            {"label": "storm_name", "value": "Beryl"},
            {"label": "basin", "value": "Atlantic"},
            {"label": "category", "value": 4},
            {"label": "wind_speed_kt", "value": 115, "unit": "kt"},
            {"label": "central_pressure_mb", "value": 950, "unit": "mb"},
            {"label": "lat", "value": 14.5},
            {"label": "lon", "value": -57.0},
            {"label": "advisory_number", "value": "9"},
            {"label": "public_advisory_url", "value": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"},
            {"label": "record_label", "value": "earliest Atlantic Category 4 on record"},
            {"label": "record_scope", "value": "Atlantic best-track archive"},
        ],
        historical_context={
            "record_label": "earliest Atlantic Category 4 on record",
            "record_scope": "Atlantic best-track archive",
            "scope": "basin_record",
        },
        raw_signal_dump={
            "storm_name": "Beryl",
            "basin": "Atlantic",
            "category": 4,
            "wind_kt": 115,
            "record_label": "earliest Atlantic Category 4 on record",
        },
    )


@pytest.fixture
def co2_milestone_bundle() -> StoryBundle:
    """CO2 milestone — no city, no temperature. Tests writer adapting to
    a non-place, non-temperature signal kind."""
    return StoryBundle(
        signal_kind="co2_milestone",
        where="Mauna Loa",
        when="2026-04-19",
        event_id="co2_milestone_436ppm",
        headline_metric={"label": "ppm_crossed", "value": 436, "unit": "ppm"},
        current_facts=[
            {"label": "ppm_crossed", "value": 436},
            {"label": "actual_ppm", "value": 436.1},
            {"label": "source", "value": "NOAA GML"},
            {"label": "station", "value": "Mauna Loa"},
            {"label": "audience_unit", "value": "fahrenheit_first"},
        ],
        historical_context={
            "preindustrial_ppm": 280,
            "first_400ppm_year": 2013,
            "ppm_growth_per_year_recent": 2.5,
        },
        raw_signal_dump={
            "ppm_crossed": 436,
            "actual_ppm": 436.1,
            "date": "2026-04-19",
            "event_id": "co2_milestone_436ppm",
        },
    )


@pytest.fixture
def ch4_milestone_bundle() -> StoryBundle:
    """CH4 methane milestone fixture for NOAA GML atmospheric signals."""
    return StoryBundle(
        signal_kind="ch4_milestone",
        where="NOAA GML global marine surface mean",
        when="2026-04-01",
        event_id="ch4_milestone_1940ppb",
        headline_metric={"label": "ppb_crossed", "value": 1940, "unit": "ppb"},
        current_facts=[
            {"label": "ppb_crossed", "value": 1940},
            {"label": "actual_ppb", "value": 1942.3},
            {"label": "measurement_date", "value": "2026-04-01"},
            {"label": "source_name", "value": "NOAA GML"},
        ],
        historical_context={
            "scope": "atmospheric_ch4_threshold_crossed",
            "preindustrial_baseline_ppb": 722,
        },
        raw_signal_dump={
            "ppb_crossed": 1940,
            "actual_ppb": 1942.3,
            "date": "2026-04-01",
            "event_id": "ch4_milestone_1940ppb",
            "source_name": "NOAA GML",
        },
    )


@pytest.fixture
def coral_bleaching_bundle() -> StoryBundle:
    """Coral bleaching DHW fixture with CRW region and threshold facts."""
    return StoryBundle(
        signal_kind="coral_bleaching",
        where="Northern GBR",
        when="2026-05-13",
        event_id="coral_dhw_gbr_northern_tier8",
        headline_metric={"label": "DHW", "value": 8.2, "unit": "°C-weeks"},
        current_facts=[
            {"label": "region_id", "value": "gbr_northern"},
            {"label": "region_full_name", "value": "Northern GBR"},
            {"label": "dhw_value", "value": 8.2, "unit": "°C-weeks"},
            {"label": "dhw_tier", "value": 8, "unit": "°C-weeks"},
            {"label": "bleaching_level", "value": "mass bleaching expected"},
            {"label": "stress_level", "value": "Alert Level 1"},
            {"label": "source_name", "value": "NOAA Coral Reef Watch"},
            {"label": "region_climate_system", "value": "the Great Barrier Reef shelf lagoon"},
            {
                "label": "climate_mechanism_note",
                "value": "a shallow tropical shelf reef system is exposed to marine heat stress",
            },
        ],
        historical_context={
            "scope": "coral_reef_watch_regional_dhw_threshold",
            "thresholds_c_weeks": [4, 8, 12],
        },
        raw_signal_dump={
            "region_id": "gbr_northern",
            "region_full_name": "Northern GBR",
            "date": "2026-05-13",
            "dhw_value": 8.2,
            "dhw_tier": 8,
            "bleaching_level": "mass bleaching expected",
            "stress_level": "Alert Level 1",
        },
    )


@pytest.fixture
def regional_anomaly_bundle() -> StoryBundle:
    """A realistic Sahel regional-anomaly bundle, built by the production builder.

    Honesty Layer 1 is baked in (where = "N sampled cities in Sahel",
    data_kind = point_index_not_area_weighted, forbidden_claims). Used to exercise
    Layers 2-3 (writer + fact-check prompts) live."""
    from src.data.reanalysis_anomaly import RegionalAnomalyEvent
    from src.two_bot.intern import build_regional_anomaly_bundle

    ev = RegionalAnomalyEvent(
        region="Sahel",
        region_slug="Sahel",
        cities_sampled=7,
        mean_anomaly_c=7.8,
        mean_zscore=3.4,
        fraction_exceeding=0.86,
        sustained_days=5,
        window_start="2026-06-03",
        window_end="2026-06-07",
        event_id="reganom_Sahel_2026-06-07",
    )
    return build_regional_anomaly_bundle(ev)


@pytest.fixture
def precipitation_extreme_bundle() -> StoryBundle:
    """GPM precipitation record fixture with city-cluster context."""
    from src.data.gpm_imerg import PrecipExtremeEvent
    from src.two_bot.intern import build_precipitation_bundle

    ev = PrecipExtremeEvent(
        kind="daily_city_cluster",
        location="Sylhet",
        country="Bangladesh",
        date="2026-06-11",
        mm_total=186.4,
        period_days=1,
        deviation_from_record_mm=34.2,
        previous_record_mm=152.2,
        previous_record_year=2017,
        lat=24.9,
        lon=91.9,
        city_count=5,
        sample_cities=["Sylhet", "Moulvibazar", "Sunamganj"],
        event_id="precip_extreme_sylhet_2026-06-11",
    )
    return build_precipitation_bundle(ev)


@pytest.fixture
def air_quality_hazard_bundle() -> StoryBundle:
    """CAMS PM2.5 hazard fixture for a dense South Asian city."""
    from src.data.air_quality import PM25HazardEvent
    from src.two_bot.intern import build_pm25_hazard_bundle

    ev = PM25HazardEvent(
        city="Lahore",
        country="Pakistan",
        lat=31.5,
        lon=74.3,
        date="2026-06-11",
        pm25_24h_mean=182.6,
        tier=1,
        who_multiple=12.2,
        us_aqi_daily_max=244,
        event_id="pm25_lahore_2026-06-11_tier1",
    )
    return build_pm25_hazard_bundle(ev)


@pytest.fixture
def dust_event_bundle() -> StoryBundle:
    """Mineral dust fixture with CAMS model evidence and AOD support."""
    from src.data.air_quality import DustEvent
    from src.two_bot.intern import build_dust_event_bundle

    ev = DustEvent(
        city="Khartoum",
        country="Sudan",
        lat=15.5,
        lon=32.6,
        date="2026-06-11",
        dust_daily_max=1640.0,
        tier=1,
        aod_daily_max=1.74,
        event_id="dust_khartoum_2026-06-11_tier1",
    )
    return build_dust_event_bundle(ev)


@pytest.fixture
def synthesis_fire_drought_heat_bundle() -> StoryBundle:
    """Cross-source fire + drought + heat synthesis fixture."""
    from src.two_bot.intern import build_synthesis_bundle

    synthesis = {
        "event_id": "synthesis_fire_drought_heat_texas_2026-06-11",
        "region": "Texas",
        "kind": "fire_drought_heat",
        "headline": "Texas fire, drought, and heat signals overlap",
        "rule_name": "RULE_FIRE_DROUGHT_HEAT",
        "components": [
            {"kind": "drought", "d4_pct": 18.4},
            {"kind": "fire", "peak_frp_mw": 920.0, "peak_region": "Panhandle"},
            {
                "kind": "heat",
                "peak_city": "Laredo",
                "peak_kind": "monthly_high",
                "peak_value_c": 43.1,
            },
        ],
        "window_days": 14,
        "total_score": 88,
    }
    return build_synthesis_bundle(synthesis)


@pytest.fixture
def marine_heatwave_bundle() -> StoryBundle:
    """Global ocean SST streak fixture for marine heatwave wording."""
    from src.data.ocean_sst import MarineHeatwaveStreakEvent
    from src.two_bot.intern import build_marine_heatwave_bundle

    ev = MarineHeatwaveStreakEvent(
        kind="milestone",
        days=150,
        peak_anomaly_c=0.92,
        today_c=21.18,
        archive_max_c=20.74,
        archive_max_year=2024,
        years_of_data=44,
        date="2026-06-11",
        event_id="global_sst_streak_150_2026-06-11",
    )
    return build_marine_heatwave_bundle(ev)


@pytest.fixture
def wet_bulb_extreme_bundle() -> StoryBundle:
    """Wet-bulb extreme fixture with audience units and health-context facts."""
    from src.data.open_meteo import WetBulbEvent
    from src.two_bot.intern import build_wet_bulb_bundle

    ev = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=34.1,
        tier=2,
        tier_label="extreme",
        tier_threshold_c=33.0,
        event_id="wetbulb_jacobabad_2026-06-11_tier2",
        signal_date=None,
        lat=28.3,
        lon=68.4,
        archive_max_tw_c=33.6,
        archive_max_year=2022,
        archive_years=31,
    )
    return build_wet_bulb_bundle(ev)


@pytest.fixture
def fresh_memory_slice() -> MemorySlice:
    """Empty memory — all era anchors / peer comparisons / framings
    available. Used in replay tests so writer isn't constrained by
    test-irrelevant memory state."""
    return MemorySlice(
        recent_tweets_same_country=[],
        recent_tweets_same_event=[],
        ongoing_event=None,
        used_era_anchors=[],
        used_peer_comparisons=[],
        used_framings=[],
        shipped_tweet_texts=[],
    )
