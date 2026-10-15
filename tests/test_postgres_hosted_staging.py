"""Actual isolated PG17 TLS/SCRAM tests, never Neon or production credentials.

The fixed production port is asserted separately. Only the private port constant
is redirected to this task-owned ephemeral server to avoid touching local 5432.
"""

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

import pytest

from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import PreviewServer
from src.commands.schema import Command, CommandError
from src.editorial.revisions import record_human_review, bind_reviewed_revision
from tests.test_ghcn_time_integrity import NOW as SUPPLY_NOW
from src.storage import hosted_staging as h
from src.storage import postgres_projection as p
from src.storage.scientific_supply import ScientificSupplySession
from tests.test_command_authority import EDITOR, NOW, request, resolver, story
from tests import test_ghcn_scientific_supply as supply_fixtures

supply = supply_fixtures.supply
supply_inputs = supply_fixtures.supply_inputs
from tests.test_postgres_scientific_supply_retention import metrics_for, trap_replay


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in tuple(os.environ):
        if (
            key.startswith(("PG", "AWS_", "TWITTER_", "BLUESKY_", "X_API_"))
            or re.search(
                r"(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$",
                key,
            )
            or key in {"NODE_ENV", "THEHEAT_ENVIRONMENT"}
        ):
            monkeypatch.delenv(key)


def private_json(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def files(tmp_path):
    folder = tmp_path.resolve() / "private"
    folder.mkdir(mode=0o700)
    ca = folder / "ca.pem"
    ca.write_text("Invented certificate bytes, no connection in config tests.")
    ca.chmod(0o600)
    identity = dict(
        schema=1,
        environment="preview",
        project_id="synthetic-project",
        branch_id="br-synthetic",
        endpoint_id="ep-synthetic",
        host="localhost",
        port=5432,
        database="synthetic_database",
        purpose="runtime",
        role="fixture_runtime",
        ca_path=str(ca),
        ca_sha256=hashlib.sha256(ca.read_bytes()).hexdigest(),
    )
    identity_path = private_json(folder / "identity.json", identity)
    config_path = private_json(folder / "connection.json", {**identity, "password": "a" * 48})
    return config_path, identity_path


def load(files):
    return h.HostedStagingConfig.load(files[0], trusted_identity=files[1])


def test_strict_factory_preserves_exact_classes_and_refuses_loopback_ingress(files):
    assert h._PORT == 5432
    config = load(files)
    authority = PostgresCommandAuthority.for_hosted_staging(config)
    assert type(authority) is PostgresCommandAuthority
    assert type(authority.projections) is p.PostgresProjectionRepository
    assert authority.environment == authority.projections.environment == "preview"
    assert "a" * 48 not in repr(config)
    with pytest.raises(ValueError, match="local_authority_required"):
        PreviewServer(authority, None, port=3138, origin="http://127.0.0.1:3137")
    with pytest.raises(p.ProjectionError, match="explicit_staging_config_required"):
        p.PostgresProjectionRepository.for_hosted_staging({})


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "wrong.example"),
        ("database", "other"),
        ("role", "other"),
        ("purpose", "owner"),
        ("project_id", "other"),
        ("branch_id", "other"),
        ("endpoint_id", "other"),
        ("ca_sha256", "0" * 64),
        ("schema", True),
    ],
)
def test_config_cannot_self_assert_destination(files, field, value):
    raw = json.loads(files[0].read_text())
    raw[field] = value
    private_json(files[0], raw)
    with pytest.raises(p.ProjectionError):
        load(files)


@pytest.mark.parametrize(
    "field,value",
    [
        ("port", 55473),
        ("host", "a,b"),
        ("host", "a-pooler.example"),
        ("host", "127.0.0.1"),
        ("host", "a host=x"),
        ("database", "dbname=x"),
        ("environment", "production"),
        ("purpose", "admin"),
        ("ca_path", "system"),
        ("role", "x;sql"),
    ],
)
def test_even_matching_unsafe_identity_refused(files, field, value):
    for path in files:
        data = json.loads(path.read_text())
        data[field] = value
        private_json(path, data)
    with pytest.raises(p.ProjectionError):
        load(files)


