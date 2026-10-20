"""One continuous invented saved VIIRS draft through the actual preview, browser validator,
packaged runtime and native media package. Invented fixtures only; no source truth claim,
production state, network, paid call, attachment or publication authority."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from tests.dashboard_graphic_helpers import saved_viirs_preview

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
ADAPTER = ROOT / "src/media/viirs_map_graphic_adapter.py"
CONFIDENCE_ROW = "A high · B nominal · C low · D high"


def _manifest():
    return json.loads((ROOT / "dashboard/lib/graphic-runtime-manifest.json").read_text())


def _current_request():
    manifest = _manifest()
    state, request = saved_viirs_preview()
    policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
    request.update(expected_policy_source_sha256=policy, expected_preview_runtime_sha256=runtime)
    return state, request, policy, runtime


def _node_validate(tmp_path, response, request):
    (tmp_path / "response.json").write_text(json.dumps(response))
    (tmp_path / "request.json").write_text(json.dumps(request))
    code = '''
import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
const [root, temp] = process.argv.slice(1);
const {validateGraphicResponse} = await import(pathToFileURL(root + '/dashboard/lib/graphic-preview.js'));
const read = path => JSON.parse(fs.readFileSync(path));
await validateGraphicResponse(read(temp + '/response.json'), read(temp + '/request.json'),
 read(root + '/dashboard/lib/graphic-runtime-manifest.json'));
'''
    return subprocess.run(["node", "--input-type=module", "-e", code, str(ROOT), str(tmp_path)],
                          timeout=15, capture_output=True, text=True)


def test_continuous_saved_viirs_draft_preview_browser_and_packaged_runtime(tmp_path):
    state, request, policy, runtime = _current_request()
    before = deepcopy(state)
    reads = []

    def read():
        reads.append(True)
        return state

    body = build_preview(request, policy_sha=policy, runtime_sha=runtime, read_state=read,
                         budget=Budget(), synthetic=True)
    # Actual Python qualification and SVG rendering; state is read twice and never changed.
    assert state == before and len(reads) == 2
    result = json.loads(body)
    assert result["binding"]["template"] == "viirs_thermal_detection_map"
    assert result["binding"]["template_version"] == "p31-viirs-locator-1"
    assert result["source"] == "NASA FIRMS · VIIRS"
    assert result["source_context"] == {"kind": "viirs_acquisition", "acquired_at": "2032-02-29T23:59:00Z"}
    assert result["publication_approved"] is False and result["attachment"] is False
    assert result["revision_identity"] == request["expected_revision"]
    renderer = result["binding"]["renderer"]
    files = _manifest()["identity"]["files"]
    assert renderer["adapter_sha256"] == hashlib.sha256(ADAPTER.read_bytes()).hexdigest()
    assert renderer["adapter_sha256"] == files["src/media/viirs_map_graphic_adapter.py"]
    texts = ["".join(n.itertext()) for n in ET.fromstring(result["svg_utf8"]).findall(".//" + NS + "text")]
    for expected in ("SYNTHETIC DATA", "125.75 MW", "NASA FIRMS · NOAA-20 VIIRS", "2032-02-29 23:59 UTC",
                     "Source detection confidence", CONFIDENCE_ROW):
        assert expected in texts
    assert "SYNTHETIC DEMONSTRATION" in result["alt_text"] and "MODIS" not in result["alt_text"]

    # The real JavaScript validator accepts it and refuses tampering or template confusion.
    accepted = _node_validate(tmp_path, result, request)
    assert accepted.returncode == 0, accepted.stderr[-500:]
    for change in (lambda v: v.update(svg_utf8=v["svg_utf8"] + " "),
                   lambda v: v.update(source="NASA FIRMS · MODIS"),
                   lambda v: v["source_context"].update(kind="modis_acquisition"),
                   lambda v: v["binding"].update(template="modis_thermal_detection_map"),
                   lambda v: v["binding"]["renderer"].update(adapter_sha256=files["src/media/fire_map_graphic_adapter.py"])):
        bad = deepcopy(result)
        change(bad)
        assert _node_validate(tmp_path, bad, request).returncode != 0

    # The generated runtime archive reproduces the same bytes without checkout files.
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    archive = runtime_dir / "graphic-runtime.zip"
    shutil.copyfile(ROOT / "dashboard/graphic-runtime.zip", archive)
    (runtime_dir / "state.json").write_text(json.dumps(state))
    (runtime_dir / "request.json").write_text(json.dumps(request))
    script = '''
import json, socket, sys
sys.dont_write_bytecode = True
def deny(*a, **k): raise AssertionError("network is forbidden")
socket.socket.connect = deny
socket.getaddrinfo = deny
archive, folder, policy, runtime = sys.argv[1:5]
sys.path.insert(0, archive)
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
state = json.load(open(folder + "/state.json")); request = json.load(open(folder + "/request.json"))
body = build_preview(request, policy_sha=policy, runtime_sha=runtime, read_state=lambda: state,
                     budget=Budget(), synthetic=True)
print(json.dumps({"sha": __import__("hashlib").sha256(body).hexdigest(),
                  "sources": sorted({str(getattr(m, "__file__", "")) for n, m in sys.modules.items()
                                     if n == "src" or n.startswith("src.")})}))
'''
    packaged = subprocess.run([sys.executable, "-I", "-c", script, str(archive), str(runtime_dir), policy, runtime],
                              check=True, capture_output=True, text=True, cwd=runtime_dir, timeout=60)
    output = json.loads(packaged.stdout)
    assert output["sha"] == hashlib.sha256(body).hexdigest()
    assert output["sources"] and all(path.startswith(str(archive) + "/") for path in output["sources"])
    assert "src/media/viirs_map_graphic_adapter.py" in {p.removeprefix(str(archive) + "/") for p in output["sources"]}


@pytest.mark.parametrize("change,code", [("text", "stale_preview"), ("status", "stale_preview"),
                                         ("evidence", "stale_preview"), ("conflict", "conflicted_draft")])
def test_text_evidence_or_status_change_between_reads_discards_the_render(change, code):
    state, request, policy, runtime = _current_request()
    changed = deepcopy(state)
    draft = changed["drafts"][0]
    if change == "text":
        draft["text"] = "A different invented claim."
    elif change == "status":
        draft["status"] = "approved"
    elif change == "evidence":
        draft["review_context"]["two_bot"]["bundle"]["related_signals"][2]["where"] = "Different region"
    else:
        draft["revision_conflicts"] = ["conflict"]
    snapshot = deepcopy(state), deepcopy(changed)
    reads = iter([state, changed])
    with pytest.raises(PreviewError) as error:
        build_preview(request, policy_sha=policy, runtime_sha=runtime, read_state=lambda: next(reads),
                      budget=Budget(), synthetic=True)
    assert error.value.code == code
    assert (state, changed) == snapshot
