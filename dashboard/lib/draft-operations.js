// The per-operation draft domain checks and transitions, extracted unchanged from
// app/api/drafts/route.js so the legacy direct path and the P00c serialized consumer run the
// SAME functions (ROUTE-CONTRACT-v2 §2): mutability, pending / unresolved-publication guards,
// review / approval / scheduling transitions, attestations and decision binding. Only the
// sources of request-time inputs are parameters (the request body, media preparation, the
// clock and the publish-intent id); the legacy route passes exactly what it used before.
import { requiredAttestations } from "./gist-media.js"
import { HOLD_MESSAGES, automaticTextHold } from "./automatic-text.js"
import { dashboardEditorialPolicy } from "./editorial-policy.js"
import { dashboardAutomaticPolicy } from "./publication-control.js"
import { assertMediaCurrent, assertSavedSourceTiming } from "./draft-decision-confirm.js"
import {
  authorizeDraft,
  draftIdentity,
  hasUnresolvedPublish,
  invalidateText,
  invalidateMediaAttachment,
  recordJointMediaReview,
  fingerprint,
  recordHumanReview,
  reviewIsCurrent,
  revokeApproval,
  textHash,
} from "./draft-revisions.js"

export const DRAFT_ACTIONS = ["approve", "reject", "edit", "review", "auto_approve", "cancel_auto_approve", "select_candidate", "bulk_reject_below", "attach_graphic", "remove_graphic"]
export function fail(message, status = 409, code = "revision_conflict") {
  throw Object.assign(new Error(message), { status, code })
}

export function validIdentity(value) {
  return value && Number.isSafeInteger(value.content_revision) && value.content_revision >= 0 &&
    Number.isSafeInteger(value.decision_revision) && value.decision_revision >= 0 &&
    /^[a-f0-9]{64}$/.test(value.text_sha256 || "") &&
    /^[a-f0-9]{64}$/.test(value.evidence_sha256 || "")
}

export function assertExpected(draft, expectedRevision) {
  if (!validIdentity(expectedRevision)) fail("Refresh the draft before changing it.", 400, "missing_revision")
  const current = { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 }
  if (Object.keys(current).some((key) => current[key] !== expectedRevision[key])) fail("This draft changed. Review the latest version and try again.")
}

export function assertMutable(draft, state) {
  if (!["pending", "approved"].includes(draft.status)) fail("This draft can no longer be changed.", 409, "draft_not_editable")
  if (hasUnresolvedPublish(draft, state)) fail("A publication attempt needs reconciliation before this draft can change.", 409, "publication_unresolved")
}

export function assertPending(draft) {
  if (draft.status !== "pending") fail("This draft is already awaiting publication. Cancel or edit it before approving again.", 409, "draft_not_pending")
}

export function assertReviewed(draft, policy, modelOnly = false) {
  if (!policy) fail("Editorial policy unverified. Wait for a fresh matching bot report before reviewing or approving.", 409, "editorial_policy_unverified")
  if (!reviewIsCurrent(draft, policy)) fail("Review this exact version against its source evidence first.", 409, "review_required")
  if (modelOnly && draft.review_binding?.kind !== "model") {
    fail("Automatic scheduling requires current model checks. Human-reviewed drafts can be posted manually.", 409, "model_review_required")
  }
}

// Bulk rejection: the drafts it selects, and the transition applied to each one.
export function bulkRejectSelected(draft, threshold) {
  return draft.status === "pending" && (draft.score?.total || 0) < threshold
}

export function applyBulkReject(record, currentState, expected, threshold) {
  assertExpected(record, expected)
  assertMutable(record, currentState)
  assertPending(record)
  revokeApproval(record)
  record.status = "rejected"
  record.rejected_reason = `bulk_reject_below_${threshold}`
  return record
}

