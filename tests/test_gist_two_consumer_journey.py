"""Two consumers, one retained identity, in fresh processes for every store family.

retained input (writer capability) → actual dashboard drafts route (Node) whose every
preview call is a FRESH isolated process running the verified packaged deployment's
real HTTP handler (auth, request contract, budget, build_preview, store read) →
attach / joint review with attestations / manual approval → a FRESH process running
the actual ``python -m src.main manual_tweet`` CLI against the same store → fake X
upload/alt/create → confirmed receipt and history → a second fresh sender never resends.

The PostgreSQL case executes the adapter's real statements and transactions over the
OFFLINE protocol fixture (tests/gist_pg_protocol_fixture.py: not PostgreSQL; genuine
acceptance is tests/test_postgres_gist_assets.py in required CI). The SQLite case uses
the real local store. Named fake boundaries only: the Gist HTTP API, the preview's Gist
state read, GitHub workflow dispatch (recorded), the safety model stub, the radar NWS
recheck and the X SDK factories. No network.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.gen_dashboard_graphic_runtime import DEPLOYMENT_FILES
from src.editorial.policy import current_editorial_policy
from src.media import gist_assets, gist_assets_postgres as pg
from tests import gist_pg_protocol_fixture as fx
from tests.gist_store_helpers import retain
from tests.test_gist_store_journey import FAMILIES, node_binary

ROOT = Path(__file__).resolve().parents[1]
GIST_ID = "0123456789abcdef0123"  # Invented; the preview reader requires the hex Gist id shape.
BACKENDS = ["postgres-protocol-fixture", "sqlite"]

# Fresh isolated process: verify and load the packaged deployment through its entry
# point, then serve its real HTTP handler on loopback for exactly one request.
PACKAGED_SERVER = r'''
import http.client, importlib.util, json, runpy, socket, sys, threading
from http.server import ThreadingHTTPServer
entry_path, fixture_module, fixture_file = sys.argv[1:4]
allowed, connect = [], socket.socket.connect
def guarded(self, address, *a, **k):
    if tuple(address) in allowed:
        return connect(self, address, *a, **k)
    raise AssertionError("external connection trapped")
socket.socket.connect = guarded
if fixture_module != "-":  # Test-only: the OFFLINE protocol fixture stands in for psycopg.
    spec = importlib.util.spec_from_file_location("gist_pg_protocol_fixture", fixture_module)
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture); fixture.install(fixture_file)
value = json.load(sys.stdin)
entry = runpy.run_path(entry_path)
assert entry["PreviewHandler"] is not entry["UnavailableHandler"], "verified runtime refused"
import src.dashboard_preview.http as preview_http
preview_http.read_gist = lambda env, budget: json.loads(value["raw_state"])  # Named fake: the Gist state read.
server = ThreadingHTTPServer(("127.0.0.1", 0), entry["handler"])
allowed.append(tuple(server.server_address))
thread = threading.Thread(target=server.handle_request, daemon=True); thread.start()
conn = http.client.HTTPConnection(*server.server_address, timeout=60)
conn.request("POST", "/api/graphic_preview", body=json.dumps(value["request"]).encode("utf-8"),
             headers={"Host": "localhost:3000", "Content-Type": "application/json", "Authorization": value["authorization"]})
reply = conn.getresponse(); status, raw = reply.status, reply.read()
conn.close(); thread.join(60); server.server_close()
zip_root = entry_path.rsplit("/api/", 1)[0] + "/graphic-runtime.zip/"
sources = [str(getattr(m, "__file__", "")) for k, m in list(sys.modules.items()) if k == "src" or k.startswith("src.")]
print(json.dumps({"status": status, "body": json.loads(raw), "psycopg": "psycopg" in sys.modules,
                  "sources_ok": bool(sources) and all(s.startswith(zip_root) for s in sources)}))
'''

ROUTE = r'''
import fs from "node:fs"; import { spawnSync } from "node:child_process"; import { pathToFileURL } from "node:url"
const [family, out, policyJSON, retained, configPath] = process.argv.slice(1)
const config = JSON.parse(fs.readFileSync(configPath, "utf8"))
const lib = name => pathToFileURL(`${process.cwd()}/${name}`).href
const { withGist, body, revision, attestationsFor } = await import(lib("tests/helpers/gist-hazard-harness.js"))
const { mediaPNGRequest, validateGraphicResponse } = await import(lib("lib/graphic-preview.js"))
const manifest = JSON.parse(fs.readFileSync("lib/graphic-runtime-manifest.json", "utf8"))
const packaged = []
const render = (request, rawState, authorization) => {
  const run = spawnSync(config.python, ["-I", "-c", config.server, config.entry, config.fixture_module, config.fixture_file],
    { cwd: config.cwd, env: config.env, input: JSON.stringify({ request, raw_state: rawState, authorization }),
      encoding: "utf8", timeout: 120000, maxBuffer: 32 * 1024 * 1024 })
  if (run.status !== 0) throw new Error(`packaged preview failed: ${run.stderr.slice(-4000)}`)
  const reply = JSON.parse(run.stdout)
  packaged.push({ status: reply.status, psycopg: reply.psycopg, sources_ok: reply.sources_ok,
    png_sha256: reply.body.png_sha256 ?? null, hold: reply.body.hold ?? null })
  return { status: reply.status, body: reply.body }
}
await withGist(family, async t => {
  const steps = [], original = t.get()
  const preview = t.preview(original)
  const request = mediaPNGRequest({ ...original, revision_identity: revision(original) }, manifest, retained)
  const browser = await validateGraphicResponse(preview, request, manifest)
  const step = async (name, action, extra = {}) => {
    const result = await t.post(body(t.get(), action, extra))
    steps.push({ name, status: result.status, code: result.body.code ?? null })
  }
  const sha = preview.media_descriptor_sha256
  await step("attach", "attach_graphic", { expectedMediaSha256: sha, retainedInputSha256: retained })
  const policySha = (await t.list()).find(d => d.id === t.primary).editorial_policy.policy_sha256
  await step("joint_review", "review", { reviewConfirmed: true, mediaReviewConfirmed: true, expectedMediaSha256: sha,
    expectedPolicySha256: policySha, ...attestationsFor(preview) })
  await step("approve", "approve")
  fs.writeFileSync(out, JSON.stringify({ preview, browser_ok: browser === preview, steps, dispatches: t.dispatches,
    raw_state: t.raw(), clock: t.clock.current, primary: t.primary, packaged }))
}, { editorialPolicy: JSON.parse(policyJSON), retainedInput: retained, render })
'''


def deploy_runtime(tmp_path):
    deploy = tmp_path / "deploy"
    for name in (*DEPLOYMENT_FILES, "graphic-runtime.zip", "lib/graphic-runtime-manifest.json"):
        target = deploy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "dashboard" / name, target)
    (tmp_path / "unrelated-cwd").mkdir()
    return deploy


def shared_store(backend, tmp_path):
    """The one invented store both consumers read, plus each consumer's selection."""
    if backend == "sqlite":
        path = tmp_path / "media.sqlite3"
        return gist_assets.SQLiteMediaStore(path), {gist_assets.ENV: f"sqlite:{path}"}, None
    fixture = fx.create(tmp_path / "protocol.sqlite3")
    writer = pg.PostgresMediaStore(pg.parse_dsn(fx.WRITER_DSN), role="writer", driver=fx.module(fixture))
    return writer, {gist_assets.ENV: "postgres", gist_assets.DSN_ENV: fx.READER_DSN, fx.ENV: str(fixture)}, fixture


