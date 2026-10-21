"""Actual dashboard HTTP and separate offline worker from source start to edit."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.postgres_sourced_generation import private_configuration
from src.commands.schema import utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.voice import safety
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import core as core, make_authority as make_authority, options
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_postgres_preview_command_ingress import clean_environment, operator_file
from tests.test_postgres_sourced_generation import allowance_document
from tests.workflow_clock import positive_workflow_clock as positive_workflow_clock


@pytest.fixture(autouse=True)
def _stable_positive_time(positive_workflow_clock):
    yield

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:3038"
CHILD = r'''
import json,os,socket,sys,hashlib
from datetime import UTC,datetime
from pathlib import Path
from src.voice import safety
from src.two_bot import writer
safety.GEMINI_API_KEY="offline-fixture-key"
writer.WRITER_PROVIDER="anthropic";writer.WRITER_MODEL="claude-synthetic"
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_sourced_generation import private_configuration
from src.commands.preview_ingress import Operators,safe_environment
from src.commands.schema import canonical_json,utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot import check_requests
from tests import test_check_executor as checks
from tests.test_postgres_sourced_generation import transport
from pytest import MonkeyPatch
cfg=json.loads(Path(sys.argv[1]).read_text())
from tests.workflow_clock import start_child_clock
fixture_clock=start_child_clock(cfg["test_clock"])
safe_environment()
authority=PostgresCommandAuthority(**cfg["authority"])
authority.configure_sourced_generation(private_configuration(cfg["generation"]))
operators=Operators(cfg["operators"])
assert fingerprint(current_editorial_policy())==cfg["policy_sha256"]
original=socket.socket.connect
def connect(sock,address):
    if sock.family!=socket.AF_UNIX:raise AssertionError("Fixture external network refused")
    return original(sock,address)
socket.socket.connect=connect
operation,command_id=sys.argv[2:4]
now=datetime.now(UTC)
if operation=="consume":
    result=authority.consume(operators.resolve,command_id=command_id,now=now)
elif operation=="projection":
    result=authority.candidate_projection(authority.generated_candidate_inputs(),now=now)
elif operation in {"submit","collect","capture"}:
    os.environ["ANTHROPIC_API_KEY"]="offline-fixture-key"
    os.environ["GEMINI_API_KEY"]="offline-fixture-key"
    case={"store":authority,"result":authority.result(command_id)}
    sent,factory=transport(case,at=now)
    result=authority.execute_sourced_generation_once(command_id,operators.resolve,clock=lambda:utc_text(datetime.now(UTC)),operation=operation,enabled=True,transport_factory=factory)
    with Path(cfg["requests"]).open("a") as stream:
        for method,path,body in sent:stream.write(method+" "+path+"\n")
else:
    identity=authority.result(command_id)["candidate"]["check_set_id"]
    packet=authority.check_execution("read",{"check_set_id":identity},now=utc_text(now))["packet"]
    request=canonical_json(check_requests.prepare_request(packet,operation)).encode()
    reservation=None if operation=="deterministic" else dict(intent_id="http-generation-"+operation,job_id=packet["job_id"],request_sha256=hashlib.sha256(request).hexdigest(),provider="google",role=operation,model=packet["policy"]["models"][operation],estimate_sha256="e"*64,reserve_micro_usd=5)
    os.environ["GEMINI_API_KEY"]="offline-fixture-key"
    with MonkeyPatch.context() as patch:
        sent,_=checks.provider(patch,[checks.envelope({"safety":"NO","fact_check":checks.FACT_PASS,"critic":checks.CRITIC_PASS}.get(operation,"NO"))])
        result=authority.execute_candidate_check_once(command_id,operators.resolve,clock=lambda:utc_text(datetime.now(UTC)),reservation=reservation,enabled=True)
        with Path(cfg["requests"]).open("a") as stream:
            for request in sent:stream.write(operation+"\n")
print(json.dumps(result))
'''


@pytest.fixture
def sourced_preview(store, core, inputs, monkeypatch, tmp_path, positive_workflow_clock):
    for key in tuple(os.environ):
        if key.startswith("PG") or any(word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    now = datetime.now(UTC)
    refs = store.retain_generation_input(dict(schema_version=1, source_key="firms", source_revision="invented-http",
        captured_at=utc_text(now), useful_until=utc_text(now+timedelta(hours=8)), urgent=False,
        bundle=inputs["bundle"].to_dict(), save=dict(legacy_type="fire", event_id=inputs["bundle"].event_id,
            score=None, city="", tweet_date="", cooldown_exempt=False, review_context=None, evaluator_metadata=None)))
    generation = tmp_path/"generation.json"
    reserve = store.retain_generation_reservation(allowance_document(refs["brief_id"], now=now))
    generation.write_text(json.dumps(dict(current_inputs=[refs["brief_id"]], reservation=reserve)))
    generation.chmod(0o600)
    store.configure_sourced_generation(private_configuration(generation))
    operators = operator_file(tmp_path/"operators.json")
    server = PreviewServer(store, Operators(operators), port=0, origin=ORIGIN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = tmp_path/"generation-worker.py"
    child.write_text(CHILD)
    config = dict(endpoint=f"http://127.0.0.1:{server.server_port}", origin=ORIGIN, root=str(ROOT), python=sys.executable,
        child=str(child), authority=options(core[3]), operators=str(operators), generation=str(generation),
        requests=str(tmp_path/"requests.txt"), policy_sha256=fingerprint(current_editorial_policy()),
        test_clock=positive_workflow_clock)
    config_path = tmp_path/"http.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    yield config_path, config, store
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_actual_component_http_source_start_to_checked_edited_draft(sourced_preview):
    path, config, store = sourced_preview
    before = store.read()
    result = subprocess.run(["node", "--test", "tests/sourced-generation.test.js"], cwd=ROOT/"dashboard",
        env={**clean_environment(), "THEHEAT_GENERATION_TEST_CONFIG": str(path)}, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout+result.stderr
    assert Path(config["requests"]).read_text().splitlines() == ["POST /v1/messages/batches", "GET /v1/messages/batches/msgbatch_fixture", "GET /v1/messages/batches/msgbatch_fixture/results", "safety", "fact_check", "critic"]
    saved = store.read()[1]["drafts"][-1]
    assert saved["text"] == "Edited after sourced generation; review is required."
    assert "review_binding" not in saved and "approval_binding" not in saved
    assert store.read()[1]["drafts"][:-1] == before[1]["drafts"]
