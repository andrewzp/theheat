"""Actual Anthropic SDK wire/capture tests; invented HTTP and grants only."""
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import threading
import time

import pytest

from src.commands.schema import canonical_json
from src.two_bot import synchronous_writer as sync, writer
from src.two_bot.provider_http import anthropic_httpx

http = anthropic_httpx()
KEY = "invented-offline-key"


def request():
    return writer.anthropic_writer_request("INVENTED LOCAL TRANSPORT FIXTURE; no source claim.")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def envelope():
    return json.dumps(dict(
        id="msg_invented", type="message", role="assistant", model=writer.WRITER_MODEL,
        content=[dict(type="text", text='{"tweet":"Invented transport example."}')],
        stop_reason="end_turn", stop_sequence=None,
        usage=dict(input_tokens=11, output_tokens=7),
    )).encode()


def run(response=None, *, params=None, grant=None, headers=None, monkeypatch=None):
    params = request() if params is None else params
    sent, grants, clients = [], [], []
    expected = canonical_json(params).encode()

    def authorize(wire):
        grants.append(wire)
        if grant is not None:
            return grant(wire)
        return sync.WriterDispatchGrant("a" * 64, digest(expected), digest(wire))

    def handle(value):
        assert len(grants) == 1
        sent.append(value)
        reply = envelope() if response is None else response
        if isinstance(reply, Exception):
            raise reply
        status, raw = reply if isinstance(reply, tuple) else (200, reply)
        stream = raw if isinstance(raw, http.SyncByteStream) else http.ByteStream(raw)
        return http.Response(status, stream=stream, headers=headers, request=value)

    if monkeypatch is not None:
        original = sync._capture_client

        def capture(*args, **kwargs):
            client = original(*args, **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(sync, "_capture_client", capture)
    result = sync.execute_writer_once(params, api_key=KEY, authorize=authorize,
                                      enabled=True, http_transport=http.MockTransport(handle))
    return result, sent, grants, clients


def test_disabled_does_not_validate_build_authorize_or_create_transport(monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("disabled writer must do no work")
    monkeypatch.setattr(sync, "_request_bytes", forbidden)
    monkeypatch.setattr(sync, "_capture_client", forbidden)
    result = sync.execute_writer_once(None, api_key=None, authorize=forbidden)
    assert result == sync.WriterObservation(reason="disabled", grant_status="disabled")


def test_actual_sdk_uses_exact_shared_request_one_grant_and_retains_original_bytes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://invented-invalid.example")
    monkeypatch.setenv("HTTPS_PROXY", "http://invented-invalid.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-use-ambient-key")
    params = request()
    before = deepcopy(params)
    result, sent, grants, clients = run(params=params, monkeypatch=monkeypatch)
    assert len(sent) == len(grants) == 1
    assert sent[0].method == "POST" and str(sent[0].url) == sync.ENDPOINT
    assert json.loads(sent[0].content) == params == before
    assert sent[0].headers["x-api-key"] == KEY
    assert sent[0].headers["accept-encoding"] == "identity"
    assert set(sent[0].extensions["timeout"].values()) == {15}
    assert result.wire == sent[0].content == grants[0]
    assert result.raw == envelope() and result.http_status == 200 and result.complete
    assert result.grant_status == "granted" and result.grant_id == "a" * 64
    assert clients and all(client.is_closed for client in clients)
    assert KEY not in repr(result) and "INVENTED LOCAL" not in repr(result)
    assert not hasattr(result, "candidate") and not hasattr(result, "cost_usd")


@pytest.mark.parametrize("status", [200, 400, 401, 403, 408, 409, 429, 500, 503, 307])
def test_returned_error_or_bad_model_bytes_survive_sdk_errors_without_retry(status):
    raw = b'{"private":"invented provider diagnostic with missing required fields"}'
    result, sent, grants, _ = run((status, raw), headers={"location": "https://invalid.example/"})
    assert len(sent) == len(grants) == 1
    assert result.raw == raw and result.complete and result.http_status == status
    assert result.reason == "received" and result.grant_status == "granted"


@pytest.mark.parametrize("raw", [b"", b"not json", b"\xff", b'{"usage":null}', b'{"usage":{"input_tokens":true}}'])
def test_raw_retention_does_not_depend_on_sdk_or_usage_parsing(raw):
    result, sent, grants, _ = run(raw)
    assert result.raw == raw and result.complete
    assert len(sent) == len(grants) == 1


def test_socket_error_is_one_unknown_attempt_with_no_exception_body():
    result, sent, grants, _ = run(http.ReadTimeout("secret diagnostic " + KEY))
    assert len(sent) == len(grants) == 1
    assert not result.complete and result.http_status is None and result.raw == b""
    assert result.grant_status == "granted" and result.reason == "transport_unavailable"
    assert KEY not in repr(result)


@pytest.mark.parametrize("mode", ["refused", "lost_commit", "bad_type", "bad_id", "wrong_request", "wrong_wire"])
def test_unacknowledged_or_mismatched_grant_never_sends(mode):
    def authorize(wire):
        if mode == "refused":
            return None
        if mode == "lost_commit":
            raise RuntimeError("invented ambiguous COMMIT " + KEY)
        if mode == "bad_type":
            return {"grant_id": "a" * 64}
        return sync.WriterDispatchGrant(
            "bad" if mode == "bad_id" else "a" * 64,
            "b" * 64 if mode == "wrong_request" else digest(canonical_json(request()).encode()),
            "b" * 64 if mode == "wrong_wire" else digest(wire),
        )
    result, sent, grants, _ = run(grant=authorize)
    assert not sent and len(grants) == 1
    assert result.grant_status == ("refused" if mode == "refused" else "unconfirmed")
    assert result.wire and result.raw == b"" and not result.complete
    assert KEY not in repr(result)


@pytest.mark.parametrize("change", ["model", "system", "tools", "samples", "stream", "max_tokens", "prompt_type"])
def test_request_cannot_change_shared_builder_or_select_a_second_sample(change):
    params = request()
    if change == "model":
        params["model"] = "claude-invented-wrong"
    elif change == "system":
        params["system"] = []
    elif change == "prompt_type":
        params["messages"][0]["content"] = []
    else:
        params[change] = True
    with pytest.raises(ValueError, match="invalid_writer_request"):
        run(params=params)


@pytest.mark.parametrize("change", ["url", "method", "duplicate", "extra", "oversized"])
def test_actual_wire_validation_precedes_authorization(change):
    calls = []
    client = sync._capture_client(request(), lambda wire: calls.append(wire),
        http.MockTransport(lambda req: pytest.fail("unqualified wire must not send")))
    wire = canonical_json(request()).encode()
    method, url = "POST", sync.ENDPOINT
    if change == "url":
        url += "?unreviewed=1"
    elif change == "method":
        method = "GET"
    elif change == "duplicate":
        wire = b'{"model":"one","model":"two"}'
    elif change == "extra":
        wire = canonical_json(request() | {"stream": True}).encode()
    else:
        wire = b" " * (sync.MAX_REQUEST_BYTES + 1)
    try:
        with pytest.raises(ValueError, match="writer_request_refused"):
            client.send(http.Request(method, url, content=wire))
        assert not calls and client.observation.grant_status == "not_requested"
        with pytest.raises(ValueError, match="writer_transport_already_used"):
            client.send(http.Request("POST", sync.ENDPOINT, content=canonical_json(request()).encode()))
        assert not calls
    finally:
        client.close()


def test_response_bound_retains_only_the_exact_prefix():
    raw = b"x" * (sync.MAX_RESPONSE_BYTES + 50)
    result, sent, grants, _ = run(raw)
    assert result.raw == raw[:sync.MAX_RESPONSE_BYTES]
    assert not result.complete and result.reason == "size_exceeded"
    assert len(sent) == len(grants) == 1


def test_compressed_response_is_refused_before_decompression():
    result, sent, grants, _ = run(b"not gzip", headers={"content-encoding": "gzip"})
    assert result.raw == b"" and not result.complete
    assert result.reason == "unsupported_content_encoding"
    assert len(sent) == len(grants) == 1


def test_read_budget_captures_prefix_without_a_second_request(monkeypatch):
    ticks = iter([0, sync.READ_BUDGET_SECONDS])
    monkeypatch.setattr(sync, "_monotonic", lambda: next(ticks))
    result, sent, grants, _ = run(b"x" * 8192)
    assert result.raw == b"x" * 4096
    assert not result.complete and result.reason == "time_exceeded"
    assert len(sent) == len(grants) == 1


@pytest.mark.parametrize("size", [1, 4095, 4096])
def test_partial_socket_failure_keeps_yielded_bytes(size):
    class Partial(http.SyncByteStream):
        def __iter__(self):
            yield b"x" * size
            raise http.ReadError("invented private failure")
    result, sent, grants, _ = run(Partial())
    assert result.raw == b"x" * size and not result.complete
    assert result.http_status == 200 and result.reason == "transport_unavailable"
    assert len(sent) == len(grants) == 1


def test_failed_response_cleanup_withholds_complete_even_after_full_bytes():
    class FailedClose(http.SyncByteStream):
        def __iter__(self):
            yield envelope()

        def close(self):
            raise RuntimeError("invented close failure")
    result, sent, grants, _ = run(FailedClose())
    assert not result.complete and result.reason == "cleanup_failed"
    assert result.raw == envelope()
    assert len(sent) == len(grants) == 1


@pytest.mark.parametrize("enabled", [1, None, "true"])
def test_enablement_requires_an_explicit_boolean(enabled):
    with pytest.raises(ValueError, match="writer_enabled_requires_boolean"):
        sync.execute_writer_once(request(), api_key=KEY, authorize=lambda raw: None, enabled=enabled)


def test_authority_reuse_refusal_cannot_repurchase_a_prior_attempt():
    seen = set()

    def authorize(wire):
        key = digest(wire)
        if key in seen:
            return None
        seen.add(key)
        return sync.WriterDispatchGrant("a" * 64, digest(canonical_json(request()).encode()), key)

    first, sent, _, _ = run(http.ReadTimeout("invented unknown send"), grant=authorize)
    second, again, _, _ = run(grant=authorize)
    assert first.grant_status == "granted" and len(sent) == 1
    assert second.grant_status == "refused" and not again


@pytest.mark.parametrize("outcome", ["complete", "truncated", "lost"])
def test_real_loopback_socket_preserves_wire_and_unknown_response(outcome):
    """The reviewed HTTP transport seam routes only to this owned TCP server.

    No public provider is contacted. This is real credentialless loopback HTTP,
    distinct from the MockTransport cases above and from durable PG acceptance.
    """
    params = request()
    prepared = canonical_json(params).encode()
    expected_response = envelope()
    prefix = expected_response[:23]
    received, dispatched, grants, errors = [], [], [], []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                self.connection.settimeout(2)
                size = int(self.headers["Content-Length"])
                assert 0 < size <= sync.MAX_REQUEST_BYTES
                raw = self.rfile.read(size)
                assert len(raw) == size
                assert self.path == "/v1/messages"
                assert not self.headers.get("x-api-key")
                assert not self.headers.get("authorization")
                assert len(grants) == 1
                received.append(raw)
                self.close_connection = True
                if outcome != "lost":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(expected_response)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(expected_response if outcome == "complete" else prefix)
                    self.wfile.flush()
                # A lost reply means the server received the full billable
                # request, then closed before headers; truncated closes mid-body.
                self.connection.shutdown(socket.SHUT_WR)
            except Exception as exc:
                errors.append(type(exc).__name__)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 2
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/messages"

    class LoopbackTransport(http.BaseTransport):
        def __init__(self):
            self.inner = http.HTTPTransport(retries=0, trust_env=False)
            self.closed = False

        def handle_request(self, original):
            assert original.method == "POST" and str(original.url) == sync.ENDPOINT
            dispatched.append(original.content)
            # Only this test-owned endpoint is reachable. Strip even invented
            # credentials before the bytes enter the local network fixture.
            headers = {key: value for key, value in original.headers.items()
                       if key not in {"host", "authorization", "x-api-key"}}
            local = http.Request("POST", endpoint, headers=headers, content=original.content,
                                 extensions={"timeout": dict.fromkeys(
                                     ("connect", "read", "write", "pool"), 2)})
            return self.inner.handle_request(local)

        def close(self):
            self.inner.close()
            self.closed = True

    def authorize(wire):
        grants.append(wire)
        return sync.WriterDispatchGrant("a" * 64, digest(prepared), digest(wire))

    transport = LoopbackTransport()
    thread = threading.Thread(target=server.handle_request, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        result = sync.execute_writer_once(params, api_key=KEY, authorize=authorize,
                                          enabled=True, http_transport=transport)
    finally:
        thread.join(timeout=3)
        server.server_close()
        transport.close()
    assert not thread.is_alive() and time.monotonic() - started < 6
    assert not errors and transport.closed
    assert len(received) == len(dispatched) == len(grants) == 1
    assert received[0] == dispatched[0] == grants[0] == result.wire
    assert canonical_json(json.loads(received[0])).encode() == prepared
    assert result.grant_status == "granted" and result.grant_id == "a" * 64
    if outcome == "complete":
        assert result.complete and result.raw == expected_response and result.http_status == 200
    else:
        assert not result.complete and result.reason == "transport_unavailable"
        assert result.raw == (prefix if outcome == "truncated" else b"")
        assert result.http_status == (200 if outcome == "truncated" else None)
