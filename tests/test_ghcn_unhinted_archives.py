"""An unavailable lookup may not permanently confine current archive intake.

All source responses, stations and dates here are invented. Actual collector,
cache, DLY/QC/history and selection consumers run; no SDK or network is used.
"""
from datetime import date
from dataclasses import replace
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from dashboard.tests.fixtures.ghcn_archive_intake_producer import archive_bytes
from tests.test_ghcn_discovery_hints import API, DAY, METADATA, SID, TARGET, invoke
from src.data import ghcn


ERROR = json.dumps({"errorCode": 400, "errorMessage": "Bad Request", "errors": [
    {"field": "stations", "message": "Invented station selection refused", "value": "not retained"},
]}).encode()


def archive_calls(calls):
    return [url for url, _ in calls if "/all/" in url and url.endswith(".dly")]


def test_rejected_lookup_still_checks_untracked_original_archive_and_uses_only_its_values(tmp_path):
    (bundles, _), metrics, calls, response = invoke(tmp_path, hint_status=400, hint_body=ERROR)
    found = [b for b in bundles if b.station_id == TARGET]
    assert len(found) == 1, "A failed lookup must not permanently exclude an active cached station from archive intake"
    b = found[0]
    assert b.signal_date == DAY and b.country == "South Africa"
    assert b.all_time_high.new_temp_c == 33 and b.all_time_low.new_temp_c == -15
    assert b.evidence["variables"]["TMAX"]["source_payload_sha256"] == sha256(archive_bytes(station=TARGET)).hexdigest()
    assert metrics["station_discovery"]["status"] == "unavailable"
    assert metrics["station_discovery"]["http_status"] == 400
    assert metrics["station_discovery"]["nominated_stations"] == 0
    assert metrics["station_archive_intake"]["schema_version"] == 3
    assert metrics["station_archive_intake"]["scope"] == "verified_unhinted_station_archive_sample"
    assert metrics["station_archive_intake"]["sampling_source"] == "cached_active_stations_after_lookup_400"
    assert metrics["station_archive_intake"]["sampling_pool_stations"] == 1
    assert len(archive_calls(calls)) == 2 and len(calls) == 33
    assert sum(url == API for url, _ in calls) == 1 and response.closed == 1


def test_rejected_lookup_populates_existing_lane_without_exceeding_total_archive_allowance(tmp_path):
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR, extra_stations=40)
    archives = archive_calls(calls)
    assert len(archives) == len(set(archives)) == 20
    assert any(url.endswith(f"/{SID}.dly") for url in archives)
    assert metrics["archive_selection"]["tracked"]["selected_stations"] == 1
    assert metrics["archive_selection"]["candidates"]["selected_stations"] == 19
    assert metrics["archive_selection"]["candidates"]["pool_stations"] == 41
    assert metrics["archive_verification_attempted"] == 20 and len(calls) == 51
    assert sum(url == API for url, _ in calls) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_other_failed_lookup_statuses_do_not_expand_original_archive_scope(tmp_path, status):
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=status, hint_body=ERROR)
    assert not any(url.endswith(f"/{TARGET}.dly") for url in archive_calls(calls))
    assert metrics["station_archive_intake"]["schema_version"] == 1


def test_rejected_lookup_with_no_cached_comparator_does_not_buy_unhinted_archive(tmp_path):
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR, missing_cached_baseline=True)
    assert not any(url.endswith(f"/{TARGET}.dly") for url in archive_calls(calls))
    assert metrics["station_archive_intake"]["schema_version"] == 1


@pytest.mark.parametrize("payload", [
    archive_bytes(station=TARGET, qflag="S"),
    archive_bytes(station=TARGET, target=date(2026, 11, 16)),
    archive_bytes(station=TARGET, target=date(2026, 11, 22)),
    archive_bytes(station=SID),
    b"invalid station archive",
    b"\n".join(row for row in archive_bytes(station=TARGET).splitlines() if row[11:15] >= b"2025"),
], ids=["qc", "old", "future", "wrong_station", "malformed", "thin_actual_history"])
def test_unhinted_sampling_never_overrides_actual_archive_refusals(tmp_path, payload):
    (bundles, _), _, calls, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR, payload=payload)
    assert not any(b.station_id == TARGET for b in bundles)
    assert len(archive_calls(calls)) <= 20


def test_zero_allowance_does_not_expand_any_request_scope(tmp_path):
    result, metrics, calls, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR, limit=0)
    assert result == ([], []) and metrics["archive_verification_attempted"] == 0
    assert len(calls) == 30 and not archive_calls(calls) and all(url != API for url, _ in calls)


