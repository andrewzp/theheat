"""Invented, offline prospective provenance; no model or platform access."""
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import MagicMock
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from src.data.metric_history import append_sample
from src.editorial.draft_admission import plan_draft_admission, resolve_admission_place_facts
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import (
    accepted_writer_observation, admit_writer_observation, draft_identity, fingerprint, invalidate_text,
    merge_passive_maps, publication_observation, publication_observation_status, qualifying_publication_context,
)
from src.state import _merge_drafts, _merge_publish_ledger
from src.orchestrator import posting
from src.two_bot import pipeline
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests.revision_helpers import bind_reviewed_draft
from tests.two_bot.conftest import _bundle, _state_with_memory


def journey(monkeypatch, *, edits=()):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setattr("src.voice.safety.check_llm", lambda text: (True, None))
    write = MagicMock(return_value=WriterResult(tweet="Mali thermal power is 361 MW.", kill_reason=None,
        angle_chosen="plain_number", era_anchor_used=None, peer_comparison_used=None, reasoning="offline fixture"))
    monkeypatch.setattr(pipeline.writer, "write_tweet", write)
    monkeypatch.setattr(pipeline.fact_check, "fact_check", MagicMock(return_value=FactCheckResult(
        passed=True, failures=[], raw_response="explicit offline check", extracted_claims=[])))
    monkeypatch.setattr(pipeline.critic, "critic_review", MagicMock(return_value=CriticResult(
        passed=True, kill_reason=None, raw_response="explicit offline critic")))
    state = _state_with_memory()
    result = pipeline.generate_draft(_bundle(), state)
    assert result is not None
    write.assert_called_once()
    plan = plan_draft_admission(state, text=result["text"], tweet_type=result["type"],
        event_id=result["event_id"], draft_id="invented-h3", at=datetime(2026, 10, 22, 12, tzinfo=UTC),
        editorial_policy=current_editorial_policy(),
        place_facts=resolve_admission_place_facts(state, result["event_id"]),
        review_context={"two_bot": result["two_bot_metadata"]})
    assert plan.draft is not None
    draft, state = plan.draft, plan.state
    original = deepcopy(draft)
    for text in edits:
        invalidate_text(draft, text, at="2026-10-22T12:01:00Z")
    # Explicit fixture review/approval after editing; never a production fallback.
    bind_reviewed_draft(draft, "manual", "invented-h3-intent")
    send = MagicMock(return_value={"id": "123"})
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    submitted = []
    def store(value, **kwargs):
        send.assert_not_called()
        submitted.append(deepcopy(value["publish_ledger"][draft["event_id"]]))
        return True
    storage.write_state.side_effect = store
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "_utc_now_iso", lambda: "2026-10-22T12:02:00Z")
    assert posting.post_approved(draft, state) == "posted"
    send.assert_called_once_with(draft["text"], media_png=None, alt_text=None)
    assert len(submitted) == 1
    metrics = append_sample(None, tweet_id="123", counts={"likes": 0, "created_at": "2026-10-22T12:02:00Z"},
        sampled_at=datetime(2026, 10, 22, 13, tzinfo=UTC), state=state)
    state["tweet_metrics"] = {"123": metrics}
    return state, original, submitted[0]


def test_connected_accepted_writer_origin_survives_edit_receipt_and_sample(monkeypatch):
    state, original, submitted = journey(monkeypatch, edits=("Invented edited station text.",))
    draft = state["drafts"][0]
    assert "angle_chosen" not in draft["review_context"]["two_bot"]
    assert draft["writer_observations"] == original["writer_observations"]
    receipt = state["publish_ledger"][draft["event_id"]]
    assert receipt["publication_observations"] == submitted["publication_observations"]
    sample = next(iter(state["tweet_metrics"]["123"]["samples"].values()))
    assert sample["publication_context_sha256"] in receipt["publication_observations"]


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/publication_context_contract.json"


def node(script, value):
    result = subprocess.run([shutil.which("node"), "--input-type=module", "--eval", script],
        cwd=ROOT / "dashboard", input=json.dumps(value), text=True, capture_output=True, timeout=25,
        env={key: value for key, value in os.environ.items() if key in {"PATH", "LC_ALL", "NETRC", "no_proxy", "NO_PROXY"}})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def contract_draft():
    draft = {"id": "invented-contract", "event_id": "invented-contract-event", "type": "fire",
        "text": "Invented writer text with café ☀.", "content_revision": 1,
        "review_context": {"two_bot": {"bundle": {"event_id": "invented-contract-event", "signal_kind": "fire", "value": 1.25}}}}
    draft["review_context"]["two_bot"]["accepted_writer_observation"] = accepted_writer_observation(
        draft["text"], draft["review_context"]["two_bot"]["bundle"], "plain_number", draft["event_id"])
    admit_writer_observation(draft)
    return draft


def context_receipt(draft):
    row = {**draft_identity(draft), "text": draft["text"], "intent_id": "invented-contract-intent",
        "at": "2026-10-22T12:02:00Z", "confirmed_at": "2026-10-22T12:02:01Z", "phase": "confirmed", "tweet_id": "123"}
    payload = publication_observation(draft, draft["event_id"], row)
    if payload is not None:
        row["publication_observations"] = {fingerprint(payload): payload}
    return row


