"""Offline concurrent source-snapshot corruption and recovery regressions."""
from copy import deepcopy
from itertools import permutations

from src.data import places
from src.orchestrator.world_cache import merge_caches
from tests.temperature_helpers import snapshot


def source_row(value=40.0, retrieved_at="2026-06-26T00:00:00Z"):
    identity = {**places.resolve_place("Madrid", "Spain"), "source_product": places.CACHE_PRODUCT}
    row = snapshot({"city": "Madrid", "as_of": "2026-06-26", "identity": identity,
                    "all_time_max": [40.0, 2025]})
    # All variations deliberately retain the same claimed baseline revision ID.
    row["all_time_max"] = [value, 2025]
    row["baseline"]["retrieved_at"] = retrieved_at
    key = places.cache_key(identity["city"], identity["country"], identity["lat"], identity["lon"])
    return key, row


def test_same_claimed_revision_cannot_hide_different_comparator_payload():
    key, a = source_row()
    _, b = source_row(48.0)
    before = deepcopy((a, b))
    merged = merge_caches({key: a}, {key: b})
    assert key not in merged
    assert merged == merge_caches({key: b}, {key: a})
    versions = merged["_meta"]["baseline_conflicts"][key]["versions"]
    assert sorted(row["all_time_max"][0] for row in versions.values()) == [40.0, 48.0]
    assert (a, b) == before


def test_three_way_quarantine_union_preserves_colliding_caller_version_ids():
    key, a = source_row()
    _, b = source_row(48.0)
    _, c = source_row(42.0)
    for left, middle, right in permutations([a, b, c]):
        ab = merge_caches({key: left}, {key: middle})
        ac = merge_caches({key: left}, {key: right})
        result = merge_caches(ab, ac)
        assert result == merge_caches(ac, ab)
        assert result == merge_caches(result, ab)
        versions = result["_meta"]["baseline_conflicts"][key]["versions"]
        assert sorted(row["all_time_max"][0] for row in versions.values()) == [40.0, 42.0, 48.0]
        # Legacy conflict maps could have used the same claimed revision key.
        caller_id = a["baseline"]["revision_id"]
        legacy_left = {"_meta": {"baseline_conflicts": {key: {
            "retrieved_at": a["baseline"]["retrieved_at"], "versions": {caller_id: left},
        }}}}
        legacy_right = {"_meta": {"baseline_conflicts": {key: {
            "retrieved_at": a["baseline"]["retrieved_at"], "versions": {caller_id: right},
        }}}}
        legacy = merge_caches(legacy_left, legacy_right)
        assert len(legacy["_meta"]["baseline_conflicts"][key]["versions"]) == 2
        assert legacy == merge_caches(legacy_right, legacy_left)


def test_later_source_verification_recovers_without_erasing_conflict_evidence():
    key, a = source_row()
    _, b = source_row(48.0)
    conflict = merge_caches({key: a}, {key: b})
    _, later = source_row(39.0, "2026-06-26T01:00:00Z")
    recovered = merge_caches(conflict, {key: later})
    assert recovered[key] == later
    assert recovered == merge_caches({key: later}, conflict)
    assert recovered["_meta"]["baseline_conflicts"] == conflict["_meta"]["baseline_conflicts"]
    # A replay of the old conflicting writer cannot bring the old peak back.
    replayed = merge_caches(recovered, {key: b})
    assert replayed[key] == later
    assert replayed["_meta"]["baseline_conflicts"] == conflict["_meta"]["baseline_conflicts"]


def test_offset_spellings_are_compared_as_instants_before_conflict_or_recovery():
    key, a = source_row(retrieved_at="2026-06-26T00:00:00Z")
    _, b = source_row(48.0, "2026-06-25T20:00:00-04:00")
    conflict = merge_caches({key: a}, {key: b})
    assert key not in conflict
    _, later = source_row(39.0, "2026-06-25T20:30:00-04:00")
    assert merge_caches(conflict, {key: later})[key] == later
