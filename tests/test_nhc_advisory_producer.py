"""Producer wiring: configured NHC advisory -> runner -> queue -> real chain -> pending draft."""
from copy import deepcopy
import importlib
import json

import pytest

from src.data import nhc_advisory as source
from src.editorial.revisions import approval_is_current, review_is_current
from src.orchestrator.sources import nhc_advisory as runner
from src.state import DEFAULT_STATE
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_pipeline_helpers import COPY, Transport, generate

PAIR = [source.INDEX_URL, h.URL]


def test_absent_configuration_invokes_nothing(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(source, "_http_get", transport)
    for name in ("THEHEAT_NHC_ADVISORY_ACQUISITION", "THEHEAT_NHC_ADVISORY_NOMINATION"):
        monkeypatch.delenv(name, raising=False)
    state, run = deepcopy(DEFAULT_STATE), {"sources": []}
    assert runner.run_nhc_advisory(state, run) == {"status": "absent", "promoted": 0}
    monkeypatch.setenv("THEHEAT_NHC_ADVISORY_NOMINATION", json.dumps(h.nominated()))  # Nomination alone is inert.
    monkeypatch.setenv("THEHEAT_NHC_ADVISORY_ACQUISITION", "true")
    assert runner.run_nhc_advisory(state, run) == {"status": "absent", "promoted": 0}
    assert transport.calls == [] and run == {"sources": []} and "_triage_queue" not in state


@pytest.mark.parametrize("enabled", [False, True])
def test_run_alerts_invokes_the_runner_only_when_opted_in(monkeypatch, enabled):
    alerts = importlib.import_module("src.orchestrator.run_alerts")
    monkeypatch.setattr(alerts.open_meteo, "load_cities", lambda: [])
    monkeypatch.setattr(alerts, "cities_to_state_map", lambda cities: {})
    for name in ("run_extreme_signals", "run_firms", "run_fire_footprint", "run_co2", "run_methane",
                 "run_nws_alerts", "run_gdacs", "run_usgs_quakes", "run_copernicus_ems", "_process_cyclone_source",
                 "run_sea_ice", "run_drought", "run_enso", "run_climate_indices", "run_ocean", "run_ocean_sst",
                 "run_ocean_sst_anomaly", "run_air_quality", "run_coral_dhw", "run_water_levels", "run_river_gauges",
                 "run_ice_mass", "run_gpm_imerg", "run_nsidc_snow", "run_ozone_hole", "run_reanalysis_anomaly",
                 "run_synthesis"):
        monkeypatch.setattr(alerts, name, lambda *args, **kwargs: 1)
    calls = []
    monkeypatch.setattr(runner, "run_nhc_advisory_source", lambda state, run: calls.append(run))
    monkeypatch.delenv("THEHEAT_NHC_ADVISORY_ACQUISITION", raising=False)
    if enabled:
        monkeypatch.setenv("THEHEAT_NHC_ADVISORY_ACQUISITION", "1")
    alerts.run_alerts(deepcopy(DEFAULT_STATE), current_run={"sources": []})
    assert len(calls) == int(enabled)


def test_configured_source_reaches_an_ordinary_pending_manual_draft(monkeypatch):
    transport = Transport()
    state, seen = generate(monkeypatch, transport)
    assert seen["result"] == {"status": "queued", "promoted": 1} and seen["drafted"] == 1
    assert seen["sent"] == ["writer", "safety", "fact_check", "critic"] and seen["calls"] == [1, 1, 1, 1]
    # Runner read + one live re-read at each of the four provider attempts + admission.
    assert seen["requests"] == 12 and transport.calls == PAIR * 6
    (draft,) = state["drafts"]
    assert (draft["type"], draft["status"], draft["approval_mode"], draft["approval_policy"]["mode"]) == (
        "nhc_advisory", "pending", "manual", "manual_only")
    assert draft["approval_policy"]["can_auto_approve"] is False and draft["text"].startswith(COPY)
    # Only the pipeline's model-check binding exists; no human review or approval is created.
    assert review_is_current(draft) and draft["review_binding"]["kind"] == "model"
    assert not approval_is_current(draft, "manual") and "approval_binding" not in draft
    bundle = draft["review_context"]["two_bot"]["bundle"]
    assert bundle["signal_kind"] == "nhc_advisory" and bundle["event_id"] == draft["event_id"]
    assert "expir" not in json.dumps(bundle["current_facts"]).lower()
    (row,) = seen["run"]["sources"][:1]
    assert row["source"] == "nhc_advisory" and row["status"] == "success"
    assert row["details"] == {"requests_used": 2, "storm_id": "EP492026", "advisory": "34", "hazard": "RAINFALL"}


def test_a_transient_provider_failure_retries_with_its_own_fresh_read(monkeypatch):
    transport = Transport()
    state, seen = generate(monkeypatch, transport, failures={"writer": 1})
    assert seen["sent"] == ["writer", "writer", "safety", "fact_check", "critic"] and len(state["drafts"]) == 1
    assert seen["requests"] == 14  # The retry is a separate provider attempt with its own current read.


def test_a_correction_after_the_writer_response_purchases_nothing_more(monkeypatch):
    pages = iter([h.page()] * 2)  # Runner read and the writer attempt see the original.

    def corrected():
        return (200, {}, next(pages, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4")))))
    transport = Transport({h.URL: corrected})
    state, seen = generate(monkeypatch, transport)
    assert seen["sent"] == ["writer"] and state["drafts"] == []


@pytest.mark.parametrize("index_bytes,code", [
    (h.index(advisory="35"), "nhc_advisory_superseded"), (h.index(storms=[]), "nhc_advisory_storm_not_current"),
], ids=["superseded", "removed"])
def test_superseded_or_removed_storm_holds_before_any_purchase(monkeypatch, index_bytes, code):
    transport = Transport({source.INDEX_URL: (200, {}, index_bytes)})
    state, seen = generate(monkeypatch, transport)
    assert seen["sent"] == [] and state["drafts"] == [] and seen["result"]["reason"] == code
    assert seen["run"]["sources"][0]["note"] == code and transport.calls == PAIR  # One bounded read only.


def test_copy_without_attribution_or_place_holds_before_paid_safety(monkeypatch):
    state, seen = generate(monkeypatch, Transport(), copy="Rain could trigger flash flooding tonight.")
    assert seen["sent"] == ["writer"] and state["drafts"] == []


def test_exhausted_request_budget_holds_instead_of_buying_more(monkeypatch):
    state, seen = generate(monkeypatch, Transport(), request_limit=6)
    assert seen["sent"] == ["writer", "safety"] and state["drafts"] == [] and seen["requests"] == 6


def test_generation_pause_holds_before_reading(monkeypatch):
    from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope
    from tests.nhc_advisory_pipeline_helpers import configure
    transport = Transport()
    configure(monkeypatch, transport)
    monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1")
    state, run = deepcopy(DEFAULT_STATE), {"sources": []}
    with advisory_owner_scope(AdvisoryOwner(clock=lambda: h.NOW)):
        assert runner.run_nhc_advisory(state, run)["reason"] == "nhc_advisory_generation_paused"
    assert transport.calls == []


def test_missing_owner_holds_without_reading(monkeypatch):
    from tests.nhc_advisory_pipeline_helpers import configure
    transport = Transport()
    configure(monkeypatch, transport)
    state, run = deepcopy(DEFAULT_STATE), {"sources": []}
    assert runner.run_nhc_advisory(state, run)["reason"] == "nhc_advisory_current_source_unavailable"
    assert transport.calls == []


def test_repeat_reuses_and_a_changed_source_revokes_the_pending_draft(monkeypatch):
    state, _ = generate(monkeypatch, Transport())
    again, seen = generate(monkeypatch, Transport(), state=state)
    assert seen["result"] == {"status": "reused", "promoted": 0} and len(again["drafts"]) == 1
    changed = Transport({h.URL: (200, {}, h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4"))))})
    held, seen = generate(monkeypatch, changed, state=again)
    (draft,) = held["drafts"]
    assert seen["result"] == {"status": "held", "reason": "nhc_advisory_current_source_changed", "promoted": 0}
    assert seen["sent"] == [] and draft["status"] == "pending" and "approval_binding" not in draft
    assert draft["review_context"]["nhc_advisory_source_hold"] == "nhc_advisory_current_source_changed"
    assert draft["post_error"] == "The NHC advisory changed; fresh source review is required."
