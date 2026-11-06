"""Invented NWPS acquisition through checked saved draft and retained SVG preview."""
from copy import deepcopy
import base64
from io import BytesIO
import json
from pathlib import Path
import subprocess

import pytest
from PIL import Image

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.data import nwps_major_forecasts as nwps
from src.editorial.revisions import decision_revision, draft_identity, fingerprint
from src.media import gist_assets, gist_media_export, nwps_capture
from tests.test_nwps_major_forecasts import NOW, journey, run_collector, source  # noqa: F401

POLICY, RUNTIME = "a" * 64, "b" * 64
ORIGINAL_FETCH = nwps.fetch_major_forecasts
ORIGINAL_GAUGE_READ = nwps.read_gauge_forecast
ORIGINAL_WRITER = gist_assets.configured_writer


@pytest.fixture
def saved_capture(monkeypatch, tmp_path, journey):  # noqa: F811 - imported pytest fixture
    row, metadata, forecast = source()
    url = nwps.GAUGES_URL + "/" + row["gaugelid"]
    documents = {nwps.INDEX_URL: {"features": [{"attributes": row}]},
                 url: metadata, url + "/stageflow/forecast": forecast}
    reads = []

    def read(url, **_):
        reads.append(url)
        return documents[url]

    # Exercise the real bounded acquisition using only invented response documents.
    monkeypatch.setattr(nwps, "fetch_major_forecasts", lambda now, **kw: ORIGINAL_FETCH(now, read_json=read, **kw))
    def gauge_read(hint, **kwargs):
        if "read_json" in kwargs:
            return ORIGINAL_GAUGE_READ(hint, **kwargs)
        return journey[1](hint)
    monkeypatch.setattr(nwps, "read_gauge_forecast", gauge_read)
    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    monkeypatch.setenv(nwps_capture.ENV, "1")
    store = gist_assets.SQLiteMediaStore(tmp_path / "media.sqlite3")
    monkeypatch.setattr(gist_assets, "configured_writer", lambda: store)
    state = run_collector()
    draft, = state["drafts"]
    assert reads == [nwps.INDEX_URL, url, url + "/stageflow/forecast"]
    assert journey[2] == ["writer", "safety", "fact_check", "critic"]
    assert draft["approval_policy"]["mode"] == "manual_only"
    request = {"draft_id": draft["id"],
               "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
               "expected_policy_source_sha256": POLICY, "expected_preview_runtime_sha256": RUNTIME}
    return state, request, store, documents


def preview(state, request, store, **kwargs):
    return build_preview(request, policy_sha=POLICY, runtime_sha=RUNTIME,
                         read_state=lambda: state, budget=Budget(), store=store, **kwargs)


