"""Stage orchestration for the two-bot pipeline."""

from __future__ import annotations

from src.data.firms import FireEvent
from src.two_bot import claim_extractor, fact_check, memory, writer
from src.two_bot.intern import build_fire_bundle
from src.two_bot.types import StoryBundle
from src.voice.safety import run_safety_pipeline


def generate_draft(
    bundle: StoryBundle,
    state: dict,
    *,
    result_out: dict | None = None,
) -> dict | None:
    """Run the full pipeline (writer → claim extract → fact-check) and
    record memory on success. Returns a save_draft-ready dict, or
    ``None`` if the writer kills, fact-check rejects, or anything raises.

    Signal-agnostic. The bundle's ``signal_kind`` carries the type
    forward so the writer can dispatch on it. Used by every live signal
    type that has a bundle builder; raw signal types still go through
    the voice generator until they get builders.

    Returns:
        ``{"text": str, "event_id": str, "type": str, "two_bot_metadata": dict}``
        on success. None otherwise.

    If ``result_out`` is provided, on every None-return path it will be
    populated with ``{"kill_stage": str, "kill_reason": str}`` so callers
    can record a suppression with the actual cause. Without this hook
    pipeline errors are visible only in stdout — invisible to the
    dashboard. (Found 2026-05-07: GHCN bundles dying with
    ``Object of type date is not JSON serializable`` for ~13 hours
    before anyone noticed, because the catch-all swallowed the stack.)

    Never raises.
    """

    def _record_kill(stage: str, reason: str) -> None:
        if result_out is not None:
            result_out["kill_stage"] = stage
            result_out["kill_reason"] = reason

    try:
        memory_slice = memory.build_memory_slice(state, bundle)
        writer_result = writer.write_tweet(bundle, memory_slice)
        if writer_result.tweet is None:
            print(
                f"[two_bot.pipeline] Writer killed {bundle.signal_kind} draft: "
                f"{writer_result.kill_reason}"
            )
            _record_kill("writer", writer_result.kill_reason or "unknown")
            return None

        # Safety gate at draft-time. Historically run_safety_pipeline was
        # only called at post-time (main.py:2874, 2956), so a banned-pattern
        # tweet could sit in the queue waiting for a human to notice. Now
        # the writer output is checked before fact-check — saves an LLM
        # call on the obvious kills and surfaces the failure in the
        # suppression dashboard with stage="safety".
        safety_passed, safety_reason = run_safety_pipeline(writer_result.tweet)
        if not safety_passed:
            print(
                f"[two_bot.pipeline] Safety rejected {bundle.signal_kind} "
                f"draft: {safety_reason}"
            )
            _record_kill("safety", safety_reason or "unknown")
            return None

        extracted = claim_extractor.extract_claims(writer_result.tweet)
        fact_result = fact_check.fact_check(
            writer_result.tweet, extracted, bundle, state
        )
        if not fact_result.passed:
            failures_str = "; ".join(fact_result.failures)
            print(
                f"[two_bot.pipeline] Fact-check rejected {bundle.signal_kind} "
                f"draft: {failures_str}"
            )
            _record_kill("fact_check", failures_str or "unknown")
            return None

        canonical_claims = fact_result.extracted_claims or extracted
        memory.record_shipped(state, bundle, writer_result, canonical_claims)
        return {
            "type": bundle.signal_kind,
            "text": writer_result.tweet,
            "event_id": bundle.event_id,
            "two_bot_metadata": {
                "signal_kind": bundle.signal_kind,
                "angle_chosen": writer_result.angle_chosen,
                "era_anchor_used": writer_result.era_anchor_used,
                "peer_comparison_used": writer_result.peer_comparison_used,
                "reasoning": writer_result.reasoning,
                "fact_check": fact_result.to_dict(),
                "writer_model": writer.WRITER_MODEL,
                "fact_checker_model": fact_check.FACT_CHECKER_MODEL,
            },
        }
    except Exception as exc:
        print(
            f"[two_bot.pipeline] Pipeline error ({bundle.signal_kind}): {exc}"
        )
        _record_kill("pipeline_error", f"{type(exc).__name__}: {exc}")
        return None


def generate_fire_draft(
    fire: FireEvent,
    state: dict,
    *,
    result_out: dict | None = None,
) -> dict | None:
    """Convenience wrapper: build a fire bundle and run the live pipeline.

    Kept for backwards-compat with main.py's existing fire integration.
    The ``"type"`` field is forced to ``"fire"`` for compatibility with
    the dashboard and existing draft-saving logic.
    """

    bundle = build_fire_bundle(fire)
    draft = generate_draft(bundle, state, result_out=result_out)
    if draft is not None:
        # Preserve the legacy "fire" type tag instead of "fire" coming
        # from bundle.signal_kind (which is already "fire", but be
        # explicit for any future bundle.signal_kind divergence).
        draft["type"] = "fire"
    return draft


def generate_shadow_draft(bundle: StoryBundle, state: dict) -> dict | None:
    """Run the writer + fact-check stages WITHOUT recording memory.

    Used for the shadow A/B experiment: the live tweet is still produced by
    the voice generator and posted; this output is stored alongside it for
    side-by-side review.

    Returns ``{"text": str, "two_bot_metadata": dict}`` on success, or
    ``None`` if the writer kills, fact-check rejects, or any error occurs.
    Never raises.

    Critically, this does NOT call ``memory.record_shipped`` — the shadow
    tweet is not actually shipped, so writing it into the memory layer
    would corrupt the banned-reuse list with text the audience never saw.
    Memory is read (so the writer sees the real banned list) but not
    written.
    """

    try:
        memory_slice = memory.build_memory_slice(state, bundle)
        writer_result = writer.write_tweet(bundle, memory_slice)
        if writer_result.tweet is None:
            print(
                f"[two_bot.pipeline] Shadow writer killed "
                f"{bundle.signal_kind} draft: {writer_result.kill_reason}"
            )
            return None

        safety_passed, safety_reason = run_safety_pipeline(writer_result.tweet)
        if not safety_passed:
            print(
                f"[two_bot.pipeline] Shadow safety rejected "
                f"{bundle.signal_kind} draft: {safety_reason}"
            )
            return None

        extracted = claim_extractor.extract_claims(writer_result.tweet)
        fact_result = fact_check.fact_check(
            writer_result.tweet, extracted, bundle, state
        )
        if not fact_result.passed:
            print(
                f"[two_bot.pipeline] Shadow fact-check rejected "
                f"{bundle.signal_kind} draft: " + "; ".join(fact_result.failures)
            )
            return None

        return {
            "text": writer_result.tweet,
            "two_bot_metadata": {
                "signal_kind": bundle.signal_kind,
                "angle_chosen": writer_result.angle_chosen,
                "era_anchor_used": writer_result.era_anchor_used,
                "peer_comparison_used": writer_result.peer_comparison_used,
                "reasoning": writer_result.reasoning,
                "fact_check": fact_result.to_dict(),
                "writer_model": writer.WRITER_MODEL,
                "fact_checker_model": fact_check.FACT_CHECKER_MODEL,
            },
        }
    except Exception as exc:
        print(
            f"[two_bot.pipeline] Shadow pipeline error "
            f"({bundle.signal_kind}): {exc}"
        )
        return None
