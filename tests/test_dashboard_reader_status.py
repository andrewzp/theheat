"""Actual HTTP reader-status contract with invented, offline state transport."""

from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
import requests

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.http import _BUSY
from src.dashboard_preview import reader_status
from tests.test_dashboard_graphic_auth import AUTH, BASIC, PROTECTED
from tests.test_dashboard_graphic_reader import ENV, RAW
from tests.test_dashboard_graphic_transport import install, metadata, wire

PRIVATE = "PRIVATE-token-state-source-exception-never-return"


@pytest.fixture
def status_endpoint(monkeypatch):
    for key in ("VERCEL", "VERCEL_ENV", "VERCEL_URL", "DASHBOARD_AUTH_DISABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASIC, **ENV}.items():
        monkeypatch.setenv(key, value)

    class RuntimeBase(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pytest.fail("native wrapper must not log request details")

    class Handler(RuntimeBase, reader_status.handler_type(policy_sha="a" * 64, runtime_sha="b" * 64)):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method="GET", *, body=None, headers=None, path="/api/graphic_reader_status"):
        conn = http.client.HTTPConnection(*server.server_address, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        status, result_headers, raw = response.status, dict(response.getheaders()), response.read()
        conn.close()
        assert result_headers["Cache-Control"] == "private, no-store"
        assert result_headers["X-Content-Type-Options"] == "nosniff"
        assert result_headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
        assert result_headers["Referrer-Policy"] == "no-referrer"
        assert "Access-Control-Allow-Origin" not in result_headers
        assert len(raw) <= 1024
        return status, result_headers, json.loads(raw) if raw else None

    yield call
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize("truncated", [False, True])
@pytest.mark.parametrize("path", ["/api/graphic_reader_status", "/api/graphic_reader_status.py"])
def test_real_reader_once_no_selection_render_or_state_disclosure(status_endpoint, monkeypatch, capsys, truncated, path):
    state = {"drafts": [{"id": PRIVATE, "text": PRIVATE}], "private": PRIVATE}
    before = deepcopy(state)
    encoded = json.dumps(state).encode()
    replies = ([wire(metadata(truncated=True, raw_url=RAW)), wire(encoded)] if truncated
               else [wire(metadata(content=encoded.decode()))])
    adapter = install(monkeypatch, *replies)
    calls = []
    real_reader = reader_status.read_gist

    def read(*args):
        calls.append(True)
        return real_reader(*args)

    def forbidden(*_a, **_k):
        pytest.fail("status must not select, qualify or render a draft")

    monkeypatch.setattr(reader_status, "read_gist", read)
    for name in ("_selected", "qualified_spec", "render_svg", "build_preview"):
        monkeypatch.setattr("src.dashboard_preview.preview." + name, forbidden)
    status, _, body = status_endpoint(headers={"Authorization": AUTH}, path=path)
    assert status == 200 and body == {"schema_version": 1, "state_reader": "available",
        "rendering": "not_evaluated", "source_qualification": "not_evaluated", "publication_approved": False}
    assert len(calls) == 1 and len(adapter.calls) == (2 if truncated else 1)
    assert state == before and PRIVATE not in json.dumps(body) + capsys.readouterr().err
    assert adapter.calls[0][0].headers["Authorization"] == "token fixture-secret"
    if truncated:
        assert "Authorization" not in adapter.calls[1][0].headers


@pytest.mark.parametrize("method", ["GET", "POST", "HEAD", "OPTIONS", "TRACE", "CUSTOM"])
def test_auth_precedes_every_operation(status_endpoint, monkeypatch, method):
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: pytest.fail("read before auth"))
    status, headers, body = status_endpoint(method, body=PRIVATE.encode())
    assert status == 401 and "WWW-Authenticate" in headers
    assert body is None if method == "HEAD" else body == PreviewError("authentication_required").payload()


@pytest.mark.parametrize("method", ["POST", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT", "CUSTOM"])
def test_only_get_and_correct_allow_header(status_endpoint, monkeypatch, method):
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: pytest.fail("read for wrong method"))
    status, headers, _ = status_endpoint(method, headers={"Authorization": AUTH})
    assert status == 405 and headers["Allow"] == "GET"


@pytest.mark.parametrize("path,extra,body,expected", [
    ("/api/graphic_preview", {}, None, 400), ("/api/graphic_reader_status?private=secret", {}, None, 400),
    ("/api/graphic_reader_status#private", {}, None, 400), ("//localhost/api/graphic_reader_status", {}, None, 400),
    ("http://other.example/api/graphic_reader_status", {}, None, 503),
    ("/api/graphic_reader_status", {"Origin": "null"}, None, 403),
    ("/api/graphic_reader_status", {"Origin": "https://other.example"}, None, 403),
    ("/api/graphic_reader_status", {}, b"private", 400),
    ("/api/graphic_reader_status", {"Content-Encoding": "gzip"}, None, 400),
    ("/api/graphic_reader_status", {"Transfer-Encoding": "chunked"}, b"0\r\n\r\n", 400),
    ("/api/graphic_reader_status", {"Content-Length": "00"}, None, 400),
], ids=["preview-path", "query", "fragment", "authority", "wrong-host", "null-origin", "other-origin", "body", "encoding", "chunked", "noncanonical-zero"])
def test_invalid_target_origin_or_body_never_reads(status_endpoint, monkeypatch, path, extra, body, expected):
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: pytest.fail("invalid status request read"))
    status, _, result = status_endpoint(path=path, body=body, headers={"Authorization": AUTH, **extra})
    assert status == expected
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("host,forwarded,expected", [(PROTECTED["VERCEL_URL"], "evil.example", 200),
    ("alias.vercel.app", PROTECTED["VERCEL_URL"], 403)])
def test_exact_protected_host_without_trusting_forwarded_headers(status_endpoint, monkeypatch, host, forwarded, expected):
    for name, value in PROTECTED.items():
        monkeypatch.setenv(name, value)
    reads = []
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: reads.append(True))
    assert status_endpoint(headers={"Host": host, "X-Forwarded-Host": forwarded})[0] == expected
    assert len(reads) == (1 if expected == 200 else 0)


