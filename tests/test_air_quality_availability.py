"""Invented source-to-health regressions; never call weather or model providers."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from src.data import air_quality as source
from src.data import air_quality_availability as availability
from src.data import air_quality_contract as contract
from src.orchestrator.sources.air_quality import run_air_quality
from src.state import DEFAULT_STATE, record_source_health
from scripts.source_health_sentinel import classify_source
from tests.air_quality_fixtures import payload

DAY = "2026-06-08"
COUNTS = ("complete", "incomplete", "missing", "invalid", "unavailable_window")


def city(index=0):
    return dict(city=f"Invented City {index}", country="Test Country", lat="31.5", lon="74.3")


def observation(index=0, *, pm25=0., dust=0., variable=None, loss=None):
    data = payload(day=DAY, pm25=pm25, dust=dust, pm10=0., aod=0., us_aqi=0)
    if loss == "missing":
        del data["hourly"][variable]
    elif loss == "incomplete":
        data["hourly"][variable][3] = None
    elif loss == "invalid":
        data["hourly_units"][variable] = "invented wrong unit"
    return source._parse_single_location(
        data, city(index)["city"], "Test Country", 31.5, 74.3, DAY,
        requested_at=DAY + "T12:00:00Z", retrieved_at=DAY + "T12:00:01Z",
    )


def assess(cities, observations, pm25=True, dust=True):
    qualified, summary = availability.assess_air_quality(
        cities, observations, pm25_enabled=pm25, dust_enabled=dust,
    )
    assert len(qualified) == len(cities)
    for lane in summary["hazards"].values():
        assert sum(lane[key] for key in COUNTS) == lane["requested"]
        assert all(type(lane[key]) is int and lane[key] >= 0 for key in COUNTS)
    assert len(json.dumps(summary)) < 1500  # No per-city records or hourly arrays.
    return qualified, summary


@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    monkeypatch.setenv("THEHEAT_AQ_PM25_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AQ_DUST_ENABLED", "1")
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("network forbidden")))


def run(monkeypatch, cities, observations, *, current=True):
    fetch = Mock(return_value=observations)
    monkeypatch.setattr(source, "fetch_batch_air_quality", fetch)
    state = deepcopy(DEFAULT_STATE)
    current_run = {"sources": [], "started_at": datetime.now(UTC).isoformat()} if current else None
    run_air_quality(state, current_run, cities)
    return state, current_run, fetch


def test_quiet_data_remains_available_without_event_or_evidence_mutation(monkeypatch):
    cities, observations = [city(i) for i in range(2)], [observation(i) for i in range(2)]
    before = deepcopy(observations)
    qualified, summary = assess(cities, observations)
    assert qualified == observations == before
    assert all(a is b for a, b in zip(qualified, observations, strict=True))
    assert summary["observed_cities"] == 2 and summary["evidence_type"] == "model_forecast"
    assert availability.source_status(summary) == "success"
    state, current, fetch = run(monkeypatch, cities, observations)
    assert current["sources"][0]["status"] == "success"
    assert not state.get("_triage_queue") and fetch.call_count == 1


@pytest.mark.parametrize("variable,lane,other", [("pm2_5", "pm25", "dust"), ("dust", "dust", "pm25")])
@pytest.mark.parametrize("loss", ["missing", "incomplete", "invalid"])
def test_unavailable_primary_does_not_borrow_other_hazards_success(monkeypatch, variable, lane, other, loss):
    observations = [observation(i, variable=variable, loss=loss) for i in range(2)]
    state, current, _ = run(monkeypatch, [city(0), city(1)], observations)
    entry = current["sources"][0]
    assert entry["status"] == "degraded" and entry["observed"] == 2
    summary = entry["details"]["aq_availability"]
    assert summary["hazards"][lane][loss] == 2
    assert summary["hazards"][lane]["complete"] == 0
    assert summary["hazards"][other]["complete"] == 2
    assert loss in state["source_health"]["air_quality"]["last_error"]
    assert not state.get("_triage_queue")


@pytest.mark.parametrize("complete,status", [(0, "degraded"), (89, "degraded"), (90, "success"), (95, "success"), (100, "success")])
@pytest.mark.parametrize("variable,lane", [("pm2_5", "pm25"), ("dust", "dust")])
def test_existing_tolerance_applies_to_each_enabled_hazard(complete, status, variable, lane):
    observations = [observation(i, variable=variable, loss=None if i < complete else "missing") for i in range(100)]
    _, summary = assess([city(i) for i in range(100)], observations)
    assert availability.source_status(summary) == status
    assert summary["observed_cities"] == 100
    assert summary["hazards"][lane]["complete"] == complete
    assert summary["hazards"][lane]["coverage"] == complete / 100


@pytest.mark.parametrize("variable", ["pm10", "aerosol_optical_depth", "us_aqi"])
@pytest.mark.parametrize("loss", ["missing", "incomplete", "invalid"])
def test_optional_series_loss_is_not_primary_hazard_loss(variable, loss):
    _, summary = assess([city()], [observation(variable=variable, loss=loss)])
    assert availability.source_status(summary) == "success"
    assert all(lane["complete"] == 1 for lane in summary["hazards"].values())


@pytest.mark.parametrize("disabled", ["pm25", "dust", "both"])
def test_disabled_lanes_do_not_count_as_missing_or_fetch_when_both_off(monkeypatch, disabled):
    for lane in ("pm25", "dust"):
        if disabled in (lane, "both"):
            monkeypatch.setenv(f"THEHEAT_AQ_{lane.upper()}_ENABLED", "0")
    unavailable = "pm2_5" if disabled == "pm25" else "dust"
    state, current, fetch = run(monkeypatch, [city()], [observation(variable=unavailable, loss="missing")])
    entry = current["sources"][0]
    assert entry["status"] == ("skipped" if disabled == "both" else "success")
    assert fetch.call_count == (0 if disabled == "both" else 1)
    assert entry["details"]["failed_cities"] == 0
    for key, lane in entry["details"]["aq_availability"]["hazards"].items():
        if disabled in (key, "both"):
            assert lane["status"] == "disabled" and lane["coverage"] is None
            assert lane["requested"] == sum(lane[k] for k in COUNTS) == 0
    assert not state.get("_triage_queue")


def test_only_disabled_data_does_not_establish_enabled_coverage():
    qualified, summary = assess([city()], [observation(variable="pm2_5", loss="missing")], dust=False)
    assert qualified == [None] and summary["observed_cities"] == 0
    assert summary["hazards"]["pm25"]["missing"] == 1
    assert availability.source_status(summary) == "failed"


def test_empty_configuration_is_skipped_without_fetch(monkeypatch):
    state, current, fetch = run(monkeypatch, [], [])
    fetch.assert_not_called()
    entry = current["sources"][0]
    assert entry["status"] == "skipped" and entry["observed"] == 0
    assert entry["details"]["aq_availability"]["result_shape"] == "not_requested"
    assert state["source_health"]["air_quality"]["skipped"] == 1


@pytest.mark.parametrize("results,shape,received", [([], "mismatch", 0), ([None, None], "mismatch", 2),
    (None, "invalid", None), ({}, "invalid", None), ((None,), "invalid", None)])
def test_wrong_positional_cardinality_cannot_be_partially_paired(results, shape, received):
    qualified, summary = assess([city()], results)
    assert qualified == [None] and availability.source_status(summary) == "failed"
    assert summary["result_shape"] == shape and summary["received_slots"] == received
    assert all(lane["unavailable_window"] == 1 for lane in summary["hazards"].values())


@pytest.mark.parametrize("count", [1, 3])
def test_even_good_positional_results_require_exact_cardinality(monkeypatch, count):
    state, current, _ = run(monkeypatch, [city(0), city(1)], [observation(i, pm25=250.) for i in range(count)])
    entry = current["sources"][0]
    assert entry["status"] == "failed" and entry["observed"] == 0
    assert entry["details"]["failed_cities"] == 2 and not state.get("_triage_queue")


@pytest.mark.parametrize("field,value", [("city", "Other"), ("country", "Other"), ("lat", 32.),
    ("lon", 75.), ("lat", True), ("lon", float("nan")), ("date", "2026-06-09"),
    ("pm25_24h_mean", 1.), ("dust_daily_max", 1.), ("pm10_24h_mean", 1.),
    ("aod_daily_max", 1.), ("us_aqi_daily_max", 1), ("pm25_24h_mean", False),
    ("pm25_24h_mean", "0"), ("dust_daily_max", float("inf")), ("forecast_window", None)])
def test_detached_projection_is_not_qualified(field, value):
    _, summary = assess([city()], [replace(observation(), **{field: value})])
    assert availability.source_status(summary) == "failed"
    assert summary["hazards"]["pm25"]["unavailable_window"] == 1


@pytest.mark.parametrize("bad", [None, {}, {**city(), "lat": True}, {**city(), "lat": "nan"},
    {**city(), "country": "Other"}, {**city(), "city": 1}])
def test_malformed_city_is_contained_and_cannot_erase_valid_neighbor(monkeypatch, bad):
    state, current, _ = run(monkeypatch, [bad, city(1)], [observation(0), observation(1)])
    entry = current["sources"][0]
    assert entry["status"] == "degraded" and entry["observed"] == 1
    assert entry["details"]["failed_cities"] == 1 and not state.get("_triage_queue")


def test_rehashed_wrong_place_packet_does_not_match_requested_slot():
    obs = observation()
    obs.forecast_window["requested_location"]["city"] = "Other"
    packet = obs.forecast_window
    packet["selected_record_sha256"] = hashlib.sha256(contract._encoded(
        {k: v for k, v in packet.items() if k != "selected_record_sha256"})).hexdigest()
    contract.validate_window(packet)  # Internally consistent is not request identity.
    _, summary = assess([city()], [replace(obs, city="Other")])
    assert availability.source_status(summary) == "failed"


@pytest.mark.parametrize("mutation", ["hash", "hours", "date", "oversized", "not_record"])
def test_malformed_selected_record_is_unavailable(mutation):
    obs = observation()
    if mutation == "not_record":
        obs = {"pm25_24h_mean": 0., "dust_daily_max": 0.}
    elif mutation == "hash":
        obs.forecast_window["selected_record_sha256"] = "0" * 64
    elif mutation == "hours":
        obs.forecast_window["hours"].pop()
    elif mutation == "date":
        obs.forecast_window["date"] = "2026-06-09"
    else:
        obs.forecast_window["extra"] = "x" * 33000
    _, summary = assess([city()], [obs])
    assert availability.source_status(summary) == "failed"


def test_none_and_complete_null_primaries_never_become_quiet_data(monkeypatch):
    assert observation(pm25=None, dust=None) is None
    state, current, _ = run(monkeypatch, [city()], [None])
    entry = current["sources"][0]
    assert entry["status"] == "failed" and entry["observed"] == 0
    summary = entry["details"]["aq_availability"]
    assert all(lane["unavailable_window"] == 1 for lane in summary["hazards"].values())
    assert not state.get("_triage_queue")


def test_durable_only_reporting_and_sentinel_remain_degraded(monkeypatch):
    state, current, _ = run(monkeypatch, [city()], [observation(variable="pm2_5", loss="missing")], current=False)
    assert current is None
    health = state["source_health"]["air_quality"]
    first = health["runs"][0]
    for offset in (1, 2):
        record_source_health(state, "air_quality", "degraded", first["error"],
                             timestamp=datetime.now(UTC) + timedelta(seconds=offset))
    verdict = classify_source("air_quality", state["source_health"]["air_quality"])
    assert verdict["category"] == "degraded" and verdict["error_class"] == "unknown"
    assert first.get("error_class") != "timeout"


@pytest.mark.parametrize("total", [401, 403, 404, 410, 429, 500, 503])
def test_city_counts_cannot_be_misclassified_as_http_errors(monkeypatch, total):
    state, current, _ = run(monkeypatch, [city(i) for i in range(total)], [None] * total)
    entry = current["sources"][0]
    assert entry["details"]["aq_availability"]["hazards"]["pm25"]["unavailable_window"] == total
    assert str(total) not in entry["error"]
    verdict = classify_source("air_quality", state["source_health"]["air_quality"])
    assert verdict["category"] == "failing" and verdict["error_class"] == "unknown"


@pytest.mark.parametrize("fallback", [False, True])
def test_real_source_result_reaches_existing_dashboard_projection_and_render(monkeypatch, fallback):
    state, current, _ = run(monkeypatch, [city()], [observation(variable="pm2_5", loss="missing")])
    state["run_history"] = [current]
    if fallback:
        state["source_health"] = {}
    script = """
      import {buildSourceHealthPayload} from './lib/source-health.js';
      import {SourceHealthContent} from './app/health/page.js';
      import {renderToStaticMarkup} from 'react-dom/server';
      import React from 'react';
      let input=''; for await (const chunk of process.stdin) input+=chunk;
      const result=buildSourceHealthPayload(JSON.parse(input));
      const markup=renderToStaticMarkup(React.createElement(SourceHealthContent,{...result,now:Date.now()}));
      console.log(JSON.stringify({source:result.sources[0],markup}));
    """
    result = subprocess.run(['node', '--input-type=module', '-e', script],
                            cwd=Path(__file__).resolve().parents[1] / 'dashboard',
                            input=json.dumps(state), capture_output=True, text=True, check=True, timeout=20)
    rendered = json.loads(result.stdout)
    assert rendered["source"]["health"] == "degraded"
    assert "PM2.5 unavailable: 0.0% complete (missing)" in rendered["markup"]
    assert "dust available: 100.0% complete" in rendered["markup"]
    assert "Invented City" not in rendered["markup"]


def test_candidate_retains_exact_evidence_and_waits_for_success_callback(monkeypatch):
    obs = observation(pm25=250.)
    packet = deepcopy(obs.forecast_window)
    state, current, _ = run(monkeypatch, [city()], [obs])
    assert current["sources"][0]["status"] == "success"
    candidate, = state["_triage_queue"]
    assert candidate.bundle.raw_signal_dump["forecast_window"] == packet
    assert not state["air_quality_pm25_tiers"]
    candidate.on_draft_success()
    assert len(state["air_quality_pm25_tiers"]) == 1


@pytest.mark.parametrize("coverage,expected", [(1 / 3000, "<0.1%"), (2999 / 3000, "<100%")])
def test_tiny_gaps_or_supply_are_not_rounded_into_complete_or_absent(coverage, expected):
    _, summary = assess([city()], [observation()])
    summary["hazards"]["pm25"]["coverage"] = coverage
    assert expected in availability.availability_note(summary)


def test_fetch_exception_does_not_invent_per_city_classifications(monkeypatch):
    from src.data.source_status import SourceFetchError
    fetch = Mock(side_effect=SourceFetchError("invented stale source"))
    monkeypatch.setattr(source, "fetch_batch_air_quality", fetch)
    state, current = deepcopy(DEFAULT_STATE), {"sources": []}
    run_air_quality(state, current, [city()])
    entry = current["sources"][0]
    assert entry["status"] == "failed" and entry["observed"] == 0
    assert "details" not in entry and not state.get("_triage_queue")
    fetch.assert_called_once()
