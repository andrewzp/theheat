from __future__ import annotations

from src.data.ocean import ExtremeWaveEvent, OceanReading


def _reading() -> OceanReading:
    return OceanReading(
        location="Gulf of Mexico",
        ocean="Atlantic",
        lat=28.5,
        lon=-88.0,
        wave_height_max_m=11.2,
        sst_c=None,
        date="2026-06-12",
        event_id="ocean_gulf_of_mexico_2026-06-12",
    )


def _event() -> ExtremeWaveEvent:
    return ExtremeWaveEvent(
        location="Gulf of Mexico",
        ocean="Atlantic",
        wave_height_m=11.2,
        date="2026-06-12",
        event_id="extreme_wave_gulf_of_mexico_2026-06-12",
    )


def test_marine_success_enqueues_extreme_wave_candidate(fresh_state, monkeypatch):
    from src.orchestrator.sources import marine

    monkeypatch.setattr(marine, "_fetch_strict", lambda *args, **kwargs: [_reading()])
    monkeypatch.setattr(marine.ocean, "detect_extreme_waves", lambda readings: [_event()])
    monkeypatch.setattr(marine, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    marine.run_ocean(fresh_state, current_run)

    queue = fresh_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "extreme_wave_gulf_of_mexico_2026-06-12"
    assert queue[0].legacy_type == "extreme_wave"
    assert queue[0].source == "ocean"
    source_entry = next(row for row in current_run["sources"] if row["source"] == "ocean")
    assert source_entry["status"] == "success"
    assert source_entry["observed"] == 1
    assert source_entry["promoted"] == 1


def test_marine_failure_records_failed_and_cycle_continues(fresh_state, monkeypatch):
    from src.orchestrator.sources import marine

    monkeypatch.setattr(marine, "_fetch_strict", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("marine down")))

    current_run = {"sources": []}
    marine.run_ocean(fresh_state, current_run)

    source_entry = next(row for row in current_run["sources"] if row["source"] == "ocean")
    assert source_entry["status"] == "failed"
    assert "marine down" in source_entry["error"]
    assert any(error["source"] == "ocean" for error in fresh_state["errors"])


def test_marine_dedup_short_circuits_candidate(fresh_state, monkeypatch):
    from src.orchestrator.sources import marine

    fresh_state["posted_events"] = ["extreme_wave_gulf_of_mexico_2026-06-12"]
    monkeypatch.setattr(marine, "_fetch_strict", lambda *args, **kwargs: [_reading()])
    monkeypatch.setattr(marine.ocean, "detect_extreme_waves", lambda readings: [_event()])
    monkeypatch.setattr(marine, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    marine.run_ocean(fresh_state, current_run)

    assert fresh_state.get("_triage_queue", []) == []
    source_entry = next(row for row in current_run["sources"] if row["source"] == "ocean")
    assert source_entry["status"] == "success"
    assert source_entry["promoted"] == 0
