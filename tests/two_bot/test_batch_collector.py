"""Real local recovery plus actual SDK HTTP mocks; no provider or checker calls."""

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import httpx
import pytest

from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.two_bot import batch_collector as collect, batch_transport as batch
from src.voice import safety
from tests import test_batch_result_journal as receipts
from tests import test_batch_worker_journal as workers
from tests.two_bot import test_batch_contract as contracts
from tests.two_bot.test_batch_transport import Clock, sdk_transport

store = workers.store
inputs = workers.inputs


class Reader:
    def __init__(self, metadata, results, *, after_read=None):
        self.metadata = metadata
        self.raw_results = results
        self.calls = []
        self.closed = False
        self.after_read = after_read

    def retrieve(self, identity):
        self.calls.append(("metadata", identity))
        return self.metadata

    def results(self, identity):
        self.calls.append(("results", identity))
        if self.after_read:
            self.after_read()
        return self.raw_results

    def close(self):
        self.closed = True


@pytest.fixture
def submitted(store, inputs, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-google-key")
    monkeypatch.setenv("WRITER_SAMPLES", "1")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "fixture-loaded-safety-key")
    inputs["policy"] = current_editorial_policy()
    pair, grant = receipts.started(store, inputs)
    return store, pair, grant


def reader(pair, **kwargs):
    return Reader(batch.BatchDownload(receipts.metadata(), True),
                  batch.BatchDownload(contracts.raw_rows(receipts.rows(pair)), True), **kwargs)


def run(submitted, transport, *, clock=None, context=None, **kwargs):
    store, pair, _ = submitted
    return collect.collect_batch_once(
        store, pair[1]["job_id"], current_context=context or contracts.context(pair[0]),
        owner="worker-one", clock=clock or Clock(), enabled=True,
        transport_factory=lambda: transport, **kwargs,
    )


def test_off_does_not_inspect_credentials_store_clock_or_factory():
    store, clock, factory = Mock(), Mock(), Mock()
    assert collect.collect_batch_once(
        store, "job", current_context={}, owner="worker", clock=clock, transport_factory=factory
    )["outcome"] == "disabled"
    assert not store.mock_calls and not clock.mock_calls and not factory.mock_calls


@pytest.mark.parametrize("field,value", [("enabled", 1), ("enabled", "true"), ("refresh", 1)])
def test_flag_types_are_explicit_without_io(field, value):
    with pytest.raises(batch.BatchTransportError, match="boolean"):
        collect.collect_batch_once(Mock(), "job", current_context={}, owner="worker", clock=Mock(),
                                   **{field: value})


def test_complete_download_is_retained_and_reviewed_without_draft_or_spend_change(submitted):
    store, pair, _ = submitted
    before = store.read()
    spend_before = store.spending("status", {}, now=workers.NOW)
    transport = reader(pair)
    report = run(submitted, transport)
    assert report["outcome"] == "reviewed" and transport.closed
    assert transport.calls == [("metadata", "msgbatch_fixture"), ("results", "msgbatch_fixture")]
    assert store.read_artifact(workers.digest(transport.raw_results.raw)) == transport.raw_results.raw
    assert report["review"]["report"]["rows"][0]["eligible_for_checks"]
    assert not report["publication_approved"] and not report["required_checks_completed"]
    assert report["cost_usd"] is None and not report["accounting_complete"]
    assert store.read() == before and store.spending("status", {}, now=workers.NOW) == spend_before


def test_restart_reuses_retained_bytes_without_transport_or_any_provider_key(submitted, monkeypatch):
    store, pair, grant = submitted
    initial = run(submitted, reader(pair))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("GEMINI_API_KEY")
    transport = Mock()
    recovered = run((SQLiteAuthority(store.path), pair, grant), transport)
    assert recovered["outcome"] == "reviewed" and not transport.mock_calls
    assert recovered["review"]["review_id"] == initial["review"]["review_id"]
    assert recovered["review"]["reused"]


def test_collection_does_not_need_mandatory_checker_credentials(submitted, monkeypatch):
    _, pair, _ = submitted
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    report = run(submitted, reader(pair))
    assert report["outcome"] == "reviewed" and not report["required_checks_completed"]


