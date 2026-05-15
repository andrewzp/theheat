"""@theheat bot orchestrator.

All generated tweets go to drafts in the shared state store.
Low-sensitivity drafts (Hot 10, CO2, official confirmations) may
auto-post after a timed delay if both signal and copy scores are
strong. Human-impact events (fires, disasters, floods, severe
weather) always require manual approval via the dashboard.
"""

import argparse
import contextlib
import os
import secrets
import sys
import time
from typing import Any, cast
from datetime import UTC, date, datetime, timedelta

from src import state
from src.data import open_meteo, ghcn, firms, fire_footprint, co2, nws_alerts, gdacs, sea_ice, drought, enso, ocean, ocean_sst, water_levels, river_gauges, ice_mass
from src.data.open_meteo import AllTimeRecord, AnomalyEvent, MonthlyRecord, RecordEvent
from src.state_schema import BotState
from src.data.source_status import SourceSkipped
from src.editorial import synthesis
from src.editorial.approval import recommend_approval_policy
from src.editorial.candidates import CandidateBundle
from src.editorial._regions import cities_to_state_map, lat_lon_to_state
from src.editorial.simultaneous_format import select_roll_call_subset
from src.editorial.scoring import (
    EditorialScore,
    score_all_time_record,
    score_anomaly,
    score_co2_milestone,
    score_drought,
    score_enso_transition,
    score_extreme_wave,
    score_marine_heatwave,
    score_fire_event,
    score_fire_footprint,
    score_global_disaster,
    score_hot10,
    score_monthly_record,
    score_country_record,
    score_record_event,
    score_record_low_event,
    score_record_streak,
    score_river_flood,
    score_sea_ice_record,
    score_ice_mass_event,
    score_severe_weather,
    score_simultaneous_records,
    score_storm_surge,
    score_synthesis_fire_drought_heat,
)
from src.voice import generator  # noqa: F401 — referenced via @patch("src.main.generator") in tests
from src.voice.safety import run_safety_pipeline
from src.posting.bluesky import post_to_bluesky
from src.posting.twitter import post_tweet


