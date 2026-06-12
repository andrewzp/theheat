from __future__ import annotations

from copy import deepcopy

from src.data.ocean_sst_anomaly import REGION_REGISTRY, RegionalSSTReading
from src.state import DEFAULT_STATE


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


def test_run_ocean_sst_anomaly_enqueues_regional_candidate(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly._fetch_strict",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_fetch_strict called")),
    )
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [_reading()],
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    queue = bot_state["_triage_queue"]
    assert len(queue) == 1
    assert queue[0].event_id == "sst_anom_north_atlantic_tier2_2026-08-20"
    assert queue[0].legacy_type == "regional_sst_anomaly"
    assert queue[0].source == "ocean_sst_anomaly"


def test_run_ocean_sst_anomaly_duplicate_updates_tier_without_queue(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    bot_state["posted_events"] = ["sst_anom_north_atlantic_tier2_2026-08-20"]
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [_reading()],
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    assert bot_state.get("_triage_queue", []) == []
    assert bot_state["sst_anom_last_tier"]["2026/north_atlantic"] == 2


def test_run_ocean_sst_anomaly_on_success_updates_tier_and_count(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [_reading(day="2025-12-31")],
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    assert bot_state["sst_anom_last_tier"] == {}
    assert bot_state["sst_anom_annual_count"] == {}
    candidate = bot_state["_triage_queue"][0]
    assert candidate.on_draft_success is not None
    candidate.on_draft_success()
    assert bot_state["sst_anom_last_tier"] == {"2025/north_atlantic": 2}
    assert bot_state["sst_anom_annual_count"] == {"2025": 1}


def test_run_ocean_sst_anomaly_annual_state_filtered_to_reading_year(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    bot_state["sst_anom_last_tier"] = {
        "2025/north_atlantic": 3,
        "2026/north_atlantic": 1,
    }
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [_reading(day="2026-01-02", tier=2, anomaly=3.6)],
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
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [_reading(day="2025-12-31")],
    )

    run_ocean_sst_anomaly(bot_state, {"sources": []})

    assert bot_state.get("_triage_queue", []) == []


def test_run_ocean_sst_anomaly_records_success_when_no_regions_cross_tier(monkeypatch):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    bot_state = _state()
    current_run = {"sources": []}
    monkeypatch.setattr(
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [],
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
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        lambda strict=False: [_reading()],
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
        "src.orchestrator.sources.ocean_sst_anomaly.ocean_sst_anomaly.fetch_all_regions",
        _raise,
    )

    run_ocean_sst_anomaly(bot_state, current_run)

    source_entry = next(s for s in current_run["sources"] if s["source"] == "ocean_sst_anomaly")
    assert source_entry["status"] == "failed"
    assert any(error["source"] == "ocean_sst_anomaly" for error in bot_state["errors"])
