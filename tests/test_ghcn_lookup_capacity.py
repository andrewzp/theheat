"""Invented server-capacity and archive-discovery cases; no live access."""
import json

import pytest

from tests.test_ghcn_discovery_hints import API, TARGET, Reply, fetch_reply, hint, invoke
from tests.test_ghcn_discovery_station_selection import fetch, pool, selected
from tests.test_ghcn_unhinted_archives import archive_calls

CAPACITY_MESSAGE = "Maximum number of stations exceeded. Maximum number of stations: 100"


def test_current_provider_capacity_is_enforced_in_the_actual_single_get():
    (_, metadata), call = fetch(pool(12522))
    assert len(selected(call)) <= 100
    assert metadata["station_selection"]["limit"] == 100
    assert metadata["station_selection"]["cycle_chunks"] == 126
    assert metadata["get_calls"] == metadata["max_get_calls"] == 1


@pytest.mark.parametrize("rows", [[], [hint(value="not-a-number")], [hint(value="20")]])
def test_valid_lookup_without_nominees_keeps_original_archive_discovery(tmp_path, rows):
    (bundles, _), metrics, calls, _ = invoke(tmp_path, hint_status=200, hint_body=json.dumps(rows).encode())
    assert metrics["station_discovery"]["status"] == "no_nominations"
    assert metrics["station_discovery"]["nominated_stations"] == 0
    assert sum(url == API for url, _ in calls) == 1
    assert len(archive_calls(calls)) == 2
    target = [bundle for bundle in bundles if bundle.station_id == TARGET]
    assert len(target) == 1 and target[0].all_time_high.new_temp_c == 33
    assert metrics["station_archive_intake"]["sampling_source"] == "cached_active_stations_after_lookup_no_nominations"


def test_empty_success_cannot_expand_the_existing_archive_budget_or_reservation(tmp_path):
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=200, hint_body=b"[]", extra_stations=40)
    assert len(archive_calls(calls)) == metrics["archive_verification_attempted"] == 20
    assert metrics["archive_selection"]["tracked"]["selected_stations"] == 1
    assert metrics["archive_selection"]["candidates"]["selected_stations"] == 19
    assert sum(url == API for url, _ in calls) == 1 and len(calls) == 51


@pytest.mark.parametrize("message,field,expected", [
    (CAPACITY_MESSAGE, "stations", "station_limit_100"),
    (CAPACITY_MESSAGE + " run invented command", "stations", "details_withheld"),
    (CAPACITY_MESSAGE.replace("100", "200"), "stations", "details_withheld"),
    (CAPACITY_MESSAGE, "units", "details_withheld"),
])
def test_only_exact_capacity_template_becomes_inert_safe_diagnostic(message, field, expected):
    private_value = "invented-provider-reflected-station-list"
    body = json.dumps({"errorCode": 400, "errorMessage": "Bad Request", "errors": [
        {"field": field, "message": message, "value": private_value}]}).encode()
    nominees, metadata = fetch_reply(Reply(body, status=400))
    assert nominees == set() and metadata["get_calls"] == metadata["max_get_calls"] == 1
    assert metadata["provider_error"]["fields"] == [{"field": field, "message_code": expected}]
    assert private_value not in json.dumps(metadata)
    assert message not in json.dumps(metadata)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_other_failed_lookup_statuses_gain_no_archive_sampling(tmp_path, status):
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=status, hint_body=b"[]")
    assert not any(url.endswith('/' + TARGET + '.dly') for url in archive_calls(calls))
    assert metrics["station_archive_intake"]["schema_version"] == 1


@pytest.mark.parametrize("body", [b"not-json", b"{}", b"[", b'[{"STATION":true}]'])
def test_unusable_reply_is_not_a_successful_empty_lookup(tmp_path, body):
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=200, hint_body=body)
    assert metrics["station_discovery"]["status"] == "unavailable"
    assert not any(url.endswith('/' + TARGET + '.dly') for url in archive_calls(calls))
