"""P08 behavioral boundaries: real pipeline/dispatch and both queue modes, no paid calls."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations
import json

import pytest

from src.data.coral_dhw import CoralBleachingEvent
from src.two_bot.intern import build_coral_bleaching_bundle
from src.two_bot import negative_cache as cache
from src.two_bot.types import WriterResult, TriageCandidateBundle, MemorySlice
from src.state import DEFAULT_STATE
from tests.test_negative_cache import _score, _entry, row_map


@pytest.fixture(autouse=True)
def restore_compatibility_facade():
    # Earlier integration tests deliberately sync temporary src.main patches
    # into split modules. Restore the normal facade before exercising the
    # actual dispatcher; no pipeline or evidence gate is replaced here.
    from src import main

    main._sync_compat_globals()


def bundle(event="event", value=8.2):
    return build_coral_bleaching_bundle(
        CoralBleachingEvent(
            region_id="fixture_reef",
            region_full_name="Fixture Reef",
            date=datetime.now(timezone.utc).date().isoformat(),
            dhw_value=value,
            dhw_tier=8,
            bleaching_level="mass bleaching expected",
            stress_level="Alert Level 1",
            lat=-16.1,
            lon=145.975,
            event_id=event,
        )
    )


def rejection(scope="evidence", code="insufficient_evidence"):
    return WriterResult(
        None,
        "model reports missing comparative evidence",
        "",
        None,
        None,
        "",
        kill_scope=scope,
        kill_code=code,
        initial_response=True,
    )


def seed(state, event, packet, *, code="insufficient_evidence"):
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    sha = cache.bundle_fingerprint(packet, state)
    for delta in (2, 1):
        cache.record_kill(
            state,
            event,
            sha,
            "writer",
            "model reports missing evidence",
            now=now - timedelta(minutes=delta),
            scope="evidence",
            code=code,
        )


def run_direct(state, packet, output=None):
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft

    return _try_two_bot_draft(
        packet,
        state,
        _score(),
        legacy_type="coral_bleaching",
        event_id=packet.event_id,
        review_context={},
        result_out=output,
    )


@pytest.mark.parametrize("refill", [False, True])
def test_two_actual_writer_rejections_then_both_queue_modes_skip_without_spending_slots(
    monkeypatch, refill
):
    from src.two_bot import pipeline
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue
    from src.orchestrator import common

    calls = []
    monkeypatch.setattr(
        pipeline, "_writer_sample_slate", lambda b, m, s: calls.append(b.event_id) or [rejection()]
    )
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if refill else "0")
    # Keep the actual dispatch boundary rather than replacing it with a fake
    # which could omit the cache or record the same attempt twice.
    monkeypatch.setattr(
        common,
        "_try_two_bot_draft",
        __import__(
            "src.orchestrator.two_bot_dispatch", fromlist=["_try_two_bot_draft"]
        )._try_two_bot_draft,
    )
    state, packet = deepcopy(DEFAULT_STATE), bundle()
    candidate = TriageCandidateBundle(
        packet,
        _score(),
        packet.event_id,
        "coral_dhw",
        {},
        "",
        "",
        False,
        "coral_bleaching",
        datetime.now(timezone.utc).isoformat(),
    )
    for _ in range(3):
        state["_triage_queue"] = [candidate, candidate]
        _drain_and_write_triage_queue(state, {"id": "r", "sources": [{"source": "coral_dhw"}]})
    assert calls == ["event", "event"]
    assert next(iter(state["writer_negative_cache"].values()))["kills"] == 2
    assert sum(row["stage"] == "negative_cache" for row in state["suppressions"]) == 1
    assert not any("dollar" in str(row).lower() for row in state["suppressions"])


def test_direct_dispatch_reopens_on_new_evidence_and_does_not_cache_style_or_transport(monkeypatch):
    from src.two_bot import pipeline

    calls = []
    result = [rejection()]
    monkeypatch.setattr(
        pipeline, "_writer_sample_slate", lambda b, m, s: calls.append(b.event_id) or result
    )
    state, packet = deepcopy(DEFAULT_STATE), bundle()
    for _ in range(3):
        assert not run_direct(state, packet)
    assert len(calls) == 2
    assert not run_direct(state, bundle(value=9.2))
    assert len(calls) == 3
    assert sorted(row["kills"] for row in state["writer_negative_cache"].values()) == [1, 2]
    for scope in ("style", "context", "unknown", None):
        state = deepcopy(DEFAULT_STATE)
        result[:] = [rejection(scope, None)]
        for _ in range(3):
            run_direct(state, packet)
        assert not state["writer_negative_cache"]

    def unavailable(*args):
        raise ConnectionError("temporary fixture transport outage")

    monkeypatch.setattr(pipeline, "_writer_sample_slate", unavailable)
    state = deepcopy(DEFAULT_STATE)
    run_direct(state, packet)
    assert not state["writer_negative_cache"]


def test_writer_metadata_is_strict_optional_and_default_deny():
    from src.two_bot.writer import _parse_writer_json

    base = {
        "tweet": None,
        "kill_reason": "missing evidence",
        "angle_chosen": "",
        "era_anchor_used": None,
        "peer_comparison_used": None,
        "reasoning": "",
    }
    assert _parse_writer_json(json.dumps(base)).kill_scope is None
    assert (
        _parse_writer_json(
            json.dumps({**base, "kill_scope": "evidence", "kill_code": "insufficient_evidence"})
        ).kill_scope
        == "evidence"
    )
    for metadata in (
        {"kill_scope": "style", "kill_code": "insufficient_evidence"},
        {"kill_scope": []},
        {"kill_scope": True},
        {"kill_code": "routine_story"},
    ):
        with pytest.raises(ValueError):
            _parse_writer_json(json.dumps({**base, **metadata}))


def test_prompt_policy_model_and_actual_memory_changes_reopen(monkeypatch):
    from src.two_bot import writer, memory
    from src.two_bot.prompts import writer_prompt, critic_prompt, fact_check_prompt

    state, packet = deepcopy(DEFAULT_STATE), bundle()
    seed(state, "event", packet)
    assert cache.should_skip(state, "event", packet)
    for module, attribute in [
        (writer_prompt, "WRITER_SYSTEM_PROMPT"),
        (critic_prompt, "CRITIC_SYSTEM_PROMPT"),
        (fact_check_prompt, "FACT_CHECK_SYSTEM_PROMPT"),
        (writer, "WRITER_MODEL"),
        (cache, "CACHE_POLICY_VERSION"),
    ]:
        with monkeypatch.context() as scoped:
            scoped.setattr(
                module, attribute, getattr(module, attribute) + "\nfixture policy change"
            )
            assert cache.should_skip(state, "event", packet) is None
    monkeypatch.setattr(
        memory,
        "build_memory_slice",
        lambda state, packet: MemorySlice(used_framings=["new context"]),
    )
    assert cache.should_skip(state, "event", packet) is None


def test_editorial_policy_only_change_or_unknown_policy_reopens_evidence_rejections(monkeypatch):
    from src.editorial import policy

    state, packet = deepcopy(DEFAULT_STATE), bundle()
    seed(state, "event", packet)
    assert cache.should_skip(state, "event", packet)
    with monkeypatch.context() as scoped:
        scoped.setattr(policy, "source_manifest", lambda: {"source_sha256": "f" * 64})
        assert cache.should_skip(state, "event", packet) is None
    assert cache.should_skip(state, "event", packet)
    monkeypatch.setattr(policy, "current_editorial_policy", lambda: None)
    assert cache.should_skip(state, "event", packet) is None
    assert cache.decision_epoch() == ""


def test_different_evidence_codes_and_zero_cost_contract_failures_cannot_arm_cache(monkeypatch):
    state, packet = deepcopy(DEFAULT_STATE), bundle()
    sha = cache.bundle_fingerprint(packet, state)
    for code in ("insufficient_evidence", "conflicting_evidence"):
        cache.record_kill(
            state, "event", sha, "writer", "model judgment", scope="evidence", code=code
        )
    assert cache.should_skip(state, "event", packet) is None
    assert [row["kills"] for row in state["writer_negative_cache"].values()] == [1, 1]
    state = deepcopy(DEFAULT_STATE)
    cache.record_result(
        state,
        "event",
        packet,
        {
            "cacheable": True,
            "kill_stage": "evidence_contract",
            "kill_scope": "evidence",
            "kill_code": "insufficient_evidence",
        },
    )
    assert not state["writer_negative_cache"]


def test_merge_algebra_and_same_time_bounds_are_deterministic():
    now = datetime.now(timezone.utc)
    a = _entry("a" * 64, at=now - timedelta(minutes=3), kills=1)
    b = _entry("a" * 64, at=now - timedelta(minutes=2), kills=1)
    c = _entry("a" * 64, at=now - timedelta(minutes=1), kills=1)
    expected = cache.merge_entries(
        row_map(a), cache.merge_entries(row_map(b), row_map(c), now=now), now=now
    )
    for x, y, z in permutations((a, b, c)):
        result = cache.merge_entries(
            cache.merge_entries(row_map(x), row_map(y), now=now), row_map(z), now=now
        )
        assert result == expected
        assert cache.merge_entries(result, result, now=now) == result
    # Equal-time different identities and >cap dictionaries cannot depend on
    # set iteration or the left/right order of independent state writers.
    large = {
        key: row
        for i in range(cache.NEGATIVE_CACHE_MAX_ENTRIES + 5)
        for key, row in row_map(_entry("b" * 64, at=now, event=f"e{i:03}")).items()
    }
    assert cache.merge_entries(large, {}, now=now) == cache.merge_entries(
        {}, dict(reversed(list(large.items()))), now=now
    )
    clash = _entry("b" * 64, at=now)
    assert cache.merge_entries(row_map(c), row_map(clash), now=now) == cache.merge_entries(
        row_map(clash), row_map(c), now=now
    )


def test_different_input_revision_interleaving_keeps_associative_failure_evidence():
    now = datetime.now(timezone.utc)
    rows = [
        _entry(sha * 64, at=now - timedelta(minutes=minute), kills=1)
        for sha, minute in [("a", 3), ("b", 2), ("a", 1)]
    ]
    for a, b, c in permutations(rows):
        left = cache.merge_entries(
            cache.merge_entries(row_map(a), row_map(b), now=now), row_map(c), now=now
        )
        right = cache.merge_entries(
            row_map(a), cache.merge_entries(row_map(b), row_map(c), now=now), now=now
        )
        assert left == right
        assert sorted(row["kills"] for row in left.values()) == [1, 2]


def test_python_dashboard_python_sqlite_roundtrip_preserves_real_cache_and_receipts(tmp_path):
    from src.storage import sqlite_store
    from tests.test_persistence_contract import node_store

    state, packet = deepcopy(DEFAULT_STATE), bundle()
    state["drafts"] = [
        {
            "id": "draft-1",
            "event_id": "published",
            "text": "Exact published copy",
            "status": "posted",
            "tweet_id": "receipt-1",
            "publish_outcome": "confirmed",
        }
    ]
    state["publish_ledger"] = {
        "published": {"phase": "posted", "tweet_id": "receipt-1", "text_sha256": "f" * 64}
    }
    seed(state, "event", packet)
    original_cache, original_ledger = (
        deepcopy(state["writer_negative_cache"]),
        deepcopy(state["publish_ledger"]),
    )
    path = tmp_path / "cache.sqlite"
    assert sqlite_store.write_state(str(path), state)
    assert node_store(path, "read")["writer_negative_cache"] == original_cache
    # Dashboard owns draft commands; a partial write must carry all current
    # Python-owned cache metadata through its real SQLite storage boundary.
    node_store(path, "write", {"drafts": state["drafts"]})
    restored = sqlite_store.read_state(str(path), DEFAULT_STATE)
    assert restored["writer_negative_cache"] == original_cache
    assert restored["publish_ledger"] == original_ledger
    assert restored["drafts"] == state["drafts"]
    assert cache.should_skip(restored, "event", packet)


def test_cache_skipped_sibling_does_not_consume_changed_evidence_slot(monkeypatch):
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue
    from src.two_bot import pipeline
    from src.orchestrator import common
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft

    calls = []
    monkeypatch.setattr(
        pipeline,
        "_writer_sample_slate",
        lambda b, m, s: calls.append(b.headline_metric["value"]) or [rejection()],
    )
    monkeypatch.setattr(common, "_try_two_bot_draft", _try_two_bot_draft)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_TRIAGE_MAX_SURVIVORS", "1")
    old, new = bundle(), bundle(value=9.2)
    for refill in ("0", "1"):
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", refill)
        state = deepcopy(DEFAULT_STATE)
        seed(state, "event", old)
        state["_triage_queue"] = [
            TriageCandidateBundle(
                b,
                _score(),
                "event",
                "coral_dhw",
                {},
                "",
                "",
                False,
                "coral_bleaching",
                datetime.now(timezone.utc).isoformat(),
            )
            for b in (old, old, new)
        ]
        count = len(calls)
        _drain_and_write_triage_queue(state, {"id": "r", "sources": [{"source": "coral_dhw"}]})
        assert calls[count:] == [9.2]


def test_reused_dispatch_result_cannot_relabel_a_later_style_failure(monkeypatch):
    from src.two_bot import pipeline

    state, packet, output = deepcopy(DEFAULT_STATE), bundle(), {}
    monkeypatch.setattr(pipeline, "_writer_sample_slate", lambda *args: [rejection()])
    run_direct(state, packet, output)
    assert output["negative_cache_recorded"] is True
    monkeypatch.setattr(pipeline, "_writer_sample_slate", lambda *args: [rejection("style", None)])
    run_direct(state, packet, output)
    assert "cacheable" not in output
    assert next(iter(state["writer_negative_cache"].values()))["kills"] == 1


def test_actual_imported_writer_prompt_and_mismatched_cache_payload_reopen(monkeypatch):
    from src.two_bot import writer

    state, packet = deepcopy(DEFAULT_STATE), bundle()
    seed(state, "event", packet)
    assert cache.should_skip(state, "event", packet)
    with monkeypatch.context() as scoped:
        scoped.setattr(writer, "WRITER_SYSTEM_PROMPT", writer.WRITER_SYSTEM_PROMPT + " changed")
        assert cache.should_skip(state, "event", packet) is None
    row = next(iter(state["writer_negative_cache"].values()))
    row["sha"] = "a" * 64
    assert cache.should_skip(state, "event", packet) is None
    assert cache.merge_entries(state["writer_negative_cache"], {}) == {}


def test_same_time_descriptive_metadata_merge_ignores_mutable_summary_counts():
    now = datetime.now(timezone.utc)
    rows = [_entry("a" * 64, at=now, kills=n) for n in (1, 2, 3)]
    for row, reason in zip(rows, ("z judgment", "a judgment", "m judgment")):
        row["reason"] = reason
    expected = None
    for a, b, c in permutations(rows):
        merged = cache.merge_entries(
            cache.merge_entries(row_map(a), row_map(b), now=now), row_map(c), now=now
        )
        expected = expected or merged
        assert merged == expected
        assert next(iter(merged.values()))["reason"] == "z judgment"


@pytest.mark.parametrize("first_response", ["length", "json"])
def test_provider_retry_rejection_cannot_defer_original_evidence(monkeypatch, first_response):
    from src.two_bot import writer

    calls = []
    killed = {
        "tweet": None,
        "kill_reason": "model reports insufficient evidence",
        "angle_chosen": "",
        "era_anchor_used": None,
        "peer_comparison_used": None,
        "reasoning": "",
        "cited_impact": None,
        "kill_scope": "evidence",
        "kill_code": "insufficient_evidence",
    }
    overlong = {
        **killed,
        "tweet": "x" * 281,
        "angle_chosen": "fixture_fact",
        "kill_reason": None,
        "kill_scope": None,
        "kill_code": None,
    }

    def provider(prompt):
        calls.append(prompt)
        if len(calls) % 2 == 0:
            return json.dumps(killed)
        return json.dumps(overlong) if first_response == "length" else "not JSON"

    monkeypatch.setattr(writer, "_call_writer_provider", provider)
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    state, packet = deepcopy(DEFAULT_STATE), bundle()
    for _ in range(3):
        assert not run_direct(state, packet)
    assert len(calls) == 6
    assert not state["writer_negative_cache"]
    assert "retry" in calls[1].lower()


def test_provider_initial_evidence_rejections_defer_without_extra_model_stage(monkeypatch):
    from src.two_bot import writer

    calls = []

    def provider(prompt):
        calls.append(prompt)
        return json.dumps(
            {
                "tweet": None,
                "kill_reason": "model reports insufficient evidence",
                "angle_chosen": "",
                "era_anchor_used": None,
                "peer_comparison_used": None,
                "reasoning": "",
                "cited_impact": None,
                "kill_scope": "evidence",
                "kill_code": "insufficient_evidence",
            }
        )

    monkeypatch.setattr(writer, "_call_writer_provider", provider)
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    state, packet = deepcopy(DEFAULT_STATE), bundle()
    for _ in range(3):
        assert not run_direct(state, packet)
    assert len(calls) == 2
    assert next(iter(state["writer_negative_cache"].values()))["kills"] == 2
