"""Draft persistence helpers for orchestrator flows."""

from __future__ import annotations

import os
from typing import Any

from src.editorial.scheduling import defer_to_engagement_window
from src.editorial.approval import (
    AUTOSHIP_ALLOWLIST,
    ApprovalPolicy,
    autoship_on_critic_pass_enabled,
    recommend_approval_policy,
)
from src.editorial.newsworthiness import detect_impact_citation
from src.editorial.scoring import EditorialScore
from src.orchestrator.caps import CITY_COOLDOWN_DAYS, ELITE_COPY_SCORE, MAX_DRAFTS
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


def _touch_draft(draft: dict) -> None:
    draft["updated_at"] = _utc_now_iso()


# Lifecycle-transition rejections mean "the NWS warning changed tier or
# ended", not "editorially killed" — the same event id may honestly
# re-draft when its tier recurs (PDS → emergency → PDS oscillation).
# Operator and TTL rejections keep blocking. Known accepted edge: a
# dashboard re-rejection that retains a stale automatic reason re-opens
# redraft — reaching it requires an operator to REAPPROVE a
# lifecycle-rejected draft first, and reconciliation re-attests every
# cycle either way.
_REDRAFTABLE_REJECTIONS = frozenset(
    {
        "superseded_by_emergency_upgrade",
        "nws_lifecycle_downgraded",
    }
)


