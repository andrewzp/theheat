"""Qualified invented NIFC reports through actual nomination and save consumers.

Identifier text alone cannot merge the two source-owned identifier kinds. HTTP,
SDK and platform fixtures are explicit; nothing here is a real report or post.
"""
from copy import deepcopy
from datetime import timedelta
import json

from freezegun import freeze_time
import pytest

from src import state as store
from src.data import fire_footprint as source
from src.state_schema import NIFC_TIER_TRACKING_UNAVAILABLE
from src.orchestrator.sources import nifc
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.two_bot import pipeline
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.fire import build_fire_footprint_bundle
from src.two_bot.memory import build_memory_slice, bundle_memory_snapshot, record_published_draft
from src.voice import safety
from tests import live_content_harness as h
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_awc_observed_automatic import world as world  # noqa: F401
from tests.test_nifc_reported_area_consumer import NOW, capture as capture, record  # noqa: F401


@pytest.mark.parametrize("reverse", [False, True])
def test_real_nomination_keeps_equal_text_from_distinct_identifier_kinds_separate(
    monkeypatch, world, capture, reverse,
):
    _, state, run, calls, _ = world
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("THEHEAT_HAZARD_EPISODES", "0")
    run.update(id="invented-nifc-identifier-queue", mode="alerts")
    capture["payload"] = {"features": [
        record(UniqueFireIdentifier="shared-source-id", IrwinID="{other-irwin}"),
        record(UniqueFireIdentifier=None, IrwinID="{shared-source-id}"),
    ]}
    if reverse:
        capture["payload"]["features"].reverse()
    with freeze_time(NOW, tick=True):
        nifc.run_fire_footprint(state, run)
    source, = run["sources"]
    assert source["observed"] == source["details"]["qualified_rows"] == 2
    assert len(capture["calls"]) == 1 and calls == []
    queue = state.get("_triage_queue", [])
    assert len(queue) == 2, "Distinct qualified source identifier kinds must not collapse before writing"
    assert len({candidate.event_id for candidate in queue}) == 2
    assert source["promoted"] == 2
    assert state["drafts"] == []


def parsed(capture, at=NOW, **changes):
    changes.setdefault("ModifiedOnDateTime_dt", int((at - timedelta(hours=18)).timestamp() * 1000))
    capture["payload"] = {"features": [record(**changes)]}
    with freeze_time(at):
        return source.fetch_active_fire_perimeters(strict=True)


@pytest.mark.parametrize("preferred,fallback,expected_kind,expected_id", [
    ("same", "other", "UniqueFireIdentifier", "same"),
    (None, "same", "IrwinID", "same"), ("", "{same}", "IrwinID", "same"),
    (" {same} ", "other", "UniqueFireIdentifier", "same"),
    ("Case", None, "UniqueFireIdentifier", "Case"),
    ("case", None, "UniqueFireIdentifier", "case"),
    ("same-extra", None, "UniqueFireIdentifier", "same-extra"),
    ("x" * 100, None, "UniqueFireIdentifier", "x" * 100),
])
def test_actual_parser_identity_is_exact_and_shared_with_snapshot(capture, preferred, fallback, expected_kind, expected_id):
    fc, = parsed(capture, UniqueFireIdentifier=preferred, IrwinID=fallback)
    bundle = build_fire_footprint_bundle(fc)
    identity = bundle_memory_snapshot(bundle)["source_event_identity"]
    assert identity["identifier_kind"] == expected_kind and identity["source_event_id"] == expected_id
    assert fc.complex_id == expected_id
    assert fc.event_id == "nifc_report_v1_" + source.report_tracking_key(fc).rsplit("/", 1)[1] + "_tier3"
    assert audit_story_bundle(bundle).prompt_ready
    other, = parsed(capture, UniqueFireIdentifier=expected_id + "-other" if len(expected_id) < 90 else "other")
    assert other.event_id != fc.event_id


