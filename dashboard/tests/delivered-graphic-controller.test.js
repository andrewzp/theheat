/** Detached invented retained bytes only: actual response validator and controller. */
import assert from "node:assert/strict"
import test from "node:test"
import { createHash } from "node:crypto"
import { deflateSync } from "node:zlib"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { fingerprint } from "../lib/draft-revisions.js"
import { createGraphicPreviewController, typedFingerprint, validateGraphicResponse } from "../lib/graphic-preview.js"

const hash = value => createHash("sha256").update(value).digest("hex")
const paths = ["src/media/gist_media.py", "src/media/gist_published_media.py", "src/media/canonical_png.py",
  "src/media/gist_assets.py", "src/media/published_radar.py", "src/media/gist_temperature_media.py", "src/media/fonts/DejaVuSansMono.ttf"]
const files = Object.fromEntries(paths.map(path => [path, hash(`invented pin ${path}`)]))
const manifest = { identity: { files } }
const request = { draft_id: "invented-delivered", format: "png", delivered: true,
  expected_revision: { content_revision: 3, decision_revision: 0, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) },
  expected_policy_source_sha256: "c".repeat(64), expected_preview_runtime_sha256: "d".repeat(64) }
const receipt = { tweet_id: "invented-receipt", text: "Invented originally delivered text.", content_revision: 1,
  confirmed_at: "2026-10-28T12:00:00Z" }

function chunk(type, body) {
  const bytes = Buffer.concat([Buffer.from(type), body])
  let crc = 0xffffffff
  for (const byte of bytes) {
    crc ^= byte
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
  }
  const start = Buffer.alloc(4), end = Buffer.alloc(4)
  start.writeUInt32BE(body.length); end.writeUInt32BE((crc ^ 0xffffffff) >>> 0)
  return Buffer.concat([start, bytes, end])
}
function png(width, height) {
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.alloc((width * 3 + 1) * height))), chunk("IEND", Buffer.alloc(0))])
}
function common() {
  return { schema_version: 6, draft_id: request.draft_id, revision_identity: structuredClone(request.expected_revision),
    policy_source_sha256: request.expected_policy_source_sha256, preview_runtime_sha256: request.expected_preview_runtime_sha256,
    title: "Invented retained figure", scope: "Invented inspection fixture", publication_approved: false, attachment: false,
    delivered: structuredClone(receipt) }
}
async function published(product) {
  const cone = product === "nhc_track_cone_v1", width = cone ? 897 : 600, height = cone ? 736 : 550
  const derivative = png(width, height), original = png(width, height)
  const kind = cone ? "gist_published_chart_v1" : "gist_published_radar_v1"
  const attestations = cone ? ["chart_labels_match", "storm_and_advisory_match", "unaltered_product_reuse_conditions_met"]
    : ["named_point_context_matches", "raster_labels_match", "unaltered_product_reuse_conditions_met"]
  const alt = "Invented retained published image.", full = "Invented expanded retained description."
  const descriptor = { schema_version: 1, kind, product, synthetic: false,
    asset: { manifest_sha256: "e".repeat(64), original_sha256: hash(original), original_bytes: original.length,
      original_mime: "image/png", derivative_sha256: hash(derivative), derivative_bytes: derivative.length, width, height },
    source: { fixture: "invented retained source" },
    converter: { version: "gist-published-png-1", method: "decode_rgba_canonical_png_v1", png_codec: "canonical-png-fixed-huffman-1",
      pillow: "12.2.0", files: Object.fromEntries(paths.slice(0, 5).map(path => [path, files[path]])) },
    attestations: { version: 1, required: attestations },
    description: { derivation: cone ? "nhc_cone_delivery_v1" : "ktlx_radar_delivery_v1", delivery_text: alt,
      delivery_sha256: hash(alt), delivery_scalars: [...alt].length, delivery_bytes: Buffer.byteLength(alt),
      full_sha256: hash(full), full_bytes: Buffer.byteLength(full) } }
  return { ...common(), media_kind: kind, media_descriptor: descriptor, media_descriptor_sha256: await typedFingerprint(descriptor),
    png_base64: derivative.toString("base64"), png_sha256: hash(derivative), delivery_text: alt, expanded_description: full,
    original_base64: original.toString("base64"), original_sha256: hash(original), original_mime: "image/png", width, height,
    inspection: { product, label: "Invented product", source_url: "https://example.invalid/source", retrieved_at: receipt.confirmed_at,
      attribution: "Invented attribution", reuse_url: "https://example.invalid/reuse", product_reference_url: "https://example.invalid/reference",
      time_literal: "Invented source time", quantity: "Invented quantity", context: "Invented context", legend: ["Invented legend"],
      required_attestations: attestations.map(name => ({ name, text: "Invented attestation" })) } }
}
function temperature() {
  const bytes = png(1200, 1500), alt = "Invented station comparison; reporting interval and timezone unknown."
  const descriptor = { schema_version: 2, kind: "gist_temperature_comparator_v1", bundle_sha256: "e".repeat(64),
    source_revision_sha256: "f".repeat(64), baseline_revision_sha256: "a".repeat(64), station_id: "USC99000001", valid_date: "2026-10-28",
    renderer: { implementation_sha256: files[paths[5]], font_sha256: files[paths[6]], codec_sha256: files[paths[2]],
      png_codec: "canonical-png-fixed-huffman-1", pillow: "fixture", freetype: "fixture", width: 1200, height: 1500 },
    png_sha256: hash(bytes), alt_text: alt, alt_sha256: hash(alt) }
  return { ...common(), media_kind: descriptor.kind, media_descriptor: descriptor, media_descriptor_sha256: fingerprint(descriptor),
    png_base64: bytes.toString("base64"), png_sha256: hash(bytes), delivery_text: alt, expanded_description: alt,
    width: 1200, height: 1500, source: "NOAA GHCN-Daily · station observations",
    source_context: { kind: "ghcn_station_day", station_id: descriptor.station_id, valid_date: descriptor.valid_date,
      retrieved_at: receipt.confirmed_at, reporting_interval_known: false, timezone: null } }
}
async function consume(value, req = request) {
  const states = [], blobs = [], revoked = []
  const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
    fetcher: async (_url, options) => {
      assert.deepEqual(JSON.parse(options.body), req)
      return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
    }, createURL: blob => { blobs.push(blob); return `blob:invented-${blobs.length}` }, revokeURL: url => revoked.push(url) })
  await controller.start(req)
  controller.dispose(); controller.dispose()
  return { state: states.at(-1), blobs, revoked }
}

