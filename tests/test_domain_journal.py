"""Private evidence retention, failure atomicity, and honest legacy import tests."""

from copy import deepcopy
from contextlib import closing
import hashlib
import json
import multiprocessing
import os
import sqlite3

import pytest

from src.commands import domain_journal as domain
from src.commands.local_cli import main
from src.commands.schema import CommandError, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from tests.test_command_authority import (
    EDITOR,
    NOW,
    authority,
    command,
    resolver,
    story,
    _die_before_commit,
    parallel_consume,
)


def rows(store, table):
    with closing(store._connect()) as db:
        return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]


def packet(store, row):
    return json.loads(store.read_artifact(row["artifact_sha256"]))


def test_exact_original_bytes_retained_and_passive_import_does_not_replace_state(tmp_path):
    current = {"drafts": [story()], "future_field": {"unrecognized": True}}
    store = authority(tmp_path, current)
    imported = deepcopy(current)
    imported["drafts"][0].update(
        text="Changed historical text.", status="approved", approval_binding={"passed": True}
    )
    raw = json.dumps(imported, indent=3, ensure_ascii=False).encode() + b"\n"
    report = store.import_snapshot(raw, import_id="historical-source-1", now=NOW)
    assert report["publication_authorized"] is False
    assert report["qualification"] == "retained_unverified"
    assert report["unprojected_top_level_fields"] == ["future_field"]
    assert store.read_artifact(report["artifact_sha256"]) == raw
    assert hashlib.sha256(raw).hexdigest() == report["artifact_sha256"]
    assert report["artifact_sha256"] != report["canonical_sha256"]
    assert store.read() == (0, current)
    assert store.journal() == []
    assert store.domain_status(verify=True)["artifact_bytes_verified"]


