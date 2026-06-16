"""Phase A: drain + run_alerts funnel wiring.

Covers the flag-OFF zero-change guarantee and the flag-ON accumulation of
passes + shadow-slate capture, plus result_out threading through
_try_two_bot_draft.
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
        category=category, severity=80, novelty=80, timeliness=80, confidence=80,
        shareability=80, sensitivity=0, total=total, threshold=60, reasons=[],
    )


def _bundle(event_id: str = "evt", signal_kind: str = "coral_bleaching") -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind, where="Reef", when="2026-06-16", event_id=event_id,
        headline_metric={"label": "DHW", "value": 8}, current_facts=[],
    )


def _candidate(*, event_id: str, total: int = 80, source: str = "coral_dhw") -> TriageCandidateBundle:
    return TriageCandidateBundle(
        bundle=_bundle(event_id), score=_score(total), event_id=event_id, source=source,
        review_context={}, city="", tweet_date="2026-06-16", cooldown_exempt=False,
        legacy_type="coral_bleaching", created_at="2026-06-16T12:00:00Z",
    )


def test_drain_without_funnel_sink_does_not_touch_current_run_funnel(monkeypatch):
    """Flag-OFF path: drain produces no funnel artifacts (byte-for-byte today)."""
    from src.orchestrator import common

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [_candidate(event_id="e1")]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    def fake_try(bundle, state, score, **kwargs):
        return True

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    drafted = common._drain_and_write_triage_queue(bot_state, current_run)
    assert drafted == 1
    assert "funnel" not in current_run
    assert "shadow_slate" not in current_run


def test_drain_with_funnel_sink_records_passes_and_captures_slate(monkeypatch):
    from src.orchestrator import common, funnel

    bot_state = _fresh_state()
    bot_state["_triage_queue"] = [
        _candidate(event_id="hi", total=99),
        _candidate(event_id="lo", total=70),
    ]
    current_run = {"id": "r", "sources": [{"source": "coral_dhw", "drafted": 0}]}

    def fake_try(bundle, state, score, *, result_out=None, **kwargs):
        # First survivor drafts cleanly; mark all three stages passed.
        if result_out is not None:
            result_out["stage_outcomes"] = {"writer": "pass", "fact_check": "pass", "critic": "pass"}
        return True

    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)

    sink = funnel.new_funnel()
    drafted = common._drain_and_write_triage_queue(bot_state, current_run, funnel_sink=sink)

    assert drafted == 2
    assert sink["passes"] == {"writer": 2, "fact_check": 2, "critic": 2}
    # slate captured from the queue, highest score first
    assert [s["event_id"] for s in sink["_slate_skeleton"]] == ["hi", "lo"]


def test_select_survivors_records_triage_cap_kills_into_sink(monkeypatch):
    """The triage_cap suppression carries run_id=None, but the live kill counter
    must still credit it (codex P1-A) — exercised through the real select_survivors."""
    from src.orchestrator import funnel
    from src.orchestrator.triage import select_survivors

    monkeypatch.delenv("THEHEAT_PER_CATEGORY_CAP", raising=False)
    bot_state = _fresh_state()
    sink = funnel.new_funnel()
    funnel.attach_sink(bot_state, sink)
    # 5 same-category candidates; per-category cap (2) + global cap spill the rest.
    queue = [_candidate(event_id=f"c{i}", total=90 - i) for i in range(5)]
    survivors = select_survivors(bot_state, queue, global_cap=3)
    spilled = len(queue) - len(survivors)
    assert spilled > 0
    assert sink["kills"].get("triage_cap") == spilled


def test_try_two_bot_draft_surfaces_stage_outcomes(monkeypatch):
    import src.main as main
    from src.orchestrator import two_bot_dispatch

    # main.run_alerts() runs _sync_compat_globals(), a one-way raw setattr that
    # copies main's globals into the orchestrator modules. Tests that patch
    # main._try_two_bot_draft and run a cycle (e.g. test_copernicus_ems) leak
    # their fake into two_bot_dispatch._try_two_bot_draft permanently (the sync
    # is never reverted). main._try_two_bot_draft itself is monkeypatch-reverted
    # back to the real function, so restore the real one onto the dispatch module
    # before exercising it directly. (Pre-existing infra footgun — see PR notes.)
    monkeypatch.setattr(two_bot_dispatch, "_try_two_bot_draft", main._try_two_bot_draft)

    bot_state = _fresh_state()

    def fake_generate(bundle, state, result_out=None):
        if result_out is not None:
            result_out["stage_outcomes"] = {"writer": "pass", "fact_check": "pass", "critic": "kill"}
            result_out["kill_stage"] = "critic"
            result_out["kill_reason"] = "template convergence"
        return None  # critic killed → no draft

    monkeypatch.setattr("src.two_bot.pipeline.generate_draft", fake_generate)

    ro: dict = {}
    result = two_bot_dispatch._try_two_bot_draft(
        _bundle("e1"), bot_state, _score(),
        legacy_type="coral_bleaching", event_id="e1", review_context={}, result_out=ro,
    )
    assert result is False
    assert ro["stage_outcomes"] == {"writer": "pass", "fact_check": "pass", "critic": "kill"}
    assert ro["kill_stage"] == "critic"


def test_run_alerts_attaches_funnel_when_flag_on(monkeypatch):
    import importlib

    alerts_mod = importlib.import_module("src.orchestrator.run_alerts")

    monkeypatch.setenv("THEHEAT_FUNNEL_TELEMETRY", "1")
    monkeypatch.setattr(alerts_mod.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts_mod, "cities_to_state_map", lambda cities: {})
    for name in (
        "run_extreme_signals", "run_firms", "run_fire_footprint", "run_co2", "run_methane",
        "run_nws_alerts", "run_gdacs", "run_usgs_quakes", "run_copernicus_ems",
        "_process_cyclone_source", "run_sea_ice", "run_drought", "run_enso",
        "run_climate_indices", "run_ocean", "run_ocean_sst", "run_ocean_sst_anomaly",
        "run_air_quality", "run_coral_dhw", "run_water_levels", "run_river_gauges",
        "run_ice_mass", "run_gpm_imerg", "run_nsidc_snow", "run_ozone_hole",
        "run_reanalysis_anomaly", "run_synthesis",
    ):
        monkeypatch.setattr(alerts_mod, name, lambda *args, **kwargs: 1)

    current_run = {"id": "run_x", "sources": [{"source": "coral_dhw", "observed": 100,
                   "promoted": 5, "triaged_in": 3, "triaged_out": 2, "writer_attempted": 2, "drafted": 1}]}
    alerts_mod.run_alerts(_fresh_state(), current_run=current_run)
    assert "funnel" in current_run
    assert current_run["funnel"]["observed"] == 100
    assert "shadow_slate" in current_run


def test_run_alerts_no_funnel_when_flag_off(monkeypatch):
    import importlib

    alerts_mod = importlib.import_module("src.orchestrator.run_alerts")

    monkeypatch.delenv("THEHEAT_FUNNEL_TELEMETRY", raising=False)
    monkeypatch.setattr(alerts_mod.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts_mod, "cities_to_state_map", lambda cities: {})
    for name in (
        "run_extreme_signals", "run_firms", "run_fire_footprint", "run_co2", "run_methane",
        "run_nws_alerts", "run_gdacs", "run_usgs_quakes", "run_copernicus_ems",
        "_process_cyclone_source", "run_sea_ice", "run_drought", "run_enso",
        "run_climate_indices", "run_ocean", "run_ocean_sst", "run_ocean_sst_anomaly",
        "run_air_quality", "run_coral_dhw", "run_water_levels", "run_river_gauges",
        "run_ice_mass", "run_gpm_imerg", "run_nsidc_snow", "run_ozone_hole",
        "run_reanalysis_anomaly", "run_synthesis",
    ):
        monkeypatch.setattr(alerts_mod, name, lambda *args, **kwargs: 1)

    current_run = {"id": "run_x", "sources": []}
    alerts_mod.run_alerts(_fresh_state(), current_run=current_run)
    assert "funnel" not in current_run
    assert "shadow_slate" not in current_run
