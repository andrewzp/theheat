import { dashboardAutomaticPolicy } from "../../../lib/publication-control.js"
import { readStateStore, updateDraftStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"
import { readJsonObject } from "../../../lib/request-json.js"
import {
  approvalIsCurrent,
  authorizeDraft,
  draftIdentity,
  hasUnresolvedPublish,
  invalidateText,
  projectDraft,
  recordHumanReview,
  reviewIsCurrent,
  revokeApproval,
  textHash,
} from "../../../lib/draft-revisions.js"

export const runtime = "nodejs"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"
const ACTIONS = ["approve", "reject", "edit", "review", "auto_approve", "cancel_auto_approve", "select_candidate", "bulk_reject_below"]

function githubHeaders() {
  const headers = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) headers.Authorization = `token ${GITHUB_TOKEN}`
  return headers
}

function fail(message, status = 409, code = "revision_conflict") {
  throw Object.assign(new Error(message), { status, code })
}

function validIdentity(value) {
  return value && Number.isSafeInteger(value.content_revision) && value.content_revision >= 0 &&
    Number.isSafeInteger(value.decision_revision) && value.decision_revision >= 0 &&
    /^[a-f0-9]{64}$/.test(value.text_sha256 || "") &&
    /^[a-f0-9]{64}$/.test(value.evidence_sha256 || "")
}

function assertExpected(draft, expectedRevision) {
  if (!validIdentity(expectedRevision)) fail("Refresh the draft before changing it.", 400, "missing_revision")
  const current = { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 }
  if (Object.keys(current).some((key) => current[key] !== expectedRevision[key])) fail("This draft changed. Review the latest version and try again.")
}

function assertMutable(draft, state) {
  if (!["pending", "approved"].includes(draft.status)) fail("This draft can no longer be changed.", 409, "draft_not_editable")
  if (hasUnresolvedPublish(draft, state)) fail("A publication attempt needs reconciliation before this draft can change.", 409, "publication_unresolved")
}

function assertPending(draft) {
  if (draft.status !== "pending") fail("This draft is already awaiting publication. Cancel or edit it before approving again.", 409, "draft_not_pending")
}

function assertReviewed(draft, modelOnly = false) {
  if (!reviewIsCurrent(draft)) fail("Review this exact version against its source evidence first.", 409, "review_required")
  if (modelOnly && draft.review_binding?.kind !== "model") {
    fail("Automatic scheduling requires current model checks. Human-reviewed drafts can be posted manually.", 409, "model_review_required")
  }
}