for (const product of ["nws_local_standard_radar_v1", "nhc_track_cone_v1"]) {
  test(`delivered ${product}: actual controller retains product dimensions and original bytes`, async () => {
    const value = await published(product)
    assert.equal(await validateGraphicResponse(value, request, manifest), value)
    const { state, blobs, revoked } = await consume(value)
    assert.equal(state.status, "ready")
    assert.equal(state.originalURL, "blob:invented-2")
    assert.deepEqual(blobs.map(blob => blob.type), ["image/png", "image/png"])
    assert.deepEqual(Buffer.from(await blobs[0].arrayBuffer()), Buffer.from(value.png_base64, "base64"))
    assert.deepEqual(Buffer.from(await blobs[1].arrayBuffer()), Buffer.from(value.original_base64, "base64"))
    assert.deepEqual(revoked, ["blob:invented-1", "blob:invented-2"])
    assert.deepEqual(state.value.delivered, receipt)
  })
}

test("ordinary published preview keeps its original/derivative behavior", async () => {
  const value = await published("nhc_track_cone_v1"), req = { ...request, retained_input_sha256: value.media_descriptor.asset.manifest_sha256 }
  delete req.delivered; delete value.delivered
  value.schema_version = 5; value.posting_window = { status: "current", code: null, reason: null, checked_at: receipt.confirmed_at }
  const { state, blobs } = await consume(value, req)
  assert.equal(state.status, "ready"); assert.equal(blobs.length, 2)
})

