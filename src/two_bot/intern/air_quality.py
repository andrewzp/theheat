"""Air-quality two-bot intern builders."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.data.air_quality import DustEvent, PM25HazardEvent
from src.two_bot.types import StoryBundle


def build_pm25_hazard_bundle(event: PM25HazardEvent) -> StoryBundle:
    """Build factual bundle for a hazardous PM2.5 24-hour mean event."""
    current_facts: list[dict[str, Any]] = [
        {"label": "pm25_24h_mean_ug_m3", "value": round(event.pm25_24h_mean, 1)},
        {"label": "who_24h_guideline_ug_m3", "value": 15},
        {"label": "who_multiple", "value": event.who_multiple},
        {"label": "tier", "value": event.tier},
        {"label": "us_aqi_daily_max", "value": event.us_aqi_daily_max},
        {"label": "data_source", "value": "CAMS global model via Open-Meteo"},
        {"label": "model_resolution_km", "value": 45},
        {"label": "lat", "value": event.lat},
        {"label": "lon", "value": event.lon},
        {"label": "evidence_grade", "value": "model_estimated"},
    ]
    return StoryBundle(
        signal_kind="air_quality_hazard",
        where=f"{event.city}, {event.country}",
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "pm25_24h_mean_ug_m3",
            "value": round(event.pm25_24h_mean, 1),
            "unit": "μg/m³",
        },
        current_facts=current_facts,
        historical_context={},
        raw_signal_dump=asdict(event),
    )


def build_dust_event_bundle(event: DustEvent) -> StoryBundle:
    """Build factual bundle for a mineral dust daily-max event."""
    current_facts: list[dict[str, Any]] = [
        {"label": "dust_daily_max_ug_m3", "value": round(event.dust_daily_max, 0)},
        {"label": "tier", "value": event.tier},
        {
            "label": "aerosol_optical_depth",
            "value": round(event.aod_daily_max, 2) if event.aod_daily_max is not None else None,
        },
        {"label": "data_source", "value": "CAMS global model via Open-Meteo"},
        {"label": "model_resolution_km", "value": 45},
        {"label": "lat", "value": event.lat},
        {"label": "lon", "value": event.lon},
        {"label": "evidence_grade", "value": "model_estimated"},
    ]
    return StoryBundle(
        signal_kind="dust_event",
        where=f"{event.city}, {event.country}",
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "dust_daily_max_ug_m3",
            "value": round(event.dust_daily_max, 0),
            "unit": "μg/m³",
        },
        current_facts=current_facts,
        historical_context={},
        raw_signal_dump=asdict(event),
    )
