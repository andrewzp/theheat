"""Atmospheric editorial scoring."""



from __future__ import annotations



from ._shared import EditorialScore, _build_score



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
        threshold=58,
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

def score_oscillation_transition(
    index_name: str,
    value: float,
    prev_duration_months: int,
) -> EditorialScore:
    reasons = [
        f"{index_name} phase crossed zero at {value:+.2f}",
        f"previous phase lasted {prev_duration_months} months",
        "monthly NOAA climate-mode index",
    ]
    return _build_score(
        "oscillation_transition",
        severity=56 + abs(value) * 10,
        novelty=82,
        timeliness=72,
        confidence=96,
        shareability=66 + min(prev_duration_months, 24),
        sensitivity=5,
        threshold=60,
        reasons=reasons,
    )

def score_oscillation_extreme(index_name: str, sigma_excursion: float) -> EditorialScore:
    reasons = [
        f"{index_name} at {sigma_excursion:.1f} sigma from its long-term mean",
        "monthly climate-mode excursion",
        "long-arc context available",
    ]
    return _build_score(
        "oscillation_extreme",
        severity=58 + sigma_excursion * 8,
        novelty=78 + sigma_excursion * 3,
        timeliness=70,
        confidence=95,
        shareability=68 + sigma_excursion * 4,
        sensitivity=5,
        threshold=64,
        reasons=reasons,
    )

def score_ozone_hole_peak(
    area_msqkm: float,
    vs_record_year: int | None,
) -> EditorialScore:
    record_reason = (
        f"record comparison anchored to {vs_record_year}"
        if vs_record_year is not None
        else "long-term Ozone Watch comparison available"
    )
    reasons = [
        f"Antarctic ozone hole peaked at {area_msqkm:.1f} million km2",
        record_reason,
        "recovery framing from NASA Ozone Watch",
    ]
    return _build_score(
        "ozone_hole_peak",
        severity=58 + area_msqkm * 0.8,
        novelty=86,
        timeliness=76,
        confidence=96,
        shareability=74,
        sensitivity=4,
        threshold=64,
        reasons=reasons,
    )
