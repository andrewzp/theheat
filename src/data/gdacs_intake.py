"""Passive reconciliation of one returned GDACS GeoRSS capture.

Pure and bounded: no network, environment, command or storage access. Fresh,
independently qualified explicit-current rows are grouped by the exact source
event key. More than one episode identity, or same-episode rows that disagree,
leave the capture's current selection ambiguous for that event; nothing here
chooses an episode by order, recency, severity or spelling. That is a hold on
unresolved returned data, not a finding about which episode is correct.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

AMBIGUITY_REASONS = ("multiple_current_episodes", "conflicting_episode_payloads")


@dataclass(frozen=True)
class Contender:
    """One fresh explicit-current row whose episode level fits its overall level."""

    source_key: tuple[str, str]  # exact stripped (gdacs:eventtype, gdacs:eventid)
    episode_id: str
    event: Any  # GlobalDisasterEvent built by the existing adapter
    meets_threshold: bool  # episode level at or above the requested tier


def capture_sha256(text: str) -> str:
    """Identity of one complete returned capture: its exact decoded body."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def projection(event) -> dict:
    """The complete candidate-bearing projection, including source/time fields."""
    return asdict(event)


def projection_sha256(event) -> str:
    encoded = json.dumps(projection(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def intake_identity(event, capture: str) -> tuple[str, str, str]:
    """Internal admission identity: capture, exact source key and projection.

    It stays in staging/admission diagnostics; it never enters a bundle, prompt,
    cache fingerprint or persisted record.
    """
    return capture, "\x1f".join(source_key(event)), projection_sha256(event)


def _differing_fields(events) -> list[str]:
    rows = [projection(event) for event in events]
    fields = set().union(*rows)
    differing = {field for field in fields if any(row.get(field) != rows[0].get(field) for row in rows)}
    if "source_provenance" in differing:
        differing.discard("source_provenance")
        provenance = [row.get("source_provenance") or {} for row in rows]
        keys = set().union(*provenance)
        differing.update("source_provenance." + key for key in keys
                         if any(p.get(key) != provenance[0].get(key) for p in provenance))
    return sorted(differing)


def source_key(event) -> tuple[str, str]:
    return event.source_provenance.get("eventtype", ""), event.source_event_id


def staged_order(events) -> list:
    """Canonical staging order by exact source key, never by XML position."""
    return sorted(events, key=source_key)


def reconcile(contenders: list[Contender]) -> tuple[list, dict]:
    """Return the selected events and bounded reconciliation counts.

    The selected set and every selected event are independent of XML item
    order; the list keeps first-appearance order for existing parser callers,
    and staging applies staged_order. Counts cover contenders only; malformed,
    stale, unverified or inconsistent rows keep their existing diagnostics.

    Reconciliation (all integers):
      contender_items = ambiguous_items + exact_duplicate_items
                        + (contender_groups - ambiguous_groups)
      threshold_items = withheld_ambiguous_alerts + selected_groups
                        + exact_duplicate_threshold_items
    threshold_items are exactly the rows that passed every settled per-item
    gate; the parser's current_candidates_examined equals withheld current +
    withheld selected (time) + threshold_items.
    """
    groups: dict[tuple[str, str], list[Contender]] = defaultdict(list)
    for contender in contenders:
        groups[contender.source_key].append(contender)
    selected = []
    by_reason = dict.fromkeys(AMBIGUITY_REASONS, 0)
    conflicting: dict[str, int] = {}
    ambiguous_items = withheld = duplicates = duplicate_threshold = 0
    for rows in groups.values():
        reason = None
        if len({row.episode_id for row in rows}) > 1:
            reason = "multiple_current_episodes"
        elif len({projection_sha256(row.event) for row in rows}) > 1:
            reason = "conflicting_episode_payloads"
            for field in _differing_fields([row.event for row in rows]):
                conflicting[field] = conflicting.get(field, 0) + 1
        if reason is not None:
            by_reason[reason] += 1
            ambiguous_items += len(rows)
            withheld += sum(row.meets_threshold for row in rows)
            continue
        # Exact-equivalent rows of one episode are one candidate; keep the first
        # object only because every retained field is identical.
        duplicates += len(rows) - 1
        if rows[0].meets_threshold:
            duplicate_threshold += len(rows) - 1
            selected.append(rows[0].event)
    counts = dict(contender_items=len(contenders), contender_groups=len(groups),
                  threshold_items=sum(row.meets_threshold for row in contenders),
                  selected_groups=len(selected), exact_duplicate_items=duplicates,
                  exact_duplicate_threshold_items=duplicate_threshold,
                  ambiguous_groups=sum(by_reason.values()), ambiguous_items=ambiguous_items,
                  withheld_ambiguous_alerts=withheld, ambiguous_by_reason=by_reason,
                  conflicting_fields=dict(sorted(conflicting.items())))
    return selected, counts
