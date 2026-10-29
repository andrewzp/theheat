import http.client
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import threading
import time

import pytest

from src.dashboard_preview.http import handler_type, _BUSY
from tests.dashboard_graphic_helpers import POLICY, RUNTIME, saved_preview
from tests.test_dashboard_graphic_auth import AUTH, BASIC


@pytest.fixture
def endpoint(monkeypatch):
    for key in ("VERCEL", "VERCEL_ENV", "VERCEL_URL", "DASHBOARD_AUTH_DISABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in BASIC.items():
        monkeypatch.setenv(key, value)
    # Match the important native-runtime MRO: its own logger precedes our class.
    class RuntimeBase(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pytest.fail("runtime must not log request details")
    completed = threading.Event()
    class Handler(RuntimeBase, handler_type(policy_sha=POLICY, runtime_sha=RUNTIME)):
        def finish(self):
            try:
                super().finish()
            finally:
                completed.set()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def call(method="POST", body=b"{}", headers=None, path="/api/graphic_preview"):
        deadline = time.monotonic() + 5
        completed.clear()
        conn = http.client.HTTPConnection(*server.server_address, timeout=5)
        conn.request(method, path, body=body, headers={"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        status, result_headers, result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        # Reading Content-Length bytes does not join the server's finally.
        # Wait for this owned request's cleanup within the original five seconds.
        assert completed.wait(max(0, deadline - time.monotonic())), "Owned HTTP request did not finish"
        assert result_headers["Cache-Control"] == "private, no-store"
        assert result_headers["X-Content-Type-Options"] == "nosniff"
        assert "Access-Control-Allow-Origin" not in result_headers
        return status, result_headers, json.loads(result) if result else None
    yield call
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize("method", ["POST", "GET", "HEAD", "OPTIONS", "TRACE", "CUSTOM"])
def test_auth_precedes_body_method_and_all_work(endpoint, monkeypatch, method):
    monkeypatch.setattr("src.dashboard_preview.http.read_gist", lambda *_: pytest.fail("read before auth"))
    monkeypatch.setattr("src.dashboard_preview.http.build_preview", lambda *_a, **_k: pytest.fail("render before auth"))
    status, headers, _ = endpoint(method, b"not JSON")
    assert status == 401 and "WWW-Authenticate" in headers


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "TRACE", "CUSTOM"])
def test_authenticated_non_post_has_no_asset(endpoint, method):
    status, headers, _ = endpoint(method, headers={"Authorization": AUTH})
    assert status == 405 and headers["Allow"] == "POST"


@pytest.mark.parametrize("body,extra", [(b"x" * 4097, {}), (b'\xff', {}), (b'{"x":1,"x":2}', {}),
    (b"{}", {"Content-Encoding": "gzip"}), (b"{}", {"Content-Type": "text/plain"})],
    ids=["oversize", "invalid-utf8", "duplicate-key", "encoded", "wrong-type"])
def test_request_contract_before_state(endpoint, monkeypatch, body, extra):
    monkeypatch.setattr("src.dashboard_preview.http.read_gist", lambda *_: pytest.fail("bad request read"))
    assert endpoint(body=body, headers={"Authorization": AUTH, **extra})[0] == 400


def test_busy_and_unexpected_error_are_private(endpoint, monkeypatch):
    _BUSY.acquire()
    try:
        assert endpoint(headers={"Authorization": AUTH})[0] == 429
    finally:
        _BUSY.release()
    def failure(*_a, **_k):
        raise RuntimeError("private source and secret")
    monkeypatch.setattr("src.dashboard_preview.http.build_preview", failure)
    status, _, result = endpoint(headers={"Authorization": AUTH})
    assert status == 503 and "private source" not in json.dumps(result)
    assert _BUSY.acquire(blocking=False)
    _BUSY.release()


def test_production_entry_always_uses_real_source_qualification(endpoint, monkeypatch):
    _, request = saved_preview()
    def build(value, **kwargs):
        assert value == request and kwargs["synthetic"] is False
        return b'{"fixture":true}'
    monkeypatch.setattr("src.dashboard_preview.http.build_preview", build)
    assert endpoint(body=json.dumps(request).encode(), headers={"Authorization": AUTH})[2] == {"fixture": True}


def test_endpoint_does_not_return_while_owned_handler_cleanup_is_pending(endpoint, monkeypatch):
    """Response bytes may arrive before the request's finally releases _BUSY."""
    release_entered, finish_release, returned = threading.Event(), threading.Event(), threading.Event()
    lock, errors = threading.Lock(), []
    class DeferredRelease:
        def acquire(self, *args, **kwargs):
            return lock.acquire(*args, **kwargs)
        def release(self):
            release_entered.set()
            assert finish_release.wait(5), "Invented cleanup release was never allowed"
            lock.release()
    monkeypatch.setattr("src.dashboard_preview.http._BUSY", DeferredRelease())
    monkeypatch.setattr("src.dashboard_preview.http.build_preview", lambda *_a, **_k: b"{}")
    def call():
        try:
            assert endpoint(headers={"Authorization": AUTH})[0] == 200
        except BaseException as exc:
            errors.append(exc)
        finally:
            returned.set()
    client = threading.Thread(target=call)
    client.start()
    try:
        assert release_entered.wait(5)
        assert not returned.wait(0.2), "HTTP response was mistaken for completed handler cleanup"
    finally:
        finish_release.set()
        client.join(5)
    assert not client.is_alive() and not errors and returned.is_set()
    assert lock.acquire(blocking=False)
    lock.release()
