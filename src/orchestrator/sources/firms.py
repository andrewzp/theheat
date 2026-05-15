"""Source runner for NASA FIRMS wildfire alerts."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_firms(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 2. Wildfire alerts via NASA FIRMS
    print("[alerts] Checking wildfires...")
    firms_start = time.perf_counter()
    try:
        fires = _fetch_strict(firms.fetch_fires)
        source_promoted = 0
        source_drafted = 0
        for fire in fires:
            if state.is_duplicate(bot_state, fire.event_id):
                continue
            score = score_fire_event(fire.confidence, fire.frp, region=fire.nearest_city)
            if not _should_draft(score, fire.event_id):
                continue
            source_promoted += 1
            # Record synthesis component as soon as editorial gate passes:
            syn_state = lat_lon_to_state(fire.lat, fire.lon)
            if syn_state:
                state.record_synthesis_component(
                    bot_state,
                    kind="fire",
                    region=syn_state,
                    event_id=fire.event_id,
                    metadata={
                        "frp": float(fire.frp or 0),
                        "region": fire.nearest_city or "",
                    },
                )
            review_context = _review_context(
                source="NASA FIRMS",
                source_key="firms",
                headline=f"Wildfire signal near {fire.nearest_city}",
                current_run=current_run,
                facts=[
                    _fact("Nearest region", fire.nearest_city),
                    _fact("Country", fire.country),
                    _fact("Satellite confidence", f"{fire.confidence}%"),
                    _fact("Fire radiative power", f"{fire.frp:.0f} MW"),
                ],
            )
            # Two-bot pipeline for fire (replaces generator.generate_fire_tweet).
            # This loop is SERIAL by contract: generate_fire_draft mutates
            # state["memory"], so concurrent invocations would race on Gist
            # persistence.
            from src.two_bot.pipeline import generate_fire_draft

            pipeline_result: dict = {}
            draft = generate_fire_draft(
                fire,
                bot_state,
                result_out=pipeline_result,
            )
            if draft is None:
                ctx = _current_suppression_ctx()
                if ctx is not None:
                    _record_downstream_suppression(
                        bot_state=ctx["bot_state"],
                        source=ctx.get("source"),
                        run_id=ctx.get("run_id"),
                        event_id=fire.event_id,
                        score=score,
                        kill_stage=pipeline_result.get("kill_stage", "unknown"),
                        kill_reason=pipeline_result.get("kill_reason", "unknown"),
                        summary=fire.nearest_city or fire.country or None,
                    )
                continue
            review_context["two_bot"] = draft["two_bot_metadata"]
            if save_draft(
                draft["text"],
                bot_state,
                "fire",
                fire.event_id,
                score=score,
                review_context=review_context,
            ):
                state.record_event(bot_state, fire.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "firms", firms_start,
            status="success", observed=len(fires), promoted=source_promoted, drafted=source_drafted
        )
    except SourceSkipped as e:
        print(f"[alerts] FIRMS skipped: {e}")
        _record_source_run(
            current_run, bot_state, "firms", firms_start,
            status="skipped", note=str(e),
        )
    except Exception as e:
        print(f"[alerts] FIRMS error: {e}")
        state.log_error(bot_state, "firms", str(e))
        _record_source_run(
            current_run, bot_state, "firms", firms_start,
            status="failed", error=str(e)
        )
    return drafted
