"""Invented NASA-shaped bytes through the real rainfall collector and queue.

No live weather, model or platform access. The first counterexample also runs
unchanged against the accepted base: the peak is outside its city sampling list.
"""
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
import io
import json

from freezegun import freeze_time
import h5py
import numpy as np
import pytest

from src.data import gpm_imerg as gpm
from src.orchestrator.sources import gpm_imerg as source
from tests import live_content_harness as h
from tests.test_rainfall_observed_report import NOW, enabled  # noqa: F401

PEAK_LON, PEAK_LAT = -50.05, -10.05  # Invented cell inside Brazil; not a city lookup.
COPY = ("Brazil: 190.5 mm of water-equivalent precipitation in 24 hours on 15 Nov "
        "in one grid cell, NASA satellites estimate.")


def nasa_frame(*, amount=190.5, count=48):
    buffer = io.BytesIO()
    shape = (1, gpm.LON_CELLS, gpm.LAT_CELLS)
    with h5py.File(buffer, "w") as handle:
        values = handle.create_dataset("precipitation", shape=shape, dtype="f4", fillvalue=0,
                                       chunks=(1, 100, 100), compression="gzip")
        values.attrs["units"] = "mm/day"
        counts = handle.create_dataset("precipitation_cnt", shape=shape, dtype="i1", fillvalue=48,
                                       chunks=(1, 100, 100), compression="gzip")
        point = (0, gpm._lon_index(PEAK_LON), gpm._lat_index(PEAK_LAT))
        values[point], counts[point] = amount, count
        longitude = handle.create_dataset("lon", data=(-179.95 + np.arange(gpm.LON_CELLS) * .1).astype("f4"))
        latitude = handle.create_dataset("lat", data=(-89.95 + np.arange(gpm.LAT_CELLS) * .1).astype("f4"))
        longitude.attrs["units"], latitude.attrs["units"] = "degrees_east", "degrees_north"
        day = NOW.replace(hour=0) - timedelta(days=1)
        time = handle.create_dataset("time", data=[day.timestamp()])
        time.attrs["units"] = "seconds since 1970-01-01 00:00:00 UTC"
        time.attrs["calendar"] = "gregorian"
    return buffer.getvalue()


class GridTransport(h.Transport):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        self.nasa_calls = []
        self.on_request = None
        self.failure = None

    def send(self, _adapter, request, **_options):
        if request.url.startswith(gpm.DATAPOOL_BASE):
            assert request.method == "GET"
            self.nasa_calls.append(request.url)
            if self.on_request:
                self.on_request(len(self.nasa_calls))
            if self.failure:
                return h._reply(request, self.failure, b"invented unavailable NASA frame")
            return h._reply(request, 200, self.payload)
        return super().send(_adapter, request, **_options)


@pytest.fixture
def grid_world(enabled, fresh_state):  # noqa: F811
    enabled.setenv("EARTHDATA_TOKEN", "invented-no-access")
    enabled.setenv("THEHEAT_GPM_SOURCE", "datapool")
    transport = GridTransport(nasa_frame())
    transport.install(enabled.setattr)
    paris = next(r for r in gpm.load_cities() if r["city"] == "Paris" and r["country"] == "France")
    run = {"id": "invented-grid-discovery", "mode": "alerts", "started_at": NOW.isoformat(), "sources": []}
    return transport, fresh_state, run, [paris]


def test_actual_collector_discovers_qualified_cell_outside_supplied_city_list(grid_world):
    transport, state, run, cities = grid_world
    original = deepcopy(cities)
    with freeze_time(NOW):
        source.run_gpm_imerg(state, run, cities)
    assert cities == original
    assert len(transport.nasa_calls) == 1, "discovery must share the existing daily download"
    candidates = state.get("_triage_queue", [])
    assert len(candidates) == 1, "the unmonitored inland peak must enter the actual ordinary queue"
    candidate = candidates[0]
    assert candidate.bundle.country == "BR"
    assert candidate.bundle.headline_metric["value"] == 190.5
    assert "Paris" not in candidate.bundle.where


