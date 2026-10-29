/** Actual drafts route for the new hazard image families on an invented Gist.
 * See helpers/gist-hazard-harness.js for the only intercepted boundaries.
 */
import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import test from "node:test"
import { policy } from "./helpers/review-policy.js"
import { FAMILIES, attach, body, joint, pythonJSON, revision, withGist } from "./helpers/gist-hazard-harness.js"
import { approvalIsCurrent, fingerprint, reviewIsCurrent } from "../lib/draft-revisions.js"
import { GIST_HAZARD_KINDS, gistMediaCurrentness, validGistMedia } from "../lib/gist-media.js"

const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const parityCode = trap + `
from datetime import datetime, timezone
from src.media import gist_hazard_media as hazard
value=json.load(sys.stdin)
# The raw stored Gist text, as the sender reads it: JS objects lose float spellings.
draft=next(d for d in json.loads(value['raw_state'])['drafts'] if d['id']==value['draft_id'])
bundle=draft['review_context']['two_bot']['bundle']
times=[hazard.currentness(draft['media_attachment']['kind'],bundle,datetime.fromtimestamp(ms/1000,timezone.utc)) for ms in value['times']]
valid=[]
for candidate in value['descriptors']:
    try: hazard.validate_descriptor(candidate,bundle); valid.append(True)
    except ValueError: valid.append(False)
print(json.dumps(dict(times=[t[0] if t else None for t in times],valid=valid)))
`
for (const family of FAMILIES) {
  test(`${family}: real PNG -> lossless attach -> joint review -> manual approval -> one dispatch`, async () => {
    await withGist(family, async t => {
      const { original, preview, attached } = await attach(t)
      assert.ok(GIST_HAZARD_KINDS.includes(preview.media_kind))
      assert.equal(preview.schema_version, 4)
      assert.deepEqual(attached.media_attachment, preview.media_descriptor)
      assert.equal(attached.content_revision, original.content_revision + 1)
      assert.equal(attached.text, original.text)
      assert.ok(t.raw().includes(t.rawBundle), "original source numeric tokens must be retained")
      assert.ok(attached.revision_history.some(row => row.content_revision === original.content_revision
        && !Object.hasOwn(row, "media_attachment") && fingerprint(row.review_context?.two_bot?.bundle) === fingerprint(original.review_context.two_bot.bundle)))
      // Idempotent repeat: no new revision or history row.
      assert.equal((await t.post(body(attached, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))).status, 200)
      assert.deepEqual(revision(t.get()), revision(attached))
      const textOnly = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) }))
      assert.equal(textOnly.status, 409); assert.equal(textOnly.body.code, "media_review_required")
      assert.equal((await t.post(body(t.get(), "approve"))).status, 409)
      const reviewed = await joint(t)
      assert.equal(reviewed.review_binding.kind, "human_media")
      assert.equal(reviewed.review_binding.media_sha256, fingerprint(preview.media_descriptor))
      assert.equal(reviewIsCurrent(reviewed, policy), true)
      const listed = (await t.list()).find(d => d.id === t.primary)
      assert.equal(listed.media_attachment_sha256, fingerprint(preview.media_descriptor))
      assert.equal(listed.review_status, "passed"); assert.equal(listed.review_kind, "human_media")
      const auto = await t.post(body(reviewed, "auto_approve"))
      assert.equal(auto.status, 409); assert.equal(t.dispatches.length, 0)
      const approved = await t.post(body(reviewed, "approve"))
      assert.equal(approved.status, 200, JSON.stringify(approved.body))
      const saved = t.get()
      assert.equal(approvalIsCurrent(saved, "manual", policy), true)
      assert.deepEqual(saved.media_attachment, preview.media_descriptor)
      assert.equal(t.dispatches.length, 1)
      assert.deepEqual(t.dispatches[0].inputs, { mode: "manual_tweet", tweet_text: original.text, draft_id: original.id, publish_intent_id: saved.publish_intent_id })
      assert.equal((await t.post(body(saved, "approve"))).status, 409); assert.equal(t.dispatches.length, 1)
      assert.deepEqual(t.state().unrelated, { preserve: true })
    })
  })

  test(`${family}: expired source keeps the preview inspectable but approval refuses without writing`, async () => {
    await withGist(family, async t => {
      await attach(t); await joint(t)
      t.at(t.clock.expired)
      const historical = t.preview(t.get())
      assert.equal(historical.posting_window.status, "unavailable")
      const before = t.raw(), count = t.patches.length
      const refused = await t.post(body(t.get(), "approve"))
      assert.equal(refused.status, 409, JSON.stringify(refused.body))
      assert.match(refused.body.code, /^media_/)
      assert.match(refused.body.error, /cannot be approved for posting; the draft is unchanged/)
      assert.equal(t.raw(), before); assert.equal(t.patches.length, count); assert.equal(t.dispatches.length, 0)
      assert.equal(gistMediaCurrentness(t.get(), t.clock.expired).code, refused.body.code)
      t.at(t.clock.current)
      assert.equal(gistMediaCurrentness(t.get(), t.clock.current), null)
    })
  })

  test(`${family}: removal after review revokes it, keeps history and is idempotent`, async () => {
    await withGist(family, async t => {
      const { preview } = await attach(t); const reviewed = await joint(t)
      const removed = await t.post(body(reviewed, "remove_graphic"))
      assert.equal(removed.status, 200, JSON.stringify(removed.body))
      assert.equal(Object.hasOwn(t.get(), "media_attachment"), false)
      assert.equal(t.get().content_revision, reviewed.content_revision + 1)
      assert.equal(reviewIsCurrent(t.get(), policy), false)
      assert.ok(t.get().revision_history.some(row => row.content_revision === reviewed.content_revision
        && row.review_binding?.kind === "human_media" && fingerprint(row.media_attachment) === fingerprint(preview.media_descriptor)))
      const after = revision(t.get())
      assert.equal((await t.post(body(t.get(), "remove_graphic"))).status, 200)
      assert.deepEqual(revision(t.get()), after); assert.equal(t.dispatches.length, 0)
      assert.ok(t.raw().includes(t.rawBundle))
    })
  })

  for (const change of ["png", "delivery", "expanded", "kind_swap", "renderer", "extra_descriptor", "synthetic", "schema3", "draft", "posting_window_missing"]) {
    test(`${family}: attach refuses a changed ${change} preview response without writing`, async () => {
      await withGist(family, async t => {
        const original = t.get(), preview = t.preview(original), before = t.raw()
        const result = await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
        assert.equal(result.status, 409, JSON.stringify(result.body)); assert.equal(t.raw(), before)
        assert.equal(t.patches.length, 0); assert.equal(t.dispatches.length, 0)
      }, { changePreview(value) {
        if (change === "png") value.png_base64 = Buffer.from("invented changed bytes").toString("base64")
        if (change === "delivery") value.delivery_text += " changed"
        if (change === "expanded") value.expanded_description += " changed"
        if (change === "kind_swap") value.media_kind = value.media_descriptor.kind = GIST_HAZARD_KINDS.find(k => k !== value.media_kind) ?? "gist_temperature_comparator_v1"
        if (change === "renderer") value.media_descriptor.renderer.files["src/media/gist_hazard_media.py"] = "0".repeat(64)
        if (change === "extra_descriptor") value.media_descriptor.url = "https://example.invalid/arbitrary.png"
        if (change === "synthetic") value.media_descriptor.synthetic = true
        if (change === "schema3") value.schema_version = 3
        if (change === "draft") value.draft_id = `invented-${family}-secondary`
        if (change === "posting_window_missing") delete value.posting_window
      } })
    })
  }

  test(`${family}: caller media, stale revision, draft switch and unresolved delivery cannot attach`, async () => {
    await withGist(family, async t => {
      const original = t.get(), preview = t.preview(original)
      const forged = await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256,
        media_attachment: { kind: "arbitrary", url: "https://example.invalid/pixel" }, png_base64: Buffer.from("caller bytes").toString("base64") }))
      assert.equal(forged.status, 200, JSON.stringify(forged.body))
      assert.deepEqual(t.get().media_attachment, preview.media_descriptor)
      assert.ok(!t.raw().includes("example.invalid"))
      // The secondary draft names its own revision; the old preview identity is rechecked server-side.
      const other = t.get(t.secondary), stale = { ...body(other, "attach_graphic", { expectedMediaSha256: "0".repeat(64) }) }
      assert.equal((await t.post(stale)).status, 409)
      assert.equal(Object.hasOwn(t.get(t.secondary), "media_attachment"), false)
      assert.equal((await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))).status, 409)
      const state = t.state(), selected = state.drafts.find(d => d.id === t.secondary)
      state.publish_ledger[selected.event_id] = { phase: "unknown", publish_intent_id: "invented-unknown-attempt" }
      t.replaceState(state)
      const fenced = await t.post(body(t.get(t.secondary), "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
      assert.equal(fenced.status, 409); assert.equal(fenced.body.code, "publication_unresolved")
      assert.equal(t.dispatches.length, 0)
    })
  })

  test(`${family}: text edit after joint review revokes it and stale approval cannot dispatch`, async () => {
    await withGist(family, async t => {
      await attach(t); const reviewed = await joint(t)
      assert.equal((await t.post(body(reviewed, "edit", { editedText: "Invented changed text needs a new joint review." }))).status, 200)
      assert.equal(reviewIsCurrent(t.get(), policy), false)
      assert.deepEqual(t.get().media_attachment, reviewed.media_attachment)
      assert.equal((await t.post(body(reviewed, "approve"))).status, 409)
      assert.equal((await t.post(body(t.get(), "approve"))).status, 409)
      assert.equal(t.dispatches.length, 0)
    })
  })

  for (const invalid of [null, { kind: "gist_pm25_forecast_v1" }, { kind: "experimental_pg_image" }]) {
    test(`${family}: present broken attachment ${JSON.stringify(invalid)} is removable without a usable PNG`, async () => {
      await withGist(family, async t => {
        await attach(t)
        const expected = JSON.stringify(t.get().media_attachment), raw = t.raw().replace(expected, JSON.stringify(invalid))
        assert.notEqual(raw, t.raw()); t.replaceState(raw)
        const before = t.get(), previewCount = t.previews.length
        assert.equal((await t.post(body(before, "approve"))).status, 409)
        assert.equal((await t.post(body(before, "remove_graphic"))).status, 200)
        assert.equal(Object.hasOwn(t.get(), "media_attachment"), false)
        assert.equal(t.previews.length, previewCount)
        assert.equal(t.dispatches.length, 0)
      })
    })
  }

  test(`${family}: browser-free JS currentness and recipe validation match the Python sender`, async () => {
    await withGist(family, async t => {
      const { attached } = await attach(t)
      const start = t.clock.current, end = t.clock.expired
      const times = [start - 86400000 * 3, start, end - 1, end, end + 1, start + 86400000 * 3]
      const mutations = [d => d, d => { d.description.delivery_text += " " }, d => { d.synthetic = true }, d => { d.extra = 1 },
        d => { d.renderer.pillow = "12.3.0" }, d => { d.image.byte_count = 750001 }, d => { d.source.bundle_sha256 = "0".repeat(64) },
        d => { d.description.derivation = "other" }, d => { d.description.delivery_text = "x".repeat(1001) },
        // Isolated guards: a stale code pin, and a rehashed text within 1000 scalars but over 1000 bytes.
        d => { d.renderer.files["src/media/gist_hazard_media.py"] = "0".repeat(64) },
        d => { Object.assign(d.description, { delivery_text: "é".repeat(600), delivery_scalars: 600, delivery_bytes: 1200,
          delivery_sha256: createHash("sha256").update("é".repeat(600)).digest("hex") }) }]
      const descriptors = mutations.map(change => { const value = structuredClone(attached.media_attachment); change(value); return value })
      const py = pythonJSON(parityCode, { raw_state: t.raw(), draft_id: attached.id, times, descriptors })
      assert.deepEqual(times.map(ms => gistMediaCurrentness(attached, ms)?.code ?? null), py.times)
      assert.deepEqual(descriptors.map(value => validGistMedia(attached, value)), py.valid)
      assert.deepEqual(py.valid, [true, false, false, false, false, false, false, false, false, false, false])
      const two = structuredClone(attached); two.hot10_rows = [{ rank: 1 }]
      assert.equal(validGistMedia(two), false)
    })
  })
}

