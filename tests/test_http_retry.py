"""Tests for shared HTTP retry helper."""

import pytest
import requests
import responses

from src.data import _http
from src.data._http import fetch_with_cache_revalidation, fetch_with_retry


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


@responses.activate
def test_revalidation_sends_if_none_match():
    url = "https://example.test/static.csv"
    cache = {url: ('"abc"', "old")}
    responses.add(responses.GET, url, body="new", status=200, headers={"ETag": '"def"'})

    response = fetch_with_cache_revalidation(url, cache=cache, backoff_base=0)

    assert responses.calls[0].request.headers["If-None-Match"] == '"abc"'
    assert response.text == "new"


@responses.activate
def test_304_serves_cached_body():
    url = "https://example.test/static.csv"
    cache = {url: ('"abc"', "old body")}
    responses.add(responses.GET, url, status=304, headers={"ETag": '"abc"'})

    response = fetch_with_cache_revalidation(url, cache=cache, backoff_base=0)

    assert response.status_code == 200
    assert response.text == "old body"
    assert cache[url] == ('"abc"', "old body")


@responses.activate
def test_200_replaces_cache():
    url = "https://example.test/static.csv"
    cache = {url: ("Thu, 01 Jan 2026 00:00:00 GMT", "old")}
    responses.add(
        responses.GET,
        url,
        body="new",
        status=200,
        headers={"Last-Modified": "Fri, 02 Jan 2026 00:00:00 GMT"},
    )

    response = fetch_with_cache_revalidation(url, cache=cache, backoff_base=0)

    assert responses.calls[0].request.headers["If-Modified-Since"] == "Thu, 01 Jan 2026 00:00:00 GMT"
    assert response.text == "new"
    assert cache[url] == ("Fri, 02 Jan 2026 00:00:00 GMT", "new")


def _response(status_code: int, url: str = "https://www.metoc.navy.mil/jtwc/test") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response._content = b"ok"
    return response


class _QueueSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_waf_403_retried_once_then_raises(monkeypatch):
    url = "https://www.metoc.navy.mil/jtwc/products/test.txt"
    session = _QueueSession([_response(403, url), _response(403, url)])
    sleeps = []
    monkeypatch.setattr(_http, "_get_session", lambda: session)
    monkeypatch.setattr(_http, "_waf_sleep", lambda: sleeps.append("slept"))
    monkeypatch.setitem(_http._waf_budget, "remaining", 4)

    with pytest.raises(requests.HTTPError):
        fetch_with_retry(url, attempts=3, backoff_base=0)

    assert session.urls == [url, url]
    assert sleeps == ["slept"]
    assert _http._waf_budget["remaining"] == 3


def test_waf_403_not_retried_for_unlisted_host(monkeypatch):
    url = "https://example.test/blocked"
    session = _QueueSession([_response(403, url)])
    sleeps = []
    monkeypatch.setattr(_http, "_get_session", lambda: session)
    monkeypatch.setattr(_http, "_waf_sleep", lambda: sleeps.append("slept"))
    monkeypatch.setitem(_http._waf_budget, "remaining", 4)

    with pytest.raises(requests.HTTPError):
        fetch_with_retry(url, attempts=3, backoff_base=0)

    assert session.urls == [url]
    assert sleeps == []
    assert _http._waf_budget["remaining"] == 4


def test_429_retried_for_waf_host(monkeypatch):
    url = "https://waterservices.usgs.gov/nwis/iv/"
    session = _QueueSession([_response(429, url), _response(200, url)])
    sleeps = []
    monkeypatch.setattr(_http, "_get_session", lambda: session)
    monkeypatch.setattr(_http, "_waf_sleep", lambda: sleeps.append("slept"))
    monkeypatch.setitem(_http._waf_budget, "remaining", 4)

    response = fetch_with_retry(url, attempts=3, backoff_base=0)

    assert response.status_code == 200
    assert session.urls == [url, url]
    assert sleeps == ["slept"]


def test_waf_budget_caps_process_wide_retries(monkeypatch):
    url = "https://coralreefwatch.noaa.gov/product/test.json"
    session = _QueueSession([
        _response(403, url),
        _response(403, url),
        _response(403, url),
    ])
    sleeps = []
    monkeypatch.setattr(_http, "_get_session", lambda: session)
    monkeypatch.setattr(_http, "_waf_sleep", lambda: sleeps.append("slept"))
    monkeypatch.setitem(_http._waf_budget, "remaining", 1)

    with pytest.raises(requests.HTTPError):
        fetch_with_retry(url, attempts=3, backoff_base=0)
    with pytest.raises(requests.HTTPError):
        fetch_with_retry(url, attempts=3, backoff_base=0)

    assert session.urls == [url, url, url]
    assert sleeps == ["slept"]
    assert _http._waf_budget["remaining"] == 0
