import { prepareGistMedia } from "../../../lib/gist-media.js"
import { acceptLocalCommand, localCommandRequest, localDraftProjection, previewConfigured, previewError } from "../../../lib/draft-command-client.js"
import { dashboardEditorialPolicy } from "../../../lib/editorial-policy.js"
import { dashboardAutomaticPolicy } from "../../../lib/publication-control.js"
import { readStateStore, readStateWithRuntimeReport, updateDraftStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"
import { readJsonObject } from "../../../lib/request-json.js"
import { nwsSourceTiming } from "../../../lib/nws-source-timing.js"
import { confirmDraftDecision } from "../../../lib/draft-decision-confirm.js"
import { DRAFT_ACTIONS as ACTIONS, applyBulkReject, applyDraftAction, assertExpected, assertMutable, bulkRejectSelected, fail, validIdentity } from "../../../lib/draft-operations.js"
import { submitDraftUpdates, submittedResponse } from "../../../lib/gist-route-submit.js"
import { publicationAttempt } from "../../../lib/publication-recovery.js"
import {
  approvalIsCurrent,
  draftIdentity,
  hasUnresolvedPublish,
  projectDraft,
  revokeApproval,
  textHash,
} from "../../../lib/draft-revisions.js"

export const runtime = "nodejs"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

function githubHeaders() {
  const headers = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) headers.Authorization = `token ${GITHUB_TOKEN}`
  return headers
}

function projection(draft, state, local = null, runtimeReport = null) {
  if (local) return localDraftProjection(draft, state, local)
  try {
    return { ...projectDraft(draft, dashboardEditorialPolicy(state, { runtimeReport }).policy), editorial_policy: dashboardEditorialPolicy(state, { runtimeReport }), automatic_publication: dashboardAutomaticPolicy(state, { runtimeReport }), publish_blocked: hasUnresolvedPublish(draft, state),
      publish_attempt: hasUnresolvedPublish(draft, state) ? publicationAttempt(draft, state) : null }
  } catch (error) {
    return { ...draft, text: typeof draft.text === "string" ? draft.text : "[Invalid draft text]", revision_identity: null, review_status: "conflict", review_kind: null, publish_blocked: true, review_error: error.message }
  }
}

