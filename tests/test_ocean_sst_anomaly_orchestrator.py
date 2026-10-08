from __future__ import annotations

from copy import deepcopy

from src.data.ocean_sst_anomaly import REGION_REGISTRY, RegionalSSTReading
from src.state import DEFAULT_STATE
from tests.crw_fixtures import quiet_collection
from tests.marine_fixtures import marine_clock, sst_reading
import pytest


def _reading(
    slug: str = "north_atlantic",
    display: str = "North Atlantic",
    *,
    day: str = "2026-08-20",
    anomaly: float = 3.6,
    tier: int = 2,
    cells: int = 120,
) -> RegionalSSTReading:
    return RegionalSSTReading(
        region_slug=slug,
        region_display_name=display,
        date=day,
        anomaly_c=anomaly,
        tier=tier,
        cells_used=cells,
    )


def _state() -> dict:
    return deepcopy(DEFAULT_STATE)


def test_run_ocean_sst_anomaly_enqueues_regional_candidate(monkeypatch, synthetic_bundle_provenance):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly._fetch_strict",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_fetch_strict called")),
    )
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading()]),
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    queue = bot_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "sst_anom_north_atlantic_tier2_2026-08-20"
    assert queue[0].legacy_type == "regional_sst_anomaly"
    assert queue[0].source == "ocean_sst_anomaly"


@pytest.mark.usefixtures("marine_clock")
def test_run_ocean_sst_anomaly_records_synthesis_component(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly
    from src.editorial.marine_evidence import component

    bot_state = _state()
    reading = sst_reading(monkeypatch, slug="coral_triangle", value=2.1)
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([reading]),
    )
    run_ocean_sst_anomaly(bot_state, {"sources": []})
    assert bot_state.get("_triage_queue", []) == []
    stored = bot_state["synthesis_components"]["sst_anomalies"]["coral_triangle"][0]
    assert stored == component("sst_anomaly", reading)
    assert stored["marine_source"]["reading"]["tier"] == 0


def test_run_ocean_sst_anomaly_duplicate_updates_tier_without_queue(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    bot_state["posted_events"] = ["sst_anom_north_atlantic_tier2_2026-08-20"]
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading()]),
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    assert bot_state.get("_triage_queue", []) == []
    assert bot_state["sst_anom_last_tier"]["2026/north_atlantic"] == 2


def test_run_ocean_sst_anomaly_on_success_updates_tier_and_count(monkeypatch, synthetic_bundle_provenance):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading(day="2025-12-31")]),
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    assert bot_state["sst_anom_last_tier"] == {}
    assert bot_state["sst_anom_annual_count"] == {}
    candidate = bot_state["_triage_queue"][0]
    assert candidate.on_draft_success is not None
    candidate.on_draft_success()
    assert bot_state["sst_anom_last_tier"] == {"2025/north_atlantic": 2}
    assert bot_state["sst_anom_annual_count"] == {"2025": 1}


def test_run_ocean_sst_anomaly_annual_state_filtered_to_reading_year(monkeypatch, synthetic_bundle_provenance):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    bot_state["sst_anom_last_tier"] = {
        "2025/north_atlantic": 3,
        "2026/north_atlantic": 1,
    }
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading(day="2026-01-02", tier=2, anomaly=3.6)]),
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    queue = bot_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "sst_anom_north_atlantic_tier2_2026-01-02"


def test_run_ocean_sst_anomaly_annual_cap_uses_reading_year(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    bot_state["sst_anom_annual_count"] = {"2025": 10, "2026": 0}
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading(day="2025-12-31")]),
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    assert bot_state.get("_triage_queue", []) == []


def test_run_ocean_sst_anomaly_records_success_when_no_regions_cross_tier(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    current_run = {"sources": []}
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection(),
    )

    run_ocean_sst_anomaly(bot_state, current_run)

    source_entry = next(s for s in current_run["sources"] if s["source"] == "ocean_sst_anomaly")
    assert source_entry["status"] == "success"
    assert source_entry["observed"] == len(REGION_REGISTRY)
    assert bot_state.get("_triage_queue", []) == []


def test_run_ocean_sst_anomaly_source_health_observes_sampled_regions(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading()]),
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    health = bot_state["source_health"]["ocean_sst_anomaly"]
    assert health["total_observed"] == len(REGION_REGISTRY)


def test_run_ocean_sst_anomaly_records_failed_when_fetch_all_regions_fails(monkeypatch):
    from src.data.source_status import SourceFetchError
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    current_run = {"sources": []}

    def _raise(strict=False):
        raise SourceFetchError("all regions failed")

    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        _raise,
    )

    run_ocean_sst_anomaly(bot_state, current_run)

    source_entry = next(s for s in current_run["sources"] if s["source"] == "ocean_sst_anomaly")
    assert source_entry["status"] == "failed"
    assert any(error["source"] == "ocean_sst_anomaly" for error in bot_state["errors"])


def test_rejected_evidence_is_not_counted_as_promoted(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state, current_run = _state(), {"sources": []}
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: quiet_collection([_reading()]),
    )
    run_ocean_sst_anomaly(bot_state, current_run)
    assert bot_state.get("_triage_queue", []) == []  # No source receipt injected.
    assert current_run["sources"][0]["promoted"] == 0
    assert current_run["sources"][0]["observed"] == 13
    assert bot_state["sst_anom_last_tier"] == bot_state["sst_anom_annual_count"] == {}


def test_runner_records_report_counts_partial_failure_and_safe_details(monkeypatch):
    from dataclasses import replace
    from src.data.ocean_sst_anomaly import RegionalSSTCollection, RegionalSSTResult
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    quiet = quiet_collection()
    failed = replace(quiet.regions[0].primary, outcome="source_rejected", valid_cells=None,
                     total_cells=None, excluded_cells=None, diagnostic="regional_source_rejected")
    report = RegionalSSTCollection((RegionalSSTResult(failed, failed), *quiet.regions[1:]))
    bot_state, current_run = _state(), {"sources": []}
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions",
        lambda strict=False: report,
    )
    run_ocean_sst_anomaly(bot_state, current_run)
    entry = current_run["sources"][0]
    assert entry["status"] == "partial_failure" and entry["observed"] == 12
    assert entry["details"] == {**report.details(), "marine_components": {}} and entry["note"] == report.note
    health = bot_state["source_health"]["ocean_sst_anomaly"]
    assert health["degraded"] == 1 and health["total_observed"] == 12
    assert health["last_error"] == report.note


def test_runner_exception_payload_never_enters_state(monkeypatch):
    import json
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    def fail(**kwargs):
        raise ValueError("private-response-payload")

    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.collect_all_regions", fail,
    )
    bot_state, current_run = _state(), {"sources": []}
    run_ocean_sst_anomaly(bot_state, current_run)
    assert current_run["sources"][0]["error"] == "regional_sst_runner_error"
    assert "private-response-payload" not in json.dumps([bot_state, current_run])
