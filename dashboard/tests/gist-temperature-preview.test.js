import assert from "node:assert/strict"
import test from "node:test"
import { createHash } from "node:crypto"
import { deflateSync } from "node:zlib"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure, TemperatureMediaControls } from "../app/components/GraphicPreview.js"
import { fingerprint } from "../lib/draft-revisions.js"
import savedManifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, graphicRequest, temperaturePNGRequest, validateGraphicResponse } from "../lib/graphic-preview.js"

const hash = value => createHash("sha256").update(value).digest("hex")
// Detached browser fixtures only. Full source eligibility is checked in Python.
const manifest = structuredClone(savedManifest)
manifest.identity.files["src/media/gist_temperature_media.py"] = hash("invented renderer pin")
const draft = () => ({ id: "invented-temperature", type: "all_time_high", status: "pending", text: "Invented saved station comparison.",
  editorial_policy: { policy_sha256: "e".repeat(64) }, review_context: { two_bot: { bundle: {
    signal_kind: "open_meteo_archive_high", raw_signal_dump: { evidence: { source_product: "noaa-ghcn-daily-v2", evidence_type: "observed" } },
  } } }, revision_identity: { content_revision: 0, decision_revision: 0, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) } })
const request = () => temperaturePNGRequest(draft(), manifest)

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
const header = Buffer.alloc(13)
header.writeUInt32BE(1200, 0); header.writeUInt32BE(1500, 4); header[8] = 8; header[9] = 2
const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
  chunk("IDAT", deflateSync(Buffer.alloc((1200 * 3 + 1) * 1500))), chunk("IEND", Buffer.alloc(0))])

function responseValue() {
  const req = request(), files = manifest.identity.files, alt = "Invented full station comparison; source-calendar date; reporting interval unknown."
  const descriptor = { schema_version: 1, kind: "gist_temperature_comparator_v1", bundle_sha256: "c".repeat(64),
    source_revision_sha256: "d".repeat(64), baseline_revision_sha256: "f".repeat(64), station_id: "USW00000001", valid_date: "2026-10-28",
    renderer: { implementation_sha256: files["src/media/gist_temperature_media.py"], font_sha256: files["src/media/fonts/DejaVuSansMono.ttf"],
      pillow: "12.2.0", freetype: "2.13.3", zlib: "1.2.13", width: 1200, height: 1500 },
    png_sha256: hash(png), alt_text: alt, alt_sha256: hash(alt) }
  return { schema_version: 3, draft_id: req.draft_id, revision_identity: req.expected_revision,
    policy_source_sha256: req.expected_policy_source_sha256, preview_runtime_sha256: req.expected_preview_runtime_sha256,
    publication_approved: false, attachment: false, width: 1200, height: 1500, title: "Invented temperature comparison", alt_text: alt,
    scope: "Invented qualified sample; not a certified record", source: "NOAA GHCN-Daily · station observations",
    source_context: { kind: "ghcn_station_day", station_id: descriptor.station_id, valid_date: descriptor.valid_date,
      retrieved_at: "2026-10-28T12:00:00Z", reporting_interval_known: false, timezone: null },
    png_base64: png.toString("base64"), png_sha256: hash(png), media_descriptor: descriptor, media_descriptor_sha256: fingerprint(descriptor) }
}
const ok = value => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const render = element => renderToStaticMarkup(element)
function elements(element) {
  if (!element || typeof element !== "object") return []
  return [element, ...React.Children.toArray(element.props?.children).flatMap(elements)]
}

// This real component is stateless; execute its actual button handlers without a browser.
function controls(value, preview, props = {}) {
  return TemperatureMediaControls({ draft: value, preview, reviewConfirmed: false, onConfirm() {}, ...props })
}

test("temperature PNG adds only the format field to the existing bound request", () => {
  assert.deepEqual(request(), { ...graphicRequest(draft(), manifest), format: "png" })
  assert.equal(temperaturePNGRequest({ ...draft(), publish_blocked: true }, manifest), null)
  const html = render(React.createElement(GraphicPreview, { draft: draft() }))
  assert.match(html, /attach it, then review the text and graphic together/)
  assert.match(html, /Preview graphic/)
  for (const props of [{ editing: true }, { updating: true }])
    assert.doesNotMatch(render(React.createElement(GraphicPreview, { draft: draft(), ...props })), /<button|<img|<input/)
})

