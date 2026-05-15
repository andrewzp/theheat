from datetime import date

from src.data.co2 import CO2Milestone
from src.data.climate_indices import OscillationAlignmentEvent, OscillationExtremeEvent, OscillationTransition
from src.data.coral_dhw import CoralBleachingEvent
from src.data.copernicus_ems import CopernicusFloodActivation
from src.data.cyclones import (
    BasinRecordEvent,
    LandfallEvent,
    RapidIntensificationEvent,
    TierCrossingEvent,
)
from src.data.fire_footprint import FireComplex
from src.data.gdacs import GlobalDisasterEvent
from src.data.ice_mass import IceMassRecord
from src.data.methane import MethaneMilestone
from src.data.ozone_hole import OzoneHoleSeasonalEvent
from src.data.nws_alerts import SevereWeatherAlert
from src.data.ocean import ExtremeWaveEvent
from src.data.ocean_sst import MarineHeatwaveStreakEvent
from src.data.open_meteo import (
    AllTimeRecord,
    AnomalyEvent,
    CountryRecord,
    MonthlyRecord,
    RecordEvent,
    RecordStreakEvent,
)
from src.data.river_gauges import FloodEvent
from src.data.sea_ice import SeaIceRecord
from src.data.water_levels import StormSurgeEvent
from src.two_bot.intern import (
    build_all_time_record_bundle,
    build_anomaly_bundle,
    build_ch4_milestone_bundle,
    build_co2_milestone_bundle,
    build_coral_bleaching_bundle,
    build_cyclone_basin_record_bundle,
    build_cyclone_landfall_bundle,
    build_cyclone_rapid_intensification_bundle,
    build_cyclone_tier_crossing_bundle,
    build_country_record_bundle,
    build_drought_bundle,
    build_enso_bundle,
    build_oscillation_bundle,
    build_ozone_hole_bundle,
    build_extreme_wave_bundle,
    build_fire_bundle,
    build_fire_footprint_bundle,
    build_global_flood_bundle,
    build_global_disaster_bundle,
    build_hot10_bundle,
    build_ice_mass_bundle,
    build_marine_heatwave_bundle,
    build_monthly_high_bundle,
    build_record_bundle,
    build_record_streak_bundle,
    build_river_flood_bundle,
    build_sea_ice_bundle,
    build_severe_weather_bundle,
    build_simultaneous_records_bundle,
    build_storm_surge_bundle,
    build_synthesis_bundle,
)

from tests.two_bot.conftest import _fire_event


def test_build_fire_bundle_uses_fire_signal_fields():
    fire = _fire_event(event_id="fire_1", region="Southwestern US", country="US")
    bundle = build_fire_bundle(fire)

    assert bundle.signal_kind == "fire"
    assert bundle.where == "Southwestern US"
    assert bundle.when == date.today().isoformat()
    assert bundle.event_id == "fire_1"
    assert bundle.headline_metric == {"label": "FRP", "value": 361.0, "unit": "MW"}
    assert bundle.historical_context == {}
    assert bundle.raw_signal_dump["event_id"] == "fire_1"


def test_build_fire_bundle_rounds_frp_to_one_decimal():
    """Regression for fact-check kills on FRP precision (P2 in IMPROVEMENT_PLAN,
    Codex review on PR #79).

    NASA FIRMS returns FRP with two-decimal precision (e.g. 480.34 MW). The
    fact-check prompt requires exact numerical match with no tolerance, so the
    writer rounding to "480 MW" or "480.3 MW" produces a BUNDLE_FACT kill
    against the raw 480.34 in the bundle. Fix: round at the bundle builder
    so the bundle itself is the 1-decimal source of truth — the writer
    naturally echoes the clean value, the fact-checker confirms exact match.

    Observed in production 2026-05-11 and 2026-05-12: 480.34 → 480 kill,
    547.92 → 548 kill, 301.55 → 301 kill (all BUNDLE_FACT).
    """
    cases = [
        (480.34, 480.3),
        (547.92, 547.9),
        (361.0, 361.0),    # already-clean values pass through unchanged
        (250.05, 250.1),   # Python banker's rounding lands on .1, not .0
        (1000.999, 1001.0),
    ]
    for raw, expected in cases:
        fire = _fire_event(frp=raw, event_id=f"fire_{raw}")
        bundle = build_fire_bundle(fire)

        assert bundle.headline_metric == {"label": "FRP", "value": expected, "unit": "MW"}, (
            f"headline_metric FRP for raw={raw} should be {expected}, got "
            f"{bundle.headline_metric}"
        )
        assert bundle.raw_signal_dump["frp"] == expected, (
            f"raw_signal_dump.frp for raw={raw} should be {expected}, got "
            f"{bundle.raw_signal_dump['frp']}"
        )


def test_build_fire_bundle_falls_back_to_country_when_region_missing():
    fire = _fire_event(region="", country="ML")
    bundle = build_fire_bundle(fire)

    assert bundle.where == "ML"
    assert {"label": "nearest_region", "value": ""} in bundle.current_facts


# ============================================================================
# FRP intensity tier: closes the "what does 364 MW mean?" reader-anchor gap.
#
# Bundle classifies the FRP value into a tier (low/moderate/high/very_high) so
# the writer can give readers a scale word. Raw MW is opaque to non-specialists.
# Thresholds (simple round numbers, defensible across published wildfire
# research conventions):
#   <30 MW     → "low"        (floor 0)
#   30-100 MW  → "moderate"   (floor 30)
#   100-500 MW → "high"       (floor 100)
#   ≥500 MW    → "very_high"  (floor 500)
# Boundaries are inclusive at the lower bound (30.0 → moderate, 100.0 → high).
# ============================================================================


def test_build_fire_bundle_tier_low():
    fire = _fire_event(frp=20.5, event_id="fire_low")
    bundle = build_fire_bundle(fire)
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["frp_tier"] == "low"
    assert labels["frp_tier_floor_mw"] == 0


def test_build_fire_bundle_tier_moderate():
    fire = _fire_event(frp=50.0, event_id="fire_moderate")
    bundle = build_fire_bundle(fire)
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["frp_tier"] == "moderate"
    assert labels["frp_tier_floor_mw"] == 30


