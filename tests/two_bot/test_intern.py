from datetime import date

from src.data.co2 import CO2Milestone
from src.data.fire_footprint import FireComplex
from src.data.gdacs import GlobalDisasterEvent
from src.data.ice_mass import IceMassRecord
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
    build_co2_milestone_bundle,
    build_country_record_bundle,
    build_drought_bundle,
    build_enso_bundle,
    build_extreme_wave_bundle,
    build_fire_bundle,
    build_fire_footprint_bundle,
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


def test_build_fire_bundle_falls_back_to_country_when_region_missing():
    fire = _fire_event(region="", country="ML")
    bundle = build_fire_bundle(fire)

    assert bundle.where == "ML"
    assert {"label": "nearest_region", "value": ""} in bundle.current_facts


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
    assert bundle.headline_metric == {
        "label": "forecast_high_c",
        "value": 35.4,
        "unit": "C",
    }
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
    assert bundle.headline_metric == {
        "label": "forecast_high_c",
        "value": 24.4,
        "unit": "C",
    }
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


# ----------------------- batch 2: full port coverage -----------------------


def test_build_all_time_record_bundle_uses_archive_scope():
    ev = AllTimeRecord(
        city="Phoenix", country="US", kind="high",
        new_temp_c=49.4, old_record_c=48.9, old_record_year=1995,
        years_of_data=80,
        event_id="all_time_high_Phoenix_2026-05-04",
    )
    bundle = build_all_time_record_bundle(ev)
    assert bundle.signal_kind == "all_time_high"
    assert bundle.where == "Phoenix, US"
    assert bundle.historical_context["scope"] == "archive_history"
    assert bundle.historical_context["archive_years"] == 80
    assert bundle.historical_context["margin_c"] == 0.5


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


def test_build_co2_milestone_bundle_anchors_to_mauna_loa():
    m = CO2Milestone(
        ppm_crossed=434, actual_ppm=434.02, date="2026-05-04",
        event_id="co2_434_2026-05-04",
    )
    bundle = build_co2_milestone_bundle(m)
    assert bundle.where == "Mauna Loa Observatory"
    assert bundle.historical_context["preindustrial_baseline_ppm"] == 280


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
    bundle = build_ice_mass_bundle(m)
    assert bundle.signal_kind == "ice_mass_record"
    assert bundle.headline_metric["label"] == "monthly_delta_gt"
    assert bundle.headline_metric["value"] == -450.0


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
    assert bundle.headline_metric["value"] == 2


def test_build_enso_bundle_passes_through_oni():
    transition = {
        "event_id": "enso_2026-05",
        "season": "MAM",
        "status_from": "Neutral",
        "status_to": "El Nino",
        "oni_value": 0.6,
    }
    bundle = build_enso_bundle(transition)
    assert bundle.signal_kind == "enso"
    assert bundle.headline_metric["value"] == 0.6


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

