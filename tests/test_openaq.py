from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import requests

from src.data.air_quality import PM25HazardEvent
from src.data.source_status import SourceSkipped
from src.two_bot.intern.air_quality import build_pm25_hazard_bundle


def _event(pm25: float = 180.0) -> PM25HazardEvent:
    return PM25HazardEvent(
        city="Lahore",
        country="Pakistan",
        lat=31.5204,
        lon=74.3587,
        date="2026-06-08",
        pm25_24h_mean=pm25,
        tier=1,
        who_multiple=12.0,
        us_aqi_daily_max=210,
        event_id="pm25_lahore_2026-06-08_tier1",
    )


def test_corroboration_upgrades_grade(monkeypatch):
    from src.data import openaq

    now = datetime(2026, 6, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(
        openaq,
        "fetch_latest_pm25",
        lambda lat, lon, api_key=None: openaq.OpenAQPM25Reading(
            station_name="Lahore Jail Road",
            pm25_ug_m3=172.0,
            observed_at=now - timedelta(hours=1),
            distance_km=4.2,
        ),
    )

    event = openaq.corroborate_pm25_hazard(_event(), now=now)
    bundle = build_pm25_hazard_bundle(event)
    facts = {fact["label"]: fact["value"] for fact in bundle.current_facts}

    assert event.evidence_grade == "model_corroborated_by_station"
    assert event.station_name == "Lahore Jail Road"
    assert facts["evidence_grade"] == "model_corroborated_by_station"
    assert facts["station_name"] == "Lahore Jail Road"
    assert facts["station_pm25_ug_m3"] == 172.0
    assert facts["station_distance_km"] == 4.2


def test_distant_or_stale_station_no_upgrade(monkeypatch):
    from src.data import openaq

    now = datetime(2026, 6, 8, 12, tzinfo=UTC)
    readings = iter([
        openaq.OpenAQPM25Reading(
            station_name="Far Station",
            pm25_ug_m3=175.0,
            observed_at=now - timedelta(hours=1),
            distance_km=31.0,
        ),
        openaq.OpenAQPM25Reading(
            station_name="Old Station",
            pm25_ug_m3=175.0,
            observed_at=now - timedelta(hours=7),
            distance_km=5.0,
        ),
    ])
    monkeypatch.setattr(
        openaq,
        "fetch_latest_pm25",
        lambda lat, lon, api_key=None: next(readings),
    )

    assert openaq.corroborate_pm25_hazard(_event(), now=now).evidence_grade == "model_estimated"
    assert openaq.corroborate_pm25_hazard(_event(), now=now).evidence_grade == "model_estimated"


def test_openaq_failure_keeps_model_grade(monkeypatch):
    from src.data import openaq

    monkeypatch.setattr(
        openaq,
        "fetch_latest_pm25",
        lambda lat, lon, api_key=None: (_ for _ in ()).throw(requests.Timeout("slow")),
    )

    event = openaq.corroborate_pm25_hazard(_event())

    assert event.evidence_grade == "model_estimated"
    assert event.station_name is None


def test_skipped_without_api_key(monkeypatch):
    from src.data import openaq

    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    with pytest.raises(SourceSkipped, match="OPENAQ_API_KEY"):
        openaq.fetch_latest_pm25(31.5204, 74.3587)
