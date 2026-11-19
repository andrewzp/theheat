/** Invented AWC parser bytes through actual PNG and Gist draft routes. No live calls. */
import assert from "node:assert/strict"
import test from "node:test"
import { withGist, attach, joint, body } from "./helpers/gist-hazard-harness.js"
import { policy } from "./helpers/review-policy.js"
import { approvalIsCurrent, fingerprint, reviewIsCurrent } from "../lib/draft-revisions.js"
import { validGistMedia, gistMediaCurrentness } from "../lib/gist-media.js"
import { validateGraphicResponse } from "../lib/graphic-preview.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

test("AWC: actual PNG, lossless attachment, current joint review and manual dispatch only", async () => {
  await withGist("awc", async t => {
    const { original, preview, attached } = await attach(t)
    assert.equal(preview.media_kind, "gist_awc_observed_pair_v1")
    assert.equal(preview.media_descriptor.template_version, "p31-awc-airport-pair-2")
    assert.equal(preview.media_descriptor.adapter_version, "p31-awc-observed-pair-2")
    assert.equal(preview.media_descriptor.description.derivation, "awc_pair_delivery_v2")
    assert.equal(preview.source_context.kind, "awc_airport_pair")
    assert.equal(preview.source_context.points[0].temperature_c, -20)
    assert.equal(validGistMedia(attached), true)
    assert.equal(attached.content_revision, original.content_revision + 1)
    assert.equal(attached.text, original.text)
    const reviewed = await joint(t)
    assert.equal(reviewIsCurrent(reviewed, policy), true)
    assert.equal((await t.post(body(reviewed, "auto_approve"))).status, 409)
    assert.equal(t.dispatches.length, 0)
    const response = await t.post(body(reviewed, "approve"))
    assert.equal(response.status, 200, JSON.stringify(response.body))
    assert.equal(approvalIsCurrent(t.get(), "manual", policy), true)
    assert.equal(t.dispatches.length, 1)
    assert.equal(t.dispatches[0].inputs.mode, "manual_tweet")
    assert.deepEqual(t.get().review_context.two_bot.bundle, original.review_context.two_bot.bundle)
  })
})

test("AWC: changed displayed point or PNG cannot satisfy the bound preview", async () => {
  await withGist("awc", async t => {
    const { preview, attached } = await attach(t)
    const request = t.previews[0]
    await validateGraphicResponse(preview, request, manifest)
    const changed = structuredClone(preview)
    changed.source_context.points[0].temperature_c = -20.1
    await assert.rejects(validateGraphicResponse(changed, request, manifest), /invalid preview/)
    const png = structuredClone(preview)
    png.png_base64 = "AAAA"
    await assert.rejects(validateGraphicResponse(png, request, manifest))
    for (const [field, old] of [["template_version", "p31-awc-airport-pair-1"],
      ["adapter_version", "p31-awc-observed-pair-1"], ["derivation", "awc_pair_delivery_v1"]]) {
      const response = structuredClone(preview)
      if (field === "derivation") response.media_descriptor.description[field] = old
      else response.media_descriptor[field] = old
      // Rehash the envelope: refusal must come from recipe semantics, not merely
      // an unchanged digest after changing one field.
      response.media_descriptor_sha256 = fingerprint(response.media_descriptor)
      await assert.rejects(validateGraphicResponse(response, request, manifest), /invalid preview/)
      const draft = structuredClone(attached)
      draft.media_attachment = response.media_descriptor
      assert.equal(validGistMedia(draft), false)
    }
  })
})

test("AWC: expiry after joint review refuses approval without dispatch or source refresh", async () => {
  await withGist("awc", async t => {
    await attach(t)
    await joint(t)
    const source = structuredClone(t.get().review_context.two_bot.bundle)
    t.at(t.clock.expired)
    assert.equal(gistMediaCurrentness(t.get()).code, "media_source_stale")
    assert.equal((await t.post(body(t.get(), "approve"))).status, 409)
    assert.equal(t.dispatches.length, 0)
    assert.deepEqual(t.get().review_context.two_bot.bundle, source)
  })
})
