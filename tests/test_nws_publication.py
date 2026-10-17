"""Invented source and platform fixtures at the actual warning sender boundary."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
import responses

from src.data.nws_alerts import SevereWeatherAlert
from src.commands.schema import utc_text
from src.editorial.revisions import authorize_draft, record_human_review
from src.media.published_radar import source_envelope
from src.orchestrator import nws_publication as nws, posting
from src.state import DEFAULT_STATE
from src.two_bot.intern import build_severe_weather_bundle
from tests.revision_helpers import bind_reviewed_draft

pytestmark = pytest.mark.usefixtures("automatic_publication_release")
NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def feature():
    return {"type": "Feature", "geometry": None, "properties": {
        "id": "invented-warning", "event": "Typhoon Warning", "category": "Met",
        "status": "Actual", "messageType": "Alert", "references": [],
        "areaDesc": "Invented island", "severity": "Extreme",
        "headline": "Invented cyclone warning", "description": "Typhoon conditions are expected.",
        "sent": (NOW - timedelta(minutes=20)).isoformat(),
        "effective": (NOW - timedelta(minutes=20)).isoformat(),
        "onset": (NOW - timedelta(minutes=20)).isoformat(),
        "expires": (NOW + timedelta(hours=2)).isoformat(), "ends": None, "parameters": {},
    }}


def draft(source=None, mode="manual"):
    source = source or feature()
    props = source["properties"]
    alert = SevereWeatherAlert(props["event"], props["areaDesc"], props["severity"],
                               props["headline"], "nws_" + props["id"],
                               description=props["description"],
                               source_evidence=source_envelope(source, utc_text(NOW)))
    bundle = build_severe_weather_bundle(alert).to_dict()
    value = {"id": "invented-draft", "event_id": bundle["event_id"], "type": "severe_weather",
             "text": "Invented island is under a typhoon warning, the NWS says.",
             "created_at": NOW.isoformat(), "status": "pending",
             "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
             "review_context": {"two_bot": {"bundle": bundle}}}
    if mode == "auto":
        value["auto_approve_at"] = (NOW - timedelta(minutes=1)).isoformat()
        return bind_reviewed_draft(value, "auto")  # Explicit offline model fixture only.
    record_human_review(value)
    authorize_draft(value, "manual", "invented-intent")
    value["status"] = "approved"
    return value


def state(value):
    result = deepcopy(DEFAULT_STATE)
    result["drafts"] = [value]
    return result


@pytest.fixture
def boundary(monkeypatch):
    importlib.reload(posting)
    clock = {"now": NOW}
    monkeypatch.setattr(nws, "_clock", lambda: clock["now"])
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    storage.write_state.return_value = True
    send = MagicMock(return_value={"id": "invented-post"})
    safety = MagicMock(return_value=(True, None))
    lookup = MagicMock(return_value={"features": [feature()]})
    monkeypatch.setattr(nws, "_active_feed", lookup)
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "post_to_bluesky", MagicMock())
    monkeypatch.setattr(posting, "run_safety_pipeline", safety)
    monkeypatch.setattr(posting, "_record_published_two_bot_memory", MagicMock())
    monkeypatch.setattr(posting, "_utc_now", lambda: clock["now"])
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    return clock, storage, send, safety, lookup


def manual(monkeypatch, value, saved):
    monkeypatch.setenv("DRAFT_ID", value["id"])
    monkeypatch.setenv("TWEET_TEXT", value["text"])
    monkeypatch.setenv("PUBLISH_INTENT_ID", value.get("publish_intent_id", ""))
    return posting.run_manual_tweet(saved)


@pytest.mark.parametrize("path", ["manual", "due", "direct"])
def test_expired_warning_blocks_before_cost_intent_or_platform(boundary, monkeypatch, path):
    clock, storage, send, safety, lookup = boundary
    value = draft(mode="auto" if path == "due" else "manual")
    saved = state(value)
    clock["now"] += timedelta(hours=7)
    if path == "manual":
        manual(monkeypatch, value, saved)
    elif path == "due":
        posting.process_due_drafts(saved)
    else:
        assert posting.post_approved(value, saved) == "failed"
    safety.assert_not_called()
    lookup.assert_not_called()
    send.assert_not_called()
    storage.write_state.assert_not_called()
    assert saved["publish_ledger"] == {}
    assert value["status"] == "pending" and not value.get("approval_binding")
    assert "nws_source_expired_or_future" in value["post_error"]


@pytest.mark.parametrize("path,lookups", [("manual", 2), ("due", 2), ("direct", 1)])
def test_exact_current_warning_rechecked_without_adopting_source(boundary, monkeypatch, path, lookups):
    _, _, send, safety, lookup = boundary
    value = draft(mode="auto" if path == "due" else "manual")
    evidence = deepcopy(value["review_context"])
    saved = state(value)
    if path == "manual":
        manual(monkeypatch, value, saved)
    elif path == "due":
        posting.process_due_drafts(saved)
    else:
        assert posting.post_approved(value, saved) == "posted"
    assert lookup.call_count == lookups
    assert safety.call_count == (0 if path == "direct" else 1)
    send.assert_called_once_with(value["text"], media_png=None, alt_text=None)
    assert value["review_context"] == evidence


@pytest.mark.parametrize("case", ["pending", "missing_review", "edited", "unknown"])
def test_unapproved_stale_or_unknown_request_makes_no_free_or_paid_calls(boundary, monkeypatch, case):
    _, storage, send, safety, lookup = boundary
    value = draft()
    if case == "pending":
        value["status"] = "pending"
    elif case == "missing_review":
        value.pop("review_binding")
    elif case == "edited":
        value["text"] += " Extra text."
    else:
        value["publish_outcome"] = "unknown"
    manual(monkeypatch, value, state(value))
    lookup.assert_not_called()
    safety.assert_not_called()
    storage.write_state.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize("case", ["changed", "removed", "duplicate", "superseded", "cancelled", "area_conflict", "invalid"])
def test_changed_or_uncertain_live_source_never_reaches_paid_check(boundary, monkeypatch, case):
    _, storage, send, safety, lookup = boundary
    value = draft()
    source = feature()
    feed = {"features": [source]}
    if case == "changed":
        source["properties"]["description"] = "A materially different forecast."
    elif case == "removed":
        feed["features"] = []
    elif case == "duplicate":
        feed["features"].append(deepcopy(source))
    elif case in ("superseded", "cancelled"):
        successor = deepcopy(source)
        successor["properties"].update(id="invented-successor", messageType="Update" if case == "superseded" else "Cancel",
                                      references=[{"identifier": "invented-warning"}])
        feed["features"].append(successor)
    elif case == "area_conflict":
        other = deepcopy(source)
        other["properties"]["id"] = "invented-other"
        feed["features"].append(other)
    else:
        feed["features"].append({"properties": None})
    lookup.return_value = feed
    saved = state(value)
    manual(monkeypatch, value, saved)
    safety.assert_not_called()
    send.assert_not_called()
    storage.write_state.assert_not_called()
    assert not saved["publish_ledger"] and not value.get("approval_binding")


def test_unavailable_source_is_private_hold_before_paid_check(boundary, monkeypatch):
    _, _, send, safety, lookup = boundary
    lookup.side_effect = RuntimeError("invented-secret-must-not-leak")
    value = draft()
    manual(monkeypatch, value, state(value))
    safety.assert_not_called()
    send.assert_not_called()
    assert value["post_error"].endswith("nws_source_unverified")
    assert "secret" not in value["post_error"]


@pytest.mark.parametrize("changed", [1.0, True], ids=["float", "boolean"])
def test_live_feature_numeric_type_change_cannot_reuse_retained_source(boundary, changed):
    source = feature()
    source["properties"]["invented_numeric_metadata"] = 1
    value = draft(source)
    current = deepcopy(source)
    current["properties"]["invented_numeric_metadata"] = changed
    boundary[-1].return_value = {"features": [current]}
    assert nws.current_nws_source(value, live=True) == "nws_source_changed_or_missing"


def test_retained_envelope_boolean_schema_is_not_integer_schema(boundary):
    value = draft()
    value["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["source_evidence"]["schema_version"] = True
    assert nws.current_nws_source(value, live=True) == "nws_source_envelope_changed"
    boundary[-1].assert_not_called()


@pytest.mark.parametrize("work", ["paid", "media", "lookup"])
def test_expiry_during_work_stops_platform_and_preserves_delivery_state(boundary, monkeypatch, work):
    clock, storage, send, safety, lookup = boundary
    value = draft()
    saved = state(value)
    def expire():
        clock["now"] += timedelta(hours=3)
    if work == "paid":
        def checked(_text):
            expire()
            return True, None
        safety.side_effect = checked
    elif work == "media":
        def media(_draft):
            expire()
            return None, None
        monkeypatch.setattr(posting, "_hot10_media_for_draft", media)
    else:
        def fetched():
            expire()
            return {"features": [feature()]}
        lookup.side_effect = fetched
    manual(monkeypatch, value, saved)
    send.assert_not_called()
    if work == "media":
        assert storage.write_state.call_count == 1
        assert saved["publish_ledger"][value["event_id"]]["phase"] == "not_sent"
        assert value["publish_outcome"] == "not_sent"
    else:
        storage.write_state.assert_not_called()
        assert not saved["publish_ledger"]
    assert safety.call_count == (0 if work == "lookup" else 1)
    assert value["status"] == "pending" and not value.get("approval_binding")


def test_source_change_after_intent_is_not_sent_never_unknown(boundary, monkeypatch):
    _, storage, send, safety, lookup = boundary
    value = draft()
    saved = state(value)
    changed = feature()
    changed["properties"]["description"] = "Changed source after paid check."
    lookup.side_effect = [{"features": [feature()]}, {"features": [changed]}]
    manual(monkeypatch, value, saved)
    assert storage.write_state.call_count == 1 and safety.call_count == 1
    send.assert_not_called()
    assert value["publish_outcome"] == "not_sent"
    assert saved["publish_ledger"][value["event_id"]]["phase"] == "not_sent"
    assert not value.get("approval_binding") and not value.get("publish_intent_id")


def test_policy_change_during_free_lookup_cannot_buy_final_safety(boundary, monkeypatch):
    from src.voice import safety as safety_module
    _, storage, send, safety, lookup = boundary
    value = draft()
    def changed():
        monkeypatch.setattr(safety_module, "GEMINI_SAFETY_MODEL", "invented-different-policy")
        return {"features": [feature()]}
    lookup.side_effect = changed
    manual(monkeypatch, value, state(value))
    safety.assert_not_called()
    storage.write_state.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize("field", ["expires", "ends"])
def test_validity_end_is_exclusive_even_when_issuance_is_recent(boundary, field):
    source = feature()
    source["properties"][field] = NOW.isoformat()
    assert nws.current_nws_source(draft(source), live=True) == "nws_source_expired_or_future"
    boundary[-1].assert_not_called()


@pytest.mark.parametrize("case", ["missing", "hash", "provenance", "identity", "future", "effective", "nonactual"])
def test_malformed_or_unbound_retained_source_held_without_lookup(boundary, case):
    value = draft()
    bundle = value["review_context"]["two_bot"]["bundle"]
    raw = bundle["raw_signal_dump"]
    if case == "missing":
        raw.pop("source_evidence")
    elif case == "hash":
        raw["source_evidence"]["feature_sha256"] = "wrong"
    elif case == "provenance":
        raw["provenance"]["feature_sha256"] = "wrong"
    elif case == "identity":
        bundle["event_id"] = "nws_other"
    else:
        source = feature()
        source["properties"][{"future": "sent", "effective": "effective", "nonactual": "status"}[case]] = (
            "Test" if case == "nonactual" else (NOW + timedelta(minutes=1)).isoformat())
        envelope = source_envelope(source, utc_text(NOW))
        raw["source_evidence"] = envelope
        raw["provenance"] = {key: envelope[key] for key in ("source_url", "source_alert_id", "feature_sha256")}
    assert nws.current_nws_source(value, live=True)
    boundary[-1].assert_not_called()


@pytest.mark.parametrize("age,allowed", [(timedelta(hours=6), True), (timedelta(hours=6, microseconds=1), False)])
def test_issuance_six_hour_boundary_is_exact(boundary, age, allowed):
    source = feature()
    source["properties"]["sent"] = (NOW - age).isoformat()
    value = draft(source)
    assert (nws.current_nws_source(value, live=False) is None) is allowed


def test_future_forecast_onset_is_not_an_observed_intensity_or_expired_warning(boundary):
    source = feature()
    source["properties"]["onset"] = (NOW + timedelta(hours=1)).isoformat()
    assert nws.current_nws_source(draft(source), live=False) is None


def test_other_source_families_are_unchanged_and_make_no_nws_request(boundary):
    assert nws.current_nws_source({"type": "monthly_high", "event_id": "temperature-invented"}, live=True) is None
    boundary[-1].assert_not_called()


@pytest.mark.parametrize("payload", [b'{"features":[],"features":[]}', b'{"features":NaN}', b'{"features":{}}', b'not-json'])
def test_streamed_feed_invalid_json_or_shape_is_held_and_response_closed(monkeypatch, payload):
    response = SimpleNamespace(status_code=200, iter_content=lambda _size: iter([payload]), close=MagicMock())
    fetch = MagicMock(return_value=response)
    monkeypatch.setattr(nws, "fetch_with_retry", fetch)
    monkeypatch.setattr(nws, "_clock", lambda: NOW)
    assert nws.current_nws_source(draft(), live=True)
    response.close.assert_called_once()
    kwargs = fetch.call_args.kwargs
    assert kwargs["attempts"] == 3 and kwargs["timeout"] == 30
    assert kwargs["stream"] is True and kwargs["allow_redirects"] is False
    assert fetch.call_args.args == ("https://api.weather.gov/alerts/active",)


def test_stream_decoded_byte_bound_closes_response(monkeypatch):
    monkeypatch.setattr(nws, "MAX_FEED_BYTES", 8)
    response = SimpleNamespace(status_code=200, iter_content=lambda _size: iter([b"12345", b"6789"]), close=MagicMock())
    monkeypatch.setattr(nws, "fetch_with_retry", MagicMock(return_value=response))
    monkeypatch.setattr(nws, "_clock", lambda: NOW)
    assert nws.current_nws_source(draft(), live=True) == "nws_source_feed_too_large"
    response.close.assert_called_once()


@responses.activate
def test_actual_http_path_does_not_follow_redirect(monkeypatch):
    monkeypatch.setattr(nws, "_clock", lambda: NOW)
    responses.add(responses.GET, nws.NWS_URL, status=302, headers={"Location": "https://invalid.example/"})
    assert nws.current_nws_source(draft(), live=True) == "nws_source_http_status"
    assert len(responses.calls) == 1


@responses.activate
def test_actual_http_failures_have_three_attempts_no_paid_fallback(monkeypatch):
    from src.data import _http
    monkeypatch.setattr(nws, "_clock", lambda: NOW)
    monkeypatch.setattr(_http, "_sleep_before_retry", lambda *_args: None)
    responses.add(responses.GET, nws.NWS_URL, body=requests.ConnectionError("private-transport-detail"))
    assert nws.current_nws_source(draft(), live=True) == "nws_source_unverified"
    assert len(responses.calls) == 3


@responses.activate
def test_actual_streamed_http_path_uses_fixed_source_and_does_not_cache(monkeypatch):
    monkeypatch.setattr(nws, "_clock", lambda: NOW)
    responses.add(responses.GET, nws.NWS_URL, body=json.dumps({"features": [feature()]}), content_type="application/geo+json")
    value = draft()
    assert nws.current_nws_source(value, live=True) is None
    assert nws.current_nws_source(value, live=True) is None
    assert len(responses.calls) == 2
    assert all("status=actual" in row.request.url and "message_type=alert%2Cupdate" in row.request.url for row in responses.calls)