@pytest.mark.parametrize("change", [
    {"all_time_max_c": float("nan"), "all_time_min_c": None},
    {"all_time_max_c": None, "all_time_min_c": float("inf")},
    {"all_time_max_c": True, "all_time_min_c": None},
    {"archive_years": 1},
    {"archive_years": True},
    {"station_id": SID},
])
def test_unusable_or_mismatched_cached_comparator_never_buys_sampling(tmp_path, monkeypatch, change):
    original = ghcn.load_thresholds

    def load(conn, sid):
        value = original(conn, sid)
        return replace(value, **change) if sid == TARGET and value is not None else value

    monkeypatch.setattr(ghcn, "load_thresholds", load)
    (_, _), metrics, calls, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR)
    assert not any(url.endswith(f"/{TARGET}.dly") for url in archive_calls(calls))
    assert metrics["station_archive_intake"]["schema_version"] == 1


def test_sampled_and_tracked_source_facts_both_exclude_provider_error(tmp_path):
    (bundles, _), metrics, _, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR,
                                        tracked_payload=archive_bytes())
    assert {b.station_id for b in bundles} == {SID, TARGET}
    assert metrics["station_discovery"]["nominated_stations"] == 0
    for bundle in bundles:
        evidence = json.dumps(bundle.evidence, sort_keys=True)
        assert "Invented station selection refused" not in evidence and "not retained" not in evidence
        assert bundle.all_time_high.new_temp_c == 33


def test_finite_but_wrong_cached_comparators_are_only_sampling_hints(tmp_path, monkeypatch):
    original = ghcn.load_thresholds

    def load(conn, sid):
        value = original(conn, sid)
        if sid == TARGET and value is not None:
            return replace(value, all_time_max_c=80.0, all_time_min_c=-80.0)
        return value

    monkeypatch.setattr(ghcn, "load_thresholds", load)
    (bundles, _), _, _, _ = invoke(tmp_path, hint_status=400, hint_body=ERROR)
    [bundle] = [b for b in bundles if b.station_id == TARGET]
    assert bundle.all_time_high.new_temp_c == 33
    assert bundle.all_time_low.new_temp_c == -15
    assert bundle.evidence["variables"]["TMAX"]["source_payload_sha256"] == sha256(archive_bytes(station=TARGET)).hexdigest()


def test_sample_selection_is_independent_of_station_input_order_and_same_bucket_retries(tmp_path):
    extra = [dict(METADATA[1], station_id=f"SFX{index:08d}") for index in range(3, 43)]
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    one = invoke(first, hint_status=400, hint_body=ERROR, extra_stations=40, stations=METADATA + extra)
    two = invoke(second, hint_status=400, hint_body=ERROR, extra_stations=40,
                 stations=list(reversed(METADATA + extra)))
    assert set(archive_calls(one[2])) == set(archive_calls(two[2]))
    assert one[1]["archive_selection"] == two[1]["archive_selection"]
    assert len(archive_calls(one[2])) == 20


def test_one_slot_still_alternates_between_existing_history_and_unhinted_sample(tmp_path, monkeypatch):
    from tests import test_ghcn_discovery_hints as fixture

    selected = set()
    for index, now in enumerate(["2026-11-21T12:00:00Z", "2026-11-21T16:00:00Z"]):
        root = tmp_path / str(index)
        root.mkdir()
        monkeypatch.setattr(fixture, "NOW", now)
        _, metrics, calls, _ = invoke(root, hint_status=400, hint_body=ERROR, limit=1)
        urls = archive_calls(calls)
        assert len(urls) == metrics["archive_verification_attempted"] == 1
        assert len(calls) == 32
        selected.update(url.rsplit("/", 1)[-1] for url in urls)
    assert selected == {SID + ".dly", TARGET + ".dly"}


def test_actual_sampled_source_queue_candidate_reaches_required_sdk_checks_and_pending_save(monkeypatch):
    import socket
    from freezegun import freeze_time
    from dashboard.tests.fixtures.ghcn_discovery_producer import produce
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    from src.state import DEFAULT_STATE
    from src.two_bot.ghcn_readable_warrant import decode_wire
    from tests.test_observed_copy_guard_journey import _models

    candidates = []
    produce("error400_sampled", candidates_out=candidates)
    assert len(candidates) == 1
    candidate = candidates[0]
    text = ("Invented New Station reached 33°C on 18 November, its archive high "
            "in the available GHCN archive through 2026-11-17.")
    models = _models(monkeypatch, copy=text)

    def forbidden(*args, **kwargs):
        raise AssertionError("Invented source and SDK journey forbids real network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    state = deepcopy(DEFAULT_STATE)
    result = {}
    with freeze_time("2026-11-21T12:00:00Z", tick=True):
        saved = _try_two_bot_draft(candidate.bundle, state, candidate.score,
            legacy_type=candidate.legacy_type, event_id=candidate.event_id,
            review_context=candidate.review_context, city=candidate.city,
            tweet_date=candidate.tweet_date, result_out=result)
    assert saved, result
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["text"] == text and draft["status"] == "pending"
    assert not draft.get("tweet_id") and not draft.get("posted_at")
    full = decode_wire(draft["review_context"]["two_bot"]["bundle"])
    assert full["raw_signal_dump"]["evidence"]["station_id"] == TARGET
    assert not state.get("publish_ledger")
