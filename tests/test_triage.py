"""Unit tests for the triage stage (src/orchestrator/triage.py).

TDD: tests written before any production code. Each test exercises a
single, named behaviour from the spec § 8 + engineering review findings.
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest

from src.state import DEFAULT_STATE
from src.editorial.scoring._shared import EditorialScore
from src.two_bot.types import StoryBundle


# ---------------------------------------------------------------------------
# Helpers to build lightweight fixtures without real network calls.
# ---------------------------------------------------------------------------

def _score(total: int = 80, category: str = "coral_bleaching") -> EditorialScore:
    """Build a minimal EditorialScore with a given total."""
    return EditorialScore(
        category=category,
        severity=80,
        novelty=80,
        timeliness=80,
        confidence=80,
        shareability=80,
        sensitivity=0,
        total=total,
        threshold=60,
        reasons=[],
    )


def _bundle(signal_kind: str = "coral_bleaching") -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind,
        where="Great Barrier Reef",
        when="2026-05-17",
        event_id="test_event",
        headline_metric={"label": "DHW", "value": 8},
        current_facts=[],
    )


def _candidate(
    *,
    signal_kind: str = "coral_bleaching",
    total: int = 80,
    source: str = "coral_dhw",
    event_id: str = "evt_001",
    created_at: str = "2026-05-17T12:00:00Z",
    cooldown_exempt: bool = False,
):
    """Build a TriageCandidateBundle with sensible defaults."""
    from src.two_bot.types import TriageCandidateBundle
    return TriageCandidateBundle(
        bundle=_bundle(signal_kind),
        score=_score(total, signal_kind),
        event_id=event_id,
        source=source,
        review_context={},
        city="",
        tweet_date="2026-05-17",
        cooldown_exempt=cooldown_exempt,
        legacy_type=signal_kind,
        created_at=created_at,
    )


def _fresh_state() -> dict:
    return deepcopy(DEFAULT_STATE)


# ---------------------------------------------------------------------------
# Tests for select_survivors() — pure triage logic
# ---------------------------------------------------------------------------

class TestSelectSurvivors:

    def test_empty_queue_returns_empty(self):
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        result = select_survivors(bot_state, [])
        assert result == []

    def test_single_candidate_passes_through(self):
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        c = _candidate()
        result = select_survivors(bot_state, [c])
        assert result == [c]

    def test_ranks_by_score_descending(self):
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        # Use distinct signal_kinds so per-category cap doesn't interfere
        low = _candidate(total=65, event_id="low", signal_kind="drought", created_at="2026-05-17T10:00:00Z")
        high = _candidate(total=90, event_id="high", signal_kind="sea_ice_record", created_at="2026-05-17T09:00:00Z")
        mid = _candidate(total=75, event_id="mid", signal_kind="fire", created_at="2026-05-17T08:00:00Z")
        result = select_survivors(bot_state, [low, mid, high], global_cap=3)
        # Highest score should be first
        assert result[0].event_id == "high"
        assert result[1].event_id == "mid"
        assert result[2].event_id == "low"

    def test_per_category_cap_enforced_when_default(self, monkeypatch):
        """Default cap is 2 per category. 3 coral_bleaching candidates → only 2 survive."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        candidates = [
            _candidate(total=90, event_id="c1", created_at="2026-05-17T12:00:00Z"),
            _candidate(total=85, event_id="c2", created_at="2026-05-17T11:00:00Z"),
            _candidate(total=80, event_id="c3", created_at="2026-05-17T10:00:00Z"),
        ]
        result = select_survivors(bot_state, candidates, global_cap=10)
        assert len(result) == 2
        assert {r.event_id for r in result} == {"c1", "c2"}

    def test_per_category_cap_respects_env_override(self, monkeypatch):
        """THEHEAT_PER_CATEGORY_CAP=1 → only 1 candidate per category survives.

        _per_category_cap() reads os.environ at call time (no module-level
        cache), so monkeypatch.setenv is sufficient — no module reload needed.
        """
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "1")
        from src.orchestrator.triage import select_survivors

        bot_state = _fresh_state()
        candidates = [
            _candidate(total=90, event_id="c1", created_at="2026-05-17T12:00:00Z"),
            _candidate(total=85, event_id="c2", created_at="2026-05-17T11:00:00Z"),
        ]
        result = select_survivors(bot_state, candidates, global_cap=10)
        assert len(result) == 1
        assert result[0].event_id == "c1"

    def test_global_cap_enforced(self, monkeypatch):
        """8 candidates across categories → at most 3 survive (global_cap=3)."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        candidates = [
            _candidate(total=90 - i, event_id=f"evt_{i}", signal_kind=f"cat_{i}", source=f"src_{i}")
            for i in range(8)
        ]
        result = select_survivors(bot_state, candidates, global_cap=3)
        assert len(result) == 3

    def test_spilled_candidates_record_triage_cap_suppression(self, monkeypatch):
        """Spilled candidates appear in bot_state['suppressions'] with kill_stage='triage_cap'."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        candidates = [
            _candidate(total=90, event_id="survive", created_at="2026-05-17T12:00:00Z"),
            _candidate(total=80, event_id="survive2", created_at="2026-05-17T11:00:00Z"),
            _candidate(total=70, event_id="spilled", created_at="2026-05-17T10:00:00Z"),
        ]
        select_survivors(bot_state, candidates, global_cap=10)  # per-category cap=2 spills 3rd
        suppressions = bot_state.get("suppressions", [])
        triage_supps = [s for s in suppressions if s.get("stage") == "triage_cap"]
        assert len(triage_supps) == 1
        assert triage_supps[0]["event_id"] == "spilled"

    def test_spill_reason_distinguishes_per_category_cap(self, monkeypatch):
        """A1: per-category-capped spills emit reasons=['per_category_cap=N']."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        # 3 same-category candidates, generous global_cap so only per-category fires
        candidates = [
            _candidate(total=90, event_id="c1", signal_kind="coral_bleaching"),
            _candidate(total=85, event_id="c2", signal_kind="coral_bleaching"),
            _candidate(total=70, event_id="c3_spilled", signal_kind="coral_bleaching"),
        ]
        select_survivors(bot_state, candidates, global_cap=10)
        supps = [s for s in bot_state.get("suppressions", []) if s.get("stage") == "triage_cap"]
        assert len(supps) == 1
        assert supps[0]["event_id"] == "c3_spilled"
        assert supps[0]["reasons"][0].startswith("per_category_cap="), (
            f"expected per_category_cap=... reason, got {supps[0]['reasons']}"
        )

    def test_spill_reason_distinguishes_global_cap(self, monkeypatch):
        """A1: global-capped spills emit reasons=['global_cap=N']."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        # 5 candidates across 5 distinct categories: none hit per-category cap
        # of 2 (one each), but global_cap=3 spills the bottom 2.
        candidates = [
            _candidate(total=90, event_id="c1", signal_kind="coral_bleaching"),
            _candidate(total=85, event_id="c2", signal_kind="fire"),
            _candidate(total=80, event_id="c3", signal_kind="record"),
            _candidate(total=75, event_id="c4_spilled", signal_kind="ice_loss"),
            _candidate(total=70, event_id="c5_spilled", signal_kind="snow_extreme"),
        ]
        survivors = select_survivors(bot_state, candidates, global_cap=3)
        assert len(survivors) == 3
        supps = [s for s in bot_state.get("suppressions", []) if s.get("stage") == "triage_cap"]
        assert len(supps) == 2
        for s in supps:
            assert s["reasons"][0].startswith("global_cap="), (
                f"expected global_cap=... reason, got {s['reasons']}"
            )
        assert {s["event_id"] for s in supps} == {"c4_spilled", "c5_spilled"}

    def test_score_tie_broken_by_created_at_desc(self, monkeypatch):
        """When two candidates tie on score, the more recent one (created_at DESC) wins."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        older = _candidate(total=80, event_id="older", created_at="2026-05-17T10:00:00Z")
        newer = _candidate(total=80, event_id="newer", created_at="2026-05-17T12:00:00Z")
        result = select_survivors(bot_state, [older, newer], global_cap=1)
        assert len(result) == 1
        assert result[0].event_id == "newer"

    def test_kill_switch_disables_triage(self, monkeypatch):
        """THEHEAT_TRIAGE_ENABLED=0 → drain writes everything in queue order (no-op)."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
        from src.orchestrator.common import _triage_enabled
        assert not _triage_enabled()

    def test_kill_switch_disables_pending_ttl_sweep(self, monkeypatch):
        """THEHEAT_TRIAGE_ENABLED=0 must not mutate pending drafts via TTL."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
        from src.orchestrator import common

        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {
                "id": "old_pending",
                "type": "coral_bleaching",
                "status": "pending",
                "created_at": "2026-05-01T00:00:00Z",
            }
        ]

        drafted = common._drain_and_write_triage_queue(bot_state, {"sources": []})

        assert drafted == 0
        assert bot_state["drafts"][0]["status"] == "pending"
        assert "rejected_reason" not in bot_state["drafts"][0]

    def test_cooldown_exempt_still_subject_to_triage_cap(self, monkeypatch):
        """cooldown_exempt=True doesn't bypass the triage cap."""
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()
        candidates = [
            _candidate(total=90, event_id="c1", cooldown_exempt=True),
            _candidate(total=85, event_id="c2", cooldown_exempt=True),
            _candidate(total=80, event_id="c3", cooldown_exempt=True),  # 3rd of same category
        ]
        result = select_survivors(bot_state, candidates, global_cap=10)
        # Per-category cap=2, so only 2 survive even though all are cooldown_exempt
        assert len(result) == 2
        assert {r.event_id for r in result} == {"c1", "c2"}


