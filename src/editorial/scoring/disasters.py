"""Disasters editorial scoring."""



from __future__ import annotations



from ._shared import EditorialScore, _build_score



def score_severe_weather(event_type: str, severity: str) -> EditorialScore:
    event_weight = {
        "Tornado Warning": 92,
        "Flash Flood Emergency": 96,
        "Hurricane Warning": 94,
        "Storm Surge Warning": 90,
        "Extreme Wind Warning": 88,
        "Blizzard Warning": 84,
    }
    severity_weight = {
        "Extreme": 94,
        "Severe": 84,
        "Moderate": 70,
    }
    severity_score = max(event_weight.get(event_type, 78), severity_weight.get(severity, 74))
    reasons = [event_type]
    if "Warning" in event_type:
        reasons.append("active warning, not outlook")
    reasons.append("fast-moving operational signal")
    return _build_score(
        "severe_weather",
        severity=severity_score,
        novelty=52,
        timeliness=98,
        confidence=92,
        shareability=54,
        sensitivity=74,
        threshold=58,
        reasons=reasons,
    )

def score_global_disaster(severity: str, disaster_type: str) -> EditorialScore:
    severity_score = {"Red": 96, "Orange": 82, "Green": 60}.get(severity, 70)
    novelty = 66 if severity == "Red" else 58
    reasons = [f"GDACS {severity} alert", disaster_type]
    if severity == "Red":
        reasons.append("highest global alert tier")
    return _build_score(
        "global_disaster",
        severity=severity_score,
        novelty=novelty,
        timeliness=82,
        confidence=88,
        shareability=58,
        sensitivity=82,
        threshold=62,
        reasons=reasons,
    )

def score_global_flood(
    severity: str,
    populations_affected: int,
    affected_area_km2: float,
    country: str,
) -> EditorialScore:
    severity_score = {
        "Extreme": 98,
        "Major": 90,
        "Moderate": 68,
        "Minor": 48,
    }.get(severity, 70)
    population_bonus = min(populations_affected / 25_000, 12)
    area_bonus = min(affected_area_km2 / 50.0, 10)
    reasons = [f"Copernicus EMS {severity} flood activation", country]
    if populations_affected > 0:
        reasons.append(f"{populations_affected:,} people affected")
    if affected_area_km2 > 0:
        reasons.append(f"{affected_area_km2:.1f} sq km mapped flood extent")
    return _build_score(
        "global_flood",
        severity=severity_score + population_bonus + area_bonus,
        novelty=78 + min(population_bonus + area_bonus, 12),
        timeliness=94,
        confidence=88,
        shareability=72 + min(population_bonus, 10),
        sensitivity=60,
        threshold=72,
        reasons=reasons[:4],
    )

def score_cyclone_rapid_intensification(
    delta_kt_24h: int,
    current_category: int,
    basin: str,
) -> EditorialScore:
    """Score cyclone rapid intensification, the high-bar cyclone signal."""

    major_bonus = 10 if current_category >= 3 else 0
    very_fast_bonus = max(delta_kt_24h - 35, 0) * 0.8
    reasons = [
        f"+{delta_kt_24h} kt in 24 hours",
        f"current category {current_category}",
        basin,
    ]
    if delta_kt_24h >= 35:
        reasons.append("exceeds rapid-intensification threshold")
    return _build_score(
        "cyclone_rapid_intensification",
        severity=82 + major_bonus + very_fast_bonus,
        novelty=82 + min(delta_kt_24h - 30, 20) * 0.5,
        timeliness=96,
        confidence=92,
        shareability=74 + min(delta_kt_24h - 30, 25) * 0.8,
        sensitivity=72,
        threshold=70,
        reasons=reasons[:3],
    )

def score_cyclone_tier_crossing(from_cat: int, to_cat: int, basin: str) -> EditorialScore:
    """Score a Saffir-Simpson category upgrade."""

    crossed_major = from_cat < 3 <= to_cat
    reasons = [
        f"Category {from_cat} to Category {to_cat}",
        basin,
        "Saffir-Simpson tier crossing",
    ]
    if crossed_major:
        reasons.append("crossed major-hurricane threshold")
    return _build_score(
        "cyclone_tier_crossing",
        severity=70 + to_cat * 6 + (8 if crossed_major else 0),
        novelty=66 + to_cat * 5,
        timeliness=94,
        confidence=92,
        shareability=62 + to_cat * 5,
        sensitivity=74,
        threshold=68,
        reasons=reasons[:3],
    )

def score_cyclone_landfall(category: int, location: str, basin: str) -> EditorialScore:
    """Score a confirmed Cat 3+ tropical cyclone landfall."""

    reasons = [
        f"Category {category} landfall",
        location,
        basin,
    ]
    return _build_score(
        "cyclone_landfall",
        severity=88 + max(category - 3, 0) * 5,
        novelty=82 + max(category - 3, 0) * 4,
        timeliness=98,
        confidence=94,
        shareability=78 + max(category - 3, 0) * 4,
        sensitivity=86,
        threshold=70,
        reasons=reasons,
    )

def score_cyclone_basin_record(category: int, basin: str, record_label: str) -> EditorialScore:
    """Score archive-backed basin records once a caller supplies the archive rule."""

    return _build_score(
        "cyclone_basin_record",
        severity=80 + category * 4,
        novelty=94,
        timeliness=88,
        confidence=90,
        shareability=84,
        sensitivity=72,
        threshold=72,
        reasons=[record_label, basin, f"Category {category}"],
    )

def score_storm_surge(anomaly_m: float) -> EditorialScore:
    reasons = [f"{anomaly_m:.2f}m above predicted tide"]
    if anomaly_m >= 1.0:
        reasons.append("major storm-surge threshold")
    return _build_score(
        "storm_surge",
        severity=54 + anomaly_m * 42,
        novelty=62,
        timeliness=90,
        confidence=86,
        shareability=58 + anomaly_m * 18,
        sensitivity=66,
        threshold=60,
        reasons=reasons,
    )

def score_river_flood(above_by_ft: float) -> EditorialScore:
    reasons = [f"{above_by_ft:.1f}ft above flood stage"]
    if above_by_ft >= 5:
        reasons.append("major river flood exceedance")
    return _build_score(
        "river_flood",
        severity=50 + above_by_ft * 8,
        novelty=58,
        timeliness=86,
        confidence=88,
        shareability=54 + above_by_ft * 4,
        sensitivity=72,
        threshold=62,
        reasons=reasons,
    )
