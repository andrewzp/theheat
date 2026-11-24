"""Real Requests preparation/redirects with invented responses; no source access."""
from datetime import date

import pytest
import requests

from src.data import gpm_imerg as gpm

TOKEN = "invented-explicit-earthdata-token"
DAY = date(2026, 11, 22)


@pytest.fixture
def transport(monkeypatch):
    calls, lookups, sessions, closed = [], [], [], []
    replies = [(200, None)]
    original_init, original_close = requests.Session.__init__, requests.Session.close

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, prepared, **kwargs):
            calls.append((prepared, kwargs))
            item = replies.pop(0) if len(replies) > 1 else replies[0]
            if isinstance(item, Exception):
                raise item
            status, destination = item
            response = requests.Response()
            response.status_code = status
            response.url, response.request = prepared.url, prepared
            response._content = b"invented opaque bytes, not a weather frame"
            response._content_consumed = True
            response.headers["Content-Type"] = "application/octet-stream"
            if destination is not None:
                response.headers["Location"] = destination
            return response

        def close(self):
            pass

    def initialize(session):
        original_init(session)
        session.mount("https://", Adapter())
        session.mount("http://", Adapter())
        sessions.append(session)

    def close(session):
        closed.append(session)
        original_close(session)

    def ambient(*args, **kwargs):
        lookups.append("netrc")
        return "invented-ambient-user", "invented-ambient-password"

    def proxies(*args, **kwargs):
        lookups.append("proxies")
        return {"https": "http://invented-proxy.invalid"}

    monkeypatch.setattr(requests.Session, "__init__", initialize)
    monkeypatch.setattr(requests.Session, "close", close)
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", ambient)
    monkeypatch.setattr(requests.sessions, "get_environ_proxies", proxies)
    return calls, lookups, sessions, closed, replies


def fetch():
    return gpm._fetch_grid_bytes_datapool(target_date=DAY, product="late", token=TOKEN)


def assert_owned(transport):
    calls, lookups, sessions, closed, _ = transport
    assert not lookups, "No netrc or environment proxy discovery"
    assert len(sessions) == 1 and closed == sessions
    assert sessions[0].trust_env is False
    assert all(kwargs["verify"] is True and kwargs["proxies"] == {} for _, kwargs in calls)
    assert all(kwargs["timeout"] == gpm._request_timeout_s() for _, kwargs in calls)


def test_datapool_uses_explicit_token_without_ambient_authentication(transport, capsys):
    assert fetch() == b"invented opaque bytes, not a weather frame"
    calls, _, _, _, _ = transport
    assert len(calls) == 1
    assert calls[0][0].url == f"{gpm.DATAPOOL_BASE}/{gpm._imerg_relpath('late', DAY)}"
    assert calls[0][0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in capsys.readouterr().out
    assert_owned(transport)


@pytest.mark.parametrize("location,retained", [
    ("https://data.gesdisc.earthdata.nasa.gov/other.nc4", True),
    ("https://urs.earthdata.nasa.gov/login", False),
    ("https://other.invalid/other.nc4", False),
    ("http://data.gesdisc.earthdata.nasa.gov/other.nc4", False),
    ("https://data.gesdisc.earthdata.nasa.gov:444/other.nc4", False),
])
def test_redirects_preserve_existing_authorization_stripping_without_netrc(transport, location, retained):
    calls, _, _, _, replies = transport
    replies[:] = [(302, location), (200, None)]
    assert fetch() == b"invented opaque bytes, not a weather frame"
    assert len(calls) == 2
    assert calls[0][0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert calls[1][0].headers.get("Authorization") == (f"Bearer {TOKEN}" if retained else None)
    assert_owned(transport)


@pytest.mark.parametrize("status,error", [(400, gpm._GridTransient), (401, gpm._GridTransient),
    (403, gpm._GridTransient), (404, gpm._GridNotFound), (503, gpm._GridTransient)])
def test_status_refusals_remain_one_request_and_close_owned_session(transport, status, error):
    calls, _, _, _, replies = transport
    replies[:] = [(status, None)]
    with pytest.raises(error):
        fetch()
    assert len(calls) == 1
    assert_owned(transport)


@pytest.mark.parametrize("error", [requests.Timeout("invented timeout"), requests.ConnectionError("invented connection failure")])
def test_transport_failure_does_not_retry_or_leave_a_session_open(transport, error):
    calls, _, _, _, replies = transport
    replies[:] = [error]
    with pytest.raises(gpm._GridTransient):
        fetch()
    assert len(calls) == 1
    assert_owned(transport)


def test_default_redirect_limit_is_unchanged(transport):
    calls, _, sessions, _, replies = transport
    replies[:] = [(302, "https://data.gesdisc.earthdata.nasa.gov/repeat.nc4")]
    with pytest.raises(requests.TooManyRedirects):
        fetch()
    assert sessions[0].max_redirects == requests.sessions.DEFAULT_REDIRECT_LIMIT == 30
    assert len(calls) == 31
    assert_owned(transport)
