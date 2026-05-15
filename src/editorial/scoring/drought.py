"""Drought editorial scoring."""



from __future__ import annotations



from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold



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
            threshold=get_threshold("drought_empty"),
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
        threshold=get_threshold("drought"),
        reasons=reasons,
    )
