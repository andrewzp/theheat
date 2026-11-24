"""NEW local PG fixture: source-mapped fire history through the actual writer.

Every map, incident, publication text and identifier here is invented. No real
weather, provider, hosted database, account or X platform request is performed.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import os
import re
import threading
import uuid

import pytest

from src.data import nifc_perimeter as source
from src.orchestrator.fire_episodes import prepare_fire_request
from src.state import DEFAULT_STATE
from src.storage import fire_episodes as fire, postgres_projection as p
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.fire_perimeter import build_fire_perimeter_bundle
from src.two_bot.memory import (build_memory_slice, bundle_memory_snapshot,
    record_shipped, _story_bundle_from_metadata)
from src.two_bot.types import WriterResult
from src.two_bot.writer import build_writer_user_prompt
from tests import test_postgres_projection as pg
from tests.test_nifc_perimeter import INCIDENT, CAPTURED, SOURCE, body, feature, ms

cluster, database, repository = pg.cluster, pg.database, pg.repository
BASE = "ab68cdb98cda4ff6cb48ff625cc6ab65d146a705"
EPISODE = fire.episode_id(INCIDENT)
NOW = "2026-11-22T12:00:00Z"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for key in tuple(os.environ):
        if (key.startswith(("PG", "AWS_", "TWITTER_", "BLUESKY_", "X_API_"))
            or re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$", key)
            or key in {"NODE_ENV", "THEHEAT_ENVIRONMENT"}):
            monkeypatch.delenv(key)


def capture(session, f=None, *, captured_at=CAPTURED, capture_id=None):
    raw = json.dumps(body(f or feature())).encode()
    identity = capture_id or str(uuid.uuid4())
    receipt, restored = session.retain_capture(raw, capture_id=identity,
        captured_at=captured_at, producer_revision=BASE, source_url=SOURCE)
    assert restored.raw_bytes == raw
    return identity, receipt, restored


def apply(session, captured, *, expected=None, operation=None, incident=INCIDENT):
    capture_id, receipt, _ = captured
    return session.apply_capture(capture_id, receipt.canonical_sha256, incident,
        expected_head=expected, operation_id=operation or str(uuid.uuid4()))


def expanded(*, captured="2026-11-22T06:00:00Z", **attrs):
    f = feature(poly_PolygonDateTime=ms(captured), poly_GISAcres=33000.0, **attrs)
    f["geometry"]["rings"][0] = [[-120., 40.], [-120., 40.15], [-119.85, 40.15],
                                   [-119.85, 40.], [-120., 40.]]
    return f


def seed(repo):
    session = fire.FireEpisodeSession(repo)
    first = capture(session)
    initial = apply(session, first)
    context, _ = session.prepare_story_context(EPISODE, initial["revision_sha256"], now=NOW)
    second = capture(session, expanded())
    final = apply(session, second, expected=initial["revision_sha256"])
    return session, first, initial, context, second, final


def test_actual_retention_memory_audit_request_and_snapshot_roundtrip(repository):
    session, first, initial, context, second, final = seed(repository[1])
    # A previous context is genuinely stale after the second immutable head.
    with pytest.raises(ValueError, match="fire_head_changed"):
        build_fire_perimeter_bundle(context)
    snapshot = deepcopy(DEFAULT_STATE)
    old_binding = context.binding
    snapshot["memory"]["shipped_tweets"] = [dict(tweet_text="Invented prior dated map.",
        tweet_id="123456789", shipped_at="2026-11-21T15:00:00Z", signal_kind="source_mapped_fire_perimeter",
        physical_episode=old_binding, event_id="invented-old", country="")]
    snapshot["memory"]["ongoing_events"] = [dict(physical_episode=old_binding,
        days_running=999, first_seen="1900-01-01", tweet_text="Invented duration poison")]
    before = deepcopy(snapshot)
    current_context, _ = session.prepare_story_context(EPISODE, final["revision_sha256"], now=NOW)
    audited = audit_story_bundle(build_fire_perimeter_bundle(current_context), episode_context=current_context)
    assert audited.prompt_ready, audited.issues
    result = prepare_fire_request(session, EPISODE, final["revision_sha256"], snapshot, now=NOW)
    assert snapshot == before and result["provider_transport"] == "not_attempted"
    assert result["callback_enrollment"] == "not_supported" and result["evidence_prompt_ready"]
    memory = result["memory"]
    assert memory["recent_tweets_same_event"] == ["Invented prior dated map."]
    maps = memory["ongoing_event"]["dated_source_maps"]
    assert [row["polygon_captured_at"] for row in maps] == ["2026-11-21T12:00:00Z", "2026-11-22T06:00:00Z"]
    assert [row["source_area_acres"] for row in maps] == [23700., 33000.]
    actual = result["writer_request"]["messages"][0]["content"]
    assert "33000" in actual and "23700" in actual and "invented-method-a" in actual
    assert "2026-11-21T12:00:00Z" in actual and "days_running" not in actual and "1900-01-01" not in actual
    assert "Invented duration poison" not in actual
    current, _ = session.prepare_story_context(EPISODE, final["revision_sha256"], now=NOW)
    bundle = build_fire_perimeter_bundle(current)
    assert not audit_story_bundle(bundle).prompt_ready  # no resolver, no pass
    assert audit_story_bundle(bundle, episode_context=current).prompt_ready
    metadata = bundle_memory_snapshot(bundle)
    restored = _story_bundle_from_metadata({"bundle": metadata}, {"id": "invented"})
    assert restored is not None and restored.raw_signal_dump["physical_episode"] == current.binding
    # Miniature publication snapshots are bookkeeping, never generation proof.
    assert not audit_story_bundle(restored, episode_context=current).prompt_ready
    fresh = deepcopy(DEFAULT_STATE)
    record_shipped(fresh, restored, WriterResult(tweet="Invented map copy.", kill_reason=None, angle_chosen="", era_anchor_used=None, peer_comparison_used=None, reasoning="Invented fixture"), [],
        tweet_id="987654321", shipped_at=NOW)
    assert not fresh["memory"]["ongoing_events"]
    assert fresh["memory"]["shipped_tweets"][0]["physical_episode"] == current.binding
    assert session.read_capture(first[0], expected_sha=first[1].canonical_sha256)[1].raw_bytes == first[2].raw_bytes


def test_retrieval_edits_names_and_ring_start_do_not_buy_an_opportunity(repository):
    session = fire.FireEpisodeSession(repository[1])
    first = capture(session)
    result = apply(session, first)
    before = session.read_current(EPISODE)
    changed = feature(poly_IncidentName="Different administrative label", poly_DateCurrent=ms(NOW))
    ring = changed["geometry"]["rings"][0]
    changed["geometry"]["rings"][0] = ring[1:-1] + [ring[0], ring[1]]
    duplicate = capture(session, changed, captured_at="2026-11-22T13:00:00Z")
    assert apply(session, duplicate, expected=result["revision_sha256"])["status"] == "duplicate"
    assert session.read_current(EPISODE) == before
    # An area-only report edit and a tiny map change are retained editions but
    # cannot mint another material map opportunity or refresh its source time.
    changed = feature(poly_GISAcres=33000., poly_PolygonDateTime=ms("2026-11-22T06:00:00Z"))
    newer = apply(session, capture(session, changed), expected=result["revision_sha256"])
    revision = session.read_current(EPISODE)[1]
    assert len(revision["derived"]["opportunities"]) == 1
    prepared = prepare_fire_request(session, EPISODE, newer["revision_sha256"], deepcopy(DEFAULT_STATE), now=NOW)
    assert prepared["bundle"]["when"] == "2026-11-21T12:00:00Z"
    assert prepared["opportunity_id"] == before[1]["derived"]["opportunities"][0]["opportunity_id"]


@pytest.mark.parametrize("reverse", [False, True])
def test_same_date_contradictions_hold_every_consumer_in_either_order(repository, reverse):
    session = fire.FireEpisodeSession(repository[1])
    rows = [feature(), expanded(captured="2026-11-21T12:00:00Z")]
    if reverse:
        rows.reverse()
    first = apply(session, capture(session, rows[0]))
    held = apply(session, capture(session, rows[1]), expected=first["revision_sha256"])
    assert held["status"] == "held"
    assert "conflicting_dated_maps" in session.read_current(EPISODE)[1]["derived"]["holds"]
    with pytest.raises(ValueError, match="fire_episode_held"):
        prepare_fire_request(session, EPISODE, held["revision_sha256"], deepcopy(DEFAULT_STATE), now=NOW)


@pytest.mark.parametrize("attrs", [{"poly_Source": "Different source"}, {"poly_MapMethod": "invented-method-b"}])
def test_changed_mapping_provenance_is_not_a_comparable_update(repository, attrs):
    session = fire.FireEpisodeSession(repository[1])
    first = apply(session, capture(session))
    held = apply(session, capture(session, expanded(**attrs)), expected=first["revision_sha256"])
    assert held["status"] == "held"
    with pytest.raises(ValueError, match="fire_episode_held"):
        session.prepare_story_context(EPISODE, held["revision_sha256"], now=NOW)


def test_same_name_geometry_other_id_and_unknown_delivery_cannot_supply_map_memory(repository):
    session, _, _, _, _, final = seed(repository[1])
    other = "33333333-3333-4333-8333-333333333333"
    different = expanded(poly_IRWINID=other, attr_IrwinID=other, poly_SourceGlobalID="44444444-4444-4444-8444-444444444444")
    other_result = apply(session, capture(session, different), incident=other)
    other_context, _ = session.prepare_story_context(fire.episode_id(other), other_result["revision_sha256"], now=NOW)
    own_context, _ = session.prepare_story_context(EPISODE, final["revision_sha256"], now=NOW)
    state = deepcopy(DEFAULT_STATE)
    state["memory"]["shipped_tweets"] = [
        dict(physical_episode=other_context.binding, tweet_id="123", tweet_text="Other incident poison"),
        dict(physical_episode=own_context.binding, tweet_id="456", delivery_state="unknown", tweet_text="Unknown delivery poison"),
        dict(physical_episode=own_context.binding, tweet_text="Missing receipt poison"),
        dict(event_id=INCIDENT, signal_kind="reported_fire_incident_size", tweet_text="Point report poison"),
        dict(event_id=INCIDENT, signal_kind="fire", tweet_text="Sensor pixel poison")]
    with pytest.raises(ValueError, match="fire_unknown_delivery"):
        prepare_fire_request(session, EPISODE, final["revision_sha256"], state, now=NOW)
    state["memory"]["shipped_tweets"].pop(1)  # explicit unknown stays fenced; absent receipt stays excluded
    result = prepare_fire_request(session, EPISODE, final["revision_sha256"], state, now=NOW)
    assert result["memory"]["recent_tweets_same_event"] == []
    assert "Unknown delivery poison" not in result["writer_request"]["messages"][0]["content"]
    assert "Missing receipt poison" not in result["writer_request"]["messages"][0]["content"]
    assert len(result["memory"]["ongoing_event"]["dated_source_maps"]) == 2
    assert len(session.read_current(fire.episode_id(other))[1]["derived"]["maps"]) == 1


def test_stale_or_forged_context_and_mutated_bundle_refuse_before_request(repository):
    session, _, _, _, _, final = seed(repository[1])
    context, _ = session.prepare_story_context(EPISODE, final["revision_sha256"], now=NOW)
    bundle = build_fire_perimeter_bundle(context)
    memory = build_memory_slice(deepcopy(DEFAULT_STATE), bundle, episode_context=context)
    memory.ongoing_event["days_running"] = 999
    with pytest.raises(ValueError, match="resolved_fire_memory_required"):
        build_writer_user_prompt(bundle, memory, episode_context=context)
    with pytest.raises(ValueError):
        build_writer_user_prompt(bundle, build_memory_slice(deepcopy(DEFAULT_STATE), bundle,
            episode_context=context), episode_context=True)
    bundle.headline_metric["value"] = 999999
    assert not audit_story_bundle(bundle, episode_context=context).prompt_ready
    with pytest.raises(ValueError, match="resolved_fire_context_required"):
        build_memory_slice(deepcopy(DEFAULT_STATE), bundle, episode_context=context)
    with pytest.raises(ValueError, match="fire_map_not_current"):
        prepare_fire_request(session, EPISODE, final["revision_sha256"], deepcopy(DEFAULT_STATE),
                             now="2026-11-25T00:00:00Z")


def test_final_head_and_policy_drift_during_real_request_preparation_refuse(repository, monkeypatch):
    from src.two_bot import writer
    from src.editorial import policy
    session, _, _, _, _, final = seed(repository[1])
    builder = writer.anthropic_writer_request
    def advance(prompt):
        next_map = expanded(captured="2026-11-22T07:00:00Z")
        apply(session, capture(session, next_map), expected=final["revision_sha256"])
        return builder(prompt)
    monkeypatch.setattr(writer, "anthropic_writer_request", advance)
    with pytest.raises(ValueError, match="fire_head_changed"):
        prepare_fire_request(session, EPISODE, final["revision_sha256"], deepcopy(DEFAULT_STATE), now=NOW)
    monkeypatch.setattr(writer, "anthropic_writer_request", builder)
    head = session.read_current(EPISODE)[0].canonical_sha256
    original = policy.current_editorial_policy
    def switch(prompt):
        monkeypatch.setattr(policy, "current_editorial_policy", lambda: {"changed": True})
        return builder(prompt)
    monkeypatch.setattr(writer, "anthropic_writer_request", switch)
    with pytest.raises(ValueError, match="fire_policy_changed"):
        prepare_fire_request(session, EPISODE, head, deepcopy(DEFAULT_STATE), now=NOW)
    monkeypatch.setattr(policy, "current_editorial_policy", original)


def test_real_concurrent_expected_head_only_one_commit_and_exact_operation_replay(repository):
    session = fire.FireEpisodeSession(repository[1])
    first = capture(session)
    barrier = threading.Barrier(2)
    operation = str(uuid.uuid4())
    def write(_):
        barrier.wait(timeout=5)
        return apply(session, first, operation=operation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [0, 1]))
    assert results[0] == results[1] and results[0]["status"] == "committed"
    assert session.read_current(EPISODE)[1]["sequence"] == 1
    next_map = capture(session, expanded())
    with pytest.raises(ValueError, match="fire_operation_conflict"):
        apply(session, next_map, operation=operation)
    with pytest.raises(ValueError, match="fire_head_changed"):
        apply(session, next_map)


def test_retained_decode_guards_point_pixel_status_and_missing_capture_time(repository):
    session = fire.FireEpisodeSession(repository[1])
    for attrs in ({"poly_PolygonDateTime": None}, {"attr_IsCpxChild": 1},
                  {"poly_FeatureAccess": "Private"}, {"attr_IncidentTypeCategory": "RX"}):
        with pytest.raises(ValueError):
            capture(session, feature(**attrs))
    assert pg.counts(repository[2]) == [0, 0, 0]


def test_old_nhc_binding_stays_a_separate_closed_type(repository):
    from src.storage.physical_events import validate_binding
    session, _, _, _, _, final = seed(repository[1])
    context, _ = session.prepare_story_context(EPISODE, final["revision_sha256"], now=NOW)
    with pytest.raises(ValueError):
        validate_binding(context.binding)
    with pytest.raises(ValueError):
        fire.validate_binding(dict(context.binding, identity_class="source_scoped"))


def test_late_earlier_map_is_held_instead_of_rewriting_opportunity_history(repository):
    session = fire.FireEpisodeSession(repository[1])
    newest = apply(session, capture(session, expanded()))
    held = apply(session, capture(session), expected=newest["revision_sha256"])
    assert held["status"] == "held"
    assert "late_dated_map_review_required" in session.read_current(EPISODE)[1]["derived"]["holds"]


def test_lost_commit_ack_is_read_once_and_never_rewrites_or_reacquires(repository, monkeypatch):
    session = fire.FireEpisodeSession(repository[1])
    original = session.repository._connection
    writes = []
    @contextmanager
    def lose_write_ack(*, writing=False):
        with original(writing=writing) as connection:
            yield connection
        if writing:
            writes.append(True)
            raise p.ProjectionError("write_outcome_unknown")
    with monkeypatch.context() as patch:
        patch.setattr(session.repository, "_connection", lose_write_ack)
        retained = capture(session)
        result = apply(session, retained)
    assert len(writes) == 2  # one committed capture and one committed operation
    assert result["status"] == "committed"
    assert session.read_current(EPISODE)[1]["sequence"] == 1
    assert len(session.read_current(EPISODE)[1]["members"]) == 1
    assert pg.admin(repository[2], f"SELECT count(*) FROM {p.SCHEMA}.versions")[0][0] == 4


def test_concurrent_distinct_operations_with_same_old_head_cannot_both_advance(repository):
    session = fire.FireEpisodeSession(repository[1])
    first = apply(session, capture(session))
    second = capture(session, expanded())
    third = capture(session, expanded(captured="2026-11-22T07:00:00Z"))
    barrier = threading.Barrier(2)
    def write(captured):
        barrier.wait(timeout=5)
        try:
            return apply(session, captured, expected=first["revision_sha256"])["status"]
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [second, third]))
    assert sorted(results) == ["committed", "fire_head_changed"]
    assert session.read_current(EPISODE)[1]["sequence"] == 2


def test_source_polygon_ownership_conflict_across_captures_cannot_create_second_episode(repository):
    session = fire.FireEpisodeSession(repository[1])
    capture(session)
    before = pg.counts(repository[2])
    other = "33333333-3333-4333-8333-333333333333"
    with pytest.raises(p.ProjectionError, match="projection_idempotency_conflict"):
        capture(session, feature(poly_IRWINID=other, attr_IrwinID=other))
    assert pg.counts(repository[2]) == before


@pytest.mark.parametrize("area,expected", [(105., 1), (105.00001, 2)])
def test_existing_five_percent_materiality_equality_does_not_buy_an_opportunity(repository, area, expected):
    session = fire.FireEpisodeSession(repository[1])
    first = apply(session, capture(session, feature(poly_GISAcres=100.)))
    new_map = expanded()
    new_map["attributes"]["poly_GISAcres"] = area
    apply(session, capture(session, new_map), expected=first["revision_sha256"])
    assert len(session.read_current(EPISODE)[1]["derived"]["opportunities"]) == expected


@pytest.mark.parametrize("clock", ["2026-11-22T09:00:00Z", "2026-11-22T11:59:59Z"])
def test_as_of_request_cannot_use_later_retained_capture_or_nonmaterial_map(repository, clock):
    session = fire.FireEpisodeSession(repository[1])
    first = apply(session, capture(session))
    newer = feature(poly_PolygonDateTime=ms("2026-11-22T10:00:00Z"))
    head = apply(session, capture(session, newer), expected=first["revision_sha256"])
    with pytest.raises(ValueError, match="fire_future_evidence"):
        prepare_fire_request(session, EPISODE, head["revision_sha256"], deepcopy(DEFAULT_STATE), now=clock)


def test_whole_second_map_precedes_later_millisecond_in_actual_bundle_history(repository):
    session = fire.FireEpisodeSession(repository[1])
    first = apply(session, capture(session))
    later = expanded(captured="2026-11-21T12:00:00.001000Z")
    head = apply(session, capture(session, later), expected=first["revision_sha256"])
    result = prepare_fire_request(session, EPISODE, head["revision_sha256"], deepcopy(DEFAULT_STATE), now=NOW)
    assert result["bundle"]["historical_context"]["dated_source_maps"][0]["polygon_captured_at"] == "2026-11-21T12:00:00Z"


@pytest.mark.parametrize("where", ["draft", "draft_id", "ledger", "conflict", "memory", "ledger_receipt", "conflict_receipt"])
def test_explicit_unknown_attempt_fences_request_even_with_a_numeric_receipt(repository, where):
    session, _, initial, old_context, _, final = seed(repository[1])
    state = deepcopy(DEFAULT_STATE)
    unknown = dict(id="invented-unresolved", event_id="mapped-fire:"
        + session.repository.read(fire.REVISION, fire._prefix(EPISODE) + "0000000001")[1]["derived"]["opportunities"][0]["opportunity_id"],
        text="Invented prior copy.", physical_episode=old_context.binding, publish_outcome="unknown", tweet_id="123")
    if where == "draft":
        state["drafts"] = [unknown]
    elif where == "draft_id":
        fallback = {**unknown, "id": unknown["event_id"]}
        fallback.pop("event_id")
        state["drafts"] = [fallback]
    elif where == "memory":
        state["memory"]["shipped_tweets"] = [unknown]
    elif where in {"ledger_receipt", "conflict_receipt"}:
        state["drafts"] = [{**unknown, "publish_outcome": "confirmed", "status": "posted"}]
        state["publish_ledger"][unknown["event_id"]] = dict(phase="unknown" if where == "ledger_receipt" else "confirmed",
            tweet_id="123", text=unknown["text"], attempt_conflicts=([] if where == "ledger_receipt" else
                [dict(phase="unknown", tweet_id="123", text=unknown["text"])]))
    else:
        state["publish_ledger"][unknown["event_id"]] = ({"attempt_conflicts": [{"phase": "unknown"}],
            "tweet_id": "123", "text": unknown["text"]} if where == "conflict" else {"phase": "unknown"})
    before = deepcopy(state)
    with pytest.raises(ValueError, match="fire_unknown_delivery"):
        prepare_fire_request(session, EPISODE, final["revision_sha256"], state, now=NOW)
    assert state == before
    # Explicitly resolved prior-copy history permits the distinct material map.
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [{**unknown, "publish_outcome": "confirmed", "status": "posted"}]
    state["publish_ledger"][unknown["event_id"]] = dict(phase="confirmed", tweet_id="123", text=unknown["text"])
    assert prepare_fire_request(session, EPISODE, final["revision_sha256"], state, now=NOW)["provider_transport"] == "not_attempted"
    # An unrelated incident's unknown attempt cannot suppress this incident.
    state["drafts"][0]["publish_outcome"] = "unknown"
    state["drafts"][0]["event_id"] = "other-invented-event"
    state["drafts"][0]["physical_episode"] = {**old_context.binding, "episode_id": "ep1:fire:nifc:33333333-3333-4333-8333-333333333333"}
    state["publish_ledger"] = {}
    assert prepare_fire_request(session, EPISODE, final["revision_sha256"], state, now=NOW)["provider_transport"] == "not_attempted"
