from __future__ import annotations

from src.data.water_levels import StormSurgeEvent, WaterLevelReading


def _reading() -> WaterLevelReading:
    return WaterLevelReading(
        station_name="The Battery, NY",
        state="NY",
        station_id="8518750",
        observed_m=2.1,
        predicted_m=1.2,
        anomaly_m=0.9,
        date="2026-06-12",
        event_id="water_8518750_2026-06-12",
    )


def _event() -> StormSurgeEvent:
    return StormSurgeEvent(
        station_name="The Battery, NY",
        state="NY",
        anomaly_m=0.9,
        observed_m=2.1,
        predicted_m=1.2,
        date="2026-06-12",
        event_id="surge_notable_8518750_2026-06-12",
    )


def test_co_ops_success_enqueues_storm_surge_candidate(fresh_state, monkeypatch):
    from src.orchestrator.sources import co_ops

    monkeypatch.setattr(co_ops, "_fetch_strict", lambda *args, **kwargs: [_reading()])
    monkeypatch.setattr(co_ops.water_levels, "detect_storm_surge", lambda readings: [_event()])
    monkeypatch.setattr(co_ops, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    co_ops.run_water_levels(fresh_state, current_run)

    queue = fresh_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "surge_notable_8518750_2026-06-12"
    assert queue[0].legacy_type == "storm_surge"
    assert queue[0].source == "water_levels"
    source_entry = next(row for row in current_run["sources"] if row["source"] == "water_levels")
    assert source_entry["status"] == "success"
    assert source_entry["observed"] == 1
    assert source_entry["promoted"] == 1


def test_co_ops_failure_records_failed_and_cycle_continues(fresh_state, monkeypatch):
    from src.orchestrator.sources import co_ops

    monkeypatch.setattr(co_ops, "_fetch_strict", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("coops down")))

    current_run = {"sources": []}
    co_ops.run_water_levels(fresh_state, current_run)

    source_entry = next(row for row in current_run["sources"] if row["source"] == "water_levels")
    assert source_entry["status"] == "failed"
    assert "coops down" in source_entry["error"]
    assert any(error["source"] == "water_levels" for error in fresh_state["errors"])


def test_co_ops_dedup_short_circuits_candidate(fresh_state, monkeypatch):
    from src.orchestrator.sources import co_ops

    fresh_state["posted_events"] = ["surge_notable_8518750_2026-06-12"]
    monkeypatch.setattr(co_ops, "_fetch_strict", lambda *args, **kwargs: [_reading()])
    monkeypatch.setattr(co_ops.water_levels, "detect_storm_surge", lambda readings: [_event()])
    monkeypatch.setattr(co_ops, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    co_ops.run_water_levels(fresh_state, current_run)

    assert fresh_state.get("_triage_queue", []) == []
    source_entry = next(row for row in current_run["sources"] if row["source"] == "water_levels")
    assert source_entry["status"] == "success"
    assert source_entry["promoted"] == 0