for (const family of FAMILIES) {
  test(`${family}: a quote-reference-only edit revokes joint review but keeps text, source and image`, async () => {
    await withGist(family, async t => {
      await attach(t); const reviewed = await joint(t)
      const items = [{ claim: { start: 0, end: 8, text: reviewed.text.slice(0, 8) }, sources: [{ pointer: "/current_facts/0" }] }]
      const result = await t.post(body(reviewed, "edit", { editedText: reviewed.text, operator_claim_references: items }))
      if (family === "pm25") {
        // Existing limit: the retained PM2.5 grid fact is not a quotable scalar. Nothing changes.
        assert.equal(result.status, 422, JSON.stringify(result.body))
        assert.deepEqual(revision(t.get()), revision(reviewed)); assert.equal(reviewIsCurrent(t.get(), policy), true)
        return
      }
      assert.equal(result.status, 200, JSON.stringify(result.body))
      const edited = t.get()
      assert.equal(edited.text, reviewed.text)
      assert.deepEqual(edited.media_attachment, reviewed.media_attachment)
      assert.equal(fingerprint(edited.review_context.two_bot.bundle), fingerprint(reviewed.review_context.two_bot.bundle))
      assert.equal(edited.content_revision, reviewed.content_revision + 1)
      assert.equal(reviewIsCurrent(edited, policy), false)
      assert.equal(validGistMedia(edited), true)
      assert.equal((await t.post(body(edited, "approve"))).status, 409)
      const again = await joint(t)
      assert.equal(again.review_binding.kind, "human_media")
      assert.equal((await t.post(body(again, "approve"))).status, 200)
      assert.equal(t.dispatches.length, 1)
    })
  })

  test(`${family}: a broken present recipe is replaced by the current preview as one revision`, async () => {
    await withGist(family, async t => {
      const { preview } = await attach(t)
      const stored = JSON.stringify(t.get().media_attachment)
      const broken = structuredClone(t.get().media_attachment); broken.description.delivery_text += " stale"
      t.replaceState(t.raw().replace(stored, JSON.stringify(broken)))
      const before = t.get()
      assert.equal(validGistMedia(before), false)
      const replaced = await t.post(body(before, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
      assert.equal(replaced.status, 200, JSON.stringify(replaced.body))
      assert.deepEqual(t.get().media_attachment, preview.media_descriptor)
      assert.equal(t.get().content_revision, before.content_revision + 1)
      assert.ok(t.get().revision_history.some(row => fingerprint(row.media_attachment ?? null) === fingerprint(broken)))
    })
  })
}

test("modis: a fire source without a reviewed family is refused before any preview request", async () => {
  if (!FAMILIES.includes("modis")) return
  await withGist("modis", async t => {
    const raw = t.raw(), changed = raw.split('"source_product": "MODIS_NRT"').join('"source_product": "VIIRS_SNPP_NRT"')
    assert.notEqual(changed, raw); t.replaceState(changed)
    const before = t.raw()
    const result = await t.post(body(t.get(), "attach_graphic", { expectedMediaSha256: "a".repeat(64) }))
    assert.equal(result.status, 409); assert.match(result.body.error, /no reviewed post-image family/)
    assert.equal(t.previews.length, 0); assert.equal(t.raw(), before); assert.equal(t.dispatches.length, 0)
  })
})
