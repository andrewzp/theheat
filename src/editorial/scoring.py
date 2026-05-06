from __future__ import annotations

"""Editorial scoring heuristics for deciding what is worth drafting.

EDITORIAL PRINCIPLE: The "Wait, what?" test.
Every event must pass this: would a weather-aware person react with genuine
surprise? If the answer is "yeah, that happens" — suppress it.

Guidelines:
- Record-breaking means something only if the old record was old or the margin
  is large. Breaking a 2-year record by 0.1C is not news.
- Context matters. 11m waves in Drake Passage is Tuesday. 11m in the Caribbean
  is catastrophic. An Orange cyclone alert is routine; Red is extraordinary.
- Routine drought updates, minor flood stage exceedances, and medium-severity
  disaster alerts are NOT astounding. Only the extremes of the extremes.
- The data is already public. Our value is editorial judgement — knowing when
  a number is genuinely extraordinary vs. merely large.
"""

from dataclasses import dataclass
from datetime import date

from src.editorial._util import clamp as _clamp


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
        reasons=reasons,
    )


def score_record_event(
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
    *,
    kind: str = "high",
) -> EditorialScore:
    delta = max(new_temp_c - old_record_c, 0.0) if kind == "high" else max(old_record_c - new_temp_c, 0.0)
    record_age = max(date.today().year - old_record_year, 0)
    absolute_bonus = max(new_temp_c - 40, 0) * 2.5 if kind == "high" else max(-10 - new_temp_c, 0) * 2.0
    severity = 56 + delta * 22 + absolute_bonus
    novelty = 45 + min(record_age, 100) * 0.45
    timeliness = 94
    confidence = 72
    shareability = 52 + min(record_age, 80) * 0.30
    shareability += max(new_temp_c - 42, 0) * 1.5 if kind == "high" else max(-15 - new_temp_c, 0) * 1.2
    reasons = []
    if record_age >= 25:
        reasons.append(f"{record_age}-year-old record")
    elif record_age <= 2:
        reasons.append("fresh repeat record")
    if delta >= 1.0:
        reasons.append(f"beat prior record by {delta:.1f}C")
    if kind == "high" and new_temp_c >= 45:
        reasons.append("extreme absolute temperature")
    if kind == "low" and new_temp_c <= -20:
        reasons.append("extreme absolute cold")
    return _build_score(
        "record",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=8,
        threshold=72,
        reasons=reasons or ["clear weather record"],
    )


