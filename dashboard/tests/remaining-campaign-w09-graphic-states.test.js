/** W09.3 joint graphic workflow states for every completed Gist post-image family.
 * Real Python previews (current and after the source window) for the native hazard
 * families and the store-backed families (invented local media store); the actual
 * drafts route over an invented Gist for the hold -> remove -> text-only recovery.
 * Python runs with sockets trapped; nothing is fetched or published.
 */
import assert from "node:assert/strict"
import test from "node:test"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreviewFigure, GraphicState, MediaControls } from "../app/components/GraphicPreview.js"
import { MEDIA_HOLD_MESSAGES } from "../lib/graphic-preview.js"
import { policy } from "./helpers/review-policy.js"
import { FAMILIES, attach, body, joint, pythonJSON, withGist } from "./helpers/gist-hazard-harness.js"
import { fingerprint, reviewIsCurrent } from "../lib/draft-revisions.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const code = trap + `
from pathlib import Path
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import decision_revision, draft_identity
value=json.load(sys.stdin)
store=None
if value['family'] in ('crw','radar','cone'):
    from src.media import gist_assets
    from tests.gist_store_helpers import CLOCKS, retain, saved_state
    store=gist_assets.SQLiteMediaStore(Path(value['store']))
    retained=retain(value['family'],store)
else:
    from tests.gist_hazard_helpers import CLOCKS, saved_state
    retained=None
state=saved_state(value['family'])
draft=state['drafts'][0]
request={'draft_id':draft['id'],'expected_revision':{**draft_identity(draft),'decision_revision':decision_revision(draft)},
  'expected_policy_source_sha256':value['policy'],'expected_preview_runtime_sha256':value['runtime'],'format':'png',
  **({'retained_input_sha256':retained} if retained else {})}
out={}
for name,at in (('current',CLOCKS[value['family']][0]),('historical',CLOCKS[value['family']][1])):
    with freeze_time(at):
        out[name]=json.loads(build_preview(request,policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget(),store=store))
