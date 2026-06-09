"""Wet-bulb extreme editorial scoring."""

from __future__ import annotations

from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold

_TIER_SEVERITY_BOOST = {1: 0, 2: 8, 3: 20}
_TIER_NOVELTY_BOOST = {1: 0, 2: 6, 3: 14}
_TIER_SHARE_BOOST = {1: 0, 2: 6, 3: 16}


def score_wet_bulb_extreme(tw_c: float, tier: int) -> EditorialScore:
    """Score a wet-bulb extreme event."""
    tier = max(1, min(3, tier))
    severity = 60 + (tw_c - 31.0) * 3.5 + _TIER_SEVERITY_BOOST[tier]
    novelty = 74 + _TIER_NOVELTY_BOOST[tier]
    timeliness = 94
    confidence = 80
    shareability = 74 + _TIER_SHARE_BOOST[tier]

    reasons = [f"wet-bulb tier {tier}: TW {tw_c:.1f}C"]
    if tier == 3:
        reasons.append("tier-3 threshold at 35C TW")
    if tier >= 2 and tw_c >= 33.0:
        reasons.append("sustained exposure dangerous even for fit adults")

    return _build_score(
        "wet_bulb_extreme",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=10,
        threshold=get_threshold("wet_bulb_extreme"),
        reasons=reasons,
    )
