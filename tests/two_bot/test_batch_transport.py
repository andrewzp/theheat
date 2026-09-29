"""No paid calls: actual SDK uses MockTransport; local grants use real SQLite."""

from copy import deepcopy
import json
from unittest.mock import Mock

import httpx
import pytest

from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.two_bot import batch_transport as batch
from src.voice import safety
from tests import test_batch_worker_journal as workers
from tests.two_bot import test_batch_contract as contracts

inputs = contracts.inputs
store = workers.store


class Clock:
    seconds = 0

    def __call__(self):
        return workers.later(self.seconds)


class FakeTransport:
    def __init__(self, raw=None, on_submit=None):
        self.raw = workers.ack() if raw is None else raw
        self.on_submit = on_submit
        self.calls = []
        self.closed = False

    def submit(self, requests):
        self.calls.append(deepcopy(requests))
        if self.on_submit:
            self.on_submit()
        return self.raw

    def close(self):
        self.closed = True


@pytest.fixture
def prepared(store, inputs, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-google-key")
    monkeypatch.setenv("WRITER_SAMPLES", "1")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "fixture-loaded-safety-key")
    inputs["policy"] = current_editorial_policy()
    pair = workers.ready(store, inputs)
    return store, pair


def run(prepared, transport, *, clock=None, **kwargs):
    authority, pair = prepared
    return batch.submit_batch_once(
        authority,
        pair[1]["job_id"],
        current_context=contracts.context(pair[0]),
        owner="worker-one",
        clock=clock or Clock(),
        enabled=True,
        transport_factory=lambda: transport,
        **kwargs,
    )


def test_off_by_default_performs_no_authority_clock_or_transport_io():
    authority, clock, factory = Mock(), Mock(), Mock()
    report = batch.submit_batch_once(
        authority, "job", current_context={}, owner="owner", clock=clock, transport_factory=factory
    )
    assert report["outcome"] == "disabled" and not report["dispatch_granted"]
    authority.assert_not_called()
    assert not authority.mock_calls
    clock.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_nonboolean_activation_is_refused_without_io(flag):
    with pytest.raises(batch.BatchTransportError, match="boolean"):
        batch.submit_batch_once(
            None, "job", current_context={}, owner="owner", clock=Mock(), enabled=flag
        )


def test_exact_requests_submit_once_then_replay_cannot_send_again(prepared):
    authority, pair = prepared
    transport = FakeTransport()
    before = authority.read()
    report = run(prepared, transport)
    assert report["outcome"] == "submitted" and report["provider_batch_id"] == "msgbatch_fixture"
    assert transport.calls == [json.loads(pair[0])["requests"]] and transport.closed
    assert authority.read_artifact(workers.digest(transport.raw)) == transport.raw
    assert (
        not report["dispatch_granted"]
        and not report["publication_approved"]
        and not report["collection_granted"]
    )
    replay_transport = FakeTransport()
    replay = run((SQLiteAuthority(authority.path), pair), replay_transport)
    assert (
        replay["outcome"] == "not_dispatched"
        and replay_transport.calls == []
        and replay_transport.closed
    )
    assert authority.read() == before
    assert authority.spending("status", {}, now=workers.NOW)["totals"]["held_micro_usd"] == 60


@pytest.mark.parametrize("key", ["ANTHROPIC_API_KEY", "GEMINI_API_KEY"])
def test_missing_required_credential_blocks_before_factory_and_grant(prepared, monkeypatch, key):
    authority, pair = prepared
    monkeypatch.delenv(key)
    factory = Mock()
    before = workers.snapshot(authority)
    report = batch.submit_batch_once(
        authority,
        pair[1]["job_id"],
        current_context=contracts.context(pair[0]),
        owner="worker-one",
        clock=Clock(),
        enabled=True,
        transport_factory=factory,
    )
    assert report["reason"] == "missing_provider_prerequisite"
    factory.assert_not_called()
    assert workers.snapshot(authority) == before


def test_changed_loaded_policy_blocks_before_factory(prepared, monkeypatch):
    authority, pair = prepared
    monkeypatch.setattr(safety, "GEMINI_SAFETY_MODEL", "changed-model")
    factory = Mock()
    report = batch.submit_batch_once(
        authority,
        pair[1]["job_id"],
        current_context=contracts.context(pair[0]),
        owner="worker-one",
        clock=Clock(),
        enabled=True,
        transport_factory=factory,
    )
    assert report["reason"] == "changed_runtime_policy"
    factory.assert_not_called()
    assert authority.batch_status(pair[1]["job_id"])["reservation_state"] == "reserved"