def base_env(tmp_path):
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "LC_ALL": "C", "LANG": "C",
            "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1"}


def route_journey(family, tmp_path, retained, store_env, fixture, *, python=None):
    deploy = deploy_runtime(tmp_path)
    preview_env = {**base_env(tmp_path), "DASHBOARD_USERNAME": "invented-reviewer",
                   "DASHBOARD_PASSWORD": "invented-password",
                   **{k: v for k, v in store_env.items() if k != fx.ENV}}
    config = {"python": python or sys.executable, "server": PACKAGED_SERVER, "entry": str(deploy / "api/graphic_preview.py"),
              "fixture_module": str(Path(fx.__file__).resolve()) if fixture else "-",
              "fixture_file": str(fixture or "-"), "cwd": str(tmp_path / "unrelated-cwd"), "env": preview_env}
    config_path, out = tmp_path / "route-config.json", tmp_path / "route-result.json"
    config_path.write_text(json.dumps(config))
    env = {**base_env(tmp_path), "THEHEAT_TEST_PYTHON": sys.executable}
    run = subprocess.run([node_binary(), "--input-type=module", "-e", ROUTE, family, str(out),
                          json.dumps(current_editorial_policy()), retained, str(config_path)],
                         cwd=ROOT / "dashboard", env=env, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads(out.read_text())


def send(tmp_path, raw_state, inputs, event_id, now, store_env, *, family, name="sender", failure=None,
         gist_write_failure=None, nws_features=None, fault_after_intent=None):
    """One fresh actual-CLI manual sender process; returns its record and the saved state."""
    gist = tmp_path / "gist-state.json"
    if not gist.exists():
        gist.write_text(raw_state)
    workdir = tmp_path / name
    workdir.mkdir()
    config = {"gist_file": str(gist), "out": str(workdir / "record.json"), "event_id": event_id,
              "now": now, "failure": failure, "gist_write_failure": gist_write_failure,
              "nws_features": nws_features, "fault_after_intent": fault_after_intent}
    if family == "radar" and nws_features is None:
        from tests.gist_published_helpers import radar_feature
        config["nws_feature"] = radar_feature()
    (workdir / "config.json").write_text(json.dumps(config))
    env = {**base_env(workdir), **store_env, "GIST_ID": GIST_ID, "GITHUB_TOKEN": "invented-not-a-real-token",
           "THEHEAT_STATE_BACKEND": "gist", "TWEET_TEXT": inputs["tweet_text"], "DRAFT_ID": inputs["draft_id"],
           "PUBLISH_INTENT_ID": inputs["publish_intent_id"]}
    run = subprocess.run([sys.executable, "-m", "tests.gist_two_consumer_sender", str(workdir / "config.json")],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-4000:]
    record = json.loads((workdir / "record.json").read_text())
    record["uploaded"] = (workdir / "uploaded.png").read_bytes() if (workdir / "uploaded.png").exists() else None
    return record, json.loads(gist.read_text())


def send_routed(tmp_path, route, store_env, **options):
    saved = json.loads(route["raw_state"])
    primary = next(d for d in saved["drafts"] if d["id"] == route["primary"])
    now = datetime.fromtimestamp(route["clock"] / 1000, timezone.utc).isoformat()
    return send(tmp_path, route["raw_state"], route["dispatches"][0]["inputs"], primary["event_id"], now, store_env,
                **options)


def packaged_preview(tmp_path, deploy, state, request, store_env, fixture=None, *, python=None):
    """One fresh isolated process serving the packaged handler for exactly one request."""
    env = {**base_env(tmp_path), "DASHBOARD_USERNAME": "invented-reviewer", "DASHBOARD_PASSWORD": "invented-password",
           **{k: v for k, v in store_env.items() if k != fx.ENV}}
    auth = "Basic " + base64.b64encode(b"invented-reviewer:invented-password").decode()
    run = subprocess.run([python or sys.executable, "-I", "-c", PACKAGED_SERVER, str(deploy / "api/graphic_preview.py"),
                          str(Path(fx.__file__).resolve()) if fixture else "-", str(fixture or "-")],
                         input=json.dumps({"request": request, "raw_state": json.dumps(state), "authorization": auth}),
                         cwd=tmp_path / "unrelated-cwd", env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads(run.stdout)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("family", FAMILIES)
def test_packaged_preview_and_actual_sender_share_one_retained_identity(family, backend, tmp_path):
    writer, store_env, fixture = shared_store(backend, tmp_path)
    retained = retain(family, writer)
    route = route_journey(family, tmp_path, retained, store_env, fixture)
    preview = route["preview"]
    assert route["browser_ok"] is True and preview["schema_version"] == (4 if family == "crw" else 5)
    assert [(s["name"], s["status"]) for s in route["steps"]] == [("attach", 200), ("joint_review", 200), ("approve", 200)]
    # Every preview (browser + route re-checks) ran in its own packaged process from the ZIP.
    assert len(route["packaged"]) >= 3 and all(p["status"] == 200 and p["sources_ok"] for p in route["packaged"])
    assert {p["png_sha256"] for p in route["packaged"]} == {preview["png_sha256"]}
    assert all(p["psycopg"] is (backend != "sqlite") for p in route["packaged"])

    record, final = send_routed(tmp_path, route, store_env, family=family)
    reviewed_png = base64.b64decode(preview["png_base64"])
    saved = json.loads(route["raw_state"])
    primary = next(d for d in saved["drafts"] if d["id"] == route["primary"])
    assert record["exit"] == 0 and record["intent_before_upload"] == "submitted"
    assert record["uploaded"] == reviewed_png
    assert record["calls"] == [["upload", hashlib.sha256(reviewed_png).hexdigest(), "hot10.png"],
                               ["alt", "98765", preview["delivery_text"]],
                               ["create", primary["text"], {"media_ids": ["98765"]}]]
    assert record["postgres_adapter"] is (backend != "sqlite") and record["psycopg"] is (backend != "sqlite")
    receipt = final["publish_ledger"][primary["event_id"]]
    assert receipt["phase"] == "confirmed" and receipt["tweet_id"] == "invented-x-receipt"
    sent = next(d for d in final["drafts"] if d["id"] == primary["id"])
    assert sent["status"] == "posted" and sent["tweet_id"] == "invented-x-receipt"
    assert sent["media_attachment"] == primary["media_attachment"] == preview["media_descriptor"]
    assert any(r.get("mode") == "manual_tweet" for r in final["run_history"])
    assert saved["unrelated"] == {"preserve": True}  # The route's lossless write; the bot CLI normalizes.
    assert "png_base64" not in json.dumps(final) and "iVBORw0KGgo" not in json.dumps(final)

    again, _ = send_routed(tmp_path, route, store_env, family=family, name="sender-again")
    assert again["exit"] == 0 and again["calls"] == [] and again["uploaded"] is None
    if fixture:
        assert fx.counter(fixture, "payload_reads") >= 5  # Previews and the sender read real rows.
        assert fx.counter(fixture, "connections") == fx.counter(fixture, "closed")


def approved_state(family, tmp_path, writer, store_env, fixture=None, *, python=None):
    """Retain → packaged HTTP preview (fresh process) → saved attach/joint review/approval.

    Returns (state, draft, preview); the state is what the route would have saved."""
    from src.editorial.revisions import decision_revision, draft_identity
    from src.media import gist_media
    from tests.gist_media_helpers import approve, attach
    from tests.gist_store_helpers import CLOCKS, saved_state
    retained = retain(family, writer)
    deploy = deploy_runtime(tmp_path)
    manifest = json.loads((deploy / "lib/graphic-runtime-manifest.json").read_text())
    state = saved_state(family)
    draft = state["drafts"][0]
    request = {"draft_id": draft["id"], "format": "png", "retained_input_sha256": retained,
               "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
               "expected_policy_source_sha256": manifest["identity"]["policy_source_sha256"],
               "expected_preview_runtime_sha256": manifest["runtime_sha256"]}
    reply = packaged_preview(tmp_path, deploy, state, request, store_env, fixture, python=python)
    assert reply["status"] == 200 and reply["sources_ok"], reply["body"]
    preview = reply["body"]
    attach(draft, preview["media_descriptor"], at=CLOCKS[family][0])
    approve(draft, attestations={name: True for name in gist_media.required_attestations(draft["media_attachment"])})
    return state, draft, preview


def inputs_for(draft):
    return {"tweet_text": draft["text"], "draft_id": draft["id"], "publish_intent_id": draft["publish_intent_id"]}


def python_two_consumers(family, tmp_path, writer, store_env, fixture=None, *, python=None):
    """Node-free variant (also used by required CI's genuine PostgreSQL run): packaged
    HTTP preview in a fresh process → saved attach/joint review/approval → actual CLI sender."""
    from tests.gist_store_helpers import CLOCKS
    state, draft, preview = approved_state(family, tmp_path, writer, store_env, fixture, python=python)
    record, final = send(tmp_path, json.dumps(state), inputs_for(draft), draft["event_id"], CLOCKS[family][0], store_env,
                         family=family)
    reviewed_png = base64.b64decode(preview["png_base64"])
    assert record["exit"] == 0 and record["intent_before_upload"] == "submitted" and record["uploaded"] == reviewed_png
    assert [c[0] for c in record["calls"]] == ["upload", "alt", "create"]
    assert record["calls"][1][2] == preview["delivery_text"] and record["calls"][2][1] == draft["text"]
    receipt = final["publish_ledger"][draft["event_id"]]
    assert receipt["phase"] == "confirmed" and receipt["tweet_id"] == "invented-x-receipt"
    return preview, record, final


@pytest.mark.parametrize("family", FAMILIES)
def test_node_free_two_consumers_over_the_protocol_fixture(family, tmp_path):
    writer, store_env, fixture = shared_store("postgres-protocol-fixture", tmp_path)
    _preview, record, _final = python_two_consumers(family, tmp_path, writer, store_env, fixture)
    assert record["postgres_adapter"] is True
    assert fx.counter(fixture, "connections") == fx.counter(fixture, "closed")
