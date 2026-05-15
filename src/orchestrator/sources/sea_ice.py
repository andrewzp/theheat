"""Source runner for Sea ice records."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_sea_ice(bot_state: BotState, current_run: dict | None) -> int:
    drafted = 0
    # 6. Sea ice records (check weekly on Mondays to avoid hammering NSIDC)
    if date.today().weekday() == 0:
        print("[alerts] Checking sea ice records...")
        for hemisphere in ("Arctic", "Antarctic"):
            sea_ice_start = time.perf_counter()
            try:
                readings = _fetch_strict(sea_ice.fetch_sea_ice, hemisphere=hemisphere)
                record = sea_ice.detect_record_low(readings)
                sea_ice_score: EditorialScore | None = None
                if record and not state.is_duplicate(bot_state, record.event_id):
                    sea_ice_score = score_sea_ice_record(
                        record.extent_million_km2,
                        record.previous_extent,
                        record.previous_year,
                    )
                source_promoted = 1 if sea_ice_score and record and _should_draft(sea_ice_score, record.event_id) else 0
                source_drafted = 0
                if record and source_promoted:
                    review_context = _review_context(
                        source="NSIDC",
                        source_key=f"sea_ice_{hemisphere.lower()}",
                        headline=f"{record.hemisphere} sea ice record low",
                        current_run=current_run,
                        facts=[
                            _fact("Current extent", f"{record.extent_million_km2:.2f} million sq km"),
                            _fact("Previous record", f"{record.previous_extent:.2f} million sq km"),
                            _fact("Previous record year", record.previous_year),
                        ],
                    )
                    from src.two_bot.intern import build_sea_ice_bundle
                    si_bundle = build_sea_ice_bundle(record)
                    if _try_two_bot_draft(
                        si_bundle, bot_state, sea_ice_score,
                        legacy_type="sea_ice_record",
                        event_id=record.event_id,
                        review_context=review_context,
                    ):
                        state.record_event(bot_state, record.event_id)
                        drafted += 1
                        source_drafted = 1
                observed = len(readings) if hasattr(readings, "__len__") else 0
                _record_source_run(
                    current_run, bot_state, f"sea_ice_{hemisphere.lower()}", sea_ice_start,
                    status="success", observed=observed, promoted=source_promoted, drafted=source_drafted
                )
            except Exception as e:
                print(f"[alerts] Sea ice ({hemisphere}) error: {e}")
                state.log_error(bot_state, f"sea_ice_{hemisphere.lower()}", str(e))
                _record_source_run(
                    current_run, bot_state, f"sea_ice_{hemisphere.lower()}", sea_ice_start,
                    status="failed", error=str(e)
                )
    else:
        for hemisphere in ("Arctic", "Antarctic"):
            skipped_start = time.perf_counter()
            _record_source_run(
                current_run, bot_state, f"sea_ice_{hemisphere.lower()}", skipped_start,
                status="skipped", note="Runs Mondays only"
            )
    return drafted
