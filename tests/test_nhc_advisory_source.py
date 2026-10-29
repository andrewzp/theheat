"""Fixed-source NHC advisory adapter over invented HTTP transports (no network)."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
import requests

from src.data import nhc_advisory as source
from src.editorial.nhc_advisory import AdvisoryHold
from tests import nhc_advisory_helpers as h


class Transport:
    """Invented responses by exact URL; records every request in order."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, url, *, limit):
        self.calls.append((url, limit))
        value = self.responses.get(url)
        if value is None:
            value = (200, {}, h.index() if url == source.INDEX_URL else h.page())
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def transport(monkeypatch):
    value = Transport()
    monkeypatch.setattr(source, "_http_get", value)
    return value


def clock():
    return h.CAPTURED


def test_one_current_read_is_exactly_two_fixed_requests_in_order(transport):
    with source.request_budget_scope() as budget:
        evidence = source.current_evidence(h.selected(), clock=lambda: h.CAPTURED + timedelta(seconds=1))
    assert [url for url, _ in transport.calls] == ["https://www.nhc.noaa.gov/CurrentStorms.json",
                                                   "https://www.nhc.noaa.gov/text/MIATCPEP5.shtml"]
    assert [limit for _, limit in transport.calls] == [128 * 1024, 8 * 1024 * 1024]
    assert budget.used == 2 and budget.remaining == 30
    assert evidence.capture.captured_at == "2026-10-29T21:26:01Z"


def test_budget_is_finite_per_phase_and_reads_need_a_scope(transport):
    with pytest.raises(AdvisoryHold) as unscoped:
        source.read_capture(h.selected(), clock=clock)
    assert unscoped.value.code == "nhc_advisory_request_budget_unscoped" and transport.calls == []
    with source.request_budget_scope() as budget:
        for _ in range(16):
            source.read_capture(h.selected(), clock=clock)
        with pytest.raises(AdvisoryHold) as exhausted:
            source.read_capture(h.selected(), clock=clock)
    assert exhausted.value.code == "nhc_advisory_request_budget_exhausted"
    assert budget.used == 32 and len(transport.calls) == 32
    for limit in (1, 33, "32"):
        with pytest.raises(AdvisoryHold):
            with source.request_budget_scope(limit):
                pass


def test_odd_budget_cannot_split_a_read_into_an_unchecked_half(transport):
    with source.request_budget_scope(3):
        source.read_capture(h.selected(), clock=clock)
        with pytest.raises(AdvisoryHold) as half:
            source.read_capture(h.selected(), clock=clock)
    assert half.value.code == "nhc_advisory_request_budget_exhausted"  # Index read, advisory refused.


@pytest.mark.parametrize("response,code", [
    ((301, {"location": "https://www.nhc.noaa.gov/other"}, b""), "nhc_advisory_redirect_refused"),
    ((302, {"location": "https://evil.example.test/"}, b""), "nhc_advisory_redirect_refused"),
    ((307, {}, b""), "nhc_advisory_redirect_refused"),
    ((404, {}, b""), "nhc_advisory_source_unavailable"),
    ((503, {}, b""), "nhc_advisory_source_unavailable"),
    ((200, {"content-encoding": "gzip"}, b"x"), "nhc_advisory_encoding_invalid"),
    ((200, {"content-length": "999"}, b"short"), "nhc_advisory_partial_response"),
    ((200, {}, b""), "nhc_advisory_response_bound"),
    (AdvisoryHold("nhc_advisory_source_slow"), "nhc_advisory_source_slow"),
], ids=["301", "302-other-host", "307", "404", "503", "gzip", "short", "empty", "slow"])
@pytest.mark.parametrize("which", ["index", "page"])
def test_http_irregularities_hold_with_named_codes(monkeypatch, response, code, which):
    url = source.INDEX_URL if which == "index" else h.URL
    fake = Transport({url: response})
    monkeypatch.setattr(source, "_http_get", fake)
    with source.request_budget_scope(), pytest.raises(AdvisoryHold) as raised:
        source.read_capture(h.selected(), clock=clock)
    assert raised.value.code == code
    assert len(fake.calls) == (1 if which == "index" else 2)  # Never a retry or redirect follow.


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(b"ok",), delay=0.0):
        self.status_code, self.headers, self._chunks, self._delay = status, headers or {}, chunks, delay

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        import time
        for chunk in self._chunks:
            time.sleep(self._delay)
            yield chunk


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.trust_env, self.max_redirects, self.calls = response, error, True, 30, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs, self.trust_env, self.max_redirects))
        if self.error is not None:
            raise self.error
        return self.response


