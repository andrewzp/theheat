"""Posting and publish queue modes."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *
from src.editorial.approval import (
    AUTOSHIP_ALLOWLIST,
    autoship_max_age_hours,
    autoship_on_critic_pass_enabled,
)
from src.orchestrator.draft_save import _critic_passed


_PUBLISH_INTENT_TTL = timedelta(hours=2)
_DEFAULT_MIN_TWEET_SPACING_MIN = 15


def _demote_autoship_to_manual(draft: dict, reason: str) -> None:
    """Pull a marked auto-ship draft back to manual review (Phase B guard)."""
    draft.pop("auto_approve_at", None)
    draft["approval_mode"] = "manual"
    draft["post_error"] = reason
    _touch_draft(draft)


def _autoship_freshness_anchor(draft: dict):
    """Oldest of the draft's queue age and its source-observation date.

    ``created_at`` catches drafts that SAT in the queue; the source date
    (``tweet_date`` or the persisted bundle ``when``, e.g. a CO2/CH4 milestone's
    measurement date) catches a freshly-created draft built from stale upstream
    data. Either being older than the ceiling blocks the auto-ship.
    """
    anchors = [
        _parse_iso_utc(draft.get("created_at")),
        _parse_iso_utc(draft.get("tweet_date")),
    ]
    review = draft.get("review_context")
    bundle = review.get("two_bot", {}).get("bundle") if isinstance(review, dict) else None
    if isinstance(bundle, dict):
        anchors.append(_parse_iso_utc(bundle.get("when")))
    valid = [a for a in anchors if a is not None]
    return min(valid) if valid else None


def _hot10_card_enabled() -> bool:
    return os.environ.get("THEHEAT_HOT10_CARD_ENABLED", "0") == "1"


def _hot10_media_for_draft(draft: dict) -> tuple[bytes | None, str | None]:
    if not _hot10_card_enabled():
        return None, None
    rows = draft.get("hot10_rows")
    if not isinstance(rows, list) or not rows:
        return None, None

    try:
        from src.media.hot10_card import build_hot10_alt_text, render_hot10_card

        return render_hot10_card(rows), build_hot10_alt_text(rows)
    except Exception as exc:
        print(f"[post] Hot 10 card render failed; posting text-only: {exc!r}")
        return None, None


def _coerce_publish_draft(draft_or_text: dict | str) -> dict:
    if isinstance(draft_or_text, dict):
        return draft_or_text
    return {"text": str(draft_or_text or "")}


def _publish_event_id(draft: dict, *, ensure: bool = True) -> str:
    event_id = str(draft.get("event_id") or draft.get("id") or "").strip()
    if not event_id:
        event_id = f"manual:{secrets.token_hex(8)}"
    if ensure:
        draft.setdefault("event_id", event_id)
    return event_id


def _publish_intent_id(draft: dict, event_id: str) -> str:
    return str(draft.get("publish_intent_id") or draft.get("id") or event_id)


def _publish_ledger(bot_state: BotState) -> dict:
    ledger = bot_state.get("publish_ledger")
    if not isinstance(ledger, dict):
        ledger = {}
        bot_state["publish_ledger"] = ledger
    return ledger


def _reconcile_publish_ledger(bot_state: BotState) -> None:
    """Repair drafts already known posted and clear stale pre-post intents."""
    ledger = _publish_ledger(bot_state)
    now = _utc_now()
    for event_id, row in list(ledger.items()):
        if not isinstance(row, dict):
            del ledger[event_id]
            continue
        at = _parse_iso_utc(row.get("at"))
        tweet_id = row.get("tweet_id")
        if tweet_id:
            for draft in bot_state.get("drafts", []):
                if _publish_event_id(draft, ensure=False) != event_id:
                    continue
                if draft.get("status") == "posted":
                    continue
                draft["status"] = "posted"
                draft["tweet_id"] = str(tweet_id)
                draft["posted_at"] = row.get("at") or _utc_now_iso()
                draft["last_publish_attempt_at"] = draft["posted_at"]
                draft.pop("auto_approve_at", None)
                draft.pop("auto_approve_requested_at", None)
                draft.pop("post_error", None)
                draft.pop("publish_intent_id", None)
                _touch_draft(draft)
                print(f"[post] Repaired posted draft {draft.get('id') or event_id} from publish ledger")
            continue
        if at is None or now - at > _PUBLISH_INTENT_TTL:
            del ledger[event_id]
            print(f"[post] Cleared stale publish intent for {event_id}")


def _publish_intent_in_progress(draft: dict, bot_state: BotState) -> bool:
    row = _publish_ledger(bot_state).get(_publish_event_id(draft))
    if not isinstance(row, dict) or row.get("tweet_id"):
        return False
    at = _parse_iso_utc(row.get("at"))
    return at is not None and _utc_now() - at <= _PUBLISH_INTENT_TTL


def _min_tweet_spacing() -> timedelta:
    raw = os.environ.get("THEHEAT_MIN_TWEET_SPACING_MIN", str(_DEFAULT_MIN_TWEET_SPACING_MIN))
    try:
        minutes = max(0, int(raw))
    except ValueError:
        minutes = _DEFAULT_MIN_TWEET_SPACING_MIN
    return timedelta(minutes=minutes)


def _last_posted_at(bot_state: BotState):
    last_post = None
    for draft in bot_state.get("drafts", []):
        if draft.get("status") != "posted":
            continue
        posted_at = _parse_iso_utc(draft.get("posted_at"))
        if posted_at is not None and (last_post is None or posted_at > last_post):
            last_post = posted_at
    return last_post


def _record_published_two_bot_memory(bot_state: BotState, draft: dict) -> None:
    try:
        from src.two_bot.memory import record_published_draft

        record_published_draft(bot_state, draft)
    except Exception as exc:  # noqa: BLE001
        print(f"[post] Failed to record two-bot publish memory: {exc!r}")


def post_approved(draft_or_text: dict | str, bot_state: BotState) -> str:
    """Post an approved tweet to X.

    Returns "posted", "rate_limited", or "failed".
    """
    if not state.check_daily_cap(bot_state):
        print("[post] Daily tweet cap reached, skipping")
        return "failed"

    draft = _coerce_publish_draft(draft_or_text)
    tweet_text = str(draft.get("text") or "")
    event_id = _publish_event_id(draft)
    intent_id = _publish_intent_id(draft, event_id)
    ledger = _publish_ledger(bot_state)
    ledger[event_id] = {
        "intent_id": intent_id,
        "tweet_id": None,
        "at": _utc_now_iso(),
    }
    if not state.write_state(bot_state):
        print(f"[post] Failed to durably record publish intent for {event_id}, aborting")
        return "failed"

    media_png, alt_text = _hot10_media_for_draft(draft)
    result = post_tweet(tweet_text, media_png=media_png, alt_text=alt_text)
    if result is None:
        print("[post] Failed to post to X")
        return "failed"

    if result.get("error") == "rate_limited":
        return "rate_limited"

    tweet_id = str(result.get("id") or "")
    if not tweet_id:
        print("[post] Posted response missing tweet id")
        return "failed"

    ledger[event_id]["tweet_id"] = tweet_id
    draft["tweet_id"] = tweet_id
    draft["status"] = "posted"
    draft["posted_at"] = _utc_now_iso()
    draft["last_publish_attempt_at"] = draft["posted_at"]
    if event_id and event_id not in bot_state.get("posted_events", []):
        state.record_event(bot_state, event_id)
    _record_published_two_bot_memory(bot_state, draft)
    post_to_bluesky(tweet_text)
    state.increment_daily_count(bot_state)
    print(f"[post] Posted to X: {tweet_text[:60]}...")
    return "posted"


def run_manual_tweet(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Post an approved tweet from the TWEET_TEXT env var."""
    manual_start = time.perf_counter()
    tweet_text = os.environ.get("TWEET_TEXT", "").strip()
    draft_id = os.environ.get("DRAFT_ID", "").strip()
    publish_intent_id = os.environ.get("PUBLISH_INTENT_ID", "").strip()
    _reconcile_publish_ledger(bot_state)
    draft = _find_draft(bot_state, draft_id=draft_id, tweet_text=tweet_text)
    if not tweet_text:
        print("[manual] No TWEET_TEXT provided, skipping")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="skipped", note="No TWEET_TEXT provided"
        )
        return bot_state

    if draft_id and not draft:
        reason = f"Draft not found for id {draft_id}"
        print(f"[manual] {reason}, skipping")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    if draft_id and draft and draft.get("status") == "posted":
        print(f"[manual] Draft {draft_id} already posted, skipping duplicate publish")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="skipped", observed=1, note=f"Draft {draft_id} already posted"
        )
        return bot_state

    if draft_id and draft and draft.get("status") != "approved":
        reason = f"Draft {draft_id} is not approved for publishing"
        print(f"[manual] {reason}")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    if draft_id and draft and publish_intent_id and draft.get("publish_intent_id") != publish_intent_id:
        reason = f"Draft {draft_id} publish intent is stale"
        print(f"[manual] {reason}, skipping")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="skipped", observed=1, note=reason
        )
        return bot_state

    if len(tweet_text) > 280:
        print(f"[manual] Tweet too long ({len(tweet_text)} chars), skipping")
        if draft:
            draft["status"] = "pending"
            draft["post_error"] = f"Tweet too long ({len(tweet_text)} chars)"
            draft.pop("publish_intent_id", None)
            _touch_draft(draft)
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=f"Tweet too long ({len(tweet_text)} chars)"
        )
        return bot_state

    passed, safety_reason = run_safety_pipeline(tweet_text)
    if not passed:
        reason = safety_reason or "Safety pipeline rejected tweet"
        print(f"[manual] Safety rejected tweet: {reason}")
        if draft:
            draft["status"] = "pending"
            draft["post_error"] = reason
            draft.pop("publish_intent_id", None)
            _touch_draft(draft)
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    print(f"[manual] Posting: {tweet_text}")
    publish_draft = draft or {"text": tweet_text}
    result = post_approved(publish_draft, bot_state)

    # Update draft status with post result
    if draft:
        draft["last_publish_attempt_at"] = _utc_now_iso()
        if result == "posted":
            draft["status"] = "posted"
            draft["posted_at"] = _utc_now_iso()
            draft.pop("post_error", None)
            draft.pop("publish_intent_id", None)
        elif result == "rate_limited":
            draft["status"] = "pending"
            draft["post_error"] = "Rate limited — retry later"
            draft.pop("publish_intent_id", None)
            print("[manual] Rate limited, draft kept as pending for retry")
        else:
            draft["status"] = "pending"
            draft["post_error"] = "Failed to post to X"
            draft.pop("publish_intent_id", None)
        _touch_draft(draft)

    source_status = "success" if result == "posted" else "failed"
    error = None if result == "posted" else ("Rate limited — retry later" if result == "rate_limited" else "Failed to post to X")
    _record_source_run(
        current_run, bot_state, "manual_publish", manual_start,
        status=source_status, observed=1, promoted=1, drafted=1 if result == "posted" else 0, error=error
    )
    return bot_state


