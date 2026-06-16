"""Unit tests for Phase A funnel instrumentation (src/orchestrator/funnel.py).

TDD: written before the production module. Covers the codex must-fixes:
  - 7-day rollup built from run_history (per-run funnel frozen on the run dict),
    NOT source_health.
  - exact per-stage denominators (critic_pass_rate = passes/(passes+kills)).
  - kills counted from THIS run's suppressions only (run_id scoped) — immune to
    the global 100-row suppressions cap because each run's counts are frozen.
  - shadow slate captured before the queue drains, terminal stage resolved from
    drafts + suppressions (so cycle_cap / triage_cap land correctly).
  - flag default-OFF and zero-behaviour-change when off.
"""

from __future__ import annotations

from copy import deepcopy

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE
from src.two_bot.types import StoryBundle, TriageCandidateBundle


def _fresh_state() -> dict:
    return deepcopy(DEFAULT_STATE)


def _score(total: int = 80, category: str = "coral_bleaching") -> EditorialScore:
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


def _bundle(signal_kind: str = "coral_bleaching", event_id: str = "evt", where: str = "Reef") -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind,
        where=where,
        when="2026-06-16",
        event_id=event_id,
        headline_metric={"label": "DHW", "value": 8},
        current_facts=[],
    )


def _candidate(*, event_id: str, total: int = 80, source: str = "coral_dhw",
               signal_kind: str = "coral_bleaching", where: str = "Reef") -> TriageCandidateBundle:
    return TriageCandidateBundle(
        bundle=_bundle(signal_kind, event_id, where),
        score=_score(total, signal_kind),
        event_id=event_id,
        source=source,
        review_context={},
        city="",
        tweet_date="2026-06-16",
        cooldown_exempt=False,
        legacy_type=signal_kind,
        created_at="2026-06-16T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# Flag
# ---------------------------------------------------------------------------

class TestFlag:
    def test_default_off(self, monkeypatch):
        from src.orchestrator import funnel
        monkeypatch.delenv("THEHEAT_FUNNEL_TELEMETRY", raising=False)
        assert funnel.funnel_telemetry_enabled() is False

    def test_truthy_values_enable(self, monkeypatch):
        from src.orchestrator import funnel
        for v in ("1", "true", "on", "yes", "TRUE", "On"):
            monkeypatch.setenv("THEHEAT_FUNNEL_TELEMETRY", v)
            assert funnel.funnel_telemetry_enabled() is True

    def test_falsy_values_disable(self, monkeypatch):
        from src.orchestrator import funnel
        for v in ("0", "false", "off", "no", ""):
            monkeypatch.setenv("THEHEAT_FUNNEL_TELEMETRY", v)
            assert funnel.funnel_telemetry_enabled() is False


# ---------------------------------------------------------------------------
# Skeleton + pass accumulation
# ---------------------------------------------------------------------------

class TestPassAccumulation:
    def test_new_funnel_zeroes_pass_stages(self):
        from src.orchestrator import funnel
        sink = funnel.new_funnel()
        assert sink["passes"] == {"writer": 0, "fact_check": 0, "critic": 0}

    def test_records_only_pass_outcomes_for_pass_stages(self):
        from src.orchestrator import funnel
        sink = funnel.new_funnel()
        # died at critic: writer + fact_check passed, critic killed
        funnel.record_candidate_passes(sink, {"writer": "pass", "fact_check": "pass", "critic": "kill"})
        # clean success: all three passed
        funnel.record_candidate_passes(sink, {"writer": "pass", "fact_check": "pass", "critic": "pass"})
        # died at writer
        funnel.record_candidate_passes(sink, {"writer": "kill"})
        assert sink["passes"] == {"writer": 2, "fact_check": 2, "critic": 1}

    def test_ignores_non_pass_stage_keys(self):
        from src.orchestrator import funnel
        sink = funnel.new_funnel()
        funnel.record_candidate_passes(sink, {"safety": "pass", "honesty_gate": "pass", "writer": "pass"})
        assert sink["passes"] == {"writer": 1, "fact_check": 0, "critic": 0}


# ---------------------------------------------------------------------------
# Shadow slate capture
# ---------------------------------------------------------------------------

class TestSlateCapture:
    def test_captures_top_n_by_score_descending(self):
        from src.orchestrator import funnel
        sink = funnel.new_funnel()
        queue = [
            _candidate(event_id="low", total=61, where="Lima"),
            _candidate(event_id="high", total=99, where="Cairo"),
            _candidate(event_id="mid", total=80, where="Oslo"),
        ]
        funnel.capture_slate(sink, queue)
        skel = sink["_slate_skeleton"]
        assert [s["event_id"] for s in skel] == ["high", "mid", "low"]
        assert skel[0]["score_total"] == 99
        assert skel[0]["type"] == "coral_bleaching"
        assert skel[0]["summary"] == "Cairo"

    def test_caps_at_shadow_slate_size_and_dedupes_event_ids(self):
        from src.orchestrator import funnel
        sink = funnel.new_funnel()
        queue = [_candidate(event_id=f"e{i}", total=50 + i) for i in range(20)]
        queue.append(_candidate(event_id="e0", total=99))  # duplicate event_id, higher score
        funnel.capture_slate(sink, queue)
        skel = sink["_slate_skeleton"]
        assert len(skel) == funnel.SHADOW_SLATE_SIZE
        ids = [s["event_id"] for s in skel]
        assert len(ids) == len(set(ids))  # distinct
        # the higher-scoring duplicate of e0 represents e0
        e0 = next(s for s in skel if s["event_id"] == "e0")
        assert e0["score_total"] == 99


# ---------------------------------------------------------------------------
# finalize_funnel — the load-bearing aggregation
# ---------------------------------------------------------------------------

class TestFinalizeFunnel:
    def test_volume_summed_from_current_run_sources(self):
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        current_run = {"id": "run_x", "sources": [
            {"source": "a", "observed": 100, "promoted": 10, "triaged_in": 5,
             "triaged_out": 3, "writer_attempted": 3, "drafted": 1},
            {"source": "b", "observed": 50, "promoted": 4, "triaged_in": 2,
             "triaged_out": 1, "writer_attempted": 1, "drafted": 0},
        ]}
        sink = funnel.new_funnel()
        funnel.finalize_funnel(sink, current_run, bot_state)
        f = current_run["funnel"]
        assert f["observed"] == 150
        assert f["promoted"] == 14
        assert f["writer_attempted"] == 4
        assert f["drafted"] == 1

    def test_kills_counted_live_into_sink(self):
        """Kills are counted live via record_kill into the attached sink — never
        read back from the truncatable global suppressions ledger."""
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        sink = funnel.new_funnel()
        funnel.attach_sink(bot_state, sink)
        funnel.record_kill(bot_state, "critic")
        funnel.record_kill(bot_state, "critic")
        funnel.record_kill(bot_state, "city_cooldown")
        current_run = {"id": "run_x", "sources": []}
        funnel.finalize_funnel(sink, current_run, bot_state)
        assert current_run["funnel"]["kills"] == {"critic": 2, "city_cooldown": 1}
        # sink is popped off bot_state at finalize (transient, never persisted)
        assert "_funnel_sink" not in bot_state

    def test_kills_immune_to_suppressions_cap(self):
        """A cycle with >100 kills (the global ledger truncates at 100) still
        freezes the true per-run count — codex must-fix on the cap blindness."""
        from src.orchestrator import funnel
        from src.state import MAX_SUPPRESSIONS
        bot_state = _fresh_state()
        sink = funnel.new_funnel()
        funnel.attach_sink(bot_state, sink)
        total = MAX_SUPPRESSIONS + 50
        for _ in range(total):
            funnel.record_kill(bot_state, "triage_cap")
        current_run = {"id": "run_x", "sources": []}
        funnel.finalize_funnel(sink, current_run, bot_state)
        assert current_run["funnel"]["kills"]["triage_cap"] == total

    def test_record_kill_no_sink_is_noop(self):
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        funnel.record_kill(bot_state, "critic")  # no sink attached → no-op, no crash

    def test_critic_pass_rate_uses_passes_and_kills(self):
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        sink = funnel.new_funnel()
        funnel.attach_sink(bot_state, sink)
        funnel.record_kill(bot_state, "critic")  # 1 critic kill
        funnel.record_candidate_passes(sink, {"writer": "pass", "fact_check": "pass", "critic": "pass"})
        funnel.record_candidate_passes(sink, {"writer": "pass", "fact_check": "pass", "critic": "pass"})
        funnel.record_candidate_passes(sink, {"writer": "pass", "fact_check": "pass", "critic": "pass"})
        current_run = {"id": "run_x", "sources": []}
        funnel.finalize_funnel(sink, current_run, bot_state)
        rates = funnel.funnel_rates(current_run["funnel"])
        # 3 passes, 1 kill => 0.75
        assert rates["critic_pass_rate"] == 0.75
        assert rates["stages"]["critic"]["attempts"] == 4

    def test_rates_none_when_no_attempts(self):
        from src.orchestrator import funnel
        f = {"observed": 0, "promoted": 0, "triaged_in": 0, "triaged_out": 0,
             "writer_attempted": 0, "drafted": 0,
             "passes": {"writer": 0, "fact_check": 0, "critic": 0}, "kills": {}}
        rates = funnel.funnel_rates(f)
        assert rates["critic_pass_rate"] is None
        assert rates["draft_yield"] is None
        assert rates["triage_cap_rate"] is None

    def test_slate_terminal_drafted_vs_drain_kill_vs_triage_cap(self):
        """Terminal stages come from drain-observed records (record_slate_terminal)
        + live drafts — NOT the suppression ledger (triage_cap rows have run_id=None)."""
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        bot_state["drafts"] = [{"event_id": "drafted_evt", "status": "pending"}]
        current_run = {"id": "run_x", "sources": []}
        sink = funnel.new_funnel()
        queue = [
            _candidate(event_id="drafted_evt", total=99),
            _candidate(event_id="critic_evt", total=90),
            _candidate(event_id="cut_evt", total=70),
        ]
        funnel.capture_slate(sink, queue)
        # drain-observed terminals:
        funnel.record_slate_terminal(sink, "critic_evt", "critic")
        funnel.record_slate_terminal(sink, "cut_evt", "triage_cap")
        funnel.finalize_funnel(sink, current_run, bot_state)
        slate = {s["event_id"]: s["terminal_stage"] for s in current_run["shadow_slate"]}
        assert slate["drafted_evt"] == "drafted"
        assert slate["critic_evt"] == "critic"
        assert slate["cut_evt"] == "triage_cap"

    def test_record_slate_terminal_ignores_non_slate_events(self):
        from src.orchestrator import funnel
        sink = funnel.new_funnel()
        funnel.capture_slate(sink, [_candidate(event_id="in_slate", total=80)])
        funnel.record_slate_terminal(sink, "not_in_slate", "critic")
        assert "not_in_slate" not in sink["_slate_terminal"]

    def test_slate_terminal_cycle_cap_overrides(self):
        """A draft pruned by the cycle cap (pruned_event_ids) is reclassified
        cycle_cap, overriding the drain's 'drafted' record."""
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        bot_state["drafts"] = []  # pruned out of drafts
        current_run = {"id": "run_x", "sources": []}
        sink = funnel.new_funnel()
        funnel.capture_slate(sink, [_candidate(event_id="pruned_evt", total=88)])
        funnel.record_slate_terminal(sink, "pruned_evt", "drafted")
        funnel.finalize_funnel(sink, current_run, bot_state, pruned_event_ids={"pruned_evt"})
        assert current_run["shadow_slate"][0]["terminal_stage"] == "cycle_cap"

    def test_zero_safe_on_empty_run(self):
        from src.orchestrator import funnel
        bot_state = _fresh_state()
        current_run = {"id": "run_x", "sources": []}
        sink = funnel.new_funnel()
        funnel.finalize_funnel(sink, current_run, bot_state)
        f = current_run["funnel"]
        assert f["observed"] == 0 and f["drafted"] == 0
        assert current_run["shadow_slate"] == []


# ---------------------------------------------------------------------------
# 7-day rollup over run_history (must-fix #2: from run_history, not source_health)
# ---------------------------------------------------------------------------

class TestRollup:
    def test_rollup_sums_per_run_funnels(self):
        from src.orchestrator import funnel
        run_history = [
            {"id": "r1", "funnel": {"observed": 100, "promoted": 10, "triaged_in": 5,
                                    "triaged_out": 3, "writer_attempted": 3, "drafted": 1,
                                    "passes": {"writer": 3, "fact_check": 3, "critic": 1},
                                    "kills": {"critic": 2}}},
            {"id": "r2", "funnel": {"observed": 200, "promoted": 20, "triaged_in": 6,
                                    "triaged_out": 4, "writer_attempted": 4, "drafted": 2,
                                    "passes": {"writer": 4, "fact_check": 4, "critic": 2},
                                    "kills": {"critic": 2, "writer": 1}}},
            {"id": "r3"},  # no funnel (telemetry was off) — skipped, not crash
        ]
        rollup = funnel.rollup_funnels(run_history)
        assert rollup["observed"] == 300
        assert rollup["drafted"] == 3
        assert rollup["passes"]["critic"] == 3
        assert rollup["kills"]["critic"] == 4
        assert rollup["kills"]["writer"] == 1
        rates = funnel.funnel_rates(rollup)
        # critic: 3 passes, 4 kills => 3/7
        assert abs(rates["critic_pass_rate"] - 3 / 7) < 1e-9
