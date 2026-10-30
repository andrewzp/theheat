"""Precipitation and snow two-bot intern builders."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.data.gpm_imerg import PrecipExtremeEvent
from src.data.nsidc_snow import SnowExtremeEvent
from src.two_bot.types import StoryBundle

from ._shared import _climate_context_facts


RAINFALL_PROVENANCE_FLAG = "THEHEAT_RAINFALL_WINDOW_PROVENANCE"


def rainfall_window_failures(window: dict[str, Any]) -> list[str]:
    from src.data.rainfall_supply import window_failures

    return window_failures(window)


def build_precipitation_bundle(event: PrecipExtremeEvent) -> StoryBundle:
    from src.data.rainfall_supply import window_evidence

    window = window_evidence(event)
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
        {"label": "city_count", "value": event.city_count},
        {"label": "sample_cities", "value": event.sample_cities},
        {"label": "lat", "value": event.lat},
        {"label": "lon", "value": event.lon},
        *_climate_context_facts(event.lat, event.lon, category="rain"),
    ]
    # Record facts ONLY when a real archive record exists (the daily_record
    # path). Threshold-crossing kinds (multi_day_accumulation) carry
    # alert_threshold_mm instead — a static trigger presented as "the previous
    # record" is a false-record claim no downstream gate can catch, because
    # the tweet matches the bundle (#372).
    if event.previous_record_mm is not None:
        facts.append({
            "label": "deviation_from_record_mm",
            "value": _rounded(event.deviation_from_record_mm),
        })
        facts.append({
            "label": "previous_record_mm",
            "value": _rounded(event.previous_record_mm),
        })
        facts.append({
            "label": "previous_record_year",
            "value": event.previous_record_year,
        })
    if event.alert_threshold_mm is not None:
        facts.append({
            "label": "alert_threshold_mm",
            "value": _rounded(event.alert_threshold_mm),
            "unit": "mm",
        })
    # R-03: precip served by the Open-Meteo model witness during a GPM outage is a
    # MODEL estimate, not a satellite observation. model_fallback tells the writer
    # + fact-check prompts to never write "observed/measured/recorded" (R-00).
    if event.source_leg == "open_meteo":
        facts.append({"label": "evidence_grade", "value": "model_fallback"})
        facts.append(
            {"label": "data_source", "value": "Open-Meteo multi-model forecast (ICON/GFS/ECMWF) — GPM backup, model estimate"}
        )
    historical_context: dict[str, Any] = {
        "scope": event.kind,
        "period_days": event.period_days,
        "city_count": event.city_count,
    }
    if event.previous_record_mm is not None:
        historical_context["previous_record_mm"] = event.previous_record_mm
        historical_context["previous_record_year"] = event.previous_record_year
    if event.alert_threshold_mm is not None:
        historical_context["alert_threshold_mm"] = event.alert_threshold_mm
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
        current_facts=[*facts, *_window_facts(window)],
        historical_context=historical_context,
        raw_signal_dump={**asdict(event), "rainfall_window": window},
    )


def _window_facts(window: dict[str, Any]) -> list[dict[str, Any]]:
    """W06: the accumulation window and footprint reach the brief and checks explicitly."""
    raw_footprint = window.get("footprint")
    footprint: dict[str, Any] = raw_footprint if isinstance(raw_footprint, dict) else {}
    rows: list[dict[str, Any]] = [
        {"label": "accumulation_window_utc",
         "value": f"{window.get('accumulation_start')} to {window.get('accumulation_end')}"},
        {"label": "footprint", "value": footprint.get("kind")},
        {"label": "rainfall_scope_limit", "value": window.get("limit")},
        {"label": "product_version", "value": window.get("product_version")},
        # Retrieval time is not carried on the event: it stays unknown (absent), never invented.
        *([{"label": "retrieved_at", "value": window["retrieved_at"]}] if window.get("retrieved_at") else []),
    ]
    # The requested product is real source identity; supplying it lets a complete
    # packet pass the existing provenance gate. Default off (exact "1"): until Root
    # enables it, rainfall candidates stay withheld at admission exactly as today.
    import os

    if os.environ.get(RAINFALL_PROVENANCE_FLAG) == "1" and not rainfall_window_failures(window):
        version = window.get("product_version")
        rows.append({"label": "source_product",
                     "value": f"{window['source_product']} {version}" if version else window["source_product"]})
    return rows


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
