"""Stage orchestration for the two-bot pipeline."""

from __future__ import annotations

from src.data.firms import FireEvent
from src.two_bot import claim_extractor, fact_check, memory, writer
from src.two_bot.intern import build_fire_bundle
from src.two_bot.types import StoryBundle


def generate_draft(bundle: StoryBundle, state: dict) -> dict | None:
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

    Never raises.
    """

    try:
        memory_slice = memory.build_memory_slice(state, bundle)
        writer_result = writer.write_tweet(bundle, memory_slice)
        if writer_result.tweet is None:
            print(
                f"[two_bot.pipeline] Writer killed {bundle.signal_kind} draft: "
                f"{writer_result.kill_reason}"
            )
            return None

        extracted = claim_extractor.extract_claims(writer_result.tweet)
        fact_result = fact_check.fact_check(
            writer_result.tweet, extracted, bundle, state
        )
        if not fact_result.passed:
            print(
                f"[two_bot.pipeline] Fact-check rejected {bundle.signal_kind} "
                f"draft: " + "; ".join(fact_result.failures)
            )
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
        return None


def generate_fire_draft(fire: FireEvent, state: dict) -> dict | None:
    """Convenience wrapper: build a fire bundle and run the live pipeline.

    Kept for backwards-compat with main.py's existing fire integration.
    The ``"type"`` field is forced to ``"fire"`` for compatibility with
    the dashboard and existing draft-saving logic.
    """

    bundle = build_fire_bundle(fire)
    draft = generate_draft(bundle, state)
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
