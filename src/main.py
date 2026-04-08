"""@theheat bot orchestrator.

All generated tweets go to drafts in the state Gist.
Nothing posts automatically. Approved tweets are posted
via manual_tweet mode triggered from the dashboard.
"""

import argparse
import os
import sys
from datetime import date, datetime

from src import state
from src.data import open_meteo, firms, co2, noaa_acis, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges
from src.voice import generator
from src.posting.twitter import post_tweet


MAX_DRAFTS = 200


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
        "id": f"draft_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{len(drafts)}",
        "text": tweet_text,
        "type": tweet_type,
        "event_id": event_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
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

    state.increment_daily_count(bot_state)
    print(f"[post] Posted to X: {tweet_text[:60]}...")
    return "posted"


def run_alerts(bot_state: dict) -> dict:
    """Check all alert data sources and save drafts."""
    drafted = 0
    try:
        cities = open_meteo.load_cities()
    except Exception as e:
        print(f"[alerts] Failed to load cities: {e}")
        state.log_error(bot_state, "load_cities", str(e))
        cities = []

    # 1. Heat records via Open-Meteo historical
    print("[alerts] Checking heat records...")
    try:
        records = open_meteo.check_records_for_cities(cities, max_checks=20)
        for record in records:
            if state.is_duplicate(bot_state, record.event_id):
                continue
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
    except Exception as e:
        print(f"[alerts] Heat records error: {e}")
        state.log_error(bot_state, "open_meteo_records", str(e))

    # 1a. Record lows via Open-Meteo historical
    print("[alerts] Checking record lows...")
    try:
        record_lows = open_meteo.check_record_lows_for_cities(cities, max_checks=20)
        for record in record_lows:
            if state.is_duplicate(bot_state, record.event_id):
                continue
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
    except Exception as e:
        print(f"[alerts] Record lows error: {e}")
        state.log_error(bot_state, "open_meteo_record_lows", str(e))

    # 1b. NOAA record confirmations
    print("[alerts] Checking NOAA confirmations...")
    try:
        expired = state.get_expired_confirmations(bot_state, min_hours=24)
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
                state.remove_pending_confirmation(bot_state, pending["event_id"])
    except Exception as e:
        print(f"[alerts] NOAA confirmation error: {e}")
        state.log_error(bot_state, "noaa_confirmation", str(e))

    # 2. Wildfire alerts via NASA FIRMS
    print("[alerts] Checking wildfires...")
    try:
        fires = firms.fetch_fires()
        for fire in fires:
            if state.is_duplicate(bot_state, fire.event_id):
                continue
            tweet = generator.generate_fire_tweet(
                region=fire.nearest_city,
                country=fire.country,
                confidence=fire.confidence,
                frp=fire.frp,
            )
            if tweet and save_draft(tweet, bot_state, "fire", fire.event_id):
                state.record_event(bot_state, fire.event_id)
                drafted += 1
    except Exception as e:
        print(f"[alerts] FIRMS error: {e}")
        state.log_error(bot_state, "firms", str(e))

    # 3. CO2 milestones (max one CO2 draft per day)
    print("[alerts] Checking CO2...")
    co2_drafted_today = any(
        d.get("type", "").startswith("co2")
        and d.get("created_at", "").startswith(date.today().isoformat())
        for d in bot_state.get("drafts", [])
    )
    try:
        readings = co2.fetch_co2_data()
        milestone = co2.detect_milestone(readings)
        if milestone and not co2_drafted_today and not state.is_duplicate(bot_state, milestone.event_id):
            tweet = generator.generate_co2_milestone_tweet(
                ppm_crossed=milestone.ppm_crossed,
                actual_ppm=milestone.actual_ppm,
            )
            if tweet and save_draft(tweet, bot_state, "co2_milestone", milestone.event_id):
                state.record_event(bot_state, milestone.event_id)
                drafted += 1
                co2_drafted_today = True

        # Weekly comparison (Sundays, skip if milestone already drafted today)
        if date.today().weekday() == 6 and not co2_drafted_today:
            comparison = co2.compute_weekly_comparison(readings)
            if comparison and not state.is_duplicate(bot_state, comparison.event_id):
                tweet = generator.generate_co2_weekly_tweet(
                    current=comparison.current_avg,
                    last_year=comparison.last_year_avg,
                    diff=comparison.difference,
                )
                if tweet and save_draft(tweet, bot_state, "co2_weekly", comparison.event_id):
                    state.record_event(bot_state, comparison.event_id)
                    drafted += 1
    except Exception as e:
        print(f"[alerts] CO2 error: {e}")
        state.log_error(bot_state, "co2", str(e))

    # 4. NWS severe weather alerts (US)
    print("[alerts] Checking NWS severe weather...")
    try:
        alerts = nws_alerts.fetch_alerts()
        for alert in alerts:
            if state.is_duplicate(bot_state, alert.event_id):
                continue
            tweet = generator.generate_severe_weather_tweet(
                event_type=alert.event_type,
                area=alert.area,
                severity=alert.severity,
            )
            if tweet and save_draft(tweet, bot_state, "severe_weather", alert.event_id):
                state.record_event(bot_state, alert.event_id)
                drafted += 1
    except Exception as e:
        print(f"[alerts] NWS error: {e}")
        state.log_error(bot_state, "nws_alerts", str(e))

    # 5. GDACS global disasters (Orange/Red severity)
    print("[alerts] Checking GDACS global disasters...")
    try:
        disasters = gdacs.fetch_disasters(min_severity="Orange")
        for disaster in disasters:
            if state.is_duplicate(bot_state, disaster.event_id):
                continue
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
    except Exception as e:
        print(f"[alerts] GDACS error: {e}")
        state.log_error(bot_state, "gdacs", str(e))

    # 6. Sea ice records (check weekly on Mondays to avoid hammering NSIDC)
    if date.today().weekday() == 0:
        print("[alerts] Checking sea ice records...")
        for hemisphere in ("Arctic", "Antarctic"):
            try:
                readings = sea_ice.fetch_sea_ice(hemisphere=hemisphere)
                record = sea_ice.detect_record_low(readings)
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
            except Exception as e:
                print(f"[alerts] Sea ice ({hemisphere}) error: {e}")
                state.log_error(bot_state, f"sea_ice_{hemisphere.lower()}", str(e))

    # 7. US Drought Monitor (weekly, check on Fridays after Thursday update)
    if date.today().weekday() == 4:
        print("[alerts] Checking US drought conditions...")
        try:
            drought_updates = drought.fetch_drought_data()
            if drought_updates:
                event_id = f"drought_{date.today().isoformat()}"
                if not state.is_duplicate(bot_state, event_id):
                    tweet = generator.generate_drought_tweet(states=drought_updates)
                    if tweet and save_draft(tweet, bot_state, "drought", event_id):
                        state.record_event(bot_state, event_id)
                        drafted += 1
        except Exception as e:
            print(f"[alerts] Drought error: {e}")
            state.log_error(bot_state, "drought", str(e))

    # 8. ENSO transitions (monthly, check on 1st of month)
    if date.today().day == 1:
        print("[alerts] Checking ENSO status...")
        try:
            enso_readings = enso.fetch_enso_data()
            transition = enso.detect_transition(enso_readings)
            if transition and not state.is_duplicate(bot_state, transition["event_id"]):
                tweet = generator.generate_enso_tweet(
                    to_status=transition["to_status"],
                    oni_value=transition["oni_value"],
                    previous_duration=transition["previous_duration_months"],
                )
                if tweet and save_draft(tweet, bot_state, "enso", transition["event_id"]):
                    state.record_event(bot_state, transition["event_id"])
                    drafted += 1
        except Exception as e:
            print(f"[alerts] ENSO error: {e}")
            state.log_error(bot_state, "enso", str(e))

    # 9. Extreme ocean waves (every run)
    print("[alerts] Checking ocean conditions...")
    try:
        ocean_readings = ocean.fetch_ocean_conditions()
        extreme_waves = ocean.detect_extreme_waves(ocean_readings)
        for wave in extreme_waves:
            if state.is_duplicate(bot_state, wave.event_id):
                continue
            tweet = generator.generate_extreme_wave_tweet(
                location=wave.location,
                ocean=wave.ocean,
                wave_height_m=wave.wave_height_m,
            )
            if tweet and save_draft(tweet, bot_state, "extreme_wave", wave.event_id):
                state.record_event(bot_state, wave.event_id)
                drafted += 1
    except Exception as e:
        print(f"[alerts] Ocean error: {e}")
        state.log_error(bot_state, "ocean", str(e))

    # 10. Storm surge / abnormal water levels (every run)
    print("[alerts] Checking coastal water levels...")
    try:
        wl_readings = water_levels.fetch_water_levels()
        surges = water_levels.detect_storm_surge(wl_readings)
        for surge in surges:
            if state.is_duplicate(bot_state, surge.event_id):
                continue
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
    except Exception as e:
        print(f"[alerts] Water levels error: {e}")
        state.log_error(bot_state, "water_levels", str(e))

    # 11. River flood stages (every run)
    print("[alerts] Checking river flood stages...")
    try:
        river_readings = river_gauges.fetch_river_levels()
        floods = river_gauges.detect_floods(river_readings)
        for flood in floods:
            if state.is_duplicate(bot_state, flood.event_id):
                continue
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
    except Exception as e:
        print(f"[alerts] River gauges error: {e}")
        state.log_error(bot_state, "river_gauges", str(e))

    print(f"[alerts] Done. Saved {drafted} drafts.")
    return bot_state


