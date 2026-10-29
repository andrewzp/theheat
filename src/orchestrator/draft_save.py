"""Draft persistence helpers for orchestrator flows."""

from __future__ import annotations

import os

from src.editorial.publication import automatic_publication_policy
from src.editorial.scheduling import defer_to_engagement_window
from src.editorial.approval import (
    AUTOSHIP_ALLOWLIST,
    ApprovalPolicy,
    autoship_on_critic_pass_enabled,
)
from src.editorial.newsworthiness import detect_impact_citation
from src.editorial.revisions import authorize_draft, review_is_current
from src.editorial.scoring import EditorialScore
from src.orchestrator.caps import CITY_COOLDOWN_DAYS
from src.orchestrator.common import (
    _parse_iso_utc,
    _utc_after_minutes_iso,
    _utc_now,
    _utc_now_iso,
)
from src.orchestrator.dedup import (
    _posted_city_within_days,
    _same_day_already_posted,
    _same_day_pending_collision,
)
from src.orchestrator.suppression import _record_save_rejection
from src.state_schema import BotState
from src.data.places import event_identity, legacy_publication_status
from src.data.fire_identity import legacy_history_reason


def _touch_draft(draft: dict) -> None:
    draft["updated_at"] = _utc_now_iso()


def can_draft_candidate(bot_state: BotState, candidate) -> tuple[bool, str]:
    """Pre-writer deterministic gate (Phase C): would ``save_draft`` reject this
    candidate regardless of the not-yet-written copy? If so the refill loop skips
    it BEFORE the writer runs ($0 LLM). ``save_draft`` keeps the same gates as
    defense in depth; this only mirrors the *certain* rejections.

    Safe because two-bot drafts never pass ``candidate_score`` to ``save_draft``,
    so the copy-elite cooldown bypass is dead — every rejection here is certain.
    Covers BOTH dedup layers (codex correction): durable posted-event dedup
    (``state.is_duplicate``) AND draft_save's event/city-date/cooldown gates.
    Returns ``(True, "")`` when drafting may proceed, else ``(False, reason)``
    where reason matches the suppression stage vocabulary.
    """
    from src import state as _state

    event_id = getattr(candidate, "event_id", "") or ""
    fire_hold = legacy_history_reason(bot_state, event_id)
    if fire_hold:
        return False, fire_hold
    place_id = event_identity(event_id).get("place_id", "")
    history_status = legacy_publication_status(bot_state, event_id)
    if history_status == "duplicate":
        return False, "duplicate_posted"
    if history_status == "unresolved":
        return False, "legacy_publish_unresolved"
    if history_status == "unregistered":
        return False, "unregistered_place"
    drafts = bot_state.get("drafts", []) or []
    if event_id and any(d.get("event_id") == event_id for d in drafts):
        return False, "duplicate_draft"
    if event_id and _state.is_duplicate(bot_state, event_id):
        return False, "duplicate_posted"

    city = getattr(candidate, "city", "") or ""
    tweet_date = getattr(candidate, "tweet_date", "") or ""
    score = getattr(candidate, "score", None)
    new_total = int(getattr(score, "total", 0) or 0)
    if city and tweet_date:
        if _same_day_already_posted(drafts, city, tweet_date, place_id=place_id):
            return False, "same_day_posted"
        collision = _same_day_pending_collision(drafts, city, tweet_date, place_id=place_id)
        if collision:
            _idx, other = collision
            other_total = int((other.get("score") or {}).get("total", 0) or 0)
            if new_total <= other_total:
                return False, "same_day_dedup"
            # Stronger than the pending same-day draft — save_draft will supersede
            # (pop) the weaker one; allow the attempt.
    if (
        city
        and not getattr(candidate, "cooldown_exempt", False)
        and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS, place_id=place_id)
    ):
        return False, "city_cooldown"
    return True, ""


def _critic_passed(review_context: dict | None) -> bool:
    """True only when the draft carries an explicit two-bot critic PASS.

    Fail-closed (Phase B / codex): no two-bot critic metadata (critic disabled, or
    a non-two-bot draft) ⇒ NOT a pass. A fact-check-only draft never auto-ships.
    """
    if not isinstance(review_context, dict):
        return False
    critic = review_context.get("two_bot", {})
    critic = critic.get("critic") if isinstance(critic, dict) else None
    if not isinstance(critic, dict):
        return False
    return critic.get("passed") is True and str(critic.get("verdict", "")).upper() == "PASS"


def _maybe_defer_auto_approve_at(auto_approve_at: str) -> str:
    if os.environ.get("THEHEAT_ENGAGEMENT_WINDOW_ENABLED", "0") != "1":
        return auto_approve_at
    parsed = _parse_iso_utc(auto_approve_at)
    if parsed is None:
        return auto_approve_at
    return defer_to_engagement_window(parsed).isoformat().replace("+00:00", "Z")


