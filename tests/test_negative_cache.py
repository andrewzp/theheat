"""Economics P1.3: cross-cycle negative cache for paid-stage writer kills.

Pins the hardened contract (codex r1): the skip activates only after
``min_kills`` (default 2) kills of the same (event_id, bundle sha, decision
epoch) — one stochastic kill never suppresses a story; changed facts or a
rotated decision epoch (model/prompt/flags) restart the evidence; the read
predicate is pure; TTL expiry, malformed entries, and the size cap are
enforced in the drain prune AND inside the state merge (no resurrection
from stale overlays); the drain checks the cache as the LAST $0 predicate
before the paid boundary so cheaper deterministic kills are never
misattributed to it.
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


def _entry(sha: str, *, at: datetime, kills: int = 2, epoch: str | None = None) -> dict:
    return {
        "sha": sha, "epoch": epoch if epoch is not None else negative_cache.decision_epoch(),
        "stage": "writer", "reason": "dull", "at": at.isoformat(), "kills": kills,
    }


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


def test_min_kills_gate_one_kill_never_skips():
    """A single stochastic kill records evidence but must not suppress."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert state["writer_negative_cache"]["e1"]["kills"] == 1
    assert negative_cache.should_skip(state, "e1", bundle) is None
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert state["writer_negative_cache"]["e1"]["kills"] == 2
    assert negative_cache.should_skip(state, "e1", bundle) is not None


def test_changed_facts_restart_evidence_and_reopen():
    state = _fresh_state()
    sha8 = negative_cache.bundle_fingerprint(_bundle("e1", dhw=8))
    negative_cache.record_kill(state, "e1", sha8, "writer", "dull")
    negative_cache.record_kill(state, "e1", sha8, "writer", "dull")
    assert negative_cache.should_skip(state, "e1", _bundle("e1", dhw=8)) is not None
    # Facts change: no skip, and a new kill restarts the count at 1.
    assert negative_cache.should_skip(state, "e1", _bundle("e1", dhw=9)) is None
    sha9 = negative_cache.bundle_fingerprint(_bundle("e1", dhw=9))
    negative_cache.record_kill(state, "e1", sha9, "critic", "meh")
    assert state["writer_negative_cache"]["e1"]["kills"] == 1


def test_epoch_rotation_invalidates(monkeypatch):
    """A sampling-flag flip (part of the decision epoch) reopens the lane
    and restarts the evidence count (codex r1 P1: decision context)."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert negative_cache.should_skip(state, "e1", bundle) is not None
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "2")
    assert negative_cache.should_skip(state, "e1", bundle) is None
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert state["writer_negative_cache"]["e1"]["kills"] == 1


def test_should_skip_is_pure():
    """The read predicate must not mutate state (codex r1 P2)."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    before = deepcopy(state["writer_negative_cache"])
    assert negative_cache.should_skip(state, "e1", bundle) is not None
    assert state["writer_negative_cache"] == before


def test_should_skip_does_not_insert_key_on_empty_state():
    """Purity extends to the missing-key case: a read on a state without
    the cache key must not create it (codex r2 P2)."""
    state = _fresh_state()
    del state["writer_negative_cache"]
    assert negative_cache.should_skip(state, "e1", _bundle("e1")) is None
    assert "writer_negative_cache" not in state


def test_min_kills_floor_is_two(monkeypatch):
    """The one-kill invariant is not tunable: env=1 still requires 2
    (codex r2 P1)."""
    monkeypatch.setenv("THEHEAT_NEGATIVE_CACHE_MIN_KILLS", "1")
    assert negative_cache.min_kills() == 2
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert negative_cache.should_skip(state, "e1", bundle) is None


def test_critic_kill_switch_rotates_epoch(monkeypatch):
    """Disabling an over-killing critic must reopen cached candidates
    (codex r2 P1)."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    negative_cache.record_kill(state, "e1", sha, "critic", "meh")
    negative_cache.record_kill(state, "e1", sha, "critic", "meh")
    assert negative_cache.should_skip(state, "e1", bundle) is not None
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    assert negative_cache.should_skip(state, "e1", bundle) is None


def test_expired_evidence_does_not_resurrect():
    """A prior kill older than the TTL is expired evidence — a fresh kill
    restarts the count at 1 instead of activating the skip (codex r2)."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    old = datetime.now(timezone.utc) - timedelta(hours=60)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull", now=old)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    assert state["writer_negative_cache"]["e1"]["kills"] == 1
    assert negative_cache.should_skip(state, "e1", bundle) is None


