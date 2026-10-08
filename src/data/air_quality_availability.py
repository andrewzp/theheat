"""Count qualified requested forecast slots without inferring missing-data causes."""
from __future__ import annotations

from typing import Any

from src.data.air_quality import CityAirQuality
from src.data import air_quality_contract as contract
from src.data.source_status import SourceFetchError

AQ_MIN_COVERAGE = 0.90
_HAZARDS = {"pm25": "pm2_5", "dust": "dust"}
_COUNTS = ("complete", "incomplete", "missing", "invalid", "unavailable_window")
_AGGREGATES = {
    "pm25_24h_mean": "pm2_5", "dust_daily_max": "dust",
    "aod_daily_max": "aerosol_optical_depth", "us_aqi_daily_max": "us_aqi",
    "pm10_24h_mean": "pm10",
}


def _same_number(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual is None
    return contract._number(actual) and actual == expected


def _qualified(city: Any, observation: Any) -> CityAirQuality | None:
    if not isinstance(observation, CityAirQuality) or type(city) is not dict:
        return None
    try:
        packet = observation.forecast_window
        values = contract.validate_window(packet)
        assert isinstance(packet, dict)  # Established by the contract validator.
        location = packet["requested_location"]
        for key in ("city", "country"):
            if type(city.get(key)) is not str or city[key] != location[key] or getattr(observation, key) != location[key]:
                return None
        for key in ("lat", "lon"):
            if type(city.get(key)) not in (str, int, float):
                return None
            requested = float(city[key])
            if not _same_number(requested, location[key]) or not _same_number(getattr(observation, key), location[key]):
                return None
        if observation.date != packet["date"]:
            return None
        if any(not _same_number(getattr(observation, attr), values[key]) for attr, key in _AGGREGATES.items()):
            return None
        return observation
    except (SourceFetchError, TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
        return None


def assess_air_quality(
    cities: list[dict], observations: Any, *, pm25_enabled: bool, dust_enabled: bool,
) -> tuple[list[CityAirQuality | None], dict[str, Any]]:
    """Return qualified slots and constant-size telemetry; never repair evidence.

    Counts describe request slots, not distinct places or independent global recall.
    The fetcher's None result has no reliable finer failure cause.
    """
    total = len(cities)
    enabled = {"pm25": pm25_enabled, "dust": dust_enabled}
    attempted = bool(total and any(enabled.values()))
    received = len(observations) if type(observations) is list else None
    shape = ("matched" if received == total else "mismatch") if received is not None else "invalid"
    if not attempted:
        shape, received = "not_requested", None
    hazards: dict[str, Any] = {
        key: dict(enabled=flag, status="disabled" if not flag else "not_configured",
                  requested=total if flag else 0, coverage=None, **{name: 0 for name in _COUNTS})
        for key, flag in enabled.items()
    }
    qualified: list[CityAirQuality | None] = [None] * total
    observed = 0
    if attempted:
        for index, city in enumerate(cities):
            observation = _qualified(city, observations[index]) if shape == "matched" else None
            available = False
            for key, variable in _HAZARDS.items():
                if not enabled[key]:
                    continue
                category = (observation.forecast_window["series"][variable]["status"]
                            if observation is not None and observation.forecast_window is not None
                            else "unavailable_window")
                hazards[key][category] += 1
                available |= category == "complete"
            if available:
                observed += 1
                qualified[index] = observation
        for lane in hazards.values():
            if lane["enabled"]:
                lane["coverage"] = lane["complete"] / total
                lane["status"] = ("available" if lane["coverage"] >= AQ_MIN_COVERAGE else
                                  "partial" if lane["complete"] else "unavailable")
    return qualified, dict(schema_version=1, evidence_type="model_forecast",
                           requested_cities=total, observed_cities=observed,
                           result_shape=shape, received_slots=received, hazards=hazards)


def source_status(summary: dict[str, Any]) -> str:
    if summary["result_shape"] == "not_requested":
        return "skipped"
    if not summary["observed_cities"]:
        return "failed"
    return "success" if all(not lane["enabled"] or lane["status"] == "available"
                            for lane in summary["hazards"].values()) else "degraded"


def availability_note(summary: dict[str, Any]) -> str:
    """Safe fixed labels and percentages; bare city counts can mimic HTTP codes."""
    parts = []
    for key, label in (("pm25", "PM2.5"), ("dust", "dust")):
        lane = summary["hazards"][key]
        coverage = lane["coverage"]
        if coverage is None:
            parts.append(f"{label} {lane['status'].replace('_', ' ')}")
            continue
        percent = f"{coverage:.1%}"
        if coverage < 1 and percent == "100.0%":
            percent = "<100%"
        elif coverage > 0 and percent == "0.0%":
            percent = "<0.1%"
        gaps = [name.replace("_", " ") for name in _COUNTS[1:] if lane[name]]
        suffix = f" ({', '.join(gaps)})" if gaps else ""
        parts.append(f"{label} {lane['status']}: {percent} complete{suffix}")
    return "CAMS forecast availability: " + "; ".join(parts)
