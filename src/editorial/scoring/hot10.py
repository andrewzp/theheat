"""Hot10 editorial scoring."""



from __future__ import annotations



from ._shared import EditorialScore, _build_score
from src.editorial.thresholds import get_threshold



def score_hot10(top_anomaly_c: float, city_count: int, change_count: int) -> EditorialScore:
    reasons = [f"top anomaly +{top_anomaly_c:.1f}C"]
    if change_count:
        reasons.append(f"{change_count} notable ranking changes")
    reasons.append("daily recurring scoreboard")
    return _build_score(
        "hot10",
        severity=52 + top_anomaly_c * 5,
        novelty=60 + min(change_count, 5) * 5,
        timeliness=88,
        confidence=82,
        shareability=66 + min(city_count, 10),
        sensitivity=6,
        threshold=get_threshold("hot10"),
        reasons=reasons,
    )
