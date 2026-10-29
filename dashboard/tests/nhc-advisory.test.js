import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { nhcAdvisoryForDisplay, nhcAdvisoryTiming } from "../lib/nhc-advisory-evidence.js"
import { nhcAdvisoryValidation } from "../lib/nhc-advisory-validation.js"
import { NhcAdvisoryEvidence } from "../app/components/NhcAdvisoryEvidence.js"
import { draftReviewControls, reviewQueueOrder } from "../lib/draft-review-ui.js"
import { body } from "./helpers/warning-gist-harness.js"
import { importedAdvisory, withNhcGist, NHC_NOW } from "./helpers/nhc-advisory-harness.js"

const seed = importedAdvisory()
const fixture = () => JSON.parse(seed.raw_state).drafts[0]
const bundle = draft => draft.review_context.two_bot.bundle
const record = draft => bundle(draft).raw_signal_dump.nhc_advisory
const at = Date.parse(NHC_NOW)
const COPY = "Up to 3 inches of rain could trigger flash flooding and mudslides in Example Province tonight, NHC forecasts."

test("imported advisory has Python/JS byte parity and a complete inert source card", () => {
  const draft = fixture(), original = structuredClone(draft)
  assert.equal(draft.status, "pending")
  assert.deepEqual(nhcAdvisoryValidation(draft, at), { blocked: false })
  const source = nhcAdvisoryForDisplay(draft)
  assert.equal(source.status, "present")
  const html = renderToStaticMarkup(React.createElement(NhcAdvisoryEvidence, { draft, now: at }))
  for (const value of ["National Hurricane Center (NHC)", "Tropical Depression Inventa / Advisory 34", "RAINFALL", "Example Province",
    "2026-10-29T21:00:00Z", "2026-10-29T21:26:00Z", "Upstream expiry", "Not stated by NHC (unknown)",
    "Operator freshness deadline (UTC)", "2026-10-29T21:56:00Z (our recheck limit, not an NHC expiry)",
    "not a report that", "does not authenticate", "fresh source check", "https://www.nhc.noaa.gov/text/MIATCPEP5.shtml",
    "<summary>Read the saved original bulletin</summary>"])
    assert.ok(html.includes(value), value)
  // Unknown upstream expiry is never presented as a time or as the deadline.
  assert.doesNotMatch(html, /Message expires|Expires \(UTC\)|valid until/i)
  assert.equal(record(draft).times.upstream_expiry, null)
  assert.deepEqual(draft, original)
})

for (const [name, change] of [
  ["bulletin bytes", draft => { record(draft).bulletin_utf8 = record(draft).bulletin_utf8.replace("Example Province", "Example Provinces") }],
  ["bulletin hash", draft => { record(draft).bulletin_sha256 = "0".repeat(64) }],
  ["synthetic expiry", draft => { record(draft).times.upstream_expiry = "2026-10-30T03:00:00Z" }],
  ["expiry fact", draft => { bundle(draft).current_facts.push({ ...bundle(draft).current_facts[0], label: "expires_at", value: "2026-10-30T03:00:00Z" }) }],
  ["changed fact", draft => { bundle(draft).current_facts[4].value = "RAINFALL: record rainfall observed." }],
  ["extended deadline", draft => { record(draft).times.operator_recheck_deadline = "2026-10-29T22:56:00Z" }],
  ["other host", draft => { bundle(draft).raw_signal_dump.source_url = "https://www.nhc.noaa.gov.example.test/text/MIATCPEP5.shtml" }],
  ["held correction", draft => { draft.review_context.nhc_advisory_source_hold = "nhc_advisory_current_source_changed" }],
  ["type", draft => { draft.type = "fire" }],
  ["attribution", draft => { bundle(draft).raw_signal_dump.source_name = "Another issuer" }],
]) test(`changed retained advisory is held before mutation: ${name}`, async () => {
  await withNhcGist(async t => {
    const changed = t.state(); change(changed.drafts[0]); t.replace(changed)
    const before = t.raw()
    const result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: t.policy.source_sha256 }))
    assert.equal(result.status, 409, JSON.stringify(result.body))
    assert.equal(result.body.code, "nhc_advisory_source_review_required")
    assert.equal(t.raw(), before); assert.equal(t.patches.length, 0); assert.equal(t.dispatches.length, 0)
  })
})

