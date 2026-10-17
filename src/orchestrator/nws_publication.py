"""Current-warning checks at the NWS publication boundary, without source adoption."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from src.data._http import fetch_with_retry
from src.data.nws_alerts import NWS_URL, TRACKED_EVENTS, _typhoon_warning
from src.media.published_radar import encoded, interval, rare_tornado, source_envelope

MAX_FEED_BYTES = 32 * 1024 * 1024
MAX_ISSUANCE_AGE = timedelta(hours=6)


class NwsPublicationHold(ValueError):
    """A fixed diagnostic code, never raw source or transport exception text."""


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise NwsPublicationHold(code)


def _utc(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(at.utcoffset() is not None, "nws_source_time_invalid")
    return at.astimezone(timezone.utc)


def _bundle(draft: dict) -> dict | None:
    context = draft.get("review_context")
    two_bot = context.get("two_bot") if isinstance(context, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    raw = bundle.get("raw_signal_dump") if isinstance(bundle, dict) else None
    envelope = raw.get("source_evidence") if isinstance(raw, dict) else None
    nws = (draft.get("type") == "severe_weather"
           or str(draft.get("event_id", "")).startswith("nws_")
           or (isinstance(bundle, dict) and (bundle.get("signal_kind") == "severe_weather"
               or str(bundle.get("event_id", "")).startswith("nws_")))
           or (isinstance(envelope, dict) and envelope.get("source_url") == NWS_URL))
    if not nws:
        return None
    _require(isinstance(bundle, dict), "nws_source_missing")
    return bundle


def _retained(draft: dict, now: datetime) -> dict | None:
    bundle = _bundle(draft)
    if bundle is None:
        return None
    raw = bundle["raw_signal_dump"]
    envelope = raw["source_evidence"]
    _require(encoded(envelope) == encoded(source_envelope(envelope["feature"], envelope["captured_at"])),
             "nws_source_envelope_changed")
    identity = "nws_" + envelope["source_alert_id"]
    _require(bundle["signal_kind"] == "severe_weather" and draft.get("event_id") == identity
             and bundle["event_id"] == identity and raw["event_id"] == identity
             and envelope["source_url"] == NWS_URL, "nws_source_identity_changed")
    _require(raw["provenance"] == {key: envelope[key] for key in (
        "source_url", "source_alert_id", "feature_sha256")}, "nws_source_provenance_changed")
    props = envelope["feature"]["properties"]
    _require(props.get("status") == "Actual" and props.get("category") == "Met"
             and (_typhoon_warning(props) or rare_tornado(props) or (
                 props.get("event") in TRACKED_EVENTS and props.get("event") != "Typhoon Warning"
                 and props.get("messageType") == "Alert")), "nws_source_product_unsupported")
    sent = _utc(envelope["times"]["sent"]["utc"])
    effective = _utc(envelope["times"]["effective"]["utc"])
    _, end = interval(envelope["times"])
    _require(timedelta(0) <= now - sent <= MAX_ISSUANCE_AGE and effective <= now < _utc(end)
             and timedelta(0) <= now - _utc(envelope["captured_at"]) <= MAX_ISSUANCE_AGE,
             "nws_source_expired_or_future")
    return envelope


def _object(pairs: list[tuple[str, Any]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        _require(key not in value, "nws_source_duplicate_json_key")
        value[key] = item
    return value


def _nonfinite(_value: str) -> None:
    raise NwsPublicationHold("nws_source_nonfinite_json")


def _active_feed() -> dict:
    response = fetch_with_retry(
        NWS_URL, params={"status": "actual", "message_type": "alert,update"},
        headers={"User-Agent": "(theheat-bot, contact@theheat.app)",
                 "Accept": "application/geo+json"},
        timeout=30, attempts=3, backoff_base=1.0, stream=True, allow_redirects=False,
    )
    try:
        _require(response.status_code == 200, "nws_source_http_status")
        chunks = []
        length = 0
        for chunk in response.iter_content(65536):
            length += len(chunk)
            _require(length <= MAX_FEED_BYTES, "nws_source_feed_too_large")
            chunks.append(chunk)
        feed = json.loads(b"".join(chunks), object_pairs_hook=_object, parse_constant=_nonfinite)
        _require(isinstance(feed, dict) and isinstance(feed.get("features"), list),
                 "nws_source_feed_invalid")
        return feed
    finally:
        response.close()


def _unchanged(envelope: dict, feed: dict) -> None:
    identity = envelope["source_alert_id"]
    products = []
    matches = []
    for feature in feed["features"]:
        _require(isinstance(feature, dict) and isinstance(feature.get("properties"), dict),
                 "nws_source_feed_invalid")
        props = feature["properties"]
        if props.get("id") == identity:
            matches.append(feature)
        references = props.get("references")
        if props.get("messageType") in ("Update", "Cancel") and isinstance(references, list):
            _require(not any(isinstance(row, dict) and row.get("identifier") == identity
                             for row in references), "nws_source_superseded")
        if _typhoon_warning(props):
            products.append(props)
    _require(len(matches) == 1 and encoded(matches[0]) == encoded(envelope["feature"]),
             "nws_source_changed_or_missing")
    props = envelope["feature"]["properties"]
    if props["event"] == "Typhoon Warning":
        _require(sum(row["areaDesc"] == props["areaDesc"] for row in products) == 1,
                 "nws_source_area_conflict")


def current_nws_source(draft: dict, *, live: bool) -> str | None:
    """Return a hold code or None; never mutate evidence or confer approval.

    Non-NWS families are untouched. The sender calls live before paid safety and
    again before transport. Static checks also run before creating an intent.
    """
    try:
        envelope = _retained(draft, _clock())
        if envelope is not None and live:
            _unchanged(envelope, _active_feed())
            _retained(draft, _clock())  # Expiry can cross while the free lookup runs.
        return None
    except NwsPublicationHold as exc:
        return str(exc)
    except Exception:  # A source failure is a hold, never a fallback pass or retry here.
        return "nws_source_unverified"
