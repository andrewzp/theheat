"""Invented provider errors stay diagnostics, never nominations or weather facts."""
from datetime import date
from dataclasses import asdict
import hashlib
import http.client
from io import BytesIO
import json
from unittest.mock import patch

import pytest
import requests
from urllib3.response import HTTPResponse as RawHTTPResponse

from src.data import ghcn_discovery as discovery
from dashboard.tests.fixtures.ghcn_archive_intake_producer import archive_bytes
from tests.ghcn_intake_cases import SID
from tests.test_ghcn_discovery_hints import Reply, Raw, TARGET, fetch_reply, known_cache, invoke


def error_body(**change):
    value = {"errorCode": 400, "errorMessage": "Bad Request", "errors": [
        {"field": "units", "message": "Invalid units. Valid units are standard or metric.", "value": "private-ignored-value"}]}
    value.update(change)
    return json.dumps(value).encode()


def chunked_reply(body, *, status=400, separator=b"\r\n", trailer=b"\r\n"):
    wire = (f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n".encode()
            + f"{len(body):x}\r\n".encode() + body + separator + b"0\r\n" + trailer)

    class Sock:
        def makefile(self, *_args, **_kwargs):
            return BytesIO(wire)

    original = http.client.HTTPResponse(Sock())
    original.begin()
    reply = Reply(body, status)
    reply.headers.pop("Content-Length")
    reply.headers["Transfer-Encoding"] = "chunked"
    reply.raw = RawHTTPResponse(body=original, headers={"Transfer-Encoding": "chunked"}, status=status,
                                preload_content=False, decode_content=False)
    return reply


@pytest.mark.parametrize("status", [200, 400])
def test_multiple_supported_chunks_keep_the_original_payload_and_response_meaning(status):
    from tests.test_ghcn_discovery_hints import hint

    body = error_body() if status == 400 else json.dumps([hint()]).encode()
    wire = f"HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n".encode()
    for part in (body[:3], body[3:17], body[17:]):
        wire += f"{len(part):x}\r\n".encode() + part + b"\r\n"
    wire += b"0\r\n\r\n"

    class Sock:
        def makefile(self, *_args, **_kwargs):
            return BytesIO(wire)

    original = http.client.HTTPResponse(Sock())
    original.begin()
    reply = Reply(body, status)
    reply.headers.pop("Content-Length")
    reply.headers["Transfer-Encoding"] = "chunked"
    reply.raw = RawHTTPResponse(body=original, headers={"Transfer-Encoding": "chunked"}, status=status,
                                preload_content=False, decode_content=False)
    candidates, metadata = fetch_reply(reply)
    if status == 400:
        assert not candidates and metadata["provider_error"]["body_sha256"] == hashlib.sha256(body).hexdigest()
    else:
        assert candidates == {TARGET} and metadata["response_sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("message", ["PRIVATE_FIXTURE_VALUE Authorization: Bearer INVENTED_TOKEN ftp://invented.invalid/private",
                                     "PRIVATE_FIXTURE_VALUE", "unexpected \u202ereversed"])
def test_untrusted_message_never_retains_arbitrary_text_even_when_it_echoes_the_value(message):
    body = error_body(errors=[{"field": "units", "message": message, "value": "PRIVATE_FIXTURE_VALUE"}])
    _, metadata = fetch_reply(Reply(body, 400))
    stored = json.dumps(metadata, ensure_ascii=False)
    assert all(value not in stored for value in ["PRIVATE_FIXTURE_VALUE", "Authorization", "INVENTED_TOKEN", "ftp://", "\u202e"])


@pytest.mark.parametrize("status", [200, 400])
def test_bad_data_chunk_separator_refuses_both_hints_and_error_diagnostics(status):
    from tests.test_ghcn_discovery_hints import hint

    body = error_body() if status == 400 else json.dumps([hint()]).encode()
    candidates, metadata = fetch_reply(chunked_reply(body, status=status, separator=b"XX"))
    assert not candidates
    if status == 400:
        assert metadata.get("provider_error") is None
    else:
        assert metadata["status"] == "unavailable"


@pytest.mark.parametrize("status", [200, 400])
def test_present_empty_transfer_encoding_cannot_be_treated_as_absent(status):
    from tests.test_ghcn_discovery_hints import hint

    reply = Reply(error_body() if status == 400 else json.dumps([hint()]).encode(), status)
    reply.headers["Transfer-Encoding"] = ""
    candidates, metadata = fetch_reply(reply)
    assert not candidates and reply.raw.tell() == 0
    if status == 400:
        assert metadata.get("provider_error") is None


