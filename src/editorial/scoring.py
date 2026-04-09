from __future__ import annotations

"""Editorial scoring heuristics for deciding what is worth drafting."""

from dataclasses import dataclass
from datetime import date


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def _label(total: int) -> str:
    if total >= 85:
        return "elite"
    if total >= 72:
        return "strong"
    if total >= 60:
        return "borderline"
    return "weak"


def _compute_total(
    *,
    severity: int,
    novelty: int,
    timeliness: int,
    confidence: int,
    shareability: int,
    sensitivity: int,
) -> int:
    base = (
        0.28 * severity
        + 0.24 * novelty
        + 0.16 * timeliness
        + 0.16 * confidence
        + 0.16 * shareability
    )
    penalty = 0.20 * sensitivity
    return _clamp(base - penalty)


@dataclass(frozen=True)
class EditorialScore:
    category: str
    severity: int
    novelty: int
    timeliness: int
    confidence: int
    shareability: int
    sensitivity: int
    total: int
    threshold: int
    reasons: list[str]

    @property
    def passes(self) -> bool:
        return self.total >= self.threshold

    @property
    def label(self) -> str:
        return _label(self.total)

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "novelty": self.novelty,
            "timeliness": self.timeliness,
            "confidence": self.confidence,
            "shareability": self.shareability,
            "sensitivity": self.sensitivity,
            "total": self.total,
            "threshold": self.threshold,
            "passes": self.passes,
            "label": self.label,
            "reasons": self.reasons,
        }


def _build_score(
    category: str,
    *,
    severity: int,
    novelty: int,
    timeliness: int,
    confidence: int,
    shareability: int,
    sensitivity: int,
    threshold: int,
    reasons: list[str],
) -> EditorialScore:
    return EditorialScore(
        category=category,
        severity=_clamp(severity),
        novelty=_clamp(novelty),
        timeliness=_clamp(timeliness),
        confidence=_clamp(confidence),
        shareability=_clamp(shareability),
        sensitivity=_clamp(sensitivity),
        total=_compute_total(
            severity=_clamp(severity),
            novelty=_clamp(novelty),
            timeliness=_clamp(timeliness),
            confidence=_clamp(confidence),
            shareability=_clamp(shareability),
            sensitivity=_clamp(sensitivity),
        ),
        threshold=threshold,
        reasons=reasons[:3],
    )


def score_record_event(new_temp_c: float, old_record_c: float, old_record_year: int, *, official: bool = False) -> EditorialScore:
    delta = max(new_temp_c - old_record_c, 0.0)
    record_age = max(date.today().year - old_record_year, 0)
    severity = 56 + delta * 22 + max(new_temp_c - 40, 0) * 2.5
    novelty = 45 + min(record_age, 100) * 0.45
    timeliness = 72 if official else 94
    confidence = 98 if official else 72
    shareability = 52 + min(record_age, 80) * 0.30 + max(new_temp_c - 42, 0) * 1.5
    reasons = []
    if record_age >= 25:
        reasons.append(f"{record_age}-year-old record")
    elif record_age <= 2:
        reasons.append("fresh repeat record")
    if delta >= 1.0:
        reasons.append(f"beat prior record by {delta:.1f}C")
    if new_temp_c >= 45:
        reasons.append("extreme absolute temperature")
    if official:
        reasons.append("official NOAA confirmation")
    return _build_score(
        "record_confirmation" if official else "record",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=8,
        threshold=58 if official else 62,
        reasons=reasons or ["clear weather record"],
    )


def score_record_low_event(new_temp_c: float, old_record_c: float, old_record_year: int) -> EditorialScore:
    delta = max(old_record_c - new_temp_c, 0.0)
    record_age = max(date.today().year - old_record_year, 0)
    severity = 46 + delta * 18 + max(0 - new_temp_c, 0) * 1.8
    novelty = 48 + min(record_age, 100) * 0.40
    timeliness = 92
    confidence = 72
    shareability = 48 + min(record_age, 80) * 0.28 + max(0 - new_temp_c, 0) * 1.2
    reasons = []
    if record_age >= 25:
        reasons.append(f"{record_age}-year-old cold record")
    if delta >= 1.0:
        reasons.append(f"{delta:.1f}C below prior record")
    if new_temp_c <= 0:
        reasons.append("freezing-or-below reading")
    return _build_score(
        "record_low",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=8,
        threshold=60,
        reasons=reasons or ["notable cold record"],
    )


def score_noaa_confirmation_event(temp_f: float) -> EditorialScore:
    reasons = [
        "official NOAA confirmation",
        f"confirmed high of {temp_f:.0f}F",
        "authoritative follow-up to earlier detection",
    ]
    return _build_score(
        "record_confirmation",
        severity=72 + max(temp_f - 100, 0) * 0.5,
        novelty=74,
        timeliness=68,
        confidence=99,
        shareability=70 + max(temp_f - 100, 0) * 0.2,
        sensitivity=8,
        threshold=58,
        reasons=reasons,
    )


