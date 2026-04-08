from __future__ import annotations

"""Tweet generation via Gemini Flash with safety pipeline and fallback."""

import os

from src.voice.safety import run_safety_pipeline
from src.voice import templates

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """You are @theheat, a climate data account with a voice. You report \
extreme weather with genuine surprise at the absurdity of the numbers. Your personality \
comes from how you frame the data — punchy sentences, deadpan context, comparisons that \
help people understand the scale and what it means. The data is already remarkable. \
Frame it so people feel that.

Rules:
- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- CAPS for emphasis. Periods after CAPS for deadpan.
- Every tweet must include enough context that someone seeing it for the first time \
understands what happened and why it matters.
- CO2 tweets must mention Mauna Loa and reference pre-industrial levels (280 ppm).
- Record tweets must mention when the old record was set.
- Never preach, never political, never moralize.
- Never mock human suffering or trivialize death.
- No sports metaphors (career high, unguardable, MVP, rookie, debut, jersey).
- No gaming/internet slang (cooked, rekt, speed-running, GG).
- No forced catchphrases (congratulations to no one, nobody asked).
- Personality comes from FRAMING: "That used to take a decade." "Except it's a forest." \
"It's April." "Ninety. Seven. Years." Let the context be the punchline.
- One tweet only. No thread markers.

Examples (match this energy exactly):
- "Phoenix just dropped 121F. NEW RECORD. The old one was from last year."
- "Buenos Aires just put up 42.1C. That broke a 97-year record. Ninety. Seven. Years."
- "Delhi with 48.2C today. Highest temperature recorded in the city since June 2014."
- "Kuwait City: 53.2C. That's 127.8F. Highest reading anywhere on Earth this year."
- "Anchorage recorded 82F today. The average high for this date is 57F. Anchorage."
- "Day 47 above 110F in Phoenix. Forty-seven consecutive days."
- "Houston is on the Hot 10. In April. That doesn't usually happen until July."
- "Ocean surface temps just broke the record for the 400th consecutive day. Four. Hundred. Days."
- "Earth has recorded above-average global temperatures for 14 consecutive months. Fourteen. Straight. Months."
- "Atmospheric CO2 at Mauna Loa: 433.24 ppm. First time above 433 in recorded history. Pre-industrial was 280."
- "CO2 this week at Mauna Loa: 436.2 ppm. Same week last year: 433.8. We added 2.4 ppm in a year. That used to take a decade."
- "Daily CO2 at Mauna Loa: 435.11 ppm. Yesterday: 435.02. Last week: 434.89. This number has literally never gone down."
- "New wildfire in Northern California. Satellite confidence: HIGH. 0% contained. It's April."
- "Satellite picked up a 1,200 MW fire in Siberia. For reference, a large power plant is about 1,000 MW. Except it's a forest."
- "Another fire in California. At this point the satellite is just forwarding us the same email."
- "Arctic sea ice: 12.4 million sq km. Lowest for this date since satellite records began in 1979."
- "No records broken today. No new fires. CO2 held at 433.18 ppm. Honestly suspicious."
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
        print("[generator] WARNING: No GEMINI_API_KEY — using template fallback")
        if fallback_fn and fallback_args:
            return fallback_fn(**fallback_args)
        return None

    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[generator] WARNING: Gemini client init failed ({e}) — using template fallback")
        if fallback_fn and fallback_args:
            return fallback_fn(**fallback_args)
        return None

    for attempt in range(MAX_RETRIES):
        try:
            prompt = f"{SYSTEM_PROMPT}\n\nWrite a tweet about this:\n{data_description}"
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            tweet = response.text.strip().strip('"').strip("'")

            # Run safety pipeline
            passed, reason = run_safety_pipeline(tweet)
            if passed:
                return tweet
            print(f"[generator] Safety rejected attempt {attempt + 1}: {reason}")

        except Exception as e:
            print(f"[generator] Gemini attempt {attempt + 1} failed: {e}")
            continue

    # All retries exhausted, use template fallback
    print("[generator] WARNING: All Gemini retries exhausted — using template fallback")
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
