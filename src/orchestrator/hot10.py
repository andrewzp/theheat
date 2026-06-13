"""Hot 10 leaderboard mode."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data import twitter_metrics
from src.orchestrator.common import *


_METRICS_SOURCE = "twitter_metrics"
_METRICS_LOOKBACK_DAYS = 30
_METRICS_MAX_IDS = 50


def _compact_hot10_rows(hot10) -> list[dict]:
    rows = []
    for rank, ct in enumerate(hot10[:10], start=1):
        rows.append({
            "rank": rank,
            "city": ct.city,
            "country": ct.country,
            "anomaly_c": round(float(ct.anomaly_c or 0.0), 1),
            "temp_high_c": round(float(ct.temp_high_c), 1),
        })
    return rows


def _metrics_enabled() -> bool:
    return os.environ.get("THEHEAT_METRICS_ENABLED", "0") == "1"


def _metric_source_seen_today(bot_state: BotState, now: datetime) -> bool:
    today = now.date()
    for run in bot_state.get("run_history", []):
        run_at = _parse_iso_utc(run.get("started_at") or run.get("ended_at"))
        if run_at is None or run_at.date() != today:
            continue
        for source in run.get("sources", []):
            if source.get("source") == _METRICS_SOURCE:
                return True
    return False


def _metric_candidate_tweet_ids(bot_state: BotState, now: datetime) -> list[str]:
    cutoff = now - timedelta(days=_METRICS_LOOKBACK_DAYS)
    candidates: list[tuple[datetime, str]] = []

    def add(tweet_id, sampled_at) -> None:
        tweet_id = str(tweet_id or "").strip()
        sampled = _parse_iso_utc(str(sampled_at or ""))
        if not tweet_id or sampled is None or sampled < cutoff:
            return
        candidates.append((sampled, tweet_id))

    publish_ledger = bot_state.get("publish_ledger", {})
    if isinstance(publish_ledger, dict):
        for row in publish_ledger.values():
            if isinstance(row, dict):
                add(row.get("tweet_id"), row.get("at"))

    for draft in bot_state.get("drafts", []):
        if not isinstance(draft, dict):
            continue
        add(draft.get("tweet_id"), draft.get("posted_at") or draft.get("last_publish_attempt_at"))

    candidates.sort(key=lambda item: item[0], reverse=True)
    ids: list[str] = []
    seen = set()
    for _sampled, tweet_id in candidates:
        if tweet_id in seen:
            continue
        seen.add(tweet_id)
        ids.append(tweet_id)
        if len(ids) >= _METRICS_MAX_IDS:
            break
    return ids


def _run_twitter_metrics(
    bot_state: BotState,
    current_run: dict | None = None,
    *,
    now: datetime | None = None,
) -> None:
    if not _metrics_enabled():
        return

    metrics_start = time.perf_counter()
    sample_time = now or _utc_now()

    if _metric_source_seen_today(bot_state, sample_time):
        _record_source_run(
            current_run, bot_state, _METRICS_SOURCE, metrics_start,
            status="skipped", note="Metrics already polled today"
        )
        return

    tweet_ids = _metric_candidate_tweet_ids(bot_state, sample_time)
    if not tweet_ids:
        _record_source_run(
            current_run, bot_state, _METRICS_SOURCE, metrics_start,
            status="skipped", note="No recent tweet ids to poll"
        )
        return

    if not twitter_metrics.credentials_available():
        _record_source_run(
            current_run, bot_state, _METRICS_SOURCE, metrics_start,
            status="skipped", observed=len(tweet_ids),
            note="No Twitter credentials configured"
        )
        return

    try:
        metrics = twitter_metrics.fetch_metrics(tweet_ids)
    except Exception as exc:
        _record_source_run(
            current_run, bot_state, _METRICS_SOURCE, metrics_start,
            status="failed", observed=len(tweet_ids), error=str(exc)
        )
        return

    sampled_at = sample_time.isoformat().replace("+00:00", "Z")
    table = bot_state.setdefault("tweet_metrics", {})
    for tweet_id, row in metrics.items():
        table[str(tweet_id)] = {
            "at": sampled_at,
            "likes": int(row.get("likes", 0)),
            "retweets": int(row.get("retweets", 0)),
            "replies": int(row.get("replies", 0)),
        }

    _record_source_run(
        current_run, bot_state, _METRICS_SOURCE, metrics_start,
        status="success", observed=len(tweet_ids), promoted=len(metrics),
        note=f"Stored {len(metrics)} metric row(s)"
    )


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
            _run_twitter_metrics(bot_state, current_run)
            return bot_state

        temps_with_anomalies = open_meteo.compute_anomalies(temps, normals)
        hot10 = open_meteo.rank_hot10(temps_with_anomalies)

        if not hot10:
            print("[leaderboard] No valid anomalies to rank")
            _record_source_run(
                current_run, bot_state, "leaderboard", leaderboard_start,
                status="success", observed=len(temps), promoted=0, drafted=0, note="No valid anomalies to rank"
            )
            _run_twitter_metrics(bot_state, current_run)
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
            hot10_rows = _compact_hot10_rows(hot10)
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
                draft_metadata={"hot10_rows": hot10_rows},
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
        _run_twitter_metrics(bot_state, current_run)

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="failed", error=str(e)
        )

    return bot_state