def test_non_cacheable_stage_entry_never_skips():
    """A structurally-clean entry carrying a transient stage (corrupt or
    adversarial overlay) must fail validation and never suppress
    (codex r2 P2)."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    entry = _entry(sha, at=datetime.now(timezone.utc), kills=5)
    entry["stage"] = "budget_exhausted"
    state["writer_negative_cache"]["e1"] = entry
    assert not negative_cache.valid_entry(entry)
    assert negative_cache.should_skip(state, "e1", bundle) is None
    # bool kills (int subclass) and empty epochs are equally rejected.
    assert not negative_cache.valid_entry(dict(_entry(sha, at=datetime.now(timezone.utc)), kills=True))
    assert not negative_cache.valid_entry(dict(_entry(sha, at=datetime.now(timezone.utc)), epoch=""))


def test_ttl_expiry_reopens_and_prune_removes():
    state = _fresh_state()
    bundle = _bundle("e1")
    old = datetime.now(timezone.utc) - timedelta(hours=72)
    sha = negative_cache.bundle_fingerprint(bundle)
    negative_cache.record_kill(state, "e1", sha, "critic", "meh", now=old)
    negative_cache.record_kill(state, "e1", sha, "critic", "meh", now=old)
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
    state["writer_negative_cache"]["e1"] = _entry(sha, at=datetime.now(timezone.utc))
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


def test_merge_newest_wins_by_parsed_instant_not_string():
    """An entry stamped with a +02:00 offset must lose to a LATER UTC
    instant even though its string sorts higher (codex r1 P2)."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    utc_newer = _entry("b" * 64, at=now)
    # Same wall-clock string minus 2h in real terms, but "2026-…+02:00"
    # string-compares above the UTC form on many layouts.
    offset_older = dict(
        _entry("a" * 64, at=now),
        at=now.astimezone(timezone(timedelta(hours=2))).replace(
            microsecond=0
        ).isoformat(),
    )
    # offset_older's instant == now; make it strictly older:
    offset_older["at"] = (
        (now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=2))).isoformat()
    )
    merged = _merge_writer_negative_cache({"e1": offset_older}, {"e1": utc_newer})
    assert merged["e1"]["sha"] == "b" * 64


def test_merge_takes_max_kills_for_same_evidence():
    now = datetime.now(timezone.utc)
    epoch = negative_cache.decision_epoch()
    a = _entry("c" * 64, at=now - timedelta(minutes=5), kills=3, epoch=epoch)
    b = _entry("c" * 64, at=now, kills=2, epoch=epoch)
    merged = _merge_writer_negative_cache({"e1": a}, {"e1": b})
    assert merged["e1"]["kills"] == 3  # newest entry, max count


def test_merge_does_not_resurrect_expired_and_drops_malformed():
    """A stale overlay must not bring back TTL-expired or junk entries
    (codex r1 P2 — reproduced pre-fix)."""
    old = datetime.now(timezone.utc) - timedelta(hours=100)
    expired = _entry("d" * 64, at=old)
    merged = _merge_writer_negative_cache({"e1": expired, "junk": "nope"}, {})
    assert merged == {}


def test_merge_stale_side_cannot_revive_kill_count():
    """A TTL-stale kills=2 row max()'d into a fresh restarted kills=1 row
    must NOT produce a fresh kills=2 (codex r3 P1 — reproduced pre-fix).
    Each side is freshness-filtered BEFORE reconciliation."""
    now = datetime.now(timezone.utc)
    epoch = negative_cache.decision_epoch()
    sha = "c" * 64
    stale = _entry(sha, at=now - timedelta(hours=60), kills=2, epoch=epoch)
    fresh = _entry(sha, at=now, kills=1, epoch=epoch)
    merged = _merge_writer_negative_cache({"e1": stale}, {"e1": fresh})
    assert merged["e1"]["kills"] == 1, "expired evidence must not resurrect via merge"


def test_parse_at_overflow_boundary_returns_none():
    """astimezone() raises OverflowError on boundary stamps — one corrupt
    entry must be dropped, never abort a state write (codex r3 P1)."""
    assert negative_cache.parse_at("0001-01-01T00:00:00+14:00") is None
    # And the merge survives such an entry:
    bad = dict(_entry("d" * 64, at=datetime.now(timezone.utc)), at="0001-01-01T00:00:00+14:00")
    merged = _merge_writer_negative_cache({"e1": bad}, {})
    assert merged == {}