def test_build_fire_bundle_tier_high():
    """309.6 MW is the live Mali Sahel draft FRP. Should land in high-intensity tier."""
    fire = _fire_event(frp=309.6, event_id="fire_high")
    bundle = build_fire_bundle(fire)
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["frp_tier"] == "high"
    assert labels["frp_tier_floor_mw"] == 100


def test_build_fire_bundle_tier_very_high():
    fire = _fire_event(frp=600.0, event_id="fire_very_high")
    bundle = build_fire_bundle(fire)
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["frp_tier"] == "very_high"
    assert labels["frp_tier_floor_mw"] == 500


def test_build_fire_bundle_tier_boundary_30():
    """30.0 MW is the inclusive lower bound of the moderate tier."""
    fire = _fire_event(frp=30.0, event_id="fire_boundary_30")
    bundle = build_fire_bundle(fire)
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["frp_tier"] == "moderate"
    assert labels["frp_tier_floor_mw"] == 30


def test_build_fire_bundle_tier_boundary_100():
    """100.0 MW is the inclusive lower bound of the high tier."""
    fire = _fire_event(frp=100.0, event_id="fire_boundary_100")
    bundle = build_fire_bundle(fire)
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["frp_tier"] == "high"
    assert labels["frp_tier_floor_mw"] == 100


def test_build_monthly_high_bundle_populates_historical_context():
    ev = MonthlyRecord(
        city="Conakry",
        country="Guinea",
        kind="high",
        month=5,
        new_temp_c=35.4,
        old_record_c=34.3,
        old_record_year=2022,
        years_of_data=30,
        event_id="meteo_monthly_Conakry_2026-05-01",
    )

    bundle = build_monthly_high_bundle(ev)

    assert bundle.signal_kind == "monthly_high"
    assert bundle.where == "Conakry, Guinea"
    assert bundle.event_id == "meteo_monthly_Conakry_2026-05-01"
    assert bundle.headline_metric["label"] == "forecast_high_c"
    assert bundle.headline_metric["value"] == 35.4
    assert bundle.headline_metric["unit"] == "C"
    assert bundle.historical_context["prior_record_c"] == 34.3
    assert bundle.historical_context["prior_record_year"] == 2022
    assert bundle.historical_context["archive_years"] == 30
    assert bundle.historical_context["month"] == "May"
    assert bundle.historical_context["margin_c"] == 1.1


def test_build_country_record_bundle_uses_kind_in_signal_kind():
    cr = CountryRecord(
        country="France",
        kind="high",
        new_temp_c=42.1,
        peak_city="Toulouse",
        old_record_c=41.5,
        old_record_year=2003,
        old_record_city="Lyon",
        years_of_data=80,
        cities_sampled=15,
        event_id="meteo_country_France_high_2026-05-01",
    )

    bundle = build_country_record_bundle(cr)

    assert bundle.signal_kind == "country_high"
    assert bundle.where == "France"
    assert bundle.headline_metric["label"] == "country_archive_peak_c"
    assert bundle.historical_context["prior_peak_c"] == 41.5
    assert bundle.historical_context["prior_peak_year"] == 2003
    assert bundle.historical_context["prior_peak_city"] == "Lyon"
    assert bundle.historical_context["cities_sampled"] == 15
    assert {"label": "peak_city_today", "value": "Toulouse"} in bundle.current_facts


def test_build_severe_weather_bundle_has_empty_historical_context():
    alert = SevereWeatherAlert(
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

    bundle = build_severe_weather_bundle(alert)

    assert bundle.signal_kind == "severe_weather"
    assert bundle.where == "Point Lay, AK"
    assert bundle.headline_metric == {
        "label": "event_type",
        "value": "Blizzard Warning",
    }
    assert bundle.historical_context == {}
    assert {"label": "max_wind_gust", "value": "40 mph"} in bundle.current_facts


def test_build_cyclone_rapid_intensification_bundle_includes_climate_context():
    event = RapidIntensificationEvent(
        source="nhc",
        storm_id="AL012026",
        storm_name="Beryl",
        basin="Atlantic",
        advisory_number="12",
        issued_at="2026-07-02T00:00:00Z",
        current_wind_kt=115,
        previous_wind_kt=75,
        delta_kt_24h=40,
        current_category=4,
        previous_category=1,
        pressure_mb=950,
        lat=18.0,
        lon=-75.0,
        public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        event_id="nhc_ri_al012026_12_115",
    )

    bundle = build_cyclone_rapid_intensification_bundle(event)
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}

    assert bundle.signal_kind == "cyclone_rapid_intensification"
    assert bundle.where == "Beryl, Atlantic"
    assert bundle.headline_metric == {"label": "delta_kt_24h", "value": 40, "unit": "kt"}
    assert labels["storm_name"] == "Beryl"
    assert labels["public_advisory_url"] == "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"
    assert labels["region_climate_system"] == "the Caribbean warm pool"
    assert bundle.historical_context["rapid_intensification_threshold_kt"] == 30


def test_build_cyclone_tier_crossing_bundle_carries_required_fields():
    event = TierCrossingEvent(
        source="nhc",
        storm_id="AL012026",
        storm_name="Beryl",
        basin="Atlantic",
        advisory_number="12",
        issued_at="2026-07-02T00:00:00Z",
        from_category=2,
        to_category=4,
        wind_kt=115,
        pressure_mb=950,
        lat=18.0,
        lon=-75.0,
        public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        event_id="nhc_tier_al012026_12_cat4",
    )

    bundle = build_cyclone_tier_crossing_bundle(event)
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}

    assert bundle.signal_kind == "cyclone_tier_crossing"
    assert bundle.headline_metric == {"label": "category", "value": 4}
    assert labels["from_category"] == 2
    assert labels["to_category"] == 4
    assert labels["wind_speed_kt"] == 115


def test_build_cyclone_landfall_bundle_uses_landfall_location_as_where():
    event = LandfallEvent(
        source="nhc",
        storm_id="AL012026",
        storm_name="Beryl",
        basin="Atlantic",
        advisory_number="12",
        issued_at="2026-07-02T00:00:00Z",
        category=3,
        wind_kt=100,
        location="Cedar Key, Florida",
        pressure_mb=960,
        lat=29.1,
        lon=-83.0,
        public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        event_id="nhc_landfall_al012026_12_cedar_key",
    )

    bundle = build_cyclone_landfall_bundle(event)

    assert bundle.signal_kind == "cyclone_landfall"
    assert bundle.where == "Cedar Key, Florida"
    assert {"label": "landfall_location", "value": "Cedar Key, Florida"} in bundle.current_facts
    assert bundle.historical_context["scope"] == "major_hurricane_landfall"