def score_fire_event(confidence: int, frp: float, *, region: str = "") -> EditorialScore:
    shoulder_season = date.today().month in {1, 2, 3, 4, 11, 12}
    severity = 42 + min(frp, 1800) / 18
    novelty = 54 + (15 if shoulder_season else 0) + (8 if frp >= 800 else 0)
    timeliness = 94
    confidence_score = 45 + confidence * 0.55
    shareability = 46 + min(frp, 1400) / 28 + (8 if confidence >= 95 else 0)
    reasons = []
    if shoulder_season:
        reasons.append("out-of-season fire signal")
    if frp >= 1000:
        reasons.append("power-plant-scale fire intensity")
    if confidence >= 95:
        reasons.append("high-confidence satellite detection")
    if region and region != "Unknown":
        reasons.append(f"clear location hook: {region}")
    return _build_score(
        "fire",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence_score,
        shareability=shareability,
        sensitivity=34,
        threshold=64,
        reasons=reasons or ["large active wildfire"],
    )


def score_co2_milestone(ppm_crossed: int, actual_ppm: float) -> EditorialScore:
    severity = 62 + max(ppm_crossed - 420, 0) * 1.2
    novelty = 92
    timeliness = 78
    confidence = 99
    shareability = 82 + max(actual_ppm - ppm_crossed, 0) * 5
    reasons = [
        f"new integer milestone above {ppm_crossed} ppm",
        "clean pre-industrial comparison",
        "high-confidence NOAA source",
    ]
    return _build_score(
        "co2_milestone",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=3,
        threshold=58,
        reasons=reasons,
    )


def score_co2_weekly(diff: float) -> EditorialScore:
    severity = 56 + max(diff, 0) * 12
    novelty = 72 + max(diff - 2.0, 0) * 8
    timeliness = 72
    confidence = 96
    shareability = 68 + max(diff, 0) * 8
    reasons = [
        f"{diff:+.1f} ppm year-over-year",
        "easy same-week comparison",
        "climate trend signal, not weather noise",
    ]
    return _build_score(
        "co2_weekly",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=3,
        threshold=62,
        reasons=reasons,
    )


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
        threshold=54,
        reasons=reasons,
    )


def score_sea_ice_record(extent: float, previous_extent: float, previous_year: int) -> EditorialScore:
    gap = max(previous_extent - extent, 0.0)
    years_since_prev = max(date.today().year - previous_year, 0)
    reasons = [
        f"record low since {previous_year}",
        f"extent lower by {gap:.2f} million sq km",
        "long-run climate signal",
    ]
    return _build_score(
        "sea_ice_record",
        severity=62 + gap * 120,
        novelty=88 + min(years_since_prev, 25) * 0.2,
        timeliness=72,
        confidence=98,
        shareability=74 + gap * 40,
        sensitivity=4,
        threshold=60,
        reasons=reasons,
    )


def score_drought(states: list) -> EditorialScore:
    if not states:
        return _build_score(
            "drought",
            severity=0,
            novelty=0,
            timeliness=0,
            confidence=0,
            shareability=0,
            sensitivity=0,
            threshold=60,
            reasons=["no drought states provided"],
        )

    totals = []
    for state in states[:3]:
        d3 = state.d3_pct if hasattr(state, "d3_pct") else state.get("d3_pct", 0)
        d4 = state.d4_pct if hasattr(state, "d4_pct") else state.get("d4_pct", 0)
        totals.append(float(d3) + float(d4))
    worst = max(totals) if totals else 0.0
    reasons = [f"worst state at {worst:.0f}% extreme/exceptional drought"]
    if len(states) >= 3:
        reasons.append("multi-state drought footprint")
    return _build_score(
        "drought",
        severity=48 + worst * 0.8,
        novelty=58 + len(states) * 2,
        timeliness=68,
        confidence=88,
        shareability=48 + min(worst, 30) * 0.7,
        sensitivity=38,
        threshold=52,
        reasons=reasons,
    )


def score_enso_transition(oni_value: float, previous_duration_months: int) -> EditorialScore:
    reasons = [
        f"ENSO phase shift at ONI {oni_value:+.1f}",
        f"previous phase lasted {previous_duration_months} months",
        "monthly climate regime change",
    ]
    return _build_score(
        "enso",
        severity=58 + abs(oni_value) * 18,
        novelty=84,
        timeliness=70,
        confidence=96,
        shareability=64 + min(previous_duration_months, 12) * 1.5,
        sensitivity=6,
        threshold=56,
        reasons=reasons,
    )


def score_extreme_wave(wave_height_m: float) -> EditorialScore:
    shoulder_month = date.today().month in {4, 5, 9, 10}
    reasons = [f"{wave_height_m:.1f}m wave height"]
    if shoulder_month:
        reasons.append("off-peak seasonal timing")
    if wave_height_m >= 12:
        reasons.append("40-foot-plus wave event")
    return _build_score(
        "extreme_wave",
        severity=50 + wave_height_m * 4.2,
        novelty=58 + (12 if shoulder_month else 0),
        timeliness=84,
        confidence=84,
        shareability=56 + wave_height_m * 2.4,
        sensitivity=12,
        threshold=62,
        reasons=reasons,
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
        threshold=58,
        reasons=reasons,
    )


def score_hot10(top_anomaly_c: float, city_count: int, change_count: int) -> EditorialScore:
    reasons = [f"top anomaly +{top_anomaly_c:.1f}C"]
    if change_count:
        reasons.append(f"{change_count} notable ranking changes")
    reasons.append("daily recurring scoreboard")
    return _build_score(
        "hot10",
        severity=52 + top_anomaly_c * 5,
        novelty=60 + min(change_count, 5) * 5,
        timeliness=88,
        confidence=82,
        shareability=66 + min(city_count, 10),
        sensitivity=6,
        threshold=56,
        reasons=reasons,
    )