@pytest.mark.parametrize(
    "password", ["", "has\x00nul", "has\nnewline", "postgresql://secret", "napi_" + "a" * 40]
)
def test_password_contract_no_key_or_uri_fallback(files, password):
    raw = json.loads(files[0].read_text())
    raw["password"] = password
    private_json(files[0], raw)
    with pytest.raises(p.ProjectionError, match="invalid_staging_password"):
        load(files)


@pytest.mark.parametrize(
    "mode",
    ["duplicate", "unknown", "oversize", "symlink", "hardlink", "permission", "directory", "fifo"],
)
def test_private_configuration_boundary(files, mode):
    path = files[0]
    if mode == "duplicate":
        path.write_text('{"schema":1,' + path.read_text()[1:])
    elif mode == "unknown":
        raw = json.loads(path.read_text())
        raw["include"] = "other.json"
        private_json(path, raw)
    elif mode == "oversize":
        path.write_bytes(b"x" * (h.MAX_CONFIG_BYTES + 1))
    elif mode == "permission":
        path.chmod(0o644)
    elif mode == "directory":
        path.parent.chmod(0o755)
    else:
        path.unlink()
        if mode == "symlink":
            path.symlink_to(files[1])
        elif mode == "hardlink":
            os.link(files[1], path)
        else:
            os.mkfifo(path, 0o600)
    with pytest.raises(p.ProjectionError):
        load(files)


@pytest.mark.parametrize("password", ["npg_FixtureAb12cd", "short", "punctuation: =\"'ä"])
def test_existing_database_password_formats_are_not_regenerated(files, password):
    raw = json.loads(files[0].read_text())
    raw["password"] = password
    private_json(files[0], raw)
    assert load(files).parameters()["password"] == password


@pytest.mark.parametrize("mode", ["config", "identity", "ca", "ambient", "disabled"])
def test_recheck_every_dial_before_connect(files, monkeypatch, mode):
    config = load(files)
    if mode in {"config", "identity"}:
        files[mode == "identity"].write_text("{}")
    elif mode == "ca":
        Path(config.parameters()["ca_path"]).write_text("changed")
    elif mode == "ambient":
        monkeypatch.setenv("GITHUB_TOKEN", "invented")
    else:
        (files[0].parent / "disabled-libpq-file").write_text("forbidden")

    class NoDial:
        @staticmethod
        def connect(**kwargs):
            raise AssertionError("dial must not occur")

    with pytest.raises(p.ProjectionError), h.connection(config, NoDial):
        pass


@pytest.mark.parametrize("reverse", [False, True])
def test_fresh_interpreter_import_order(reverse):
    names = [
        "src.storage.postgres_projection",
        "src.commands.postgres_authority",
        "src.commands.preview_ingress",
        "src.storage.hosted_staging",
        "src.storage.scientific_supply",
    ]
    if reverse:
        names.reverse()
    code = "import sys; sys.addaudithook(lambda name, args: (_ for _ in ()).throw(AssertionError('network')) if name in ('socket.connect', 'socket.getaddrinfo') else None); "
    code += "; ".join(f"__import__({name!r})" for name in names)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()