def test_epoch_rotates_on_gate_model_change(monkeypatch):
    """Critic/fact-check model changes produce verdicts under a different
    regime — cached kills must not outlive them (codex r3 P1)."""
    from src.two_bot import critic as critic_mod

    e1 = negative_cache.decision_epoch()
    monkeypatch.setattr(critic_mod, "CRITIC_MODEL", "gemini-9.9-test")
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


def test_version_read_failure_disables_caching(monkeypatch):
    """A VERSION read failure must fail OPEN (epoch "", cache no-ops) — a
    stable "unknown" epoch would defeat deploy rotation (codex r3 P2)."""
    from pathlib import Path

    def _boom(self, *a, **k):
        raise OSError("no VERSION")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert negative_cache.decision_epoch() == ""
    state = _fresh_state()
    negative_cache.record_kill(state, "e1", "a" * 64, "writer", "dull")
    assert state["writer_negative_cache"] == {}


def test_sha_must_be_hex():
    """64 arbitrary characters is not a fingerprint (codex r3 P2)."""
    entry = _entry("z" * 64, at=datetime.now(timezone.utc))
    assert not negative_cache.valid_entry(entry)


def test_cap_eviction_orders_by_instant_not_string():
    """An offset-stamped OLDER instant must be evicted before a UTC NEWER
    one even though its raw string sorts higher (codex r2 P2)."""
    now = datetime.now(timezone.utc)
    state = _fresh_state()
    cache = state["writer_negative_cache"]
    # Fill to the cap with recent UTC entries.
    for i in range(negative_cache.NEGATIVE_CACHE_MAX_ENTRIES):
        cache[f"e{i}"] = _entry("a" * 64, at=now - timedelta(minutes=i + 10))
    # The oldest INSTANT, but stamped in +10:00 (string sorts above "2026-…Z"-less UTC forms).
    cache["offset_old"] = dict(
        _entry("b" * 64, at=now),
        at=(now - timedelta(hours=20)).astimezone(timezone(timedelta(hours=10))).isoformat(),
    )
    negative_cache.prune(state)
    assert "offset_old" not in cache, "oldest instant must be evicted regardless of offset"
    assert "e0" in cache


# --------------------------------------------------------------- drain layer


def test_refill_drain_two_kills_then_skip(monkeypatch):
    """Kill 1 records; kill 2 (cycle 2) activates; cycle 3 spends $0."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert calls == ["e1"]
    assert bot_state["writer_negative_cache"]["e1"]["kills"] == 1

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert calls == ["e1", "e1"], "one kill must NOT suppress (supply safety)"
    assert bot_state["writer_negative_cache"]["e1"]["kills"] == 2

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert calls == ["e1", "e1"], "after two kills on identical facts, cycle 3 is $0"
    negcache_rows = [
        s for s in bot_state.get("suppressions", [])
        if s.get("kill_stage") == "negative_cache"
        or s.get("stage") == "negative_cache"
    ]
    assert negcache_rows, "the skip must be visible as a negative_cache suppression"


def test_duplicate_queue_rows_count_one_cache_skip(monkeypatch):
    """Two queue rows for one cached event: the first is the negative_cache
    skip, the second must fall to the in-cycle duplicate_draft path —
    double-counting would inflate claimed savings (codex r3 P2)."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    # Two cycles of kills arm the cache.
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    # Cycle 3: the SAME event appears twice in the ranked queue.
    _run_refill(
        monkeypatch, bot_state,
        [_candidate(event_id="e1"), _candidate(event_id="e1")], fake,
    )
    assert calls == ["e1", "e1"], "no paid attempts in cycle 3"
    rows = bot_state.get("suppressions", [])
    negcache_rows = [
        s for s in rows
        if (s.get("kill_stage") or s.get("stage")) == "negative_cache"
    ]
    dup_rows = [
        s for s in rows
        if (s.get("kill_stage") or s.get("stage")) == "duplicate_draft"
    ]
    assert len(negcache_rows) == 1, "exactly one skip replaced a potential writer call"
    assert len(dup_rows) == 1, "the duplicate row is a duplicate_draft, not a second skip"


def test_refill_drain_reattempts_when_facts_change(monkeypatch):
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    # Two kills on dhw=8 — but the story's facts move on:
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=11)], fake)
    assert calls == ["e1", "e1", "e1"], "changed material facts must re-open the lane"


def test_refill_drain_does_not_cache_drafted_candidates(monkeypatch):
    bot_state = _fresh_state()
    calls: list = []

    def fake_success(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        return True

    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake_success)
    assert bot_state["writer_negative_cache"] == {}


