"""Actual Next HTTP handlers and a separate checker using invented SDK traffic."""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.postgres_candidate_admission import PAUSED_EPOCH
from src.commands.schema import utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.voice import safety
from tests import test_batch_journal as batch, test_batch_result_journal as results
from tests import test_batch_worker_journal as worker, test_check_executor as checks
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import core as core, make_authority as make_authority, options
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_postgres_preview_command_ingress import clean_environment, operator_file

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:3036"
# Explicit private-fixture capability injection; public ingress defaults are unchanged.
CHILD_CODE = r'''
import json,os,socket,sys
from datetime import UTC,datetime
from pathlib import Path
from src.voice import safety
from src.two_bot import writer
safety.GEMINI_API_KEY="offline-fixture-key"
writer.WRITER_PROVIDER="anthropic";writer.WRITER_MODEL="claude-synthetic"
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators,safe_environment
from src.commands.schema import canonical_json,utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot import check_requests
from tests import test_check_executor as fixtures
from pytest import MonkeyPatch
config=json.loads(Path(sys.argv[1]).read_text())
safe_environment()
authority=PostgresCommandAuthority(**config["authority"])
operators=Operators(config["operators"])
assert fingerprint(current_editorial_policy())==config["policy_sha256"]
original=socket.socket.connect
def connect(sock,address):
    if sock.family!=socket.AF_UNIX:raise AssertionError("Fixture external network refused")
    return original(sock,address)
socket.socket.connect=connect
if sys.argv[2]=="consume":
    result=authority.consume(operators.resolve,command_id=sys.argv[3],now=datetime.now(UTC))
else:
    import hashlib
    command_id=sys.argv[3]
    completed=authority.result(command_id)
    identity=completed["candidate"]["check_set_id"]
    packet=authority.check_execution("read",{"check_set_id":identity},now=utc_text(datetime.now(UTC)))["packet"]
    stage=sys.argv[4]
    request=canonical_json(check_requests.prepare_request(packet,stage)).encode()
    reservation=None if stage=="deterministic" else dict(intent_id="http-fixture-"+stage,job_id=packet["job_id"],request_sha256=hashlib.sha256(request).hexdigest(),provider="google",role=stage,model=packet["policy"]["models"][stage],estimate_sha256="e"*64,reserve_micro_usd=5)
    os.environ["GEMINI_API_KEY"]="offline-fixture-key"
    with MonkeyPatch.context() as patch:
        sent,_=fixtures.provider(patch,[fixtures.envelope({"safety":"NO","fact_check":fixtures.FACT_PASS,"critic":fixtures.CRITIC_PASS}.get(stage,"NO"))])
        result=authority.execute_candidate_check_once(command_id,operators.resolve,clock=lambda:utc_text(datetime.now(UTC)),reservation=reservation,enabled=True)
        with Path(config["requests"]).open("a") as stream:
            for request in sent:stream.write(stage+"\n")
print(json.dumps(result))
'''


@pytest.fixture
def candidate_preview(store, core, inputs, tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("PG") or any(word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    now = datetime.now(UTC)
    captured = now - timedelta(seconds=301)
    at = utc_text(captured)
    inputs.update(policy=current_editorial_policy(), publication_epoch=PAUSED_EPOCH,
                  created_at=at, useful_until=utc_text(now+timedelta(hours=8)))
    pair = batch.packet(inputs)
    batch.register(store, pair, at=at)
    worker.acquire(store, at=at)
    grant = worker.begin(store, pair, at=at)
    ack = worker.ack()
    worker.observe(store, grant, ack, at=at)
    worker.adopt(store, ack, at=at)
    rows = results.rows(pair)
    candidate = json.loads(rows[0]["result"]["message"]["content"][0]["text"])
    candidate["tweet"] = checks.TEXT
    rows[0]["result"]["message"]["content"][0]["text"] = json.dumps(candidate)
    receipt = results.retain(store, grant, results.contract.raw_rows(rows), at=at)
    refs = store.capture_candidate_input(dict(job_id=pair[1]["job_id"], custom_id=json.loads(pair[0])["requests"][0]["custom_id"],
        receipt_id=receipt["receipt_id"], owner="worker-one", fence=1, bundle=inputs["bundle"].to_dict(), memory=inputs["memory"].to_dict(),
        save=dict(legacy_type="fire", event_id=inputs["bundle"].event_id, score=None, city="", tweet_date="", cooldown_exempt=False,
                  review_context=None, evaluator_metadata=None)), now=captured)
    operators = operator_file(tmp_path/"operators.json")
    server = PreviewServer(store, Operators(operators), port=0, origin=ORIGIN, candidate_inputs=(refs["admission_input_id"],))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child = tmp_path/"invented-candidate-worker.py"
    child.write_text(CHILD_CODE)
    config = dict(endpoint=f"http://127.0.0.1:{server.server_port}", origin=ORIGIN, root=str(ROOT), python=sys.executable,
        child=str(child), authority=options(core[3]), operators=str(operators), requests=str(tmp_path/"requests.txt"),
        policy_sha256=fingerprint(current_editorial_policy()), refs=refs)
    config_path = tmp_path/"candidate-http.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    yield config_path, config, store, inputs
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_actual_next_candidate_request_checks_admission_and_edit(candidate_preview):
    config_path, config, store, inputs = candidate_preview
    before = store.read()
    raw_bundle = json.dumps(inputs["bundle"].to_dict(), sort_keys=True, separators=(",", ":"))
    assert "361.0" in raw_bundle  # Node displays integer; authority retains exact original float.
    result = subprocess.run(["node", "--test", "tests/draft-command-api.test.js"], cwd=ROOT/"dashboard",
        env={**clean_environment(), "THEHEAT_CANDIDATE_TEST_CONFIG": str(config_path)}, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout+result.stderr
    assert Path(config["requests"]).read_text().splitlines() == ["safety", "fact_check", "critic"]
    draft = store.read()[1]["drafts"][-1]
    assert draft["text"] == "Edited after required checks; a new review is required."
    assert "review_binding" not in draft and "approval_binding" not in draft
    original_proof = draft["revision_history"][0]["review_context"]["two_bot"]["required_checks_binding"]
    assert len(original_proof["stages"]) == 4
    with store.projections._connection() as c:
        from src.commands.postgres_candidate_admission import read_input
        retained = read_input(c, config["refs"])
    assert json.dumps(retained["bundle"], sort_keys=True, separators=(",", ":")) == raw_bundle
    assert before[1]["drafts"] == store.read()[1]["drafts"][:-1]