def test_acquired_capture_stays_outside_the_writer_bundle_and_survives_restore(saved_capture, tmp_path):
    state, request, store, documents = saved_capture
    draft = state["drafts"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    reference = draft["review_context"][nwps_capture.CONTEXT_KEY]
    assert len(json.dumps(reference)) < 400
    assert "nwps_point_capture" not in bundle and "forecast" not in bundle["raw_signal_dump"]
    capture = nwps_capture.load(bundle, reference, store)
    assert capture["forecast"] == documents[nwps.GAUGES_URL + "/FAKF1/stageflow/forecast"]
    assert reference["bundle_sha256"] == fingerprint(bundle)
    assert reference["capture_sha256"] == fingerprint(capture)
    before = deepcopy(state)
    body = preview(state, request, store)
    plan = gist_media_export.plan(store, state)
    assert plan["present"] == 1 and plan["held"] == 0
    assert plan["export_batches"] == [["--nwps-capture", reference["artifact_sha256"]]]
    assert plan["items"][0]["drafts"][0]["reasons"] == ["retained_source"]
    target = tmp_path / "export"
    gist_media_export.export(store, [("nwps_capture", reference["artifact_sha256"])], target)
    restored_store = gist_assets.SQLiteMediaStore(tmp_path / "restored.sqlite3")
    result = gist_media_export.restore(restored_store, target)
    assert result == {"restored_items": 1, "restored_blobs": 1, "verified": True}
    reader = gist_assets.SQLiteMediaStore(restored_store.path, writable=False)
    assert preview(json.loads(json.dumps(state)), request, reader) == body
    png_request = {**request, "format": "river_png"}
    png = preview(state, png_request, reader)
    assert preview(json.loads(json.dumps(state)), png_request, store) == png
    assert state == before
    value = json.loads(body)
    raster = json.loads(png)
    assert raster["schema_version"] == 7 and raster["attachment"] is raster["publication_approved"] is False
    assert "media_descriptor" not in raster
    assert raster["source_context"] == value["source_context"] and raster["alt_text"] == value["alt_text"]
    assert raster["binding"]["source_evidence_sha256"] == value["binding"]["source_evidence_sha256"]
    with Image.open(BytesIO(base64.b64decode(raster["png_base64"]))) as image:
        image.load()
        assert (image.format, image.size, image.mode) == ("PNG", (1200, 1500), "RGB")
    assert value["source_context"] == {
        "kind": "nwps_forecast_points", "gauge": "FAKF1", "unit": "ft",
        "issued_at": "2026-07-01T14:00:00+00:00", "first_major_at": "2026-07-02T18:00:00+00:00",
        "checked_at": NOW.isoformat(), "point_count": 3}
    assert "3 forecast points" in value["alt_text"]
    assert "Crossing time is uncertain" in value["alt_text"]
    assert "Source checked 2026-07-01 16:00:00 UTC" in value["alt_text"]
    assert "Source checked 2026-07-01 16:00:00 UTC" in value["svg_utf8"]
    assert "currentness requires a new source check" in value["alt_text"]
    assert value["publication_approved"] is False and value["attachment"] is False
    assert "raw_signal_dump" not in value and "capture" not in value
    assert "Major threshold: 17.0 ft" in value["svg_utf8"]


@pytest.mark.parametrize("change", ["text", "capture_reference", "bundle", "draft_switch"])
@pytest.mark.parametrize("format", [None, "river_png"])
def test_change_during_render_never_returns_the_old_preview(saved_capture, change, format):
    state, request, store, _ = saved_capture
    if format:
        request["format"] = format
    changed = deepcopy(state)
    draft = changed["drafts"][0]
    if change == "text":
        draft["text"] += " Changed."
    elif change == "capture_reference":
        draft["review_context"][nwps_capture.CONTEXT_KEY]["artifact_sha256"] = "e" * 64
    elif change == "bundle":
        draft["review_context"]["two_bot"]["bundle"]["where"] = "Changed river"
    else:
        draft["id"] = "different-draft"
    reads = iter([state, changed])
    with pytest.raises(PreviewError) as error:
        build_preview(request, policy_sha=POLICY, runtime_sha=RUNTIME,
                      read_state=lambda: next(reads), budget=Budget(), store=store)
    assert error.value.code in {"stale_preview", "draft_unavailable"}


@pytest.mark.parametrize("change", ["missing", "wrong_bundle", "boolean_schema", "wrong_hash"])
def test_invalid_reference_is_refused_before_loading_a_store(saved_capture, monkeypatch, change):
    state, request, _, _ = saved_capture
    draft = state["drafts"][0]
    ref = draft["review_context"][nwps_capture.CONTEXT_KEY]
    if change == "missing":
        del draft["review_context"][nwps_capture.CONTEXT_KEY]
    elif change == "wrong_bundle":
        ref["bundle_sha256"] = "c" * 64
    elif change == "boolean_schema":
        ref["schema_version"] = True
    else:
        ref["artifact_sha256"] = "a/path"
    request["expected_revision"].update(draft_identity(draft))
    monkeypatch.setattr(gist_assets, "configured", lambda: pytest.fail("invalid reference read a store"))
    with pytest.raises(PreviewError) as error:
        preview(state, request, None)
    assert error.value.code == "media_hold"


def test_source_disagreement_is_refused_even_with_a_new_packet_identity(saved_capture, tmp_path):
    state, request, store, _ = saved_capture
    draft = state["drafts"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    ref = draft["review_context"][nwps_capture.CONTEXT_KEY]
    packet = gist_assets.get_document(store, ref["artifact_sha256"])
    packet["capture"]["forecast"]["primaryUnits"] = "m"
    ref["artifact_sha256"] = gist_assets.put_document(store, packet)
    ref["capture_sha256"] = fingerprint(packet["capture"])
    request["expected_revision"].update(draft_identity(draft))
    with pytest.raises(gist_assets.MediaStoreError):
        nwps_capture.load(bundle, ref, store)
    with pytest.raises(PreviewError) as error:
        preview(state, request, store)
    assert error.value.code == "media_hold"
    target = tmp_path / "invalid-export"
    with pytest.raises(gist_media_export.ExportError):
        gist_media_export.export(store, [("nwps_capture", ref["artifact_sha256"])], target)
    assert not target.exists()


def test_png_has_no_unreviewed_attachment_route(saved_capture, monkeypatch):
    state, request, store, _ = saved_capture
    monkeypatch.setattr(store, "get", lambda *a, **kw: pytest.fail("PNG read the source packet"))
    with pytest.raises(PreviewError) as error:
        preview(state, {**request, "format": "png"}, store)
    assert error.value.code == "graphic_unavailable"


@pytest.mark.parametrize("format", [None, "river_png"])
def test_real_python_response_passes_browser_contract(saved_capture, tmp_path, format):
    state, request, store, _ = saved_capture
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "dashboard/lib/graphic-runtime-manifest.json").read_text())
    policy, runtime = manifest["identity"]["policy_source_sha256"], manifest["runtime_sha256"]
    request.update(expected_policy_source_sha256=policy, expected_preview_runtime_sha256=runtime)
    if format:
        request["format"] = format
    body = build_preview(request, policy_sha=policy, runtime_sha=runtime,
                         read_state=lambda: state, budget=Budget(), store=store)
    (tmp_path / "response.json").write_bytes(body)
    (tmp_path / "request.json").write_text(json.dumps(request))
    code = """
import fs from 'node:fs'; import assert from 'node:assert/strict'; import {pathToFileURL} from 'node:url';
const [root,temp]=process.argv.slice(1);
const {createGraphicPreviewController,validateGraphicResponse}=await import(pathToFileURL(root+'/dashboard/lib/graphic-preview.js'));
const read=name=>JSON.parse(fs.readFileSync(name));
const value=read(temp+'/response.json'), request=read(temp+'/request.json'), manifest=read(root+'/dashboard/lib/graphic-runtime-manifest.json');
await validateGraphicResponse(value,request,manifest);
if (request.format === 'river_png') {
    for (const change of [
        v => { v.source_context.point_count++; },
        v => { v.alt_text += 'changed'; },
        v => { v.binding.renderer_sha256 = '0'.repeat(64); },
        v => { v.png_base64 = v.png_base64.slice(0, -4); },
        v => { v.attachment = true; },
    ]) {
        const changed=structuredClone(value);
        change(changed);
        await assert.rejects(validateGraphicResponse(changed,request,manifest));
    }
    await assert.rejects(validateGraphicResponse(value,{...request, format:'png'},manifest));
    let url, rendered, revoked;
    const controller = createGraphicPreviewController({manifest, onChange: state => { rendered = state; },
      fetcher: async () => new Response(JSON.stringify(value), {headers: {'Content-Type': 'application/json'}}),
      createURL: blob => { assert.equal(blob.type, 'image/png'); return url = 'blob:local'; },
      revokeURL: value => { revoked = value; }});
    await controller.start(request);
    assert.equal(rendered.status, 'ready');
    assert.equal(rendered.url, url);
    controller.dispose();
    assert.equal(revoked, url);
}
"""
    completed = subprocess.run(["node", "--input-type=module", "-e", code, str(root), str(tmp_path)],
                               timeout=15, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("outcome", ["off", "unavailable_capture"])
def test_retention_failure_preserves_the_normal_checked_text_path(journey, monkeypatch, outcome):  # noqa: F811
    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    if outcome == "off":
        monkeypatch.delenv(nwps_capture.ENV, raising=False)
        monkeypatch.setattr(gist_assets, "configured_writer", lambda: pytest.fail("disabled retention opened a writer"))
    else:
        monkeypatch.setenv(nwps_capture.ENV, "1")
        monkeypatch.setattr(gist_assets, "configured_writer", lambda: None)
    state = run_collector()
    draft, = state["drafts"]
    assert nwps_capture.CONTEXT_KEY not in draft["review_context"]
    assert journey[2] == ["writer", "safety", "fact_check", "critic"]
    assert draft["approval_policy"]["mode"] == "manual_only"
    if outcome == "off":
        journey[0].assert_called_once_with(NOW)


@pytest.mark.parametrize("failure", ["unknown_write", "write_error", "missing_store"])
def test_qualified_retention_failure_returns_no_reference(saved_capture, monkeypatch, failure):
    state, _, store, _ = saved_capture
    draft = state["drafts"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    capture = nwps_capture.load(bundle, draft["review_context"][nwps_capture.CONTEXT_KEY], store)
    if failure == "unknown_write":
        monkeypatch.setattr(store, "put_many", lambda *a: ["f" * 64])
    elif failure == "write_error":
        def refuse(*args):
            raise gist_assets.MediaStoreError("media_retention_unknown", "invented incomplete write")
        monkeypatch.setattr(store, "put_many", refuse)
    else:
        store = None
    before = deepcopy(bundle)
    reference, code = nwps_capture.retain(bundle, capture, store)
    assert reference is None
    assert code == ("store_unavailable" if failure == "missing_store" else "retention_unknown")
    assert bundle == before


def test_writer_configuration_failure_preserves_the_checked_text(saved_capture, journey, monkeypatch):  # noqa: F811
    def fail():
        raise RuntimeError("invented media writer setup failure")
    monkeypatch.setattr(gist_assets, "configured_writer", fail)
    journey[2].clear()
    draft, = run_collector()["drafts"]
    assert nwps_capture.CONTEXT_KEY not in draft["review_context"]
    assert journey[2] == ["writer", "safety", "fact_check", "critic"]
    assert draft["approval_policy"]["mode"] == "manual_only"


def test_capture_roundtrip_through_the_operator_command(saved_capture, tmp_path, capsys, monkeypatch):
    from scripts import retain_gist_media as command
    state, request, store, _ = saved_capture
    monkeypatch.setattr(gist_assets, "configured_writer", ORIGINAL_WRITER)
    key = state["drafts"][0]["review_context"][nwps_capture.CONTEXT_KEY]["artifact_sha256"]
    code = command.main(["--store", f"sqlite:{store.path}", "readback", "--nwps-capture", key], environ={})
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["items"][0]["kind"] == "nwps_capture" and result["items"][0]["verified"]
    target = tmp_path / "command-export"
    code = command.main(["--store", f"sqlite:{store.path}", "export", "--nwps-capture", key,
                         "--target", str(target)], environ={})
    assert code == 0
    capsys.readouterr()
    restored = tmp_path / "command-restored.sqlite3"
    code = command.main(["--store", f"sqlite:{restored}", "restore", "--source", str(target)], environ={})
    assert code == 0
    capsys.readouterr()
    reader = gist_assets.SQLiteMediaStore(restored, writable=False)
    assert preview(state, request, reader) == preview(state, request, store)
