"""Invented NIFC captures through retained publication memory and real prompts.

No model, source, account or platform access; a fixture receipt is not a post.
"""
from copy import deepcopy
from datetime import timedelta
import json

from freezegun import freeze_time
import pytest

from src.data import fire_footprint as source
from src import state as state_store
from src.state import DEFAULT_STATE
from src.two_bot.intern.fire import build_fire_footprint_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.memory import (build_memory_slice, bundle_memory_snapshot,
                                record_published_draft)
from src.two_bot.writer import anthropic_writer_request, build_writer_user_prompt
from tests.live_content_harness import trap_network
from tests.test_nifc_reported_area_consumer import NOW, capture as capture, record

PRIOR_COPY = "Invented first NIFC report; not real weather or publication."


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)


def report(capture, at=NOW, **changes):
    changes.setdefault("ModifiedOnDateTime_dt", int((at-timedelta(hours=18)).timestamp()*1000))
    capture["payload"] = {"features": [record(**changes)]}
    with freeze_time(at):
        row, = source.fetch_active_fire_perimeters(strict=True)
        return build_fire_footprint_bundle(row)


def published_memory(bundle, at=NOW):
    saved = deepcopy(DEFAULT_STATE)
    snapshot = json.loads(json.dumps(bundle_memory_snapshot(bundle)))
    draft = {"id": "invented-published-nifc", "type": bundle.signal_kind,
             "event_id": bundle.event_id, "status": "posted", "text": PRIOR_COPY,
             "tweet_id": "invented-offline-receipt", "posted_at": at.isoformat(),
             "review_context": {"two_bot": {"bundle": snapshot}}}
    with freeze_time(at):
        assert record_published_draft(saved, draft)
        assert not record_published_draft(saved, draft), "One fixture receipt is recorded once"
    assert len(saved["memory"]["shipped_tweets"]) == 1
    return saved, draft


def test_real_parser_snapshot_recorder_and_prompt_keep_one_official_incident_across_tier_and_region_updates(capture):
    first = report(capture)
    saved, draft = published_memory(first)
    current = report(capture, NOW+timedelta(days=1), IncidentSize=1600000.0, POOState="US-WA")
    assert first.event_id != current.event_id
    before = deepcopy(saved)
    actual = build_memory_slice(saved, current, now=NOW+timedelta(days=1))
    assert actual.source_report_series is not None
    assert actual.source_report_series["recent_published_texts"] == [PRIOR_COPY]
    assert actual.source_report_series["previous_report_context"]["reported_region"] == first.where
    assert actual.recent_tweets_same_event == [] and actual.ongoing_event is None
    assert "days_running" not in json.dumps(actual.source_report_series)
    assert "growth rate" in actual.source_report_series["claim_limit"]
    prompt = build_writer_user_prompt(current, actual)
    assert PRIOR_COPY in prompt and '"ongoing_event": null' in prompt
    request = anthropic_writer_request(prompt)
    assert PRIOR_COPY in json.dumps(request) and "source_report_series" in json.dumps(request)
    assert saved == before and draft["status"] == "posted"
    assert not saved.get("publish_ledger"), "The recorder is not a sender"


def test_snapshot_retains_exact_report_inputs_without_aliasing_the_current_capture(capture):
    first = report(capture)
    snapshot = bundle_memory_snapshot(first)
    identity = snapshot["source_event_identity"]
    assert identity["source_event_id"] == first.raw_signal_dump["complex_id"]
    assert snapshot["raw_signal_dump"] == first.raw_signal_dump
    snapshot["raw_signal_dump"]["evidence"]["source_record"]["IncidentSize"] = -1
    assert first.raw_signal_dump["evidence"]["source_record"]["IncidentSize"] == 800000.0


@pytest.mark.parametrize("changes", [
    {"UniqueFireIdentifier": "2026-OR-EXAMPLE-002"},
    {"UniqueFireIdentifier": "2026-OR-EXAMPLE-001-extra"},
    {"UniqueFireIdentifier": "2026-or-example-001"},
    {"UniqueFireIdentifier": None, "IrwinID": "{2026-OR-EXAMPLE-001}"},
])
def test_same_name_region_and_id_prefix_never_merge_distinct_incident_identifiers(capture, changes):
    saved, _ = published_memory(report(capture))
    current = report(capture, **changes)
    actual = build_memory_slice(saved, current, now=NOW)
    assert actual.ongoing_event is None and actual.recent_tweets_same_event == []
    assert actual.source_report_series is not None
    assert actual.source_report_series["recent_published_texts"] == []
    assert PRIOR_COPY in actual.recent_tweets_same_country  # Explicitly general history.


