"""Fallback tweet templates when Gemini is unavailable.

These are the safety net. If Gemini is down or all retries fail,
the bot still posts with proper context. Every template must be
self-contained — someone seeing it for the first time understands
what happened, where, and why it matters.
"""

import datetime
import random


def record_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    years_ago = datetime.date.today().year - old_year
    variants = [
        f"{city}, {country}: {temp_f}F ({temp_c}C) today. New record for this date. Previous: {old_f}F, set in {old_year}.",
        f"{city} recorded {temp_f}F today. Breaks the record for this date, which stood since {old_year}. {years_ago} years.",
        f"{city}, {country}: {temp_f}F. Previous record for this date was {old_f}F ({old_year}). That record stood {years_ago} years.",
    ]
    return random.choice(variants)


def fire_template(region: str, country: str, confidence: int, frp: float) -> str:
    month = datetime.date.today().strftime("%B")
    variants = [
        f"Wildfire detected in {region}, {country}. Satellite confidence: {confidence}%. Fire Radiative Power: {frp:.0f} MW.",
        f"New fire in {region}, {country}. {confidence}% satellite confidence. {frp:.0f} MW. Detected {month} {datetime.date.today().day}.",
        f"Satellite detected a {frp:.0f} MW fire in {region}, {country}. Confidence: {confidence}%.",
    ]
    return random.choice(variants)


def co2_milestone_template(ppm: int, actual: float) -> str:
    variants = [
        f"Atmospheric CO2 at Mauna Loa, Hawaii: {actual} ppm. First reading above {ppm} in recorded history. Pre-industrial baseline was 280.",
        f"CO2 at Mauna Loa crossed {ppm} ppm. Actual reading: {actual}. Pre-industrial level was 280 ppm.",
        f"Mauna Loa CO2: {actual} ppm. First time above {ppm}. For context, pre-industrial CO2 was approximately 280 ppm.",
    ]
    return random.choice(variants)


def co2_weekly_template(current: float, last_year: float, diff: float) -> str:
    variants = [
        f"Weekly CO2 average at Mauna Loa: {current} ppm. Same week last year: {last_year} ppm. +{diff} ppm year over year.",
        f"Mauna Loa weekly CO2: {current} ppm. Last year same week: {last_year} ppm. Year-over-year change: +{diff} ppm.",
    ]
    return random.choice(variants)


def hot10_template(cities: list[dict]) -> str:
    """Format Hot 10 as a compact single tweet. cities: [{city, anomaly_c}, ...]"""
    top3 = cities[:3]
    entries = [f"{c['city']} +{c['anomaly_c']:.1f}C" for c in top3]
    rest_count = min(len(cities), 10) - 3
    if rest_count > 0:
        return f"Hottest cities by anomaly today: {', '.join(entries)}, and {rest_count} more above normal."
    return f"Hottest cities by anomaly today: {', '.join(entries)}."


def noaa_confirmation_template(city: str, state: str, temp_f: float, date: str) -> str:
    variants = [
        f"NOAA confirms: {city}, {state} broke the temperature record on {date}. Official reading: {temp_f}F.",
        f"NOAA ACIS confirms {city}, {state} set a new daily high on {date}. {temp_f}F.",
    ]
    return random.choice(variants)
