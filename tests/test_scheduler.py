from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from src import state
from src.orchestrator import suppression
from src.orchestrator.scheduler import SourceRunner, run_stage1_sources, run_stage1_then_synthesis
from src.state import _fresh_state


def test_stage1_concurrent_stage2_after():
    order: list[str] = []
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "sources": []}

    run_stage1_then_synthesis(
        bot_state,
        current_run,
        serial_runners=[],
        concurrent_runners=[
            SourceRunner("source_a", lambda: order.append("source_a")),
            SourceRunner("source_b", lambda: order.append("source_b")),
        ],
        synthesis_runner=SourceRunner("synthesis_fire_drought_heat", lambda: order.append("synthesis")),
        budget_seconds=1,
    )

    assert order[-1] == "synthesis"
    assert set(order[:-1]) == {"source_a", "source_b"}


def test_runner_budget_timeout_records_failed():
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "sources": []}

    def slow_runner():
        time.sleep(0.05)

    run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=[],
        concurrent_runners=[SourceRunner("slow_source", slow_runner)],
        budget_seconds=0.01,
    )

    row = current_run["sources"][0]
    assert row["source"] == "slow_source"
    assert row["status"] == "failed"
    assert row["error"] == "budget exceeded (0.01s)"
    assert row["error_class"] == "timeout"
    assert bot_state["source_health"]["slow_source"]["runs"][-1]["error_class"] == "timeout"


def test_breaker_skips_after_3_timeouts():
    bot_state = _fresh_state()
    for ts in ("2026-06-12T00:00:00Z", "2026-06-12T01:00:00Z", "2026-06-12T02:00:00Z"):
        state.record_source_health(
            bot_state,
            "slow_source",
            "failed",
            "budget exceeded (120s)",
            timestamp=ts,
            error_class="timeout",
        )
    current_run = {"id": "run_1", "sources": []}
    ran = False

    def should_not_run():
        nonlocal ran
        ran = True

    run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=[],
        concurrent_runners=[SourceRunner("slow_source", should_not_run)],
        budget_seconds=1,
    )

    assert ran is False
    assert current_run["sources"][0]["status"] == "skipped"
    assert current_run["sources"][0]["breaker"] is True


def test_breaker_records_skipped_not_failed():
    bot_state = _fresh_state()
    # Anchor the failures to "now" rather than a frozen calendar date: the breaker
    # records its skip with a now() timestamp, which becomes the latest run and
    # pulls the 7-day source-health window cutoff forward. Hardcoded past dates
    # eventually fall outside that window and get pruned (failed -> 0), so this
    # test must stay relative to wall-clock time to keep asserting failed == 3.
    now = datetime.now(timezone.utc)
    recent = tuple(
        (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ") for h in (3, 2, 1)
    )
    for ts in recent:
        state.record_source_health(
            bot_state,
            "slow_source",
            "failed",
            "budget exceeded (120s)",
            timestamp=ts,
            error_class="timeout",
        )
    current_run = {"id": "run_1", "sources": []}

    run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=[],
        concurrent_runners=[SourceRunner("slow_source", lambda: None)],
        budget_seconds=1,
    )

    row = current_run["sources"][0]
    assert row["status"] == "skipped"
    assert row["error"] == "circuit breaker (cooldown 1 cycle)"
    assert bot_state["source_health"]["slow_source"]["skipped"] == 1
    assert bot_state["source_health"]["slow_source"]["failed"] == 3


def test_composite_runner_records_real_source_health_keys():
    bot_state = _fresh_state()
    for source in ("sea_ice_arctic", "sea_ice_antarctic"):
        for ts in ("2026-06-12T00:00:00Z", "2026-06-12T01:00:00Z", "2026-06-12T02:00:00Z"):
            state.record_source_health(
                bot_state,
                source,
                "failed",
                "budget exceeded (120s)",
                timestamp=ts,
                error_class="timeout",
            )
    current_run = {"id": "run_1", "sources": []}

    run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=[],
        concurrent_runners=[
            SourceRunner(
                "sea_ice",
                lambda: None,
                health_sources=("sea_ice_arctic", "sea_ice_antarctic"),
            )
        ],
        budget_seconds=1,
    )

    assert [row["source"] for row in current_run["sources"]] == [
        "sea_ice_arctic",
        "sea_ice_antarctic",
    ]
    assert "sea_ice" not in bot_state["source_health"]
    assert all(row["breaker"] is True for row in current_run["sources"])


