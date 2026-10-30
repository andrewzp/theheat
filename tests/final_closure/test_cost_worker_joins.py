"""D1 — operation/attempt authority across worker threads, late calls and usage attribution.

Invented candidates, models and responses; network is trapped. The real
scheduler, writer-sample slate, candidate budget, provider seam, news
allowance and usage ledger run; only the provider ``send`` is a stub.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.orchestrator import scheduler
from src.orchestrator.candidate_budget import CandidateBudget
from src.two_bot import call_inventory as inv
from src.two_bot import usage_ledger
from src.two_bot import usage_observations as observations
from src.two_bot.trial_budget import provider_call
from tests import live_content_harness as h


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    h.trap_network(monkeypatch.setattr)
    monkeypatch.setattr(usage_ledger, "_BUFFER", [])
    monkeypatch.setattr(inv, "_UNJOINED", {})


def _budget(limit="2"):
    return CandidateBudget.for_operation("alerts", {"THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": limit})


def _anthropic_response():
    usage = SimpleNamespace(input_tokens=11, output_tokens=7, cache_creation_input_tokens=None,
                            cache_read_input_tokens=None)
    return SimpleNamespace(usage=usage, model="invented-model", id="invented-response")


def _writer_call():
    response = provider_call("writer", "anthropic", {"model": "invented-model"}, lambda **_: _anthropic_response())
    usage_ledger.record_writer_response(response, "invented-model", "anthropic")
    return response


def _bot_state():
    return {"source_health": {}}


def _observation_rows():
    return [row["usage_observation"] for row in usage_ledger._BUFFER if "usage_observation" in row]


def test_a_concurrent_source_runner_joins_the_submitting_operation_and_attempt():
    """Counterexample on the released base: the worker sees no join, so 0 rows."""
    budget = _budget()
    with inv.operation_scope("alerts") as join:
        assert budget.reserve("event:invented_heat_01")
        runner = scheduler.SourceRunner("invented_source", _writer_call)
        scheduler.run_stage1_sources(_bot_state(), {}, serial_runners=[], concurrent_runners=[runner],
                                     budget_seconds=10, max_workers=2)
        budget.settle("event:invented_heat_01", writer_started=False)
    assert join.dispatched() == 1 and join.rows[0]["outcome"] == "returned"
    # The attempt kept its slot: a request it joined can never be refunded.
    assert budget.joined_requests == 1 and budget.summary()["attempts"] == 1
    assert inv.unjoined_calls()["total"] == 0


def test_serial_runner_threads_also_carry_the_join():
    with inv.operation_scope("leaderboard") as join:
        runner = scheduler.SourceRunner("invented_serial", _writer_call)
        scheduler.run_stage1_sources(_bot_state(), {}, serial_runners=[runner], concurrent_runners=[],
                                     budget_seconds=10)
    assert join.dispatched() == 1


def test_writer_samples_join_the_candidate_attempt_and_keep_its_slot(monkeypatch):
    """Counterexample on the base: multi-sample writer requests were unjoined and refundable."""
    from src.two_bot import pipeline

    monkeypatch.setattr(pipeline.writer, "write_tweet", lambda bundle, memory: _writer_call())
    budget = _budget()
    with inv.operation_scope("alerts") as join:
        assert budget.reserve("event:invented_heat_02")
        slate = pipeline._writer_sample_slate(cast(Any, object()), cast(Any, object()), 2)
        budget.settle("event:invented_heat_02", writer_started=False)
    assert len(slate) == 2 and join.dispatched() == 2
    assert budget.joined_requests == 2 and budget.refused_before_writer == 0


def test_a_worker_that_outlives_its_operation_is_counted_late_never_joined():
    release, sent = threading.Event(), threading.Event()
    current_run: dict = {}

    def slow_writer():
        release.wait(5)
        try:
            _writer_call()
        finally:
            sent.set()

    executor = ThreadPoolExecutor(max_workers=1)
    with inv.operation_scope("alerts") as join:
        inv.submit_in_context(executor, slow_writer)
        inv.record_operation_cost(current_run, inv.operation_cost_row("alerts", join=join), join=join)
    release.set()
    assert sent.wait(5)
    executor.shutdown(wait=True)
    # The closed join gained no row; the late request is visible and still spent.
    assert join.rows == [] and join.dispatched() == 0 and join.late_after_close == 1
    persisted = current_run["operation_costs"][0]["requests"]
    assert persisted["total"] == 0 and persisted["late_after_close"] == 1
    assert persisted["late_by_stage"] == {"writer": 1}
    assert inv.unjoined_calls()["by_stage"] == [{"stage": "writer", "reason": "late_after_close", "physical_calls": 1}]
    [observed] = _observation_rows()
    assert observed["attribution"]["status"] == "late_after_close"
    assert observed["attribution"]["operation"] is None and observed["attribution"]["event_id"] is None


def test_a_call_with_no_operation_is_counted_unjoined_and_attributed_absent():
    _writer_call()
    assert inv.unjoined_calls()["by_stage"] == [{"stage": "writer", "reason": "no_operation", "physical_calls": 1}]
    [observed] = _observation_rows()
    assert observed["attribution"] == observations_unjoined()
    assert observations.valid_record(observed)


def observations_unjoined():
    return {"schema_version": 1, "status": "unjoined", "operation": None, "path": None, "attempt": None,
            "event_id": None}


def test_usage_observation_carries_the_dispatch_join_through_a_worker_thread():
    budget = _budget()
    executor = ThreadPoolExecutor(max_workers=1)
    with inv.operation_scope("alerts"):
        assert budget.reserve("event:invented_heat_03")
        inv.submit_in_context(executor, _writer_call).result(5)
        budget.settle("event:invented_heat_03", writer_started=True)
    executor.shutdown(wait=True)
    [observed] = _observation_rows()
    assert observed["attribution"] == {
        "schema_version": 1, "status": "joined_attempt", "operation": "alerts", "path": "ordinary",
        "attempt": hashlib.sha256(b"event:invented_heat_03").hexdigest()[:16], "event_id": "invented_heat_03"}
    assert observations.valid_record(observed)
    merged = observations.merge_observations({"schema_version": 1, "observations": [observed],
                                              "truncated": False, "invalid": False})
    assert merged["observations"][0]["attribution"]["event_id"] == "invented_heat_03" and not merged["invalid"]


def test_a_bundle_keyed_attempt_has_no_event_id_and_an_operation_only_call_has_no_attempt():
    budget = _budget()
    with inv.operation_scope("leaderboard"):
        _writer_call()
        assert budget.reserve("bundle:" + "a" * 64)
        _writer_call()
        budget.settle("bundle:" + "a" * 64, writer_started=True)
    operation_only, bundle_attempt = (row["attribution"] for row in _observation_rows())
    assert operation_only == {"schema_version": 1, "status": "joined_operation", "operation": "leaderboard",
                              "path": "ordinary", "attempt": None, "event_id": None}
    assert bundle_attempt["status"] == "joined_attempt" and bundle_attempt["event_id"] is None


def test_a_response_never_borrows_another_stages_dispatch():
    with inv.operation_scope("alerts"):
        provider_call("writer", "anthropic", {"model": "invented-model"}, lambda **_: _anthropic_response())
        usage_ledger.record_response("critic", SimpleNamespace(usage_metadata=None), "invented", "google")
    [observed] = _observation_rows()
    assert observed["attribution"] == observations_unjoined()


def test_finite_trial_reaches_a_worker_thread_and_still_refuses_news(tmp_path):
    """Counterexample on the base: the worker saw no trial and the news refusal never fired."""
    from src.data import newsworthiness as news
    from src.two_bot.trial_budget import TrialBudget, trial_scope

    budget = TrialBudget(lambda _row: None, tmp_path / "stop")
    run: dict = {}
    with trial_scope(budget):
        runner = scheduler.SourceRunner("invented_news", news._refuse_finite_trial_news)
        scheduler.run_stage1_sources(_bot_state(), run, serial_runners=[], concurrent_runners=[runner],
                                     budget_seconds=10)
    assert budget.stopped == "trial_unassigned_stage"


def test_news_allowance_counts_only_its_own_contexts_physical_attempts():
    """Counterexample on the base: process-wide deltas absorbed a concurrent thread's call."""
    from src.data import newsworthiness as news

    first_sent, second_sent = threading.Event(), threading.Event()

    def call_a():
        inv.consume("newsworthiness_verify", provider="google")
        first_sent.set()
        assert second_sent.wait(5)
        return "{}"

    def call_b():
        assert first_sent.wait(5)
        inv.consume("newsworthiness_verify", provider="google")
        second_sent.set()
        return "{}"

    allowances = [news.news_discovery_allowance(), news.news_discovery_allowance()]
    for allowance in allowances:
        assert allowance.reserve("newsworthiness_verify")
    threads = [threading.Thread(target=news._counted, args=(allowance, "newsworthiness_verify", call))
               for allowance, call in zip(allowances, (call_a, call_b))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert [a.physical_attempts["newsworthiness_verify"] for a in allowances] == [1, 1]


def test_an_unreserved_allowance_attempt_is_refused_before_egress():
    from src.data import newsworthiness as news

    allowance = news.news_discovery_allowance()
    sent: list[int] = []

    def send():
        inv.consume("newsworthiness_verify", provider="google")
        sent.append(1)

    with pytest.raises(ValueError, match="unreserved_physical_attempt"):
        news._counted(allowance, "newsworthiness_verify", send)
    assert sent == [] and allowance.outcomes["newsworthiness_verify"]["unavailable"] == 1


def test_exact_cache_reuse_is_recorded_without_a_slot_or_attempt():
    from src.data import newsworthiness as news

    allowance = news.news_discovery_allowance()
    allowance.cache_hit("newsworthiness_verify")
    stage = allowance.summary()["stages"]["newsworthiness_verify"]
    assert stage["exact_cache_hits"] == 1 and stage["reserved"] == 0 and stage["physical_attempts"] == 0


def test_every_thread_boundary_in_src_propagates_or_is_a_declared_unjoined_data_pool():
    """Inventory guard: a new executor/thread that may reach a joined call must copy the context."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    # join=False source fetches only (``source_http_get``): counted process-wide by declaration.
    data_pools = {"src/data/ghcn.py", "src/data/coral_dhw.py", "src/data/gpm_imerg.py",
                  "src/data/ocean_sst_anomaly.py", "src/data/normals_acquisition.py"}
    propagated = {"src/orchestrator/scheduler.py", "src/two_bot/pipeline.py"}
    # A helper thread that only resolves a hostname and writes its own local box;
    # it can never reach a declared call. Kept DNS-only by the assertion below.
    dns_only = {"src/data/bounded_http.py"}
    found = set()
    for path in (root / "src").rglob("*.py"):
        text = path.read_text()
        if re.search(r"ThreadPoolExecutor\(|threading\.Thread\(|run_in_executor|asyncio\.to_thread", text):
            found.add(str(path.relative_to(root)))
    assert found == data_pools | propagated | dns_only
    for name in dns_only:
        text = (root / name).read_text()
        threads = re.findall(r"threading\.Thread\(([^)]*)\)", text)
        assert threads == ['target=lookup, name="theheat-bounded-dns", daemon=True'], threads
        lookup = text.split("def lookup() -> None:", 1)[1].split("helper = threading.Thread", 1)[0]
        assert "socket.getaddrinfo(" in lookup and not re.search(r"consume|urlopen|request|send|\.connect", lookup)
    for name in propagated:
        text = (root / name).read_text()
        assert "submit_in_context(" in text and ".submit(" not in text.replace("submit_in_context(", "")
    for name in data_pools:
        assert "provider_call" not in (root / name).read_text()



@pytest.mark.parametrize("concurrent", [False, True])
def test_a_timed_out_runner_buys_no_further_call_after_its_deadline(monkeypatch, concurrent):
    """Counterexample on the base: the runner kept sending after its budget expired."""
    monkeypatch.setattr(inv, "_CANCELLED", {})
    release, finished = threading.Event(), threading.Event()
    outcome: dict = {}

    def slow_runner():
        inv.consume("source_http_get", join=False)
        release.wait(5)
        try:
            inv.consume("source_http_get", join=False)
            outcome["late"] = "sent"
        except inv.OperationCancelled as exc:
            outcome["late"] = exc.reason
        finally:
            finished.set()

    runner = scheduler.SourceRunner("invented_slow", slow_runner)
    run: dict = {}
    before = inv.runtime_counts().get("source_http_get", 0)
    scheduler.run_stage1_sources(_bot_state(), run, serial_runners=[] if concurrent else [runner],
                                 concurrent_runners=[runner] if concurrent else [], budget_seconds=0.2)
    release.set()
    assert finished.wait(5)
    assert outcome["late"] == "runner_budget_exceeded"
    assert inv.runtime_counts()["source_http_get"] == before + 1  # Only the in-budget call was made.
    assert inv.unjoined_calls()["cancelled_before_egress"] == [{"stage": "source_http_get", "refused_calls": 1}]


def test_an_uncancelled_token_changes_nothing():
    token = inv.CancelToken("invented")
    assert inv.run_cancellable(token, lambda: inv.consume("source_http_get", join=False).stage) == "source_http_get"
    token.cancel("first")
    token.cancel("second")
    with pytest.raises(inv.OperationCancelled, match="first"):
        inv.run_cancellable(token, inv.consume, "source_http_get", join=False)
