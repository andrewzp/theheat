"""Bounded acquisition diagnostics, never a source/observation approval."""
from copy import deepcopy
from datetime import date
from unittest.mock import patch

import pytest
import requests

from dashboard.tests.fixtures.ghcn_fetch_producer import produce_fetch
from src.data import ghcn
from tests.ghcn_intake_cases import NOW, SID, TODAY, payloads

OUTCOMES = {"payload": "payload_returned", "404": "http_404", "401": "http_401", "403": "http_403",
            "429": "http_429", "503": "http_5xx", "timeout": "timeout", "connection": "connection_error"}


def metrics(state):
    details = state["run_history"][0]["sources"][0]["details"]
    return details.get("pipeline_metrics", details.get("ghcn_pipeline_metrics"))


@pytest.mark.parametrize("case,expected", OUTCOMES.items())
def test_real_source_carries_only_actual_fixed_fetch_counts_through_json(case, expected):
    state = produce_fetch(case)
    m = metrics(state)
    trace = m["diff_fetch"]
    assert trace["schema_version"] == 1 and trace["scope"] == "client_get_invocations"
    assert trace["window_day"] == "2026-11-21" and trace["target_count"] == 3
    assert set(trace) == {"schema_version", "scope", "window_day", "target_count", "get_calls", "counts", "started_at", "ended_at"}
    assert trace["started_at"] == trace["ended_at"] == NOW
    assert trace["get_calls"] == (3 if case == "payload" else 30)
    assert trace["counts"][expected] == trace["get_calls"]
    assert sum(trace["counts"].values()) == trace["get_calls"]
    assert trace["counts"]["payload_returned"] == m["diff_dates_fetched"]
    calls = [(url, kwargs) for url, kwargs in state["invented_transport_calls"] if "/superghcnd/" in url]
    assert len(calls) == trace["get_calls"] and all(kwargs == {"timeout": 60} for _, kwargs in calls)
    assert "invented-private-detail" not in str(trace) and "https://" not in str(trace)
    assert state["drafts"] == []


def test_combined_provider_keeps_the_same_source_scoped_acquisition_denominator():
    single, combined = produce_fetch("404"), produce_fetch("404", "both_global")
    assert metrics(single)["diff_fetch"] == metrics(combined)["diff_fetch"]
    assert metrics(single)["diff_dates_attempted"] == metrics(combined)["diff_dates_attempted"] == 3
    assert single["drafts"] == combined["drafts"] == []


def test_fetch_capture_does_not_change_retained_scientific_outcome():
    from src.storage.scientific_supply import _outcome
    m = metrics(produce_fetch("payload"))
    previous = deepcopy(m)
    previous.pop("diff_fetch")
    assert _outcome(m) == _outcome(previous)


def test_mixed_responses_preserve_the_existing_probe_order_timeout_and_returned_bytes():
    target = date(2026, 11, 20)
    urls = ghcn._diff_urls_for_end_date(target)
    effects = [404, 403, 429, 503, requests.ReadTimeout("invented"), requests.ConnectionError("invented"),
               requests.HTTPError("invented"), requests.RequestException("invented"), 418, 200]
    calls = []
    content = b"invented bytes are not certified NOAA data"

    def get(url, **kwargs):
        calls.append((url, kwargs))
        value = effects[len(calls) - 1]
        if isinstance(value, Exception):
            raise value
        response = requests.Response()
        response.status_code, response.url, response._content = value, url, content
        return response

    captured = {}
    with patch.object(ghcn.requests, "get", get):
        assert ghcn._fetch_diff(target, diagnostics_out=captured) == content
    assert calls == [(url, {"timeout": 60}) for url in urls]
    assert captured["get_calls"] == 10 and sum(captured["counts"].values()) == 10
    assert all(captured["counts"][name] == 1 for name in ("payload_returned", "http_404", "http_403", "http_429",
        "http_5xx", "timeout", "connection_error", "http_other_error", "request_error", "http_other_4xx"))


def test_replay_and_uninstrumented_custom_fetches_cannot_reuse_live_http_counts():
    from freezegun import freeze_time

    raw = payloads()
    stale = metrics(produce_fetch("404"))["diff_fetch"]

    class Replay:
        def diffs(self, dates):
            return {day: raw[day] for day in dates}

        def diff_time(self, day):
            return NOW

    for runtime in (None, Replay()):
        m = {"diff_fetch": deepcopy(stale)}
        with patch.object(ghcn, "_fetch_diff", lambda day, **_kwargs: raw[day]), freeze_time(NOW):
            values = ghcn._fetch_recent_obs(frozenset({SID}), today=TODAY, metrics_out=m, _runtime=runtime)
        assert values and "diff_fetch" not in m
        assert m["diff_intake"]["counts"]["final_station_days"] == 1


def test_unexpected_exception_is_not_converted_into_a_captured_http_result_or_a_retry():
    calls, diagnostics = [], {}

    def crash(url, **kwargs):
        calls.append(url)
        raise RuntimeError("invented process failure")

    with patch.object(ghcn.requests, "get", crash), pytest.raises(RuntimeError, match="invented process failure"):
        ghcn._fetch_diff(TODAY, diagnostics_out=diagnostics)
    assert len(calls) == 1 and diagnostics["get_calls"] == 1
    assert sum(diagnostics["counts"].values()) == 0


def test_failed_source_without_tracked_history_keeps_complete_acquisition_and_stays_failed():
    state = produce_fetch("404", tracked=False)
    row = state["run_history"][0]["sources"][0]
    assert row["status"] == "failed" and state["request_count"] == 30
    assert metrics(state)["diff_fetch"]["counts"]["http_404"] == 30
    assert state["drafts"] == []


def test_empty_public_collection_clears_prior_capture_and_preserves_unrelated_caller_fields(tmp_path):
    path = tmp_path / "existing.sqlite"
    path.touch()
    m = deepcopy(metrics(produce_fetch("payload")))
    m["caller_marker"] = {"retained": True}
    assert "diff_fetch" in m and "diff_intake" in m
    assert ghcn.check_extreme_signals_for_stations(stations=[], db_path=path, metrics_out=m) == ([], [])
    assert "diff_fetch" not in m and "diff_intake" not in m
    assert "diff_dates_attempted" not in m and "diff_dates_fetched" not in m
    assert m["caller_marker"] == {"retained": True} and m["stations_active"] == 0


def test_returned_invalid_bytes_keep_their_acquisition_but_never_become_valid_inputs():
    state = produce_fetch("invalid_payload", tracked=False)
    assert state["run_history"][0]["sources"][0]["status"] == "failed"
    assert metrics(state)["diff_fetch"]["counts"]["payload_returned"] == 3
    assert "diff_intake" not in metrics(state) and state["drafts"] == []
