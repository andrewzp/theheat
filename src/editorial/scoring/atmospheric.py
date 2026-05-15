"""Atmospheric editorial scoring."""



from __future__ import annotations



from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold



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
        threshold=get_threshold("co2_milestone"),
        reasons=reasons,
    )

def score_ch4_milestone(ppb_crossed: int, actual_ppb: float) -> EditorialScore:
    severity = 58 + max(ppb_crossed - 1900, 0) * 0.25
    novelty = 90
    timeliness = 74
    confidence = 99
    shareability = 78 + max(actual_ppb - ppb_crossed, 0) * 1.5
    reasons = [
        f"new 10-ppb methane milestone above {ppb_crossed} ppb",
        "pre-industrial methane baseline available",
        "high-confidence NOAA GML source",
    ]
    return _build_score(
        "ch4_milestone",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence,
        shareability=shareability,
        sensitivity=3,
        threshold=get_threshold("ch4_milestone"),
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
        threshold=get_threshold("enso"),
        reasons=reasons,
    )
