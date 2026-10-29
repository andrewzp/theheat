/** Browser contract for new-family PNG previews, using a real Python response for
 * invented data. No network: Python runs with sockets trapped.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { createHash } from "node:crypto"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure, MediaControls } from "../app/components/GraphicPreview.js"
import { createGraphicPreviewController, mediaPNGRequest, typedFingerprint, validateGraphicResponse } from "../lib/graphic-preview.js"
import { FAMILIES, pythonJSON } from "./helpers/gist-hazard-harness.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const hash = value => createHash("sha256").update(value).digest("hex")
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const code = trap + `
from datetime import datetime
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import decision_revision, draft_identity
from tests.gist_hazard_helpers import CLOCKS, saved_state
value=json.load(sys.stdin)
state=saved_state(value['family'])
draft=state['drafts'][0]
request={'draft_id':draft['id'],'expected_revision':{**draft_identity(draft),'decision_revision':decision_revision(draft)},
  'expected_policy_source_sha256':value['policy'],'expected_preview_runtime_sha256':value['runtime'],'format':'png'}
out={}
for name,at in (('current',CLOCKS[value['family']][0]),('historical',CLOCKS[value['family']][1])):
    with freeze_time(at):
        out[name]=json.loads(build_preview(request,policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget()))
draft['revision_identity']=request['expected_revision']
print(json.dumps(dict(draft=draft,request=request,**out),ensure_ascii=False))
`
const fixtures = {}
function fixture(family) {
  fixtures[family] ??= pythonJSON(code, { family, policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
  return structuredClone(fixtures[family])
}
const render = element => renderToStaticMarkup(element)

for (const family of FAMILIES) {
  test(`${family}: real Python PNG response satisfies the browser contract; the request is unchanged plus format`, async () => {
    const { draft, request, current } = fixture(family)
    assert.deepEqual(mediaPNGRequest(draft, manifest), request)
    assert.equal(await validateGraphicResponse(current, request, manifest), current)
    assert.equal(current.schema_version, 4)
    assert.equal(current.media_descriptor_sha256, await typedFingerprint(current.media_descriptor))
    assert.ok([...current.delivery_text].length <= 1000 && Buffer.byteLength(current.delivery_text) <= 1000)
    assert.equal(current.posting_window.status, "current")
  })

  test(`${family}: every bound response field is checked independently`, async () => {
    const { request, current } = fixture(family)
    const changes = [
      v => { v.schema_version = 3 }, v => { v.draft_id += "-other" }, v => { v.revision_identity.decision_revision++ },
      v => { v.preview_runtime_sha256 = "0".repeat(64) }, v => { v.publication_approved = true }, v => { v.attachment = true },
      v => { v.media_kind = "gist_temperature_comparator_v1" }, v => { v.media_descriptor.kind = "gist_unknown_v1" },
      v => { v.media_descriptor.synthetic = true }, v => { v.media_descriptor.extra = 1 },
      v => { v.media_descriptor.renderer.files["src/media/gist_hazard_media.py"] = "0".repeat(64) },
      v => { v.media_descriptor.renderer.pillow = "12.3.0" }, v => { v.media_descriptor.renderer.layout = "raqm" },
      v => { v.media_descriptor.template_version = "other" }, v => { v.media_descriptor.description.derivation = "other" },
      v => { v.delivery_text += " " }, v => { v.media_descriptor.description.delivery_text += " " },
      v => { v.expanded_description += " " }, v => { v.png_sha256 = "0".repeat(64) },
      // Same UTF-8 length, different bytes: only the digest can catch it.
      v => { v.expanded_description = v.expanded_description.replace("a", "b") },
      v => { v.png_base64 = Buffer.from("invented").toString("base64") },
      v => { v.media_descriptor_sha256 = "0".repeat(64) }, v => { v.posting_window.status = "approved" },
      v => { v.posting_window = { status: "current", code: "media_x", reason: null, checked_at: v.posting_window.checked_at } },
      v => { v.source = "Unrelated provider" }, v => { v.source_context.kind = "ghcn_station_day" },
      v => { v.delivery_text = "x".repeat(1001); v.media_descriptor.description.delivery_text = v.delivery_text },
      v => { v.png_url = "https://example.invalid/x.png" },
    ]
    for (const change of changes) {
      const bad = structuredClone(current); change(bad)
      await assert.rejects(validateGraphicResponse(bad, request, manifest), undefined, change.toString())
    }
    const unpinned = structuredClone(manifest); delete unpinned.identity.files["src/media/gist_hazard_media.py"]
    await assert.rejects(validateGraphicResponse(current, request, unpinned))
  })

  test(`${family}: figure shows the exact X description, expanded details and posting disclosure`, () => {
    const { current, historical } = fixture(family)
    const html = render(React.createElement(GraphicPreviewFigure, { value: current, url: "blob:invented" }))
    assert.match(html, /<strong>Image description sent to X<\/strong>/)
    assert.ok(html.includes(current.delivery_text.replaceAll("&", "&amp;")))
    assert.match(html, /<details><summary>Expanded source details \(not sent\)<\/summary>/)
    assert.match(html, /Within its posting window when previewed/)
    assert.ok(html.includes(`alt="${current.delivery_text.replaceAll("&", "&amp;")}"`))
    const old = render(React.createElement(GraphicPreviewFigure, { value: historical, url: "blob:invented" }))
    assert.match(old, /Not postable now: /)
    assert.match(old, /historical preview stays available to inspect; approval and sending will refuse it/)
    if (family === "pm25") {
      assert.match(html, /model forecast/)
      assert.match(html, /Retrieval is not a model run time, and a forecast never becomes an observation/)
    }
  })

  test(`${family}: shared controls attach, review the delivery description and remove`, () => {
    const { draft, current } = fixture(family)
    const actions = []
    const value = { ...draft, editorial_policy: { policy_sha256: "a".repeat(64) } }
    const preview = { status: "ready", value: current, url: "blob:invented" }
    const onAction = (action, payload) => actions.push([action, payload])
    let element = MediaControls({ draft: value, preview, reviewConfirmed: false, onConfirm() {}, onAction })
    assert.match(render(element), /Attach graphic/)
    element.props.children[0].props.onClick()
    assert.deepEqual(actions.pop(), ["attach_graphic", { expectedRevision: value.revision_identity, expectedMediaSha256: current.media_descriptor_sha256 }])
    const attached = { ...value, media_attachment: current.media_descriptor, media_attachment_sha256: current.media_descriptor_sha256 }
    const html = render(MediaControls({ draft: attached, preview, reviewConfirmed: true, onConfirm() {}, onAction }))
    assert.match(html, /This image and its X image description are attached/)
    assert.match(html, /the image description sent to X and the expanded source details/)
    assert.match(html, /I checked the exact text, image, X image description and source details/)
    assert.match(html, /Remove graphic/)
    const mismatched = { ...attached, media_attachment_sha256: "0".repeat(64) }
    assert.doesNotMatch(render(MediaControls({ draft: mismatched, preview, reviewConfirmed: true, onConfirm() {}, onAction })), /Record joint review/)
  })

  test(`${family}: component offers the PNG preview, hides it while editing and keeps broken attachments removable`, () => {
    const { draft } = fixture(family)
    const html = render(React.createElement(GraphicPreview, { draft }))
    assert.match(html, /Build the saved-source image, attach it, then review the text and graphic together/)
    assert.match(html, /Preview graphic/)
    for (const mode of [{ editing: true }, { updating: true }])
      assert.doesNotMatch(render(React.createElement(GraphicPreview, { draft, ...mode })), /<button|<img/)
    const broken = { ...draft, media_attachment: { kind: "experimental_pg_image" } }
    assert.match(render(React.createElement(GraphicPreview, { draft: broken, onAction() {} })), /Remove graphic/)
  })

  test(`${family}: controller turns the response into an image/png Blob and revokes it`, async () => {
    const { request, current } = fixture(family)
    const states = [], revoked = []
    const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
      fetcher: async () => new Response(JSON.stringify(current), { headers: { "Content-Type": "application/json" } }),
      createURL: blob => { assert.equal(blob.type, "image/png"); assert.equal(blob.size, current.media_descriptor.image.byte_count); return "blob:hazard" },
      revokeURL: url => revoked.push(url) })
    await controller.start(request); controller.dispose()
    assert.equal(states.at(-1).status, "ready"); assert.deepEqual(revoked, ["blob:hazard"])
    assert.equal(hash(Buffer.from(current.png_base64, "base64")), current.png_sha256)
  })
}

for (const family of FAMILIES) {
  test(`${family}: full-size view is an explicit labelled dialog control; the image loads only when opened`, () => {
    const { current } = fixture(family)
    const html = render(React.createElement(GraphicPreviewFigure, { value: current, url: "blob:invented" }))
    assert.match(html, /<button type="button" class="btn sm graphic-full-size-open" aria-haspopup="dialog">View full size<\/button>/)
    assert.match(html, /<dialog class="graphic-full-size" aria-label="Full-size image: [^"]+"><button type="button" class="btn sm">Close full-size image<\/button><\/dialog>/)
    assert.equal(html.match(/<img /g).length, 1)
    assert.match(html, /(Model forecast chart|MODIS satellite detections|NOAA-20\/NOAA-21 VIIRS satellite detections)/)
  })

  test(`${family}: a stale or mismatched attachment offers replacement, never a review`, () => {
    const { draft, current } = fixture(family)
    const value = { ...draft, editorial_policy: { policy_sha256: "a".repeat(64) }, media_attachment: { kind: "stale" },
      media_attachment_sha256: "0".repeat(64) }
    const actions = []
    const element = MediaControls({ draft: value, preview: { status: "ready", value: current, url: "blob:x" },
      reviewConfirmed: true, onConfirm() {}, onAction: (action, payload) => actions.push([action, payload]) })
    const html = render(element)
    assert.match(html, /Replace attached graphic/); assert.match(html, /Remove graphic/)
    assert.doesNotMatch(html, /Record joint review/)
    element.props.children[0].props.children[1].props.onClick()
    assert.deepEqual(actions, [["attach_graphic", { expectedRevision: value.revision_identity, expectedMediaSha256: current.media_descriptor_sha256 }]])
  })

  test(`${family}: a delayed response for a replaced or disposed draft never installs an image`, async () => {
    const { request, current } = fixture(family)
    const states = [], created = []
    let release
    const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
      fetcher: () => new Promise(resolve => { release = () => resolve(new Response(JSON.stringify(current), { headers: { "Content-Type": "application/json" } })) }),
      createURL: blob => { created.push(blob); return "blob:late" }, revokeURL() {} })
    const pending = controller.start(request)
    controller.dispose(); release(); await pending
    assert.equal(created.length, 0)
    assert.ok(!states.some(state => state.status === "ready"))
  })
}