@pytest.mark.parametrize("preferred,fallback", [
    (" ", "valid"), (True, "valid"), ("bad/id", "valid"), ("x" * 101, "valid"),
    (None, None), (None, 7), (None, "bad/id"),
])
def test_invalid_preferred_identifier_is_not_replaced_by_valid_fallback(capture, preferred, fallback):
    assert parsed(capture, UniqueFireIdentifier=preferred, IrwinID=fallback) == []


def test_case_full_prefix_and_identifier_kind_do_not_alias_but_descriptions_do_not_create_a_new_incident(capture):
    events = []
    for identifier in ("Case", "case", "Case-more", "Case-even-more"):
        fc, = parsed(capture, UniqueFireIdentifier=identifier)
        events.append(fc.event_id)
    fallback, = parsed(capture, UniqueFireIdentifier=None, IrwinID="Case")
    assert len(set(events + [fallback.event_id])) == 5
    renamed, = parsed(capture, UniqueFireIdentifier="Case", IncidentName="Renamed incident", POOState="US-WA")
    assert renamed.event_id == events[0], "Name and origin-state revisions are not new incidents or footprint changes"
    normalized, = parsed(capture, UniqueFireIdentifier=" {Case} ")
    assert normalized.event_id == events[0]


def test_unqualified_or_disagreeing_packet_never_gains_a_tracking_key(capture):
    fc, = parsed(capture)
    for changed in ("missing", "area", "kind", "event"):
        other = deepcopy(fc)
        if changed == "missing":
            other.evidence = None
        elif changed == "area":
            other.hectares += 1
        elif changed == "event":
            other.event_id += "-other"
        else:
            other.evidence["source_record"]["UniqueFireIdentifier"] = None
            other.evidence["source_record_sha256"] = source._canonical_sha(other.evidence["source_record"])
        with pytest.raises(ValueError, match="nifc_report_unverified"):
            source.report_tracking_key(other)


@pytest.mark.parametrize("kind", ["UniqueFireIdentifier", "IrwinID"])
@pytest.mark.parametrize("legacy", ["watermark", "posted", "pending", "unknown", "memory", "ledger"])
def test_visible_legacy_identity_is_held_free_without_mutation(monkeypatch, world, capture, kind, legacy):
    _, state, run, calls, _ = world
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    old_id = "fire_footprint_shared-source-id_tier3"
    row = {"id": "invented-old-draft", "type": "fire_footprint", "event_id": old_id,
           "status": "pending" if legacy == "pending" else "posted", "text": "Invented old report."}
    if legacy == "watermark":
        state["fire_complex_tiers"]["shared-source-id"] = 1
    elif legacy == "posted":
        state["posted_events"].append(old_id)
    elif legacy in {"pending", "unknown"}:
        state["drafts"].append(row)
        if legacy == "unknown":
            state["publish_ledger"][old_id] = {"phase": "unknown", "draft_id": row["id"]}
    elif legacy == "memory":
        state["memory"]["shipped_tweets"].append(row)
    else:
        state["publish_ledger"][old_id] = {"phase": "unknown"}
    before = deepcopy(state)
    parsed(capture, UniqueFireIdentifier="shared-source-id" if kind == "UniqueFireIdentifier" else None,
           IrwinID="{shared-source-id}")
    run.update(id="invented-legacy-hold", mode="alerts")
    with freeze_time(NOW, tick=True):
        nifc.run_fire_footprint(state, run)
        _drain_and_write_triage_queue(state, run)
    assert calls == [] and run["sources"][-1]["promoted"] == 0
    assert run["sources"][-1]["details"]["admission_holds"] == 1
    assert "saved-tier tracking held" in run["sources"][-1]["note"]
    for key in ("drafts", "posted_events", "publish_ledger", "fire_complex_tiers", "memory"):
        assert state[key] == before[key]


@pytest.mark.parametrize("invalid", [None, True, "3", -1, 6, {}, 3.0])
def test_malformed_saved_tier_cannot_become_a_new_report(capture, invalid):
    fc, = parsed(capture)
    state = deepcopy(store.DEFAULT_STATE)
    state["fire_complex_tiers"][source.report_tracking_key(fc)] = invalid
    holds = []
    before = deepcopy(state)
    assert source.detect_tier_crossings([fc], state, tracking_holds=holds) == []
    assert holds == ["nifc_saved_tier_invalid"] and state == before