def test_synthesis_component_writers_serialized():
    bot_state = _fresh_state()
    current_run = {"id": "run_1", "sources": []}
    active = 0
    max_active = 0
    lock = threading.Lock()
    order: list[str] = []

    def serial_runner(name: str):
        def run():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                order.append(f"start:{name}")
            time.sleep(0.01)
            with lock:
                order.append(f"end:{name}")
                active -= 1
        return run

    run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=[
            SourceRunner("open_meteo_extreme_signals", serial_runner("open_meteo")),
            SourceRunner("firms", serial_runner("firms")),
            SourceRunner("drought", serial_runner("drought")),
        ],
        concurrent_runners=[],
        budget_seconds=1,
    )

    assert max_active == 1
    assert order == [
        "start:open_meteo",
        "end:open_meteo",
        "start:firms",
        "end:firms",
        "start:drought",
        "end:drought",
    ]


def test_flag_off_runs_sequential_legacy(monkeypatch):
    import importlib

    alerts_mod = importlib.import_module("src.orchestrator.run_alerts")

    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "0")
    monkeypatch.setattr(alerts_mod, "run_stage1_then_synthesis", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scheduler should be off")), raising=False)
    monkeypatch.setattr(alerts_mod.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts_mod, "cities_to_state_map", lambda cities: {})
    order: list[str] = []

    for name in (
        "run_extreme_signals",
        "run_firms",
        "run_fire_footprint",
        "run_co2",
        "run_methane",
        "run_nws_alerts",
        "run_gdacs",
        "run_copernicus_ems",
        "run_sea_ice",
        "run_drought",
        "run_enso",
        "run_climate_indices",
        "run_ocean",
        "run_ocean_sst",
        "run_ocean_sst_anomaly",
        "run_air_quality",
        "run_coral_dhw",
        "run_water_levels",
        "run_river_gauges",
        "run_ice_mass",
        "run_gpm_imerg",
        "run_nsidc_snow",
        "run_ozone_hole",
        "run_reanalysis_anomaly",
        "run_synthesis",
    ):
        monkeypatch.setattr(alerts_mod, name, lambda *args, _name=name, **kwargs: order.append(_name))
    monkeypatch.setattr(alerts_mod, "_process_cyclone_source", lambda *args, **kwargs: order.append("_process_cyclone_source"))
    monkeypatch.setattr(alerts_mod, "_drain_and_write_triage_queue", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        alerts_mod,
        "_prune_weakest_cycle_drafts",
        lambda bot_state, drafts_before, current_run, drafted, **kwargs: drafted,
    )

    alerts_mod.run_alerts(_fresh_state(), current_run={"id": "run_1", "sources": []})

    assert order[:3] == ["run_extreme_signals", "run_firms", "run_fire_footprint"]
    assert order[-1] == "run_synthesis"


def test_flag_on_dispatches_scheduler(monkeypatch):
    import importlib

    alerts_mod = importlib.import_module("src.orchestrator.run_alerts")

    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "1")
    monkeypatch.setattr(alerts_mod.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts_mod, "cities_to_state_map", lambda cities: {})
    seen: dict[str, object] = {}

    def record_scheduler(bot_state, current_run, *, serial_runners, concurrent_runners, synthesis_runner):
        seen["serial"] = [runner.source for runner in serial_runners]
        seen["concurrent"] = [runner.source for runner in concurrent_runners]
        seen["synthesis"] = synthesis_runner.source

    monkeypatch.setattr(alerts_mod, "run_stage1_then_synthesis", record_scheduler)
    monkeypatch.setattr(alerts_mod, "_drain_and_write_triage_queue", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        alerts_mod,
        "_prune_weakest_cycle_drafts",
        lambda bot_state, drafts_before, current_run, drafted, **kwargs: drafted,
    )

    alerts_mod.run_alerts(_fresh_state(), current_run={"id": "run_1", "sources": []})

    assert seen["serial"] == ["open_meteo_extreme_signals", "firms", "drought"]
    assert "ch4_milestone" in seen["concurrent"]
    assert "fire_footprint" in seen["concurrent"]
    assert "water_levels" in seen["concurrent"]
    assert "ocean" in seen["concurrent"]
    assert seen["synthesis"] == "synthesis_fire_drought_heat"


def test_suppression_context_is_thread_local():
    barrier = threading.Barrier(2)
    seen: dict[str, str | None] = {}

    def worker(source: str):
        with suppression._suppression_context(_fresh_state(), source=source, run_id="run_1"):
            barrier.wait()
            seen[source] = (suppression._current_suppression_ctx() or {}).get("source")

    threads = [threading.Thread(target=worker, args=(source,)) for source in ("source_a", "source_b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert seen == {"source_a": "source_a", "source_b": "source_b"}