test("delivered native temperature reaches the controller with exact PNG, alt and historical receipt", async () => {
  const value = temperature(), before = structuredClone(value)
  const { state, blobs, revoked } = await consume(value)
  assert.equal(state.status, "ready")
  assert.equal(state.originalURL, null)
  assert.equal(blobs.length, 1); assert.equal(blobs[0].type, "image/png")
  assert.deepEqual(Buffer.from(await blobs[0].arrayBuffer()), Buffer.from(value.png_base64, "base64"))
  assert.equal(state.value.delivery_text, value.media_descriptor.alt_text)
  assert.deepEqual(state.value.delivered, receipt)
  assert.deepEqual(value, before); assert.deepEqual(revoked, ["blob:invented-1"])
})

test("actual Python delivered handler feeds the controller after text and attachment edits", async () => {
  const native = temperature()
  const code = `
import base64,json,sys
def guard(event, args):
    if event.startswith(('socket.', 'sqlite3.', 'subprocess.')):
        raise AssertionError('forbidden fixture side effect: ' + event)
sys.addaudithook(guard)
import pytest
from copy import deepcopy
from src.editorial import revisions
from tests import test_delivered_temperature_preview as fixture
value=json.load(sys.stdin)
fixture.RETAINED_BYTES=base64.b64decode(value['png'])
fixture.PROFILE=value['profile']
with pytest.MonkeyPatch.context() as patch:
    state,draft,receipt,prepared,_=fixture.retained_temperature(patch)
    revisions.invalidate_text(draft,'Invented later edited text.',at=fixture.AT)
    revisions.invalidate_media_attachment(draft,None,at=fixture.AT)
    draft['status']='posted'
    before=deepcopy(state)
    request=fixture.request_for(draft)
    response=fixture.build(state,request)
    assert state==before
    print(json.dumps(dict(request=request,response=response,receipt=receipt,descriptor=prepared['descriptor'])))
`
  const processResult = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c", code], {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
    input: JSON.stringify({ png: native.png_base64, profile: native.media_descriptor.renderer }),
    env: { PATH: process.env.PATH, LC_ALL: "C", TZ: "UTC", PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1" },
  })
  assert.equal(processResult.status, 0, processResult.stderr)
  const actual = JSON.parse(processResult.stdout), { state, blobs } = await consume(actual.response, actual.request)
  assert.equal(state.status, "ready")
  assert.deepEqual(state.value.media_descriptor, actual.descriptor)
  assert.equal(state.value.delivery_text, actual.descriptor.alt_text)
  assert.equal(state.value.delivered.text, actual.receipt.text)
  assert.equal(state.value.delivered.content_revision, actual.receipt.content_revision)
  assert.ok(actual.request.expected_revision.content_revision > actual.receipt.content_revision)
  assert.deepEqual(Buffer.from(await blobs[0].arrayBuffer()), Buffer.from(native.png_base64, "base64"))
})

test("delivered temperature does not relax source, profile, byte, alt or receipt validation", async () => {
  const changes = [v => { v.source_context.valid_date = "2026-10-27" }, v => { v.source_context.station_id = "USC99000002" },
    v => { v.source_context.reporting_interval_known = true }, v => { v.source_context.timezone = "UTC" },
    v => { v.media_descriptor.renderer.implementation_sha256 = "0".repeat(64) }, v => { v.png_base64 = png(1201, 1500).toString("base64") },
    v => { v.delivery_text += " altered" }, v => { v.expanded_description += " altered" },
    v => { v.delivered.tweet_id = "" }, v => { v.delivered.confirmed_at = "not a time" },
    v => { v.revision_identity.content_revision++ }, v => { v.media_kind = "unknown" },
    v => { v.publication_approved = true }, v => { v.attachment = true }, v => { v.original_base64 = "extra" }]
  for (const change of changes) {
    const bad = temperature(); change(bad)
    const { state, blobs } = await consume(bad)
    assert.equal(state.status, "error"); assert.equal(blobs.length, 0)
  }
})

test("delivered published drift is refused before creating either Blob", async () => {
  for (const change of [v => { v.width++ }, v => { v.original_base64 += "AAAA" },
    v => { v.png_sha256 = "0".repeat(64) }, v => { v.delivery_text += " altered" }, v => { v.delivered.tweet_id = "" }]) {
    const bad = await published("nhc_track_cone_v1"); change(bad)
    const { state, blobs } = await consume(bad)
    assert.equal(state.status, "error"); assert.equal(blobs.length, 0)
  }
})
