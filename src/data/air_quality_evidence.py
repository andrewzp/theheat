"""Bind air-quality story values to the retained local-day forecast samples."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields, replace
import json
from typing import Any

from src.data import air_quality_contract as contract
from src.data.source_status import SourceFetchError

KINDS = frozenset({"air_quality_hazard", "dust_event"})


def is_air_quality(value: Any) -> bool:
    raw = getattr(value, "raw_signal_dump", None)
    kind = getattr(value, "signal_kind", None)
    return ((isinstance(kind, str) and kind in KINDS)
            or getattr(value, "air_quality_evidence", None) is not None
            or (isinstance(raw, dict) and "forecast_window" in raw))


def window_facts(packet: Any) -> list[dict]:
    if not isinstance(packet, dict):
        return []
    # Preserve supplied values, even when invalid; the audit rejects alteration.
    return [{"label": key, "value": deepcopy(packet.get(key))} for key in (
        "timezone", "valid_start", "valid_end", "requested_at", "retrieved_at",
    )] + [
        {"label": "time_basis", "value": "City-local forecast calendar day"},
        {"label": "aggregation_method", "value": contract.METHOD},
        {"label": "claim_limit", "value": contract.LIMITS},
        {"label": "source_grid_location", "value": deepcopy(packet.get("grid_location"))},
    ]


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def _expected(raw: Any, kind: str):
    from src.data.air_quality import (
        CityAirQuality, DustEvent, PM25HazardEvent, detect_dust_event, detect_pm25_hazard,
    )
    from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle

    if type(raw) is not dict or not isinstance(kind, str) or kind not in KINDS:
        contract.reject("wrong_signal")
    cls = DustEvent if kind == "dust_event" else PM25HazardEvent
    event = cls(**{f.name: raw[f.name] for f in fields(cls) if f.name in raw})
    packet = event.forecast_window
    values = contract.validate_window(packet)
    if not isinstance(packet, dict):
        contract.reject("missing_window")
    loc = packet["requested_location"]
    obs = CityAirQuality(
        **loc, date=packet["date"], pm25_24h_mean=values["pm2_5"], dust_daily_max=values["dust"],
        aod_daily_max=values["aerosol_optical_depth"], pm10_24h_mean=values["pm10"],
        us_aqi_daily_max=int(values["us_aqi"]) if values["us_aqi"] is not None else None,
        forecast_window=packet,
    )
    expected: DustEvent | PM25HazardEvent | None
    expected = detect_dust_event(obs) if kind == "dust_event" else detect_pm25_hazard(obs)
    if expected is None:
        contract.reject("no_qualified_threshold")
    if isinstance(event, PM25HazardEvent) and isinstance(expected, PM25HazardEvent):
        if event.evidence_grade == "model_corroborated_by_station":
            if (not isinstance(event.station_name, str) or not 0 < len(event.station_name.strip()) <= 500
                    or not contract._number(event.station_pm25_ug_m3) or event.station_pm25_ug_m3 < 0
                    or not contract._number(event.station_distance_km) or not 0 <= event.station_distance_km <= 30):
                contract.reject("station_annotation")
            expected = replace(expected, evidence_grade=event.evidence_grade, station_name=event.station_name,
                               station_pm25_ug_m3=event.station_pm25_ug_m3,
                               station_distance_km=event.station_distance_km)
    if not _same(asdict(event), asdict(expected)):
        contract.reject("aggregate_binding")
    return build_dust_event_bundle(expected) if isinstance(expected, DustEvent) else build_pm25_hazard_bundle(expected)


def validate_bundle(bundle: Any):
    expected = _expected(bundle.raw_signal_dump, bundle.signal_kind)
    for key in ("event_id", "where", "when", "country", "headline_metric", "current_facts",
                "historical_context", "raw_signal_dump"):
        if not _same(getattr(bundle, key), getattr(expected, key)):
            contract.reject("story_projection")
    return expected


def bundle_failures(bundle: Any) -> list[str]:
    failures = []
    caught = (SourceFetchError, TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError)
    if is_air_quality(bundle):
        try:
            validate_bundle(bundle)
        except caught:
            failures.append("Primary air-quality evidence requires an intact complete dated forecast window and matching aggregates")
    related = getattr(bundle, "related_signals", None)
    if isinstance(related, list):
        for signal in related:
            if not is_air_quality(signal):
                continue
            try:
                expected = _expected(getattr(signal, "air_quality_evidence", None), signal.signal_kind)
                for key in ("event_id", "where", "when", "country", "headline_metric"):
                    if not _same(getattr(signal, key), getattr(expected, key)):
                        contract.reject("related_projection")
            except caught:
                failures.append("Related air-quality evidence requires an intact dated forecast window and matching aggregate")
                break
    return failures
