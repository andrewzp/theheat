"""W15 coverage intake, production matching, metrics intake, route evaluation, corrections.

Every reference event, post, response and discrepancy here is invented; none is
an actual label, measurement, audience figure or correction.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from src.data import metric_intake
from src.evaluation import coverage as cov
from src.evaluation import correction_candidates, production_match, reference_intake, route_evaluation

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-20T12:00:00Z"
LATER = "2026-10-20T13:00:00Z"
SHA = "a" * 64


def event(event_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_id": event_id, "origin": "reference", "kind": "physical_event_candidate", "source_class": "observed",
        "hazards": [{"label": "Heat record", "evidence_sha256": SHA, "support": "invented station table"}],
        "regions": [{"label": "Fictionville, Utopia", "evidence_sha256": "b" * 64}],
        "event_start": "2026-10-10T00:00:00Z", "event_end": "2026-10-11T00:00:00Z", "issued_at": None,
        "published_at": None, "first_available_at": None, "label_source": "invented reviewer table",
        "uncertainty": "Invented: station siting unknown.", "exclusion": None}
    row.update(overrides)
    return row


def intake_doc(*events: dict, quiet: list | None = None, method: str = "invented_fixture") -> dict[str, Any]:
    return {"schema": reference_intake.SCHEMA, "set_id": "fixture-w15-set", "created_at": NOW,
            "selection": {"scope_label": "Invented W15 fixture", "method": method, "independent_of_bot_output": False,
                          "protocol_document_sha256": "c" * 64},
            "comparison_window": {"start": "2026-10-01", "end": "2026-10-19"},
            "events": list(events), "quiet_periods": quiet or []}


def state() -> dict[str, Any]:
    text = "Fictionville hit 49.1C, an invented all-time record for this fixture."
    return {
        "drafts": [
            {"id": "d_fiction_1", "event_id": "ghcn_fictionville_2026-10-10", "type": "heat_record", "city": "Fictionville",
             "country": "Utopia", "status": "posted", "created_at": "2026-10-10T18:00:00Z",
             "posted_at": "2026-10-10T19:00:00Z", "tweet_id": "1900000000000000001", "text": text},
            {"id": "d_other_place", "event_id": "ghcn_elsewhere_2026-10-10", "type": "heat_record", "city": "Elsewhere",
             "status": "pending", "created_at": "2026-10-10T18:30:00Z", "text": "Invented pending draft."},
        ],
        "publish_ledger": {"ghcn_fictionville_2026-10-10": {
            "phase": "confirmed", "tweet_id": "1900000000000000001", "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "confirmed_at": "2026-10-10T19:00:01Z"}},
        "suppressions": [
            {"id": "supp_flood_1", "ts": "2026-10-12T06:00:00Z", "stage": "fact_check", "category": "flood",
             "event_id": "gpm_atlantis_2026-10-12", "summary": "Invented Atlantis rainfall"},
            {"id": "supp_fire_1", "ts": "2026-10-13T06:00:00Z", "stage": "budget_exhausted", "category": "fire",
             "event_id": "firms_bigwood_2026-10-13", "summary": "Invented Bigwood fire"},
        ],
        "run_history": [{"run_id": "run_1", "ts": "2026-10-15T06:00:00Z",
                         "sources": [{"name": "gdacs_cyclone", "status": "error"}]}],
        "tweet_metrics": {},
    }


def record(*events: dict) -> dict:
    return reference_intake.intake(intake_doc(*events), retained_at=NOW)


# 15.1 -----------------------------------------------------------------------

def test_intake_builds_a_valid_reference_set_and_keeps_label_provenance_aside():
    rec = record(event("ref-heat-1"))
    document = rec["retained"]["wrapper"]["document"]
    assert cov.reference_set(document)["qualification"]["status"] == "not_qualified"
    assert rec["labels"]["ref-heat-1"]["label_source"] == "invented reviewer table"
    assert rec["labels"]["ref-heat-1"]["uncertainty"].startswith("Invented")
    assert rec["metrics"] == {"event_recall": None, "reason": "denominator_not_qualified"}
    assert reference_intake.retained_input(rec).value(cov.SET)["reference"] == rec["reference"]


def test_bot_discovered_and_historical_posts_are_not_reference_opportunities_and_exclusions_stay_listed():
    rec = record(event("ref-heat-1"), event("bot-found", origin="source_discovered"),
                 event("old-bad-post", origin="historical_post"), event("ref-excluded", exclusion="duplicate report"))
    units = rec["retained"]["wrapper"]["document"]["units"]
    assert [u["unit_id"] for u in units] == ["ref-heat-1"]
    assert {r["event_id"] for r in rec["not_reference_opportunities"]} == {"bot-found", "old-bad-post"}
    assert rec["excluded"] == [{"event_id": "ref-excluded", "reason": "duplicate report",
                                "label_source": "invented reviewer table"}]


def test_calendar_day_stays_calendar_and_quiet_periods_need_inventory_and_traces():
    quiet = [{"period_id": "quiet-1", "hazards": ["flood"], "regions": ["Atlantis"], "source_classes": ["observed"],
              "start": "2026-10-01T00:00:00Z", "end": "2026-10-05T00:00:00Z"},
             {"period_id": "quiet-2", "hazards": ["flood"], "regions": ["Atlantis"], "source_classes": ["observed"],
              "start": "2026-10-06T00:00:00Z", "end": "2026-10-07T00:00:00Z",
              "required_source_inventory_sha256s": ["d" * 64], "availability_trace_sha256s": ["e" * 64]}]
    rec = reference_intake.intake(intake_doc(event("ref-day", event_start="2026-10-10", event_end="2026-10-10"),
                                             quiet=quiet), retained_at=NOW)
    document = rec["retained"]["wrapper"]["document"]
    assert document["units"][0]["time_fields"]["event_start"]["precision"] == "calendar"
    assert document["units"][0]["time_fields"]["event_start"]["utc"] is None
    assert [q["state"] for q in document["quiet_periods"]] == ["evidence_incomplete", "adjudication_pending"]
    readiness = rec["denominator"]
    assert readiness["status"] == "not_qualified"
    assert readiness["requirements"]["independent_selection"] == "missing"
    assert readiness["requirements"]["quiet_period_inventory_and_traces"] == "missing"


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["events"][0].update(hazards=[]), "labels_required"),
    (lambda d: d["events"][0].update(origin="guess"), "event_enum"),
    (lambda d: d["events"][0].update(surprise=True), "event_shape"),
    (lambda d: d["events"].append(deepcopy(d["events"][0])), "event_id"),
    (lambda d: d["events"][0]["hazards"][0].update(evidence_sha256="nope"), "evidence_sha256"),
])
def test_intake_refuses_malformed_or_duplicate_input(mutate, code):
    document = intake_doc(event("ref-heat-1"))
    mutate(document)
    with pytest.raises(reference_intake.IntakeError, match=code):
        reference_intake.intake(document, retained_at=NOW)


# 15.2 -----------------------------------------------------------------------

def _assess(rec: dict, saved: dict) -> dict:
    return production_match.assess(rec, saved, cutoff=NOW, evaluated_at=LATER, state_version=3,
                                   policy_sha256="f" * 64, execution_class="invented_fixture")


def test_exact_match_reaches_coverage_stages_with_reviewable_evidence():
    result = _assess(record(event("ref-heat-1")), state())
    unit = result["units"][0]
    assert unit["match_evidence"]["status"] == "matched"
    assert unit["match_evidence"]["matched"][0]["evidence"] == {"alias": False, "hazard": True, "place": True, "window": True}
    cells = {c["stage"]: c for c in unit["stages"]}
    assert cells["draft_saved"]["state"] == "recorded" and cells["draft_saved"]["execution_class"] == "invented_fixture"
    assert cells["publication_confirmed"]["state"] == "recorded"
    assert result["metrics"]["event_recall"] is None
    assert result["production_match"]["summary"]["matched"] == 1


def test_misses_name_what_differed_and_ambiguity_is_neither_success_nor_miss():
    saved = state()
    saved["drafts"].append({"id": "d_fiction_2", "event_id": "openmeteo_fictionville_x", "type": "heat_anomaly",
                            "city": "Fictionville", "status": "pending", "created_at": "2026-10-10T20:00:00Z"})
    rec = record(
        event("ref-ambiguous"),
        event("ref-late", event_start="2026-09-01T00:00:00Z", event_end="2026-09-02T00:00:00Z"),
        event("ref-atlantis-flood", hazards=[{"label": "Flood", "evidence_sha256": SHA}],
              regions=[{"label": "Atlantis", "evidence_sha256": SHA}],
              event_start="2026-10-12T00:00:00Z", event_end="2026-10-12T12:00:00Z"),
        event("ref-bigwood-fire", hazards=[{"label": "Wildfire", "evidence_sha256": SHA}],
              regions=[{"label": "Bigwood", "evidence_sha256": SHA}],
              event_start="2026-10-13T00:00:00Z", event_end="2026-10-13T12:00:00Z"),
        event("ref-cyclone", hazards=[{"label": "Tropical cyclone", "evidence_sha256": SHA}],
              regions=[{"label": "Nowhere", "evidence_sha256": SHA}],
              event_start="2026-10-15T00:00:00Z", event_end="2026-10-15T12:00:00Z"),
    )
    units = {u["unit_id"]: u for u in _assess(rec, saved)["units"]}
    assert units["ref-ambiguous"]["match_evidence"]["status"] == "ambiguous"
    assert "trace_ambiguous" in units["ref-ambiguous"]["holds"]
    assert all(c["state"] != "recorded" for c in units["ref-ambiguous"]["stages"])
    assert "reference_out_of_window" in units["ref-late"]["holds"]
    flood = units["ref-atlantis-flood"]
    assert flood["match_evidence"]["status"] == "matched" and "checks_failed" in flood["holds"]
    assert "budget_excluded" in units["ref-bigwood-fire"]["holds"]
    cyclone = units["ref-cyclone"]
    assert "source_failed" in cyclone["holds"] and cyclone["match_evidence"]["source_failures"] == ["run_1:gdacs_cyclone"]


def test_alias_identity_matches_even_when_place_text_is_absent():
    saved = state()
    saved["drafts"][0].pop("city")
    saved["drafts"][0].pop("country")
    rec = record(event("ref-alias", production_aliases=["ghcn_fictionville_2026-10-10"]))
    unit = _assess(rec, saved)["units"][0]
    assert unit["match_evidence"]["status"] == "matched" and unit["match_evidence"]["matched"][0]["evidence"]["alias"]


def test_wrong_place_is_named_not_counted():
    rec = record(event("ref-elsewhere", regions=[{"label": "Nowhereland", "evidence_sha256": SHA}]))
    unit = _assess(rec, state())["units"][0]
    assert unit["match_evidence"]["status"] == "near_match" and "place_mismatch" in unit["holds"]


# 15.4 -----------------------------------------------------------------------

def _response(**public: Any) -> bytes:
    return json.dumps({"data": [{"id": "1900000000000000001", "created_at": "2026-10-10T19:00:00.000Z",
                                 "public_metrics": {"like_count": 7, "retweet_count": 2, "reply_count": 1,
                                                    "quote_count": 0, **public}}],
                       "errors": [{"resource_id": "1900000000000000009",
                                   "type": "https://api.twitter.com/2/problems/resource-not-found"}]}).encode()


def test_supplied_response_appends_samples_without_overwriting_and_keeps_unknowns_null():
    saved = state()
    first, report = metric_intake.ingest(saved, _response(), captured_at=datetime(2026, 10, 11, 19, tzinfo=UTC),
                                         requested_ids=["1900000000000000001", "1900000000000000009", "123"],
                                         now=datetime(2026, 10, 20, tzinfo=UTC))
    statuses = {p["tweet_id"]: p["status"] for p in report["posts"]}
    assert statuses == {"1900000000000000001": "sample_appended", "1900000000000000009": "not_a_retained_post",
                        "123": "not_a_retained_post"}
    appended = report["posts"][0]
    assert appended["post_age_seconds"] == 86400.0 and appended["post_time_status"] == "recorded"
    assert appended["unavailable_dimensions"] == ["bookmarks", "impressions"]
    saved["tweet_metrics"] = first
    second, _ = metric_intake.ingest(saved, _response(like_count=9), captured_at=datetime(2026, 10, 12, 19, tzinfo=UTC),
                                     requested_ids=["1900000000000000001"], now=datetime(2026, 10, 20, tzinfo=UTC))
    samples = list(second["1900000000000000001"]["samples"].values())
    assert sorted(s["counts"]["likes"] for s in samples) == [7, 9]
    assert all(s["counts"]["impressions"] is None for s in samples)
    assert saved["tweet_metrics"] is first and "samples" in first["1900000000000000001"]


def test_access_refusal_records_nothing_and_future_capture_is_refused():
    saved = state()
    refused = json.dumps({"errors": [{"resource_id": "1900000000000000001",
                                      "type": "https://api.twitter.com/2/problems/not-authorized-for-resource"}]}).encode()
    metrics, report = metric_intake.ingest(saved, refused, captured_at=datetime(2026, 10, 11, tzinfo=UTC),
                                           requested_ids=["1900000000000000001"], now=datetime(2026, 10, 20, tzinfo=UTC))
    assert metrics == {} and report["posts"][0]["status"] == "access_refused" and report["appended"] == 0
    with pytest.raises(metric_intake.MetricIntakeError, match="captured_at_in_future"):
        metric_intake.ingest(saved, refused, captured_at=datetime(2030, 1, 1, tzinfo=UTC),
                             requested_ids=["1900000000000000001"], now=datetime(2026, 10, 20, tzinfo=UTC))


# 15.5 -----------------------------------------------------------------------

def test_route_columns_stay_separate_and_counterexamples_are_negative_only():
    saved = state()
    bad = saved["publish_ledger"]["ghcn_fictionville_2026-10-10"]["text_sha256"]
    result = route_evaluation.evaluate(saved, window_start=datetime(2026, 10, 1, tzinfo=UTC),
                                       window_end=datetime(2026, 10, 19, tzinfo=UTC),
                                       counterexample_text_sha256s={bad}, execution="invented_fixture",
                                       human_comparisons={"heat_record": {"supplied_ratings": 3}})
    heat = result["routes"]["heat_record"]
    assert heat["drafts"] == 2 and heat["delivered"][0]["identity"] == "recorded"
    assert heat["known_counterexamples"] == [{"tweet_id": "1900000000000000001", "use": "negative_only"}]
    assert heat["human_comparison"]["status"] == "supplied"
    assert result["routes"]["flood"]["factual_refusals"]["fact_check"] == 1
    assert result["routes"]["flood"]["human_comparison"] == "not_supplied"
    assert result["routes"]["fire"]["budget_exclusions"] == 1
    assert result["cost"] == {"status": "unavailable"}
    assert "score" not in json.dumps(result).replace("not combined into a score", "")


# 15.6 -----------------------------------------------------------------------

def test_correction_candidates_need_source_complete_discrepancies_and_never_act():
    saved = state()
    complete = {"tweet_id": "1900000000000000001", "claim": "49.1C", "kind": "value",
                "source_evidence": {"artifact_sha256": "9" * 64, "retrieved_at": "2026-10-18T00:00:00Z",
                                    "statement": "Invented corrected station table shows 48.7C."},
                "uncertainty": "Invented: provisional QC."}
    partial = {"tweet_id": "1900000000000000001", "claim": "not in the post", "kind": "value", "source_evidence": {}}
    result = correction_candidates.prepare(saved, [complete, partial],
                                           reader_flags=[{"tweet_id": "1900000000000000001"}])
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["action"] == "editor_review_only" and candidate["automatic_correction"] is False
    assert candidate["deletion"] is False and candidate["publication_class"] == "heat_record"
    assert set(result["incomplete"][0]["needed"]) == {"exact_claim_quoted_from_delivered_text", "source_artifact_sha256",
                                                      "source_retrieved_at", "source_statement", "stated_uncertainty"}
    assert result["reader_flags"] == []


# fresh-process CLI -----------------------------------------------------------

def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts/theheat_evaluation.py"), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120, check=False,
                          env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1"})


def test_cli_intake_then_match_then_refuses_to_overwrite(tmp_path):
    (tmp_path / "intake.json").write_text(json.dumps(intake_doc(event("ref-heat-1"))))
    (tmp_path / "state.json").write_text(json.dumps(state()))
    done = _cli("reference-intake", "--input", str(tmp_path / "intake.json"), "--retained-at", NOW,
                "--output", str(tmp_path / "record.json"))
    assert done.returncode == 0, done.stdout + done.stderr
    done = _cli("match-coverage", "--record", str(tmp_path / "record.json"), "--state", str(tmp_path / "state.json"),
                "--cutoff", NOW, "--evaluated-at", LATER, "--policy-sha256", "f" * 64, "--invented-fixture",
                "--output", str(tmp_path / "assessment.json"))
    assert done.returncode == 0, done.stdout + done.stderr
    assessment = json.loads((tmp_path / "assessment.json").read_text())
    assert assessment["units"][0]["match_evidence"]["status"] == "matched"
    again = _cli("reference-intake", "--input", str(tmp_path / "intake.json"), "--retained-at", NOW,
                 "--output", str(tmp_path / "record.json"))
    assert again.returncode == 2 and "output_exists" in again.stdout