@pytest.mark.parametrize("when", ["headers", "first_chunk"])
def test_cancellation_stops_the_next_optional_diagnostic_read_and_closes_once(when):
    from src.two_bot.call_inventory import CancelToken, OperationCancelled, run_cancellable

    token, reads = CancelToken("invented-diagnostic-cancellation"), []

    class Chunks(Raw):
        def read1(self, size=-1, **kwargs):
            reads.append(token.cancelled)
            part = super().read1(min(size, 16), **kwargs)
            if when == "first_chunk":
                token.cancel("cancelled_diagnostic_read")
            return part

    reply = Reply(error_body(), 400)
    reply.raw = Chunks(error_body())

    def get(*args, **kwargs):
        if when == "headers":
            token.cancel("cancelled_diagnostic_read")
        return reply

    with patch.object(discovery.requests, "get", get), pytest.raises(OperationCancelled, match="cancelled_diagnostic_read"):
        run_cancellable(token, discovery.fetch_nominations, frozenset({TARGET}), known_cache(),
                        today=date(2026, 11, 21), max_age_days=4, anomaly=8)
    assert reads == ([] if when == "headers" else [False])
    assert reply.closed == 1 and reply.raw.tell() == (0 if when == "headers" else 16)


def test_complete_provider_error_keeps_only_bounded_inert_diagnostic_and_never_nominates():
    body = error_body()
    candidates, metadata = fetch_reply(Reply(body, 400))
    assert candidates == set() and metadata["status"] == "unavailable" and metadata["http_status"] == 400
    assert metadata["schema_version"] == 2 and metadata["reason"] == "http_error"
    assert metadata["provider_error"] == {
        "schema_version": 1, "scope": "untrusted_provider_error_not_weather",
        "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
        "fields": [{"field": "units", "message_code": "invalid_units"}]}
    assert metadata["response_bytes"] is None and metadata["rows_received"] is None
    assert metadata["nominated_stations"] == 0 and "private-ignored-value" not in json.dumps(metadata)


@pytest.mark.parametrize("body", [b"{", b"null", b"[]", b"[{}]", b"\xff",
    b'{"errorCode":400,"errorCode":400,"errors":[]}',
    error_body(errorCode=True), error_body(errorCode=500), error_body(errors=[]),
    error_body(errors=[{"field": "units", "message": "bad\ncontrol"}]),
    error_body(errors=[{"field": "units", "message": "bad\u0085control"}]),
    error_body(errors=[{"field": "units", "message": "\ud800"}]),
    error_body(errors=[{"field": "units", "message": "https://invented.invalid/"}]),
    error_body(errors=[{"field": "units", "message": "x" * 241}]),
    error_body(errors=[{"field": "unsupported", "message": "Bad request"}]),
    error_body(errors=[{"field": "units", "message": {"weather": 49}}]),
    error_body(errors=[{"field": "units", "message": "Bad request"}] * 9),
    error_body(extra="not-an-error-schema"),
])
def test_malformed_diagnostic_keeps_http_refusal_and_no_weather_authority(body):
    candidates, metadata = fetch_reply(Reply(body, 400))
    assert not candidates and metadata["reason"] == "http_error" and metadata["http_status"] == 400
    assert metadata["schema_version"] == 2 and metadata["provider_error"] is None
    assert metadata["nominated_stations"] == 0 and metadata["numeric_hints"] is None


@pytest.mark.parametrize("headers", [
    {"Content-Type": "text/html"}, {"Content-Encoding": "gzip"},
    {"Content-Length": "8193"}, {"Content-Length": "1"},
    {"Transfer-Encoding": "chunked"},
])
def test_unproven_error_body_framing_is_not_reported_as_a_complete_diagnostic(headers):
    reply = Reply(error_body(), 400)
    reply.headers.update(headers)
    candidates, metadata = fetch_reply(reply)
    assert not candidates and metadata["provider_error"] is None


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_other_error_responses_keep_existing_shape_and_are_not_read(status):
    reply = Reply(error_body(), status)
    candidates, metadata = fetch_reply(reply)
    assert not candidates and metadata["schema_version"] == 1 and "provider_error" not in metadata
    assert reply.raw.tell() == 0


