"""Stage 1: deterministic story-bundle assembly for each signal type."""

from dataclasses import asdict
from datetime import date

from src.data.firms import FireEvent
from src.data.nws_alerts import SevereWeatherAlert
from src.data.open_meteo import CountryRecord, MonthlyRecord
from src.two_bot.types import StoryBundle

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def build_fire_bundle(fire: FireEvent) -> StoryBundle:
    """Assemble a pure-facts StoryBundle for a fire signal."""

    return StoryBundle(
        signal_kind="fire",
        where=fire.nearest_city or fire.country,
        when=date.today().isoformat(),
        event_id=fire.event_id,
        headline_metric={"label": "FRP", "value": fire.frp, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": fire.confidence, "unit": "%"},
            {"label": "country", "value": fire.country},
            {"label": "nearest_region", "value": fire.nearest_city},
            {"label": "lat", "value": fire.lat},
            {"label": "lon", "value": fire.lon},
        ],
        historical_context={},
        raw_signal_dump={
            "lat": fire.lat,
            "lon": fire.lon,
            "confidence": fire.confidence,
            "frp": fire.frp,
            "nearest_city": fire.nearest_city,
            "country": fire.country,
            "event_id": fire.event_id,
        },
    )


def build_monthly_high_bundle(ev: MonthlyRecord) -> StoryBundle:
    """Assemble a StoryBundle for a monthly high-temperature record signal."""

    month_name = _MONTH_NAMES[ev.month] if 1 <= ev.month <= 12 else str(ev.month)
    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    return StoryBundle(
        signal_kind="monthly_high",
        where=where,
        when=date.today().isoformat(),
        event_id=ev.event_id,
        headline_metric={
            "label": "forecast_high_c",
            "value": ev.new_temp_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "month", "value": month_name},
            {"label": "kind", "value": ev.kind},
        ],
        historical_context={
            "prior_record_c": ev.old_record_c,
            "prior_record_year": ev.old_record_year,
            "archive_years": ev.years_of_data,
            "month": month_name,
            "margin_c": round(ev.new_temp_c - ev.old_record_c, 2),
        },
        raw_signal_dump=asdict(ev),
    )


def build_country_record_bundle(cr: CountryRecord) -> StoryBundle:
    """Assemble a StoryBundle for a country-level archive-record signal."""

    return StoryBundle(
        signal_kind=f"country_{cr.kind}",
        where=cr.country,
        when=date.today().isoformat(),
        event_id=cr.event_id,
        headline_metric={
            "label": "country_archive_peak_c",
            "value": cr.new_temp_c,
            "unit": "C",
        },
        current_facts=[
            {"label": "country", "value": cr.country},
            {"label": "peak_city_today", "value": cr.peak_city},
            {"label": "prior_peak_city", "value": cr.old_record_city},
            {"label": "kind", "value": cr.kind},
        ],
        historical_context={
            "prior_peak_c": cr.old_record_c,
            "prior_peak_year": cr.old_record_year,
            "prior_peak_city": cr.old_record_city,
            "archive_years": cr.years_of_data,
            "cities_sampled": cr.cities_sampled,
            "kind": cr.kind,
            "margin_c": round(cr.new_temp_c - cr.old_record_c, 2),
        },
        raw_signal_dump=asdict(cr),
    )


def build_severe_weather_bundle(alert: SevereWeatherAlert) -> StoryBundle:
    """Assemble a StoryBundle for an NWS severe-weather alert.

    ``historical_context`` is intentionally empty: NWS alerts carry no
    archive comparison, so the writer must rely on the empty-context
    discipline already in the prompt.
    """

    return StoryBundle(
        signal_kind="severe_weather",
        where=alert.area,
        when=date.today().isoformat(),
        event_id=alert.event_id,
        headline_metric={"label": "event_type", "value": alert.event_type},
        current_facts=[
            {"label": "event_type", "value": alert.event_type},
            {"label": "area", "value": alert.area},
            {"label": "severity", "value": alert.severity},
            {"label": "max_wind_gust", "value": alert.max_wind_gust},
            {"label": "max_hail_size", "value": alert.max_hail_size},
            {"label": "tornado_detection", "value": alert.tornado_detection},
            {"label": "description", "value": alert.description},
            {"label": "sender_name", "value": alert.sender_name},
        ],
        historical_context={},
        raw_signal_dump=asdict(alert),
    )

