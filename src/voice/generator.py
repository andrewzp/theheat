from __future__ import annotations

"""Tweet generation via Gemini Flash with safety pipeline and fallback."""

import os

from src.voice.safety import run_safety_pipeline
from src.voice import templates

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """You are @theheat, a climate data bot with the personality of a cynical \
weatherman who's seen too much. You are dry, darkly funny, and exhausted by the relentless \
data. You never preach. You never use hashtags or emojis or exclamation points. You never \
take political positions. You just report the numbers with a tone that makes people feel \
the weight of them.

Rules:
- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- Sound tired, not angry. Dry, not dramatic.
- If this is a record, note when the old one was set.
- If this is a streak, note how long it's been going.
- Never mock human suffering or trivialize death.
- One tweet only. No thread markers.

Examples of the voice:
- "Phoenix. Again. 119F. New record. The old one was set... last year."
- "Day 47 above 110 in Phoenix. At this point the streak has its own personality."
- "Congratulations to Miami for making the Hot 10 for the first time. Nobody asked for this."
- "CO2 hit 428 ppm today. For context, it was 280 ppm for the entire history of human civilization. We're speed-running this."
- "New wildfire detected in Northern California. Satellite confidence: HIGH. 0% contained. It's April."
- "NOAA confirms: Phoenix officially broke the April record. Congratulations to no one."
- "12 consecutive months of record ocean temps. We stopped counting at 12 because that's a year."
"""

MAX_RETRIES = 3


def generate_tweet(data_description: str, fallback_fn=None, fallback_args=None) -> str | None:
    """Generate a tweet using Gemini Flash with safety checks.

    Args:
        data_description: Structured description of the data point.
        fallback_fn: Template function to call if Gemini fails.
        fallback_args: Args for the fallback function.

    Returns:
        Tweet text, or None if all attempts fail.
    """
    if not GEMINI_API_KEY:
        if fallback_fn and fallback_args:
            return fallback_fn(**fallback_args)
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception:
        if fallback_fn and fallback_args:
            return fallback_fn(**fallback_args)
        return None

    for attempt in range(MAX_RETRIES):
        try:
            prompt = f"{SYSTEM_PROMPT}\n\nWrite a tweet about this:\n{data_description}"
            response = model.generate_content(prompt)
            tweet = response.text.strip().strip('"').strip("'")

            # Run safety pipeline
            passed, reason = run_safety_pipeline(tweet)
            if passed:
                return tweet

        except Exception:
            continue

    # All retries exhausted, use template fallback
    if fallback_fn and fallback_args:
        return fallback_fn(**fallback_args)
    return None


def generate_record_tweet(
    city: str,
    country: str,
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
) -> str | None:
    temp_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_record_c * 9 / 5 + 32, 1)
    data = (
        f"{city}, {country} just recorded {temp_f}F ({new_temp_c}C) today. "
        f"The previous record for this calendar date was {old_f}F ({old_record_c}C), "
        f"set in {old_record_year}."
    )
    return generate_tweet(
        data,
        fallback_fn=templates.record_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": new_temp_c, "old_temp_c": old_record_c, "old_year": old_record_year,
        },
    )


def generate_fire_tweet(
    region: str,
    country: str,
    confidence: int,
    frp: float,
) -> str | None:
    data = (
        f"Large wildfire detected in {region}, {country}. "
        f"Satellite confidence: {confidence}%. "
        f"Fire Radiative Power: {frp:.0f} MW. "
        f"Today's date: {__import__('datetime').date.today().strftime('%B %d')}."
    )
    return generate_tweet(
        data,
        fallback_fn=templates.fire_template,
        fallback_args={
            "region": region, "country": country,
            "confidence": confidence, "frp": frp,
        },
    )


def generate_co2_milestone_tweet(ppm_crossed: int, actual_ppm: float) -> str | None:
    data = (
        f"Daily CO2 reading at Mauna Loa: {actual_ppm} ppm. "
        f"This is the first time the daily reading has been above {ppm_crossed} ppm. "
        f"Pre-industrial CO2 was about 280 ppm."
    )
    return generate_tweet(
        data,
        fallback_fn=templates.co2_milestone_template,
        fallback_args={"ppm": ppm_crossed, "actual": actual_ppm},
    )


def generate_co2_weekly_tweet(current: float, last_year: float, diff: float) -> str | None:
    data = (
        f"Average CO2 this week: {current} ppm. "
        f"Same week last year: {last_year} ppm. "
        f"Year-over-year increase: +{diff} ppm."
    )
    return generate_tweet(
        data,
        fallback_fn=templates.co2_weekly_template,
        fallback_args={"current": current, "last_year": last_year, "diff": diff},
    )


def generate_noaa_confirmation_tweet(
    city: str,
    state: str,
    temp_f: float,
    record_date: str,
) -> str | None:
    """Generate a tweet about NOAA confirming a temperature record."""
    data = (
        f"NOAA ACIS has officially confirmed: {city}, {state} broke the temperature "
        f"record on {record_date}. The recorded high was {temp_f}F."
    )
    return generate_tweet(
        data,
        fallback_fn=templates.noaa_confirmation_template,
        fallback_args={
            "city": city, "state": state,
            "temp_f": temp_f, "date": record_date,
        },
    )
