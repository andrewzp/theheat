"""Invented retained reports; actual local PG and current P20 story consumer."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.commands import postgres_report_development as domain
from src.commands.schema import Principal
from src.editorial.policy import current_editorial_policy
from src.editorial.report_development import prepare_report_development, resolve_story_context
from src.state_schema import BotState
from src.orchestrator.cyclone_episodes import prepare_episode_requests
from src.storage import postgres_projection as p
from src.storage.retained_reports import (ARTIFACT, OPERATION, REVISION, ReportError,
    RetainedReportSession, TIME_KEYS, digest)
from tests import test_postgres_physical_events as episodes_fixture
from tests import test_postgres_projection as pg

cluster, database, repository = pg.cluster, pg.database, pg.repository
isolated = episodes_fixture.isolated
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
NOW_TEXT = "2026-10-11T12:00:00Z"


def meta(**updates):
    return dict(media_type="text/plain", source_url="https://example.test/report", retrieved_at=NOW_TEXT,
                original_artifact_id=None, extraction=None) | updates


def report_fixture(repo, *, language="en", kind="reported_impact", excerpt="Invented authority bulletin refers to AL012026."):
    session = RetainedReportSession(repo)
    raw = excerpt.encode()
    artifact = session.retain_artifact(raw, declared_sha256=hashlib.sha256(raw).hexdigest(), metadata=meta())
    times = dict.fromkeys(TIME_KEYS)
    times.update(event_start=dict(original="October11", utc=None, date="2026-10-11", precision="calendar", timezone=None),
                 event_end=dict(original="October11", utc=None, date="2026-10-11", precision="calendar", timezone=None))
    claim = dict(claim_id="claim1", kind=kind, summary="Invented report claim", anchors=[dict(artifact_id=artifact.snapshot_id,
        content_sha256=hashlib.sha256(raw).hexdigest(), start=0, end=len(raw), text=excerpt)], original_language=language,
        translation=dict(text=None, status="not_needed" if language == "en" else "unreviewed", decision_ref=None),
        source_review=dict(status="pending", decision_ref=None), attribution="Invented agency", times=times,
        quantity=dict(value=4, unit="people", operator="reported", scope="cumulative"),
        geography=dict(reported_scope="Invented regional footprint", role="reported_footprint", map_marker=None, geometry=None),
        identity_reference=dict(authority="nhc", source_id="AL012026", anchor_index=0), holds=["impact_not_independently_adjudicated"])
    document = dict(schema_version=1, lineage_id="fixture:report1", previous_report_sha256=None, publisher="Invented agency",
        source_url="https://example.test/report", hazards=["cyclone", "reported_flooding"], original_language=language,
        artifact_refs=[artifact.snapshot_id], upstream_lineage_refs=["fixture:original1"], claims=[claim], limits=["Invented data only"],
        captured_at=NOW_TEXT, reference_review=dict(candidate_id=None, adjudication="pending_human_and_source_review",
            benchmark_eligible=False, importance=None, detection_deadline=None, bot_match="not_evaluated"), legacy_metadata=None)
    return session, document, artifact


def retained(repo, **kwargs):
    session, document, artifact = report_fixture(repo, **kwargs)
    result = session.retain_revision(document, expected_head=None, operation_id=str(uuid4()))
    return session, document, result["report_sha256"], artifact


def authority_fixture(repo, head, episode=None):
    config = dict(current_reports=[dict(lineage_id="fixture:report1", report_sha256=head, episode_reference=episode)], decision_refs=[])
    return SimpleNamespace(environment="local", projections=repo, report_configuration=lambda: deepcopy(config), _validate=repo._validate), config


def command_fixture(head, episode=None):
    return SimpleNamespace(action="open_report_evidence", actor_subject="fixture-editor", authentication_context="fixture-session",
        expires_at="2026-10-11T13:00:00Z", payload=dict(lineage_id="fixture:report1", report_sha256=head,
            expected_policy_sha256=digest(current_editorial_policy()), episode_reference=episode))


def test_retained_report_actual_unlinked_and_current_story_consumer(repository):
    repo = repository[1]
    session, document, report_head, _ = retained(repo)
    episodes, physical_head, _, _ = episodes_fixture.seed(repo)
    unrelated = prepare_report_development(session, document["lineage_id"], report_head,
        episode_reference=None, snapshot={}, now=NOW_TEXT)
    assert unrelated["prepared_stories"] == [] and unrelated["report"]["development_status"] == "evidence_review_required"
    assert unrelated["report"]["reference_review"]["benchmark_eligible"] is False
    reference = dict(episode_id=episodes_fixture.EPISODE, revision_sha256=physical_head, claim_id="claim1")
    original = prepare_episode_requests(episodes, reference["episode_id"], physical_head, {}, now=NOW_TEXT)
    linked = prepare_report_development(session, document["lineage_id"], report_head,
        episode_reference=reference, snapshot={}, now=NOW_TEXT)
    assert linked["report"]["related_story"]["association_status"] == "source_identity_reference_only"
    assert linked["report"]["related_story"]["time_compatibility"] == "source_calendar_compatibility_only"
    row = linked["prepared_stories"][0]
    assert row.pop("reports_for_evidence_review")[0]["holds"]
    assert linked["prepared_stories"] == original  # every bundle, request, memory and hash unchanged
    assert "human_impact" not in row["bundle"]


@pytest.mark.parametrize("mode", ["id", "year", "AL90", "unknown_time", "meeting", "translation", "stale_head", "legacy"])
def test_source_identity_and_time_are_not_guessed(repository, mode):
    repo = repository[1]
    session, document, _ = report_fixture(repo, language="pt" if mode == "translation" else "en")
    episodes, physical_head, _, _ = episodes_fixture.seed(repo)
    reference = dict(episode_id=episodes_fixture.EPISODE, revision_sha256=physical_head, claim_id="claim1")
    claim = document["claims"][0]
    if mode in {"id", "year", "AL90"}:
        token = {"id": "Invented A", "year": "AL012025", "AL90": "AL902026"}[mode]
        session, document, _ = report_fixture(repo, excerpt=f"Invented source refers to {token}.")
        document["claims"][0]["identity_reference"]["source_id"] = token
    elif mode == "unknown_time":
        claim["times"]["event_start"] = None
    elif mode == "meeting":
        claim["geography"]["role"] = "meeting_location"
    elif mode == "stale_head":
        reference["revision_sha256"] = "f"*64
    elif mode == "legacy":
        document["legacy_metadata"] = {"confidence": "verified"}
    result = session.retain_revision(document, expected_head=None, operation_id=str(uuid4()))
    with pytest.raises(ValueError):
        resolve_story_context(session, document["lineage_id"], result["report_sha256"], reference)
    # An unlinked report is still available for evidence development.
    assert prepare_report_development(session, document["lineage_id"], result["report_sha256"],
        episode_reference=None, snapshot={}, now=NOW_TEXT)["report"]["generation_available"] is False


@pytest.mark.parametrize("kind", ["reported_impact", "source_reported_observation", "forecast", "warning", "project_update", "unclassified"])
def test_report_kinds_open_without_sensor_or_draft_mutation(repository, kind):
    repo = repository[1]
    _, _, head, _ = retained(repo, kind=kind)
    authority, _ = authority_fixture(repo, head)
    command = command_fixture(head)
    actor = Principal("fixture-editor", "editor", "fixture-session")
    state = {"drafts": [], "news_events": []}
    before = deepcopy(state)
    with repo._connection(writing=True) as c:
        repo._validate(c)
        outcome = domain.prepare(authority, c, state, command, actor, now=NOW, editorial_policy=current_editorial_policy()).outcome
    assert state == before and outcome["draft_mutated"] is False and outcome["provider_request_created"] is False
    assert outcome["status"] == "evidence_review_required" and not outcome["reused"]
    with repo._connection(writing=True) as c:
        repo._validate(c)
        retry = domain.prepare(authority, c, state, command, actor, now=NOW, editorial_policy=current_editorial_policy()).outcome
    assert retry["reused"] and retry["item_sha256"] == outcome["item_sha256"]
    view = domain.projection(authority, now=NOW)
    assert len(view["reports"]) == 1 and view["reports"][0]["development_status"] == "evidence_review_required"
    assert view["reports"][0]["claims"][0]["quantity"]["scope"] == "cumulative"


def test_review_status_needs_trusted_actual_decision_not_caller_label(repository):
    session, document, _ = report_fixture(repository[1], language="pt")
    claim = document["claims"][0]
    fake = dict(namespace="report-human-decision-v1", snapshot_id="a"*64, sha256="a"*64)
    for dimension in ("source_review", "translation"):
        changed = deepcopy(document)
        changed["claims"][0][dimension].update(status="human_reviewed", decision_ref=fake)
        with pytest.raises(ReportError, match="report_review_unavailable"):
            session.document(changed)
    assert claim["source_review"]["status"] == "pending"


@pytest.mark.parametrize("mode", ["text", "offset", "hash", "boolean_offset", "missing_artifact", "gold", "geometry", "nan", "oversize", "translation_label"])
def test_bad_report_evidence_never_enters_storage(repository, mode):
    session, document, _ = report_fixture(repository[1])
    claim = document["claims"][0]
    if mode == "text":
        claim["anchors"][0]["text"] = "Changed"
    elif mode == "offset":
        claim["anchors"][0]["end"] += 1
    elif mode == "hash":
        claim["anchors"][0]["content_sha256"] = "a"*64
    elif mode == "boolean_offset":
        claim["anchors"][0]["start"] = False
    elif mode == "missing_artifact":
        document["artifact_refs"] = []
    elif mode == "gold":
        document["reference_review"]["benchmark_eligible"] = True
    elif mode == "geometry":
        claim["geography"]["geometry"] = [0, 0]
    elif mode == "nan":
        claim["quantity"]["value"] = float("nan")
    elif mode == "oversize":
        claim["summary"] = "x"*140000
    else:
        claim["translation"]["text"] = "Unreviewed but relabeled as not needed"
    with pytest.raises(ValueError):
        session.retain_revision(document, expected_head=None, operation_id=str(uuid4()))
    with session.repository._connection() as c:
        assert c.execute(f"SELECT count(*) FROM {p.SCHEMA}.versions WHERE namespace=%s", (REVISION,)).fetchone()[0] == 0


def test_report_head_update_keeps_original_and_refuses_stale_consumer(repository):
    repo = repository[1]
    session, original, head, artifact = retained(repo)
    correction = deepcopy(original)
    correction["previous_report_sha256"] = head
    correction["claims"][0]["holds"].append("impact_scope_conflict")
    operation = str(uuid4())
    result = session.retain_revision(correction, expected_head=head, operation_id=operation)
    assert session.retain_revision(correction, expected_head=head, operation_id=operation) == result
    with pytest.raises(ReportError, match="report_head_changed"):
        session.read_current(original["lineage_id"], head)
    changed = deepcopy(correction)
    changed["limits"].append("changed")
    with pytest.raises(ReportError, match="report_operation_conflict"):
        session.retain_revision(changed, expected_head=head, operation_id=operation)
    assert session.read_artifact(artifact.snapshot_id)[2] == original["claims"][0]["anchors"][0]["text"].encode()
    with repo._connection() as c:
        assert c.execute(f"SELECT count(*) FROM {p.SCHEMA}.versions WHERE namespace=%s", (REVISION,)).fetchone()[0] == 2


def test_retention_lost_ack_and_atomic_operation_failure(repository, monkeypatch):
    repo = repository[1]
    session, document, _ = report_fixture(repo)
    connection = p.PostgresProjectionRepository._connection
    @contextmanager
    def lost_ack(owner, *, writing=False):
        with connection(owner, writing=writing) as c:
            yield c
        if writing:
            raise p.ProjectionError("write_outcome_unknown")
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", lost_ack)
    result = session.retain_revision(document, expected_head=None, operation_id=str(uuid4()))
    assert result["sequence"] == 1
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", connection)
    record = p.PostgresProjectionRepository._record
    def fail(c, namespace, *args):
        if namespace == OPERATION:
            raise p.ProjectionError("storage_unavailable")
        return record(c, namespace, *args)
    monkeypatch.setattr(p.PostgresProjectionRepository, "_record", staticmethod(fail))
    changed = deepcopy(document)
    changed["previous_report_sha256"] = result["report_sha256"]
    changed["claims"][0]["holds"].append("correction_unresolved")
    with pytest.raises(p.ProjectionError):
        session.retain_revision(changed, expected_head=result["report_sha256"], operation_id=str(uuid4()))
    assert session.read_current(document["lineage_id"])[0].canonical_sha256 == result["report_sha256"]


def test_artifact_bound_is_checked_before_base64_and_decode(repository, monkeypatch):
    import src.storage.retained_reports as module
    session = RetainedReportSession(repository[1])
    monkeypatch.setattr(module, "MAX_ARTIFACT", 4)
    monkeypatch.setattr(module.base64, "b64encode", lambda *a: pytest.fail("encoded oversized bytes"))
    with pytest.raises(ReportError, match="report_artifact_bound"):
        session.retain_artifact(b"12345", declared_sha256=hashlib.sha256(b"12345").hexdigest(), metadata=meta())
    with session.repository._connection() as c:
        assert c.execute(f"SELECT count(*) FROM {p.SCHEMA}.versions WHERE namespace=%s", (ARTIFACT,)).fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["viewer", "changed_actor", "expired", "policy", "config_drift"])
def test_open_failure_cannot_leave_a_development_item(repository, monkeypatch, mode):
    repo = repository[1]
    _, _, head, _ = retained(repo)
    authority, config = authority_fixture(repo, head)
    command = command_fixture(head)
    actor = Principal("fixture-editor", "viewer" if mode == "viewer" else "editor", "fixture-session")
    if mode == "changed_actor":
        actor = Principal("different-editor", "editor", "fixture-session")
    elif mode == "expired":
        command.expires_at = "2026-10-11T11:00:00Z"
    elif mode == "policy":
        command.payload["expected_policy_sha256"] = "e"*64
    elif mode == "config_drift":
        record = p.PostgresProjectionRepository._record
        def change_after_write(c, namespace, *args):
            receipt = record(c, namespace, *args)
            if namespace == domain.DEVELOPMENT:
                config["current_reports"] = []
            return receipt
        monkeypatch.setattr(p.PostgresProjectionRepository, "_record", staticmethod(change_after_write))
    before = {"drafts": [], "publish_ledger": {}}
    state = deepcopy(before)
    with pytest.raises(ValueError):
        with repo._connection(writing=True) as c:
            repo._validate(c)
            domain.prepare(authority, c, state, command, actor, now=NOW, editorial_policy=current_editorial_policy())
    assert state == before
    with repo._connection() as c:
        assert c.execute(f"SELECT count(*) FROM {p.SCHEMA}.versions WHERE namespace=%s", (domain.DEVELOPMENT,)).fetchone()[0] == 0


def test_revision_cas_race_has_one_winner_and_preserves_both_inputs(repository):
    from concurrent.futures import ThreadPoolExecutor
    repo = repository[1]
    session, original, head, _ = retained(repo)
    alternatives = []
    for reason in ("scope_unresolved", "time_unresolved"):
        value = deepcopy(original)
        value["previous_report_sha256"] = head
        value["claims"][0]["holds"].append(reason)
        alternatives.append(value)
    def retain_one(value):
        try:
            return session.retain_revision(value, expected_head=head, operation_id=str(uuid4()))
        except ReportError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(retain_one, alternatives))
    assert sum(type(result) is dict for result in results) == 1
    assert "report_head_changed" in results
    assert session.read_current(original["lineage_id"])[1] in alternatives
    # The original immutable source artifact still resolves for both candidates.
    assert session.document(alternatives[0]) and session.document(alternatives[1])


def test_report_correction_makes_old_open_item_unavailable_until_reconfigured(repository):
    repo = repository[1]
    session, original, head, _ = retained(repo)
    authority, config = authority_fixture(repo, head)
    command = command_fixture(head)
    actor = Principal("fixture-editor", "editor", "fixture-session")
    with repo._connection(writing=True) as c:
        repo._validate(c)
        old = domain.prepare(authority, c, {}, command, actor, now=NOW, editorial_policy=current_editorial_policy()).outcome
    changed = deepcopy(original)
    changed["previous_report_sha256"] = head
    changed["claims"][0]["quantity"]["scope"] = "currently_affected"
    changed["claims"][0]["holds"].append("cumulative_active_scope_unreconciled")
    newer = session.retain_revision(changed, expected_head=head, operation_id=str(uuid4()))
    assert domain.projection(authority, now=NOW)["reports"][0]["development_status"] == "unavailable"
    config["current_reports"][0]["report_sha256"] = newer["report_sha256"]
    assert domain.projection(authority, now=NOW)["reports"][0]["development_status"] == "evidence_changed_refresh_required"
    with repo._connection(writing=True) as c:
        repo._validate(c)
        revised = domain.prepare(authority, c, {}, command_fixture(newer["report_sha256"]), actor, now=NOW,
                                 editorial_policy=current_editorial_policy()).outcome
    assert old["item_id"] == revised["item_id"] and old["item_sha256"] != revised["item_sha256"]
    assert session.read_current(original["lineage_id"])[1]["claims"][0]["quantity"]["scope"] == "currently_affected"
    with repo._connection() as c:
        _, item = domain._latest(c, original["lineage_id"])
    assert item["previous_sha256"] == old["item_sha256"] and item["sequence"] == 2


@pytest.mark.parametrize("mode", ["retained", "mismatch", "observer_failure"])
def test_actual_news_source_observer_uses_returned_result_without_extra_calls(repository, monkeypatch, mode):
    from src.data.newsworthiness import NewsRetrievalResult
    from src.orchestrator.sources import newsworthiness as runner
    from src.storage.retained_reports import RetainedNewsReportLane
    event = dict(kind="fire", headline="Invented retained news", window_start="2026-10-11", confidence="verified",
        impact=[dict(claim="reported effects", value=4, source_name="Invented agency", url="https://example.test/news", as_of="unknown")])
    calls = []
    monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
    def fetch():
        calls.append("fetch")
        # Each invented retrieval owns its own allowance; never copy its lock.
        return NewsRetrievalResult(events=[deepcopy(event)], verify_calls=1, verify_fetches=1)
    monkeypatch.setattr(runner, "fetch_news_events", fetch)
    monkeypatch.setattr(runner.time, "perf_counter", lambda: 1.0)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(runner.state, "datetime", Clock)
    baseline: BotState = {}
    observed: BotState = {}
    assert runner.run_newsworthiness(baseline, None) is None
    session = RetainedReportSession(repository[1])
    lane = RetainedNewsReportLane(session, (dict(event_index=0, event_sha256=digest(event) if mode != "mismatch" else "a"*64,
        lineage_id="fixture:news", expected_head=None, operation_id=str(uuid4())),), NOW_TEXT)
    if mode == "observer_failure":
        monkeypatch.setattr(RetainedNewsReportLane, "__call__", lambda *a: (_ for _ in ()).throw(OSError("invented storage outage")))
    result = runner.run_newsworthiness(observed, None, retention_observer=lane)
    assert observed == baseline and calls == ["fetch", "fetch"]
    assert result is not None
    if mode != "retained":
        assert result["status"] == "retention_unavailable"
        return
    assert result["status"] == "retained_metadata_only"
    report = result["reports"][0]
    receipt, document = session.read_current(report["lineage_id"], report["report_sha256"])
    assert document["legacy_metadata"]["event"] == event
    assert all(value is None for value in document["claims"][0]["times"].values())
    artifact = session.read_artifact(result["retrieval_artifact_id"])
    import json
    retained_result = json.loads(artifact[2])
    assert retained_result["verify_calls"] == 1
    assert retained_result["allowance"]["operation"] == "news_discovery"
    authority, config = authority_fixture(repository[1], report["report_sha256"])
    config["current_reports"][0]["lineage_id"] = report["lineage_id"]
    command = command_fixture(report["report_sha256"])
    command.payload["lineage_id"] = report["lineage_id"]
    with repository[1]._connection(writing=True) as c:
        development = domain.prepare(authority, c, {}, command, Principal("fixture-editor", "editor", "fixture-session"),
            now=NOW, editorial_policy=current_editorial_policy())
    assert development.outcome["status"] == "evidence_review_required" and not development.outcome["provider_request_created"]
