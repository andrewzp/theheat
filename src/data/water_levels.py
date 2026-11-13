"""NOAA CO-OPS — coastal water levels, tides, and storm surge.

Free API, no auth required. Real-time water level data from
tide gauges across the US coastline.
Docs: https://api.tidesandcurrents.noaa.gov/api/prod/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import hashlib
import math
from copy import deepcopy
from urllib.parse import urlencode

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

COOPS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

# Key coastal stations: (station_id, name, state)
# These cover major coastline regions and are historically significant
STATIONS = [
    ("8518750", "The Battery, NY", "NY"),
    ("8723214", "Virginia Key, FL", "FL"),
    ("8729108", "Panama City, FL", "FL"),
    ("8771450", "Galveston, TX", "TX"),
    ("9410660", "Los Angeles, CA", "CA"),
    ("9414290", "San Francisco, CA", "CA"),
    ("9447130", "Seattle, WA", "WA"),
    ("8665530", "Charleston, SC", "SC"),
    ("8574680", "Baltimore, MD", "MD"),
    ("8443970", "Boston, MA", "MA"),
    ("1612340", "Honolulu, HI", "HI"),
    ("9455920", "Anchorage, AK", "AK"),
]

# Anomaly threshold: water level this far above predicted = notable (meters)
SURGE_THRESHOLD_M = 0.5
MAJOR_SURGE_THRESHOLD_M = 1.0


@dataclass
class WaterLevelReading:
    station_name: str
    state: str
    station_id: str
    observed_m: float
    predicted_m: float
    anomaly_m: float
    date: str
    event_id: str
    evidence: dict = field(default_factory=dict)


@dataclass
class StormSurgeEvent:
    station_name: str
    state: str
    anomaly_m: float
    observed_m: float
    predicted_m: float
    date: str
    event_id: str
    station_id: str = ""
    evidence: dict = field(default_factory=dict)


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, float, int)) or value == "":
        raise ValueError("water_levels invalid value")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("water_levels nonfinite value")
    return number


def _sample_time(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("water_levels missing GMT timestamp")
    # The request fixes time_zone=gmt; do not infer station-local midnight.
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def _pair(station_id: str, name: str, state: str, observed: dict, predicted: dict,
          *, now: datetime, observed_sha256: str, predicted_sha256: str) -> WaterLevelReading:
    if not isinstance(observed, dict) or not isinstance(predicted, dict):
        raise ValueError("water_levels invalid response")
    metadata = observed.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("id") != station_id:
        raise ValueError("water_levels station identity mismatch")
    rows = observed.get("data")
    predictions = predicted.get("predictions")
    if not isinstance(rows, list) or not rows or not isinstance(predictions, list) or not predictions:
        raise ValueError("water_levels missing paired samples")
    # A rejected latest sample never falls back to an older good one.
    times = [(_sample_time(row.get("t")), row) for row in rows if isinstance(row, dict)]
    if len(times) != len(rows):
        raise ValueError("water_levels malformed observation")
    latest = max(t for t, _ in times)
    matching = [row for t, row in times if t == latest]
    if any(row != matching[0] for row in matching):
        raise ValueError("water_levels contradictory observation")
    if latest > now or now - latest > timedelta(hours=6):
        raise ValueError("water_levels stale data or future observation")
    row = matching[0]
    quality, flags = row.get("q"), row.get("f")
    if quality not in {"p", "v"} or not isinstance(flags, str):
        raise ValueError("water_levels missing quality support")
    parts = flags.split(",")
    if len(parts) != 4 or any(not part.isdigit() for part in parts):
        raise ValueError("water_levels malformed quality flags")
    # Preliminary first component counts outlying 1-second samples; verified
    # first component flags inference. Preserve that distinction, not q=p=>bad.
    if any(int(part) != 0 for part in parts[1:]) or quality == "v" and int(parts[0]) != 0:
        raise ValueError("water_levels flagged or inferred observation")
    value = _number(row.get("v"))
    paired = [p for p in predictions if isinstance(p, dict) and p.get("t") == row["t"]]
    if not paired or any(p != paired[0] for p in paired):
        raise ValueError("water_levels missing or conflicting same-time tide prediction")
    tide = _number(paired[0].get("v"))
    valid = latest.isoformat().replace("+00:00", "Z")
    retrieved = now.isoformat().replace("+00:00", "Z")
    day = latest.date().isoformat()
    evidence = {"source_product": "noaa-coops-water-level-v1", "source_url": COOPS_URL,
                "evidence_type": "observed", "station_id": station_id,
                "valid_date": day, "valid_time": valid, "retrieved_at": retrieved,
                "unit": "m", "datum": "MLLW", "time_zone": "gmt",
                "quality": quality, "quality_status": "preliminary" if quality == "p" else "verified",
                "quality_flags": flags,
                "observed_m": value, "predicted_tide_m": tide,
                "prediction_valid_time": valid, "prediction_product": "predictions",
                "observed_response_sha256": observed_sha256,
                "prediction_response_sha256": predicted_sha256,
                "claim_scope": "Gauge height minus same-time astronomical tide prediction; no storm cause, flood impact or historical-record claim."}
    return WaterLevelReading(name, state, station_id, round(value, 3), round(tide, 3),
                             round(value - tide, 3), day, f"water_{station_id}_{day}", evidence)


def fetch_water_levels(*, strict: bool = False, metrics_out: dict | None = None) -> list[WaterLevelReading]:
    """Fetch paired, time-bound observed gauge and tide-comparison samples."""
    readings: list[WaterLevelReading] = []
    failures: list[str] = []
    now = datetime.now(UTC)
    begin = (now - timedelta(hours=6)).strftime("%Y%m%d %H:%M")
    end = now.strftime("%Y%m%d %H:%M")
    for station_id, name, state in STATIONS:
        try:
            params = {"begin_date": begin, "end_date": end, "station": station_id,
                      "datum": "MLLW", "units": "metric", "time_zone": "gmt",
                      "application": "theheat_bot", "format": "json"}
            obs = fetch_with_retry(COOPS_URL, params={**params, "product": "water_level"},
                                   timeout=15, attempts=3, backoff_base=1.0)
            pred = fetch_with_retry(COOPS_URL, params={**params, "product": "predictions", "interval": "6"},
                                    timeout=15, attempts=3, backoff_base=1.0)
            reading = _pair(station_id, name, state, obs.json(), pred.json(), now=datetime.now(UTC),
                            observed_sha256=hashlib.sha256(obs.content).hexdigest(),
                            predicted_sha256=hashlib.sha256(pred.content).hexdigest())
            reading.evidence["source_requests"] = {
                "observation_query": urlencode({**params, "product": "water_level"}),
                "tide_comparison_query": urlencode({**params, "product": "predictions", "interval": "6"}),
            }
            readings.append(reading)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            failures.append(f"{station_id}: {exc}")
    if metrics_out is not None:
        metrics_out.update(stations_requested=len(STATIONS), stations_qualified=len(readings),
                           stations_withheld=len(failures))
    if strict and failures and not readings:
        raise SourceFetchError(f"Water levels fetch failed for all stations: {failures[0]}")
    return readings


def detect_storm_surge(
    readings: list[WaterLevelReading],
    threshold_m: float = SURGE_THRESHOLD_M,
) -> list[StormSurgeEvent]:
    """Detect stations where water level is significantly above predicted."""
    events = []
    for r in readings:
        if r.anomaly_m >= threshold_m:
            severity = "major" if r.anomaly_m >= MAJOR_SURGE_THRESHOLD_M else "notable"
            events.append(StormSurgeEvent(
                station_name=r.station_name,
                state=r.state,
                anomaly_m=r.anomaly_m,
                observed_m=r.observed_m,
                predicted_m=r.predicted_m,
                date=r.date,
                station_id=r.station_id,
                evidence=deepcopy(r.evidence),
                event_id=f"surge_{severity}_{r.station_id}_{r.date}",
            ))
    return events