// Delivered posts whose confirmed receipt names a native image, newest first. Read-only:
// the Python preview rebuilds and verifies the exact delivered snapshot on request.
function deliveredGraphics(state, runtimeReport) {
  const ledger = state.publish_ledger && typeof state.publish_ledger === "object" ? state.publish_ledger : {}
  const hasMedia = draft => Object.hasOwn(draft, "media_attachment")
    || (Array.isArray(draft.revision_history) && draft.revision_history.some(row => row && Object.hasOwn(row, "media_attachment")))
  return (state.drafts || []).flatMap(draft => {
    const row = draft && ledger[draft.event_id]
    if (!row || row.phase !== "confirmed" || typeof row.tweet_id !== "string" || !row.tweet_id || !hasMedia(draft)
        || (draft.tweet_id !== row.tweet_id && !String(draft.post_error ?? "").startsWith("A prior revision was published"))) return []
    const confirmed = typeof row.confirmed_at === "string" ? row.confirmed_at : typeof row.at === "string" ? row.at : null
    return [{ ...projection(draft, state, null, runtimeReport), delivered: { tweet_id: row.tweet_id, confirmed_at: confirmed,
      text: typeof row.text === "string" ? row.text : null } }]
  }).sort((a, b) => String(b.delivered.confirmed_at).localeCompare(String(a.delivered.confirmed_at))).slice(0, 20)
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (new URL(request.url).searchParams.get("delivered") === "1") {
    try {
      if (previewConfigured()) return Response.json({ delivered: [], local_preview: true }, { headers: { "Cache-Control": "private, no-store" } })
      const { state, runtimeReport } = await readStateWithRuntimeReport()
      return Response.json({ delivered: deliveredGraphics(state, runtimeReport) }, { headers: { "Cache-Control": "private, no-store" } })
    } catch (error) {
      return Response.json({ delivered: [], error: error.message }, { status: 500 })
    }
  }
  try {
    if (previewConfigured() && new URL(request.url).searchParams.has("commandId")) {
      const id = new URL(request.url).searchParams.get("commandId")
      const { payload } = await localCommandRequest(request, `/commands/${id}`)
      return Response.json(payload, { headers: { "Cache-Control": "private, no-store" } })
    }
    const local = previewConfigured() ? (await localCommandRequest(request, "/state")).payload : null
    const { state, runtimeReport } = local ? { state: local.state, runtimeReport: null } : await readStateWithRuntimeReport()
    const now = Date.now()
    const drafts = (state.drafts || [])
      .filter((d) => ["pending", "approved"].includes(d.status))
      .sort((a, b) => {
        const sourceDiff = local ? 0 : Number(nwsSourceTiming(a, now).blocked) - Number(nwsSourceTiming(b, now).blocked)
        if (sourceDiff) return sourceDiff
        const priorityA = (a.score?.total || 0) + (a.candidate_score?.total || 0) * 0.35
        const priorityB = (b.score?.total || 0) + (b.candidate_score?.total || 0) * 0.35
        return priorityB - priorityA || new Date(b.created_at || 0) - new Date(a.created_at || 0)
      })
      .map((d) => ({ ...projection(d, state, local, runtimeReport), tweet_id: d.tweet_id ?? null }))
    return Response.json({ drafts, ...(local ? { local_preview: true, state_version: local.state_version, candidates: local.candidates || [], operator_role: local.role } : {}) }, { headers: { "Cache-Control": "private, no-store" } })
  } catch (error) {
    if (previewConfigured()) return previewError(error)
    return Response.json({ drafts: [], error: error.message }, { status: 500 })
  }
}

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (previewConfigured()) return acceptLocalCommand(request)
  const { body, error } = await readJsonObject(request, { strict: true })
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
      const targets = (state.drafts || []).filter((d) => bulkRejectSelected(d, threshold))
      // Validate the complete requested snapshot before the first write. Each
      // updater repeats this check because a later write can still conflict.
      for (const draft of targets) {
        assertExpected(draft, body.expectedRevisions?.[draft.id])
        assertMutable(draft, state)
      }
      // P00c route mode: each prepared rejection is collected, then ONE all-or-nothing command.
      const collected = []
      const collect = async (updates) => { collected.push(...updates); return { status: "collected" } }
      for (const draft of targets) {
        const expected = body.expectedRevisions[draft.id]
        const { draft: rejected, submitted } = await updateDraftStore(draft.id, (record, currentState) =>
          applyBulkReject(record, currentState, expected, threshold), { expectedRevision: expected, routeCommand: collect })
        if (submitted) continue
        if (!rejected) fail("A draft disappeared during the bulk action.")
        changedIds.push(draft.id)
      }
      if (collected.length) return submittedResponse(await submitDraftUpdates(collected, { operation: "bulk_reject_below" }))
      return Response.json({ ok: true, action: "bulk_rejected", count: changedIds.length, changedIds, threshold })
    }

    if (!validIdentity(expectedRevision)) fail("Refresh the draft before changing it.", 400, "missing_revision")
    let publishIntentId
    let autoApproveAt
    let minutes
    let checkedPolicySha = null
    let checkedAutomaticEpoch = null
    const { draft: updatedDraft, state: updatedState, runtimeReport: updatedReport = null, submitted } = await updateDraftStore(draftId, async (draft, state, { runtimeReport = null } = {}) => {
      assertExpected(draft, expectedRevision)
      const done = await applyDraftAction(draft, state, { runtimeReport, action, body,
        prepareMedia: (current, expectedMediaSha256, retained) => prepareGistMedia(request, current, expectedMediaSha256, undefined, retained) })
      ;({ publishIntentId, autoApproveAt, minutes, checkedPolicySha, checkedAutomaticEpoch } = done)
      return done.draft
    }, { expectedRevision, confirmContext: ["review", "approve", "auto_approve"].includes(action)
      ? (latestState, { runtimeReport = null } = {}) => confirmDraftDecision(latestState, { runtimeReport },
        { action, draftId, checkedPolicySha, checkedAutomaticEpoch }) : undefined,
      // P00c route mode: the same decision becomes a compare-and-swap command; the serialized
      // consumer repeats the confirmation above and (for approve) dispatches the manual sender.
      routeCommand: (updates) => submitDraftUpdates(updates, { operation: action,
        confirm: ["review", "approve", "auto_approve"].includes(action) ? { name: "draft_decision", action,
          checked_policy_sha256: checkedPolicySha, checked_automatic_epoch: action === "auto_approve" ? checkedAutomaticEpoch : null } : null,
        followUp: action === "approve" ? { kind: "bot_manual_tweet", publish_intent_id: publishIntentId } : null }) })

    if (submitted) return submittedResponse(submitted)
    if (!updatedDraft) fail("Draft not found", 404, "draft_not_found")
    if (action !== "approve") {
      const names = { edit: "edited", select_candidate: "selected_candidate", reject: "rejected", review: "reviewed", auto_approve: "auto_approved", cancel_auto_approve: "cancelled_auto_approve", attach_graphic: "graphic_attached", remove_graphic: "graphic_removed" }
      return Response.json({ ok: true, action: names[action], draft: projection(updatedDraft, updatedState, null, updatedReport), ...(autoApproveAt ? { autoApproveAt, minutes } : {}) })
    }

    if (!approvalIsCurrent(updatedDraft, "manual", dashboardEditorialPolicy(updatedState, { runtimeReport: updatedReport }).policy) || updatedDraft.publish_intent_id !== publishIntentId || hasUnresolvedPublish(updatedDraft, updatedState)) {
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
    if (res.ok || res.status === 204) return Response.json({ ok: true, action: "approved", draft: projection(updatedDraft, updatedState, null, updatedReport) })

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