function projection(draft, state) {
  try {
    return { ...projectDraft(draft), automatic_publication: dashboardAutomaticPolicy(state), publish_blocked: hasUnresolvedPublish(draft, state) }
  } catch (error) {
    return { ...draft, text: typeof draft.text === "string" ? draft.text : "[Invalid draft text]", revision_identity: null, review_status: "conflict", review_kind: null, publish_blocked: true, review_error: error.message }
  }
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  try {
    const state = await readStateStore()
    const drafts = (state.drafts || [])
      .filter((d) => ["pending", "approved"].includes(d.status))
      .sort((a, b) => {
        const priorityA = (a.score?.total || 0) + (a.candidate_score?.total || 0) * 0.35
        const priorityB = (b.score?.total || 0) + (b.candidate_score?.total || 0) * 0.35
        return priorityB - priorityA || new Date(b.created_at || 0) - new Date(a.created_at || 0)
      })
      .map((d) => ({ ...projection(d, state), tweet_id: d.tweet_id ?? null }))
    return Response.json({ drafts })
  } catch (error) {
    return Response.json({ drafts: [], error: error.message }, { status: 500 })
  }
}

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  const { body, error } = await readJsonObject(request)
  if (error) return error
  const { action, draftId, editedText, delayMinutes, candidateRank, expectedRevision } = body
  if (!ACTIONS.includes(action)) return Response.json({ error: "Invalid action" }, { status: 400 })
  if (action === "edit" && (typeof editedText !== "string" || !editedText.trim() || Array.from(editedText).length > 280)) {
    return Response.json({ error: "Invalid text" }, { status: 400 })
  }

  const changedIds = []
  try {
    if (action === "edit") textHash(editedText)
    if (action === "bulk_reject_below") {
      const threshold = Number(delayMinutes ?? 72)
      if (!Number.isFinite(threshold) || threshold < 0 || threshold > 100) fail("Invalid threshold (0-100)", 400, "invalid_threshold")
      const state = await readStateStore()
      const targets = (state.drafts || []).filter((d) => d.status === "pending" && (d.score?.total || 0) < threshold)
      // Validate the complete requested snapshot before the first write. Each
      // updater repeats this check because a later write can still conflict.
      for (const draft of targets) {
        assertExpected(draft, body.expectedRevisions?.[draft.id])
        assertMutable(draft, state)
      }
      for (const draft of targets) {
        const expected = body.expectedRevisions[draft.id]
        const { draft: rejected } = await updateDraftStore(draft.id, (record, currentState) => {
          assertExpected(record, expected)
          assertMutable(record, currentState)
          assertPending(record)
          revokeApproval(record)
          record.status = "rejected"
          record.rejected_reason = `bulk_reject_below_${threshold}`
          return record
        }, { expectedRevision: expected })
        if (!rejected) fail("A draft disappeared during the bulk action.")
        changedIds.push(draft.id)
      }
      return Response.json({ ok: true, action: "bulk_rejected", count: changedIds.length, changedIds, threshold })
    }

    if (!validIdentity(expectedRevision)) fail("Refresh the draft before changing it.", 400, "missing_revision")
    let publishIntentId
    let autoApproveAt
    let minutes
    const { draft: updatedDraft, state: updatedState } = await updateDraftStore(draftId, (draft, state) => {
      assertExpected(draft, expectedRevision)
      assertMutable(draft, state)
      if (action === "edit") {
        invalidateText(draft, editedText)
        draft.manual_override = true
        draft.post_error = null
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
        if (body.reviewConfirmed !== true) fail("Confirm that you checked this text against its source evidence.", 400, "review_confirmation_required")
        if (draft.revision_conflicts?.length) fail("Resolve the conflicting text with an edit before reviewing it.")
        revokeApproval(draft)
        recordHumanReview(draft)
      } else if (action === "auto_approve") {
        const publication = dashboardAutomaticPolicy(state)
        if (!publication.enabled) fail(publication.reason, 409, "automatic_publication_paused")
        assertPending(draft)
        assertReviewed(draft, true)
        const policy = draft.approval_policy || {}
        if (policy.can_auto_approve === false) fail("This draft type requires manual approval", 400, "manual_only")
        minutes = Number(delayMinutes ?? policy.recommended_delay_minutes ?? 30)
        if (!Number.isFinite(minutes) || minutes < 5 || minutes > 1440) fail("Delay must be between 5 and 1440 minutes", 400, "invalid_delay")
        autoApproveAt = new Date(Date.now() + minutes * 60 * 1000).toISOString()
        revokeApproval(draft)
        authorizeDraft(draft, "auto", null, publication.epoch)
        draft.auto_approve_at = autoApproveAt
        draft.auto_approve_requested_at = new Date().toISOString()
        draft.approval_mode = "auto"
        draft.post_error = null
      } else if (action === "approve") {
        assertPending(draft)
        assertReviewed(draft)
        publishIntentId = crypto.randomUUID()
        revokeApproval(draft)
        authorizeDraft(draft, "manual", publishIntentId)
        draft.status = "approved"
        draft.approved_at = new Date().toISOString()
        draft.approval_mode = "manual"
        draft.post_error = null
        draft.publish_intent_id = publishIntentId
        draft.publish_requested_at = new Date().toISOString()
      }
      return draft
    }, { expectedRevision })

    if (!updatedDraft) fail("Draft not found", 404, "draft_not_found")
    if (action !== "approve") {
      const names = { edit: "edited", select_candidate: "selected_candidate", reject: "rejected", review: "reviewed", auto_approve: "auto_approved", cancel_auto_approve: "cancelled_auto_approve" }
      return Response.json({ ok: true, action: names[action], draft: projection(updatedDraft, updatedState), ...(autoApproveAt ? { autoApproveAt, minutes } : {}) })
    }

    if (!approvalIsCurrent(updatedDraft, "manual") || updatedDraft.publish_intent_id !== publishIntentId || hasUnresolvedPublish(updatedDraft, updatedState)) {
      fail("This draft changed before dispatch. Review its current version before publishing.")
    }
    let res
    try {
      res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/bot.yml/dispatches`, {
        method: "POST",
        headers: { ...githubHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: {
          mode: "manual_tweet",
          tweet_text: updatedDraft.text,
          draft_id: updatedDraft.id,
          publish_intent_id: publishIntentId,
        } }),
      })
    } catch {
      // The request may have reached GitHub. Keep its exact approval/intent;
      // erasing it and retrying would conceal a potentially queued workflow.
      return Response.json({ error: "Unable to confirm workflow dispatch. Approval remains queued; check the workflow before retrying.", code: "dispatch_uncertain" }, { status: 503 })
    }
    if (res.ok || res.status === 204) return Response.json({ ok: true, action: "approved", draft: projection(updatedDraft, updatedState) })

    const errorText = await res.text()
    // A failed old dispatch must never roll back a newer edit or approval.
    let rollbackSkipped = false
    try {
      await updateDraftStore(draftId, (draft, state) => {
        if (draft.publish_intent_id !== publishIntentId || draft.status !== "approved" || hasUnresolvedPublish(draft, state)) fail("Publication state changed while dispatching.")
        revokeApproval(draft)
        draft.status = "pending"
        draft.post_error = `Failed to trigger workflow: ${res.status}`
        return draft
      }, { expectedRevision: { ...draftIdentity(updatedDraft), decision_revision: updatedDraft.decision_revision ?? 0 } })
    } catch (rollbackError) {
      if (rollbackError.status === 409 || rollbackError.statusCode === 409) rollbackSkipped = true
      else throw rollbackError
    }
    return Response.json({ error: `Failed to trigger workflow: ${res.status} ${errorText}`, rollbackSkipped }, { status: 500 })
  } catch (failure) {
    const invalidData = /^(Invalid (?:draft text|content revision|decision revision|Unicode)|Draft text must|Revision evidence must)/.test(failure.message)
    return Response.json({ error: failure.message, code: failure.code || (invalidData ? "invalid_draft_data" : undefined), ...(action === "bulk_reject_below" ? { changedIds, count: changedIds.length } : {}) }, { status: failure.status || failure.statusCode || (invalidData ? 422 : 500) })
  }
}
