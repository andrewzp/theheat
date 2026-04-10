import { readStateStore, updateDraftStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"

export const runtime = "nodejs"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

function gistHeaders() {
  const h = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) h.Authorization = `token ${GITHUB_TOKEN}`
  return h
}

// GET — return pending drafts
export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  try {
    const state = await readStateStore()
    const drafts = (state.drafts || [])
      .filter((d) => d.status === "pending")
      .sort((a, b) => {
        const priorityA = (a.score?.total || 0) + (a.candidate_score?.total || 0) * 0.35
        const priorityB = (b.score?.total || 0) + (b.candidate_score?.total || 0) * 0.35
        const scoreDiff = priorityB - priorityA
        if (scoreDiff !== 0) return scoreDiff
        return new Date(b.created_at || 0) - new Date(a.created_at || 0)
      })
    return Response.json({ drafts })
  } catch (e) {
    return Response.json({ drafts: [], error: e.message })
  }
}

// POST — approve, reject, or edit a draft
export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  const { action, draftId, editedText, delayMinutes, candidateRank } = await request.json()

  if (!["approve", "reject", "edit", "auto_approve", "cancel_auto_approve", "select_candidate"].includes(action)) {
    return Response.json({ error: "Invalid action" }, { status: 400 })
  }

  try {
    const state = await readStateStore()
    const draft = (state.drafts || []).find((candidate) => candidate.id === draftId)
    if (!draft) {
      return Response.json({ error: "Draft not found" }, { status: 404 })
    }

    if (action === "reject") {
      await updateDraftStore(draftId, async (draftRecord) => {
        draftRecord.status = "rejected"
        delete draftRecord.auto_approve_at
        delete draftRecord.auto_approve_requested_at
        draftRecord.post_error = null
        delete draftRecord.publish_intent_id
        return draftRecord
      })
      return Response.json({ ok: true, action: "rejected" })
    }

    if (action === "edit") {
      if (!editedText || editedText.length > 280) {
        return Response.json({ error: "Invalid text" }, { status: 400 })
      }
      await updateDraftStore(draftId, async (draftRecord) => {
        draftRecord.text = editedText
        draftRecord.manual_override = true
        draftRecord.post_error = null
        delete draftRecord.publish_intent_id
        return draftRecord
      })
      return Response.json({ ok: true, action: "edited" })
    }

    if (action === "select_candidate") {
      const rank = Number(candidateRank)
      if (!Number.isFinite(rank)) {
        return Response.json({ error: "Invalid candidate rank" }, { status: 400 })
      }
      const candidates = draft.candidates || []
      const selected = candidates.find((candidate) => candidate.rank === rank)
      if (!selected) {
        return Response.json({ error: "Candidate not found" }, { status: 404 })
      }
      const { draft: updatedDraft } = await updateDraftStore(draftId, async (draftRecord) => {
        const currentCandidates = draftRecord.candidates || []
        const nextSelected = currentCandidates.find((candidate) => candidate.rank === rank)
        if (!nextSelected) {
          return null
        }
        draftRecord.text = nextSelected.text
        draftRecord.candidate_score = nextSelected.score
        draftRecord.selected_candidate_rank = nextSelected.rank
        draftRecord.manual_override = false
        draftRecord.candidates = [
          nextSelected,
          ...currentCandidates.filter((candidate) => candidate.rank !== rank),
        ]
        draftRecord.post_error = null
        delete draftRecord.publish_intent_id
        return draftRecord
      })
      if (!updatedDraft) {
        return Response.json({ error: "Candidate not found" }, { status: 404 })
      }
      return Response.json({ ok: true, action: "selected_candidate" })
    }

    if (action === "auto_approve") {
      const policy = draft.approval_policy || {}
      if (policy.can_auto_approve === false) {
        return Response.json({ error: "This draft type requires manual approval" }, { status: 400 })
      }
      const requestedMinutes = delayMinutes ?? policy.recommended_delay_minutes ?? 30
      const minutes = Number(requestedMinutes)
      if (!Number.isFinite(minutes) || minutes < 5 || minutes > 1440) {
        return Response.json({ error: "Delay must be between 5 and 1440 minutes" }, { status: 400 })
      }
      const autoApproveAt = new Date(Date.now() + minutes * 60 * 1000).toISOString()
      await updateDraftStore(draftId, async (draftRecord) => {
        draftRecord.auto_approve_at = autoApproveAt
        draftRecord.auto_approve_requested_at = new Date().toISOString()
        draftRecord.approval_mode = "auto"
        draftRecord.post_error = null
        delete draftRecord.publish_intent_id
        return draftRecord
      })
      return Response.json({ ok: true, action: "auto_approved", autoApproveAt, minutes })
    }

    if (action === "cancel_auto_approve") {
      await updateDraftStore(draftId, async (draftRecord) => {
        delete draftRecord.auto_approve_at
        delete draftRecord.auto_approve_requested_at
        if (draftRecord.approval_mode === "auto") {
          draftRecord.approval_mode = "manual"
        }
        delete draftRecord.publish_intent_id
        return draftRecord
      })
      return Response.json({ ok: true, action: "cancelled_auto_approve" })
    }

    if (action === "approve") {
      const publishIntentId = crypto.randomUUID()
      const { draft: approvedDraft } = await updateDraftStore(draftId, async (draftRecord) => {
        draftRecord.status = "approved"
        draftRecord.approved_at = new Date().toISOString()
        delete draftRecord.auto_approve_at
        delete draftRecord.auto_approve_requested_at
        draftRecord.approval_mode = "manual"
        draftRecord.post_error = null
        draftRecord.publish_intent_id = publishIntentId
        draftRecord.publish_requested_at = new Date().toISOString()
        return draftRecord
      })

      if (!approvedDraft) {
        return Response.json({ error: "Draft not found" }, { status: 404 })
      }

      // Trigger GitHub Actions to post the tweet
      const res = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/bot.yml/dispatches`,
        {
          method: "POST",
          headers: { ...gistHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            ref: "main",
            inputs: {
              mode: "manual_tweet",
              tweet_text: approvedDraft.text,
              draft_id: approvedDraft.id,
              publish_intent_id: publishIntentId,
            },
          }),
        }
      )

      if (res.ok || res.status === 204) {
        return Response.json({ ok: true, action: "approved" })
      }

      const errorText = await res.text()
      await updateDraftStore(draftId, async (draftRecord) => {
        draftRecord.status = "pending"
        draftRecord.post_error = `Failed to trigger workflow: ${res.status}`
        delete draftRecord.publish_intent_id
        delete draftRecord.publish_requested_at
        return draftRecord
      })
      return Response.json(
        { error: `Failed to trigger workflow: ${res.status} ${errorText}` },
        { status: 500 }
      )
    }
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
