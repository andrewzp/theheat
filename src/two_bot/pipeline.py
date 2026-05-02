"""Stage orchestration for the two-bot pipeline."""

from __future__ import annotations

from src.data.firms import FireEvent
from src.two_bot import claim_extractor, fact_check, memory, writer
from src.two_bot.intern import build_fire_bundle
from src.two_bot.types import StoryBundle


def generate_fire_draft(fire: FireEvent, state: dict) -> dict | None:
    """Run the five-stage fire pipeline and return a save_draft-ready dict."""

    try:
        bundle = build_fire_bundle(fire)
        memory_slice = memory.build_memory_slice(state, bundle)
        writer_result = writer.write_tweet(bundle, memory_slice)
        if writer_result.tweet is None:
            print(f"[two_bot.pipeline] Writer killed fire draft: {writer_result.kill_reason}")
            return None

        extracted = claim_extractor.extract_claims(writer_result.tweet)
        fact_result = fact_check.fact_check(writer_result.tweet, extracted, bundle, state)
        if not fact_result.passed:
            print(
                "[two_bot.pipeline] Fact-check rejected fire draft: "
                + "; ".join(fact_result.failures)
            )
            return None

        canonical_claims = fact_result.extracted_claims or extracted
        memory.record_shipped(state, bundle, writer_result, canonical_claims)
        return {
            "type": "fire",
            "text": writer_result.tweet,
            "event_id": fire.event_id,
            "two_bot_metadata": {
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
        print(f"[two_bot.pipeline] Fire pipeline error: {exc}")
        return None


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