@pytest.mark.parametrize("kind", ["header", "body", "json", "unknown"])
def test_real_transport_failures_return_only_fixed_authenticated_codes(status_endpoint, monkeypatch, capsys, kind):
    expected = {"header": "invalid_header", "body": "content_decoding", "json": "json_decode", "unknown": "preview_error"}[kind]
    expected_stage = {"header": "state_metadata_send", "body": "state_metadata_body",
                      "json": "state_metadata_json", "unknown": "state_metadata_send"}[kind]
    replies = {"header": [], "body": [wire(PRIVATE.encode(), encoding="gzip")],
               "json": [wire(b'{"broken":')], "unknown": [RuntimeError(PRIVATE)]}[kind]
    adapter = install(monkeypatch, *replies)
    if kind == "header":
        monkeypatch.setenv("GITHUB_TOKEN", PRIVATE + "\r\nInjected: no")
    status, _, result = status_endpoint(headers={"Authorization": AUTH})
    assert status == 503 and result == {"schema_version": 1, "state_reader": "unavailable",
        "rendering": "not_evaluated", "source_qualification": "not_evaluated", "publication_approved": False,
        "failure_code": expected, "reader_stage": expected_stage}
    assert len(adapter.calls) == (0 if kind == "header" else 1)
    assert PRIVATE not in json.dumps(result) + capsys.readouterr().err
    assert _BUSY.acquire(blocking=False)
    _BUSY.release()


def test_busy_never_reads_and_failure_releases_lock(status_endpoint, monkeypatch):
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: pytest.fail("busy read"))
    _BUSY.acquire()
    try:
        assert status_endpoint(headers={"Authorization": AUTH})[0] == 429
    finally:
        _BUSY.release()
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: (_ for _ in ()).throw(AttributeError(PRIVATE)))
    assert status_endpoint(headers={"Authorization": AUTH})[2]["failure_code"] == "attribute"
    assert _BUSY.acquire(blocking=False)
    _BUSY.release()


