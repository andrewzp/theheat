import { requireDashboardAuth } from "../../../lib/auth.js"
import { previewConfigured } from "../../../lib/draft-command-client.js"
import { draftIdentity } from "../../../lib/draft-revisions.js"
import { EPISODE_ACTIONS, applyEpisodeCommand, episodeView } from "../../../lib/hazard-episodes.js"
import { readJsonObject } from "../../../lib/request-json.js"
import { readStateStore, updateDraftStore } from "../../../lib/state-store.js"

// Physical-episode inspection and correction for one draft (W07.2/07.3/07.6).
// Same authority as the drafts route: dashboard auth + same-origin mutation rule,
// and every change names the exact draft revision it was decided against.
export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }
const DRAFT_ID = /^[A-Za-z0-9_.:-]{1,200}$/

function refuse(message, status, code) {
  return Response.json({ error: message, code }, { status, headers })
}

function localPreview() {
  return previewConfigured()
    ? refuse("Episode corrections are not available through local command authority.", 503, "episode_commands_unavailable")
    : null
}

function validIdentity(value) {
  return value && Number.isSafeInteger(value.content_revision) && value.content_revision >= 0 &&
    Number.isSafeInteger(value.decision_revision) && value.decision_revision >= 0 &&
    /^[a-f0-9]{64}$/.test(value.text_sha256 || "") && /^[a-f0-9]{64}$/.test(value.evidence_sha256 || "")
}

function sameRevision(draft, expected) {
  const current = { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 }
  return Object.keys(current).every(key => current[key] === expected[key])
}

export async function GET(request) {
  const error = requireDashboardAuth(request) || localPreview()
  if (error) return error
  const draftId = new URL(request.url).searchParams.get("draftId")
  if (!DRAFT_ID.test(draftId || "")) return refuse("Name one draft.", 400, "invalid_draft_id")
  try {
    const view = episodeView(await readStateStore(), draftId)
    return view ? Response.json(view, { headers }) : refuse("Draft not found.", 404, "draft_not_found")
  } catch (failure) {
    return refuse("Saved drafts are unavailable.", 503, failure.code || "state_unavailable")
  }
}

export async function POST(request) {
  const error = requireDashboardAuth(request) || localPreview()
  if (error) return error
  const { body, error: bodyError } = await readJsonObject(request, { strict: true })
  if (bodyError) return bodyError
  const { action, draftId, expectedRevision } = body
  if (!EPISODE_ACTIONS.includes(action)) return refuse("Invalid episode action.", 400, "invalid_episode_action")
  if (!DRAFT_ID.test(draftId || "")) return refuse("Name one draft.", 400, "invalid_draft_id")
  if (!validIdentity(expectedRevision)) return refuse("Refresh the draft before changing it.", 400, "missing_revision")
  try {
    const { draft, state } = await updateDraftStore(draftId, (record, current) => {
      if (!sameRevision(record, expectedRevision)) {
        throw Object.assign(new Error("This draft changed. Review the latest version and try again."), { status: 409, code: "revision_conflict" })
      }
      return applyEpisodeCommand(record, body, { state: current, actor: "dashboard" })
    }, { expectedRevision })
    if (!draft) return refuse("Draft not found.", 404, "draft_not_found")
    return Response.json({ ok: true, action, revision_identity: { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 },
      view: episodeView(state, draftId) }, { headers })
  } catch (failure) {
    return refuse(failure.message, failure.status || failure.statusCode || 500, failure.code || "episode_command_failed")
  }
}
