"""Ordinary policy skips over invented forecasts; no provider/model/platform calls."""

from copy import deepcopy
from datetime import datetime, timedelta, UTC

import pytest

from src.orchestrator.sources import air_quality as runner
from src.state import DEFAULT_STATE, record_source_health
from scripts.source_health_sentinel import classify_source, run_sentinel, plan_health_issue_actions
from tests.air_quality_fixtures import observation

CLASS = "editorial_scope"
CITY = {"city": "Invented Town", "country": "Example", "lat": "31.5", "lon": "74.3"}


@pytest.fixture
def world(monkeypatch):
    for key, value in {
        "THEHEAT_OBSERVED_WEATHER_ONLY": "1",
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_REF": "refs/heads/main",
        "THEHEAT_AQ_PM25_ENABLED": "1",
        "THEHEAT_AQ_DUST_ENABLED": "1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    calls = []

    def fetch(cities):
        calls.append(deepcopy(cities))
        return [observation(city=CITY["city"], country=CITY["country"], dust=None)]

    monkeypatch.setattr(runner.air_quality, "fetch_batch_air_quality", fetch)
    return (
        deepcopy(DEFAULT_STATE),
        {"id": "invented-policy-run", "mode": "alerts", "sources": []},
        calls,
    )


@pytest.mark.parametrize("mode", ["alerts", "both"])
def test_policy_skip_precedes_provider_openaq_and_queue_and_records_no_attempt(
    world, monkeypatch, mode
):
    state, run, calls = world
    run["mode"] = mode
    monkeypatch.setenv("OPENAQ_API_KEY", "invented-never-used")

    def forbidden(*args, **kwargs):
        raise AssertionError("policy skip must not reach corroboration or queue")

    monkeypatch.setattr(runner.openaq, "corroborate_pm25_hazard", forbidden)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", forbidden)
    state["air_quality_pm25_tiers"] = {"invented": {"tier": 3, "date": "2026-01-01"}}
    before_tiers = deepcopy(state["air_quality_pm25_tiers"])
    prior = datetime.now(UTC) - timedelta(hours=1)
    for index in range(3):
        record_source_health(
            state,
            "air_quality",
            "failed",
            "Invented previous timeout",
            timestamp=(prior + timedelta(minutes=index)).isoformat(),
        )
    before = deepcopy(state["source_health"]["air_quality"])
    runner.run_air_quality(state, run, [CITY])
    assert calls == []
    assert state["air_quality_pm25_tiers"] == before_tiers
    assert "_triage_queue" not in state and state["drafts"] == []
    [row] = run["sources"]
    assert row["status"] == "skipped" and row["error"] is None and row["error_class"] == CLASS
    assert all(
        row[key] == 0
        for key in (
            "observed",
            "promoted",
            "triaged_in",
            "triaged_out",
            "writer_attempted",
            "drafted",
        )
    )
    health = state["source_health"]["air_quality"]
    assert health["failed"] == before["failed"] == 3 and health["success"] == 0
    assert (
        health["last_error"] == before["last_error"]
        and health["last_success_ts"] == before["last_success_ts"]
    )
    assert health["runs"][:-1] == before["runs"]
    verdict = classify_source("air_quality", health)
    assert verdict["category"] == "idle" and verdict["issue_resolution_unknown"] is True
    report = run_sentinel(state["source_health"])
    assert plan_health_issue_actions(report, {"air_quality": 123}) == []  # No fabricated recovery.


@pytest.mark.parametrize(
    "key,value",
    [
        ("THEHEAT_OBSERVED_WEATHER_ONLY", "0"),
        ("THEHEAT_OBSERVED_WEATHER_ONLY", "true"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REF", "refs/heads/private"),
        ("GITHUB_REF", "refs/tags/main"),
    ],
)
def test_one_context_deviation_keeps_existing_forecast_acquisition(world, monkeypatch, key, value):
    state, run, calls = world
    monkeypatch.setenv(key, value)
    runner.run_air_quality(state, run, [CITY])
    assert calls == [[CITY]]
    assert run["sources"][0].get("error_class") != CLASS
    assert state["source_health"]["air_quality"]["runs"][-1]["status"] != "skipped"


@pytest.mark.parametrize("mode", [None, "private", "metar_report"])
def test_unscoped_or_other_run_mode_keeps_private_forecast_acquisition(world, mode):
    state, run, calls = world
    run["mode"] = mode
    runner.run_air_quality(state, run, [CITY])
    assert calls == [[CITY]]


def test_absent_run_keeps_existing_acquisition(world):
    state, _, calls = world
    runner.run_air_quality(state, None, [CITY])
    assert calls == [[CITY]]


@pytest.mark.parametrize(
    "source,status,kind",
    [
        ("air_quality", "failed", CLASS),
        ("air_quality", "skipped", "different"),
        ("ocean", "skipped", CLASS),
    ],
)
def test_skip_diagnostic_cannot_hide_an_active_failure_or_another_source(source, status, kind):
    health = {
        "failed": 3,
        "success": 0,
        "last_error": "Invented timeout",
        "runs": [{"status": "failed"}] * 3 + [{"status": status, "error_class": kind}],
    }
    assert classify_source(source, health)["category"] == "failing"
