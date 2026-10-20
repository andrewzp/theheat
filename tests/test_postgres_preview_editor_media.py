"""Actual Next handlers -> authenticated HTTP -> PG + separate native/check process."""

from datetime import datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest

from src.commands import preview_ingress
from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.schema import utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from tests.test_postgres_editor_media import (
    admitted as admitted, offline_connections as offline_connections, AT,
)
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import (
    core as core,
    make_authority as make_authority,
    options,
)
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_postgres_preview_command_ingress import clean_environment

ROOT = Path(__file__).resolve().parents[1]
CHILD = r"""
import json,os,socket,sys
from pathlib import Path
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators,safe_environment
from src.commands.preview_media_worker import consume_media_once
from src.commands.schema import utc_datetime,utc_text,canonical_json,CommandError
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot import writer,check_requests
from src.two_bot.check_origin import spending_job
from src.voice import safety
from tests import test_check_executor as executor
from tests.test_postgres_editor_media import fact_pass
from pytest import MonkeyPatch
config=json.loads(Path(sys.argv[1]).read_text()); operation,identity=sys.argv[2:4]
safe_environment()
writer.WRITER_PROVIDER=config["writer_provider"];writer.WRITER_MODEL=config["writer_model"]
safety.GEMINI_API_KEY="invented-offline-key"
assert fingerprint(current_editorial_policy())==config["policy_sha256"]
original=socket.socket.connect
def connect(sock,address):
    if sock.family!=socket.AF_UNIX:raise AssertionError("External connection refused")
    return original(sock,address)
socket.socket.connect=connect
authority=PostgresCommandAuthority(**config["authority"])
authority.configure_sourced_generation(lambda:config["generation"])
authority.configure_editor_media(**config["native"])
operators=Operators(config["operators"]); now=utc_datetime(config["at"])
if operation=="consume":
    try:result=authority.consume(operators.resolve,command_id=identity,now=now)
    except CommandError as exc:
        if exc.code!="native_preparation_required":raise
        result=consume_media_once(authority,operators.resolve,command_id=identity,now=now)
else:
    set_id=authority.result(identity)["revision_checks"]["check_set_id"]
    packet=authority.check_execution("read",{"check_set_id":set_id},now=config["at"])["packet"]
    raw=canonical_json(check_requests.prepare_request(packet,operation)).encode()
    reserve=None if operation=="deterministic" else dict(intent_id="http-media-"+operation,job_id=spending_job(packet),
        request_sha256=__import__("hashlib").sha256(raw).hexdigest(),provider="google",role=operation,
        model=packet["policy"]["models"][operation],estimate_sha256="e"*64,reserve_micro_usd=5)
    os.environ["GEMINI_API_KEY"]="invented-offline-key"
    with MonkeyPatch.context() as patch:
        response={"safety":"NO","fact_check":fact_pass(packet["final_text"]),"critic":executor.CRITIC_PASS}.get(operation,"NO")
        sent,_=executor.provider(patch,[executor.envelope(response)])
        result=authority.execute_revision_check_once(identity,operators.resolve,clock=lambda:config["at"],reservation=reserve,enabled=True)
        with Path(config["requests"]).open("a") as stream:
            for request in sent:stream.write(operation+"\n")
print(json.dumps(result))
"""