def process_due_drafts(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Post drafts whose auto-approval window has elapsed."""
    queue_start = time.perf_counter()
    _reconcile_publish_ledger(bot_state)
    now = _utc_now()
    due_drafts = []
    for draft in bot_state.get("drafts", []):
        if draft.get("status") != "pending":
            continue
        auto_approve_at = _parse_iso_utc(draft.get("auto_approve_at"))
        if auto_approve_at and auto_approve_at <= now:
            due_drafts.append(draft)

    if not due_drafts:
        _record_source_run(
            current_run, bot_state, "auto_publish_due", queue_start,
            status="skipped", observed=0, note="No drafts due for auto-approval"
        )
        return bot_state

    published = 0
    failures = []
    spacing = _min_tweet_spacing()
    for idx, draft in enumerate(due_drafts):
        last_post = _last_posted_at(bot_state)
        if last_post is not None and _utc_now() - last_post < spacing:
            deferred = sum(
                1 for remaining in due_drafts[idx:]
                if remaining.get("status") == "pending"
            )
            print(f"[posting] spacing guard: deferring {deferred} due drafts")
            break

        if _publish_intent_in_progress(draft, bot_state):
            draft["post_error"] = "Publish intent already recorded; waiting for post result"
            _touch_draft(draft)
            failures.append(f"{draft.get('id')}: publish intent in progress")
            continue

        policy = draft.get("approval_policy", {})
        is_policy_auto = policy.get("mode") == "armed_auto"
        is_requested_auto = (
            policy.get("mode") == "suggested_auto"
            and draft.get("approval_mode") == "auto"
        )
        if policy.get("can_auto_approve") is False or not (is_policy_auto or is_requested_auto):
            draft.pop("auto_approve_at", None)
            draft["approval_mode"] = "manual"
            draft["post_error"] = "Auto-approval blocked by policy"
            _touch_draft(draft)
            failures.append(f"{draft.get('id')}: blocked by policy")
            continue

        # Phase B auto-ship guards. A draft is "managed" if it was armed at save
        # time (the marker) OR — to close the activation-window hole — it is a due
        # allowlist-type draft while the flag is ON (e.g. an armed_auto policy_auto
        # draft created before the flag was flipped on). When the flag is OFF and a
        # draft has no marker, `managed` is False → byte-for-byte the current path.
        flag_on = autoship_on_critic_pass_enabled()
        managed = bool(draft.get("autoship_on_critic_pass")) or (
            flag_on and draft.get("type") in AUTOSHIP_ALLOWLIST
        )
        if managed:
            # (1) Rollback: flag flipped OFF stops auto-shipping even pre-marked drafts.
            if not flag_on:
                _demote_autoship_to_manual(draft, "Autoship disabled (flag off)")
                failures.append(f"{draft.get('id')}: autoship disabled")
                continue
            # (1b) Critic PASS is mandatory. Pre-marked drafts already proved it at
            # save time; an unmarked transition-window draft must prove it now from
            # its review_context (fail-closed: no critic PASS ⇒ manual, never post).
            if not draft.get("autoship_on_critic_pass") and not _critic_passed(draft.get("review_context")):
                _demote_autoship_to_manual(draft, "Autoship blocked: no critic PASS")
                failures.append(f"{draft.get('id')}: autoship no critic pass")
                continue
            # (2) Idempotency (one-shot): a prior attempt that didn't confirm 'posted'
            # is handed to a human — never blind-retried (unknown-success double-post).
            if draft.get("autoship_attempted"):
                _demote_autoship_to_manual(draft, "Autoship attempt unconfirmed; needs human review")
                failures.append(f"{draft.get('id')}: autoship attempt unconfirmed")
                continue
            # (3) Freshness: stale real-time framing must not auto-ship — checks
            # both queue age AND source-observation date (oldest wins).
            anchor = _autoship_freshness_anchor(draft)
            if anchor is not None and _utc_now() - anchor > timedelta(hours=autoship_max_age_hours()):
                _demote_autoship_to_manual(draft, "Autoship blocked: stale framing (queue or source age)")
                failures.append(f"{draft.get('id')}: autoship stale")
                continue
            # (4) Event idempotency: never auto-post an event already posted (a
            # second pending draft for the same event_id from a state merge would
            # otherwise double-post — post_approved overwrites the ledger row).
            event_id = _publish_event_id(draft, ensure=False)
            ledger_row = _publish_ledger(bot_state).get(event_id)
            already_posted = (event_id and event_id in (bot_state.get("posted_events") or [])) or (
                isinstance(ledger_row, dict) and ledger_row.get("tweet_id")
            )
            if already_posted:
                _demote_autoship_to_manual(draft, "Autoship blocked: event already posted")
                failures.append(f"{draft.get('id')}: autoship event already posted")
                continue
            # Mark the attempt BEFORE post_approved's durable state write, and bump
            # updated_at so this marked draft copy wins the state merge — a crash
            # mid-post can't drop the marker and blind-retry into a double-post.
            draft["autoship_attempted"] = True
            _touch_draft(draft)

        # Safety check before auto-posting (same gate as manual path)
        passed, reason = run_safety_pipeline(draft["text"])
        if not passed:
            draft.pop("auto_approve_at", None)
            draft["status"] = "pending"
            draft["approval_mode"] = "manual"
            draft["post_error"] = f"Auto-post safety rejected: {reason}"
            _touch_draft(draft)
            failures.append(f"{draft.get('id')}: safety rejected: {reason}")
            continue

        result = post_approved(draft, bot_state)
        draft["last_publish_attempt_at"] = _utc_now_iso()
        if result == "posted":
            draft["status"] = "posted"
            draft["approved_at"] = draft.get("approved_at") or _utc_now_iso()
            draft["posted_at"] = _utc_now_iso()
            draft["approval_mode"] = draft.get("approval_mode") or "auto"
            draft.pop("auto_approve_at", None)
            draft.pop("auto_approve_requested_at", None)
            draft.pop("post_error", None)
            published += 1
        elif result == "rate_limited":
            draft["post_error"] = "Rate limited — retry later"
            # Clean pre-post rejection (no tweet sent) — safe to retry next cycle, so
            # clear the one-shot marker on any auto-ship draft we attempted (marked
            # or transition-window). Keyed on autoship_attempted, which only managed
            # drafts ever carry.
            if draft.get("autoship_attempted"):
                draft.pop("autoship_attempted", None)
            failures.append(f"{draft.get('id')}: rate limited")
        else:
            draft["post_error"] = "Failed to post to X"
            # Unknown outcome (request may have reached X) — hand to a human rather
            # than blind-retry into a possible double-post.
            if draft.get("autoship_attempted"):
                draft["approval_mode"] = "manual"
                draft.pop("auto_approve_at", None)
            failures.append(f"{draft.get('id')}: failed to post")
        _touch_draft(draft)

    status = "success" if not failures else "partial_failure"
    _record_source_run(
        current_run, bot_state, "auto_publish_due", queue_start,
        status=status,
        observed=len(due_drafts),
        promoted=len(due_drafts),
        drafted=published,
        error="; ".join(failures[:3]) if failures else None,
    )
    return bot_state
