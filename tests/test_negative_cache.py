"""P08 cache regressions adapted from PR464 exact2b70565a44faaecef4c2c818ca5f89a1841e799f.

Reuses the PR's two-fresh-verdict, offset, expiry, pure-read, malformed-row,
policy-rotation and retention cases. P08 uses explicit evidence dispositions
and keys each event/input/policy/code revision independently.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE
from src.two_bot import negative_cache as cache
from src.two_bot.types import StoryBundle


def _score(total=80, category="coral_bleaching"):
    return EditorialScore(category, 80, 80, 80, 80, 80, 0, total, 60, [])


def _bundle(value=8):
    return StoryBundle(
        "coral_bleaching", "Reef", "2026-06-16", "event", {"label": "dhw", "value": value}, []
    )


def _entry(sha, *, at, kills=2, epoch=None, event="event", code="insufficient_evidence"):
    return {
        "event_id": event,
        "sha": sha,
        "epoch": epoch or cache.decision_epoch(),
        "stage": "writer",
        "scope": "evidence",
        "code": code,
        "reason": "model reports missing evidence",
        "at": at.isoformat(),
        "kills": kills,
        "kills_at": [(at - timedelta(minutes=i)).isoformat() for i in range(kills)],
    }


def row_map(row):
    return {
        cache.entry_key(row["event_id"], row["sha"], row["epoch"], row["stage"], row["code"]): row
    }


def record(state, packet, *, now=None, code="insufficient_evidence", epoch=None):
    cache.record_kill(
        state,
        packet.event_id,
        cache.bundle_fingerprint(packet, state),
        "writer",
        "model reports missing evidence",
        scope="evidence",
        code=code,
        now=now,
        epoch=epoch,
    )


def test_two_distinct_fresh_failures_then_reopen_on_changed_facts_and_expiry():
    state, packet = deepcopy(DEFAULT_STATE), _bundle()
    now = datetime.now(timezone.utc)
    record(state, packet, now=now - timedelta(minutes=2))
    assert cache.should_skip(state, "event", packet, now=now) is None
    record(state, packet, now=now - timedelta(minutes=1))
    assert cache.should_skip(state, "event", packet, now=now)
    assert cache.should_skip(state, "event", _bundle(9), now=now) is None
    assert cache.should_skip(state, "event", packet, now=now + timedelta(hours=13)) is None
    assert cache.prune(state, now=now + timedelta(hours=13)) == 1


def test_same_timestamp_cannot_count_as_two_failures_and_read_is_pure():
    state, packet = deepcopy(DEFAULT_STATE), _bundle()
    now = datetime.now(timezone.utc)
    record(state, packet, now=now)
    record(state, packet, now=now)
    before = deepcopy(state)
    assert cache.should_skip(state, "event", packet, now=now) is None
    assert state == before
    empty = {}
    assert cache.should_skip(empty, "event", packet) is None and empty == {}


def test_per_kill_expiry_cannot_be_extended_by_a_chain_of_new_failures():
    state, packet = deepcopy(DEFAULT_STATE), _bundle()
    now = datetime.now(timezone.utc)
    record(state, packet, now=now - timedelta(hours=22))
    record(state, packet, now=now - timedelta(hours=11))
    assert cache.should_skip(state, "event", packet, now=now) is None
    assert (
        cache.merge_entries(state["writer_negative_cache"], {}, now=now)[
            next(iter(state["writer_negative_cache"]))
        ]["kills"]
        == 1
    )


@pytest.mark.parametrize(
    "stage",
    [
        "critic",
        "fact_check",
        "safety",
        "honesty_gate",
        "cross_signal",
        "budget_exhausted",
        "pipeline_error",
        "evidence_contract",
    ],
)
def test_text_context_or_infrastructure_failures_never_mark_event_ineligible(stage):
    state = deepcopy(DEFAULT_STATE)
    cache.record_kill(
        state,
        "event",
        "a" * 64,
        stage,
        "any reason",
        scope="evidence",
        code="insufficient_evidence",
    )
    assert not state["writer_negative_cache"]


def test_missing_or_malformed_disposition_is_default_deny():
    state = deepcopy(DEFAULT_STATE)
    for options in (
        {},
        {"scope": "style", "code": None},
        {"scope": "evidence", "code": None},
        {"scope": "evidence", "code": []},
    ):
        cache.record_kill(state, "event", "a" * 64, "writer", "missing evidence", **options)
    assert not state["writer_negative_cache"]


def test_disabled_cache_and_minimum_two_are_enforced(monkeypatch):
    monkeypatch.setenv("THEHEAT_NEGATIVE_CACHE_MIN_KILLS", "1")
    assert cache.min_kills() == 2
    monkeypatch.setenv("THEHEAT_NEGATIVE_CACHE_ENABLED", "0")
    state, packet = deepcopy(DEFAULT_STATE), _bundle()
    record(state, packet)
    assert not state["writer_negative_cache"]
    state["writer_negative_cache"] = row_map(
        _entry(cache.bundle_fingerprint(packet, state), at=datetime.now(timezone.utc))
    )
    assert cache.should_skip(state, "event", packet) is None


def test_unknown_policy_disables_cache(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: (_ for _ in ()).throw(OSError("fixture unavailable policy")),
    )
    assert cache.decision_epoch() == ""
    state = deepcopy(DEFAULT_STATE)
    record(state, _bundle())
    assert not state["writer_negative_cache"]


@pytest.mark.parametrize(
    "change",
    [
        {"sha": "z" * 64},
        {"kills": True},
        {"epoch": ""},
        {"code": []},
        {"at": "0001-01-01T00:00:00+14:00"},
        {"kills_at": [None]},
        {"at": "2026-09-09T00:00:00"},
    ],
)
def test_malformed_row_cannot_skip_or_abort_merge(change):
    now = datetime.now(timezone.utc)
    row = _entry("a" * 64, at=now)
    key = next(iter(row_map(row)))
    row.update(change)
    assert not cache.valid_entry(row)
    assert cache.merge_entries({key: row}, {}, now=now) == {}


def test_kill_union_uses_real_instants_and_expired_overlay_never_revives():
    now = datetime.now(timezone.utc)
    a = _entry("a" * 64, at=now - timedelta(minutes=2))
    b = _entry("a" * 64, at=now)
    b["kills_at"].append(a["at"].replace("+00:00", "Z"))
    b["kills"] = len(b["kills_at"])
    merged = cache.merge_entries(row_map(a), row_map(b), now=now)
    assert next(iter(merged.values()))["kills"] == 4
    stale = _entry("a" * 64, at=now - timedelta(hours=60), kills=8)
    assert cache.merge_entries(merged, row_map(stale), now=now) == merged
    assert cache.merge_entries(row_map(a), row_map(b), now=now) == cache.merge_entries(
        row_map(b), row_map(a), now=now
    )


def test_fingerprint_and_lookup_do_not_backfill_absent_memory():
    packet, state = _bundle(), {}
    fingerprint = cache.bundle_fingerprint(packet, state)
    assert fingerprint and state == {}
    record(state, packet, now=datetime.now(timezone.utc) - timedelta(minutes=2))
    record(state, packet, now=datetime.now(timezone.utc) - timedelta(minutes=1))
    before = deepcopy(state)
    assert cache.should_skip(state, "event", packet)
    assert state == before and "memory" not in state
