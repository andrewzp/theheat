from datetime import UTC, date, datetime
import os
import tempfile

import pytest

from src.data._freshness import assert_freshness
from src.data.source_status import SourceFetchError, assert_response_schema
from src.state import (
    DEFAULT_STATE,
    _merge_state,
    record_source_health,
)


def test_default_state_has_source_health():
    assert DEFAULT_STATE["source_health"] == {}


def test_record_source_health_adds_success_row():
    state = {"source_health": {}}

    record_source_health(
        state,
        "firms",
        "success",
        timestamp="2026-05-14T10:00:00Z",
    )

    health = state["source_health"]["firms"]
    assert health["success"] == 1
    assert health["degraded"] == 0
    assert health["failed"] == 0
    assert health["skipped"] == 0
    assert health["last_success_ts"] == "2026-05-14T10:00:00Z"
    assert health["last_error"] is None


def test_record_source_health_aggregates_multiple_statuses():
    state = {"source_health": {}}

    record_source_health(state, "ocean_sst", "success", timestamp="2026-05-12T10:00:00Z")
    record_source_health(state, "ocean_sst", "degraded", "shape warning", timestamp="2026-05-13T10:00:00Z")
    record_source_health(state, "ocean_sst", "failed", "not json", timestamp="2026-05-14T10:00:00Z")
    record_source_health(state, "ocean_sst", "skipped", timestamp="2026-05-14T14:00:00Z")

    health = state["source_health"]["ocean_sst"]
    assert health["success"] == 1
    assert health["degraded"] == 1
    assert health["failed"] == 1
    assert health["skipped"] == 1
    assert health["last_success_ts"] == "2026-05-12T10:00:00Z"
    assert health["last_error"] == "not json"
    assert health["last_error_ts"] == "2026-05-14T10:00:00Z"


def test_record_source_health_maps_partial_failure_to_degraded():
    state = {"source_health": {}}

    record_source_health(
        state,
        "auto_publish_due",
        "partial_failure",
        "rate limited",
        timestamp="2026-05-14T10:00:00Z",
    )

    health = state["source_health"]["auto_publish_due"]
    assert health["degraded"] == 1
    assert health["failed"] == 0
    assert health["last_error"] == "rate limited"


def test_record_source_health_prunes_older_than_rolling_seven_days():
    state = {"source_health": {}}

    record_source_health(state, "river_gauges", "success", timestamp="2026-05-01T10:00:00Z")
    record_source_health(state, "river_gauges", "failed", "old failure", timestamp="2026-05-06T09:59:59Z")
    record_source_health(state, "river_gauges", "success", timestamp="2026-05-13T10:00:00Z")

    health = state["source_health"]["river_gauges"]
    assert health["success"] == 1
    assert health["failed"] == 0
    assert [row["ts"] for row in health["runs"]] == ["2026-05-13T10:00:00Z"]


def test_record_source_health_keeps_tolerance_boundary():
    state = {"source_health": {}}

    record_source_health(state, "co2", "success", timestamp="2026-05-07T10:00:00Z")
    record_source_health(state, "co2", "success", timestamp="2026-05-14T10:00:00Z")

    health = state["source_health"]["co2"]
    assert health["success"] == 2
    assert [row["ts"] for row in health["runs"]] == [
        "2026-05-07T10:00:00Z",
        "2026-05-14T10:00:00Z",
    ]


def test_merge_state_merges_source_health_runs():
    base = {"source_health": {}}
    incoming = {"source_health": {}}
    record_source_health(base, "firms", "success", timestamp="2026-05-13T10:00:00Z")
    record_source_health(incoming, "firms", "failed", "timeout", timestamp="2026-05-14T10:00:00Z")

    merged = _merge_state(base, incoming)

    health = merged["source_health"]["firms"]
    assert health["success"] == 1
    assert health["failed"] == 1
    assert health["last_error"] == "timeout"


def test_sqlite_round_trip_preserves_source_health():
    from src.storage import sqlite_store

    state = {"source_health": {}}
    record_source_health(state, "firms", "success", timestamp="2026-05-14T10:00:00Z")
    record_source_health(state, "ocean_sst", "failed", "not json", timestamp="2026-05-14T10:01:00Z")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "theheat.sqlite")
        assert sqlite_store.write_state(db_path, state)
        out = sqlite_store.read_state(db_path, DEFAULT_STATE)

    assert out["source_health"]["firms"]["success"] == 1
    assert out["source_health"]["ocean_sst"]["failed"] == 1
    assert out["source_health"]["ocean_sst"]["last_error"] == "not json"


def test_record_source_run_writes_health_and_run_row():
    from src.main import _record_source_run

    bot_state = {"source_health": {}}
    run = {"sources": []}

    _record_source_run(
        run,
        bot_state,
        "open_meteo_extreme_signals",
        0,
        status="degraded",
        note="provider:ghcn diff_dates_missing:1",
    )

    assert run["sources"][0]["source"] == "open_meteo_extreme_signals"
    health = bot_state["source_health"]["open_meteo_extreme_signals"]
    assert health["degraded"] == 1
    assert health["last_error"] == "provider:ghcn diff_dates_missing:1"


def test_assert_response_schema_valid_payload_passes():
    assert_response_schema({"temps_jra55": [], "extra": True}, ["temps_jra55"], "ocean_sst")


def test_assert_response_schema_extra_fields_do_not_fail():
    assert_response_schema({"required": 1, "new_optional": 2}, ["required"], "test_source")


def test_assert_response_schema_missing_field_names_source_and_keys():
    with pytest.raises(SourceFetchError) as excinfo:
        assert_response_schema({"temps": []}, ["temps_jra55", "metadata"], "ocean_sst")

    message = str(excinfo.value)
    assert "ocean_sst schema drift" in message
    assert "temps_jra55" in message
    assert "metadata" in message


def test_assert_response_schema_non_mapping_fails():
    with pytest.raises(SourceFetchError) as excinfo:
        assert_response_schema([], ["items"], "river_gauges")

    assert "expected JSON object" in str(excinfo.value)


def test_assert_freshness_accepts_fresh_date():
    assert_freshness(date(2026, 5, 13), "co2", 2, today=date(2026, 5, 14))


def test_assert_freshness_accepts_boundary_age():
    assert_freshness("2026-05-07", "sea_ice", 7, today=date(2026, 5, 14))


def test_assert_freshness_rejects_stale_date():
    with pytest.raises(SourceFetchError) as excinfo:
        assert_freshness(date(2026, 5, 1), "co2", 7, today=date(2026, 5, 14))

    assert "co2 stale data" in str(excinfo.value)
    assert "13 days old" in str(excinfo.value)


def test_assert_freshness_accepts_datetime():
    assert_freshness(
        datetime(2026, 5, 14, 1, 2, tzinfo=UTC),
        "firms",
        0,
        today=date(2026, 5, 14),
    )