def _blocks_redraft(draft: dict) -> bool:
    return not (
        draft.get("status") == "rejected"
        and draft.get("rejected_reason") in _REDRAFTABLE_REJECTIONS
    )


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
    drafts = bot_state.get("drafts", []) or []
    if event_id and any(
        d.get("event_id") == event_id and _blocks_redraft(d) for d in drafts
    ):
        return False, "duplicate_draft"
    if event_id and _state.is_duplicate(bot_state, event_id):
        return False, "duplicate_posted"

    city = getattr(candidate, "city", "") or ""
    tweet_date = getattr(candidate, "tweet_date", "") or ""
    score = getattr(candidate, "score", None)
    new_total = int(getattr(score, "total", 0) or 0)
    if city and tweet_date:
        if _same_day_already_posted(drafts, city, tweet_date):
            return False, "same_day_posted"
        collision = _same_day_pending_collision(drafts, city, tweet_date)
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
        and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS)
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
    drafts = bot_state.setdefault("drafts", [])

    # Don't duplicate drafts for the same event
    if event_id and any(
        d.get("event_id") == event_id and _blocks_redraft(d) for d in drafts
    ):
        print(f"[draft] Already drafted: {event_id}")
        _record_save_rejection(
            bot_state=bot_state,
            event_id=event_id,
            score=score,
            kill_stage="duplicate_draft",
            kill_reason="Event already has a draft",
            summary=tweet_text[:120] or event_id,
        )
        return False

    # (city, date) dedup — highest signal wins
    if city and tweet_date:
        if _same_day_already_posted(drafts, city, tweet_date):
            print(f"[draft] Already posted for {city} on {tweet_date}, skipping")
            _record_save_rejection(
                bot_state=bot_state,
                event_id=event_id,
                score=score,
                kill_stage="same_day_posted",
                kill_reason=f"Already posted for {city} on {tweet_date}",
                summary=city,
            )
            return False

        collision = _same_day_pending_collision(drafts, city, tweet_date)
        if collision:
            idx, other = collision
            other_total = (other.get("score") or {}).get("total", 0)
            new_total = score.total if score else 0
            if new_total <= other_total:
                print(
                    f"[draft] Weaker signal for {city} on {tweet_date} "
                    f"({new_total} ≤ {other_total}), skipping"
                )
                _record_save_rejection(
                    bot_state=bot_state,
                    event_id=event_id,
                    score=score,
                    kill_stage="same_day_dedup",
                    kill_reason=(
                        f"Weaker same-day signal for {city} "
                        f"({new_total} <= {other_total})"
                    ),
                    summary=city,
                )
                return False
            _record_save_rejection(
                bot_state=bot_state,
                event_id=other.get("event_id", ""),
                score=other.get("score"),
                kill_stage="same_day_superseded",
                kill_reason=(
                    f"Superseded by stronger same-day signal "
                    f"({new_total} > {other_total})"
                ),
                summary=city,
            )
            drafts.pop(idx)
            print(
                f"[draft] Superseded pending {city} draft "
                f"({other_total} → {new_total})"
            )

    # City cooldown — skip if we posted about this city in the last N days.
    # Exceptional copy (candidate_score.total >= ELITE_COPY_SCORE) bypasses,
    # even if the underlying signal wasn't flagged elite by the caller.
    copy_is_elite = bool(
        candidate_score
        and isinstance(candidate_score, dict)
        and candidate_score.get("total", 0) >= ELITE_COPY_SCORE
    )
    if (
        city
        and not cooldown_exempt
        and not copy_is_elite
        and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS)
    ):
        print(f"[draft] {city} in {CITY_COOLDOWN_DAYS}-day cooldown, skipping")
        _record_save_rejection(
            bot_state=bot_state,
            event_id=event_id,
            score=score,
            kill_stage="city_cooldown",
            kill_reason=f"{city} in {CITY_COOLDOWN_DAYS}-day cooldown",
            summary=city,
        )
        return False

    # Prune oldest non-pending drafts to prevent unbounded growth
    if len(drafts) >= MAX_DRAFTS:
        before = len(drafts)
        bot_state["drafts"] = [
            d for d in drafts if d.get("status") == "pending"
        ][-MAX_DRAFTS:]
        drafts = bot_state["drafts"]
        print(f"[draft] Pruned {before - len(drafts)} old drafts")

    draft: dict[str, Any] = {
        "id": f"draft_{_utc_now().strftime('%Y%m%d_%H%M%S')}_{len(drafts)}",
        "text": tweet_text,
        "type": tweet_type,
        "event_id": event_id,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "status": "pending",
    }
    if city:
        draft["city"] = city
    if tweet_date:
        draft["tweet_date"] = tweet_date
    if score is not None:
        draft["score"] = score.as_dict()
    if candidates:
        draft["candidates"] = candidates
    if candidate_score:
        draft["candidate_score"] = candidate_score
    if review_context:
        draft["review_context"] = review_context
    if evaluator_metadata is not None:
        draft.update(evaluator_metadata)

    policy = recommend_approval_policy(
        tweet_type,
        signal_total=score.total if score is not None else 0,
        candidate_score=candidate_score,
    )

    # Bet A decision 4: a draft whose TEXT cites a sourced human_impact fact is
    # forced manual_only regardless of signal type — including the autoship
    # allowlist types. Death tolls are life-safety-adjacent; a human stays in
    # the loop for every impact-carrying tweet in v1. The rule keys on what the
    # tweet says (writer self-report + regex sweep, fail-closed), not what lane
    # produced it — an enriched draft that does NOT cite impact keeps its #352
    # autoship eligibility.
    citation = detect_impact_citation(tweet_text, review_context)
    if citation.forced:
        if citation.disagreement:
            print(
                "[draft] impact-citation signals disagree "
                f"(writer={citation.writer_flag} regex={citation.regex_hit}) "
                "— forcing manual review (fail-closed)"
            )
        policy = ApprovalPolicy(
            key="impact_citation_manual",
            mode="manual_only",
            recommended_delay_minutes=None,
            can_auto_approve=False,
            reason=(
                "Draft cites a sourced human-impact fact. Impact-carrying "
                "tweets always get a human review (Bet A decision 4)."
            ),
        )
        draft["forced_manual"] = "cited_impact"

    draft["approval_policy"] = policy.as_dict()
    draft.setdefault("approval_mode", "manual")

    if (
        not citation.forced
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
        if _critic_passed(review_context):
            delay = policy.recommended_delay_minutes or 30
            draft["auto_approve_at"] = _maybe_defer_auto_approve_at(_utc_after_minutes_iso(delay))
            draft["auto_approve_requested_at"] = _utc_now_iso()
            draft["approval_mode"] = "auto"
            draft["autoship_on_critic_pass"] = True
    elif policy.mode == "armed_auto" and policy.recommended_delay_minutes:
        # Existing armed_auto path: flag OFF, or armed_auto types NOT in the allowlist
        # (e.g. oscillation_transition). Byte-for-byte the current behavior.
        draft["auto_approve_at"] = _maybe_defer_auto_approve_at(
            _utc_after_minutes_iso(policy.recommended_delay_minutes)
        )
        draft["auto_approve_requested_at"] = _utc_now_iso()
        draft["approval_mode"] = "policy_auto"

    drafts.append(draft)
    print(f"[draft] Saved: {tweet_text[:60]}...")
    return True


__all__ = [
    "_touch_draft",
    "can_draft_candidate",
    "save_draft",
]
