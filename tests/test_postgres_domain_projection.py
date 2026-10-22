"""Existing invented producers -> genuine PG reads -> fresh domain inspection.

Only task-owned Unix-socket databases and public fixtures. HTTP is replaced at
the client transport boundary by the same real authority context function.
"""
from copy import deepcopy
from datetime import date
import json
from uuid import uuid4

import pytest

from src.commands import domain_projection as domain
from src.commands import postgres_ghcn_source_results as ghcn_domain
from src.commands.postgres_authority import PostgresCommandAuthority
from src.orchestrator.ghcn_source_result_client import GhcnSourceResultClient
from src.storage import postgres_projection as pg
from src.storage import scientific_supply, cyclone_supply, physical_events, retained_reports
from src.storage import ghcn_runtime_inputs
from tests import test_postgres_physical_events as episodes
from tests import test_postgres_report_development as reports
from tests.test_postgres_command_authority import options
from tests.test_postgres_projection import cluster as cluster, database as database, repository as repository, admin
from tests.test_ghcn_runtime_inputs import source_bytes as source_bytes
from tests.test_domain_projection import cli, authority, story, database_dump

OWNERS = {
    scientific_supply.NAMESPACE: "src.storage.scientific_supply",
    cyclone_supply.NAMESPACE: "src.storage.cyclone_supply",
    physical_events.REVISION: "src.storage.physical_events",
    retained_reports.REVISION: "src.storage.retained_reports",
    ghcn_runtime_inputs.INPUT: "src.storage.ghcn_runtime_inputs",
    # Raw owner artifacts are deliberately opaque, while retaining exact bytes.
    retained_reports.ARTIFACT: "src.storage.retained_reports",
    ghcn_runtime_inputs.RAW: "src.storage.ghcn_runtime_inputs",
}


def exported(repo):
    with repo._connection() as connection:
        repo._validate(connection)
        keys = connection.execute(f"SELECT namespace,snapshot_id FROM {pg.SCHEMA}.versions WHERE namespace=ANY(%s) ORDER BY namespace,snapshot_id", (list(OWNERS),)).fetchall()
    packets = []
    for namespace, identity in keys:
        receipt, value = repo.read(namespace, identity)
        packets.append(domain.projection_packet(receipt, value, owner=OWNERS[namespace]))
    return packets


def write_packets(tmp_path, packets):
    paths = []
    for index, packet in enumerate(packets):
        path = tmp_path / f"owner{index}.json"
        path.write_text(json.dumps(packet))
        paths.append(path)
    return paths


def absolute_extreme_owner_record(repo, maximum, minimum):
    from src.data import open_meteo
    day = date(2026, 10, 20)
    event = open_meteo.detect_absolute_extreme(40.0, -111.0, maximum, minimum,
        "Invented", "United States", signal_date=day, data_source="ghcn")
    assert event is not None
    evidence = dict(evidence_type="observed", source_product="noaa-ghcn-daily-v2", unit="C",
        station_id="USW00000001", valid_date=day.isoformat(), reporting_interval_known=False,
        valid_start=None, valid_end=None, timezone=None, baseline={})
    event.evidence = deepcopy(evidence)
    bundle = open_meteo.ExtremeSignalBundle(city=event.city, country=event.country,
        absolute_extreme=event, today_max_c=maximum, today_min_c=minimum, signal_date=day,
        station_id=evidence["station_id"], lat=40.0, lon=-111.0, evidence=evidence)
    session = scientific_supply.ScientificSupplySession(repo, str(uuid4()), "capture", "2026-10-21T12:00:00Z", "a" * 40)
    session.capture([bundle], [], dict(status="success", threshold_verification="unknown"))
    receipt, value = repo.read(scientific_supply.NAMESPACE, session.snapshot_id)
    return event, session, receipt, value


