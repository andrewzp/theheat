"""Actual report component/Next HTTP and separate PG consumer, invented only."""
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import pytest

from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_report_development import private_configuration
from src.commands.preview_ingress import Operators
from src.storage.retained_reports import RetainedReportSession
from tests.test_postgres_preview_command_ingress import (preview as preview, cluster as cluster,
    database as database, clean_environment, http)
from tests.test_postgres_report_development import retained
from tests import test_postgres_physical_events as physical

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def report_preview(preview, tmp_path):
    port, authority, initial, operators, _, arguments, params = preview
    session, document, head, artifact = retained(authority.projections)
    config = dict(current_reports=[dict(lineage_id=document["lineage_id"], report_sha256=head, episode_reference=None)], decision_refs=[])
    path = tmp_path/"reports.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    authority.configure_report_development(private_configuration(path))
    args = [*arguments, "--report-inputs", str(path)]
    def consume(command_id):
        child = subprocess.run([sys.executable, "-m", "src.commands.preview_worker", *args, "--command-id", command_id],
            cwd=ROOT, env=clean_environment(), capture_output=True, text=True, timeout=30)
        assert child.returncode == 0, child.stdout+child.stderr
        return json.loads(child.stdout)["result"]
    return dict(port=port, authority=authority, initial=initial, operators=operators, args=args, params=params,
        session=session, document=document, head=head, artifact=artifact, config=config, path=path, consume=consume)


def request(report):
    from datetime import timedelta
    from src.commands.schema import utc_text
    now = datetime.now(UTC)
    return dict(command_id=str(uuid4()), action="open_report_evidence", targets=[], requested_at=utc_text(now),
        expires_at=utc_text(now+timedelta(hours=1)), payload={key:report[key] for key in
        ("lineage_id", "report_sha256", "expected_policy_sha256", "episode_reference")})


