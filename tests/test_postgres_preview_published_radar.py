"""One invented real parser/SDK/PG/HTTP/component/media/outbox/restore journey."""

import base64
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from uuid import uuid4

import psycopg

from src.commands import preview_ingress
from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_published_media import configure
from src.commands.schema import Command, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.media.published_radar import convert
from tests import test_postgres_preview_editor_media as existing
from tests import (
    test_postgres_editor_media as editor,
    test_postgres_candidate_admission as candidate,
)
from tests import test_postgres_delivery as delivery
from tests.local_delivery_helpers import fixture_server
from tests.test_postgres_published_media import radar_case as radar_case, original
from tests.test_postgres_editor_media import offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import (
    core as core,
    make_authority as make_authority,
    options,
)
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_preview_command_ingress import clean_environment

ROOT = Path(__file__).resolve().parents[1]
CHILD = existing.CHILD.replace(
    'authority.configure_editor_media(**config["native"])',
    """authority.configure_editor_media(**config["native"])
from src.commands.postgres_published_media import configure
configure(authority,lambda:config["published"])
authority.configure_delivery(config["delivery"])""",
).replace(
    'if sock.family!=socket.AF_UNIX:raise AssertionError("External connection refused")',
    'if sock.family!=socket.AF_UNIX and (not isinstance(address,tuple) or address[0]!="127.0.0.1"):raise AssertionError("External connection refused")',
)
CHILD = CHILD.replace(
    'if operation=="consume":',
    """if operation=="deliver":
    from src.commands.preview_delivery_worker import execute_delivery_once
    from src.commands.postgres_delivery import STAGES
    for key in ("GEMINI_API_KEY","ANTHROPIC_API_KEY"):
        os.environ.pop(key,None)
    receipts=[]
    for platform,stages in STAGES.items():
        for stage in stages:
            row=execute_delivery_once(authority,identity,platform,stage,operators.resolve,owner="invented-radar-worker",clock=lambda:config["at"],enabled=True)
            receipts.append(row)
            replay=execute_delivery_once(authority,identity,platform,stage,operators.resolve,owner="invented-radar-worker",clock=lambda:config["at"],enabled=True)
            assert replay["outcome"]=="confirmed" and replay["network_mutation"] is False
    result={"receipts":receipts}
elif operation=="consume":""",
)


def test_published_radar_source_to_park_restore(radar_case, core, cluster, monkeypatch, tmp_path):
    case = radar_case
    for key in tuple(os.environ):
        if key.startswith("PG") or any(
            word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        ):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return editor.AT

    monkeypatch.setattr(preview_ingress, "datetime", Clock)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        origin = "http://127.0.0.1:" + str(probe.getsockname()[1])
    operators = tmp_path / "operators.json"
    operators.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operators": [
                    dict(
                        username=role,
                        password="invented-" + role,
                        subject="invented-" + role,
                        role=role,
                    )
                    for role in ("editor", "publisher", "viewer")
                ],
            }
        )
    )
    operators.chmod(0o600)
    child = tmp_path / "published-worker.py"
    child.write_text(CHILD)
    from src.two_bot import writer

    expected_png, _ = convert(case["original"], case["radar_input"])
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(expected_png, case["text"]) as (fixture, trace, accepted):
        delivery_path = delivery.configure(case["store"], tmp_path, fixture)
        server = PreviewServer(case["store"], Operators(operators), port=0, origin=origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = dict(
            endpoint=f"http://127.0.0.1:{server.server_port}",
            origin=origin,
            root=str(ROOT),
            python=sys.executable,
            child=str(child),
            authority=options(core[3]),
            operators=str(operators),
            generation=case["config"],
            native=case["store"].editor_media_configuration,
            requests=str(tmp_path / "requests.txt"),
            policy_sha256=fingerprint(current_editorial_policy()),
            draft_id=case["draft_id"],
            at=utc_text(editor.AT),
            writer_provider=writer.WRITER_PROVIDER,
            writer_model=writer.WRITER_MODEL,
            published=case["published_config"],
            delivery=str(delivery_path),
            original_base64=base64.b64encode(case["original"]).decode(),
        )
        path = tmp_path / "http.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        try:
            result = subprocess.run(
                [
                    os.environ.get("THEHEAT_NODE24", "node"),
                    "--test",
                    "tests/published-radar.test.js",
                ],
                cwd=ROOT / "dashboard",
                env={**clean_environment(), "THEHEAT_PUBLISHED_RADAR_HTTP_CONFIG": str(path)},
                capture_output=True,
                text=True,
                timeout=240,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert Path(config["requests"]).read_text().splitlines() == [
                "safety",
                "fact_check",
                "critic",
            ]
            assert len(trace) == len(accepted) == 5
            assert len(case["provider_requests"]) == 1
            # Browser fixture operations were simulated operator actions, not
            # genuine human attention or independent source validation.
            draft = next(
                d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"]
            )
            proposal = (
                draft["media_review_binding"]["proposal_sha256"]
                if "media_review_binding" in draft
                else None
            )
            if proposal is None:
                with case["store"].projections._connection() as c:
                    proposal = c.execute(
                        "SELECT proposal_sha256 FROM theheat_media.packages"
                    ).fetchone()[0]
            assert original(case, proposal) == case["original"]
            command = Command.from_request(
                dict(
                    command_id=str(uuid4()),
                    action="edit_revision",
                    requested_at=utc_text(editor.AT),
                    expires_at=utc_text(editor.AT + timedelta(minutes=5)),
                    targets=[editor._identity(draft)],
                    payload=dict(
                        text="Pending invented restored edit.",
                    ),
                ),
                candidate.EDITOR,
                environment="local",
                now=editor.AT,
            )
            case["store"].accept(command, candidate.EDITOR, now=editor.AT)
            rows = editor.all_application_rows(core[3])
            before = case["store"].read()
            params, tool, directory = cluster
            dump = directory / ("published-radar-" + uuid4().hex + ".dump")
            args = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
            tool("pg_dump", *args, "-Fc", "-f", str(dump), core[3]["dbname"])
            name = "restore_" + uuid4().hex
            admin(
                params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name))
            )
            restored_params = dict(core[3], dbname=name)
            try:
                tool("pg_restore", *args, "--single-transaction", "-d", name, str(dump))
                authority = PostgresCommandAuthority(**options(restored_params))
                authority.configure_sourced_generation(lambda: case["config"])
                authority.configure_editor_media(**case["store"].editor_media_configuration)
                configure(authority, lambda: case["published_config"])
                authority.configure_delivery(delivery_path)
                restored = dict(case, store=authority)
                assert (
                    authority.read() == before
                    and editor.all_application_rows(restored_params) == rows
                )
                assert (
                    original(restored, proposal) == case["original"]
                    and editor.view(restored, png=proposal) == expected_png
                )
                result = authority.consume(
                    candidate.resolve, command_id=command.command_id, now=editor.AT
                )
                assert result["status"] == "applied"
                assert editor.view(restored)["review_current"] is False
                assert (
                    editor.view(restored, now=editor.AT + timedelta(minutes=14))["status"]
                    == "unavailable"
                )
                assert original(restored, proposal) == case["original"]
            finally:
                admin(
                    params,
                    psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        psycopg.sql.Identifier(name)
                    ),
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
