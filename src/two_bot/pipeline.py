"""Stage orchestration for the two-bot fire pipeline."""

from __future__ import annotations

from src.data.firms import FireEvent
from src.two_bot import claim_extractor, fact_check, memory, writer
from src.two_bot.intern import build_fire_bundle


def generate_fire_draft(fire: FireEvent, state: dict) -> dict | None:
    """Run the five-stage fire pipeline and return a save_draft-ready dict."""

    try:
        bundle = build_fire_bundle(fire)
        memory_slice = memory.build_memory_slice(state, bundle)
        writer_result = writer.write_fire_tweet(bundle, memory_slice)
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