def save_draft(
    tweet_text: str,
    bot_state: BotState,
    tweet_type: str,
    event_id: str = "",
    score: EditorialScore | None = None,
    candidates: list[dict] | None = None,
    candidate_score: dict | None = None,
    review_context: dict | None = None,
    evaluator_metadata: dict | None = None,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    """Save a generated tweet as a draft for review.

    When ``city`` and ``tweet_date`` are provided, two extra gates apply:

    * **Same (city, date) dedup.** Only the highest-scoring draft per city
      per day survives. A stronger signal arriving later supersedes a still-
      pending weaker draft; a weaker signal is dropped. If a draft for that
      (city, date) has already been posted, the new one is skipped.

    * **City cooldown.** If the city had a tweet posted within the last
      ``CITY_COOLDOWN_DAYS`` days, new drafts for that city are dropped
      unless ``cooldown_exempt=True`` (elite signals — all-time records,
      extreme anomalies, streaks, NOAA confirmations) OR the copy itself
      is exceptional (``candidate_score.total >= ELITE_COPY_SCORE``).

    These gates are scoped to city-based extreme-temperature signals; other
    event types (fires, disasters, CO2, sea ice, etc.) omit ``city`` and
    pass through unchanged.
    """
    from src.editorial.draft_admission import plan_draft_admission, resolve_admission_place_facts
    from src.editorial.policy import current_editorial_policy

    clock = _utc_now()
    if tweet_type == "official_warning":
        from src.editorial.official_warning import WarningHold
        from src.editorial.warning_runtime import guard_warning_story
        from src.two_bot.types import StoryBundle
        try:
            raw_bundle = (review_context or {}).get("two_bot", {}).get("bundle")
            guard_warning_story(StoryBundle(**raw_bundle), candidate=tweet_text)
        except (WarningHold, TypeError, ValueError, AttributeError):
            return False
    # Plan before changing the caller: in particular, a later cooldown rejection
    # cannot delete the stronger candidate's still-pending predecessor.
    # These three existing cycle-only objects are neither publication history nor
    # stored state. Preserve their original shared references when committing.
    planning_state = {k: v for k, v in bot_state.items() if k not in {"_triage_queue", "_funnel_sink", "_reganom_live_cache"}}
    place_facts = resolve_admission_place_facts(planning_state, event_id)
    plan = plan_draft_admission(planning_state, text=tweet_text, tweet_type=tweet_type, place_facts=place_facts,
        event_id=event_id, draft_id=f"draft_{clock.strftime('%Y%m%d_%H%M%S')}_{len(bot_state.get('drafts', []))}",
        at=clock, editorial_policy=current_editorial_policy(), score=score.as_dict() if score else None,
        candidates=candidates, candidate_score=candidate_score, review_context=review_context,
        evaluator_metadata=evaluator_metadata, city=city, tweet_date=tweet_date, cooldown_exempt=cooldown_exempt)
    if plan.draft is None:
        for decision in plan.suppressions:
            _record_save_rejection(bot_state=bot_state, **decision)
        print(f"[draft] Not saved: {plan.reason}")
        return False
    draft = plan.draft
    policy = ApprovalPolicy(**draft["approval_policy"])
    citation = detect_impact_citation(tweet_text, review_context)
    history_status = legacy_publication_status(bot_state, event_id)

    publication_policy = automatic_publication_policy(bot_state)
    if (
        publication_policy["enabled"]
        and not citation.forced
        and history_status != "ambiguous"
        and autoship_on_critic_pass_enabled()
        and tweet_type in AUTOSHIP_ALLOWLIST
    ):
        # Phase B: when the flag is ON, this branch governs ALL auto-shipping for the
        # HARD allowlist types — including the armed_auto-policy (strong) variants, so
        # they no longer bare-post around the critic/freshness/idempotency guards.
        # A real critic PASS arms the guarded autoship path (approval_mode="auto" + a
        # delayed auto_approve_at — process_due_drafts needs BOTH — plus the marker
        # that scopes the posting-time guards). Anything else stays MANUAL
        # (fail-closed): a disabled/absent critic verdict never auto-ships.
        if _critic_passed(review_context) and review_is_current(draft):
            delay = policy.recommended_delay_minutes or 30
            draft["auto_approve_at"] = _maybe_defer_auto_approve_at(_utc_after_minutes_iso(delay))
            draft["auto_approve_requested_at"] = _utc_now_iso()
            draft["approval_mode"] = "auto"
            draft["autoship_on_critic_pass"] = True
            authorize_draft(draft, "auto", publication_epoch=publication_policy["epoch"])
    elif (
        publication_policy["enabled"]
        and policy.mode == "armed_auto"
        and policy.recommended_delay_minutes
        and review_is_current(draft)
        and (draft.get("review_binding") or {}).get("kind") == "model"
    ):
        # Policy-only automation needs the same current review as critic autoship.
        draft["auto_approve_at"] = _maybe_defer_auto_approve_at(
            _utc_after_minutes_iso(policy.recommended_delay_minutes)
        )
        draft["auto_approve_requested_at"] = _utc_now_iso()
        draft["approval_mode"] = "policy_auto"
        authorize_draft(draft, "auto", publication_epoch=publication_policy["epoch"])

    if tweet_type == "official_warning":
        try:
            guard_warning_story(StoryBundle(**raw_bundle), candidate=tweet_text)
        except (WarningHold, TypeError, ValueError, AttributeError):
            return False
    bot_state["drafts"] = plan.state["drafts"]
    for decision in plan.suppressions:
        _record_save_rejection(bot_state=bot_state, **decision)
    # Retention belongs at state persistence, after cycle selection. Pruning
    # here could drop protected history and shift the cycle's starting index.
    print(f"[draft] Saved: {tweet_text[:60]}...")
    return True


__all__ = [
    "_touch_draft",
    "can_draft_candidate",
    "save_draft",
]