def test_missing_read_key_blocks_before_transport(submitted, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    transport = Mock()
    report = run(submitted, transport)
    assert report["reason"] == "missing_batch_read_credential" and not transport.mock_calls


@pytest.mark.parametrize("state", ["in_progress", "canceling"])
def test_nonterminal_metadata_is_one_get_observation_without_receipt_or_loop(submitted, state):
    store, pair, _ = submitted
    transport = reader(pair)
    transport.metadata = batch.BatchDownload(workers.ack(processing_status=state), True)
    assert run(submitted, transport)["outcome"] == "pending"
    assert len(transport.calls) == 1 and transport.closed
    assert store.batch_results_status(pair[1]["job_id"], now=workers.NOW)["receipts"] == []


@pytest.mark.parametrize("raw,complete", [(b"{", True), (receipts.metadata(), False),
                                          (receipts.metadata(id="msgbatch_other"), True)])
def test_invalid_metadata_is_retained_without_result_get(submitted, raw, complete):
    store, pair, _ = submitted
    transport = reader(pair)
    transport.metadata = batch.BatchDownload(raw, complete, "SECRET not echoed")
    report = run(submitted, transport)
    assert len(transport.calls) == 1 and transport.closed
    assert report["outcome"] == "reviewed"
    assert store.read_artifact(workers.digest(raw)) == raw
    assert "SECRET" not in json.dumps(report) and not report["publication_approved"]
    assert not report["review"]["report"]["complete"]


def test_partial_download_recovers_on_next_read_without_new_submission(submitted):
    store, pair, _ = submitted
    first = reader(pair)
    first.raw_results = replace(first.raw_results, complete=False)
    partial = run(submitted, first)
    assert not partial["review"]["report"]["rows"][0]["eligible_for_checks"]
    second = reader(pair)
    recovered = run(submitted, second)
    assert recovered["review"]["report"]["rows"][0]["eligible_for_checks"] and len(second.calls) == 2
    assert store.spending("status", {}, now=workers.NOW)["intent_count"] == 1


@pytest.mark.parametrize("phase", ["record", "review"])
def test_lost_commit_acknowledgment_recovers_from_database_without_second_download(submitted, monkeypatch, phase):
    store, pair, grant = submitted
    method = "record_batch_results" if phase == "record" else "review_batch_results"
    real = getattr(store, method)

    def lost(*args, **kwargs):
        real(*args, **kwargs)
        raise OSError("SECRET acknowledgment lost")

    monkeypatch.setattr(store, method, lost)
    initial = run(submitted, reader(pair))
    assert initial["outcome"] in {"retained", "reconciliation_required"}
    transport = Mock()
    restarted = run((SQLiteAuthority(store.path), pair, grant), transport)
    assert restarted["outcome"] == "reviewed" and not transport.mock_calls
    assert "SECRET" not in json.dumps(initial)


def test_expired_worker_keeps_result_bytes_but_cannot_review(submitted):
    store, pair, grant = submitted
    clock = Clock()
    transport = reader(pair, after_read=lambda: setattr(clock, "seconds", 300))
    initial = run(submitted, transport, clock=clock)
    assert initial["outcome"] == "retained" and initial["reason"] == "current_review_unavailable"
    assert store.read_artifact(workers.digest(transport.raw_results.raw)) == transport.raw_results.raw
    recovered = run((SQLiteAuthority(store.path), pair, grant), Mock(), clock=clock)
    assert recovered["outcome"] == "reviewed" and recovered["review"]["binding"]["fence"] == 2


@pytest.mark.parametrize("key", ["bundle_sha256", "memory_sha256", "publication_epoch"])
def test_changed_current_context_retains_usage_but_withholds_text(submitted, key):
    _, pair, _ = submitted
    context = contracts.context(pair[0])
    context[key] = "changed-epoch" if key == "publication_epoch" else "e" * 64
    report = run(submitted, reader(pair), context=context)["review"]["report"]
    assert report["rows"][0]["usage"]["input_tokens"] == 17
    assert not report["rows"][0]["eligible_for_checks"]


def test_actual_loaded_policy_overrides_stale_caller_policy_before_review(submitted, monkeypatch):
    _, pair, _ = submitted
    monkeypatch.setattr(safety, "GEMINI_SAFETY_MODEL", "new-model")
    report = run(submitted, reader(pair))["review"]
    assert report["binding"]["current_context"]["policy_sha256"] != contracts.context(pair[0])["policy_sha256"]
    assert not report["report"]["rows"][0]["eligible_for_checks"]


def test_policy_unavailable_still_retains_usage_evidence(submitted, monkeypatch):
    store, pair, _ = submitted
    monkeypatch.setattr("src.editorial.policy.current_editorial_policy", lambda: None)
    transport = reader(pair)
    report = run(submitted, transport)
    assert report["outcome"] == "retained" and report["reason"] == "runtime_policy_unavailable"
    assert store.read_artifact(workers.digest(transport.raw_results.raw)) == transport.raw_results.raw


def test_expired_job_is_collected_for_accounting_without_usable_text(submitted):
    _, pair, _ = submitted
    report = run(submitted, reader(pair), clock=lambda: json.loads(pair[0])["useful_until"])
    assert report["outcome"] == "reviewed"
    assert "expired" in report["review"]["report"]["context_blocked_reasons"]
    assert report["review"]["report"]["rows"][0]["usage"]


def test_explicit_refresh_detects_conflicting_complete_output_and_invalidates_prior_text(submitted):
    _, pair, _ = submitted
    run(submitted, reader(pair))
    other = reader(pair)
    row = receipts.rows(pair)[0]
    row["result"]["message"]["usage"]["input_tokens"] += 1
    other.raw_results = batch.BatchDownload(contracts.raw_rows([row]), True)
    refreshed = run(submitted, other, refresh=True)
    assert len(other.calls) == 2
    assert "conflicting_complete_results" in refreshed["review"]["report"]["context_blocked_reasons"]
    cached = run(submitted, Mock())
    assert not cached["review"]["report"]["rows"][0]["eligible_for_checks"]


def test_late_conflicting_provider_id_blocks_cached_text_without_network(submitted):
    store, pair, grant = submitted
    run(submitted, reader(pair))
    workers.observe(store, grant, workers.ack(id="msgbatch_conflict"))
    report = run(submitted, Mock())
    assert report["outcome"] == "reviewed"
    assert not report["review"]["report"]["rows"][0]["eligible_for_checks"]


def test_metadata_read_exception_returns_bounded_reason_and_closes(submitted):
    transport = Mock()
    transport.retrieve.side_effect = RuntimeError("SECRET unpublished data")
    result = run(submitted, transport)
    assert result["outcome"] == "read_failed" and "SECRET" not in json.dumps(result)
    transport.close.assert_called_once()
    transport.results.assert_not_called()


def test_result_read_exception_preserves_terminal_metadata(submitted):
    store, pair, _ = submitted
    transport = Mock()
    transport.retrieve.return_value = batch.BatchDownload(receipts.metadata(), True)
    transport.results.side_effect = RuntimeError("SECRET unpublished data")
    result = run(submitted, transport)
    assert result["outcome"] == "reviewed" and "SECRET" not in json.dumps(result)
    assert store.read_artifact(workers.digest(receipts.metadata())) == receipts.metadata()
    transport.close.assert_called_once()


def test_cleanup_failure_cannot_undo_retained_evidence_or_resend(submitted):
    _, pair, _ = submitted
    transport = reader(pair)
    transport.close = Mock(side_effect=RuntimeError("SECRET"))
    report = run(submitted, transport)
    assert report["outcome"] == "reviewed" and report["cleanup_failed"]
    assert len(transport.calls) == 2 and "SECRET" not in json.dumps(report)


def test_capacity_blocks_new_read_but_exact_retained_review_still_works(submitted):
    store, pair, grant = submitted
    for i in range(16):
        receipts.retain(store, grant, str(i).encode(), complete=False)
    transport = Mock()
    assert run(submitted, transport)["reason"] == "batch_result_capacity_reached"
    assert not transport.mock_calls


def test_actual_sdk_gets_only_fixed_routes_ignoring_supplied_result_url(submitted, monkeypatch):
    _, pair, _ = submitted
    requests = []
    meta = json.loads(receipts.metadata())
    meta["results_url"] = "https://untrusted.invalid/steal-key"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://untrusted.invalid")

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/results"):
            return httpx.Response(200, content=contracts.raw_rows(receipts.rows(pair)))
        return httpx.Response(200, json=meta)

    transport, client = sdk_transport(handler)
    assert run(submitted, transport)["outcome"] == "reviewed" and client.is_closed
    assert [r.method for r in requests] == ["GET", "GET"]
    assert [r.url.path for r in requests] == ["/v1/messages/batches/msgbatch_fixture",
                                            "/v1/messages/batches/msgbatch_fixture/results"]
    assert all(r.url.host == "api.anthropic.com" for r in requests)
    assert all(r.extensions["timeout"]["read"] == 30 for r in requests)


@pytest.mark.parametrize("status", [302, 307, 401, 429, 500])
def test_actual_sdk_http_failure_never_retries_or_redirects(submitted, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://untrusted.invalid"},
                              json={"error": {"message": "SECRET private body"}})

    transport, client = sdk_transport(handler)
    report = run(submitted, transport)
    assert len(requests) == 1 and client.is_closed and "SECRET" not in json.dumps(report)
    assert not report["publication_approved"]


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks, *, error=None):
        self.chunks = chunks
        self.error = error
        self.reads = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