MAX_DRAFTS = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _utc_after_minutes_iso(minutes: int) -> str:
    return (_utc_now() + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO timestamp with optional Z suffix."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_draft(bot_state: BotState, draft_id: str = "", tweet_text: str = "") -> dict | None:
    """Find a draft by explicit id first, then by approved tweet text fallback."""
    drafts = bot_state.get("drafts", [])
    if draft_id:
        for draft in drafts:
            if draft.get("id") == draft_id:
                return draft

    for draft in drafts:
        if draft.get("text") == tweet_text and draft.get("status") == "approved":
            return draft
    return None


def _record_source_run(
    current_run: dict | None,
    bot_state: BotState | None,
    source: str,
    started_at: float,
    *,
    status: str,
    observed: int = 0,
    promoted: int = 0,
    drafted: int = 0,
    error: str | None = None,
    note: str | None = None,
    details: dict | None = None,
) -> None:
    """Track a source result when run telemetry is enabled."""
    if bot_state is not None:
        health_error = error
        if not health_error and status in {"failed", "degraded", "partial_failure"}:
            health_error = note
        state.record_source_health(bot_state, source, status, health_error)

    if current_run is None:
        return

    duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
    state.add_source_run(
        current_run,
        source=source,
        status=status,
        duration_ms=duration_ms,
        observed=observed,
        promoted=promoted,
        drafted=drafted,
        error=error,
        note=note,
        details=details,
    )


def _previous_drafts_for_event(bot_state: BotState, event_base: str) -> list[str]:
    """Find text of previous drafts for the same base event.

    For evolving events (e.g. cyclones), the event_id changes with each
    intensity tier but shares a common base like "gdacs_TC_1001270".
    Returns up to 5 most recent draft texts to avoid repeating comparisons.
    """
    drafts = bot_state.get("drafts", [])
    matches = []
    for d in drafts:
        eid = d.get("event_id", "")
        if event_base and event_base in eid:
            text = d.get("text", "")
            if text:
                matches.append(text)
    return matches[-5:]


# ---------------------------------------------------------------------------
# Suppression capture: when _should_draft() returns False, optionally persist
# a record of *what* almost-shipped and *why* it got cut. Lets the dashboard
# surface the "near-miss" distribution so the editorial bar can be tuned with
# evidence rather than vibes.
#
# Activated by wrapping a source loop in `with _suppression_context(bot_state,
# source="..."):`. Only suppressions where the score gap is within the
# near-miss window (env var SUPPRESSION_NEAR_MISS_GAP, default 15) are kept,
# to prevent the ledger from flooding with obvious noise.
# ---------------------------------------------------------------------------

_CURRENT_SUPPRESSION_CTX: dict | None = None


def _near_miss_gap() -> int:
    """Max (threshold - total) gap to record. Smaller = stricter."""
    try:
        return int(os.environ.get("SUPPRESSION_NEAR_MISS_GAP", "15"))
    except (TypeError, ValueError):
        return 15


@contextlib.contextmanager
def _suppression_context(bot_state: BotState, *, source: str, run_id: str | None = None):
    """Activate suppression capture for `_should_draft()` calls inside the block."""
    global _CURRENT_SUPPRESSION_CTX
    prev = _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = {"bot_state": bot_state, "source": source, "run_id": run_id}
    try:
        yield
    finally:
        _CURRENT_SUPPRESSION_CTX = prev


def _activate_suppression_ctx(bot_state: BotState, *, source: str, run_id: str | None = None) -> None:
    """Set the suppression context for the rest of the process.

    Used at the top of each top-level run function (run_alerts, run_leaderboard,
    etc.) so all `_should_draft()` calls during the run capture suppressions.
    No auto-cleanup — relies on the bot exiting after each invocation. Tests
    should call `_clear_suppression_ctx()` between cases.
    """
    global _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = {"bot_state": bot_state, "source": source, "run_id": run_id}


def _clear_suppression_ctx() -> None:
    """Clear the current suppression context. Mainly for tests."""
    global _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = None


def _score_field(score, key: str, default=None):
    if isinstance(score, dict):
        return score.get(key, default)
    return getattr(score, key, default)


def _score_int(score, key: str) -> int:
    try:
        return int(_score_field(score, key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _score_reasons(score) -> list[str]:
    raw = _score_field(score, "reasons", []) or []
    if not isinstance(raw, list):
        return [str(raw)]
    return [str(item) for item in raw]


def _record_suppression(
    *,
    bot_state: BotState,
    source: str | None,
    run_id: str | None,
    event_id: str,
    score: EditorialScore,
    summary: str | None,
) -> None:
    """Append an editorial-gate near-miss suppression record (stage=score_gate),
    capped to last 200.
    """
    suppressions = bot_state.setdefault("suppressions", [])
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    suppressions.append({
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "stage": "score_gate",
        "event_id": event_id or None,
        "category": _score_field(score, "category"),
        "score_total": _score_int(score, "total"),
        "threshold": _score_int(score, "threshold"),
        "reasons": _score_reasons(score),
        "summary": summary,
    })
    if len(suppressions) > 200:
        bot_state["suppressions"] = suppressions[-200:]


def _record_downstream_suppression(
    *,
    bot_state: BotState,
    source: str | None,
    run_id: str | None,
    event_id: str,
    score,
    kill_stage: str,
    kill_reason: str,
    summary: str | None,
) -> None:
    """Append a downstream-kill suppression — a bundle that passed the
    editorial score gate but died in the two-bot pipeline (writer kill,
    fact-check rejection, or pipeline exception). Stage discriminates
    from score-gate near-misses; ``score_total`` is preserved so the
    dashboard can show "passing score 80, killed in writer".
    """
    suppressions = bot_state.setdefault("suppressions", [])
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    suppressions.append({
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "stage": kill_stage,  # "writer" | "fact_check" | "pipeline_error" | "unknown"
        "event_id": event_id or None,
        "category": _score_field(score, "category"),
        "score_total": _score_int(score, "total"),
        "threshold": _score_int(score, "threshold"),
        "reasons": [kill_reason] if kill_reason else [],
        "summary": summary,
    })
    if len(suppressions) > 200:
        bot_state["suppressions"] = suppressions[-200:]


def _record_save_rejection(
    *,
    bot_state: BotState,
    event_id: str,
    score,
    kill_stage: str,
    kill_reason: str,
    summary: str | None,
) -> None:
    """Record a post-score draft-save gate as a suppression row."""
    if score is None:
        return
    ctx = _CURRENT_SUPPRESSION_CTX
    if ctx is None:
        return
    _record_downstream_suppression(
        bot_state=bot_state,
        source=ctx.get("source"),
        run_id=ctx.get("run_id"),
        event_id=event_id,
        score=score,
        kill_stage=kill_stage,
        kill_reason=kill_reason,
        summary=summary,
    )


def _should_draft(
    score: EditorialScore,
    event_id: str = "",
    *,
    summary: str | None = None,
) -> bool:
    """Decide whether an event is strong enough to enter the draft queue."""
    if score.passes:
        return True
    event_desc = f" {event_id}" if event_id else ""
    print(
        f"[score] Suppressed{event_desc}: {score.category} "
        f"{score.total} < {score.threshold} ({', '.join(score.reasons)})"
    )
    ctx = _CURRENT_SUPPRESSION_CTX
    if ctx is not None:
        gap = int(getattr(score, "threshold", 0) or 0) - int(getattr(score, "total", 0) or 0)
        if gap <= _near_miss_gap():
            _record_suppression(
                bot_state=ctx["bot_state"],
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=event_id,
                score=score,
                summary=summary,
            )
    return False


def _unwrap_generated_result(
    generated: str | CandidateBundle | object | None,
) -> tuple[str, list[dict] | None, dict | None, dict | None]:
    if generated is None:
        return "", None, None, None

    if isinstance(generated, str):
        return generated, None, None, None

    if isinstance(generated, CandidateBundle):
        candidates = [candidate.as_dict() for candidate in generated.candidates]
        selected_score = generated.selected_score.as_dict() if generated.selected_score else None
        evaluator_metadata = _evaluator_metadata_from_bundle(generated)
        return generated.text, candidates, selected_score, evaluator_metadata

    text = getattr(generated, "text", "") if isinstance(getattr(generated, "text", ""), str) else ""
    raw_candidates: Any = getattr(generated, "candidates", None)
    raw_selected_score: Any = getattr(generated, "selected_score", None)
    evaluator_metadata = _evaluator_metadata_from_bundle(generated)

    candidate_payload: list[dict] | None = None
    if raw_candidates:
        candidate_payload = []
        for candidate in raw_candidates:
            if hasattr(candidate, "as_dict"):
                candidate_payload.append(candidate.as_dict())
            elif isinstance(candidate, dict):
                candidate_payload.append(candidate)

    selected_payload = (
        raw_selected_score.as_dict() if hasattr(raw_selected_score, "as_dict") else raw_selected_score
    )
    return text, candidate_payload, selected_payload, evaluator_metadata


def _evaluator_metadata_from_bundle(generated: object) -> dict | None:
    verdict = getattr(generated, "evaluator_verdict", None)
    if not isinstance(verdict, dict):
        return None

    scores = verdict.get("scores") if isinstance(verdict.get("scores"), dict) else {}
    failures_raw = verdict.get("failures")
    failures = [str(item) for item in failures_raw] if isinstance(failures_raw, list) else []
    skipped = verdict.get("reasoning") == "evaluator skipped"
    # Null means the evaluator did not actually run; True/False means it returned a verdict.
    evaluator_pass = None if skipped else bool(verdict.get("passed"))

    return {
        "evaluator_pass": evaluator_pass,
        "evaluator_total": int(verdict.get("total") or 0),
        "evaluator_scores": scores,
        "evaluator_failures": failures,
        "evaluator_used_rewrite": bool(getattr(generated, "evaluator_used_rewrite", False)),
    }


def _fact(label: str, value: str | int | float | None) -> dict | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return {"label": label, "value": text}


def _fetch_strict(fetch_fn, *args, **kwargs):
    """Call a source fetch helper in strict mode, with old test-double fallback."""
    try:
        return fetch_fn(*args, strict=True, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument 'strict'" not in str(exc):
            raise
        return fetch_fn(*args, **kwargs)


def _check_city_extreme_signals(cities: list[dict], metrics_out: dict):
    """Call Open-Meteo city signal scan with metrics, tolerating old test doubles."""
    try:
        return open_meteo.check_extreme_signals_for_cities(
            cities,
            metrics_out=metrics_out,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'metrics_out'" not in str(exc):
            raise
        return open_meteo.check_extreme_signals_for_cities(cities)


def _classify_ghcn_source_status(
    pipeline_metrics: dict,
    *,
    today: date | None = None,
) -> str:
    """Classify GHCN source health while tolerating normal newest-diff lag."""
    diff_missing = int(pipeline_metrics.get("diff_dates_missing", 0) or 0)
    if diff_missing <= 0:
        return "success"

    diff_fetched = int(pipeline_metrics.get("diff_dates_fetched", 0) or 0)
    if diff_fetched <= 0:
        return "degraded"

    missing_dates = pipeline_metrics.get("diff_missing_dates")
    if not isinstance(missing_dates, list) or len(missing_dates) != diff_missing:
        return "degraded"

    current_date = today or date.today()
    tolerated_missing_dates = {current_date - timedelta(days=1)}
    try:
        parsed_missing = {date.fromisoformat(str(raw)) for raw in missing_dates}
    except ValueError:
        return "degraded"

    if parsed_missing.issubset(tolerated_missing_dates):
        return "success"
    return "degraded"


def _temp_pair_c(temp_c: float) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    return f"{temp_c:.1f}C / {temp_f:.1f}F"


def _review_context(
    *,
    source: str,
    source_key: str,
    headline: str,
    facts: list[dict | None],
    current_run: dict | None = None,
) -> dict:
    return {
        "source": source,
        "source_key": source_key,
        "headline": headline,
        "facts": [fact for fact in facts if fact],
        "run_id": current_run.get("id") if current_run else None,
        "run_mode": current_run.get("mode") if current_run else None,
        "run_started_at": current_run.get("started_at") if current_run else None,
    }


def _touch_draft(draft: dict) -> None:
    draft["updated_at"] = _utc_now_iso()


CITY_COOLDOWN_DAYS = 3
ELITE_COPY_SCORE = 95
CO2_ANNUAL_CAP = 12


def _co2_annual_cap_reached(bot_state: BotState, cap: int = CO2_ANNUAL_CAP) -> bool:
    """True if we've already drafted CO2_ANNUAL_CAP CO2 tweets this calendar year."""
    year_key = str(date.today().year)
    count = bot_state.get("co2_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[co2] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False


def _increment_co2_annual_count(bot_state: BotState) -> None:
    year_key = str(date.today().year)
    counts = bot_state.setdefault("co2_annual_count", {})
    counts[year_key] = counts.get(year_key, 0) + 1


ICE_ANNUAL_CAP = 8


def _ice_annual_cap_reached(bot_state: BotState, cap: int = ICE_ANNUAL_CAP) -> bool:
    """True if we've already drafted ICE_ANNUAL_CAP ice-mass tweets this year."""
    year_key = str(date.today().year)
    count = bot_state.get("ice_annual_count", {}).get(year_key, 0)
    if count >= cap:
        print(f"[ice_mass] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False


def _increment_ice_annual_count(bot_state: BotState) -> None:
    year_key = str(date.today().year)
    counts = bot_state.setdefault("ice_annual_count", {})
    counts[year_key] = counts.get(year_key, 0) + 1


def _same_day_already_posted(drafts: list[dict], city: str, tweet_date: str) -> bool:
    """True if a posted draft exists for this (city, tweet_date) tuple."""
    if not city or not tweet_date:
        return False
    for d in drafts:
        if (
            d.get("city") == city
            and d.get("tweet_date") == tweet_date
            and d.get("status") == "posted"
        ):
            return True
    return False


def _same_day_pending_collision(
    drafts: list[dict], city: str, tweet_date: str
) -> tuple[int, dict] | None:
    """Return (index, draft) of a pending draft matching (city, tweet_date), if any."""
    if not city or not tweet_date:
        return None
    for i, d in enumerate(drafts):
        if (
            d.get("city") == city
            and d.get("tweet_date") == tweet_date
            and d.get("status") == "pending"
        ):
            return i, d
    return None


def _posted_city_within_days(drafts: list[dict], city: str, days: int) -> bool:
    """True if any posted draft for this city exists within the last N days."""
    if not city:
        return False
    cutoff = _utc_now() - timedelta(days=days)
    for d in drafts:
        if d.get("city") != city:
            continue
        if d.get("status") != "posted":
            continue
        ts = _parse_iso_utc(
            d.get("posted_at") or d.get("updated_at") or d.get("created_at")
        )
        if ts and ts >= cutoff:
            return True
    return False


def save_draft(
    tweet_text: str,
    bot_state: BotState,
    tweet_type: str,
    event_id: str = "",
    score: EditorialScore | None = None,
    candidates: list[dict] | None = None,
    candidate_score: dict | None = None,
    review_context: dict | None = None,
    evaluator_metadata: dict | None = None,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    """Save a generated tweet as a draft for review.

    When ``city`` and ``tweet_date`` are provided, two extra gates apply:

    * **Same (city, date) dedup.** Only the highest-scoring draft per city
      per day survives. A stronger signal arriving later supersedes a still-
      pending weaker draft; a weaker signal is dropped. If a draft for that
      (city, date) has already been posted, the new one is skipped.

    * **City cooldown.** If the city had a tweet posted within the last
      ``CITY_COOLDOWN_DAYS`` days, new drafts for that city are dropped
      unless ``cooldown_exempt=True`` (elite signals — all-time records,
      extreme anomalies, streaks, NOAA confirmations) OR the copy itself
      is exceptional (``candidate_score.total >= ELITE_COPY_SCORE``).

    These gates are scoped to city-based extreme-temperature signals; other
    event types (fires, disasters, CO2, sea ice, etc.) omit ``city`` and
    pass through unchanged.
    """
    drafts = bot_state.setdefault("drafts", [])

    # Don't duplicate drafts for the same event
    if event_id and any(d.get("event_id") == event_id for d in drafts):
        print(f"[draft] Already drafted: {event_id}")
        _record_save_rejection(
            bot_state=bot_state,
            event_id=event_id,
            score=score,
            kill_stage="duplicate_draft",
            kill_reason="Event already has a draft",
            summary=tweet_text[:120] or event_id,
        )
        return False

    # (city, date) dedup — highest signal wins
    if city and tweet_date:
        if _same_day_already_posted(drafts, city, tweet_date):
            print(f"[draft] Already posted for {city} on {tweet_date}, skipping")
            _record_save_rejection(
                bot_state=bot_state,
                event_id=event_id,
                score=score,
                kill_stage="same_day_posted",
                kill_reason=f"Already posted for {city} on {tweet_date}",
                summary=city,
            )
            return False

        collision = _same_day_pending_collision(drafts, city, tweet_date)
        if collision:
            idx, other = collision
            other_total = (other.get("score") or {}).get("total", 0)
            new_total = score.total if score else 0
            if new_total <= other_total:
                print(
                    f"[draft] Weaker signal for {city} on {tweet_date} "
                    f"({new_total} ≤ {other_total}), skipping"
                )
                _record_save_rejection(
                    bot_state=bot_state,
                    event_id=event_id,
                    score=score,
                    kill_stage="same_day_dedup",
                    kill_reason=(
                        f"Weaker same-day signal for {city} "
                        f"({new_total} <= {other_total})"
                    ),
                    summary=city,
                )
                return False
            _record_save_rejection(
                bot_state=bot_state,
                event_id=other.get("event_id", ""),
                score=other.get("score"),
                kill_stage="same_day_superseded",
                kill_reason=(
                    f"Superseded by stronger same-day signal "
                    f"({new_total} > {other_total})"
                ),
                summary=city,
            )
            drafts.pop(idx)
            print(
                f"[draft] Superseded pending {city} draft "
                f"({other_total} → {new_total})"
            )

    # City cooldown — skip if we posted about this city in the last N days.
    # Exceptional copy (candidate_score.total >= ELITE_COPY_SCORE) bypasses,
    # even if the underlying signal wasn't flagged elite by the caller.
    copy_is_elite = bool(
        candidate_score
        and isinstance(candidate_score, dict)
        and candidate_score.get("total", 0) >= ELITE_COPY_SCORE
    )
    if (
        city
        and not cooldown_exempt
        and not copy_is_elite
        and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS)
    ):
        print(f"[draft] {city} in {CITY_COOLDOWN_DAYS}-day cooldown, skipping")
        _record_save_rejection(
            bot_state=bot_state,
            event_id=event_id,
            score=score,
            kill_stage="city_cooldown",
            kill_reason=f"{city} in {CITY_COOLDOWN_DAYS}-day cooldown",
            summary=city,
        )
        return False

    # Prune oldest non-pending drafts to prevent unbounded growth
    if len(drafts) >= MAX_DRAFTS:
        before = len(drafts)
        bot_state["drafts"] = [
            d for d in drafts if d.get("status") == "pending"
        ][-MAX_DRAFTS:]
        drafts = bot_state["drafts"]
        print(f"[draft] Pruned {before - len(drafts)} old drafts")

    draft: dict[str, Any] = {
        "id": f"draft_{_utc_now().strftime('%Y%m%d_%H%M%S')}_{len(drafts)}",
        "text": tweet_text,
        "type": tweet_type,
        "event_id": event_id,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "status": "pending",
    }
    if city:
        draft["city"] = city
    if tweet_date:
        draft["tweet_date"] = tweet_date
    if score is not None:
        draft["score"] = score.as_dict()
    if candidates:
        draft["candidates"] = candidates
    if candidate_score:
        draft["candidate_score"] = candidate_score
    if review_context:
        draft["review_context"] = review_context
    if evaluator_metadata is not None:
        draft.update(evaluator_metadata)

    policy = recommend_approval_policy(
        tweet_type,
        signal_total=score.total if score is not None else 0,
        candidate_score=candidate_score,
    )
    draft["approval_policy"] = policy.as_dict()
    draft.setdefault("approval_mode", "manual")

    if policy.mode == "armed_auto" and policy.recommended_delay_minutes:
        draft["auto_approve_at"] = _utc_after_minutes_iso(policy.recommended_delay_minutes)
        draft["auto_approve_requested_at"] = _utc_now_iso()
        draft["approval_mode"] = "policy_auto"

    drafts.append(draft)
    print(f"[draft] Saved: {tweet_text[:60]}...")
    return True


def _save_generated_draft(
    generated: str | CandidateBundle | object | None,
    bot_state: BotState,
    tweet_type: str,
    event_id: str,
    score: EditorialScore,
    review_context: dict | None = None,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    tweet_text, candidates, candidate_score, evaluator_metadata = _unwrap_generated_result(generated)
    if not tweet_text:
        return False
    return save_draft(
        tweet_text,
        bot_state,
        tweet_type,
        event_id,
        score=score,
        candidates=candidates,
        candidate_score=candidate_score,
        review_context=review_context,
        evaluator_metadata=evaluator_metadata,
        city=city,
        tweet_date=tweet_date,
        cooldown_exempt=cooldown_exempt,
    )


def _two_bot_bundle_for_extreme_signal(
    strongest_type: str,
    strongest_signal,
    *,
    result_out: dict | None = None,
):
    """Return a StoryBundle for the extreme_signals dispatch loop.

    All extreme_signals types now have bundle builders (full port,
    2026-05-04). Voice generator is no longer reachable from this loop.
    Returns None only if a build raises — in which case the signal is
    silently dropped rather than falling through to voice gen.
    """
    try:
        from src.two_bot import intern

        if strongest_type in ("record", "record_low"):
            return intern.build_record_bundle(strongest_signal)
        if strongest_type in ("monthly_high", "monthly_low"):
            return intern.build_monthly_high_bundle(strongest_signal)
        if strongest_type in ("all_time_high", "all_time_low"):
            return intern.build_all_time_record_bundle(strongest_signal)
        if strongest_type in ("anomaly_hot", "anomaly_cold"):
            return intern.build_anomaly_bundle(strongest_signal)
    except Exception as exc:
        print(f"[two_bot.dispatch] Bundle build failed for {strongest_type}: {exc}")
        if result_out is not None:
            result_out["kill_stage"] = "bundle_build"
            result_out["kill_reason"] = f"{type(exc).__name__}: {exc}"
        return None
    if result_out is not None:
        result_out["kill_stage"] = "bundle_build"
        result_out["kill_reason"] = f"No bundle builder for {strongest_type!r}"
    return None


def _try_two_bot_draft(
    bundle,
    bot_state: BotState,
    score,
    *,
    legacy_type: str,
    event_id: str,
    review_context: dict,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
) -> bool:
    """Run the live two-bot pipeline (writer → claim extract → fact-check
    → memory) and save the draft. Returns True iff a draft was saved.

    Bypasses the voice generator entirely. The cheap-model directive
    (2026-05-03): no Gemini Flash writes the audience-facing text. If
    two-bot returns None, no draft ships for this signal — we do NOT
    fall through to the voice generator.

    ``legacy_type`` is the pre-port signal-type label (e.g. "record",
    "monthly_high", "country_high") used by the dashboard and editorial
    state. The bundle.signal_kind may differ slightly (e.g.
    "calendar_record" vs "record") to give the writer better semantic
    cues, but the saved draft uses the legacy label for compatibility.

    On a None return from the pipeline (writer kill, fact-check rejection,
    or pipeline exception), records a downstream suppression so the
    dashboard surfaces it. These are *post-score* kills, distinct from
    the editorial-gate near-misses captured by ``_should_draft``.
    """
    from src.two_bot.pipeline import generate_draft

    pipeline_result: dict = {}
    draft = generate_draft(bundle, bot_state, result_out=pipeline_result)
    if draft is None:
        ctx = _CURRENT_SUPPRESSION_CTX
        if ctx is not None:
            _record_downstream_suppression(
                bot_state=ctx["bot_state"],
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=event_id,
                score=score,
                kill_stage=pipeline_result.get("kill_stage", "unknown"),
                kill_reason=pipeline_result.get("kill_reason", "unknown"),
                summary=getattr(bundle, "where", None) or city or None,
            )
        return False
    review_context["two_bot"] = draft["two_bot_metadata"]
    return save_draft(
        draft["text"],
        bot_state,
        legacy_type,
        event_id,
        score=score,
        review_context=review_context,
        city=city,
        tweet_date=tweet_date,
        cooldown_exempt=cooldown_exempt,
    )


def _maybe_shadow_two_bot(bundle, bot_state: BotState, review_context: dict) -> None:
    """Run the shadow two-bot pipeline if enabled, attaching results in place.

    Gated by ``THEHEAT_SHADOW_AB_ENABLED=1``. The shadow's tweet text and
    metadata are stored on ``review_context["shadow_two_bot"]``; the live
    voice-generator tweet is unaffected. Never raises.
    """
    if os.environ.get("THEHEAT_SHADOW_AB_ENABLED") != "1":
        return
    if review_context is None:
        return
    try:
        from src.two_bot.pipeline import generate_shadow_draft

        shadow = generate_shadow_draft(bundle, bot_state)
        if shadow:
            review_context["shadow_two_bot"] = {
                "text": shadow["text"],
                **shadow["two_bot_metadata"],
            }
    except Exception as exc:
        print(f"[shadow_ab] Skipped due to error: {exc}")


def post_approved(tweet_text: str, bot_state: BotState) -> str:
    """Post an approved tweet to X.

    Returns "posted", "rate_limited", or "failed".
    """
    if not state.check_daily_cap(bot_state):
        print("[post] Daily tweet cap reached, skipping")
        return "failed"

    result = post_tweet(tweet_text)
    if result is None:
        print("[post] Failed to post to X")
        return "failed"

    if result.get("error") == "rate_limited":
        return "rate_limited"

    post_to_bluesky(tweet_text)
    state.increment_daily_count(bot_state)
    print(f"[post] Posted to X: {tweet_text[:60]}...")
    return "posted"


MAX_DRAFTS_PER_CYCLE = 3


def run_alerts(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Check all alert data sources and save drafts."""
    _activate_suppression_ctx(
        bot_state,
        source="alerts",
        run_id=(current_run or {}).get("id"),
    )
    drafted = 0
    drafts_before = len(bot_state.get("drafts", []))
    us_city_state_map: dict[str, str] = {}
    cities_start = time.perf_counter()
    try:
        cities = open_meteo.load_cities()
        us_city_state_map = cities_to_state_map(cities)
        _record_source_run(
            current_run, bot_state, "load_cities", cities_start,
            status="success", observed=len(cities), promoted=len(cities)
        )
    except Exception as e:
        print(f"[alerts] Failed to load cities: {e}")
        state.log_error(bot_state, "load_cities", str(e))
        cities = []
        _record_source_run(
            current_run, bot_state, "load_cities", cities_start,
            status="failed", error=str(e)
        )

    # (city, country) → elevation lookup for downstream prompt enrichment
    # (notably the simultaneous_records roll-call format, which surfaces
    # stations spanning low and high altitudes). Keyed by the pair because
    # cities.csv has duplicate city names across countries (Hyderabad in
    # India and Pakistan, Barcelona in Spain and Venezuela, etc.) — keying
    # by city alone silently inherits the wrong country's elevation. Rows
    # where elevation_m is empty are silently skipped.
    city_elevations: dict[tuple[str, str], int] = {}
    for c in cities:
        raw = (c.get("elevation_m") or "").strip()
        if not raw:
            continue
        try:
            city_elevations[(c["city"], c["country"])] = int(float(raw))
        except (ValueError, TypeError):
            continue

    # 1. Extreme climate signals — dispatched by THEHEAT_SIGNALS_PROVIDER.
    # "open_meteo" (default): 638 curated cities via Open-Meteo archive API.
    # "ghcn": ~9,449 active NOAA GHCN-Daily stations via superghcnd_diff + SQLite threshold cache.
    # Hot 10 leaderboard (run_leaderboard) always uses Open-Meteo regardless of this flag.
    _signals_provider = os.environ.get("THEHEAT_SIGNALS_PROVIDER", "open_meteo").lower()
    print(f"[alerts] Checking extreme climate signals (provider={_signals_provider})...")
    signals_start = time.perf_counter()
    signal_counts = {"all_time": 0, "monthly": 0, "anomaly": 0, "calendar": 0, "streak": 0}
    # Per-station data for the simultaneous_records signal. Richer than
    # just (city, country) so the roll-call format can surface temps,
    # margins, and elevations. See src/editorial/simultaneous_format.py
    # for the routing decision (flat summary vs. multi-station roll-call).
    simultaneous_record_stations: list[dict] = []
    ghcn_pipeline_metrics: dict = {}
    open_meteo_pipeline_metrics: dict = {}
    # Per-bundle decision log for the dashboard drill-down. Each row records
    # which bundle was processed, what its strongest signal was (if any), and
    # whether it ended up as a draft, rejection, duplicate, or no-signal.
    ghcn_event_log: list[dict] = []
    try:
        if _signals_provider not in {"open_meteo", "ghcn"}:
            raise ValueError(
                "THEHEAT_SIGNALS_PROVIDER must be 'open_meteo' or 'ghcn', "
                f"got {_signals_provider!r}"
            )
        if _signals_provider == "ghcn":
            bundles, country_records = ghcn.check_extreme_signals_for_stations(
                metrics_out=ghcn_pipeline_metrics,
            )
        else:
            bundles, country_records = _check_city_extreme_signals(
                cities,
                open_meteo_pipeline_metrics,
            )
        source_promoted = 0
        source_drafted = 0
        for bundle in bundles:
            # Process signals in descending order of priority:
            # all-time > monthly > anomaly > calendar-date.
            # The strongest signal wins — we don't draft multiple tweets for the same city.

            strongest_signal: AllTimeRecord | MonthlyRecord | AnomalyEvent | RecordEvent | None = None
            strongest_score: EditorialScore | None = None
            strongest_event_id: str | None = None
            strongest_headline = ""
            strongest_facts = []
            strongest_type = ""
            strongest_city = ""
            signal_year = (bundle.signal_date or date.today()).year
            # Default these so the bottom-of-loop event-log capture
            # works whether or not the if-cascade fires.
            two_bot_saved = False

            if bundle.all_time_high:
                ev: AllTimeRecord = bundle.all_time_high
                if not state.is_duplicate(bot_state, ev.event_id):
                    score = score_all_time_record(
                        ev.new_temp_c, ev.old_record_c, ev.old_record_year,
                        ev.years_of_data, kind="high",
                    )
                    if _should_draft(score, ev.event_id):
                        strongest_signal = ev
                        strongest_score = score
                        strongest_event_id = ev.event_id
                        strongest_type = "all_time_high"
                        strongest_city = ev.city
                        strongest_headline = f"{ev.city} on pace for its hottest in {ev.years_of_data}yr archive"
                        strongest_facts = [
                            _fact("Forecast high", _temp_pair_c(ev.new_temp_c)),
                            _fact("Prior archive max", _temp_pair_c(ev.old_record_c)),
                            _fact("Prior max year", ev.old_record_year),
                            _fact("Archive span", f"{ev.years_of_data} years"),
                            _fact("Country", ev.country),
                        ]
                        signal_counts["all_time"] += 1

            if strongest_signal is None and bundle.all_time_low:
                ev = bundle.all_time_low
                if not state.is_duplicate(bot_state, ev.event_id):
                    score = score_all_time_record(
                        ev.new_temp_c, ev.old_record_c, ev.old_record_year,
                        ev.years_of_data, kind="low",
                    )
                    if _should_draft(score, ev.event_id):
                        strongest_signal = ev
                        strongest_score = score
                        strongest_event_id = ev.event_id
                        strongest_type = "all_time_low"
                        strongest_city = ev.city
                        strongest_headline = f"{ev.city} hit its coldest reading in {ev.years_of_data}yr archive"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev.new_temp_c)),
                            _fact("Prior archive min", _temp_pair_c(ev.old_record_c)),
                            _fact("Prior min year", ev.old_record_year),
                            _fact("Archive span", f"{ev.years_of_data} years"),
                            _fact("Country", ev.country),
                        ]
                        signal_counts["all_time"] += 1

            if strongest_signal is None and bundle.monthly_high:
                ev_mh: MonthlyRecord = bundle.monthly_high
                # Suppress "hottest April ever - old record set in 2026"
                # tweets. When the prior record was set in the same year as
                # this reading, the "hottest ever" framing reads as nonsense.
                if (
                    not state.is_duplicate(bot_state, ev_mh.event_id)
                    and ev_mh.old_record_year != signal_year
                ):
                    score = score_monthly_record(
                        ev_mh.new_temp_c, ev_mh.old_record_c, ev_mh.old_record_year,
                        ev_mh.month, ev_mh.years_of_data, kind="high",
                    )
                    if _should_draft(score, ev_mh.event_id):
                        month_name = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][ev_mh.month]
                        strongest_signal = ev_mh
                        strongest_score = score
                        strongest_event_id = ev_mh.event_id
                        strongest_type = "monthly_high"
                        strongest_city = ev_mh.city
                        strongest_headline = f"{ev_mh.city} on pace for hottest {month_name} on record"
                        strongest_facts = [
                            _fact("Forecast high", _temp_pair_c(ev_mh.new_temp_c)),
                            _fact(f"Prior {month_name} max", _temp_pair_c(ev_mh.old_record_c)),
                            _fact("Prior year", ev_mh.old_record_year),
                            _fact("Archive span", f"{ev_mh.years_of_data} years"),
                        ]
                        signal_counts["monthly"] += 1

            if strongest_signal is None and bundle.monthly_low:
                ev_ml: MonthlyRecord = bundle.monthly_low
                if (
                    not state.is_duplicate(bot_state, ev_ml.event_id)
                    and ev_ml.old_record_year != signal_year
                ):
                    score = score_monthly_record(
                        ev_ml.new_temp_c, ev_ml.old_record_c, ev_ml.old_record_year,
                        ev_ml.month, ev_ml.years_of_data, kind="low",
                    )
                    if _should_draft(score, ev_ml.event_id):
                        month_name = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][ev_ml.month]
                        strongest_signal = ev_ml
                        strongest_score = score
                        strongest_event_id = ev_ml.event_id
                        strongest_type = "monthly_low"
                        strongest_city = ev_ml.city
                        strongest_headline = f"{ev_ml.city} hit its coldest {month_name} reading on record"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev_ml.new_temp_c)),
                            _fact(f"Prior {month_name} min", _temp_pair_c(ev_ml.old_record_c)),
                            _fact("Prior year", ev_ml.old_record_year),
                            _fact("Archive span", f"{ev_ml.years_of_data} years"),
                        ]
                        signal_counts["monthly"] += 1

            if strongest_signal is None and bundle.anomaly_hot:
                ev_ah: AnomalyEvent = bundle.anomaly_hot
                if not state.is_duplicate(bot_state, ev_ah.event_id):
                    score = score_anomaly(
                        ev_ah.today_temp_c, ev_ah.historical_mean_c, ev_ah.anomaly_c,
                        kind="hot",
                    )
                    if _should_draft(score, ev_ah.event_id):
                        strongest_signal = ev_ah
                        strongest_score = score
                        strongest_event_id = ev_ah.event_id
                        strongest_type = "anomaly_hot"
                        strongest_city = ev_ah.city
                        strongest_headline = f"{ev_ah.city}: +{ev_ah.anomaly_c:.1f}C above normal"
                        strongest_facts = [
                            _fact("Today", _temp_pair_c(ev_ah.today_temp_c)),
                            _fact("Historical mean", _temp_pair_c(ev_ah.historical_mean_c)),
                            _fact("Anomaly", f"+{ev_ah.anomaly_c:.1f}C"),
                        ]
                        signal_counts["anomaly"] += 1

            if strongest_signal is None and bundle.anomaly_cold:
                ev_ac: AnomalyEvent = bundle.anomaly_cold
                if not state.is_duplicate(bot_state, ev_ac.event_id):
                    score = score_anomaly(
                        ev_ac.today_temp_c, ev_ac.historical_mean_c, ev_ac.anomaly_c,
                        kind="cold",
                    )
                    if _should_draft(score, ev_ac.event_id):
                        strongest_signal = ev_ac
                        strongest_score = score
                        strongest_event_id = ev_ac.event_id
                        strongest_type = "anomaly_cold"
                        strongest_city = ev_ac.city
                        strongest_headline = f"{ev_ac.city}: {ev_ac.anomaly_c:.1f}C below normal"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev_ac.today_temp_c)),
                            _fact("Historical mean low", _temp_pair_c(ev_ac.historical_mean_c)),
                            _fact("Anomaly", f"{ev_ac.anomaly_c:.1f}C"),
                        ]
                        signal_counts["anomaly"] += 1

            if strongest_signal is None and bundle.calendar_date_high:
                ev_cdh: RecordEvent = bundle.calendar_date_high
                if not state.is_duplicate(bot_state, ev_cdh.event_id):
                    score = score_record_event(
                        ev_cdh.new_temp_c, ev_cdh.old_record_c, ev_cdh.old_record_year,
                    )
                    if _should_draft(score, ev_cdh.event_id):
                        strongest_signal = ev_cdh
                        strongest_score = score
                        strongest_event_id = ev_cdh.event_id
                        strongest_type = "record"
                        strongest_city = ev_cdh.city
                        strongest_headline = f"{ev_cdh.city} is forecast to challenge a heat record"
                        strongest_facts = [
                            _fact("Forecast high", _temp_pair_c(ev_cdh.new_temp_c)),
                            _fact("Previous record", _temp_pair_c(ev_cdh.old_record_c)),
                            _fact("Old record year", ev_cdh.old_record_year),
                            _fact("Record gap", f"+{ev_cdh.new_temp_c - ev_cdh.old_record_c:.1f}C"),
                            _fact("Country", ev_cdh.country),
                        ]
                        signal_counts["calendar"] += 1
                        # Track only heat records for the simultaneous-records
                        # lane, preserving enough station detail for roll-call.
                        simultaneous_record_stations.append({
                            "city": ev_cdh.city,
                            "country": ev_cdh.country,
                            "temp_c": ev_cdh.new_temp_c,
                            "kind": "high",
                            "old_record_c": ev_cdh.old_record_c,
                            "old_record_year": ev_cdh.old_record_year,
                            "margin_c": round(ev_cdh.new_temp_c - ev_cdh.old_record_c, 1),
                            "elevation_m": city_elevations.get((ev_cdh.city, ev_cdh.country)),
                            "signal_date": (bundle.signal_date or date.today()).isoformat(),
                        })

            if strongest_signal is None and bundle.calendar_date_low:
                ev_cdl: RecordEvent = bundle.calendar_date_low
                if not state.is_duplicate(bot_state, ev_cdl.event_id):
                    score = score_record_low_event(
                        ev_cdl.new_temp_c, ev_cdl.old_record_c, ev_cdl.old_record_year,
                    )
                    if _should_draft(score, ev_cdl.event_id):
                        strongest_signal = ev_cdl
                        strongest_score = score
                        strongest_event_id = ev_cdl.event_id
                        strongest_type = "record_low"
                        strongest_city = ev_cdl.city
                        strongest_headline = f"{ev_cdl.city} hit a daily cold record"
                        strongest_facts = [
                            _fact("Observed low", _temp_pair_c(ev_cdl.new_temp_c)),
                            _fact("Previous record low", _temp_pair_c(ev_cdl.old_record_c)),
                            _fact("Old record year", ev_cdl.old_record_year),
                            _fact("Record gap", f"{ev_cdl.new_temp_c - ev_cdl.old_record_c:.1f}C"),
                            _fact("Country", ev_cdl.country),
                        ]
                        signal_counts["calendar"] += 1

            if strongest_signal:
                # If strongest_signal is set, the cascade above always set
                # strongest_event_id alongside it — narrow for downstream calls
                # that accept only str.
                assert strongest_event_id is not None
                source_promoted += 1
                # Record synthesis component as soon as editorial gate passes:
                syn_state = us_city_state_map.get(strongest_city)
                if syn_state and strongest_type in {
                    "all_time_high", "monthly_high", "anomaly_hot", "record",
                }:
                    value_c = getattr(strongest_signal, "new_temp_c", None)
                    if value_c is None:
                        value_c = getattr(strongest_signal, "today_temp_c", 0.0)
                    # Compute an anomaly figure the synthesis scorer can use.
                    # anomaly_hot events expose a true anomaly; record events
                    # carry an implicit margin over their prior archive-high,
                    # which is a reasonable proxy. Unknown → 0 (scorer clamps
                    # with abs()+min() so zero contributes nothing).
                    anomaly_c = getattr(strongest_signal, "anomaly_c", None)
                    if anomaly_c is None:
                        old_record_c = getattr(strongest_signal, "old_record_c", None)
                        if old_record_c is not None and value_c is not None:
                            anomaly_c = max(float(value_c) - float(old_record_c), 0.0)
                    kind_map = {
                        "all_time_high": "all_time",
                        "monthly_high": "monthly",
                        "anomaly_hot": "anomaly",
                        "record": "calendar",
                    }
                    state.record_synthesis_component(
                        bot_state,
                        kind="heat",
                        region=syn_state,
                        event_id=strongest_event_id,
                        metadata={
                            "kind": kind_map.get(strongest_type, "record"),
                            "city": strongest_city,
                            "value_c": float(value_c or 0),
                            "anomaly_c": (
                                float(anomaly_c) if anomaly_c is not None else None
                            ),
                        },
                    )
                _signal_source_label = (
                    f"NOAA GHCN-Daily (station {bundle.station_id})"
                    if _signals_provider == "ghcn"
                    else "Open-Meteo forecast + archive"
                )
                review_context = _review_context(
                    source=_signal_source_label,
                    source_key="open_meteo_extreme_signals",
                    headline=strongest_headline,
                    current_run=current_run,
                    facts=strongest_facts,
                )
                # Elite signals bypass the city cooldown. Non-elite signals
                # (calendar-date, monthly, modest anomalies) apply it so a
                # single city heatwave doesn't monopolize the feed.
                elite = strongest_type in ("all_time_high", "all_time_low")
                if strongest_type in ("anomaly_hot", "anomaly_cold"):
                    anomaly_magnitude = abs(
                        getattr(strongest_signal, "anomaly_c", 0) or 0
                    )
                    if anomaly_magnitude >= 18:
                        elite = True

                # Route through the two-bot pipeline. User directive
                # 2026-05-04: the cheap model never writes audience-
                # facing prose. If a future signal type is added that
                # doesn't have a bundle builder, we DROP the signal
                # rather than fall through to voice gen — a missed
                # tweet is better than a Gemini-Flash-written tweet.
                bundle_result: dict = {}
                two_bot_bundle = _two_bot_bundle_for_extreme_signal(
                    strongest_type,
                    strongest_signal,
                    result_out=bundle_result,
                )
                if two_bot_bundle is None:
                    print(
                        f"[two_bot.dispatch] No bundle builder for "
                        f"extreme-signal type {strongest_type!r}; "
                        f"dropping {strongest_event_id}"
                    )
                    ctx = _CURRENT_SUPPRESSION_CTX
                    if ctx is not None:
                        _record_downstream_suppression(
                            bot_state=ctx["bot_state"],
                            source=ctx.get("source"),
                            run_id=ctx.get("run_id"),
                            event_id=strongest_event_id,
                            score=strongest_score,
                            kill_stage=bundle_result.get("kill_stage", "bundle_build"),
                            kill_reason=bundle_result.get(
                                "kill_reason", "Bundle build failed"
                            ),
                            summary=strongest_city or strongest_headline or None,
                        )
                    continue

                two_bot_saved = _try_two_bot_draft(
                    two_bot_bundle, bot_state, strongest_score,
                    legacy_type=strongest_type,
                    event_id=strongest_event_id,
                    review_context=review_context,
                    city=strongest_city,
                    tweet_date=(bundle.signal_date or date.today()).isoformat(),
                    cooldown_exempt=elite,
                )
                voice_gen_saved = False  # voice gen no longer reachable
                if two_bot_saved:
                    state.record_event(bot_state, strongest_event_id)
                    drafted += 1
                    source_drafted += 1

                if two_bot_saved or voice_gen_saved:
                    # Streak tracking — update on any calendar-date high record.
                    # Key: station_id on GHCN path; city name on Open-Meteo path.
                    # Old city-name entries prune naturally via prune_stale_record_streaks.
                    if strongest_type == "record" and bundle.calendar_date_high:
                        ev_cd = bundle.calendar_date_high
                        streak_key = bundle.station_id if _signals_provider == "ghcn" and bundle.station_id else ev_cd.city
                        state.update_record_streak(
                            bot_state,
                            streak_key,
                            ev_cd.new_temp_c,
                            event_date=bundle.signal_date,
                        )
                        streak = state.get_record_streak(bot_state, streak_key)
                        if streak and streak.get("days", 0) >= 3:
                            streak_event_id = f"streak_{streak_key.replace(' ', '_')}_{streak['last_date']}"
                            if not state.is_duplicate(bot_state, streak_event_id):
                                streak_score = score_record_streak(
                                    streak["days"], streak.get("peak_temp_c", ev_cd.new_temp_c),
                                )
                                if _should_draft(streak_score, streak_event_id):
                                    from src.data.open_meteo import RecordStreakEvent
                                    from src.two_bot.intern import build_record_streak_bundle
                                    streak_event = RecordStreakEvent(
                                        city=ev_cd.city,
                                        country=ev_cd.country,
                                        consecutive_days=streak["days"],
                                        start_date=streak["start_date"],
                                        peak_temp_c=streak.get("peak_temp_c", ev_cd.new_temp_c),
                                        event_id=streak_event_id,
                                        signal_date=bundle.signal_date,
                                    )
                                    streak_bundle = build_record_streak_bundle(streak_event)
                                    streak_ctx = _review_context(
                                        source="state.record_streaks",
                                        source_key="record_streak",
                                        headline=f"{ev_cd.city}: {streak['days']} consecutive daily records",
                                        current_run=current_run,
                                        facts=[
                                            _fact("Consecutive days", streak["days"]),
                                            _fact("Streak start", streak["start_date"]),
                                            _fact("Peak temp", _temp_pair_c(streak.get("peak_temp_c", ev_cd.new_temp_c))),
                                        ],
                                    )
                                    if _try_two_bot_draft(
                                        streak_bundle, bot_state, streak_score,
                                        legacy_type="record_streak",
                                        event_id=streak_event_id,
                                        review_context=streak_ctx,
                                        city=ev_cd.city,
                                        tweet_date=(bundle.signal_date or date.today()).isoformat(),
                                        cooldown_exempt=True,
                                    ):
                                        state.record_event(bot_state, streak_event_id)
                                        drafted += 1
                                        signal_counts["streak"] += 1

            # Append a per-bundle row to the dashboard event log. Captured
            # for every bundle iterated regardless of decision so the UI can
            # show "X considered, Y drafted, Z rejected, W no-signal".
            # Only the GHCN provider exposes station_id; rows from the
            # Open-Meteo provider get an empty station_id and the city instead.
            if _signals_provider == "ghcn":
                if strongest_event_id and not two_bot_saved:
                    decision = "rejected"
                elif two_bot_saved:
                    decision = "drafted"
                else:
                    decision = "no_qualifying_signal"
                ghcn_event_log.append({
                    "station_id": bundle.station_id,
                    "station_name": bundle.station_name,
                    "country": bundle.country,
                    "city": bundle.city,
                    "signal_date": (
                        bundle.signal_date.isoformat() if bundle.signal_date else None
                    ),
                    "decision": decision,
                    "type": strongest_type or None,
                    "event_id": strongest_event_id,
                    "score": (
                        round(strongest_score.total, 2) if strongest_score else None
                    ),
                    "today_max_c": bundle.today_max_c,
                    "today_min_c": bundle.today_min_c,
                })

        # Simultaneous records detection — fire one summary signal if many cities broke records.
        # Two formats available; flat summary is the default. Roll-call (per-station list with
        # elevations) fires only when the cluster shape qualifies — same country with a
        # meaningful elevation spread. See src/editorial/simultaneous_format.py.
        simultaneous_groups: dict[str, list[dict]] = {}
        for station_row in simultaneous_record_stations:
            sim_date = station_row.get("signal_date") or date.today().isoformat()
            simultaneous_groups.setdefault(sim_date, []).append(station_row)
        for today_iso, simultaneous_group in simultaneous_groups.items():
            if len(simultaneous_group) < 5:
                continue
            sim_event_id = f"simultaneous_records_{today_iso}"
            if not state.is_duplicate(bot_state, sim_event_id):
                city_names = [s["city"] for s in simultaneous_group]
                sim_score = score_simultaneous_records(len(city_names), city_names)
                if _should_draft(sim_score, sim_event_id):
                    from src.two_bot.intern import build_simultaneous_records_bundle
                    roll_call_subset = select_roll_call_subset(simultaneous_group)
                    if roll_call_subset:
                        rc_country = roll_call_subset[0].get("country", "")
                        rc_elevs = [
                            s["elevation_m"] for s in roll_call_subset
                            if s.get("elevation_m") is not None
                        ]
                        rc_facts = [
                            _fact("Format", "roll-call"),
                            _fact("Country", rc_country),
                            _fact("Stations in subset", len(roll_call_subset)),
                            _fact("Total simultaneous", len(simultaneous_group)),
                        ]
                        if rc_elevs:
                            rc_facts.append(
                                _fact(
                                    "Elevation range",
                                    f"{min(rc_elevs)}m to {max(rc_elevs)}m",
                                )
                            )
                        sim_ctx = _review_context(
                            source=(
                                "NOAA GHCN-Daily"
                                if _signals_provider == "ghcn"
                                else "open_meteo_extreme_signals"
                            ),
                            source_key="simultaneous_records",
                            headline=(
                                f"{len(roll_call_subset)} stations across {rc_country} "
                                f"broke records (multi-altitude)"
                            ),
                            current_run=current_run,
                            facts=rc_facts,
                        )
                        sim_stations = roll_call_subset
                    else:
                        sim_ctx = _review_context(
                            source=(
                                "NOAA GHCN-Daily"
                                if _signals_provider == "ghcn"
                                else "open_meteo_extreme_signals"
                            ),
                            source_key="simultaneous_records",
                            headline=f"{len(city_names)} cities broke records on same day",
                            current_run=current_run,
                            facts=[
                                _fact("Format", "flat summary"),
                                _fact("City count", len(city_names)),
                                _fact("Sample cities", ", ".join(city_names[:5])),
                            ],
                        )
                        sim_stations = simultaneous_group
                    sim_bundle = build_simultaneous_records_bundle(
                        sim_stations, event_id=sim_event_id, when=today_iso,
                    )
                    if _try_two_bot_draft(
                        sim_bundle, bot_state, sim_score,
                        legacy_type="simultaneous_records",
                        event_id=sim_event_id,
                        review_context=sim_ctx,
                    ):
                        state.record_event(bot_state, sim_event_id)
                        drafted += 1

        # Country-level records — the biggest story our pipeline produces.
        # Aggregates across every sampled city in a country; fires when
        # today's peak beats the archive-wide peak anywhere in the country.
        country_count = 0
        for cr in country_records:
            if state.is_duplicate(bot_state, cr.event_id):
                continue
            score = score_country_record(
                cr.new_temp_c, cr.old_record_c, cr.old_record_year,
                kind=cr.kind, cities_sampled=cr.cities_sampled,
                years_of_data=cr.years_of_data,
            )
            if not _should_draft(score, cr.event_id):
                continue
            source_promoted += 1
            descriptor = "hottest" if cr.kind == "high" else "coldest"
            country_source_label = (
                "NOAA GHCN-Daily station aggregate"
                if _signals_provider == "ghcn"
                else "Open-Meteo archive (country-wide aggregate)"
            )
            cr_ctx = _review_context(
                source=country_source_label,
                source_key="country_record",
                headline=f"{cr.country}: {descriptor} reading in {cr.years_of_data}-yr archive",
                current_run=current_run,
                facts=[
                    _fact("Country", cr.country),
                    _fact("Peak city today", cr.peak_city),
                    _fact("Peak temp today", _temp_pair_c(cr.new_temp_c)),
                    _fact("Prior archive peak", _temp_pair_c(cr.old_record_c)),
                    _fact("Prior peak city", cr.old_record_city),
                    _fact("Prior peak year", cr.old_record_year),
                    _fact("Cities aggregated", cr.cities_sampled),
                ],
            )
            # Country records: ported to two-bot writer (Sonnet) on
            # 2026-05-03. Country records are also not subject to
            # per-city cooldown — no single city "owns" this story.
            from src.two_bot.intern import build_country_record_bundle
            cr_bundle = build_country_record_bundle(cr)
            if _try_two_bot_draft(
                cr_bundle, bot_state, score,
                legacy_type=f"country_{cr.kind}",
                event_id=cr.event_id,
                review_context=cr_ctx,
                tweet_date=(cr.signal_date or date.today()).isoformat(),
            ):
                state.record_event(bot_state, cr.event_id)
                drafted += 1
                source_drafted += 1
                country_count += 1
                syn_state = us_city_state_map.get(cr.peak_city)
                if cr.kind == "high" and syn_state:
                    state.record_synthesis_component(
                        bot_state,
                        kind="heat",
                        region=syn_state,
                        event_id=cr.event_id,
                        metadata={
                            "kind": "all_time",
                            "city": cr.peak_city,
                            "value_c": float(cr.new_temp_c or 0),
                        },
                    )

        # Prune stale streaks at cycle end
        state.prune_stale_record_streaks(bot_state)

        total_observed = sum(signal_counts.values()) + country_count
        # Build a structured note. For GHCN: surface the funnel
        # (active → with-obs → checked → raw_signals → bundles → drafted)
        # so the dashboard can render pipeline visibility.
        signal_breakdown = (
            f"all_time:{signal_counts['all_time']} monthly:{signal_counts['monthly']} "
            f"anomaly:{signal_counts['anomaly']} calendar:{signal_counts['calendar']} "
            f"streak:{signal_counts['streak']} country:{country_count}"
        )
        source_status = "success"
        details: dict | None = None
        if _signals_provider == "ghcn" and ghcn_pipeline_metrics:
            source_status = _classify_ghcn_source_status(ghcn_pipeline_metrics)
            diff_attempted = ghcn_pipeline_metrics.get("diff_dates_attempted", "-")
            diff_fetched = ghcn_pipeline_metrics.get("diff_dates_fetched", "-")
            diff_missing = ghcn_pipeline_metrics.get("diff_dates_missing", "-")
            funnel = (
                f"stations_active:{ghcn_pipeline_metrics.get('stations_active', '-')} "
                f"stations_with_obs:{ghcn_pipeline_metrics.get('stations_with_obs', '-')} "
                f"checked:{ghcn_pipeline_metrics.get('stations_checked', '-')} "
                f"raw_signals:{ghcn_pipeline_metrics.get('raw_signals', '-')} "
                f"bundles:{ghcn_pipeline_metrics.get('bundles_after_dedup', '-')} "
                f"diffs:{diff_fetched}/{diff_attempted} "
                f"diff_missing:{diff_missing} "
                f"drafted:{source_drafted}"
            )
            note = f"provider:ghcn {funnel} | {signal_breakdown}"
            details = {
                "provider": "ghcn",
                "pipeline_metrics": dict(ghcn_pipeline_metrics),
                # Cap the events list so a single noisy cycle (thousands of
                # raw signals dedup-survived to dozens of bundles) doesn't
                # bloat the run record.
                "events": ghcn_event_log[:200],
            }
        else:
            city_failures = int(open_meteo_pipeline_metrics.get("city_fetch_failures", 0) or 0)
            city_readings = int(open_meteo_pipeline_metrics.get("city_readings", 0) or 0)
            if city_failures and city_readings:
                source_status = "degraded"
            elif city_failures and not city_readings:
                source_status = "failed"
            note = f"provider:{_signals_provider} {signal_breakdown}"
            if open_meteo_pipeline_metrics:
                details = {
                    "provider": "open_meteo",
                    "pipeline_metrics": dict(open_meteo_pipeline_metrics),
                }
        if source_status == "failed":
            fail_count = state.increment_data_source_failure(bot_state, _signals_provider)
            try:
                if fail_count >= 3:
                    print(
                        f"[alerts] STRUCTURAL ALERT: {_signals_provider} "
                        f"has failed {fail_count} consecutive cycles"
                    )
            except TypeError:
                pass
        else:
            state.reset_data_source_failure(bot_state, _signals_provider)
        _record_source_run(
            current_run, bot_state, "open_meteo_extreme_signals", signals_start,
            status=source_status, observed=total_observed,
            promoted=source_promoted, drafted=source_drafted,
            note=note, details=details,
        )
    except Exception as e:
        print(f"[alerts] Extreme signals error: {e}")
        fail_count = state.increment_data_source_failure(bot_state, _signals_provider)
        try:
            if fail_count >= 3:
                print(f"[alerts] STRUCTURAL ALERT: {_signals_provider} has failed {fail_count} consecutive cycles")
        except TypeError:
            pass  # mock or unexpected return type — skip the alert
        state.log_error(bot_state, "open_meteo_extreme_signals", str(e))
        _record_source_run(
            current_run, bot_state, "open_meteo_extreme_signals", signals_start,
            status="failed", error=str(e),
        )

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
                ctx = _CURRENT_SUPPRESSION_CTX
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

    # 2b. Fire footprint / acreage (NIFC, once per day)
    today_iso = date.today().isoformat()
    if bot_state.get("fire_footprint_last_run") != today_iso:
        print("[alerts] Checking fire footprints (NIFC)...")
        ff_start = time.perf_counter()
        source_promoted = 0
        source_drafted = 0
        try:
            complexes = _fetch_strict(fire_footprint.fetch_active_fire_perimeters)
            crossings = fire_footprint.detect_tier_crossings(complexes, cast(dict, bot_state))
            for fc in crossings:
                try:
                    if state.is_duplicate(bot_state, fc.event_id):
                        continue
                    score = score_fire_footprint(
                        hectares=fc.hectares,
                        tier=fc.tier,
                        region=fc.region,
                        has_name=bool(fc.name),
                    )
                    if not _should_draft(score, fc.event_id):
                        continue
                    source_promoted += 1
                    tier_idx = min(fc.tier, len(fire_footprint.TIERS_HECTARES) - 1)
                    tier_threshold = fire_footprint.TIERS_HECTARES[tier_idx]
                    review_context = _review_context(
                        source="NIFC",
                        source_key="fire_footprint",
                        headline=f"Fire complex crossed {tier_threshold:,} ha",
                        current_run=current_run,
                        facts=[
                            _fact("Complex", fc.name or fc.complex_id),
                            _fact("Country", fc.country),
                            _fact("Region", fc.region),
                            _fact("Cumulative burn area", f"{int(fc.hectares):,} ha"),
                            _fact("Tier crossed", f"{tier_threshold:,} ha"),
                            _fact("Ignition date", fc.start_date.isoformat() if fc.start_date else "—"),
                        ],
                    )
                    from src.two_bot.intern import build_fire_footprint_bundle
                    ff_bundle = build_fire_footprint_bundle(fc)
                    if _try_two_bot_draft(
                        ff_bundle, bot_state, score,
                        legacy_type="fire_footprint",
                        event_id=fc.event_id,
                        review_context=review_context,
                    ):
                        state.record_event(bot_state, fc.event_id)
                        state.update_fire_complex_tier(bot_state, fc.complex_id, fc.tier)
                        drafted += 1
                        source_drafted += 1
                except Exception as fc_err:
                    print(f"[alerts] Fire footprint: error processing {fc.complex_id}: {fc_err}")
                    state.log_error(bot_state, "fire_footprint", f"{fc.complex_id}: {fc_err}")
            # Only mark as run-today on success — failed fetches retry on next cron tick.
            bot_state["fire_footprint_last_run"] = today_iso
            _record_source_run(
                current_run, bot_state, "fire_footprint", ff_start,
                status="success", observed=len(complexes),
                promoted=source_promoted, drafted=source_drafted,
            )
        except Exception as e:
            print(f"[alerts] Fire footprint error: {e}")
            state.log_error(bot_state, "fire_footprint", str(e))
            _record_source_run(
                current_run, bot_state, "fire_footprint", ff_start,
                status="failed", error=str(e),
            )
    else:
        ff_skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "fire_footprint", ff_skipped_start,
            status="skipped", note="Already ran today",
        )

    # 3. CO2 milestones.
    # Annual cap: at most CO2_ANNUAL_CAP tweets/year. Milestone crossings are
    # the only CO2 signal type we tweet — weekly telemetry was deemed too
    # routine ("we should only talk about CO2 in the extreme"). Growth rate is
    # ~2-3 ppm/year so natural milestone rate is well under cap; the guardrail
    # covers future signal types and pathological multi-crossing weeks.
    print("[alerts] Checking CO2...")
    co2_drafted_today = any(
        d.get("type", "").startswith("co2")
        and d.get("created_at", "").startswith(date.today().isoformat())
        for d in bot_state.get("drafts", [])
    )
    co2_start = time.perf_counter()
    try:
        readings = _fetch_strict(co2.fetch_co2_data)
        milestone = co2.detect_milestone(readings)
        source_promoted = 0
        source_drafted = 0
        if (
            milestone
            and not co2_drafted_today
            and not state.is_duplicate(bot_state, milestone.event_id)
            and not _co2_annual_cap_reached(bot_state)
        ):
            score = score_co2_milestone(milestone.ppm_crossed, milestone.actual_ppm)
            if _should_draft(score, milestone.event_id):
                source_promoted += 1
                review_context = _review_context(
                    source="NOAA GML",
                    source_key="co2",
                    headline=f"Mauna Loa crossed {milestone.ppm_crossed} ppm",
                    current_run=current_run,
                    facts=[
                        _fact("Actual reading", f"{milestone.actual_ppm:.2f} ppm"),
                        _fact("Milestone crossed", f"{milestone.ppm_crossed} ppm"),
                        _fact("Pre-industrial baseline", "280 ppm"),
                    ],
                )
                from src.two_bot.intern import build_co2_milestone_bundle
                co2_bundle = build_co2_milestone_bundle(milestone)
                if _try_two_bot_draft(
                    co2_bundle, bot_state, score,
                    legacy_type="co2_milestone",
                    event_id=milestone.event_id,
                    review_context=review_context,
                ):
                    state.record_event(bot_state, milestone.event_id)
                    _increment_co2_annual_count(bot_state)
                    drafted += 1
                    co2_drafted_today = True
                    source_drafted += 1
        _record_source_run(
            current_run, bot_state, "co2", co2_start,
            status="success", observed=len(readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] CO2 error: {e}")
        state.log_error(bot_state, "co2", str(e))
        _record_source_run(
            current_run, bot_state, "co2", co2_start,
            status="failed", error=str(e)
        )

    # 4. NWS severe weather alerts (US)
    print("[alerts] Checking NWS severe weather...")
    nws_start = time.perf_counter()
    try:
        alerts = _fetch_strict(nws_alerts.fetch_alerts)
        source_promoted = 0
        source_drafted = 0
        for alert in alerts:
            if state.is_duplicate(bot_state, alert.event_id):
                continue
            score = score_severe_weather(alert.event_type, alert.severity)
            if not _should_draft(score, alert.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NWS Alerts",
                source_key="nws_alerts",
                headline=f"{alert.event_type} for {alert.area}",
                current_run=current_run,
                facts=[
                    _fact("Event", alert.event_type),
                    _fact("Area", alert.area),
                    _fact("Severity", alert.severity),
                    _fact("Max wind gust", alert.max_wind_gust or "—"),
                    _fact("Max hail", alert.max_hail_size or "—"),
                    _fact("Tornado detection", alert.tornado_detection or "—"),
                ],
            )
            # Severe weather: ported to two-bot writer 2026-05-03.
            # Event-scoped repetition now flows through the two-bot
            # memory slice as ``recent_tweets_same_event``.
            from src.two_bot.intern import build_severe_weather_bundle
            sw_bundle = build_severe_weather_bundle(alert)
            if _try_two_bot_draft(
                sw_bundle, bot_state, score,
                legacy_type="severe_weather",
                event_id=alert.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, alert.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "nws_alerts", nws_start,
            status="success", observed=len(alerts), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] NWS error: {e}")
        state.log_error(bot_state, "nws_alerts", str(e))
        _record_source_run(
            current_run, bot_state, "nws_alerts", nws_start,
            status="failed", error=str(e)
        )

    # 5. GDACS global disasters (Red only — Orange isn't extraordinary)
    print("[alerts] Checking GDACS global disasters...")
    gdacs_start = time.perf_counter()
    try:
        disasters = _fetch_strict(gdacs.fetch_disasters, min_severity="Red")
        source_promoted = 0
        source_drafted = 0
        for disaster in disasters:
            if state.is_duplicate(bot_state, disaster.event_id):
                continue
            score = score_global_disaster(disaster.severity, disaster.disaster_type)
            if not _should_draft(score, disaster.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="GDACS",
                source_key="gdacs",
                headline=f"{disaster.disaster_type} alert: {disaster.name}",
                current_run=current_run,
                facts=[
                    _fact("Alert tier", disaster.severity),
                    _fact("Disaster type", disaster.disaster_type),
                    _fact("Country", disaster.country),
                    _fact("Name", disaster.name),
                ],
            )
            # Event-scoped repetition now flows through the two-bot
            # memory slice as ``recent_tweets_same_event``.
            from src.two_bot.intern import build_global_disaster_bundle
            gd_bundle = build_global_disaster_bundle(disaster)
            if _try_two_bot_draft(
                gd_bundle, bot_state, score,
                legacy_type="global_disaster",
                event_id=disaster.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, disaster.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "gdacs", gdacs_start,
            status="success", observed=len(disasters), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] GDACS error: {e}")
        state.log_error(bot_state, "gdacs", str(e))
        _record_source_run(
            current_run, bot_state, "gdacs", gdacs_start,
            status="failed", error=str(e)
        )

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

    # 8. ENSO transitions (monthly, check on 1st of month)
    if date.today().day == 1:
        print("[alerts] Checking ENSO status...")
        enso_start = time.perf_counter()
        try:
            enso_readings = _fetch_strict(enso.fetch_enso_data)
            transition = enso.detect_transition(enso_readings)
            enso_score: EditorialScore | None = None
            if transition and not state.is_duplicate(bot_state, transition["event_id"]):
                enso_score = score_enso_transition(
                    transition["oni_value"],
                    transition["previous_duration_months"],
                )
            source_promoted = 1 if enso_score and transition and _should_draft(enso_score, transition["event_id"]) else 0
            source_drafted = 0
            if transition and source_promoted:
                review_context = _review_context(
                    source="NOAA CPC",
                    source_key="enso",
                    headline=f"ENSO shifted to {transition['to_status']}",
                    current_run=current_run,
                    facts=[
                        _fact("New phase", transition["to_status"]),
                        _fact("ONI", f"{transition['oni_value']:+.1f}"),
                        _fact("Previous duration", f"{transition['previous_duration_months']} months"),
                    ],
                )
                from src.two_bot.intern import build_enso_bundle
                enso_bundle = build_enso_bundle(transition)
                if _try_two_bot_draft(
                    enso_bundle, bot_state, enso_score,
                    legacy_type="enso",
                    event_id=transition["event_id"],
                    review_context=review_context,
                ):
                    state.record_event(bot_state, transition["event_id"])
                    drafted += 1
                    source_drafted = 1
            observed = len(enso_readings) if hasattr(enso_readings, "__len__") else 0
            _record_source_run(
                current_run, bot_state, "enso", enso_start,
                status="success", observed=observed, promoted=source_promoted, drafted=source_drafted
            )
        except Exception as e:
            print(f"[alerts] ENSO error: {e}")
            state.log_error(bot_state, "enso", str(e))
            _record_source_run(
                current_run, bot_state, "enso", enso_start,
                status="failed", error=str(e)
            )
    else:
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, bot_state, "enso", skipped_start,
            status="skipped", note="Runs on the 1st of the month"
        )

    # 9. Extreme ocean waves (every run)
    print("[alerts] Checking ocean conditions...")
    ocean_start = time.perf_counter()
    try:
        ocean_readings = _fetch_strict(ocean.fetch_ocean_conditions)
        extreme_waves = ocean.detect_extreme_waves(ocean_readings)
        source_promoted = 0
        source_drafted = 0
        for wave in extreme_waves:
            if state.is_duplicate(bot_state, wave.event_id):
                continue
            score = score_extreme_wave(wave.wave_height_m)
            if not _should_draft(score, wave.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="Open-Meteo Marine",
                source_key="ocean",
                headline=f"Extreme wave signal in {wave.location}",
                current_run=current_run,
                facts=[
                    _fact("Location", wave.location),
                    _fact("Ocean", wave.ocean),
                    _fact("Wave height", f"{wave.wave_height_m:.1f}m / {wave.wave_height_m * 3.281:.0f}ft"),
                ],
            )
            from src.two_bot.intern import build_extreme_wave_bundle
            wave_bundle = build_extreme_wave_bundle(wave)
            if _try_two_bot_draft(
                wave_bundle, bot_state, score,
                legacy_type="extreme_wave",
                event_id=wave.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, wave.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "ocean", ocean_start,
            status="success", observed=len(ocean_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] Ocean error: {e}")
        state.log_error(bot_state, "ocean", str(e))
        _record_source_run(
            current_run, bot_state, "ocean", ocean_start,
            status="failed", error=str(e)
        )

    # 9b. Global ocean SST marine-heatwave streak (every run)
    print("[alerts] Checking global ocean SST...")
    sst_start = time.perf_counter()
    try:
        obs = _fetch_strict(ocean_sst.fetch_global_sst)
        source_promoted = 0
        source_drafted = 0
        event = None
        if obs is not None:
            prior_streak = bot_state.get(
                "ocean_sst_streak",
                state.DEFAULT_STATE["ocean_sst_streak"],
            )
            new_streak, event = ocean_sst.detect_streak_milestone(obs, cast(dict, prior_streak))
            state.update_ocean_sst_streak(bot_state, new_streak)

        if event and not state.is_duplicate(bot_state, event.event_id):
            score = score_marine_heatwave(
                event.days, event.peak_anomaly_c, event.years_of_data,
            )
            if _should_draft(score, event.event_id):
                source_promoted += 1
                review_context = _review_context(
                    source="NOAA OISST v2.1 (ClimateReanalyzer)",
                    source_key="ocean_sst",
                    headline=f"Global ocean SST streak: day {event.days}",
                    current_run=current_run,
                    facts=[
                        _fact("Streak length", f"{event.days} consecutive days above record"),
                        _fact("Today's global-mean SST", f"{event.today_c:.2f}°C"),
                        _fact("Prior daily max", f"{event.archive_max_c:.2f}°C ({event.archive_max_year})"),
                        _fact("Peak anomaly during streak", f"{event.peak_anomaly_c:+.2f}°C"),
                        _fact("Archive span", f"{event.years_of_data} years"),
                    ],
                )
                from src.two_bot.intern import build_marine_heatwave_bundle
                mhw_bundle = build_marine_heatwave_bundle(event)
                if _try_two_bot_draft(
                    mhw_bundle, bot_state, score,
                    legacy_type="marine_heatwave",
                    event_id=event.event_id,
                    review_context=review_context,
                ):
                    state.record_event(bot_state, event.event_id)
                    drafted += 1
                    source_drafted += 1
        _record_source_run(
            current_run, bot_state, "ocean_sst", sst_start,
            status="success",
            observed=1 if obs is not None else 0,
            promoted=source_promoted,
            drafted=source_drafted,
        )
    except Exception as e:
        print(f"[alerts] Ocean SST error: {e}")
        state.log_error(bot_state, "ocean_sst", str(e))
        _record_source_run(
            current_run, bot_state, "ocean_sst", sst_start,
            status="failed", error=str(e),
        )

    # 10. Storm surge / abnormal water levels (every run)
    print("[alerts] Checking coastal water levels...")
    water_levels_start = time.perf_counter()
    try:
        wl_readings = _fetch_strict(water_levels.fetch_water_levels)
        surges = water_levels.detect_storm_surge(wl_readings)
        source_promoted = 0
        source_drafted = 0
        for surge in surges:
            if state.is_duplicate(bot_state, surge.event_id):
                continue
            score = score_storm_surge(surge.anomaly_m)
            if not _should_draft(score, surge.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="NOAA CO-OPS",
                source_key="water_levels",
                headline=f"Storm surge signal at {surge.station_name}",
                current_run=current_run,
                facts=[
                    _fact("Station", surge.station_name),
                    _fact("State", surge.state),
                    _fact("Anomaly", f"{surge.anomaly_m:.2f}m / {surge.anomaly_m * 3.281:.1f}ft above predicted"),
                    _fact("Observed vs predicted", f"{surge.observed_m:.2f}m vs {surge.predicted_m:.2f}m"),
                ],
            )
            from src.two_bot.intern import build_storm_surge_bundle
            ss_bundle = build_storm_surge_bundle(surge)
            if _try_two_bot_draft(
                ss_bundle, bot_state, score,
                legacy_type="storm_surge",
                event_id=surge.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, surge.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "water_levels", water_levels_start,
            status="success", observed=len(wl_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] Water levels error: {e}")
        state.log_error(bot_state, "water_levels", str(e))
        _record_source_run(
            current_run, bot_state, "water_levels", water_levels_start,
            status="failed", error=str(e)
        )

    # 11. River flood stages (every run)
    print("[alerts] Checking river flood stages...")
    river_start = time.perf_counter()
    try:
        river_readings = _fetch_strict(river_gauges.fetch_river_levels)
        floods = river_gauges.detect_floods(river_readings)
        source_promoted = 0
        source_drafted = 0
        for flood in floods:
            if state.is_duplicate(bot_state, flood.event_id):
                continue
            score = score_river_flood(flood.above_by_ft)
            if not _should_draft(score, flood.event_id):
                continue
            source_promoted += 1
            review_context = _review_context(
                source="USGS Water",
                source_key="river_gauges",
                headline=f"{flood.river} flood-stage exceedance",
                current_run=current_run,
                facts=[
                    _fact("River", flood.river),
                    _fact("Location", flood.location),
                    _fact("Gauge height", f"{flood.gauge_height_ft:.1f}ft"),
                    _fact("Above flood stage", f"{flood.above_by_ft:.1f}ft"),
                ],
            )
            from src.two_bot.intern import build_river_flood_bundle
            rf_bundle = build_river_flood_bundle(flood)
            if _try_two_bot_draft(
                rf_bundle, bot_state, score,
                legacy_type="river_flood",
                event_id=flood.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, flood.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, bot_state, "river_gauges", river_start,
            status="success", observed=len(river_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] River gauges error: {e}")
        state.log_error(bot_state, "river_gauges", str(e))
        _record_source_run(
            current_run, bot_state, "river_gauges", river_start,
            status="failed", error=str(e)
        )

    # 12. GRACE-FO ice mass (Greenland + Antarctica).
    # Monthly-cadence source with 1-2 month lag. Run once per week on
    # Mondays. Per-region short-circuit via ice_mass_last_seen prevents
    # re-processing the same published month. Annual cap: 8 tweets/year.
    if date.today().weekday() == 0:
        print("[alerts] Checking GRACE ice mass...")
        for region in ("greenland", "antarctica"):
            region_key = f"ice_mass_{region}"
            im_start = time.perf_counter()
            try:
                if _ice_annual_cap_reached(bot_state):
                    _record_source_run(
                        current_run, bot_state, region_key, im_start,
                        status="skipped", note="annual cap reached",
                    )
                    continue
                readings = _fetch_strict(ice_mass.fetch_grace_mass, region=region)
                if not readings:
                    _record_source_run(
                        current_run, bot_state, region_key, im_start,
                        status="success", observed=0,
                    )
                    continue
                latest_month = readings[-1].month
                last_seen = bot_state.get("ice_mass_last_seen", {}).get(region)
                if last_seen == latest_month:
                    _record_source_run(
                        current_run, bot_state, region_key, im_start,
                        status="skipped",
                        note=f"already processed {latest_month}",
                    )
                    continue

                ice_record = ice_mass.detect_monthly_record(readings, cast(dict, bot_state))
                if ice_record is None:
                    ice_record = ice_mass.detect_cumulative_milestone(readings, cast(dict, bot_state))

                source_promoted = 0
                source_drafted = 0
                if ice_record and not state.is_duplicate(bot_state, ice_record.event_id):
                    score = score_ice_mass_event(
                        region=ice_record.region,
                        kind=ice_record.kind,
                        monthly_delta_gt=ice_record.monthly_delta_gt,
                        previous_worst_gt=ice_record.previous_worst_gt,
                        threshold_gt=ice_record.threshold_gt,
                    )
                    if _should_draft(score, ice_record.event_id):
                        source_promoted = 1
                        earliest = readings[0].month
                        earliest_year = int(earliest.split("-")[0])
                        years_of_record = date.today().year - earliest_year
                        # Narrow the kind-conditional optional fields once;
                        # see IceMassRecord (src/data/ice_mass.py): monthly_*
                        # set for "monthly_loss_record", threshold_*+current_*
                        # set for cumulative milestones.
                        if ice_record.kind == "monthly_loss_record":
                            assert ice_record.monthly_delta_gt is not None
                            assert ice_record.month is not None
                            headline = f"{ice_record.region.title()}: largest monthly ice loss on ice_record"
                        else:
                            assert ice_record.threshold_gt is not None
                            assert ice_record.current_mass_gt is not None
                            headline = f"{ice_record.region.title()}: cumulative loss crosses {abs(int(ice_record.threshold_gt))} Gt"
                        facts = [
                            _fact("Region", ice_record.region.title()),
                            _fact("Latest month", ice_record.month or latest_month),
                        ]
                        if ice_record.kind == "monthly_loss_record":
                            assert ice_record.monthly_delta_gt is not None
                            facts.append(_fact(
                                "Monthly loss",
                                f"{abs(ice_record.monthly_delta_gt):.0f} Gt",
                            ))
                            if ice_record.previous_worst_gt is not None:
                                facts.append(_fact(
                                    "Previous worst",
                                    f"{abs(ice_record.previous_worst_gt):.0f} Gt "
                                    f"({ice_record.previous_worst_month})",
                                ))
                        else:
                            assert ice_record.threshold_gt is not None
                            assert ice_record.current_mass_gt is not None
                            facts.append(_fact(
                                "Cumulative threshold",
                                f"{abs(int(ice_record.threshold_gt))} Gt",
                            ))
                            facts.append(_fact(
                                "Current anomaly",
                                f"{abs(ice_record.current_mass_gt):.0f} Gt below 2002 baseline",
                            ))
                        review_context = _review_context(
                            source="NASA GRACE-FO / JPL PODAAC",
                            source_key=region_key,
                            headline=headline,
                            current_run=current_run,
                            facts=facts,
                        )
                        from src.two_bot.intern import build_ice_mass_bundle
                        ice_bundle = build_ice_mass_bundle(
                            ice_record,
                            years_of_record=years_of_record,
                            archive_start_year=earliest_year,
                        )
                        if _try_two_bot_draft(
                            ice_bundle, bot_state, score,
                            legacy_type="ice_mass_record",
                            event_id=ice_record.event_id,
                            review_context=review_context,
                        ):
                            state.record_event(bot_state, ice_record.event_id)
                            _increment_ice_annual_count(bot_state)
                            drafted += 1
                            source_drafted = 1
                            # Update the extreme trackers on success.
                            if ice_record.kind == "monthly_loss_record":
                                assert ice_record.monthly_delta_gt is not None
                                assert ice_record.month is not None
                                bot_state.setdefault("ice_mass_max_loss", {})[ice_record.region] = {
                                    "gt": ice_record.monthly_delta_gt,
                                    "month": ice_record.month,
                                }
                            else:
                                assert ice_record.threshold_gt is not None
                                bot_state.setdefault("ice_mass_last_milestone", {})[ice_record.region] = ice_record.threshold_gt

                # Always mark the month as seen so we don't reprocess until data updates.
                bot_state.setdefault("ice_mass_last_seen", {})[region] = latest_month
                _record_source_run(
                    current_run, bot_state, region_key, im_start,
                    status="success", observed=len(readings),
                    promoted=source_promoted, drafted=source_drafted,
                )
            except SourceSkipped as e:
                print(f"[alerts] ice_mass {region} skipped: {e}")
                _record_source_run(
                    current_run, bot_state, region_key, im_start,
                    status="skipped", note=str(e),
                )
            except Exception as e:
                print(f"[alerts] ice_mass {region} error: {e}")
                state.log_error(bot_state, region_key, str(e))
                _record_source_run(
                    current_run, bot_state, region_key, im_start,
                    status="failed", error=str(e),
                )
    else:
        for region in ("greenland", "antarctica"):
            skipped_start = time.perf_counter()
            _record_source_run(
                current_run, bot_state, f"ice_mass_{region}", skipped_start,
                status="skipped", note="Runs Mondays only",
            )

    # --- Cross-source synthesis (runs after every per-source section) ---
    print("[alerts] Running cross-source synthesis...")
    synthesis_start = time.perf_counter()
    synthesis_observed = 0
    synthesis_promoted = 0
    synthesis_drafted = 0
    try:
        signals = synthesis.detect_fire_drought_heat(bot_state)
        synthesis_observed = len(signals)
        for sig in signals:
            if state.is_duplicate(bot_state, sig.event_id):
                continue
            if state.is_synthesis_on_cooldown(bot_state, sig.rule_name, sig.region):
                continue
            comps = sig.components
            score = score_synthesis_fire_drought_heat(
                drought_d4_pct=comps["drought_d4_pct"],
                fire_peak_frp=comps["fire_peak_frp"],
                heat_peak_anomaly_c=comps.get(
                    "heat_peak_anomaly_c",
                    # Fallback for any legacy (pre-fix) components: treat
                    # absolute as zero-anomaly to avoid absurd severity.
                    0.0,
                ),
                component_count={
                    "fires": comps["fire_count"],
                    "heats": comps["heat_count"],
                },
                heat_kind=comps["heat_peak_kind"],
            )
            synthesis_promoted += 1
            if not _should_draft(score, sig.event_id):
                continue
            review_context = _review_context(
                source="Cross-source synthesis (FIRMS + USDM + Open-Meteo)",
                source_key="synthesis_fire_drought_heat",
                headline=sig.headline,
                current_run=current_run,
                facts=[
                    _fact("State", sig.region),
                    _fact("D4 drought %", f"{comps['drought_d4_pct']:.1f}"),
                    _fact("Peak fire FRP", f"{comps['fire_peak_frp']:.0f} MW"),
                    _fact("Peak heat city", comps["heat_peak_city"]),
                    _fact("Peak heat value", f"{comps['heat_peak_value_c']:.1f}C"),
                    _fact("Window", f"{comps['window_days']} days"),
                ],
            )
            from src.two_bot.intern import build_synthesis_bundle
            synth_bundle = build_synthesis_bundle({
                "event_id": sig.event_id,
                "region": sig.region,
                "kind": "fire_drought_heat",
                "headline": sig.headline,
                "rule_name": sig.rule_name,
                "components": [
                    {"kind": "drought", "d4_pct": comps["drought_d4_pct"]},
                    {"kind": "fire", "peak_frp_mw": comps["fire_peak_frp"], "peak_region": comps["fire_peak_region"]},
                    {"kind": "heat", "peak_city": comps["heat_peak_city"], "peak_kind": comps["heat_peak_kind"], "peak_value_c": comps["heat_peak_value_c"]},
                ],
                "window_days": comps["window_days"],
                "total_score": score.total if hasattr(score, "total") else None,
            })
            if _try_two_bot_draft(
                synth_bundle, bot_state, score,
                legacy_type="synthesis_fire_drought_heat",
                event_id=sig.event_id,
                review_context=review_context,
            ):
                state.record_event(bot_state, sig.event_id)
                state.record_synthesis_fired(bot_state, sig.rule_name, sig.region)
                drafted += 1
                synthesis_drafted += 1
        state.prune_stale_synthesis_components(bot_state)
        _record_source_run(
            current_run, bot_state, "synthesis_fire_drought_heat", synthesis_start,
            status="success",
            observed=synthesis_observed,
            promoted=synthesis_promoted,
            drafted=synthesis_drafted,
        )
    except Exception as e:
        print(f"[alerts] Synthesis error: {e}")
        state.log_error(bot_state, "synthesis_fire_drought_heat", str(e))
        _record_source_run(
            current_run, bot_state, "synthesis_fire_drought_heat", synthesis_start,
            status="failed", error=str(e),
        )

    # Prune weakest drafts from this cycle if we exceeded the cap.
    drafted = _prune_weakest_cycle_drafts(
        bot_state, drafts_before, current_run, drafted,
    )
    print(f"[alerts] Done. Saved {drafted} drafts.")
    return bot_state


# Source-key lookup used during per-cycle pruning to roll back
# overstated drafted telemetry. Ice mass logs per-region sub-sources
# (e.g. ``ice_mass_greenland``); the prune helper handles that with
# prefix-matching rather than enumerating every sub-source here.
_PRUNE_SOURCE_KEY_BY_TYPE = {
    "all_time_high": "open_meteo_extreme_signals",
    "all_time_low": "open_meteo_extreme_signals",
    "monthly_high": "open_meteo_extreme_signals",
    "monthly_low": "open_meteo_extreme_signals",
    "anomaly_hot": "open_meteo_extreme_signals",
    "anomaly_cold": "open_meteo_extreme_signals",
    "record": "open_meteo_extreme_signals",
    "record_low": "open_meteo_extreme_signals",
    "record_streak": "open_meteo_extreme_signals",
    "simultaneous_records": "open_meteo_extreme_signals",
    "country_high": "open_meteo_extreme_signals",
    "country_low": "open_meteo_extreme_signals",
    "fire": "firms",
    "fire_footprint": "fire_footprint",
    "co2_milestone": "co2",
    "severe_weather": "nws_alerts",
    "global_disaster": "gdacs",
    "sea_ice_record": "sea_ice",
    "drought": "drought",
    "enso": "enso",
    "extreme_wave": "ocean",
    "storm_surge": "water_levels",
    "river_flood": "river_gauges",
    "marine_heatwave": "ocean_sst",
    "ice_mass_record": "ice_mass",
    "synthesis_fire_drought_heat": "synthesis_fire_drought_heat",
}


def _prune_weakest_cycle_drafts(
    bot_state: BotState,
    drafts_before: int,
    current_run: dict | None,
    drafted: int,
) -> int:
    """Enforce MAX_DRAFTS_PER_CYCLE by dropping the weakest drafts added
    this cycle.

    When a draft is pruned, its ``event_id`` must also be removed from
    ``posted_events`` — each source block records the event as "seen"
    as soon as it saves a draft, so leaving pruned IDs in the list
    permanently blocks future cycles from re-drafting that event even
    though no tweet ever shipped. Also rolls back overstated
    source-level ``drafted`` telemetry in the run record.

    Returns the post-prune drafted count the caller should report.
    """
    drafts = bot_state.get("drafts", [])
    new_drafts = drafts[drafts_before:]
    if len(new_drafts) <= MAX_DRAFTS_PER_CYCLE:
        return drafted

    scored = [(d, d.get("score", {}).get("total", 0)) for d in new_drafts]
    scored.sort(key=lambda x: x[1], reverse=True)
    keep = {id(d) for d, _ in scored[:MAX_DRAFTS_PER_CYCLE]}
    pruned = [d for d, _ in scored[MAX_DRAFTS_PER_CYCLE:]]
    bot_state["drafts"] = drafts[:drafts_before] + [d for d in new_drafts if id(d) in keep]

    pruned_event_ids = {d.get("event_id") for d in pruned if d.get("event_id")}
    if pruned_event_ids:
        bot_state["posted_events"] = [
            e for e in bot_state.get("posted_events", [])
            if e not in pruned_event_ids
        ]
        if current_run is not None:
            for d in pruned:
                src = _PRUNE_SOURCE_KEY_BY_TYPE.get(d.get("type") or "")
                if not src:
                    continue
                for s_run in current_run.get("sources", []):
                    if (
                        s_run.get("source") == src
                        or s_run.get("source", "").startswith(f"{src}_")
                    ) and s_run.get("drafted", 0) > 0:
                        s_run["drafted"] -= 1
                        break

    print(f"[alerts] Pruned {len(pruned)} weaker drafts, kept top {MAX_DRAFTS_PER_CYCLE}")
    for d, s in scored[MAX_DRAFTS_PER_CYCLE:]:
        print(f"[alerts]   Pruned: score={s} {d.get('text', '')[:50]}...")
        ctx = _CURRENT_SUPPRESSION_CTX
        if ctx is not None:
            _record_downstream_suppression(
                bot_state=bot_state,
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=d.get("event_id", ""),
                score=d.get("score") or {},
                kill_stage="cycle_cap",
                kill_reason=f"Pruned by MAX_DRAFTS_PER_CYCLE={MAX_DRAFTS_PER_CYCLE}",
                summary=d.get("text", "")[:120] or d.get("event_id"),
            )
    return MAX_DRAFTS_PER_CYCLE


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
        drafted_count = 0
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
            if _try_two_bot_draft(
                hot10_bundle, bot_state, score,
                legacy_type="hot10",
                event_id=event_id,
                review_context=review_context,
            ):
                drafted_count = 1

        bot_state["last_hot10"] = {
            "date": date.today().isoformat(),
            "cities": [ct.city for ct in hot10],
        }
        state.update_streaks(bot_state, [ct.city for ct in hot10])
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="success", observed=len(temps), promoted=len(hot10) if score.passes else 0, drafted=drafted_count
        )

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))
        _record_source_run(
            current_run, bot_state, "leaderboard", leaderboard_start,
            status="failed", error=str(e)
        )

    return bot_state


def run_manual_tweet(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Post an approved tweet from the TWEET_TEXT env var."""
    manual_start = time.perf_counter()
    tweet_text = os.environ.get("TWEET_TEXT", "").strip()
    draft_id = os.environ.get("DRAFT_ID", "").strip()
    publish_intent_id = os.environ.get("PUBLISH_INTENT_ID", "").strip()
    draft = _find_draft(bot_state, draft_id=draft_id, tweet_text=tweet_text)
    if not tweet_text:
        print("[manual] No TWEET_TEXT provided, skipping")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="skipped", note="No TWEET_TEXT provided"
        )
        return bot_state

    if draft_id and not draft:
        reason = f"Draft not found for id {draft_id}"
        print(f"[manual] {reason}, skipping")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    if draft_id and draft and draft.get("status") == "posted":
        print(f"[manual] Draft {draft_id} already posted, skipping duplicate publish")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="skipped", observed=1, note=f"Draft {draft_id} already posted"
        )
        return bot_state

    if draft_id and draft and draft.get("status") != "approved":
        reason = f"Draft {draft_id} is not approved for publishing"
        print(f"[manual] {reason}")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    if draft_id and draft and publish_intent_id and draft.get("publish_intent_id") != publish_intent_id:
        reason = f"Draft {draft_id} publish intent is stale"
        print(f"[manual] {reason}, skipping")
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="skipped", observed=1, note=reason
        )
        return bot_state

    if len(tweet_text) > 280:
        print(f"[manual] Tweet too long ({len(tweet_text)} chars), skipping")
        if draft:
            draft["status"] = "pending"
            draft["post_error"] = f"Tweet too long ({len(tweet_text)} chars)"
            draft.pop("publish_intent_id", None)
            _touch_draft(draft)
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=f"Tweet too long ({len(tweet_text)} chars)"
        )
        return bot_state

    passed, safety_reason = run_safety_pipeline(tweet_text)
    if not passed:
        reason = safety_reason or "Safety pipeline rejected tweet"
        print(f"[manual] Safety rejected tweet: {reason}")
        if draft:
            draft["status"] = "pending"
            draft["post_error"] = reason
            draft.pop("publish_intent_id", None)
            _touch_draft(draft)
        _record_source_run(
            current_run, bot_state, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    print(f"[manual] Posting: {tweet_text}")
    result = post_approved(tweet_text, bot_state)

    # Update draft status with post result
    if draft:
        draft["last_publish_attempt_at"] = _utc_now_iso()
        if result == "posted":
            draft["status"] = "posted"
            draft["posted_at"] = _utc_now_iso()
            draft.pop("post_error", None)
            draft.pop("publish_intent_id", None)
        elif result == "rate_limited":
            draft["status"] = "pending"
            draft["post_error"] = "Rate limited — retry later"
            draft.pop("publish_intent_id", None)
            print("[manual] Rate limited, draft kept as pending for retry")
        else:
            draft["status"] = "pending"
            draft["post_error"] = "Failed to post to X"
            draft.pop("publish_intent_id", None)
        _touch_draft(draft)

    source_status = "success" if result == "posted" else "failed"
    error = None if result == "posted" else ("Rate limited — retry later" if result == "rate_limited" else "Failed to post to X")
    _record_source_run(
        current_run, bot_state, "manual_publish", manual_start,
        status=source_status, observed=1, promoted=1, drafted=1 if result == "posted" else 0, error=error
    )
    return bot_state


def process_due_drafts(bot_state: BotState, current_run: dict | None = None) -> BotState:
    """Post drafts whose auto-approval window has elapsed."""
    queue_start = time.perf_counter()
    now = _utc_now()
    due_drafts = []
    for draft in bot_state.get("drafts", []):
        if draft.get("status") != "pending":
            continue
        auto_approve_at = _parse_iso_utc(draft.get("auto_approve_at"))
        if auto_approve_at and auto_approve_at <= now:
            due_drafts.append(draft)

    if not due_drafts:
        _record_source_run(
            current_run, bot_state, "auto_publish_due", queue_start,
            status="skipped", observed=0, note="No drafts due for auto-approval"
        )
        return bot_state

    published = 0
    failures = []
    for draft in due_drafts:
        policy = draft.get("approval_policy", {})
        is_policy_auto = policy.get("mode") == "armed_auto"
        is_requested_auto = (
            policy.get("mode") == "suggested_auto"
            and draft.get("approval_mode") == "auto"
        )
        if policy.get("can_auto_approve") is False or not (is_policy_auto or is_requested_auto):
            draft.pop("auto_approve_at", None)
            draft["approval_mode"] = "manual"
            draft["post_error"] = "Auto-approval blocked by policy"
            _touch_draft(draft)
            failures.append(f"{draft.get('id')}: blocked by policy")
            continue

        # Safety check before auto-posting (same gate as manual path)
        passed, reason = run_safety_pipeline(draft["text"])
        if not passed:
            draft.pop("auto_approve_at", None)
            draft["status"] = "pending"
            draft["approval_mode"] = "manual"
            draft["post_error"] = f"Auto-post safety rejected: {reason}"
            _touch_draft(draft)
            failures.append(f"{draft.get('id')}: safety rejected: {reason}")
            continue

        result = post_approved(draft["text"], bot_state)
        draft["last_publish_attempt_at"] = _utc_now_iso()
        if result == "posted":
            draft["status"] = "posted"
            draft["approved_at"] = draft.get("approved_at") or _utc_now_iso()
            draft["posted_at"] = _utc_now_iso()
            draft["approval_mode"] = draft.get("approval_mode") or "auto"
            draft.pop("auto_approve_at", None)
            draft.pop("auto_approve_requested_at", None)
            draft.pop("post_error", None)
            published += 1
        elif result == "rate_limited":
            draft["post_error"] = "Rate limited — retry later"
            failures.append(f"{draft.get('id')}: rate limited")
        else:
            draft["post_error"] = "Failed to post to X"
            failures.append(f"{draft.get('id')}: failed to post")
        _touch_draft(draft)

    status = "success" if not failures else "partial_failure"
    _record_source_run(
        current_run, bot_state, "auto_publish_due", queue_start,
        status=status,
        observed=len(due_drafts),
        promoted=len(due_drafts),
        drafted=published,
        error="; ".join(failures[:3]) if failures else None,
    )
    return bot_state


def main():
    parser = argparse.ArgumentParser(description="@theheat climate bot")
    parser.add_argument(
        "mode",
        choices=["alerts", "leaderboard", "both", "manual_tweet", "auto_publish_due"],
        help="Which content to generate and post",
    )
    args = parser.parse_args()

    print(f"[main] Starting @theheat in {args.mode} mode")

    try:
        bot_state = state.read_state()
    except state.StateReadError as exc:
        print(f"[main] ERROR: {exc}")
        sys.exit(1)
    current_run = state.init_run(args.mode)
    final_status = "success"

    if args.mode in ("alerts", "both"):
        bot_state = run_alerts(bot_state, current_run=current_run)

    if args.mode in ("leaderboard", "both"):
        bot_state = run_leaderboard(bot_state, current_run=current_run)

    if args.mode == "manual_tweet":
        bot_state = run_manual_tweet(bot_state, current_run=current_run)

    if args.mode == "auto_publish_due":
        bot_state = process_due_drafts(bot_state, current_run=current_run)

    if any(source.get("status") in {"failed", "partial_failure"} for source in current_run.get("sources", [])):
        final_status = "partial_failure"

    if not state.write_state(bot_state):
        print("[main] WARNING: State write failed, retrying...")
        if not state.write_state(bot_state):
            print("[main] ERROR: State write failed twice. Drafts from this run may be lost.")
            state.log_error(bot_state, "state", "write_state failed twice")
            final_status = "failed"
    else:
        print("[main] State saved")

    state.finalize_run(bot_state, current_run, status=final_status)
    if not state.write_state(bot_state):
        print("[main] WARNING: Final run history write failed")
    print("[main] Done")


if __name__ == "__main__":
    main()
