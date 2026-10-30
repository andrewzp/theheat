"""Hot 10 leaderboard mode."""

from __future__ import annotations

# ruff: noqa: F403,F405
from src.data import twitter_metrics
from src.data.metric_history import PUBLIC_FIELDS, append_sample
from src.orchestrator.common import *


_METRICS_SOURCE = "twitter_metrics"
_METRICS_LOOKBACK_DAYS = 30
_METRICS_MAX_IDS = 50


def _compact_hot10_rows(hot10: list[dict]) -> list[dict]:
    rows = []
    for rank, row in enumerate(hot10[:10], start=1):
        rows.append({
            "rank": rank,
            "city": row["city"],
            "country": row["country"],
            "anomaly_c": round(float(row["anomaly_c"]), 1),
            "temp_high_c": round(float(row["temp_high_c"]), 1),
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
        if not tweet_id or sampled is None or sampled < cutoff or sampled > now:
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
        add(draft.get("tweet_id"), draft.get("posted_at"))

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

    returned = {tweet_id: row for tweet_id, row in metrics.items()
                if tweet_id in tweet_ids and isinstance(row, dict)}
    sample_time = now or _utc_now()  # Client observation after the lookup returned.
    table = bot_state.setdefault("tweet_metrics", {})
    usable = 0
    for tweet_id, row in returned.items():
        table[str(tweet_id)] = append_sample(
            table.get(str(tweet_id)), tweet_id=str(tweet_id), counts=row,
            sampled_at=sample_time, state=bot_state,
        )
        if any(type(value) is int and 0 <= value <= 2**53 - 1
               for key, value in row.items() if key in PUBLIC_FIELDS):
            usable += 1

    missing = len(tweet_ids) - usable
    _record_source_run(
        current_run, bot_state, _METRICS_SOURCE, metrics_start,
        status="partial_failure" if missing else "success", observed=len(tweet_ids), promoted=usable,
        note=f"Stored {len(returned)} metric sample(s); {missing} requested post(s) without usable counts",
        error=f"No usable metric counts returned for {missing} requested post(s)" if missing else None,
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

        from src.editorial import hot10_contract
        qualified = hot10_contract.qualify(temps, normals, sampled=len(cities), now=_utc_now())
        universe = qualified["universe"]
        if not qualified["complete"]:
            # Ten unique qualified places or no bulletin: never pad, substitute or estimate.
            print(f"[leaderboard] Hot 10 held: {universe['qualified_cities']} qualified of {len(temps)} returned")
            _record_source_run(
                current_run, bot_state, "leaderboard", leaderboard_start,
                status="degraded", observed=len(temps), promoted=0, drafted=0,
                note=(f"hot10_short_slate: {universe['qualified_cities']} of {hot10_contract.SIZE} required "
                      f"qualified locations; excluded {universe['excluded']}"),
            )
            _run_twitter_metrics(bot_state, current_run)
            return bot_state
        rows = qualified["rows"]

        prev_cities = bot_state.get("last_hot10", {}).get("place_ids", [])
        changes = []
        for i, row in enumerate(rows):
            if row["place_id"] in prev_cities:
                old_pos = prev_cities.index(row["place_id"]) + 1
                new_pos = i + 1
                if old_pos != new_pos:
                    direction = "UP" if new_pos < old_pos else "DOWN"
                    changes.append(f"{row['city']} {direction} {abs(old_pos - new_pos)} spots")
            else:
                changes.append(f"{row['city']} NEW to the Hot 10")

        top_anomaly = rows[0]["anomaly_c"]
        score = score_hot10(top_anomaly, len(rows), len(changes))

        event_id = f"hot10_{_utc_now().date().isoformat()}"
        # One daily bulletin: an already drafted or published day never buys another writer call.
        from types import SimpleNamespace
        from src.orchestrator.draft_save import can_draft_candidate
        daily_open, daily_reason = can_draft_candidate(bot_state, SimpleNamespace(event_id=event_id))
        if not daily_open:
            print(f"[leaderboard] Hot 10 {event_id} not redrafted: {daily_reason}")
        if daily_open and _should_draft(score, event_id):
            leader = rows[0]
            review_context = _review_context(
                source="Open-Meteo forecast + Meteostat point normals",
                source_key="leaderboard",
                headline="Daily Hot 10 forecast-anomaly leaderboard",
                current_run=current_run,
                facts=[
                    _fact("Leader", leader["city"]),
                    _fact("Top anomaly", f"+{leader['anomaly_c']:.1f}C"),
                    _fact("Cities ranked", len(rows)),
                    _fact("Qualified universe", f"{universe['qualified_cities']} of {universe['sampled_cities']} sampled"),
                    _fact("Ranking changes", len(changes)),
                ],
            )
            from src.two_bot.intern import build_hot10_bundle
            hot10_bundle = build_hot10_bundle(rows, changes=changes, event_id=event_id, universe=universe)
            _enqueue_story_candidate(
                bot_state,
                bundle=hot10_bundle,
                score=score,
                source="leaderboard",
                legacy_type="hot10",
                event_id=event_id,
                review_context=review_context,
                draft_metadata={"hot10_rows": _compact_hot10_rows(rows)},
            )

        bot_state["last_hot10"] = {
            "date": _utc_now().date().isoformat(),
            "cities": [row["city"] for row in rows],
            "place_ids": [row["place_id"] for row in rows],
        }
        state.update_streaks(bot_state, [row["place_id"] for row in rows])
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="success", observed=len(temps), promoted=len(rows) if score.passes and daily_open else 0,
            drafted=0, note=None if daily_open else f"hot10_daily_event_exists: {daily_reason}",
        )
        # Hot10 is its own operation: one daily candidate, at most one writer attempt.
        from src.orchestrator.candidate_budget import CandidateBudget
        from src.two_bot.call_inventory import operation_cost_row, operation_scope, record_operation_cost
        leaderboard_budget = CandidateBudget.for_operation("leaderboard")
        with operation_scope("leaderboard") as cost_join:
            try:
                _drain_and_write_triage_queue(bot_state, current_run, candidate_budget=leaderboard_budget)
            finally:
                record_operation_cost(current_run, operation_cost_row(
                    "leaderboard", join=cost_join, candidate_budget=leaderboard_budget))
        _run_twitter_metrics(bot_state, current_run)

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="failed", error=str(e)
        )

    return bot_state
