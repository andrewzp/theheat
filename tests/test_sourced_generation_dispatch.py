"""Both actual queue drains distinguish queued work from paid/saved work."""
from dataclasses import replace

import pytest

from src.commands.schema import CommandError
from src.orchestrator import common, funnel, triage_queue, two_bot_dispatch
from src.two_bot import pipeline
from tests.test_triage import _candidate, _fresh_state


@pytest.mark.parametrize("refill", [False, True])
def test_actual_drain_queues_one_slot_without_refill_draft_or_callback(monkeypatch, refill):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", str(int(refill)))
    monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_GLOBAL_CAP", "1")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", two_bot_dispatch._try_two_bot_draft)
    monkeypatch.setattr(pipeline, "generate_draft", lambda *a, **k: pytest.fail("legacy provider bypass"))
    calls = []
    class Client:
        def submit(self, bundle, **save):
            calls.append(save["event_id"])
            return dict(generation_status="queued", job_id="invented-shared-job")
    def callback():
        pytest.fail("unsupported asynchronous callback invoked")
    state = _fresh_state()
    state["_triage_queue"] = [
        replace(_candidate(event_id="unsupported", total=99), annual_cap_check=callback, on_draft_success=callback),
        _candidate(event_id="selected", total=95), _candidate(event_id="refill", total=90),
    ]
    run = {"sources": [{"source": "coral_dhw", "drafted": 0, "writer_attempted": 0}]}
    sink = funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(state, run, generation_client=Client(), funnel_sink=sink) == 0
    assert calls == ["selected"]
    assert "_triage_queue" not in state and not state["drafts"]
    assert run["sources"][0]["drafted"] == run["sources"][0]["writer_attempted"] == 0
    assert sink["_slate_terminal"]["selected"] == "generation_queued"
    assert sink["_slate_terminal"]["unsupported"] == "generation_start"
    assert not state.get("writer_negative_cache")


def test_explicit_generation_refusal_never_falls_back(monkeypatch):
    monkeypatch.setattr(pipeline, "generate_draft", lambda *a, **k: pytest.fail("legacy provider bypass"))
    class Client:
        def submit(self, *a, **k):
            raise CommandError("generation_source_not_retained", "Retain source evidence first")
    row = _candidate()
    result = {"generation_status": "queued", "job_id": "old"}
    assert two_bot_dispatch._try_two_bot_draft(row.bundle, _fresh_state(), row.score, legacy_type=row.legacy_type,
        event_id=row.event_id, review_context=row.review_context, generation_client=Client(), result_out=result) is False
    assert result == dict(kill_stage="generation_start", kill_reason="generation_source_not_retained")