@pytest.fixture(scope="module")
def tls_cluster():
    if os.environ.get("THEHEAT_TEST_POSTGRES") != "1":
        pytest.skip("actual PG profile required")
    import psycopg

    bindir = Path(os.environ["THEHEAT_POSTGRES_BINDIR"])
    tools = {name: str(bindir / name) for name in ("initdb", "pg_ctl", "pg_dump", "pg_restore")}
    openssl = shutil.which("openssl")
    assert openssl and all(Path(path).is_file() for path in tools.values())
    with tempfile.TemporaryDirectory(
        prefix="theheat-tls-", dir="/private/tmp" if sys.platform == "darwin" else "/tmp"
    ) as directory:
        root = Path(directory).resolve()
        root.chmod(0o700)
        sock = root / "socket"
        sock.mkdir(mode=0o700)
        data = root / "data"

        def command(name, *args):
            return subprocess.run(
                [tools[name], *map(str, args)], capture_output=True, check=True, timeout=60
            )

        command(
            "initdb",
            "-D",
            data,
            "-U",
            "fixture_admin",
            "--auth-local=trust",
            "--auth-host=scram-sha-256",
            "--encoding=UTF8",
            "--no-locale",
        )
        cert, key = root / "server.crt", root / "server.key"
        ssl_config = root / "openssl.cnf"
        ssl_config.write_text(
            "[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\nbasicConstraints=critical,CA:TRUE\n"
        )
        subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-config",
                str(ssl_config),
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        key.chmod(0o600)
        cert.chmod(0o600)
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        args = dict(
            host=str(sock), port=port, dbname="postgres", user="fixture_admin", autocommit=True
        )
        try:
            command(
                "pg_ctl",
                "-D",
                data,
                "-l",
                root / "server.log",
                "-o",
                f"-k {sock} -p {port} -c listen_addresses=127.0.0.1 -c ssl=on -c ssl_cert_file={cert} -c ssl_key_file={key}",
                "-w",
                "start",
            )
            with psycopg.connect(**args) as c:
                for role, password in (("fixture_owner", "a" * 48), ("fixture_runtime", "b" * 48)):
                    c.execute(
                        psycopg.sql.SQL(
                            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 2 PASSWORD {}"
                        ).format(psycopg.sql.Identifier(role), psycopg.sql.Literal(password))
                    )
            yield root, args, command, cert, data
        finally:
            if (data / "postmaster.pid").exists():
                command("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


@pytest.fixture
def tls_database(tls_cluster, monkeypatch):
    import psycopg

    root, args, command, cert, data = tls_cluster
    name = "staging_" + uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(
            psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                psycopg.sql.Identifier(name)
            )
        )
        c.execute(
            psycopg.sql.SQL("REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC").format(
                psycopg.sql.Identifier(name)
            )
        )
        c.execute(
            psycopg.sql.SQL("GRANT CONNECT,CREATE ON DATABASE {} TO fixture_owner").format(
                psycopg.sql.Identifier(name)
            )
        )
        c.execute(
            psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO fixture_runtime").format(
                psycopg.sql.Identifier(name)
            )
        )
    monkeypatch.setattr(h, "_PORT", args["port"])
    folder = root / name
    folder.mkdir(mode=0o700)
    configs = []
    for purpose, role, password in (
        ("owner", "fixture_owner", "a" * 48),
        ("runtime", "fixture_runtime", "b" * 48),
    ):
        identity = dict(
            schema=1,
            environment="preview",
            project_id="synthetic-project",
            branch_id="br-synthetic",
            endpoint_id="ep-synthetic",
            host="localhost",
            port=args["port"],
            database=name,
            purpose=purpose,
            role=role,
            ca_path=str(cert),
            ca_sha256=hashlib.sha256(cert.read_bytes()).hexdigest(),
        )
        identity_path = private_json(folder / f"{purpose}-identity.json", identity)
        config_path = private_json(folder / f"{purpose}.json", {**identity, "password": password})
        configs.append(h.HostedStagingConfig.load(config_path, trusted_identity=identity_path))
    yield configs, {**args, "dbname": name}
    with psycopg.connect(**args) as c:
        c.execute(
            psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name))
        )


def authorities(tls_database):
    configs, args = tls_database
    return *(PostgresCommandAuthority.for_hosted_staging(c) for c in configs), args


def preview_command(draft, **kwargs):
    return Command.from_request(request(draft, **kwargs), EDITOR, environment="preview", now=NOW)


def test_actual_tls_command_transaction_and_identity(tls_database):
    owner, runtime, args = authorities(tls_database)
    initial = {"drafts": [story()], "unknown": {"typed": [1, 1.0, -0.0, None]}}
    record_human_review(initial["drafts"][0])
    bind_reviewed_revision(initial["drafts"][0], "manual", at=NOW.isoformat())
    assert initial["drafts"][0]["approval_binding"]
    owner.initialize(initial, runtime_role="fixture_runtime")
    with runtime.projections._connection() as c:
        assert c.pgconn.ssl_in_use
        assert c.execute("SHOW statement_timeout").fetchone() == ("10s",)
        assert c.execute("SHOW lock_timeout").fetchone() == ("1s",)
        assert c.execute("SHOW idle_in_transaction_session_timeout").fetchone() == ("15s",)
    first = preview_command(initial["drafts"][0])
    second = preview_command(initial["drafts"][0], payload={"text": "Conflicting invented edit."})
    receipt = runtime.accept(first, EDITOR, now=NOW)
    assert runtime.accept(first, EDITOR, now=NOW) == receipt
    runtime.accept(second, EDITOR, now=NOW)
    assert runtime.consume(resolver, now=NOW)["status"] == "applied"
    assert runtime.consume(resolver, now=NOW)["code"] == "revision_conflict"
    assert runtime.result(first.command_id) == runtime.consume(
        resolver, command_id=first.command_id, now=NOW
    )
    assert runtime.read()[0] == 1
    current = runtime.read()[1]["drafts"][0]
    assert "review_binding" not in current and "approval_binding" not in current
    assert current["content_revision"] == 2
    with pytest.raises(p.ProjectionError, match="non_owner_runtime_role_required"):
        owner.read()


