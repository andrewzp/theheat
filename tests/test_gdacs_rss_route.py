"""Qualified RSS routing and bounded response consumption, no live source calls."""

from copy import deepcopy
from datetime import UTC, datetime
import gzip
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import responses

from src.data import _http, gdacs
from src.data.source_status import SourceFetchError
from src.orchestrator.sources.gdacs import run_gdacs
from src.state import DEFAULT_STATE
from tests.test_gdacs import SAMPLE_RESPONSE

BODY = Path(__file__).parent / "fixtures/gdacs_georss_unknown_country.xml"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: datetime(2026, 9, 9, tzinfo=UTC))


@responses.activate
def test_valid_unqualified_json_cannot_bypass_rss_current_episode_and_provenance(monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_URL, json=SAMPLE_RESPONSE)
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=BODY.read_bytes())
    witness = Mock(side_effect=AssertionError("A qualified response is not an outage"))
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness)
    events = gdacs.fetch_disasters(strict=True)
    assert [call.request.url for call in responses.calls] == [gdacs.GDACS_GEORSS_URL]
    assert [event.source_event_id for event in events] == ["fixture-red"]
    assert all(event.source_product == "gdacs-georss" and event.source_leg == "georss" for event in events)
    assert events.source_diagnostics["map_status"] == "withdrawn_unqualified"
    assert "primary_error_class" not in events.source_diagnostics
    witness.assert_not_called()


@responses.activate
def test_runner_preserves_visible_limited_product_when_zero_alerts_qualify(monkeypatch):
    body = BODY.read_text().replace("<gdacs:episodealertlevel>Red</gdacs:episodealertlevel>",
                                   "<gdacs:episodealertlevel>Green</gdacs:episodealertlevel>")
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=body)
    enqueue = Mock(side_effect=AssertionError("Withheld current episode cannot be drafted"))
    witness = Mock(side_effect=AssertionError("Zero selection is not an outage"))
    monkeypatch.setattr("src.orchestrator.sources.gdacs._enqueue_story_candidate", enqueue)
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness)
    run = {"sources": []}
    run_gdacs(deepcopy(DEFAULT_STATE), run)
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == 0
    assert "configured limited GeoRSS product; MAP withdrawn" in row["note"]
    diagnostic = row["details"]["feed_diagnostics"]
    assert diagnostic["configured_product"] == "gdacs-georss"
    assert diagnostic["withheld_current_by_reason"]["episode_below_threshold"] == 1
    assert diagnostic["selected_alerts"] == 0
    assert len(responses.calls) == 1 and not witness.called and not enqueue.called


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False
        self.headers = {"Content-Length": "1"}  # Never sufficient as a size proof.

    @property
    def text(self):
        raise AssertionError("Do not buffer an unbounded response")

    def iter_content(self, *, chunk_size):
        assert chunk_size == 32768
        for chunk in self.chunks:
            self.reads += 1
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize("extra", [0, 1])
def test_exact_body_byte_limit_closes_without_consuming_rest(monkeypatch, extra):
    monkeypatch.setattr(gdacs, "MAX_GEORSS_BYTES", 8)
    stream = Stream([b"abcd", b"efgh" + b"x" * extra] + ([b"must-not-read"] if extra else []))
    fetch = Mock(return_value=stream)
    monkeypatch.setattr(gdacs, "fetch_with_retry", fetch)
    if extra:
        with pytest.raises(SourceFetchError, match="body byte bound"):
            gdacs._read_georss_body()
    else:
        assert gdacs._read_georss_body() == "abcdefgh"
    assert stream.closed and stream.reads == 2
    fetch.assert_called_once_with(gdacs.GDACS_GEORSS_URL, timeout=30, attempts=3, backoff_base=1.0, stream=True)


@pytest.mark.parametrize("parts,expected", [([b"\xef\xbb\xbf", b"<rss/>"] , "\ufeff<rss/>"),
    ([b"caf\xc3", b"\xa9"], "café"), ([b"", b"<rss/>", b""], "<rss/>")])
def test_body_preserves_bom_and_split_utf8_without_replacement(monkeypatch, parts, expected):
    stream = Stream(parts)
    monkeypatch.setattr(gdacs, "fetch_with_retry", Mock(return_value=stream))
    assert gdacs._read_georss_body() == expected and stream.closed


