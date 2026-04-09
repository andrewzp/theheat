"""@theheat bot orchestrator.

All generated tweets go to drafts in the shared state store.
Low-sensitivity drafts (Hot 10, CO2, official confirmations) may
auto-post after a timed delay if both signal and copy scores are
strong. Human-impact events (fires, disasters, floods, severe
weather) always require manual approval via the dashboard.
"""

import argparse
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta

from src import state
from src.data import open_meteo, firms, co2, noaa_acis, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges
from src.editorial.approval import recommend_approval_policy
from src.editorial.candidates import CandidateBundle
from src.editorial.scoring import (
    EditorialScore,
    score_co2_milestone,
    score_co2_weekly,
    score_drought,
    score_enso_transition,
    score_extreme_wave,
    score_fire_event,
    score_global_disaster,
    score_hot10,
    score_noaa_confirmation_event,
    score_record_event,
    score_record_low_event,
    score_river_flood,
    score_sea_ice_record,
    score_severe_weather,
    score_storm_surge,
)
from src.voice import generator
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


def _find_draft(bot_state: dict, draft_id: str = "", tweet_text: str = "") -> dict | None:
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
    source: str,
    started_at: float,
    *,
    status: str,
    observed: int = 0,
    promoted: int = 0,
    drafted: int = 0,
    error: str | None = None,
    note: str | None = None,
) -> None:
    """Track a source result when run telemetry is enabled."""
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
    )


def _should_draft(score: EditorialScore, event_id: str = "") -> bool:
    """Decide whether an event is strong enough to enter the draft queue."""
    if score.passes:
        return True
    event_desc = f" {event_id}" if event_id else ""
    print(
        f"[score] Suppressed{event_desc}: {score.category} "
        f"{score.total} < {score.threshold} ({', '.join(score.reasons)})"
    )
    return False


def _unwrap_generated_result(
    generated: str | CandidateBundle | object | None,
) -> tuple[str, list[dict] | None, dict | None]:
    if generated is None:
        return "", None, None

    if isinstance(generated, str):
        return generated, None, None

    if isinstance(generated, CandidateBundle):
        candidates = [candidate.as_dict() for candidate in generated.candidates]
        selected_score = generated.selected_score.as_dict() if generated.selected_score else None
        return generated.text, candidates, selected_score

    text = getattr(generated, "text", "") if isinstance(getattr(generated, "text", ""), str) else ""
    candidates = getattr(generated, "candidates", None)
    selected_score = getattr(generated, "selected_score", None)

    candidate_payload = None
    if candidates:
        candidate_payload = []
        for candidate in candidates:
            if hasattr(candidate, "as_dict"):
                candidate_payload.append(candidate.as_dict())
            elif isinstance(candidate, dict):
                candidate_payload.append(candidate)

    selected_payload = selected_score.as_dict() if hasattr(selected_score, "as_dict") else selected_score
    return text, candidate_payload, selected_payload


def _fact(label: str, value: str | int | float | None) -> dict | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return {"label": label, "value": text}


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


def save_draft(
    tweet_text: str,
    bot_state: dict,
    tweet_type: str,
    event_id: str = "",
    score: EditorialScore | None = None,
    candidates: list[dict] | None = None,
    candidate_score: dict | None = None,
    review_context: dict | None = None,
) -> bool:
    """Save a generated tweet as a draft for review."""
    drafts = bot_state.setdefault("drafts", [])

    # Don't duplicate drafts for the same event
    if event_id and any(d.get("event_id") == event_id for d in drafts):
        print(f"[draft] Already drafted: {event_id}")
        return False

    # Prune oldest non-pending drafts to prevent unbounded growth
    if len(drafts) >= MAX_DRAFTS:
        before = len(drafts)
        bot_state["drafts"] = [
            d for d in drafts if d.get("status") == "pending"
        ][-MAX_DRAFTS:]
        drafts = bot_state["drafts"]
        print(f"[draft] Pruned {before - len(drafts)} old drafts")

    draft = {
        "id": f"draft_{_utc_now().strftime('%Y%m%d_%H%M%S')}_{len(drafts)}",
        "text": tweet_text,
        "type": tweet_type,
        "event_id": event_id,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "status": "pending",
    }
    if score is not None:
        draft["score"] = score.as_dict()
    if candidates:
        draft["candidates"] = candidates
    if candidate_score:
        draft["candidate_score"] = candidate_score
    if review_context:
        draft["review_context"] = review_context

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
    bot_state: dict,
    tweet_type: str,
    event_id: str,
    score: EditorialScore,
    review_context: dict | None = None,
) -> bool:
    tweet_text, candidates, candidate_score = _unwrap_generated_result(generated)
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
    )