def test_actual_tls_retained_six_and_replay(tls_database, supply, monkeypatch):
    from src.orchestrator.sources import open_meteo as source
    from src.orchestrator import caps

    configs, args = tls_database
    owner, runtime = [p.PostgresProjectionRepository.for_hosted_staging(c) for c in configs]
    owner.initialize(runtime_role="fixture_runtime")
    capture = ScientificSupplySession(runtime, str(uuid4()), "capture", SUPPLY_NOW, "a" * 40)
    retained = capture.capture(*supply[:2], metrics_for(supply))
    trap_replay(monkeypatch)
    for cap in (0, 1, 2, 6):
        monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", cap)
        result = source.replay_retained_ghcn_supply(
            replace(capture, mode="replay", captured_at=None, producer_revision=None), {}
        )
        assert result["status"] == "available"
        assert len(result["retained_bundle_keys"]) == 6
        assert len(result["individual_bundle_keys"]) == cap
        assert result["source_acquisition"] == "not_attempted"
    assert capture.read() == retained


@pytest.mark.parametrize("failure", ["ca", "password", "database", "membership"])
def test_real_tls_and_role_failures(tls_database, failure):
    import psycopg

    configs, args = tls_database
    owner, runtime, _ = authorities(tls_database)
    owner.initialize({"drafts": []}, runtime_role="fixture_runtime")
    if failure == "membership":
        with psycopg.connect(**args) as c:
            c.execute("GRANT fixture_owner TO fixture_runtime")
        try:
            with pytest.raises(p.ProjectionError, match="non_owner_runtime_role_required"):
                runtime.read()
        finally:
            with psycopg.connect(**args) as c:
                c.execute("REVOKE fixture_owner FROM fixture_runtime")
        return
    config = configs[1]
    values = [json.loads(path.read_text()) for path in (config.config_path, config.identity_path)]
    if failure == "database":
        for value in values:
            value["database"] = "absent_synthetic_db"
    elif failure == "password":
        values[0]["password"] = "wrong" * 10
    else:
        ca = config.config_path.parent / "wrong-ca.pem"
        subprocess.run(
            [
                shutil.which("openssl"),
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(ca.with_suffix(".key")),
                "-out",
                str(ca),
                "-days",
                "1",
                "-subj",
                "/CN=unrelated-local-CA",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        ca.chmod(0o600)
        for value in values:
            value["ca_path"], value["ca_sha256"] = (
                str(ca),
                hashlib.sha256(ca.read_bytes()).hexdigest(),
            )
    for path, value in zip((config.config_path, config.identity_path), values):
        private_json(path, value)
    invalid = load((config.config_path, config.identity_path))
    # Unlike a malformed PEM or DNS failure, this is a valid unrelated CA.
    if failure == "ca":
        original_connect = psycopg.connect
        errors = []

        def observed_connect(**kwargs):
            try:
                return original_connect(**kwargs)
            except psycopg.OperationalError as exc:
                errors.append("certificate verify failed" in str(exc))
                raise

        from unittest.mock import patch

        with patch.object(psycopg, "connect", observed_connect):
            with pytest.raises(p.ProjectionError, match="storage_unavailable"):
                PostgresCommandAuthority.for_hosted_staging(invalid).read()
        assert errors == [True]
        return
    with pytest.raises(p.ProjectionError, match="storage_unavailable"):
        PostgresCommandAuthority.for_hosted_staging(invalid).read()


@pytest.mark.parametrize(
    "failure", ["read_only", "lock_timeout", "disconnect_before_commit", "lost_commit_ack"]
)
def test_real_tls_failed_transactions_no_partial_state(tls_database, monkeypatch, failure):
    import psycopg
    from tests.test_postgres_projection import wrap_connections

    owner, runtime, args = authorities(tls_database)
    initial = {"drafts": [story()]}
    owner.initialize(initial, runtime_role="fixture_runtime")
    cmd = preview_command(initial["drafts"][0])
    runtime.accept(cmd, EDITOR, now=NOW)
    if failure == "read_only":
        with psycopg.connect(**args) as c:
            c.execute("ALTER ROLE fixture_runtime SET default_transaction_read_only=on")
        try:
            with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
                runtime.consume(resolver, now=NOW)
        finally:
            with psycopg.connect(**args) as c:
                c.execute("ALTER ROLE fixture_runtime RESET default_transaction_read_only")
    elif failure == "lock_timeout":
        with psycopg.connect(**{**args, "autocommit": False}) as locked:
            locked.execute("SELECT * FROM theheat_commands.state FOR UPDATE")
            with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
                runtime.consume(resolver, now=NOW)
    else:

        def disconnect(conn):
            conn.execute("SELECT pg_terminate_backend(pg_backend_pid())")

        with monkeypatch.context() as patch:
            wrap_connections(
                patch,
                before_commit=disconnect if failure == "disconnect_before_commit" else None,
                lost_ack=failure == "lost_commit_ack",
            )
            with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
                runtime.consume(resolver, now=NOW)
    result = runtime.result(cmd.command_id)
    if failure == "lost_commit_ack":
        assert result["status"] == "applied" and runtime.read()[0] == 1
        assert runtime.consume(resolver, command_id=cmd.command_id, now=NOW) == result
    else:
        assert result is None and runtime.read() == (0, initial)
        assert runtime.consume(resolver, command_id=cmd.command_id, now=NOW)["status"] == "applied"
    assert runtime.read()[0] == 1


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE SCHEMA forbidden",
        "CREATE TEMP TABLE forbidden(x int)",
        "DELETE FROM theheat_projection.versions",
        "UPDATE theheat_projection.metadata SET version=2",
        "ALTER TABLE theheat_commands.state ADD COLUMN forbidden int",
        "SET ROLE fixture_owner",
        "GRANT fixture_owner TO fixture_runtime",
        "CREATE DATABASE forbidden",
        "CREATE TABLE public.forbidden(x int)",
    ],
)
def test_actual_runtime_privilege_denials(tls_database, sql):
    import psycopg

    owner, runtime, args = authorities(tls_database)
    owner.initialize({"drafts": []}, runtime_role="fixture_runtime")
    with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
        with runtime.projections._connection(writing=True) as c:
            c.execute(sql)
    assert runtime.read() == (0, {"drafts": []})


