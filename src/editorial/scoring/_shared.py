"""Shared editorial scoring primitives."""



from __future__ import annotations



from dataclasses import dataclass



from src.editorial._util import clamp as _clamp



def _label(total: int) -> str:
    if total >= 85:
        return "elite"
    if total >= 72:
        return "strong"
    if total >= 60:
        return "borderline"
    return "weak"

def _compute_total(
    *,
    severity: float,
    novelty: float,
    timeliness: float,
    confidence: float,
    shareability: float,
    sensitivity: float,
) -> int:
    base = (
        0.28 * severity
        + 0.24 * novelty
        + 0.16 * timeliness
        + 0.16 * confidence
        + 0.16 * shareability
    )
    penalty = 0.20 * sensitivity
    return _clamp(base - penalty)

@dataclass(frozen=True)
class EditorialScore:
    category: str
    severity: int
    novelty: int
    timeliness: int
    confidence: int
    shareability: int
    sensitivity: int
    total: int
    threshold: int
    reasons: list[str]

    @property
    def passes(self) -> bool:
        return self.total >= self.threshold

    @property
    def label(self) -> str:
        return _label(self.total)

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "novelty": self.novelty,
            "timeliness": self.timeliness,
            "confidence": self.confidence,
            "shareability": self.shareability,
            "sensitivity": self.sensitivity,
            "total": self.total,
            "threshold": self.threshold,
            "passes": self.passes,
            "label": self.label,
            "reasons": self.reasons,
        }

def _build_score(
    category: str,
    *,
    severity: float,
    novelty: float,
    timeliness: float,
    confidence: float,
    shareability: float,
    sensitivity: float,
    threshold: int,
    reasons: list[str],
) -> EditorialScore:
    """Construct an EditorialScore from raw arithmetic metrics.

    Metric params accept ``float`` so callers can pass results of
    weighted-sum formulas without manual ``int()`` casts. ``_clamp``
    (from ``editorial/_util``) coerces back to ``int`` before the
    EditorialScore dataclass enforces ``int`` storage — wire format
    unchanged.
    """
    return EditorialScore(
        category=category,
        severity=_clamp(severity),
        novelty=_clamp(novelty),
        timeliness=_clamp(timeliness),
        confidence=_clamp(confidence),
        shareability=_clamp(shareability),
        sensitivity=_clamp(sensitivity),
        total=_compute_total(
            severity=_clamp(severity),
            novelty=_clamp(novelty),
            timeliness=_clamp(timeliness),
            confidence=_clamp(confidence),
            shareability=_clamp(shareability),
            sensitivity=_clamp(sensitivity),
        ),
        threshold=threshold,
        reasons=reasons,
    )
