"""Source runner for NWS severe weather alerts."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *

from datetime import UTC as _UTC
from datetime import datetime as _datetime

# Imported directly (not via the star-imported module binding, which tests
# may replace): a constant must compare equal regardless of patching.
from src.data.nws_alerts import CENSUS_INCOMPLETE_KEY

# Designated-tier ids minted by src.data.nws_alerts for promoted
# emergencies/PDS warnings (VTEC-keyed, or the day-scoped fallback).
_LIFECYCLE_ID_PREFIXES = ("nws_vtec:", "nws_emergency:")


def _reject_draft(draft: dict, reason: str) -> None:
    # Mirrors the pending-TTL sweep's rejection mutation. updated_at moves
    # too: _merge_drafts resolves same-id conflicts by recency, and a
    # rejection that doesn't advance it would lose the merge to a stale
    # pending copy coming back from the dashboard.
    draft["status"] = "rejected"
    draft["rejected_reason"] = reason
    draft["rejected_at"] = _datetime.now(_UTC).isoformat().replace("+00:00", "Z")
    draft["updated_at"] = draft["rejected_at"]


def _reconcile_pending_lifecycle_drafts(
    bot_state: BotState, lifecycle_tiers: dict[str, int]
) -> int:
    """Reject pending designated-tier drafts whose warning is no longer at
    THAT tier. Downgrades, cancellations and expirations (absent from the
    map) mean a present-tense emergency/PDS draft is stale; an upgrade
    means the stale PDS would hold the pending-type-cap slot its own
    replacement needs. Both rejection reasons are redraftable
    (draft_save._REDRAFTABLE_REJECTIONS): the current-tier alert flows
    through the normal pipeline the same cycle, and a tier that recurs
    (PDS → emergency → PDS) drafts honestly again."""
    rejected = 0
    for draft in bot_state.get("drafts", []) or []:
        # "approved" is still preventable: the posting worker requires
        # status == "approved", so rejecting invalidates the publish
        # intent before it fires. Only "posted" is past the point of
        # automatic retraction.
        if not isinstance(draft, dict) or draft.get("status") not in ("pending", "approved"):
            continue
        event_id = str(draft.get("event_id") or "")
        if not event_id.startswith(_LIFECYCLE_ID_PREFIXES):
            continue
        draft_tier = 1 if event_id.endswith(":pds") else 2
        base_id = event_id.removesuffix(":pds")
        current_tier = lifecycle_tiers.get(base_id, 0)
        if current_tier == draft_tier:
            continue
        reason = (
            "superseded_by_emergency_upgrade"
            if current_tier > draft_tier
            else "nws_lifecycle_downgraded"
        )
        _reject_draft(draft, reason)
        rejected += 1
        print(f"[alerts] pending {event_id} rejected: {reason}")
    return rejected


def _pds_downgrade_of_known_emergency(
    bot_state: BotState, alert: "nws_alerts.SevereWeatherAlert"
) -> bool:
    """A PDS-tier alert whose warning already surfaced at the emergency
    tier ON THE PUBLIC RECORD (posted) is a downgrade, not news. A merely
    pending emergency does not block the honest lower tier — reconciliation
    retires it on the downgrade cycle. The emergency id is the PDS id
    without its ``:pds`` suffix."""
    if not alert.event_id.endswith(":pds"):
        return False
    base_id = alert.event_id.removesuffix(":pds")
    if state.is_duplicate(bot_state, base_id):
        return True
    return any(
        d.get("event_id") == base_id and d.get("status") == "posted"
        for d in bot_state.get("drafts", [])
        if isinstance(d, dict)
    )


def run_nws_alerts(bot_state: BotState, current_run: dict | None) -> None:
    # 4. NWS severe weather alerts (US)
    print("[alerts] Checking NWS severe weather...")
    nws_start = time.perf_counter()
    try:
        lifecycle_tiers: dict[str, int] = {}
        alerts = _fetch_strict(nws_alerts.fetch_alerts, lifecycle_out=lifecycle_tiers)
        if lifecycle_tiers.pop(CENSUS_INCOMPLETE_KEY, 0):
            # Truncated (paginated) payload — not a complete lifecycle
            # census; retiring pending drafts against it could reject an
            # emergency still active on a later page.
            print("[alerts] paginated payload; skipping lifecycle reconciliation")
        else:
            _reconcile_pending_lifecycle_drafts(bot_state, lifecycle_tiers)
        source_promoted = 0
        for alert in alerts:
            if state.is_duplicate(bot_state, alert.event_id):
                continue
            if _pds_downgrade_of_known_emergency(bot_state, alert):
                continue
            score = score_severe_weather(
                alert.event_type,
                alert.severity,
                emergency_designation=alert.emergency_designation,
            )
            if not _should_draft(score, alert.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NWS Alerts",
                source_key="nws_alerts",
                headline=f"{alert.emergency_designation or alert.event_type} for {alert.area}",
                current_run=current_run,
                facts=[
                    _fact("Event", alert.event_type),
                    _fact("Emergency designation", alert.emergency_designation or "—"),
                    _fact("Area", alert.area),
                    _fact("Severity", alert.severity),
                    _fact("Max wind gust", alert.max_wind_gust or "—"),
                    _fact("Max hail", alert.max_hail_size or "—"),
                    _fact("Tornado detection", alert.tornado_detection or "—"),
                ],
            )
            # Severe weather: ported to two-bot writer 2026-05-03.
            # Event-scoped repetition now flows through the two-bot
            # memory slice as ``recent_tweets_same_event``.
            from src.two_bot.intern import build_severe_weather_bundle
            sw_bundle = build_severe_weather_bundle(alert)
            _enqueue_story_candidate(
                bot_state,
                bundle=sw_bundle,
                score=score,
                source="nws_alerts",
                legacy_type="severe_weather",
                event_id=alert.event_id,
                review_context=review_context,
            )
        _record_source_run(
            current_run, bot_state, "nws_alerts", nws_start,
            status="success", observed=len(alerts), promoted=source_promoted, drafted=0
        )
    except Exception as e:
        print(f"[alerts] NWS error: {e}")
        state.log_error(bot_state, "nws_alerts", str(e))
        _record_source_run(
            current_run, bot_state, "nws_alerts", nws_start,
            status="failed", error=str(e)
        )
    return
