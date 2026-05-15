"""Fire editorial scoring."""



from __future__ import annotations



from datetime import date

from ._shared import EditorialScore, _build_score



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