def test_out_of_scope_writer_kill_is_not_recorded(monkeypatch):
    """The deterministic editorial-scope guard (earthquakes) reports
    kill_stage=writer without any model call — caching it would claim
    savings that never existed (codex r2 P2)."""
    bot_state = _fresh_state()
    quake = TriageCandidateBundle(
        bundle=StoryBundle(
            signal_kind="usgs_earthquake", where="Testfault", when="2026-07-23",
            event_id="quake1", headline_metric={"label": "M", "value": 6},
            current_facts=[],
        ),
        score=_score(category="usgs_earthquake"), event_id="quake1",
        source="usgs", review_context={}, city="", tweet_date="2026-07-23",
        cooldown_exempt=False, legacy_type="usgs_earthquake",
        created_at="2026-07-23T12:00:00Z",
    )

    def fake_scope_kill(bundle, state, score, *, result_out=None, **kwargs):
        if result_out is not None:
            result_out["kill_stage"] = "writer"
            result_out["kill_reason"] = "outside @theheat's climate-data editorial scope"
        return False

    _run_refill(monkeypatch, bot_state, [quake], fake_scope_kill)
    assert bot_state["writer_negative_cache"] == {}


def test_negcache_checked_only_at_the_paid_boundary(monkeypatch):
    """When a cheaper $0 predicate (can_draft_candidate) already kills the
    candidate, the cache must not even be consulted (codex r1 P2:
    misattribution overstates savings)."""
    from src.orchestrator import draft_save
    from src.two_bot import negative_cache as negcache_mod

    bot_state = _fresh_state()
    consulted: list = []
    real_should_skip = negcache_mod.should_skip

    def spy_should_skip(*args, **kwargs):
        consulted.append(True)
        return real_should_skip(*args, **kwargs)

    monkeypatch.setattr(negcache_mod, "should_skip", spy_should_skip)
    monkeypatch.setattr(
        draft_save, "can_draft_candidate", lambda state, cand: (False, "cooldown")
    )
    calls: list = []
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], _writer_kill_fake(calls))
    assert calls == [], "can_draft rejection must stop before any paid attempt"
    assert consulted == [], "negcache must not be consulted before cheaper predicates"


def test_dispatch_advisory_safety_kill_populates_result_out(monkeypatch):
    """The post-pipeline cyclone-advisory safety rejection must surface
    kill_stage=safety in result_out (codex r1 P2: it read as save_rejected
    and was invisible to the funnel and the cache)."""
    import importlib

    from src.orchestrator import two_bot_dispatch
    from src.two_bot import pipeline as pipeline_mod

    # test_main's wrappers run main._sync_compat_globals(), which pushes
    # main's (sometimes test-patched) globals onto the orchestrator modules
    # and never restores them — a stale fake _try_two_bot_draft can linger
    # on this module. Reload to get the real, current function — and restore
    # the module's ORIGINAL dict afterwards, because downstream shim tests
    # assert object identity across common/dispatch (a reload that leaks
    # would trade one pollution for another).
    saved_dict = dict(two_bot_dispatch.__dict__)
    two_bot_dispatch = importlib.reload(two_bot_dispatch)
    try:
        # All patches live in a NESTED context so they unwind BEFORE the
        # finally restores saved_dict — the outer monkeypatch's teardown
        # would otherwise reinstall post-reload objects after the restore
        # (codex r2 P2).
        with monkeypatch.context() as mp:
            # _try_two_bot_draft imports generate_draft function-locally from
            # the pipeline module, so the patch must land on the SOURCE module.
            mp.setattr(
                pipeline_mod,
                "generate_draft",
                lambda bundle, state, result_out=None: {
                    "text": "t", "event_id": "e1", "type": "cyclone",
                    "two_bot_metadata": {},
                },
            )
            # Force the advisory append to change the text, then fail safety.
            mp.setattr(
                two_bot_dispatch, "_append_cyclone_advisory_url", lambda t, b, lt: t + " URL"
            )
            mp.setattr(
                two_bot_dispatch, "run_safety_pipeline", lambda t: (False, "banned phrase")
            )
            result_out: dict = {}
            ok = two_bot_dispatch._try_two_bot_draft(
                _bundle("e1"), _fresh_state(), _score(), event_id="e1",
                legacy_type="cyclone", review_context={}, result_out=result_out,
            )
            assert ok is False
            assert result_out.get("kill_stage") == "safety"
            assert "banned" in result_out.get("kill_reason", "")
    finally:
        # Patches are unwound (context exited); restoring the pre-reload
        # dict is now last-write-wins, so shim identity tests downstream
        # still see the original objects.
        two_bot_dispatch.__dict__.clear()
        two_bot_dispatch.__dict__.update(saved_dict)
