"""Economics P1.3: cross-cycle negative cache for paid-stage writer kills.

Pins the hardened contract (codex r1–r10): the skip activates only after
``min_kills`` (default 2) INDIVIDUALLY TTL-fresh kills of the same
(event_id, bundle sha, decision epoch, stage) — one stochastic kill never
suppresses a story, different stages never pool, and every kill carries its
own timestamp in ``kills_at``; changed facts, a rotated decision epoch
(model/prompt/flags/VERSION), or a stage change restart the evidence; the
read predicate is pure; per-kill TTL expiry, malformed entries, and the
size cap are enforced in the drain prune AND inside the state merge (no
resurrection from stale overlays); BOTH drain paths run prune + skip +
record — the refill drain checks the cache as the LAST $0 predicate
before the paid boundary (exact savings attribution), while the legacy
drain partitions cache-dead rows out BEFORE cap selection (codex r11/r12:
a $0 skip must not burn a capped survivor slot) — and a cache skip blocks
only identical facts: a changed-facts sibling row keeps its paid attempt,
and every verdict produced under the 24h category cooldown (null OR
viable-then-killed downstream) is cooldown-scoped and never cacheable.
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
    """One cache entry with ``kills`` per-kill stamps, newest == ``at``,
    one minute apart (codex r10: each kill carries its own timestamp)."""
    return {
        "sha": sha, "epoch": epoch if epoch is not None else negative_cache.decision_epoch(),
        "stage": "writer", "reason": "dull", "at": at.isoformat(), "kills": kills,
        "kills_at": [(at - timedelta(minutes=i)).isoformat() for i in range(kills)],
    }


def _writer_kill_fake(calls: list, *, cacheable: bool = True):
    """Simulates an EDITORIAL writer kill by default (the pipeline sets
    cacheable=True only for model-verdict kills — codex r8)."""

    def fake_try(bundle, state, score, *, result_out=None, **kwargs):
        calls.append(bundle.event_id)
        if result_out is not None:
            result_out["kill_stage"] = "writer"
            result_out["kill_reason"] = "all writer samples killed: routine value"
            result_out["cacheable"] = cacheable
        return False

    return fake_try


def _run_refill(monkeypatch, bot_state, queue, fake_try, *, funnel_sink=None):
    from src.orchestrator import common

    bot_state["_triage_queue"] = list(queue)
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    return common._drain_and_write_triage_queue(
        bot_state, current_run, funnel_sink=funnel_sink
    )


def _run_legacy(monkeypatch, bot_state, queue, fake_try, *, funnel_sink=None):
    """Drive the LEGACY drain (THEHEAT_REFILL_ENABLED=0) — the production
    workflow DEFAULT when the repo variable is unset. The cache must protect
    both drain paths (codex r9: this one previously re-bought every kill)."""
    from src.orchestrator import common

    bot_state["_triage_queue"] = list(queue)
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    return common._drain_and_write_triage_queue(
        bot_state, current_run, funnel_sink=funnel_sink
    )


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
    negative_cache.record_kill(state, "e1", sha9, "fact_check", "meh")
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
    negative_cache.record_kill(state, "e1", sha, "fact_check", "meh")
    negative_cache.record_kill(state, "e1", sha, "fact_check", "meh")
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
    negative_cache.record_kill(state, "e1", sha, "fact_check", "meh", now=old)
    negative_cache.record_kill(state, "e1", sha, "fact_check", "meh", now=old)
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


def test_critic_kills_are_not_cached():
    """Critic verdicts weigh today's pending-drafts context, which rolls
    over constantly — a cached critic kill could suppress a story that
    became viable when the queue changed (codex r7 P2)."""
    state = _fresh_state()
    sha = negative_cache.bundle_fingerprint(_bundle("e1"))
    negative_cache.record_kill(state, "e1", sha, "critic", "too similar to pending")
    assert state["writer_negative_cache"] == {}
    assert "critic" not in negative_cache.CACHEABLE_KILL_STAGES


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


def test_merge_unions_fresh_kill_stamps_for_same_evidence():
    """Two writers each recording real kills yield the honest combined
    evidence (codex r10): stamps union by parsed INSTANT (offset forms of
    one instant dedup to one kill), newest first — never a naive max()
    that attaches an old count to a new timestamp."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    epoch = negative_cache.decision_epoch()
    a = _entry("c" * 64, at=now - timedelta(minutes=5), kills=3, epoch=epoch)
    b = _entry("c" * 64, at=now, kills=2, epoch=epoch)
    # Overlap: b also carries a's newest instant in +02:00 form — one kill,
    # not two.
    b["kills_at"].append(
        (now - timedelta(minutes=5))
        .astimezone(timezone(timedelta(hours=2)))
        .isoformat()
    )
    b["kills"] = len(b["kills_at"])
    merged = _merge_writer_negative_cache({"e1": a}, {"e1": b})
    # a: {-5m,-6m,-7m}; b: {0,-1m,-5m(offset dup)} → 5 distinct instants.
    assert merged["e1"]["kills"] == 5
    assert len(merged["e1"]["kills_at"]) == 5
    assert merged["e1"]["at"] == now.isoformat()


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


def test_epoch_rotates_on_critic_model_change(monkeypatch):
    """A critic model change produces verdicts under a different regime —
    cached kills must not outlive it (codex r3 P1). (Renamed from the
    over-claiming *_gate_model_change — it only ever mutated the critic;
    the writer / fact-checker / prompt / revise-flag / VERSION rotations
    now have their own tests below, codex r9.)"""
    from src.two_bot import critic as critic_mod

    e1 = negative_cache.decision_epoch()
    monkeypatch.setattr(critic_mod, "CRITIC_MODEL", "gemini-9.9-test")
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


