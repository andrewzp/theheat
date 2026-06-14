"""Disasters two-bot intern builders."""



from __future__ import annotations



from dataclasses import asdict
from typing import Any

from datetime import date

from src.data.copernicus_ems import CopernicusFloodActivation

from src.data.cyclones import BasinRecordEvent

from src.data.cyclones import LandfallEvent

from src.data.cyclones import RapidIntensificationEvent

from src.data.cyclones import TierCrossingEvent

from src.data.gdacs import GlobalDisasterEvent

from src.data.nws_alerts import SevereWeatherAlert

from src.data.river_gauges import FloodEvent

from src.data.usgs_quakes import SignificantEarthquakeEvent

from src.data.water_levels import StormSurgeEvent

from src.two_bot.types import StoryBundle

from ._shared import _climate_context_facts



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

def build_global_disaster_bundle(disaster: GlobalDisasterEvent) -> StoryBundle:
    """A live-running natural disaster surfaced via GDACS."""

    return StoryBundle(
        signal_kind="global_disaster",
        where=disaster.country or "Unknown",
        when=date.today().isoformat(),
        event_id=disaster.event_id,
        headline_metric={
            "label": "severity",
            "value": disaster.severity,
        },
        current_facts=[
            {"label": "disaster_type", "value": disaster.disaster_type},
            {"label": "name", "value": disaster.name},
            {"label": "country", "value": disaster.country},
            {"label": "severity", "value": disaster.severity},
            {"label": "alert_score", "value": disaster.alert_score},
            {"label": "severity_value", "value": disaster.severity_value},
            {"label": "severity_unit", "value": disaster.severity_unit},
            {"label": "population_affected", "value": disaster.population_affected},
            {"label": "description", "value": disaster.description},
        ],
        historical_context={},
        raw_signal_dump=asdict(disaster),
    )

def build_usgs_earthquake_bundle(quake: SignificantEarthquakeEvent) -> StoryBundle:
    """A significant earthquake surfaced via USGS."""

    return StoryBundle(
        signal_kind="usgs_earthquake",
        where=quake.place or "Unknown",
        when=(quake.time or date.today().isoformat())[:10],
        event_id=quake.event_id,
        headline_metric={
            "label": "magnitude",
            "value": quake.magnitude,
            "unit": "M",
        },
        current_facts=[
            {"label": "source", "value": "USGS Earthquake Hazards Program"},
            {"label": "usgs_id", "value": quake.usgs_id},
            {"label": "title", "value": quake.title},
            {"label": "place", "value": quake.place},
            {"label": "magnitude", "value": quake.magnitude, "unit": "M"},
            {"label": "depth_km", "value": quake.depth_km, "unit": "km"},
            {"label": "time", "value": quake.time},
            {"label": "pager_alert", "value": quake.alert},
            {"label": "significance", "value": quake.significance},
            {"label": "felt_reports", "value": quake.felt_reports},
            {"label": "cdi", "value": quake.cdi},
            {"label": "mmi", "value": quake.mmi},
            {"label": "tsunami", "value": quake.tsunami},
            {"label": "lat", "value": quake.latitude},
            {"label": "lon", "value": quake.longitude},
            {"label": "url", "value": quake.url},
        ],
        historical_context={
            "feed": "USGS significant_day GeoJSON",
            "coverage": "official significant earthquakes from the past day",
        },
        raw_signal_dump=asdict(quake),
    )

def _cyclone_common_facts(
    *,
    source: str,
    storm_name: str,
    basin: str,
    category: int,
    wind_kt: int,
    pressure_mb: int | None,
    lat: float | None,
    lon: float | None,
    advisory_number: str,
    public_advisory_url: str,
) -> list[dict]:
    return [
        {"label": "source", "value": source.upper()},
        {"label": "storm_name", "value": storm_name},
        {"label": "basin", "value": basin},
        {"label": "category", "value": category},
        {"label": "wind_speed_kt", "value": wind_kt, "unit": "kt"},
        {"label": "central_pressure_mb", "value": pressure_mb, "unit": "mb"},
        {"label": "lat", "value": lat},
        {"label": "lon", "value": lon},
        {"label": "advisory_number", "value": advisory_number},
        {"label": "public_advisory_url", "value": public_advisory_url},
        *_climate_context_facts(lat, lon, category="cyclone"),
    ]

def _cyclone_where(storm_name: str, basin: str) -> str:
    return f"{storm_name}, {basin}" if basin else storm_name

