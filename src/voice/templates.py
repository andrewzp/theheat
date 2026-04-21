"""Fallback tweet templates when Gemini is unavailable.

These are the safety net. If Gemini is down or all retries fail,
the bot still posts with context and personality. The personality
comes from framing — comparisons, timing, deadpan context — not
from catchphrases or sports metaphors.
"""

import datetime
import random


def country_record_template(
    country: str,
    kind: str,
    new_temp_c: float,
    peak_city: str,
    old_temp_c: float,
    old_record_year: int,
    old_record_city: str,
    years_of_data: int,
) -> str:
    new_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    descriptor = "warmest" if kind == "high" else "coldest"
    variants = [
        f"{country}'s {descriptor} reading in {years_of_data} years of records. {peak_city}: {new_f}F. Previous: {old_f}F in {old_record_city}, {old_record_year}.",
        f"{peak_city}, {country}: {new_f}F. That's the {descriptor} reading anywhere in the country in {years_of_data} years of archive data. Last top was {old_f}F in {old_record_year}.",
    ]
    return random.choice(variants)


def record_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    years_ago = datetime.date.today().year - old_year
    variants = [
        f"{city} is forecast to hit {temp_f}F today. If it gets there, the old mark of {old_f}F from {old_year} is gone.",
        f"{city} has a forecast high of {temp_f}F today. That would break a {years_ago}-year record. Previous: {old_f}F, set in {old_year}.",
        f"{city}, {country}: forecast {temp_f}F. If it verifies, that's a new record for this date. The old one stood since {old_year}.",
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


def hot10_template(cities: list[dict]) -> str:
    """Format Hot 10 as a compact single tweet. cities: [{city, anomaly_c}, ...]"""
    top3 = cities[:3]
    entries = [f"{c['city']} +{c['anomaly_c']:.1f}C" for c in top3]
    rest_count = min(len(cities), 10) - 3
    if rest_count > 0:
        return f"Hottest cities by anomaly today: {', '.join(entries)}, and {rest_count} more above normal."
    return f"Hottest cities by anomaly today: {', '.join(entries)}."


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


def drought_template(states: list) -> str:
    top = states[:3]
    parts = []
    for s in top:
        name = s.state if hasattr(s, "state") else s["state"]
        d3 = s.d3_pct if hasattr(s, "d3_pct") else s["d3_pct"]
        d4 = s.d4_pct if hasattr(s, "d4_pct") else s["d4_pct"]
        parts.append(f"{name} {d3 + d4:.0f}%")
    return f"US Drought Monitor: Extreme/exceptional drought — {', '.join(parts)}."


def enso_template(status: str, oni: float, duration: int) -> str:
    return f"NOAA declares {status} conditions. ONI: {oni:+.1f}. Previous phase lasted {duration} months."


def record_low_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    years_ago = datetime.date.today().year - old_year
    variants = [
        f"{city} is forecast to drop to {temp_f}F overnight. If that verifies, it's a new record low. Previous: {old_f}F from {old_year}.",
        f"{city}, {country}: forecast low {temp_f}F. That would be the coldest for this date since {old_year}. Previous record: {old_f}F.",
    ]
    return random.choice(variants)


def extreme_wave_template(location: str, ocean: str, wave_height_m: float) -> str:
    wave_ft = round(wave_height_m * 3.281, 0)
    stories = max(1, round(wave_height_m / 3))
    variants = [
        f"{wave_ft:.0f}-foot waves in the {location} today. {wave_height_m:.1f} meters. That's a {stories}-story building made of ocean.",
        f"{wave_height_m:.1f}m waves in the {location}. {wave_ft:.0f} feet of {ocean} Ocean.",
        f"Marine buoys in the {location} are reporting {wave_height_m:.1f}m swells. That's {wave_ft:.0f} feet.",
    ]
    return random.choice(variants)


def storm_surge_template(station: str, state: str, anomaly_m: float, observed_m: float) -> str:
    anomaly_ft = round(anomaly_m * 3.281, 1)
    variants = [
        f"Water level at {station}, {state} is {anomaly_ft}ft above where it should be right now.",
        f"NOAA tide gauge at {station}, {state}: {anomaly_ft}ft above predicted. The ocean is not where it's supposed to be.",
        f"{station}, {state}. Water level is running {anomaly_ft}ft above predicted. That's not a rounding error.",
    ]
    return random.choice(variants)


def river_flood_template(river: str, location: str, gauge_ft: float, flood_stage_ft: float, above_ft: float) -> str:
    variants = [
        f"{river} at {location}: {gauge_ft:.1f}ft. Flood stage is {flood_stage_ft:.0f}ft. The river doesn't care what month it is.",
        f"{river} at {location} is {above_ft:.1f}ft above flood stage right now. Gauge reading: {gauge_ft:.1f}ft.",
        f"{river} at {location}: {gauge_ft:.1f}ft and rising. Flood stage is {flood_stage_ft:.0f}ft. That's {above_ft:.1f}ft of overflow.",
    ]
    return random.choice(variants)


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]}"