def install_session(monkeypatch, session):
    original = source._session

    def build():
        real = original()
        session.trust_env, session.max_redirects = real.trust_env, real.max_redirects
        real.close()
        return session
    monkeypatch.setattr(source, "_session", build)


def test_real_transport_is_credential_free_single_attempt_without_redirects(monkeypatch):
    session = FakeSession(FakeResponse(chunks=(b"abc", b"def")))
    install_session(monkeypatch, session)
    assert source._http_get(h.URL, limit=10) == (200, {}, b"abcdef")
    (url, kwargs, trust_env, max_redirects), = session.calls
    assert url == h.URL and trust_env is False and max_redirects == 0
    assert kwargs == {"headers": {"User-Agent": "(theheat-bot, contact@theheat.app)", "Accept-Encoding": "identity"},
                      "timeout": (5, 10), "allow_redirects": False, "stream": True}


@pytest.mark.parametrize("session,code", [
    (FakeSession(FakeResponse(chunks=(b"x" * 11,))), "nhc_advisory_response_bound"),
    (FakeSession(error=requests.Timeout("secret-host.example token=abc")), "nhc_advisory_source_slow"),
    (FakeSession(error=requests.ConnectionError("secret-host.example token=abc")), "nhc_advisory_source_unavailable"),
    (FakeSession(error=requests.TooManyRedirects("x")), "nhc_advisory_source_unavailable"),
], ids=["bound", "timeout", "connection", "redirects"])
def test_transport_failures_are_named_holds_without_exception_text(monkeypatch, session, code):
    install_session(monkeypatch, session)
    with pytest.raises(AdvisoryHold) as raised:
        source._http_get(h.URL, limit=10)
    assert raised.value.code == code and str(raised.value) == code
    assert raised.value.__cause__ is None and (raised.value.__context__ is None or raised.value.__suppress_context__)


def test_slow_stream_holds_instead_of_borrowing_time(monkeypatch):
    monkeypatch.setattr(source, "REQUEST_SECONDS", 0.05)
    install_session(monkeypatch, FakeSession(FakeResponse(chunks=(b"a", b"b", b"c"), delay=0.03)))
    with pytest.raises(AdvisoryHold) as raised:
        source._http_get(h.URL, limit=100)
    assert raised.value.code == "nhc_advisory_source_slow"


def test_a_caller_cannot_supply_a_url_host_or_path():
    with source.request_budget_scope(), pytest.raises(AdvisoryHold) as raised:
        source.read_capture(SimpleNamespace(advisory_url="https://evil.example.test/x"), clock=clock)
    assert raised.value.code == "nhc_advisory_nomination_invalid"
    assert {h.selected(bin=b, storm_id="EP492026").advisory_url for b in ("EP1", "EP5")} == {
        "https://www.nhc.noaa.gov/text/MIATCPEP1.shtml", "https://www.nhc.noaa.gov/text/MIATCPEP5.shtml"}


def test_fresh_read_that_disagrees_with_the_nomination_holds(transport):
    transport.responses[source.INDEX_URL] = (200, {}, h.index(advisory="35"))
    with source.request_budget_scope(), pytest.raises(AdvisoryHold) as raised:
        source.current_evidence(h.selected(), clock=lambda: h.CAPTURED)
    assert raised.value.code == "nhc_advisory_superseded"