def test_changed_current_evidence_refuses_at_grant_and_closes_transport(prepared):
    authority, pair = prepared
    context = contracts.context(pair[0])
    context["bundle_sha256"] = "f" * 64
    transport = FakeTransport()
    report = batch.submit_batch_once(
        authority,
        pair[1]["job_id"],
        current_context=context,
        owner="worker-one",
        clock=Clock(),
        enabled=True,
        transport_factory=lambda: transport,
    )
    assert report["outcome"] == "blocked" and not transport.calls and transport.closed
    assert authority.batch_status(pair[1]["job_id"])["reservation_state"] == "reserved"


def test_transport_failure_is_unknown_charge_without_exception_body_or_retry(prepared):
    authority, pair = prepared

    def fail():
        raise RuntimeError("SECRET_API_KEY private prompt exception body")

    transport = FakeTransport(on_submit=fail)
    report = run(prepared, transport)
    assert (
        report["outcome"] == "submission_uncertain"
        and len(transport.calls) == 1
        and transport.closed
    )
    assert "SECRET" not in json.dumps(report) and "private prompt" not in json.dumps(report)
    again = FakeTransport()
    assert run(prepared, again)["outcome"] == "not_dispatched" and not again.calls
    assert (
        authority.spending("status", {}, now="2027-01-01T00:00:00Z")["totals"]["held_micro_usd"]
        == 60
    )


def test_delayed_response_is_retained_without_expired_owner_adoption(prepared):
    authority, pair = prepared
    clock = Clock()

    def delayed():
        clock.seconds = 61

    transport = FakeTransport(on_submit=delayed)
    report = run(prepared, transport, clock=clock)
    assert (
        report["outcome"] == "acknowledgment_retained" and report["state"] == "submission_uncertain"
    )
    assert authority.read_artifact(workers.digest(transport.raw)) == transport.raw
    assert report["provider_batch_id"] is None and transport.closed


@pytest.mark.parametrize("raw", [b"{", b"null", workers.ack(processing_status="made-up")])
def test_malformed_ack_retained_before_marking_uncertainty(prepared, raw):
    authority, pair = prepared
    transport = FakeTransport(raw=raw)
    report = run(prepared, transport)
    assert report["outcome"] == "submission_uncertain"
    assert authority.read_artifact(workers.digest(raw)) == raw
    assert authority.spending("status", {}, now=workers.NOW)["totals"]["held_micro_usd"] == 60


def test_oversized_transport_output_keeps_attempt_without_unbounded_receipt(prepared):
    authority, pair = prepared
    report = run(prepared, FakeTransport(raw=b"a" * 65537))
    assert report["outcome"] == "submission_uncertain"
    assert workers.call(authority, "status")["receipt_count"] == 0


@pytest.mark.parametrize(
    "boundary", ["begin_before", "begin_after", "observe_before", "observe_after", "adopt_after"]
)
def test_lost_database_acknowledgments_never_repeat_provider_request(
    prepared, monkeypatch, boundary
):
    authority, pair = prepared
    original = authority.batch_work
    action, when = boundary.split("_")

    def fault(name, *args, **kwargs):
        if name == action and when == "before":
            raise OSError("sensitive local error")
        result = original(name, *args, **kwargs)
        if name == action and when == "after":
            raise OSError("sensitive local error")
        return result

    monkeypatch.setattr(authority, "batch_work", fault)
    transport = FakeTransport()
    result = run(prepared, transport)
    assert "sensitive" not in json.dumps(result)
    assert len(transport.calls) == (0 if action == "begin" else 1)
    monkeypatch.setattr(authority, "batch_work", original)
    if boundary != "begin_before":
        again = FakeTransport()
        assert run(prepared, again)["outcome"] == "not_dispatched" and not again.calls
    assert transport.closed


def test_cleanup_error_cannot_erase_success_or_prompt_resubmission(prepared):
    transport = FakeTransport()
    transport.close = Mock(side_effect=RuntimeError("secret cleanup error"))
    report = run(prepared, transport)
    assert report["outcome"] == "submitted" and report["cleanup_failed"]
    assert "secret" not in json.dumps(report)


