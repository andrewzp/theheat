/** Browser contract and Workbench controls for the store-backed families (CRW, published
 * radar, NHC cone), using real Python responses built from an invented local media store.
 * Python runs with sockets trapped; nothing is fetched.
 */
import assert from "node:assert/strict"
import test from "node:test"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure, MediaControls } from "../app/components/GraphicPreview.js"
import { createGraphicPreviewController, MEDIA_HOLD_MESSAGES, mediaPNGRequest, storeFamilyFor, typedFingerprint,
  validateGraphicResponse } from "../lib/graphic-preview.js"
import { pythonJSON } from "./helpers/gist-hazard-harness.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const code = trap + `
from pathlib import Path
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import decision_revision, draft_identity
from src.media import gist_assets
from tests.gist_store_helpers import CLOCKS, retain, saved_state
value=json.load(sys.stdin)
store=gist_assets.SQLiteMediaStore(Path(value['store']))
retained=retain(value['family'],store)
state=saved_state(value['family'])
draft=state['drafts'][0]
request={'draft_id':draft['id'],'expected_revision':{**draft_identity(draft),'decision_revision':decision_revision(draft)},
  'expected_policy_source_sha256':value['policy'],'expected_preview_runtime_sha256':value['runtime'],'format':'png',
  'retained_input_sha256':retained}
out={}
for name,at in (('current',CLOCKS[value['family']][0]),('historical',CLOCKS[value['family']][1])):
    with freeze_time(at):
        out[name]=json.loads(build_preview(request,policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget(),store=store))
