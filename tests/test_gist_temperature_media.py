"""Invented retained station evidence; deterministic PNG and actual preview contract."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import fingerprint
from src.media import gist_temperature_media as media
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests.dashboard_graphic_helpers import saved_temperature_preview
from tests.ghcn_graphic_helpers import graphic_bundles


@pytest.fixture(scope="module")
def bundle():
    return story_bundle_snapshot(graphic_bundles()[-1])


@pytest.fixture(scope="module")
def prepared(bundle):
    return media.prepare_media(bundle)


@pytest.mark.parametrize("direction", ["high", "low"])
@pytest.mark.parametrize("tier", ["all_time", "monthly", "calendar"])
def test_six_real_adapter_variants_render_exact_values_and_qualified_scope(direction, tier):
    source = story_bundle_snapshot(graphic_bundles(direction=direction, tier=tier)[-1])
    original = deepcopy(source)
    result = media.prepare_media(source)
    assert source == original
    descriptor = result["descriptor"]
    assert descriptor["bundle_sha256"] == fingerprint(source)
    assert descriptor["png_sha256"] == sha256(result["png"]).hexdigest()
    assert descriptor["alt_sha256"] == sha256(descriptor["alt_text"].encode()).hexdigest()
    assert "GHCN" in descriptor["alt_text"] and "2026-09-08" in descriptor["alt_text"]
    assert "unknown" in descriptor["alt_text"] and "°C" in descriptor["alt_text"]
    image = Image.open(BytesIO(result["png"]))
    assert image.size == (1200, 1500) and image.mode == "RGB"
    assert len(image.getcolors(1200 * 1500)) > 5
    assert image.getpixel((600, 805)) == (
        (255, 134, 89) if direction == "high" else (101, 200, 255)
    )
    assert 0 < len(result["png"]) < 750_000
    assert len(json.dumps(descriptor).encode()) < 16_384


def test_repeated_render_and_sender_use_byte_identical_png_and_alt(bundle, prepared):
    assert media.prepare_media(bundle) == prepared
    draft = {
        "media_attachment": prepared["descriptor"],
        "review_context": {"two_bot": {"bundle": bundle}},
    }
    for day in (date(2026, 9, 8), date(2026, 9, 12)):
        assert media.media_for_draft(draft, today=day) == (
            prepared["png"],
            prepared["descriptor"]["alt_text"],
        )
    for day in (date(2026, 9, 7), date(2026, 9, 13)):
        with pytest.raises(ValueError, match="future or stale"):
            media.media_for_draft(draft, today=day)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "experimental"),
        ("schema_version", True),
        ("extra", "unknown"),
        ("bundle_sha256", "0" * 64),
        ("source_revision_sha256", "0" * 64),
        ("baseline_revision_sha256", "0" * 64),
        ("station_id", "USC99000002"),
        ("valid_date", "2026-09-07"),
        ("png_sha256", "not-a-digest"),
        ("alt_text", "Changed"),
        ("alt_text", "x" * 17_000),
    ],
    ids=[
        "kind",
        "schema",
        "extra",
        "bundle",
        "source",
        "baseline",
        "station",
        "date",
        "png",
        "alt",
        "oversize",
    ],
)
def test_descriptor_mutations_refuse(bundle, prepared, field, value):
    descriptor = deepcopy(prepared["descriptor"])
    descriptor[field] = value
    with pytest.raises(ValueError):
        media.validate_descriptor(descriptor, bundle)


@pytest.mark.parametrize(
    "key,value",
    [
        ("width", True),
        ("height", 10_000),
        ("pillow", "other"),
        ("font_sha256", "0" * 64),
        ("implementation_sha256", "0" * 64),
        ("freetype", "changed"),
        ("zlib", "changed"),
    ],
)
def test_current_renderer_profile_is_required(bundle, prepared, key, value):
    descriptor = deepcopy(prepared["descriptor"])
    descriptor["renderer"][key] = value
    with pytest.raises(ValueError):
        media.validate_descriptor(descriptor, bundle)


@pytest.mark.parametrize("key", ["png_sha256", "alt_text"])
def test_well_formed_rehashed_invented_recipe_never_selects_bytes(bundle, prepared, key):
    descriptor = deepcopy(prepared["descriptor"])
    descriptor[key] = "0" * 64 if key == "png_sha256" else "Altered but rehashed description"
    if key == "alt_text":
        descriptor["alt_sha256"] = sha256(descriptor[key].encode()).hexdigest()
    media.validate_descriptor(descriptor, bundle)
    draft = {"media_attachment": descriptor, "review_context": {"two_bot": {"bundle": bundle}}}
    with pytest.raises(ValueError, match="image, description or render profile changed"):
        media.media_for_draft(draft, today=date(2026, 9, 8))


def test_missing_font_and_changed_source_hold_without_fallback(bundle, prepared, monkeypatch):
    changed = deepcopy(bundle)
    changed["raw_signal_dump"]["evidence"]["valid_date"] = "2026-09-09"
    with pytest.raises(ValueError):
        media.validate_descriptor(prepared["descriptor"], changed)
    monkeypatch.setattr(media, "FONT", "fonts/missing.ttf")
    with pytest.raises(OSError):
        media.prepare_media(bundle)


def test_comparison_scope_is_visible_and_changes_image(bundle):
    # Full adapter inputs choose the actual scope; this test guards rendered label presence.
    all_time = media.prepare_media(bundle)
    monthly = media.prepare_media(story_bundle_snapshot(graphic_bundles(tier="monthly")[-1]))
    assert all_time["png"] != monthly["png"]


def test_actual_png_preview_passes_browser_and_server_contracts(tmp_path):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    state, request = saved_temperature_preview()
    request.update(
        format="png",
        expected_policy_source_sha256=manifest["identity"]["policy_source_sha256"],
        expected_preview_runtime_sha256=manifest["runtime_sha256"],
    )
    before = deepcopy(state)
    body = build_preview(
        request,
        policy_sha=request["expected_policy_source_sha256"],
        runtime_sha=request["expected_preview_runtime_sha256"],
        read_state=lambda: state,
        budget=Budget(),
    )
    assert state == before
    (tmp_path / "response.json").write_bytes(body)
    (tmp_path / "request.json").write_text(json.dumps(request))
    (tmp_path / "draft.json").write_text(json.dumps(state["drafts"][0]))
    code = """