def fresh_child(config, *, port, operation, command_id=None, run_id=None, now=NOW):
    code = """import json, sys
from datetime import datetime
from src.storage import hosted_staging as h
from src.commands.postgres_authority import PostgresCommandAuthority
from tests.test_command_authority import resolver
from src.storage.scientific_supply import ScientificSupplySession
from src.orchestrator.sources.open_meteo import replay_retained_ghcn_supply
value=json.load(sys.stdin)
h._PORT=value['port']  # Isolated local TLS fixture port only.
config=h.HostedStagingConfig.load(value['config'],trusted_identity=value['identity'])
authority=PostgresCommandAuthority.for_hosted_staging(config)
if value['operation']=='consume':
 result=authority.consume(resolver,command_id=value['command_id'],now=datetime.fromisoformat(value['now']))
else:
 result=replay_retained_ghcn_supply(ScientificSupplySession(authority.projections,value['run_id'],'replay'),{})
print(json.dumps(result,separators=(',',':')))
"""
    packet = dict(
        config=str(config.config_path),
        identity=str(config.identity_path),
        port=port,
        operation=operation,
        command_id=command_id,
        run_id=run_id,
        now=now.isoformat(),
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(packet),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


def test_real_tls_restart_and_exact_dump_restore_pending_command(tls_database, tls_cluster, supply):
    import psycopg

    configs, args = tls_database
    root, admin, run, cert, data = tls_cluster
    owner, runtime, _ = authorities(tls_database)
    initial = {"drafts": [story()], "unknown": {"typed": [None, 1, 1.0, -0.0]}}
    owner.initialize(initial, runtime_role="fixture_runtime")
    first = preview_command(initial["drafts"][0])
    runtime.accept(first, EDITOR, now=NOW)
    consumed = fresh_child(
        configs[1], port=args["port"], operation="consume", command_id=first.command_id
    )
    assert consumed == runtime.result(first.command_id) and consumed["status"] == "applied"
    capture = ScientificSupplySession(
        runtime.projections, str(uuid4()), "capture", SUPPLY_NOW, "a" * 40
    )
    receipt = capture.capture(*supply[:2], metrics_for(supply))[0]
    replay = fresh_child(
        configs[1], port=args["port"], operation="replay", run_id=capture.supply_run_id
    )
    assert replay["status"] == "available" and replay["receipt_sha256"] == receipt.canonical_sha256
    assert len(replay["retained_bundle_keys"]) == 6
    current = runtime.read()[1]["drafts"][0]
    pending = preview_command(current, payload={"text": "One restored invented edit."})
    accepted = runtime.accept(pending, EDITOR, now=NOW)
    before = runtime.read(), runtime.journal(), runtime.result(first.command_id)
    restore_name = "restore_" + uuid4().hex
    with psycopg.connect(**admin) as c:
        c.execute(
            psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                psycopg.sql.Identifier(restore_name)
            )
        )
        c.execute(
            psycopg.sql.SQL("REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC").format(
                psycopg.sql.Identifier(restore_name)
            )
        )
        c.execute(
            psycopg.sql.SQL("GRANT CONNECT,CREATE ON DATABASE {} TO fixture_owner").format(
                psycopg.sql.Identifier(restore_name)
            )
        )
        c.execute(
            psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO fixture_runtime").format(
                psycopg.sql.Identifier(restore_name)
            )
        )
    folder = configs[0].config_path.parent
    passfile = folder / "dump-passfile"
    # Private CLI passfile covers only these two explicit invented databases.
    passfile.write_text(
        "\n".join(
            f"localhost:{args['port']}:{db}:fixture_owner:{'a' * 48}"
            for db in (args["dbname"], restore_name)
        )
    )
    passfile.chmod(0o600)
    env = {
        **os.environ,
        "PGPASSFILE": str(passfile),
        "PGSSLMODE": "verify-full",
        "PGCHANNELBINDING": "require",
        "PGSSLROOTCERT": str(cert),
        "PGSSLCERTMODE": "disable",
        "PGGSSENCMODE": "disable",
        "PGSSLCRL": str(folder / "disabled-libpq-file"),
        "PGSSLCRLDIR": str(folder / "disabled-libpq-file"),
    }
    dump = folder / "application.dump"
    dump.touch(mode=0o600)
    bindir = Path(os.environ["THEHEAT_POSTGRES_BINDIR"])
    common = ["-h", "localhost", "-p", str(args["port"]), "-U", "fixture_owner", "-w"]
    try:
        subprocess.run(
            [
                str(bindir / "pg_dump"),
                *common,
                "-Fc",
                "--schema=theheat_projection",
                "--schema=theheat_commands",
                "-f",
                str(dump),
                args["dbname"],
            ],
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        assert 0 < dump.stat().st_size <= 16 * 1024 * 1024
        subprocess.run(
            [
                str(bindir / "pg_restore"),
                *common,
                "--single-transaction",
                "--exit-on-error",
                "-d",
                restore_name,
                str(dump),
            ],
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        identity = json.loads(configs[1].identity_path.read_text())
        identity["database"] = restore_name
        restored_identity = private_json(folder / "restore-identity.json", identity)
        restored_config = private_json(folder / "restore.json", {**identity, "password": "b" * 48})
        config = h.HostedStagingConfig.load(restored_config, trusted_identity=restored_identity)
        restored = PostgresCommandAuthority.for_hosted_staging(config)
        assert (restored.read(), restored.journal(), restored.result(first.command_id)) == before
        assert restored.accept(pending, EDITOR, now=NOW) == accepted
        assert restored.result(pending.command_id) is None
        replay_restored = fresh_child(
            config, port=args["port"], operation="replay", run_id=capture.supply_run_id
        )
        assert replay_restored == replay
        result = fresh_child(
            config, port=args["port"], operation="consume", command_id=pending.command_id
        )
        assert result["status"] == "applied" and result["state_version"] == 2
        assert restored.consume(resolver, command_id=pending.command_id, now=NOW) == result
        assert restored.read()[0] == 2
        assert (runtime.read(), runtime.journal(), runtime.result(first.command_id)) == before
        assert runtime.result(pending.command_id) is None
    finally:
        with psycopg.connect(**admin) as c:
            c.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(restore_name)
                )
            )


