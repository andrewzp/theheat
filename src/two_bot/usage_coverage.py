"""Bounded original cumulative coverage witnesses, paired with usage-ledger.js.

Legacy monetary/token totals still merge by MAX. Witnesses retain contradictions
that a later larger counter could otherwise hide. They are not a per-call ledger
or proof that cumulative snapshots contain disjoint provider calls.
"""
from __future__ import annotations

import math

COVERAGE_COUNTS = ("priced_calls", "unpriced_calls", "missing_usage_calls")
COVERAGE_FIELDS = (*COVERAGE_COUNTS, "priced_usd")
SNAPSHOT_FIELDS = ("calls", "usd", *COVERAGE_FIELDS)
SNAPSHOT_LIMIT = 32
SNAPSHOTS = "cost_coverage_snapshots"
OVERFLOW = "cost_coverage_overflow"
INVALID = "cost_coverage_invalid"


def money(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def count(value) -> bool:
    # JSON has one numeric type in JavaScript: accept integral finite numbers,
    # never booleans. SDK capture separately requires actual integer metadata.
    return (type(value) in (int, float) and 0 <= value <= 2**53 - 1
            and (type(value) is int or value.is_integer()))


def coverage_fields_valid(agg: dict) -> bool:
    return all(count(agg.get(field)) for field in COVERAGE_COUNTS) and money(agg.get("priced_usd"))


def _snapshot_valid(values) -> bool:
    if not isinstance(values, (list, tuple)) or len(values) != len(SNAPSHOT_FIELDS):
        return False
    calls, usd, priced, unpriced, missing, priced_usd = values
    return (all(count(value) for value in (calls, priced, unpriced, missing))
            and money(usd) and money(priced_usd) and priced + unpriced <= calls
            and missing <= unpriced and priced_usd <= usd + 0.000001
            and (priced > 0 or priced_usd == 0))


def coverage_evidence(agg: dict) -> dict:
    """Inspect raw values BEFORE legacy normalization; never mint merged leaves."""
    result: dict = {}
    invalid = bool(agg.get(INVALID))
    overflow = bool(agg.get(OVERFLOW))
    snapshots: list = []
    if SNAPSHOTS in agg:
        raw = agg[SNAPSHOTS]
        if not isinstance(raw, list) or not raw or any(not _snapshot_valid(value) for value in raw):
            invalid = True
        else:
            snapshots = raw
            overflow = overflow or len(raw) > SNAPSHOT_LIMIT
            # A generated MAX row may have incompatible combined arithmetic,
            # but every stored leaf must be bounded by its retained projection.
            if (not count(agg.get("calls")) or not money(agg.get("usd")) or not coverage_fields_valid(agg)
                or any(any(agg[field] < value[i] for i, field in enumerate(SNAPSHOT_FIELDS)) for value in raw)
                or (not overflow and any(agg[field] != max(value[i] for value in raw)
                                        for i, field in enumerate(SNAPSHOT_FIELDS) if field in COVERAGE_FIELDS))):
                invalid = True
    elif not invalid and not overflow and any(field in agg for field in COVERAGE_FIELDS):
        candidate = [agg.get(field) for field in SNAPSHOT_FIELDS]
        if _snapshot_valid(candidate):
            snapshots = [candidate]
        else:
            invalid = True
    if snapshots:
        result[SNAPSHOTS] = [list(value) for value in sorted(set(tuple(value) for value in snapshots))[:SNAPSHOT_LIMIT]]
    if invalid:
        result[INVALID] = True
    if overflow:
        result[OVERFLOW] = True
    return result


def union_evidence(*items: dict) -> dict:
    snapshots = sorted(set(tuple(value) for item in items for value in item.get(SNAPSHOTS, [])))
    result: dict = {SNAPSHOTS: [list(value) for value in snapshots[:SNAPSHOT_LIMIT]]} if snapshots else {}
    if any(item.get(INVALID) for item in items):
        result[INVALID] = True
    if len(snapshots) > SNAPSHOT_LIMIT or any(item.get(OVERFLOW) for item in items):
        result[OVERFLOW] = True
    return result


def evidence_inconsistent(agg: dict) -> bool:
    evidence = coverage_evidence(agg)
    if evidence.get(INVALID) or evidence.get(OVERFLOW):
        return True
    snapshots = evidence.get(SNAPSHOTS, [])
    # Retain a contradictory pair even if a later larger snapshot makes the
    # final MAX row's arithmetic look consistent. Grouping cannot erase it.
    return any(not _snapshot_valid([max(a, b) for a, b in zip(left, right)])
               for i, left in enumerate(snapshots) for right in snapshots[i + 1:])
