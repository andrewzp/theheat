"""The sealed preview runtime renders every store-backed family from a shared store.

A fresh isolated interpreter loads only the verified packaged deployment through its
real entry point, from an unrelated working directory, reads the same invented store
and must return byte-identical PNG/description/descriptor to the checkout. The
PostgreSQL case drives the packaged adapter's real statements through the OFFLINE
protocol fixture (not PostgreSQL); the SQLite case uses the real local store.
THEHEAT_TEST_DASHBOARD_PYTHON may name an interpreter built from dashboard/uv.lock
(real psycopg installed) to run the packaged side; it is still never imported unless
a PostgreSQL store is selected.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from freezegun import freeze_time
import pytest

from scripts.gen_dashboard_graphic_runtime import DEPLOYMENT_FILES, ROOT
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import decision_revision, draft_identity
from src.media import gist_assets, gist_assets_postgres as pg
from tests import gist_pg_protocol_fixture as fx
from tests.gist_store_helpers import CLOCKS, retain, saved_state

FIXTURE = Path(fx.__file__).resolve()
PYTHON = os.environ.get("THEHEAT_TEST_DASHBOARD_PYTHON") or sys.executable
PACKAGED = r'''
import importlib.util, json, runpy, socket, sys
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
if sys.argv[3] != "-":  # Test-only: the OFFLINE protocol fixture stands in for psycopg.
    spec = importlib.util.spec_from_file_location("gist_pg_protocol_fixture", sys.argv[3])
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture); fixture.install(sys.argv[4])
entry = runpy.run_path(sys.argv[1])
assert entry["PreviewHandler"] is not entry["UnavailableHandler"], "verified runtime refused"
from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
manifest = json.load(open(sys.argv[2]))
policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
out = []
for state, request in json.load(sys.stdin):
    request.update(expected_policy_source_sha256=policy, expected_preview_runtime_sha256=runtime)
    try:
        out.append(json.loads(build_preview(request, policy_sha=policy, runtime_sha=runtime, read_state=lambda: state,
                                            budget=Budget())))
    except PreviewError as exc:
        out.append({"status": exc.status, **exc.payload()})
sources = sorted({str(getattr(m, "__file__", "")) for k, m in sys.modules.items() if k == "src" or k.startswith("src.")})
print(json.dumps({"responses": out, "sources": sources, "psycopg": "psycopg" in sys.modules}))
'''


def _deploy(tmp_path):
    deploy = tmp_path / "deploy"
    for name in (*DEPLOYMENT_FILES, "graphic-runtime.zip", "lib/graphic-runtime-manifest.json"):
        target = deploy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "dashboard" / name, target)
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    return deploy, elsewhere


def _request(state, retained):
    draft = state["drafts"][0]
    value = {"draft_id": draft["id"], "format": "png",
             "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)}}
    if retained:
        value["retained_input_sha256"] = retained
    return value


def _packaged(tmp_path, payload, env, fixture=None):
    deploy, elsewhere = _deploy(tmp_path)
    result = subprocess.run([PYTHON, "-I", "-c", PACKAGED, str(deploy / "api/graphic_preview.py"),
                             str(deploy / "lib/graphic-runtime-manifest.json"),
                             str(FIXTURE) if fixture else "-", str(fixture or "-")],
                            input=json.dumps(payload), capture_output=True, text=True, timeout=120, cwd=elsewhere,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": str(elsewhere), **env})
    assert result.returncode == 0, result.stderr[-3000:]
    value = json.loads(result.stdout)
    assert value["sources"] and all(s.startswith(str(deploy / "graphic-runtime.zip") + "/") for s in value["sources"])
    return value


BOUND = ("png_base64", "png_sha256", "media_descriptor", "media_descriptor_sha256", "delivery_text",
         "expanded_description", "title", "scope")


@pytest.mark.parametrize("backend", ["postgres-protocol-fixture", "sqlite"])
@pytest.mark.parametrize("family", ["crw", "radar", "cone"])
def test_packaged_preview_reads_the_shared_store_byte_identically(family, backend, tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name)
    local_store: Any
    if backend == "sqlite":
        path = tmp_path / "media.sqlite3"
        retained = retain(family, gist_assets.SQLiteMediaStore(path))
        local_store, env, fixture = gist_assets.SQLiteMediaStore(path, writable=False), {gist_assets.ENV: f"sqlite:{path}"}, None
    else:
        fixture = fx.create(tmp_path / "protocol.sqlite3")
        writer = pg.PostgresMediaStore(pg.parse_dsn(fx.WRITER_DSN), role="writer", driver=fx.module(fixture))
        retained = retain(family, writer)
        local_store = pg.PostgresMediaStore(pg.parse_dsn(fx.READER_DSN), role="reader", driver=fx.module(fixture))
        env = {gist_assets.ENV: "postgres", gist_assets.DSN_ENV: fx.READER_DSN}
    state = saved_state(family)
    manifest = json.loads((ROOT / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
    with freeze_time(CLOCKS[family][0]):
        local = json.loads(build_preview({**_request(state, retained), "expected_policy_source_sha256": policy,
                                          "expected_preview_runtime_sha256": runtime}, policy_sha=policy,
                                         runtime_sha=runtime, read_state=lambda: deepcopy(state), budget=Budget(),
                                         store=local_store))
    value = _packaged(tmp_path, [[state, _request(state, retained)]], env, fixture)
    packaged = value["responses"][0]
    assert packaged["schema_version"] == local["schema_version"] == (4 if family == "crw" else 5)
    for key in BOUND:
        assert packaged[key] == local[key], key
    if family != "crw":
        assert packaged["original_base64"] == local["original_base64"]
    assert value["psycopg"] is (backend != "sqlite")


def test_native_previews_work_with_no_store_and_no_driver_while_store_lanes_hold(tmp_path, monkeypatch):
    from tests.gist_hazard_helpers import saved_state as native_state
    payload = [[saved_state("crw"), _request(saved_state("crw"), "1" * 64)],
               [native_state("pm25"), _request(native_state("pm25"), None)]]
    value = _packaged(tmp_path, payload, {})
    held, native = value["responses"]
    assert held["status"] == 422 and held["hold"] == "media_store_unavailable"
    assert native["schema_version"] == 4 and native["media_kind"] == "gist_pm25_forecast_v1"
    assert value["psycopg"] is False
    unconfigured = _packaged(tmp_path / "pg", [payload[0]], {gist_assets.ENV: "postgres"})
    assert unconfigured["responses"][0]["hold"] == "media_store_unavailable"
