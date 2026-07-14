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

import pytest

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


def test_funnel_rates_keeps_editorial_cuts_visible_alongside_billing(monkeypatch):
    """codex r4 P2 exact scenario: 5 triaged in, triage selected 3 survivors
    (2 REAL editorial cuts), billing aborted 2 of the survivors. The rates
    must report triage_cut=2 — never let the billing skips swallow it."""
    from src.orchestrator import funnel

    rates = funnel.funnel_rates({
        "triaged_in": 5,
        "triaged_out": 3,
        "billing_aborted": 2,
        "writer_attempted": 1,
        "drafted": 0,
        "passes": {},
        "kills": {"budget_exhausted": 1, "billing_cycle_abort": 1},
    })

    assert rates["triage_cut"] == 2, "real editorial cuts stay visible"
    assert rates["triage_cap_rate"] == pytest.approx(2 / 5)
    assert rates["billing_aborted"] == 2


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


def test_billing_abort_never_overwrites_resolved_terminals(monkeypatch):
    """codex P1 regression: duplicate event_ids are expected in the ranked
    queue — a candidate that already resolved (drafted) must keep its true
    terminal when the abort marks the skipped remainder."""
    from src.orchestrator import common, funnel

    bot_state = _fresh_state()
    # e1 drafts; e2 billing-kills; the queue carries a DUPLICATE e1 after e2.
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
        _candidate(event_id="e1", total=85),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    def fake_try(bundle, state, score, *, result_out=None, **kwargs):
        if bundle.event_id == "e1":
            if result_out is not None:
                result_out["stage_outcomes"] = {"writer": "pass"}
            return True
        if result_out is not None:
            result_out["kill_stage"] = "budget_exhausted"
            result_out["kill_reason"] = "credit balance is too low"
        return False

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)

    sink = funnel.new_funnel()
    common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=sink)

    terminals = sink.get("_slate_terminal", {})
    assert terminals.get("e1") == "drafted", (
        "a resolved terminal must survive the billing abort"
    )
    assert terminals.get("e2") == "budget_exhausted"


