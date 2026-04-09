import { readStateStore, writeStateStore } from "../../../lib/state-store.js"

export const runtime = "nodejs"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

function gistHeaders() {
  const h = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) h.Authorization = `token ${GITHUB_TOKEN}`
  return h
}

// GET — return pending drafts
export async function GET() {
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
  const { action, draftId, editedText, delayMinutes, candidateRank } = await request.json()

  if (!["approve", "reject", "edit", "auto_approve", "cancel_auto_approve", "select_candidate"].includes(action)) {
    return Response.json({ error: "Invalid action" }, { status: 400 })
  }

  try {
    const state = await readStateStore()
    const drafts = state.drafts || []
    const draft = drafts.find((d) => d.id === draftId)

    if (!draft) {
      return Response.json({ error: "Draft not found" }, { status: 404 })
    }

    if (action === "reject") {
      draft.status = "rejected"
      delete draft.auto_approve_at
      delete draft.auto_approve_requested_at
      await writeStateStore(state)
      return Response.json({ ok: true, action: "rejected" })
    }

    if (action === "edit") {
      if (!editedText || editedText.length > 280) {
        return Response.json({ error: "Invalid text" }, { status: 400 })
      }
      draft.text = editedText
      draft.manual_override = true
      await writeStateStore(state)
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
      draft.text = selected.text
      draft.candidate_score = selected.score
      draft.selected_candidate_rank = selected.rank
      draft.manual_override = false
      draft.candidates = [
        selected,
        ...candidates.filter((candidate) => candidate.rank !== rank),
      ]
      await writeStateStore(state)
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
      draft.auto_approve_at = autoApproveAt
      draft.auto_approve_requested_at = new Date().toISOString()
      draft.approval_mode = "auto"
      await writeStateStore(state)
      return Response.json({ ok: true, action: "auto_approved", autoApproveAt, minutes })
    }

    if (action === "cancel_auto_approve") {
      delete draft.auto_approve_at
      delete draft.auto_approve_requested_at
      if (draft.approval_mode === "auto") {
        draft.approval_mode = "manual"
      }
      await writeStateStore(state)
      return Response.json({ ok: true, action: "cancelled_auto_approve" })
    }

    if (action === "approve") {
      // Trigger GitHub Actions to post the tweet
      const res = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/bot.yml/dispatches`,
        {
          method: "POST",
          headers: { ...gistHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            ref: "main",
            inputs: { mode: "manual_tweet", tweet_text: draft.text, draft_id: draft.id },
          }),
        }
      )

      if (res.ok || res.status === 204) {
        draft.status = "approved"
        draft.approved_at = new Date().toISOString()
        delete draft.auto_approve_at
        delete draft.auto_approve_requested_at
        draft.approval_mode = "manual"
        await writeStateStore(state)
        return Response.json({ ok: true, action: "approved" })
      }

      return Response.json({ error: "Failed to trigger workflow" }, { status: 500 })
    }
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