@pytest.mark.parametrize("admitted", ["modis", "pm25", "viirs_n20"], indirect=True)
def test_actual_private_http_native_review_check_park_recovery(
    admitted, core, monkeypatch, tmp_path
):
    case = admitted
    for key in tuple(os.environ):
        if key.startswith("PG") or any(
            word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        ):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return AT

    monkeypatch.setattr(preview_ingress, "datetime", Clock)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        origin = "http://127.0.0.1:" + str(probe.getsockname()[1])
    operators = tmp_path / "operators.json"
    operators.write_text(
        json.dumps(
            {
                "operators": [
                    dict(
                        username=role,
                        password="invented-" + role,
                        subject="invented-" + role,
                        role=role,
                    )
                    for role in ("editor", "publisher", "viewer")
                ]
            }
        )
    )
    operators.chmod(0o600)
    server = PreviewServer(case["store"], Operators(operators), port=0, origin=origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = tmp_path / "media-worker.py"
    child.write_text(CHILD)
    from src.two_bot import writer

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
        at=utc_text(AT),
        writer_provider=writer.WRITER_PROVIDER,
        writer_model=writer.WRITER_MODEL,
    )
    path = tmp_path / "http.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    try:
        result = subprocess.run(
            [os.environ.get("THEHEAT_NODE24", "node"), "--test", "tests/editor-media-http.test.js"],
            cwd=ROOT / "dashboard",
            env={**clean_environment(), "THEHEAT_MEDIA_HTTP_CONFIG": str(path)},
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert Path(config["requests"]).read_text().splitlines() == [
            "safety",
            "fact_check",
            "critic",
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("admitted", ["viirs_snpp"], indirect=True)
def test_actual_http_source_refusal_is_durable_and_does_not_block_edit(admitted, monkeypatch, tmp_path):
    from datetime import timedelta
    from uuid import uuid4

    from src.commands.preview_media_worker import consume_media_once
    from src.commands.reducer import _identity
    from tests.test_postgres_preview_command_ingress import ORIGIN, http

    case, store = admitted, admitted["store"]
    for key in tuple(os.environ):
        if key.startswith("PG") or any(word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return AT

    monkeypatch.setattr(preview_ingress, "datetime", Clock)
    path = tmp_path / "refusal-operators.json"
    path.write_text(json.dumps({"operators": [dict(username="editor", password="invented-editor",
                                                 subject="invented-editor", role="editor")]}))
    path.chmod(0o600)
    operators = Operators(path)
    server = PreviewServer(store, operators, port=0, origin=ORIGIN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    before = store.read()
    draft = next(d for d in before[1]["drafts"] if d["id"] == case["draft_id"])

    def command(action, payload):
        return dict(command_id=str(uuid4()), action=action, requested_at=utc_text(AT),
                    expires_at=utc_text(AT + timedelta(minutes=5)), targets=[_identity(draft)], payload=payload)

    try:
        status, body, headers = http(server.server_port, f"/drafts/{case['draft_id']}/media")
        assert status == 200 and body["status"] == "unavailable" and body["code"] == "graphic_source_unqualified"
        assert headers["Cache-Control"] == "private, no-store"
        prepare = command("prepare_media_revision", dict(
            expected_policy_sha256=fingerprint(current_editorial_policy()),
            expected_renderer_profile_sha256="f" * 64))
        assert http(server.server_port, "/commands", method="POST", value=prepare)[0] == 202
        refused = consume_media_once(store, operators.resolve, command_id=prepare["command_id"], now=AT)
        assert refused["status"] == "rejected" and refused["code"] == "graphic_source_unqualified"
        assert consume_media_once(store, operators.resolve, command_id=prepare["command_id"], now=AT) == refused
        assert http(server.server_port, f"/commands/{prepare['command_id']}")[1]["result"] == refused
        assert store.read() == before
        edit = command("edit_revision", {"text": "An edited invented VIIRS source statement."})
        assert http(server.server_port, "/commands", method="POST", value=edit)[0] == 202
        result = store.consume(operators.resolve, command_id=edit["command_id"], now=AT)
        assert result["status"] == "applied"  # Never command_pending behind the refused preparation.
        assert http(server.server_port, f"/commands/{edit['command_id']}")[1]["result"] == result
        after = store.read()[1]
        assert {k: v for k, v in after.items() if k != "drafts"} == {
            k: v for k, v in before[1].items() if k != "drafts"
        }  # Preserve even absent optional publication fields, not just ledger counts.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
