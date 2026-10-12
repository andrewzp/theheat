"""Actual PG plus real NHC parsing, intern, audit, memory and request builders.

All meteorology, names, responses and publication memory here are invented.
No real source, model, platform, hosted DB or success callback is invoked.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
import re
import subprocess
import sys
import uuid

import pytest
import responses

from src.data import nhc
from src.data.cyclones import CycloneAdvisory
from src.orchestrator.cyclone_episodes import CycloneEpisodeLane, prepare_episode_requests
from src.orchestrator.cyclones import _process_cyclone_source
from src.state import DEFAULT_STATE
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import CycloneSupplyError, CycloneSupplySession, NAMESPACE, digest
from src.storage.physical_events import (OPERATION, PROPOSAL, REVISION, PhysicalEpisodeSession,
                                         episode_id, forecast_qualified)
from src.two_bot.memory import _story_bundle_from_metadata, bundle_memory_snapshot, record_shipped
from src.two_bot.types import WriterResult
from tests import test_postgres_projection as pg
from tests import test_ghcn_scientific_supply as ghcn_fixtures

cluster, database, repository = pg.cluster, pg.database, pg.repository
supply, supply_inputs = ghcn_fixtures.supply, ghcn_fixtures.supply_inputs
BASE = "d4714c088ddd011b9487ee7da47a6eb7f2cff158"
NOW = "2026-10-11T12:00:00Z"
EPISODE = "ep1:cyclone:nhc:AL012026"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for key in tuple(os.environ):
        if (key.startswith(("PG", "AWS_", "TWITTER_", "BLUESKY_", "X_API_"))
            or re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$", key)
            or key in {"NODE_ENV", "THEHEAT_ENVIRONMENT"}):
            monkeypatch.delenv(key)


def advisory(**kwargs):
    return CycloneAdvisory(**(dict(source="nhc", storm_id="AL012026", storm_name="Invented A",
        basin="Atlantic", advisory_number="1", issued_at="2026-10-11T00:00:00Z", wind_kt=70,
        lat=15.0, lon=-75.0, pressure_mb=980,
        public_advisory_url="https://www.nhc.noaa.gov/text/fixture.shtml") | kwargs))


def capture(repo, rows, *, observations=None, now=NOW, status="success"):
    session = CycloneSupplySession(repo, str(uuid.uuid4()), now, BASE)
    receipt, restored, value = session.capture(rows, {"status": status}, observations=observations)
    assert restored == rows
    return session, receipt, value


def apply(session, receipt, episodes, heads, *, now=NOW, cities=None, operation=None):
    return episodes.apply_retained_run(session.supply_run_id, receipt.canonical_sha256,
        operation_id=operation or str(uuid.uuid4()), expected_heads=heads, now=now, cities=cities or [])


def seed(repo):
    episodes = PhysicalEpisodeSession(repo)
    first, first_receipt, _ = capture(repo, [advisory()])
    result = apply(first, first_receipt, episodes, {EPISODE: None})
    head = result["episodes"][0]["revision_sha256"]
    second, second_receipt, _ = capture(repo, [advisory(advisory_number="2", issued_at="2026-10-11T06:00:00Z", wind_kt=100)])
    result = apply(second, second_receipt, episodes, {EPISODE: head})
    return episodes, result["episodes"][0]["revision_sha256"], second, second_receipt


def forbid(*args, **kwargs):
    raise AssertionError("forbidden acquisition, provider or operational mutation")


def test_retained_complete_episode_actual_story_and_meaningful_dedup(repository, monkeypatch):
    repo = repository[1]
    episodes, head, second, receipt = seed(repo)
    monkeypatch.setattr(nhc, "fetch_active_cyclones", forbid)
    snapshot = deepcopy(DEFAULT_STATE)
    before = deepcopy(snapshot)
    requests = prepare_episode_requests(episodes, EPISODE, head, snapshot, now=NOW)
    assert len(requests) == 1 and snapshot == before
    row = requests[0]
    assert row["bundle"]["signal_kind"] == "cyclone_tier_crossing"
    assert row["bundle"]["raw_signal_dump"]["physical_episode"]["revision_sha256"] == head
    assert row["writer_request"]["messages"][0]["role"] == "user"
    assert "physical_episode" in row["writer_request"]["messages"][0]["content"]
    assert row["provider_transport"] == "not_attempted" and row["callback_enrollment"] == "not_supported"
    _, value = episodes.read_current(EPISODE)
    assert len(value["members"]) == 2 and value["sequence"] == 2
    assert value["observed_at"] == "2026-10-11T06:00:00Z"
    same, same_receipt, _ = capture(repo, second.read()[1], now="2026-10-11T13:00:00Z")
    duplicate = apply(same, same_receipt, episodes, {EPISODE: head})
    assert duplicate["episodes"][0] == dict(episode_id=EPISODE, status="duplicate", revision_sha256=head)
    assert episodes.read_current(EPISODE)[1] == value
    later, later_receipt, _ = capture(repo, [advisory(advisory_number="3", issued_at="2026-10-11T12:00:00Z", wind_kt=100)])
    apply(later, later_receipt, episodes, {EPISODE: head})
    newer_head, newer = episodes.read_current(EPISODE)
    assert len(newer["opportunities"]) == 1 and newer["seen_opportunities"] == value["seen_opportunities"]
    assert newer["opportunities"][0]["opportunity_id"] == row["opportunity_id"]
    with pytest.raises(CycloneSupplyError, match="episode_head_changed"):
        prepare_episode_requests(episodes, EPISODE, head, snapshot, now=NOW)
    rebuilt = prepare_episode_requests(episodes, EPISODE, newer_head.canonical_sha256, snapshot, now=NOW)
    assert rebuilt[0]["opportunity_id"] == row["opportunity_id"]
    assert rebuilt[0]["bundle"]["raw_signal_dump"]["advisory_number"] == "3"


@pytest.mark.parametrize("identifier", ["AL002026", "AL502026", "AL792026", "AL802026", "AL892026", "AL902026", "AL992026", "AL01", "Invented A", "CP012026", "AL010000"])
def test_recycled_investigative_internal_test_and_unscoped_ids_held(repository, identifier):
    repo = repository[1]
    rows = [advisory(storm_id=identifier), advisory(storm_id=identifier, advisory_number="1", issued_at="2026-10-11T06:00:00Z", lat=40.0, storm_name="Different invented storm")]
    session, receipt, _ = capture(repo, rows)
    result = apply(session, receipt, PhysicalEpisodeSession(repo), {})
    assert result["episodes"] == [] and len(result["held"]) == 2
    assert all(row["reason"] == "source_identity_unqualified" for row in result["held"])
    assert len(session.read()[1]) == 2


def test_year_authority_basin_and_potential_status_are_not_inferred(repository):
    repo = repository[1]
    rows = [advisory(storm_id="AL492026", classification="Potential Tropical Cyclone", wind_kt=30),
            advisory(storm_id="AL492025"), advisory(storm_id="EP012026", basin="East Pacific"),
            advisory(storm_id="AL012026", basin="East Pacific"),
            advisory(source="jtwc", storm_id="02W", basin="West Pacific")]
    session, receipt, _ = capture(repo, rows)
    heads = {episode_id(row): None for row in rows if episode_id(row)}
    episodes = PhysicalEpisodeSession(repo)
    result = apply(session, receipt, episodes, heads)
    assert len(result["episodes"]) == 3 and len(result["held"]) == 2
    _, potential = episodes.read_current("ep1:cyclone:nhc:AL492026")
    assert potential["opportunities"] == []
    continuation, continuation_receipt, _ = capture(repo, [advisory(storm_id="AL492026", issued_at="2027-01-01T06:00:00Z", wind_kt=40)])
    apply(continuation, continuation_receipt, episodes, {"ep1:cyclone:nhc:AL492026": digest(potential)}, now="2027-01-01T12:00:00Z")
    assert episodes.read_current("ep1:cyclone:nhc:AL492026")[1]["sequence"] == 2


def test_conflicting_advisory_correction_holds_old_consumer_and_keeps_evidence(repository):
    episodes, head, second, receipt = seed(repository[1])
    original = second.read()
    corrected, corrected_receipt, _ = capture(repository[1], [replace(original[1][0], wind_kt=80)])
    result = apply(corrected, corrected_receipt, episodes, {EPISODE: head})
    assert result["episodes"][0]["status"] == "held"
    _, held = episodes.read_current(EPISODE)
    assert "identity_or_revision_conflict" in held["holds"] and len(held["members"]) == 3
    assert held["correction_notices"][0]["affected_opportunity_ids"]
    assert second.read() == original
    with pytest.raises(CycloneSupplyError, match="episode_head_changed"):
        prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)
    with pytest.raises(CycloneSupplyError, match="episode_consumer_held"):
        prepare_episode_requests(episodes, EPISODE, digest(held), {}, now=NOW)


def test_late_source_history_held_without_reversing_current(repository):
    episodes, head, _, _ = seed(repository[1])
    earlier, receipt, _ = capture(repository[1], [advisory(advisory_number="0", issued_at="2026-10-10T06:00:00Z", wind_kt=40, lat=10.0)])
    apply(earlier, receipt, episodes, {EPISODE: head})
    _, value = episodes.read_current(EPISODE)
    assert value["observed_at"] == "2026-10-11T06:00:00Z"
    assert value["opportunities"] == [] and "late_evidence_derivation_review" in value["holds"]
    assert episodes._items(value["members"])[-1]["advisory"]["lat"] == 10.0


def test_actual_ri_uses_retained_prior_wind_location_and_time(repository):
    repo = repository[1]
    episodes = PhysicalEpisodeSession(repo)
    initial, initial_receipt, _ = capture(repo, [advisory(issued_at="2026-10-10T06:00:00Z", wind_kt=60, lat=10.0, lon=-70.0)])
    first_head = apply(initial, initial_receipt, episodes, {EPISODE: None})["episodes"][0]["revision_sha256"]
    latest, latest_receipt, _ = capture(repo, [advisory(advisory_number="5", issued_at="2026-10-11T06:00:00Z", wind_kt=100)])
    head = apply(latest, latest_receipt, episodes, {EPISODE: first_head})["episodes"][0]["revision_sha256"]
    result = prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)
    ri = next(row for row in result if row["bundle"]["signal_kind"] == "cyclone_rapid_intensification")
    assert ri["bundle"]["raw_signal_dump"]["previous_wind_kt"] == 60
    assert ri["bundle"]["raw_signal_dump"]["delta_kt_24h"] == 40
    _, value = episodes.read_current(EPISODE)
    history = episodes._items(value["members"])
    assert history[0]["advisory"]["lat"] == 10.0 and history[1]["advisory"]["lat"] == 15.0


def test_episode_changes_during_request_construction_are_refused(repository, monkeypatch):
    from src.two_bot import writer
    episodes, head, second, _ = seed(repository[1])
    later, later_receipt, _ = capture(repository[1], [replace(second.read()[1][0], wind_kt=80)])
    actual = writer.anthropic_writer_request
    def prepare(prompt):
        result = actual(prompt)
        apply(later, later_receipt, episodes, {EPISODE: head})
        return result
    monkeypatch.setattr(writer, "anthropic_writer_request", prepare)
    with pytest.raises(CycloneSupplyError, match="episode_head_changed"):
        prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)


@pytest.mark.parametrize("mode", ["number_missing", "equal_time", "failed_source"])
def test_unordered_or_failed_source_versions_stay_held(repository, mode):
    repo = repository[1]
    rows = [advisory()]
    if mode == "number_missing":
        rows = [advisory(advisory_number="")]
    if mode == "equal_time":
        rows += [advisory(advisory_number="2", wind_kt=100)]
    session, receipt, _ = capture(repo, rows, status="failed" if mode == "failed_source" else "success")
    episodes = PhysicalEpisodeSession(repo)
    result = apply(session, receipt, episodes, {EPISODE: None})
    assert result["episodes"][0]["status"] == "held"
    assert episodes.read_current(EPISODE)[1]["opportunities"] == []


@pytest.mark.parametrize("status", ["failed", "degraded"])
def test_complete_success_recovers_same_assertion_without_renewing_freshness(repository, status):
    repo = repository[1]
    episodes = PhysicalEpisodeSession(repo)
    failed, failed_receipt, original = capture(repo, [advisory()], status=status)
    held_head = apply(failed, failed_receipt, episodes, {EPISODE: None})["episodes"][0]["revision_sha256"]
    held = episodes.read_current(EPISODE)[1]
    assert held["observed_at"] is None and held["qualified_content_sha256"] == []
    assert held["latest_retained_issued_at"] == advisory().issued_at
    recovered, receipt, _ = capture(repo, [advisory()], now="2026-10-11T13:00:00Z")
    operation = str(uuid.uuid4())
    result = apply(recovered, receipt, episodes, {EPISODE: held_head}, operation=operation)
    current = episodes.read_current(EPISODE)[1]
    assert result["episodes"][0]["status"] == "committed" and current["holds"] == []
    assert current["members"][0] == held["members"][0] and len(current["members"]) == 2
    assert len(current["qualified_content_sha256"]) == 1
    assert current["observed_at"] == advisory().issued_at and current["opportunities"] == []
    assert current["previous_bindings"] == []  # held evidence never became writer authority
    assert apply(recovered, receipt, PhysicalEpisodeSession(repo), {EPISODE: held_head}, operation=operation) == result
    assert failed.read()[2] == original
    duplicate, duplicate_receipt, _ = capture(repo, [advisory()])
    assert apply(duplicate, duplicate_receipt, episodes, {EPISODE: digest(current)})["episodes"][0]["status"] == "duplicate"
    with pytest.raises(CycloneSupplyError, match="episode_source_not_current"):
        prepare_episode_requests(episodes, EPISODE, digest(current), {}, now="2026-10-14T12:00:00Z")


def test_failed_only_history_cannot_create_crossing_or_ri_after_later_recovery(repository):
    repo = repository[1]
    episodes = PhysicalEpisodeSession(repo)
    failed, receipt, _ = capture(repo, [advisory(issued_at="2026-10-10T06:00:00Z", wind_kt=60)], status="failed")
    held = apply(failed, receipt, episodes, {EPISODE: None})["episodes"][0]["revision_sha256"]
    latest, receipt, _ = capture(repo, [advisory(advisory_number="5", issued_at="2026-10-11T06:00:00Z", wind_kt=100)])
    head = apply(latest, receipt, episodes, {EPISODE: held})["episodes"][0]["revision_sha256"]
    current = episodes.read_current(EPISODE)[1]
    assert current["holds"] == [] and len(current["members"]) == 2
    assert len(current["qualified_content_sha256"]) == 1
    assert prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW) == []
    next_run, receipt, _ = capture(repo, [advisory(advisory_number="6", issued_at="2026-10-11T12:00:00Z", wind_kt=115)])
    head = apply(next_run, receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    requests = prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)
    assert len(requests) == 1 and requests[0]["bundle"]["signal_kind"] == "cyclone_tier_crossing"
    assert requests[0]["bundle"]["raw_signal_dump"]["from_category"] == 3
    assert len(requests[0]["bundle"]["raw_signal_dump"]["physical_episode"]["source_assertion_refs"]) == 2


def test_newer_failed_evidence_stays_held_against_older_success(repository):
    repo = repository[1]
    episodes, head, second, _ = seed(repo)
    failed, receipt, _ = capture(repo, [advisory(advisory_number="3", issued_at="2026-10-11T12:00:00Z", wind_kt=115)], status="failed")
    head = apply(failed, receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    older, receipt, _ = capture(repo, second.read()[1])
    head = apply(older, receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    current = episodes.read_current(EPISODE)[1]
    assert current["holds"] == ["source_failed"] and current["state"] == "held"
    assert current["observed_at"] == "2026-10-11T06:00:00Z"
    assert current["latest_retained_issued_at"] == "2026-10-11T12:00:00Z"
    with pytest.raises(CycloneSupplyError, match="episode_consumer_held"):
        prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)
    degraded, receipt, _ = capture(repo, failed.read()[1], status="degraded")
    apply(degraded, receipt, episodes, {EPISODE: head})
    assert episodes.read_current(EPISODE)[1]["state"] == "held"


@pytest.mark.parametrize("hold", ["identity_or_revision_conflict", "late_evidence_derivation_review", "geography_context_changed", "relationship_resolution_required"])
def test_source_recovery_cannot_clear_unrelated_holds(repository, hold):
    repo = repository[1]
    episodes, head, second, second_receipt = seed(repo)
    cities = []
    if hold == "relationship_resolution_required":
        result = episodes.retain_relationship(proposal_id=str(uuid.uuid4()), hazard="cyclone", kind="uncertain_identity",
            evidence_refs=[dict(namespace=NAMESPACE, snapshot_id="run:"+second.supply_run_id, sha256=second_receipt.canonical_sha256)],
            expected_heads={EPISODE: head}, now=NOW)
        head = result["episodes"][0]["revision_sha256"]
    elif hold == "identity_or_revision_conflict":
        conflict, receipt, _ = capture(repo, [replace(second.read()[1][0], wind_kt=80)])
        head = apply(conflict, receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    elif hold == "late_evidence_derivation_review":
        old, receipt, _ = capture(repo, [advisory(advisory_number="0", issued_at="2026-10-10T12:00:00Z")])
        head = apply(old, receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    else:
        cities = [dict(name="Invented", country="Cuba", lat=20.0, lon=-75.0, population=100000)]
    latest = advisory(advisory_number="3", issued_at="2026-10-11T12:00:00Z", wind_kt=100)
    failed, receipt, _ = capture(repo, [latest], status="failed")
    head = apply(failed, receipt, episodes, {EPISODE: head}, cities=cities)["episodes"][0]["revision_sha256"]
    complete, receipt, _ = capture(repo, [latest])
    apply(complete, receipt, episodes, {EPISODE: head}, cities=cities)
    current = episodes.read_current(EPISODE)[1]
    assert "source_failed" not in current["holds"] and hold in current["holds"]
    assert current["state"] == "held" and current["opportunities"] == []
    with pytest.raises(CycloneSupplyError, match="episode_consumer_held"):
        episodes.prepare_story_context(EPISODE, digest(current))


def test_one_transaction_concurrent_cas_and_exact_operation_retry(repository):
    episodes, head, _, _ = seed(repository[1])
    sessions = [capture(repository[1], [advisory(advisory_number=str(number), issued_at="2026-10-11T12:00:00Z", wind_kt=115)]) for number in (3, 4)]
    operations = [str(uuid.uuid4()), str(uuid.uuid4())]
    def run(index):
        try:
            session, receipt, _ = sessions[index]
            return apply(session, receipt, episodes, {EPISODE: head}, operation=operations[index])
        except CycloneSupplyError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (0, 1)))
    assert sum(type(value) is dict for value in results) == 1
    assert "episode_head_changed" in results
    winner = next(i for i, value in enumerate(results) if type(value) is dict)
    assert run(winner) == results[winner]
    assert episodes.read_current(EPISODE)[1]["sequence"] == 3
    session, receipt, _ = sessions[winner]
    with pytest.raises(CycloneSupplyError, match="episode_operation_conflict"):
        apply(session, receipt, episodes, {EPISODE: head}, operation=operations[winner], now="2026-10-11T13:00:00Z")


def test_lost_commit_ack_reconciles_once_same_operation_and_atomic_failure(repository, monkeypatch):
    repo = repository[1]
    session, receipt, _ = capture(repo, [advisory()])
    episodes = PhysicalEpisodeSession(repo)
    connection = p.PostgresProjectionRepository._connection
    calls = []
    @contextmanager
    def lost_ack(repository, *, writing=False):
        with connection(repository, writing=writing) as c:
            yield c
        if writing:
            calls.append("committed_without_ack")
            raise p.ProjectionError("write_outcome_unknown")
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", lost_ack)
    result = apply(session, receipt, episodes, {EPISODE: None})
    assert calls == ["committed_without_ack"] and result["episodes"][0]["status"] == "committed"
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", connection)
    head = episodes.read_current(EPISODE)[0].canonical_sha256
    next_session, next_receipt, _ = capture(repo, [advisory(advisory_number="2", issued_at="2026-10-11T06:00:00Z", wind_kt=100)])
    record = p.PostgresProjectionRepository._record
    def failed(cls, c, namespace, *args):
        if namespace == OPERATION:
            raise p.ProjectionError("fixture_before_operation")
        return record(c, namespace, *args)
    monkeypatch.setattr(p.PostgresProjectionRepository, "_record", classmethod(failed))
    with pytest.raises(p.ProjectionError, match="fixture_before_operation"):
        apply(next_session, next_receipt, episodes, {EPISODE: head})
    assert episodes.read_current(EPISODE)[0].canonical_sha256 == head
    assert next_session.read()[0] == next_receipt


def test_current_episode_memory_survives_metadata_and_isolates_nearby_storm(repository):
    episodes, head, _, _ = seed(repository[1])
    context, _ = episodes.prepare_story_context(EPISODE, head)
    first = prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)[0]
    from src.two_bot.candidate_derivation import retained_bundle
    bundle = retained_bundle(first["bundle"])
    state = deepcopy(DEFAULT_STATE)
    record_shipped(state, bundle, WriterResult(tweet="Invented earlier storm report.", kill_reason=None, angle_chosen="fixture", era_anchor_used=None, peer_comparison_used=None, reasoning="invented"), [], shipped_at=NOW)
    restored = _story_bundle_from_metadata({"bundle": bundle_memory_snapshot(bundle)}, {})
    assert restored.raw_signal_dump["physical_episode"] == context.binding
    same = prepare_episode_requests(episodes, EPISODE, head, state, now=NOW)[0]
    assert same["memory"]["recent_tweets_same_event"] == ["Invented earlier storm report."]
    rows = [advisory(storm_id="AL022026"), advisory(storm_id="AL022026", advisory_number="2", issued_at="2026-10-11T06:00:00Z", wind_kt=100)]
    session, receipt, _ = capture(repository[1], rows)
    other_id = "ep1:cyclone:nhc:AL022026"
    result = apply(session, receipt, episodes, {other_id: None})
    other = prepare_episode_requests(episodes, other_id, result["episodes"][0]["revision_sha256"], state, now=NOW)[0]
    assert other["memory"]["recent_tweets_same_event"] == [] and other["memory"]["ongoing_event"] is None
    assert "Invented earlier storm report." in other["memory"]["shipped_tweet_texts"]  # labeled global copy history only


@responses.activate
def test_actual_source_observer_cross_border_products_and_source_boundary(repository, monkeypatch):
    # The source acquisition remains the real fetch/retry/parser stack; only
    # HTTP responses are invented. Its freshness gate uses a current fixture.
    now = datetime.now(UTC).replace(microsecond=0)
    issued = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    forecast = now + timedelta(hours=12)
    text = (f"FORECAST VALID {forecast:%d/%H%MZ} 15.0N 75.0W\nMAX WIND 100 KT\n"
            f"FORECAST VALID {forecast:%d/%H%MZ} 16.0N 76.0W\nMAX WIND 100 KT\n")
    raw = dict(id="AL012026", name="Invented A", intensity="100", lastUpdate=issued,
        latitudeNumeric="15.0N", longitudeNumeric="75.0W",
        publicAdvisory=dict(advNum="2A", url="/text/fixture-public.shtml", issuance=issued),
        forecastAdvisory=dict(advNum="2A", url="/text/fixture-forecast.shtml", issuance=issued))
    responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms": [raw]})
    responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-public.shtml", body="Invented public advisory.")
    responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-forecast.shtml", body=text)
    repo = repository[1]
    session = CycloneSupplySession(repo, str(uuid.uuid4()), issued, BASE)
    cities = [dict(city="Invented North", country="United States", lat=15.0, lon=-75.0),
              dict(city="Invented South", country="Canada", lat=16.0, lon=-76.0)]
    lane = CycloneEpisodeLane(session, PhysicalEpisodeSession(repo), str(uuid.uuid4()), {EPISODE: None}, issued, cities)
    snapshot = deepcopy(DEFAULT_STATE)
    before = deepcopy(snapshot)
    from src.orchestrator import common
    monkeypatch.setattr(common, "_enqueue_story_candidate", forbid)
    result = _process_cyclone_source(snapshot, None, source_key="nhc", source_label="NHC",
        fetch_fn=nhc.fetch_active_cyclones, detect_module=nhc, episode_lane=lane)
    assert len(responses.calls) == 3 and snapshot == before
    _, restored, envelope = session.read()
    assert len(restored[0].forecast_points) == 2 and forecast_qualified(envelope["rows"][0])
    assert envelope["rows"][0]["metadata"]["forecast_advisory_number"] == "2A"
    assert envelope["raw_response_available"] is False
    assert {r["bundle"]["raw_signal_dump"]["landmass_country"] for r in result["requests"]} == {"United States", "Canada"}
    _, revision = lane.episodes.read_current(EPISODE)
    assert len([a for a in revision["areas"] if a["kind"] == "forecast_threat"]) == 2
    assert all(r["bundle"]["signal_kind"] == "cyclone_land_threat" for r in result["requests"])
    assert len({r["bundle"]["raw_signal_dump"]["physical_episode"]["episode_id"] for r in result["requests"]}) == 1


@responses.activate
@pytest.mark.parametrize("mode", ["truncated", "suffix", "missing_issue", "old_issue", "failure", "old_point"])
def test_forecast_hold_reaches_actual_retained_consumer(repository, mode):
    now = datetime.now(UTC).replace(microsecond=0)
    issued = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    point = now + timedelta(hours=96 if mode == "old_point" else 12)
    text = f"FORECAST VALID {point:%d/%H%MZ} 15.0N 75.0W\nMAX WIND 100 KT\n"
    metadata = dict(advNum="2" if mode == "suffix" else "2A", issuance=issued, url="/text/fixture-forecast.shtml")
    if mode == "missing_issue":
        metadata.pop("issuance")
    if mode == "old_issue":
        metadata["issuance"] = "2000-01-01T00:00:00Z"
    raw = dict(id="AL012026", name="Invented A", intensity="100", lastUpdate=issued,
               publicAdvisory=dict(advNum="2A"), forecastAdvisory=metadata)
    responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms": [raw]})
    responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-forecast.shtml",
                  body=text+("x"*8001 if mode == "truncated" else ""), status=503 if mode == "failure" else 200)
    repo = repository[1]
    supply_session = CycloneSupplySession(repo, str(uuid.uuid4()), issued, BASE)
    lane = CycloneEpisodeLane(supply_session, PhysicalEpisodeSession(repo), str(uuid.uuid4()), {EPISODE: None}, issued,
                             [dict(city="Invented Coast", country="Canada", lat=15, lon=-75)])
    result = lane.capture_prepare({}, nhc.fetch_active_cyclones)
    assert result["requests"] == []
    _, value = lane.episodes.read_current(EPISODE)
    assert not any(area["kind"] == "forecast_threat" for area in value["areas"])
    if mode not in {"failure", "old_point"}:
        assert "forecast_product_unresolved" in value["holds"]
    assert len(supply_session.read()[1]) == 1


@responses.activate
def test_unconsumed_land_threat_survives_ordinary_advisory_and_restart(repository, monkeypatch):
    from src.two_bot import writer
    actual_prompt = writer.build_writer_user_prompt
    now = datetime.now(UTC).replace(microsecond=0)
    forecast = now + timedelta(hours=18)
    cities = [dict(city="Invented Coast", country="Canada", lat=15.0, lon=-75.0)]
    repo = repository[1]
    episodes = PhysicalEpisodeSession(repo)
    original_identity = None
    head = None
    for number, issued in ((1, now), (2, now+timedelta(hours=6))):
        clock = issued.strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = dict(id="AL012026", name="Invented A", intensity="100", lastUpdate=clock,
            publicAdvisory=dict(advNum=str(number)),
            forecastAdvisory=dict(advNum=str(number), issuance=clock, url="/text/fixture-forecast.shtml"))
        responses.reset()
        responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms": [raw]})
        responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-forecast.shtml",
                      body=f"FORECAST VALID {forecast:%d/%H%MZ} 15.0N 75.0W\nMAX WIND 100 KT\n")
        observed = []
        advisories = nhc.fetch_active_cyclones(strict=True, retention_observer=lambda a, m: observed.append((a, m)))
        session, receipt, _ = capture(repo, advisories, observations=observed, now=clock)
        monkeypatch.setattr(writer, "build_writer_user_prompt", forbid)
        applied = apply(session, receipt, episodes, {EPISODE: head}, cities=cities, now=clock)
        head = applied["episodes"][0]["revision_sha256"]
        value = episodes.read_current(EPISODE)[1]
        assert len(value["opportunities"]) == 1
        identity = value["opportunities"][0]["opportunity_id"]
        if number == 1:
            original_identity = identity  # commit followed by crash before any request
        else:
            assert identity == original_identity and len(value["seen_opportunities"]) == 1
    monkeypatch.setattr(writer, "build_writer_user_prompt", actual_prompt)
    current = prepare_episode_requests(episodes, EPISODE, head, {}, now=clock)
    assert current[0]["opportunity_id"] == original_identity
    assert current[0]["bundle"]["raw_signal_dump"]["advisory_number"] == "2"
    assert _fresh_process(repo, EPISODE, head, now=clock) == current
    assert pg.admin(repository[2], f"SELECT count(*) FROM {p.SCHEMA}.versions WHERE namespace=%s", (OPERATION,))[0][0] == 2


def test_no_consumption_receipt_invented_and_weakened_tier_is_not_carried(repository):
    episodes, head, _, _ = seed(repository[1])  # episode committed; no request built
    ordinary, receipt, _ = capture(repository[1], [advisory(advisory_number="3", issued_at="2026-10-11T12:00:00Z", wind_kt=100)])
    current = apply(ordinary, receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    assert len(_fresh_process(repository[1], EPISODE, current)) == 1
    weaker, weaker_receipt, _ = capture(repository[1], [advisory(advisory_number="4", issued_at="2026-10-11T18:00:00Z", wind_kt=70)])
    lower = apply(weaker, weaker_receipt, episodes, {EPISODE: current}, now="2026-10-11T18:00:00Z")["episodes"][0]["revision_sha256"]
    assert prepare_episode_requests(episodes, EPISODE, lower, {}, now="2026-10-11T18:00:00Z") == []


def test_relationship_holds_all_heads_without_moving_members_or_memory(repository):
    repo = repository[1]
    episodes, head, session, receipt = seed(repo)
    second, second_receipt, _ = capture(repo, [advisory(storm_id="AL022026")])
    other = "ep1:cyclone:nhc:AL022026"
    other_head = apply(second, second_receipt, episodes, {other: None})["episodes"][0]["revision_sha256"]
    before = {key: episodes.read_current(key)[1]["members"] for key in (EPISODE, other)}
    kwargs = dict(proposal_id=str(uuid.uuid4()), hazard="cyclone", kind="merge", now=NOW,
        expected_heads={EPISODE: head, other: other_head}, evidence_refs=[dict(namespace=NAMESPACE,
            snapshot_id="run:"+session.supply_run_id, sha256=receipt.canonical_sha256)])
    result = episodes.retain_relationship(**kwargs)
    assert result == episodes.retain_relationship(**kwargs) and len(result["episodes"]) == 2
    for key in before:
        _, value = episodes.read_current(key)
        assert value["members"] == before[key] and value["state"] == "held"
        assert "relationship_resolution_required" in value["holds"]
    with pytest.raises(CycloneSupplyError, match="episode_operation_conflict"):
        episodes.retain_relationship(**(kwargs | {"kind": "split"}))


@pytest.mark.parametrize("hazard", ["fire", "flood"])
def test_report_lineage_proposal_not_an_incident_or_cumulative_total(repository, hazard):
    repo = repository[1]
    receipt = repo.record("invented-report-assertions", hazard, dict(reports=[
        dict(report_id="a", revised_report_id=None, count=2, reporting_unit="nearby"),
        dict(report_id="b", revised_report_id="a", count=3, reporting_unit="nearby")]))
    result = PhysicalEpisodeSession(repo).retain_relationship(proposal_id=str(uuid.uuid4()), hazard=hazard,
        kind="uncertain_identity", now=NOW, expected_heads={},
        evidence_refs=[dict(namespace=receipt.namespace, snapshot_id=receipt.snapshot_id, sha256=receipt.canonical_sha256)])
    assert result["status"] == "unconfirmed_relationship" and result["episodes"] == []
    value = repo.read(PROPOSAL, result["proposal_sha256"])[1]
    assert value["evidence_class"] == "retained_assertion_unadjudicated"
    assert "count" not in value and "episode_id" not in value


def test_real_p18_six_station_proposal_before_caps_never_becomes_heatwave(repository, supply, monkeypatch):
    from src.storage.scientific_supply import ScientificSupplySession
    from src.orchestrator import caps
    from tests.test_postgres_scientific_supply_retention import metrics_for, trap_replay
    from tests.test_ghcn_time_integrity import NOW as GHCN_NOW
    repo = repository[1]
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "success")
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
    monkeypatch.setenv("THEHEAT_RECORDS_CLUSTER_ENABLED", "1")
    capture_session = ScientificSupplySession(repo, str(uuid.uuid4()), "capture", GHCN_NOW, BASE)
    capture_session.capture(*supply[:2], metrics_for(supply))
    replay = replace(capture_session, mode="replay", captured_at=None, producer_revision=None)
    trap_replay(monkeypatch)
    episodes = PhysicalEpisodeSession(repo)
    identities = []
    for cap in (0, 1, 2, 6):
        monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", cap)
        result = episodes.retain_heat_proposals(replay, deepcopy(DEFAULT_STATE))
        assert len(result["proposals"]) == 1
        proposal = result["proposals"][0]
        assert proposal["status"] == "unconfirmed_grouping" and len(proposal["grouping"]["members"]) == 6
        assert proposal["grouping"]["aggregate_hold_codes"]
        assert "physical_episode_not_established" in proposal["holds"]
        assert len(result["source_preview"]["individual_bundle_keys"]) == cap
        identities.append(proposal["proposal_sha256"])
    assert len(set(identities)) == 1


def test_actual_cross_border_heat_archives_and_spatial_bridge_remain_unconfirmed(repository, supply_inputs, monkeypatch):
    from datetime import date
    from src.data import ghcn
    from src.data.ghcn_db import open_db, upsert_thresholds
    from src.data.ghcn_format import DailyObs, compute_thresholds
    from src.storage.scientific_supply import ScientificSupplySession
    from tests.test_ghcn_time_integrity import NOW as GHCN_NOW
    from tests.test_postgres_scientific_supply_retention import metrics_for
    inputs = dict(supply_inputs)
    stations = deepcopy(inputs["stations"][:6])
    identities = {}
    for index, station in enumerate(stations):
        old = station["station_id"]
        new = old if index < 4 else old.replace("USW", "CAW")
        identities[old] = new
        station.update(station_id=new, lat=40.0+index*1.8)  # adjacent links; endpoints >350 km
        if index >= 4:
            station.update(country_code="CA", country_name="Canada", state="")
            with open_db(inputs["db_path"]) as connection:
                upsert_thresholds(connection, compute_thresholds([DailyObs(new, date(2020, 6, 25), "TMAX", 31.9)]))
    source_observations = inputs["_fetch_obs_fn"](None)
    observations = {(identities[station], day): [replace(obs, station_id=identities[station]) for obs in rows]
                    for (station, day), rows in source_observations.items() if station in identities}
    original_archive = inputs["_fetch_archive_fn"]
    reverse = {new: old for old, new in identities.items()}
    inputs.update(stations=stations, _fetch_obs_fn=lambda _: observations,
                  _fetch_archive_fn=lambda station: original_archive(reverse[station]).replace(reverse[station].encode(), station.encode()))
    metrics = {}
    bundles, countries = ghcn.check_extreme_signals_for_stations(**inputs, metrics_out=metrics)
    assert len(bundles) == 6 and {bundle.country for bundle in bundles} == {"United States", "Canada"}
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "success")
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
    monkeypatch.setenv("THEHEAT_RECORDS_CLUSTER_ENABLED", "1")
    repo = repository[1]
    session = ScientificSupplySession(repo, str(uuid.uuid4()), "capture", GHCN_NOW, BASE)
    session.capture(bundles, countries, metrics_for((bundles, countries, metrics)))
    result = PhysicalEpisodeSession(repo).retain_heat_proposals(replace(session, mode="replay"), {})
    assert len(result["proposals"]) == 1
    group = result["proposals"][0]
    assert len(group["grouping"]["members"]) == 6 and group["status"] == "unconfirmed_grouping"
    assert group["grouping"]["aggregate_hold_codes"] and "source_calendar_utc_unresolved" in group["holds"]
    assert "episode_id" not in group


def test_bounds_hold_current_consumer_and_keep_complete_source_inventory(repository, monkeypatch):
    from src.storage import physical_events
    episodes, head, _, _ = seed(repository[1])
    new, receipt, _ = capture(repository[1], [advisory(advisory_number="3", issued_at="2026-10-11T12:00:00Z")])
    monkeypatch.setattr(physical_events, "MAX_MEMBERS", 2)
    result = apply(new, receipt, episodes, {EPISODE: head})
    assert result["episodes"][0]["status"] == "held"
    _, value = episodes.read_current(EPISODE)
    assert value["state"] == "held" and len(value["members"]) == 2
    assert value["correction_notices"][0]["run_sha256"] == receipt.canonical_sha256
    assert len(new.read()[1]) == 1
    retry = apply(new, receipt, episodes, {EPISODE: digest(value)})
    assert retry["episodes"][0]["reason"] == "episode_member_bound"
    assert episodes.read_current(EPISODE)[1] == value
    with pytest.raises(CycloneSupplyError, match="episode_consumer_held"):
        episodes.prepare_story_context(EPISODE, digest(value))


def test_corrupt_or_missing_receipt_unknown_schema_and_proposal_bound_refuse(repository, monkeypatch):
    repo = repository[1]
    session, receipt, envelope = capture(repo, [advisory()])
    with pytest.raises(CycloneSupplyError, match="cyclone_supply_changed"):
        session.read(expected_sha="e"*64)
    with pytest.raises(CycloneSupplyError, match="cyclone_supply_unavailable"):
        CycloneSupplySession(repo, str(uuid.uuid4())).read()
    envelope["schema_version"] = True
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", lambda *a: (receipt, envelope))
    with pytest.raises(CycloneSupplyError, match="unsupported_cyclone_codec"):
        session.read()
    with pytest.raises(CycloneSupplyError, match="relationship_evidence_bound"):
        PhysicalEpisodeSession(repo).retain_relationship(proposal_id=str(uuid.uuid4()), hazard="fire",
            kind="uncertain_identity", evidence_refs=[{}]*17, expected_heads={}, now=NOW)


def _fresh_process(repo, episode, head, *, now=NOW):
    code = '''import json,sys,requests
from src.storage.postgres_projection import PostgresProjectionRepository
from src.storage.physical_events import PhysicalEpisodeSession
from src.orchestrator.cyclone_episodes import prepare_episode_requests
from src.data import nhc
from src.two_bot import writer
def forbid(*a,**k): raise AssertionError("unexpected acquisition/provider")
requests.sessions.Session.request=forbid
nhc.fetch_active_cyclones=forbid
writer._call_writer_provider=forbid
a=json.loads(sys.argv[1]); repo=PostgresProjectionRepository(**a.pop("repository"))
print(json.dumps(prepare_episode_requests(PhysicalEpisodeSession(repo),a["episode"],a["head"],{},now=a["now"]),sort_keys=True))
'''
    arguments = dict(repository=dict(socket_directory=repo.socket_directory, port=repo.port,
        database=repo.database, user=repo.user), episode=episode, head=head, now=now)
    result = subprocess.run([sys.executable, "-c", code, json.dumps(arguments)], capture_output=True,
                            text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def test_fresh_process_and_owned_dump_restore_resume_exact_consumer(repository, cluster):
    import psycopg
    repo = repository[1]
    episodes, head, _, _ = seed(repo)
    original = prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)
    later = advisory(advisory_number="3", issued_at="2026-10-11T12:00:00Z", wind_kt=100)
    failed, failed_receipt, failed_bytes = capture(repo, [later], status="failed")
    held_head = apply(failed, failed_receipt, episodes, {EPISODE: head})["episodes"][0]["revision_sha256"]
    complete, receipt, _ = capture(repo, [later])
    operation = str(uuid.uuid4())
    result = apply(complete, receipt, episodes, {EPISODE: held_head}, operation=operation)
    head = result["episodes"][0]["revision_sha256"]
    expected = prepare_episode_requests(episodes, EPISODE, head, {}, now=NOW)
    assert expected[0]["opportunity_id"] == original[0]["opportunity_id"]
    assert expected[0]["bundle"]["raw_signal_dump"]["advisory_number"] == "3"
    assert failed.read()[2] == failed_bytes
    assert _fresh_process(repo, EPISODE, head) == expected
    args, command, root = cluster
    dump = root / ("episodes-"+uuid.uuid4().hex+".dump")
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"]]
    command("pg_dump", *common, "-Fc", "-f", dump, repo.database)
    name = "episode_restore_"+uuid.uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    try:
        command("pg_restore", *common, "--single-transaction", "-d", name, dump)
        restored = p.PostgresProjectionRepository(socket_directory=args["host"], port=args["port"], database=name, user=repo.user)
        assert _fresh_process(restored, EPISODE, head) == expected
        assert apply(complete, receipt, PhysicalEpisodeSession(restored), {EPISODE: held_head}, operation=operation) == result
        assert CycloneSupplySession(restored, failed.supply_run_id).read()[2] == failed_bytes
        assert episodes.read_current(EPISODE)[0].canonical_sha256 == head
    finally:
        with psycopg.connect(**args) as c:
            c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
