"""Invented CO-OPS responses through acquisition, detection and real admission."""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from freezegun import freeze_time

from src.data import water_levels as wl
from src.data.source_status import SourceFetchError
from src.editorial.observed_scope import story_hold
from src.two_bot.intern import build_storm_surge_bundle
from src.two_bot.strict_contract import bundle_schema_issues

NOW = datetime(2026, 11, 13, 7, 30, tzinfo=UTC)
STATION = ("8518750", "Invented Gauge", "NY")


def payloads():
    return (
        {
            "metadata": {"id": STATION[0]},
            "data": [
                {"t": "2026-11-13 07:18", "v": "2.100", "q": "p", "f": "0,0,0,0"},
                {"t": "2026-11-13 07:24", "v": "3.100", "q": "p", "f": "0,0,0,0"},
            ],
        },
        {
            "predictions": [
                {"t": "2026-11-13 07:24", "v": "1.0"},
                {"t": "2026-11-13 07:30", "v": "0.5"},
            ]
        },
    )


def install(monkeypatch, observed, predicted):
    monkeypatch.setattr(wl, "STATIONS", [STATION])
    responses.add(responses.GET, wl.COOPS_URL, json=observed)
    responses.add(responses.GET, wl.COOPS_URL, json=predicted)


@responses.activate
def test_exact_observation_comparison_quality_and_byte_receipts_reach_admission(
    monkeypatch, fresh_state
):
    from src.orchestrator.sources import co_ops

    observed, predicted = payloads()
    install(monkeypatch, observed, predicted)
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    run = {"id": "invented-coastal-run", "sources": []}
    with freeze_time(NOW):
        co_ops.run_water_levels(fresh_state, run)
    candidate = fresh_state["_triage_queue"][0]
    bundle = candidate.bundle
    evidence = bundle.raw_signal_dump["evidence"]
    assert evidence["observed_m"] == 3.1 and evidence["predicted_tide_m"] == 1
    assert bundle.headline_metric["value"] == 2.1
    assert bundle.when == evidence["valid_time"] == "2026-11-13T07:24:00Z"
    assert evidence["prediction_valid_time"] == bundle.when
    assert evidence["quality"] == "p" and evidence["datum"] == "MLLW"
    assert bundle.raw_signal_dump["station_id"] == STATION[0]
    assert (
        evidence["observed_response_sha256"]
        == sha256(responses.calls[0].response.content).hexdigest()
    )
    assert (
        evidence["prediction_response_sha256"]
        == sha256(responses.calls[1].response.content).hexdigest()
    )
    assert bundle_schema_issues(bundle) == [] and story_hold(bundle) is None
    assert run["sources"][0]["promoted"] == 1
    assert "no storm cause, flood impact or historical-record claim" in evidence["claim_scope"]
    for call, product in zip(responses.calls, ("water_level", "predictions")):
        params = parse_qs(urlsplit(call.request.url).query)
        assert params["station"] == [STATION[0]] and params["datum"] == ["MLLW"]
        assert params["units"] == ["metric"] and params["time_zone"] == ["gmt"]
        assert params["product"] == [product]
    assert parse_qs(urlsplit(responses.calls[1].request.url).query)["interval"] == ["6"]


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", True, {}, []])
@responses.activate
def test_missing_or_nonfinite_latest_value_never_falls_back_or_fabricates_zero(monkeypatch, value):
    observed, predicted = payloads()
    observed["data"][-1]["v"] = value
    install(monkeypatch, observed, predicted)
    with freeze_time(NOW), pytest.raises(SourceFetchError):
        wl.fetch_water_levels(strict=True)


@pytest.mark.parametrize("change", ["missing", "mismatch", "conflict", "nan"])
@responses.activate
def test_comparison_must_exist_at_the_exact_observation_time(monkeypatch, change):
    observed, predicted = payloads()
    if change == "missing":
        predicted["predictions"] = []
    elif change == "mismatch":
        predicted["predictions"] = predicted["predictions"][1:]
    elif change == "conflict":
        predicted["predictions"].append({"t": "2026-11-13 07:24", "v": "1.1"})
    else:
        predicted["predictions"][0]["v"] = "NaN"
    install(monkeypatch, observed, predicted)
    with freeze_time(NOW), pytest.raises(SourceFetchError):
        wl.fetch_water_levels(strict=True)


@pytest.mark.parametrize(
    "quality,flags,allowed",
    [
        ("p", "2,0,0,0", True),
        ("v", "0,0,0,0", True),
        ("v", "1,0,0,0", False),
        ("p", "0,1,0,0", False),
        ("p", "0,0,1,0", False),
        ("p", "0,0,0,1", False),
        (None, "0,0,0,0", False),
        ("x", "0,0,0,0", False),
        ("p", None, False),
        ("p", "0,0", False),
        ("p", "x,0,0,0", False),
    ],
)
@responses.activate
def test_preliminary_status_and_outlier_count_differ_from_failed_flags(
    monkeypatch, quality, flags, allowed
):
    observed, predicted = payloads()
    observed["data"][-1].update(q=quality, f=flags)
    install(monkeypatch, observed, predicted)
    with freeze_time(NOW):
        if allowed:
            assert wl.fetch_water_levels(strict=True)[0].evidence["quality"] == quality
        else:
            with pytest.raises(SourceFetchError):
                wl.fetch_water_levels(strict=True)


