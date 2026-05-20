"""Hot 10 leaderboard mode."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.orchestrator.common import *


def run_leaderboard(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Generate the daily Hot 10 leaderboard as a draft."""
    _activate_suppression_ctx(
        bot_state,
        source="leaderboard",
        run_id=(current_run or {}).get("id"),
    )
    print("[leaderboard] Generating Hot 10...")
    leaderboard_start = time.perf_counter()
    try:
        cast(dict, bot_state).pop("_triage_queue", None)
        cities = open_meteo.load_cities()
        normals = open_meteo.load_normals()
        temps = open_meteo.fetch_all_city_temps(cities)

        if not temps:
            print("[leaderboard] No temperature data available")
            _record_source_run(
                current_run, bot_state, "leaderboard", leaderboard_start,
                status="success", observed=0, promoted=0, drafted=0, note="No temperature data available"
            )
            return bot_state

        temps_with_anomalies = open_meteo.compute_anomalies(temps, normals)
        hot10 = open_meteo.rank_hot10(temps_with_anomalies)

        if not hot10:
            print("[leaderboard] No valid anomalies to rank")
            _record_source_run(
                current_run, bot_state, "leaderboard", leaderboard_start,
                status="success", observed=len(temps), promoted=0, drafted=0, note="No valid anomalies to rank"
            )
            return bot_state

        prev_cities = bot_state.get("last_hot10", {}).get("cities", [])
        changes = []
        for i, ct in enumerate(hot10):
            if ct.city in prev_cities:
                old_pos = prev_cities.index(ct.city) + 1
                new_pos = i + 1
                if old_pos != new_pos:
                    direction = "UP" if new_pos < old_pos else "DOWN"
                    changes.append(f"{ct.city} {direction} {abs(old_pos - new_pos)} spots")
            else:
                changes.append(f"{ct.city} NEW to the Hot 10")

        top_anomaly = (hot10[0].anomaly_c or 0.0) if hot10 else 0.0
        score = score_hot10(top_anomaly, len(hot10), len(changes))

        event_id = f"hot10_{date.today().isoformat()}"
        if _should_draft(score, event_id):
            leader = hot10[0] if hot10 else None
            review_context = _review_context(
                source="Open-Meteo + normals",
                source_key="leaderboard",
                headline="Daily Hot 10 anomaly leaderboard",
                current_run=current_run,
                facts=[
                    _fact("Leader", leader.city if leader else None),
                    _fact("Top anomaly", f"+{leader.anomaly_c:.1f}C" if leader else None),
                    _fact("Cities ranked", len(hot10)),
                    _fact("Ranking changes", len(changes)),
                ],
            )
            from src.two_bot.intern import build_hot10_bundle
            hot10_dicts = [
                {
                    "city": ct.city,
                    "country": ct.country,
                    "temp_high_c": ct.temp_high_c,
                    "normal_high_c": ct.normal_high_c,
                    "anomaly_c": ct.anomaly_c,
                }
                for ct in hot10
            ]
            hot10_bundle = build_hot10_bundle(
                hot10_dicts, changes=changes, event_id=event_id,
            )
            _enqueue_story_candidate(
                bot_state,
                bundle=hot10_bundle,
                score=score,
                source="leaderboard",
                legacy_type="hot10",
                event_id=event_id,
                review_context=review_context,
            )

        bot_state["last_hot10"] = {
            "date": date.today().isoformat(),
            "cities": [ct.city for ct in hot10],
        }
        state.update_streaks(bot_state, [ct.city for ct in hot10])
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="success", observed=len(temps), promoted=len(hot10) if score.passes else 0, drafted=0
        )
        _drain_and_write_triage_queue(bot_state, current_run)

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="failed", error=str(e)
        )

    return bot_state