def test_stable_entities_and_distinct_revisions_despite_legacy_counter_reuse(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    changed = deepcopy(draft)
    changed["text"] = "The same legacy counter with genuinely different text."
    store.import_snapshot(canonical_json({"drafts": [changed]}).encode(), import_id="later")
    assert len(rows(store, "domain_entities")) == 1
    revs = rows(store, "domain_revisions")
    assert len(revs) == 2
    assert len({r["content_revision"] for r in revs}) == 1
    assert len({r["text_sha256"] for r in revs}) == 2
    original_evidence = revs[0]["evidence_sha256"]
    changed["review_context"]["two_bot"]["bundle"]["value"] = 99
    store.import_snapshot(canonical_json({"drafts": [changed]}).encode(), import_id="new-evidence")
    revs = rows(store, "domain_revisions")
    assert len(revs) == 3 and revs[-1]["evidence_sha256"] != original_evidence
    assert all(r["evidence_sha256"] != r["evidence_artifact_sha256"] for r in revs)


def test_import_replay_origin_conflict_and_namespace_isolation(tmp_path):
    store = authority(tmp_path, {})
    raw = b'{"drafts": []}\n'
    first = store.import_snapshot(raw, import_id="archive")
    counts = store.domain_status()["counts"]
    assert store.import_snapshot(raw, import_id="archive") == first
    assert store.domain_status()["counts"] == counts
    with pytest.raises(domain.DomainJournalError, match="different evidence"):
        store.import_snapshot(b'{"drafts": []}', import_id="archive")
    assert store.domain_status()["counts"] == counts
    with pytest.raises(domain.DomainJournalError, match="namespace"):
        store.initialize({}, source_namespace="different-source")
    other = SQLiteAuthority(tmp_path / "other.sqlite")
    other.initialize({"drafts": [story()]}, source_namespace="another-account")
    store.import_snapshot(canonical_json({"drafts": [story()]}).encode(), import_id="story")
    assert (
        rows(store, "domain_entities")[0]["entity_id"]
        != rows(other, "domain_entities")[0]["entity_id"]
    )


def test_ambiguous_missing_and_malformed_aliases_quarantined_without_discarding_packets(tmp_path):
    drafts = [
        story("duplicate"),
        story("duplicate"),
        {"text": "Missing alias"},
        {"id": 42, "text": "Numeric alias"},
        "unexpected",
        {"id": "unique", "text": None},
    ]
    store = authority(tmp_path, {"drafts": drafts})
    packets = [r for r in rows(store, "domain_occurrences") if r["kind"] == "draft_packet"]
    assert len(packets) == len(drafts)
    for row, expected in zip(packets, drafts):
        assert packet(store, row) == expected
        assert row["revision_id"] is None
    assert all(row["entity_id"] is None for row in packets[:5])
    assert json.loads(packets[0]["issues_json"]) == ["ambiguous_draft_alias"]
    assert json.loads(packets[-1]["issues_json"]) == ["draft_identity_unavailable"]


def test_historical_assertions_never_become_verified_checks_or_receipts(tmp_path):
    draft = story()
    draft.update(
        status="posted",
        revision_history=[{"text": "Earlier claim"}],
        review_binding={"passed": True},
    )
    draft["review_context"]["two_bot"]["fact_check"] = {"allowed": True}
    state = {
        "drafts": [draft, dict(story("receipt"), tweet_id="receipt-id", status="posted")],
        "memory": {"shipped_tweets": [{"text": "Generated but not known published"}]},
        "publish_ledger": {"key/with~escapes": {"phase": "sending"}},
        "source_runs": [{"execution": "unknown"}],
    }
    store = authority(tmp_path, state)
    packets = rows(store, "domain_occurrences")
    assert any(r["disposition"] == "posted_without_receipt" for r in packets)
    assert sum(r["disposition"] == "receipt_id_present" for r in packets) == 1
    memory = next(r for r in packets if r["kind"] == "generation_memory")
    assert memory["entity_id"] is None and memory["disposition"] == "publication_unverified_memory"
    ledger = next(r for r in packets if r["kind"] == "publication_assertion")
    assert ledger["locator"] == "/publish_ledger/key~1with~0escapes"
    assert "not_a_reconciled_delivery" in ledger["issues_json"]
    check = next(r for r in packets if r["locator"].endswith("/fact_check"))
    assert packet(store, check) == {"allowed": True}
    assert check["disposition"] == "retained_unverified"
    assert "execution_status_unverified" in check["issues_json"]
    report = json.loads(rows(store, "domain_snapshots")[0]["report_json"])
    assert (
        report["publication_authorized"] is False
        and "source_runs" in report["unprojected_top_level_fields"]
    )
    assert "not unique historical" in report["limitations"][0]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"drafts":[],"drafts":[]}',
        b'{"a": {"x":1,"x":2}}',
        b"[]",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":"\\ud800"}',
        b"\xff",
    ],
)
def test_ambiguous_nonfinite_or_invalid_utf8_imports_leave_no_partial_rows(tmp_path, raw):
    store = authority(tmp_path, {})
    before = store.domain_status()
    with pytest.raises(domain.DomainJournalError):
        store.import_snapshot(raw, import_id="invalid")
    assert store.domain_status() == before


def test_bounds_fail_atomically_without_terminal_command_rejection(tmp_path, monkeypatch):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    store.accept(cmd, EDITOR, now=NOW)
    before = store.domain_status()
    monkeypatch.setattr(domain, "MAX_OCCURRENCES", 1)
    with pytest.raises(domain.DomainJournalError, match="occurrence bound"):
        store.consume(resolver, now=NOW)
    assert store.read() == (0, {"drafts": [draft]})
    assert store.result(cmd.command_id) is None
    assert store.domain_status() == before
    monkeypatch.setattr(domain, "MAX_OCCURRENCES", 10000)
    assert store.consume(resolver, now=NOW)["status"] == "applied"
    assert len(rows(store, "domain_snapshots")) == 2


def test_artifact_bound_and_failed_bootstrap_rollback_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(domain, "MAX_ARTIFACT_BYTES", 10)
    store = SQLiteAuthority(tmp_path / "new.sqlite")
    with pytest.raises(domain.DomainJournalError):
        store.initialize({"drafts": [story()]})
    with closing(store._connect()) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    assert os.stat(store.path).st_mode & 0o777 == 0o600


