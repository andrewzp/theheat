"""NOAA CO-OPS — coastal water levels, tides, and storm surge.

Free API, no auth required. Real-time water level data from
tide gauges across the US coastline.
Docs: https://api.tidesandcurrents.noaa.gov/api/prod/
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
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


@dataclass
class StormSurgeEvent:
    station_name: str
    state: str
    anomaly_m: float
    observed_m: float
    predicted_m: float
    date: str
    event_id: str


def fetch_water_levels(*, strict: bool = False) -> list[WaterLevelReading]:
    """Fetch latest water level readings for all monitored stations."""
    readings = []
    failures: list[str] = []
    payload_dates = []
    today = date.today()
    now = datetime.now(UTC)
    begin = (now - timedelta(hours=6)).strftime("%Y%m%d %H:%M")
    end = now.strftime("%Y%m%d %H:%M")

    for station_id, name, state in STATIONS:
        try:
            resp = fetch_with_retry(
                COOPS_URL,
                params={
                    "begin_date": begin,
                    "end_date": end,
                    "station": station_id,
                    "product": "water_level",
                    "datum": "MLLW",
                    "units": "metric",
                    "time_zone": "gmt",
                    "application": "theheat_bot",
                    "format": "json",
                },
                timeout=15,
                attempts=3,
                backoff_base=1.0,
            )
            data = resp.json()

            obs_data = data.get("data", [])
            if not obs_data:
                continue

            # Get the most recent observation
            latest_obs = obs_data[-1]
            obs_time = latest_obs.get("t", "")
            payload_dates.append(obs_time)
            observed = float(latest_obs.get("v", 0))

            # Fetch predicted tide for comparison
            resp_pred = fetch_with_retry(
                COOPS_URL,
                params={
                    "begin_date": begin,
                    "end_date": end,
                    "station": station_id,
                    "product": "predictions",
                    "datum": "MLLW",
                    "units": "metric",
                    "time_zone": "gmt",
                    "application": "theheat_bot",
                    "format": "json",
                },
                timeout=15,
                attempts=3,
                backoff_base=1.0,
            )
            pred_data = resp_pred.json().get("predictions", [])
            if not pred_data:
                continue

            # Match prediction to observation by closest timestamp
            predicted = float(pred_data[-1].get("v", 0))
            if obs_time:
                for p in pred_data:
                    if p.get("t", "") == obs_time:
                        predicted = float(p.get("v", 0))
                        break
            anomaly = observed - predicted

            event_id = f"water_{station_id}_{today.isoformat()}"

            readings.append(WaterLevelReading(
                station_name=name,
                state=state,
                station_id=station_id,
                observed_m=round(observed, 3),
                predicted_m=round(predicted, 3),
                anomaly_m=round(anomaly, 3),
                date=today.isoformat(),
                event_id=event_id,
            ))

        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            failures.append(f"{station_id}: {exc}")
            continue

    if strict and failures and not readings:
        raise SourceFetchError(f"Water levels fetch failed for all stations: {failures[0]}")
    if newest_date := newest_freshness_date(payload_dates):
        assert_freshness(newest_date, "water_levels", max_age_days=2)
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
                event_id=f"surge_{severity}_{r.station_id}_{r.date}",
            ))
    return events