def post_approved(tweet_text: str, bot_state: dict) -> str:
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


def run_alerts(bot_state: dict, current_run: dict | None = None) -> dict:
    """Check all alert data sources and save drafts."""
    drafted = 0
    cities_start = time.perf_counter()
    try:
        cities = open_meteo.load_cities()
        _record_source_run(
            current_run, "load_cities", cities_start,
            status="success", observed=len(cities), promoted=len(cities)
        )
    except Exception as e:
        print(f"[alerts] Failed to load cities: {e}")
        state.log_error(bot_state, "load_cities", str(e))
        cities = []
        _record_source_run(
            current_run, "load_cities", cities_start,
            status="failed", error=str(e)
        )

    # 1. Heat records via Open-Meteo historical
    print("[alerts] Checking heat records...")
    records_start = time.perf_counter()
    try:
        records = open_meteo.check_records_for_cities(cities, max_checks=20)
        source_promoted = 0
        source_drafted = 0
        for record in records:
            if state.is_duplicate(bot_state, record.event_id):
                continue
            score = score_record_event(record.new_temp_c, record.old_record_c, record.old_record_year)
            if not _should_draft(score, record.event_id):
                continue
            source_promoted += 1
            generated = generator.generate_record_tweet(
                city=record.city,
                country=record.country,
                new_temp_c=record.new_temp_c,
                old_record_c=record.old_record_c,
                old_record_year=record.old_record_year,
                return_bundle=True,
            )
            review_context = _review_context(
                source="Open-Meteo historical",
                source_key="open_meteo_records",
                headline=f"{record.city} set a heat record",
                current_run=current_run,
                facts=[
                    _fact("New high", _temp_pair_c(record.new_temp_c)),
                    _fact("Previous record", _temp_pair_c(record.old_record_c)),
                    _fact("Old record year", record.old_record_year),
                    _fact("Record gap", f"+{record.new_temp_c - record.old_record_c:.1f}C"),
                    _fact("Country", record.country),
                ],
            )
            if _save_generated_draft(generated, bot_state, "record", record.event_id, score, review_context=review_context):
                state.record_event(bot_state, record.event_id)
                drafted += 1
                source_drafted += 1

            # Queue US records for later NOAA confirmation
            if record.country == "US":
                state.add_pending_confirmation(bot_state, {
                    "event_id": record.event_id,
                    "detected": date.today().isoformat(),
                    "source": "open-meteo",
                    "city": record.city,
                    "state_code": noaa_acis.get_state_code(record.city),
                    "country": record.country,
                })
        _record_source_run(
            current_run, "open_meteo_records", records_start,
            status="success", observed=len(records), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] Heat records error: {e}")
        state.log_error(bot_state, "open_meteo_records", str(e))
        _record_source_run(
            current_run, "open_meteo_records", records_start,
            status="failed", error=str(e)
        )

    # 1a. Record lows via Open-Meteo historical
    print("[alerts] Checking record lows...")
    record_lows_start = time.perf_counter()
    try:
        record_lows = open_meteo.check_record_lows_for_cities(cities, max_checks=20)
        source_promoted = 0
        source_drafted = 0
        for record in record_lows:
            if state.is_duplicate(bot_state, record.event_id):
                continue
            score = score_record_low_event(record.new_temp_c, record.old_record_c, record.old_record_year)
            if not _should_draft(score, record.event_id):
                continue
            source_promoted += 1
            generated = generator.generate_record_low_tweet(
                city=record.city,
                country=record.country,
                new_temp_c=record.new_temp_c,
                old_record_c=record.old_record_c,
                old_record_year=record.old_record_year,
                return_bundle=True,
            )
            review_context = _review_context(
                source="Open-Meteo historical",
                source_key="open_meteo_record_lows",
                headline=f"{record.city} set a cold record",
                current_run=current_run,
                facts=[
                    _fact("New low", _temp_pair_c(record.new_temp_c)),
                    _fact("Previous low", _temp_pair_c(record.old_record_c)),
                    _fact("Old record year", record.old_record_year),
                    _fact("Record gap", f"-{record.old_record_c - record.new_temp_c:.1f}C"),
                    _fact("Country", record.country),
                ],
            )
            if _save_generated_draft(generated, bot_state, "record_low", record.event_id, score, review_context=review_context):
                state.record_event(bot_state, record.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "open_meteo_record_lows", record_lows_start,
            status="success", observed=len(record_lows), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] Record lows error: {e}")
        state.log_error(bot_state, "open_meteo_record_lows", str(e))
        _record_source_run(
            current_run, "open_meteo_record_lows", record_lows_start,
            status="failed", error=str(e)
        )

    # 1b. NOAA record confirmations
    print("[alerts] Checking NOAA confirmations...")
    noaa_start = time.perf_counter()
    try:
        expired = state.get_expired_confirmations(bot_state, min_hours=24)
        source_drafted = 0
        for pending in expired:
            if pending.get("country") != "US":
                state.remove_pending_confirmation(bot_state, pending["event_id"])
                continue

            confirm_event_id = f"noaa_confirm_{pending['city'].replace(' ', '_')}_{pending['detected']}"
            if state.is_duplicate(bot_state, confirm_event_id):
                state.remove_pending_confirmation(bot_state, pending["event_id"])
                continue

            confirmation = noaa_acis.check_record_confirmation(
                city=pending["city"],
                state_code=pending.get("state_code"),
                record_date=pending["detected"],
            )
            if confirmation:
                score = score_noaa_confirmation_event(confirmation.new_temp_f)
                if not _should_draft(score, confirm_event_id):
                    state.remove_pending_confirmation(bot_state, pending["event_id"])
                    continue
                generated = generator.generate_noaa_confirmation_tweet(
                    city=confirmation.city,
                    state=confirmation.state,
                    temp_f=confirmation.new_temp_f,
                    record_date=confirmation.date,
                    return_bundle=True,
                )
                review_context = _review_context(
                    source="NOAA ACIS",
                    source_key="noaa_confirmation",
                    headline=f"NOAA confirmed {confirmation.city}'s record",
                    current_run=current_run,
                    facts=[
                        _fact("Official high", f"{confirmation.new_temp_f:.0f}F"),
                        _fact("Record date", confirmation.date),
                        _fact("City", confirmation.city),
                        _fact("State", confirmation.state),
                    ],
                )
                if _save_generated_draft(generated, bot_state, "noaa_confirmation", confirm_event_id, score, review_context=review_context):
                    state.record_event(bot_state, confirm_event_id)
                    drafted += 1
                    source_drafted += 1
                state.remove_pending_confirmation(bot_state, pending["event_id"])
        _record_source_run(
            current_run, "noaa_confirmation", noaa_start,
            status="success", observed=len(expired), promoted=len(expired), drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] NOAA confirmation error: {e}")
        state.log_error(bot_state, "noaa_confirmation", str(e))
        _record_source_run(
            current_run, "noaa_confirmation", noaa_start,
            status="failed", error=str(e)
        )

    # 2. Wildfire alerts via NASA FIRMS
    print("[alerts] Checking wildfires...")
    firms_start = time.perf_counter()
    try:
        fires = firms.fetch_fires()
        source_promoted = 0
        source_drafted = 0
        for fire in fires:
            if state.is_duplicate(bot_state, fire.event_id):
                continue
            score = score_fire_event(fire.confidence, fire.frp, region=fire.nearest_city)
            if not _should_draft(score, fire.event_id):
                continue
            source_promoted += 1
            generated = generator.generate_fire_tweet(
                region=fire.nearest_city,
                country=fire.country,
                confidence=fire.confidence,
                frp=fire.frp,
                return_bundle=True,
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
            if _save_generated_draft(generated, bot_state, "fire", fire.event_id, score, review_context=review_context):
                state.record_event(bot_state, fire.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "firms", firms_start,
            status="success", observed=len(fires), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] FIRMS error: {e}")
        state.log_error(bot_state, "firms", str(e))
        _record_source_run(
            current_run, "firms", firms_start,
            status="failed", error=str(e)
        )

    # 3. CO2 milestones (max one CO2 draft per day)
    print("[alerts] Checking CO2...")
    co2_drafted_today = any(
        d.get("type", "").startswith("co2")
        and d.get("created_at", "").startswith(date.today().isoformat())
        for d in bot_state.get("drafts", [])
    )
    co2_start = time.perf_counter()
    try:
        readings = co2.fetch_co2_data()
        milestone = co2.detect_milestone(readings)
        source_promoted = 0
        source_drafted = 0
        if milestone and not co2_drafted_today and not state.is_duplicate(bot_state, milestone.event_id):
            score = score_co2_milestone(milestone.ppm_crossed, milestone.actual_ppm)
            if _should_draft(score, milestone.event_id):
                source_promoted += 1
                generated = generator.generate_co2_milestone_tweet(
                    ppm_crossed=milestone.ppm_crossed,
                    actual_ppm=milestone.actual_ppm,
                    return_bundle=True,
                )
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
                if _save_generated_draft(generated, bot_state, "co2_milestone", milestone.event_id, score, review_context=review_context):
                    state.record_event(bot_state, milestone.event_id)
                    drafted += 1
                    co2_drafted_today = True
                    source_drafted += 1

        # Weekly comparison (Sundays, skip if milestone already drafted today)
        if date.today().weekday() == 6 and not co2_drafted_today:
            comparison = co2.compute_weekly_comparison(readings)
            if comparison and not state.is_duplicate(bot_state, comparison.event_id):
                score = score_co2_weekly(comparison.difference)
                if _should_draft(score, comparison.event_id):
                    source_promoted += 1
                    generated = generator.generate_co2_weekly_tweet(
                        current=comparison.current_avg,
                        last_year=comparison.last_year_avg,
                        diff=comparison.difference,
                        return_bundle=True,
                    )
                    review_context = _review_context(
                        source="NOAA GML",
                        source_key="co2",
                        headline="Weekly Mauna Loa CO2 comparison",
                        current_run=current_run,
                        facts=[
                            _fact("This week", f"{comparison.current_avg:.2f} ppm"),
                            _fact("Same week last year", f"{comparison.last_year_avg:.2f} ppm"),
                            _fact("Year-over-year change", f"{comparison.difference:+.2f} ppm"),
                        ],
                    )
                    if _save_generated_draft(generated, bot_state, "co2_weekly", comparison.event_id, score, review_context=review_context):
                        state.record_event(bot_state, comparison.event_id)
                        drafted += 1
                        source_drafted += 1
        _record_source_run(
            current_run, "co2", co2_start,
            status="success", observed=len(readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] CO2 error: {e}")
        state.log_error(bot_state, "co2", str(e))
        _record_source_run(
            current_run, "co2", co2_start,
            status="failed", error=str(e)
        )

    # 4. NWS severe weather alerts (US)
    print("[alerts] Checking NWS severe weather...")
    nws_start = time.perf_counter()
    try:
        alerts = nws_alerts.fetch_alerts()
        source_promoted = 0
        source_drafted = 0
        for alert in alerts:
            if state.is_duplicate(bot_state, alert.event_id):
                continue
            score = score_severe_weather(alert.event_type, alert.severity)
            if not _should_draft(score, alert.event_id):
                continue
            source_promoted += 1
            generated = generator.generate_severe_weather_tweet(
                event_type=alert.event_type,
                area=alert.area,
                severity=alert.severity,
                return_bundle=True,
            )
            review_context = _review_context(
                source="NWS Alerts",
                source_key="nws_alerts",
                headline=f"{alert.event_type} for {alert.area}",
                current_run=current_run,
                facts=[
                    _fact("Event", alert.event_type),
                    _fact("Area", alert.area),
                    _fact("Severity", alert.severity),
                ],
            )
            if _save_generated_draft(generated, bot_state, "severe_weather", alert.event_id, score, review_context=review_context):
                state.record_event(bot_state, alert.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "nws_alerts", nws_start,
            status="success", observed=len(alerts), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] NWS error: {e}")
        state.log_error(bot_state, "nws_alerts", str(e))
        _record_source_run(
            current_run, "nws_alerts", nws_start,
            status="failed", error=str(e)
        )

    # 5. GDACS global disasters (Orange/Red severity)
    print("[alerts] Checking GDACS global disasters...")
    gdacs_start = time.perf_counter()
    try:
        disasters = gdacs.fetch_disasters(min_severity="Orange")
        source_promoted = 0
        source_drafted = 0
        for disaster in disasters:
            if state.is_duplicate(bot_state, disaster.event_id):
                continue
            score = score_global_disaster(disaster.severity, disaster.disaster_type)
            if not _should_draft(score, disaster.event_id):
                continue
            source_promoted += 1
            generated = generator.generate_global_disaster_tweet(
                disaster_type=disaster.disaster_type,
                name=disaster.name,
                country=disaster.country,
                severity=disaster.severity,
                description=disaster.description,
                return_bundle=True,
            )
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
            if _save_generated_draft(generated, bot_state, "global_disaster", disaster.event_id, score, review_context=review_context):
                state.record_event(bot_state, disaster.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "gdacs", gdacs_start,
            status="success", observed=len(disasters), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] GDACS error: {e}")
        state.log_error(bot_state, "gdacs", str(e))
        _record_source_run(
            current_run, "gdacs", gdacs_start,
            status="failed", error=str(e)
        )

    # 6. Sea ice records (check weekly on Mondays to avoid hammering NSIDC)
    if date.today().weekday() == 0:
        print("[alerts] Checking sea ice records...")
        for hemisphere in ("Arctic", "Antarctic"):
            sea_ice_start = time.perf_counter()
            try:
                readings = sea_ice.fetch_sea_ice(hemisphere=hemisphere)
                record = sea_ice.detect_record_low(readings)
                score = None
                if record and not state.is_duplicate(bot_state, record.event_id):
                    score = score_sea_ice_record(
                        record.extent_million_km2,
                        record.previous_extent,
                        record.previous_year,
                    )
                source_promoted = 1 if score and _should_draft(score, record.event_id) else 0
                source_drafted = 0
                if record and source_promoted:
                    generated = generator.generate_sea_ice_record_tweet(
                        hemisphere=record.hemisphere,
                        extent=record.extent_million_km2,
                        previous_extent=record.previous_extent,
                        previous_year=record.previous_year,
                        return_bundle=True,
                    )
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
                    if _save_generated_draft(generated, bot_state, "sea_ice_record", record.event_id, score, review_context=review_context):
                        state.record_event(bot_state, record.event_id)
                        drafted += 1
                        source_drafted = 1
                observed = len(readings) if hasattr(readings, "__len__") else 0
                _record_source_run(
                    current_run, f"sea_ice_{hemisphere.lower()}", sea_ice_start,
                    status="success", observed=observed, promoted=source_promoted, drafted=source_drafted
                )
            except Exception as e:
                print(f"[alerts] Sea ice ({hemisphere}) error: {e}")
                state.log_error(bot_state, f"sea_ice_{hemisphere.lower()}", str(e))
                _record_source_run(
                    current_run, f"sea_ice_{hemisphere.lower()}", sea_ice_start,
                    status="failed", error=str(e)
                )
    else:
        for hemisphere in ("Arctic", "Antarctic"):
            skipped_start = time.perf_counter()
            _record_source_run(
                current_run, f"sea_ice_{hemisphere.lower()}", skipped_start,
                status="skipped", note="Runs Mondays only"
            )

    # 7. US Drought Monitor (weekly, check on Fridays after Thursday update)
    if date.today().weekday() == 4:
        print("[alerts] Checking US drought conditions...")
        drought_start = time.perf_counter()
        try:
            drought_updates = drought.fetch_drought_data()
            source_promoted = 0
            source_drafted = 0
            if drought_updates:
                event_id = f"drought_{date.today().isoformat()}"
                if not state.is_duplicate(bot_state, event_id):
                    score = score_drought(drought_updates)
                    if _should_draft(score, event_id):
                        source_promoted = 1
                        generated = generator.generate_drought_tweet(states=drought_updates, return_bundle=True)
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
                        if _save_generated_draft(generated, bot_state, "drought", event_id, score, review_context=review_context):
                            state.record_event(bot_state, event_id)
                            drafted += 1
                            source_drafted = 1
            _record_source_run(
                current_run, "drought", drought_start,
                status="success", observed=len(drought_updates), promoted=source_promoted, drafted=source_drafted
            )
        except Exception as e:
            print(f"[alerts] Drought error: {e}")
            state.log_error(bot_state, "drought", str(e))
            _record_source_run(
                current_run, "drought", drought_start,
                status="failed", error=str(e)
            )
    else:
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, "drought", skipped_start,
            status="skipped", note="Runs Fridays only"
        )

    # 8. ENSO transitions (monthly, check on 1st of month)
    if date.today().day == 1:
        print("[alerts] Checking ENSO status...")
        enso_start = time.perf_counter()
        try:
            enso_readings = enso.fetch_enso_data()
            transition = enso.detect_transition(enso_readings)
            score = None
            if transition and not state.is_duplicate(bot_state, transition["event_id"]):
                score = score_enso_transition(
                    transition["oni_value"],
                    transition["previous_duration_months"],
                )
            source_promoted = 1 if score and _should_draft(score, transition["event_id"]) else 0
            source_drafted = 0
            if transition and source_promoted:
                generated = generator.generate_enso_tweet(
                    to_status=transition["to_status"],
                    oni_value=transition["oni_value"],
                    previous_duration=transition["previous_duration_months"],
                    return_bundle=True,
                )
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
                if _save_generated_draft(generated, bot_state, "enso", transition["event_id"], score, review_context=review_context):
                    state.record_event(bot_state, transition["event_id"])
                    drafted += 1
                    source_drafted = 1
            observed = len(enso_readings) if hasattr(enso_readings, "__len__") else 0
            _record_source_run(
                current_run, "enso", enso_start,
                status="success", observed=observed, promoted=source_promoted, drafted=source_drafted
            )
        except Exception as e:
            print(f"[alerts] ENSO error: {e}")
            state.log_error(bot_state, "enso", str(e))
            _record_source_run(
                current_run, "enso", enso_start,
                status="failed", error=str(e)
            )
    else:
        skipped_start = time.perf_counter()
        _record_source_run(
            current_run, "enso", skipped_start,
            status="skipped", note="Runs on the 1st of the month"
        )

    # 9. Extreme ocean waves (every run)
    print("[alerts] Checking ocean conditions...")
    ocean_start = time.perf_counter()
    try:
        ocean_readings = ocean.fetch_ocean_conditions()
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
            generated = generator.generate_extreme_wave_tweet(
                location=wave.location,
                ocean=wave.ocean,
                wave_height_m=wave.wave_height_m,
                return_bundle=True,
            )
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
            if _save_generated_draft(generated, bot_state, "extreme_wave", wave.event_id, score, review_context=review_context):
                state.record_event(bot_state, wave.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "ocean", ocean_start,
            status="success", observed=len(ocean_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] Ocean error: {e}")
        state.log_error(bot_state, "ocean", str(e))
        _record_source_run(
            current_run, "ocean", ocean_start,
            status="failed", error=str(e)
        )

    # 10. Storm surge / abnormal water levels (every run)
    print("[alerts] Checking coastal water levels...")
    water_levels_start = time.perf_counter()
    try:
        wl_readings = water_levels.fetch_water_levels()
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
            generated = generator.generate_storm_surge_tweet(
                station_name=surge.station_name,
                state=surge.state,
                anomaly_m=surge.anomaly_m,
                observed_m=surge.observed_m,
                predicted_m=surge.predicted_m,
                return_bundle=True,
            )
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
            if _save_generated_draft(generated, bot_state, "storm_surge", surge.event_id, score, review_context=review_context):
                state.record_event(bot_state, surge.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "water_levels", water_levels_start,
            status="success", observed=len(wl_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] Water levels error: {e}")
        state.log_error(bot_state, "water_levels", str(e))
        _record_source_run(
            current_run, "water_levels", water_levels_start,
            status="failed", error=str(e)
        )

    # 11. River flood stages (every run)
    print("[alerts] Checking river flood stages...")
    river_start = time.perf_counter()
    try:
        river_readings = river_gauges.fetch_river_levels()
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
            generated = generator.generate_river_flood_tweet(
                river=flood.river,
                location=flood.location,
                gauge_height_ft=flood.gauge_height_ft,
                flood_stage_ft=flood.flood_stage_ft,
                above_by_ft=flood.above_by_ft,
                return_bundle=True,
            )
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
            if _save_generated_draft(generated, bot_state, "river_flood", flood.event_id, score, review_context=review_context):
                state.record_event(bot_state, flood.event_id)
                drafted += 1
                source_drafted += 1
        _record_source_run(
            current_run, "river_gauges", river_start,
            status="success", observed=len(river_readings), promoted=source_promoted, drafted=source_drafted
        )
    except Exception as e:
        print(f"[alerts] River gauges error: {e}")
        state.log_error(bot_state, "river_gauges", str(e))
        _record_source_run(
            current_run, "river_gauges", river_start,
            status="failed", error=str(e)
        )

    print(f"[alerts] Done. Saved {drafted} drafts.")
    return bot_state


def run_leaderboard(bot_state: dict, current_run: dict | None = None) -> dict:
    """Generate the daily Hot 10 leaderboard as a draft."""
    print("[leaderboard] Generating Hot 10...")
    leaderboard_start = time.perf_counter()
    try:
        cities = open_meteo.load_cities()
        normals = open_meteo.load_normals()
        temps = open_meteo.fetch_all_city_temps(cities)

        if not temps:
            print("[leaderboard] No temperature data available")
            _record_source_run(
                current_run, "leaderboard", leaderboard_start,
                status="success", observed=0, promoted=0, drafted=0, note="No temperature data available"
            )
            return bot_state

        temps_with_anomalies = open_meteo.compute_anomalies(temps, normals)
        hot10 = open_meteo.rank_hot10(temps_with_anomalies)

        if not hot10:
            print("[leaderboard] No valid anomalies to rank")
            _record_source_run(
                current_run, "leaderboard", leaderboard_start,
                status="success", observed=len(temps), promoted=0, drafted=0, note="No valid anomalies to rank"
            )
            return bot_state

        hot10_data = []
        for i, ct in enumerate(hot10, 1):
            hot10_data.append(
                f"{i}. {ct.city}, {ct.country}: "
                f"{ct.temp_high_c:.1f}C (normal: {ct.normal_high_c:.1f}C, "
                f"anomaly: +{ct.anomaly_c:.1f}C)"
            )

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

        data_desc = "Today's Hot 10 cities by temperature anomaly (how far above normal):\n"
        data_desc += "\n".join(hot10_data)
        if changes:
            data_desc += "\n\nChanges from yesterday: " + ", ".join(changes[:3])

        from src.voice.templates import hot10_template
        top_anomaly = hot10[0].anomaly_c if hot10 else 0.0
        score = score_hot10(top_anomaly, len(hot10), len(changes))
        generated = generator.generate_tweet(
            data_desc,
            category="hot10",
            return_bundle=True,
            fallback_fn=hot10_template,
            fallback_args={"cities": [{"city": ct.city, "anomaly_c": ct.anomaly_c} for ct in hot10]},
        )

        event_id = f"hot10_{date.today().isoformat()}"
        drafted_count = 0
        if generated and _should_draft(score, event_id):
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
            drafted_count = 1 if _save_generated_draft(generated, bot_state, "hot10", event_id, score, review_context=review_context) else 0

        bot_state["last_hot10"] = {
            "date": date.today().isoformat(),
            "cities": [ct.city for ct in hot10],
        }
        state.update_streaks(bot_state, [ct.city for ct in hot10])
        _record_source_run(
            current_run, "leaderboard", leaderboard_start,
            status="success", observed=len(temps), promoted=len(hot10) if score.passes else 0, drafted=drafted_count
        )

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))
        _record_source_run(
            current_run, "leaderboard", leaderboard_start,
            status="failed", error=str(e)
        )

    return bot_state


def run_manual_tweet(bot_state: dict, current_run: dict | None = None) -> dict:
    """Post an approved tweet from the TWEET_TEXT env var."""
    manual_start = time.perf_counter()
    tweet_text = os.environ.get("TWEET_TEXT", "").strip()
    draft_id = os.environ.get("DRAFT_ID", "").strip()
    publish_intent_id = os.environ.get("PUBLISH_INTENT_ID", "").strip()
    draft = _find_draft(bot_state, draft_id=draft_id, tweet_text=tweet_text)
    if not tweet_text:
        print("[manual] No TWEET_TEXT provided, skipping")
        _record_source_run(
            current_run, "manual_publish", manual_start,
            status="skipped", note="No TWEET_TEXT provided"
        )
        return bot_state

    if draft_id and not draft:
        reason = f"Draft not found for id {draft_id}"
        print(f"[manual] {reason}, skipping")
        _record_source_run(
            current_run, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    if draft_id and draft and draft.get("status") == "posted":
        print(f"[manual] Draft {draft_id} already posted, skipping duplicate publish")
        _record_source_run(
            current_run, "manual_publish", manual_start,
            status="skipped", observed=1, note=f"Draft {draft_id} already posted"
        )
        return bot_state

    if draft_id and draft and draft.get("status") != "approved":
        reason = f"Draft {draft_id} is not approved for publishing"
        print(f"[manual] {reason}")
        _record_source_run(
            current_run, "manual_publish", manual_start,
            status="failed", observed=1, error=reason
        )
        return bot_state

    if draft_id and draft and publish_intent_id and draft.get("publish_intent_id") != publish_intent_id:
        reason = f"Draft {draft_id} publish intent is stale"
        print(f"[manual] {reason}, skipping")
        _record_source_run(
            current_run, "manual_publish", manual_start,
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
            current_run, "manual_publish", manual_start,
            status="failed", observed=1, error=f"Tweet too long ({len(tweet_text)} chars)"
        )
        return bot_state

    passed, reason = run_safety_pipeline(tweet_text)
    if not passed:
        print(f"[manual] Safety rejected tweet: {reason}")
        if draft:
            draft["status"] = "pending"
            draft["post_error"] = reason
            draft.pop("publish_intent_id", None)
            _touch_draft(draft)
        _record_source_run(
            current_run, "manual_publish", manual_start,
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
        current_run, "manual_publish", manual_start,
        status=source_status, observed=1, promoted=1, drafted=1 if result == "posted" else 0, error=error
    )
    return bot_state


def process_due_drafts(bot_state: dict, current_run: dict | None = None) -> dict:
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
            current_run, "auto_publish_due", queue_start,
            status="skipped", observed=0, note="No drafts due for auto-approval"
        )
        return bot_state

    published = 0
    failures = []
    for draft in due_drafts:
        policy = draft.get("approval_policy", {})
        if policy.get("mode") != "armed_auto" or policy.get("can_auto_approve") is False:
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
        current_run, "auto_publish_due", queue_start,
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