@pytest.mark.parametrize("change", ["missing-packet", "changed-identity", "changed-fact", "changed-date", "changed-policy-marker"])
def test_unqualified_current_report_keeps_candidate_publication_history_without_source_series(capture, change):
    bundle = report(capture)
    saved, _ = published_memory(bundle)
    if change == "missing-packet":
        bundle.raw_signal_dump.pop("evidence")
    elif change == "changed-identity":
        bundle.raw_signal_dump["complex_id"] = "other"
    elif change == "changed-fact":
        bundle.current_facts[0]["value"] = "Other incident"
    elif change == "changed-date":
        bundle.when = "2000-01-01"
    else:
        bundle.raw_signal_dump["evidence"]["source_product"] = "unrecognized"
    actual = build_memory_slice(saved, bundle, now=NOW)
    assert actual.ongoing_event is None and actual.recent_tweets_same_event == [PRIOR_COPY]
    assert actual.source_report_series is None


def test_retained_report_identity_cannot_be_promoted_from_legacy_or_changed_snapshot(capture):
    first = report(capture)
    saved, draft = published_memory(first)
    payload = draft["review_context"]["two_bot"]["bundle"]
    assert "source_event_identity" in payload
    for change in ("legacy", "changed-record", "changed-identity", "changed-facts"):
        bad = deepcopy(draft)
        bad["tweet_id"] += "-" + change
        packet = bad["review_context"]["two_bot"]["bundle"]
        if change == "legacy":
            packet.pop("raw_signal_dump")
        elif change == "changed-record":
            packet["raw_signal_dump"]["evidence"]["source_record"]["IncidentSize"] *= 2
        elif change == "changed-identity":
            packet["source_event_identity"]["source_event_id"] = "other"
        else:
            packet["current_facts"][0]["value"] = "Other incident"
        state = deepcopy(DEFAULT_STATE)
        with freeze_time(NOW):
            assert record_published_draft(state, bad)
        assert not state["memory"]["ongoing_events"]
        result = build_memory_slice(state, first, now=NOW)
        assert result.source_report_series["recent_published_texts"] == []
    assert len(saved["memory"]["shipped_tweets"]) == 1


def test_fallback_irwin_identity_retains_its_own_report_series_without_aliasing_unique_fire_ids(capture):
    first = report(capture, UniqueFireIdentifier=None, IrwinID="{invented-irwin}")
    saved, _ = published_memory(first)
    current = report(capture, NOW+timedelta(days=1), UniqueFireIdentifier="", IrwinID="{invented-irwin}",
                     IncidentSize=1600000.0)
    actual = build_memory_slice(saved, current, now=NOW+timedelta(days=1))
    assert actual.source_report_series["identity"]["identifier_kind"] == "IrwinID"
    assert actual.source_report_series["recent_published_texts"] == [PRIOR_COPY]
    other = report(capture, UniqueFireIdentifier="invented-irwin", IrwinID=None)
    assert build_memory_slice(saved, other, now=NOW).source_report_series["recent_published_texts"] == []


@pytest.mark.parametrize("change", ["legacy", "null", "schema", "issuer", "event-type", "field-type", "identity-type", "extra"])
def test_unqualified_stored_series_keys_never_grant_history(capture, change):
    bundle = report(capture)
    saved, _ = published_memory(bundle)
    for row in saved["memory"]["shipped_tweets"]:
        key = row["source_event_identity"]
        if change == "legacy":
            row.pop("source_event_identity")
        elif change == "null":
            row["source_event_identity"] = None
        elif change == "schema":
            key["schema"] = "nifc-source-memory/v99"
        elif change == "issuer":
            key["issuer"] = "gdacs-georss"
        elif change == "event-type":
            key["event_type"] = "FL"
        elif change == "field-type":
            key["identifier_kind"] = []
        elif change == "identity-type":
            key["source_event_id"] = 123
        else:
            key["extra"] = "not-supported"
    actual = build_memory_slice(saved, bundle, now=NOW)
    assert actual.source_report_series["previous_report_context"] is None
    assert actual.source_report_series["recent_published_texts"] == []
    assert actual.recent_tweets_same_event == ([PRIOR_COPY] if change in {"legacy", "null"} else [])
    assert actual.ongoing_event is None


def test_oversize_report_keeps_general_publication_history_without_changing_source_qualification(capture):
    bundle = report(capture, ProviderNote="é" * 20000)
    assert audit_story_bundle(bundle).prompt_ready
    snapshot = bundle_memory_snapshot(bundle)
    assert "source_event_identity" not in snapshot and "raw_signal_dump" not in snapshot
    saved, _ = published_memory(bundle)
    actual = build_memory_slice(saved, bundle, now=NOW)
    assert actual.source_report_series["recent_published_texts"] == []
    assert PRIOR_COPY in actual.recent_tweets_same_country
    assert audit_story_bundle(bundle).prompt_ready


