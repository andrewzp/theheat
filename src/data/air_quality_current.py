"""Current-source guard and opt-in automatic TEXT eligibility for one PM2.5/dust city window.

Default off. Nothing here fetches unless the story's own flag is exactly "1":
``THEHEAT_PM25_FORECAST_AUTO_TEXT`` (air_quality_hazard) or
``THEHEAT_DUST_FORECAST_AUTO_TEXT`` (dust_event). With a flag on, the existing
Open-Meteo client re-reads exactly the retained city and local day once at the
paid-generation, admission and pre-safety automatic-send boundaries: one GET,
one attempt, a 10-second deadline and a 64 KiB body bound. A hold never tries
another city, day, provider or retry, and a changed source invalidates the
draft instead of updating its evidence. Manual sends keep their existing gates.

A complete historical day is not current eligibility; neither is a passed
check. Automatic eligibility also needs text only, a forecast qualifier in the
copy, the first publication or a tier rise for its city/day episode and no
unknown earlier delivery in that episode.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
import re
from typing import Any

from src.data import air_quality_contract as contract
from src.data.source_status import SourceFetchError

KIND_FLAGS = {"air_quality_hazard": "THEHEAT_PM25_FORECAST_AUTO_TEXT", "dust_event": "THEHEAT_DUST_FORECAST_AUTO_TEXT"}
KINDS = frozenset(KIND_FLAGS)
REQUEST_TIMEOUT_S = 10.0
MAX_BODY_BYTES = 65_536
MAX_SOURCE_AGE = timedelta(hours=6)
FUTURE_TOLERANCE = timedelta(minutes=5)
_FORECAST = re.compile(r"\b(?:forecasts?|forecasted|model(?:led|ed)?|projected|expected)\b", re.I)
_EVENT = re.compile(r"^(?P<episode>(?:pm25|dust)_.+_\d{4}-\d{2}-\d{2})_tier(?P<tier>[1-3])$")
HOLD_MESSAGES = {
    "air_quality_auto_text_disabled": "Automatic text for this air-quality forecast is switched off.",
    "air_quality_auto_text_only": "Air-quality forecasts publish automatically as text only.",
    "air_quality_auto_missing_forecast_qualifier": "Automatic air-quality copy must say it is a forecast.",
    "air_quality_contract_invalid": "The retained air-quality forecast window is not intact.",
    "air_quality_window_ended": "The forecast's local day has ended.",
    "air_quality_source_stale": "The retained forecast is too old for automatic publication.",
    "air_quality_source_future": "The retained forecast has a retrieval time in the future.",
    "air_quality_source_unavailable": "The current forecast could not be re-read.",
    "air_quality_source_oversize": "The current forecast response exceeded its size bound.",
    "air_quality_source_shape": "The current forecast no longer matches the retained day, zone or grid.",
    "air_quality_source_changed": "The forecast changed after the copy was checked.",
    "air_quality_prior_delivery_unknown": "An earlier post for this city and day has an unknown outcome.",
    "air_quality_episode_already_published": "This city and day already has a post at this tier or higher.",
}


class CurrentSourceHold(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def auto_text_enabled(kind: Any) -> bool:
    return isinstance(kind, str) and kind in KIND_FLAGS and os.environ.get(KIND_FLAGS[kind]) == "1"


def _story(bundle: Any):
    """The validated retained story, from a live StoryBundle or a saved bundle dict."""
    from src.data.air_quality_evidence import validate_bundle
    from src.two_bot.types import StoryBundle

    if isinstance(bundle, dict):
        bundle = StoryBundle(**bundle)
    validate_bundle(bundle)
    return bundle


def _instant(value: Any) -> datetime:
    return contract._utc(value).astimezone(UTC)


def static_hold(bundle: Any, now: datetime, *, automatic: bool) -> str | None:
    """Rules that need no fetch: intact evidence, unexpired window and (automatic) source age."""
    try:
        packet = _story(bundle).raw_signal_dump["forecast_window"]
        end, retrieved = _instant(packet["valid_end"]), _instant(packet["retrieved_at"])
    except (SourceFetchError, KeyError, TypeError, ValueError, AttributeError):
        return "air_quality_contract_invalid"
    now = now.astimezone(UTC)
    if now >= end:
        return "air_quality_window_ended"
    if automatic and retrieved > now + FUTURE_TOLERANCE:
        return "air_quality_source_future"
    if automatic and now - retrieved > MAX_SOURCE_AGE:
        return "air_quality_source_stale"
    return None


def _compared_keys(story: Any) -> tuple[str, ...]:
    if story.signal_kind == "air_quality_hazard":
        return ("pm2_5",)
    # The dust story's PM10 anchor is part of its evidence only when it is supplied.
    return ("dust", "pm10") if story.raw_signal_dump.get("who_pm10_multiple") is not None else ("dust",)


def fetch_current(packet: dict, *, transport=None) -> dict:
    """One bounded GET for the retained location and local day; returns the re-read series."""
    from src.data._http import fetch_with_retry

    location = packet["requested_location"]
    body = bytearray()
    oversize = False
    try:
        response = (transport or fetch_with_retry)(
            contract.SOURCE_URL, timeout=REQUEST_TIMEOUT_S, attempts=1, stream=True,
            params={"latitude": str(location["lat"]), "longitude": str(location["lon"]),
                    "hourly": ",".join(contract.VARIABLES), "timezone": "auto", "domains": "auto",
                    "start_date": packet["date"], "end_date": packet["date"]},
        )
        try:
            for chunk in response.iter_content(chunk_size=16_384):
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    oversize = True  # Stop reading; never buffer an unbounded body.
                    break
        finally:
            response.close()
    except Exception as exc:  # noqa: BLE001 - any transport outcome is one unavailable read, never a retry.
        raise CurrentSourceHold("air_quality_source_unavailable") from exc
    if oversize:
        raise CurrentSourceHold("air_quality_source_oversize")
    try:
        return contract.current_series(json.loads(bytes(body)), packet)
    except (SourceFetchError, ValueError, TypeError):
        raise CurrentSourceHold("air_quality_source_shape") from None


def live_hold(bundle: Any, now: datetime, *, transport=None) -> str | None:
    """Static rules, then one re-read compared with the retained samples (never updated in place)."""
    hold = static_hold(bundle, now, automatic=True)
    if hold is not None:
        return hold
    story = _story(bundle)
    packet = story.raw_signal_dump["forecast_window"]
    try:
        current = fetch_current(packet, transport=transport)
    except CurrentSourceHold as exc:
        return exc.code
    for key in _compared_keys(story):
        if current[key] != packet["series"][key]:
            return "air_quality_source_changed"
    return None


def generation_hold(bundle: Any, now: datetime | None = None, *, transport=None) -> str | None:
    """Paid-generation boundary: only for an enabled kind; otherwise no fetch at all."""
    if not auto_text_enabled(getattr(bundle, "signal_kind", None)):
        return None
    return live_hold(bundle, now or datetime.now(UTC), transport=transport)


def admission_hold(kind: str, bundle: Any, now: datetime, *, transport=None) -> str | None:
    if not auto_text_enabled(kind):
        return None
    return live_hold(bundle, now, transport=transport)


def _episode(event_id: Any) -> tuple[str, int] | None:
    match = _EVENT.match(event_id) if isinstance(event_id, str) else None
    return (match["episode"], int(match["tier"])) if match else None


def episode_hold(draft: dict, state: Any) -> str | None:
    """Existing city/day event and ledger identities: first post or a rise; unknown blocks."""
    current = _episode(draft.get("event_id"))
    if current is None:
        return "air_quality_contract_invalid"
    episode, tier = current
    ledger = state.get("publish_ledger") if isinstance(state, dict) else None
    ledger = ledger if isinstance(ledger, dict) else {}
    posted = set(state.get("posted_events") or []) if isinstance(state, dict) else set()
    candidates = set(ledger) | posted | {d.get("event_id") for d in (state.get("drafts") or []) if isinstance(d, dict)}
    for event_id in candidates:
        other = _episode(event_id)
        if other is None or other[0] != episode or event_id == draft.get("event_id"):
            continue
        row = ledger.get(event_id)
        if isinstance(row, dict) and not row.get("tweet_id") and row.get("phase") != "not_sent":
            return "air_quality_prior_delivery_unknown"
        published = event_id in posted or (isinstance(row, dict) and row.get("tweet_id")) or any(
            isinstance(d, dict) and d.get("event_id") == event_id and d.get("status") == "posted"
            for d in state.get("drafts") or [])
        if published and other[1] >= tier:
            return "air_quality_episode_already_published"
    return None


def episode_unresolved(state: Any, event_id: str) -> bool:
    """Source-runner fence: an unknown delivery in this city/day episode stops a new candidate."""
    return episode_hold({"event_id": event_id}, state) == "air_quality_prior_delivery_unknown"


def auto_text_hold(draft: dict, state: Any, now: datetime, *, live: bool, transport=None) -> str | None:
    """Every automatic-text rule for one saved air-quality draft; None when eligible."""
    kind = draft.get("type")
    if not auto_text_enabled(kind):
        return "air_quality_auto_text_disabled"
    if "media_attachment" in draft:
        return "air_quality_auto_text_only"
    if not isinstance(draft.get("text"), str) or not _FORECAST.search(draft["text"]):
        return "air_quality_auto_missing_forecast_qualifier"
    hold = episode_hold(draft, state)
    if hold is not None:
        return hold
    review = draft.get("review_context")
    two_bot = review.get("two_bot") if isinstance(review, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    if live:
        return live_hold(bundle, now, transport=transport)
    return static_hold(bundle, now, automatic=True)


__all__ = ["HOLD_MESSAGES", "KINDS", "KIND_FLAGS", "MAX_BODY_BYTES", "MAX_SOURCE_AGE", "REQUEST_TIMEOUT_S",
           "CurrentSourceHold", "admission_hold", "auto_text_enabled", "auto_text_hold", "episode_hold",
           "episode_unresolved", "fetch_current", "generation_hold", "live_hold", "static_hold"]
