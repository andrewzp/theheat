"""Invented WFIGS records through the actual parser, admission and manual writer.

No provenance/check/approval guard is replaced. HTTP and model replies are
explicit offline fixtures, never provider truth, quality or publication proof.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

from freezegun import freeze_time
import pytest
import requests

from src.data import fire_footprint as source
from src.data.source_status import SourceFetchError
from src.editorial.approval import recommend_approval_policy
from src.orchestrator.sources import nifc
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.two_bot import pipeline
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.fire import build_fire_footprint_bundle
from src.voice import safety
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_awc_observed import NOW
from tests.test_awc_observed_automatic import world as world

MODIFIED = NOW - timedelta(hours=18)
COPY = "NIFC lists Juniper Fire in Oregon at about 800,000 acres in its November 14 update."


def record(**changes):
    attrs = {
        "UniqueFireIdentifier": "2026-OR-EXAMPLE-001", "IrwinID": "{invented-incident-1}",
        "IncidentName": "Juniper Fire", "CpxName": "Different Umbrella Complex",
        "IsCpxChild": 0, "IncidentTypeCategory": "WF", "ActiveFireCandidate": 1,
        "IncidentSize": 800000.0, "POOState": "US-OR",
        "FireDiscoveryDateTime": int((NOW-timedelta(days=2)).timestamp()*1000),
        "ModifiedOnDateTime_dt": int(MODIFIED.timestamp()*1000),
    }
    attrs.update(changes)
    return {"attributes": attrs}


@pytest.fixture
def capture(monkeypatch):
    settings = {"payload": {"features": [record()]}, "calls": [], "wire": None}

    def fetch(url, **kwargs):
        settings["calls"].append((url, kwargs))
        response = requests.Response()
        response.status_code, response.url = 200, url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(settings["payload"]).encode()
        response.request = requests.Request("GET", url).prepare()
        settings["wire"] = response.content
        return response

    monkeypatch.setattr(source, "fetch_with_retry", fetch)
    return settings


def acquire(capture):
    with freeze_time(NOW):
        return source.fetch_active_fire_perimeters(strict=True)


def test_request_uses_documented_current_clock_field_without_redirects(capture):
    acquire(capture)
    url, options = capture["calls"][0]
    fields = parse_qs(urlsplit(url).query)["outFields"][0].split(",")
    assert "ModifiedOnDateTime_dt" in fields and "ModifiedOnDateTime" not in fields
    assert options["allow_redirects"] is False
    assert len(capture["calls"]) == 1


@pytest.mark.parametrize("payload", [{"error": {"code": 400, "message": "Invented invalid field"}}, {}])
def test_service_error_or_missing_envelope_is_not_a_successful_empty_feed(capture, payload):
    capture["payload"] = payload
    with pytest.raises(SourceFetchError):
        acquire(capture)


def test_actual_parsed_capture_supplies_qualified_report_and_separate_clocks(capture):
    fc, = acquire(capture)
    with freeze_time(NOW+timedelta(days=1)):
        bundle = build_fire_footprint_bundle(fc)
    assert audit_story_bundle(bundle).prompt_ready
    assert bundle.when == MODIFIED.date().isoformat(), "A later view is not the report's measurement date"
    evidence = bundle.raw_signal_dump["evidence"]
    assert evidence["source_payload_sha256"] == hashlib.sha256(capture["wire"]).hexdigest()
    assert evidence["measurement_interval_known"] is False
    assert evidence["source_record"]["IncidentSize"] == 800000.0
    assert evidence["record_modified_at"].startswith(MODIFIED.date().isoformat())
    assert evidence["retrieved_at"].startswith(NOW.date().isoformat())
    assert bundle.country == "US"
    assert bundle.headline_metric == {"label": "reported_incident_area_acres", "value": 800000.0, "unit": "acres"}
    assert fc.name == "Juniper Fire", "An umbrella complex name cannot replace the named incident"


@pytest.mark.parametrize("stamp", [None, int((NOW+timedelta(days=1)).timestamp()*1000)])
def test_unknown_or_future_report_clock_cannot_borrow_discovery_or_retrieval(capture, stamp):
    capture["payload"] = {"features": [record(ModifiedOnDateTime_dt=stamp)]}
    assert acquire(capture) == []


def test_one_fresh_record_never_lends_freshness_to_an_old_incident(capture):
    old = record(UniqueFireIdentifier="old-incident", ModifiedOnDateTime_dt=int((NOW-timedelta(days=10)).timestamp()*1000))
    capture["payload"] = {"features": [old, record()]}
    rows = acquire(capture)
    assert [r.complex_id for r in rows] == ["2026-OR-EXAMPLE-001"]


@pytest.mark.parametrize("size", [float("inf"), float("nan"), -100.0, True])
def test_unusable_area_never_becomes_a_fire_candidate(capture, size):
    capture["payload"] = {"features": [record(IncidentSize=size)]}
    assert acquire(capture) == []


@pytest.mark.parametrize("state", ["CA-BC", "US-XX", None])
def test_unknown_or_foreign_region_never_becomes_an_assumed_us_incident(capture, state):
    capture["payload"] = {"features": [record(POOState=state)]}
    assert acquire(capture) == []


def test_packet_value_disagreement_is_held_by_the_real_builder_audit(capture):
    fc, = acquire(capture)
    fc.hectares += 50000
    with freeze_time(NOW):
        bundle = build_fire_footprint_bundle(fc)
    assert not audit_story_bundle(bundle).prompt_ready


def test_unnamed_incident_does_not_inherit_its_umbrella_name(capture):
    capture["payload"] = {"features": [record(IncidentName=None)]}
    fc, = acquire(capture)
    bundle = build_fire_footprint_bundle(fc)
    assert audit_story_bundle(bundle).prompt_ready
    assert next(f for f in bundle.current_facts if f["label"] == "incident_name")["value"] == "Unnamed incident"
    assert fc.name is None


@pytest.mark.parametrize("change", ["name", "date", "area", "origin", "record-value-rehashed"])
def test_source_packet_and_writing_facts_cannot_disagree_after_build(capture, change):
    fc, = acquire(capture)
    bundle = build_fire_footprint_bundle(fc)
    assert audit_story_bundle(bundle).prompt_ready
    if change == "name":
        next(f for f in bundle.current_facts if f["label"] == "incident_name")["value"] = "Different Umbrella Complex"
    elif change == "date":
        bundle.when = NOW.date().isoformat()
    elif change == "area":
        next(f for f in bundle.current_facts if f["label"] == "area_acres_approx")["value"] *= 2
    elif change == "origin":
        bundle.raw_signal_dump["evidence"]["source_url"] = "https://example.invalid/"
    else:
        packet = bundle.raw_signal_dump["evidence"]
        packet["source_record"]["IncidentSize"] *= 2
        packet["source_record_sha256"] = hashlib.sha256(json.dumps(
            packet["source_record"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
    assert not audit_story_bundle(bundle).prompt_ready


def test_direct_report_policy_stays_manual_even_with_high_copy_scores():
    policy = recommend_approval_policy(source.KIND, signal_total=100, candidate_score={"total": 100})
    assert policy.mode == "manual_only" and not policy.can_auto_approve
    assert policy.recommended_delay_minutes is None


@pytest.mark.parametrize("change", ["historical_context", "country"])
def test_changed_source_owned_context_stops_before_queue_and_paid_writer(monkeypatch, world, capture, change):
    transport, state, run, calls, _ = world
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    run.update(mode="alerts", id="invented-nifc-review-repair")
    stages = stage_fakes(calls, copy=COPY)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    original_admission = nifc._enqueue_story_candidate
    seen = []

    def changed_context(*args, **kwargs):
        bundle = kwargs["bundle"]
        assert audit_story_bundle(bundle).prompt_ready
        if change == "country":
            bundle.country = "CA"
        else:
            bundle.historical_context = {"previous_record_acres": 1000, "claim": "Largest fire in 100 years"}
        seen.append(audit_story_bundle(bundle).prompt_ready)
        return original_admission(*args, **kwargs)

    monkeypatch.setattr(nifc, "_enqueue_story_candidate", changed_context)
    with freeze_time(NOW, tick=True):
        nifc.run_fire_footprint(state, run)
        _drain_and_write_triage_queue(state, run)
    assert seen == [False], "Unsupported source identity/history must fail the real audit"
    assert calls == [] and state["drafts"] == [] and transport.x_posts == []
    assert state.get("_triage_queue", []) == []
    assert run["sources"][-1]["promoted"] == 0
    assert run["sources"][-1]["details"]["admission_holds"] == 1


@pytest.mark.parametrize("scheduled", [False, True], ids=["operator-manual-draft", "ordinary-automatic-hold"])
def test_real_runner_admission_checks_and_save_keep_manual_only_policy(monkeypatch, world, capture, scheduled):
    transport, state, run, calls, _ = world
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule" if scheduled else "workflow_dispatch")
    run.update(mode="alerts", id="invented-nifc-report-run")
    stages = stage_fakes(calls, copy=COPY)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    with freeze_time(NOW, tick=True):
        nifc.run_fire_footprint(state, run)
        assert len(state.get("_triage_queue", [])) == 1
        assert run["sources"][-1]["promoted"] == 1
        _drain_and_write_triage_queue(state, run)
    assert transport.x_posts == []
    if scheduled:
        assert calls == [] and state["drafts"] == []
    else:
        assert calls == ["writer", "safety", "fact_check", "critic"]
        draft, = state["drafts"]
        assert draft["text"] == COPY
        assert draft["status"] == "pending" and draft["approval_mode"] == "manual"
        assert not draft.get("approval_binding") and not draft.get("auto_publish_at")
        assert draft["review_binding"]["kind"] == "model"
        assert draft["review_context"]["two_bot"]["bundle"]["when"] == MODIFIED.date().isoformat()
        saved = deepcopy(state)
        with freeze_time(NOW, tick=True):
            nifc.run_fire_footprint(state, run)
        assert state["drafts"] == saved["drafts"]
        assert state.get("publish_ledger") == saved.get("publish_ledger")
        assert len(capture["calls"]) == 1 and len(calls) == 4


def test_failed_admission_is_not_reported_as_a_promotion(monkeypatch, fresh_state, capture):
    # The parsed record remains genuine to this invented capture. Deliberately
    # change its value before the builder; no audit is patched to make it pass.
    fc, = acquire(capture)
    fc.hectares += 50000
    monkeypatch.setattr(nifc, "_fetch_strict", lambda *args, **kwargs: [fc])
    run = {"sources": []}
    with freeze_time(NOW):
        nifc.run_fire_footprint(fresh_state, run)
    assert fresh_state.get("_triage_queue", []) == []
    assert run["sources"][-1]["promoted"] == 0
    assert run["sources"][-1]["status"] == "degraded"
    assert run["sources"][-1]["details"]["admission_holds"] == 1
