"""Editorial format preference and pacing; no source or event inference."""
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Mapping

from src.data.awc_observed import KIND
from src.editorial.revisions import binding_matches

SPACING = timedelta(hours=24)


def is_context_comparison(candidate: Any) -> bool:
    """Identify the bare airport comparison format, never its factual validity.

    Both identities must agree. Source admission still refuses disagreements;
    neither other airport products nor a supplied importance label qualify.
    """
    return (getattr(candidate, "legacy_type", None) == KIND
            and getattr(getattr(candidate, "bundle", None), "signal_kind", None) == KIND)


def _time(value: Any) -> datetime | None:
    if (type(value) is not str or len(value) > 64
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                            r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)", value, re.ASCII) is None):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def awc_format_hold(bot_state: Mapping[str, Any], *, now: datetime) -> str | None:
    """One routine contrast per 24h after a bound, confirmed X receipt.

    Missing/unknown legacy deliveries cannot establish a publication. This is
    neither scientific eligibility nor a general guarantee over unknown sends.
    Historical receipt binding is checked without re-running its old review.
    """
    if now.utcoffset() is None:
        return "awc_format_spacing_unavailable"
    clock = now.astimezone(UTC)
    drafts, ledger = bot_state.get("drafts", []), bot_state.get("publish_ledger", {})
    if type(drafts) is not list or type(ledger) is not dict:
        return "awc_format_spacing_unavailable"
    for draft in drafts:
        if (type(draft) is not dict or draft.get("type") != KIND or draft.get("status") != "posted"
                or draft.get("publish_outcome") not in (None, "confirmed")):
            continue
        event = draft.get("event_id")
        if type(event) is not str:
            continue
        receipt = ledger.get(event)
        if (type(receipt) is not dict or receipt.get("phase") != "confirmed"
                or type(receipt.get("tweet_id")) is not str
                or re.fullmatch(r"[1-9][0-9]{0,29}", receipt["tweet_id"], re.ASCII) is None
                or receipt["tweet_id"] != draft.get("tweet_id")
                or type(receipt.get("attempt_conflicts", [])) is not list
                or receipt.get("attempt_conflicts") or not binding_matches(draft, receipt)):
            continue
        if "text" in receipt and (type(receipt["text"]) is not str or receipt["text"] != draft.get("text")):
            continue
        at, confirmed = _time(receipt.get("at")), _time(receipt.get("confirmed_at"))
        if at is not None and confirmed is not None and at <= confirmed <= clock and clock - confirmed < SPACING:
            return "awc_format_spacing"
    return None


def candidate_format_hold(bot_state: Mapping[str, Any], candidate: Any, *, now: datetime) -> str | None:
    bundle = getattr(candidate, "bundle", None)
    from src.data import awc_gust
    if bundle is not None and awc_gust.is_family(bundle):
        return awc_gust.operation_hold(bundle, bot_state, now=now)
    if is_context_comparison(candidate):
        return awc_format_hold(bot_state, now=now)
    return None