def build_cyclone_rapid_intensification_bundle(event: RapidIntensificationEvent) -> StoryBundle:
    """A tropical cyclone gained at least 30 kt in roughly 24 hours."""

    return StoryBundle(
        signal_kind="cyclone_rapid_intensification",
        where=_cyclone_where(event.storm_name, event.basin),
        when=event.issued_at or date.today().isoformat(),
        event_id=event.event_id,
        headline_metric={
            "label": "delta_kt_24h",
            "value": event.delta_kt_24h,
            "unit": "kt",
        },
        current_facts=[
            *_cyclone_common_facts(
                source=event.source,
                storm_name=event.storm_name,
                basin=event.basin,
                category=event.current_category,
                wind_kt=event.current_wind_kt,
                pressure_mb=event.pressure_mb,
                lat=event.lat,
                lon=event.lon,
                advisory_number=event.advisory_number,
                public_advisory_url=event.public_advisory_url,
            ),
            {"label": "previous_wind_kt", "value": event.previous_wind_kt, "unit": "kt"},
            {"label": "previous_category", "value": event.previous_category},
            {"label": "delta_kt_24h", "value": event.delta_kt_24h, "unit": "kt"},
        ],
        historical_context={
            "window_hours": 24,
            "rapid_intensification_threshold_kt": 30,
        },
        raw_signal_dump=asdict(event),
    )

def build_cyclone_tier_crossing_bundle(event: TierCrossingEvent) -> StoryBundle:
    """A tropical cyclone crossed into a higher Saffir-Simpson category."""

    return StoryBundle(
        signal_kind="cyclone_tier_crossing",
        where=_cyclone_where(event.storm_name, event.basin),
        when=event.issued_at or date.today().isoformat(),
        event_id=event.event_id,
        headline_metric={
            "label": "category",
            "value": event.to_category,
        },
        current_facts=[
            *_cyclone_common_facts(
                source=event.source,
                storm_name=event.storm_name,
                basin=event.basin,
                category=event.to_category,
                wind_kt=event.wind_kt,
                pressure_mb=event.pressure_mb,
                lat=event.lat,
                lon=event.lon,
                advisory_number=event.advisory_number,
                public_advisory_url=event.public_advisory_url,
            ),
            {"label": "from_category", "value": event.from_category},
            {"label": "to_category", "value": event.to_category},
        ],
        historical_context={"scope": "saffir_simpson_tier_crossing"},
        raw_signal_dump=asdict(event),
    )

def build_cyclone_landfall_bundle(event: LandfallEvent) -> StoryBundle:
    """A Cat 3+ tropical cyclone landfall was confirmed in an advisory."""

    return StoryBundle(
        signal_kind="cyclone_landfall",
        where=event.location,
        when=event.issued_at or date.today().isoformat(),
        event_id=event.event_id,
        headline_metric={
            "label": "category",
            "value": event.category,
        },
        current_facts=[
            *_cyclone_common_facts(
                source=event.source,
                storm_name=event.storm_name,
                basin=event.basin,
                category=event.category,
                wind_kt=event.wind_kt,
                pressure_mb=event.pressure_mb,
                lat=event.lat,
                lon=event.lon,
                advisory_number=event.advisory_number,
                public_advisory_url=event.public_advisory_url,
            ),
            {"label": "landfall_location", "value": event.location},
        ],
        historical_context={"scope": "major_hurricane_landfall"},
        raw_signal_dump=asdict(event),
    )

def build_cyclone_basin_record_bundle(event: BasinRecordEvent) -> StoryBundle:
    """An archive-backed tropical cyclone basin record."""

    return StoryBundle(
        signal_kind="cyclone_basin_record",
        where=_cyclone_where(event.storm_name, event.basin),
        when=event.issued_at or date.today().isoformat(),
        event_id=event.event_id,
        headline_metric={
            "label": "category",
            "value": event.category,
        },
        current_facts=[
            *_cyclone_common_facts(
                source=event.source,
                storm_name=event.storm_name,
                basin=event.basin,
                category=event.category,
                wind_kt=event.wind_kt,
                pressure_mb=event.pressure_mb,
                lat=event.lat,
                lon=event.lon,
                advisory_number=event.advisory_number,
                public_advisory_url=event.public_advisory_url,
            ),
            {"label": "record_label", "value": event.record_label},
            {"label": "record_scope", "value": event.record_scope},
        ],
        historical_context={
            "record_label": event.record_label,
            "record_scope": event.record_scope,
            "scope": "basin_record",
        },
        raw_signal_dump=asdict(event),
    )

