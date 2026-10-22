"""Real owners to read-only inspection, with invented data and exact opaque bytes."""
import base64
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.commands import domain_projection as domain
from src.commands.local_cli import main
from src.commands.schema import canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from src.data import places
from src.storage import postgres_projection as pg
from tests.test_command_authority import authority, story
from tests import test_check_executor as checks

store, inputs, case = checks.store, checks.inputs, checks.case


def record(raw, *, owner="invented.unknown", namespace="invented-opaque-v1", identity="fixture1"):
    return domain.Record(domain.OwnerRef(owner=owner, namespace=namespace, record_id=identity,
        sha256=domain.digest(raw)), raw, "caller_supplied_integrity_only")


def packet(row):
    return dict(schema_version=1, owner=row.reference.owner, namespace=row.reference.namespace,
        record_id=row.reference.record_id, sha256=row.reference.sha256,
        payload_base64=base64.b64encode(row.raw).decode("ascii"))


def cli(database, paths=()):
    arguments = [sys.executable, "-m", "src.commands.local_cli", "--database", str(database), "domain-status", "--verify"]
    for path in paths:
        arguments.extend(["--projection-record", str(path)])
    # Child inherits only the explicit offline test environment; no provider keys.
    env = {"PATH": os.environ["PATH"], "LC_ALL": "C", "no_proxy": "*"}
    child = subprocess.run(arguments, env=env, capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    return json.loads(child.stdout)


def database_dump(store):
    with closing(store._connect()) as connection:
        return tuple(connection.iterdump())


def test_actual_registry_and_opaque_bytes_through_fresh_cli_restart_restore(tmp_path):
    store = authority(tmp_path, {"drafts": [story()], "unknown_assertion": {"passed": True}})
    row = places.registry()[0]
    known = record(pg._canonical(row), owner="src.data.places", namespace="place-registry-v1", identity=row["place_id"])
    # Raw spelling, large integer and bool/number differences are retained even
    # where a supported projection codec cannot safely interpret them.
    raw = b'{"int":1, "float":1.0,"exp":1e0,"neg":-0.0,"huge":9007199254740993,"bool":true}\n'
    unknown = record(raw)
    files = []
    for index, item in enumerate([known, unknown]):
        path = tmp_path / f"record{index}.json"
        path.write_text(json.dumps(packet(item)))
        files.append(path)
    before = database_dump(store)
    reports = [cli(store.path, files), cli(store.path, files)]
    backup = tmp_path / "restore.sqlite"
    with closing(store._connect()) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    reports.append(cli(backup, files))
    assert reports[0] == reports[1] == reports[2]
    assert database_dump(store) == before
    view = reports[0]["typed_domain"]
    place = next(obj for obj in view["objects"] if obj["core"]["kind"] == "place")
    assert place["core"]["place_id"] == row["place_id"]
    assert place["core"]["sampling_point_id"] == places.sampling_point_id(row["lat"], row["lon"])
    artifact = next(item for item in view["artifacts"] if item["reference"] == unknown.reference.model_dump())
    assert base64.b64decode(artifact["payload_base64"]) == raw
    assert artifact["provenance"] == "caller_supplied_integrity_only"
    assert any(item["reference"] == unknown.reference.model_dump() and item["disposition"] == "opaque_unverified" for item in view["unprojected"])
    assert view["required_checks_completed"] is False
    assert view["publication_authorized"] is False and not view["source_truth_verified"]
    assert all(obj["qualification"] == "unverified" for obj in view["objects"])


@pytest.mark.parametrize("change", ["bool_version", "unknown_key", "wrong_hash", "duplicate_key", "bad_base64"])
def test_closed_record_envelope_refuses_before_application_mutation(tmp_path, change, capsys):
    store = authority(tmp_path, {})
    item = packet(record(b'{"n":1.0}'))
    if change == "bool_version":
        item["schema_version"] = True
    elif change == "unknown_key":
        item["core"] = {"approved": True}
    elif change == "wrong_hash":
        item["sha256"] = "f" * 64
    elif change == "bad_base64":
        item["payload_base64"] = "@@@"
    raw = json.dumps(item).encode()
    if change == "duplicate_key":
        raw = b'{"schema_version":1,' + raw[1:]
    path = tmp_path / "packet.json"
    path.write_bytes(raw)
    before = database_dump(store)
    assert main(["--database", store.path, "domain-status", "--projection-record", str(path)]) == 2
    assert database_dump(store) == before
    assert "invalid_domain_record_envelope" in capsys.readouterr().err


def test_bound_file_count_total_and_payload_without_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(domain, "MAX_RECORDS", 1)
    with pytest.raises(domain.DomainProjectionError, match="record_count_bound"):
        domain.read_packets(["must-not-be-opened", "must-not-be-opened"])
    path = tmp_path / "record.json"
    path.write_text(json.dumps(packet(record(b'{"x":1}'))))
    monkeypatch.setattr(domain, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(domain.DomainProjectionError, match="input_byte_bound"):
        domain.read_packets([str(path)])


@pytest.mark.parametrize("raw", [b'{"x":NaN}', b'{"x":1,"x":2}', b'\xff', b'{"n":9007199254740993}'])
def test_malformed_supported_extension_stays_opaque_with_exact_bytes(raw):
    item = record(raw, owner="src.storage.scientific_supply", namespace="scientific-supply-ghcn-v1")
    view = domain.inspect_records([item])
    assert view["objects"] == [] and view["unprojected"][0]["reason"] == "malformed_or_unsupported_namespaced_extension"
    assert base64.b64decode(view["artifacts"][0]["payload_base64"]) == raw


def test_strict_core_rejects_bool_and_retains_integer_float_distinction():
    values = dict(subject_id="station", variable="TMAX", value=True, unit="degC", product="fixture",
        evidence_class="unverified", time=domain.TimeValue(kind="unknown"), interval=domain.TimeValue(kind="unknown"))
    with pytest.raises(ValidationError):
        domain.Observation(**values)
    integer = domain.Observation(**(values | {"value": 1}))
    floating = domain.Observation(**(values | {"value": 1.0}))
    assert type(integer.value) is int and type(floating.value) is float
    one, another = record(b'{"n":1}'), record(b'{"n":1.0}')
    view = domain.inspect_records([one, another])
    assert len(view["conflicts"]) == 1
    assert one.reference.sha256 != another.reference.sha256


def test_public_envelope_schemas_match_the_closed_runtime_contract():
    root = Path(__file__).resolve().parents[1] / "docs/schemas"
    for name, cls in [("domain-object-v1.schema.json", domain.DomainObject), ("domain-owner-packet-v1.schema.json", domain.OwnerPacket)]:
        expected = cls.model_json_schema()
        expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        assert json.loads((root / name).read_text()) == expected
        assert expected["additionalProperties"] is False


def test_native_job_review_checks_and_observation_are_actual_owner_reads(case, tmp_path):
    store = case["store"]
    checks.run(case, "deterministic")
    before = database_dump(store)
    first = cli(store.path)
    from src.commands import domain_journal
    with closing(sqlite3.connect(Path(store.path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        assert domain_journal.inspect(connection, verify=True) == first
    view = first["typed_domain"]
    kinds = {obj["core"]["kind"] for obj in view["objects"]}
    assert {"job", "review", "check_execution"} <= kinds
    check_rows = [obj for obj in view["objects"] if obj["core"]["kind"] == "check_execution"]
    assert len(check_rows) == 4
    assert {obj["core"]["disposition"] for obj in check_rows} == {"passed", "pending"}
    assert all(obj["core"]["check_set_id"] == case["identity"] for obj in check_rows)
    assert all(obj["relationships"][0]["disposition"] == "present_in_inspection" for obj in check_rows)
    backup = tmp_path / "checks-restored.sqlite"
    with closing(store._connect()) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    assert cli(backup) == first == cli(store.path)
    assert database_dump(store) == before


def test_legacy_import_is_opaque_and_immutable_reports_not_rewritten(tmp_path):
    store = authority(tmp_path, {})
    raw = b'{"source_runs":[{"id":"assertion","passed":true}],"observations":[{"value":1e0}],"drafts":[]}\n'
    report = store.import_snapshot(raw, import_id="asserted-history")
    before = database_dump(store)
    view = store.domain_status()["typed_domain"]
    assert not [obj for obj in view["objects"] if obj["core"]["kind"] in {"source_run", "observation"}]
    assert store.import_snapshot(raw, import_id="asserted-history") == report
    assert store.read_artifact(report["artifact_sha256"]) == raw
    assert "source_runs" in report["unprojected_top_level_fields"]
    assert database_dump(store) == before