def sdk_transport(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = batch.AnthropicBatchTransport(api_key="offline-fixture-key", http_client=client)
    return transport, client


def test_actual_sdk_http_request_uses_exact_plan_and_fixed_api_origin(prepared, monkeypatch):
    _, pair = prepared
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://untrusted.invalid")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, content=workers.ack(), headers={"content-type": "application/json"}
        )

    transport, client = sdk_transport(handler)
    assert run(prepared, transport)["outcome"] == "submitted"
    assert client.is_closed and len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages/batches"
    assert request.method == "POST" and json.loads(request.content) == {
        "requests": json.loads(pair[0])["requests"]
    }
    assert request.extensions["timeout"] == {"connect": 30, "read": 30, "write": 30, "pool": 30}


@pytest.mark.parametrize("status", [400, 401, 429, 500, 529, "timeout"])
def test_actual_sdk_has_one_http_attempt_on_error_and_no_secret_leak(prepared, status):
    requests = []

    def handler(request):
        requests.append(request)
        if status == "timeout":
            raise httpx.ReadTimeout("SECRET_API_KEY unpublished prompt", request=request)
        return httpx.Response(
            status,
            json={
                "type": "error",
                "error": {"type": "api_error", "message": "SECRET_API_KEY unpublished prompt"},
            },
        )

    transport, client = sdk_transport(handler)
    report = run(prepared, transport)
    assert len(requests) == 1 and client.is_closed
    assert report["outcome"] == "submission_uncertain"
    assert "SECRET" not in json.dumps(report) and "unpublished" not in json.dumps(report)


def test_actual_sdk_oversized_success_is_not_fully_consumed(prepared):
    class Stream(httpx.SyncByteStream):
        reads = 0
        closed = False

        def __iter__(self):
            for _ in range(100):
                self.reads += 1
                yield b"a" * 4096

        def close(self):
            self.closed = True

    stream = Stream()
    transport, client = sdk_transport(
        lambda request: httpx.Response(
            200, stream=stream, headers={"content-type": "application/json"}
        )
    )
    report = run(prepared, transport)
    assert report["outcome"] == "submission_uncertain" and stream.reads == 17
    assert stream.closed and client.is_closed


def test_actual_sdk_read_elapsed_bound_preserves_uncertain_hold(prepared, monkeypatch):
    ticks = iter([0.0, 31.0])
    transport, client = sdk_transport(
        lambda request: httpx.Response(
            200, content=workers.ack(), headers={"content-type": "application/json"}
        )
    )
    monkeypatch.setattr(batch, "_monotonic", lambda: next(ticks))
    report = run(prepared, transport)
    assert report["outcome"] == "submission_uncertain" and client.is_closed


@pytest.mark.parametrize("status", [302, 307])
def test_redirect_cannot_repeat_post_or_forward_key_to_other_origin(prepared, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://untrusted.invalid/capture"})

    transport, client = sdk_transport(handler)
    assert run(prepared, transport)["outcome"] == "submission_uncertain"
    assert len(requests) == 1 and client.is_closed
    assert requests[0].url.host == "api.anthropic.com"


def test_real_default_client_disables_redirects_without_opening_network():
    transport = batch.AnthropicBatchTransport(api_key="offline-fixture")
    client = transport._client._client
    assert not client.follow_redirects and transport._client.max_retries == 0
    transport.close()
    assert client.is_closed


def test_redirect_enabled_injected_client_is_refused():
    with httpx.Client(follow_redirects=True, transport=httpx.MockTransport(Mock())) as client:
        with pytest.raises(batch.BatchTransportError, match="redirects"):
            batch.AnthropicBatchTransport(api_key="offline-fixture", http_client=client)


def test_unbounded_identity_is_not_echoed_or_sent():
    authority, factory = Mock(), Mock()
    report = batch.submit_batch_once(
        authority,
        "a" * 10000,
        current_context={},
        owner="worker",
        clock=Clock(),
        enabled=True,
        transport_factory=factory,
    )
    assert report["reason"] == "invalid_batch_identity" and len(json.dumps(report)) < 400
    assert not authority.mock_calls and not factory.mock_calls
