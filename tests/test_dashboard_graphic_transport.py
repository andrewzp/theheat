"""Real request preparation and urllib3 streaming, with no external I/O."""

import gzip
import io
import json
import socket

import pytest
import requests
from urllib3.response import HTTPResponse
from urllib3 import exceptions as transport_errors

from src.dashboard_preview.errors import PreviewError, failure_code, log_unavailable
from src.dashboard_preview.reader import Budget, read_gist
from tests.test_dashboard_graphic_reader import ENV, GIST, RAW

PRIVATE = "PRIVATE-header-url-body-exception-never-log"
REAL_SESSION = requests.Session


class WireAdapter(requests.adapters.BaseAdapter):
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        response = requests.Response()
        response.status_code = 200
        response.url, response.request = request.url, request
        response.raw = reply
        return response

    def close(self):
        pass


def install(monkeypatch, *replies):
    adapter = WireAdapter(replies)
    session = REAL_SESSION()
    session.mount("https://", adapter)
    monkeypatch.setattr("requests.Session", lambda: session)
    return adapter


def wire(body, *, encoding=None):
    return HTTPResponse(body=io.BytesIO(body), preload_content=False, decode_content=False,
                        headers={} if encoding is None else {"Content-Encoding": encoding})


def metadata(**changes):
    file = {"filename": "state.json", "truncated": False, "content": '{"drafts":[]}', **changes}
    return json.dumps({"id": GIST, "files": {"state.json": file}}).encode()


def unavailable(capsys, call):
    with pytest.raises(PreviewError) as caught:
        call()
    assert caught.value.payload() == PreviewError("preview_unavailable").payload()
    output = capsys.readouterr()
    assert PRIVATE not in output.out + output.err
    rows = [json.loads(line) for line in output.err.splitlines()]
    assert all(set(row) <= {"component", "stage", "http_status", "error_code"} for row in rows)
    return rows


@pytest.mark.parametrize("token", [PRIVATE + "\nvalue", PRIVATE + "\r\nX-Other: secret"], ids=["embedded-newline", "header-injection"])
def test_real_header_preparation_refuses_before_transport_without_logging_value(monkeypatch, capsys, token):
    adapter = install(monkeypatch)
    rows = unavailable(capsys, lambda: read_gist({**ENV, "GITHUB_TOKEN": token}, Budget()))
    assert adapter.calls == []
    assert rows == [{"component": "graphic_preview", "stage": "state_configuration"}]


def test_real_prepared_request_and_gzip_stream_preserve_two_read_credential_boundary(monkeypatch, capsys):
    adapter = install(monkeypatch, wire(gzip.compress(metadata(truncated=True, raw_url=RAW)), encoding="gzip"),
                      wire(gzip.compress(b'{"drafts":[]}'), encoding="gzip"))
    assert read_gist(ENV, Budget()) == {"drafts": []}
    assert len(adapter.calls) == 2
    assert adapter.calls[0][0].headers["Authorization"] == "token fixture-secret"
    assert "Authorization" not in adapter.calls[1][0].headers
    assert adapter.calls[1][0].url == RAW
    assert all(kwargs["stream"] and kwargs["timeout"] == (2, 3) for _, kwargs in adapter.calls)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("where", ["metadata", "raw"])
def test_real_gzip_decode_failure_is_classified_at_body_without_retry(monkeypatch, capsys, where):
    broken = wire(PRIVATE.encode(), encoding="gzip")
    replies = [broken] if where == "metadata" else [wire(metadata(truncated=True, raw_url=RAW)), broken]
    adapter = install(monkeypatch, *replies)
    rows = unavailable(capsys, lambda: read_gist(ENV, Budget()))
    assert rows[0] == {"component": "graphic_preview", "stage": f"state_{where}_body", "error_code": "content_decoding"}
    assert len(adapter.calls) == len(replies)


@pytest.mark.parametrize("body,code", [(b'{"x":', "json_decode"), (b'{"x":1,"x":2}', "value"),
                                       (b'\xff', "value"), (b'[]', "value")], ids=["syntax", "duplicate", "utf8", "shape"])
def test_metadata_strict_decode_separate_from_successful_transport(monkeypatch, capsys, body, code):
    adapter = install(monkeypatch, wire(body))
    rows = unavailable(capsys, lambda: read_gist(ENV, Budget()))
    assert rows == [{"component": "graphic_preview", "stage": "state_metadata_json", "error_code": code}]
    assert len(adapter.calls) == 1


class TimedOut(io.BytesIO):
    def read1(self, *_a):
        raise socket.timeout(PRIVATE)


def test_real_urllib3_timeout_wrap_is_classified_without_message_or_retry(monkeypatch, capsys):
    response = HTTPResponse(body=TimedOut(b"invented"), preload_content=False)
    adapter = install(monkeypatch, response)
    rows = unavailable(capsys, lambda: read_gist(ENV, Budget()))
    assert rows[0]["stage"] == "state_metadata_body" and rows[0]["error_code"] == "read_timeout"
    assert len(adapter.calls) == 1


