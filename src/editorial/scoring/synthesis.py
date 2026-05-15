"""Synthesis editorial scoring."""



from __future__ import annotations



from ._shared import EditorialScore, _build_score



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
