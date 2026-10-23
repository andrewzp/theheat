"""Connected private diagnosis over actual D1 archives; INVENTED transports and state.

Dispositions here are mechanical fixture outcomes. No weather truth, model quality,
human preference, invoice truth or publication authority is established.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import uuid

import pytest

from src.editorial.revisions import (
    accepted_writer_observation, admit_writer_observation, draft_identity,
    merge_passive_maps, publication_observation, text_hash,
)
from src.evaluation import operator_diagnosis as diagnosis
from src.two_bot.request_archive import strict_json_loads
from src.two_bot.request_archive_replay import load_archive
from tests.test_archive_usage import anthropic_item, google_item
from tests.test_private_copy_pack import MANUAL_TEXT
from tests.test_request_archive_sdk import (
    FIXTURE, critic_json, fact_json, journey_env, private_root, run_journey, writer_json,
)

__all__ = ["journey_env"]
ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def explicit_node_fixture(monkeypatch):
    # Test-only installed-runtime lookup; production requires an explicit pin.
    node = os.environ.get("THEHEAT_DIAGNOSIS_NODE") or shutil.which("node")
    assert node and Path(node).is_absolute(), "offline Node fixture needs an installed runtime"
    monkeypatch.setattr(diagnosis, "NODE", str(Path(node).resolve()))


def scripted(prefix, tweet, *, safety="NO", fact=None, critic="PASS", stop=None):
    """Invented responses with unique provider IDs per archive (no cross-archive collisions)."""
    script = {"writer": [anthropic_item(writer_json(tweet), message_id=f"msg_invented_d4_{prefix}_writer",
                                        request_id=f"req_invented_d4_{prefix}_writer")]}
    if stop == "writer":
        return script
    script["safety"] = [google_item(safety, response_id=f"invented-d4-{prefix}-safety")]
    if stop == "safety":
        return script
    script["fact_check"] = [google_item(fact or fact_json(True), response_id=f"invented-d4-{prefix}-fact")]
    if stop == "fact_check":
        return script
    script["critic"] = [google_item(critic_json(critic, kill_reason=FIXTURE["critic_kill_reason"]
                                                if critic == "KILL" else None),
                                    response_id=f"invented-d4-{prefix}-critic")]
    return script


def build_scenario_archives(base: Path) -> dict:
    from src.two_bot.intern.fire import build_fire_bundle
    from tests.test_archive_usage import d2_accepted_script
    from tests.two_bot.conftest import _fire_event
    other_bundle = build_fire_bundle(_fire_event(lat=14.1, lon=-3.9))
    plan = {
        "accepted": (d2_accepted_script(), None),
        "second": (scripted("second", FIXTURE["revised_tweet"]), None),
        "factual": (scripted("factual", TWEET, fact=fact_json(False, failures=[FIXTURE["factual_failure"]]),
                             stop="fact_check"), None),
        "safety": (scripted("safety", TWEET, safety="YES", stop="safety"), None),
        "critic": (scripted("critic", TWEET, critic="KILL"), None),
        "uncertain": ({"writer": [{"raise": "timeout"}] * 3}, None),
        "malformed": ({"writer": [anthropic_item(FIXTURE["malformed_writer_text"], message_id="msg_invented_d4_bad_1"),
                                  anthropic_item("still invented non-json", message_id="msg_invented_d4_bad_2")]}, None),
        "precheck": ({"writer": [anthropic_item(writer_json(FIXTURE["local_precheck_tweet"]),
                                                message_id="msg_invented_d4_precheck")]}, None),
        "other_bundle": (scripted("other", TWEET), other_bundle),
    }
    archives = {}
    for name, (script, bundle) in plan.items():
        archives[name] = run_journey(script, root=private_root(base, f"archive-{name}"), bundle=bundle)
    return archives


TWEET = FIXTURE["accepted_tweet"]


def retained_state(archives: dict, *, posted_at="2026-10-22T12:00:00+00:00") -> dict:
    """INVENTED receipt-bound snapshot: one exact post, one manually edited post."""
    def draft(run, *, text=None, manual=False, tweet_id):
        archive = load_archive(run.archive)
        bundle = json.loads(archive.artifact(archive.inputs[0]["bundle_artifact"]))
        value = {"id": f"invented-draft-{tweet_id}", "event_id": run.draft["event_id"], "type": run.draft["type"],
                 "status": "posted", "publish_outcome": "confirmed", "tweet_id": tweet_id,
                 "text": text or run.draft["text"], "content_revision": 2 if manual else 1, "manual_override": manual,
                 "posted_at": posted_at, "review_context": {"source": "invented fixture", "two_bot": {"bundle": bundle}}}
        receipt = {**draft_identity(value), "text": value["text"], "tweet_id": tweet_id, "phase": "confirmed",
                   "intent_id": str(uuid.UUID(int=int(tweet_id), version=4)), "at": posted_at}
        value["review_context"]["two_bot"]["accepted_writer_observation"] = accepted_writer_observation(
            run.draft["text"], bundle, "thermal_power", run.draft["event_id"])
        # The invented model original is admitted before any simulated manual revision.
        if not manual:
            admit_writer_observation(value)
            receipt["publication_observations"] = merge_passive_maps({
                "invented": publication_observation(value, value["event_id"], receipt)})
        return value, receipt
    exact, exact_receipt = draft(archives["accepted"], tweet_id="1900000000000000001")
    edited, edited_receipt = draft(archives["other_bundle"], text=MANUAL_TEXT, manual=True, tweet_id="1900000000000000002")
    sample = {"schema_version": 1, "tweet_id": "1900000000000000001", "source": "x_api.public_metrics",
              "sampled_at": "2026-10-23T00:00:00Z", "posted_at": "2026-10-22T12:00:00Z",
              "post_time_basis": "x_api.created_at", "post_time_status": "recorded", "post_age_seconds": 43200,
              "counts": {"likes": 3, "impressions": 120}}
    return {"drafts": [exact, edited],
            "publish_ledger": {exact["event_id"]: exact_receipt, edited["event_id"]: edited_receipt},
            "tweet_metrics": {"1900000000000000001": {"samples": {"invented-sample": sample}}}}


def write_private(directory: Path, name: str, value) -> Path:
    path = directory / name
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    os.chmod(path, 0o600)
    return path


@pytest.fixture
def scenario(journey_env, tmp_path):
    return build_scenario_archives(tmp_path), tmp_path


def _readers(state_path: Path) -> dict:
    return diagnosis.run_review_readers(node=diagnosis.NODE, state_path=str(state_path), feedback_path=None,
                                        as_of=AS_OF)


def run(archives_by_name, *, state=None, readers=None, reconciliation=None, copy_private=None, copy_import=None,
        feedback=None):
    archives = [load_archive(r.archive) for r in archives_by_name.values()]
    components, usable = diagnosis.verify_components(archives=archives, reconciliation=reconciliation,
                                                     copy_private=copy_private, copy_import=copy_import,
                                                     readers=readers, state=state, feedback=feedback, as_of=AS_OF)
    return diagnosis.diagnose(archives=archives, components=components, usable=usable, as_of=AS_OF, input_files=[])


def by_scope(report, run_result):
    scope = load_archive(run_result.archive).scope_id
    return [c for c in report["candidates"] if c["scope_id"] == scope], \
           [g for g in report["generations"] if g["scope_id"] == scope]


def test_candidate_decisions_and_mechanical_dispositions(scenario):
    archives, _ = scenario
    report = run(archives)
    [accepted], _ = by_scope(report, archives["accepted"])
    assert accepted["decision"] == "accepted" and accepted["publication"]["status"] == "receipts_absent"
    assert {c["stage"] for c in accepted["calls"]} == {"safety", "fact_check", "critic"}
    for name, stage in (("factual", "fact_check"), ("safety", "safety"), ("critic", "critic")):
        [candidate], _ = by_scope(report, archives[name])
        assert candidate["decision"] == f"rejected_at:{stage}", name
    [precheck], _ = by_scope(report, archives["precheck"])
    assert "decided_without_provider_call:fact_check" in precheck["dispositions"]
    _, [uncertain] = by_scope(report, archives["uncertain"])
    assert uncertain["candidate_count"] == 0 and uncertain["terminal"]["kill_stage"] == "pipeline_error"
    assert {"missing_response:call_1", "unknown_send_outcome:call_1", "unknown_send_outcome:call_3"} <= set(
        uncertain["dispositions"])
    _, [malformed] = by_scope(report, archives["malformed"])
    assert "invalid_model_output_schema:writer" in malformed["dispositions"]
    assert report["overview"]["checks"] == {"candidates": 7, "accepted": 3, "rejected": 4,
                                            "generations_without_candidate": 2, "decided_without_provider_call": 1}
    for absent in ("spend", "preference", "publication"):
        assert report["overview"][absent]["status"] == "absent"  # Never zero.
    assert report["decision"]["promotion"] == "HOLD" and report["decision"]["approvals"] == "none"


def test_receipts_join_only_on_exact_text_and_bundle(scenario):
    archives, tmp_path = scenario
    state = retained_state(archives)
    inputs = private_root(tmp_path, "state")
    readers = _readers(write_private(inputs, "state.json", state))
    report = run(archives, state=state, readers=readers)
    [accepted], _ = by_scope(report, archives["accepted"])
    assert accepted["publication"]["status"] == "joined"
    assert accepted["publication"]["join"] == "writer_source_and_unchanged_revision_receipt_identity"
    published = accepted["publication"]["posts"][0]
    assert published["tweet_id"] == "1900000000000000001" and published["observation_count"] == 1
    assert published["observations"][0]["counts"]["retweets"] is None
    assert accepted["publication"]["authorship"] == "unknown"
    # The critic-rejected run produced the same text on the same bundle; rejected candidates never join.
    joined = [c for c in report["candidates"] if c["publication"]["status"] == "joined"]
    assert joined == [accepted] and accepted["candidate_text_sha256"] == text_hash(TWEET)
    [rejected_same_text], _ = by_scope(report, archives["critic"])
    assert rejected_same_text["publication"]["status"] == "not_published_in_supplied_state"
    [other], _ = by_scope(report, archives["other_bundle"])
    assert other["publication"]["status"] == "not_published_in_supplied_state"
    assert [p["tweet_id"] for p in report["unjoined_posts"]] == ["1900000000000000002"]  # The manual edit.
    assert report["overview"]["publication"]["manual_or_edited"] == 1
    assert report["overview"]["publication"]["engagement_lift"] is None
    moved = deepcopy(state)
    moved["drafts"][0]["review_context"]["two_bot"]["bundle"]["event_id"] = "invented-other-event"
    moved["drafts"][0]["event_id"] = moved["drafts"][0]["review_context"]["two_bot"]["bundle"]["event_id"]
    moved["publish_ledger"] = {moved["drafts"][0]["event_id"]: {**draft_identity(moved["drafts"][0]),
                               "text": TWEET, "tweet_id": "1900000000000000001", "phase": "confirmed",
                               "intent_id": str(uuid.uuid4())}}
    moved_readers = _readers(write_private(inputs, "moved.json", moved))
    changed = run(archives, state=moved, readers=moved_readers)
    [same_text], _ = by_scope(changed, archives["accepted"])
    assert same_text["publication"]["status"] == "same_text_different_evidence"
    assert "evidence_changed_since_capture" in same_text["dispositions"]


def test_component_lineage_mismatches_hold_instead_of_joining(scenario):
    archives, tmp_path = scenario
    subset = {k: archives[k] for k in ("accepted", "factual")}
    state = retained_state(archives)
    readers = _readers(write_private(private_root(tmp_path, "s"), "state.json", state))
    other_state = deepcopy(state)
    other_state["drafts"] = other_state["drafts"][:1]
    report = run(subset, state=other_state, readers=readers,
                 reconciliation={"schema": "theheat.archive-reconciliation/v1", "report_sha256": "0" * 64},
                 copy_private={"schema": "theheat.copy-review-private/v1"})
    statuses = {c["component"]: c["status"] for c in report["components"] if c["component"] != "archive"}
    assert statuses == {"reconciliation": "invalid", "copy_review": "invalid", "retained_state": "lineage_mismatch"}
    assert report["overview"]["publication"]["status"] == "absent"
    assert all(c["publication"]["status"] == "receipts_absent" for c in report["candidates"])


def test_durable_output_restore_retry_conflict_and_interruption(scenario, monkeypatch):
    archives, tmp_path = scenario
    report = run({k: archives[k] for k in ("accepted", "uncertain")})
    out = private_root(tmp_path, "out")
    assert diagnosis.write_report(out, report) == {name: "new" for name in (*diagnosis.COMPONENTS, diagnosis.MARKER)}
    assert diagnosis.verify_output(out)["status"] == "complete"
    assert set(diagnosis.write_report(out, report).values()) == {"identical_existing"}
    changed = dict(report, as_of="2026-10-24T00:00:00+00:00")
    changed["report_sha256"] = diagnosis._identity(changed)
    with pytest.raises(Exception, match="private_file_conflict"):
        diagnosis.write_report(out, changed)
    # Interrupt a NEW report after its first component: no marker, never a complete diagnosis.
    partial = private_root(tmp_path, "partial")
    real = diagnosis.write_private_file_exclusive
    calls = []

    def interrupted(directory, name, data):
        calls.append(name)
        if len(calls) > 1:
            raise OSError(5, "invented interruption")
        return real(directory, name, data)
    monkeypatch.setattr(diagnosis, "write_private_file_exclusive", interrupted)
    with pytest.raises(OSError):
        diagnosis.write_report(partial, report)
    monkeypatch.setattr(diagnosis, "write_private_file_exclusive", real)
    assert diagnosis.verify_output(partial) == {"status": "incomplete", "reason": "completion_marker_missing"}
    assert sorted(os.listdir(partial)) == ["diagnosis.json"]
    # Restart: the identical first component is reused, nothing is deleted or adopted silently.
    assert diagnosis.write_report(partial, report)["diagnosis.json"] == "identical_existing"
    assert diagnosis.verify_output(partial)["status"] == "complete"


@pytest.mark.parametrize("tamper", ["markdown", "json_value", "missing_html", "marker"])
def test_tampered_or_partial_components_are_never_a_clean_report(scenario, tamper):
    archives, tmp_path = scenario
    out = private_root(tmp_path, "out")
    diagnosis.write_report(out, run({"accepted": archives["accepted"]}))
    if tamper == "markdown":
        (out / "diagnosis.md").write_text("# edited\n")
        expected = "component_hash_mismatch"
    elif tamper == "json_value":
        data = json.loads((out / "diagnosis.json").read_bytes())
        data["decision"]["promotion"] = "PROMOTE"
        (out / "diagnosis.json").write_bytes(diagnosis.report_json(data))
        expected = "component_hash_mismatch"
    elif tamper == "missing_html":
        os.remove(out / "diagnosis.html")
        expected = "component_missing"
    else:
        marker = json.loads((out / diagnosis.MARKER).read_bytes())
        data = json.loads((out / "diagnosis.json").read_bytes())
        data["decision"]["promotion"] = "PROMOTE"
        new_json = diagnosis.report_json(data)
        (out / "diagnosis.json").write_bytes(new_json)
        marker["components"]["diagnosis.json"] = diagnosis.sha256_hex(new_json)
        (out / diagnosis.MARKER).write_bytes(diagnosis.report_json(marker))
        expected = "report_identity_mismatch"
    assert diagnosis.verify_output(out) == {"status": "invalid", "reason": expected}


def test_views_are_escaped_content_free_and_have_no_actions(scenario):
    archives, _ = scenario
    report = run(archives)
    page = diagnosis.render_html(report)
    markdown = diagnosis.render_markdown(report)
    assert "<script" not in page.lower() and "<form" not in page and "<button" not in page
    assert "default-src 'none'" in page and "Promotion: HOLD." in page
    for candidate in report["candidates"]:
        assert f"id='{candidate['anchor']}'" in page
    for private in (TWEET, FIXTURE["factual_failure"], FIXTURE["critic_kill_reason"], "PRIMARY SIGNAL"):
        assert private not in page and private not in markdown and private not in json.dumps(report)
    assert strict_json_loads(diagnosis.report_json(report), allow_floats=True)["report_sha256"] == report["report_sha256"]


def test_manual_reverted_unknown_and_conflicting_revision_contexts_never_join(scenario):
    archives, tmp_path = scenario
    inputs = private_root(tmp_path, "revision-cases")
    for mode in ("manual_same_text", "reverted", "unknown", "conflicting", "different_evidence"):
        state = retained_state(archives)
        draft = state["drafts"][0]
        receipt = state["publish_ledger"][draft["event_id"]]
        if mode == "manual_same_text":
            draft["manual_override"] = True
        elif mode == "reverted":
            draft["content_revision"] = 3
            draft["revision_history"] = [{"content_revision": 2, "text": "Invented manual intermediate text.",
                "text_sha256": text_hash("Invented manual intermediate text."), "evidence_sha256": receipt["evidence_sha256"],
                "invalidated_at": "2026-10-22T11:00:00Z"}]
        elif mode == "different_evidence":
            draft["content_revision"] = 2
            draft["review_context"]["source"] = "Changed invented retained evidence"
        receipt.update(draft_identity(draft))
        receipt["publication_observations"] = merge_passive_maps({
            "current": publication_observation(draft, draft["event_id"], receipt)})
        if mode == "unknown":
            del receipt["publication_observations"]
        elif mode == "conflicting":
            receipt["publication_observations"] = merge_passive_maps(receipt["publication_observations"], {
                "other": {"text": "PRIVATE MALFORMED CONTEXT BODY"}})
        readers = _readers(write_private(inputs, f"{mode}.json", state))
        report = run(archives, state=state, readers=readers)
        [candidate], _ = by_scope(report, archives["accepted"])
        assert candidate["publication"]["status"] != "joined", mode
        row = next(p for p in report["unjoined_posts"] if p["tweet_id"] == draft["tweet_id"])
        assert row["join"] == "candidate_revision_receipt_lineage_unavailable", mode
        assert "PRIVATE MALFORMED CONTEXT BODY" not in json.dumps(report)


def test_outcome_unknowns_post_age_stale_feedback_and_receipt_denominators_are_preserved(scenario):
    archives, tmp_path = scenario
    state = retained_state(archives)
    draft = state["drafts"][0]
    receipt = state["publish_ledger"][draft["event_id"]]
    sample = state["tweet_metrics"][draft["tweet_id"]]["samples"]["invented-sample"]
    sample.pop("post_age_seconds")
    sample["counts"] = {"likes": True, "impressions": "120", "retweets": 0}
    feedback: dict = {"records": [{"schema_version": 1, "kind": "dashboard_editorial_opinion",
        "request_id": "b6f74042-dcc1-42e5-bc76-eab95ff9bc5a", "received_at": "2026-10-22T13:00:00Z",
        "target": {"draft_id": draft["id"], "tweet_id": draft["tweet_id"], "posted_at": draft["posted_at"],
            "text": draft["text"], **draft_identity(draft), "intent_id": receipt["intent_id"]},
        "punch": 4, "clarity": 5, "economy": 3, "note": "PRIVATE STALE OPINION", "own_rating": True}]}
    feedback["records"][0]["target"]["evidence_sha256"] = "0" * 64
    inputs = private_root(tmp_path, "outcomes")
    state_path, feedback_path = write_private(inputs, "state.json", state), write_private(inputs, "feedback.json", feedback)
    readers = diagnosis.run_review_readers(node=diagnosis.NODE, state_path=str(state_path),
                                          feedback_path=str(feedback_path), as_of=AS_OF)
    report = run(archives, state=state, readers=readers, feedback=feedback)
    [candidate], _ = by_scope(report, archives["accepted"])
    observed = candidate["publication"]["posts"][0]["observations"][0]
    assert observed["age_status"] == "conflict" and observed["post_age_seconds"] is None
    assert observed["counts"]["likes"] is None and observed["counts"]["impressions"] is None
    assert observed["counts"]["retweets"] == 0
    assert report["overview"]["publication"]["exclusions"]["stale_opinion_targets"] == 1
    assert report["overview"]["publication"]["editorial_feedback"]["records_in_window"] == 0
    assert "PRIVATE STALE OPINION" not in json.dumps(report)
    # The feedback read must bind to the same contents used by the Node reader.
    mismatched = run(archives, state=state, readers=readers, feedback={"records": []})
    assert mismatched["overview"]["publication"] == {"status": "absent"}
    state["publish_ledger"] = {}
    readers = _readers(write_private(inputs, "draft-only.json", state))
    draft_only = run(archives, state=state, readers=readers)
    publication = draft_only["overview"]["publication"]
    assert publication["outcome_inventory_rows"] == 2 and publication["posts_with_receipts"] == 0
    assert publication["weekly_delivery_count"] == 0 and publication["feedback"] == "absent"


def test_import_summary_and_clock_counterexamples_are_held(journey_env, tmp_path):
    from src.evaluation import private_copy_pack as packs
    from tests.test_private_copy_pack import built, make_review_workspace, ballot, rating
    workspace = make_review_workspace(tmp_path)
    public, private, _ = built(workspace)
    imported = packs.import_ballots(private, [ballot(public, [rating(public["pairs"][0], "A")])], as_of=AS_OF)
    archives = [load_archive(path) for path in workspace["archives"]]

    def statuses(value):
        components, _ = diagnosis.verify_components(archives=archives, reconciliation=None, copy_private=private,
            copy_import=value, readers=None, state=None, as_of=AS_OF)
        return {c["component"]: c["status"] for c in components}

    assert statuses(imported)["copy_ratings"] == "verified"
    changed = deepcopy(imported)
    changed["real_human_ratings_added"] = 100
    changed["human_asserted_summary"]["eligible_preferences_by_display_side"]["A"] = 100
    assert statuses(changed)["copy_ratings"] == "invalid"
    future = packs.import_ballots(private, [], as_of=datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
    assert statuses(future)["copy_ratings"] == "invalid"
    # Even a self-consistent producer record must match the supplied archive.
    changed_private = deepcopy(private)
    changed_scope = changed_private["archives"][0]["scope_id"]
    changed_private["archives"][0]["status"] = "incomplete"
    for provenance in changed_private["provenance"].values():
        if provenance["scope_id"] == changed_scope:
            provenance["archive_status"] = "incomplete"
    changed_private["private_sha256"] = packs._identity(changed_private, "private_sha256")
    packs.verify_private_record(changed_private)
    components, _ = diagnosis.verify_components(archives=archives, reconciliation=None, copy_private=changed_private,
        copy_import=None, readers=None, state=None, as_of=AS_OF)
    assert next(c for c in components if c["component"] == "copy_review")["status"] == "lineage_mismatch"
    for view in (diagnosis.render_html, diagnosis.render_markdown):
        # Nested human/synthetic and monetary qualifications remain visible.
        report = {"report_sha256": "0" * 64, "as_of": AS_OF.isoformat(), "components": [], "candidates": [],
            "generations": [], "unjoined_posts": [], "limits": [], "overview": {
                "source": {}, "checks": {}, "publication": {},
                "preference": diagnosis._copy_summary(private, imported),
                "spend": {"billed_totals": [{"net": "0.125", "currency": "USD"}], "actual_cost_known": False}}}
        rendered = view(report)
        assert "synthetic_fixture_preferences" in rendered and "real_human_ratings_added" in rendered
        assert "0.125" in rendered and "actual_cost_known" in rendered


@pytest.mark.parametrize("same_text", [True, False])
def test_multigeneration_same_bundle_and_text_keeps_calls_decisions_and_anchors_disjoint(journey_env, tmp_path, same_text):
    from contextlib import redirect_stdout
    import io
    from src.two_bot import request_archive
    from tests.test_request_archive_sdk import OfflineProviders, offline_transport
    from tests.two_bot.conftest import _bundle, _state_with_memory
    providers = OfflineProviders()
    second_text = TWEET if same_text else FIXTURE["revised_tweet"]
    for script in (scripted("gen-first", TWEET, critic="KILL"), scripted("gen-second", second_text)):
        for stage, items in script.items():
            providers.queue(stage, *items)
    with offline_transport(providers), redirect_stdout(io.StringIO()), request_archive.capture(
            private_root(tmp_path, "multi"), operation="invented multi-generation") as scope:
        first, _ = scope.run_generation(_bundle(), _state_with_memory())
        second, _ = scope.run_generation(_bundle(), _state_with_memory())
    assert first is None and second is not None
    archive = load_archive(scope.directory)
    assert archive.status == "complete", archive.problems
    components, usable = diagnosis.verify_components(archives=[archive], reconciliation=None, copy_private=None,
        copy_import=None, readers=None, state=None, as_of=AS_OF)
    report = diagnosis.diagnose(archives=[archive], components=components, usable=usable, as_of=AS_OF, input_files=[])
    one, two = report["candidates"]
    assert one["decision"] == "rejected_at:critic" and two["decision"] == "accepted"
    assert {c["call"] for c in one["calls"]}.isdisjoint(c["call"] for c in two["calls"])
    assert {c["call"] for c in report["generations"][0]["writer_calls"]}.isdisjoint(
        c["call"] for c in report["generations"][1]["writer_calls"])
    assert one["anchor"] != two["anchor"] and one["candidate_key"] != two["candidate_key"]
    from tests.test_private_workflow_end_to_end import fresh
    exports = private_root(tmp_path, "exports")
    code, result, modules = fresh(str(ROOT / "scripts/theheat_diagnose.py"), "export-copy",
        "--archive", str(scope.directory), "--candidate", text_hash(TWEET), "--output", str(exports / "copy.json"))
    assert modules == []
    if same_text:
        assert code == 2 and result == {"error": "candidate_identity_ambiguous"}
        assert list(exports.iterdir()) == []
    else:
        assert code == 0 and result["content_written_to_stdout"] is False
        payload = json.loads((exports / "copy.json").read_bytes())
        assert payload["text"] == TWEET and payload["bundle_sha256"] == archive.inputs[0]["bundle_sha256"]
        assert [reason["stage"] for reason in payload["stage_reasons"]] == ["critic"]
        code, _, modules = fresh(str(ROOT / "scripts/theheat_diagnose.py"), "export-copy",
            "--archive", str(scope.directory), "--candidate", text_hash(second_text), "--output", str(exports / "second.json"))
        assert code == 0 and modules == []
        assert json.loads((exports / "second.json").read_bytes())["stage_reasons"] == []


def test_renderer_version_mismatch_is_explicit_and_node_override_is_refused(scenario):
    archives, tmp_path = scenario
    report = run({"accepted": archives["accepted"]})
    report["view_renderer"] = "theheat.private-diagnosis-views/future"
    report["report_sha256"] = diagnosis._identity(report)
    out = private_root(tmp_path, "renderer")
    diagnosis.write_report(out, report)
    assert diagnosis.verify_output(out) == {"status": "unverifiable_views", "reason": "view_renderer_version_differs"}
    with pytest.raises(diagnosis.DiagnosisError, match="review_readers_node_not_pinned"):
        diagnosis.run_review_readers(node="/bin/sh", state_path="/not/read", feedback_path=None, as_of=AS_OF)


def test_reader_stdout_limit_stops_child_without_retaining_unbounded_output(monkeypatch):
    # Fixed code owned by this test; never an input-specified executable or module.
    import sys
    monkeypatch.setattr(diagnosis, "MAX_READER_OUTPUT", 1024)
    with pytest.raises(diagnosis.DiagnosisError, match="review_readers_output_over_limit"):
        diagnosis._bounded_reader_output([sys.executable, "-I", "-c", "import os;os.write(1,b'x'*4096)"],
                                         {"PATH": "/usr/bin:/bin"})


@pytest.mark.parametrize("pin", ["", "node", "/bin/sh", "/not-a-runtime/python"])
def test_reader_missing_or_non_node_configuration_refuses_before_child(monkeypatch, pin):
    monkeypatch.setattr(diagnosis, "NODE", pin)
    def unexpected(*args):
        raise AssertionError("must not spawn a child")
    monkeypatch.setattr(diagnosis, "_bounded_reader_output", unexpected)
    with pytest.raises(diagnosis.DiagnosisError, match="review_readers_node_not_pinned"):
        diagnosis.run_review_readers(node=pin, state_path="/not-read", feedback_path=None, as_of=AS_OF)