def marine_heatwave_template(
    kind: str,
    days: int,
    today_c: float,
    archive_max_c: float,
    archive_max_year: int,
    years_of_data: int,
) -> str:
    if kind == "first":
        variants = [
            (
                f"The global ocean has now been above the daily record for "
                f"{days} straight days in {years_of_data} years of satellite "
                f"data. Today: {today_c:.2f}°C. Prior daily max: "
                f"{archive_max_c:.2f}°C, set {archive_max_year}."
            ),
            (
                f"{days} consecutive days of record-breaking global ocean "
                f"surface temps. Today's mean: {today_c:.2f}°C. The previous "
                f"record for this date was {archive_max_c:.2f}°C in "
                f"{archive_max_year}. Archive goes back {years_of_data} years."
            ),
        ]
    else:
        variants = [
            (
                f"The global ocean just posted its {_ordinal(days)} consecutive day "
                f"above the daily record in {years_of_data} years of "
                f"satellite data. Today: {today_c:.2f}°C."
            ),
            (
                f"{days} consecutive days and counting. Global mean SST "
                f"today: {today_c:.2f}°C. Old record for this date: "
                f"{archive_max_c:.2f}°C ({archive_max_year}). "
                f"{years_of_data}-year archive."
            ),
        ]
    return random.choice(variants)


def _month_label(month: str) -> str:
    """Render YYYY-MM as 'Month YYYY'."""
    try:
        year_str, mon_str = month.split("-")
        mon_idx = int(mon_str)
        names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        return f"{names[mon_idx - 1]} {year_str}"
    except (ValueError, IndexError):
        return month


def ice_mass_template(
    region: str,
    kind: str,
    *,
    month: str | None = None,
    monthly_delta_gt: float | None = None,
    years_of_record: int | None = None,
    threshold_gt: float | None = None,
) -> str:
    region_name = {"greenland": "Greenland", "antarctica": "Antarctica"}.get(
        region, region.title()
    )
    if kind == "monthly_loss_record":
        loss = abs(monthly_delta_gt or 0.0)
        month_name = _month_label(month or "")
        yrs = years_of_record or 0
        variants = [
            f"{region_name} lost {loss:.0f} gigatons in {month_name}. The largest monthly loss in {yrs} years of GRACE observations.",
            f"{region_name}: {loss:.0f} Gt of ice gone in {month_name} alone. That's the worst single-month loss in the {yrs}-year GRACE record.",
        ]
        return random.choice(variants)
    # cumulative_milestone
    threshold_abs = abs(int(threshold_gt or 0))
    variants = [
        f"{region_name} has now lost more than {threshold_abs:,} gigatons of ice since 2002, per GRACE. A threshold first crossed this month.",
        f"Cumulative ice loss from {region_name} passes {threshold_abs:,} Gt. GRACE has been watching since 2002.",
    ]
    return random.choice(variants)


def fire_footprint_template(
    name: str | None,
    country: str,
    region: str,
    hectares: float,
) -> str:
    """Safety-net fallback when Gemini fails.

    Named complexes lead with the name. Unnamed complexes use a regional
    descriptor. Every variant leads with acreage — the scale IS the story.
    """
    subject = name if name else f"A fire complex in {region}"
    hectares_str = f"{int(hectares):,}"
    acres_str = f"{int(round(hectares * 2.47105, 0)):,}"
    variants = [
        f"{subject}, {country} has burned {hectares_str} hectares. That's {acres_str} acres.",
        f"{subject}: {hectares_str} hectares burned. {country}.",
        f"Fire footprint update. {subject} in {country} is now at {hectares_str} hectares.",
    ]
    return random.choice(variants)
