from datetime import date

from src.data.nws_alerts import SevereWeatherAlert
from src.data.open_meteo import CountryRecord, MonthlyRecord, RecordEvent
from src.two_bot.intern import (
    build_country_record_bundle,
    build_fire_bundle,
    build_monthly_high_bundle,
    build_record_bundle,
    build_severe_weather_bundle,
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