@pytest.mark.parametrize("failure,expected", [(b"\xff", SourceFetchError),
    (requests.ConnectionError("body interrupted"), requests.ConnectionError),
    (requests.Timeout("body timed out"), requests.Timeout),
    (requests.exceptions.ContentDecodingError("bad gzip"), SourceFetchError)])
def test_body_failures_close_and_do_not_start_another_retry_loop(monkeypatch, failure, expected):
    stream = Stream([b"<rss>", failure, b"must-not-read"])
    fetch = Mock(return_value=stream)
    monkeypatch.setattr(gdacs, "fetch_with_retry", fetch)
    with pytest.raises(expected):
        gdacs._read_georss_body()
    assert stream.closed and stream.reads == 2 and fetch.call_count == 1


@responses.activate
@pytest.mark.parametrize("oversize", [False, True])
def test_actual_requests_gzip_decoding_uses_decoded_size_not_small_wire_size(monkeypatch, oversize):
    body = BODY.read_bytes()
    if oversize:
        body += b" " * gdacs.MAX_GEORSS_BYTES
    compressed = gzip.compress(body)
    assert len(compressed) < gdacs.MAX_GEORSS_BYTES
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=compressed,
                  headers={"Content-Encoding": "gzip"})
    if oversize:
        with pytest.raises(SourceFetchError, match="body byte bound"):
            gdacs.fetch_disasters(strict=True)
    else:
        assert len(gdacs.fetch_disasters(strict=True)) == 1
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("status", [400, 401, 404, 410])
def test_access_or_configuration_failure_cannot_be_hidden_by_witness(status, monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, status=status)
    witness = Mock(side_effect=AssertionError("Configuration/access is not an outage"))
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness)
    with pytest.raises(SourceFetchError):
        gdacs.fetch_disasters(strict=True)
    assert len(responses.calls) == 1 and not witness.called


@responses.activate
@pytest.mark.parametrize("body", [b"<rss><channel /></rss>", b"<broken", b"\xff"])
def test_invalid_source_body_never_invokes_an_unrelated_witness(body, monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=body)
    witness = Mock(side_effect=AssertionError("Malformed source data is not an outage"))
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness)
    with pytest.raises(SourceFetchError, match="schema drift"):
        gdacs.fetch_disasters(strict=True)
    assert len(responses.calls) == 1 and not witness.called


@responses.activate
@pytest.mark.parametrize("strict", [False, True])
def test_only_strict_transport_outage_uses_witness_after_existing_retry_cap(strict, monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, status=503)
    witness = Mock(return_value=[])
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness)
    assert gdacs.fetch_disasters(strict=strict) == []
    assert len(responses.calls) == 3 and witness.call_count == int(strict)
    assert all(call.request.url == gdacs.GDACS_GEORSS_URL for call in responses.calls)


@pytest.mark.parametrize("codes", [[502, 200], [502, 503, 504], [401], [403, 403]])
def test_streaming_header_errors_close_each_discarded_response_before_retry(monkeypatch, codes):
    url = "https://www.metoc.navy.mil/fixture" if codes[0] == 403 else gdacs.GDACS_GEORSS_URL
    results = []
    for code in codes:
        response = requests.Response()
        response.status_code = code
        response.url = url
        response.close = Mock()
        results.append(response)
    session = Mock()
    def next_response(*args, **kwargs):
        index = session.get.call_count - 1
        if index:
            results[index - 1].close.assert_called_once()
        return results[index]
    session.get.side_effect = next_response
    monkeypatch.setattr(_http, "_get_session", lambda: session)
    monkeypatch.setattr(_http, "_waf_sleep", lambda: None)
    monkeypatch.setitem(_http._waf_budget, "remaining", 4)
    if codes[-1] == 200:
        assert _http.fetch_with_retry(url, stream=True) is results[-1]
        results[-1].close.assert_not_called()  # Caller owns the successful body.
    else:
        with pytest.raises(requests.HTTPError):
            _http.fetch_with_retry(url, stream=True)
    for response in results:
        if response.status_code != 200:
            response.close.assert_called_once()
    assert session.get.call_count == len(codes)
