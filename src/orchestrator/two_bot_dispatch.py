"""Two-bot draft dispatch helpers."""

from __future__ import annotations

import os

from src.orchestrator.suppression import (
    _current_suppression_ctx,
    _record_downstream_suppression,
)
from src.state_schema import BotState


def _two_bot_bundle_for_extreme_signal(
    strongest_type: str,
    strongest_signal,
    *,
    result_out: dict | None = None,
):
    """Return a StoryBundle for the extreme_signals dispatch loop.

    All extreme_signals types now have bundle builders (full port,
    2026-05-04). Voice generator is no longer reachable from this loop.
    Returns None only if a build raises — in which case the signal is
    silently dropped rather than falling through to voice gen.
    """
    try:
        from src.two_bot import intern

        if strongest_type in ("record", "record_low"):
            return intern.build_record_bundle(strongest_signal)
        if strongest_type in ("monthly_high", "monthly_low"):
            return intern.build_monthly_high_bundle(strongest_signal)
        if strongest_type in ("all_time_high", "all_time_low"):
            return intern.build_all_time_record_bundle(strongest_signal)
        if strongest_type in ("anomaly_hot", "anomaly_cold"):
            return intern.build_anomaly_bundle(strongest_signal)
        if strongest_type == "absolute_extreme":
            return intern.build_absolute_extreme_bundle(strongest_signal)
    except Exception as exc:
        print(f"[two_bot.dispatch] Bundle build failed for {strongest_type}: {exc}")
        if result_out is not None:
            result_out["kill_stage"] = "bundle_build"
            result_out["kill_reason"] = f"{type(exc).__name__}: {exc}"
        return None
    if result_out is not None:
        result_out["kill_stage"] = "bundle_build"
        result_out["kill_reason"] = f"No bundle builder for {strongest_type!r}"
    return None


def _try_two_bot_draft(
    bundle,
    bot_state: BotState,
    score,
    *,
    legacy_type: str,
    event_id: str,
    review_context: dict,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    """Run the live two-bot pipeline (writer → claim extract → fact-check
    → memory) and save the draft. Returns True iff a draft was saved.

    Bypasses the voice generator entirely. The cheap-model directive
    (2026-05-03): no Gemini Flash writes the audience-facing text. If
    two-bot returns None, no draft ships for this signal — we do NOT
    fall through to the voice generator.

    ``legacy_type`` is the pre-port signal-type label (e.g. "record",
    "monthly_high", "country_high") used by the dashboard and editorial
    state. The bundle.signal_kind may differ slightly (e.g.
    "calendar_record" vs "record") to give the writer better semantic
    cues, but the saved draft uses the legacy label for compatibility.

    On a None return from the pipeline (writer kill, fact-check rejection,
    or pipeline exception), records a downstream suppression so the
    dashboard surfaces it. These are *post-score* kills, distinct from
    the editorial-gate near-misses captured by ``_should_draft``.
    """
    from src.two_bot.pipeline import generate_draft

    pipeline_result: dict = {}
    draft = generate_draft(bundle, bot_state, result_out=pipeline_result)
    if draft is None:
        ctx = _current_suppression_ctx()
        if ctx is not None:
            _record_downstream_suppression(
                bot_state=ctx["bot_state"],
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=event_id,
                score=score,
                kill_stage=pipeline_result.get("kill_stage", "unknown"),
                kill_reason=pipeline_result.get("kill_reason", "unknown"),
                summary=getattr(bundle, "where", None) or city or None,
            )
        return False
    review_context["two_bot"] = draft["two_bot_metadata"]
    from src.orchestrator import common as _common

    return _common.save_draft(
        draft["text"],
        bot_state,
        legacy_type,
        event_id,
        score=score,
        review_context=review_context,
        city=city,
        tweet_date=tweet_date,
        cooldown_exempt=cooldown_exempt,
    )


def _maybe_shadow_two_bot(bundle, bot_state: BotState, review_context: dict) -> None:
    """Run the shadow two-bot pipeline if enabled, attaching results in place.

    Gated by ``THEHEAT_SHADOW_AB_ENABLED=1``. The shadow's tweet text and
    metadata are stored on ``review_context["shadow_two_bot"]``; the live
    voice-generator tweet is unaffected. Never raises.
    """
    if os.environ.get("THEHEAT_SHADOW_AB_ENABLED") != "1":
        return
    if review_context is None:
        return
    try:
        from src.two_bot.pipeline import generate_shadow_draft

        shadow = generate_shadow_draft(bundle, bot_state)
        if shadow:
            review_context["shadow_two_bot"] = {
                "text": shadow["text"],
                **shadow["two_bot_metadata"],
            }
    except Exception as exc:
        print(f"[shadow_ab] Skipped due to error: {exc}")


__all__ = [
    "_maybe_shadow_two_bot",
    "_try_two_bot_draft",
    "_two_bot_bundle_for_extreme_signal",
]