// One single-draft operation. `prepareMedia(draft, expectedMediaSha256, retainedInputSha256)` returns
// the checked media descriptor; `now()` is the decision clock; `newPublishIntentId()` names an approval.
export async function applyDraftAction(draft, state, { runtimeReport = null, action, body, prepareMedia,
  now = () => new Date(), newPublishIntentId = () => globalThis.crypto.randomUUID() }) {
  let publishIntentId
  let autoApproveAt
  let minutes
  let checkedPolicySha = null
  let checkedAutomaticEpoch = null
  const nowMs = () => now().getTime()
  const editedText = body.editedText, delayMinutes = body.delayMinutes, candidateRank = body.candidateRank
  assertMutable(draft, state)
  if (["review", "approve", "auto_approve"].includes(action)) assertSavedSourceTiming(draft)
  const editorialPolicy = dashboardEditorialPolicy(state, { runtimeReport })
  if (action === "attach_graphic") {
    // Store-backed images also name their exact retained input (CRW packet or published asset).
    const descriptor = await prepareMedia(draft, body.expectedMediaSha256, body.retainedInputSha256 ?? null)
    invalidateMediaAttachment(draft, descriptor)
  } else if (action === "remove_graphic") {
    invalidateMediaAttachment(draft, null)
  } else if (action === "edit") {
    const previousRevision = draft.content_revision
    try {
      if (Object.hasOwn(body, "operator_claim_references")) invalidateText(draft, editedText, body.operator_claim_references)
      else invalidateText(draft, editedText)
    } catch (error) { fail(error.message, 422, "invalid_draft_edit") }
    if (draft.content_revision !== previousRevision) {
      draft.manual_override = true
      draft.post_error = null
    }
  } else if (action === "select_candidate") {
    const rank = Number(candidateRank)
    if (!Number.isInteger(rank) || rank < 1) fail("Invalid candidate rank", 400, "invalid_candidate")
    const candidates = draft.candidates || []
    const selected = candidates.find((candidate) => candidate.rank === rank)
    if (!selected) fail("Candidate not found", 404, "candidate_not_found")
    if (typeof selected.text !== "string" || !selected.text.trim() || Array.from(selected.text).length > 280) fail("Invalid candidate text", 400, "invalid_candidate")
    textHash(selected.text)
    invalidateText(draft, selected.text)
    draft.candidate_score = selected.score
    draft.selected_candidate_rank = selected.rank
    draft.manual_override = false
    draft.post_error = null
    draft.candidates = [selected, ...candidates.filter((candidate) => candidate.rank !== rank)]
  } else if (action === "reject") {
    revokeApproval(draft)
    draft.status = "rejected"
    draft.post_error = null
  } else if (action === "cancel_auto_approve") {
    revokeApproval(draft)
    draft.status = "pending"
  } else if (action === "review") {
    assertPending(draft)
    const joint = Object.hasOwn(draft, "media_attachment")
    if (joint) {
      if (body.mediaReviewConfirmed !== true) fail("Review the text, image and full description together.", 409, "media_review_required")
      const attached = draft.media_attachment
      const retained = attached?.source?.packet_artifact_sha256 ?? attached?.asset?.manifest_sha256 ?? null
      const descriptor = await prepareMedia(draft, body.expectedMediaSha256, retained)
      if (fingerprint(descriptor) !== fingerprint(draft.media_attachment)) fail("The attached graphic changed; preview it again.", 409, "media_changed")
      const required = requiredAttestations(draft.media_attachment), supplied = body.publishedAttestations ?? {}
      if (!supplied || typeof supplied !== "object" || Array.isArray(supplied) || Object.keys(supplied).length !== required.length
          || !required.every(name => supplied[name] === true))
        fail("Confirm every published-image attestation together with the text and image.", 409, "media_attestation_required")
    }
    if (body.reviewConfirmed !== true) fail("Confirm that you checked this text against its source evidence.", 400, "review_confirmation_required")
    if (draft.revision_conflicts?.length) fail("Resolve the conflicting text with an edit before reviewing it.")
    if (!editorialPolicy.policy) fail(editorialPolicy.reason, 409, "editorial_policy_unverified")
    if (body.expectedPolicySha256 !== editorialPolicy.policy_sha256) fail("Editorial policy changed since your confirmation. Refresh and review again.", 409, "editorial_policy_changed")
    if (joint) recordJointMediaReview(draft, editorialPolicy.policy, body.publishedAttestations ?? null)
    else recordHumanReview(draft, editorialPolicy.policy)
  } else if (action === "auto_approve") {
    const publication = dashboardAutomaticPolicy(state, { runtimeReport })
    if (!publication.enabled) fail(publication.reason, 409, "automatic_publication_paused")
    checkedAutomaticEpoch = publication.epoch
    assertPending(draft)
    assertReviewed(draft, editorialPolicy.policy, true)
    const textHold = automaticTextHold(draft.text)
    if (textHold) fail(HOLD_MESSAGES[textHold], 409, textHold)
    if (["air_quality_hazard", "dust_event"].includes(draft.type)) {
      fail("Air-quality forecasts are armed only by their own current-source check, never from the dashboard.", 409, "air_quality_auto_owner")
    }
    const policy = draft.approval_policy || {}
    if (policy.can_auto_approve === false) fail("This draft type requires manual approval", 400, "manual_only")
    minutes = Number(delayMinutes ?? policy.recommended_delay_minutes ?? 30)
    if (!Number.isFinite(minutes) || minutes < 5 || minutes > 1440) fail("Delay must be between 5 and 1440 minutes", 400, "invalid_delay")
    autoApproveAt = new Date(nowMs() + minutes * 60 * 1000).toISOString()
    revokeApproval(draft)
    authorizeDraft(draft, "auto", null, publication.epoch, editorialPolicy.policy)
    draft.auto_approve_at = autoApproveAt
    draft.auto_approve_requested_at = new Date(nowMs()).toISOString()
    draft.approval_mode = "auto"
    draft.post_error = null
  } else if (action === "approve") {
    assertPending(draft)
    assertReviewed(draft, editorialPolicy.policy)
    assertMediaCurrent(draft)
    publishIntentId = newPublishIntentId()
    revokeApproval(draft)
    authorizeDraft(draft, "manual", publishIntentId, null, editorialPolicy.policy)
    draft.status = "approved"
    draft.approved_at = new Date(nowMs()).toISOString()
    draft.approval_mode = "manual"
    draft.post_error = null
    draft.publish_intent_id = publishIntentId
    draft.publish_requested_at = new Date(nowMs()).toISOString()
  }
  if (["review", "approve", "auto_approve"].includes(action)) checkedPolicySha = editorialPolicy.policy_sha256
  return { draft, publishIntentId, autoApproveAt, minutes, checkedPolicySha, checkedAutomaticEpoch }
}
