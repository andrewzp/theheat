from __future__ import annotations

from copy import deepcopy

import pytest

from src.data.air_quality import CityAirQuality
from src.state import DEFAULT_STATE


def _city(city: str = "Lahore", country: str = "Pakistan") -> dict:
    return {"city": city, "country": country, "lat": "31.5", "lon": "74.3"}


def _obs(
    city: str = "Lahore",
    country: str = "Pakistan",
    *,
    day: str = "2026-06-08",
    pm25: float | None = 150.0,
    dust: float | None = None,
) -> CityAirQuality:
    return CityAirQuality(
        city=city,
        country=country,
        lat=31.5,
        lon=74.3,
        date=day,
        pm25_24h_mean=pm25,
        dust_daily_max=dust,
        aod_daily_max=0.6,
        us_aqi_daily_max=210,
    )


@pytest.fixture
def bot_state() -> dict:
    return deepcopy(DEFAULT_STATE)


def test_run_air_quality_enqueues_pm25_candidate(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs()],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    queue = bot_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "pm25_lahore_2026-06-08_tier1"
    assert queue[0].legacy_type == "air_quality_hazard"


def test_run_air_quality_enqueues_dust_candidate(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(city="Khartoum", country="Sudan", pm25=None, dust=500.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city(city="Khartoum", country="Sudan")])

    queue = bot_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "dust_khartoum_2026-06-08_tier1"
    assert queue[0].legacy_type == "dust_event"


def test_run_air_quality_tier_dedup_no_refire(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    bot_state["air_quality_pm25_tiers"] = {"lahore": {"tier": 1, "date": "2026-06-08"}}
    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(pm25=150.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    assert bot_state.get("_triage_queue", []) == []


def test_run_air_quality_tier_upgrade_fires(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    bot_state["air_quality_pm25_tiers"] = {"lahore": {"tier": 1, "date": "2026-06-08"}}
    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(pm25=250.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    queue = bot_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "pm25_lahore_2026-06-08_tier2"


def test_run_air_quality_new_day_resets_tier(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    bot_state["air_quality_pm25_tiers"] = {"lahore": {"tier": 1, "date": "2026-06-07"}}
    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(pm25=150.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    assert len(bot_state["_triage_queue"]) == 1


def test_run_air_quality_is_duplicate_guard(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    bot_state["posted_events"] = ["pm25_lahore_2026-06-08_tier1"]
    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(pm25=150.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    assert bot_state.get("_triage_queue", []) == []


def test_run_air_quality_empty_city_list(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [],
    )

    current_run = {"sources": []}
    run_air_quality(bot_state, current_run, [])

    source_entry = next(s for s in current_run["sources"] if s["source"] == "air_quality")
    assert source_entry["status"] == "success"
    assert source_entry["observed"] == 0


def test_run_air_quality_all_cities_fail_http_records_failed(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [None, None],
    )

    current_run = {"sources": []}
    run_air_quality(bot_state, current_run, [_city(), _city(city="Delhi", country="India")])

    source_entry = next(s for s in current_run["sources"] if s["source"] == "air_quality")
    assert source_entry["status"] == "failed"
    assert source_entry["observed"] == 0
    assert source_entry["details"]["failed_cities"] == 2
    assert any(error["source"] == "air_quality" for error in bot_state["errors"])


def test_run_air_quality_tier_state_written_on_success(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(pm25=150.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    assert bot_state["air_quality_pm25_tiers"] == {}
    candidate = bot_state["_triage_queue"][0]
    assert candidate.on_draft_success is not None
    candidate.on_draft_success()
    assert bot_state["air_quality_pm25_tiers"] == {
        "lahore": {"tier": 1, "date": "2026-06-08"}
    }


def test_run_air_quality_tier_state_not_written_without_success(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda cities: [_obs(pm25=150.0)],
    )

    run_air_quality(bot_state, {"sources": []}, [_city()])

    assert len(bot_state["_triage_queue"]) == 1
    assert bot_state["air_quality_pm25_tiers"] == {}


def test_multi_city_tier_state_each_recorded(bot_state, monkeypatch):
    from src.orchestrator.sources.air_quality import run_air_quality

    observations = [
        _obs(city="Lahore", country="Pakistan", pm25=150.0),
        _obs(city="Delhi", country="India", pm25=250.0),
    ]
    cities = [
        _city(city="Lahore", country="Pakistan"),
        _city(city="Delhi", country="India"),
    ]
    monkeypatch.setattr(
        "src.orchestrator.sources.air_quality.air_quality.fetch_batch_air_quality",
        lambda rows: observations,
    )

    run_air_quality(bot_state, {"sources": []}, cities)

    queue = bot_state["_triage_queue"]
    assert len(queue) == 2
    for candidate in queue:
        assert candidate.on_draft_success is not None
        candidate.on_draft_success()
    assert bot_state["air_quality_pm25_tiers"] == {
        "lahore": {"tier": 1, "date": "2026-06-08"},
        "delhi": {"tier": 2, "date": "2026-06-08"},
    }
