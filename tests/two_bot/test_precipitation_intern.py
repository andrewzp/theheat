from src.data.gpm_imerg import PrecipExtremeEvent
from src.data.nsidc_snow import SnowExtremeEvent
from src.two_bot.intern import (
    build_precipitation_bundle,
    build_seasonal_snow_bundle,
    build_snow_extreme_bundle,
)


def test_precipitation_bundle_includes_f2_context():
    event = PrecipExtremeEvent(
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

    bundle = build_precipitation_bundle(event)
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}

    assert bundle.signal_kind == "precipitation_extreme"
    assert bundle.headline_metric == {"label": "rainfall_mm", "value": 160.0, "unit": "mm"}
    assert labels["region_climate_system"] == "the Gulf Coast humid subtropical belt"
    assert bundle.raw_signal_dump["previous_record_year"] == 2017


def test_snow_extreme_bundle_includes_f2_snow_context():
    event = SnowExtremeEvent(
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

    bundle = build_snow_extreme_bundle(event)
    labels = {fact["label"]: fact["value"] for fact in bundle.current_facts}

    assert bundle.signal_kind == "snow_extreme"
    assert labels["region_climate_system"] == "the Great Lakes lake-effect belt"
    assert labels["event_swe_mm"] == 76.2


def test_seasonal_snow_bundle_uses_seasonal_signal_kind():
    event = SnowExtremeEvent(
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

    bundle = build_seasonal_snow_bundle(event)

    assert bundle.signal_kind == "seasonal_snow_record"
    assert bundle.historical_context["years_of_archive"] == 12