def test_configuration_error_before_state_has_no_failure_code(status_endpoint, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "")
    monkeypatch.setattr(reader_status, "read_gist", lambda *_: pytest.fail("read for bad auth config"))
    assert status_endpoint(headers={"Authorization": AUTH})[2] == PreviewError("preview_unavailable").payload()


@pytest.mark.parametrize("case", ["overflow", "deadline"])
def test_real_reader_bounds_and_no_retry_through_status(status_endpoint, monkeypatch, case):
    from src.dashboard_preview.reader import Budget
    adapter = install(monkeypatch, wire(metadata()))
    if case == "overflow":
        monkeypatch.setattr("src.dashboard_preview.reader.API_LIMIT", 20)
    else:
        ticks = iter([0, 0, 0, 24, 26])
        monkeypatch.setattr(reader_status, "Budget", lambda: Budget(clock=lambda: next(ticks)))
    status, _, result = status_endpoint(headers={"Authorization": AUTH})
    assert status == 503 and result["state_reader"] == "unavailable"
    assert len(adapter.calls) == 1


def test_unknown_exception_and_broken_logging_cannot_leak(status_endpoint, monkeypatch, capsys):
    import io

    class Hostile(RuntimeError):
        def __str__(self):
            pytest.fail("exception message evaluated")

    class Broken(io.StringIO):
        def write(self, *_):
            raise OSError(PRIVATE)

    def fail(*_):
        raise Hostile(PRIVATE)

    monkeypatch.setattr(reader_status, "read_gist", fail)
    with monkeypatch.context() as context:
        context.setattr("src.dashboard_preview.errors.sys.stderr", Broken())
        status, _, result = status_endpoint(headers={"Authorization": AUTH})
    assert status == 503 and result["failure_code"] == "unknown"
    assert PRIVATE not in json.dumps(result) + capsys.readouterr().err


def test_late_client_disconnect_does_not_retry_reader(monkeypatch):
    handler = reader_status.handler_type(policy_sha="a" * 64, runtime_sha="b" * 64)
    instance = object.__new__(handler)
    writes = []

    def broken(*_a, **_k):
        writes.append(True)
        raise BrokenPipeError(PRIVATE)

    monkeypatch.setattr(instance, "_write_reply", broken)
    instance._reply(200, b"{}")
    assert writes == [True] and instance.close_connection is True


def test_duplicate_headers_fail_before_reader():
    from email.message import Message
    from src.dashboard_preview.auth import authorize

    headers = Message()
    headers["Host"], headers["Authorization"] = "localhost", AUTH
    headers["Authorization"] = AUTH
    with pytest.raises(PreviewError):
        authorize("/api/graphic_reader_status", headers, BASIC, paths=reader_status.PATHS)


def test_missing_stream_method_is_explicit_without_fallback_or_retry(status_endpoint, monkeypatch, capsys):
    from tests.test_dashboard_graphic_reader import Response, Session

    class Missing:
        @property
        def read1(self):
            raise AttributeError(PRIVATE)

        def close(self):
            pass

    response = Response(b"unused")
    response.raw = Missing()
    session = Session([response])
    monkeypatch.setattr("requests.Session", lambda: session)
    status, _, result = status_endpoint(headers={"Authorization": AUTH})
    assert status == 503 and result["reader_stage"] == "state_metadata_stream"
    assert result["failure_code"] == "attribute" and len(session.calls) == 1
    assert PRIVATE not in json.dumps(result) + capsys.readouterr().err


def test_untrusted_stage_and_exception_subclass_cannot_supply_diagnostic_fields():
    from src.dashboard_preview.errors import reader_failure_stage

    error = PreviewError("preview_unavailable")
    for value in (PRIVATE, [], {}, None, 42):
        error._reader_stage = value
        assert reader_failure_stage(error) == "state_read"

    class Hostile(PreviewError):
        def __getattribute__(self, name):
            pytest.fail("subclass attribute inspected")

    hostile = BaseException.__new__(Hostile)
    assert reader_failure_stage(hostile) == "state_read"