def test_build_cyclone_basin_record_bundle_preserves_record_context():
    event = BasinRecordEvent(
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

    bundle = build_cyclone_basin_record_bundle(event)

    assert bundle.signal_kind == "cyclone_basin_record"
    assert {"label": "record_label", "value": "earliest Atlantic Category 4 on record"} in bundle.current_facts
    assert bundle.historical_context["record_scope"] == "Atlantic best-track archive"


def test_build_record_bundle_includes_country_in_where():
    """Regression: a 2026-05-03 draft shipped 'Riga' without 'Latvia'.
    The geographic-orientation rule lives in the writer prompt, but
    'where' must already include the country so the writer doesn't
    have to re-derive it from current_facts. (Bundle-level discipline,
    not just prompt-level discipline.)"""
    ev = RecordEvent(
        city="Riga",
        country="Latvia",
        new_temp_c=24.4,  # 75.9F
        old_record_c=22.6,  # 72.7F
        old_record_year=1996,
        event_id="record_Riga_2026-05-03",
    )

    bundle = build_record_bundle(ev)

    assert bundle.signal_kind == "calendar_record"
    assert bundle.where == "Riga, Latvia"
    assert bundle.event_id == "record_Riga_2026-05-03"
    assert bundle.headline_metric["label"] == "forecast_high_c"
    assert bundle.headline_metric["value"] == 24.4
    assert bundle.headline_metric["unit"] == "C"
    assert bundle.historical_context["prior_record_c"] == 22.6
    assert bundle.historical_context["prior_record_year"] == 1996
    assert bundle.historical_context["scope"] == "calendar_date_only"
    # Margin matters: a +1.8C this-date-only "record" is not extraordinary.
    # The writer's discipline must see the small margin and decide whether
    # to ship.
    assert bundle.historical_context["margin_c"] == 1.8


def test_build_record_bundle_falls_back_to_city_when_country_missing():
    ev = RecordEvent(
        city="Reykjavik",
        country="",
        new_temp_c=15.0,
        old_record_c=14.0,
        old_record_year=2020,
        event_id="record_Reykjavik_2026-05-03",
    )

    bundle = build_record_bundle(ev)

    assert bundle.where == "Reykjavik"


def test_build_record_bundle_marks_calendar_low_records():
    # Open-Meteo path (default source): forecast_low_c, no state passed.
    # (The pre-existing code had a bug: low used "observed_low_c" while
    # high used "forecast_high_c". Both now go through _headline_temp_label
    # which emits "forecast_*_c" for Open-Meteo and "observed_*_c" for GHCN.)
    ev = RecordEvent(
        city="Nome",
        country="United States",
        new_temp_c=-33.0,
        old_record_c=-31.0,
        old_record_year=1989,
        event_id="record_low_Nome_2026-01-10",
        kind="low",
    )

    bundle = build_record_bundle(ev)

    assert bundle.signal_kind == "calendar_record_low"
    assert bundle.headline_metric["label"] == "forecast_low_c"
    assert bundle.headline_metric["value"] == -33.0
    assert bundle.headline_metric["unit"] == "C"
    assert {"label": "kind", "value": "low"} in bundle.current_facts
    assert bundle.historical_context["kind"] == "low"


# ----------------------- batch 2: full port coverage -----------------------


def test_build_all_time_record_bundle_uses_archive_scope():
    ev = AllTimeRecord(
        city="Phoenix", country="US", kind="high",
        new_temp_c=49.4, old_record_c=48.9, old_record_year=1995,
        years_of_data=80,
        event_id="all_time_high_Phoenix_2026-05-04",
    )
    bundle = build_all_time_record_bundle(ev)
    assert bundle.signal_kind == "open_meteo_archive_high"
    assert bundle.where == "Phoenix, US"
    assert bundle.historical_context["scope"] == "archive_history"
    assert bundle.historical_context["archive_years"] == 80
    assert bundle.historical_context["margin_c"] == 0.5
    assert bundle.historical_context["archive_window_only"] is True
    assert "hottest ever" in bundle.historical_context["forbidden_claims"]


def test_build_monthly_low_bundle_uses_low_semantics():
    ev = MonthlyRecord(
        city="Ulaanbaatar", country="Mongolia", kind="low",
        month=5,
        new_temp_c=-8.0, old_record_c=-6.5, old_record_year=1998,
        years_of_data=30,
        event_id="monthly_low_Ulaanbaatar_2026-05-04",
    )
    bundle = build_monthly_high_bundle(ev)
    assert bundle.signal_kind == "monthly_low"
    assert bundle.headline_metric["label"] == "forecast_low_c"
    assert bundle.headline_metric["value"] == -8.0
    assert bundle.headline_metric["unit"] == "C"
    assert bundle.historical_context["margin_c"] == -1.5


def test_build_anomaly_bundle_classifies_kind_by_sign():
    hot = AnomalyEvent(
        city="Quito", country="Ecuador",
        today_temp_c=22.0, historical_mean_c=18.0, anomaly_c=4.0,
        years_of_data=30, event_id="anomaly_Quito",
    )
    cold = AnomalyEvent(
        city="Quito", country="Ecuador",
        today_temp_c=10.0, historical_mean_c=18.0, anomaly_c=-8.0,
        years_of_data=30, event_id="anomaly_Quito_cold",
    )
    assert build_anomaly_bundle(hot).signal_kind == "anomaly_hot"
    assert build_anomaly_bundle(cold).signal_kind == "anomaly_cold"


def test_build_fire_bundle_adds_sahel_climate_context():
    fire = _fire_event(lat=13.5, lon=-4.2, region="Mali", country="ML")
    bundle = build_fire_bundle(fire)

    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["region_climate_system"] == "the Sahel"
    assert labels["climate_mechanism_note"] == (
        "a semi-arid transition zone sits between the Sahara and wetter savanna"
    )
    assert labels["season_context"] == "sharp wet-dry seasonal transition"


def test_build_monthly_high_bundle_adds_western_pacific_warm_pool_context():
    ev = MonthlyRecord(
        city="Chuuk",
        country="Micronesia",
        kind="high",
        month=5,
        new_temp_c=34.0,
        old_record_c=33.1,
        old_record_year=2019,
        years_of_data=30,
        event_id="monthly_high_Chuuk_2026-05-14",
        lat=7.4,
        lon=151.8,
    )
    bundle = build_monthly_high_bundle(ev)

    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["region_climate_system"] == "the western Pacific warm pool"
    assert labels["climate_mechanism_note"] == (
        "persistently warm tropical ocean water anchors deep convection"
    )


def test_build_record_bundle_adds_androscoggin_topography_context():
    ev = RecordEvent(
        city="Bethel",
        country="United States",
        new_temp_c=-4.0,
        old_record_c=-2.0,
        old_record_year=1981,
        event_id="cal_low_Bethel_2026-05-14",
        kind="low",
        state="Maine",
        lat=44.4,
        lon=-70.8,
    )
    bundle = build_record_bundle(ev, source="ghcn")

    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["region_climate_system"] == "the northern New England mountain-valley climate"
    assert labels["local_topography_note"] == (
        "the Androscoggin River valley sits near the White Mountains"
    )


def test_build_anomaly_bundle_adds_eastern_mongolian_steppe_context():
    ev = AnomalyEvent(
        city="Choibalsan",
        country="Mongolia",
        today_temp_c=33.0,
        historical_mean_c=18.0,
        anomaly_c=15.0,
        years_of_data=30,
        event_id="anomaly_hot_Choibalsan_2026-05-14",
        lat=46.5,
        lon=114.0,
    )
    bundle = build_anomaly_bundle(ev)

    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["region_climate_system"] == "the eastern Mongolian steppe"
    assert labels["climate_mechanism_note"] == (
        "continental grassland climate brings dry air and large temperature swings"
    )


def test_temperature_bundle_without_coordinates_has_no_climate_context():
    ev = RecordEvent(
        city="Reykjavik",
        country="Iceland",
        new_temp_c=15.0,
        old_record_c=14.0,
        old_record_year=2020,
        event_id="record_Reykjavik_2026-05-03",
    )
    bundle = build_record_bundle(ev)

    labels = {f["label"] for f in bundle.current_facts}
    assert "region_climate_system" not in labels
    assert "climate_mechanism_note" not in labels
    assert "local_topography_note" not in labels


def test_build_record_streak_bundle_includes_consecutive_days():
    ev = RecordStreakEvent(
        city="Sevilla", country="Spain",
        consecutive_days=5,
        start_date="2026-04-30",
        peak_temp_c=42.7,
        event_id="streak_Sevilla_2026-05-04",
    )
    bundle = build_record_streak_bundle(ev)
    assert bundle.signal_kind == "record_streak"
    assert bundle.where == "Sevilla, Spain"
    assert bundle.headline_metric["value"] == 5


def test_build_simultaneous_records_bundle_lists_countries():
    stations = [
        {"city": "Madrid", "country": "Spain", "temp_c": 38.0, "kind": "high",
         "old_record_c": 36.5, "old_record_year": 2020, "margin_c": 1.5, "elevation_m": 650},
        {"city": "Lisbon", "country": "Portugal", "temp_c": 37.0, "kind": "high",
         "old_record_c": 36.0, "old_record_year": 2018, "margin_c": 1.0, "elevation_m": 60},
    ]
    bundle = build_simultaneous_records_bundle(
        stations, event_id="simultaneous_2026-05-04",
    )
    assert bundle.signal_kind == "simultaneous_records"
    assert "Portugal" in bundle.where
    assert "Spain" in bundle.where
    assert bundle.headline_metric["value"] == 2


def test_build_fire_footprint_bundle_includes_complex_name():
    fc = FireComplex(
        complex_id="cx_001", name="Caldor Fire", country="US", region="California",
        hectares=89000, start_date=date(2026, 4, 1), tier=2,
        event_id="ff_cx_001_2",
    )
    bundle = build_fire_footprint_bundle(fc)
    assert bundle.signal_kind == "fire_footprint"
    assert bundle.where == "California, US"
    assert {"label": "complex_name", "value": "Caldor Fire"} in bundle.current_facts
    assert {"label": "tier_hectares", "value": 100000, "unit": "hectares"} in bundle.current_facts


def test_build_co2_milestone_bundle_anchors_to_mauna_loa():
    m = CO2Milestone(
        ppm_crossed=434, actual_ppm=434.02, date="2026-05-04",
        event_id="co2_434_2026-05-04",
    )
    bundle = build_co2_milestone_bundle(m)
    assert bundle.where == "Mauna Loa Observatory"
    assert bundle.historical_context["preindustrial_baseline_ppm"] == 280


def test_build_ch4_milestone_bundle_preserves_ppb_and_baseline():
    m = MethaneMilestone(
        ppb_crossed=1940,
        actual_ppb=1942.3,
        date="2026-04-01",
        event_id="ch4_milestone_1940ppb",
    )
    bundle = build_ch4_milestone_bundle(m)
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}
    assert bundle.signal_kind == "ch4_milestone"
    assert bundle.headline_metric == {"label": "ppb_crossed", "value": 1940, "unit": "ppb"}
    assert labels["actual_ppb"] == 1942.3
    assert labels["source_name"] == "NOAA GML"
    assert bundle.historical_context["preindustrial_baseline_ppb"] == 722


