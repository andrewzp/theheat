/** W01 Hot10 on the actual drafts route over an invented Gist: replacement and history
 * continuity, the delivered-snapshot read path, and stale preview refusals. The Hot10
 * family's generic attach/review/approve/currentness acceptance runs in
 * gist-hazard-route.test.js (FAMILIES includes hot10). See helpers/gist-hazard-harness.js.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { policy } from "./helpers/review-policy.js"
import { attach, body, joint, pythonJSON, revision, withGist } from "./helpers/gist-hazard-harness.js"
import { fingerprint, reviewIsCurrent } from "../lib/draft-revisions.js"
import { validGistMedia } from "../lib/gist-media.js"
import { deliveredPNGRequest, validateGraphicResponse } from "../lib/graphic-preview.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const trap = "import json,sys,socket,contextlib\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
// Append an earlier Hot10 post delivered once through the real sender (fake X factories only).
const deliverCode = trap + `
from tests.gist_hazard_helpers import delivered_hot10_draft
state=json.loads(json.load(sys.stdin)['raw_state'])
with contextlib.redirect_stdout(sys.stderr):
    draft, calls = delivered_hot10_draft(state)
print(json.dumps(dict(raw_state=json.dumps(state, ensure_ascii=False), alt=calls[1][2])))
`
const inspectCode = trap + `
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value=json.load(sys.stdin); state=json.loads(value['raw_state'])
sys.stdout.buffer.write(build_preview(value['request'],policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget()))
`
// A re-qualified bulletin captured 30 minutes later replaces the draft's retained source. Python
// rewrites the stored JSON so every retained number keeps its spelling (JS would not).
const replacedCode = trap + `
from datetime import timedelta
from tests.gist_hazard_helpers import HOT10_CAPTURE, hot10_bundle
value=json.load(sys.stdin); state=json.loads(value['raw_state'])
draft=next(d for d in state['drafts'] if d['id']==value['draft_id'])
draft['review_context']['two_bot']['bundle']=hot10_bundle(now=HOT10_CAPTURE + timedelta(minutes=30))
print(json.dumps(dict(raw=json.dumps(state, ensure_ascii=False))))
`

test("hot10: a replaced source invalidates the reviewed image; the replacement attaches as one revision with history", async () => {
  await withGist("hot10", async t => {
    const { preview } = await attach(t); const reviewed = await joint(t)
    assert.equal(reviewIsCurrent(reviewed, policy), true)
    t.replaceState(pythonJSON(replacedCode, { raw_state: t.raw(), draft_id: t.primary }).raw)
    const changed = t.get()
    assert.equal(validGistMedia(changed), false); assert.equal(reviewIsCurrent(changed, policy), false)
    assert.equal((await t.post(body(changed, "approve"))).status, 409); assert.equal(t.dispatches.length, 0)
    // The old preview identity cannot attach to the changed draft; a new preview of the new source can.
    const stale = await t.post(body(changed, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
    assert.equal(stale.status, 409)
    const fresh = t.preview(changed)
    assert.notEqual(fresh.media_descriptor_sha256, preview.media_descriptor_sha256)
    const replacedAttach = await t.post(body(changed, "attach_graphic", { expectedMediaSha256: fresh.media_descriptor_sha256 }))
    assert.equal(replacedAttach.status, 200, JSON.stringify(replacedAttach.body))
    const now = t.get()
    assert.deepEqual(now.media_attachment, fresh.media_descriptor); assert.equal(now.content_revision, changed.content_revision + 1)
    assert.ok(now.revision_history.some(row => fingerprint(row.media_attachment ?? null) === fingerprint(preview.media_descriptor)
      && row.review_binding?.kind === "human_media"))
    assert.equal(reviewIsCurrent(now, policy), false)
    const again = await joint(t)
    assert.equal(again.review_binding.media_sha256, fingerprint(fresh.media_descriptor))
  })
})

test("hot10: a text edit makes an earlier preview stale; it cannot attach until previewed again", async () => {
  await withGist("hot10", async t => {
    const original = t.get(), early = t.preview(original)
    assert.equal((await t.post(body(original, "edit", { editedText: original.text + " Revised before attaching." }))).status, 200)
    const edited = t.get(), before = t.raw()
    const refused = await t.post(body(original, "attach_graphic", { expectedMediaSha256: early.media_descriptor_sha256 }))
    assert.equal(refused.status, 409); assert.equal(t.raw(), before)
    // Same graphic recipe, new text revision: the current preview binds the current revision.
    const current = t.preview(edited)
    assert.equal(current.media_descriptor_sha256, early.media_descriptor_sha256)
    assert.notDeepEqual(current.revision_identity, early.revision_identity)
    assert.equal((await t.post(body(edited, "attach_graphic", { expectedMediaSha256: current.media_descriptor_sha256 }))).status, 200)
  })
})

test("hot10: the delivered post stays listed and inspectable byte-for-byte while the current draft changes", async () => {
  await withGist("hot10", async t => {
    const seeded = pythonJSON(deliverCode, { raw_state: t.raw() })
    t.replaceState(seeded.raw_state)
    const listed = await t.delivered()
    assert.deepEqual(listed.map(d => d.id), ["invented-hot10-delivered"])
    const item = listed[0]
    assert.equal(item.delivered.tweet_id, "invented-x-receipt-invented-hot10-delivered"); assert.equal(item.status, "posted")
    const posted = t.get("invented-hot10-delivered")
    assert.equal(item.delivered.text, posted.text)
    // The current pending Hot10 draft is edited and given an image; the delivered list is unchanged.
    await attach(t); await joint(t)
    assert.equal((await t.post(body(t.get(), "edit", { editedText: "Invented current draft, edited after the earlier post." }))).status, 200)
    assert.deepEqual((await t.delivered()).map(d => d.id), ["invented-hot10-delivered"])
    const request = deliveredPNGRequest(item, manifest)
    assert.equal(request.delivered, true); assert.deepEqual(request.expected_revision, revision(posted))
    const response = pythonJSON(inspectCode, { raw_state: t.raw(), request, policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
    assert.equal(await validateGraphicResponse(response, request, manifest), response)
    assert.equal(response.png_sha256, posted.media_attachment.image.png_sha256)
    assert.equal(response.delivery_text, seeded.alt); assert.equal(response.delivered.text, posted.text)
    for (const change of [v => { v.delivered.tweet_id = "" }, v => { v.delivered.text = "" }, v => { v.delivered.extra = 1 },
      v => { v.schema_version = 4 }, v => { v.png_sha256 = "0".repeat(64) }, v => { v.posting_window = null }]) {
      const bad = structuredClone(response); change(bad)
      await assert.rejects(validateGraphicResponse(bad, request, manifest), undefined, change.toString())
    }
    // Inspection is read-only: no write, review, approval or dispatch happened.
    assert.equal(t.dispatches.length, 0)
    assert.deepEqual(t.get("invented-hot10-delivered"), posted)
  })
})