def test_real_stream_overflow_and_budget_still_fail_closed(monkeypatch, capsys):
    adapter = install(monkeypatch, wire(b"x" * 100))
    monkeypatch.setattr("src.dashboard_preview.reader.API_LIMIT", 20)
    rows = unavailable(capsys, lambda: read_gist(ENV, Budget()))
    assert rows[0]["stage"] == "state_metadata_body" and rows[0]["error_code"] == "preview_error"
    assert len(adapter.calls) == 1
    times = iter([0, 0, 24, 26])
    adapter = install(monkeypatch, wire(metadata()))
    rows = unavailable(capsys, lambda: read_gist(ENV, Budget(clock=lambda: next(times))))
    assert rows[0]["error_code"] == "preview_error" and len(adapter.calls) == 1


@pytest.mark.parametrize("factory,expected", [
    (lambda: requests.exceptions.InvalidURL(PRIVATE), "invalid_url"),
    (lambda: requests.exceptions.SSLError(PRIVATE), "tls"),
    (lambda: requests.exceptions.ConnectTimeout(PRIVATE), "connect_timeout"),
    (lambda: requests.exceptions.ReadTimeout(PRIVATE), "read_timeout"),
    (lambda: requests.exceptions.ConnectionError(PRIVATE), "connection"),
    (lambda: requests.exceptions.ChunkedEncodingError(PRIVATE), "chunked_encoding"),
    (lambda: requests.exceptions.ContentDecodingError(PRIVATE), "content_decoding"),
    (lambda: transport_errors.SSLError(PRIVATE), "tls"),
    (lambda: transport_errors.ProtocolError(PRIVATE), "connection"),
    (lambda: ValueError(PRIVATE), "value"), (lambda: TypeError(PRIVATE), "type"),
    (lambda: AttributeError(PRIVATE), "attribute"), (lambda: TimeoutError(PRIVATE), "timeout"),
    (lambda: OSError(PRIVATE), "os"), (lambda: RuntimeError(PRIVATE), "unknown"),
], ids=["url", "tls", "connect-timeout", "read-timeout", "connection", "chunked", "decode", "raw-tls", "raw-protocol", "value", "type", "attribute", "timeout", "os", "unknown"])
def test_safe_exact_types_from_actual_send_boundary(monkeypatch, capsys, factory, expected):
    adapter = install(monkeypatch, factory())
    rows = unavailable(capsys, lambda: read_gist(ENV, Budget()))
    assert rows[0] == {"component": "graphic_preview", "stage": "state_metadata_send", "error_code": expected}
    assert len(adapter.calls) == 1


def test_only_immediate_cause_and_no_hostile_exception_hooks(capsys):
    class HostileMeta(type):
        def __hash__(cls):
            pytest.fail("custom type hash")
        def __eq__(cls, other):
            pytest.fail("custom type equality")

    class Hostile(ValueError, metaclass=HostileMeta):
        def __str__(self):
            pytest.fail("exception string")
        def __getattribute__(self, name):
            pytest.fail("exception attribute")

    hostile = Hostile(PRIVATE)
    assert failure_code(hostile) == "unknown"
    outer = PreviewError("preview_unavailable")
    outer.__cause__ = hostile
    assert failure_code(outer) == "preview_error"
    middle = RuntimeError(PRIVATE)
    middle.__cause__ = ValueError(PRIVATE)
    outer.__cause__ = middle
    assert failure_code(outer) == "preview_error"
    outer.__cause__ = json.JSONDecodeError(PRIVATE, PRIVATE, 0)
    assert failure_code(outer) == "json_decode"
    log_unavailable("state_metadata_json", error_code=failure_code(outer))
    assert PRIVATE not in capsys.readouterr().err


@pytest.mark.parametrize("code", [PRIVATE, {}, [], None, 2, True])
def test_logger_drops_unallowlisted_code(code, capsys):
    log_unavailable("state_metadata_send", error_code=code)
    assert json.loads(capsys.readouterr().err) == {"component": "graphic_preview", "stage": "state_metadata_send"}


def test_failed_logging_does_not_replace_transport_error_or_retry(monkeypatch, capsys):
    class BrokenLog(io.StringIO):
        def write(self, value):
            raise OSError(PRIVATE)
    adapter = install(monkeypatch, requests.exceptions.SSLError(PRIVATE))
    with monkeypatch.context() as context:
        context.setattr("src.dashboard_preview.errors.sys.stderr", BrokenLog())
        rows = unavailable(capsys, lambda: read_gist(ENV, Budget()))
    assert rows == [] and len(adapter.calls) == 1
