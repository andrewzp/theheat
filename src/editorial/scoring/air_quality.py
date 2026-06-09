"""Air-quality editorial scoring."""

from __future__ import annotations

from src.editorial.thresholds import get_threshold

from ._shared import EditorialScore, _build_score


def score_pm25_hazard(
    pm25_24h_mean: float,
    tier: int,
    who_multiple: float,
) -> EditorialScore:
    """Score a CAMS model PM2.5 hazard event."""
    tier_bonus = (tier - 1) * 12
    elite_bonus = 8 if tier >= 3 else 0
    reasons = [
        (
            f"PM2.5 {pm25_24h_mean:.0f} μg/m³ 24h-mean "
            f"({who_multiple:.1f}x WHO 2021 24h guideline of 15 μg/m³)"
        ),
        f"tier {tier} of 3 ({['>=150', '>=250', '>=350'][tier - 1]} μg/m³ 24h-mean)",
        "CAMS global model 0.4 degrees, about 45 km; model estimate, not station-measured",
    ]
    return _build_score(
        "air_quality_hazard",
        severity=62 + tier_bonus + elite_bonus,
        novelty=80,
        timeliness=88,
        confidence=78,
        shareability=76 + tier_bonus * 0.7 + elite_bonus * 0.5,
        sensitivity=8,
        threshold=get_threshold("air_quality_hazard"),
        reasons=reasons,
    )


def score_dust_event(dust_daily_max: float, tier: int) -> EditorialScore:
    """Score a CAMS model mineral dust event."""
    tier_bonus = (tier - 1) * 10
    reasons = [
        f"mineral dust {dust_daily_max:.0f} μg/m³ daily-max",
        f"tier {tier} of 3 ({['>=500', '>=2000', '>=5000'][tier - 1]} μg/m³)",
        "CAMS global model 0.4 degrees, about 45 km; mineral dust model estimate",
    ]
    return _build_score(
        "dust_event",
        severity=58 + tier_bonus,
        novelty=78,
        timeliness=86,
        confidence=76,
        shareability=68 + tier_bonus * 0.5,
        sensitivity=4,
        threshold=get_threshold("dust_event"),
        reasons=reasons,
    )
