"""Source runner for NASA FIRMS wildfire alerts."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data._witness import degraded_via
from src.orchestrator.common import *


def run_firms(bot_state: BotState, current_run: dict | None) -> None:
    # 2. Wildfire alerts via NASA FIRMS
    print("[alerts] Checking wildfires...")
    firms_start = time.perf_counter()
    try:
        fires = _fetch_strict(firms.fetch_fires)
        source_promoted = 0
        # Bet A A2 (default OFF): a sourced newsworthiness match can rescue a
        # NEAR-miss before the gate — the Congo-vs-Colorado fix. The plan is
        # computed over the WHOLE batch first so a nameless news event that
        # matches several same-state fires rescues NONE of them (identity
        # ambiguity — same rule as A1's enrich matcher). A planner error
        # degrades to no boosts; it must never kill the cycle.
        from src.editorial import newsworthiness as _news

        boost_plan: dict[str, dict] = {}
        if _news.news_boost_enabled():
            try:
                today_iso = date.today().isoformat()
                boost_plan = _news.plan_fire_boosts(
                    bot_state.get("news_events"),
                    [
                        {
                            "id": f.event_id, "country": f.country,
                            "when": today_iso, "lat": f.lat, "lon": f.lon,
                        }
                        for f in fires
                    ],
                )
            except Exception as boost_exc:  # noqa: BLE001
                print(f"[news_boost] firms boost planning error (continuing): {boost_exc!r}")
        for fire in fires:
            if state.is_duplicate(bot_state, fire.event_id):
                continue
            score = score_fire_event(fire.confidence, fire.frp, region=fire.nearest_city)
            # Applied between score construction and the passes check so a
            # rescued (or still-failing boosted) score reaches the suppression
            # ledger with its news_boost provenance visible.
            matched_news = boost_plan.get(fire.event_id)
            if matched_news is not None:
                try:
                    score = _news.apply_newsworthiness_boost(score, matched_news)
                except Exception as boost_exc:  # noqa: BLE001
                    print(f"[news_boost] firms boost error (continuing): {boost_exc!r}")
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
            from src.two_bot.intern import build_fire_bundle

            fire_bundle = build_fire_bundle(fire)
            _enqueue_story_candidate(
                bot_state,
                bundle=fire_bundle,
                score=score,
                source="firms",
                legacy_type="fire",
                event_id=fire.event_id,
                review_context=review_context,
            )
        # R-01/R-02: if the NOAA HMS witness served (primary FIRMS down), record
        # `degraded` with "served via <leg>" so the sentinel + dashboard show the
        # primary is down even while backup drafts still flow. A healthy primary
        # leaves source_leg unset -> success.
        served = degraded_via(fires)
        _record_source_run(
            current_run, bot_state, "firms", firms_start,
            status="degraded" if served else "success",
            observed=len(fires), promoted=source_promoted, drafted=0,
            note=served,
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
    return