draft['revision_identity']=request['expected_revision']
print(json.dumps(dict(draft=draft,**out),ensure_ascii=False))
`
const fixtures = {}
function fixture(family) {
  if (!fixtures[family]) {
    const folder = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "theheat-w09-states-")))
    fixtures[family] = pythonJSON(code, { family, store: path.join(folder, "media.sqlite3"),
      policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
  }
  return structuredClone(fixtures[family])
}
const render = element => renderToStaticMarkup(element)
const visible = html => html.replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ")
const stateOf = (draft, preview, held = false) => {
  const html = render(React.createElement(GraphicState, { draft, preview, held }))
  return { key: html.match(/data-graphic-state="([a-z_]+)"/)[1], text: visible(html) }
}

for (const family of ["pm25", "modis", "viirs", "hot10", "crw", "radar", "cone"]) {
  test(`${family}: preview, expiry, attached, needs review, unavailable and held are distinct actionable states`, () => {
    const { draft, current, historical } = fixture(family)
    const ready = value => ({ status: "ready", value, url: "blob:invented" })
    assert.equal(current.posting_window.status, "current"); assert.equal(historical.posting_window.status, "unavailable")
    assert.equal(stateOf(draft, { status: "idle" }).key, "none")
    assert.equal(stateOf(draft, ready(current)).key, "preview")
    const expired = stateOf(draft, ready(historical))
    assert.equal(expired.key, "preview_expired"); assert.ok(expired.text.includes(historical.posting_window.reason.replace(/\.$/, "")))
    assert.match(expired.text, /the text can still be reviewed and posted without it/)
    // The same recipe binds both previews: the clock never changes what was attached.
    assert.equal(historical.media_descriptor_sha256, current.media_descriptor_sha256)
    const attached = { ...draft, media_attachment: current.media_descriptor, media_attachment_sha256: current.media_descriptor_sha256,
      editorial_policy: { policy_sha256: "a".repeat(64) } }
    assert.equal(stateOf({ ...attached, review_status: "media_review_required" }, ready(current)).key, "needs_review")
    assert.equal(stateOf({ ...attached, review_status: "passed", review_kind: "human_media" }, ready(current)).key, "attached")
    const passedExpired = stateOf({ ...attached, review_status: "passed", review_kind: "human_media" }, ready(historical))
    assert.equal(passedExpired.key, "source_expired")
    assert.match(passedExpired.text, /cannot be approved or sent; inspect it here or remove it to post the text alone/)
    const message = MEDIA_HOLD_MESSAGES.media_source_unqualified
    const unavailable = stateOf({ ...attached, review_status: "media_review_required" }, { status: "error", message, hold: "media_source_unqualified" })
    // The hold text stays in the preview status line only; the state line points to it.
    assert.equal(unavailable.key, "attached_unavailable"); assert.ok(!unavailable.text.includes(message))
    assert.match(unavailable.text, /remove it to post the text alone/)
    // Removal stays offered while the image is unavailable; the historical figure stays inspectable.
    const controls = render(MediaControls({ draft: attached, preview: { status: "error", message }, reviewConfirmed: false, onConfirm() {}, onAction() {} }))
    assert.match(controls, /Remove graphic/); assert.doesNotMatch(controls, /Record joint review/)
    assert.match(render(React.createElement(GraphicPreviewFigure, { value: historical, url: "blob:invented" })), /Not postable now: /)
    assert.equal(stateOf(attached, { status: "idle" }, true).key, "held")
    assert.equal(stateOf(draft, { status: "error", message }).key, "unavailable")
  })
}

for (const family of FAMILIES) {
  test(`${family}: an unavailable graphic is an actionable hold; removing it keeps the text draft postable once`, async () => {
    const options = { previewFailure: false }
    await withGist(family, async t => {
      await attach(t); const reviewed = await joint(t)
      assert.equal((await t.post(body(reviewed, "edit", { editedText: reviewed.text + " Edited while the image is held." }))).status, 200)
      const edited = t.get()
      assert.equal(reviewIsCurrent(edited, policy), false); assert.deepEqual(edited.media_attachment, reviewed.media_attachment)
      options.previewFailure = true
      const before = t.raw()
      const held = await t.post(body(edited, "review", { reviewConfirmed: true, mediaReviewConfirmed: true,
        expectedMediaSha256: fingerprint(edited.media_attachment), expectedPolicySha256: fingerprint(policy) }))
      assert.equal(held.status, 409); assert.equal(t.raw(), before)
      assert.equal((await t.post(body(edited, "approve"))).status, 409)
      const removed = await t.post(body(edited, "remove_graphic"))
      assert.equal(removed.status, 200, JSON.stringify(removed.body))
      const textOnly = t.get()
      assert.equal(textOnly.text, edited.text); assert.equal(Object.hasOwn(textOnly, "media_attachment"), false)
      assert.ok(textOnly.revision_history.some(row => fingerprint(row.media_attachment ?? null) === fingerprint(reviewed.media_attachment)))
      const review = await t.post(body(textOnly, "review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) }))
      assert.equal(review.status, 200, JSON.stringify(review.body))
      assert.equal((await t.post(body(t.get(), "approve"))).status, 200)
      assert.equal(t.dispatches.length, 1); assert.equal(t.dispatches[0].inputs.tweet_text, edited.text)
    }, options)
  })
}

test("temperature comparator: the same states without a posting disclosure (its date rule runs at approval and send)", () => {
  // Schema-3 previews carry no posting window; only the shape the state line reads is needed here.
  const value = { schema_version: 3, media_descriptor_sha256: "c".repeat(64) }
  const draft = { id: "invented-temperature", type: "all_time_high", status: "pending", text: "Invented station comparison.",
    revision_identity: { content_revision: 1, decision_revision: 0, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) } }
  const ready = { status: "ready", value, url: "blob:invented" }
  assert.equal(stateOf(draft, ready).key, "preview")
  const attached = { ...draft, media_attachment: { kind: "gist_temperature_comparator_v1" }, media_attachment_sha256: "c".repeat(64) }
  assert.equal(stateOf({ ...attached, review_status: "media_review_required" }, ready).key, "needs_review")
  assert.equal(stateOf({ ...attached, review_status: "passed", review_kind: "delegated_media" }, ready).text,
    " Attached: reviewed together with this exact text (delegated, one manual post). ")
  assert.equal(stateOf(attached, { status: "error", message: "Invented refusal." }).key, "attached_unavailable")
})
