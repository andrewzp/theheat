import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { officialWarningForDisplay, officialWarningTiming } from "../lib/official-warning-evidence.js"
import { officialWarningValidation } from "../lib/official-warning-validation.js"
import { OfficialWarningEvidence } from "../app/components/OfficialWarningEvidence.js"
import { draftReviewControls } from "../lib/draft-review-ui.js"
import { generatedWarning, withWarningGist, body, NOW } from "./helpers/warning-gist-harness.js"

const fixture = () => JSON.parse(generatedWarning().raw_state).drafts[0]
const metadata = draft => draft.review_context.two_bot.bundle.raw_signal_dump.official_warning
const at = Date.parse(NOW)

test("actual generated warning has byte/hash parity in Python and JS and complete inert source display", () => {
  const draft = fixture(), original = structuredClone(draft)
  assert.deepEqual(officialWarningValidation(draft, at), { blocked: false })
  const source = officialWarningForDisplay(draft)
  assert.equal(source.status, "present")
  const html = renderToStaticMarkup(React.createElement(OfficialWarningEvidence, { draft, now: at }))
  for (const value of ["Invented Warning Agency", "Example Island", "2026-10-30T00:00:00Z", "INVENTED official bulletin", "not a report that", "does not authenticate", "fresh source check"])
    assert.ok(html.includes(value), value)
  assert.deepEqual(draft, original)
})

for (const [name, change] of [
  ["bytes", draft => { metadata(draft).source_utf8 += "changed" }],
  ["metadata whitespace", draft => { metadata(draft).metadata_utf8 += " " }],
  ["evidence identity", draft => { metadata(draft).evidence_sha256 = "0".repeat(64) }],
  ["attribution", draft => { draft.review_context.two_bot.bundle.raw_signal_dump.source_name = "Another issuer" }],
  ["held correction", draft => { draft.review_context.official_warning_source_hold = "changed" }],
  ["type", draft => { draft.type = "fire" }],
]) test(`changed warning is held before mutation: ${name}`, async () => {
  await withWarningGist(async t => {
    const changed = t.state(); change(changed.drafts[0]); t.replace(changed)
    const before = t.raw()
    const result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: t.policy.source_sha256 }))
    assert.equal(result.status, 409)
    assert.equal(result.body.code, "warning_source_review_required")
    assert.equal(t.raw(), before); assert.equal(t.patches.length, 0); assert.equal(t.dispatches.length, 0)
  })
})

test("expiry and missing modality block browser review; the agency name is not warning modality", () => {
  const draft = fixture()
  assert.equal(officialWarningTiming(draft, Date.parse("2026-10-30T00:00:00Z")).blocked, true)
  draft.text = "Invented Warning Agency: dangerous winds on Example Island."
  assert.equal(officialWarningTiming(draft, at).blocked, true)
  draft.review_status = "passed"
  assert.equal(draftReviewControls(draft, at).canApprove, false)
})

test("actual authenticated edit, quote reference, human review and manual approval preserve source bytes", async () => {
  await withWarningGist(async t => {
    const original = structuredClone(metadata(t.get()))
    const text = "Example Island faces possible dangerous winds tonight, Invented Warning Agency warns."
    let result = await t.post(body(t.get(), "edit", { editedText: text, operator_claim_references: [{ claim: { start: 0, end: 14, text: "Example Island" }, sources: [{ pointer: "/current_facts/2" }] }] }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.get().text, text)
    assert.equal(t.get().approval_binding, undefined)
    const listed = (await t.list())[0]
    result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: listed.editorial_policy.policy_sha256 }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    result = await t.post(body(t.get(), "approve"))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.dispatches.length, 1)
    assert.equal(t.get().status, "approved")
    assert.deepEqual(metadata(t.get()), original)
  })
})

test("expired saved source refuses review without writing", async () => {
  await withWarningGist(async t => {
    t.at("2026-10-30T00:00:00Z")
    const old = t.raw()
    const response = await t.post(body(t.get(), "review", { reviewConfirmed: true }))
    assert.equal(response.status, 409)
    assert.equal(response.body.code, "warning_source_review_required")
    assert.equal(t.raw(), old)
  })
})