def test_contract_golden_and_actual_cross_runtime_canonical_parity():
    draft = contract_draft()
    original = deepcopy(draft)
    invalidate_text(draft, "Invented intervening text.", at="2026-10-22T12:00:00.000001Z")
    invalidate_text(draft, original["text"], at="2026-10-22T12:01:00Z")
    row = context_receipt(draft)
    fixture = {"original": original, "draft": draft, "receipt": row,
               "context_sha256": qualifying_publication_context(row, draft["event_id"])}
    assert fixture == json.loads(FIXTURE.read_text())
    result = node("""
      import {admitWriterObservation, publicationObservation, qualifyingPublicationContext, fingerprint} from './lib/draft-revisions.js';
      let input='';for await(const chunk of process.stdin) input+=chunk;
      const value=JSON.parse(input), draft=structuredClone(value.original);delete draft.writer_observations;
      admitWriterObservation(draft);
      const payload=publicationObservation(value.draft,value.draft.event_id,value.receipt);
      console.log(JSON.stringify({original:draft,payload,digest:fingerprint(payload),reference:qualifyingPublicationContext(value.receipt,value.draft.event_id)}));
    """, fixture)
    assert result["original"] == original
    assert result["payload"] == next(iter(row["publication_observations"].values()))
    assert result["digest"] == result["reference"] == fixture["context_sha256"]


