"""Bounded source-failure diagnostics; all HTTP and SDK data are invented."""
from datetime import timedelta

from freezegun import freeze_time
import pytest
import requests

from src.data import awc_observed as source
from tests import live_content_harness as h
from tests.test_awc_observed import NOW
from tests.test_awc_observed_automatic import sender
from tests.test_observed_airport_body_budget import SHORT, ordinary, stage_and_drain

PRIVATE_MARKER = "invented-private-response-and-exception-do-not-log"
CASES = [
    ("http", 401, "awc_http_401"), ("http", 403, "awc_http_403"),
    ("http", 404, "awc_http_404"), ("http", 429, "awc_http_429"),
    ("http", 500, "awc_http_500"), ("http", 503, "awc_http_503"),
    ("timeout", None, "awc_transport_timeout"),
    ("tls", None, "awc_transport_tls"),
    ("connection", None, "awc_transport_connection"),
    ("stream", None, "awc_response_stream_error"),
    ("request", None, "awc_request_error"),
    ("http-no-response", None, "awc_http_error"),
    ("unexpected", None, "awc_current_source_unexpected"),
]


def fail_history(monkeypatch, kind, status=None, *, at_call=1):
    original = requests.adapters.HTTPAdapter.send
    attempts, closed = [], []

    def fail(adapter, request, **options):
        if not request.url.startswith(source.HISTORY_URL + "?"):
            return original(adapter, request, **options)
        attempts.append(request.url)
        assert options["stream"] is True and options["timeout"] == 12
        assert options["verify"] is True
        if len(attempts) < at_call:
            return original(adapter, request, **options)
        if kind in ("http", "stream"):
            response = h._reply(request, status if kind == "http" else 200, PRIVATE_MARKER.encode())
            response.reason = PRIVATE_MARKER
            close = response.close

            def record_close():
                closed.append(True)
                close()

            monkeypatch.setattr(response, "close", record_close)
            if kind == "stream":
                def chunks(size):
                    assert size == 64 * 1024
                    yield b"<response>"
                    raise requests.exceptions.ChunkedEncodingError(PRIVATE_MARKER)
                monkeypatch.setattr(response, "iter_content", chunks)
            return response
        errors = {
            "timeout": requests.exceptions.ReadTimeout,
            "tls": requests.exceptions.SSLError,
            "connection": requests.exceptions.ConnectionError,
            "request": requests.exceptions.RequestException,
            "http-no-response": requests.exceptions.HTTPError,
            "unexpected": TypeError,
        }
        raise errors[kind](PRIVATE_MARKER)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fail)
    return attempts, closed


@pytest.mark.parametrize("kind,status,expected", CASES, ids=[f"{k}-{s}" for k, s, _ in CASES])
@pytest.mark.parametrize("consumer", ["bundle", "draft"])
def test_actual_currentness_consumer_retains_bounded_failure_without_a_retry_or_secret(
        monkeypatch, fresh_state, capsys, kind, status, expected, consumer):
    transport, models, _run, _budget = ordinary(monkeypatch, fresh_state)
    with freeze_time(NOW, tick=True):
        evidence = source.nominate()
        bundle = source.build_bundle(evidence)
    draft = {"type": source.KIND, "event_id": bundle.event_id,
             "text": SHORT + "\n" + evidence["source_url"],
             "review_context": {"two_bot": {"bundle": bundle.to_dict()}}}
    attempts, closed = fail_history(monkeypatch, kind, status)
    at = NOW + timedelta(minutes=1)
    if consumer == "bundle":
        hold = source.current_bundle_hold(bundle, live=True, now=lambda: at)
    else:
        hold = source.current_draft_hold(draft, live=True, now=lambda: at)
    assert hold == expected
    assert len(attempts) == 1
    assert len(closed) == (1 if kind in ("http", "stream") else 0)
    assert PRIVATE_MARKER not in str(hold)
    output = capsys.readouterr()
    assert PRIVATE_MARKER not in output.out + output.err
    assert models.stages() == [] and fresh_state["drafts"] == []
    assert transport.x_posts == [] and transport.gist_patches == 0


@pytest.mark.parametrize("kind,status,expected", [
    ("http", 429, "awc_http_429"), ("timeout", None, "awc_transport_timeout"),
    ("unexpected", None, "awc_current_source_unexpected"),
])
@pytest.mark.parametrize("at_call", [1, 2], ids=["before-intent", "after-intent"])
def test_real_sender_still_revokes_failed_source_approval_and_names_observed_airport_evidence(
        monkeypatch, fresh_state, capsys, kind, status, expected, at_call):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 1
    [draft] = fresh_state["drafts"]
    assert draft["approval_binding"]["mode"] == "auto"
    attempts, closed = fail_history(monkeypatch, kind, status, at_call=at_call)
    sender(monkeypatch, (transport, fresh_state, run, [], []), at=NOW + timedelta(minutes=2))
    assert len(attempts) == at_call  # Existing distinct source boundaries, not a failed-read retry.
    assert draft["post_error"] == f"Observed airport report needs fresh source review: {expected}"
    assert draft["status"] == "pending" and draft["approval_mode"] == "manual"
    assert draft.get("approval_binding") is None
    if at_call == 2:
        assert draft["publish_outcome"] == "not_sent"
        assert fresh_state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"
    else:
        assert "publish_outcome" not in draft and draft["event_id"] not in fresh_state.get("publish_ledger", {})
    assert "tweet_id" not in draft and transport.x_posts == []
    assert models.stages().count("writer") == 1  # No fallback generation or substitute.
    assert len(closed) == (1 if kind == "http" else 0)
    output = capsys.readouterr()
    assert PRIVATE_MARKER not in output.out + output.err + draft["post_error"]