def test_build_coral_bleaching_bundle_carries_verifiable_dhw_fields():
    event = CoralBleachingEvent(
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
    bundle = build_coral_bleaching_bundle(event)
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}
    assert bundle.signal_kind == "coral_bleaching"
    assert bundle.where == "Northern GBR"
    assert bundle.headline_metric == {"label": "DHW", "value": 8.2, "unit": "°C-weeks"}
    assert labels["region_id"] == "gbr_northern"
    assert labels["region_full_name"] == "Northern GBR"
    assert labels["dhw_value"] == 8.2
    assert labels["dhw_tier"] == 8
    assert labels["bleaching_level"] == "mass bleaching expected"
    assert labels["region_climate_system"] == "the Great Barrier Reef shelf lagoon"


def test_build_global_disaster_bundle_preserves_severity_value():
    d = GlobalDisasterEvent(
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
    bundle = build_global_disaster_bundle(d)
    assert bundle.signal_kind == "global_disaster"
    assert bundle.where == "Australia"
    assert {"label": "severity_value", "value": 220.0} in bundle.current_facts


def test_build_sea_ice_bundle_marks_record_type():
    r = SeaIceRecord(
        hemisphere="Antarctic",
        extent_million_km2=2.41,
        date="2026-02-15",
        record_type="lowest",
        previous_extent=2.59,
        previous_year=2023,
        event_id="sea_ice_antarctic_2026-02-15",
    )
    bundle = build_sea_ice_bundle(r)
    assert bundle.where == "Antarctic hemisphere"
    assert bundle.historical_context["scope"] == "satellite_archive_lowest"


def test_build_ice_mass_bundle_picks_metric_from_kind():
    m = IceMassRecord(
        region="greenland",
        kind="monthly_loss_record",
        month="2026-04",
        monthly_delta_gt=-450.0,
        previous_worst_gt=-410.0,
        previous_worst_month="2019-07",
        threshold_gt=None,
        current_mass_gt=None,
        event_id="ice_mass_grn_2026-04",
    )
    bundle = build_ice_mass_bundle(m, years_of_record=24, archive_start_year=2002)
    assert bundle.signal_kind == "ice_mass_record"
    assert bundle.headline_metric["label"] == "monthly_delta_gt"
    assert bundle.headline_metric["value"] == -450.0
    assert bundle.historical_context["years_of_record"] == 24
    assert bundle.historical_context["archive_start_year"] == 2002


def test_build_marine_heatwave_bundle_uses_global_where():
    mhw = MarineHeatwaveStreakEvent(
        kind="milestone", days=400, peak_anomaly_c=0.45,
        today_c=21.2, archive_max_c=20.9, archive_max_year=2023,
        years_of_data=44,
        date="2026-05-04",
        event_id="mhw_400",
    )
    bundle = build_marine_heatwave_bundle(mhw)
    assert "Global ocean" in bundle.where
    assert bundle.headline_metric["value"] == 400


def test_build_river_flood_bundle_uses_above_by_ft():
    f = FloodEvent(
        river="Mississippi", location="Memphis, TN",
        gauge_height_ft=42.0, flood_stage_ft=34.0, above_by_ft=8.0,
        date="2026-05-04",
        event_id="flood_memphis",
    )
    bundle = build_river_flood_bundle(f)
    assert bundle.where == "Memphis, TN"
    assert bundle.headline_metric["value"] == 8.0


def test_build_global_flood_bundle_includes_copernicus_fields():
    flood = CopernicusFloodActivation(
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

    bundle = build_global_flood_bundle(flood)

    assert bundle.signal_kind == "global_flood"
    assert bundle.where == "Colombia"
    assert bundle.when == "2026-05-14"
    assert bundle.headline_metric == {
        "label": "populations_affected",
        "value": 125000,
        "unit": "people",
    }
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}
    assert labels["activation_id"] == "EMSR999"
    assert labels["copernicus_url"].endswith("/EMSR999/")


def test_build_storm_surge_bundle_uses_anomaly_m():
    s = StormSurgeEvent(
        station_name="Battery", state="NY",
        anomaly_m=0.85, observed_m=2.3, predicted_m=1.45,
        date="2026-05-04",
        event_id="surge_battery",
    )
    bundle = build_storm_surge_bundle(s)
    assert bundle.where == "Battery, NY"
    assert bundle.headline_metric["value"] == 0.85


def test_build_extreme_wave_bundle_includes_ocean():
    w = ExtremeWaveEvent(
        location="Cape Horn",
        ocean="South Atlantic",
        wave_height_m=12.4,
        date="2026-05-04",
        event_id="wave_horn",
    )
    bundle = build_extreme_wave_bundle(w)
    assert "South Atlantic" in bundle.where
    assert bundle.headline_metric["value"] == 12.4


def test_build_drought_bundle_aggregates_states():
    updates = [
        {"state": "California", "d3_pct": 25.0, "d4_pct": 8.0, "total_drought_pct": 60.0},
        {"state": "Nevada", "d3_pct": 15.0, "d4_pct": 4.0, "total_drought_pct": 50.0},
    ]
    bundle = build_drought_bundle(updates, event_id="drought_2026-05-04")
    assert bundle.signal_kind == "drought"
    assert bundle.headline_metric == {
        "label": "worst_extreme_exceptional_pct",
        "value": 33.0,
        "unit": "%",
    }
    assert {"label": "worst_state", "value": "California"} in bundle.current_facts


def test_build_enso_bundle_passes_through_oni():
    transition = {
        "event_id": "enso_2026-05",
        "season": "MAM",
        "from_status": "Neutral",
        "to_status": "El Nino",
        "oni_value": 0.6,
        "previous_duration_months": 8,
    }
    bundle = build_enso_bundle(transition)
    assert bundle.signal_kind == "enso"
    assert bundle.headline_metric["value"] == 0.6
    assert {"label": "status_from", "value": "Neutral"} in bundle.current_facts
    assert {"label": "status_to", "value": "El Nino"} in bundle.current_facts
    assert {"label": "previous_duration_months", "value": 8} in bundle.current_facts


def test_build_oscillation_transition_bundle_carries_long_arc_fields():
    event = OscillationTransition(
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

    bundle = build_oscillation_bundle(event)

    assert bundle.signal_kind == "oscillation_transition"
    assert bundle.where == "North Atlantic Oscillation"
    assert bundle.when == "2026-02-01"
    assert {"label": "to_phase", "value": "Negative"} in bundle.current_facts
    assert bundle.historical_context["anchor_year"] == 2026


def test_build_oscillation_extreme_bundle_carries_comparison_year():
    event = OscillationExtremeEvent(
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

    bundle = build_oscillation_bundle(event)

    assert bundle.signal_kind == "oscillation_extreme"
    assert bundle.headline_metric["value"] == 2.6
    assert {"label": "comparison_year", "value": 1973} in bundle.current_facts
    assert bundle.historical_context["comparison_year"] == 1973


def test_build_oscillation_alignment_bundle_uses_joint_signal_kind():
    event = OscillationAlignmentEvent(
        year=2026,
        month=1,
        nao_value=-2.3,
        ao_value=-2.1,
        nao_sigma_excursion=2.5,
        ao_sigma_excursion=2.2,
        event_id="oscillation_alignment_nao_ao_2026_01",
    )

    bundle = build_oscillation_bundle(event)

    assert bundle.signal_kind == "oscillation_alignment"
    assert bundle.headline_metric["value"] == 2.5
    assert {"label": "ao_value", "value": -2.1} in bundle.current_facts


def test_build_ozone_hole_bundle_preserves_recovery_comparisons():
    event = OzoneHoleSeasonalEvent(
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

    bundle = build_ozone_hole_bundle(event)

    assert bundle.signal_kind == "ozone_hole_peak"
    assert bundle.headline_metric["unit"] == "million km2"
    assert bundle.historical_context["record_year"] == 2000
    assert {"label": "larger_than_previous_year", "value": True} in bundle.current_facts


def test_build_synthesis_bundle_carries_components():
    synthesis = {
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
    bundle = build_synthesis_bundle(synthesis)
    assert bundle.signal_kind == "synthesis_fire_drought_heat"
    assert bundle.where == "Texas"
    assert bundle.headline_metric["value"] == 92


def test_build_hot10_bundle_centers_on_leader():
    cities = [
        {"city": "Phoenix", "country": "US", "temp_high_c": 47.2,
         "normal_high_c": 38.0, "anomaly_c": 9.2},
        {"city": "Yuma", "country": "US", "temp_high_c": 46.0,
         "normal_high_c": 36.5, "anomaly_c": 9.5},
    ]
    bundle = build_hot10_bundle(
        cities, changes=["Phoenix UP 2 spots"], event_id="hot10_2026-05-04",
    )
    assert bundle.signal_kind == "hot10"
    assert bundle.where == "Phoenix, US"
    assert bundle.headline_metric["value"] == 9.2


class TestStateAndObservationKindEnrichment:
    """Regression: writer hallucinations on 2026-05-08 added "Washington"
    (state) and time-of-day prose ("night" / "afternoon") that weren't
    in the bundle. Fact-check correctly rejected them. Surfacing state
    grounds the writer + lets the fact-check pass entity claims.

    Updated (Codex findings #2 + #3): observation_kind now uses
    source-neutral daily-extrema labels (``daily_minimum`` /
    ``daily_maximum``) and is only emitted when ``state`` is present.
    """

    def test_monthly_low_bundle_includes_state_and_daily_minimum(self):
        from src.data.open_meteo import MonthlyRecord
        from src.two_bot.intern import build_monthly_high_bundle

        ev = MonthlyRecord(
            city="Sissonville",
            country="United States",
            kind="low",
            month=5,
            new_temp_c=-2.2,
            old_record_c=1.0,
            old_record_year=1995,
            years_of_data=30,
            event_id="monthly_low_USC00468191_05_2026-05-04",
            state="West Virginia",
        )
        bundle = build_monthly_high_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("state") == "West Virginia"
        assert labels.get("observation_kind") == "daily_minimum"
        # where now includes the state
        assert bundle.where == "Sissonville, West Virginia, United States"

    def test_monthly_high_bundle_includes_state_and_daily_maximum(self):
        from src.data.open_meteo import MonthlyRecord
        from src.two_bot.intern import build_monthly_high_bundle

        ev = MonthlyRecord(
            city="Phoenix",
            country="United States",
            kind="high",
            month=5,
            new_temp_c=46.0,
            old_record_c=44.0,
            old_record_year=2018,
            years_of_data=30,
            event_id="monthly_high_X_05_2026-05-04",
            state="Arizona",
        )
        bundle = build_monthly_high_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("state") == "Arizona"
        assert labels.get("observation_kind") == "daily_maximum"

    def test_anomaly_cold_bundle_uses_daily_minimum(self):
        from src.data.open_meteo import AnomalyEvent
        from src.two_bot.intern import build_anomaly_bundle

        ev = AnomalyEvent(
            city="Apalachicola",
            country="United States",
            today_temp_c=9.4,
            historical_mean_c=18.9,
            anomaly_c=-9.5,
            years_of_data=30,
            event_id="anomaly_cold_X_2026-05-04",
            state="Florida",
        )
        bundle = build_anomaly_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("state") == "Florida"
        assert labels.get("observation_kind") == "daily_minimum"

    def test_calendar_record_bundle_with_state_and_kind(self):
        from src.data.open_meteo import RecordEvent
        from src.two_bot.intern import build_record_bundle

        ev = RecordEvent(
            city="Dayton",
            country="United States",
            new_temp_c=-2.0,
            old_record_c=2.0,
            old_record_year=2010,
            event_id="cal_low_X_2026-05-08",
            kind="low",
            state="Washington",
        )
        bundle = build_record_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("state") == "Washington"
        assert labels.get("observation_kind") == "daily_minimum"
        assert bundle.where == "Dayton, Washington, United States"

    def test_no_state_no_state_or_observation_kind_fact(self):
        """Open-Meteo path / non-US stations: state is None → no state fact
        and no observation_kind fact (guard is on state presence)."""
        from src.data.open_meteo import MonthlyRecord
        from src.two_bot.intern import build_monthly_high_bundle

        ev = MonthlyRecord(
            city="Verkhoyansk",
            country="Russia",
            kind="low",
            month=5,
            new_temp_c=-15.0,
            old_record_c=-12.0,
            old_record_year=1990,
            years_of_data=30,
            event_id="monthly_low_X_05",
            state=None,
        )
        bundle = build_monthly_high_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert "state" not in labels
        # observation_kind must NOT appear when state is absent
        assert "observation_kind" not in labels
        assert bundle.where == "Verkhoyansk, Russia"


class TestCodexFindingsObservedLabels:
    """Codex findings #2 + #3 (both medium severity).

    A) GHCN bundle builders must emit ``observed_*_c`` in headline_metric,
       not ``forecast_*_c``.  Open-Meteo builders must still emit
       ``forecast_*_c``.

    B) ``observation_kind`` must use source-neutral daily extrema labels
       (``daily_minimum`` / ``daily_maximum``) not time-of-day prose.
       It must only be emitted when ``state`` is present (GHCN path).
    """

    def test_ghcn_monthly_bundle_emits_observed_label(self):
        """GHCN monthly-high/low builder → observed_*_c in headline_metric."""
        ev = MonthlyRecord(
            city="Sissonville",
            country="United States",
            kind="low",
            month=5,
            new_temp_c=-2.2,
            old_record_c=1.0,
            old_record_year=1995,
            years_of_data=30,
            event_id="monthly_low_GHCN_05",
            state="West Virginia",
        )
        bundle = build_monthly_high_bundle(ev, source="ghcn")
        assert bundle.headline_metric["label"] == "observed_low_c"

    def test_open_meteo_monthly_bundle_still_emits_forecast_label(self):
        """Open-Meteo monthly builder → forecast_*_c in headline_metric."""
        ev = MonthlyRecord(
            city="Conakry",
            country="Guinea",
            kind="high",
            month=5,
            new_temp_c=35.4,
            old_record_c=34.3,
            old_record_year=2022,
            years_of_data=30,
            event_id="meteo_monthly_Conakry_2026-05-01",
        )
        bundle = build_monthly_high_bundle(ev)
        assert bundle.headline_metric["label"] == "forecast_high_c"

    def test_ghcn_bundle_observation_kind_is_daily_minimum_when_state_present(self):
        """GHCN low bundle with state → observation_kind=daily_minimum."""
        ev = MonthlyRecord(
            city="Sissonville",
            country="United States",
            kind="low",
            month=5,
            new_temp_c=-2.2,
            old_record_c=1.0,
            old_record_year=1995,
            years_of_data=30,
            event_id="monthly_low_GHCN_05_obs",
            state="West Virginia",
        )
        bundle = build_monthly_high_bundle(ev, source="ghcn")
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("observation_kind") == "daily_minimum"

    def test_no_observation_kind_when_state_absent(self):
        """When state is None, observation_kind must NOT appear in bundle."""
        ev = MonthlyRecord(
            city="Conakry",
            country="Guinea",
            kind="low",
            month=5,
            new_temp_c=22.1,
            old_record_c=23.0,
            old_record_year=2010,
            years_of_data=30,
            event_id="monthly_low_Conakry_no_state",
        )
        bundle = build_monthly_high_bundle(ev)
        labels = {f["label"] for f in bundle.current_facts}
        assert "observation_kind" not in labels


class TestExpandUsState:
    """The state-code → full-name mapping for US stations."""

    def test_expands_known_us_states(self):
        from src.data.ghcn import expand_us_state
        assert expand_us_state("WV", "US") == "West Virginia"
        assert expand_us_state("WA", "US") == "Washington"
        assert expand_us_state("FL", "US") == "Florida"
        assert expand_us_state("MN", "US") == "Minnesota"

    def test_handles_lowercase_input(self):
        from src.data.ghcn import expand_us_state
        assert expand_us_state("wv", "US") == "West Virginia"
        assert expand_us_state(" CA ", "US") == "California"

    def test_returns_none_for_non_us(self):
        from src.data.ghcn import expand_us_state
        # Canadian provinces have 2-letter codes but we don't expand them
        # because the mapping is US-specific.
        assert expand_us_state("ON", "CA") is None  # Ontario
        assert expand_us_state("BC", "CA") is None  # British Columbia

    def test_returns_none_for_unknown_codes(self):
        from src.data.ghcn import expand_us_state
        assert expand_us_state("ZZ", "US") is None
        assert expand_us_state("", "US") is None
        assert expand_us_state(None, "US") is None
        assert expand_us_state("WA", None) is None

    def test_handles_us_territories(self):
        from src.data.ghcn import expand_us_state
        # Per GHCN, US territories use the US country prefix in some cases
        assert expand_us_state("PR", "US") == "Puerto Rico"
        assert expand_us_state("DC", "US") == "District of Columbia"


class TestFahrenheitConversion:
    """Bundle enrichment for US-audience-first formatting (PR landed
    2026-05-08). All GHCN-touching builders surface integer-rounded
    Fahrenheit alongside Celsius and an audience_unit fact telling
    the writer which to lead with."""

    def test_c_to_f_roundtrip_known_values(self):
        from src.two_bot.intern import _c_to_f
        assert _c_to_f(0) == 32
        assert _c_to_f(37) == 99
        assert _c_to_f(-2.2) == 28
        assert _c_to_f(40) == 104
        assert _c_to_f(-50) == -58

    def test_c_to_f_passes_none(self):
        from src.two_bot.intern import _c_to_f
        assert _c_to_f(None) is None

    def test_is_us_country_recognizes_canonical_forms(self):
        from src.two_bot.intern import _is_us_country
        assert _is_us_country("United States") is True
        assert _is_us_country("USA") is True
        assert _is_us_country("US") is True
        assert _is_us_country("U.S.") is True
        assert _is_us_country("united states") is True

    def test_is_us_country_rejects_territories_with_brackets(self):
        from src.two_bot.intern import _is_us_country
        assert _is_us_country("Puerto Rico [United States]") is False
        assert _is_us_country("Guam") is False

    def test_is_us_country_rejects_non_us(self):
        from src.two_bot.intern import _is_us_country
        assert _is_us_country("Canada") is False
        assert _is_us_country("United Kingdom") is False
        assert _is_us_country("") is False
        assert _is_us_country(None) is False

    def test_monthly_low_us_bundle_has_fahrenheit_first(self):
        from src.data.open_meteo import MonthlyRecord
        from src.two_bot.intern import build_monthly_high_bundle

        ev = MonthlyRecord(
            city="Sissonville", country="United States", kind="low", month=5,
            new_temp_c=-2.2, old_record_c=-1.7, old_record_year=2020,
            years_of_data=16, event_id="monthly_low_X_05",
            state="West Virginia",
        )
        bundle = build_monthly_high_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("today_temp_c") == -2.2
        assert labels.get("today_temp_f") == 28
        assert labels.get("audience_unit") == "fahrenheit_first"
        assert bundle.headline_metric["value_f"] == 28
        assert bundle.historical_context["prior_record_f"] == 29
        assert bundle.historical_context["margin_f"] == -1

    def test_non_us_bundle_has_celsius_first(self):
        from src.data.open_meteo import MonthlyRecord
        from src.two_bot.intern import build_monthly_high_bundle

        ev = MonthlyRecord(
            city="Verkhoyansk", country="Russia", kind="low", month=5,
            new_temp_c=-15.0, old_record_c=-12.0, old_record_year=1990,
            years_of_data=30, event_id="monthly_low_X", state=None,
        )
        bundle = build_monthly_high_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("audience_unit") == "celsius_first"
        assert labels.get("today_temp_c") == -15.0
        assert labels.get("today_temp_f") == 5

    def test_anomaly_delta_uses_scaling_only_no_offset(self):
        """anomaly_c is a DELTA, so F conversion uses 9/5 scaling only,
        no +32 offset. -9.5C anomaly = -17F anomaly, not -49."""
        from src.data.open_meteo import AnomalyEvent
        from src.two_bot.intern import build_anomaly_bundle

        ev = AnomalyEvent(
            city="Apalachicola", country="United States",
            today_temp_c=9.4, historical_mean_c=18.9, anomaly_c=-9.5,
            years_of_data=30, event_id="anomaly_cold_X", state="Florida",
        )
        bundle = build_anomaly_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("anomaly_f") == -17
        assert labels.get("today_f") == 49
        assert labels.get("historical_mean_f") == 66

    def test_calendar_record_us_bundle(self):
        from src.data.open_meteo import RecordEvent
        from src.two_bot.intern import build_record_bundle

        ev = RecordEvent(
            city="Phoenix", country="United States",
            new_temp_c=46.0, old_record_c=44.0, old_record_year=2018,
            event_id="cal_high_X", kind="high", state="Arizona",
        )
        bundle = build_record_bundle(ev)
        labels = {f["label"]: f["value"] for f in bundle.current_facts}
        assert labels.get("today_temp_f") == 115
        assert labels.get("audience_unit") == "fahrenheit_first"
        assert bundle.historical_context["prior_record_f"] == 111
        assert bundle.historical_context["margin_f"] == 4


# ============================================================================
# Belt-and-suspenders: bundle builders normalize GHCN-style suffixed cities.
#
# Root-cause fix lives in src/data/ghcn.py (PR #82 — _COOP_SUFFIX_RE and
# _MILITARY_SUFFIX_RE patterns). These tests lock the boundary contract at
# the bundle layer so any future signal-detection path that bypasses ghcn.py's
# normalization still produces a clean place name in `where` and
# `current_facts.city`. normalize_station_name is idempotent — re-normalizing
# an already-clean "Paddock Lake" returns "Paddock Lake" — so this layer is
# pure defense, no behavior change on the production path.
# ============================================================================


def test_build_monthly_high_bundle_normalizes_suffixed_city():
    ev = MonthlyRecord(
        city="Paddock Lake 4 Ne",
        country="United States",
        kind="low",
        month=5,
        new_temp_c=-1.0,
        old_record_c=0.5,
        old_record_year=2003,
        years_of_data=25,
        event_id="monthly_low_USC00086092_05_2026-05-12",
        state="Wisconsin",
    )

    bundle = build_monthly_high_bundle(ev, source="ghcn")

    assert "4 Ne" not in bundle.where
    assert bundle.where.startswith("Paddock Lake")
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["city"] == "Paddock Lake"
    # raw_signal_dump must also carry the normalized name — otherwise the
    # bundle is internally inconsistent (where = "Paddock Lake" but raw dump
    # = "Paddock Lake 4 Ne"), which defeats the defense-in-depth premise.
    assert bundle.raw_signal_dump["city"] == "Paddock Lake"


def test_build_record_bundle_normalizes_suffixed_city():
    ev = RecordEvent(
        city="Sioux City Ang",
        country="United States",
        new_temp_c=33.0,
        old_record_c=31.0,
        old_record_year=1998,
        event_id="cal_high_USW00014943_2026-05-12",
        kind="high",
        state="Iowa",
    )

    bundle = build_record_bundle(ev, source="ghcn")

    assert "Ang" not in bundle.where
    assert bundle.where.startswith("Sioux City")
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["city"] == "Sioux City"
    assert bundle.raw_signal_dump["city"] == "Sioux City"


def test_build_all_time_record_bundle_normalizes_suffixed_city():
    ev = AllTimeRecord(
        city="Paddock Lake 4 Ne",
        country="United States",
        kind="low",
        new_temp_c=-12.0,
        old_record_c=-11.5,
        old_record_year=1996,
        years_of_data=30,
        event_id="all_time_low_USC00086092_2026-05-12",
        state="Wisconsin",
    )

    bundle = build_all_time_record_bundle(ev, source="ghcn")

    assert "4 Ne" not in bundle.where
    assert bundle.where.startswith("Paddock Lake")
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["city"] == "Paddock Lake"
    assert bundle.raw_signal_dump["city"] == "Paddock Lake"


def test_build_anomaly_bundle_normalizes_suffixed_city():
    ev = AnomalyEvent(
        city="Sioux City Ang",
        country="United States",
        today_temp_c=35.0,
        historical_mean_c=18.0,
        anomaly_c=17.0,
        years_of_data=30,
        event_id="anomaly_hot_USW00014943_2026-05-12",
        state="Iowa",
    )

    bundle = build_anomaly_bundle(ev, source="ghcn")

    assert "Ang" not in bundle.where
    assert bundle.where.startswith("Sioux City")
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["city"] == "Sioux City"
    assert bundle.raw_signal_dump["city"] == "Sioux City"


def test_normalize_station_name_idempotent_in_bundle_builders():
    """A clean ev.city (the production case after ghcn.py:381) must round-trip
    unchanged through the builder. Guards against accidental over-normalization
    (e.g. stripping legitimate trailing tokens like 'San Juan' to 'San')."""
    ev = MonthlyRecord(
        city="San Juan",
        country="Puerto Rico",
        kind="high",
        month=5,
        new_temp_c=35.0,
        old_record_c=33.5,
        old_record_year=1999,
        years_of_data=40,
        event_id="monthly_high_TJSJ_05_2026-05-12",
    )

    bundle = build_monthly_high_bundle(ev)

    assert bundle.where == "San Juan, Puerto Rico"
    labels = {f["label"]: f["value"] for f in bundle.current_facts}
    assert labels["city"] == "San Juan"
