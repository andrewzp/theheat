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