@pytest.mark.parametrize("maximum,minimum,kind,variable,field", [
    (55.0, 10.0, "hot", "TMAX", "today_max_c"),
    (10.0, -50.0, "cold", "TMIN", "today_min_c"),
    (None, -50.0, "cold", "TMIN", "today_min_c"),
])
def test_absolute_extreme_detector_owner_projection_exact_observation(repository, tmp_path, maximum, minimum, kind, variable, field):
    repo = repository[1]
    event, session, receipt, value = absolute_extreme_owner_record(repo, maximum, minimum)
    assert event.kind == kind
    local = authority(tmp_path, {})
    owner_packet = domain.projection_packet(receipt, value, owner="src.storage.scientific_supply")
    view = cli(local.path, write_packets(tmp_path, [owner_packet]))["typed_domain"]
    claim = next(obj for obj in view["objects"] if obj["core"]["kind"] == "claim_revision")
    relation = claim["relationships"][0]
    target = next(obj for obj in view["objects"] if obj["reference"] == relation["target"])
    assert relation["disposition"] == "present_in_inspection"
    assert relation["target"]["locator"] == f"/bundles/0/{field}"
    assert target["core"]["variable"] == variable
    assert target["core"]["value"] == claim["core"]["value"] == event.today_temp_c
    assert target["core"]["product"] == "noaa-ghcn-daily-v2" and target["core"]["unit"] == "C"
    assert all(obj["qualification"] == "unverified" and not obj["publication_authorized"] for obj in view["objects"])
    assert not view["source_truth_verified"] and not view["required_checks_completed"]
    assert repo.read(scientific_supply.NAMESPACE, session.snapshot_id) == (receipt, value)


@pytest.mark.parametrize("kind", ["unknown", "", True, None])
def test_absolute_extreme_unknown_or_malformed_kind_is_opaque_without_fallback(repository, tmp_path, kind):
    import base64
    repo = repository[1]
    _, session, receipt, value = absolute_extreme_owner_record(repo, 10.0, -50.0)
    # Preserve the genuine owner read; the altered caller-selected artifact must
    # remain opaque instead of acquiring a default TMAX or TMIN relationship.
    altered = deepcopy(value)
    altered["bundles"][0]["absolute_extreme"]["fields"]["kind"] = kind
    raw = pg._canonical(altered)
    owner_packet = domain.projection_packet(receipt, value, owner="src.storage.scientific_supply")
    owner_packet.update(sha256=domain.digest(raw), payload_base64=base64.b64encode(raw).decode("ascii"))
    local = authority(tmp_path, {})
    view = cli(local.path, write_packets(tmp_path, [owner_packet]))["typed_domain"]
    assert view["objects"] == []
    assert view["unprojected"][0]["disposition"] == "opaque_unverified"
    artifact = next(item for item in view["artifacts"] if item["reference"]["sha256"] == owner_packet["sha256"])
    assert base64.b64decode(artifact["payload_base64"]) == raw
    assert repo.read(scientific_supply.NAMESPACE, session.snapshot_id) == (receipt, value)