def test_epoch_rotates_on_safety_llm_change(monkeypatch):
    """Safety's Layer-2 is a Gemini LLM whenever the module holds a key —
    its model and enabled-state are verdict context (codex r4 P1)."""
    from src.voice import safety as safety_mod

    e1 = negative_cache.decision_epoch()
    monkeypatch.setattr(safety_mod, "GEMINI_SAFETY_MODEL", "gemini-9.9-safety-test")
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2
    # Enabled-state flip (key present <-> absent) also rotates.
    monkeypatch.setattr(safety_mod, "GEMINI_API_KEY", "")
    e3 = negative_cache.decision_epoch()
    monkeypatch.setattr(safety_mod, "GEMINI_API_KEY", "test-key")
    e4 = negative_cache.decision_epoch()
    assert e3 != e4


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
    funnel_sink: dict = {"_slate_ids": {"e1"}}
    _run_refill(
        monkeypatch, bot_state,
        [_candidate(event_id="e1"), _candidate(event_id="e1")], fake,
        funnel_sink=funnel_sink,
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
    # First terminal wins (codex r4 P2): the duplicate row must not
    # overwrite the event's slate terminal.
    assert funnel_sink.get("_slate_terminal", {}).get("e1") == "negative_cache"


def test_paid_result_respects_existing_terminal(monkeypatch):
    """A same-ID row that reaches the writer after another row already
    resolved a pre-writer terminal must not overwrite it (codex r6 P2);
    the suppression ledger + stage_outcomes still carry the paid attempt."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    funnel_sink: dict = {"_slate_ids": {"e1"}, "_slate_terminal": {"e1": "triage_cap"}}

    def fake_success(bundle, state, score, *, result_out=None, **kwargs):
        return True

    _run_refill(
        monkeypatch, bot_state, [_candidate(event_id="e1")], fake_success,
        funnel_sink=funnel_sink,
    )
    assert funnel_sink["_slate_terminal"]["e1"] == "triage_cap"


def test_ceiling_cut_preserves_resolved_terminal(monkeypatch):
    """Non-adjacent duplicate past the drafts ceiling: _cut()'s triage_cap
    must not overwrite an event's resolved negative_cache terminal
    (codex r5 P2)."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "1")
    bot_state = _fresh_state()
    kill_calls: list = []
    kill_fake = _writer_kill_fake(kill_calls)
    # Arm the cache for e1 with two kill cycles.
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], kill_fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], kill_fake)

    def mixed_fake(bundle, state, score, *, result_out=None, **kwargs):
        if bundle.event_id == "e2":
            return True  # drafts — hits the target ceiling of 1
        if result_out is not None:
            result_out["kill_stage"] = "writer"
            result_out["kill_reason"] = "kill"
        return False

    funnel_sink: dict = {"_slate_ids": {"e1", "e2"}}
    # Queue: e1 (cached → skip, terminal resolves), e2 (drafts → ceiling),
    # then a NON-ADJACENT duplicate e1 that lands in _cut(global_cap).
    _run_refill(
        monkeypatch, bot_state,
        [_candidate(event_id="e1"), _candidate(event_id="e2"),
         _candidate(event_id="e1")],
        mixed_fake, funnel_sink=funnel_sink,
    )
    assert funnel_sink.get("_slate_terminal", {}).get("e1") == "negative_cache"


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


def test_infra_shaped_kill_is_not_recorded(monkeypatch):
    """A kill without the pipeline's cacheable=True disposition (parse or
    length exhaustion, critic-influenced text) must never arm the cache,
    even under a cacheable stage name (codex r8 P1)."""
    bot_state = _fresh_state()
    calls: list = []
    infra_fake = _writer_kill_fake(calls, cacheable=False)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], infra_fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], infra_fake)
    assert bot_state["writer_negative_cache"] == {}
    assert calls == ["e1", "e1"], "infra kills keep the lane open"


def test_pipeline_sets_cacheable_disposition(monkeypatch):
    """generate_draft marks editorial writer kills cacheable=True and
    infra-shaped (parse-exhausted) kills cacheable=False (codex r8 P1)."""
    from src.two_bot import pipeline as pipeline_mod
    from src.two_bot import writer as writer_mod
    from src.two_bot.types import MemorySlice, WriterResult

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setattr(
        pipeline_mod, "_audit_bundle_for_generation", lambda b, **k: True
    )
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice", lambda s, b: MemorySlice()
    )

    def editorial_kill(bundle, memory, **kwargs):
        return WriterResult(
            tweet=None, kill_reason="no extraordinary angle", angle_chosen="",
            era_anchor_used=None, peer_comparison_used=None,
            reasoning="routine", kill_is_editorial=True,
        )

    def infra_kill(bundle, memory, **kwargs):
        return WriterResult(
            tweet=None, kill_reason="writer returned invalid JSON across 2 attempts",
            angle_chosen="", era_anchor_used=None, peer_comparison_used=None,
            reasoning="parse retry exhausted",  # kill_is_editorial defaults False
        )

    out: dict = {}
    monkeypatch.setattr(writer_mod, "write_tweet", editorial_kill)
    monkeypatch.setattr(pipeline_mod.writer, "write_tweet", editorial_kill)
    assert pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "writer" and out["cacheable"] is True

    out = {}
    monkeypatch.setattr(pipeline_mod.writer, "write_tweet", infra_kill)
    assert pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "writer" and out["cacheable"] is False


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


