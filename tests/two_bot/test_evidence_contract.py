from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.data.co2 import CO2Milestone
from src.data.climate_indices import OscillationExtremeEvent, OscillationTransition
from src.data.coral_dhw import CoralBleachingEvent
from src.data.copernicus_ems import CopernicusFloodActivation
from src.data.cyclones import BasinRecordEvent
from src.data.fire_footprint import FireComplex
from src.data.gdacs import GlobalDisasterEvent
from src.data.gpm_imerg import PrecipExtremeEvent
from src.data.ice_mass import IceMassRecord
from src.data.methane import MethaneMilestone
from src.data.nsidc_snow import SnowExtremeEvent
from src.data.nws_alerts import SevereWeatherAlert
from src.data.ocean import ExtremeWaveEvent
from src.data.ocean_sst import MarineHeatwaveStreakEvent
from src.data.open_meteo import AllTimeRecord, AnomalyEvent, RecordEvent
from src.data.ozone_hole import OzoneHoleSeasonalEvent
from src.data.river_gauges import FloodEvent
from src.data.sea_ice import SeaIceRecord
from src.data.water_levels import StormSurgeEvent
from src.two_bot.evidence_contract import (
    EvidenceContractError,
    assert_prompt_ready,
    audit_story_bundle,
)
from src.two_bot.intern import (
    build_all_time_record_bundle,
    build_anomaly_bundle,
    build_ch4_milestone_bundle,
    build_co2_milestone_bundle,
    build_coral_bleaching_bundle,
    build_cyclone_basin_record_bundle,
    build_drought_bundle,
    build_enso_bundle,
    build_extreme_wave_bundle,
    build_fire_bundle,
    build_fire_footprint_bundle,
    build_global_disaster_bundle,
    build_global_flood_bundle,
    build_hot10_bundle,
    build_ice_mass_bundle,
    build_marine_heatwave_bundle,
    build_oscillation_bundle,
    build_ozone_hole_bundle,
    build_precipitation_bundle,
    build_record_bundle,
    build_river_flood_bundle,
    build_sea_ice_bundle,
    build_seasonal_snow_bundle,
    build_severe_weather_bundle,
    build_simultaneous_records_bundle,
    build_snow_extreme_bundle,
    build_storm_surge_bundle,
    build_synthesis_bundle,
)
from tests.two_bot.conftest import _bundle, _fire_event


def _codes(audit) -> set[str]:
    return {issue.code for issue in audit.issues}


def _error_codes(audit) -> set[str]:
    return {issue.code for issue in audit.issues if issue.severity == "error"}


def test_temperature_record_bundle_passes_with_no_errors():
    bundle = build_record_bundle(
        RecordEvent(
            city="Riga",
            country="Latvia",
            new_temp_c=24.4,
            old_record_c=22.6,
            old_record_year=1996,
            event_id="record_Riga_2026-05-03",
        )
    )

    audit = audit_story_bundle(bundle)

    assert audit.prompt_ready is True
    assert _error_codes(audit) == set()


def test_fire_bundle_passes_and_warns_on_empty_historical_context():
    bundle = build_fire_bundle(_fire_event(event_id="fire_evidence"))

    audit = audit_story_bundle(bundle)

    assert audit.prompt_ready is True
    assert _error_codes(audit) == set()
    assert "empty_historical_context" in _codes(audit)


def test_blank_event_id_fails_contract():
    audit = audit_story_bundle(replace(_bundle(), event_id=""))

    assert audit.prompt_ready is False
    assert "missing_event_id" in _error_codes(audit)


def test_empty_current_facts_fails_contract():
    audit = audit_story_bundle(replace(_bundle(), current_facts=[]))

    assert audit.prompt_ready is False
    assert "missing_current_facts" in _error_codes(audit)


def test_empty_raw_signal_dump_fails_contract():
    audit = audit_story_bundle(replace(_bundle(), raw_signal_dump={}))

    assert audit.prompt_ready is False
    assert "missing_raw_signal_dump" in _error_codes(audit)


def test_cached_reading_cannot_reach_triage():
    bundle = replace(
        _bundle(),
        current_facts=[
            {"label": "source", "value": "NOAA"},
            {"label": "last-good", "value": "2026-06-10", "from_cache": True},
        ],
        raw_signal_dump={"source": "NOAA", "event_id": "cached_guard"},
    )

    audit = audit_story_bundle(bundle)

    assert audit.prompt_ready is False
    assert "cached_reading_in_story_bundle" in _error_codes(audit)