def test_real_source_baseline_observation_event_claim_producers_restart_and_restore(database, source_bytes, tmp_path, monkeypatch, cluster):
    import psycopg
    _, _, params = database
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    initial = {"drafts": [], "publish_ledger": {}, "source_health": {"other": {"untouched": True}}}
    owner.initialize(deepcopy(initial), runtime_role="projection_runtime")
    store = PostgresCommandAuthority(**options(params))
    store.configure_ghcn_source_results(source_bytes["baseline"])
    repo = store.projections
    client = GhcnSourceResultClient(repo, "http://127.0.0.1:1", "http://127.0.0.1:1", "invented", "invented")
    # No listener, HTTP request, source retrieval or provider transport is used.
    # Keep the actual capture/parser/owner writes and actual context calculation.
    monkeypatch.setattr(GhcnSourceResultClient, "context", lambda self: ghcn_domain.snapshot(store))
    run_id = str(uuid4())
    client.capture(run_id, source_bytes["baseline"], source_bytes["responses"], producer_revision="a" * 40,
        source_now=source_bytes["now"], started_at=source_bytes["started_at"], completed_at=source_bytes["completed_at"])
    event_owner, _, _, _ = episodes.seed(repo)
    reports.retained(repo)
    original = exported(repo)
    local = authority(tmp_path, {"drafts": [story()]})
    paths = write_packets(tmp_path, original)
    before = database_dump(local)
    first = cli(local.path, paths)
    assert cli(local.path, paths) == first
    assert exported(repo) == original and store.read() == (0, initial)
    assert database_dump(local) == before
    view = first["typed_domain"]
    assert {"draft_revision", "source_run", "observation", "baseline_revision", "physical_event_revision", "claim_revision"} <= {obj["core"]["kind"] for obj in view["objects"]}
    baselines = [obj for obj in view["objects"] if obj["core"]["kind"] == "baseline_revision"]
    assert len(baselines) == 1
    assert baselines[0]["core"]["database_sha256"] == source_bytes["baseline"].database_sha256
    assert baselines[0]["relationships"][0]["disposition"] == "present_in_inspection"
    observations = [obj for obj in view["objects"] if obj["core"]["kind"] == "observation" and obj["core"]["product"] == "noaa-ghcn-daily-v2"]
    assert len(observations) == 6
    assert all(obj["core"]["time"]["kind"] == "source_calendar_date" and obj["core"]["time"]["timezone"] is None
        and obj["core"]["interval"]["kind"] == "unknown" for obj in observations)
    report_claim = next(obj for obj in view["objects"] if obj["core"].get("evidence_class") == "unverified_imported_report_assertion")
    assert report_claim["core"]["value"] == 4 and type(report_claim["core"]["value"]) is int
    assert report_claim["core"]["time"]["timezone"] is None
    assert report_claim["relationships"][0]["disposition"] == "opaque"
    event_rows = [obj for obj in view["objects"] if obj["core"]["kind"] == "physical_event_revision"]
    assert len(event_rows) == 2
    assert all(relation["disposition"] == "present_in_inspection" for obj in event_rows for relation in obj["relationships"])
    # Genuine database backup/restore preserves the immutable owner exports.
    args, run, directory = cluster
    dump = directory / ("domain-" + uuid4().hex + ".dump")
    common = ("-h", args["host"], "-p", str(args["port"]), "-U", args["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", dump, params["dbname"])
    name = "domain_restore_" + uuid4().hex
    admin(args, psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, dump)
        restored = pg.PostgresProjectionRepository(socket_directory=args["host"], port=args["port"], database=name, user=repo.user)
        assert exported(restored) == original
        assert cli(local.path, write_packets(tmp_path, exported(restored))) == first
    finally:
        admin(args, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def test_unknown_schema_extra_fields_and_missing_conflicting_owner_joins(database, source_bytes, tmp_path, monkeypatch):
    _, _, params = database
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    owner.initialize({}, runtime_role="projection_runtime")
    store = PostgresCommandAuthority(**options(params))
    repo = store.projections
    event_owner, _, _, _ = episodes.seed(repo)
    packets = exported(repo)
    local = authority(tmp_path, {})
    # Removing a real source read does not fabricate its relationship.
    source_packet = next(packet for packet in packets if packet["namespace"] == cyclone_supply.NAMESPACE)
    limited = [packet for packet in packets if packet is not source_packet]
    missing = cli(local.path, write_packets(tmp_path, limited))["typed_domain"]
    assert any(relation["disposition"] == "missing" for obj in missing["objects"] for relation in obj["relationships"])
    import base64
    value = json.loads(base64.b64decode(source_packet["payload_base64"]))
    for change in (lambda row: row.update(schema_version=True), lambda row: row.update(reserved_core={"approved": True})):
        altered = deepcopy(value)
        change(altered)
        raw = pg._canonical(altered)
        changed = dict(source_packet, sha256=domain.digest(raw), payload_base64=base64.b64encode(raw).decode("ascii"))
        view = cli(local.path, write_packets(tmp_path, packets + [changed]))["typed_domain"]
        assert len(view["conflicts"]) == 1
        assert any(item["reference"]["sha256"] == changed["sha256"] for item in view["unprojected"])
        assert any(relation["disposition"] == "conflicting" for obj in view["objects"] for relation in obj["relationships"])
    # A present run/hash alone does not prove its asserted membership join.
    physical_packet = next(packet for packet in reversed(packets) if packet["namespace"] == physical_events.REVISION)
    altered = json.loads(base64.b64decode(physical_packet["payload_base64"]))
    altered["members"][0]["assertion_key"] = "0" * 64
    raw = pg._canonical(altered)
    changed = dict(physical_packet, sha256=domain.digest(raw), payload_base64=base64.b64encode(raw).decode("ascii"))
    view = cli(local.path, write_packets(tmp_path, [changed if packet is physical_packet else packet for packet in packets]))["typed_domain"]
    assert any(relation["role"] == "source_assertion" and relation["disposition"] == "conflicting"
        for obj in view["objects"] for relation in obj["relationships"])
