"""Marine editorial scoring."""



from __future__ import annotations



from datetime import date

from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold



def score_coral_bleaching(dhw_value: float, tier: int, region: str) -> EditorialScore:
    severity = 58 + tier * 2.8 + max(dhw_value - tier, 0) * 2.5
    novelty = 66 + tier * 1.6
    timeliness = 92
    confidence = 94
    shareability = 58 + tier * 2.2 + (6 if region else 0)
    reasons = [
        f"DHW {dhw_value:.1f} °C-weeks",
        f"crossed {tier} °C-week bleaching threshold",
        "NOAA Coral Reef Watch regional virtual station",
    ]
    if region:
        reasons.append(region)
    return _build_score(
        "coral_bleaching",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=24,
        threshold=get_threshold("coral_bleaching"),
        reasons=reasons[:3],
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
        threshold=get_threshold("sea_ice_record"),
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
            threshold=get_threshold("ice_mass_record"),
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
        threshold=get_threshold("ice_mass_record"),
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
        threshold=get_threshold("extreme_wave"),
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
        threshold=get_threshold("marine_heatwave"),
        reasons=reasons,
    )


_NAMED_BASIN_SLUGS = {
    "north_atlantic",
    "subpolar_n_atlantic",
    "ne_pacific_blob",
    "mediterranean",
    "great_barrier_reef",
}

_REGIONAL_SST_TIER_THRESHOLDS = {
    1: 2.5,
    2: 3.5,
    3: 4.5,
}


def score_regional_sst_anomaly(
    region_slug: str,
    anomaly_c: float,
    tier: int,
) -> EditorialScore:
    """Score a per-region SST anomaly event.

    This is not a Hobday MHW score. Tiers are provisional absolute
    area-weighted basin-mean anomaly thresholds from NOAA CRW's published
    gridded anomaly.
    """

    tier_threshold = _REGIONAL_SST_TIER_THRESHOLDS.get(tier, 2.5)
    reasons = [
        f"{anomaly_c:+.2f}°C area-weighted basin-mean SST anomaly (NOAA CRW)",
        f"tier {tier} regional SST anomaly (threshold: {tier_threshold:+.1f}°C)",
        "NOAA Coral Reef Watch 5km published anomaly (gridded)",
    ]
    if tier == 3:
        reasons.append("extreme: +4.5°C basin-mean threshold crossed")

    named_basin_bump = 6 if region_slug in _NAMED_BASIN_SLUGS else 0
    return _build_score(
        "regional_sst_anomaly",
        severity=68 + tier * 4 + min((anomaly_c - 2.5) * 3, 10),
        novelty=76 + tier * 3,
        timeliness=86,
        confidence=86,
        shareability=72 + tier * 3 + named_basin_bump,
        sensitivity=6,
        threshold=get_threshold("regional_sst_anomaly"),
        reasons=reasons,
    )
