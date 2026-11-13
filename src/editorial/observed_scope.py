"""Editorial scope, separate from source validity: observed events and context.

This hold never grants evidence quality or approval. Forecast archives and
graphics remain valid private inputs; the operating mode excludes forecast
stories before paid writing and at publication. Only structured primary-source
metadata is inspected, never words occurring in a source's prose.
"""
from __future__ import annotations

import os
from typing import Any

FLAG = "THEHEAT_OBSERVED_WEATHER_ONLY"
HOLD = "editorial_forecast_excluded"
MESSAGE = "TheHeat reports observed events and factual context; forecast stories are outside the current editorial scope."
FORECAST_KINDS = frozenset({
    "hot10", "air_quality_hazard", "dust_event", "severe_weather",
    "official_warning", "nhc_advisory", "cyclone_land_threat", "wet_bulb_extreme", "extreme_wave",
})
FORECAST_PRODUCTS = frozenset({
    "openmeteo-best-match-forecast-daily-v1", "open-meteo-cams-air-quality-auto",
    "Open-Meteo multi-model forecast precipitation", "openmeteo-marine-forecast",
})
FORECAST_TYPES = frozenset({"forecast", "model_forecast"})


def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def _field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _forecast(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    kind, product = value.get("evidence_type"), value.get("source_product")
    return (isinstance(kind, str) and kind in FORECAST_TYPES
            or isinstance(product, str) and product in FORECAST_PRODUCTS)


def _primary_forecast(value: Any) -> bool:
    kind = _field(value, "signal_kind") or _field(value, "type")
    if isinstance(kind, str) and kind in FORECAST_KINDS:
        return True
    raw = _field(value, "raw_signal_dump")
    if not isinstance(raw, dict):
        raw = {}
    # These exact fallback legs request forecast data; real gauges and GPM stay eligible.
    if raw.get("source_leg") == "open_meteo_flood" or (
        kind == "precipitation_extreme" and raw.get("source_leg") == "open_meteo"
    ):
        return True
    # A canonical product cannot be relabelled by a conflicting outer tag.
    if any(_forecast(row) for row in (raw, raw.get("evidence"), raw.get("forecast_window"),
                                      raw.get("source_evidence"), raw.get("rainfall_window"), _field(value, "air_quality_evidence"))):
        return True
    facts = _field(value, "current_facts")
    if isinstance(facts, list) and any(
        isinstance(row, dict) and (
            row.get("label") == "evidence_type" and isinstance(row.get("value"), str) and row["value"] in FORECAST_TYPES
            or row.get("label") == "source_product" and isinstance(row.get("value"), str) and row["value"] in FORECAST_PRODUCTS
        ) for row in facts
    ):
        return True
    metric = _field(value, "headline_metric")
    return isinstance(metric, dict) and (metric.get("is_forecast") is True
        or metric.get("label") == "modeled_discharge_m3s"
        or isinstance(metric.get("label"), str) and metric["label"].startswith("forecast_"))


def story_hold(value: Any, *, observed_only: bool | None = None) -> str | None:
    """Hold a forecast bundle or retained draft; absence of a hold grants nothing."""
    if not (enabled() if observed_only is None else observed_only):
        return None
    if _primary_forecast(value):
        return HOLD
    if isinstance(value, dict):
        context = value.get("review_context")
        two_bot = context.get("two_bot") if isinstance(context, dict) else None
        bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
        if isinstance(bundle, dict) and _primary_forecast(bundle):
            return HOLD
        if isinstance(bundle, dict):
            value = bundle
    related = _field(value, "related_signals")
    if isinstance(related, list) and any(_primary_forecast(row) for row in related):
        return HOLD
    return None
