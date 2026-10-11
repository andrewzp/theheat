import assert from "node:assert/strict"
import test from "node:test"
import { createHash } from "node:crypto"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure } from "../app/components/GraphicPreview.js"
import { fingerprint } from "../lib/draft-revisions.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, graphicRequest, graphicRequestKey, validateGraphicResponse } from "../lib/graphic-preview.js"

const hash = text => createHash("sha256").update(text).digest("hex")
const draft = () => ({ id: "invented", type: "fire", status: "pending", revision_identity: {
  content_revision: 0, decision_revision: 0, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64),
} })
const request = () => graphicRequest(draft(), manifest)
// Browser contract fixture only: source eligibility is tested by the actual Python adapter.
function responseValue() {
  const req = request(), files = manifest.identity.files
  const binding = { template: "modis_thermal_detections", template_version: "p31-modis-thermal-1",
    source_evidence_sha256: "c".repeat(64), renderer: { library: "ReportLab", version: "4.4.9", format: "svg", schema_version: 1,
      width: 1200, height: 1500, implementation_sha256: files["src/media/evidence_graphic_render.py"],
      contract_sha256: files["src/media/evidence_graphic.py"], adapter_sha256: files["src/media/fire_graphic_adapter.py"],
      font_sha256: files["src/media/fonts/DejaVuSansMono.ttf"] } }
  const svg = '<svg xmlns="http://www.w3.org/2000/svg"><title>Invented browser contract fixture</title></svg>'
  return { schema_version: 1, draft_id: req.draft_id, revision_identity: req.expected_revision,
    policy_source_sha256: req.expected_policy_source_sha256, preview_runtime_sha256: req.expected_preview_runtime_sha256,
    publication_approved: false, attachment: false, width: 1200, height: 1500, source: "NASA FIRMS · MODIS",
    source_time: "2032-02-29T23:59:00Z", title: "Invented", alt_text: "Invented, no physical incident claim", scope: "Saved detections",
    svg_utf8: svg, svg_sha256: hash(svg), binding, cache_key: fingerprint(binding) }
}
const ok = value => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }

test("request keys bind every revision, source policy and packaged runtime", () => {
  const base = request(), key = graphicRequestKey(base)
  for (const field of ["content_revision", "decision_revision", "text_sha256", "evidence_sha256"]) {
    const changed = structuredClone(base)
    changed.expected_revision[field] = typeof changed.expected_revision[field] === "number" ? 1 : "d".repeat(64)
    assert.notEqual(graphicRequestKey(changed), key)
  }
  for (const field of ["draft_id", "expected_policy_source_sha256", "expected_preview_runtime_sha256"])
    assert.notEqual(graphicRequestKey({ ...base, [field]: "changed" }), key)
  for (const changes of [{ status: "posted" }, { publish_blocked: true }, { review_status: "conflict" }, { revision_identity: {} }])
    assert.equal(graphicRequest({ ...draft(), ...changes }, manifest), null)
})

test("actual component keeps preview separate from approval and hides it during editing", () => {
  const render = props => renderToStaticMarkup(React.createElement(GraphicPreview, props))
  const html = render({ draft: draft() })
  assert.match(html, /Saved-source preview/)
  assert.match(html, /Preview only; not attached or approved/)
  assert.match(html, /Preview graphic/)
  assert.doesNotMatch(html, /<img|download|<input/)
  assert.doesNotMatch(render({ draft: draft(), editing: true }), /<button|<img/)
  assert.doesNotMatch(render({ draft: draft(), updating: true }), /<button|<img/)
  assert.equal(render({ draft: { ...draft(), type: "rainfall" } }), "")
})