import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
const [root,temp]=process.argv.slice(1), read=n=>JSON.parse(fs.readFileSync(n));
const value=read(temp+'/response.json'), req=read(temp+'/request.json'), draft=read(temp+'/draft.json');
const {validateGraphicResponse}=await import(pathToFileURL(root+'/dashboard/lib/graphic-preview.js'));
const {prepareGistTemperatureMedia}=await import(pathToFileURL(root+'/dashboard/lib/gist-temperature-media.js'));
const manifest=read(root+'/dashboard/lib/graphic-runtime-manifest.json');
await validateGraphicResponse(value,req,manifest);
const request=new Request('http://127.0.0.1:3137/api/drafts',{headers:{Host:'127.0.0.1:3137'}});
const descriptor=await prepareGistTemperatureMedia(request,draft,value.media_descriptor_sha256,
 async()=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}}));
if(JSON.stringify(descriptor)!==JSON.stringify(value.media_descriptor))throw new Error('descriptor changed');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code, str(root), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_png_preview_discards_source_change_during_render():
    state, request = saved_temperature_preview()
    request["format"] = "png"
    changed = deepcopy(state)
    changed["drafts"][0]["text"] += " Changed."
    reads = iter([state, changed])
    with pytest.raises(PreviewError) as error:
        build_preview(
            request,
            policy_sha=request["expected_policy_source_sha256"],
            runtime_sha=request["expected_preview_runtime_sha256"],
            read_state=lambda: next(reads),
            budget=Budget(),
        )
    assert error.value.code == "stale_preview"


def test_exact_runtime_zip_renders_same_image_without_checkout_resources(tmp_path, bundle, prepared):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "source.json").write_text(json.dumps(bundle))
    code = '''
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from src.media import gist_temperature_media as media
assert media.__file__.startswith(sys.argv[1])
result=media.prepare_media(json.loads(Path('source.json').read_text()))
Path('image.png').write_bytes(result['png'])
Path('descriptor.json').write_text(json.dumps(result['descriptor']))
'''
    result = subprocess.run([sys.executable, "-I", "-c", code, str(root / "dashboard/graphic-runtime.zip")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "image.png").read_bytes() == prepared["png"]
    assert json.loads((tmp_path / "descriptor.json").read_text()) == prepared["descriptor"]
