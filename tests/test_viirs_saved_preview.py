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
from src.dashboard_preview.preview import build_preview, qualified_spec
from src.dashboard_preview.reader import Budget
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text
from src.media.evidence_graphic_render import render_preview
from src.media.review_packet import build_media_review_packet, media_review_packet_is_current
from tests.dashboard_graphic_helpers import saved_viirs_preview
from tests.test_joint_media_review import make, status

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


def _draft(bundle):
    return {"id": "invented-viirs-media", "event_id": bundle["event_id"], "type": "fire",
            "text": "Invented VIIRS thermal detections for a native package test.",
            "content_revision": 1, "decision_revision": 1, "status": "pending",
            "review_context": {"two_bot": {"bundle": bundle}}}


def test_actual_native_viirs_png_package_binds_the_new_template_and_refuses_altered_content(tmp_path):
    pdftoppm = shutil.which("pdftoppm")
    assert pdftoppm, "The native package test requires the locked profile's pdftoppm; a skip is not a pass"
    state, _ = saved_viirs_preview()
    bundle = state["drafts"][0]["review_context"]["two_bot"]["bundle"]
    spec, _, _ = qualified_spec(deepcopy(bundle), synthetic=True, include_viirs=True)
    manifest_path = render_preview(**spec, output_dir=tmp_path / "media", pdftoppm=pdftoppm)
    manifest = json.loads(manifest_path.read_text())
    folder = manifest_path.parent
    png = (folder / "preview.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    binding = manifest["binding"]
    assert (binding["template"], binding["template_version"]) == ("viirs_thermal_detection_map", "p31-viirs-locator-1")
    media = ROOT / "src/media"
    for key, name in (("adapter_sha256", "viirs_map_graphic_adapter.py"),
                      ("implementation_sha256", "evidence_graphic_render.py"),
                      ("contract_sha256", "evidence_graphic.py")):
        assert binding["renderer"][key] == hashlib.sha256((media / name).read_bytes()).hexdigest()
    assert set(manifest["files"]) == {"input.json", "preview.svg", "preview.pdf", "preview.png", "alt.txt"}
    assert manifest["publication_approved"] is False and manifest["synthetic"] is True
    svg_texts = ["".join(n.itertext()) for n in ET.parse(folder / "preview.svg").getroot().iter(NS + "text")]
    assert CONFIDENCE_ROW in svg_texts and "NASA FIRMS · NOAA-20 VIIRS" in svg_texts
    # Identical inputs reuse the immutable package; a changed cached asset is refused, never overwritten.
    assert render_preview(**spec, output_dir=tmp_path / "media", pdftoppm=pdftoppm) == manifest_path

    draft = _draft(bundle)
    inputs = dict(draft=draft, expected_draft_identity=draft_identity(draft),
                  editorial_policy=current_editorial_policy(), graphic_spec=spec,
                  renderer_manifest=manifest, png_bytes=png)
    packet = build_media_review_packet(**inputs)
    assert packet["graphic_binding"]["template"] == "viirs_thermal_detection_map"
    assert packet["graphic_binding"]["template_version"] == "p31-viirs-locator-1"
    assert (packet["media"]["width"], packet["media"]["height"], packet["media"]["png_sha256"]) == (
        1200, 1500, hashlib.sha256(png).hexdigest())
    assert packet["publication_approved"] is False and packet["claim_agreement_status"] == "unreviewed"
    current = {k: v for k, v in inputs.items() if k != "draft"}
    assert media_review_packet_is_current(packet, draft, **current)
    record = make(inputs)
    assert status(record, inputs)["accepted"]

    for change in ("png", "text", "receipt", "template", "bundle"):
        altered = deepcopy(inputs)
        if change == "png":
            altered["png_bytes"] = png + b"changed"
        elif change == "text":
            invalidate_text(altered["draft"], "A different invented claim.")
            altered["expected_draft_identity"] = draft_identity(altered["draft"])
        elif change == "receipt":
            e = altered["graphic_spec"]["evidence"]
            e["input_binding"]["selected_receipt_sha256"][1] = "b" * 64
            altered["graphic_spec"]["expected_evidence_sha256"] = fingerprint(e)
        elif change == "template":
            altered["renderer_manifest"]["binding"]["template_version"] = "p31-modis-locator-2-social"
        else:
            altered["draft"]["review_context"]["two_bot"]["bundle"]["where"] = "Different City"
        assert not media_review_packet_is_current(packet, altered["draft"],
                                                  **{k: v for k, v in altered.items() if k != "draft"})
        assert not status(record, altered)["accepted"]

    (folder / "preview.png").write_bytes(png + b"tampered")
    with pytest.raises(ValueError, match="Cached preview content changed"):
        render_preview(**spec, output_dir=tmp_path / "media", pdftoppm=pdftoppm)