def test_numeric_headline_without_unit_signal_warns():
    bundle = replace(
        _bundle(),
        headline_metric={"label": "score", "value": 99},
        raw_signal_dump={"event_id": "unitless_score", "source": "test"},
    )

    audit = audit_story_bundle(bundle)

    assert audit.prompt_ready is True
    assert "numeric_headline_without_unit" in _codes(audit)


def test_assert_prompt_ready_raises_only_for_error_bundles():
    assert_prompt_ready(_bundle())

    with pytest.raises(EvidenceContractError, match="missing_event_id"):
        assert_prompt_ready(replace(_bundle(), event_id=""))


@pytest.mark.parametrize(
    ("case", "bundle"),
    [
        (
            "temperature_all_time",
            build_all_time_record_bundle(
                AllTimeRecord(
                    city="Phoenix",
                    country="US",
                    kind="high",
                    new_temp_c=49.4,
                    old_record_c=48.9,
                    old_record_year=1995,
                    years_of_data=80,
                    event_id="all_time_high_Phoenix_2026-05-04",
                )
            ),
        ),
        (
            "temperature_anomaly",
            build_anomaly_bundle(
                AnomalyEvent(
                    city="Quito",
                    country="Ecuador",
                    today_temp_c=22.0,
                    historical_mean_c=18.0,
                    anomaly_c=4.0,
                    years_of_data=30,
                    event_id="anomaly_Quito",
                )
            ),
        ),
        (
            "temperature_simultaneous",
            build_simultaneous_records_bundle(
                [
                    {
                        "city": "Madrid",
                        "country": "Spain",
                        "temp_c": 38.0,
                        "kind": "high",
                        "old_record_c": 36.5,
                        "old_record_year": 2020,
                        "margin_c": 1.5,
                    },
                    {
                        "city": "Lisbon",
                        "country": "Portugal",
                        "temp_c": 37.0,
                        "kind": "high",
                        "old_record_c": 36.0,
                        "old_record_year": 2018,
                        "margin_c": 1.0,
                    },
                ],
                event_id="simultaneous_2026-05-04",
            ),
        ),
        (
            "hot10",
            build_hot10_bundle(
                [
                    {
                        "city": "Phoenix",
                        "country": "US",
                        "temp_high_c": 47.2,
                        "normal_high_c": 38.0,
                        "anomaly_c": 9.2,
                    }
                ],
                changes=["Phoenix UP 2 spots"],
                event_id="hot10_2026-05-04",
            ),
        ),
        ("fire", build_fire_bundle(_fire_event(event_id="fire_prompt_ready"))),
        (
            "fire_footprint",
            build_fire_footprint_bundle(
                FireComplex(
                    complex_id="cx_001",
                    name="Caldor Fire",
                    country="US",
                    region="California",
                    hectares=89000,
                    start_date=date(2026, 4, 1),
                    tier=2,
                    event_id="ff_cx_001_2",
                )
            ),
        ),
        (
            "co2",
            build_co2_milestone_bundle(
                CO2Milestone(
                    ppm_crossed=434,
                    actual_ppm=434.02,
                    date="2026-05-04",
                    event_id="co2_434_2026-05-04",
                )
            ),
        ),
        (
            "ch4",
            build_ch4_milestone_bundle(
                MethaneMilestone(
                    ppb_crossed=1940,
                    actual_ppb=1942.3,
                    date="2026-04-01",
                    event_id="ch4_milestone_1940ppb",
                )
            ),
        ),
        (
            "enso",
            build_enso_bundle(
                {
                    "event_id": "enso_2026-05",
                    "season": "MAM",
                    "from_status": "Neutral",
                    "to_status": "El Nino",
                    "oni_value": 0.6,
                    "previous_duration_months": 8,
                }
            ),
        ),
        (
            "oscillation_transition",
            build_oscillation_bundle(
                OscillationTransition(
                    index_name="NAO",
                    full_name="North Atlantic Oscillation",
                    year=2026,
                    month=2,
                    value=-1.4,
                    from_phase="Positive",
                    to_phase="Negative",
                    previous_duration_months=6,
                    event_id="oscillation_transition_nao_negative_2026_02",
                )
            ),
        ),
        (
            "oscillation_extreme",
            build_oscillation_bundle(
                OscillationExtremeEvent(
                    index_name="PDO",
                    full_name="Pacific Decadal Oscillation",
                    year=2026,
                    month=4,
                    value=-2.1,
                    mean=0.0,
                    stdev=0.8,
                    sigma_excursion=2.6,
                    comparison_year=1973,
                    comparison_month=5,
                    event_id="oscillation_extreme_pdo_2026_04",
                )
            ),
        ),
        (
            "ozone",
            build_ozone_hole_bundle(
                OzoneHoleSeasonalEvent(
                    year=2026,
                    peak_date="2026-09-20",
                    area_million_km2=23.0,
                    previous_year=2025,
                    previous_area_million_km2=20.8,
                    record_year=2000,
                    record_area_million_km2=29.9,
                    trailing_10yr_mean_area_million_km2=21.4,
                    larger_than_previous_year=True,
                    event_id="ozone_hole_peak_2026",
                )
            ),
        ),
        (
            "severe_weather",
            build_severe_weather_bundle(
                SevereWeatherAlert(
                    event_type="Blizzard Warning",
                    area="Point Lay, AK",
                    severity="Severe",
                    headline="Blizzard Warning issued",
                    event_id="nws_Blizzard_Warning_PointLay",
                    description="40 mph gusts",
                    max_wind_gust="40 mph",
                    max_hail_size="",
                    tornado_detection="",
                    sender_name="NWS Anchorage",
                )
            ),
        ),
        (
            "global_disaster",
            build_global_disaster_bundle(
                GlobalDisasterEvent(
                    disaster_type="Tropical Cyclone",
                    name="Yasi",
                    country="Australia",
                    severity="Red",
                    description="220 km/h sustained",
                    event_id="gdacs_TC_001",
                    alert_score=2.5,
                    severity_value=220.0,
                    severity_unit="km/h",
                    population_affected=120000,
                )
            ),
        ),
        (
            "global_flood",
            build_global_flood_bundle(
                CopernicusFloodActivation(
                    activation_id="EMSR999",
                    country="Colombia",
                    event_type="Riverine flood",
                    severity="Major",
                    populations_affected=125000,
                    affected_area_km2=215.4,
                    lat=8.8,
                    lon=-75.9,
                    activation_date="2026-05-14T12:00:00",
                    copernicus_url="https://mapping.emergency.copernicus.eu/activations/EMSR999/",
                    event_id="copernicus_flood_EMSR999_major",
                    name="Flood in Cordoba, Colombia",
                )
            ),
        ),
        (
            "river_flood",
            build_river_flood_bundle(
                FloodEvent(
                    river="Mississippi",
                    location="Memphis, TN",
                    gauge_height_ft=42.0,
                    flood_stage_ft=34.0,
                    above_by_ft=8.0,
                    date="2026-05-04",
                    event_id="flood_memphis",
                )
            ),
        ),
        (
            "storm_surge",
            build_storm_surge_bundle(
                StormSurgeEvent(
                    station_name="Battery",
                    state="NY",
                    anomaly_m=0.85,
                    observed_m=2.3,
                    predicted_m=1.45,
                    date="2026-05-04",
                    event_id="surge_battery",
                )
            ),
        ),
        (
            "cyclone_basin_record",
            build_cyclone_basin_record_bundle(
                BasinRecordEvent(
                    source="nhc",
                    storm_id="AL012026",
                    storm_name="Beryl",
                    basin="Atlantic",
                    advisory_number="9",
                    issued_at="2026-06-15T00:00:00Z",
                    category=4,
                    wind_kt=115,
                    record_label="earliest Atlantic Category 4 on record",
                    record_scope="Atlantic best-track archive",
                    event_id="nhc_record_al012026_9_earliest_cat4",
                )
            ),
        ),
        (
            "coral",
            build_coral_bleaching_bundle(
                CoralBleachingEvent(
                    region_id="gbr_northern",
                    region_full_name="Northern GBR",
                    date="2026-05-13",
                    dhw_value=8.2,
                    dhw_tier=8,
                    bleaching_level="mass bleaching expected",
                    stress_level="Alert Level 1",
                    lat=-16.1,
                    lon=145.975,
                    event_id="coral_dhw_gbr_northern_tier8",
                )
            ),
        ),
        (
            "sea_ice",
            build_sea_ice_bundle(
                SeaIceRecord(
                    hemisphere="Antarctic",
                    extent_million_km2=2.41,
                    date="2026-02-15",
                    record_type="lowest",
                    previous_extent=2.59,
                    previous_year=2023,
                    event_id="sea_ice_antarctic_2026-02-15",
                )
            ),
        ),
        (
            "ice_mass",
            build_ice_mass_bundle(
                IceMassRecord(
                    region="greenland",
                    kind="monthly_loss_record",
                    month="2026-04",
                    monthly_delta_gt=-450.0,
                    previous_worst_gt=-410.0,
                    previous_worst_month="2019-07",
                    threshold_gt=None,
                    current_mass_gt=None,
                    event_id="ice_mass_grn_2026-04",
                ),
                years_of_record=24,
                archive_start_year=2002,
            ),
        ),
        (
            "marine_heatwave",
            build_marine_heatwave_bundle(
                MarineHeatwaveStreakEvent(
                    kind="milestone",
                    days=400,
                    peak_anomaly_c=0.45,
                    today_c=21.2,
                    archive_max_c=20.9,
                    archive_max_year=2023,
                    years_of_data=44,
                    date="2026-05-04",
                    event_id="mhw_400",
                )
            ),
        ),
        (
            "extreme_wave",
            build_extreme_wave_bundle(
                ExtremeWaveEvent(
                    location="Cape Horn",
                    ocean="South Atlantic",
                    wave_height_m=12.4,
                    date="2026-05-04",
                    event_id="wave_horn",
                )
            ),
        ),
        (
            "drought",
            build_drought_bundle(
                [
                    {
                        "state": "California",
                        "d3_pct": 25.0,
                        "d4_pct": 8.0,
                        "total_drought_pct": 60.0,
                    }
                ],
                event_id="drought_2026-05-04",
            ),
        ),
        (
            "precipitation",
            build_precipitation_bundle(
                PrecipExtremeEvent(
                    kind="daily_record",
                    location="Houston",
                    country="US",
                    date="2026-05-14",
                    mm_total=160.0,
                    period_days=1,
                    deviation_from_record_mm=45.0,
                    previous_record_mm=115.0,
                    previous_record_year=2017,
                    lat=29.8,
                    lon=-95.4,
                    city_count=None,
                    sample_cities=[],
                    event_id="gpm_precip_record_us_houston_2026-05-14",
                )
            ),
        ),
        (
            "snow_extreme",
            build_snow_extreme_bundle(
                SnowExtremeEvent(
                    kind="daily_swe_gain_record",
                    station="Buffalo Snow Site",
                    date="2026-01-15",
                    swe_mm=220.0,
                    mm_swe=76.2,
                    deviation_from_record_mm=30.0,
                    previous_record_mm=46.2,
                    previous_record_year=2022,
                    consecutive_days=None,
                    years_of_archive=None,
                    lat=42.9,
                    lon=-78.9,
                    elevation_m=183.0,
                    event_id="nsidc_snow_daily_swe_gain_record_buffalo_2026-01-15",
                )
            ),
        ),
        (
            "seasonal_snow",
            build_seasonal_snow_bundle(
                SnowExtremeEvent(
                    kind="seasonal_snow_record",
                    station="Albro Lake",
                    date="2026-05-14",
                    swe_mm=500.0,
                    mm_swe=500.0,
                    deviation_from_record_mm=60.0,
                    previous_record_mm=440.0,
                    previous_record_year=2025,
                    consecutive_days=None,
                    years_of_archive=12,
                    lat=45.6,
                    lon=-111.96,
                    elevation_m=2529.8,
                    event_id="nsidc_snow_seasonal_snow_record_albro_lake_2026-05-14",
                )
            ),
        ),
        (
            "synthesis",
            build_synthesis_bundle(
                {
                    "event_id": "synth_TX_2026-05-04",
                    "region": "Texas",
                    "kind": "fire_drought_heat",
                    "headline": "Texas is on fire",
                    "components": [
                        {"kind": "fire", "peak_frp_mw": 800},
                        {"kind": "drought", "d4_pct": 60.0},
                    ],
                    "total_score": 92,
                }
            ),
        ),
    ],
)
def test_representative_source_bundles_are_prompt_ready(case, bundle):
    audit = audit_story_bundle(bundle)

    assert audit.prompt_ready is True, (case, audit.issues)
    assert _error_codes(audit) == set()