def test_legacy_drain_non_billing_kills_do_not_trip_breaker(monkeypatch):
    """codex P2: the legacy loop's breaker condition is duplicated code — pin
    that ordinary kills keep it walking there too."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
        _candidate(event_id="e3", total=85),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []

    def honesty_kill_fake(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        if result_out is not None:
            result_out["kill_stage"] = "honesty_gate"
            result_out["kill_reason"] = "forbidden claim: 'heat dome'"
        return False

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", honesty_kill_fake)

    common._drain_and_write_triage_queue(bot_state, current_run)

    assert calls == ["e1", "e2", "e3"]
    assert _abort_rows(bot_state) == []


def test_legacy_drain_marks_funnel_terminals_on_abort(monkeypatch):
    """codex P2: funnel-terminal marking on abort, legacy path."""
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
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", _billing_kill_fake(calls))

    sink = funnel.new_funnel()
    common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=sink)

    assert calls == ["e1"]
    terminals = sink.get("_slate_terminal", {})
    assert terminals.get("e1") == "budget_exhausted"
    assert terminals.get("e2") == "billing_abort"
    assert terminals.get("e3") == "billing_abort"
    # Volumes (codex r4 P2): the legacy loop pre-counted all 3 survivors in
    # triaged_out — the abort adds billing_aborted only, no double count.
    source_entry = current_run["sources"][0]
    assert source_entry.get("triaged_out") == 3
    assert source_entry.get("billing_aborted") == 2


def test_abort_suppression_row_shape_and_cap(monkeypatch):
    """codex P2: pin the row shape and the MAX_SUPPRESSIONS eviction so a
    malformed or unbounded implementation cannot pass."""
    from src.orchestrator import common
    from src.state import MAX_SUPPRESSIONS

    bot_state = _fresh_state()
    # Pre-fill the ledger to the cap: the abort append must evict, not grow.
    bot_state["suppressions"] = [
        {"id": f"supp_old_{i}", "ts": "2026-06-01T00:00:00Z", "stage": "writer"}
        for i in range(MAX_SUPPRESSIONS)
    ]
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    calls: list = []
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", _billing_kill_fake(calls))

    common._drain_and_write_triage_queue(bot_state, current_run)

    suppressions = bot_state["suppressions"]
    assert len(suppressions) == MAX_SUPPRESSIONS, (
        "append at cap must evict to exactly the cap, not truncate further"
    )
    ids = [r["id"] for r in suppressions]
    assert "supp_old_0" not in ids, "the OLDEST row is the one evicted"
    assert ids[0] == "supp_old_1", "eviction preserves order and recent history"
    assert suppressions[-1]["stage"] == "billing_cycle_abort", (
        "the abort row lands newest"
    )
    rows = _abort_rows(bot_state)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"].startswith("supp_")
    assert isinstance(row["ts"], str) and row["ts"]
    assert row["run_id"] is None
    assert row["source"] == "billing"
    assert row["stage"] == "billing_cycle_abort"
    assert row["event_id"] == "e1"
    assert row["category"] is None
    assert row["score_total"] == 0
    assert row["threshold"] == 0
    assert row["summary"] is None
    assert isinstance(row["reasons"], list) and len(row["reasons"]) == 1
    assert "1 queued candidate(s) skipped" in row["reasons"][0]


def test_call_with_retries_transient_gets_three_attempts(monkeypatch):
    """codex P2: pin the single-transport-owner behavior — a transient
    provider error gets exactly 3 outer attempts through _call_anthropic."""
    import anthropic
    from anthropic.types import TextBlock  # noqa: F401 — real import guards env

    attempts: list = []

    class _FlakyMessages:
        def create(self, **kwargs):
            attempts.append(1)
            raise RuntimeError("transient boom")

    class _FakeClient:
        def __init__(self, **kwargs):
            self.messages = _FlakyMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    monkeypatch.setattr("src.two_bot.retry.time.sleep", lambda s: None)

    from src.two_bot.writer import _call_anthropic

    with pytest.raises(RuntimeError, match="transient boom"):
        _call_anthropic("user prompt")
    assert len(attempts) == 3, "call_with_retries owns exactly 3 attempts"


def test_call_with_retries_billing_400_single_attempt(monkeypatch):
    """codex P2: a billing 400 short-circuits on the FIRST attempt and
    surfaces as BudgetExhaustedError — no paid re-confirmation of the bill."""
    import anthropic

    from src.two_bot.retry import BudgetExhaustedError

    attempts: list = []

    class _BrokeMessages:
        def create(self, **kwargs):
            attempts.append(1)
            raise RuntimeError(
                "Error code: 400 — Your credit balance is too low to access "
                "the Anthropic API."
            )

    class _FakeClient:
        def __init__(self, **kwargs):
            self.messages = _BrokeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    monkeypatch.setattr("src.two_bot.retry.time.sleep", lambda s: None)

    from src.two_bot.writer import _call_anthropic

    with pytest.raises(BudgetExhaustedError):
        _call_anthropic("user prompt")
    assert len(attempts) == 1, "billing errors must not burn retries"


def test_billing_abort_volume_not_misread_as_triage_cut(monkeypatch):
    """codex r3 P2: billing-aborted candidates must not inflate triage_cut —
    a billing outage must not read as an editorial cap on the dashboard."""
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
    frozen = funnel.finalize_funnel(sink, current_run, bot_state)
    rates = funnel.funnel_rates(frozen)

    assert frozen["billing_aborted"] == 2
    # Refill counts triaged_out per attempt (1) + per billing skip (2), so
    # the skips leave the cut denominator instead of being subtracted later.
    assert frozen["triaged_out"] == 3
    assert rates["billing_aborted"] == 2
    assert rates["triage_cut"] == 0, "billing skips are not editorial cuts"


def test_latch_blocks_subsequent_drains_in_same_cycle(monkeypatch):
    """codex r2 P1: in `both` mode the cli runs alerts THEN leaderboard on
    the same bot_state. After the alerts drain aborts on billing, a later
    drain must make ZERO writer calls and record ZERO additional abort rows
    — the latch is a transient state key scoped to this process's cycle."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")

    calls: list = []
    monkeypatch.setattr(common, "_try_two_bot_draft", _billing_kill_fake(calls))

    # Drain 1 (alerts): trips the breaker + the latch.
    bot_state["_triage_queue"] = [
        _candidate(event_id="e1", total=99),
        _candidate(event_id="e2", total=90),
    ]
    common._drain_and_write_triage_queue(bot_state, current_run)
    assert calls == ["e1"]
    assert bot_state.get("_billing_exhausted_latch") is True

    # Drain 2 (leaderboard, same bot_state): must not re-probe the balance.
    bot_state["_triage_queue"] = [
        _candidate(event_id="e3", total=95),
        _candidate(event_id="e4", total=88),
    ]
    drafted = common._drain_and_write_triage_queue(bot_state, current_run)

    assert drafted == 0
    assert calls == ["e1"], "latched drain must make zero writer calls"
    assert len(_abort_rows(bot_state)) == 1, "no duplicate abort row"
    # Volume telemetry: 1 skipped by the abort (e2) + 2 by the latched drain;
    # triaged_out pairs each skip (plus e1's attempt) so nothing reads as a cut.
    source_entry = current_run["sources"][0]
    assert source_entry.get("billing_aborted") == 3
    assert source_entry.get("triaged_out") == 4


def test_latch_never_persists_through_state_merge():
    """The latch must die with the process: _merge_state drops keys outside
    MERGE_SPEC, so the next cron re-probes billing with one fresh attempt."""
    from src.state import _merge_state

    bot_state = _fresh_state()
    bot_state["_billing_exhausted_latch"] = True

    merged = _merge_state(bot_state, bot_state)

    assert "_billing_exhausted_latch" not in merged


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
