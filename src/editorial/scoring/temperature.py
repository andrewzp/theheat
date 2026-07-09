"""Temperature editorial scoring."""



from __future__ import annotations



from datetime import date

from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold



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
        threshold=get_threshold("record"),
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
        threshold=get_threshold(f"country_{kind}"),
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
        threshold=get_threshold("record_low"),
        reasons=reasons or ["notable cold record"],
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
        threshold=get_threshold("all_time_record"),  # high bar - only elite records pass
        reasons=reasons,
    )

def score_monthly_record(new_temp_c: float, old_record_c: float, old_record_year: int, month: int, years_of_data: int, *, kind: str = "high") -> EditorialScore:
    """Hottest/coldest reading ever observed for this month of year."""
    delta = abs(new_temp_c - old_record_c)
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
        threshold=get_threshold("monthly_record"),
        reasons=reasons,
    )

def score_anomaly(today_temp_c: float, historical_mean_c: float, anomaly_c: float, *, kind: str = "hot") -> EditorialScore:
    """Today's reading vs historical mean for this month. Pure anomaly signal."""
    abs_anomaly = abs(anomaly_c)
    reasons = [
        f"{'+' if kind == 'hot' else '-'}{abs_anomaly:.1f}C from normal for this month",
        f"historical mean: {historical_mean_c:.1f}C; today: {today_temp_c:.1f}C",
    ]
    # Anomaly scoring: 15C = baseline elite, 20C+ = extreme.
    # Threshold 74 (not 76) admits 11–14C anomalies — empirically extraordinary
    # but rejected by the prior bar. 8C and below still self-filter via the
    # formula's downside penalty. See test_anomaly_11c_florida_cold_passes.
    return _build_score(
        "anomaly",
        severity=72 + min(abs_anomaly - 15, 10) * 3,
        novelty=82,
        timeliness=92,
        confidence=82,
        shareability=80 + min(abs_anomaly - 15, 10) * 2,
        sensitivity=10,
        threshold=get_threshold("anomaly"),
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
        threshold=get_threshold("record_streak"),  # fires at 3+ days
        reasons=reasons,
    )

def score_absolute_extreme(
    temp_c: float,
    lat: float,
    band_label: str,
    threshold_c: float,
    *,
    kind: str = "hot",
) -> EditorialScore:
    """Score a reading that exceeds the absolute threshold for its latitude band."""
    margin = abs(temp_c - threshold_c)
    severity = 80 + margin * 2.0
    novelty = 88
    timeliness = 94
    confidence = 80
    shareability = 84 + margin * 1.5
    reasons = [
        f"{kind} absolute extreme for {band_label} latitude band",
        f"{temp_c:.1f}C vs {threshold_c:.1f}C band threshold",
        f"latitude {lat:.1f}",
    ]
    if margin >= 5:
        reasons.append(f"{margin:.1f}C over band threshold")
    return _build_score(
        "absolute_extreme",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=10,
        threshold=get_threshold("absolute_extreme"),
        reasons=reasons,
    )

def score_regional_anomaly(
    mean_anomaly_c: float,
    sustained_days: int,
    cities_sampled: int,
) -> EditorialScore:
    """Score a sustained regional anomaly (a point index over N sampled cities).

    The detection gate (+6C absolute AND >=2sigma AND >=50% point support over
    >=3 consecutive complete days) is the noise filter; this score is for ranking.
    Calibration: minimal 6C/3d/3-city -> 78 (clears 76 by +2); elite 8C/7d/6-city -> 83.
    """
    margin = mean_anomaly_c - 6.0
    reasons = [
        f"{mean_anomaly_c:.1f}C sampled-city mean anomaly above ERA5 daily normal",
        f"sustained {sustained_days} consecutive days across {cities_sampled} sampled cities",
        "point index, not an area-weighted national mean",
    ]
    if margin >= 2:
        reasons.append(f"{margin:.1f}C over the +6C regional-anomaly floor")
    return _build_score(
        "regional_anomaly",
        severity=72 + min(margin, 8) * 3 + min(sustained_days - 3, 7) * 2,
        novelty=84,
        timeliness=90,
        confidence=72 + min(cities_sampled, 8) * 1.5,
        shareability=80 + min(margin, 6) * 2,
        sensitivity=10,
        threshold=get_threshold("regional_anomaly"),
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
        threshold=get_threshold("simultaneous_records"),
        reasons=reasons,
    )

def score_heat_records_cluster(
    *,
    all_time_count: int,
    monthly_count: int,
    daily_count: int,
    country_count: int,
    region_name: str | None = None,
) -> EditorialScore:
    """A spatially-coherent cluster of same-day heat records — a regional heat
    event (the "records are falling across [region]" story), not scattered records.

    Scores on record SIGNIFICANCE (all-time >> monthly >> daily), not a raw daily
    count: an all-time or monthly record carries far more weight than "warmest
    this-date here". The caller applies ``is_significant_cluster`` FIRST, so a
    daily-only cluster is never scored — every cluster reaching this function has
    already cleared the significance gate, and this score ranks it (and clears the
    threshold) accordingly. A documented region or a multi-country span adds
    novelty; spatial breadth (city count) adds shareability.
    """
    city_count = all_time_count + monthly_count + daily_count
    reasons = [
        f"{city_count} cities set heat records in one spatial cluster",
        "spatially coherent — a regional heat event, not scattered records",
    ]
    if all_time_count:
        reasons.append(f"{all_time_count} all-time record(s) in the cluster")
    if monthly_count:
        reasons.append(f"{monthly_count} monthly record(s) in the cluster")
    if region_name:
        reasons.append(f"documented region: {region_name}")
    if country_count >= 3:
        reasons.append(f"spans {country_count} countries")
    if city_count >= 15:
        reasons.append("mass event")
    return _build_score(
        "heat_records_cluster",
        # Significance-weighted: all-time and monthly records dominate; daily
        # records add only a sliver. A minimal significant cluster (one all-time
        # record) clears the threshold; more/heavier records rank higher.
        severity=74 + all_time_count * 6 + monthly_count * 3 + daily_count * 0.5,
        novelty=87 + (5 if region_name else 0) + (4 if country_count >= 3 else 0),
        timeliness=94,
        confidence=86,
        shareability=82 + min(city_count - 6, 24) * 1.0,
        sensitivity=6,
        threshold=get_threshold("heat_records_cluster"),
        reasons=reasons,
    )
