"""Economics P1.3: cross-cycle negative cache for paid-stage writer kills.

Pins the contract: a candidate killed at a paid stage (writer/critic/
fact-check/safety/honesty) is skipped as a $0 ``negative_cache`` pre-writer
kill on later cycles while its material facts are byte-identical and the
entry is inside the TTL; changed facts, TTL expiry, transient stages, and
the kill-switch all re-open the lane. The store is capped and self-pruning,
and the state merge keeps the newest entry per event without resurrecting
an unbounded store.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE, _merge_writer_negative_cache
from src.two_bot import negative_cache
from src.two_bot.types import StoryBundle, TriageCandidateBundle


def _fresh_state() -> dict:
    return deepcopy(DEFAULT_STATE)


def _score(total: int = 80, category: str = "coral_bleaching") -> EditorialScore:
    return EditorialScore(
        category=category, severity=80, novelty=80, timeliness=80, confidence=80,
        shareability=80, sensitivity=0, total=total, threshold=60, reasons=[],
    )


def _bundle(event_id: str = "evt", *, dhw: int = 8) -> StoryBundle:
    return StoryBundle(
        signal_kind="coral_bleaching", where="Reef", when="2026-06-16",
        event_id=event_id, headline_metric={"label": "DHW", "value": dhw},
        current_facts=[],
    )


def _candidate(*, event_id: str, dhw: int = 8, total: int = 80) -> TriageCandidateBundle:
    return TriageCandidateBundle(
        bundle=_bundle(event_id, dhw=dhw), score=_score(total), event_id=event_id,
        source="coral_dhw", review_context={}, city="", tweet_date="2026-06-16",
        cooldown_exempt=False, legacy_type="coral_bleaching",
        created_at="2026-06-16T12:00:00Z",
    )


def _writer_kill_fake(calls: list):
    def fake_try(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        if result_out is not None:
            result_out["kill_stage"] = "writer"
            result_out["kill_reason"] = "all writer samples killed: routine value"
        return False

    return fake_try


def _run_refill(monkeypatch, bot_state, queue, fake_try):
    from src.orchestrator import common

    bot_state["_triage_queue"] = list(queue)
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    return common._drain_and_write_triage_queue(bot_state, current_run)


# ---------------------------------------------------------------- unit layer


def test_fingerprint_is_deterministic_and_fact_sensitive():
    a1 = negative_cache.bundle_fingerprint(_bundle("e1", dhw=8))
    a2 = negative_cache.bundle_fingerprint(_bundle("e1", dhw=8))
    b = negative_cache.bundle_fingerprint(_bundle("e1", dhw=9))
    assert a1 == a2 and a1 != b and len(a1) == 64


def test_record_then_skip_then_facts_change_reopens():
    state = _fresh_state()
    bundle = _bundle("e1", dhw=8)
    negative_cache.record_kill(
        state, "e1", negative_cache.bundle_fingerprint(bundle), "writer", "dull",
    )
    assert negative_cache.should_skip(state, "e1", bundle) is not None
    # Material facts changed → fingerprint differs → re-attempt allowed.
    assert negative_cache.should_skip(state, "e1", _bundle("e1", dhw=9)) is None


def test_ttl_expiry_reopens_and_prune_removes(monkeypatch):
    state = _fresh_state()
    bundle = _bundle("e1")
    old = datetime.now(timezone.utc) - timedelta(hours=72)
    negative_cache.record_kill(
        state, "e1", negative_cache.bundle_fingerprint(bundle), "critic", "meh",
        now=old,
    )
    assert negative_cache.should_skip(state, "e1", bundle) is None  # 72h > 48h TTL
    removed = negative_cache.prune(state)
    assert removed == 1 and state["writer_negative_cache"] == {}


def test_transient_stages_are_not_cached():
    state = _fresh_state()
    sha = negative_cache.bundle_fingerprint(_bundle("e1"))
    negative_cache.record_kill(state, "e1", sha, "budget_exhausted", "billing")
    negative_cache.record_kill(state, "e1", sha, "pipeline_error", "boom")
    negative_cache.record_kill(state, "e1", sha, "save_rejected", "cooldown")
    assert state["writer_negative_cache"] == {}


def test_kill_switch_disables_both_sides(monkeypatch):
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    monkeypatch.setenv("THEHEAT_NEGATIVE_CACHE_ENABLED", "0")
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert state["writer_negative_cache"] == {}
    # Pre-existing entries stop skipping too.
    state["writer_negative_cache"]["e1"] = {
        "sha": sha, "stage": "writer", "reason": "dull",
        "at": datetime.now(timezone.utc).isoformat(), "hits": 0,
    }
    assert negative_cache.should_skip(state, "e1", bundle) is None


def test_cap_evicts_oldest_first():
    state = _fresh_state()
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(negative_cache.NEGATIVE_CACHE_MAX_ENTRIES + 5):
        negative_cache.record_kill(
            state, f"e{i}", "a" * 64, "writer", "dull",
            now=base + timedelta(seconds=i),
        )
    cache = state["writer_negative_cache"]
    assert len(cache) == negative_cache.NEGATIVE_CACHE_MAX_ENTRIES
    assert "e0" not in cache and f"e{negative_cache.NEGATIVE_CACHE_MAX_ENTRIES + 4}" in cache


# --------------------------------------------------------------- merge layer


def test_merge_keeps_newest_per_event_and_caps():
    now = datetime.now(timezone.utc)
    older = {"sha": "a" * 64, "stage": "writer", "reason": "x",
             "at": (now - timedelta(hours=2)).isoformat(), "hits": 0}
    newer = {"sha": "b" * 64, "stage": "critic", "reason": "y",
             "at": now.isoformat(), "hits": 3}
    merged = _merge_writer_negative_cache({"e1": older}, {"e1": newer, "junk": "nope"})
    assert merged["e1"]["sha"] == "b" * 64
    assert "junk" not in merged  # malformed entries dropped


# --------------------------------------------------------------- drain layer


def test_refill_drain_skips_recent_identical_kill(monkeypatch):
    """Cycle 1 kills at the writer; cycle 2 with identical facts spends $0."""
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)

    drafted = _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert drafted == 0 and calls == ["e1"]
    assert "e1" in bot_state["writer_negative_cache"]

    drafted = _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert drafted == 0
    assert calls == ["e1"], "cycle 2 must not re-spend a writer call on unchanged facts"
    negcache_rows = [
        s for s in bot_state.get("suppressions", [])
        if s.get("kill_stage") == "negative_cache"
        or s.get("stage") == "negative_cache"
    ]
    assert negcache_rows, "the skip must be visible as a negative_cache suppression"


def test_refill_drain_reattempts_when_facts_change(monkeypatch):
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=11)], fake)
    assert calls == ["e1", "e1"], "changed material facts must re-open the writer lane"


def test_refill_drain_does_not_cache_drafted_candidates(monkeypatch):
    bot_state = _fresh_state()
    calls: list = []

    def fake_success(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        return True

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake_success)
    assert bot_state["writer_negative_cache"] == {}