# ------------------------------------------------------------- codex r9 layer


def test_legacy_drain_two_kills_then_skip(monkeypatch):
    """The LEGACY drain (refill flag OFF — the workflow default) must skip
    and record exactly like the refill drain (codex r9 P1: it previously
    went straight to the paid writer with an armed cache)."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)

    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert calls == ["e1"]
    assert bot_state["writer_negative_cache"]["e1"]["kills"] == 1

    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert calls == ["e1", "e1"], "one kill must NOT suppress (supply safety)"
    assert bot_state["writer_negative_cache"]["e1"]["kills"] == 2

    funnel_sink: dict = {"_slate_ids": {"e1"}}
    _run_legacy(
        monkeypatch, bot_state, [_candidate(event_id="e1")], fake,
        funnel_sink=funnel_sink,
    )
    assert calls == ["e1", "e1"], "after two kills on identical facts, cycle 3 is $0"
    negcache_rows = [
        s for s in bot_state.get("suppressions", [])
        if (s.get("kill_stage") or s.get("stage")) == "negative_cache"
    ]
    assert negcache_rows, "the skip must be visible as a negative_cache suppression"
    assert funnel_sink.get("_slate_terminal", {}).get("e1") == "negative_cache"


def test_legacy_kills_arm_refill_skips_and_vice_versa(monkeypatch):
    """Evidence is one shared store: kills recorded by the legacy drain must
    activate the refill drain's skip (same state key, same disposition)."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    assert calls == ["e1", "e1"], "refill must honor legacy-recorded evidence"


