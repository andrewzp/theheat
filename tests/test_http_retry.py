"""Tests for shared HTTP retry helper."""

import pytest
import requests
import responses

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