draft['revision_identity']=request['expected_revision']
print(json.dumps(dict(draft=draft,request=request,retained=retained,**out),ensure_ascii=False))
`
const fixtures = {}
function fixture(family) {
  if (!fixtures[family]) {
    const folder = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "theheat-store-")))
    fixtures[family] = pythonJSON(code, { family, store: path.join(folder, "media.sqlite3"),
      policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
  }
  return structuredClone(fixtures[family])
}
const render = element => renderToStaticMarkup(element)

for (const family of ["crw", "radar", "cone"]) {
  test(`${family}: real Python response satisfies the browser contract and names its retained input`, async () => {
    const { draft, request, current, retained } = fixture(family)
    assert.equal(storeFamilyFor(draft), family)
    assert.deepEqual(mediaPNGRequest(draft, manifest, retained), request)
    assert.equal(mediaPNGRequest(draft, manifest, "not-a-sha"), null)
    assert.equal(await validateGraphicResponse(current, request, manifest), current)
    assert.equal(current.schema_version, family === "crw" ? 4 : 5)
    assert.equal(current.media_descriptor_sha256, await typedFingerprint(current.media_descriptor))
    assert.ok([...current.delivery_text].length <= 1000 && Buffer.byteLength(current.delivery_text) <= 1000)
    assert.equal(current.posting_window.status, "current")
  })

  test(`${family}: every bound response field is checked independently`, async () => {
    const { request, current } = fixture(family)
    const changes = [
      v => { v.draft_id += "-other" }, v => { v.revision_identity.decision_revision++ }, v => { v.preview_runtime_sha256 = "0".repeat(64) },
      v => { v.publication_approved = true }, v => { v.attachment = true }, v => { v.media_descriptor.synthetic = true },
      v => { v.media_descriptor.extra = 1 }, v => { v.delivery_text += " " }, v => { v.expanded_description += " " },
      v => { v.expanded_description = v.expanded_description.replace("a", "b") }, v => { v.png_sha256 = "0".repeat(64) },
      v => { v.png_base64 = Buffer.from("invented").toString("base64") }, v => { v.media_descriptor_sha256 = "0".repeat(64) },
      v => { v.posting_window.status = "approved" }, v => { v.png_url = "https://example.invalid/x.png" },
      v => { v.media_descriptor.description.derivation = "other" },
    ]
    if (family === "crw") changes.push(
      v => { v.source = "Unrelated provider" }, v => { v.source_context.valid_cells = 2 },
      v => { v.media_descriptor.renderer.files["src/media/gist_crw_media.py"] = "0".repeat(64) },
      v => { v.media_descriptor.renderer.version = "gist-hazard-png-2" }, v => { v.media_descriptor.adapter_version = "p31-crw-erddap-9" })
    else changes.push(
      v => { v.schema_version = 4 }, v => { v.original_base64 = Buffer.from("invented").toString("base64") },
      v => { v.original_sha256 = "0".repeat(64) }, v => { v.original_mime = "image/jpeg" },
      v => { v.inspection.required_attestations.pop() }, v => { v.inspection.source_url = "javascript:alert(1)" },
      v => { v.media_descriptor.attestations.required = [] }, v => { v.media_descriptor.converter.png_codec = "other" },
      v => { v.media_descriptor.converter.files["src/media/gist_published_media.py"] = "0".repeat(64) },
      v => { v.media_descriptor.asset.manifest_sha256 = "0".repeat(64) }, v => { v.width += 1 })
    for (const change of changes) {
      const bad = structuredClone(current); change(bad)
      await assert.rejects(validateGraphicResponse(bad, request, manifest), undefined, change.toString())
    }
    await assert.rejects(validateGraphicResponse(current, { ...request, retained_input_sha256: "1".repeat(64) }, manifest),
      undefined, "a response for another retained input")
  })

  test(`${family}: figure shows what X receives, the description and the source inspection`, () => {
    const { current, historical } = fixture(family)
    const html = render(React.createElement(GraphicPreviewFigure, { value: current, url: "blob:derivative", originalURL: "blob:original" }))
    assert.match(html, /<strong>Image description sent to X<\/strong>/)
    assert.match(html, /Expanded source details \(not sent\)/)
    assert.match(html, /View full size/)
    if (family === "crw") assert.match(html, /sampled cells, not a continuous surface/)
    else {
      assert.match(html, /published original, not a TheHeat chart/)
      assert.match(html, /Original as retained \(exact bytes, inspection only\)/)
      assert.ok(html.includes('src="blob:original"'))
      assert.match(html, /nothing is fetched now/)
      assert.match(html, /no endorsement implied/)
      assert.match(html, family === "radar" ? /station reflectivity, dBZ/ : /forecast track of the storm centre/)
    }
    const old = render(React.createElement(GraphicPreviewFigure, { value: historical, url: "blob:derivative", originalURL: "blob:original" }))
    assert.match(old, /Not postable now: /)
  })

  test(`${family}: controls attach with the retained input and require every attestation`, () => {
    const { draft, current, retained } = fixture(family)
    const actions = [], onAction = (action, payload) => actions.push([action, payload])
    const value = { ...draft, editorial_policy: { policy_sha256: "a".repeat(64) } }
    const preview = { status: "ready", value: current, url: "blob:invented" }
    const element = MediaControls({ draft: value, preview, reviewConfirmed: false, onConfirm() {}, onAction, retainedInput: retained })
    element.props.children[0].props.onClick()
    assert.deepEqual(actions.pop(), ["attach_graphic", { expectedRevision: value.revision_identity,
      expectedMediaSha256: current.media_descriptor_sha256, retainedInputSha256: retained }])
    const attached = { ...value, media_attachment: current.media_descriptor, media_attachment_sha256: current.media_descriptor_sha256 }
    const required = current.inspection?.required_attestations ?? []
    const none = render(MediaControls({ draft: attached, preview, reviewConfirmed: true, onConfirm() {}, onAction, retainedInput: retained }))
    for (const row of required) assert.ok(none.includes(row.text.replaceAll("'", "&#x27;")))
    assert.equal(/Record joint review<\/button>/.test(none) && /disabled=""[^>]*>Record joint review/.test(none), required.length > 0)
    const all = Object.fromEntries(required.map(row => [row.name, true]))
    const ready = MediaControls({ draft: attached, preview, reviewConfirmed: true, onConfirm() {}, onAction, retainedInput: retained, attestations: all })
    const panel = ready.props.children.at(-1), button = panel.props.children.at(-1)
    button.props.onClick()
    const [action, payload] = actions.pop()
    assert.equal(action, "review")
    assert.deepEqual(payload.publishedAttestations, required.length ? all : undefined)
  })
}

test("named holds come from the client's closed table; unknown holds fall back to the fixed message", async () => {
  const request = mediaPNGRequest({ id: "invented", status: "pending", revision_identity: { content_revision: 1, decision_revision: 0,
    text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) } }, manifest, "c".repeat(64))
  for (const [hold, expected] of [["media_store_unavailable", MEDIA_HOLD_MESSAGES.media_store_unavailable],
    ["media_original_missing", MEDIA_HOLD_MESSAGES.media_original_missing],
    ["invented_private_detail", "The saved source or display limits cannot support this graphic. No substitute was used."]]) {
    const states = []
    const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
      fetcher: async () => new Response(JSON.stringify({ code: "media_hold", hold, error: "server text is never shown" }),
        { status: 422, headers: { "Content-Type": "application/json" } }) })
    await controller.start(request)
    assert.equal(states.at(-1).status, "error")
    assert.equal(states.at(-1).message, expected)
  }
})

test("cancel discards an in-flight preview for a previous retained input", async () => {
  const { request, current } = fixture("cone")
  const states = [], revoked = []
  let release
  const controller = createGraphicPreviewController({ manifest, onChange: state => states.push(state),
    fetcher: () => new Promise(resolve => { release = () => resolve(new Response(JSON.stringify(current), { headers: { "Content-Type": "application/json" } })) }),
    createURL: () => "blob:never", revokeURL: url => revoked.push(url) })
  const pending = controller.start(request)
  controller.cancel()
  release(); await pending
  assert.deepEqual(states.map(state => state.status), ["loading", "idle"])
  assert.deepEqual(revoked, [])
})

test("the Workbench asks for the retained input before any preview and keeps broken attachments removable", () => {
  for (const family of ["crw", "radar", "cone"]) {
    const { draft } = fixture(family)
    const html = render(React.createElement(GraphicPreview, { draft }))
    assert.match(html, family === "crw" ? /Retained CRW source packet \(SHA256\)/ : /Retained published (radar asset|forecast cone) \(SHA256\)/)
    assert.match(html, /retain_gist_media\.py/)
    assert.match(html, /disabled=""[^>]*>Preview graphic/)
    const broken = { ...draft, media_attachment: { kind: "gist_published_radar_v1" } }
    assert.match(render(React.createElement(GraphicPreview, { draft: broken, onAction() {} })), /Remove graphic/)
  }
})