def run_leaderboard(bot_state: dict) -> dict:
    """Generate the daily Hot 10 leaderboard as a draft."""
    print("[leaderboard] Generating Hot 10...")
    try:
        cities = open_meteo.load_cities()
        normals = open_meteo.load_normals()
        temps = open_meteo.fetch_all_city_temps(cities)

        if not temps:
            print("[leaderboard] No temperature data available")
            return bot_state

        temps_with_anomalies = open_meteo.compute_anomalies(temps, normals)
        hot10 = open_meteo.rank_hot10(temps_with_anomalies)

        if not hot10:
            print("[leaderboard] No valid anomalies to rank")
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
        if tweet:
            save_draft(tweet, bot_state, "hot10", event_id)

        bot_state["last_hot10"] = {
            "date": date.today().isoformat(),
            "cities": [ct.city for ct in hot10],
        }
        state.update_streaks(bot_state, [ct.city for ct in hot10])

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))

    return bot_state


def run_manual_tweet(bot_state: dict) -> dict:
    """Post an approved tweet from the TWEET_TEXT env var."""
    tweet_text = os.environ.get("TWEET_TEXT", "").strip()
    if not tweet_text:
        print("[manual] No TWEET_TEXT provided, skipping")
        return bot_state

    if len(tweet_text) > 280:
        print(f"[manual] Tweet too long ({len(tweet_text)} chars), skipping")
        return bot_state

    print(f"[manual] Posting: {tweet_text}")
    result = post_approved(tweet_text, bot_state)

    # Update draft status with post result
    for draft in bot_state.get("drafts", []):
        if draft.get("text") == tweet_text and draft.get("status") == "approved":
            if result == "posted":
                draft["status"] = "posted"
                draft["posted_at"] = datetime.utcnow().isoformat() + "Z"
            elif result == "rate_limited":
                draft["status"] = "pending"
                draft["post_error"] = "Rate limited — retry later"
                print("[manual] Rate limited, draft kept as pending for retry")
            else:
                draft["post_error"] = "Failed to post to X"
            break

    return bot_state


def main():
    parser = argparse.ArgumentParser(description="@theheat climate bot")
    parser.add_argument(
        "mode",
        choices=["alerts", "leaderboard", "both", "manual_tweet"],
        help="Which content to generate and post",
    )
    args = parser.parse_args()

    print(f"[main] Starting @theheat in {args.mode} mode")

    bot_state = state.read_state()

    if args.mode in ("alerts", "both"):
        bot_state = run_alerts(bot_state)

    if args.mode in ("leaderboard", "both"):
        bot_state = run_leaderboard(bot_state)

    if args.mode == "manual_tweet":
        bot_state = run_manual_tweet(bot_state)

    if not state.write_state(bot_state):
        print("[main] WARNING: State write failed, retrying...")
        if not state.write_state(bot_state):
            print("[main] ERROR: State write failed twice. Drafts from this run may be lost.")
            state.log_error(bot_state, "state", "write_state failed twice")
    else:
        print("[main] State saved")
    print("[main] Done")


if __name__ == "__main__":
    main()