def test_expired_error_read_deadline_does_not_start_a_diagnostic_read():
    reply = Reply(error_body(), 400)
    times = iter([0, 16])
    candidates, metadata = fetch_reply(reply, clock=lambda: next(times))
    assert not candidates and metadata["provider_error"] is None and reply.raw.tell() == 0


@pytest.mark.parametrize("trailer,complete,size", [(b"\r\n", True, None), (b"", False, None),
    (b"X-Foo: cut", False, None), (b"\r\n", True, 8192), (b"\r\n", False, 9000)])
def test_real_chunked_error_diagnostic_requires_complete_supported_framing(trailer, complete, size):
    body = error_body()
    if size is not None:
        body += b" " * (size - len(body))
    wire = (b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
            + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n" + trailer)

    class Sock:
        def makefile(self, *_args, **_kwargs):
            return BytesIO(wire)

    original = http.client.HTTPResponse(Sock())
    original.begin()
    reply = Reply(body, 400)
    reply.headers.pop("Content-Length")
    reply.headers["Transfer-Encoding"] = "chunked"
    reply.raw = RawHTTPResponse(body=original, headers={"Transfer-Encoding": "chunked"}, status=400,
                                preload_content=False, decode_content=False)
    candidates, metadata = fetch_reply(reply)
    assert not candidates and (metadata["provider_error"] is not None) is complete
    assert reply.raw.tell() <= 8193


def test_weather_shaped_error_cannot_reach_the_nomination_parser():
    from tests.test_ghcn_discovery_hints import hint

    with patch.object(discovery, "nominate", side_effect=AssertionError("error body is not weather")):
        candidates, metadata = fetch_reply(Reply(json.dumps([hint()]).encode(), 400))
    assert not candidates and metadata["provider_error"] is None and metadata["numeric_hints"] is None


def test_error_diagnostic_refusal_keeps_original_tracked_signal_and_never_enters_its_evidence(tmp_path):
    (signals, _), metrics, calls, _ = invoke(tmp_path, hint_status=400, hint_body=error_body(),
                                            tracked_payload=archive_bytes())
    assert len(signals) == 1 and signals[0].station_id == SID and len(calls) == 32
    assert metrics["station_discovery"]["provider_error"] is not None
    assert "Unsupported units" not in json.dumps([asdict(row) for row in signals], default=str)


def test_cancelled400_diagnostic_cannot_start_later_archives(tmp_path):
    from src.two_bot.call_inventory import CancelToken, OperationCancelled, run_cancellable

    token, calls = CancelToken("invented-error-diagnostic"), []
    with pytest.raises(OperationCancelled, match="cancelled_error_response"):
        run_cancellable(token, invoke, tmp_path, calls_out=calls, hint_status=400, hint_body=error_body(),
                        on_hint=lambda: token.cancel("cancelled_error_response"))
    assert len(calls) == 31 and all("/all/" not in url for url, _ in calls)


def test_genuine_requests_and_shared_fetch_close_once_without_redirect_auth_or_second_send(monkeypatch):
    body = error_body()

    class CountedRaw(Raw):
        consumed = 0
        close_calls = 0

        def read1(self, size=-1, **kwargs):
            result = super().read1(size, **kwargs)
            self.consumed += len(result)
            return result

        def close(self):
            self.close_calls += 1
            super().close()

    raw = CountedRaw(body)
    response = requests.Response()
    response.status_code, response.raw = 400, raw
    response.headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})

    class Adapter(requests.adapters.BaseAdapter):
        sent = 0

        def send(self, request, **kwargs):
            self.sent += 1
            self.prepared = request
            response.request, response.url = request, request.url
            return response

        def close(self):
            pass

    session, adapter = requests.Session(), Adapter()
    session.mount("https://", adapter)
    with patch.object(requests.sessions, "Session", return_value=session), \
         patch.object(requests.sessions, "get_netrc_auth", return_value=None) as netrc:
        candidates, metadata = discovery.fetch_nominations(frozenset({TARGET}), known_cache(),
            today=date(2026, 11, 21), max_age_days=4, anomaly=8)
    assert not candidates and metadata["provider_error"]["fields"][0]["field"] == "units"
    assert (adapter.sent, metadata["get_calls"], raw.close_calls, raw.consumed, netrc.call_count) == (1, 1, 1, len(body), 0)
    assert adapter.prepared.url == (discovery.URL + "?dataset=daily-summaries&startDate=2026-11-17"
        "&endDate=2026-11-21&dataTypes=TMAX%2CTMIN&units=metric&format=json")
    assert "Authorization" not in adapter.prepared.headers
