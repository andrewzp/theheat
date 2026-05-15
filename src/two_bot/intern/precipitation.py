"""Precipitation and snow two-bot intern builders."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.data.gpm_imerg import PrecipExtremeEvent
from src.data.nsidc_snow import SnowExtremeEvent
from src.two_bot.types import StoryBundle

from ._shared import _climate_context_facts


def build_precipitation_bundle(event: PrecipExtremeEvent) -> StoryBundle:
    where = event.location if not event.country or event.location == event.country else (
        f"{event.location}, {event.country}"
    )
    facts: list[dict[str, Any]] = [
        {"label": "event_kind", "value": event.kind},
        {"label": "location", "value": event.location},
        {"label": "country", "value": event.country},
        {"label": "date", "value": event.date},
        {"label": "rainfall_mm", "value": round(event.mm_total, 1), "unit": "mm"},
        {"label": "period_days", "value": event.period_days},
        {"label": "deviation_from_record_mm", "value": _rounded(event.deviation_from_record_mm)},
        {"label": "previous_record_mm", "value": _rounded(event.previous_record_mm)},
        {"label": "previous_record_year", "value": event.previous_record_year},
        {"label": "city_count", "value": event.city_count},
        {"label": "sample_cities", "value": event.sample_cities},
        {"label": "lat", "value": event.lat},
        {"label": "lon", "value": event.lon},
        *_climate_context_facts(event.lat, event.lon, category="rain"),
    ]
    return StoryBundle(
        signal_kind="precipitation_extreme",
        where=where,
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "rainfall_mm",
            "value": round(event.mm_total, 1),
            "unit": "mm",
        },
        current_facts=facts,
        historical_context={
            "scope": event.kind,
            "period_days": event.period_days,
            "previous_record_mm": event.previous_record_mm,
            "previous_record_year": event.previous_record_year,
            "city_count": event.city_count,
        },
        raw_signal_dump=asdict(event),
    )


def build_snow_extreme_bundle(event: SnowExtremeEvent) -> StoryBundle:
    return _snow_bundle(event, signal_kind="snow_extreme")


def build_seasonal_snow_bundle(event: SnowExtremeEvent) -> StoryBundle:
    return _snow_bundle(event, signal_kind="seasonal_snow_record")


def _snow_bundle(event: SnowExtremeEvent, *, signal_kind: str) -> StoryBundle:
    facts: list[dict[str, Any]] = [
        {"label": "event_kind", "value": event.kind},
        {"label": "station", "value": event.station},
        {"label": "date", "value": event.date},
        {"label": "swe_mm", "value": _rounded(event.swe_mm), "unit": "mm"},
        {"label": "event_swe_mm", "value": round(event.mm_swe, 1), "unit": "mm"},
        {"label": "deviation_from_record_mm", "value": _rounded(event.deviation_from_record_mm)},
        {"label": "previous_record_mm", "value": _rounded(event.previous_record_mm)},
        {"label": "previous_record_year", "value": event.previous_record_year},
        {"label": "consecutive_days", "value": event.consecutive_days},
        {"label": "years_of_archive", "value": event.years_of_archive},
        {"label": "elevation_m", "value": _rounded(event.elevation_m)},
        {"label": "lat", "value": event.lat},
        {"label": "lon", "value": event.lon},
        *_climate_context_facts(event.lat, event.lon, category="snow"),
    ]
    return StoryBundle(
        signal_kind=signal_kind,
        where=event.station,
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "swe_mm",
            "value": round(event.mm_swe, 1),
            "unit": "mm",
        },
        current_facts=facts,
        historical_context={
            "scope": event.kind,
            "previous_record_mm": event.previous_record_mm,
            "previous_record_year": event.previous_record_year,
            "years_of_archive": event.years_of_archive,
        },
        raw_signal_dump=asdict(event),
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
