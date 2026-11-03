"""An expired forecast cannot take the sole ranked writer slot."""
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from freezegun import freeze_time

from src.editorial.scoring import score_dust_event
from src.orchestrator import triage_queue
from tests.operation_budget_helpers import Spies, enqueue_fires, fresh_state
from tests.test_air_quality_auto_text import dust_bundle


@pytest.mark.parametrize("refill", ["0", "1"])
@pytest.mark.parametrize("writer_kills", [False, True])
def test_ended_forecast_leaves_the_only_slot_for_eligible_story(monkeypatch, refill, writer_kills):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", refill)
    monkeypatch.delenv("THEHEAT_DUST_FORECAST_AUTO_TEXT", raising=False)
    spy = Spies().install(monkeypatch)
    state = fresh_state()
    expired = dust_bundle()
    with freeze_time(datetime(2026, 10, 30, 2, tzinfo=UTC)):
        assert triage_queue._enqueue_story_candidate(
            state, bundle=expired, score=replace(score_dust_event(2000.0, 2), total=100), source="air_quality",
            legacy_type="dust_event", event_id=expired.event_id, review_context={},
        )
        fire_id, _next_id = enqueue_fires(state, 2)
        if writer_kills:
            spy.writer_kill.add(fire_id)
        run = {"id": "invented-ended-aq", "sources": []}
        assert triage_queue._drain_and_write_triage_queue(state, run) == int(not writer_kills)
    assert spy.writer_events() == [fire_id]
    if writer_kills:
        assert spy.calls == [("writer", fire_id)]
        assert not state["drafts"]
    else:
        assert [stage for stage, _ in spy.calls] == ["writer", "safety", "fact_check", "critic"]
        assert state["drafts"][0]["event_id"] == fire_id
    assert any("air_quality_window_ended" in str(row) for row in state["suppressions"])
