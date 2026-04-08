"""Fallback tweet templates when Gemini is unavailable.

These are the safety net. If Gemini is down or all retries fail,
the bot still posts in voice. Not as good as LLM output, but still
on-brand and under 280 characters.
"""

import datetime
import random


def record_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    years_ago = datetime.date.today().year - old_year
    variants = [
        f"{city} just dropped {temp_f}F. NEW RECORD. The old one was from {old_year}. That's {years_ago} years.",
        f"{city} with {temp_f}F today. That's a new career high. Old record stood since {old_year}.",
        f"{city} just put up {temp_f}F. Broke a {years_ago}-year record. Congratulations to no one.",
    ]
    return random.choice(variants)


def fire_template(region: str, country: str, confidence: int, frp: float) -> str:
    month = datetime.date.today().strftime("%B")
    conf_label = "HIGH" if confidence >= 80 else f"{confidence}%"
    variants = [
        f"New wildfire detected in {region}. Satellite confidence: {conf_label}. {frp:.0f} MW. 0% contained. It's {month}.",
        f"Satellite just picked up a fire in {region}. {confidence}% confidence. {frp:.0f} MW. It's {month}.",
        f"Another fire. {region}, {country}. {confidence}% confidence. {frp:.0f} MW. We are getting rekt out here.",
    ]
    return random.choice(variants)


def co2_milestone_template(ppm: int, actual: float) -> str:
    variants = [
        f"CO2 just crossed {ppm} ppm. Actual reading: {actual}. Pre-industrial was 280. We're speed-running this.",
        f"CO2 posted another personal best. {actual} ppm. First time above {ppm}. Unguardable.",
        f"Daily CO2: {actual} ppm. First reading above {ppm}. Pre-industrial was 280. Nobody asked for this.",
    ]
    return random.choice(variants)


def co2_weekly_template(current: float, last_year: float, diff: float) -> str:
    variants = [
        f"CO2 this week: {current} ppm. Same week last year: {last_year} ppm. +{diff} ppm. This number has literally never gone down.",
        f"Weekly CO2: {current} ppm. Last year: {last_year}. That's +{diff} ppm year over year. Unguardable.",
    ]
    return random.choice(variants)


def hot10_template(cities: list[dict]) -> str:
    """Format Hot 10 as a compact single tweet. cities: [{city, anomaly_c}, ...]"""
    top3 = cities[:3]
    entries = [f"{c['city']} +{c['anomaly_c']:.0f}C" for c in top3]
    rest_count = min(len(cities), 10) - 3
    if rest_count > 0:
        return f"HOT 10. Top 3: {', '.join(entries)}. {rest_count} more cities nobody wants to be on this list."
    return f"HOT 10. {', '.join(entries)}. Nobody asked for this."


def noaa_confirmation_template(city: str, state: str, temp_f: float, date: str) -> str:
    variants = [
        f"NOAA confirms: {city}, {state} officially broke the record on {date}. {temp_f}F. Congratulations to no one.",
        f"It's official. NOAA says {city}, {state} broke the record on {date}. {temp_f}F. The paperwork is in.",
    ]
    return random.choice(variants)
