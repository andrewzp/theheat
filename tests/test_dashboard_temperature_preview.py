"""Existing GHCN warrants reach the read-only preview; invented archives only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import xml.etree.ElementTree as ET

import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import qualified_spec
from src.editorial.revisions import draft_identity
from tests.dashboard_graphic_helpers import saved_temperature_preview
from tests.test_dashboard_graphic_preview import preview

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("No source/provider request belongs in a saved preview")
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(scope="module")
def retained():
    return saved_temperature_preview()


@pytest.mark.parametrize("direction", ["high", "low"])
@pytest.mark.parametrize("tier", ["all_time", "monthly", "calendar"])
def test_qualified_station_comparator_crosses_real_python_js_and_component(tmp_path, direction, tier):
    state, request = saved_temperature_preview(direction=direction, tier=tier)
    before = deepcopy(state)
    manifest = json.loads((ROOT / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
    request.update(expected_policy_source_sha256=policy, expected_preview_runtime_sha256=runtime)
    result = json.loads(preview(state, request, policy_sha=policy, runtime_sha=runtime))
    assert state == before
    assert result["publication_approved"] is False and result["attachment"] is False
    assert result["binding"]["template"] == "temperature_comparator"
    assert result["source_context"] == dict(kind="ghcn_station_day", station_id="USC99000001",
        valid_date="2026-09-08", retrieved_at="2026-09-09T12:00:00Z",
        reporting_interval_known=False, timezone=None)
    assert "source_time" not in result
    assert result["svg_sha256"] == hashlib.sha256(result["svg_utf8"].encode()).hexdigest()
    texts = " ".join("".join(n.itertext()) for n in ET.fromstring(result["svg_utf8"]).iter("{http://www.w3.org/2000/svg}text"))
    assert "SYNTHETIC" in texts
    assert "no official record" in texts.lower()
    assert "SYNTHETIC DEMONSTRATION" in result["alt_text"]
    assert "reporting interval and timezone are unknown" in result["alt_text"]
    assert "no implied UTC observation time" in result["alt_text"]
    (tmp_path / "response.json").write_text(json.dumps(result))
    (tmp_path / "request.json").write_text(json.dumps(request))
    code = '''
import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
const [root,temp] = process.argv.slice(1);
const read = path => JSON.parse(fs.readFileSync(path));
const {validateGraphicResponse} = await import(pathToFileURL(root+'/dashboard/lib/graphic-preview.js'));
const response = await validateGraphicResponse(read(temp+'/response.json'),read(temp+'/request.json'),
 read(root+'/dashboard/lib/graphic-runtime-manifest.json'));
const {default:React} = await import(pathToFileURL(root+'/dashboard/node_modules/react/index.js'));
const {renderToStaticMarkup} = await import(pathToFileURL(root+'/dashboard/node_modules/react-dom/server.node.js'));
const {GraphicPreviewFigure} = await import(pathToFileURL(root+'/dashboard/app/components/GraphicPreview.js'));
const html=renderToStaticMarkup(React.createElement(GraphicPreviewFigure,{value:response,url:'blob:invented'}));
for (const text of ['USC99000001','2026-09-08 source-calendar date','observed; reporting interval and timezone unknown',
 'Archive retrieved 2026-09-09T12:00:00Z','not a certified record','Read the full graphic description'])
 if(!html.includes(text))throw new Error('Missing station qualifier: '+text);
if(html.includes('2026-09-08 00:00') || html.includes('model forecast'))throw new Error('Invented valid interval or type');
'''
    subprocess.run(["node", "--input-type=module", "-e", code, str(ROOT), str(tmp_path)],
                   check=True, timeout=15, capture_output=True, text=True)


@pytest.mark.parametrize("change", ["product", "forecast", "station", "date", "unit", "qflag", "interval", "cutoff", "headline"])
def test_unqualified_station_source_does_not_reach_renderer(retained, monkeypatch, change):
    state, request = deepcopy(retained)
    draft = state["drafts"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    evidence = bundle["raw_signal_dump"]["evidence"]
    if change == "product":
        evidence["source_product"] = "unqualified-archive"
    elif change == "forecast":
        evidence["evidence_type"] = "forecast"
    elif change == "station":
        evidence["station_id"] = "USC99000002"
    elif change == "date":
        evidence["valid_date"] = "2026-09-09"
    elif change == "unit":
        evidence["unit"] = "F"
    elif change == "qflag":
        evidence["variables"]["TMAX"]["qflag"] = "S"
    elif change == "interval":
        evidence["reporting_interval_known"] = True
    elif change == "cutoff":
        evidence["baseline"]["requested_comparison_cutoff"] = "2026-09-08"
    else:
        bundle["headline_metric"]["value"] += 1
    request["expected_revision"].update(draft_identity(draft))
    before = deepcopy(state)
    monkeypatch.setattr("src.dashboard_preview.preview.render_svg", lambda **_: pytest.fail("Unqualified render"))
    with pytest.raises(PreviewError) as error:
        preview(state, request)
    assert error.value.code == "graphic_unavailable"
    assert state == before


@pytest.mark.parametrize("change", ["text", "source", "approval", "status"])
def test_temperature_two_read_fence_discards_changed_source_or_draft(retained, change):
    state, request = deepcopy(retained)
    changed = deepcopy(state)
    draft = changed["drafts"][0]
    if change == "source":
        draft["review_context"]["two_bot"]["bundle"]["headline_metric"]["value"] += 1
    elif change == "text":
        draft["text"] = "Changed after rendering began."
    elif change == "approval":
        draft["decision_revision"] = 1
    else:
        draft["status"] = "posted"
    reads = iter([state, changed])
    with pytest.raises(PreviewError) as error:
        preview(state, request, read_state=lambda: next(reads))
    assert error.value.code in {"stale_preview", "draft_unavailable"}


def test_temperature_requires_its_own_explicit_opt_in(retained):
    state, _ = retained
    with pytest.raises(PreviewError) as error:
        qualified_spec(state["drafts"][0]["review_context"]["two_bot"]["bundle"], synthetic=True, include_viirs=True)
    assert error.value.code == "graphic_unavailable"
