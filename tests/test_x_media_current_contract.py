"""Current production media wire, with invented OAuth and no external socket."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
import requests
import tweepy

from src.posting import twitter

PNG = b"\x89PNG\r\n\x1a\ninvented-fixture-only"
MEDIA_ID = "1234567890123456789"


@pytest.fixture(autouse=True)
def invented_credentials(monkeypatch):
    for name, value in (("API_KEY", "invented-key"), ("API_SECRET", "invented-secret"),
                        ("ACCESS_TOKEN", "invented-token"), ("ACCESS_SECRET", "invented-token-secret")):
        monkeypatch.setattr(twitter, name, value)
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *args, **kwargs: pytest.fail("network forbidden"))


def wire(monkeypatch, replies):
    requests_seen, sessions_closed = [], []
    original_close = requests.Session.close

    def send(session, request, **kwargs):
        requests_seen.append((request, kwargs, session.trust_env, session.get_adapter(request.url).max_retries.total))
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        status, payload = reply
        response = requests.Response()
        response.status_code = status
        response.reason = "fixture"
        response.url, response.request = request.url, request
        response._content = payload if type(payload) is bytes else json.dumps(payload).encode()
        response._content_consumed = True
        response.headers["Content-Type"] = "application/json"
        return response

    def close(session):
        sessions_closed.append(session)
        return original_close(session)

    monkeypatch.setattr(requests.Session, "send", send)
    monkeypatch.setattr(requests.Session, "close", close)
    return requests_seen, sessions_closed


def uploaded(**extra):
    return {"data": {"id": MEDIA_ID, "size": len(PNG), **extra}}


def test_actual_factory_uses_current_upload_contract(monkeypatch):
    seen, closed = wire(monkeypatch, [(200, uploaded())])
    media = twitter.upload_png(twitter._get_upload_api(), PNG)
    request, options, trust_env, retries = seen[0]
    assert request.method == "POST"
    assert request.url == "https://api.x.com/2/media/upload"
    assert json.loads(request.body) == {
        "media": base64.b64encode(PNG).decode("ascii"), "media_category": "tweet_image"}
    assert str(media.media_id) == MEDIA_ID
    auth = request.headers["Authorization"]
    if isinstance(auth, str):
        auth = auth.encode("ascii")
    assert auth.startswith(b"OAuth ") and b'invented-key' in auth and b'invented-token' in auth
    assert b'invented-secret' not in auth and b'invented-token-secret' not in auth
    assert options["allow_redirects"] is False and options["timeout"] == (5, 5)
    assert trust_env is False and retries == 0 and len(closed) == 1


def test_post_tweet_uses_upload_metadata_create_in_order(monkeypatch):
    seen, closed = wire(monkeypatch, [(200, uploaded()), (200, {"data": {"id": MEDIA_ID}})])
    created = []

    def create_tweet(**kwargs):
        assert len(seen) == 2
        created.append(kwargs)
        return SimpleNamespace(data={"id": "987654321"})

    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(create_tweet=create_tweet))
    assert twitter.post_tweet("Observed fixture context.", PNG, "Cold −34°C; warm 36°C.") == {
        "id": "987654321", "text": "Observed fixture context."}
    assert [row[0].url for row in seen] == [
        "https://api.x.com/2/media/upload", "https://api.x.com/2/media/metadata"]
    assert json.loads(seen[1][0].body) == {
        "id": MEDIA_ID, "metadata": {"alt_text": {"text": "Cold −34°C; warm 36°C."}}}
    assert created == [{"text": "Observed fixture context.", "media_ids": [MEDIA_ID]}]
    assert len(closed) == 2


@pytest.mark.parametrize("payload", [
    {}, {"data": {}}, {"data": {"id": 123}}, {"data": {"id": "0"}},
    {"data": {"id": "01"}}, {"data": {"id": "1,2"}}, {"data": {"id": "１"}},
    {"data": {"id": "1" * 20}}, {"data": {"id": MEDIA_ID, "size": True}},
    uploaded(size=len(PNG) + 1), uploaded(processing_info={"state": "pending"}),
    uploaded(processing_info={"state": "failed"}),
    {"data": {"id": MEDIA_ID}, "errors": [{"detail": "private provider prose"}]},
    b'{"data":{"id":"123"},"data":{"id":"456"}}', b'{"data":',
    b"x" * 65537,
], ids=["no-data", "no-id", "numeric-id", "zero-id", "leading-zero", "packed-id", "unicode-id",
        "long-id", "boolean-size", "wrong-size", "pending", "failed", "errors", "duplicate-json", "partial", "oversize"])
def test_upload_failure_cannot_advance_to_metadata_or_create(monkeypatch, payload, capsys):
    seen, closed = wire(monkeypatch, [(200, payload)])
    created = []
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(
        create_tweet=lambda **kwargs: created.append(kwargs)))
    assert twitter.post_tweet("Fixture.", PNG, "Fixture alt.") is None
    assert len(seen) == len(closed) == 1 and not created
    assert "private provider prose" not in capsys.readouterr().out


@pytest.mark.parametrize("status,expected", [(301, None), (401, None), (402, None),
                                          (403, None), (429, {"error": "rate_limited"}), (500, None)])
def test_http_refusal_is_single_request_without_fallback(monkeypatch, status, expected, capsys):
    seen, closed = wire(monkeypatch, [(status, {"detail": "private response"})])
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(
        create_tweet=lambda **kwargs: pytest.fail("must not create")))
    assert twitter.post_tweet("Fixture.", PNG, "Alt.") == expected
    assert len(seen) == len(closed) == 1
    assert "private response" not in capsys.readouterr().out


@pytest.mark.parametrize("error", [requests.Timeout("private timeout"), requests.ConnectionError("private connection")])
def test_transport_failure_is_unknown_without_retry(monkeypatch, error, capsys):
    seen, closed = wire(monkeypatch, [error])
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(
        create_tweet=lambda **kwargs: pytest.fail("must not create")))
    assert twitter.post_tweet("Fixture.", PNG, "Alt.") is None
    assert len(seen) == len(closed) == 1
    assert "private" not in capsys.readouterr().out


@pytest.mark.parametrize("png", [b"", b"not png", b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024)],
                         ids=["empty", "non-png", "oversize"])
def test_bad_image_refuses_before_admission(monkeypatch, png):
    seen, _ = wire(monkeypatch, [])
    monkeypatch.setattr(twitter, "_declared", lambda *args: pytest.fail("must validate before admission"))
    with pytest.raises(tweepy.TweepyException, match="x_media_png_invalid"):
        twitter.upload_png(twitter._get_upload_api(), png)
    assert seen == []


@pytest.mark.parametrize("identity,alt", [("0", "Alt"), ("1,2", "Alt"),
                                        (MEDIA_ID, ""), (MEDIA_ID, "x" * 1001), (MEDIA_ID, "\ud800")],
                         ids=["zero-id", "packed-id", "empty-alt", "long-alt", "surrogate"])
def test_bad_metadata_refuses_before_admission(monkeypatch, identity, alt):
    seen, _ = wire(monkeypatch, [])
    monkeypatch.setattr(twitter, "_declared", lambda *args: pytest.fail("must validate before admission"))
    with pytest.raises(tweepy.TweepyException, match="x_media_metadata_invalid"):
        twitter.set_alt_text(twitter._get_upload_api(), identity, alt)
    assert seen == []


@pytest.mark.parametrize("payload", [{}, {"data": {"id": "987"}},
                                    {"data": {"id": MEDIA_ID}, "errors": [{}]}])
def test_metadata_acknowledgement_must_bind_the_uploaded_id(monkeypatch, payload):
    seen, closed = wire(monkeypatch, [(200, payload)])
    with pytest.raises(tweepy.TweepyException, match="x_media_response_invalid"):
        twitter.set_alt_text(twitter._get_upload_api(), MEDIA_ID, "Alt")
    assert len(seen) == len(closed) == 1


@pytest.mark.parametrize("reply,expected", [
    ((403, {}), "not_sent"), (requests.Timeout("fixture"), "unknown"),
    ((200, {"data": {}}), "unknown"),
], ids=["complete-rejection", "lost-response", "unusable-response"])
def test_real_current_wire_preserves_outbox_refusal_classes(monkeypatch, reply, expected):
    from src.posting.outbox_outcome import classify, recording
    seen, closed = wire(monkeypatch, [reply])
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(
        create_tweet=lambda **kwargs: pytest.fail("must not create")))
    with recording() as report:
        result = twitter.post_tweet("Fixture.", PNG, "Alt.")
    outcome = classify(report, result)
    assert outcome["status"] == expected and outcome["stage"] == "upload"
    assert len(seen) == len(closed) == 1


def test_invalid_png_is_proven_no_egress_not_an_unknown_send(monkeypatch):
    from src.posting.outbox_outcome import classify, recording
    seen, _ = wire(monkeypatch, [])
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(
        create_tweet=lambda **kwargs: pytest.fail("must not create")))
    with recording() as report:
        result = twitter.post_tweet("Fixture.", b"not-png", "Alt.")
    assert classify(report, result)["status"] == "not_sent"
    assert report["stages"] == [] and seen == []


def test_current_media_phases_keep_existing_paid_call_tickets(monkeypatch):
    from src.two_bot import call_inventory
    from src.posting.outbox_outcome import classify, recording
    seen, _ = wire(monkeypatch, [(200, uploaded()), (200, {"data": {"id": MEDIA_ID}})])
    tickets = []

    def consume(stage, *, provider):
        assert stage == "x_publish" and provider == "x"
        row = []
        tickets.append(row)
        return SimpleNamespace(settle=row.append)

    monkeypatch.setattr(call_inventory, "consume", consume)
    monkeypatch.setattr(twitter, "_get_client", lambda: SimpleNamespace(
        create_tweet=lambda **kwargs: SimpleNamespace(data={"id": "987654321"})))
    with recording() as report:
        result = twitter.post_tweet("Fixture.", PNG, "Alt.")
    assert [entry["stage"] for entry in report["stages"]] == ["upload", "alt", "create"]
    assert tickets == [["returned"], ["returned"], ["returned"]]
    assert classify(report, result)["status"] == "confirmed" and len(seen) == 2


@pytest.mark.parametrize("extra", [
    {"expires_after_secs": 0}, {"expires_after_secs": -1}, {"expires_after_secs": True},
    {"processing_info": {"state": "succeeded", "error": {"name": "failed"}}},
], ids=["expired", "negative-expiry", "boolean-expiry", "contradictory-processing"])
def test_unusable_upload_does_not_grant_a_media_id(monkeypatch, extra):
    seen, closed = wire(monkeypatch, [(200, uploaded(**extra))])
    with pytest.raises(tweepy.TweepyException, match="x_media_response_invalid"):
        twitter.upload_png(twitter._get_upload_api(), PNG)
    assert len(seen) == len(closed) == 1
