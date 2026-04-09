"""@theheat bot orchestrator.

All generated tweets go to drafts in the state Gist.
Nothing posts automatically. Approved tweets are posted
via manual_tweet mode triggered from the dashboard.
"""

import argparse
import os
import sys
import time
from datetime import UTC, date, datetime

from src import state
from src.data import open_meteo, firms, co2, noaa_acis, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges
from src.voice import generator
from src.voice.safety import run_safety_pipeline
from src.posting.bluesky import post_to_bluesky
from src.posting.twitter import post_tweet


MAX_DRAFTS = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


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


def save_draft(tweet_text: str, bot_state: dict, tweet_type: str, event_id: str = "") -> bool:
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
        "status": "pending",
    }
    drafts.append(draft)
    print(f"[draft] Saved: {tweet_text[:60]}...")
    return True


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
            source_promoted += 1
            tweet = generator.generate_record_tweet(
                city=record.city,
                country=record.country,
                new_temp_c=record.new_temp_c,
                old_record_c=record.old_record_c,
                old_record_year=record.old_record_year,
            )
            if tweet and save_draft(tweet, bot_state, "record", record.event_id):
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
            source_promoted += 1
            tweet = generator.generate_record_low_tweet(
                city=record.city,
                country=record.country,
                new_temp_c=record.new_temp_c,
                old_record_c=record.old_record_c,
                old_record_year=record.old_record_year,
            )
            if tweet and save_draft(tweet, bot_state, "record_low", record.event_id):
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
                tweet = generator.generate_noaa_confirmation_tweet(
                    city=confirmation.city,
                    state=confirmation.state,
                    temp_f=confirmation.new_temp_f,
                    record_date=confirmation.date,
                )
                if tweet and save_draft(tweet, bot_state, "noaa_confirmation", confirm_event_id):
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
            source_promoted += 1
            tweet = generator.generate_fire_tweet(
                region=fire.nearest_city,
                country=fire.country,
                confidence=fire.confidence,
                frp=fire.frp,
            )
            if tweet and save_draft(tweet, bot_state, "fire", fire.event_id):
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
            source_promoted += 1
            tweet = generator.generate_co2_milestone_tweet(
                ppm_crossed=milestone.ppm_crossed,
                actual_ppm=milestone.actual_ppm,
            )
            if tweet and save_draft(tweet, bot_state, "co2_milestone", milestone.event_id):
                state.record_event(bot_state, milestone.event_id)
                drafted += 1
                co2_drafted_today = True
                source_drafted += 1

        # Weekly comparison (Sundays, skip if milestone already drafted today)
        if date.today().weekday() == 6 and not co2_drafted_today:
            comparison = co2.compute_weekly_comparison(readings)
            if comparison and not state.is_duplicate(bot_state, comparison.event_id):
                source_promoted += 1
                tweet = generator.generate_co2_weekly_tweet(
                    current=comparison.current_avg,
                    last_year=comparison.last_year_avg,
                    diff=comparison.difference,
                )
                if tweet and save_draft(tweet, bot_state, "co2_weekly", comparison.event_id):
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
            source_promoted += 1
            tweet = generator.generate_severe_weather_tweet(
                event_type=alert.event_type,
                area=alert.area,
                severity=alert.severity,
            )
            if tweet and save_draft(tweet, bot_state, "severe_weather", alert.event_id):
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
            source_promoted += 1
            tweet = generator.generate_global_disaster_tweet(
                disaster_type=disaster.disaster_type,
                name=disaster.name,
                country=disaster.country,
                severity=disaster.severity,
                description=disaster.description,
            )
            if tweet and save_draft(tweet, bot_state, "global_disaster", disaster.event_id):
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
                source_promoted = 1 if record and not state.is_duplicate(bot_state, record.event_id) else 0
                source_drafted = 0
                if record and not state.is_duplicate(bot_state, record.event_id):
                    tweet = generator.generate_sea_ice_record_tweet(
                        hemisphere=record.hemisphere,
                        extent=record.extent_million_km2,
                        previous_extent=record.previous_extent,
                        previous_year=record.previous_year,
                    )
                    if tweet and save_draft(tweet, bot_state, "sea_ice_record", record.event_id):
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
                    source_promoted = 1
                    tweet = generator.generate_drought_tweet(states=drought_updates)
                    if tweet and save_draft(tweet, bot_state, "drought", event_id):
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
            source_promoted = 1 if transition and not state.is_duplicate(bot_state, transition["event_id"]) else 0
            source_drafted = 0
            if transition and not state.is_duplicate(bot_state, transition["event_id"]):
                tweet = generator.generate_enso_tweet(
                    to_status=transition["to_status"],
                    oni_value=transition["oni_value"],
                    previous_duration=transition["previous_duration_months"],
                )
                if tweet and save_draft(tweet, bot_state, "enso", transition["event_id"]):
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
            source_promoted += 1
            tweet = generator.generate_extreme_wave_tweet(
                location=wave.location,
                ocean=wave.ocean,
                wave_height_m=wave.wave_height_m,
            )
            if tweet and save_draft(tweet, bot_state, "extreme_wave", wave.event_id):
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
            source_promoted += 1
            tweet = generator.generate_storm_surge_tweet(
                station_name=surge.station_name,
                state=surge.state,
                anomaly_m=surge.anomaly_m,
                observed_m=surge.observed_m,
                predicted_m=surge.predicted_m,
            )
            if tweet and save_draft(tweet, bot_state, "storm_surge", surge.event_id):
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
            source_promoted += 1
            tweet = generator.generate_river_flood_tweet(
                river=flood.river,
                location=flood.location,
                gauge_height_ft=flood.gauge_height_ft,
                flood_stage_ft=flood.flood_stage_ft,
                above_by_ft=flood.above_by_ft,
            )
            if tweet and save_draft(tweet, bot_state, "river_flood", flood.event_id):
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
        tweet = generator.generate_tweet(
            data_desc,
            fallback_fn=hot10_template,
            fallback_args={"cities": [{"city": ct.city, "anomaly_c": ct.anomaly_c} for ct in hot10]},
        )

        event_id = f"hot10_{date.today().isoformat()}"
        drafted_count = 0
        if tweet:
            drafted_count = 1 if save_draft(tweet, bot_state, "hot10", event_id) else 0

        bot_state["last_hot10"] = {
            "date": date.today().isoformat(),
            "cities": [ct.city for ct in hot10],
        }
        state.update_streaks(bot_state, [ct.city for ct in hot10])
        _record_source_run(
            current_run, "leaderboard", leaderboard_start,
            status="success", observed=len(temps), promoted=len(hot10), drafted=drafted_count
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
    draft = _find_draft(bot_state, draft_id=draft_id, tweet_text=tweet_text)
    if not tweet_text:
        print("[manual] No TWEET_TEXT provided, skipping")
        _record_source_run(
            current_run, "manual_publish", manual_start,
            status="skipped", note="No TWEET_TEXT provided"
        )
        return bot_state

    if len(tweet_text) > 280:
        print(f"[manual] Tweet too long ({len(tweet_text)} chars), skipping")
        if draft:
            draft["status"] = "pending"
            draft["post_error"] = f"Tweet too long ({len(tweet_text)} chars)"
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
        elif result == "rate_limited":
            draft["status"] = "pending"
            draft["post_error"] = "Rate limited — retry later"
            print("[manual] Rate limited, draft kept as pending for retry")
        else:
            draft["status"] = "pending"
            draft["post_error"] = "Failed to post to X"

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
        result = post_approved(draft["text"], bot_state)
        draft["last_publish_attempt_at"] = _utc_now_iso()
        if result == "posted":
            draft["status"] = "posted"
            draft["approved_at"] = draft.get("approved_at") or _utc_now_iso()
            draft["posted_at"] = _utc_now_iso()
            draft["approval_mode"] = "auto"
            draft.pop("post_error", None)
            published += 1
        elif result == "rate_limited":
            draft["post_error"] = "Rate limited — retry later"
            failures.append(f"{draft.get('id')}: rate limited")
        else:
            draft["post_error"] = "Failed to post to X"
            failures.append(f"{draft.get('id')}: failed to post")

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

    bot_state = state.read_state()
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