@pytest.mark.parametrize("missing", ["root", "malformed-root", "current-watermark", "legacy-event-id"])
def test_missing_tracking_is_not_assumed_fresh(capture, missing):
    fc, = parsed(capture)
    state = deepcopy(store.DEFAULT_STATE)
    if missing == "root":
        del state["fire_complex_tiers"]
    elif missing == "malformed-root":
        state["fire_complex_tiers"] = []
    elif missing == "current-watermark":
        state["drafts"].append({"type": source.KIND, "event_id": fc.event_id, "status": "pending"})
    else:
        state["drafts"].append({"type": "fire_footprint", "status": "posted"})
    holds = []
    assert source.detect_tier_crossings([fc], state, tracking_holds=holds) == [] and len(holds) == 1


@pytest.mark.parametrize("suffix", ["unknown", "99", "-1", "", "3-other"])
def test_malformed_legacy_event_tier_does_not_escape_the_ambiguity_hold(capture, suffix):
    fc, = parsed(capture)
    state = deepcopy(store.DEFAULT_STATE)
    state["posted_events"] = [f"fire_footprint_{fc.complex_id}_tier{suffix}"]
    holds = []
    assert source.detect_tier_crossings([fc], state, tracking_holds=holds) == []
    assert holds == ["nifc_legacy_event_namespace_ambiguous"]


def test_actual_gist_missing_tracking_stays_unknown_through_write_read_and_retention(monkeypatch, world, capture):
    transport, _, _, _, _ = world
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "gist")
    monkeypatch.setattr(store, "GIST_ID", h.GIST_ID)
    monkeypatch.setattr(store, "GITHUB_TOKEN", h.INVENTED_TOKEN)
    raw = deepcopy(store.DEFAULT_STATE)
    del raw["fire_complex_tiers"]
    raw["drafts"] = [{"id": "invented-unrelated-pending", "text": "Keep exactly.", "status": "pending"}]
    transport.gist = {"state.json": json.dumps(raw)}
    fc, = parsed(capture)
    with freeze_time(NOW, tick=True):
        state = store.read_state()
        assert state["fire_complex_tiers"] == {NIFC_TIER_TRACKING_UNAVAILABLE: 0}
        holds = []
        assert source.detect_tier_crossings([fc], state, tracking_holds=holds) == []
        assert holds == ["nifc_tier_tracking_unavailable"]
        assert store.write_state(state)
        restored = store.read_state()
    with freeze_time(NOW + timedelta(days=180)):
        store._prune_tier_store(restored, "fire_complex_tiers", 90, NOW + timedelta(days=180))
        assert restored["fire_complex_tiers"] == {NIFC_TIER_TRACKING_UNAVAILABLE: 0}
        assert store.write_state(restored)
        assert store.read_state()["fire_complex_tiers"] == {NIFC_TIER_TRACKING_UNAVAILABLE: 0}
    assert restored["drafts"] == raw["drafts"] and transport.x_posts == []
    known = deepcopy(store.DEFAULT_STATE)
    known["fire_complex_tiers"]["old-known-key"] = 4
    merged = store._merge_state(restored, known)
    assert merged["fire_complex_tiers"] == {NIFC_TIER_TRACKING_UNAVAILABLE: 0, "old-known-key": 4}
    assert source.detect_tier_crossings([fc], merged) == []


@pytest.mark.parametrize("shape", ["double-encoded-map", "string", "list", "number", "null", "boolean"])
def test_nonobject_gist_root_is_refused_without_normalization_or_history_rewrite(monkeypatch, world, capture, shape):
    transport, _, _, calls, _ = world
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "gist")
    monkeypatch.setattr(store, "GIST_ID", h.GIST_ID)
    monkeypatch.setattr(store, "GITHUB_TOKEN", h.INVENTED_TOKEN)
    fc, = parsed(capture)
    saved = deepcopy(store.DEFAULT_STATE)
    saved["fire_complex_tiers"][source.report_tracking_key(fc)] = fc.tier
    value = {"double-encoded-map": json.dumps(saved), "string": "fire_complex_tiers",
             "list": [saved], "number": 1, "null": None, "boolean": True}[shape]
    raw = json.dumps(value)
    transport.gist = {"state.json": raw}
    with pytest.raises(store.StateReadError, match="root must be a JSON object"):
        store.read_state()
    assert transport.gist == {"state.json": raw}
    assert transport.gist_patches == 0 and transport.x_posts == [] and calls == []


