"""Source runner for US Drought Monitor."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_drought(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 7. US Drought Monitor (weekly, check on Fridays after Thursday update)
    if date.today().weekday() == 4:
        print("[alerts] Checking US drought conditions...")
        drought_start = time.perf_counter()
        try:
            drought_updates = _fetch_strict(drought.fetch_drought_data)
            source_promoted = 0
            source_drafted = 0
            if drought_updates:
                event_id = f"drought_{date.today().isoformat()}"
                if not state.is_duplicate(bot_state, event_id):
                    score = score_drought(drought_updates)
                    if _should_draft(score, event_id):
                        source_promoted = 1
                        worst_state = max(
                            drought_updates,
                            key=lambda item: (
                                (item.d3_pct if hasattr(item, "d3_pct") else item["d3_pct"])
                                + (item.d4_pct if hasattr(item, "d4_pct") else item["d4_pct"])
                            ),
                        )
                        worst_name = worst_state.state if hasattr(worst_state, "state") else worst_state["state"]
                        worst_total = (
                            (worst_state.d3_pct if hasattr(worst_state, "d3_pct") else worst_state["d3_pct"])
                            + (worst_state.d4_pct if hasattr(worst_state, "d4_pct") else worst_state["d4_pct"])
                        )
                        review_context = _review_context(
                            source="US Drought Monitor",
                            source_key="drought",
                            headline="Weekly drought footprint update",
                            current_run=current_run,
                            facts=[
                                _fact("Worst state", worst_name),
                                _fact("Extreme + exceptional drought", f"{worst_total:.0f}%"),
                                _fact("States summarized", len(drought_updates)),
                            ],
                        )
                        # The drought source feeds the writer the per-state
                        # dicts so it can pick its own emphasis (one
                        # standout vs. roll-call across N states).
                        from dataclasses import asdict as _asdict, is_dataclass
                        from src.two_bot.intern import build_drought_bundle
                        drought_dicts = [
                            _asdict(item) if is_dataclass(item) and not isinstance(item, type) else dict(item)
                            for item in drought_updates
                        ]
                        drought_bundle = build_drought_bundle(drought_dicts, event_id=event_id)
                        if _try_two_bot_draft(
                            drought_bundle, bot_state, score,
                            legacy_type="drought",
                            event_id=event_id,
                            review_context=review_context,
                        ):
                            state.record_event(bot_state, event_id)
                            drafted += 1
                            source_drafted = 1
            if drought_updates:
                state.record_synthesis_drought_snapshot(bot_state, drought_updates)
            _record_source_run(
                current_run, bot_state, "drought", drought_start,
                status="success", observed=len(drought_updates), promoted=source_promoted, drafted=source_drafted
            )
        except Exception as e:
            print(f"[alerts] Drought error: {e}")
            state.log_error(bot_state, "drought", str(e))
            _record_source_run(
                current_run, bot_state, "drought", drought_start,
                status="failed", error=str(e)
            )
    else:
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "drought", skipped_start,
            status="skipped", note="Runs Fridays only"
        )
    return drafted