class TestSuppressionContext:

    def test_context_manager_sets_and_restores_context(self):
        from src.orchestrator.common import (
            _clear_suppression_ctx,
            _current_suppression_ctx,
            _suppression_context,
        )

        bot_state = _fresh_state()
        _clear_suppression_ctx()

        with _suppression_context(bot_state, source="test_source", run_id="run_1"):
            ctx = _current_suppression_ctx()
            assert ctx is not None
            assert ctx["bot_state"] is bot_state
            assert ctx["source"] == "test_source"
            assert ctx["run_id"] == "run_1"

        assert _current_suppression_ctx() is None


class TestTriageExceptionHandling:

    def test_triage_exception_falls_through_to_legacy(self, monkeypatch):
        """If triage.select_survivors raises, drain_and_write writes everything."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        from src.orchestrator import common

        bot_state = _fresh_state()
        candidates = [_candidate(event_id="c1"), _candidate(event_id="c2")]
        bot_state["_triage_queue"] = candidates

        written = []

        def fake_try_two_bot_draft(bundle, state, score, **kwargs):
            written.append(kwargs.get("event_id"))
            return True

        def boom(state, queue, **kwargs):
            raise RuntimeError("triage exploded")

        monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", fake_try_two_bot_draft)
        monkeypatch.setattr("src.orchestrator.triage.select_survivors", boom)

        current_run = {"sources": []}
        drafted = common._drain_and_write_triage_queue(bot_state, current_run)

        # Both candidates should have been written (fallback to full queue)
        assert len(written) == 2
        assert drafted == 2

    def test_triage_exception_clears_queue_for_next_cron(self, monkeypatch):
        """Even if triage raises, the queue key is removed from bot_state after drain."""
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        from src.orchestrator import common

        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [_candidate()]

        monkeypatch.setattr("src.orchestrator.common._try_two_bot_draft", lambda *a, **k: True)
        monkeypatch.setattr(
            "src.orchestrator.triage.select_survivors",
            lambda s, q, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        current_run = {"sources": []}
        drafted = common._drain_and_write_triage_queue(bot_state, current_run)

        # Queue must be gone from bot_state so next cron doesn't re-process stale candidates
        assert "_triage_queue" not in bot_state
        assert drafted == 1

    def test_triage_exception_records_suppression_and_source_health(self, monkeypatch):
        """A2: When triage raises, drain step records both a triage_error
        suppression row AND a source_health['triage'] entry while preserving
        the legacy passthrough behavior (all queued candidates still drafted).
        Without these signals, broken triage is invisible to the dashboard.
        """
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
        from src.orchestrator import common

        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _candidate(event_id="c1"),
            _candidate(event_id="c2"),
        ]

        written: list[str | None] = []
        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda bundle, state, score, **kwargs: (
                written.append(kwargs.get("event_id")) or True
            ),
        )
        monkeypatch.setattr(
            "src.orchestrator.triage.select_survivors",
            lambda s, q, **k: (_ for _ in ()).throw(RuntimeError("triage exploded")),
        )

        drafted = common._drain_and_write_triage_queue(bot_state, {"sources": []})

        # Legacy passthrough preserved — both candidates still drafted.
        assert drafted == 2
        assert len(written) == 2

        # (a) Suppression row records the triage stage failure.
        triage_errors = [
            s for s in bot_state.get("suppressions", [])
            if s.get("stage") == "triage_error"
        ]
        assert len(triage_errors) == 1
        assert triage_errors[0]["source"] == "triage"
        assert "triage exploded" in triage_errors[0]["reasons"][0]

        # (b) source_health['triage'] entry surfaces the error in the dashboard.
        health_map = bot_state.get("source_health", {})
        triage_health = health_map.get("triage")
        assert triage_health is not None, "source_health['triage'] must exist after drain failure"
        assert triage_health.get("degraded", 0) + triage_health.get("failed", 0) >= 1
        assert "triage exploded" in (triage_health.get("last_error") or "")


class TestTriageTelemetry:

    def test_spill_records_source_attribution_for_dashboard(self, monkeypatch):
        """Spilled candidates land in the suppression ledger with their source
        attached, so the dashboard can attribute spills back to the source
        runner that produced them.

        NOTE: The spec § 9 also calls for per-source `triaged_in` and
        `triaged_out` running counters in `current_run["sources"][source]`.
        Those are deferred to a follow-up PR alongside the first source
        migration (coral_dhw) where the telemetry surface actually lights
        up — see TODO in `_drain_and_write_triage_queue` in
        src/orchestrator/common.py.
        """
        monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
        from src.orchestrator.triage import select_survivors
        bot_state = _fresh_state()

        # 3 coral_bleaching candidates — 2 survive, 1 spills (per-category cap=2)
        candidates = [
            _candidate(total=90, event_id="c1", source="coral_dhw"),
            _candidate(total=85, event_id="c2", source="coral_dhw"),
            _candidate(total=70, event_id="c3", source="coral_dhw"),
        ]
        survivors = select_survivors(bot_state, candidates, global_cap=10)
        spilled = [c for c in candidates if c not in survivors]

        assert len(survivors) == 2
        assert len(spilled) == 1
        assert spilled[0].event_id == "c3"

        # The suppression record for the spilled candidate exists AND
        # captures its source so the dashboard can attribute it.
        suppressions = bot_state.get("suppressions", [])
        triage_supps = [s for s in suppressions if s.get("stage") == "triage_cap"]
        assert len(triage_supps) == 1
        assert triage_supps[0]["source"] == "coral_dhw"
        assert triage_supps[0]["event_id"] == "c3"


# ---------------------------------------------------------------------------
# Tests for _enqueue_candidate
# ---------------------------------------------------------------------------

class TestEnqueueCandidate:

    def test_enqueue_appends_to_triage_queue(self):
        from src.orchestrator.common import _enqueue_candidate
        bot_state = _fresh_state()
        c = _candidate()
        _enqueue_candidate(bot_state, c)
        assert bot_state["_triage_queue"] == [c]

    def test_enqueue_multiple_candidates(self):
        from src.orchestrator.common import _enqueue_candidate
        bot_state = _fresh_state()
        c1 = _candidate(event_id="e1")
        c2 = _candidate(event_id="e2")
        _enqueue_candidate(bot_state, c1)
        _enqueue_candidate(bot_state, c2)
        assert bot_state["_triage_queue"] == [c1, c2]


class TestEnqueueStoryCandidate:

    def _valid_bundle(self) -> StoryBundle:
        return StoryBundle(
            signal_kind="river_flood",
            where="Ohio River at Cincinnati",
            when="2026-05-19",
            event_id="river_flood_1",
            headline_metric={"label": "Above flood stage", "value": 3.2, "unit": "ft"},
            current_facts=[
                {"label": "Gauge", "value": "Ohio River at Cincinnati"},
                {"label": "Source", "value": "USGS Water"},
            ],
            historical_context={"flood_stage_ft": 52.0},
            raw_signal_dump={
                "source": "USGS Water",
                "station": "03255000",
                "above_by_ft": 3.2,
            },
        )

    def test_enqueue_story_candidate_audits_and_enqueues_valid_bundle(self):
        from src.orchestrator.common import _enqueue_story_candidate

        bot_state = _fresh_state()
        ok = _enqueue_story_candidate(
            bot_state,
            bundle=self._valid_bundle(),
            score=_score(85, "river_flood"),
            source="river_gauges",
            legacy_type="river_flood",
            event_id="river_flood_1",
            review_context={"source": "USGS Water"},
            city="Ohio River at Cincinnati",
            tweet_date="2026-05-19",
        )

        assert ok is True
        queue = bot_state["_triage_queue"]
        assert len(queue) == 1
        assert queue[0].source == "river_gauges"
        assert queue[0].event_id == "river_flood_1"
        assert queue[0].legacy_type == "river_flood"

    def test_enqueue_story_candidate_rejects_invalid_bundle_before_queue(self):
        from dataclasses import replace

        from src.orchestrator.common import _enqueue_story_candidate

        bot_state = _fresh_state()
        bad_bundle = replace(self._valid_bundle(), event_id="")

        ok = _enqueue_story_candidate(
            bot_state,
            bundle=bad_bundle,
            score=_score(85, "river_flood"),
            source="river_gauges",
            legacy_type="river_flood",
            event_id="river_flood_1",
            review_context={"source": "USGS Water"},
        )

        assert ok is False
        assert "_triage_queue" not in bot_state
        suppressions = bot_state.get("suppressions", [])
        assert len(suppressions) == 1
        assert suppressions[0]["source"] == "river_gauges"
        assert suppressions[0]["stage"] == "evidence_contract"
        assert suppressions[0]["reasons"] == ["missing_event_id"]


# ---------------------------------------------------------------------------
# Pending-queue diversity gate (0.9.6.0)
# ---------------------------------------------------------------------------

class TestPendingTypeCap:
    """Triage refuses to promote new candidates of a type the pending queue
    already saturates.

    This is the structural fix for the May 2026 coral-bleaching pile-up: the
    pre-0.9.0.0 unbounded promoter let 10 coral_bleaching drafts accumulate
    in pending. The per-category cycle cap bounds new INPUT per cron but does
    nothing about pending-queue COMPOSITION over many cycles. This cap is
    the queue-aware backstop.
    """

    def test_blocks_promotion_when_pending_already_at_cap(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_PENDING_TYPE_CAP", raising=False)
        # Raise the per-category cycle cap so it doesn't gate this test —
        # we want pending_type_cap to be the killing gate, not per_category_cap.
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")
        from src.orchestrator.triage import select_survivors

        bot_state = _fresh_state()
        # Pending already at default cap (3) for coral_bleaching.
        bot_state["drafts"] = [
            {"type": "coral_bleaching", "status": "pending", "id": f"d{i}"}
            for i in range(3)
        ]
        candidate = _candidate(
            signal_kind="coral_bleaching",
            total=95,
            event_id="new_coral",
        )

        result = select_survivors(bot_state, [candidate], global_cap=10)

        assert result == []
        suppressions = bot_state.get("suppressions", [])
        assert len(suppressions) == 1
        assert suppressions[0]["stage"] == "triage_cap"
        assert suppressions[0]["reasons"] == ["pending_type_cap=3"]
        assert suppressions[0]["event_id"] == "new_coral"

    def test_admits_promotion_when_pending_below_cap(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_PENDING_TYPE_CAP", raising=False)
        from src.orchestrator.triage import select_survivors

        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {"type": "coral_bleaching", "status": "pending", "id": "d1"},
        ]  # 1 pending — under default cap of 3
        candidate = _candidate(signal_kind="coral_bleaching", total=90)

        result = select_survivors(bot_state, [candidate], global_cap=10)

        assert len(result) == 1
        assert result[0].event_id == candidate.event_id

    def test_rejected_drafts_do_not_count_toward_cap(self, monkeypatch):
        """Only status='pending' drafts gate the cap. Rejected/posted free
        the slot — the cap is about CURRENT queue composition, not history."""
        monkeypatch.delenv("THEHEAT_PENDING_TYPE_CAP", raising=False)
        from src.orchestrator.triage import select_survivors

        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {"type": "coral_bleaching", "status": "rejected", "id": "old1"},
            {"type": "coral_bleaching", "status": "rejected", "id": "old2"},
            {"type": "coral_bleaching", "status": "posted", "id": "old3"},
            {"type": "coral_bleaching", "status": "pending", "id": "current1"},
        ]  # 4 with this type, but only 1 pending — under cap
        candidate = _candidate(signal_kind="coral_bleaching", total=90)

        result = select_survivors(bot_state, [candidate], global_cap=10)

        assert len(result) == 1

    def test_consecutive_same_type_survivors_increment_pending_count(self, monkeypatch):
        """First survivor of a type bumps the pending count for the next
        candidate of the same type — prevents over-admission within one
        cycle if pending was already close to cap."""
        monkeypatch.delenv("THEHEAT_PENDING_TYPE_CAP", raising=False)
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")  # don't let category cap interfere
        from src.orchestrator.triage import select_survivors

        bot_state = _fresh_state()
        # Pending has 2 — one slot left before hitting cap of 3.
        bot_state["drafts"] = [
            {"type": "snow_extreme", "status": "pending", "id": "s1"},
            {"type": "snow_extreme", "status": "pending", "id": "s2"},
        ]
        # Two new snow_extreme candidates from this cycle.
        c1 = _candidate(signal_kind="snow_extreme", total=90, event_id="snow_new_1")
        c2 = _candidate(signal_kind="snow_extreme", total=88, event_id="snow_new_2")

        result = select_survivors(bot_state, [c1, c2], global_cap=10)

        # Only one can pass (filling the last pending slot); the other spills.
        assert len(result) == 1
        assert result[0].event_id == "snow_new_1"  # highest score wins ranking
        suppressions = bot_state.get("suppressions", [])
        assert len(suppressions) == 1
        assert suppressions[0]["reasons"] == ["pending_type_cap=3"]

    def test_pending_type_cap_respects_env_override(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_PENDING_TYPE_CAP", "1")
        from src.orchestrator.triage import select_survivors

        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {"type": "coral_bleaching", "status": "pending", "id": "d1"},
        ]
        candidate = _candidate(signal_kind="coral_bleaching", total=95)

        result = select_survivors(bot_state, [candidate], global_cap=10)

        assert result == []  # cap=1 means 1 pending is full


class TestPendingTtlSweep:
    """The TTL sweep auto-rejects pending drafts older than the configured
    TTL window. Wired into _drain_and_write_triage_queue so it runs every
    cycle, freeing pending-type-cap slots for fresh signals.
    """

    def test_rejects_drafts_older_than_ttl(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_PENDING_TTL_DAYS", raising=False)
        from datetime import UTC, datetime, timedelta

        from src.orchestrator.triage import apply_pending_ttl_sweep

        now = datetime(2026, 5, 27, 18, 30, tzinfo=UTC)
        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {
                "id": "old1",
                "type": "coral_bleaching",
                "status": "pending",
                "created_at": (now - timedelta(days=13)).isoformat().replace("+00:00", "Z"),
            },
            {
                "id": "old2",
                "type": "coral_bleaching",
                "status": "pending",
                "created_at": (now - timedelta(days=8)).isoformat().replace("+00:00", "Z"),
            },
        ]

        n = apply_pending_ttl_sweep(bot_state, now=now)

        assert n == 2
        for d in bot_state["drafts"]:
            assert d["status"] == "rejected"
            assert d["rejected_reason"] == "staleness_ttl_7d"
            assert "rejected_at" in d

    def test_preserves_drafts_inside_ttl_window(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_PENDING_TTL_DAYS", raising=False)
        from datetime import UTC, datetime, timedelta

        from src.orchestrator.triage import apply_pending_ttl_sweep

        now = datetime(2026, 5, 27, 18, 30, tzinfo=UTC)
        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {
                "id": "fresh",
                "type": "coral_bleaching",
                "status": "pending",
                "created_at": (now - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
            },
        ]

        n = apply_pending_ttl_sweep(bot_state, now=now)

        assert n == 0
        assert bot_state["drafts"][0]["status"] == "pending"

    def test_only_affects_pending_status(self, monkeypatch):
        """Already-rejected and posted drafts are not double-processed."""
        monkeypatch.delenv("THEHEAT_PENDING_TTL_DAYS", raising=False)
        from datetime import UTC, datetime, timedelta

        from src.orchestrator.triage import apply_pending_ttl_sweep

        now = datetime(2026, 5, 27, 18, 30, tzinfo=UTC)
        stale_ts = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {"id": "r1", "status": "rejected", "created_at": stale_ts},
            {"id": "p1", "status": "posted", "created_at": stale_ts},
        ]

        n = apply_pending_ttl_sweep(bot_state, now=now)

        assert n == 0
        assert bot_state["drafts"][0]["status"] == "rejected"  # unchanged
        assert bot_state["drafts"][1]["status"] == "posted"  # unchanged

    def test_handles_missing_or_malformed_created_at(self, monkeypatch):
        """Drafts without a usable created_at field are left alone — better
        to leak a stale draft than to mass-reject everything if a field
        rename slips through."""
        monkeypatch.delenv("THEHEAT_PENDING_TTL_DAYS", raising=False)
        from datetime import UTC, datetime

        from src.orchestrator.triage import apply_pending_ttl_sweep

        now = datetime(2026, 5, 27, 18, 30, tzinfo=UTC)
        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {"id": "no_field", "status": "pending"},
            {"id": "null_field", "status": "pending", "created_at": None},
            {"id": "empty_field", "status": "pending", "created_at": ""},
        ]

        n = apply_pending_ttl_sweep(bot_state, now=now)

        assert n == 0
        for d in bot_state["drafts"]:
            assert d["status"] == "pending"

    def test_ttl_respects_env_override(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_PENDING_TTL_DAYS", "3")
        from datetime import UTC, datetime, timedelta

        from src.orchestrator.triage import apply_pending_ttl_sweep

        now = datetime(2026, 5, 27, 18, 30, tzinfo=UTC)
        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {
                "id": "d_4d_old",
                "status": "pending",
                "created_at": (now - timedelta(days=4)).isoformat().replace("+00:00", "Z"),
            },
            {
                "id": "d_2d_old",
                "status": "pending",
                "created_at": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            },
        ]

        n = apply_pending_ttl_sweep(bot_state, now=now)

        assert n == 1
        statuses = {d["id"]: d["status"] for d in bot_state["drafts"]}
        assert statuses["d_4d_old"] == "rejected"
        assert statuses["d_2d_old"] == "pending"
        rejected = next(d for d in bot_state["drafts"] if d["id"] == "d_4d_old")
        assert rejected["rejected_reason"] == "staleness_ttl_3d"
