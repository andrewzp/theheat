"""Batch submission evidence through the installed Anthropic SDK and an INVENTED
offline MockTransport; local grants use the real SQLite authority.

No provider is contacted. A physical-send witness (the MockTransport handler)
is compared with the archive's own witness. These fixtures prove mechanical
capture and unchanged authority behavior, never provider truth or billing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.two_bot import batch_transport as batch, request_archive as archive
from src.two_bot.provider_http import anthropic_httpx
from src.voice import safety
from tests import test_batch_worker_journal as workers, test_spend_journal as spend
from tests.two_bot import test_batch_contract as contracts

httpx = anthropic_httpx()
inputs = contracts.inputs
store = workers.store
CANARIES = ("canary-batch-key-R2D7-never-archive", "canary-cookie-V9Q4-never-archive",
            "canary-error-body-K3M8-never-archive")


class Clock:
    seconds = 0

    def __call__(self):
        return workers.later(self.seconds)


def private_root(base: Path, name: str = "private-archive") -> Path:
    root = base / name
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    return root


def manifest(scope) -> list[dict]:
    raw = archive.read_private_file(scope.directory / archive.MANIFEST, 1 << 22)
    return [archive.strict_json_loads(line) for line in raw.split(b"\n") if line]


def records(scope, kind) -> list[dict]:
    return [row["data"] for row in manifest(scope) if row["type"] == kind]


def artifact(scope, digest) -> bytes:
    return archive.read_private_file(scope.directory / archive.ARTIFACTS / digest, 1 << 22)


def all_bytes(scope) -> bytes:
    data = archive.read_private_file(scope.directory / archive.MANIFEST, 1 << 22)
    for name in os.listdir(scope.directory / archive.ARTIFACTS):
        data += archive.read_private_file(scope.directory / archive.ARTIFACTS / name, 1 << 22)
    return data


class Provider:
    """Invented offline Anthropic batch endpoint; every physical send is witnessed."""

    def __init__(self, respond=None):
        self.requests: list = []
        self.respond = respond

    def __call__(self, request):
        request.read()
        assert request.url.host == "api.anthropic.com", "external network trapped"
        self.requests.append(request)
        if self.respond is not None:
            return self.respond(request)
        return httpx.Response(200, content=workers.ack(), headers={
            "content-type": "application/json", "request-id": "req_invented_batch_1",
            "set-cookie": f"session={CANARIES[1]}"})


def sdk_factory(provider, made=None):
    def factory():
        client = httpx.Client(transport=httpx.MockTransport(provider))
        transport = batch.AnthropicBatchTransport(api_key=CANARIES[0], http_client=client)
        if made is not None:
            made.append((transport, client))
        return transport
    return factory


def fresh_store(tmp_path, name):
    value = SQLiteAuthority(tmp_path / f"{name}.sqlite")
    value.initialize({"drafts": [spend.story()]})
    value.spending("configure", spend.LIMITS, now=spend.NOW)
    return value


@pytest.fixture
def prepared(store, inputs, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-google-key")
    monkeypatch.setenv("WRITER_SAMPLES", "1")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "fixture-loaded-safety-key")
    inputs["policy"] = current_editorial_policy()
    return store, workers.ready(store, inputs), inputs


def run(authority, pair, factory, *, enabled=True, clock=None):
    return batch.submit_batch_once(authority, pair[1]["job_id"], current_context=contracts.context(pair[0]),
                                   owner="worker-one", clock=clock or Clock(), enabled=enabled,
                                   transport_factory=factory)


def actions(authority, monkeypatch):
    seen: list[str] = []
    original = authority.batch_work

    def observed(action, *args, **kwargs):
        seen.append(action)
        return original(action, *args, **kwargs)
    monkeypatch.setattr(authority, "batch_work", observed)
    return seen


def test_disabled_lane_stays_disabled_inside_a_route_scope(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider()
    made: list = []
    before = workers.snapshot(authority)
    with archive.capture(private_root(tmp_path), operation="disabled batch", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider, made), enabled=False)
    assert report["outcome"] == "disabled" and provider.requests == [] and made == []
    assert workers.snapshot(authority) == before
    assert [row["type"] for row in manifest(scope)] == ["scope_opened", "scope_closed"]
    assert manifest(scope)[0]["schema"] == archive.SCHEMA_V2


def test_one_exact_submission_is_witnessed_bound_and_closed(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider()
    with archive.capture(private_root(tmp_path), operation="batch submit", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider))
    assert report["outcome"] == "submitted" and report["provider_batch_id"] == "msgbatch_fixture"
    assert len(provider.requests) == 1
    plan = json.loads(pair[0])
    intent, = records(scope, "route_intent")
    assert intent["family"] == "batch_submit" and intent["expected_path"] == "/v1/messages/batches"
    assert intent["binding"]["job_id"] == {"value": pair[1]["job_id"], "source": "batch_registration"}
    assert intent["binding"]["plan_sha256"]["value"] == workers.digest(pair[0])
    logical = json.loads(artifact(scope, intent["logical_request"]["artifact"]))
    assert logical == {"kwargs": {"requests": plan["requests"]}}
    bound, = records(scope, "route_bound")
    assert report["grant_id"] and bound["binding"]["grant_id"] == {"value": report["grant_id"],
                                                                   "source": "batch_begin_result"}
    wire, = records(scope, "route_wire_request")
    assert wire["method"] == "POST" and wire["path"] == "/v1/messages/batches" and not wire["query_present"]
    assert artifact(scope, wire["body"]["artifact"]) == provider.requests[0].content
    assert wire["observed"]["custom_ids"] == {"availability": "observed",
                                             "values": [row["custom_id"] for row in plan["requests"]]}
    response, = records(scope, "route_response")
    assert artifact(scope, response["body"]["artifact"]) == workers.ack()
    assert response["body"]["form"] == "decoded_http_entity" and response["complete"] is True
    assert response["observed"]["provider_batch_id"] == "msgbatch_fixture"
    assert response["headers"]["request-id"] == "req_invented_batch_1" and "set-cookie" not in response["headers"]
    result, = records(scope, "route_result")
    assert result["outcome"] == "returned" and result["archival"] == "complete" and result["billing"] == "unknown"
    assert result["provider_outcome"] == "response_observed" and result["wire_attempts"] == 1
    assert result["disposition"]["outcome"] == "submitted"
    assert scope.held is None
    assert not any(canary.encode() in all_bytes(scope) for canary in CANARIES)


def test_capture_off_and_on_send_identical_bytes_with_identical_authority_order(prepared, tmp_path, monkeypatch):
    authority, pair, values = prepared
    other = fresh_store(tmp_path, "off")
    off_pair = workers.ready(other, values)
    off_provider, on_provider = Provider(), Provider()
    off_actions, on_actions = actions(other, monkeypatch), actions(authority, monkeypatch)
    off = run(other, off_pair, sdk_factory(off_provider))
    with archive.capture(private_root(tmp_path), operation="parity", routes=True):
        on = run(authority, pair, sdk_factory(on_provider))
    assert [r.content for r in on_provider.requests] == [r.content for r in off_provider.requests]
    assert len(on_provider.requests) == len(off_provider.requests) == 1
    assert on_actions == off_actions
    assert {k: v for k, v in on.items() if k != "grant_id"} == {k: v for k, v in off.items() if k != "grant_id"}


@pytest.mark.parametrize("raw", [b"{", b"null", b"not json at all", workers.ack()[:-7]],
                         ids=["truncated_object", "null", "non_json", "truncated_ack"])
def test_malformed_ack_is_retained_exactly_and_never_names_a_batch(prepared, tmp_path, raw):
    authority, pair, _ = prepared
    provider = Provider(lambda request: httpx.Response(200, content=raw, headers={"content-type": "application/json"}))
    with archive.capture(private_root(tmp_path), operation="malformed ack", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider))
    assert report["outcome"] == "submission_uncertain" and len(provider.requests) == 1
    response, = records(scope, "route_response")
    assert artifact(scope, response["body"]["artifact"]) == raw and "provider_batch_id" not in response["observed"]
    result, = records(scope, "route_result")
    assert result["archival"] == "complete" and result["disposition"]["outcome"] == "submission_uncertain"
    again = Provider()
    assert run(SQLiteAuthority(authority.path), pair, sdk_factory(again))["outcome"] == "not_dispatched"
    assert again.requests == []


@pytest.mark.parametrize("status", [400, 500, 529])
def test_sdk_status_error_after_observed_send_keeps_status_never_error_body(prepared, tmp_path, status):
    authority, pair, _ = prepared
    provider = Provider(lambda request: httpx.Response(
        status, json={"type": "error", "error": {"type": "api_error", "message": CANARIES[2]}}))
    with archive.capture(private_root(tmp_path), operation="status error", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider))
    assert report["outcome"] == "submission_uncertain" and len(provider.requests) == 1
    response, = records(scope, "route_response")
    assert response["status"] == status and response["body"] == {"availability": "not_observed"}
    result, = records(scope, "route_result")
    assert result["outcome"] == "raised" and result["provider_outcome"] == "unknown"
    assert result["archival"] == "complete" and scope.held is None
    assert CANARIES[2].encode() not in all_bytes(scope)


def test_lost_ack_is_unknown_and_never_resubmitted(prepared, tmp_path):
    authority, pair, _ = prepared

    def lost(request):
        raise httpx.ReadTimeout("invented lost acknowledgment", request=request)
    provider = Provider(lost)
    with archive.capture(private_root(tmp_path), operation="lost ack", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider))
    assert report["outcome"] == "submission_uncertain" and len(provider.requests) == 1
    result, = records(scope, "route_result")
    assert result["physical_send_observed"] is True and result["provider_outcome"] == "unknown"
    again = Provider()
    with archive.capture(private_root(tmp_path, "second"), operation="retry refused", routes=True):
        assert run(SQLiteAuthority(authority.path), pair, sdk_factory(again))["outcome"] == "not_dispatched"
    assert again.requests == []


def test_transport_built_outside_the_scope_is_refused_before_any_grant(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider()
    outside = sdk_factory(provider)()
    before = authority.batch_status(pair[1]["job_id"])
    with archive.capture(private_root(tmp_path), operation="unobserved client", routes=True) as scope:
        report = run(authority, pair, lambda: outside)
    assert report["outcome"] == "blocked" and report["reason"] == "archive_refused_before_grant"
    assert provider.requests == [] and authority.batch_status(pair[1]["job_id"]) == before
    assert records(scope, "call_refused")[-1]["reason"] == "archive_unobserved_transport"


def test_synchronous_only_scope_refuses_the_batch_lane(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider()
    with archive.capture(private_root(tmp_path), operation="v1 scope"):
        report = run(authority, pair, sdk_factory(provider))
    assert report["outcome"] == "blocked" and provider.requests == []


@pytest.mark.parametrize("target", ["https://api.anthropic.com/v1/messages/batches?alt=sse",
                                    "https://api.anthropic.com/v1/messages",
                                    "https://example.invalid/v1/messages/batches"])
def test_witness_refuses_wrong_endpoint_or_streaming_query_before_transport(tmp_path, target):
    provider = Provider()
    with archive.capture(private_root(tmp_path), operation="endpoint guard", routes=True) as scope:
        client = httpx.Client(transport=httpx.MockTransport(provider), follow_redirects=False)
        scope.observe_client(client)
        route = scope.begin_route("batch_submit", client=client, expected_path="/v1/messages/batches",
                                  binding={}, logical={"requests": []})
        with pytest.raises(archive.RequestArchiveRefused):
            client.post(target, content=b'{"requests":[]}')
        assert route.refusal == "archive_unsupported_endpoint"
        assert route.finish("refused_before_send") is None
    assert provider.requests == []
    result, = records(scope, "route_result")
    assert result["outcome"] == "refused_before_send" and result["provider_outcome"] == "not_sent"


def test_a_second_send_in_one_route_is_refused_and_holds(tmp_path):
    provider = Provider()
    with archive.capture(private_root(tmp_path), operation="second send", routes=True) as scope:
        client = httpx.Client(transport=httpx.MockTransport(provider), follow_redirects=False)
        scope.observe_client(client)
        scope.begin_route("batch_submit", client=client, expected_path="/v1/messages/batches",
                          binding={}, logical={"requests": []})
        client.post("https://api.anthropic.com/v1/messages/batches", content=b'{"requests":[]}')
        with pytest.raises(archive.RequestArchiveRefused):
            client.post("https://api.anthropic.com/v1/messages/batches", content=b'{"requests":[]}')
        assert scope.held == "archive_second_send_refused"
    assert len(provider.requests) == 1


def test_oversized_ack_is_bounded_by_the_transport_and_retained_as_a_prefix(prepared, tmp_path):
    authority, pair, _ = prepared

    base: Any = httpx.SyncByteStream

    class Stream(base):
        reads = 0

        def __iter__(self):
            for _ in range(100):
                Stream.reads += 1
                yield b"a" * 4096

    provider = Provider(lambda request: httpx.Response(200, stream=Stream(),
                                                       headers={"content-type": "application/json"}))
    with archive.capture(private_root(tmp_path), operation="oversized ack", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider))
    assert report["outcome"] == "submission_uncertain" and Stream.reads < 100
    response, = records(scope, "route_response")
    kept = artifact(scope, response["body"]["artifact"])
    assert len(kept) <= batch.ACK_LIMIT and kept == b"a" * len(kept)
    assert response["complete"] is False and response["reason"] == "batch_ack_read_bound_exceeded"
    assert response["body"]["form"] == "decoded_http_entity_bounded_prefix"


def test_read_time_bound_is_the_transports_own(prepared, tmp_path, monkeypatch):
    authority, pair, _ = prepared
    ticks = iter([0.0] + [1000.0] * 50)
    monkeypatch.setattr(batch, "_monotonic", lambda: next(ticks))
    with archive.capture(private_root(tmp_path), operation="time bound", routes=True) as scope:
        report = run(authority, pair, sdk_factory(Provider()))
    assert report["outcome"] == "submission_uncertain"
    response, = records(scope, "route_response")
    assert response["reason"] == "batch_ack_read_bound_exceeded" and response["complete"] is False


@pytest.mark.parametrize("limit", ["routes", "attempts"])
def test_count_limits_refuse_without_a_physical_send(prepared, tmp_path, monkeypatch, limit):
    authority, pair, _ = prepared
    provider = Provider()
    monkeypatch.setattr(archive, "MAX_CALLS" if limit == "routes" else "MAX_WIRE_ATTEMPTS", 0)
    with archive.capture(private_root(tmp_path), operation="count bound", routes=True):
        report = run(authority, pair, sdk_factory(provider))
    assert provider.requests == []
    if limit == "routes":
        assert report["reason"] == "archive_refused_before_grant"
    else:
        # A refused send after a durable grant is uncertain, never resubmitted.
        assert report["outcome"] == "submission_uncertain"
        assert run(SQLiteAuthority(authority.path), pair, sdk_factory(Provider()))["outcome"] == "not_dispatched"


@pytest.mark.parametrize("failing", ["route_intent", "route_bound", "route_wire_request", "route_response",
                                     "route_result"])
def test_archive_io_failure_refuses_before_send_and_holds_after(prepared, tmp_path, monkeypatch, failing):
    authority, pair, _ = prepared
    provider = Provider()
    original = archive._write_all

    def fail(fd, data):
        if f'"type":"{failing}"'.encode() in data:
            raise OSError("invented disk failure")
        return original(fd, data)
    monkeypatch.setattr(archive, "_write_all", fail)
    with archive.capture(private_root(tmp_path), operation="io failure", routes=True) as scope:
        report = run(authority, pair, sdk_factory(provider))
    sent = failing in ("route_response", "route_result")
    assert len(provider.requests) == (1 if sent else 0)
    if failing == "route_intent":
        assert report["reason"] == "archive_refused_before_grant"
    elif not sent:
        assert report["outcome"] == "submission_uncertain"
    else:
        # After a real send the authority's own outcome is unchanged; evidence is held.
        assert report["outcome"] == "submitted" and scope.held is not None
    again = Provider()
    rerun = run(SQLiteAuthority(authority.path), pair, sdk_factory(again))
    assert again.requests == [] or failing == "route_intent"
    if failing != "route_intent":
        assert rerun["outcome"] == "not_dispatched"


def test_close_failure_keeps_success_and_complete_evidence(prepared, tmp_path, monkeypatch):
    authority, pair, _ = prepared
    made: list = []
    with archive.capture(private_root(tmp_path), operation="close failure", routes=True) as scope:
        def factory():
            transport = sdk_factory(Provider(), made)()
            monkeypatch.setattr(transport, "close", lambda: (_ for _ in ()).throw(RuntimeError(CANARIES[2])))
            return transport
        report = run(authority, pair, factory)
    assert report["outcome"] == "submitted" and report["cleanup_failed"]
    result, = records(scope, "route_result")
    assert result["archival"] == "complete" and CANARIES[2].encode() not in all_bytes(scope)


def test_missing_plan_provenance_is_recorded_as_missing_not_guessed(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider()
    with archive.capture(private_root(tmp_path), operation="missing provenance", routes=True) as scope:
        transport = sdk_factory(provider)()
        try:
            report = batch._attempt(authority, pair[1]["job_id"], contracts.context(pair[0]), "worker-one", Clock(),
                                    transport, json.loads(pair[0])["requests"])
        finally:
            transport.close()
    assert report["outcome"] == "submitted" and len(provider.requests) == 1
    intent, = records(scope, "route_intent")
    assert intent["binding"]["plan_sha256"] == {"value": None, "source": "missing"}
    assert intent["binding"]["policy_sha256"] == {"value": None, "source": "missing"}
