"""O3: the actual producer entrypoints under the operation candidate budget.

``run_alerts`` runs EVERY real source runner. The network is refused, so each
source without an invented feed records itself unavailable. FIRMS receives
invented detections at its adapter boundary and a supplied official warning
enters through the real warning runner. Model stages are labelled OFFLINE stubs
behind the real provider boundary. CLI cases run ``src.main.main()`` with an
invented in-memory store. Nothing reaches a source, model, Gist or X.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import importlib
import socket
import sys

import pytest

from src.data.open_meteo import CityTemp
from src.editorial.scoring import EditorialScore
from tests.operation_budget_helpers import OTHER_ALERT_RUNNERS, fresh_state, isolate_firms, offline_world

alerts_mod = importlib.import_module("src.orchestrator.run_alerts")
hot10_mod = importlib.import_module("src.orchestrator.hot10")
WARNING_SCORE = EditorialScore("official_warning", 80, 80, 80, 80, 80, 0, 80, 60,
                               ["Explicit invented editorial nomination."])


@pytest.fixture
def world(monkeypatch):
    return offline_world(monkeypatch)


def test_offline_world_refuses_dns_and_both_connection_paths(world):
    with pytest.raises(OSError, match="network refused"):
        socket.getaddrinfo("invented.invalid", 443)
    with socket.socket() as transport:
        for connect in (transport.connect, transport.connect_ex):
            with pytest.raises(OSError, match="network refused"):
                connect(("192.0.2.1", 443))
    assert len(world.connects) == 3


def test_firms_isolation_restores_every_compatibility_target(world, monkeypatch):
    main = importlib.import_module("src.main")
    originals = [(module, name, getattr(module, name)) for module in main._SYNC_MODULES
                 for name in OTHER_ALERT_RUNNERS if hasattr(module, name)]
    with monkeypatch.context() as scoped:
        isolate_firms(scoped)
        main._sync_compat_globals()
        assert all(getattr(module, name) is not original for module, name, original in originals)
    assert all(getattr(module, name) is original for module, name, original in originals)


def run_alerts(*, warning=False):
    from tests.warning_journey_helpers import source
    state, run = fresh_state(), {"id": "run-o3", "sources": []}
    extra = {"warning_source": source(), "warning_score": WARNING_SCORE} if warning else {}
    alerts_mod.run_alerts(state, run, **extra)
    return state, run


def rows(run, status):
    return [row["source"] for row in run["sources"] if row["status"] == status]


def cuts(state, prefix):
    return [row for row in state["suppressions"] if row.get("stage") == "triage_cap"
            and any(reason.startswith(prefix) for reason in row.get("reasons", []))]


def test_multi_source_slate_at_n1_attempts_exactly_one_candidate(world):
    state, run = run_alerts(warning=True)
    (chosen,) = world.spies.writer_events()
    assert [stage for stage, _ in world.spies.calls] == ["writer", "safety", "fact_check", "critic"]
    (draft,) = state["drafts"]
    assert draft["event_id"] == chosen and draft["status"] == "pending" and "approval_binding" not in draft
    # Four live candidates from two useful sources; three held by the unchanged caps, visibly.
    assert sum(row["triaged_in"] for row in run["sources"] if "triaged_in" in row) == 4
    assert len(cuts(state, "global_cap=") + cuts(state, "per_category_cap=")) == 3
    # An unavailable source earlier in the run did not stop a later useful one.
    order = [row["source"] for row in run["sources"]]
    assert order.index("open_meteo_extreme_signals") < order.index("firms")
    assert "open_meteo_extreme_signals" in rows(run, "failed") and "firms" in rows(run, "success")
    assert "official_warning" in rows(run, "success") and "nws_alerts" in rows(run, "failed")


def test_a_ranking_fault_holds_the_whole_operation(world, monkeypatch):
    monkeypatch.setattr("src.orchestrator.triage.select_survivors",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("invented ranking fault")))
    state, run = run_alerts(warning=True)
    assert world.spies.calls == [] and state["drafts"] == []
    (row,) = [row for row in run["sources"] if row["source"] == "triage"]
    assert row["status"] == "partial_failure" and row["details"]["held"] == 4


@pytest.mark.parametrize("refill", [False, True], ids=["refill-off", "refill-on"])
def test_a_rejected_first_attempt_is_not_replaced_at_n1(world, monkeypatch, refill):
    if refill:
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    world.spies.critic_reject_first = 99
    state, run = run_alerts(warning=True)
    assert len(world.spies.writer_events()) == 1 and state["drafts"] == []
    assert sum(row.get("stage") == "critic" for row in state["suppressions"]) == 1
    if refill:
        assert len(cuts(state, "candidate_budget=1")) == 3  # Refill met the spent budget, not its own 2 x 3.


@pytest.mark.parametrize("refill", [False, True], ids=["refill-off", "refill-on"])
def test_refill_toggle_stays_within_n_and_off_runs_no_refill_path(world, monkeypatch, refill):
    from src.orchestrator import triage_queue
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2")
    monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "50")
    entered: list = []
    real = triage_queue._refill_drain
    monkeypatch.setattr(triage_queue, "_refill_drain", lambda *a, **k: entered.append(1) or real(*a, **k))
    if refill:
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
    world.spies.critic_reject_first = 1
    state, run = run_alerts(warning=True)
    assert len(world.spies.writer_events()) == 2 and len(state["drafts"]) == 1  # First rejected, second saved.
    assert entered == ([1] if refill else [])  # Refill off makes no refill attempt at all.


def test_a_green_cli_run_with_unavailable_sources_is_reported_partial(world, monkeypatch):
    saved = []
    monkeypatch.setattr("src.state.read_state", lambda: fresh_state())
    monkeypatch.setattr("src.state.write_state", lambda state: saved.append(state) or True)
    monkeypatch.setattr(sys, "argv", ["src.main", "alerts"])
    importlib.import_module("src.main").main()  # Returns normally: the workflow step would be green.
    report = saved[-1]["run_history"][0]
    assert report["status"] == "partial_failure" and report["drafted_count"] == 1
    assert report["failure_count"] >= 1 and len(world.spies.writer_events()) == 1


def _leaderboard_inputs(monkeypatch, tmp_path=None, *, stray=False):
    """Unqualified legacy rows (no adapter evidence or normals) by default; with
    ``tmp_path``, invented catalogue cities carrying the real adapter's evidence."""
    cities: list[dict]
    normals: dict
    if tmp_path is None:
        ranked = [CityTemp(f"Invented City {i}", "ZZ", 10.0 + i, 20.0 + i, 40.0 - i, 30.0, 10.0 - i,
                           signal_date=date(2026, 10, 29)) for i in range(10)]
        cities, normals = [], {}
    else:
        from tests.live_content_harness import qualified_inputs
        cities, normals, ranked = qualified_inputs(tmp_path, datetime.now(UTC))
    monkeypatch.setattr(hot10_mod.open_meteo, "load_cities", lambda: cities)
    monkeypatch.setattr(hot10_mod.open_meteo, "load_normals", lambda: normals)
    monkeypatch.setattr(hot10_mod.open_meteo, "fetch_all_city_temps", lambda cities: ranked)
    if stray:
        real = hot10_mod._enqueue_story_candidate

        def enqueue_with_stray(state, **kwargs):
            # An invented second, distinct qualified Hot10 candidate sharing this operation's queue.
            from src.two_bot.intern import build_hot10_bundle
            raw = kwargs["bundle"].raw_signal_dump
            stray_id = "hot10_" + (date.fromisoformat(kwargs["event_id"][6:]) - timedelta(days=1)).isoformat()
            stray_bundle = build_hot10_bundle(raw["cities"], changes=[], event_id=stray_id, universe=raw["universe"])
            assert real(state, **{**kwargs, "bundle": stray_bundle, "event_id": stray_id})
            return real(state, **kwargs)
        monkeypatch.setattr(hot10_mod, "_enqueue_story_candidate", enqueue_with_stray)


