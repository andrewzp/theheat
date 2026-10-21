"""Actual SDK and Requests with invented credentials and offline transports only."""
from copy import deepcopy
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import pytest
import requests
import tweepy

from src.data import twitter_metrics as metrics
from src.orchestrator import hot10


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect

    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] != "127.0.0.1":
            raise AssertionError("External connection refused in metrics fixture")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(metrics, key, "invented-offline-value")


class OfflineAdapter(requests.adapters.BaseAdapter):
    def __init__(self, status=200, *, timeout=False):
        self.status = status
        self.timeout = timeout
        self.sent = []
        self.closed = False

    def send(self, request, **kwargs):
        assert request.method == "GET" and request.url.startswith("https://api.twitter.com/2/tweets?")
        auth = request.headers.get("Authorization", "")
        auth = auth.decode("ascii") if isinstance(auth, bytes) else auth
        # Never retain the signed Authorization value, even for invented keys.
        self.sent.append(dict(auth_scheme=auth.split(" ", 1)[0], timeout=kwargs.get("timeout")))
        if self.timeout:
            raise requests.ReadTimeout("Invented offline stall")
        response = requests.Response()
        response.status_code = self.status
        response.headers["Content-Type"] = "application/json"
        if self.status == 302:
            response.headers["Location"] = "https://elsewhere.invalid/never-follow"
        response._content = json.dumps(dict(data=[dict(id="123456789", text="Invented offline post",
            created_at="2026-10-20T00:00:00.000Z", edit_history_tweet_ids=["123456789"],
            public_metrics=dict(like_count=0))]) if self.status == 200
            else dict(title="Invented error", detail="Offline fixture")).encode()
        response.request = request
        response.url = request.url
        return response

    def close(self):
        self.closed = True


def client(monkeypatch, adapter):
    value = metrics._get_client()
    assert value is not None and value.wait_on_rate_limit is False
    assert value.session.get_adapter("https://api.twitter.com").max_retries.total == 0
    value.session.mount("https://", adapter)
    monkeypatch.setattr(metrics, "_get_client", lambda: value)
    return value


@pytest.mark.parametrize("status,error", [(200, None), (401, tweepy.Unauthorized),
    (403, tweepy.Forbidden), (429, tweepy.TooManyRequests), (503, tweepy.TwitterServerError),
    (302, tweepy.HTTPException)])
def test_actual_sdk_uses_configured_oauth_one_bounded_attempt_and_closes(monkeypatch, status, error):
    adapter = OfflineAdapter(status)
    client(monkeypatch, adapter)
    if error:
        with pytest.raises(error):
            metrics.fetch_metrics(["123456789"])
    else:
        result = metrics.fetch_metrics(["123456789"])
        assert result["123456789"]["likes"] == 0
        assert result["123456789"]["impressions"] is None
    assert adapter.sent == [dict(auth_scheme="OAuth", timeout=(5.0, 15.0))]
    assert adapter.closed is True


def test_sdk_timeout_remains_failed_unknown_and_daily_guard_stops_second_lookup(monkeypatch):
    adapter = OfflineAdapter(timeout=True)
    client(monkeypatch, adapter)
    monkeypatch.setenv("THEHEAT_METRICS_ENABLED", "1")
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    state = dict(drafts=[], run_history=[], tweet_metrics={}, publish_ledger={
        "event": dict(tweet_id="123456789", at="2026-10-20T00:00:00Z")})
    original = deepcopy(state)
    run = dict(started_at=now.isoformat(), sources=[])
    hot10._run_twitter_metrics(state, run, now=now)
    assert run["sources"][-1]["status"] == "failed"
    assert state["tweet_metrics"] == original["tweet_metrics"]
    assert state["drafts"] == original["drafts"] and state["publish_ledger"] == original["publish_ledger"]
    state["run_history"].append(deepcopy(run))
    hot10._run_twitter_metrics(state, dict(started_at=now.isoformat(), sources=[]), now=now)
    assert adapter.sent == [dict(auth_scheme="OAuth", timeout=(5.0, 15.0))]
    assert adapter.closed is True


def test_owned_loopback_stall_obeys_same_configured_sdk_session_timeout(monkeypatch):
    calls = []
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(1)
            try:
                time.sleep(.5)
                self.send_response(200)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                finished.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=.01), daemon=True)
    worker.start()
    monkeypatch.setattr(metrics, "_METRICS_TIMEOUT", (.1, .1))
    sdk = metrics._get_client()
    started = time.monotonic()
    try:
        with pytest.raises(requests.ReadTimeout):
            sdk.session.get(f"http://127.0.0.1:{server.server_port}/invented-stall")
        assert time.monotonic() - started < 2
        assert calls == [1]
    finally:
        sdk.session.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert finished.wait(timeout=2)
