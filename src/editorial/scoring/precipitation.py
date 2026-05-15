"""Precipitation and snow editorial scoring."""

from __future__ import annotations

from ..thresholds import get_threshold
from ._shared import EditorialScore, _build_score


def score_precipitation_extreme(
    mm_total: float,
    period_days: int,
    deviation_from_record: float | None,
    region: str,
) -> EditorialScore:
    margin = max(deviation_from_record or 0.0, 0.0)
    period_bonus = 6 if period_days >= 7 else 3 if period_days >= 3 else 0
    severity = 56 + min(mm_total / max(period_days, 1) * 0.45, 28) + period_bonus
    novelty = 64 + min(margin * 0.7, 24)
    shareability = 58 + min(mm_total / 10.0, 24) + (4 if region else 0)
    reasons = [
        f"{mm_total:.0f} mm in {period_days} day{'s' if period_days != 1 else ''}",
        (
            f"{margin:.0f} mm above prior record"
            if margin > 0
            else "extreme multi-day rainfall threshold"
        ),
        region or "GPM IMERG daily precipitation",
    ]
    return _build_score(
        "precipitation_extreme",
        severity=severity,
        novelty=novelty,
        timeliness=90,
        confidence=82,
        shareability=shareability,
        sensitivity=28,
        threshold=get_threshold("precipitation_extreme"),
        reasons=reasons[:3],
    )


def score_snow_extreme(
    mm_swe: float,
    deviation_from_record: float | None,
    region: str,
) -> EditorialScore:
    margin = max(deviation_from_record or 0.0, 0.0)
    reasons = [
        f"{mm_swe:.0f} mm snow-water equivalent",
        (
            f"{margin:.0f} mm SWE above prior record"
            if margin > 0
            else "multi-day heavy-snow SWE threshold"
        ),
        region or "NSIDC Snow Today",
    ]
    return _build_score(
        "snow_extreme",
        severity=58 + min(mm_swe * 0.55, 30),
        novelty=66 + min(margin * 0.8, 22),
        timeliness=88,
        confidence=86,
        shareability=62 + min(mm_swe * 0.25, 20),
        sensitivity=24,
        threshold=get_threshold("snow_extreme"),
        reasons=reasons[:3],
    )


def score_seasonal_snow_record(
    total_mm: float,
    years_of_archive: int,
    region: str,
) -> EditorialScore:
    reasons = [
        f"{total_mm:.0f} mm seasonal SWE",
        f"{years_of_archive}-year archive",
        region or "NSIDC Snow Today",
    ]
    return _build_score(
        "seasonal_snow_record",
        severity=60 + min(total_mm / 35.0, 24),
        novelty=76 + min(years_of_archive, 40) * 0.3,
        timeliness=72,
        confidence=86,
        shareability=68 + min(total_mm / 80.0, 14),
        sensitivity=18,
        threshold=get_threshold("seasonal_snow_record"),
        reasons=reasons,
    )
