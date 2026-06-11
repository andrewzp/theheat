"""Source runner for reanalysis regional-anomaly detection (Part B / "reganom").

Standalone runner (gpm_imerg pattern): loads its data, detects per region, builds
a bundle inline, and enqueues a writer candidate — it is NOT part of the per-city
extreme-signal machinery. Launches env-gated OFF (THEHEAT_REGANOM_ENABLED) and
manual_only, so landing is a zero-change-on-land until an operator backfills +
commits the climatology cache and flips the env var.

Data flow per cycle:
  THEHEAT_REGANOM_ENABLED != 1            -> return
  load_daily_climatology()  cache absent  -> SourceSkipped -> status=skipped
  _reganom_live_cache same-day hit        -> reuse (no API)
                          miss            -> fetch_all_reganom_t2m(all coords)
                                             total failure {} -> status=degraded
  per region (per-region try/except):
    detect_regional_anomaly(...)          -> None -> skip
    window_start <= reganom_last_fired    -> skip (same ongoing spell)   [onset guard]
    is_duplicate(event_id)                -> skip
    score < threshold                     -> skip
    set_reganom_last_fired (ATTEMPT TIME) -> suppress same-window retries [§D]
    build_regional_anomaly_bundle + _enqueue_story_candidate (manual_only)
"""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *
from src.two_bot.intern import build_regional_anomaly_bundle


def run_reanalysis_anomaly(bot_state: BotState, current_run: dict | None) -> None:
    if os.environ.get("THEHEAT_REGANOM_ENABLED", "0") != "1":
        return  # env-gated OFF by default — zero-change-on-land

    print("[alerts] Checking reanalysis regional anomaly...")
    start = time.perf_counter()
    source_promoted = 0
    try:
        from src.data.reanalysis_anomaly import (
            REGION_WATCHLIST,
            all_watchlist_coords,
            detect_regional_anomaly,
            fetch_all_reganom_t2m,
            load_daily_climatology,
        )

        clim = load_daily_climatology()  # raises SourceSkipped if the cache is absent

        today = date.today().isoformat()
        state_dict = cast(dict, bot_state)
        cache = state_dict.get("_reganom_live_cache", {})
        if not (isinstance(cache, dict) and cache.get("date") == today and cache.get("results")):
            batch = fetch_all_reganom_t2m(all_watchlist_coords())
            if not batch:  # total failure -> degraded, no crash
                _record_source_run(
                    current_run, bot_state, "reanalysis_anomaly", start, status="degraded"
                )
                return
            state_dict["_reganom_live_cache"] = {
                "date": today,
                "results": {f"{la},{lo}": v for (la, lo), v in batch.items() if v is not None},
            }
            cache = state_dict["_reganom_live_cache"]

        results = cache["results"]
        last_fired = state_dict.get("reganom_last_fired", {})
        for region in REGION_WATCHLIST:
            try:
                live = {(la, lo): results.get(f"{la},{lo}") for (la, lo) in region.points}
                ev = detect_regional_anomaly(region, clim, live)
                if ev is None:
                    continue
                # Onset guard: a still-ongoing spell (window_start not newer than the
                # last attempt) must not re-enter the pipeline.
                if ev.window_start <= last_fired.get(ev.region_slug, ""):
                    continue
                if state.is_duplicate(bot_state, ev.event_id):
                    continue
                score = score_regional_anomaly(
                    ev.mean_anomaly_c, ev.sustained_days, ev.cities_sampled
                )
                if not _should_draft(score, ev.event_id):
                    continue

                source_promoted += 1
                # §D: write the suppression marker at ATTEMPT time, before the writer
                # runs, so writer / safety / honesty-gate / fact-check / triage kills
                # still suppress same-window retries (no repeated LLM spend).
                state.set_reganom_last_fired(bot_state, ev.region_slug, ev.window_start)

                review_context = _review_context(
                    source="ERA5 reanalysis (Open-Meteo archive) sampled-city daily anomaly",
                    source_key="reanalysis_anomaly",
                    headline=(
                        f"{ev.region}: {ev.cities_sampled} sampled cities "
                        f"{ev.mean_anomaly_c:+.1f}°C above daily normal, {ev.sustained_days}d"
                    ),
                    current_run=current_run,
                    facts=[
                        _fact("Region", ev.region),
                        _fact("Sampled cities", str(ev.cities_sampled)),
                        _fact(
                            "Mean anomaly",
                            f"{ev.mean_anomaly_c:+.1f}°C above 1991-2020 daily normal",
                        ),
                        _fact("Mean z-score", f"{ev.mean_zscore:.1f}"),
                        _fact("Sustained", f"{ev.sustained_days} consecutive days"),
                        _fact(
                            "Signal type",
                            "Point index over N sampled cities; NOT an area-weighted national mean",
                        ),
                    ],
                )
                bundle = build_regional_anomaly_bundle(ev)
                _enqueue_story_candidate(
                    bot_state,
                    bundle=bundle,
                    score=score,
                    source="reanalysis_anomaly",
                    legacy_type="regional_anomaly",
                    event_id=ev.event_id,
                    review_context=review_context,
                    city="",
                    tweet_date=ev.window_end,
                    cooldown_exempt=True,
                )
            except Exception as ce:  # noqa: BLE001 - one region's gap must not abort the rest
                print(f"[alerts] reganom {region.name} skipped: {ce}")

        _record_source_run(
            current_run,
            bot_state,
            "reanalysis_anomaly",
            start,
            status="success",
            promoted=source_promoted,
            drafted=0,
        )
    except SourceSkipped as exc:
        _record_source_run(
            current_run, bot_state, "reanalysis_anomaly", start, status="skipped", note=str(exc)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[alerts] reanalysis_anomaly error: {exc}")
        state.log_error(bot_state, "reanalysis_anomaly", str(exc))
        _record_source_run(
            current_run, bot_state, "reanalysis_anomaly", start, status="failed", error=str(exc)
        )
    return
