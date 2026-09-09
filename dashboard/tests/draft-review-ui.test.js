import test from "node:test"
import assert from "node:assert/strict"
import { draftReviewControls, draftTextLength, revisionKey } from "../lib/draft-review-ui.js"

test("revised, conflicted and unresolved drafts cannot be approved or scheduled", () => {
  for (const draft of [
    { status: "pending", review_status: "needs_revalidation" },
    { status: "pending", review_status: "conflict" },
    { status: "pending", review_status: "passed", review_kind: "model", publish_blocked: true },
  ]) {
    assert.equal(draftReviewControls(draft).canApprove, false)
    assert.equal(draftReviewControls(draft).canSchedule, false)
  }
  assert.equal(draftReviewControls({ status: "pending", review_status: "needs_revalidation" }).canReview, true)
  assert.equal(draftReviewControls({ status: "pending", review_status: "conflict" }).canReview, false)
})

test("human review only permits manual approval; queued text remains editable before submission", () => {
  const human = draftReviewControls({ status: "pending", review_status: "passed", review_kind: "human" })
  assert.equal(human.canApprove, true)
  assert.equal(human.canSchedule, false)
  const queued = draftReviewControls({ status: "approved", review_status: "passed", review_kind: "model" })
  assert.equal(queued.canEdit, true)
  assert.equal(queued.canApprove, false)
  assert.equal(queued.canReview, false)
  assert.equal(queued.canSchedule, false)
  assert.equal(draftReviewControls({ status: "posted", review_status: "passed", review_kind: "model" }).canEdit, false)
})

test("captured edit/review identities stop matching after revision, text or evidence changes", () => {
  const captured = { content_revision: 1, text_sha256: "text-a", evidence_sha256: "evidence-a" }
  const key = revisionKey(captured)
  for (const current of [
    { ...captured, content_revision: 2 },
    { ...captured, text_sha256: "text-b" },
    { ...captured, evidence_sha256: "evidence-b" },
    { ...captured, decision_revision: 1 },
  ]) assert.notEqual(revisionKey(current), key)
  assert.equal(revisionKey(structuredClone(captured)), key)
  assert.notEqual(revisionKey(null), key)
})

test("the draft counter counts astral emoji as code points rather than UTF-16 halves", () => {
  const text = "A storm update: " + "🌀".repeat(141)
  assert.ok(text.length > 280)
  assert.equal(draftTextLength(text), Array.from(text).length)
  assert.ok(draftTextLength(text) < 280)
})
