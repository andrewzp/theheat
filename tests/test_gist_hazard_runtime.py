"""The sealed graphic-runtime ZIP renders every new family exactly like the checkout.

A fresh isolated interpreter loads only the verified packaged deployment through
its real entry point, from an unrelated working directory, then runs the saved-
draft PNG preview. Bytes and descriptions must equal the checkout's own result.
"""
import base64
from copy import deepcopy
import hashlib
import json
import shutil
import subprocess
import sys

from freezegun import freeze_time
import pytest

from scripts.gen_dashboard_graphic_runtime import DEPLOYMENT_FILES, ROOT
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import decision_revision, draft_identity
from src.media import gist_hazard_media as hazard
from tests.gist_hazard_helpers import CLOCKS, saved_state

PACKAGED = r'''
import json, runpy, sys, socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
entry = runpy.run_path(sys.argv[1])
assert entry["PreviewHandler"] is not entry["UnavailableHandler"], "verified runtime refused"
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value = json.load(sys.stdin)
manifest = json.load(open(sys.argv[2]))
policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
out = []
for state, request in value:
    request.update(expected_policy_source_sha256=policy, expected_preview_runtime_sha256=runtime)
    out.append([json.loads(build_preview(request, policy_sha=policy, runtime_sha=runtime, read_state=lambda: state,
                                         budget=Budget())) for _ in range(2)])
sources = sorted({str(getattr(m, "__file__", "")) for k, m in sys.modules.items() if k == "src" or k.startswith("src.")})
print(json.dumps({"responses": out, "sources": sources}))
'''


def _request(state):
    draft = state["drafts"][0]
    return {"draft_id": draft["id"], "format": "png",
            "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)}}


@pytest.mark.parametrize("family", ["pm25", "modis", "viirs", "hot10"])
def test_packaged_runtime_renders_exact_bytes_and_descriptions_from_an_unrelated_directory(family, tmp_path):
    deploy = tmp_path / "deploy"
    for name in (*DEPLOYMENT_FILES, "graphic-runtime.zip", "lib/graphic-runtime-manifest.json"):
        target = deploy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "dashboard" / name, target)
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    state = saved_state(family)
    request = _request(state)
    manifest = json.loads((ROOT / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
    with freeze_time(CLOCKS[family][0]):
        local = json.loads(build_preview({**request, "expected_policy_source_sha256": policy,
                                          "expected_preview_runtime_sha256": runtime},
                                         policy_sha=policy, runtime_sha=runtime, read_state=lambda: deepcopy(state),
                                         budget=Budget()))
    result = subprocess.run([sys.executable, "-I", "-c", PACKAGED, str(deploy / "api/graphic_preview.py"),
                             str(deploy / "lib/graphic-runtime-manifest.json")],
                            input=json.dumps([[state, request]]), capture_output=True, text=True, timeout=120,
                            cwd=elsewhere, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": str(elsewhere)})
    assert result.returncode == 0, result.stderr[-3000:]
    payload = json.loads(result.stdout)
    assert payload["sources"] and all(name.startswith(str(deploy / "graphic-runtime.zip") + "/") for name in payload["sources"])
    first, second = payload["responses"][0]
    for response in (first, second):
        assert response["schema_version"] == 4 and response["media_kind"] == local["media_kind"]
        # The posting disclosure uses each process's own clock; everything bound is identical.
        for key in ("png_base64", "png_sha256", "media_descriptor", "media_descriptor_sha256", "delivery_text",
                    "expanded_description", "title", "scope", "source", "source_context"):
            assert response[key] == local[key], key
    png = base64.b64decode(first["png_base64"])
    assert hashlib.sha256(png).hexdigest() == local["media_descriptor"]["image"]["png_sha256"]
    descriptor = first["media_descriptor"]
    assert descriptor["renderer"]["files"] == {path: manifest["identity"]["files"][path] for path in hazard.FAMILIES[descriptor["kind"]]["files"]}