@pytest.mark.parametrize("edits,comparison,different", [
    ((), "matches", False), (("Invented changed text.",), "differs", False),
    (("Invented changed text.", "Mali thermal power is 361 MW."), "matches", True),
])
def test_actual_pipeline_to_authenticated_get_and_rendered_history(monkeypatch, tmp_path, edits, comparison, different):
    state, original, submitted = journey(monkeypatch, edits=edits)
    origin = next(iter(original["writer_observations"].values()))
    assert origin["angle_chosen"] == "plain_number"
    # Current metadata and root text cannot relabel the immutable send snapshot.
    state["drafts"][0]["review_context"]["two_bot"]["angle_chosen"] = "later_unbound_angle"
    state["drafts"][0]["text"] = "Later root draft text is never the published text."
    script = r"""
      import assert from 'node:assert/strict';import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';
      import History from './app/components/PostOutcomeHistory.js';
      let input='';for await(const chunk of process.stdin) input+=chunk;const state=JSON.parse(input),before=JSON.stringify(state);
      Object.assign(process.env,{NODE_ENV:'production',DASHBOARD_USERNAME:'fixture-reader',DASHBOARD_PASSWORD:'fixture-only',
        GITHUB_TOKEN:'fixture-only',GIST_ID:'fixture_h3',THEHEAT_STATE_BACKEND:'gist'});
      Date.now=()=>Date.parse('2026-10-22T14:00:00Z');const reads=[];
      globalThis.fetch=async(url,options)=>{assert.ok(!options?.method||options.method==='GET');reads.push(String(url));
        if(String(url)==='https://api.github.com/gists/fixture_h3')return Response.json({files:{'state.json':{content:JSON.stringify(state)}}});
        if(String(url).endsWith('/actions/runs?per_page=10'))return Response.json({workflow_runs:[]});throw Error('Unexpected request');};
      const {GET}=await import('./app/api/dashboard/route.js');
      assert.equal((await GET(new Request('http://localhost/api/dashboard'))).status,401);assert.equal(reads.length,0);
      const response=await GET(new Request('http://localhost/api/dashboard',{headers:{authorization:'Basic '+Buffer.from('fixture-reader:fixture-only').toString('base64')}}));
      assert.equal(response.status,200);assert.equal(reads.length,2);const body=await response.json();
      const outcomes=body.productHealth.post_outcomes,post=outcomes.posts[0],html=renderToStaticMarkup(React.createElement(History,{outcomes}));
      assert.match(html,/Writer-reported angle \(captured accepted result\): plain number/);
      assert.match(html,/Retained history is incomplete/);assert.match(html,/Actor and human authorship are unknown/);
      assert.doesNotMatch(html,/later_unbound_angle|Later root draft text/);assert.equal(JSON.stringify(state),before);
      console.log(JSON.stringify({post,html,unauthenticated_reads:0,intercepted_existing_GETs:reads.length,real_calls:0}));
    """
    result = node(script, state)
    context = result["post"]["writer_context"]
    assert context["status"] == "recorded" and context["text_comparison"] == comparison
    assert context["retained_different_text"] is different
    assert result["post"]["observations"][0]["writer_context_status"] == "recorded"
    assert result["post"]["observations"][0]["counts"]["likes"] == 0
    assert result["post"]["observations"][0]["counts"]["impressions"] is None
    assert result["intercepted_existing_GETs"] == 2 and result["unauthenticated_reads"] == result["real_calls"] == 0
    (tmp_path / "connected-trace.json").write_text(json.dumps({"original": original, "submitted": submitted,
        "state": state, "reader": result}, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("change", ["legacy", "text", "bundle", "event", "copied_hash", "null_seed"])
def test_admission_cannot_backfill_or_repair_unbound_writer_metadata(change):
    draft = contract_draft()
    del draft["writer_observations"]
    two = draft["review_context"]["two_bot"]
    if change == "legacy":
        del two["accepted_writer_observation"]
        two.update(angle_chosen="legacy_angle", manual_override=True, review={"kind": "human"}, selected_candidate_rank=1)
    elif change == "text":
        draft["text"] = "Different candidate."
    elif change == "bundle":
        two["bundle"]["value"] = 2
    elif change == "event":
        draft["event_id"] = "detached"
    elif change == "copied_hash":
        two["accepted_writer_observation"]["text_sha256"] = "f" * 64
    else:
        two["accepted_writer_observation"] = None
    admit_writer_observation(draft)
    assert "writer_observations" not in draft


@pytest.mark.parametrize("change", ["source", "event", "intent", "at", "identity", "text", "same_revision", "malformed_writer", "conflicting_writer", "malformed_history", "conflicting_history"])
def test_binding_and_conflict_negatives_have_python_js_parity(change):
    draft = contract_draft()
    invalidate_text(draft, "Invented different text.", at="2026-10-22T12:01:00Z")
    row = context_receipt(draft)
    payload = next(iter(row["publication_observations"].values()))
    writer = next(iter(payload["writer_observations"].values()))
    expected = "unknown"
    if change == "source":
        payload["source_bundle_sha256"] = "f" * 64
    elif change in {"event", "intent", "at"}:
        payload[{"event": "event_id", "intent": "intent_id", "at": "at"}[change]] = "detached"
    elif change == "identity":
        payload["identity"]["evidence_sha256"] = "f" * 64
    elif change == "text":
        row["text"] = "Tampered receipt text."
    elif change == "same_revision":
        writer["original_identity"]["content_revision"] = row["content_revision"]
    elif change == "malformed_writer":
        payload["writer_observations"] = {"bad": None}
    elif change == "conflicting_writer":
        other = {**deepcopy(writer), "angle_chosen": "different_angle"}
        payload["writer_observations"]["conflict"] = other
        expected = "conflict"
    elif change == "malformed_history":
        next(iter(payload["text_observations"].values()))["invalidated_at"] = "2026-02-30T12:00:00Z"
    else:
        other = deepcopy(next(iter(payload["text_observations"].values())))
        other["text_sha256"] = "f" * 64
        payload["text_observations"]["conflict"] = other
        expected = "conflict"
    assert publication_observation_status(payload, draft["event_id"], row) == expected
    result = node("""
      import {publicationObservationStatus} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      const {payload,event,row}=JSON.parse(s);console.log(JSON.stringify(publicationObservationStatus(payload,event,row)));
    """, {"payload": payload, "event": draft["event_id"], "row": row})
    assert result == expected
    assert qualifying_publication_context(row, draft["event_id"]) is None


def test_media_only_same_text_and_incomplete_history_are_not_text_edits():
    draft = contract_draft()
    before = deepcopy(draft)
    invalidate_text(draft, draft["text"], at="2026-10-22T12:00:00Z")
    assert draft == before
    # A media-only revision changes evidence/full identity, not actual text.
    draft["content_revision"] += 1
    draft["media_attachment"] = {"invented": "media-only-observation"}
    draft["revision_history"] = [{**draft_identity(before), "text": before["text"], "invalidated_at": "2026-10-22T12:01:00Z"}]
    row = context_receipt(draft)
    payload = next(iter(row["publication_observations"].values()))
    assert publication_observation_status(payload, draft["event_id"], row) == "recorded"
    assert {item["text_sha256"] for item in payload["text_observations"].values()} == {row["text_sha256"]}
    draft["revision_history"].append({"partial": True})
    payload = next(iter(context_receipt(draft)["publication_observations"].values()))
    assert payload["history_unavailable"] is True and payload["history_scope"] == "retained_incomplete"


def test_passive_variants_union_without_delivery_conflict_or_authority_changes():
    draft = contract_draft()
    row = context_receipt(draft)
    other = deepcopy(row)
    next(iter(other["publication_observations"].values()))["history_unavailable"] = True
    # A stale submitted phase with different passive annotations is still one call.
    other["phase"] = "submitted"
    other["tweet_id"] = None
    other.pop("confirmed_at")
    merged = _merge_publish_ledger({draft["event_id"]: row}, {draft["event_id"]: other})
    assert merged == _merge_publish_ledger({draft["event_id"]: other}, {draft["event_id"]: row})
    result = merged[draft["event_id"]]
    assert len(result["publication_observations"]) == 2 and "attempt_conflicts" not in result
    assert result["phase"] == "confirmed" and result["tweet_id"] == "123"
    assert qualifying_publication_context(result, draft["event_id"]) is None
    assert _merge_publish_ledger(merged, merged) == merged
    other_draft = deepcopy(draft)
    other_draft["writer_observations"] = {"forged-key": {"malformed": True}}
    drafts = _merge_drafts([draft], [other_draft])
    assert len(drafts[0]["writer_observations"]) == 2
    assert drafts == _merge_drafts([other_draft], [draft])
    assert _merge_drafts(drafts, drafts) == drafts
    assert draft_identity(drafts[0]) == draft_identity(draft)
    assert "revision_conflicts" not in drafts[0]
    paired = node("""
      import {mergePublishLedger,mergeDrafts} from './lib/state-store.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s);console.log(JSON.stringify({ledger:mergePublishLedger(v.base,v.next),drafts:mergeDrafts(v.drafts1,v.drafts2)}));
    """, {"base": {draft["event_id"]: row}, "next": {draft["event_id"]: other}, "drafts1": [draft], "drafts2": [other_draft]})
    assert paired == {"ledger": merged, "drafts": drafts}


@pytest.mark.parametrize("malformed", [None, [], "invalid", {"bad": None}, {}])
def test_malformed_map_variants_are_retained_and_never_qualify(malformed):
    merged = merge_passive_maps(malformed, malformed)
    assert merge_passive_maps(merged) == merged
    draft = contract_draft()
    draft["writer_observations"] = malformed
    row = context_receipt(draft)
    assert qualifying_publication_context(row, draft["event_id"]) is None


@pytest.mark.parametrize("phase", ["submitted", "unknown", "not_sent"])
def test_nonconfirmed_context_does_not_change_sample_and_unknown_never_resends(monkeypatch, phase):
    draft = contract_draft()
    bind_reviewed_draft(draft, "manual", "invented-contract-intent")
    row = context_receipt(draft)
    row["phase"] = phase
    state = {"drafts": [draft], "publish_ledger": {draft["event_id"]: row}, "posted_events": []}
    metrics = append_sample(None, tweet_id="123", counts={}, sampled_at=datetime(2026, 10, 22, 13, tzinfo=UTC), state=state)
    assert "publication_context_sha256" not in next(iter(metrics["samples"].values()))
    send = MagicMock(side_effect=AssertionError("Never resend retained receipt"))
    monkeypatch.setattr(posting, "post_tweet", send)
    storage = MagicMock()
    storage.check_daily_cap.return_value = True
    monkeypatch.setattr(posting, "state", storage)
    assert posting.post_approved(draft, state) == "failed"
    send.assert_not_called()


def test_optional_reference_retains_older_schema1_observation():
    draft = contract_draft()
    row = context_receipt(draft)
    state = {"drafts": [draft], "publish_ledger": {draft["event_id"]: row}}
    old_state = deepcopy(state)
    del old_state["publish_ledger"][draft["event_id"]]["publication_observations"]
    args = dict(tweet_id="123", counts={"likes": 0}, sampled_at=datetime(2026, 10, 22, 13, tzinfo=UTC))
    old = append_sample(None, **args, state=old_state)
    old_samples = deepcopy(old["samples"])
    new = append_sample(old, **args, state=state)
    assert len(new["samples"]) == 2
    assert all(new["samples"][key] == value for key, value in old_samples.items())
    assert all("publication_context_sha256" not in sample for sample in old_samples.values())
    detached = deepcopy(state)
    detached["publish_ledger"] = {}
    absent = append_sample(None, **args, state=detached)
    assert "publication_context_sha256" not in next(iter(absent["samples"].values()))


def test_passive_annotations_cannot_reorder_same_rank_same_time_physical_attempts():
    draft = contract_draft()
    original = context_receipt(draft)
    original.pop("publication_observations")
    other = {**deepcopy(original), "intent_id": "another-distinct-intent"}
    event = draft["event_id"]
    legacy = _merge_publish_ledger({event: original}, {event: other})
    def strip(row):
        return {key: [strip(child) for child in value] if key == "attempt_conflicts" else value
                for key, value in row.items() if key != "publication_observations"}
    for number in range(32):
        left, right = deepcopy(original), deepcopy(other)
        left["publication_observations"] = {"arbitrary": {"variant": number}}
        right["publication_observations"] = {"arbitrary": {"variant": 31 - number}}
        merged = _merge_publish_ledger({event: left}, {event: right})
        assert strip(merged[event]) == legacy[event]
        assert merged == _merge_publish_ledger({event: right}, {event: left})


def test_distinct_tweet_receipt_key_retains_passive_variants_without_extra_attempt():
    draft = contract_draft()
    original = context_receipt(draft)
    alternate = {**deepcopy(original), "tweet_id": "456"}
    variant = deepcopy(alternate)
    next(iter(variant["publication_observations"].values()))["history_unavailable"] = True
    event = draft["event_id"]
    merged = _merge_publish_ledger({event: original}, {event: alternate})
    merged = _merge_publish_ledger(merged, {event: variant})
    rows = [merged[event], *merged[event].get("attempt_conflicts", [])]
    assert len(rows) == 2
    assert len(next(row for row in rows if row["tweet_id"] == "456")["publication_observations"]) == 2
    paired = node("""
      import {mergePublishLedger} from './lib/state-store.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s);console.log(JSON.stringify(mergePublishLedger(mergePublishLedger(v.a,v.b),v.c)));
    """, {"a": {event: original}, "b": {event: alternate}, "c": {event: variant}})
    assert paired == merged


@pytest.mark.parametrize("conflicts", [None, {}, [None]])
def test_unreadable_delivery_conflict_evidence_cannot_qualify_context(conflicts):
    draft = contract_draft()
    row = context_receipt(draft)
    row["attempt_conflicts"] = conflicts
    assert qualifying_publication_context(row, draft["event_id"]) is None


def test_duplicate_payloads_collapse_by_actual_content_not_declared_map_keys():
    draft = contract_draft()
    row = context_receipt(draft)
    payload = next(iter(row["publication_observations"].values()))
    writer = next(iter(payload["writer_observations"].values()))
    payload["writer_observations"] = {"first": writer, "arbitrary_copy": deepcopy(writer)}
    assert publication_observation_status(payload, draft["event_id"], row) == "recorded"
    duplicate = deepcopy(payload)
    row["publication_observations"] = {"bad_declared_digest": payload, "also_bad": duplicate}
    assert qualifying_publication_context(row, draft["event_id"]) == fingerprint(payload)
    paired = node("""
      import {qualifyingPublicationContext} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s);console.log(JSON.stringify(qualifyingPublicationContext(v.row,v.event)));
    """, {"row": row, "event": draft["event_id"]})
    assert paired == fingerprint(payload)


def test_invalid_unicode_passive_payload_is_retained_unavailable_with_cross_runtime_parity():
    malformed = {"note": "\ud800", "nested": {"\udfff": ["café ☀", -0.0, 1.25], "𐀀": True, "10": 10, "2": 2}}
    normalized = merge_passive_maps({"declared": malformed})
    encoded = next(iter(normalized.values()))["passive_unavailable_record"]["raw_data"]
    assert json.loads(encoded)[0] == "object"
    assert "\\ud800" in encoded and "\\udfff" in encoded
    assert merge_passive_maps(normalized, normalized) == normalized
    draft = contract_draft()
    baseline = draft_identity(draft)
    draft["writer_observations"] = {"bad": malformed}
    # Required canonical identity validation is unchanged; only the sidecar is encoded.
    with pytest.raises(UnicodeError):
        fingerprint(malformed)
    assert draft_identity(draft) == baseline
    merged_drafts = _merge_drafts([draft], [draft])
    assert merged_drafts[0]["writer_observations"] == normalized
    row = context_receipt(draft)
    assert qualifying_publication_context(row, draft["event_id"]) is None
    original = context_receipt(contract_draft())
    other = {**deepcopy(original), "intent_id": "other-physical-intent", "publication_observations": {"bad": malformed}}
    merged = _merge_publish_ledger({draft["event_id"]: original}, {draft["event_id"]: other})
    other_clean = {key: value for key, value in other.items() if key != "publication_observations"}
    legacy = _merge_publish_ledger({draft["event_id"]: original}, {draft["event_id"]: other_clean})
    assert merged[draft["event_id"]]["intent_id"] == legacy[draft["event_id"]]["intent_id"]
    paired = node("""
      import {mergePassiveMaps, qualifyingPublicationContext} from './lib/draft-revisions.js';
      import {mergeDrafts,mergePublishLedger} from './lib/state-store.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s);console.log(JSON.stringify({normalized:mergePassiveMaps({declared:v.malformed}),
        drafts:mergeDrafts([v.draft],[v.draft]),rowContext:qualifyingPublicationContext(v.row,v.draft.event_id),
        ledger:mergePublishLedger({[v.draft.event_id]:v.original},{[v.draft.event_id]:v.other})}));
    """, {"malformed": malformed, "draft": draft, "row": row, "original": original, "other": other})
    assert paired == {"normalized": normalized, "drafts": merged_drafts, "rowContext": None, "ledger": merged}


def test_unicode_passive_guard_is_exact_and_collision_free_and_storage_send_succeeds(monkeypatch):
    from src import state as real_state
    from src.editorial.revisions import approval_is_current, passive_comparison_value
    malformed = {"bad": {"note": "\ud800", "n": 1.25}}
    draft = contract_draft()
    draft["writer_observations"] = malformed
    bind_reviewed_draft(draft, "manual", "invented-contract-intent")
    state = {"drafts": [draft], "publish_ledger": {}, "posted_events": []}
    original = deepcopy(state)
    assert approval_is_current(draft, "manual")
    assert real_state._expected_draft_matches(original, deepcopy(draft), None)
    for field, value in [("writer_observations", {"bad": {"note": "\ud801", "n": 1.25}}),
                         ("writer_observations", {"different_key": malformed["bad"]}),
                         ("writer_observations", []), ("writer_observations", None),
                         ("writer_observations", {"unavailable_unicode_json": passive_comparison_value(malformed)}),
                         ("text", "Changed ordinary text."), ("status", "pending"),
                         ("decision_revision", draft["decision_revision"] + 1),
                         ("publish_intent_id", "changed-intent"), ("approval_binding", {}),
                         ("review_binding", {}), ("review_context", {})]:
        changed = deepcopy(original)
        changed["drafts"][0][field] = value
        assert not real_state._expected_draft_matches(changed, draft, None), field
    missing = deepcopy(original)
    del missing["drafts"][0]["writer_observations"]
    assert not real_state._expected_draft_matches(missing, draft, None)
    receipt = context_receipt(contract_draft())
    receipt["publication_observations"] = malformed
    with_ledger = {**deepcopy(original), "publish_ledger": {draft["event_id"]: receipt}}
    assert real_state._expected_draft_matches(with_ledger, draft, deepcopy(receipt))
    detached = deepcopy(receipt)
    detached["publication_observations"] = {"bad": {"note": "\ud801", "n": 1.25}}
    assert not real_state._expected_draft_matches(with_ledger, draft, detached)
    for key, value in [("intent_id", "detached"), ("at", "2026-10-22T12:03:00Z"), ("phase", "unknown")]:
        detached = deepcopy(receipt)
        detached[key] = value
        assert not real_state._expected_draft_matches(with_ledger, draft, detached)
    paired = node("""
      import {passiveComparisonValue} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      console.log(JSON.stringify(passiveComparisonValue(JSON.parse(s))));
    """, malformed)
    assert paired == passive_comparison_value(malformed)
    persisted = []
    monkeypatch.setattr(real_state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(real_state, "_read_gist_state", lambda **kwargs: deepcopy(original))
    def save(value):
        persisted.append(deepcopy(value))
        return True
    monkeypatch.setattr(real_state, "_write_gist_state", save)
    monkeypatch.setattr(posting, "state", real_state)
    send = MagicMock(return_value={"id": "123"})
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "_utc_now_iso", lambda: "2026-10-22T12:02:00Z")
    assert posting.post_approved(draft, state) == "posted"
    send.assert_called_once_with(original["drafts"][0]["text"], media_png=None, alt_text=None)
    assert len(persisted) == 1 and persisted[0]["publish_ledger"][draft["event_id"]]["phase"] == "submitted"
    assert approval_is_current(draft, "manual")
    assert qualifying_publication_context(state["publish_ledger"][draft["event_id"]], draft["event_id"]) is None


@pytest.mark.parametrize("path", ["revision_history", "revision_conflicts", "published_revision", "attempt_conflicts"])
def test_nested_new_passive_unicode_is_merge_safe_and_python_js_identical(path):
    from src.editorial.revisions import normalize_passive_snapshots
    draft = contract_draft()
    malformed = {"bad": {"note": "\ud800"}}
    if path == "attempt_conflicts":
        primary = context_receipt(draft)
        alternate = {**deepcopy(primary), "intent_id": "alternate-physical-attempt", "publication_observations": malformed}
        primary["attempt_conflicts"] = [alternate]
        result = _merge_publish_ledger({draft["event_id"]: primary}, {draft["event_id"]: primary})
        rows = [result[draft["event_id"]], *result[draft["event_id"]].get("attempt_conflicts", [])]
        assert len(rows) == 2
        assert any(next(iter(row["publication_observations"].values())).get("passive_unavailable_record") for row in rows)
        paired = node("""
          import {mergePublishLedger} from './lib/state-store.js';let s='';for await(const c of process.stdin)s+=c;
          const v=JSON.parse(s);console.log(JSON.stringify(mergePublishLedger(v,v)));
        """, {draft["event_id"]: primary})
    else:
        if path == "published_revision":
            child = context_receipt(draft)
            child["publication_observations"] = malformed
            draft[path] = child
        else:
            child = deepcopy(draft)
            child["writer_observations"] = malformed
            draft[path] = [child]
        result = _merge_drafts([draft], [draft])
        normalized_child = result[0][path] if path == "published_revision" else result[0][path][0]
        namespace = "publication_observations" if path == "published_revision" else "writer_observations"
        assert next(iter(normalized_child[namespace].values()))["passive_unavailable_record"]["raw_data"]
        paired = node("""
          import {mergeDrafts} from './lib/state-store.js';let s='';for await(const c of process.stdin)s+=c;
          const v=JSON.parse(s);console.log(JSON.stringify(mergeDrafts([v],[v])));
        """, draft)
    assert paired == result
    ordinary = {"text": "\ud800", "review_context": {"source": "\udfff"}, "writer_observations": malformed}
    safe = normalize_passive_snapshots(ordinary)
    assert safe["text"] == ordinary["text"] and safe["review_context"] == ordinary["review_context"]
    with pytest.raises(UnicodeError):
        fingerprint(safe)


def test_new_writer_seed_unicode_has_no_origin_and_preserves_real_send_and_exact_stale_guard(monkeypatch):
    from src import state as real_state
    from src.editorial.revisions import approval_is_current
    draft = contract_draft()
    del draft["writer_observations"]
    draft["review_context"]["two_bot"]["accepted_writer_observation"] = {"bad": "\ud800"}
    admit_writer_observation(draft)
    assert "writer_observations" not in draft
    bind_reviewed_draft(draft, "manual", "invented-contract-intent")
    state = {"drafts": [draft], "publish_ledger": {}, "posted_events": []}
    original = deepcopy(state)
    assert real_state._expected_draft_matches(original, deepcopy(draft), None)
    for value in ({"bad": "\ud801"}, {"different": "\ud800"}, [], None):
        changed = deepcopy(original)
        changed["drafts"][0]["review_context"]["two_bot"]["accepted_writer_observation"] = value
        assert not real_state._expected_draft_matches(changed, draft, None)
    for sibling in ("bundle", "angle_chosen"):
        changed = deepcopy(original)
        changed["drafts"][0]["review_context"]["two_bot"][sibling] = {"changed": True}
        assert not real_state._expected_draft_matches(changed, draft, None)
    saved = []
    monkeypatch.setattr(real_state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(real_state, "_read_gist_state", lambda **kwargs: deepcopy(original))
    monkeypatch.setattr(real_state, "_write_gist_state", lambda value: saved.append(deepcopy(value)) or True)
    monkeypatch.setattr(posting, "state", real_state)
    send = MagicMock(return_value={"id": "123"})
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "_utc_now_iso", lambda: "2026-10-22T12:02:00Z")
    assert posting.post_approved(draft, state) == "posted"
    send.assert_called_once()
    assert len(saved) == 1 and approval_is_current(draft, "manual")
    assert "publication_observations" not in state["publish_ledger"][draft["event_id"]]
    normalized = saved[0]["drafts"][0]
    assert normalized["review_context"]["two_bot"]["accepted_writer_observation"]["passive_unavailable_record"]["raw_data"]
    paired = node("""
      import {normalizePassiveSnapshots} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      console.log(JSON.stringify(normalizePassiveSnapshots(JSON.parse(s))));
    """, original["drafts"][0])
    assert paired["review_context"]["two_bot"]["accepted_writer_observation"] == normalized["review_context"]["two_bot"]["accepted_writer_observation"]


def test_review_p30_h3_01_distinct_raw_unicode_and_envelope_survive_merge_and_roundtrip():
    from src.editorial.revisions import passive_comparison_value
    raw = {"note": "\ud800"}
    envelope = {"unavailable_unicode_json": passive_comparison_value(raw)}
    container_envelope = {"unavailable_container": None}
    unicode_variants = merge_passive_maps({"raw": raw, "raw_envelope": envelope})
    container_variants = merge_passive_maps(None, {"raw_envelope": container_envelope})
    assert len(unicode_variants) == 2
    assert len(container_variants) == 2
    for variants in (unicode_variants, container_variants):
        roundtrip = json.loads(json.dumps(variants))
        assert merge_passive_maps(roundtrip, roundtrip) == variants
        assert merge_passive_maps(variants) == variants
    assert unicode_variants == merge_passive_maps({"raw_envelope": envelope}, {"raw": raw})
    assert container_variants == merge_passive_maps({"raw_envelope": container_envelope}, None)
    paired = node("""
      import {mergePassiveMaps} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s),unicode=mergePassiveMaps({raw:v.raw,raw_envelope:v.envelope}),container=mergePassiveMaps(null,{raw_envelope:v.container});
      console.log(JSON.stringify({unicode,container,unicode_reload:mergePassiveMaps(JSON.parse(JSON.stringify(unicode))),container_reload:mergePassiveMaps(JSON.parse(JSON.stringify(container)))}));
    """, {"raw": raw, "envelope": envelope, "container": container_envelope})
    assert paired == {"unicode": unicode_variants, "container": container_variants,
        "unicode_reload": unicode_variants, "container_reload": container_variants}


@pytest.mark.parametrize("category", ["unicode_payload", "container"])
def test_review_p30_h3_01_raw_codec_envelope_and_validated_reload_are_distinct(category):
    from src.editorial.revisions import _decode_passive_data, passive_comparison_value
    raw = {"note": "\ud800"} if category == "unicode_payload" else None
    encoded = merge_passive_maps({"raw": raw}) if category == "unicode_payload" else merge_passive_maps(raw)
    key, frame = next(iter(encoded.items()))
    assert key.startswith("unavailable-v1:")
    record = frame["passive_unavailable_record"]
    assert record["schema_version"] == 1 and record["category"] == category
    assert record["raw_data"] == passive_comparison_value(raw)
    assert _decode_passive_data(json.loads(record["raw_data"])) == raw
    raw_frame = {"ordinary": deepcopy(frame)}
    combined = merge_passive_maps(encoded, raw_frame)
    assert len(combined) == 2 and fingerprint(frame) in combined and key in combined
    assert combined[fingerprint(frame)] == frame == combined[key]
    assert combined == merge_passive_maps(raw_frame, encoded)
    for _ in range(3):
        combined = merge_passive_maps(json.loads(json.dumps(combined)), combined)
        assert len(combined) == 2
    paired = node("""
      import {mergePassiveMaps} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s);let combined=mergePassiveMaps(v.encoded,{ordinary:v.frame});
      for(let index=0;index<3;index++)combined=mergePassiveMaps(JSON.parse(JSON.stringify(combined)),combined);
      console.log(JSON.stringify(combined));
    """, {"encoded": encoded, "frame": frame})
    assert paired == combined
    draft = contract_draft()
    original = deepcopy(draft["writer_observations"])
    assert list(original) == [fingerprint(next(iter(original.values())))]
    draft["writer_observations"] = encoded
    assert qualifying_publication_context(context_receipt(draft), draft["event_id"]) is None


@pytest.mark.parametrize("corruption", ["key", "frame_key", "version", "type", "category", "data", "whitespace", "ascii", "valid_unicode", "object_container", "duplicate_keys", "nonfinite", "negative_zero"])
def test_review_p30_h3_01_unverified_unavailable_framing_stays_raw_and_preserves_alternatives(corruption):
    from src.editorial.revisions import passive_comparison_value
    encoded = merge_passive_maps({"raw": {"note": "\ud800"}})
    key, original_frame = next(iter(encoded.items()))
    frame = deepcopy(original_frame)
    record = frame["passive_unavailable_record"]
    bad_key = key
    if corruption == "key":
        bad_key = "unavailable-v1:" + "0" * 64
    elif corruption == "frame_key":
        frame = {"unexpected": record}
    elif corruption == "version":
        record["schema_version"] = 2
    elif corruption == "type":
        record["schema_version"] = True
    elif corruption == "category":
        record["category"] = "writer_origin"
    elif corruption == "data":
        record["raw_data"] = passive_comparison_value({"note": "\ud801"})
    elif corruption == "whitespace":
        record["raw_data"] = " " + record["raw_data"]
    elif corruption == "ascii":
        record["raw_data"] = passive_comparison_value("café").replace("\\u00e9", "é")
    elif corruption == "valid_unicode":
        record["raw_data"] = passive_comparison_value({"note": "ordinary"})
    elif corruption == "object_container":
        record["category"] = "container"
        record["raw_data"] = passive_comparison_value({})
    elif corruption == "duplicate_keys":
        record["raw_data"] = '["object",[["a",["null"]],["a",["null"]]]]'
    elif corruption == "nonfinite":
        record["raw_data"] = '["number","7ff0000000000000"]'
    else:
        record["raw_data"] = '["number","8000000000000000"]'
    raw_key = fingerprint(frame)
    mixed = merge_passive_maps(encoded, {bad_key: frame})
    assert len(mixed) == 2 and raw_key in mixed and key in mixed
    assert mixed[raw_key] == frame and mixed[key] == original_frame
    assert merge_passive_maps(json.loads(json.dumps(mixed)), mixed) == mixed
    assert merge_passive_maps({bad_key: frame}, encoded) == mixed
    paired = node("""
      import {mergePassiveMaps} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s);console.log(JSON.stringify(mergePassiveMaps(v.encoded,{[v.key]:v.frame})));
    """, {"encoded": encoded, "key": bad_key, "frame": frame})
    assert paired == mixed


def test_review_p30_h3_01_actual_storage_preserves_raw_and_framed_variants_without_origin(monkeypatch):
    from src import state as real_state
    from src.editorial.revisions import approval_is_current
    raw = {"note": "\ud800"}
    encoded = merge_passive_maps({"raw": raw})
    frame = deepcopy(next(iter(encoded.values())))
    expected = merge_passive_maps(encoded, {"ordinary_frame": frame})
    draft = contract_draft()
    draft["writer_observations"] = merge_passive_maps({"raw": raw, "ordinary_frame": frame})
    bind_reviewed_draft(draft, "manual", "invented-contract-intent")
    state = {"drafts": [draft], "publish_ledger": {}, "posted_events": []}
    original = deepcopy(state)
    assert real_state._expected_draft_matches(original, deepcopy(draft), None)
    changed = deepcopy(original)
    changed["drafts"][0]["writer_observations"] = {"ordinary_frame": frame}
    assert not real_state._expected_draft_matches(changed, draft, None)
    stored = []
    monkeypatch.setattr(real_state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(real_state, "_read_gist_state", lambda **kwargs: deepcopy(original))
    monkeypatch.setattr(real_state, "_write_gist_state", lambda value: stored.append(json.loads(json.dumps(value))) or True)
    monkeypatch.setattr(posting, "state", real_state)
    send = MagicMock(return_value={"id": "123"})
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "_utc_now_iso", lambda: "2026-10-22T12:02:00Z")
    assert posting.post_approved(draft, state) == "posted"
    send.assert_called_once()
    assert approval_is_current(draft, "manual")
    assert len(stored) == 1 and stored[0]["drafts"][0]["writer_observations"] == expected
    assert len(expected) == 2
    assert _merge_drafts(stored[0]["drafts"], stored[0]["drafts"])[0]["writer_observations"] == expected
    receipt = state["publish_ledger"][draft["event_id"]]
    assert next(iter(receipt["publication_observations"].values()))["writer_observations"] == expected
    assert qualifying_publication_context(receipt, draft["event_id"]) is None
    metrics = append_sample(None, tweet_id="123", counts={"likes": 0},
        sampled_at=datetime(2026, 10, 22, 13, tzinfo=UTC), state=state)
    assert "publication_context_sha256" not in next(iter(metrics["samples"].values()))


@pytest.mark.parametrize("token,recognized", [("1", True), ("1.0", True), ("1e0", True), ("true", False), ('"1"', False), ("0", False), ("2", False)])
def test_review_p30_h3_01_codec_version_literal_json_has_shared_numeric_semantics(token, recognized):
    valid = merge_passive_maps(None)
    literal = json.dumps(valid, separators=(",", ":")).replace('"schema_version":1', '"schema_version":' + token, 1)
    parsed = json.loads(literal)
    direct = merge_passive_maps(parsed)
    combined = merge_passive_maps(valid, parsed)
    frame = next(iter(parsed.values()))
    assert merge_passive_maps({"unverified": frame}) == {fingerprint(frame): frame}
    assert len(combined) == (1 if recognized else 2)
    assert combined == merge_passive_maps(parsed, valid)
    assert merge_passive_maps(json.loads(json.dumps(combined)), combined) == combined
    assert merge_passive_maps(json.loads(json.dumps(direct))) == direct
    paired = node("""
      import {mergePassiveMaps} from './lib/draft-revisions.js';let s='';for await(const c of process.stdin)s+=c;
      const v=JSON.parse(s),parsed=JSON.parse(v.literal),direct=mergePassiveMaps(parsed),combined=mergePassiveMaps(v.valid,parsed);
      console.log(JSON.stringify({direct,combined,reverse:mergePassiveMaps(parsed,v.valid),reload:mergePassiveMaps(JSON.parse(JSON.stringify(combined)),combined),direct_reload:mergePassiveMaps(JSON.parse(JSON.stringify(direct)))}));
    """, {"literal": literal, "valid": valid})
    assert paired == {"direct": direct, "combined": combined, "reverse": combined,
        "reload": combined, "direct_reload": direct}
