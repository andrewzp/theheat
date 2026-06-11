"""Tests for shared HTTP retry helper."""

import pytest
import requests
import responses

from src.data import _http
from src.data._http import fetch_with_retry


@responses.activate
def test_fetch_with_retry_retries_5xx_then_success():
    url = "https://example.test/source.csv"
    responses.add(responses.GET, url, status=502)
    responses.add(responses.GET, url, body="ok", status=200)

    resp = fetch_with_retry(url, backoff_base=0)

    assert resp.text == "ok"
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_with_retry_does_not_retry_4xx():
    url = "https://example.test/source.csv"
    responses.add(responses.GET, url, status=404)

    with pytest.raises(requests.HTTPError):
        fetch_with_retry(url, backoff_base=0)

    assert len(responses.calls) == 1


@responses.activate
def test_fetch_with_retry_retries_timeout_then_success():
    url = "https://example.test/source.csv"
    responses.add(responses.GET, url, body=requests.Timeout("slow"))
    responses.add(responses.GET, url, body="ok", status=200)

    resp = fetch_with_retry(url, backoff_base=0)

    assert resp.text == "ok"
    assert len(responses.calls) == 2


def test_force_ipv4_disables_urllib3_ipv6():
    """GitHub runners have broken IPv6; several NASA EOSDIS hosts publish AAAA
    records, so requests tries IPv6 and dies with '[Errno 101] Network is
    unreachable'. force_ipv4 flips urllib3's HAS_IPV6 flag so all connections
    use IPv4."""
    import urllib3.util.connection as conn

    from src.data._http import force_ipv4

    original = conn.HAS_IPV6
    try:
        conn.HAS_IPV6 = True
        force_ipv4()
        assert conn.HAS_IPV6 is False
    finally:
        conn.HAS_IPV6 = original


@responses.activate
def test_fetch_with_retry_injects_default_user_agent():
    """No-UA callers (e.g. firms) get a polite identifying UA — some hosts
    reject generic/no-UA clients."""
    url = "https://example.test/x"
    responses.add(responses.GET, url, body="ok", status=200)

    fetch_with_retry(url, backoff_base=0)

    ua = responses.calls[0].request.headers.get("User-Agent", "")
    assert "theheat" in ua.lower()


@responses.activate
def test_fetch_with_retry_preserves_caller_user_agent():
    """A caller's explicit UA must not be overridden by the default."""
    url = "https://example.test/x"
    responses.add(responses.GET, url, body="ok", status=200)

    fetch_with_retry(url, headers={"User-Agent": "custom-agent/9.9"}, backoff_base=0)

    assert responses.calls[0].request.headers["User-Agent"] == "custom-agent/9.9"


def test_get_session_is_pooled_singleton(monkeypatch):
    monkeypatch.setattr(_http, "_session", None)

    session = _http._get_session()

    assert _http._get_session() is session
    assert session.adapters["https://"]._pool_connections == 8
    assert session.adapters["https://"]._pool_maxsize == 8
    assert session.adapters["http://"]._pool_connections == 8
    assert session.adapters["http://"]._pool_maxsize == 8


@pytest.mark.real_backoff
def test_sleep_before_retry_jitter_bounds(monkeypatch):
    calls = []
    sleeps = []
    jitter_values = [0.0, 1.5]

    def fake_uniform(low, high):
        calls.append((low, high))
        return jitter_values.pop(0)

    monkeypatch.setattr(_http.random, "uniform", fake_uniform)
    monkeypatch.setattr(_http.time, "sleep", sleeps.append)

    _http._sleep_before_retry(attempt_index=1, backoff_base=1.5)
    _http._sleep_before_retry(attempt_index=1, backoff_base=1.5)

    assert calls == [(0, 1.5), (0, 1.5)]
    assert sleeps == [3.0, 4.5]


def test_fetch_uses_shared_session(monkeypatch):
    class RecordingResponse:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

    class RecordingSession:
        def __init__(self):
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            return RecordingResponse()

    session = RecordingSession()
    monkeypatch.setattr(_http, "_get_session", lambda: session)

    fetch_with_retry("https://example.test/a", backoff_base=0)
    fetch_with_retry("https://example.test/b", backoff_base=0)

    assert session.urls == ["https://example.test/a", "https://example.test/b"]
