// P00c route mode: dashboard routes submit commands to the serialized consumer instead of
// PATCHing the Gist. The response retains the exact command body so a lost response can be
// resubmitted unchanged (POST /api/commands); success is never synthesized.
import { buildCommand, submitCommand } from "./gist-write-route.js"

// The dashboard authenticates one shared credential (see src/commands/command_roles.py).
export const DASHBOARD_ACTOR = "dashboard-operator"

export async function submitDraftUpdates(prepared, { operation, confirm = null, followUp = null }) {
  const { raw } = buildCommand({ action: "draft_update", producerKind: "dashboard_editor", actorSubject: DASHBOARD_ACTOR,
    targets: prepared.map(item => item.target),
    payload: { operation, updates: prepared.map(item => item.update), confirm, follow_up: followUp } })
  return submitCommand(raw)
}

export async function submitReconciliation(payload) {
  const { raw } = buildCommand({ action: "reconcile_delivery", producerKind: "dashboard_reconciliation",
    actorSubject: DASHBOARD_ACTOR, payload })
  return submitCommand(raw)
}

export async function submitFeedback(input) {
  const { raw } = buildCommand({ action: "post_feedback", producerKind: "post_feedback", actorSubject: DASHBOARD_ACTOR,
    payload: { input_json: JSON.stringify(input) } })
  return submitCommand(raw)
}

export function submittedBody(submitted) {
  if (submitted.status === "pending") {
    return { status: 202, body: { ok: true, action: "command_submitted", status: "pending", command_id: submitted.command_id,
      digest: submitted.digest, command: submitted.command } }
  }
  if (submitted.status === "submission_uncertain") {
    return { status: 503, body: { ok: false, status: "submission_uncertain", code: "command_submission_uncertain",
      error: "The serialized writer may not have received this command. Check its status; resubmit the same command only if it is unknown.",
      command_id: submitted.command_id, digest: submitted.digest, command: submitted.command } }
  }
  return { status: 502, body: { ok: false, status: "not_submitted", code: "command_submission_failed",
    error: "The serialized writer did not accept this command; nothing changed.", command_id: submitted.command_id } }
}

export function submittedResponse(submitted, headers = {}) {
  const { status, body } = submittedBody(submitted)
  return Response.json(body, { status, headers })
}
