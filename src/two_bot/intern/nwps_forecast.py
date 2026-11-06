"""Build an explicitly forecast-only brief for a qualified official river gauge."""

from collections.abc import Callable
from datetime import datetime, timezone
import re
from typing import Any

from requests import RequestException

from src.data import nwps_major_forecasts as nwps
from src.two_bot.types import StoryBundle

EVENT_PREFIX = "nwps_major_forecast_"
_FORECAST = re.compile(r"\b(?:forecast(?:s|ed)?|expect(?:s|ed)?)\b", re.I)
_ISSUER = re.compile(r"\b(?:NWS|NOAA|National Weather Service)\b", re.I)
_OBSERVED = re.compile(
    r"\b(?:already\s+(?:reached|hit)|has\s+(?:reached|hit)|reached|rose to|is at)\s+"
    r"(?:the\s+)?(?:major flood stage|\d+(?:\.\d+)?\s*(?:ft|feet)\b)", re.I,
)


def forecast_clock() -> datetime:
    return datetime.now(timezone.utc)


def build_nwps_forecast_bundle(event: nwps.MajorRiverForecast) -> StoryBundle:
    source = f"{nwps.GAUGES_URL}/{event.lid}/stageflow/forecast"
    where = f"{event.gauge_name}, {event.state_name}"
    valid = event.first_major_at.isoformat()
    facts: list[dict[str, Any]] = [
        {"label": "source_name", "value": "NOAA/NWS National Water Prediction Service"},
        {"label": "source_url", "value": source},
        {"label": "gauge", "value": event.lid},
        {"label": "location", "value": where},
        {"label": "issued_at", "value": event.issued_at.isoformat()},
        {"label": "first_forecast_major_point_at", "value": valid},
        {"label": "forecast_stage_ft", "value": event.forecast_ft, "unit": "ft"},
        {"label": "major_threshold_ft", "value": event.major_threshold_ft, "unit": "ft"},
        {"label": "evidence_grade", "value": "forecast"},
        {"label": "claim_limit", "value": (
            "This is forecast gauge stage at a single point. The first supplied point at or above "
            "major stage is not an exact crossing time. Any named impact is conditional on stage."
        )},
    ]
    if event.threshold_impact is not None:
        facts.append({"label": "conditional_impact_at_major_threshold", "value": event.threshold_impact})
    return StoryBundle(
        signal_kind="river_flood", where=where, when=valid,
        event_id=f"{EVENT_PREFIX}{event.lid}_{event.first_major_at.date().isoformat()}",
        headline_metric={"label": "forecast_stage_ft", "value": event.forecast_ft, "unit": "ft"},
        current_facts=facts,
        raw_signal_dump={
            "source_url": source,
            "nwps_index_hint": dict(event.index_hint),
            "evidence": {"evidence_type": "forecast", "source_url": source,
                         "gauge_lid": event.lid, "issued_at": event.issued_at.isoformat(),
                         "forecast_valid_at": valid, "forecast_stage_ft": event.forecast_ft,
                         "major_threshold_ft": event.major_threshold_ft},
        },
    )


def forecast_text_hold(text: Any) -> str | None:
    if not isinstance(text, str) or not _ISSUER.search(text) or not _FORECAST.search(text) or _OBSERVED.search(text):
        return "nwps_copy_requires_attributed_forecast"
    return None


def is_nwps_forecast(bundle: StoryBundle) -> bool:
    return (str(bundle.event_id).startswith(EVENT_PREFIX)
            or (isinstance(bundle.raw_signal_dump, dict) and "nwps_index_hint" in bundle.raw_signal_dump))


def current_nwps_forecast(draft: dict, *, live: bool, clock: Callable[[], datetime]) -> str | None:
    """A river forecast stays manual and bound to the exact still-current issue."""
    review = draft.get("review_context") or {}
    two_bot = review.get("two_bot") if isinstance(review, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    raw = bundle.get("raw_signal_dump") if isinstance(bundle, dict) else None
    event_id = draft.get("event_id")
    bundle_id = bundle.get("event_id") if isinstance(bundle, dict) else None
    if not (str(event_id).startswith(EVENT_PREFIX) or str(bundle_id).startswith(EVENT_PREFIX)
            or (isinstance(raw, dict) and "nwps_index_hint" in raw)):
        return None
    approval = draft.get("approval_binding")
    if (draft.get("auto_approve_at") is not None or draft.get("approval_mode") in ("auto", "policy_auto")
            or (isinstance(approval, dict) and approval.get("mode") == "auto")):
        return "nwps_manual_review_required"
    if not isinstance(bundle, dict) or not isinstance(raw, dict) or draft.get("type") != "river_flood":
        return "nwps_forecast_unverified"
    if hold := forecast_text_hold(draft.get("text")):
        return hold
    if event_id != bundle_id:
        return "nwps_forecast_unverified"
    attachment = draft.get("media_attachment")
    if isinstance(attachment, dict) and attachment.get("kind") == "gist_nwps_forecast_v1":
        series_sha = attachment.get("series_sha256")
        if not isinstance(series_sha, str) or re.fullmatch(r"[a-f0-9]{64}", series_sha) is None:
            return "nwps_forecast_unverified"
        return forecast_source_hold(bundle, live=live, clock=clock, series_sha=series_sha)
    return forecast_source_hold(bundle, live=live, clock=clock)


def forecast_source_hold(bundle: dict, *, live: bool, clock: Callable[[], datetime], series_sha: str | None = None) -> str | None:
    from src.editorial.revisions import fingerprint

    try:
        raw = bundle["raw_signal_dump"]
        hint = raw["nwps_index_hint"]
        evidence = raw["evidence"]
        issued = datetime.fromisoformat(evidence["issued_at"])
        valid = datetime.fromisoformat(evidence["forecast_valid_at"])
        now = clock()
        lid = hint["gaugelid"]
        expected_id = f"{EVENT_PREFIX}{lid}_{valid.date().isoformat()}"
        if (not isinstance(lid, str) or re.fullmatch(r"[A-Z0-9]{5}", lid) is None
                or bundle["event_id"] != expected_id or evidence["gauge_lid"] != lid
                or bundle["signal_kind"] != "river_flood" or bundle["when"] != evidence["forecast_valid_at"]):
            return "nwps_forecast_unverified"
        if not now - nwps.MAX_SOURCE_AGE <= issued <= now < valid <= now + nwps.HORIZON:
            return "nwps_forecast_expired"
        if live:
            metadata, series = nwps.read_gauge_forecast(hint)
            expected = build_nwps_forecast_bundle(nwps.verify_major_forecast(hint, metadata, series, clock())).to_dict()
            if fingerprint({key: bundle[key] for key in expected}) != fingerprint(expected):
                return "nwps_forecast_changed"
            if series_sha is not None and fingerprint(series["data"]) != series_sha:
                return "nwps_forecast_series_changed"
        return None
    except (RequestException, KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return "nwps_forecast_unverified"
