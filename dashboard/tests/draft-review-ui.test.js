import test from "node:test"
import assert from "node:assert/strict"
import { draftReviewControls, draftTextLength, revisionKey, reviewQueueOrder, manualReviewLabel } from "../lib/draft-review-ui.js"
import { nwsDraft } from "./fixtures/nws-warning-evidence.js"

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

test("joint graphic review cannot be replaced by the text-only confirmation", () => {
  const controls = draftReviewControls({ status: "pending", review_status: "media_review_required" })
  assert.equal(controls.canReview, false)
  assert.equal(controls.canApprove, false)
  assert.equal(controls.canSchedule, false)
  assert.equal(controls.canEdit, true)
})

test("local command preview retains its own authority currentness contract", () => {
  const preview = { local_preview: true, operator_role: "publisher", type: "severe_weather", status: "pending", review_status: "passed", review_kind: "human" }
  assert.equal(draftReviewControls(preview).canApprove, true)
  assert.equal(draftReviewControls(preview).sourceHold, null)
  assert.equal(draftReviewControls({ ...preview, operator_role: "viewer" }).canApprove, false)
})

test("client refresh cannot put a newer held warning above usable copy or mutate the received queue", () => {
  const fresh = nwsDraft(), held = structuredClone(fresh)
  fresh.id = "fresh"; fresh.created_at = "2026-01-01T00:10:00Z"
  held.id = "held"; held.created_at = "2026-01-02T00:00:00Z"
  held.review_context.two_bot.bundle.raw_signal_dump.source_evidence.feature.properties.expires = "2026-01-01T00:30:00Z"
  const other = { id: "other", type: "hot10", created_at: "2026-01-01T00:20:00Z" }
  const queue = [held, fresh, other], before = structuredClone(queue), now = Date.parse("2026-01-01T01:00:00Z")
  assert.deepEqual(reviewQueueOrder(queue, { now }).map(d => d.id), ["other", "fresh", "held"])
  assert.deepEqual(queue, before)
  assert.deepEqual(reviewQueueOrder(queue, { now, localPreview: true }).map(d => d.id), ["held", "other", "fresh"])
})


test("delegated review is attributed to the assistant and cannot schedule", () => {
  const draft = { status: "pending", review_status: "passed", review_kind: "delegated", automatic_publication: { enabled: true }, approval_policy: { can_auto_approve: true } }
  assert.equal(manualReviewLabel(draft), "assistant reviewed")
  assert.equal(manualReviewLabel({ review_kind: "human" }), "human reviewed")
  assert.equal(manualReviewLabel({ review_kind: "model" }), null)
  assert.equal(draftReviewControls(draft).canApprove, true)
  assert.equal(draftReviewControls(draft).canSchedule, false)
})