test("clock boundaries and copy bindings block browser review and approval", () => {
  const draft = fixture()
  assert.equal(nhcAdvisoryTiming(draft, Date.parse("2026-10-29T21:55:59Z")).blocked, false)
  const late = nhcAdvisoryTiming(draft, Date.parse("2026-10-29T21:56:00Z"))
  assert.equal(late.blocked, true); assert.match(late.message, /operator freshness deadline passed \(this is not an NHC expiry\)/)
  assert.equal(nhcAdvisoryTiming(draft, Date.parse("2026-10-29T21:25:59Z")).blocked, true)
  for (const text of ["Rain could trigger flash flooding in Example Province tonight.",
    "Up to 3 inches of rain could trigger flash flooding tonight, NHC forecasts.",
    "NHC: heavy rain in Example Province tonight.",
    "Example Province has flooded, NHC says it could get worse.",
    "Record rain could flood Example Province, NHC forecasts."]) {
    const edited = { ...draft, text, review_status: "passed" }
    assert.equal(nhcAdvisoryTiming(edited, at).blocked, true, text)
    const controls = draftReviewControls(edited, at)
    assert.equal(controls.canApprove, false, text); assert.ok(controls.sourceHold, text)
  }
  assert.equal(nhcAdvisoryTiming({ ...draft, text: COPY.replace("NHC forecasts", "the National Hurricane Center forecasts") }, at).blocked, false)
  const queue = reviewQueueOrder([{ ...draft, id: "late", review_context: { ...draft.review_context, nhc_advisory_source_hold: "x" } }, draft], { now: at })
  assert.equal(queue[0].id, draft.id)
})

test("a displayed or human_reviewed label grants no review, approval or dispatch", async () => {
  await withNhcGist(async t => {
    const labelled = t.state()
    Object.assign(labelled.drafts[0], { human_reviewed: true, review_kind: "human", review_status: "passed", reviewed_by: "invented" })
    t.replace(labelled)
    const listed = (await t.list())[0]
    assert.equal(listed.review_status, "needs_revalidation"); assert.equal(listed.review_kind, null)
    assert.equal(draftReviewControls(listed, at).canApprove, false)
    const before = t.raw()
    const result = await t.post(body(t.get(), "approve"))
    assert.equal(result.status, 409); assert.equal(result.body.code, "review_required")
    assert.equal(t.raw(), before); assert.equal(t.dispatches.length, 0)
  })
})

test("actual edit, human review and manual approval through the handlers keep the retained advisory exact", async () => {
  await withNhcGist(async t => {
    const original = structuredClone(record(t.get()))
    const listed = (await t.list())[0]
    assert.equal(listed.review_status, "needs_revalidation")
    assert.equal(draftReviewControls(listed, at).canReview, true)
    const text = "Example Province could see up to 3 inches of rain and flash flooding tonight, NHC forecasts."
    let result = await t.post(body(t.get(), "edit", { editedText: text }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.get().text, text); assert.equal(t.get().content_revision, 2)
    result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: listed.editorial_policy.policy_sha256 }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.get().review_binding.kind, "human")
    // An edit after review invalidates the obsolete review; approval then refuses.
    result = await t.post(body(t.get(), "edit", { editedText: COPY }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.get().review_binding, undefined)
    result = await t.post(body(t.get(), "approve"))
    assert.equal(result.status, 409); assert.equal(result.body.code, "review_required")
    result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: listed.editorial_policy.policy_sha256 }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    result = await t.post(body(t.get(), "approve"))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.dispatches.length, 1); assert.equal(t.dispatches[0].inputs.mode, "manual_tweet")
    assert.equal(t.get().status, "approved"); assert.equal(t.get().approval_binding.mode, "manual")
    assert.deepEqual(record(t.get()), original)
  })
})

test("an edit that drops attribution is saved but cannot be reviewed", async () => {
  await withNhcGist(async t => {
    let result = await t.post(body(t.get(), "edit", { editedText: "Up to 3 inches of rain could flood Example Province tonight." }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    const before = t.raw()
    result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: t.policy.source_sha256 }))
    assert.equal(result.status, 409); assert.equal(result.body.code, "nhc_advisory_source_review_required")
    assert.equal(t.raw(), before)
  })
})

test("the operator deadline passing before review refuses without writing", async () => {
  await withNhcGist(async t => {
    t.at("2026-10-29T21:56:00.000Z")
    const before = t.raw()
    const result = await t.post(body(t.get(), "review", { reviewConfirmed: true, expectedPolicySha256: t.policy.source_sha256 }))
    assert.equal(result.status, 409); assert.equal(result.body.code, "nhc_advisory_source_review_required")
    assert.match(result.body.error, /not an NHC expiry/)
    assert.equal(t.raw(), before); assert.equal(t.patches.length, 0)
  })
})
