"""Fallback tweet templates when Gemini is unavailable."""


def record_template(city: str, country: str, temp_c: float, old_temp_c: float, old_year: int) -> str:
    temp_f = round(temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    return f"{city}, {country}: {temp_f}F today. Previous record for this date: {old_f}F, set in {old_year}."


def fire_template(region: str, country: str, confidence: int, frp: float) -> str:
    return f"Fire detected: {region}, {country}. Satellite confidence: {confidence}%. FRP: {frp:.0f} MW."


def co2_milestone_template(ppm: int, actual: float) -> str:
    return f"CO2 daily reading: {actual} ppm. First time above {ppm} ppm."


def co2_weekly_template(current: float, last_year: float, diff: float) -> str:
    return f"CO2 this week: {current} ppm. Same week last year: {last_year} ppm. +{diff} ppm year over year."


def hot10_template(cities: list[dict]) -> str:
    """Format Hot 10 as a simple list. cities: [{city, anomaly_c}, ...]"""
    lines = ["Today's Hot 10 (degrees above normal):"]
    for i, c in enumerate(cities[:10], 1):
        lines.append(f"{i}. {c['city']}: +{c['anomaly_c']:.1f}C")
    return "\n".join(lines)