@pytest.mark.parametrize("failure", ["hostname_mismatch", "tls_disabled"])
def test_specific_real_tls_failure_reaches_owned_server(
    tls_database, tls_cluster, monkeypatch, failure
):
    import psycopg

    configs, args = tls_database
    root, admin, command, cert, data = tls_cluster
    original_certificate = cert.read_bytes()
    key = root / "server.key"
    config = configs[1]
    if failure == "hostname_mismatch":
        bad = root / "bad-san.cnf"
        bad.write_text(
            "[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=wrong.invalid\n[ext]\nsubjectAltName=DNS:wrong.invalid\nbasicConstraints=critical,CA:TRUE\n"
        )
        subprocess.run(
            [
                shutil.which("openssl"),
                "req",
                "-x509",
                "-key",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-config",
                str(bad),
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        for path in (config.config_path, config.identity_path):
            value = json.loads(path.read_text())
            value["ca_sha256"] = hashlib.sha256(cert.read_bytes()).hexdigest()
            private_json(path, value)
        config = load((config.config_path, config.identity_path))

    def restart(ssl):
        command(
            "pg_ctl",
            "-D",
            data,
            "-l",
            root / "server.log",
            "-o",
            f"-k {admin['host']} -p {args['port']} -c listen_addresses=127.0.0.1 -c ssl={ssl} -c ssl_cert_file={cert} -c ssl_key_file={key}",
            "-w",
            "restart",
            "-m",
            "fast",
        )

    errors = []
    real_connect = psycopg.connect

    def observed_connect(**kwargs):
        try:
            return real_connect(**kwargs)
        except psycopg.OperationalError as exc:
            # Invented local connection only. Never retain a real connection error.
            raw = str(exc)
            if "does not match host name" in raw:
                errors.append("certificate_hostname_mismatch")
            elif "server does not support SSL" in raw:
                errors.append("server_tls_disabled")
            else:
                errors.append("unexpected_connection_failure")
            raise

    try:
        restart("on" if failure == "hostname_mismatch" else "off")
        monkeypatch.setattr(psycopg, "connect", observed_connect)
        with pytest.raises(p.ProjectionError, match="storage_unavailable"):
            PostgresCommandAuthority.for_hosted_staging(config).read()
        assert errors == [
            "certificate_hostname_mismatch"
            if failure == "hostname_mismatch"
            else "server_tls_disabled"
        ]
    finally:
        cert.write_bytes(original_certificate)
        restart("on")


@pytest.mark.parametrize("mode", ["strict_client", "client_tls_false", "wrong_database", "wrong_user", "missing_identity"])
def test_client_tls_and_database_identity_are_separate_guards(files, mode):
    """Explicit offline driver model; real certificate negatives remain above."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    configured = load(files)
    value = configured.parameters()
    statements = []
    identity = (value["database"], value["role"])
    if mode == "wrong_database":
        identity = ("wrong_database", value["role"])
    elif mode == "wrong_user":
        identity = (value["database"], "wrong_role")
    elif mode == "missing_identity":
        identity = None

    class Connection:
        info = SimpleNamespace(server_version=170000)
        pgconn = None

        def execute(self, query):
            statements.append(query)
            assert query == "SELECT current_database(),current_user"
            return SimpleNamespace(fetchone=lambda: identity)

    class Driver:
        @staticmethod
        @contextmanager
        def connect(**kwargs):
            assert kwargs["sslmode"] == "verify-full"
            assert kwargs["channel_binding"] == "require"
            assert kwargs["sslrootcert"] == value["ca_path"]
            connection = Connection()
            connection.pgconn = SimpleNamespace(
                ssl_in_use=mode != "client_tls_false",
                info=[SimpleNamespace(keyword=k.encode(), val=str(v).encode()) for k, v in kwargs.items()],
            )
            yield connection

    if mode == "strict_client":
        with h.connection(configured, Driver):
            pass
        assert statements == ["SELECT current_database(),current_user"]
    else:
        code = "staging_tls_identity_mismatch" if mode == "client_tls_false" else "staging_database_identity_mismatch"
        with pytest.raises(p.ProjectionError, match=code):
            with h.connection(configured, Driver):
                pytest.fail("invalid client TLS or database identity accepted")
        assert statements == ([] if mode == "client_tls_false" else ["SELECT current_database(),current_user"])