test("response requires exact revision, bytes, renderer and absence of publication authority", async () => {
  const good = responseValue()
  assert.deepEqual(await validateGraphicResponse(good, request(), manifest), good)
  for (const change of [value => { value.attachment = true }, value => { value.publication_approved = true },
    value => { value.revision_identity.decision_revision++ }, value => { value.svg_utf8 += "changed" },
    value => { value.preview_runtime_sha256 = "d".repeat(64) }, value => { value.binding.renderer.font_sha256 = "d".repeat(64) },
    value => { value.cache_key = "d".repeat(64) }, value => { value.svg_utf8 = "<svg><script/></svg>"; value.svg_sha256 = hash(value.svg_utf8) }]) {
    const bad = structuredClone(good); change(bad)
    await assert.rejects(validateGraphicResponse(bad, request(), manifest))
  }
})

test("figure exposes complete accessible description, minute precision and escaped labels", () => {
  const value = { ...responseValue(), title: "<script>not markup</script>", alt_text: "Complete invented description & source limits" }
  const html = renderToStaticMarkup(React.createElement(GraphicPreviewFigure, { value, url: "blob:invented" }))
  assert.match(html, /2032-02-29 23:59 UTC \(minute precision\)/)
  assert.doesNotMatch(html, /23:59:00|<script>|<svg|download/)
  assert.match(html, /alt="Complete invented description &amp; source limits"/)
  assert.match(html, /<details><summary>Read the full graphic description<\/summary><p>Complete invented description &amp; source limits<\/p>/)
  assert.match(html, /&lt;script&gt;not markup&lt;\/script&gt;/)
})

test("duplicate click does not fetch again and disposal rejects a late response", async () => {
  const pending = deferred(), states = []; let calls = 0, signal
  const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
    fetcher: async (url, options) => {
      calls++; signal = options.signal
      assert.equal(url, "/api/graphic_preview"); assert.equal(options.redirect, "error")
      assert.equal(options.cache, "no-store"); assert.equal(options.credentials, "same-origin")
      return pending.promise
    }, createURL: () => assert.fail("late asset"), revokeURL: () => assert.fail("no asset yet") })
  const first = controller.start(request()); await controller.start(request())
  assert.equal(calls, 1)
  controller.dispose(); assert.ok(signal.aborted)
  pending.resolve(ok(responseValue())); await first
  assert.deepEqual(states, [{ status: "loading" }])
})

test("replacing and unmounting revoke each Blob URL exactly once", async () => {
  const revoked = [], states = []; let next = 0
  const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
    fetcher: async () => ok(responseValue()), createURL: blob => {
      assert.equal(blob.type, "image/svg+xml"); return `blob:fixture-${++next}`
    }, revokeURL: url => revoked.push(url) })
  await controller.start(request()); await controller.start(request()); controller.dispose(); controller.dispose()
  assert.deepEqual(revoked, ["blob:fixture-1", "blob:fixture-2"])
  assert.equal(states.filter(state => state.status === "ready").length, 2)
})

test("error, redirect-like HTML and oversized response produce no image or raw server detail", async () => {
  for (const response of [new Response("private raw exception", { status: 409 }),
    new Response("<html>login</html>", { headers: { "Content-Type": "text/html" } }),
    new Response("x".repeat(1024 * 1024 + 1), { headers: { "Content-Type": "application/json" } })]) {
    const states = [], controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
      fetcher: async () => response, createURL: () => assert.fail("invalid image") })
    await controller.start(request()); controller.dispose()
    assert.equal(states.at(-1).status, "error")
    assert.ok(!JSON.stringify(states).includes("private raw"))
  }
})

test("deadline clears loading and discards a fetch that ignores abort", async () => {
  const pending = deferred(), states = []
  const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state), timeoutMs: 1,
    fetcher: () => pending.promise, createURL: () => assert.fail("expired image") })
  const first = controller.start(request())
  await new Promise(resolve => setTimeout(resolve, 15))
  assert.equal(states.at(-1).status, "error")
  pending.resolve(ok(responseValue())); await first; controller.dispose()
  assert.equal(states.filter(state => state.status === "ready").length, 0)
})