def build_river_flood_bundle(flood: FloodEvent) -> StoryBundle:
    """A river flood signal from either a gauge stage or a model fallback."""

    if flood.source_leg == "open_meteo_flood":
        facts: list[dict[str, Any]] = [
            {"label": "river", "value": flood.river},
            {"label": "location", "value": flood.location},
            {"label": "modeled_discharge_m3s", "value": flood.discharge_m3s, "unit": "m3/s"},
            {
                "label": "model_threshold_m3s",
                "value": flood.discharge_threshold_m3s,
                "unit": "m3/s",
            },
            {"label": "discharge_ratio", "value": flood.discharge_ratio},
            {"label": "data_source", "value": "Open-Meteo Flood / GloFAS model"},
            {"label": "evidence_grade", "value": "model_fallback"},
        ]
        return StoryBundle(
            signal_kind="river_flood",
            where=flood.location,
            when=flood.date,
            event_id=flood.event_id,
            headline_metric={
                "label": "modeled_discharge_m3s",
                "value": flood.discharge_m3s,
                "unit": "m3/s",
            },
            current_facts=facts,
            historical_context={
                "model_fallback": True,
                "coverage_limit": "GloFAS samples the largest nearby river cell; this is modeled discharge, not a gauge reading.",
            },
            raw_signal_dump=asdict(flood),
        )

    return StoryBundle(
        signal_kind="river_flood",
        where=flood.location,
        when=flood.date,
        event_id=flood.event_id,
        headline_metric={
            "label": "above_flood_stage_ft",
            "value": flood.above_by_ft,
            "unit": "ft",
        },
        current_facts=[
            {"label": "river", "value": flood.river},
            {"label": "location", "value": flood.location},
            {"label": "gauge_height_ft", "value": flood.gauge_height_ft},
            {"label": "flood_stage_ft", "value": flood.flood_stage_ft},
            {"label": "above_by_ft", "value": flood.above_by_ft},
        ],
        historical_context={},
        raw_signal_dump=asdict(flood),
    )

def build_global_flood_bundle(event: CopernicusFloodActivation) -> StoryBundle:
    """A non-US flood activation from Copernicus EMS Rapid Mapping."""

    headline_metric = (
        {
            "label": "populations_affected",
            "value": event.populations_affected,
            "unit": "people",
        }
        if event.populations_affected > 0
        else {
            "label": "affected_area_km2",
            "value": event.affected_area_km2,
            "unit": "km2",
        }
    )
    return StoryBundle(
        signal_kind="global_flood",
        where=event.country or event.name or "Unknown",
        when=event.activation_date[:10],
        event_id=event.event_id,
        headline_metric=headline_metric,
        current_facts=[
            {"label": "activation_id", "value": event.activation_id},
            {"label": "country", "value": event.country},
            {"label": "event_type", "value": event.event_type},
            {"label": "severity", "value": event.severity},
            {"label": "populations_affected", "value": event.populations_affected},
            {"label": "affected_area_km2", "value": event.affected_area_km2},
            {"label": "lat", "value": event.lat},
            {"label": "lon", "value": event.lon},
            {"label": "activation_date", "value": event.activation_date},
            {"label": "copernicus_url", "value": event.copernicus_url},
            {"label": "name", "value": event.name},
            *_climate_context_facts(event.lat, event.lon, category="flood"),
        ],
        historical_context={
            "source": "Copernicus EMS Rapid Mapping",
            "scope": "non_us_global_flood_activation",
        },
        raw_signal_dump=asdict(event),
    )

def build_storm_surge_bundle(surge: StormSurgeEvent) -> StoryBundle:
    """A NOAA tide station observed water level far above prediction."""

    where = f"{surge.station_name}, {surge.state}" if surge.state else surge.station_name
    return StoryBundle(
        signal_kind="storm_surge",
        where=where,
        when=surge.date,
        event_id=surge.event_id,
        headline_metric={
            "label": "surge_anomaly_m",
            "value": surge.anomaly_m,
            "unit": "m",
        },
        current_facts=[
            {"label": "station_name", "value": surge.station_name},
            {"label": "state", "value": surge.state},
            {"label": "observed_m", "value": surge.observed_m},
            {"label": "predicted_m", "value": surge.predicted_m},
            {"label": "anomaly_m", "value": surge.anomaly_m},
        ],
        historical_context={},
        raw_signal_dump=asdict(surge),
    )
