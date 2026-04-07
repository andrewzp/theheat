"""@theheat bot orchestrator."""

import argparse
import sys

from src import state
from src.data import open_meteo, firms, co2
from src.voice import generator
from src.posting.twitter import post_tweet
from src.posting.bluesky import post_to_bluesky


def post_everywhere(tweet_text: str, bot_state: dict) -> bool:
    """Post to X and Bluesky. Returns True if at least one succeeded."""
    if not state.check_daily_cap(bot_state):
        print("[main] Daily tweet cap reached, skipping")
        return False

    x_result = post_tweet(tweet_text)
    bs_result = post_to_bluesky(tweet_text)
    success = x_result is not None or bs_result is not None

    if success:
        state.increment_daily_count(bot_state)

    return success


def run_alerts(bot_state: dict) -> dict:
    """Check all alert data sources and post new events."""
    posted = 0

    # 1. Heat records via Open-Meteo historical
    print("[alerts] Checking heat records...")
    try:
        cities = open_meteo.load_cities()
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
            if tweet and post_everywhere(tweet, bot_state):
                state.record_event(bot_state, record.event_id)
                posted += 1
                print(f"[alerts] Posted record: {record.city}")
    except Exception as e:
        print(f"[alerts] Heat records error: {e}")
        state.log_error(bot_state, "open_meteo_records", str(e))

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
            if tweet and post_everywhere(tweet, bot_state):
                state.record_event(bot_state, fire.event_id)
                posted += 1
                print(f"[alerts] Posted fire: {fire.nearest_city}")
    except Exception as e:
        print(f"[alerts] FIRMS error: {e}")
        state.log_error(bot_state, "firms", str(e))

    # 3. CO2 milestones
    print("[alerts] Checking CO2...")
    try:
        readings = co2.fetch_co2_data()
        milestone = co2.detect_milestone(readings)
        if milestone and not state.is_duplicate(bot_state, milestone.event_id):
            tweet = generator.generate_co2_milestone_tweet(
                ppm_crossed=milestone.ppm_crossed,
                actual_ppm=milestone.actual_ppm,
            )
            if tweet and post_everywhere(tweet, bot_state):
                state.record_event(bot_state, milestone.event_id)
                posted += 1
                print(f"[alerts] Posted CO2 milestone: {milestone.ppm_crossed} ppm")

        # Weekly comparison (post once per week on Sundays)
        from datetime import date
        if date.today().weekday() == 6:  # Sunday
            comparison = co2.compute_weekly_comparison(readings)
            if comparison and not state.is_duplicate(bot_state, comparison.event_id):
                tweet = generator.generate_co2_weekly_tweet(
                    current=comparison.current_avg,
                    last_year=comparison.last_year_avg,
                    diff=comparison.difference,
                )
                if tweet and post_everywhere(tweet, bot_state):
                    state.record_event(bot_state, comparison.event_id)
                    posted += 1
    except Exception as e:
        print(f"[alerts] CO2 error: {e}")
        state.log_error(bot_state, "co2", str(e))

    print(f"[alerts] Done. Posted {posted} tweets.")
    return bot_state


def run_leaderboard(bot_state: dict) -> dict:
    """Generate and post the daily Hot 10 leaderboard."""
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

        # Build data description for Gemini
        hot10_data = []
        for i, ct in enumerate(hot10, 1):
            hot10_data.append(
                f"{i}. {ct.city}, {ct.country}: "
                f"{ct.temp_high_c:.1f}C (normal: {ct.normal_high_c:.1f}C, "
                f"anomaly: +{ct.anomaly_c:.1f}C)"
            )

        # Check for position changes vs yesterday
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

        if tweet:
            post_everywhere(tweet, bot_state)

        # Update state
        from datetime import date
        bot_state["last_hot10"] = {
            "date": date.today().isoformat(),
            "cities": [ct.city for ct in hot10],
        }
        state.update_streaks(bot_state, [ct.city for ct in hot10])

    except Exception as e:
        print(f"[leaderboard] Error: {e}")
        state.log_error(bot_state, "leaderboard", str(e))

    return bot_state


def main():
    parser = argparse.ArgumentParser(description="@theheat climate bot")
    parser.add_argument(
        "mode",
        choices=["alerts", "leaderboard", "both"],
        help="Which content to generate and post",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't post, just print")
    args = parser.parse_args()

    print(f"[main] Starting @theheat in {args.mode} mode")

    bot_state = state.read_state()

    if args.mode in ("alerts", "both"):
        bot_state = run_alerts(bot_state)

    if args.mode in ("leaderboard", "both"):
        bot_state = run_leaderboard(bot_state)

    if not args.dry_run:
        state.write_state(bot_state)
        print("[main] State saved")
    else:
        print("[main] Dry run, state not saved")

    print("[main] Done")


if __name__ == "__main__":
    main()
