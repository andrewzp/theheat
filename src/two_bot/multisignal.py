"""Phase D — optional cross-signal writer context (THEHEAT_MULTISIGNAL_CONTEXT).

Attaches up to a couple of OTHER same-cycle events to a candidate's bundle as
``related_signals`` so the writer can earn a synthesis-grade tweet from verifiable
facts. Default OFF. The window is deliberately conservative (codex must-fix #2):
exact same country AND within a short day window, capped — global / undated /
missing-country candidates are excluded both as host and as a related signal.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from src.two_bot.types import RelatedSignal

MAX_RELATED_SIGNALS = 2
RELATED_WINDOW_DAYS = 7

# Global / planetary / whole-country signal kinds are excluded from windowing
# (codex must-fix #2: exclude global / missing-coordinate signals). They have no
# meaningful regional locus, so they can be neither a host nor a related signal —
# "same country, same week" only means something for point/regional events.
_GLOBAL_OR_COARSE_KINDS: frozenset[str] = frozenset({
    "co2_milestone", "ch4_milestone", "sea_ice_record", "enso",
    "oscillation_transition", "oscillation_extreme", "oscillation_alignment",
    "ozone_hole_peak", "ice_mass_record", "global_disaster",
    "country_high", "country_low",
})


def multisignal_context_enabled() -> bool:
    """True only when THEHEAT_MULTISIGNAL_CONTEXT is explicitly truthy (default OFF)."""
    raw = os.environ.get("THEHEAT_MULTISIGNAL_CONTEXT", "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _is_regional(bundle) -> bool:
    """A bundle participates in windowing only if it is a point/regional signal —
    not a global / planetary / whole-country kind."""
    return bool(bundle) and getattr(bundle, "signal_kind", "") not in _GLOBAL_OR_COARSE_KINDS


def _bundle_country(bundle) -> str:
    """Canonical country for windowing: the bundle's ``country`` field, else a
    ``country`` entry in current_facts. Empty string = unknown (excluded)."""
    country = (getattr(bundle, "country", "") or "").strip()
    if country:
        return country
    for fact in getattr(bundle, "current_facts", None) or []:
        if isinstance(fact, dict) and fact.get("label") == "country":
            return str(fact.get("value") or "").strip()
    return ""


def _bundle_date(bundle) -> date | None:
    """Parse the bundle's ``when`` (the pinned date source) to a date, else None."""
    raw = str(getattr(bundle, "when", "") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _score_total(candidate) -> int:
    score = getattr(candidate, "score", None)
    try:
        return int(getattr(score, "total", 0) or 0)
    except (TypeError, ValueError):
        return 0


def attach_related_signals(
    queue,
    *,
    max_related: int = MAX_RELATED_SIGNALS,
    window_days: int = RELATED_WINDOW_DAYS,
) -> None:
    """Attach up to ``max_related`` same-country, same-window OTHER candidates to
    each candidate's ``bundle.related_signals`` (in place), ranked by score.

    Conservative window: exact country match AND ``|Δdays| <= window_days``.
    A candidate with no country or an unparseable date participates in neither
    direction. Distinct events only (same event_id never relates to itself).
    """
    metas = []
    for candidate in queue:
        bundle = getattr(candidate, "bundle", None)
        metas.append((
            candidate,
            _bundle_country(bundle) if bundle is not None else "",
            _bundle_date(bundle) if bundle is not None else None,
        ))

    for candidate, country, when in metas:
        if not country or when is None or not _is_regional(getattr(candidate, "bundle", None)):
            continue
        matches = []
        for other, other_country, other_when in metas:
            if other is candidate:
                continue
            if getattr(other, "event_id", None) == getattr(candidate, "event_id", None):
                continue
            if not other_country or other_country != country or other_when is None:
                continue
            if not _is_regional(getattr(other, "bundle", None)):
                continue
            if abs((other_when - when).days) > window_days:
                continue
            matches.append(other)

        matches.sort(key=_score_total, reverse=True)
        related = [
            RelatedSignal(
                event_id=other.event_id,
                signal_kind=other.bundle.signal_kind,
                where=other.bundle.where,
                when=other.bundle.when,
                headline_metric=other.bundle.headline_metric,
                country=_bundle_country(other.bundle),
            )
            for other in matches[:max_related]
        ]
        if related:
            candidate.bundle.related_signals = related


__all__ = [
    "MAX_RELATED_SIGNALS",
    "RELATED_WINDOW_DAYS",
    "attach_related_signals",
    "multisignal_context_enabled",
]