@pytest.mark.parametrize("invalid", [None, [], "unavailable"])
def test_malformed_tracking_is_not_normalized_away_in_durable_merge(capture, invalid):
    raw = deepcopy(store.DEFAULT_STATE)
    raw["fire_complex_tiers"] = invalid
    merged = store._merge_state(raw, deepcopy(raw))
    assert merged["fire_complex_tiers"] == invalid
    fc, = parsed(capture)
    assert source.detect_tier_crossings([fc], merged) == []
    with pytest.raises(ValueError, match="nifc_tier_tracking_unmergeable"):
        store._merge_state(raw, deepcopy(store.DEFAULT_STATE))


def test_full_legacy_identifier_suffix_is_parsed_from_right_before_comparison(capture):
    short, = parsed(capture, UniqueFireIdentifier="Abc")
    long, = parsed(capture, UniqueFireIdentifier="Abc_tierNorth")
    state = deepcopy(store.DEFAULT_STATE)
    state["posted_events"] = [f"fire_footprint_{long.complex_id}_tier3"]
    assert source.detect_tier_crossings([short], state) == [short]
    holds = []
    assert source.detect_tier_crossings([long], state, tracking_holds=holds) == []
    assert holds == ["nifc_legacy_event_namespace_ambiguous"]


def test_storage_key_cannot_be_an_accepted_legacy_identifier_or_shadow_it(capture):
    target, = parsed(capture, UniqueFireIdentifier="Abc")
    key = source.report_tracking_key(target)
    assert parsed(capture, UniqueFireIdentifier=key) == [], "New key is disjoint from the accepted bare-ID grammar"
    old_shaped_key = "nifc_report_v1_" + key.rsplit("/", 1)[1]
    old, = parsed(capture, UniqueFireIdentifier=old_shaped_key)
    assert old.complex_id == old_shaped_key
    state = deepcopy(store.DEFAULT_STATE)
    state["fire_complex_tiers"][old.complex_id] = target.tier
    assert source.detect_tier_crossings([target], state) == [target]
    assert state["fire_complex_tiers"] == {old.complex_id: target.tier}


@pytest.mark.parametrize("retained", ["draft", "posted", "ledger", "memory"])
def test_visible_saved_higher_tier_refuses_a_contradictory_watermark_without_repair(capture, retained):
    current, = parsed(capture)
    higher, = parsed(capture, IncidentSize=1600000.0)
    assert current.tier == 3 and higher.tier == 4
    state = deepcopy(store.DEFAULT_STATE)
    key = source.report_tracking_key(current)
    state["fire_complex_tiers"][key] = 1
    row = {"type": source.KIND, "event_id": higher.event_id, "status": "pending"}
    if retained == "draft":
        state["drafts"].append(row)
    elif retained == "posted":
        state["posted_events"].append(higher.event_id)
    elif retained == "ledger":
        state["publish_ledger"][higher.event_id] = {"phase": "unknown"}
    else:
        state["memory"]["shipped_tweets"].append(row)
    before = deepcopy(state)
    holds = []
    assert source.detect_tier_crossings([current], state, tracking_holds=holds) == []
    assert holds == ["nifc_saved_tier_contradiction"] and state == before
    # A higher watermark with pruned older draft history is valid, not a reset.
    state["fire_complex_tiers"][key] = 5
    holds = []
    assert source.detect_tier_crossings([higher], state, tracking_holds=holds) == [] and holds == []