def score_country_record(
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
    *,
    kind: str = "high",
    cities_sampled: int = 2,
    years_of_data: int = 30,
) -> EditorialScore:
    """Score a country-level all-time record.

    Country records are a bigger story than per-city records — "France's
    hottest day ever recorded" beats "Marseille's hottest day ever." So
    the bar is higher (threshold 82) and a pass tends to be elite.
    """
    delta = abs(new_temp_c - old_record_c)
    record_age = max(date.today().year - old_record_year, 0)
    severity = 70 + delta * 6 + (6 if kind == "high" and new_temp_c >= 45 else 0)
    novelty = 80 + min(record_age, 80) * 0.20
    timeliness = 96
    confidence = 70 + min(cities_sampled, 10) * 2  # more cities → more trustworthy aggregate
    shareability = 76 + min(record_age, 80) * 0.25 + min(cities_sampled, 12) * 0.5
    reasons = [
        f"country-wide {kind} across {cities_sampled} sampled cities",
        f"breaks {years_of_data}-year archive peak",
    ]
    if record_age >= 10:
        reasons.append(f"{record_age}-year-old national record")
    if delta >= 1.0:
        reasons.append(f"{delta:.1f}C over prior national peak")
    return _build_score(
        f"country_{kind}",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=8,
        threshold=82,
        reasons=reasons[:3],
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
        threshold=72,
        reasons=reasons or ["notable cold record"],
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


def score_fire_footprint(
    hectares: float,
    tier: int,
    *,
    region: str = "",
    has_name: bool = False,
) -> EditorialScore:
    """Score a fire-complex tier crossing.

    Signal is the cumulative burn area (hectares) and which tier we've
    just crossed. Named complexes score slightly higher because the name
    itself is a shareability hook. Out-of-season fires score higher on
    novelty, matching the existing FIRMS pattern.
    """
    # Northern-hemisphere shoulder. NIFC is US-only so this is always correct
    # in production; revisit if a global source is added.
    shoulder_season = date.today().month in {1, 2, 3, 4, 11, 12}
    severity = 58 + tier * 6 + min(hectares, 1_500_000) / 30_000
    novelty = 52 + tier * 4 + (12 if shoulder_season else 0)
    timeliness = 88
    confidence_score = 82  # NIFC WFIGS is authoritative
    shareability = 58 + tier * 5 + (10 if has_name else 0)
    reasons = [f"{int(hectares):,} ha cumulative burn area"]
    if has_name:
        reasons.append("named fire complex")
    if shoulder_season:
        reasons.append("out-of-season fire signal")
    if tier >= 3:
        reasons.append("top-tier historical scale")
    if region and region != "Unknown":
        reasons.append(f"location hook: {region}")
    return _build_score(
        "fire_footprint",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence_score,
        shareability=shareability,
        sensitivity=34,
        threshold=72,
        reasons=reasons[:3],
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


def score_ice_mass_event(
    region: str,
    kind: str,
    *,
    monthly_delta_gt: float | None = None,
    previous_worst_gt: float | None = None,
    threshold_gt: float | None = None,
) -> EditorialScore:
    """Score a GRACE-FO ice-mass-loss event.

    Two kinds share one category + threshold:
    - "monthly_loss_record": new largest single-month loss in the record.
    - "cumulative_milestone": cumulative anomaly crosses next -1000 Gt floor.
    """
    if kind == "monthly_loss_record":
        loss = abs(monthly_delta_gt or 0.0)
        severity = max(60, 72 + (loss - 300.0) * 0.15)
        margin = 0.0
        if previous_worst_gt is not None and monthly_delta_gt is not None:
            margin = max(abs(monthly_delta_gt) - abs(previous_worst_gt), 0.0)
        shareability = 78 + margin * 0.1
        reasons = [
            "largest monthly loss in GRACE record",
            (
                f"previous worst: {abs(previous_worst_gt):.0f} Gt"
                if previous_worst_gt is not None
                else "first monthly record observed"
            ),
            "GRACE-FO gravimetry",
        ]
        return _build_score(
            "ice_mass_record",
            severity=severity,
            novelty=90,
            # timeliness raised from spec's 64: even a small monthly record
            # must pass the 78 threshold (the annual cap controls volume).
            timeliness=84,
            confidence=96,
            shareability=shareability,
            sensitivity=8,
            threshold=78,
            reasons=reasons,
        )

    # cumulative_milestone
    threshold_abs = abs(threshold_gt or 0.0)
    severity = 76 + threshold_abs / 1000.0 * 2.0
    reasons = [
        f"cumulative loss crosses {threshold_abs:.0f} Gt",
        f"region: {region}",
        "GRACE-FO gravimetry",
    ]
    return _build_score(
        "ice_mass_record",
        severity=severity,
        novelty=82,
        timeliness=60,
        confidence=96,
        shareability=84,
        sensitivity=8,
        threshold=78,
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
        threshold=62,
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


def score_marine_heatwave(
    days: int,
    peak_anomaly_c: float,
    years_of_data: int,
) -> EditorialScore:
    reasons = [
        f"{days}-day streak above the daily archive record",
        f"peak {peak_anomaly_c:+.2f}°C above prior daily max",
        f"{years_of_data}-year satellite record",
    ]
    if days >= 100:
        reasons.append("triple-digit consecutive-day streak")
    if peak_anomaly_c >= 0.5:
        reasons.append("half-degree anomaly on a global mean")

    return _build_score(
        "marine_heatwave",
        severity=72 + min(days / 4.0, 22) + min(peak_anomaly_c * 10, 10),
        novelty=80 + min(days / 10.0, 10),
        timeliness=86,
        confidence=92,
        shareability=80 + min(days / 20.0, 12),
        sensitivity=6,
        threshold=78,
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
        threshold=62,
        reasons=reasons,
    )


def score_all_time_record(new_temp_c: float, old_record_c: float, old_record_year: int, years_of_data: int, *, kind: str = "high") -> EditorialScore:
    """All-time records within the archive window. Inherently elite."""
    delta = abs(new_temp_c - old_record_c)
    age = max(date.today().year - old_record_year, 0)
    # All-time records are inherently top-tier. Even a 0.1C margin on an
    # all-time record is genuinely astounding.
    reasons = [
        f"{kind} temp record in {years_of_data} years of archive data",
        f"beat prior by {delta:.1f}C" if delta >= 0.2 else "edged prior record",
    ]
    if age >= 20:
        reasons.append(f"{age}-year-old record fell")
    elif age <= 2:
        reasons.append("previous record was recent")
    return _build_score(
        "all_time_record",
        severity=88 + delta * 4,
        novelty=92 + min(age, 50) * 0.2,
        timeliness=94,
        confidence=78,  # provisional forecast data
        shareability=86 + delta * 3,
        sensitivity=10 if kind == "high" else 8,
        threshold=80,  # high bar — only elite records pass
        reasons=reasons,
    )


def score_monthly_record(new_temp_c: float, old_record_c: float, old_record_year: int, month: int, years_of_data: int, *, kind: str = "high") -> EditorialScore:
    """Hottest/coldest reading ever observed for this month of year."""
    delta = abs(new_temp_c - old_record_c)
    age = max(date.today().year - old_record_year, 0)
    month_name = ["", "January","February","March","April","May","June",
                  "July","August","September","October","November","December"][month]
    reasons = [
        f"{kind} temp ever observed in {month_name}",
        f"in {years_of_data} years of archive data",
    ]
    if delta >= 1.0:
        reasons.append(f"beat prior by {delta:.1f}C")
    return _build_score(
        "monthly_record",
        severity=78 + delta * 5,
        novelty=84,
        timeliness=90,
        confidence=74,
        shareability=78 + delta * 3,
        sensitivity=10,
        threshold=76,
        reasons=reasons,
    )


def score_anomaly(today_temp_c: float, historical_mean_c: float, anomaly_c: float, *, kind: str = "hot") -> EditorialScore:
    """Today's reading vs historical mean for this month. Pure anomaly signal."""
    abs_anomaly = abs(anomaly_c)
    reasons = [
        f"{'+' if kind == 'hot' else '-'}{abs_anomaly:.1f}C from normal for this month",
        f"historical mean: {historical_mean_c:.1f}C; today: {today_temp_c:.1f}C",
    ]
    # Anomaly scoring: 15C = baseline elite, 20C+ = extreme
    return _build_score(
        "anomaly",
        severity=72 + min(abs_anomaly - 15, 10) * 3,
        novelty=82,
        timeliness=92,
        confidence=82,
        shareability=80 + min(abs_anomaly - 15, 10) * 2,
        sensitivity=10,
        threshold=76,
        reasons=reasons,
    )


def score_record_streak(consecutive_days: int, peak_temp_c: float) -> EditorialScore:
    """A city has broken its daily record multiple days running."""
    reasons = [f"{consecutive_days} consecutive days of daily records"]
    if consecutive_days >= 10:
        reasons.append("double-digit streak")
    if consecutive_days >= 5:
        reasons.append("sustained pattern, not noise")
    return _build_score(
        "record_streak",
        severity=70 + min(consecutive_days, 20) * 1.5,
        novelty=80 + min(consecutive_days, 20) * 0.8,
        timeliness=88,
        confidence=76,
        shareability=78 + min(consecutive_days, 20) * 1.2,
        sensitivity=8,
        threshold=74,  # fires at 3+ days
        reasons=reasons,
    )


def score_simultaneous_records(city_count: int, sample_cities: list[str]) -> EditorialScore:
    """Multiple cities broke records on the same day — a pattern signal."""
    reasons = [
        f"{city_count} cities broke records today",
        "pattern signal, not isolated event",
    ]
    if city_count >= 10:
        reasons.append("mass event")
    return _build_score(
        "simultaneous_records",
        severity=74 + min(city_count - 5, 15) * 2,
        novelty=86,
        timeliness=94,
        confidence=84,
        shareability=82 + min(city_count - 5, 15) * 1.5,
        sensitivity=6,
        threshold=78,
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


def score_synthesis_fire_drought_heat(
    *,
    drought_d4_pct: float,
    fire_peak_frp: float,
    heat_peak_anomaly_c: float,
    component_count: dict,
    heat_kind: str,
) -> EditorialScore:
    """Score a Fire×Drought×Heat synthesis signal.

    Threshold 82 — synthesis is elite by definition. The minimum-viable
    case (1% D4, 250 MW fire, 4 °C anomaly, single fire + single heat)
    is still designed to clear the bar because merely _qualifying_ for
    the rule is itself a story; the scoring factor ranges above that
    reflect the amplification.
    """
    fires_n = int((component_count or {}).get("fires", 0) or 0)
    heats_n = int((component_count or {}).get("heats", 0) or 0)

    severity = 78 + drought_d4_pct * 0.3 + min(fire_peak_frp, 1500) / 25 + min(abs(heat_peak_anomaly_c), 15) * 1.8
    novelty = 88 + (6 if heat_kind == "all_time" else 0)
    timeliness = 90
    confidence = 78
    shareability = 82 + (4 if fires_n >= 2 else 0) + (4 if heats_n >= 2 else 0)
    sensitivity = 28

    reasons = [
        f"{drought_d4_pct:.0f}% in exceptional drought",
        f"peak fire {fire_peak_frp:.0f} MW",
        f"{heat_kind} heat record + {abs(heat_peak_anomaly_c):.1f}C above normal",
    ]
    return _build_score(
        "synthesis_fire_drought_heat",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=sensitivity,
        threshold=82,
        reasons=reasons,
    )
