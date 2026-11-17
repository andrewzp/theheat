"""Invented rolling metadata through real state merge/persistence; no live I/O."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
import json

from freezegun import freeze_time
import pytest

from src import state
from tests import live_content_harness as h

NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)
WINDOWS = [("candidates_log", "date", 7), ("coverage_log", "date", 21), ("news_events", "window_end", 7)]


def row(label, field, value):
    return {"event_id": label, "kind": label, "headline": label, "window_start": "2026-06-01", field: value}


def snapshot():
    value = state._fresh_state()
    for key, field, days in WINDOWS:
        cutoff = (NOW - timedelta(days=days)).date()
        value[key] = [row("expired", field, (cutoff - timedelta(days=1)).isoformat()),
                      row("boundary", field, cutoff.isoformat()), row("current", field, NOW.date().isoformat())]
    value["run_history"] = [{"id": "invented-completed", "mode": "alerts", "status": "success",
                             "started_at": "2026-07-01T11:55:00Z", "ended_at": "2026-07-01T12:00:00Z"}]
    value["drafts"] = [{"id": "invented-pending", "status": "pending", "text": "Invented retained text",
                         "review_context": {"retained": "evidence"}}]
    value["publish_ledger"] = {"held": {"phase": "unknown", "attempt": "invented-no-resend"}}
    value["last_hot10"] = {"keep": ["all", "bytes", 0, False, None]}
    return value


def ids(rows):
    return [r["event_id"] for r in rows]


@pytest.mark.parametrize("key,field,days", WINDOWS)
def test_real_gist_merge_cannot_restore_expired_rows_from_a_stale_snapshot(monkeypatch, key, field, days):
    current = snapshot()
    incoming = deepcopy(current)
    # The existing producer has already pruned its local rolling list.
    incoming[key] = incoming[key][1:]
    transport = h.Transport(gist={"state.json": json.dumps(current)})
    transport.install(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "gist")
    monkeypatch.setenv("THEHEAT_GIST_WRITE_ROUTE", "legacy")
    monkeypatch.setattr(state, "GIST_ID", h.GIST_ID)
    monkeypatch.setattr(state, "GITHUB_TOKEN", "invented-no-access")
    with freeze_time(NOW):
        assert state.write_state(incoming)
        first = json.loads(transport.gist["state.json"])
        assert ids(first[key]) == ["boundary", "current"]
        stale = deepcopy(current)
        stale[key].append(row("concurrent", field, NOW.date().isoformat()))
        assert state.write_state(json.loads(json.dumps(stale)))
    saved = json.loads(transport.gist["state.json"])
    assert ids(saved[key]) == ["boundary", "current", "concurrent"]
    assert transport.gist_patches == 2 and transport.x_posts == []
    assert saved["publish_ledger"] == current["publish_ledger"]
    assert saved["drafts"] == current["drafts"]
    assert saved["last_hot10"] == current["last_hot10"]
    assert ids(current[key]) == ["expired", "boundary", "current"]


@pytest.mark.parametrize("key,field,days", WINDOWS)
def test_an_empty_completed_cycle_expires_metadata_at_the_existing_inclusive_window(key, field, days):
    value = snapshot()
    state.prune_state(value, NOW)
    assert ids(value[key]) == ["boundary", "current"]
    # A stale merge must apply the same completed-run watermark afterwards.
    with freeze_time(NOW):
        saved = state._prepare_merged_write(snapshot(), value)
    assert ids(saved[key]) == ["boundary", "current"]


@pytest.mark.parametrize("key,field,days", WINDOWS)
def test_unknown_malformed_and_future_dates_are_not_size_trimmed(key, field, days):
    value = snapshot()
    extra = [row("missing", field, None), row("malformed", field, "2026-02-30"),
             row("noncanonical", field, "20260101"), row("future", field, "2099-01-01"),
             row("wrong_type", field, False)]
    value[key] += deepcopy(extra)
    state.prune_state(value, NOW)
    assert value[key][2:] == extra
    assert ids(value[key])[:2] == ["boundary", "current"]


@pytest.mark.parametrize("clock", [None, "broken", "2026-07-01T12:00:00", "2099-01-01T00:00:00Z"])
def test_no_valid_completed_clock_preserves_a_historical_import(clock):
    value = snapshot()
    value["run_history"] = [] if clock is None else [{"id": "unusable", "status": "success",
        "started_at": "2026-07-01T11:55:00Z", "ended_at": clock}]
    with freeze_time(NOW):
        merged = state._prepare_merged_write(value, deepcopy(value))
    for key, _, _ in WINDOWS:
        assert merged[key] == value[key]


def test_historical_restore_uses_its_completion_clock_not_todays_wall_clock():
    value = snapshot()
    with freeze_time(NOW + timedelta(days=90)):
        merged = state._prepare_merged_write(value, deepcopy(value))
    for key, _, _ in WINDOWS:
        assert ids(merged[key]) == ["boundary", "current"]


def test_only_the_three_rolling_namespaces_and_existing_revision_counter_change():
    current = snapshot()
    incoming = deepcopy(current)
    with freeze_time(NOW):
        baseline = state._merge_state(current, incoming)
        saved = state._prepare_merged_write(current, incoming)
    for key in set(saved) | set(baseline):
        if key not in {"candidates_log", "coverage_log", "news_events", "_state_rev"}:
            assert saved[key] == baseline[key], key
    assert saved["_state_rev"] == 1


def test_a_contradictory_or_configuration_only_run_cannot_supply_a_pruning_clock():
    value = snapshot()
    value["run_history"][0]["started_at"] = "2026-07-02T00:00:00Z"
    value["run_history"].append({**snapshot()["run_history"][0], "id": "configuration",
                                  "configuration_only": True})
    with freeze_time(NOW):
        merged = state._prepare_merged_write(value, deepcopy(value))
    for key, _, _ in WINDOWS:
        assert merged[key] == value[key]


@pytest.mark.parametrize("status", ["success", "partial_failure", "failed"])
def test_completed_failed_or_partial_collection_still_maintains_metadata(status):
    value = snapshot()
    value["run_history"][0]["status"] = status
    with freeze_time(NOW):
        merged = state._prepare_merged_write(value, deepcopy(value))
    assert ids(merged["candidates_log"]) == ["boundary", "current"]


@pytest.mark.parametrize("status", ["in_progress", None])
def test_uncompleted_status_conveys_no_maintenance_clock(status):
    value = snapshot()
    value["run_history"][0]["status"] = status
    with freeze_time(NOW):
        merged = state._prepare_merged_write(value, deepcopy(value))
    assert merged["candidates_log"] == value["candidates_log"]


def test_latest_current_completion_wins_over_a_stale_writers_clock():
    current, stale = snapshot(), snapshot()
    stale["run_history"][0].update(id="older", started_at="2026-06-29T11:00:00Z",
                                    ended_at="2026-06-29T12:00:00Z")
    with freeze_time(NOW):
        merged = state._prepare_merged_write(current, stale)
    assert ids(merged["candidates_log"]) == ["boundary", "current"]


def test_supplied_completion_clock_uses_utc_day_across_timezone_boundary():
    value = snapshot()
    local = datetime(2026, 6, 30, 23, 30, tzinfo=timezone(timedelta(hours=-2)))
    state.prune_state(value, local)
    assert ids(value["candidates_log"]) == ["boundary", "current"]


def test_real_empty_finalize_path_expires_metadata_without_a_new_candidate():
    value = snapshot()
    with freeze_time(NOW):
        state.finalize_run(value, {"id": "empty", "mode": "auto_publish_due",
                                  "started_at": "2026-07-01T11:59:59Z", "sources": []})
    for key, _, _ in WINDOWS:
        assert ids(value[key]) == ["boundary", "current"]


def test_stale_draft_guard_still_refuses_before_any_patch(monkeypatch):
    value = snapshot()
    transport = h.Transport(gist={"state.json": json.dumps(value)})
    transport.install(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "gist")
    monkeypatch.setenv("THEHEAT_GIST_WRITE_ROUTE", "legacy")
    monkeypatch.setattr(state, "GIST_ID", h.GIST_ID)
    monkeypatch.setattr(state, "GITHUB_TOKEN", "invented-no-access")
    stale = {**value["drafts"][0], "text": "Different invented decision"}
    with freeze_time(NOW):
        assert state.write_state(value, expected_draft=stale) is False
    assert transport.gist_patches == 0
    assert json.loads(transport.gist["state.json"]) == value
