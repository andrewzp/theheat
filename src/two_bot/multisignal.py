"""Phase D — optional cross-signal writer context (THEHEAT_MULTISIGNAL_CONTEXT).

Attaches up to a couple of OTHER same-cycle events to a candidate's bundle as
``related_signals`` so the writer can earn a synthesis-grade tweet from verifiable
facts. Default OFF. The window is deliberately conservative (codex must-fix #2):
exact same country AND within a short day window, capped — global / undated /
missing-country candidates are excluded both as host and as a related signal.
"""

from __future__ import annotations

import os
import json
import logging
from datetime import date, datetime

from src.two_bot.strict_contract import _evidence_default
from src.two_bot.types import RelatedSignal

MAX_RELATED_SIGNALS = 2
RELATED_WINDOW_DAYS = 7
logger = logging.getLogger(__name__)

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


def _identity(value) -> str | None:
    return value if isinstance(value, str) and value and value == value.strip() else None


def _summary(candidate) -> tuple[str, RelatedSignal]:
    """Compare and detach exactly the facts that will reach the writer."""
    bundle = candidate.bundle
    from src.data.fire_evidence import is_thermal, validate_bundle
    from src.data.source_status import SourceFetchError

    receipt = None
    if is_thermal(bundle):
        try:
            validate_bundle(bundle)
        except SourceFetchError as exc:
            raise ValueError("Unqualified thermal related observation") from exc
        receipt = bundle.raw_signal_dump["acquisition_provenance"]
    signal = RelatedSignal(
        event_id=candidate.event_id, signal_kind=bundle.signal_kind,
        where=bundle.where, when=bundle.when, headline_metric=bundle.headline_metric,
        country=_bundle_country(bundle), acquisition_evidence=receipt,
    )
    encoded = json.dumps(signal.to_dict(), sort_keys=True, allow_nan=False,
                         ensure_ascii=False, default=_evidence_default)
    encoded.encode("utf-8")
    return encoded, RelatedSignal(**json.loads(encoded))


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
    direction. Each identity contributes at most once. Conflicting summaries for
    one identity are withheld, even when one falls outside the host's window.
    This does not adjudicate or remove the underlying primary candidates.
    """
    queue = list(queue)
    for candidate in queue:
        bundle = getattr(candidate, "bundle", None)
        if bundle is not None:
            bundle.related_signals = []

    # Resolve identities before windowing/ranking. Otherwise a low-ranked or
    # out-of-window duplicate could conceal conflicting evidence for the same ID.
    metas = []
    summaries: dict[str, tuple[str, RelatedSignal, int]] = {}
    invalid: set[str] = set()
    conflicting: set[str] = set()
    invalid_rows = 0
    for candidate in queue:
        bundle = getattr(candidate, "bundle", None)
        candidate_id = _identity(getattr(candidate, "event_id", None))
        bundle_id = _identity(getattr(bundle, "event_id", None))
        if candidate_id is None or bundle_id is None or candidate_id != bundle_id:
            invalid.update(value for value in (candidate_id, bundle_id) if value is not None)
            invalid_rows += 1
            continue
        try:
            encoded, signal = _summary(candidate)
        except (ValueError, TypeError, UnicodeError, OverflowError, AttributeError, RecursionError):
            invalid.add(candidate_id)
            invalid_rows += 1
            continue
        score = _score_total(candidate)
        previous = summaries.get(candidate_id)
        if previous is not None:
            if previous[0] != encoded:
                conflicting.add(candidate_id)
            score = max(score, previous[2])
        summaries[candidate_id] = (encoded, signal, score)
        metas.append((candidate, candidate_id, signal.country, _bundle_date(bundle)))

    if invalid_rows or conflicting:
        logger.info("Related-signal context withheld: invalid_identity_rows=%d conflicting_identities=%d",
                    invalid_rows, len(conflicting))
    eligible = {key: value for key, value in summaries.items() if key not in invalid | conflicting}
    limit = max(0, min(max_related, MAX_RELATED_SIGNALS))

    for candidate, event_id, country, when in metas:
        if not country or when is None or not _is_regional(getattr(candidate, "bundle", None)):
            continue
        matches = []
        for other_id, (encoded, other, score) in eligible.items():
            if other_id == event_id:
                continue
            other_country, other_when = other.country, _bundle_date(other)
            if not other_country or other_country != country or other_when is None:
                continue
            if not _is_regional(other):
                continue
            if abs((other_when - when).days) > window_days:
                continue
            matches.append((encoded, score))

        matches.sort(key=lambda item: item[1], reverse=True)
        candidate.bundle.related_signals = [
            RelatedSignal(**json.loads(encoded)) for encoded, _ in matches[:limit]
        ]


__all__ = [
    "MAX_RELATED_SIGNALS",
    "RELATED_WINDOW_DAYS",
    "attach_related_signals",
    "multisignal_context_enabled",
]
