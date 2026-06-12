from __future__ import annotations

from datetime import date

from src.data.fire_footprint import FireComplex


def _complex() -> FireComplex:
    return FireComplex(
        complex_id="NIFC-2026-OR-001",
        name="Juniper Ridge Complex",
        country="US",
        region="OR",
        hectares=125_000.0,
        start_date=date(2026, 6, 1),
        tier=2,
        event_id="fire_footprint_NIFC-2026-OR-001_tier2",
    )


def test_nifc_success_enqueues_fire_footprint_candidate(fresh_state, monkeypatch):
    from src.orchestrator.sources import nifc

    monkeypatch.setattr(nifc, "_fetch_strict", lambda *args, **kwargs: [_complex()])
    monkeypatch.setattr(nifc.fire_footprint, "detect_tier_crossings", lambda complexes, state: [_complex()])
    monkeypatch.setattr(nifc, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    nifc.run_fire_footprint(fresh_state, current_run)

    queue = fresh_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "fire_footprint_NIFC-2026-OR-001_tier2"
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


def test_nifc_dedup_short_circuits_candidate(fresh_state, monkeypatch):
    from src.orchestrator.sources import nifc

    fresh_state["posted_events"] = ["fire_footprint_NIFC-2026-OR-001_tier2"]
    monkeypatch.setattr(nifc, "_fetch_strict", lambda *args, **kwargs: [_complex()])
    monkeypatch.setattr(nifc.fire_footprint, "detect_tier_crossings", lambda complexes, state: [_complex()])
    monkeypatch.setattr(nifc, "_should_draft", lambda score, event_id: True)

    current_run = {"sources": []}
    nifc.run_fire_footprint(fresh_state, current_run)

    assert fresh_state.get("_triage_queue", []) == []
    source_entry = next(row for row in current_run["sources"] if row["source"] == "fire_footprint")
    assert source_entry["status"] == "success"
    assert source_entry["promoted"] == 0