def test_legacy_drain_writer_attempted_not_bumped_on_skip(monkeypatch):
    """A $0 negative-cache skip is not a writer attempt — the telemetry
    counter must reflect paid attempts only (legacy accounting parity)."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1")], fake)

    from src.orchestrator import common

    bot_state["_triage_queue"] = [_candidate(event_id="e1")]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake)
    common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=None)
    source_row = current_run["sources"][0]
    assert calls == ["e1", "e1"], "cycle 3 must be a $0 skip"
    assert source_row.get("writer_attempted", 0) == 0, (
        "a negative-cache skip is not a writer attempt"
    )


def test_mixed_stage_kills_do_not_pool(monkeypatch):
    """A writer kill plus a fact-check kill on the same facts are two
    DIFFERENT failure modes — and the fact-check attempt proves the writer
    passed once. They must not pool toward one activation threshold
    (codex r9 P1): a stage change restarts the evidence."""
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull")
    negative_cache.record_kill(state, "e1", sha, "fact_check", "claim mismatch")
    entry = state["writer_negative_cache"]["e1"]
    assert entry["kills"] == 1 and entry["stage"] == "fact_check", (
        "a different stage restarts the evidence at 1"
    )
    assert negative_cache.should_skip(state, "e1", bundle) is None
    # The SAME mode repeating is real evidence.
    negative_cache.record_kill(state, "e1", sha, "fact_check", "claim mismatch")
    assert state["writer_negative_cache"]["e1"]["kills"] == 2
    assert negative_cache.should_skip(state, "e1", bundle) is not None


def test_merge_does_not_pool_kills_across_stages():
    """The state merge's max-kills reconciliation applies only to identical
    (sha, epoch, STAGE) evidence — an older cross-stage row must not donate
    its higher count to the surviving entry (codex r9 P1)."""
    now = datetime.now(timezone.utc)
    a = {"e1": _entry("a" * 64, at=now, kills=1)}  # stage "writer", newest
    b_entry = _entry("a" * 64, at=now - timedelta(hours=1), kills=5)
    b_entry["stage"] = "fact_check"
    b = {"e1": b_entry}
    merged = _merge_writer_negative_cache(a, b)
    assert merged["e1"]["stage"] == "writer"
    assert merged["e1"]["kills"] == 1, (
        "cross-stage kills must not pool through the merge"
    )


def test_cooldown_scoped_editorial_kill_sets_context_flag(monkeypatch):
    """An editorial kill issued while the bundle's category sits in the 24h
    ``recent_categories`` cooldown is (possibly) cooldown-caused — the
    writer must mark it context-scoped so it never arms the 48h cache
    (codex r9 P1: up to ~32h of wrongful suppression past the cooldown)."""
    from src.two_bot import memory as memory_mod
    from src.two_bot import writer as writer_mod
    from src.two_bot.types import MemorySlice

    kill_json = (
        '{"tweet": null, "kill_reason": "category cooldown — already posted '
        'coral within 24h", "angle_chosen": "", "era_anchor_used": null, '
        '"peer_comparison_used": null, "reasoning": "cooldown"}'
    )
    monkeypatch.setattr(writer_mod, "_call_writer_provider", lambda p: kill_json)
    bundle = _bundle("e1")
    category = memory_mod._signal_kind_to_category(bundle.signal_kind)

    hot = writer_mod.write_tweet(bundle, MemorySlice(recent_categories=[category]))
    assert hot.kill_is_editorial is True
    assert hot.cooldown_context_active is True

    cold = writer_mod.write_tweet(bundle, MemorySlice(recent_categories=["other"]))
    assert cold.kill_is_editorial is True
    assert cold.cooldown_context_active is False


def test_pipeline_cooldown_scoped_kill_not_cacheable(monkeypatch):
    """A slate containing any cooldown-scoped verdict must not be cacheable —
    the suppression would outlive the cooldown that (possibly) caused it
    (codex r9 P1)."""
    from src.two_bot import pipeline as pipeline_mod
    from src.two_bot.types import MemorySlice, WriterResult

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setattr(
        pipeline_mod, "_audit_bundle_for_generation", lambda b, **k: True
    )
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice", lambda s, b: MemorySlice()
    )

    def scoped_kill(bundle, memory, **kwargs):
        return WriterResult(
            tweet=None, kill_reason="category cooldown", angle_chosen="",
            era_anchor_used=None, peer_comparison_used=None, reasoning="cooldown",
            kill_is_editorial=True, cooldown_context_active=True,
        )

    out: dict = {}
    monkeypatch.setattr(pipeline_mod.writer, "write_tweet", scoped_kill)
    assert pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "writer" and out["cacheable"] is False


def test_missing_tweet_field_is_parse_error_not_editorial(monkeypatch):
    """A writer response that OMITS the ``tweet`` field is a contract
    violation, not an editorial verdict — it must route into the JSON-retry
    lane, never into the cache (codex r9 P2)."""
    import pytest

    from src.two_bot import writer as writer_mod

    with pytest.raises(ValueError, match="missing required field 'tweet'"):
        writer_mod._parse_writer_json('{"kill_reason": "routine value"}')

    # The explicit-null form remains the model's editorial verdict.
    explicit = writer_mod._parse_writer_json(
        '{"tweet": null, "kill_reason": "routine value", "angle_chosen": "", '
        '"era_anchor_used": null, "peer_comparison_used": null, "reasoning": ""}'
    )
    assert explicit.kill_is_editorial is True

    # End to end: a provider that persistently omits the field exhausts the
    # JSON-retry lane and surfaces as an INFRA kill (not cacheable).
    from src.two_bot.types import MemorySlice

    monkeypatch.setattr(
        writer_mod, "_call_writer_provider",
        lambda p: '{"kill_reason": "routine value"}',
    )
    result = writer_mod.write_tweet(_bundle("e1"), MemorySlice())
    assert result.tweet is None
    assert result.kill_is_editorial is False
    assert "invalid JSON" in (result.kill_reason or "")


def test_dispatch_safety_kill_carries_cacheable_disposition(monkeypatch):
    """The post-pipeline advisory-URL safety kill must carry an honest
    cacheable disposition: True for uncritiqued text, False when the
    pipeline reports critic-shaped text, False (default-deny) when the
    pipeline reported nothing (codex r9 P2 — r8's gate silently dropped
    these kills for want of the key)."""
    import importlib

    from src.orchestrator import two_bot_dispatch
    from src.two_bot import pipeline as pipeline_mod

    saved_dict = dict(two_bot_dispatch.__dict__)
    two_bot_dispatch = importlib.reload(two_bot_dispatch)
    try:
        with monkeypatch.context() as mp:
            _ABSENT = object()

            def fake_generate(critic_shaped, cooldown_scoped=False):
                def _g(bundle, state, result_out=None):
                    if result_out is not None:
                        if critic_shaped is not _ABSENT:
                            result_out["critic_shaped"] = critic_shaped
                        if cooldown_scoped is not _ABSENT:
                            result_out["cooldown_scoped"] = cooldown_scoped
                    return {
                        "text": "t", "event_id": "e1", "type": "cyclone",
                        "two_bot_metadata": {},
                    }
                return _g

            mp.setattr(
                two_bot_dispatch, "_append_cyclone_advisory_url",
                lambda t, b, lt: t + " URL",
            )
            mp.setattr(
                two_bot_dispatch, "run_safety_pipeline",
                lambda t: (False, "banned phrase"),
            )

            for critic_shaped, cooldown_scoped, expected in [
                (False, False, True),    # both explicit False → cacheable
                (True, False, False),    # critic-shaped → rolling context
                (False, True, False),    # cooldown-shaped text (codex r12)
                (_ABSENT, False, False), # pipeline silent → default-deny
                (False, _ABSENT, False), # cooldown report missing → deny
                (None, False, False),    # malformed explicit values
                (0, False, False),       #   (codex r11 P3): only `is False`
                ("", False, False),      #   authorizes — falsey still denies
            ]:
                mp.setattr(
                    pipeline_mod, "generate_draft",
                    fake_generate(critic_shaped, cooldown_scoped),
                )
                result_out: dict = {}
                ok = two_bot_dispatch._try_two_bot_draft(
                    _bundle("e1"), _fresh_state(), _score(), event_id="e1",
                    legacy_type="cyclone", review_context={}, result_out=result_out,
                )
                assert ok is False
                assert result_out.get("kill_stage") == "safety"
                assert result_out.get("cacheable") is expected, (
                    f"critic_shaped={critic_shaped} must yield cacheable={expected}"
                )
    finally:
        two_bot_dispatch.__dict__.clear()
        two_bot_dispatch.__dict__.update(saved_dict)


def test_pipeline_reports_critic_shaped_on_success(monkeypatch):
    """generate_draft must tell the dispatch layer whether the final text
    was critic-shaped — slate selection and revise both count; a plain
    single-sample pass does not (codex r9 P2)."""
    from src.two_bot import pipeline as pipeline_mod
    from src.two_bot.types import MemorySlice, WriterResult

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    monkeypatch.setattr(
        pipeline_mod, "_audit_bundle_for_generation", lambda b, **k: True
    )
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice", lambda s, b: MemorySlice()
    )
    # The downstream gates are not under test — pass them (the real
    # fact-checker needs GEMINI_API_KEY).
    from src.two_bot.types import FactCheckResult

    monkeypatch.setattr(
        pipeline_mod, "_check_safety_honesty_fact",
        lambda *a, **k: FactCheckResult(passed=True, failures=[], raw_response="{}"),
    )

    def good_draft(bundle, memory, **kwargs):
        return WriterResult(
            tweet="a fine tweet", kill_reason=None, angle_chosen="a",
            era_anchor_used=None, peer_comparison_used=None, reasoning="",
        )

    out: dict = {}
    monkeypatch.setattr(pipeline_mod.writer, "write_tweet", good_draft)
    draft = pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out)
    assert draft is not None
    assert out.get("critic_shaped") is False, (
        "single sample, critic disabled → the text is not critic-shaped"
    )


# -------------------------------------------------- codex r9 epoch coverage


def test_epoch_rotates_on_writer_model_change(monkeypatch):
    from src.two_bot import writer as writer_mod

    e1 = negative_cache.decision_epoch()
    monkeypatch.setattr(writer_mod, "WRITER_MODEL", "claude-test-9-9")
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


def test_epoch_rotates_on_fact_checker_model_change(monkeypatch):
    from src.two_bot import fact_check as fact_check_mod

    e1 = negative_cache.decision_epoch()
    monkeypatch.setattr(fact_check_mod, "FACT_CHECKER_MODEL", "gemini-9.9-fc-test")
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


def test_epoch_rotates_on_prompt_change(monkeypatch):
    """A writer system-prompt edit rotates the epoch. The module caches the
    prompt sha — the test resets the cache around each controlled value;
    monkeypatch teardown restores the real cached sha afterwards."""
    from src.two_bot.prompts import writer_prompt as prompt_mod

    monkeypatch.setattr(prompt_mod, "WRITER_SYSTEM_PROMPT", "prompt A")
    monkeypatch.setattr(negative_cache, "_PROMPT_SHA", None)
    e1 = negative_cache.decision_epoch()
    monkeypatch.setattr(prompt_mod, "WRITER_SYSTEM_PROMPT", "prompt B")
    negative_cache._PROMPT_SHA = None
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


def test_epoch_rotates_on_revise_flag_change(monkeypatch):
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    e1 = negative_cache.decision_epoch()
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


def test_changed_facts_sibling_row_gets_its_paid_attempt(monkeypatch):
    """A $0 cache skip must not consume the event's paid slot for the
    cycle (codex r10 P1): with cached facts A skipped, a same-event row
    with CHANGED facts (new fingerprint) must reach the writer — while an
    identical-facts sibling still falls to duplicate_draft."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    # Arm the cache for facts A (dhw=8).
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    _run_refill(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    assert calls == ["e1", "e1"]

    # Cycle 3: cached A, then identical A-dup, then CHANGED facts B.
    funnel_sink: dict = {"_slate_ids": {"e1"}}
    _run_refill(
        monkeypatch, bot_state,
        [
            _candidate(event_id="e1", dhw=8),
            _candidate(event_id="e1", dhw=8),
            _candidate(event_id="e1", dhw=9),
        ],
        fake,
        funnel_sink=funnel_sink,
    )
    assert calls == ["e1", "e1", "e1"], (
        "changed facts must reach the writer despite the same-event cache skip"
    )
    rows = bot_state.get("suppressions", [])
    stages = [(s.get("kill_stage") or s.get("stage")) for s in rows]
    assert stages.count("negative_cache") == 1, "one skip for the cached facts"
    assert stages.count("duplicate_draft") == 1, "identical sibling is a dup"
    # First terminal wins: the event's slate terminal stays the first
    # resolution (negative_cache), not B's later paid kill.
    assert funnel_sink.get("_slate_terminal", {}).get("e1") == "negative_cache"


def test_legacy_changed_facts_sibling_and_first_terminal(monkeypatch):
    """Legacy-path parity for codex r10: identical-facts sibling of a
    cache-skipped event records duplicate_draft; changed facts reach the
    writer; the paid result must NOT overwrite the first slate terminal
    (codex r10 P2)."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)

    funnel_sink: dict = {"_slate_ids": {"e1"}}
    _run_legacy(
        monkeypatch, bot_state,
        [
            _candidate(event_id="e1", dhw=8),
            _candidate(event_id="e1", dhw=8),
            _candidate(event_id="e1", dhw=9),
        ],
        fake,
        funnel_sink=funnel_sink,
    )
    assert calls == ["e1", "e1", "e1"], "changed facts must reach the writer"
    rows = bot_state.get("suppressions", [])
    stages = [(s.get("kill_stage") or s.get("stage")) for s in rows]
    assert stages.count("duplicate_draft") == 1
    assert funnel_sink.get("_slate_terminal", {}).get("e1") == "negative_cache", (
        "the paid result must not overwrite the first terminal (first wins)"
    )


def test_kill_chain_cannot_extend_evidence_past_ttl():
    """Each kill participates only while INDIVIDUALLY fresh (codex r10 P1):
    kills at t0 and t0+47h must not read as two fresh kills at t0+94h —
    the rolling newest-stamp previously kept ancient evidence alive."""
    t0 = datetime.now(timezone.utc) - timedelta(hours=94)
    state = _fresh_state()
    bundle = _bundle("e1")
    sha = negative_cache.bundle_fingerprint(bundle)
    negative_cache.record_kill(state, "e1", sha, "writer", "dull", now=t0)
    negative_cache.record_kill(
        state, "e1", sha, "writer", "dull", now=t0 + timedelta(hours=47)
    )
    # Shortly after the second kill BOTH are fresh — the skip is active.
    assert negative_cache.should_skip(
        state, "e1", bundle, now=t0 + timedelta(hours=47, minutes=30)
    ) is not None
    # At t0+94h only the second kill is inside the 48h window — one fresh
    # kill must never suppress.
    assert negative_cache.should_skip(
        state, "e1", bundle, now=t0 + timedelta(hours=94)
    ) is None


def test_malformed_kill_reason_type_is_parse_error(monkeypatch):
    """An explicit-null tweet with a non-string kill_reason (e.g. []) is a
    contract violation, not an editorial verdict (codex r10 P2) — it must
    route into the JSON-retry lane and surface as an INFRA kill."""
    import pytest

    from src.two_bot import writer as writer_mod

    with pytest.raises(ValueError, match="kill_reason"):
        writer_mod._parse_writer_json('{"tweet": null, "kill_reason": []}')
    with pytest.raises(ValueError, match="kill_reason"):
        writer_mod._parse_writer_json('{"tweet": null, "kill_reason": "  "}')
    with pytest.raises(ValueError, match="'tweet' must be a string"):
        writer_mod._parse_writer_json('{"tweet": 42, "kill_reason": null}')

    from src.two_bot.types import MemorySlice

    monkeypatch.setattr(
        writer_mod, "_call_writer_provider",
        lambda p: '{"tweet": null, "kill_reason": []}',
    )
    result = writer_mod.write_tweet(_bundle("e1"), MemorySlice())
    assert result.tweet is None
    assert result.kill_is_editorial is False, (
        "malformed verdicts must never be cacheable editorial evidence"
    )


def test_mixed_slate_with_scoped_kill_is_not_cacheable(monkeypatch):
    """One cooldown-scoped verdict anywhere in a multi-sample slate makes
    the aggregate writer kill non-cacheable (codex r10 P2 pins the r9
    ``any(...)`` rule — a single-sample test could not distinguish it)."""
    from src.two_bot import pipeline as pipeline_mod
    from src.two_bot.types import MemorySlice, WriterResult

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "2")
    monkeypatch.setattr(
        pipeline_mod, "_audit_bundle_for_generation", lambda b, **k: True
    )
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice", lambda s, b: MemorySlice()
    )

    def _kill(scoped: bool) -> WriterResult:
        return WriterResult(
            tweet=None, kill_reason="no angle", angle_chosen="",
            era_anchor_used=None, peer_comparison_used=None, reasoning="",
            kill_is_editorial=True, cooldown_context_active=scoped,
        )

    # Thread-safe handout: each sampler pops one prepared result.
    results = [_kill(True), _kill(False)]
    monkeypatch.setattr(
        pipeline_mod.writer, "write_tweet",
        lambda bundle, memory, **kw: results.pop(),
    )
    out: dict = {}
    assert pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "writer" and out["cacheable"] is False

    # Control: two UNscoped editorial kills stay cacheable.
    results = [_kill(False), _kill(False)]
    out = {}
    assert pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "writer" and out["cacheable"] is True


def test_critic_shaped_true_for_slate_selection_and_revise(monkeypatch):
    """The success report must be True on BOTH critic-shaping paths —
    slate selection and an adopted revise (codex r10 P2 pins the r9
    ``critic_shaped`` rule beyond the plain False case)."""
    from src.two_bot import pipeline as pipeline_mod
    from src.two_bot.types import CriticResult, FactCheckResult, MemorySlice, WriterResult

    monkeypatch.setattr(
        pipeline_mod, "_audit_bundle_for_generation", lambda b, **k: True
    )
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice", lambda s, b: MemorySlice()
    )
    monkeypatch.setattr(
        pipeline_mod, "_check_safety_honesty_fact",
        lambda *a, **k: FactCheckResult(passed=True, failures=[], raw_response="{}"),
    )

    def good(text: str) -> WriterResult:
        return WriterResult(
            tweet=text, kill_reason=None, angle_chosen="a",
            era_anchor_used=None, peer_comparison_used=None, reasoning="",
        )

    # --- Path 1: slate selection (samples=2, critic enabled). ---
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "2")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setattr(
        pipeline_mod.writer, "write_tweet",
        lambda bundle, memory, **kw: good("sample tweet"),
    )
    monkeypatch.setattr(
        pipeline_mod.critic, "critic_select_slate",
        lambda *a, **k: CriticResult(
            passed=True, kill_reason=None, raw_response="{}", verdict="PASS",
            selected_index=1,
        ),
    )
    out: dict = {}
    draft = pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out)
    assert draft is not None
    assert out.get("critic_shaped") is True, "slate selection shapes the text"

    # --- Path 2: adopted revise (samples=1, revise enabled). ---
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    review_calls = {"n": 0}

    def fake_review(*a, **k):
        review_calls["n"] += 1
        if review_calls["n"] == 1:
            return CriticResult(
                passed=False, kill_reason=None, raw_response="{}",
                verdict="REVISE", revise_instruction="tighten the opener",
            )
        return CriticResult(
            passed=True, kill_reason=None, raw_response="{}", verdict="PASS",
        )

    monkeypatch.setattr(pipeline_mod.critic, "critic_review", fake_review)
    monkeypatch.setattr(
        pipeline_mod.writer, "write_tweet",
        lambda bundle, memory, **kw: (
            good("revised tweet") if kw.get("revision_constraint") else good("first tweet")
        ),
    )
    out = {}
    draft = pipeline_mod.generate_draft(_bundle("e1"), _fresh_state(), result_out=out)
    assert draft is not None
    assert draft["text"] == "revised tweet"
    assert out.get("critic_shaped") is True, "an adopted revise shapes the text"


def test_epoch_rotates_on_version_change(monkeypatch):
    """A deploy (VERSION bump) rotates the epoch — every code PR bumps
    VERSION, so any shipped change to gate code invalidates prior evidence."""
    from pathlib import Path

    real_read_text = Path.read_text
    forced: dict = {"value": None}

    def fake_read_text(self, *args, **kwargs):
        if self.name == "VERSION" and forced["value"] is not None:
            return forced["value"]
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    forced["value"] = "9.9.9-epoch-a"
    e1 = negative_cache.decision_epoch()
    forced["value"] = "9.9.9-epoch-b"
    e2 = negative_cache.decision_epoch()
    assert e1 and e2 and e1 != e2


# ------------------------------------------------------------ codex r12 layer


def test_legacy_triage_caps_do_not_burn_slots_on_cache_skip(monkeypatch):
    """codex r11 P1: with triage caps ON (refill OFF), a cache-dead row must
    not consume a capped survivor slot. Cached A + live C + changed-facts
    A-sibling, same category, cap 2: C AND the sibling both reach the
    writer; the cached row records negative_cache pre-cap."""
    from src.orchestrator import common

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="eA", dhw=8)], fake)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="eA", dhw=8)], fake)
    assert calls == ["eA", "eA"]

    bot_state["_triage_queue"] = [
        _candidate(event_id="eA", dhw=8),  # cache-dead facts
        _candidate(event_id="eC", dhw=5),  # unrelated live candidate
        _candidate(event_id="eA", dhw=9),  # changed-facts sibling — reopened
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "2")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake)
    common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=None)

    assert sorted(calls[2:]) == ["eA", "eC"], (
        "the cache-dead row must not burn a cap slot — both live candidates "
        "get their paid attempt"
    )
    stages = [
        (s.get("kill_stage") or s.get("stage"))
        for s in bot_state.get("suppressions", [])
    ]
    assert stages.count("negative_cache") == 1


def test_legacy_reopened_event_single_paid_shot(monkeypatch):
    """codex r11 P2: the fingerprint partition reopens changed facts, but a
    queue carrying the reopened row TWICE buys exactly one attempt — the
    second records duplicate_draft via the attempted guard."""
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="e1", dhw=8)], fake)

    _run_legacy(
        monkeypatch, bot_state,
        [
            _candidate(event_id="e1", dhw=8),  # cache-dead
            _candidate(event_id="e1", dhw=9),  # reopened changed facts
            _candidate(event_id="e1", dhw=9),  # identical reopened duplicate
        ],
        fake,
    )
    assert calls == ["e1", "e1", "e1"], (
        "exactly ONE paid attempt for the reopened facts"
    )
    stages = [
        (s.get("kill_stage") or s.get("stage"))
        for s in bot_state.get("suppressions", [])
    ]
    assert stages.count("negative_cache") == 1
    assert stages.count("duplicate_draft") == 1


def test_ambiguous_multi_object_response_is_parse_error(monkeypatch):
    """codex r11 P2: a kill-shaped object followed by a second parseable
    object must re-sample via the JSON-retry lane — never resolve to
    whichever object came first (either could be the model's real verdict,
    and the kill shape would become durable cache evidence)."""
    import pytest

    from src.two_bot import writer as writer_mod
    from src.two_bot.json_utils import loads_model_json

    kill_obj = (
        '{"tweet": null, "kill_reason": "routine value", "angle_chosen": "", '
        '"era_anchor_used": null, "peer_comparison_used": null, "reasoning": ""}'
    )
    live_obj = (
        '{"tweet": "Fresh viable story", "kill_reason": null, '
        '"angle_chosen": "a", "era_anchor_used": null, '
        '"peer_comparison_used": null, "reasoning": ""}'
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        loads_model_json(
            kill_obj + "\n" + live_obj,
            expected="object", require_single_object=True,
        )
    with pytest.raises(ValueError, match="Ambiguous"):
        writer_mod._parse_writer_json(kill_obj + " " + live_obj)

    # Harmless prose — including unbalanced braces — stays tolerated.
    parsed = writer_mod._parse_writer_json(
        "Here is the verdict:\n" + kill_obj + "\nprose tail with { an unclosed brace"
    )
    assert parsed.kill_is_editorial is True

    # End to end: a persistently ambiguous provider exhausts the JSON-retry
    # lane and surfaces as an INFRA kill — never cacheable evidence.
    from src.two_bot.types import MemorySlice

    monkeypatch.setattr(
        writer_mod, "_call_writer_provider", lambda p: kill_obj + " " + live_obj
    )
    result = writer_mod.write_tweet(_bundle("e1"), MemorySlice())
    assert result.tweet is None
    assert result.kill_is_editorial is False


# ------------------------------------------------------------ codex r13 layer


def test_downstream_kill_under_cooldown_not_cacheable(monkeypatch):
    """codex r12 P1: viable text WRITTEN under the 24h category cooldown was
    shaped by that transient constraint — a downstream (safety) kill of it
    must not arm the cache, exactly like a null verdict. Control: the same
    kill without the cooldown stays cacheable."""
    from src.two_bot import memory as memory_mod
    from src.two_bot import pipeline as pipeline_mod
    from src.two_bot import writer as writer_mod
    from src.two_bot.types import MemorySlice

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    monkeypatch.setattr(
        pipeline_mod, "_audit_bundle_for_generation", lambda b, **k: True
    )
    viable_json = (
        '{"tweet": "A viable tweet under cooldown", "kill_reason": null, '
        '"angle_chosen": "a", "era_anchor_used": null, '
        '"peer_comparison_used": null, "reasoning": ""}'
    )
    monkeypatch.setattr(writer_mod, "_call_writer_provider", lambda p: viable_json)
    monkeypatch.setattr(
        pipeline_mod, "run_safety_pipeline", lambda t: (False, "banned phrase")
    )
    bundle = _bundle("e1")
    category = memory_mod._signal_kind_to_category(bundle.signal_kind)

    # Cooldown ACTIVE at attempt time → safety kill is not cacheable.
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice",
        lambda s, b: MemorySlice(recent_categories=[category]),
    )
    out: dict = {}
    assert pipeline_mod.generate_draft(bundle, _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "safety" and out["cacheable"] is False

    # Control: no cooldown → the same safety verdict is cacheable.
    monkeypatch.setattr(
        pipeline_mod.memory, "build_memory_slice",
        lambda s, b: MemorySlice(recent_categories=["other"]),
    )
    out = {}
    assert pipeline_mod.generate_draft(bundle, _fresh_state(), result_out=out) is None
    assert out["kill_stage"] == "safety" and out["cacheable"] is True


def test_duplicate_json_keys_are_parse_errors(monkeypatch):
    """codex r12 P2: plain json.loads keeps the LAST duplicate key, so
    {"tweet":"viable","tweet":null,...} spoofed an editorial kill. Under
    the verdict contract duplicate names anywhere are a parse error →
    JSON-retry lane."""
    import pytest

    from src.two_bot import writer as writer_mod

    dup = (
        '{"tweet": "Fresh viable story", "tweet": null, '
        '"kill_reason": "routine value", "angle_chosen": "", '
        '"era_anchor_used": null, "peer_comparison_used": null, "reasoning": ""}'
    )
    with pytest.raises(ValueError):
        writer_mod._parse_writer_json(dup)

    # End to end: the persistent dup-key provider exhausts the retry lane
    # into an INFRA kill — never editorial evidence.
    from src.two_bot.types import MemorySlice

    monkeypatch.setattr(writer_mod, "_call_writer_provider", lambda p: dup)
    result = writer_mod.write_tweet(_bundle("e1"), MemorySlice())
    assert result.tweet is None
    assert result.kill_is_editorial is False


def test_fact_check_ambiguous_and_duplicate_responses_fail_closed(monkeypatch):
    """codex r12 P2/P3: the fact-checker shares the single-verdict contract —
    sibling objects AND duplicate `passed` keys must exhaust its retry lane
    into parse_failed=True (fail-closed, never cacheable evidence)."""
    from src.two_bot import fact_check as fact_check_mod

    pass_obj = '{"passed": true, "failures": [], "extracted_claims": []}'
    kill_obj = '{"passed": false, "failures": ["number mismatch"], "extracted_claims": []}'
    dup_keys = '{"passed": true, "passed": false, "failures": [], "extracted_claims": []}'

    for raw in (kill_obj + "\n" + pass_obj, dup_keys):
        monkeypatch.setattr(fact_check_mod, "_call_gemini", lambda t, b, retry_suffix="": raw)
        result = fact_check_mod.fact_check("A tweet.", [], _bundle("e1"), _fresh_state())
        assert result.passed is False, "ambiguous verdicts must fail closed"
        assert result.parse_failed is True, (
            "ambiguous/dup-key verdicts are infra failures — never cacheable"
        )


def test_legacy_duplicate_reopened_row_does_not_burn_cap_slot(monkeypatch):
    """codex r12 P1: a duplicate REOPENED row must resolve pre-cap — under
    cap 2, [cached-A, changed-B, changed-B-dup, live-C] must buy B and C,
    not let the B-dup burn C's slot. And codex r12 P2: partition rows count
    in triaged_out so funnel triage_cut stays exact."""
    from src.orchestrator import common

    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    bot_state = _fresh_state()
    calls: list = []
    fake = _writer_kill_fake(calls)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="eA", dhw=8)], fake)
    _run_legacy(monkeypatch, bot_state, [_candidate(event_id="eA", dhw=8)], fake)
    assert calls == ["eA", "eA"]

    bot_state["_triage_queue"] = [
        _candidate(event_id="eA", dhw=8),  # cache-dead
        _candidate(event_id="eA", dhw=9),  # reopened changed facts
        _candidate(event_id="eA", dhw=9),  # duplicate reopened row
        _candidate(event_id="eC", dhw=5),  # unrelated live candidate
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "2")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake)
    common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=None)

    assert sorted(calls[2:]) == ["eA", "eC"], (
        "the duplicate reopened row must not burn the cap slot C needs"
    )
    stages = [
        (s.get("kill_stage") or s.get("stage"))
        for s in bot_state.get("suppressions", [])
    ]
    assert stages.count("negative_cache") == 1
    assert stages.count("duplicate_draft") == 1
    source_row = current_run["sources"][0]
    # triaged_in = 4 queue rows; triaged_out = 2 partition rows (cache-dead
    # A + duplicate reopened B) + 2 survivors — triage_cut stays 0.
    assert source_row.get("triaged_in") == 4
    assert source_row.get("triaged_out") == 4
