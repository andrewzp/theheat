"""Economics P0: cycle-level billing circuit breaker.

The per-call breaker (retry.py) stops retrying ONE candidate on a billing
error; these tests pin the CYCLE-level contract: the first
``kill_stage == "budget_exhausted"`` from the pipeline aborts the remaining
slate (refill AND legacy drain), records exactly ONE stage-level
suppression, and — when funnel telemetry is on — marks the never-attempted
remainder as ``billing_abort``. Motivated by 2026-07-13T21:02Z: six paid
writer attempts fired after the first "credit balance is too low" error.
"""

from __future__ import annotations

from copy import deepcopy

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE
from src.two_bot.types import StoryBundle, TriageCandidateBundle


def _fresh_state() -> dict:
    return deepcopy(DEFAULT_STATE)


def _score(total: int = 80, category: str = "coral_bleaching") -> EditorialScore:
    return EditorialScore(
        category=category, severity=80, novelty=80, timeliness=80, confidence=80,
        shareability=80, sensitivity=0, total=total, threshold=60, reasons=[],
    )


def _bundle(event_id: str = "evt", signal_kind: str = "coral_bleaching") -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind, where="Reef", when="2026-06-16", event_id=event_id,
        headline_metric={"label": "DHW", "value": 8}, current_facts=[],
    )


def _candidate(*, event_id: str, total: int = 80, source: str = "coral_dhw") -> TriageCandidateBundle:
    return TriageCandidateBundle(
        bundle=_bundle(event_id), score=_score(total), event_id=event_id, source=source,
        review_context={}, city="", tweet_date="2026-06-16", cooldown_exempt=False,
        legacy_type="coral_bleaching", created_at="2026-06-16T12:00:00Z",
    )


def _billing_kill_fake(calls: list):
    """A _try_two_bot_draft stand-in whose every attempt dies on billing."""

    def fake_try(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        if result_out is not None:
            result_out["kill_stage"] = "budget_exhausted"
            result_out["kill_reason"] = (
                "anthropic writer: provider billing exhausted: "
                "credit balance is too low"
            )
        return False

    return fake_try


def _abort_rows(state: dict) -> list[dict]:
    return [
        s for s in state.get("suppressions", [])
        if s.get("stage") == "billing_cycle_abort"
    ]


def test_legacy_drain_aborts_cycle_on_first_billing_kill(monkeypatch):
    """Non-refill path: first budget_exhausted kill stops the slate."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
        _candidate(event_id="e3", total=85),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", _billing_kill_fake(calls))

    drafted = common._drain_and_write_triage_queue(bot_state, current_run)

    assert drafted == 0
    assert calls == ["e1"], "breaker must stop after the first billing kill"
    rows = _abort_rows(bot_state)
    assert len(rows) == 1, "exactly ONE cycle-abort suppression"
    assert rows[0]["event_id"] == "e1"
    assert "2 queued candidate(s) skipped" in rows[0]["reasons"][0]


def test_refill_drain_aborts_cycle_on_first_billing_kill(monkeypatch):
    """Refill path: the generate-and-select loop honors the breaker too."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
        _candidate(event_id="e3", total=85),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", _billing_kill_fake(calls))

    drafted = common._drain_and_write_triage_queue(bot_state, current_run)

    assert drafted == 0
    assert calls == ["e1"], "refill loop must not re-discover the dead balance"
    rows = _abort_rows(bot_state)
    assert len(rows) == 1
    assert rows[0]["event_id"] == "e1"


def test_billing_abort_marks_remaining_slate_in_funnel(monkeypatch):
    """With funnel telemetry on, the skipped remainder reads billing_abort."""
    from src.orchestrator import common, funnel

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
        _candidate(event_id="e3", total=85),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", _billing_kill_fake(calls))

    sink = funnel.new_funnel()
    common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=sink)

    terminals = sink.get("_slate_terminal", {})
    assert terminals.get("e1") == "budget_exhausted"
    assert terminals.get("e2") == "billing_abort"
    assert terminals.get("e3") == "billing_abort"


def test_non_billing_kills_do_not_trip_breaker(monkeypatch):
    """An ordinary writer kill must NOT abort the cycle."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
        _candidate(event_id="e3", total=85),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []

    def writer_kill_fake(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        if result_out is not None:
            result_out["kill_stage"] = "writer"
            result_out["kill_reason"] = "no extraordinary angle"
        return False

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", writer_kill_fake)

    common._drain_and_write_triage_queue(bot_state, current_run)

    assert calls == ["e1", "e2", "e3"], "ordinary kills keep the loop walking"
    assert _abort_rows(bot_state) == []


def test_successful_drafts_do_not_trip_breaker(monkeypatch):
    """A drafted candidate leaves no kill_stage — the breaker stays silent."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []

    def drafting_fake(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        if result_out is not None:
            result_out["stage_outcomes"] = {
                "writer": "pass", "fact_check": "pass", "critic": "pass",
            }
        return True

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", drafting_fake)

    drafted = common._drain_and_write_triage_queue(bot_state, current_run)

    assert drafted == 2
    assert calls == ["e1", "e2"]
    assert _abort_rows(bot_state) == []


def test_writer_anthropic_client_owns_zero_transport_retries(monkeypatch):
    """max_retries=0: call_with_retries is the single transport-retry owner.

    The SDK default (2) stacked a second retry layer under the pipeline's
    billing-aware one — economics P0 pins the client kwargs so a future SDK
    bump can't silently reintroduce it.
    """
    import anthropic
    from anthropic.types import TextBlock

    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            class _Resp:
                content = [TextBlock(type="text", text='{"tweet": null}')]

            return _Resp()

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = _FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    from src.two_bot.writer import _call_anthropic

    raw = _call_anthropic("user prompt")

    assert captured.get("max_retries") == 0
    assert captured.get("timeout") == 180.0
    assert "tweet" in raw