test("PNG response binds bytes, descriptor fingerprint, source context and pinned renderer", async () => {
  const good = responseValue()
  assert.equal(await validateGraphicResponse(good, request(), manifest), good)
  const changes = [
    v => { v.schema_version = 2 }, v => { v.draft_id += "other" }, v => { v.revision_identity.decision_revision++ },
    v => { v.preview_runtime_sha256 = "0".repeat(64) }, v => { v.policy_source_sha256 = "0".repeat(64) },
    v => { v.publication_approved = true }, v => { v.attachment = true }, v => { v.width = 1 },
    v => { v.source = "Unrelated provider" }, v => { v.source_context.station_id = "USW00000002" },
    v => { v.source_context.valid_date = "2026-10-27" }, v => { v.source_context.reporting_interval_known = true },
    v => { v.source_context.timezone = "UTC" }, v => { v.source_time = "unsupported" }, v => { v.png_url = "https://example.test/image.png" },
    v => { v.media_descriptor.extra = true }, v => { v.media_descriptor.kind = "other" },
    v => { v.media_descriptor.schema_version = true }, v => { v.media_descriptor.bundle_sha256 = "not-a-digest" },
    v => { v.media_descriptor.source_revision_sha256 = [] }, v => { v.media_descriptor.baseline_revision_sha256 = "" },
    v => { v.media_descriptor.renderer.implementation_sha256 = "0".repeat(64) },
    v => { v.media_descriptor.renderer.font_sha256 = "0".repeat(64) }, v => { v.media_descriptor.renderer.pillow = "" },
    v => { v.media_descriptor.renderer.width = 1200.5 }, v => { v.media_descriptor.renderer.extra = "unknown" },
    v => { v.media_descriptor.png_sha256 = "0".repeat(64) }, v => { v.alt_text += "altered" },
    v => { v.media_descriptor.alt_sha256 = "0".repeat(64) }, v => { v.media_descriptor_sha256 = "0".repeat(64) },
    v => { v.media_descriptor.alt_text += "altered" }, v => { v.media_descriptor.valid_date = "2026-02-30" },
    v => { v.png_base64 = "https://example.test/image.png" }, v => { v.png_base64 += "\n" },
  ]
  for (const change of changes) {
    const bad = structuredClone(good); change(bad)
    await assert.rejects(validateGraphicResponse(bad, request(), manifest))
  }
  await assert.rejects(validateGraphicResponse(good, graphicRequest(draft(), manifest), manifest))
  const unpinned = structuredClone(manifest); delete unpinned.identity.files["src/media/gist_temperature_media.py"]
  await assert.rejects(validateGraphicResponse(good, request(), unpinned))
})

test("PNG signature, dimensions, digest and canonical base64 are checked independently", async () => {
  for (const change of [bytes => { bytes[0] = 0 }, bytes => { bytes.writeUInt32BE(13, 16) },
    bytes => { bytes.writeUInt32BE(13, 20) }, bytes => { bytes.writeUInt32BE(14, 8) },
    bytes => { bytes.write("TEXT", 12) }, bytes => bytes.fill(0)]) {
    const bad = responseValue(), changed = Buffer.from(png); change(changed)
    bad.png_base64 = changed.toString("base64"); bad.png_sha256 = bad.media_descriptor.png_sha256 = hash(changed)
    bad.media_descriptor_sha256 = fingerprint(bad.media_descriptor)
    await assert.rejects(validateGraphicResponse(bad, request(), manifest))
  }
  const bad = responseValue(); bad.png_base64 = Buffer.concat([png, Buffer.from("changed")]).toString("base64")
  await assert.rejects(validateGraphicResponse(bad, request(), manifest))
})

test("ready PNG becomes an image/png Blob; replacement and disposal revoke exact URLs", async () => {
  const states = [], revoked = []; let count = 0
  const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
    fetcher: async (_url, options) => { assert.deepEqual(JSON.parse(options.body), request()); return ok(responseValue()) },
    createURL: blob => { assert.equal(blob.type, "image/png"); assert.equal(blob.size, png.length); return `blob:png-${++count}` },
    revokeURL: url => revoked.push(url) })
  await controller.start(request()); await controller.start(request()); controller.dispose(); controller.dispose()
  assert.equal(states.filter(state => state.status === "ready").length, 2)
  assert.deepEqual(revoked, ["blob:png-1", "blob:png-2"])
})

test("PNG draft-switch cancellation, duplicate clicks and deadline discard late images", async () => {
  for (const deadline of [false, true]) {
    const pending = deferred(), states = []; let calls = 0
    const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state), timeoutMs: deadline ? 1 : 35000,
      fetcher: () => { calls++; return pending.promise }, createURL: () => assert.fail("late PNG installed") })
    const first = controller.start(request()); await controller.start(request())
    assert.equal(calls, 1)
    if (deadline) { await new Promise(resolve => setTimeout(resolve, 15)); assert.equal(states.at(-1).status, "error") }
    else controller.dispose()
    pending.resolve(ok(responseValue())); await first; controller.dispose()
    assert.equal(states.filter(state => state.status === "ready").length, 0)
  }
})

test("full PNG description is visible beside the image and escaped source labels", () => {
  const value = responseValue(); value.title = "<script>invented</script>"
  const html = render(React.createElement(GraphicPreviewFigure, { value, url: "blob:verified-png" }))
  assert.match(html, /Full graphic description/)
  assert.match(html, /source-calendar date/)
  assert.match(html, /reporting interval and timezone unknown/)
  assert.match(html, /&lt;script&gt;invented&lt;\/script&gt;/)
  assert.doesNotMatch(html, /<details|<script|<svg|https:/)
})