@pytest.mark.parametrize("change", ["old", "future", "missing-time", "wrong-station", "conflict"])
@responses.activate
def test_invalid_identity_time_or_conflicting_latest_row_is_withheld(monkeypatch, change):
    observed, predicted = payloads()
    if change == "old":
        observed["data"] = [{**observed["data"][-1], "t": "2026-11-12 23:00"}]
    elif change == "future":
        observed["data"][-1]["t"] = "2026-11-13 08:00"
    elif change == "missing-time":
        observed["data"][-1].pop("t")
    elif change == "wrong-station":
        observed["metadata"]["id"] = "0000000"
    else:
        observed["data"].append({**observed["data"][-1], "v": "4"})
    install(monkeypatch, observed, predicted)
    with freeze_time(NOW), pytest.raises(SourceFetchError):
        wl.fetch_water_levels(strict=True)


@responses.activate
def test_detector_copies_provenance_and_uses_observation_day_across_midnight(monkeypatch):
    observed, predicted = payloads()
    observed["data"] = [{**observed["data"][-1], "t": "2026-11-13 23:54"}]
    predicted["predictions"] = [{"t": "2026-11-13 23:54", "v": "1.0"}]
    install(monkeypatch, observed, predicted)
    with freeze_time(datetime(2026, 11, 14, 0, 3, tzinfo=UTC)):
        reading = wl.fetch_water_levels(strict=True)[0]
    event = wl.detect_storm_surge([reading])[0]
    assert event.station_id == STATION[0] and event.evidence == reading.evidence
    reading.evidence["quality"] = "changed"
    assert event.evidence["quality"] == "p"
    assert event.date == "2026-11-13"
    assert build_storm_surge_bundle(event).when == "2026-11-13T23:54:00Z"


@responses.activate
def test_one_failed_station_is_contained_and_reported_as_partial(monkeypatch, fresh_state):
    from src.orchestrator.sources import co_ops

    observed, predicted = payloads()
    bad = deepcopy(observed)
    bad["metadata"]["id"] = "wrong"
    monkeypatch.setattr(wl, "STATIONS", [("0000000", "Invented held gauge", ""), STATION])
    for value in (bad, predicted, observed, predicted):
        responses.add(responses.GET, wl.COOPS_URL, json=value)
    run = {"sources": []}
    with freeze_time(NOW):
        co_ops.run_water_levels(fresh_state, run)
    assert len(fresh_state["_triage_queue"]) == 1
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == row["promoted"] == 1
    assert row["details"]["coastal_observations"] == {
        "stations_requested": 2,
        "stations_qualified": 1,
        "stations_withheld": 1,
    }


@responses.activate
def test_explicit_zero_height_is_data_not_a_missing_value(monkeypatch):
    observed, predicted = payloads()
    observed["data"][-1]["v"] = "0"
    install(monkeypatch, observed, predicted)
    with freeze_time(NOW):
        reading = wl.fetch_water_levels(strict=True)[0]
    assert reading.observed_m == 0 and reading.anomaly_m == -1


@responses.activate
def test_real_admission_and_required_checks_save_manual_draft_without_auto_authority(
    monkeypatch, fresh_state
):
    from src.orchestrator.sources import co_ops
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue
    from src.orchestrator.candidate_budget import CandidateBudget
    from src.two_bot import pipeline
    from src.voice import safety
    from tests.nhc_advisory_pipeline_helpers import stage_fakes

    observed, predicted = payloads()
    install(monkeypatch, observed, predicted)
    for key, value in {
        "ANTHROPIC_API_KEY": "invented-no-access",
        "GEMINI_API_KEY": "invented-no-access",
        "THEHEAT_OBSERVED_WEATHER_ONLY": "1",
        "THEHEAT_CRITIC_ENABLED": "1",
        "THEHEAT_CRITIC_REVISE_ENABLED": "0",
        "THEHEAT_WRITER_SAMPLES": "1",
        "THEHEAT_TRIAGE_ENABLED": "0",
        "THEHEAT_REFILL_ENABLED": "0",
        "THEHEAT_AUTOMATIC_SELECTION_ONLY": "0",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1",
        "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-no-access")
    stages_called = []
    text = "Water at Invented Gauge was 2.1 m above the tide prediction at 07:24 UTC, in NOAA’s preliminary reading."
    stages = stage_fakes(stages_called, copy=text)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety.run_safety_pipeline)
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    run = {"id": "invented-coastal-checked-run", "mode": "alerts", "sources": []}
    with freeze_time(NOW, tick=True):
        co_ops.run_water_levels(fresh_state, run)
        _drain_and_write_triage_queue(
            fresh_state, run, candidate_budget=CandidateBudget(operation="alerts", limit=1)
        )
    assert stages_called == ["writer", "safety", "fact_check", "critic"], fresh_state.get(
        "suppressions"
    )
    draft = fresh_state["drafts"][0]
    assert draft["text"] == text and draft["status"] == "pending"
    assert draft["review_binding"]["kind"] == "model"
    assert not draft.get("auto_approve_at") and draft.get("approval_mode") == "manual"
    assert (
        draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["quality"]
        == "p"
    )
