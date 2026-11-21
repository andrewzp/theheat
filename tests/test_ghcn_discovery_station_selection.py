"""Finite documented station requests; invented replies never qualify observations."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from unittest.mock import patch

import pytest
import requests

from src.data import ghcn_discovery as discovery
from tests.test_ghcn_discovery_hints import API, Reply, TARGET, hint, invoke, known_cache

DAY = date(2026, 11, 21)


def pool(size):
    return frozenset(f"SFX{number:08d}" for number in range(1, size + 1))


def fetch(eligible, *, now=None, rows=(), cached=None):
    calls = []
    reply = Reply(json.dumps(list(rows)).encode())

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return reply

    clock = {} if now is None else {"now": now}
    with patch.object(discovery.requests, "get", get):
        result = discovery.fetch_nominations(eligible, cached or {}, today=DAY,
                                             max_age_days=4, anomaly=8, **clock)
    assert len(calls) == 1 and reply.closed == 1
    return result, calls[0]


def selected(call):
    url, kwargs = call
    assert url == API
    return kwargs["params"]["stations"].split(",")


def test_actual_collector_sends_exact_station_and_original_archive_still_owns_facts(tmp_path):
    (bundles, _), metrics, calls, _ = invoke(tmp_path, hint_value=49)
    url, kwargs = next(call for call in calls if call[0] == API)
    assert url == API and kwargs["params"]["stations"] == TARGET
    assert len(calls) == 33  # thirty original diff requests, one lookup, two archives
    target = next(bundle for bundle in bundles if bundle.station_id == TARGET)
    assert target.all_time_high.new_temp_c == 33  # 49 nominates; the archive owns 33
    assert metrics["station_discovery"]["station_selection"]["selected_stations"] == 1
    assert metrics["archive_verification_attempted"] == 2


def test_implicit_midnight_is_deterministic_and_queries_only_exact_eligible_ids():
    (_, metadata), call = fetch(frozenset({TARGET}))
    assert selected(call) == [TARGET]
    assert metadata["station_selection"]["bucket_start"] == "2026-11-21T00:00:00Z"
    assert metadata["station_selection"]["unselected_stations"] == 0
    assert metadata["station_selection"]["coverage_guaranteed"] is False


@pytest.mark.parametrize("size", [1, 499, 500, 501, 12522])
def test_large_pool_never_expands_the_single_request_or_internal_uri_bound(size):
    (_, metadata), call = fetch(pool(size))
    ids = selected(call)
    uri = requests.Request("GET", call[0], params=call[1]["params"]).prepare().url
    assert uri is not None and len(uri.encode("ascii")) <= 8192
    assert 0 < len(ids) <= 500 and len(ids) == len(set(ids))
    assert set(ids) <= pool(size)
    scope = metadata["station_selection"]
    assert scope["eligible_stations"] == size
    assert scope["selected_stations"] == len(ids)
    assert scope["unselected_stations"] == size - len(ids)
    assert scope["request_uri_bytes"] == len(uri.encode("ascii"))
    assert metadata["get_calls"] == metadata["max_get_calls"] == 1
    assert scope["selection_sha256"] == hashlib.sha256("\n".join(ids).encode()).hexdigest()


def test_stable_pool_is_visited_once_per_cycle_without_order_or_repeat_bias():
    eligible = pool(1001)
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    chunks = []
    for offset in range(3):
        stamp = (now + timedelta(hours=4 * offset)).isoformat()
        (_, meta), call = fetch(eligible, now=stamp)
        (_, repeat), again = fetch(frozenset(reversed(sorted(eligible))), now=stamp)
        assert call[0] == again[0] and call[1]["params"] == again[1]["params"] and meta == repeat
        chunks.append(set(selected(call)))
    assert set.union(*chunks) == eligible
    assert all(not chunks[i] & chunks[j] for i in range(3) for j in range(i))
    assert sorted(map(len, chunks)) == [1, 500, 500]


def test_same_four_hour_bucket_is_stable_and_next_bucket_advances_across_midnight():
    eligible = pool(1001)
    (_, a), first = fetch(eligible, now="2026-11-21T00:00:00Z")
    (_, b), second = fetch(eligible, now="2026-11-21T03:59:59Z")
    assert a == b and first[0] == second[0] and first[1]["params"] == second[1]["params"]
    (_, before), last = fetch(eligible, now="2026-11-21T23:59:59Z")
    with patch.object(discovery, "date", date):
        calls = []
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return Reply(b"[]")
        with patch.object(discovery.requests, "get", get):
            _, after = discovery.fetch_nominations(eligible, {}, today=DAY + timedelta(days=1),
                max_age_days=4, anomaly=8, now="2026-11-22T00:00:00Z")
    assert not set(selected(last)) & set(selected(calls[0]))
    assert before["station_selection"]["bucket_start"] == "2026-11-21T20:00:00Z"
    assert after["station_selection"]["bucket_start"] == "2026-11-22T00:00:00Z"


def test_unrequested_high_value_is_not_a_nomination_even_when_eligible_and_cached():
    eligible = pool(501)
    _, call = fetch(eligible, now="2026-11-21T00:00:00Z")
    requested = selected(call)
    outside = next(iter(eligible - set(requested)))
    cache = {sid: known_cache()[TARGET] for sid in (requested[0], outside)}
    (nominees, meta), _ = fetch(eligible, now="2026-11-21T00:00:00Z",
                              rows=[hint(station=requested[0]), hint(station=outside)], cached=cache)
    assert nominees == {requested[0]} and meta["nominated_stations"] == 1


@pytest.mark.parametrize("now", ["", "not-a-date", "2026-11-21T00:00:00",
    "2026-11-20T23:59:59Z", "2026-11-22T00:00:00Z", 42, True])
def test_invalid_clock_refuses_before_egress(now):
    with patch.object(discovery.requests, "get", side_effect=AssertionError("No send allowed")):
        with pytest.raises(ValueError, match="unsupported_discovery_clock"):
            discovery.fetch_nominations(frozenset({TARGET}), {}, today=DAY,
                                       max_age_days=4, anomaly=8, now=now)


def test_uri_limit_is_an_actual_before_send_guard(monkeypatch):
    monkeypatch.setattr(discovery, "MAX_REQUEST_URI_BYTES", 100)
    with patch.object(discovery.requests, "get", side_effect=AssertionError("No send allowed")):
        with pytest.raises(ValueError, match="discovery_request_uri_limit"):
            discovery.fetch_nominations(pool(500), {}, today=DAY, max_age_days=4, anomaly=8)