def test_real_process_crash_rolls_back_evidence_then_retry_adds_once(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    store.accept(cmd, EDITOR, now=NOW)
    before = store.domain_status()
    child = multiprocessing.get_context("spawn").Process(
        target=_die_before_commit, args=(store.path, cmd.command_id)
    )
    child.start()
    child.join(timeout=15)
    assert child.exitcode == 23
    assert store.domain_status() == before
    assert store.read() == (0, {"drafts": [draft]}) and store.result(cmd.command_id) is None
    result = store.consume(resolver, now=NOW)
    assert store.consume(resolver, command_id=cmd.command_id, now=NOW) == result
    assert len(rows(store, "domain_snapshots")) == 2
    assert len(rows(store, "domain_revisions")) == 2
    snapshot = rows(store, "domain_snapshots")[-1]
    assert snapshot["command_id"] == cmd.command_id and snapshot["authority_version"] == 1
    assert json.loads(store.read_artifact(snapshot["artifact_sha256"])) == store.read()[1]


def test_parallel_consumers_commit_every_revision_with_its_command_result(tmp_path):
    drafts = [story(f"draft-{i}") for i in range(4)]
    store = authority(tmp_path, {"drafts": drafts})
    cmds = [command(d) for d in drafts]
    for cmd in cmds:
        store.accept(cmd, EDITOR, now=NOW)
    assert all(
        r["status"] == "applied" for r in parallel_consume(store, [cmd.command_id for cmd in cmds])
    )
    snapshots = rows(store, "domain_snapshots")
    assert len(snapshots) == 5 and len(rows(store, "domain_revisions")) == 8
    assert {s["command_id"] for s in snapshots if s["origin"] == "command"} == {
        c.command_id for c in cmds
    }
    for snapshot in snapshots:
        if snapshot["command_id"]:
            assert (
                store.result(snapshot["command_id"])["state_version"]
                == snapshot["authority_version"]
            )
    assert store.domain_status(verify=True)["artifact_bytes_verified"]


@pytest.mark.parametrize("table", list(domain._TABLES))
def test_immutable_tables_reject_update_delete_replace_and_upsert(tmp_path, table):
    store = authority(tmp_path, {"drafts": [story()]})
    with closing(store._connect()) as db:
        column = db.execute(f"PRAGMA table_info({table})").fetchone()["name"]
        for sql in [
            f"UPDATE {table} SET {column}={column}",
            f"DELETE FROM {table}",
            f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}",
            f"INSERT INTO {table} SELECT * FROM {table} WHERE true ON CONFLICT DO UPDATE SET {column}=excluded.{column}",
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable domain evidence"):
                db.execute(sql)
    assert store.domain_status(verify=True)["artifact_bytes_verified"]


def test_unknown_schema_and_removed_guards_refuse_work(tmp_path):
    store = authority(tmp_path, {"drafts": [story()]})
    with closing(store._connect()) as db:
        db.execute("DROP TRIGGER domain_artifacts_no_update")
    with pytest.raises(domain.DomainJournalError, match="guards changed"):
        store.import_snapshot(b"{}", import_id="unsafe")
    with pytest.raises(domain.DomainJournalError, match="guards changed"):
        store.initialize(store.read()[1])
    with closing(store._connect()) as db:
        db.execute(domain._schema_objects()["domain_artifacts_no_update"])
        db.execute("DROP TRIGGER domain_schema_no_update")
        db.execute("UPDATE domain_schema SET version=999")
        db.execute(domain._schema_objects()["domain_schema_no_update"])
    with pytest.raises(domain.DomainJournalError, match="Unsupported"):
        store.domain_status()


def test_corrupt_artifact_hash_is_detected_even_when_length_matches(tmp_path):
    store = authority(tmp_path, {"drafts": [story()]})
    artifact = rows(store, "domain_artifacts")[0]
    with closing(store._connect()) as db:
        db.execute("DROP TRIGGER domain_artifacts_no_update")
        db.execute(
            "UPDATE domain_artifacts SET payload=? WHERE sha256=?",
            (b"x" * artifact["byte_count"], artifact["sha256"]),
        )
        db.execute(domain._schema_objects()["domain_artifacts_no_update"])
    with pytest.raises(domain.DomainJournalError, match="identity"):
        store.read_artifact(artifact["sha256"])
    with pytest.raises(domain.DomainJournalError, match="identity"):
        store.domain_status(verify=True)


def test_backup_restore_preserves_all_bytes_relationships_and_state(tmp_path):
    store = authority(tmp_path, {"drafts": [story()]})
    store.import_snapshot(b'{"drafts":[],"opaque":[1,2,3]}\n', import_id="archive")
    backup = tmp_path / "backup.sqlite"
    with closing(store._connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    restored = SQLiteAuthority(backup)
    assert restored.read() == store.read()
    assert restored.domain_status(verify=True) == store.domain_status(verify=True)
    for artifact in rows(store, "domain_artifacts"):
        assert restored.read_artifact(artifact["sha256"]) == store.read_artifact(artifact["sha256"])


def test_explicit_existing_authority_migration_is_atomic_and_idempotent(tmp_path):
    store = authority(tmp_path, {"drafts": [story()]})
    # Emulate the previous local-only schema, preserving its current state/version.
    with closing(store._connect()) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for table in reversed(domain._TABLES):
            db.execute(f"DROP TABLE {table}")
    with pytest.raises(domain.DomainJournalError, match="migration is required"):
        store.import_snapshot(b"{}", import_id="before-migration")
    current = store.read()
    store.initialize(current[1])
    counts = store.domain_status()["counts"]
    store.initialize(current[1])
    assert store.read() == current and store.domain_status()["counts"] == counts
    assert counts["domain_snapshots"] == 1


def test_foreign_database_is_unchanged_and_missing_reads_do_not_create_files(tmp_path):
    path = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE thresholds (data TEXT)")
        db.commit()
    before = path.read_bytes()
    with pytest.raises(domain.DomainJournalError, match="separate local"):
        SQLiteAuthority(path).initialize({})
    assert path.read_bytes() == before
    absent = tmp_path / "absent.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        SQLiteAuthority(absent).read()
    assert not absent.exists()
    with pytest.raises(CommandError, match="production"):
        SQLiteAuthority(path, environment="production")


def test_cli_passive_import_and_integrity_status(tmp_path, capsys):
    base = ["--database", str(tmp_path / "cli.sqlite")]
    initial = tmp_path / "state.json"
    initial.write_bytes(b'{"drafts":[]}\n')
    archive = tmp_path / "archive.json"
    archive.write_bytes(b'{"drafts":[],"opaque":true}')
    assert (
        main(base + ["init", "--state", str(initial), "--source-namespace", "private-account"]) == 0
    )
    assert main(base + ["import", "--state", str(archive), "--import-id", "archive-1"]) == 0
    assert main(base + ["domain-status", "--verify"]) == 0
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert outputs[1]["publication_authorized"] is False
    assert (
        outputs[2]["artifact_bytes_verified"] is True
        and outputs[2]["production_authority"] is False
    )
    assert outputs[2]["counts"]["domain_snapshots"] == 2


def test_cross_snapshot_alias_reuse_for_a_different_event_is_quarantined(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    draft["event_id"] = "another-event"
    report = store.import_snapshot(
        canonical_json({"drafts": [draft]}).encode(), import_id="collision"
    )
    occurrence = next(
        r
        for r in rows(store, "domain_occurrences")
        if r["snapshot_id"] == report["snapshot_id"] and r["kind"] == "draft_packet"
    )
    assert occurrence["entity_id"] is None and occurrence["revision_id"] is None
    assert json.loads(occurrence["issues_json"]) == ["conflicting_legacy_event_alias"]
    assert packet(store, occurrence) == draft
    assert len(rows(store, "domain_entities")) == 1
    assert len(rows(store, "domain_revisions")) == 1
