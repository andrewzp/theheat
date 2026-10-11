"""New source evidence must survive generation, retention and revision checks."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from src.editorial.revisions import approval_is_current, authorize_draft, fingerprint, review_is_current
from src.orchestrator.draft_save import save_draft
from src.two_bot import memory, pipeline, writer
from src.two_bot.bundle_capture import BundleCaptureError, MAX_BUNDLE_BYTES, MAX_SAFE_INTEGER, capture_bundle
from src.two_bot.types import CriticResult, FactCheckResult, RelatedSignal, WriterResult
from tests.test_draft_save_retention import round_trip
from tests.two_bot.conftest import _bundle, _state_with_memory

TEXT = "Mali thermal power is 361 MW."


def complete_bundle():
    bundle = _bundle()
    bundle.country = "ML"
    bundle.historical_context = {"scope": "synthetic sample", "samples": [100, 200]}
    from tests.fire_source_fixtures import fire_event
    from src.two_bot.intern.fire import build_fire_bundle
    related = build_fire_bundle(fire_event(lat=14.0, frp=120, country="NE", region="Synthetic place"))
    bundle.related_signals = [RelatedSignal(related.event_id, "fire", related.where, related.when,
        related.headline_metric, "NE", deepcopy(related.raw_signal_dump["acquisition_provenance"]))]
    bundle.human_impact = [{"claim": "evacuated", "value": 12, "source_name": "Synthetic bulletin",
                           "url": "https://example.org/synthetic-bulletin", "as_of": bundle.when}]
    return bundle


@pytest.fixture
def calls(monkeypatch, configured_pipeline_providers):
    stages = [Mock(return_value=WriterResult(TEXT, None, "number", None, None, "offline fixture", cited_impact=False)),
              Mock(return_value=(True, None)),
              Mock(return_value=FactCheckResult(True, [], "offline fixture")),
              Mock(return_value=CriticResult(True, None, "offline fixture"))]
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    return stages


def generated_and_saved(bundle, calls):
    state = _state_with_memory()
    result = pipeline.generate_draft(bundle, state)
    assert result and [call.call_count for call in calls] == [1, 1, 1, 1]
    assert save_draft(result["text"], state, result["type"], result["event_id"],
                      review_context={"two_bot": result["two_bot_metadata"]})
    return state, state["drafts"][-1]


def test_complete_capture_matches_writer_json_and_is_detached():
    bundle = complete_bundle()
    capture = capture_bundle(bundle)
    assert capture.serialized == writer._bundle_json(bundle)
    assert capture.payload() == json.loads(writer._bundle_json(bundle))
    before = capture.payload()
    bundle.raw_signal_dump["frp"] = 999
    capture.payload()["headline_metric"]["value"] = 0
    assert capture.payload() == before


@dataclass
class SourceValue:
    value: Decimal
    on: date


def test_documented_source_codec_matches_writer_without_changing_request():
    bundle = complete_bundle()
    bundle.raw_signal_dump.update(sample=SourceValue(Decimal("1.25"), date(2026, 4, 30)),
        stamp=datetime(2026, 4, 30, 12, tzinfo=UTC), stations={"B", "A"})
    capture = capture_bundle(bundle)
    assert capture.serialized == writer._bundle_json(bundle)
    assert capture.payload()["raw_signal_dump"]["sample"] == {"value": 1.25, "on": "2026-04-30"}
    assert capture.payload()["raw_signal_dump"]["stamp"] == "2026-04-30T12:00:00+00:00"
    assert capture.payload()["raw_signal_dump"]["stations"] == ["A", "B"]


@pytest.mark.parametrize("value,code", [(b"source bytes", "unsupported_bytes"), (float("nan"), "invalid_json"),
    (float("inf"), "invalid_json"), (object(), "invalid_json"), ("\ud800", "invalid_json"),
    (MAX_SAFE_INTEGER + 1, "unsafe_integer"), (-MAX_SAFE_INTEGER - 1, "unsafe_integer")])
def test_capture_refuses_unrepresentable_values_with_bounded_codes(value, code):
    bundle = _bundle()
    bundle.raw_signal_dump["nested"] = {"value": value}
    with pytest.raises(BundleCaptureError, match="^bundle_capture_" + code + "$"):
        capture_bundle(bundle)


@pytest.mark.parametrize("padding", [0, 1])
def test_exact_whole_bundle_byte_bound(padding):
    bundle = complete_bundle()
    bundle.raw_signal_dump["padding"] = ""
    empty_size = len(writer._bundle_json(bundle).encode("utf-8"))
    bundle.raw_signal_dump["padding"] = "x" * (MAX_BUNDLE_BYTES - empty_size + padding)
    if padding:
        with pytest.raises(BundleCaptureError, match="too_large"):
            capture_bundle(bundle)
    else:
        assert len(capture_bundle(bundle).serialized.encode("utf-8")) == MAX_BUNDLE_BYTES


def test_unicode_bound_uses_actual_writer_representation():
    bundle = _bundle()
    bundle.raw_signal_dump["padding"] = "\u2600" * 6000
    assert len(writer._bundle_json(bundle).encode("utf-8")) > MAX_BUNDLE_BYTES
    with pytest.raises(BundleCaptureError, match="too_large"):
        capture_bundle(bundle)


@pytest.mark.parametrize("value,stage", [("x" * MAX_BUNDLE_BYTES, "bundle_retention"),
    (MAX_SAFE_INTEGER + 1, "bundle_retention"), (b"bytes", "evidence_contract"),
    (float("nan"), "evidence_contract")], ids=["oversize", "unsafe-integer", "bytes", "nonfinite"])
def test_unretained_input_cannot_purchase_generation_or_checks(value, stage, calls):
    bundle = _bundle()
    bundle.raw_signal_dump["value"] = value
    outcome = {}
    assert pipeline.generate_draft(bundle, _state_with_memory(), result_out=outcome) is None
    assert outcome["kill_stage"] == stage
    assert all(not call.mock_calls for call in calls)


def test_complete_fields_survive_real_generation_save_and_state_retention(calls, monkeypatch):
    bundle = complete_bundle()
    bundle.raw_signal_dump["native_values"] = [Decimal("1.25"), date(2026, 4, 30),
        datetime(2026, 4, 30, 12, tzinfo=UTC), SourceValue(Decimal("2.5"), date(2026, 4, 29))]
    expected = json.loads(writer._bundle_json(bundle))
    state, draft = generated_and_saved(bundle, calls)
    assert review_is_current(draft)
    proof = draft["review_context"]["two_bot"]
    assert proof["bundle"] == expected
    assert proof["reviewed_bundle_sha256"] == fingerprint(expected)
    assert proof["bundle_capture"] == {"schema_version": 1, "scope": "complete_story_bundle"}
    before = deepcopy(draft)
    bundle.raw_signal_dump["frp"] = 999
    bundle.related_signals[0].headline_metric["value"] = 999
    bundle.human_impact[0]["value"] = 999
    assert draft == before
    loaded = round_trip(state, monkeypatch)
    assert loaded["drafts"] == [before]
    assert review_is_current(loaded["drafts"][0])
    compact = memory._story_bundle_from_metadata(proof, draft)
    assert compact.raw_signal_dump == compact.headline_metric == compact.historical_context == {}
    assert compact.related_signals == [] and compact.human_impact == []
    assert compact.current_facts == expected["current_facts"]


@pytest.mark.parametrize("field", ["raw_signal_dump", "historical_context", "headline_metric",
                                  "related_signals", "country", "human_impact"])
def test_every_new_retained_field_participates_in_review_and_posting_binding(field, calls, automatic_publication_release):
    _, draft = generated_and_saved(complete_bundle(), calls)
    authorize_draft(draft, "manual")
    assert review_is_current(draft) and approval_is_current(draft)
    evidence = draft["review_context"]["two_bot"]["bundle"]
    if isinstance(evidence[field], dict):
        evidence[field]["changed"] = True
    elif isinstance(evidence[field], list):
        evidence[field][0]["changed"] = True
    else:
        evidence[field] = "changed"
    assert not review_is_current(draft) and not approval_is_current(draft)


@pytest.mark.parametrize("stage", [0, 2, 3], ids=["writer", "fact-check", "critic"])
def test_mutation_during_checks_cannot_bind_changed_source_to_old_verdict(stage, calls):
    bundle = complete_bundle()
    result = calls[stage].return_value
    def mutate(*args, **kwargs):
        bundle.related_signals[0].headline_metric["value"] = 999
        return result
    calls[stage].side_effect = mutate
    outcome = {}
    assert pipeline.generate_draft(bundle, _state_with_memory(), result_out=outcome) is None
    if stage == 0:
        # The source contract now catches a detached related FRP immediately
        # after writing, before purchasing any downstream check.
        assert outcome["kill_stage"] == "fact_check"
        assert "thermal_source_unqualified" in outcome["kill_reason"]
        assert [call.call_count for call in calls] == [1, 0, 0, 0]
    else:
        assert outcome["kill_stage"] == "bundle_retention" and outcome["kill_reason"] == "bundle_changed_during_checks"


def test_legacy_compact_bundle_is_not_backfilled_by_state_round_trip(monkeypatch):
    legacy = {"id": "legacy", "event_id": "legacy", "status": "pending", "text": "Synthetic legacy copy.",
        "review_context": {"two_bot": {"bundle": {"event_id": "legacy", "current_facts": []}}}}
    assert round_trip({"drafts": [deepcopy(legacy)]}, monkeypatch)["drafts"] == [legacy]


def test_python_generated_evidence_survives_javascript_edit_merge_and_save(calls):
    from src.editorial.policy import current_editorial_policy
    from src.editorial.revisions import draft_identity
    _, draft = generated_and_saved(complete_bundle(), calls)
    script = r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { readStateStore, updateDraftStore } from "./lib/state-store.js";
import { draftIdentity, reviewIsCurrent, approvalIsCurrent, invalidateText } from "./lib/draft-revisions.js";
const {draft, policy} = JSON.parse(readFileSync(0, "utf8"));
Object.assign(process.env, {THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "bundle_fixture", GITHUB_TOKEN: "offline-fixture"});
const legacy = {id: "legacy", status: "pending", text: "Synthetic legacy text.", review_context: {two_bot: {bundle: {event_id: "legacy"}}}};
let state = {drafts: [structuredClone(draft), structuredClone(legacy)], publish_ledger: {}};
globalThis.fetch = async (url, options = {}) => {
  assert.equal(String(url), "https://api.github.com/gists/bundle_fixture");
  if (options.method === "PATCH") {
    state = JSON.parse(JSON.parse(options.body).files["state.json"].content);
    return {ok: true, status: 200, async json() {return {}}};
  }
  assert.ok(!options.method || options.method === "GET");
  return {ok: true, status: 200, async json() {return {files: {"state.json": {content: JSON.stringify(state)}}}}};
};
const original = (await readStateStore()).drafts.find(d => d.id === draft.id);
assert.equal(reviewIsCurrent(original, policy), true);
const identity = draftIdentity(original);
for (const key of ["raw_signal_dump", "historical_context", "headline_metric", "related_signals", "country", "human_impact"]) {
  const changed = structuredClone(original);
  const evidence = changed.review_context.two_bot.bundle;
  if (Array.isArray(evidence[key])) evidence[key][0].changed = true;
  else if (typeof evidence[key] === "object") evidence[key].changed = true;
  else evidence[key] = "changed";
  assert.equal(reviewIsCurrent(changed, policy), false);
}
await updateDraftStore(original.id, current => {
  invalidateText(current, "A synthetic satellite thermal detection.");
  return current;
}, {expectedRevision: {...identity, decision_revision: original.decision_revision ?? 0}});
const after = await readStateStore();
const saved = after.drafts.find(d => d.id === original.id);
assert.deepEqual(saved.review_context.two_bot.bundle, original.review_context.two_bot.bundle);
assert.deepEqual(saved.revision_history[0].review_context.two_bot, original.review_context.two_bot);
assert.equal(reviewIsCurrent(saved, policy), false);
assert.equal(approvalIsCurrent(saved, null, policy), false);
assert.deepEqual(after.drafts.find(d => d.id === "legacy"), legacy);
process.stdout.write(JSON.stringify({identity, saved}));
'''
    result = subprocess.run(["node", "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2] / "dashboard", check=True,
        input=json.dumps({"draft": draft, "policy": current_editorial_policy()}),
        capture_output=True, text=True, timeout=30)
    returned = json.loads(result.stdout)
    assert returned["identity"] == draft_identity(draft)
    assert returned["saved"]["review_context"]["two_bot"]["bundle"] == draft["review_context"]["two_bot"]["bundle"]
    assert not review_is_current(returned["saved"])