@pytest.fixture
def ordinary_grid_world(grid_world, monkeypatch):
    from src.voice import safety

    transport, state, run, cities = grid_world
    for key, value in {**h.MODEL_ENV, "THEHEAT_AUTOMATIC_SELECTION_ONLY": "0",
                       "GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", h.INVENTED_TOKEN)
    monkeypatch.setattr(safety, "_SAFETY_CACHE", type(safety._SAFETY_CACHE)())
    models = h.ModelScript(copy=COPY)
    models.install(monkeypatch.setattr)
    module = import_module("src.orchestrator.run_alerts")
    for name in vars(module):
        if name.startswith("run_") and name not in {"run_alerts", "run_gpm_imerg", "run_stage1_then_synthesis"}:
            monkeypatch.setattr(module, name, lambda *a, **kw: None)
    monkeypatch.setattr(module, "_process_cyclone_source", lambda *a, **kw: None)
    monkeypatch.setattr(module.open_meteo, "load_cities", lambda: cities)
    return transport, state, run, models, module


def collect(world):
    _transport, state, run, _models, module = world
    with freeze_time(NOW, tick=True):
        return module.run_alerts(state, run)


def send(monkeypatch, world, at=NOW + timedelta(minutes=2)):
    from src.orchestrator import posting
    from src.posting import twitter

    transport, state, _run, _models, _module = world
    transport.gist = {"state.json": json.dumps(state)}
    monkeypatch.setattr("src.state.GIST_ID", h.GIST_ID)
    monkeypatch.setattr("src.state.GITHUB_TOKEN", h.INVENTED_TOKEN)
    for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(twitter, key, h.INVENTED_TOKEN)
    with freeze_time(at, tick=True):
        posting.process_due_drafts(state, {"sources": []})


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("triage", [False, True])
def test_actual_grid_through_real_writer_checks_save_and_fixture_x(monkeypatch, ordinary_grid_world, concurrent, triage):
    transport, state, run, models, _module = ordinary_grid_world
    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "1" if concurrent else "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    assert collect(ordinary_grid_world) is state
    assert models.stages() == ["writer", "safety", "fact_check", "critic"], state.get("suppressions")
    request = next(request for stage, request in models.requests if stage == "writer")
    actual_prompt = json.dumps(request["messages"])
    assert "Explicitly say 'one grid cell' within the supplied map region." in actual_prompt
    assert "Do not invent a nearby city or imply a region-wide total." in actual_prompt
    assert "Use 'near' before the place" not in actual_prompt
    assert "For this named-place report" not in actual_prompt
    [draft] = state["drafts"]
    assert draft["text"] == COPY + "\n" + gpm_public_url()
    assert len(draft["text"]) <= 200
    assert draft["approval_binding"]["mode"] == "auto" and draft["review_binding"]["kind"] == "model"
    assert len(transport.nasa_calls) == 3  # Existing collection, prewriter and preadmission boundaries.
    row = next(row for row in run["sources"] if row["source"] == "gpm_imerg")
    assert row["details"]["rainfall_grid_discovery"]["diagnostics"]["qualifying_tiles"] == 1
    send(monkeypatch, ordinary_grid_world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    send(monkeypatch, ordinary_grid_world, at=NOW + timedelta(minutes=4))
    assert transport.x_posts == [draft["text"]]


def gpm_public_url():
    from src.data.rainfall_observed import SOURCE_URL
    return SOURCE_URL


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("triage", [False, True])
@pytest.mark.parametrize("news_enabled", [False, True])
def test_multiple_same_region_reports_keep_canonical_evidence_with_context_enabled(
    monkeypatch, ordinary_grid_world, concurrent, triage, news_enabled,
):
    """Optional context must not invalidate two otherwise qualified source packets."""
    from src.data import rainfall_grid

    transport, state, _run, models, _module = ordinary_grid_world
    monkeypatch.setenv("THEHEAT_MULTISIGNAL_CONTEXT", "1")
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1" if news_enabled else "0")
    monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1" if news_enabled else "0")
    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "1" if concurrent else "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    buffer = io.BytesIO(transport.payload)
    with h5py.File(buffer, "r+") as handle:
        # Equal invented amounts keep either legitimate tie order compatible
        # with the one fixed model fixture; selection is not under test here.
        handle["precipitation"][0, 1300, 799] = 190.5
    transport.payload = buffer.getvalue()

    collect(ordinary_grid_world)

    assert models.stages() == ["writer", "safety", "fact_check", "critic"], state.get("suppressions")
    [draft] = state["drafts"]
    saved = draft["review_context"]["two_bot"]["bundle"]
    assert "related_signals" not in saved and "human_impact" not in saved
    assert rainfall_grid.validate_bundle(saved, now=NOW) == saved["raw_signal_dump"]["evidence"]
    assert len(transport.nasa_calls) == 3
    assert draft["approval_binding"]["mode"] == "auto"
    send(monkeypatch, ordinary_grid_world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    send(monkeypatch, ordinary_grid_world, at=NOW + timedelta(minutes=4))
    assert transport.x_posts == [draft["text"]]


@pytest.mark.parametrize("field", ["related_signals", "human_impact", "headline_metric", "country"])
def test_context_is_not_stripped_to_repair_an_already_changed_rainfall_packet(
    monkeypatch, ordinary_grid_world, field,
):
    from src.two_bot.types import RelatedSignal

    transport, state, _run, models, module = ordinary_grid_world
    monkeypatch.setenv("THEHEAT_MULTISIGNAL_CONTEXT", "1")
    original = module.run_gpm_imerg
    observed = []

    def changed_source(bot_state, current_run, cities):
        result = original(bot_state, current_run, cities)
        [candidate] = bot_state["_triage_queue"]
        packet = candidate.bundle
        if field == "related_signals":
            packet.related_signals = [RelatedSignal("invented-other", "invented", "elsewhere", packet.when,
                                                  {"value": 1}, "BR")]
        elif field == "human_impact":
            packet.human_impact = [{"claim": "Invented unsupported impact"}]
        elif field == "headline_metric":
            packet.headline_metric["value"] += 1
        else:
            packet.country = "FR"
        observed.append(deepcopy(packet.to_dict()))
        return result

    monkeypatch.setattr(module, "run_gpm_imerg", changed_source)
    collect(ordinary_grid_world)
    assert observed and models.stages() == []
    assert state["drafts"] == [] and transport.x_posts == []
    assert any("rainfall_bundle_changed" in reason
               for row in state.get("suppressions", []) for reason in row.get("reasons", []))


@pytest.mark.parametrize("boundary", ["before-writer", "before-admission", "before-send"])
def test_changed_actual_source_bytes_refuse_at_each_existing_live_boundary(monkeypatch, ordinary_grid_world, boundary):
    transport, state, _run, models, _module = ordinary_grid_world
    if boundary != "before-send":
        at = 2 if boundary == "before-writer" else 3
        transport.on_request = lambda n: setattr(transport, "payload", nasa_frame(amount=191)) if n == at else None
    collect(ordinary_grid_world)
    if boundary == "before-send":
        [draft] = state["drafts"]
        transport.payload = nasa_frame(amount=191)
        send(monkeypatch, ordinary_grid_world)
        assert draft["status"] != "posted"
    else:
        assert state["drafts"] == []
    assert models.stages() == ([] if boundary == "before-writer" else ["writer", "safety", "fact_check", "critic"])
    assert transport.x_posts == []


@pytest.mark.parametrize("boundary", ["before-writer", "before-admission", "before-send"])
def test_same_value_but_changed_file_provenance_does_not_reuse_a_previous_verdict(monkeypatch, ordinary_grid_world, boundary):
    transport, state, _run, models, _module = ordinary_grid_world
    # Even unrelated metadata changes change the retained full-file identity;
    # a matching numeric value alone is insufficient evidence agreement.
    import h5py
    buffer = io.BytesIO(transport.payload)
    with h5py.File(buffer, "r+") as handle:
        handle.attrs["invented_revision"] = "changed"
    revised = buffer.getvalue()
    if boundary != "before-send":
        at = 2 if boundary == "before-writer" else 3
        transport.on_request = lambda n: setattr(transport, "payload", revised) if n == at else None
    collect(ordinary_grid_world)
    if boundary == "before-send":
        assert len(state["drafts"]) == 1
        transport.payload = revised
        send(monkeypatch, ordinary_grid_world)
        assert state["drafts"][0]["status"] != "posted"
    else:
        assert state["drafts"] == []
    assert transport.x_posts == []


@pytest.mark.parametrize("script,expected", [
    ({"writer_kill": "invented style decline"}, ["writer"]),
    ({"safety": "YES"}, ["writer", "safety"]),
    ({"safety": "MAYBE"}, ["writer", "safety"]),
    ({"fact_passed": False}, ["writer", "safety", "fact_check"]),
    ({"critic": {"verdict": "KILL", "kill_reason": "weak_signal", "revise_instruction": None,
                 "selected_index": None}}, ["writer", "safety", "fact_check", "critic"]),
])
@pytest.mark.parametrize("triage", [False, True])
def test_sdk_refusals_never_buy_a_replacement_or_send(monkeypatch, ordinary_grid_world, script, expected, triage):
    transport, state, _run, models, _module = ordinary_grid_world
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    for name, value in script.items():
        setattr(models, name, value)
    # Three qualified source cells enter the same free slate; a paid kill
    # cannot lead to a replacement writer attempt, even with ranking disabled.
    buffer = io.BytesIO(transport.payload)
    with h5py.File(buffer, "r+") as handle:
        handle["precipitation"][0, 1289, 799] = 190.5
        handle["precipitation"][0, 1279, 799] = 190.5
    transport.payload = buffer.getvalue()
    collect(ordinary_grid_world)
    assert models.stages() == expected, state.get("suppressions")
    assert state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("change", ["text", "event", "kind", "proof", "flag", "checks", "expired", "unknown-send"])
def test_changed_or_unknown_delivery_never_reaches_x(monkeypatch, ordinary_grid_world, change):
    transport, state, _run, _models, _module = ordinary_grid_world
    collect(ordinary_grid_world)
    [draft] = state["drafts"]
    at = NOW + timedelta(minutes=2)
    if change == "text":
        draft["text"] = draft["text"].replace("190.5", "191")
    elif change == "event":
        draft["event_id"] += "-changed"
    elif change == "kind":
        draft["type"] = "all_time_high"
    elif change == "proof":
        draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["row"] += 1
    elif change == "flag":
        monkeypatch.setenv("THEHEAT_GPM_OBSERVED_REPORT", "0")
    elif change == "checks":
        draft.pop("review_binding")
    elif change == "expired":
        at = NOW + timedelta(hours=20)
    else:
        state["publish_ledger"][draft["event_id"]] = {"phase": "submitted", "submitted_at": NOW.isoformat()}
    send(monkeypatch, ordinary_grid_world, at=at)
    assert transport.x_posts == [] and draft["status"] != "posted"


@pytest.mark.parametrize("count", [None, 47])
def test_incomplete_frame_spends_nothing_and_cannot_turn_into_a_manual_fallback(ordinary_grid_world, count):
    transport, state, _run, models, _module = ordinary_grid_world
    transport.payload = nasa_frame(count=47 if count is None else count)
    if count is None:
        buffer = io.BytesIO(transport.payload)
        with h5py.File(buffer, "r+") as handle:
            del handle["precipitation_cnt"]
        transport.payload = buffer.getvalue()
    collect(ordinary_grid_world)
    assert len(transport.nasa_calls) == 1
    assert models.stages() == [] and state["drafts"] == [] and transport.x_posts == []


def test_observed_only_refusal_does_not_call_forecast_witness_or_buy_copy(ordinary_grid_world):
    transport, state, _run, models, _module = ordinary_grid_world
    transport.failure = 403
    collect(ordinary_grid_world)
    assert models.stages() == [] and state["drafts"] == [] and transport.x_posts == []
    assert not transport.forecasts and not transport.air_quality