@pytest.mark.parametrize("result,bound", [(False, batch.ACK_LIMIT), (True, collect.MAX_RESULT_BYTES)])
def test_actual_sdk_bounds_download_bytes_and_marks_partial(result, bound):
    stream = Stream([b"x" * 4096] * ((bound // 4096) + 50))
    transport, client = sdk_transport(lambda req: httpx.Response(200, stream=stream))
    value = (transport.results if result else transport.retrieve)("msgbatch_fixture")
    transport.close()
    assert len(value.raw) == bound and not value.complete and value.reason == "batch_read_size_exceeded"
    assert stream.reads == bound // 4096 + 1 and stream.closed and client.is_closed


def test_actual_sdk_exact_byte_limit_at_eof_is_complete():
    transport, client = sdk_transport(lambda req: httpx.Response(200, content=b"x" * batch.ACK_LIMIT))
    value = transport.retrieve("msgbatch_fixture")
    transport.close()
    assert len(value.raw) == batch.ACK_LIMIT and value.complete and client.is_closed


def test_actual_sdk_midstream_failure_preserves_received_prefix():
    stream = Stream([b"x" * 4096], error=httpx.ReadTimeout("SECRET timeout"))
    transport, client = sdk_transport(lambda req: httpx.Response(200, stream=stream))
    value = transport.results("msgbatch_fixture")
    transport.close()
    assert value.raw == b"x" * 4096 and not value.complete
    assert value.reason == "batch_read_unavailable" and stream.closed and client.is_closed


def test_actual_sdk_elapsed_bound_preserves_partial_bytes(monkeypatch):
    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(batch, "_monotonic", lambda: next(ticks))
    stream = Stream([b"x" * 4096] * 3)
    transport, client = sdk_transport(lambda req: httpx.Response(200, stream=stream))
    value = transport.results("msgbatch_fixture")
    transport.close()
    assert not value.complete and value.reason == "batch_read_time_exceeded"
    assert value.raw == b"x" * 4096 and stream.reads == 1 and stream.closed and client.is_closed


@pytest.mark.parametrize("identity", ["../other", "https://untrusted.invalid", "msgbatch_a/results", "msgbatch_", 1])
def test_transport_rejects_unknown_provider_id_before_http(identity):
    handler = Mock()
    transport, client = sdk_transport(handler)
    with pytest.raises(batch.BatchTransportError, match="invalid_provider"):
        transport.results(identity)
    transport.close()
    assert not handler.mock_calls and client.is_closed


def test_actual_sdk_response_close_failure_preserves_bounded_evidence():
    class BadClose(Stream):
        def close(self):
            raise OSError("SECRET close")

    stream = BadClose([b"x" * 4096])
    transport, client = sdk_transport(lambda req: httpx.Response(200, stream=stream))
    value = transport.results("msgbatch_fixture")
    transport.close()
    assert value.raw == b"x" * 4096 and not value.complete
    assert value.reason in {"batch_read_cleanup_failed", "batch_read_unavailable"}
    assert client.is_closed


def test_actual_sdk_connect_timeout_makes_one_get_with_no_resubmission(submitted):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout("SECRET")

    transport, client = sdk_transport(handler)
    report = run(submitted, transport)
    assert len(calls) == 1 and calls[0].method == "GET" and client.is_closed
    assert "SECRET" not in json.dumps(report)
    assert not report["required_checks_completed"]


def test_no_confirmed_submission_never_opens_reader(store, inputs, monkeypatch):
    pair, grant = receipts.started(store, inputs, adopted=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    transport = Mock()
    result = run((store, pair, grant), transport)
    assert result["reason"] == "batch_submission_not_confirmed" and not transport.mock_calls


@pytest.mark.parametrize("value", [None, batch.BatchDownload(b"x", 1),
                                   batch.BatchDownload(b"x" * (batch.ACK_LIMIT + 1), True)])
def test_malformed_transport_download_does_not_bypass_bounds(submitted, value):
    _, pair, _ = submitted
    transport = reader(pair)
    transport.metadata = value
    report = run(submitted, transport)
    assert report["outcome"] == "read_failed" and transport.closed and len(transport.calls) == 1