def test_old_qualified_snapshot_still_supplies_read_only_report_context_but_not_source_admission(capture):
    first, = parsed(capture)
    bundle = build_fire_footprint_bundle(first)
    old_id = f"fire_footprint_{first.complex_id}_tier{first.tier}"
    bundle.event_id = bundle.raw_signal_dump["event_id"] = old_id
    assert source.historical_report_bundle_hold(bundle) is None
    assert source.report_bundle_hold(bundle) == "nifc_report_binding_changed"
    assert not audit_story_bundle(bundle).prompt_ready
    snapshot = bundle_memory_snapshot(bundle)
    assert snapshot["event_id"] == old_id and snapshot["source_event_identity"]["identifier_kind"] == "UniqueFireIdentifier"
    old_draft = {"id": "invented-old-qualified", "type": bundle.signal_kind, "event_id": old_id,
                 "status": "posted", "text": "Invented prior reported-size update.",
                 "tweet_id": "invented-offline-receipt", "posted_at": NOW.isoformat(),
                 "review_context": {"two_bot": {"bundle": snapshot}}}
    state = deepcopy(store.DEFAULT_STATE)
    with freeze_time(NOW):
        assert record_published_draft(state, old_draft)
    current, = parsed(capture, NOW + timedelta(days=1), IncidentSize=1600000.0)
    before = deepcopy(state)
    memory = build_memory_slice(state, build_fire_footprint_bundle(current), now=NOW + timedelta(days=1))
    assert memory.source_report_series["recent_published_texts"] == [old_draft["text"]]
    assert memory.ongoing_event is None and state == before
    # A legacy memory object remains a visible hold at nomination, not a new ID.
    assert source.detect_tier_crossings([current], state) == []
    bundle.raw_signal_dump["hectares"] += 1
    assert source.historical_report_bundle_hold(bundle) == "nifc_report_binding_changed"
    assert "source_event_identity" not in bundle_memory_snapshot(bundle)


def test_actual_save_callback_and_fake_gist_reload_keep_namespaces_independent(monkeypatch, world, capture):
    transport, state, _, calls, _ = world
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("THEHEAT_HAZARD_EPISODES", "0")
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "gist")
    monkeypatch.setattr(store, "GIST_ID", h.GIST_ID)
    monkeypatch.setattr(store, "GITHUB_TOKEN", h.INVENTED_TOKEN)
    transport.gist = {"state.json": json.dumps(state)}
    keys = []
    for day, fallback, acres, expected_save in [(0, False, 800000, True), (1, True, 800000, True),
                                                (2, False, 1600000, True), (3, False, 1600000, False)]:
        at = NOW + timedelta(days=day)
        rows = parsed(capture, at, UniqueFireIdentifier=None if fallback else "shared-source-id",
                      IrwinID="{shared-source-id}", IncidentSize=acres)
        key = source.report_tracking_key(rows[0])
        keys.append(key)
        copy = f"NIFC lists Juniper Fire in Oregon at about {acres:,} acres in its November {(at-timedelta(hours=18)).day} update."
        stages = stage_fakes(calls, copy=copy)
        monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
        monkeypatch.setattr(safety, "check_llm", stages[1])
        monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
        monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
        run = {"id": f"invented-nifc-save-{day}", "mode": "alerts", "sources": []}
        count, old_calls = len(state["drafts"]), len(calls)
        with freeze_time(at, tick=True):
            nifc.run_fire_footprint(state, run)
            _drain_and_write_triage_queue(state, run)
            assert len(state["drafts"]) == count + int(expected_save)
            assert len(calls) == old_calls + (4 if expected_save else 0)
            assert state["fire_complex_tiers"][key] == rows[0].tier
            assert "shared-source-id" not in state["fire_complex_tiers"]
            assert store.write_state(state), "Use the actual durable Gist merge and JSON writer"
            state = store.read_state()
        assert len(state["drafts"]) == count + int(expected_save)
        assert all(d["status"] == "pending" and d["approval_mode"] == "manual" for d in state["drafts"])
        assert not state["publish_ledger"] and transport.x_posts == []
    assert keys[0] != keys[1] and keys[0] == keys[2] == keys[3]
    assert len(state["fire_complex_tiers"]) == 2 and transport.gist_patches == 4
    assert calls == ["writer", "safety", "fact_check", "critic"] * 3
