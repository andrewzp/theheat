from __future__ import annotations

from datetime import date

from freezegun import freeze_time

from src.data.fire_footprint import report_tracking_key
from tests.test_nifc_reported_area_consumer import NOW, acquire, capture as capture  # noqa: F401


def test_nifc_success_enqueues_fire_footprint_candidate(fresh_state, monkeypatch, capture):
    from src.orchestrator.sources import nifc

    fc, = acquire(capture)
    monkeypatch.setattr(nifc, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    with freeze_time(NOW):
        nifc.run_fire_footprint(fresh_state, current_run)

    queue = fresh_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == fc.event_id
    assert queue[0].legacy_type == "fire_footprint"
    assert queue[0].source == "fire_footprint"
    source_entry = next(row for row in current_run["sources"] if row["source"] == "fire_footprint")
    assert source_entry["status"] == "success"
    assert source_entry["observed"] == 1
    assert source_entry["promoted"] == 1


def test_nifc_failure_records_failed_and_cycle_continues(fresh_state, monkeypatch):
    from src.orchestrator.sources import nifc

    monkeypatch.setattr(nifc, "_fetch_strict", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("nifc down")))

    current_run = {"sources": []}
    nifc.run_fire_footprint(fresh_state, current_run)

    source_entry = next(row for row in current_run["sources"] if row["source"] == "fire_footprint")
    assert source_entry["status"] == "failed"
    assert "nifc down" in source_entry["error"]
    assert any(error["source"] == "fire_footprint" for error in fresh_state["errors"])


def test_nifc_skip_records_already_ran_today(fresh_state):
    from src.orchestrator.sources import nifc

    fresh_state["fire_footprint_last_run"] = date.today().isoformat()
    current_run = {"sources": []}

    nifc.run_fire_footprint(fresh_state, current_run)

    source_entry = next(row for row in current_run["sources"] if row["source"] == "fire_footprint")
    assert source_entry["status"] == "skipped"
    assert source_entry["note"] == "Already ran today"


def test_nifc_dedup_short_circuits_candidate(fresh_state, monkeypatch, capture):
    from src.orchestrator.sources import nifc

    fc, = acquire(capture)
    fresh_state["posted_events"] = [fc.event_id]
    fresh_state["fire_complex_tiers"][report_tracking_key(fc)] = fc.tier
    monkeypatch.setattr(nifc, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    with freeze_time(NOW):
        nifc.run_fire_footprint(fresh_state, current_run)

    assert fresh_state.get("_triage_queue", []) == []
    source_entry = next(row for row in current_run["sources"] if row["source"] == "fire_footprint")
    assert source_entry["status"] == "success"
    assert source_entry["promoted"] == 0
