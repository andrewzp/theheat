import { policy, runtimeRun } from "./helpers/review-policy.js"
import test from "node:test"

// Explicit policy for these mocked legacy release scenarios.
process.env.THEHEAT_AUTOMATIC_PUBLICATION_ENABLED = "1"
process.env.THEHEAT_AUTOMATIC_PUBLICATION_EPOCH = "offline-test-release"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { authorizeDraft, approvalIsCurrent, draftIdentity, fingerprint, hasUnresolvedPublish,
  initializeRevision, invalidateText, projectDraft, recordHumanReview, recordModelReview, reviewIsCurrent, revokeApproval, textHash,
} from "./helpers/review-policy.js"

function reviewed() {
  const draft = { id: "d", event_id: "event", text: "40°C forecast", status: "pending", review_context: {
    two_bot: { bundle: { temperature: 40.0 }, fact_check: { passed: true, extracted_claims: ["40°C"] }, critic: { passed: true } },
  } }
  const proof = draft.review_context.two_bot
  proof.reviewed_text_sha256 = textHash(draft.text)
  proof.reviewed_policy_sha256 = fingerprint(policy)
  proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
  return initializeRevision(draft)
}

test("JS and Python use the same identity for real JSON numbers and Unicode", () => {
  const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/draft_revision_identity.json", import.meta.url), "utf8"))
  for (const item of cases) assert.deepEqual(draftIdentity(item.draft), item.identity, item.name)
})

test("changed and reverted text cannot inherit old claims, checks or authorization", () => {
  const draft = reviewed()
  authorizeDraft(draft, "auto")
  Object.assign(draft, { auto_approve_at: "old", autoship_on_critic_pass: true })
  const original = structuredClone(draft)
  invalidateText(draft, "50°C forecast")
  assert.equal(reviewIsCurrent(draft), false)
  assert.equal(approvalIsCurrent(draft), false)
  assert.equal(draft.auto_approve_at, undefined)
  assert.equal(draft.autoship_on_critic_pass, undefined)
  assert.equal(draft.review_context.two_bot.fact_check, undefined)
  assert.deepEqual(draft.revision_history[0].review_context, original.review_context)
  invalidateText(draft, original.text)
  draft.review_binding = original.review_binding
  assert.equal(draft.content_revision, 3)
  assert.equal(reviewIsCurrent(draft), false)
})

test("changing source evidence or check details invalidates a model review", () => {
  for (const change of [
    (d) => { d.review_context.two_bot.bundle.temperature = 50 },
    (d) => { d.review_context.source = "different source" },
    (d) => { d.review_context.two_bot.fact_check.extracted_claims = [] },
  ]) {
    const draft = reviewed()
    authorizeDraft(draft, "auto")
    change(draft)
    assert.equal(reviewIsCurrent(draft), false)
    assert.equal(approvalIsCurrent(draft), false)
  }
})

test("post-review text additions cannot acquire model review at save time", () => {
  const draft = reviewed()
  draft.text += " https://example.com"
  recordModelReview(draft)
  assert.equal(reviewIsCurrent(draft), false)
})

test("fresh human review permits explicit manual approval without fabricating model passes", () => {
  const draft = reviewed()
  invalidateText(draft, "Edited text")
  recordHumanReview(draft)
  assert.equal(reviewIsCurrent(draft), true)
  assert.equal(draft.review_context.two_bot.fact_check, undefined)
  assert.throws(() => authorizeDraft(draft, "auto"), /model review/)
  authorizeDraft(draft, "manual", "new-intent")
  assert.equal(approvalIsCurrent(draft, "manual"), true)
  draft.publish_intent_id = "another-intent"
  assert.equal(approvalIsCurrent(draft), false)
})

test("unknown attempts remain blockers regardless of age or newer failed attempts", () => {
  const draft = reviewed()
  const row = { at: "2020-01-01", intent_id: "attempt", phase: "unknown" }
  assert.equal(hasUnresolvedPublish(draft, { publish_ledger: { event: row } }), true)
  const clean = { phase: "not_sent" }
  assert.equal(hasUnresolvedPublish(draft, { publish_ledger: { event: clean } }), false)
  clean.attempt_conflicts = [row]
  assert.equal(hasUnresolvedPublish(draft, { publish_ledger: { event: clean } }), true)
})

test("no-op edit preserves reviewed and approved identity", () => {
  const draft = reviewed()
  authorizeDraft(draft, "auto")
  const original = structuredClone(draft)
  invalidateText(draft, draft.text)
  assert.deepEqual(draft, original)
})

test("cancelled same text cannot reuse its old decision binding or request snapshot", () => {
  const draft = reviewed()
  authorizeDraft(draft, "manual", "intent")
  const approval = structuredClone(draft.approval_binding)
  const snapshot = projectDraft(draft).revision_identity
  revokeApproval(draft)
  assert.equal(reviewIsCurrent(draft), true)
  assert.notDeepEqual(projectDraft(draft).revision_identity, snapshot)
  draft.approval_binding = approval
  draft.publish_intent_id = "intent"
  assert.equal(approvalIsCurrent(draft), false)
  authorizeDraft(draft, "manual", "new-intent")
  assert.equal(approvalIsCurrent(draft), true)
})

test("repeated model review requires fresh authorization", () => {
  const draft = reviewed()
  authorizeDraft(draft, "auto")
  recordModelReview(draft)
  assert.equal(reviewIsCurrent(draft), true)
  assert.equal(approvalIsCurrent(draft), false)
})

test("malformed Unicode edit is rejected without mutating the draft", () => {
  const draft = reviewed()
  authorizeDraft(draft, "auto")
  const original = structuredClone(draft)
  assert.throws(() => invalidateText(draft, "\ud800"), /Unicode/)
  assert.deepEqual(draft, original)
})

test("non-finite evidence and malformed Unicode never acquire review bindings", () => {
  const draft = reviewed()
  draft.review_context.bad = NaN
  assert.equal(reviewIsCurrent(draft), false)
  assert.throws(() => recordHumanReview(draft), /finite/)
  assert.throws(() => textHash("\ud800"), /Unicode/)
})