def test_hot10_is_one_operation_with_at_most_one_writer_attempt(world, monkeypatch, tmp_path):
    # Qualified inputs carry the Open-Meteo adapter's own provenance; no routing fixture.
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "5")
    _leaderboard_inputs(monkeypatch, tmp_path, stray=True)
    state, run = fresh_state(), {"id": "run-o3", "sources": []}
    hot10_mod.run_leaderboard(state, run)
    assert len(world.spies.writer_events()) == 1  # Never a ten-post or multi-candidate loop.
    assert len(cuts(state, "global_cap=1")) == 1  # The second Hot10 candidate is held visibly.


def test_hot10_without_qualified_provenance_is_held_before_any_writer(world, monkeypatch):
    # Rows without adapter evidence or attributable normals never become a bulletin.
    _leaderboard_inputs(monkeypatch)
    state = fresh_state()
    run: dict = {"id": "run-o3", "sources": []}
    hot10_mod.run_leaderboard(state, run)
    assert world.spies.calls == [] and state["drafts"] == []
    source = next(row for row in run["sources"] if row["source"] == "leaderboard")
    assert source["status"] == "degraded" and source["note"].startswith("hot10_short_slate: 0 of 10")


def test_both_mode_is_two_named_operations(world, monkeypatch):
    saved = []
    _leaderboard_inputs(monkeypatch)
    monkeypatch.setattr("src.state.read_state", lambda: fresh_state())
    monkeypatch.setattr("src.state.write_state", lambda state: saved.append(state) or True)
    monkeypatch.setattr(sys, "argv", ["src.main", "both"])
    importlib.import_module("src.main").main()
    # alerts (N=1) writes one candidate; the leaderboard is its own operation
    # (maximum 1) whose unqualified Hot10 slate is held before any writer call.
    assert len(world.spies.writer_events()) == 1 and not world.spies.writer_events()[0].startswith("hot10_")
    report = saved[-1]["run_history"][0]
    assert report["mode"] == "both" and report["drafted_count"] == 1


@pytest.mark.parametrize("flag", ["THEHEAT_FUNNEL_TELEMETRY", "THEHEAT_MULTISIGNAL_CONTEXT"])
def test_optional_capture_paths_add_no_source_or_model_calls(world, monkeypatch, flag):
    run_alerts(warning=True)
    baseline = (len(world.connects), list(world.fetches), list(world.spies.calls))
    assert baseline[0] > 0 and baseline[1] == ["firms"] and len(baseline[2]) == 4  # Meaningful counts.
    world.connects.clear(), world.fetches.clear(), world.spies.calls.clear()
    monkeypatch.setenv(flag, "1")
    run_alerts(warning=True)
    assert (len(world.connects), list(world.fetches), list(world.spies.calls)) == baseline
