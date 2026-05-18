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
        common._drain_and_write_triage_queue(bot_state, current_run)

        # Both candidates should have been written (fallback to full queue)
        assert len(written) == 2

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
        common._drain_and_write_triage_queue(bot_state, current_run)

        # Queue must be gone from bot_state so next cron doesn't re-process stale candidates
        assert "_triage_queue" not in bot_state


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