test("attach and remove call only explicit actions with exact server revision and descriptor hash", () => {
  const value = draft(), preview = { status: "ready", value: responseValue(), url: "blob:png" }, actions = []
  const onAction = (...args) => actions.push(args)
  const tree = controls(value, preview, { onAction })
  const buttons = elements(tree).filter(node => node.type === "button")
  assert.equal(buttons.length, 1); assert.equal(buttons[0].props.children, "Attach graphic")
  buttons[0].props.onClick()
  assert.deepEqual(actions.pop(), ["attach_graphic", { expectedRevision: value.revision_identity,
    expectedMediaSha256: preview.value.media_descriptor_sha256 }])
  value.media_attachment_sha256 = preview.value.media_descriptor_sha256
  const remove = elements(controls(value, { status: "error" }, { onAction })).find(node => node.type === "button")
  assert.equal(remove.props.children, "Remove graphic"); remove.props.onClick()
  assert.deepEqual(actions.pop(), ["remove_graphic", { expectedRevision: value.revision_identity }])
})

test("joint review requires ready PNG matching server-projected attachment and explicit checkbox", () => {
  const value = draft(), preview = { status: "ready", value: responseValue(), url: "blob:png" }, actions = []
  const onAction = (...args) => actions.push(args)
  value.media_attachment_sha256 = preview.value.media_descriptor_sha256
  const unconfirmed = controls(value, preview, { onAction })
  assert.match(render(unconfirmed), /Invented saved station comparison/)
  let review = elements(unconfirmed).find(node => node.type === "button" && node.props.children === "Record joint review")
  assert.equal(review.props.disabled, true)
  review.props.onClick()
  assert.equal(actions.length, 0)
  const confirmed = controls(value, preview, { reviewConfirmed: true, onAction })
  review = elements(confirmed).find(node => node.type === "button" && node.props.children === "Record joint review")
  assert.equal(review.props.disabled, false); review.props.onClick()
  assert.deepEqual(actions.pop(), ["review", { reviewConfirmed: true, mediaReviewConfirmed: true,
    expectedMediaSha256: preview.value.media_descriptor_sha256, expectedPolicySha256: value.editorial_policy.policy_sha256,
    expectedRevision: value.revision_identity }])
  for (const changed of [{}, { media_attachment_sha256: "0".repeat(64) }, { publish_blocked: true },
    { review_status: "conflict" }, { editorial_policy: {} }, { status: "posted" }]) {
    const copy = { ...value, ...changed }
    if (Object.keys(changed).length === 0) delete copy.media_attachment_sha256
    assert.doesNotMatch(render(controls(copy, preview, { reviewConfirmed: true, onAction })), /Record joint review|type="checkbox"/)
  }
  for (const state of [{ status: "idle" }, { status: "loading" }, { status: "error" }])
    assert.doesNotMatch(render(controls(value, state, { onAction })), /Record joint review|type="checkbox"/)
})

test("Workbench forwards explicit media actions and hides text-only review when media is attached", () => {
  // Workbench uses JSX; the build compiles it. Keep this focused wiring assertion
  // alongside executable controller/action tests instead of importing JSX in Node.
  const source = readFileSync(new URL("../app/components/DraftWorkbench.js", import.meta.url), "utf8")
  assert.match(source, /onAction=\{\(action, payload\) => draftAct\(selectedDraft\.id, action, payload\)\}/)
  assert.match(source, /controls\.canReview && !selectedDraft\.media_attachment_sha256 && !selectedDraft\.media_attachment/)
})


test("invalid stored attachment remains removable without a usable preview", () => {
  for (const media_attachment of [null, {kind:"unknown"}, {kind:"gist_temperature_comparator_v1", renderer:{pillow:"obsolete"}}]) {
    const value = {...draft(),media_attachment,media_attachment_sha256:null,review_status:"media_review_required"}
    for (const preview of [{status:"idle"},{status:"error",message:"Source unavailable"}]) {
      const actions=[], result=controls(value,preview,{onAction:(...args)=>actions.push(args)})
      const remove=elements(result).find(node=>node.type==="button"&&node.props.children==="Remove graphic")
      assert.equal(remove.props.disabled,false);remove.props.onClick()
      assert.deepEqual(actions,[["remove_graphic",{expectedRevision:value.revision_identity}]])
      assert.doesNotMatch(render(result),/Record joint review|Attach graphic/)
    }
  }
})


test("source-unavailable outer preview retains explicit attachment removal", () => {
  const value={...draft(),media_attachment:{kind:"obsolete"},media_attachment_sha256:null,
    review_context:{two_bot:{bundle:{signal_kind:"open_meteo_archive_high",raw_signal_dump:{}}}}}
  const html=render(React.createElement(GraphicPreview,{draft:value,onAction(){}}))
  assert.match(html,/No comparison preview is available/)
  assert.match(html,/Remove graphic/)
  assert.doesNotMatch(html,/Record joint review|Attach graphic/)
  for(const mode of [{editing:true},{updating:true}])
    assert.doesNotMatch(render(React.createElement(GraphicPreview,{draft:value,onAction(){},...mode})),/Remove graphic/)
})