def test_oversize_retained_input_cannot_bypass_snapshot_retention_limit(capture):
    bundle = report(capture)
    _, draft = published_memory(bundle)
    draft["review_context"]["two_bot"]["bundle"]["extra"] = "x" * 40000
    saved = deepcopy(DEFAULT_STATE)
    with freeze_time(NOW):
        assert record_published_draft(saved, draft)
    assert saved["memory"]["ongoing_events"] == []
    assert build_memory_slice(saved, bundle, now=NOW).source_report_series["recent_published_texts"] == []


def test_missing_packet_legacy_fire_footprint_is_general_history_only(capture):
    bundle = report(capture)
    saved, _ = published_memory(bundle)
    legacy = deepcopy(bundle)
    legacy.signal_kind = "fire_footprint"
    legacy.raw_signal_dump = {}
    actual = build_memory_slice(saved, legacy, now=NOW)
    assert actual.source_report_series is None and actual.recent_tweets_same_event == [PRIOR_COPY]
    assert actual.ongoing_event is None


def test_other_family_with_nonobject_evidence_does_not_crash_the_shared_reader(capture):
    bundle = report(capture)
    bundle.signal_kind = "invented-other-kind"
    bundle.event_id = "invented-other-event"
    bundle.raw_signal_dump = {"evidence": "not-a-nifc-packet"}
    actual = build_memory_slice(deepcopy(DEFAULT_STATE), bundle, now=NOW)
    assert actual.source_report_series is None and actual.ongoing_event is None


def test_actual_state_merge_and_durable_json_codec_preserve_the_report_history(capture):
    first = report(capture)
    saved, _ = published_memory(first)
    with freeze_time(NOW):
        merged = state_store._merge_state(deepcopy(DEFAULT_STATE), saved)
        wire = json.dumps(state_store._normalize_state(merged), default=state_store.json_default)
        restored = state_store._normalize_state(state_store._decode_gist_state_json(wire))
    current = report(capture, NOW+timedelta(days=1), IncidentSize=1600000.0)
    actual = build_memory_slice(restored, current, now=NOW+timedelta(days=1))
    assert actual.source_report_series["recent_published_texts"] == [PRIOR_COPY]
    assert actual.ongoing_event is None and restored["memory"]["ongoing_events"] == []


@pytest.mark.parametrize("change", ["schema", "headline", "country", "history", "nonobject-packet"])
def test_restore_requires_the_exact_original_qualified_bundle(capture, change):
    bundle = report(capture)
    _, draft = published_memory(bundle)
    packet = draft["review_context"]["two_bot"]["bundle"]
    if change == "schema":
        packet["source_event_identity"]["schema"] = "nifc-source-memory/v99"
    elif change == "headline":
        packet["headline_metric"]["value"] *= 2
    elif change == "country":
        packet["country"] = "CA"
    elif change == "history":
        packet["historical_context"] = {"invented_growth_rate": 20}
    else:
        packet["raw_signal_dump"]["evidence"] = "invalid"
    saved = deepcopy(DEFAULT_STATE)
    with freeze_time(NOW):
        assert record_published_draft(saved, draft)
    actual = build_memory_slice(saved, bundle, now=NOW)
    assert actual.source_report_series["recent_published_texts"] == []
    assert saved["memory"]["ongoing_events"] == []


@pytest.mark.parametrize("change", ["filtered-fact", "filled-date", "filled-kind", "filled-id", "coerced-where"])
def test_generic_restore_repairs_cannot_establish_qualified_report_history(capture, change):
    original = report(capture)
    _, draft = published_memory(original)
    packet = draft["review_context"]["two_bot"]["bundle"]
    changed = deepcopy(original)
    draft["tweet_date"] = original.when
    if change == "filtered-fact":
        packet["current_facts"].append("malformed retained fact")
        changed.current_facts = deepcopy(packet["current_facts"])
    elif change == "filled-date":
        packet["when"] = changed.when = None
    elif change == "filled-kind":
        packet["signal_kind"] = changed.signal_kind = None
    elif change == "filled-id":
        packet["event_id"] = changed.event_id = None
    else:
        packet["where"] = changed.where = None
        draft["city"] = original.where
    assert source.report_bundle_hold(changed) == "nifc_report_binding_changed"
    saved = deepcopy(DEFAULT_STATE)
    with freeze_time(NOW):
        assert record_published_draft(saved, draft), "Generic publication history is still retained"
    current = report(capture, NOW+timedelta(days=1), IncidentSize=1600000.0)
    actual = build_memory_slice(saved, current, now=NOW+timedelta(days=1))
    assert actual.source_report_series["recent_published_texts"] == []
    assert saved["memory"]["ongoing_events"] == []
