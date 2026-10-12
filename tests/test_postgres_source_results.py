"""Invented NHC captures through actual loopback ingress and shared PG authority."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4

import pytest
import responses

from src.commands import postgres_source_results as domain
from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import Command, CommandError, Principal, utc_text
from src.data import nhc
from src.orchestrator.cyclones import _process_cyclone_source
from src.orchestrator.source_result_client import SourceResultClient, SourceResultLane
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import CycloneSupplyError, CycloneSupplySession, digest
from src.storage.physical_events import PhysicalEpisodeSession, REVISION, OPERATION
from tests.test_postgres_preview_command_ingress import (preview as preview, cluster as cluster,
    database as database, http, ORIGIN, clean_environment, operator_file)
from tests.test_postgres_command_authority import options
from tests.test_command_authority import story
from src.state import DEFAULT_STATE
from tests.test_postgres_physical_events import advisory, EPISODE, isolated as isolated

BASE = "06f72333a6780360607293cec4f0386f440e0b9c"


@pytest.fixture
def configured(database, tmp_path):
    _, _, params = database
    initial = deepcopy(DEFAULT_STATE)
    initial.update(drafts=[story()], publish_ledger={}, cyclone_tiers={"unowned":3},
        cyclone_wind_history={"unowned":[dict(issued_at="2020-01-01T00:00:00Z", wind_kt=80)]},
        source_health={"other-source":{"opaque":[0,False,None,"untouched"]}},
        unowned_fixture={"negative_cache":["retained"], "unknown_cost":None},
        run_history=[dict(id="unowned-old-run", status="unknown")])
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    owner.initialize(initial, runtime_role="projection_runtime")
    authority = PostgresCommandAuthority(**options(params))
    authority.configure_source_results()
    operators = operator_file(tmp_path/"operators.json")
    server = PreviewServer(authority, Operators(operators), port=0, origin=ORIGIN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    args = ["--socket-directory", params["host"], "--database", params["dbname"],
        "--database-port", str(params["port"]), "--user", "projection_runtime", "--operators", str(operators), "--source-results"]
    def consume(command_id=None):
        result = subprocess.run([sys.executable, "-m", "src.commands.preview_worker", *args,
            *(["--command-id", command_id] if command_id else [])], env=clean_environment(),
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout+result.stderr
        return json.loads(result.stdout)["result"]
    client = SourceResultClient(authority.projections, f"http://127.0.0.1:{server.server_port}", ORIGIN, "editor", "invented-editor")
    yield client, authority, initial, Operators(operators), consume, params
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def retained(configured, *, rows=None, status="success", start=None, cities=None):
    client, authority, *_ = configured
    start = start or datetime.now(UTC)-timedelta(seconds=1)
    source = CycloneSupplySession(authority.projections, str(uuid4()), utc_text(start), BASE)
    receipt, _, _ = source.capture(rows if rows is not None else [advisory(issued_at=utc_text(start-timedelta(hours=1)))], {"status": status})
    value = dict(schema_version=1, source="nhc", supply_run_id=source.supply_run_id, supply_sha256=receipt.canonical_sha256,
        producer_revision=BASE, acquisition_started_at=utc_text(start), acquisition_completed_at=utc_text(start+timedelta(milliseconds=100)),
        duration_ms=100, cities=cities or [], cities_sha256=digest(cities or []), evidence_class="invented_local_capture")
    domain.retain_input(authority.projections, value)
    return source.supply_run_id, value


def descriptor(configured, run_id):
    client = configured[0]
    result = client.enroll(run_id)
    identity = result["command_id"]
    _, value = client.repository.read(domain.SUBMISSION, identity)
    return identity, value


def resign_descriptor(configured, value, **changes):
    value = deepcopy(value)
    value["request"]["command_id"] = str(uuid4())
    value["request"]["payload"].update(changes)
    value["runtime_input_sha256"] = value["request"]["payload"]["runtime_input_sha256"]
    domain.retain_exact(configured[0].repository, domain.SUBMISSION, value["request"]["command_id"], value)
    return value


def no_episode(authority):
    with authority.projections._connection() as c:
        return c.execute(f"SELECT count(*) FROM {p.SCHEMA}.versions WHERE namespace IN (%s,%s,%s)", (REVISION, OPERATION, domain.RESULT)).fetchone()[0] == 0


@responses.activate
def test_real_parser_source_command_http_worker_and_writer_request(configured, monkeypatch):
    client, authority, initial, _, consume, _ = configured
    now = datetime.now(UTC).replace(microsecond=0)
    forecast = now+timedelta(hours=12)
    raw = dict(id="AL012026", name="Invented A", intensity="100", lastUpdate=utc_text(now),
        latitude=15.0, longitude=-75.0, publicAdvisory={"advNum":"2A"},
        forecastAdvisory=dict(advNum="2A", issuance=utc_text(now), url="/text/fixture-source-result.shtml"))
    responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms":[raw]})
    responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-source-result.shtml",
        body=(f"FORECAST VALID {forecast:%d/%H%MZ} 15.0N 75.0W\nMAX WIND 100 KT\n"
              f"FORECAST VALID {forecast:%d/%H%MZ} 16.0N 76.0W\nMAX WIND 100 KT\n"))
    def forbid(*a, **k):
        raise AssertionError("Unowned producer/provider operation")
    import src.state as state
    monkeypatch.setattr(state, "write_state", forbid)
    from src.orchestrator import common, cyclones
    monkeypatch.setattr(common, "_enqueue_story_candidate", forbid)
    monkeypatch.setattr(cyclones, "_record_source_run", forbid)
    run = str(uuid4())
    cities = [dict(city="Invented North", country="United States", lat=15.0, lon=-75.0),
              dict(city="Invented South", country="Cuba", lat=16.0, lon=-76.0)]
    lane = SourceResultLane(client, run, BASE, cities)
    result = _process_cyclone_source(initial, None, source_key="nhc", source_label="NHC", fetch_fn=nhc.fetch_active_cyclones, detect_module=nhc, episode_lane=lane)
    assert len(responses.calls) == 2 and no_episode(authority)
    assert client.readback(run)["status"] == "pending"
    committed = consume(result["command_id"])
    assert committed["status"] == "applied" and committed["changed_ids"] == [] and committed["state_version"] == 1
    assert client.readback(run)["episodes"][0]["current"] is True
    prepared = client.prepare_requests(run)
    assert len(prepared["requests"]) == 2
    assert {row["bundle"]["raw_signal_dump"]["landmass_country"] for row in prepared["requests"]} == {"United States", "Cuba"}
    assert all(row["writer_request"]["messages"] and row["provider_transport"] == "not_attempted" for row in prepared["requests"])
    version, saved = authority.read()
    assert version == 1 and {k:v for k,v in saved.items() if k not in {"source_health", "run_history"}} == {k:v for k,v in initial.items() if k not in {"source_health", "run_history"}}
    assert saved["source_health"]["other-source"] == initial["source_health"]["other-source"]
    assert saved["run_history"][1:] == initial["run_history"]
    assert saved["run_history"][0]["sources"][0]["writer_attempted"] == 0
    assert consume(result["command_id"]) == committed
    assert client.resume(result["command_id"])["command"]["result"] == committed
    with pytest.raises(CycloneSupplyError, match="source_run_already_retained"):
        lane.capture_prepare(initial, nhc.fetch_active_cyclones)
    assert len(responses.calls) == 2


def test_duplicate_run_new_command_no_second_operational_effect(configured):
    client, authority, _, _, consume, _ = configured
    run, _ = retained(configured)
    first, _ = descriptor(configured, run)
    a = consume(first)
    version, before = authority.read()
    second, _ = descriptor(configured, run)
    b = consume(second)
    assert b["status"] == "unchanged" and b["source_run"]["reused"]
    assert b["source_run"]["result_command_id"] == a["command_id"]
    assert authority.read() == (version, before)


@pytest.mark.parametrize("failure", ["head", "policy", "input", "supply", "actor", "expired", "unconfigured"])
def test_deterministic_refusal_has_no_source_effect(configured, monkeypatch, failure):
    client, authority, initial, operators, consume, _ = configured
    run, _ = retained(configured)
    # Freeze without submitting, to change only the intended fixture condition.
    original_http = client.http
    monkeypatch.setattr(SourceResultClient, "resume", lambda self, command_id: {"command_id":command_id})
    identity, desc = descriptor(configured, run)
    if failure in {"head", "policy", "input", "supply"}:
        field = {"head":"expected_episode_heads", "policy":"expected_policy_sha256", "input":"runtime_input_sha256", "supply":"supply_sha256"}[failure]
        desc = resign_descriptor(configured, desc, **{field: {EPISODE:"e"*64} if failure == "head" else "e"*64})
    command = Command.from_request(desc["request"], operators.resolve("local-editor"), environment="local", now=datetime.now(UTC))
    authority.accept(command, operators.resolve("local-editor"), now=datetime.now(UTC))
    resolver = operators.resolve
    if failure == "actor":
        def resolver(subject):
            return Principal(subject, "editor", "changed-context")
    if failure == "unconfigured":
        authority.source_results_enabled = False
    if failure == "expired":
        monkeypatch.setattr(domain, "completion_clock", lambda: datetime.now(UTC)+timedelta(hours=1))
    result = authority.consume(resolver, command_id=command.command_id)
    assert result["status"] == "rejected" and authority.read() == (0, initial) and no_episode(authority)
    assert original_http("/commands/"+command.command_id)[1]["result"] == result


def test_atomic_multi_episode_failure_and_exact_retry(configured, monkeypatch):
    _, authority, initial, operators, _, _ = configured
    now = utc_text(datetime.now(UTC)-timedelta(hours=1))
    run, _ = retained(configured, rows=[advisory(issued_at=now), advisory(storm_id="EP022026", basin="East Pacific", issued_at=now)])
    identity, _ = descriptor(configured, run)
    original = PhysicalEpisodeSession._apply_on_connection
    def fail_second(self, c, payload, incoming):
        if payload["episode_id"].endswith("EP022026"):
            raise p.ProjectionError("invented_storage_uncertainty")
        return original(self, c, payload, incoming)
    monkeypatch.setattr(PhysicalEpisodeSession, "_apply_on_connection", fail_second)
    with pytest.raises(p.ProjectionError):
        authority.consume(operators.resolve, command_id=identity)
    assert authority.result(identity) is None and authority.read() == (0, initial) and no_episode(authority)
    monkeypatch.setattr(PhysicalEpisodeSession, "_apply_on_connection", original)
    result = authority.consume(operators.resolve, command_id=identity)
    assert result["status"] == "applied" and len(authority.source_run_projection(run)["episodes"]) == 2


def test_two_competing_runs_and_consumers_exactly_one_head_wins(configured):
    _, authority, _, operators, _, _ = configured
    run1, _ = retained(configured)
    run2, _ = retained(configured)
    first, _ = descriptor(configured, run1)
    second, _ = descriptor(configured, run2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: authority.consume(operators.resolve), range(2)))
    assert [r["status"] for r in sorted(results, key=lambda r:r["command_id"] == second)] == ["applied", "rejected"]
    assert authority.read()[0] == 1
    assert authority.result(second)["code"] == "episode_head_changed"
    assert authority.result(first)["status"] == "applied"


@pytest.mark.parametrize("status", ["success", "failed", "degraded"])
def test_empty_and_failed_runs_keep_original_time_and_no_requests(configured, status):
    client, authority, _, _, consume, _ = configured
    started = datetime.now(UTC)-timedelta(days=3)
    run, value = retained(configured, rows=[], status=status, start=started)
    identity, _ = descriptor(configured, run)
    assert consume(identity)["status"] == "applied"
    result = client.readback(run)
    assert result["counts"]["observed"] == 0 and result["source_status"] == status
    health = authority.read()[1]["source_health"]["nhc"]
    assert health["last_success_ts"] == (value["acquisition_completed_at"] if status == "success" else None)
    if status != "success":
        with pytest.raises(CycloneSupplyError, match="source_run_not_eligible"):
            client.prepare_requests(run)
    else:
        assert client.prepare_requests(run)["requests"] == []


def test_more_than_64_episodes_retained_held_without_submission(configured):
    client, authority, initial, _, _, _ = configured
    rows = [advisory(storm_id=f"AL01{year}", issued_at=f"{year}-10-01T00:00:00Z") for year in range(1961, 2026)]
    run, _ = retained(configured, rows=rows)
    result = client.enroll(run)
    assert result["command_id"] is None and result["reason"] == "episode_inventory_bound"
    assert client.readback(run)["status"] == "held"
    assert authority.read() == (0, initial) and no_episode(authority)


def test_resolver_uncertainty_and_lost_post_ack_resume_same_descriptor(configured, monkeypatch):
    client, authority, initial, operators, consume, _ = configured
    run, _ = retained(configured)
    original = SourceResultClient.http
    def lose(self, path, *, body=None):
        result = original(self, path, body=body)
        if body is not None:
            raise ConnectionResetError("invented lost POST acknowledgement")
        return result
    monkeypatch.setattr(SourceResultClient, "http", lose)
    identity = str(uuid4())
    with pytest.raises(ConnectionResetError):
        client.enroll(run, command_id=identity)
    frozen = client.repository.read(domain.SUBMISSION, identity)
    def unavailable(subject):
        raise OSError("invented role service unavailable")
    with pytest.raises(CommandError, match="authorization"):
        authority.consume(unavailable, command_id=identity)
    assert authority.read() == (0, initial) and no_episode(authority)
    monkeypatch.setattr(SourceResultClient, "http", original)
    assert client.resume(identity)["command"]["status"] == "pending"
    result = consume(identity)
    assert client.resume(identity)["command"]["result"] == result
    assert client.repository.read(domain.SUBMISSION, identity) == frozen


@pytest.mark.parametrize("stage", ["first_regression", "final_regression", "final_expiry"])
def test_trusted_completion_clock_refuses_regression_and_late_expiry(configured, monkeypatch, stage):
    _, authority, initial, operators, _, _ = configured
    run, _ = retained(configured)
    identity, _ = descriptor(configured, run)
    now = datetime.now(UTC)
    readings = ([now-timedelta(seconds=1)] if stage == "first_regression" else
        [now+timedelta(milliseconds=1), now if stage == "final_regression" else now+timedelta(hours=1)])
    iterator = iter(readings)
    monkeypatch.setattr(domain, "completion_clock", lambda: next(iterator))
    result = authority.consume(operators.resolve, command_id=identity, now=now)
    assert result["status"] == "rejected"
    assert result["code"] == ("source_command_expired" if stage == "final_expiry" else "source_clock_regressed")
    assert authority.read() == (0, initial) and no_episode(authority)


@pytest.mark.parametrize("mode", ["schema", "duration_bool", "negative_duration", "time", "cities_hash", "producer", "source_sha"])
def test_input_exact_codec_binding_refuses_before_ack(configured, mode):
    _, authority, _, _, _, _ = configured
    run, value = retained(configured)
    # A separate source identity ensures refusal isn't just an immutable key conflict.
    source = CycloneSupplySession(authority.projections, str(uuid4()), value["acquisition_started_at"], BASE)
    receipt, _, _ = source.capture([], {"status":"success"})
    value.update(supply_run_id=source.supply_run_id, supply_sha256=receipt.canonical_sha256)
    if mode == "schema":
        value["schema_version"] = True
    elif mode == "duration_bool":
        value["duration_ms"] = True
    elif mode == "negative_duration":
        value["duration_ms"] = -1
    elif mode == "time":
        value["acquisition_completed_at"] = "2000-01-01T00:00:00Z"
    elif mode == "cities_hash":
        value["cities_sha256"] = "e"*64
    elif mode == "producer":
        value["producer_revision"] = "e"*40
    else:
        value["supply_sha256"] = "e"*64
    with pytest.raises(CycloneSupplyError):
        domain.retain_input(authority.projections, value)
    with authority.projections._connection() as c:
        assert domain.optional(c, domain.INPUT, "run:"+source.supply_run_id) is None
    assert authority.source_run_projection(source.supply_run_id)["reason"] == "input_not_acknowledged"


@responses.activate
def test_crash_after_capture_before_input_never_reacquires(configured, monkeypatch):
    client, authority, initial, _, _, _ = configured
    responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms":[]})
    def crash(*args):
        raise p.ProjectionError("invented_crash_before_auxiliary_input")
    monkeypatch.setattr(domain, "retain_input", crash)
    run = str(uuid4())
    lane = SourceResultLane(client, run, BASE, [])
    with pytest.raises(p.ProjectionError):
        lane.capture_prepare(initial, nhc.fetch_active_cyclones)
    assert client.readback(run)["reason"] == "input_not_acknowledged"
    with pytest.raises(CycloneSupplyError, match="already_retained"):
        lane.capture_prepare(initial, nhc.fetch_active_cyclones)
    assert len(responses.calls) == 1 and authority.read() == (0, initial) and no_episode(authority)


def test_unknown_commit_ack_has_exact_durable_receipt_no_second_effect(configured, monkeypatch):
    client, authority, _, operators, _, _ = configured
    run, _ = retained(configured)
    identity, frozen = descriptor(configured, run)
    original = authority.projections._connection
    @contextmanager
    def lost_ack(*, writing=False):
        with original(writing=writing) as c:
            yield c
        if writing:
            raise p.ProjectionError("write_outcome_unknown")
    monkeypatch.setattr(authority.projections, "_connection", lost_ack)
    with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
        authority.consume(operators.resolve, command_id=identity)
    monkeypatch.setattr(authority.projections, "_connection", original)
    state = authority.read()
    assert state[0] == 1
    result = client.resume(identity)["command"]["result"]
    assert result["status"] == "applied" and authority.consume(operators.resolve, command_id=identity) == result
    assert authority.read() == state and client.repository.read(domain.SUBMISSION, identity)[1] == frozen


def test_partial_failed_superseded_conflict_and_original_freshness(configured):
    client, authority, _, _, consume, _ = configured
    now = datetime.now(UTC)-timedelta(seconds=2)
    initial_row = advisory(issued_at=utc_text(now-timedelta(hours=6)))
    failed_run, _ = retained(configured, rows=[initial_row], status="failed", start=now)
    first, _ = descriptor(configured, failed_run)
    assert consume(first)["source_run"]["status"] == "held"
    with pytest.raises(CycloneSupplyError, match="not_eligible"):
        client.prepare_requests(failed_run)
    # Reacquisition succeeds without renewing the old assertion's issue time.
    complete, _ = retained(configured, rows=[initial_row], start=now)
    second, _ = descriptor(configured, complete)
    assert consume(second)["source_run"]["status"] == "applied"
    assert not client.readback(failed_run)["episodes"][0]["current"]
    # A later advisory supersedes the prior source-run head.
    update, _ = retained(configured, rows=[advisory(advisory_number="2", issued_at=utc_text(now), wind_kt=100)])
    third, _ = descriptor(configured, update)
    consume(third)
    with pytest.raises(CycloneSupplyError, match="superseded"):
        client.prepare_requests(complete)
    assert client.prepare_requests(update)["requests"]
    conflict, _ = retained(configured, rows=[advisory(advisory_number="2", issued_at=utc_text(now), wind_kt=80)])
    fourth, _ = descriptor(configured, conflict)
    assert consume(fourth)["source_run"]["status"] == "held"
    assert "identity_or_revision_conflict" in PhysicalEpisodeSession(authority.projections).read_current(EPISODE)[1]["holds"]
    with pytest.raises(CycloneSupplyError, match="not_eligible"):
        client.prepare_requests(conflict)


def test_pending_descriptor_and_completed_bytes_survive_fresh_cluster_restore(configured, cluster, monkeypatch):
    import psycopg
    client, authority, _, operators, consume, params = configured
    run1, _ = retained(configured)
    completed, _ = descriptor(configured, run1)
    result = consume(completed)
    run2, _ = retained(configured, rows=[])
    pending, _ = descriptor(configured, run2)
    run3, _ = retained(configured, rows=[])
    original_resume = SourceResultClient.resume
    monkeypatch.setattr(SourceResultClient, "resume", lambda self, command_id: {"command_id":command_id})
    unsubmitted, _ = descriptor(configured, run3)
    monkeypatch.setattr(SourceResultClient, "resume", original_resume)
    _, tool, _ = cluster
    with tempfile.TemporaryDirectory(prefix="theheat-source-restore-", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket = root/"socket"
        socket.mkdir(mode=0o700)
        data, dump = root/"data", root/"invented.dump"
        tool("pg_dump", "-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-Fc", "-f", dump, params["dbname"])
        tool("initdb", "-D", data, "-U", "projection_owner", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale")
        try:
            tool("pg_ctl", "-D", data, "-l", root/"server.log", "-o", f"-c listen_addresses='' -k {socket} -p 55475", "-w", "start")
            with psycopg.connect(host=str(socket), port=55475, user="projection_owner", dbname="postgres", autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_sources TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55475", "-U", "projection_owner", "-d", "restored_sources", "--exit-on-error", "--single-transaction", dump)
            restored = PostgresCommandAuthority(socket_directory=socket, port=55475, database="restored_sources", user="projection_runtime")
            restored.configure_source_results()
            assert restored.read() == authority.read() and restored.result(completed) == result and restored.result(pending) is None
            for run in (run1, run2, run3):
                for namespace in ("cyclone-supply-nhc-v1", domain.INPUT):
                    assert restored.projections.read(namespace, "run:"+run) == authority.projections.read(namespace, "run:"+run)
            for identity in (completed, pending, unsubmitted):
                assert restored.projections.read(domain.SUBMISSION, identity) == authority.projections.read(domain.SUBMISSION, identity)
            assert restored.projections.read(domain.RESULT, "run:"+run1) == authority.projections.read(domain.RESULT, "run:"+run1)
            server = PreviewServer(restored, operators, port=0, origin=ORIGIN)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                # Fresh process reloads the frozen descriptor; no parser or acquisition.
                script = '''import json,sys
from src.commands.postgres_authority import PostgresCommandAuthority
from src.orchestrator.source_result_client import SourceResultClient
x=json.loads(sys.argv[1]); a=PostgresCommandAuthority(socket_directory=x['socket'],port=55475,database='restored_sources',user='projection_runtime'); a.configure_source_results()
c=SourceResultClient(a.projections,x['endpoint'],x['origin'],'editor','invented-editor')
print(json.dumps(c.resume(x['command_id'])))'''
                for identity in (pending, unsubmitted):
                    child = subprocess.run([sys.executable,"-c",script,json.dumps(dict(socket=str(socket), endpoint=f"http://127.0.0.1:{server.server_port}", origin=ORIGIN, command_id=identity))],env=clean_environment(),capture_output=True,text=True,timeout=30)
                    assert child.returncode == 0, child.stdout+child.stderr
                    assert json.loads(child.stdout)["command_id"] == identity
                    applied = restored.consume(operators.resolve, command_id=identity)
                    assert applied["status"] == "applied" and restored.consume(operators.resolve, command_id=identity) == applied
                assert restored.read()[0] == 3
                assert restored.source_run_projection(run3)["status"] == "applied"
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


@pytest.mark.parametrize("mode", ["expiry", "regression"])
def test_final_shared_projection_boundary_rolls_back_all_effects(configured, monkeypatch, mode):
    _, authority, initial, operators, _, _ = configured
    run, _ = retained(configured)
    identity, _ = descriptor(configured, run)
    before = datetime.now(UTC)
    original = p.PostgresProjectionRepository._record
    delayed = False
    def record(cls, c, namespace, key, encoded, fields):
        nonlocal delayed
        result = original(c, namespace, key, encoded, fields)
        if namespace == "command-core-v1":
            delayed = True
        return result
    def clock():
        if delayed:
            return before+(timedelta(hours=1) if mode == "expiry" else -timedelta(seconds=1))
        return datetime.now(UTC)
    monkeypatch.setattr(p.PostgresProjectionRepository, "_record", classmethod(record))
    monkeypatch.setattr(domain, "completion_clock", clock)
    with pytest.raises(CycloneSupplyError, match="source_command_expired" if mode == "expiry" else "source_clock_regressed"):
        authority.consume(operators.resolve, command_id=identity)
    assert authority.result(identity) is None and no_episode(authority) and authority.read() == (0, initial)
    monkeypatch.setattr(p.PostgresProjectionRepository, "_record", original)
    monkeypatch.setattr(domain, "completion_clock", lambda: datetime.now(UTC))
    later = authority.consume(operators.resolve, command_id=identity, now=before+timedelta(hours=1) if mode == "expiry" else None)
    assert later["status"] == ("rejected" if mode == "expiry" else "applied")
    if mode == "expiry":
        assert later["code"] == "source_command_expired" and no_episode(authority) and authority.read() == (0, initial)


def test_command_member_resolution_never_opens_independent_connection(configured, monkeypatch):
    _, authority, _, operators, consume, _ = configured
    run, _ = retained(configured)
    identity, _ = descriptor(configured, run)
    consume(identity)
    current = datetime.now(UTC)-timedelta(seconds=1)
    update, _ = retained(configured, rows=[advisory(advisory_number="2", issued_at=utc_text(current), wind_kt=100)])
    next_id, _ = descriptor(configured, update)
    original = authority.projections._connection
    calls = []
    @contextmanager
    def only_outer(*, writing=False):
        calls.append(writing)
        assert len(calls) == 1, "Nested connection escaped shared source transaction"
        with original(writing=writing) as c:
            yield c
    monkeypatch.setattr(authority.projections, "_connection", only_outer)
    result = authority.consume(operators.resolve, command_id=next_id)
    assert result["status"] == "applied" and calls == [True]


def test_input_and_descriptor_unknown_ack_reconcile_exact_once(configured, monkeypatch):
    client, authority, _, _, consume, _ = configured
    run, value = retained(configured)
    original_connection = authority.projections._connection
    writing_calls = []
    @contextmanager
    def unknown_input(*, writing=False):
        with original_connection(writing=writing) as c:
            yield c
        if writing:
            writing_calls.append(1)
            raise p.ProjectionError("write_outcome_unknown")
    monkeypatch.setattr(authority.projections, "_connection", unknown_input)
    # Retrying the exact immutable input does not change its original identity.
    before = authority.projections.read(domain.INPUT, "run:"+run)
    assert domain.retain_input(authority.projections, value) == before[0]
    assert writing_calls == [1]
    monkeypatch.setattr(authority.projections, "_connection", original_connection)
    original_record = authority.projections.record
    writes = []
    def unknown_descriptor(namespace, key, value):
        receipt = original_record(namespace, key, value)
        if namespace == domain.SUBMISSION:
            writes.append(receipt.canonical_sha256)
            raise p.ProjectionError("write_outcome_unknown")
        return receipt
    monkeypatch.setattr(authority.projections, "record", unknown_descriptor)
    original_read = authority.projections.read
    reads = []
    def counted_read(namespace, key):
        if namespace == domain.SUBMISSION:
            reads.append(key)
        return original_read(namespace, key)
    monkeypatch.setattr(authority.projections, "read", counted_read)
    identity, frozen = descriptor(configured, run)
    # One unknown-commit reconciliation plus the test helper's own inspection.
    assert reads == [identity, identity]
    assert len(writes) == 1 and writes[0] == digest(frozen)
    assert consume(identity)["status"] == "applied"
    assert authority.projections.read(domain.INPUT, "run:"+run) == before


@responses.activate
@pytest.mark.parametrize("mode", ["stale", "truncated", "partial_failed"])
def test_actual_parser_hold_or_failure_reaches_source_http_without_request(configured, mode):
    client, authority, initial, _, consume, _ = configured
    now = datetime.now(UTC).replace(microsecond=0)
    issued = now-timedelta(days=4) if mode == "stale" else now
    forecast = now+timedelta(hours=12)
    raw = dict(id="AL012026", name="Invented A", intensity="100", lastUpdate=utc_text(issued),
        publicAdvisory=dict(advNum="1"), forecastAdvisory=dict(advNum="1", issuance=utc_text(issued), url="/text/fixture-held.shtml"))
    rows = [raw]
    if mode == "partial_failed":
        # The actual parser observes the first row; strict canonical provenance
        # refuses the malformed second row and raises the real SourceFetchError.
        rows.append(dict(id="AL022026", name="Invented malformed row", intensity="100", lastUpdate=utc_text(now), latitude=float("nan")))
    responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, json={"activeStorms":rows})
    text = f"FORECAST VALID {forecast:%d/%H%MZ} 15.0N 75.0W\nMAX WIND 100 KT\n"
    responses.add(responses.GET, "https://www.nhc.noaa.gov/text/fixture-held.shtml", body=text+("x"*8000 if mode == "truncated" else ""))
    run = str(uuid4())
    cities = [dict(city="Invented", country="Canada", lat=15., lon=-75.)]
    if mode == "truncated":
        # Independent complete wind evidence may still support the observed
        # crossing; forecast incompleteness does not invalidate that fact.
        prior, _ = retained(configured, rows=[advisory(advisory_number="0", issued_at=utc_text(now-timedelta(hours=6)), wind_kt=70)], cities=cities)
        prior_command, _ = descriptor(configured, prior)
        consume(prior_command)
    lane = SourceResultLane(client, run, BASE, cities)
    pending = _process_cyclone_source(initial, None, source_key="nhc", source_label="NHC", fetch_fn=nhc.fetch_active_cyclones, detect_module=nhc, episode_lane=lane)
    assert consume(pending["command_id"])["source_run"]["status"] == ("applied" if mode == "truncated" else "held")
    value = client.readback(run)
    assert value["counts"]["observed"] == 1
    assert value["source_status"] == ("success" if mode == "truncated" else "failed")
    if mode == "truncated":
        assert value["episodes"][0]["holds"] == ["forecast_product_unresolved"]
        requests = client.prepare_requests(run)["requests"]
        assert requests and all(row["bundle"]["signal_kind"] != "cyclone_land_threat" for row in requests)
    else:
        with pytest.raises(CycloneSupplyError, match="not_eligible"):
            client.prepare_requests(run)
    episode = PhysicalEpisodeSession(authority.projections).read_current(EPISODE)[1]
    assert ("forecast_product_unresolved" if mode == "truncated" else "source_failed") in episode["holds"]
    source = CycloneSupplySession(authority.projections, run).read()[2]
    assert source["raw_response_available"] is False and len(source["rows"]) == 1
    if mode == "truncated":
        update, _ = retained(configured, rows=[advisory(advisory_number="2", issued_at=utc_text(datetime.now(UTC)), wind_kt=110)], cities=cities)
        update_command, _ = descriptor(configured, update)
        consume(update_command)
        superseded = client.readback(run)["episodes"][0]
        assert superseded["current"] is False and superseded["holds"] == value["episodes"][0]["holds"]


def test_real_writer_request_refuses_concurrent_saved_authority_edit(configured, monkeypatch):
    from src.orchestrator import cyclone_episodes
    from tests.test_postgres_preview_command_ingress import body
    client, authority, _, _, consume, _ = configured
    now = datetime.now(UTC)-timedelta(seconds=2)
    for number, wind, issued in (("1", 70, now-timedelta(hours=6)), ("2", 100, now)):
        run, _ = retained(configured, rows=[advisory(advisory_number=number, issued_at=utc_text(issued), wind_kt=wind)])
        identity, _ = descriptor(configured, run)
        consume(identity)
    original = cyclone_episodes.prepare_episode_requests
    actual_requests = []
    edit_text = "Invented operator edit remains authoritative."
    def edit_during_preparation(*args, **kwargs):
        requests = original(*args, **kwargs)
        actual_requests.extend(requests)
        command = body(authority.read()[1]["drafts"][0], payload={"text":edit_text})
        status, _ = client.http("/commands", body=command)
        assert status == 202 and consume(command["command_id"])["status"] == "applied"
        return requests
    monkeypatch.setattr(cyclone_episodes, "prepare_episode_requests", edit_during_preparation)
    with pytest.raises(CycloneSupplyError, match="source_authority_changed"):
        client.prepare_requests(run)
    assert actual_requests and authority.read()[1]["drafts"][0]["text"] == edit_text
    assert authority.read()[0] == 3
