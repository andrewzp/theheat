"""Synthetic joint-review retention; actual SQLite transactions and process failures."""

from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import multiprocessing
import os
import sqlite3

import pytest

from src.commands import domain_journal as domain, media_journal as media
from src.commands.schema import CommandError, Principal, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.joint_review import joint_media_review_status, record_joint_media_review
from src.media.review_packet import MediaReviewError, build_media_review_packet
from tests.test_joint_media_review import ACTOR, WHEN, payload
from tests.test_media_review_packet import seed as seed

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


def resolve(subject):
    return Principal(subject, "editor", "freshly-resolved-local-context")


@pytest.fixture
def package(seed):
    inputs = deepcopy(seed)
    manifest = inputs["renderer_manifest"]
    assets = {
        "input.json": (json.dumps(inputs["graphic_spec"], ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
        "preview.svg": b"synthetic svg", "preview.pdf": b"synthetic pdf",
        "preview.png": inputs["png_bytes"], "alt.txt": (manifest["alt_text"] + "\n").encode(),
    }
    request = {key: inputs[key] for key in media._INPUTS}
    request.update(payload=payload(), reviewed_at=WHEN,
                   expected_packet_sha256=build_media_review_packet(**inputs)["packet_sha256"])
    return dict(inputs=inputs, request=request, assets=assets)


def store_for(tmp_path, package, *, drafts=None):
    store = SQLiteAuthority(tmp_path / "authority.sqlite")
    state = {
        "drafts": [deepcopy(package["inputs"]["draft"])] if drafts is None else drafts,
        "publish_ledger": {"retained": {"phase": "unknown"}},
        "publication_control": {"enabled": False}, "unrelated": {"preserve": True},
    }
    store.initialize(state)
    return store


def retain(store, package, **overrides):
    args = dict(
        principal=ACTOR, resolve_principal=resolve, assets=package["assets"], now=NOW,
    )
    return store.retain_media_review(
        package["inputs"]["draft"]["id"], package["request"], **(args | overrides),
    )


def rows(store, table):
    with closing(store._connect()) as db:
        return [dict(r) for r in db.execute(f"SELECT * FROM {table}")]


def snapshot(store):
    return {table: rows(store, table) for table in [
        "authority_state", "command_intents", "command_events", "command_results",
        "domain_artifacts", "retained_media_reviews",
    ]}


def test_exact_roundtrip_idempotency_and_no_draft_or_command_mutation(tmp_path, package):
    store = store_for(tmp_path, package)
    state_before, inputs_before = store.read(), deepcopy(package)
    old_artifacts = rows(store, "domain_artifacts")
    receipt = retain(store, package)
    all_rows = snapshot(store)
    assert retain(store, package, now=NOW + timedelta(hours=1)) == receipt
    assert snapshot(store) == all_rows
    found = store.read_media_review(receipt["review_sha256"])
    assert found["assets"] == package["assets"] and found["receipt"] == receipt
    assert found["capture"]["draft"] == package["inputs"]["draft"]
    assert receipt["currentness"] == "not_evaluated" and receipt["synthetic"] is True
    assert receipt["publication_approved"] is receipt["production_attachment_authorized"] is False
    assert store.read() == state_before and store.journal() == [] and package == inputs_before
    for row in old_artifacts:
        assert store.read_artifact(row["sha256"]) == row["payload"]
    assert found["record"]["reviewer"]["authentication_context"] == ACTOR.authentication_context
    # Only fresh, independent inputs/role can establish effective acceptance.
    assert joint_media_review_status(
        found["record"], **package["inputs"], expected_review_sha256=receipt["review_sha256"],
        current_principal=resolve(ACTOR.subject),
    )["accepted"]


@pytest.mark.parametrize("decision", ["reject", "needs_changes"])
def test_negative_reviews_are_retained_without_suggesting_acceptance(tmp_path, package, decision):
    store = store_for(tmp_path, package)
    package["request"]["payload"] = payload(decision)
    package["request"]["payload"]["confirmations"]["alt_text_agrees"] = None
    result = store.read_media_review(retain(store, package)["review_sha256"])
    assert result["record"]["decision"] == decision
    assert result["receipt"]["currentness"] == "not_evaluated"


@pytest.mark.parametrize("resolved", [
    None, Principal(ACTOR.subject, "viewer", "revoked"), Principal("different", "publisher", "other"), {},
])
def test_current_role_is_required_even_for_duplicate_retry(tmp_path, package, resolved):
    store = store_for(tmp_path, package)
    first = retain(store, package)
    before = snapshot(store)
    with pytest.raises(CommandError):
        retain(store, package, resolve_principal=lambda subject: resolved)
    assert snapshot(store) == before
    assert store.read_media_review(first["review_sha256"])["receipt"]["currentness"] == "not_evaluated"


def test_resolver_runs_after_write_lock_and_original_identity_is_preserved(tmp_path, package):
    store = store_for(tmp_path, package)
    observed = []

    def locked_resolver(subject):
        with closing(sqlite3.connect(store.path, timeout=0)) as contender:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("BEGIN IMMEDIATE")
        observed.append(subject)
        return resolve(subject)

    retain(store, package, resolve_principal=locked_resolver)
    assert observed == [ACTOR.subject]
    with pytest.raises(CommandError, match="trusted ingress"):
        retain(store, package, principal={"subject": ACTOR.subject, "role": "publisher"})


@pytest.mark.parametrize("kind", ["missing", "ambiguous", "changed_text", "new_revision", "changed_evidence"])
def test_independent_current_authority_draft_is_required(tmp_path, package, kind):
    original = deepcopy(package["inputs"]["draft"])
    drafts = [original]
    if kind == "missing":
        drafts = []
    elif kind == "ambiguous":
        drafts = [original, deepcopy(original)]
    elif kind == "changed_text":
        invalidate_text(original, "Changed current local draft.")
    elif kind == "new_revision":
        original["content_revision"] += 1
    else:
        original["review_context"]["source_note"] = "new evidence"
    store = store_for(tmp_path, package, drafts=drafts)
    before = snapshot(store)
    with pytest.raises((MediaReviewError, media.MediaJournalError)):
        retain(store, package)
    assert snapshot(store) == before


@pytest.mark.parametrize("name", sorted(media._LIMITS))
def test_any_substituted_asset_rolls_back_everything(tmp_path, package, name):
    store = store_for(tmp_path, package)
    before = snapshot(store)
    package["assets"][name] += b"tampered"
    with pytest.raises(media.MediaJournalError, match="manifest_mismatch"):
        retain(store, package)
    assert snapshot(store) == before


@pytest.mark.parametrize("change", ["missing", "unknown", "nonbytes", "empty", "json_bound", "png_bound"])
def test_asset_shape_type_and_real_size_bounds(tmp_path, package, change):
    store = store_for(tmp_path, package)
    before = snapshot(store)
    assets = package["assets"]
    if change == "missing":
        del assets["preview.svg"]
    elif change == "unknown":
        assets["../outside"] = b"untrusted"
    elif change == "nonbytes":
        assets["preview.png"] = bytearray(assets["preview.png"])
    elif change == "empty":
        assets["preview.pdf"] = b""
    elif change == "json_bound":
        assets["input.json"] = b"x" * (media.MAX_JSON_BYTES + 1)
    else:
        assets["preview.png"] = b"x" * (media.MAX_PNG_BYTES + 1)
    with pytest.raises(media.MediaJournalError):
        retain(store, package)
    assert snapshot(store) == before


@pytest.mark.parametrize("when", ["2026-09-30T12:05:01Z", "2026-02-30T12:00:00Z", "not-time"])
def test_invalid_or_excessively_future_review_time(tmp_path, package, when):
    store = store_for(tmp_path, package)
    before = snapshot(store)
    package["request"]["reviewed_at"] = when
    with pytest.raises((CommandError, media.MediaJournalError)):
        retain(store, package)
    assert snapshot(store) == before


def test_review_time_boundary_and_aware_clock(tmp_path, package):
    store = store_for(tmp_path, package)
    package["request"]["reviewed_at"] = "2026-09-30T12:05:00Z"
    assert retain(store, package)["recorded_at"] == WHEN
    with pytest.raises(CommandError, match="aware UTC"):
        retain(store, package, now=NOW.replace(tzinfo=None))


def test_failure_after_all_writes_rolls_back_blobs_and_row(tmp_path, package):
    store = store_for(tmp_path, package)
    before = snapshot(store)

    def failure():
        raise OSError("synthetic disk failure")

    with pytest.raises(OSError):
        retain(store, package, before_commit=failure)
    assert snapshot(store) == before
    assert retain(store, package)["synthetic"] is True


def test_partial_asset_write_failure_leaves_no_orphan_blobs(tmp_path, package, monkeypatch):
    store = store_for(tmp_path, package)
    before = snapshot(store)
    original = domain._artifact
    calls = []

    def fail_third(connection, data):
        calls.append(len(data))
        if len(calls) == 3:
            raise OSError("synthetic partial write failure")
        return original(connection, data)

    monkeypatch.setattr(domain, "_artifact", fail_third)
    with pytest.raises(OSError, match="partial write"):
        retain(store, package)
    assert len(calls) == 3 and snapshot(store) == before


@pytest.mark.parametrize("field", ["draft", "principal", "publication_approved"])
def test_request_cannot_inject_authority_or_approval_fields(tmp_path, package, field):
    store = store_for(tmp_path, package)
    before = snapshot(store)
    package["request"][field] = {"claim": "untrusted"}
    with pytest.raises(media.MediaJournalError, match="invalid_media_request"):
        retain(store, package)
    assert snapshot(store) == before


def _process_write(path, package, start, queue, die=False):
    start.wait(10)
    store = SQLiteAuthority(path)
    result = retain(store, package, before_commit=(lambda: os._exit(91)) if die else None)
    queue.put(result)


def test_separate_process_race_commits_one_exact_receipt(tmp_path, package):
    store = store_for(tmp_path, package)
    before = store.read()
    ctx = multiprocessing.get_context("spawn")
    start, queue = ctx.Event(), ctx.Queue()
    children = [ctx.Process(target=_process_write, args=(store.path, package, start, queue)) for _ in range(2)]
    for child in children:
        child.start()
    start.set()
    results = [queue.get(timeout=30) for _ in children]
    for child in children:
        child.join(30)
        assert child.exitcode == 0
    assert results[0] == results[1] and len(rows(store, "retained_media_reviews")) == 1
    assert store.read() == before


def test_process_death_before_commit_and_lost_ack_recovery(tmp_path, package):
    store = store_for(tmp_path, package)
    before = snapshot(store)
    ctx = multiprocessing.get_context("spawn")
    start, queue = ctx.Event(), ctx.Queue()
    child = ctx.Process(target=_process_write, args=(store.path, package, start, queue, True))
    child.start()
    start.set()
    child.join(30)
    assert child.exitcode == 91 and snapshot(store) == before
    # A completed commit's caller can lose the return value and retry safely.
    retain(store, package)
    count = len(rows(store, "domain_artifacts"))
    recovered = retain(SQLiteAuthority(store.path), package)
    assert recovered == store.read_media_review(recovered["review_sha256"])["receipt"]
    assert len(rows(store, "domain_artifacts")) == count


@pytest.mark.parametrize("table", list(media._TABLES))
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE"])
def test_media_tables_are_append_only_even_with_replace(tmp_path, package, table, operation):
    store = store_for(tmp_path, package)
    retain(store, package)
    with closing(store._connect()) as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable media review"):
            if operation == "UPDATE":
                key = "schema_sha256" if table == "media_review_schema" else "packet_sha256"
                db.execute(f"UPDATE {table} SET {key}={key}")
            elif operation == "DELETE":
                db.execute(f"DELETE FROM {table}")
            else:
                db.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")


@pytest.mark.parametrize("tamper", ["drop_trigger", "extra_trigger", "extra_table", "artifact_bytes"])
def test_schema_or_artifact_tampering_is_refused(tmp_path, package, tamper):
    store = store_for(tmp_path, package)
    receipt = retain(store, package)
    with closing(store._connect()) as db:
        if tamper == "drop_trigger":
            db.execute("DROP TRIGGER retained_media_reviews_no_update")
        elif tamper == "extra_trigger":
            db.execute("CREATE TRIGGER injected AFTER INSERT ON retained_media_reviews BEGIN SELECT 1; END")
        elif tamper == "extra_table":
            db.execute("CREATE TABLE foreign_system (secret TEXT)")
        else:
            # Restore the exact trigger after illicit byte modification so the
            # independent artifact hash, not only the schema check, detects it.
            original = db.execute("SELECT sql FROM sqlite_master WHERE name='domain_artifacts_no_update'").fetchone()[0]
            db.execute("DROP TRIGGER domain_artifacts_no_update")
            sha = hashlib.sha256(package["assets"]["preview.svg"]).hexdigest()
            db.execute("UPDATE domain_artifacts SET payload=?,byte_count=? WHERE sha256=?", (b"changed", 7, sha))
            db.execute(original)
    with pytest.raises((domain.DomainJournalError, media.MediaJournalError)):
        store.read_media_review(receipt["review_sha256"])
    with pytest.raises((domain.DomainJournalError, media.MediaJournalError)):
        retain(store, package)


def test_additive_migration_and_backup_preserve_original_state_and_artifacts(tmp_path, package):
    store = store_for(tmp_path, package)
    state = store.read()
    artifacts = rows(store, "domain_artifacts")
    # Exact previous-authority profile: remove only the new empty additive tables.
    with closing(store._connect()) as db:
        db.execute("DROP TABLE retained_media_reviews")
        db.execute("DROP TABLE media_review_schema")
    with pytest.raises(media.MediaJournalError, match="migration_required"):
        store.read_media_review("a" * 64)
    assert store.read() == state and rows(store, "domain_artifacts") == artifacts
    store.initialize(state[1])
    assert store.read() == state and rows(store, "domain_artifacts") == artifacts
    receipt = retain(store, package)
    backup = tmp_path / "backup.sqlite"
    with closing(store._connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    restored = SQLiteAuthority(backup)
    assert restored.read_media_review(receipt["review_sha256"]) == store.read_media_review(receipt["review_sha256"])
    assert restored.domain_status(verify=True) == store.domain_status(verify=True)
    assert restored.read() == state


def test_unrelated_state_version_advance_does_not_duplicate_retention(tmp_path, package):
    store = store_for(tmp_path, package)
    receipt = retain(store, package)
    # Simulate a committed unrelated authority command's version advance.
    with closing(store._connect()) as db:
        db.execute("UPDATE authority_state SET version=version+1")
    assert retain(store, package) == receipt
    assert receipt["authority_version_at_retention"] == 0 and store.read()[0] == 1


def test_later_draft_edit_does_not_change_retained_package(tmp_path, package):
    store = store_for(tmp_path, package)
    receipt = retain(store, package)
    historical = store.read_media_review(receipt["review_sha256"])
    version, current = store.read()
    invalidate_text(current["drafts"][0], "Changed after the retained review.")
    with closing(store._connect()) as db:
        db.execute("UPDATE authority_state SET version=?,state_json=?", (version + 1, canonical_json(current)))
    with pytest.raises(MediaReviewError):
        retain(store, package)
    assert store.read_media_review(receipt["review_sha256"]) == historical
    current_inputs = {**package["inputs"], "draft": current["drafts"][0],
                      "expected_draft_identity": draft_identity(current["drafts"][0])}
    assert joint_media_review_status(
        historical["record"], **current_inputs, expected_review_sha256=receipt["review_sha256"],
        current_principal=ACTOR,
    )["status"] == "obsolete"


def test_production_and_legacy_database_remain_refused(tmp_path, package):
    with pytest.raises(CommandError, match="cannot operate on production"):
        SQLiteAuthority(tmp_path / "production.sqlite", environment="production")
    path = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE legacy_state (state_json TEXT)")
    with pytest.raises(domain.DomainJournalError):
        SQLiteAuthority(path).initialize({"drafts": []})
