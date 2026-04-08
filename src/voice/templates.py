"""Fallback tweet templates when Gemini is unavailable.

These are the safety net. If Gemini is down or all retries fail,
the bot still posts with context and personality. The personality
comes from framing — comparisons, timing, deadpan context — not
from catchphrases or sports metaphors.
"""

import datetime
import random


def record_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    years_ago = datetime.date.today().year - old_year
    variants = [
        f"{city} just dropped {temp_f}F. NEW RECORD. The old one was {old_f}F from {old_year}. That's {years_ago} years.",
        f"{city} with {temp_f}F today. That broke a {years_ago}-year record. Previous: {old_f}F, set in {old_year}.",
        f"{city}, {country}: {temp_f}F. New record for this date. The old one stood since {old_year}. {years_ago} years.",
    ]
    return random.choice(variants)


def fire_template(region: str, country: str, confidence: int, frp: float) -> str:
    month = datetime.date.today().strftime("%B")
    variants = [
        f"New wildfire in {region}, {country}. Satellite confidence: {confidence}%. {frp:.0f} MW. 0% contained. It's {month}.",
        f"Satellite picked up a {frp:.0f} MW fire in {region}, {country}. {confidence}% confidence. It's {month}.",
        f"Another fire. {region}, {country}. {confidence}% satellite confidence. {frp:.0f} MW.",
    ]
    return random.choice(variants)


def co2_milestone_template(ppm: int, actual: float) -> str:
    variants = [
        f"Atmospheric CO2 at Mauna Loa: {actual} ppm. First time above {ppm} in recorded history. Pre-industrial was 280.",
        f"CO2 at Mauna Loa just crossed {ppm} ppm. Actual reading: {actual}. Pre-industrial was 280. That's a 54% increase.",
        f"Mauna Loa CO2: {actual} ppm. First reading above {ppm}. For context, it was 280 for most of human civilization.",
    ]
    return random.choice(variants)


def co2_weekly_template(current: float, last_year: float, diff: float) -> str:
    variants = [
        f"CO2 this week at Mauna Loa: {current} ppm. Same week last year: {last_year}. +{diff} ppm. That used to take a decade.",
        f"Weekly CO2 at Mauna Loa: {current} ppm. Last year same week: {last_year} ppm. +{diff} ppm year over year.",
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
        f"NOAA confirms: {city}, {state} broke the record on {date}. Official reading: {temp_f}F.",
        f"It's official. NOAA says {city}, {state} broke the record on {date}. {temp_f}F. The paperwork is in.",
    ]
    return random.choice(variants)


def severe_weather_template(event_type: str, area: str) -> str:
    month = datetime.date.today().strftime("%B")
    variants = [
        f"{event_type} issued for {area}.",
        f"{event_type} for {area}. It's {month}.",
    ]
    return random.choice(variants)


def global_disaster_template(disaster_type: str, name: str, country: str, severity: str) -> str:
    variants = [
        f"{disaster_type}: {name}. Location: {country}. GDACS severity: {severity.upper()}.",
        f"GDACS {severity.upper()} alert. {disaster_type} — {name}, {country}.",
    ]
    return random.choice(variants)


def sea_ice_record_template(hemisphere: str, extent: float, previous_extent: float, previous_year: int) -> str:
    return (
        f"{hemisphere} sea ice: {extent} million sq km. "
        f"Lowest for this date since satellite records began in 1979. "
        f"Previous record: {previous_extent} million sq km ({previous_year})."
    )


def drought_template(states: list[dict]) -> str:
    top = states[:3]
    parts = [f"{s['state']} {s['d3_pct'] + s['d4_pct']:.0f}%" for s in top]
    return f"US Drought Monitor: Extreme/exceptional drought — {', '.join(parts)}."


def enso_template(status: str, oni: float, duration: int) -> str:
    return f"NOAA declares {status} conditions. ONI: {oni:+.1f}. Previous phase lasted {duration} months."


def record_low_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    years_ago = datetime.date.today().year - old_year
    variants = [
        f"{city} dropped to {temp_f}F overnight. NEW RECORD LOW. Previous: {old_f}F from {old_year}. {years_ago} years.",
        f"{city}, {country}: {temp_f}F low. Coldest for this date since {old_year}. Previous record: {old_f}F.",
    ]
    return random.choice(variants)


def extreme_wave_template(location: str, ocean: str, wave_height_m: float) -> str:
    wave_ft = round(wave_height_m * 3.281, 0)
    month = datetime.date.today().strftime("%B")
    variants = [
        f"{wave_height_m:.1f}m waves in the {location}. That's {wave_ft:.0f} feet. It's {month}.",
        f"Marine forecast: {wave_height_m:.1f}m ({wave_ft:.0f}ft) waves in the {location}.",
    ]
    return random.choice(variants)


def storm_surge_template(station: str, state: str, anomaly_m: float, observed_m: float) -> str:
    anomaly_ft = round(anomaly_m * 3.281, 1)
    return (
        f"Water level at {station}: {anomaly_ft}ft above predicted. "
        f"Observed: {observed_m:.2f}m."
    )


def river_flood_template(river: str, location: str, gauge_ft: float, flood_stage_ft: float, above_ft: float) -> str:
    variants = [
        f"{river} at {location}: {gauge_ft:.1f}ft. Flood stage is {flood_stage_ft:.0f}ft. Currently {above_ft:.1f}ft above.",
        f"{river} at {location} is {above_ft:.1f}ft above flood stage. Gauge: {gauge_ft:.1f}ft. Flood stage: {flood_stage_ft:.0f}ft.",
    ]
    return random.choice(variants)