@pytest.mark.parametrize("linked", [False, True])
def test_actual_component_http_report_to_separate_consumer(report_preview, tmp_path, linked):
    case = report_preview
    if linked:
        _, head, _, _ = physical.seed(case["authority"].projections)
        case["config"]["current_reports"][0]["episode_reference"] = dict(episode_id=physical.EPISODE,
            revision_sha256=head, claim_id="claim1")
        case["path"].write_text(json.dumps(case["config"]))
    before = case["authority"].read()
    config = tmp_path/"http-report.json"
    config.write_text(json.dumps(dict(endpoint=f'http://127.0.0.1:{case["port"]}', origin="http://127.0.0.1:3035",
        root=str(ROOT), python=sys.executable, arguments=case["args"], linked=linked)))
    config.chmod(0o600)
    result = subprocess.run(["node", "--test", "tests/report-development.test.js"], cwd=ROOT/"dashboard",
        env={**clean_environment(), "THEHEAT_REPORT_TEST_CONFIG": str(config)}, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout+result.stderr
    assert case["authority"].read() == before
    assert len(case["authority"].journal()) == 4


@pytest.mark.parametrize("mode", ["role", "policy", "head", "configuration"])
def test_accepted_report_rechecks_current_authority(report_preview, mode):
    case = report_preview
    current = http(case["port"], "/reports")[1]["reports"][0]
    command = request(current)
    if mode == "policy":
        command["payload"]["expected_policy_sha256"] = "e"*64
    assert http(case["port"], "/commands", method="POST", value=command)[0] == 202
    if mode == "role":
        operators = json.loads(case["operators"].read_text())
        operators["operators"] = [row for row in operators["operators"] if row["role"] != "editor"]
        case["operators"].write_text(json.dumps(operators))
    elif mode == "configuration":
        case["config"]["current_reports"] = []
        case["path"].write_text(json.dumps(case["config"]))
    elif mode == "head":
        changed = dict(case["document"], previous_report_sha256=case["head"], limits=["Invented correction"])
        case["session"].retain_revision(changed, expected_head=case["head"], operation_id=str(uuid4()))
    result = case["consume"](command["command_id"])
    assert result["status"] == "rejected"
    assert case["authority"].read() == (0, case["initial"])
    with case["authority"].projections._connection() as c:
        assert c.execute("SELECT count(*) FROM theheat_projection.versions WHERE namespace='report-development-v1'").fetchone()[0] == 0


def test_report_pending_completed_and_artifacts_survive_fresh_cluster_restore(report_preview, cluster):
    import psycopg
    case = report_preview
    report = http(case["port"], "/reports")[1]["reports"][0]
    completed = request(report)
    assert http(case["port"], "/commands", method="POST", value=completed)[0] == 202
    result = case["consume"](completed["command_id"])
    pending = request(report)
    assert http(case["port"], "/commands", method="POST", value=pending)[0] == 202
    _, tool, _ = cluster
    params = case["params"]
    with tempfile.TemporaryDirectory(prefix="theheat-report-restore-", dir="/tmp") as directory:
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
                c.execute("CREATE DATABASE restored_reports TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55475", "-U", "projection_owner", "-d", "restored_reports", "--exit-on-error", "--single-transaction", dump)
            restored = PostgresCommandAuthority(socket_directory=socket, port=55475, database="restored_reports", user="projection_runtime")
            restored.configure_report_development(private_configuration(case["path"]))
            assert restored.read() == case["authority"].read()
            assert restored.result(completed["command_id"]) == result
            assert restored.result(pending["command_id"]) is None
            reread = RetainedReportSession(restored.projections)
            assert reread.read_current(report["lineage_id"], case["head"])[1] == case["document"]
            assert reread.read_artifact(case["artifact"].snapshot_id) == case["session"].read_artifact(case["artifact"].snapshot_id)
            applied = restored.consume(Operators(case["operators"]).resolve, command_id=pending["command_id"])
            assert applied["status"] == "applied" and applied["report_development"]["reused"]
            assert applied["report_development"]["item_sha256"] == result["report_development"]["item_sha256"]
            assert restored.consume(Operators(case["operators"]).resolve, command_id=pending["command_id"]) == applied
            assert restored.read() == (0, case["initial"])
            assert len(restored.journal()) == 4
            assert restored.report_projection(now=datetime.now(UTC))["reports"][0]["development_status"] == "evidence_review_required"
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


@pytest.mark.parametrize("failure", ["item", "result", "resolver", "lost_ack"])
def test_report_command_uncertainty_keeps_exact_recoverable_intent(report_preview, monkeypatch, failure):
    from src.commands.schema import CommandError
    from src.storage import postgres_projection as p
    from tests.test_postgres_projection import wrap_connections
    case = report_preview
    report = http(case["port"], "/reports")[1]["reports"][0]
    command = request(report)
    assert http(case["port"], "/commands", method="POST", value=command)[0] == 202
    operators = Operators(case["operators"])
    def fail(query, _):
        if query.startswith("INSERT INTO " + ("theheat_projection.versions" if failure == "item" else "theheat_commands.results")):
            raise RuntimeError("Invented report transaction crash")
    def resolver(_):
        raise OSError("Invented unavailable authorization")
    with monkeypatch.context() as patch:
        if failure in {"item", "result"}:
            wrap_connections(patch, after_execute=fail)
            with pytest.raises(RuntimeError, match="Invented report transaction crash"):
                case["authority"].consume(operators.resolve, command_id=command["command_id"])
        elif failure == "resolver":
            with pytest.raises(CommandError) as error:
                case["authority"].consume(resolver, command_id=command["command_id"])
            assert error.value.code == "authorization_unavailable"
        else:
            from contextlib import contextmanager
            connection = p.PostgresProjectionRepository._connection
            @contextmanager
            def lost_write_ack(repository, *, writing=False):
                with connection(repository, writing=writing) as c:
                    yield c
                if writing:
                    raise p.ProjectionError("write_outcome_unknown")
            patch.setattr(p.PostgresProjectionRepository, "_connection", lost_write_ack)
            with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
                case["authority"].consume(operators.resolve, command_id=command["command_id"])
    retained = case["authority"].result(command["command_id"])
    assert (retained is not None) == (failure == "lost_ack")
    with case["authority"].projections._connection() as c:
        assert c.execute("SELECT count(*) FROM theheat_projection.versions WHERE namespace='report-development-v1'").fetchone()[0] == (1 if failure == "lost_ack" else 0)
    result = case["consume"](command["command_id"])
    assert result["status"] == "applied"
    if retained is not None:
        assert result == retained
    assert case["consume"](command["command_id"]) == result
    assert case["authority"].read() == (0, case["initial"])
    assert len(case["authority"].journal()) == 2
