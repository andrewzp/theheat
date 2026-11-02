// P00c route mode: dashboard routes submit SEALED, server-issued commands to the serialized
// consumer instead of PATCHing the Gist (ROUTE-CONTRACT-v2 §1–§3). The response retains the exact
// sealed envelope so a lost response can be resubmitted unchanged (POST /api/commands); success
// is never synthesized and there is no plaintext fallback.
import { randomUUID } from "node:crypto"
import { CODE_GENERATION, activeRouteActivation, submitCommand } from "./gist-write-route.js"
import { parseEnvelope, requireSealKey, sealEnvelope } from "./gist-command-seal.js"
import { CONFIRM_ACTIONS, OPERATION_PARAMS } from "./draft-operations.js"

// The dashboard authenticates one shared credential (see src/commands/command_roles.py), so the
// authenticated session's subject is that role. It is never read from a request body.
export const DASHBOARD_ACTOR = "dashboard-operator"
export const COMMAND_LIFETIME_MS = 3600000
export const MAX_BULK_TARGETS = 100

export function sessionActorSubject(request) {
  if (!request || typeof request.headers?.get !== "function") throw Object.assign(new Error("No authenticated request"), { code: "command_actor_unavailable", status: 503 })
  return DASHBOARD_ACTOR
}

const utcSeconds = date => date.toISOString().replace(/\.\d{3}Z$/, "Z")

// Seal one command bound to the CURRENT active route activation (refuses unless active).
export function buildSealedCommand({ action, operation, producerKind, actorSubject, route, targets = [], payload,
  now = new Date(), env = process.env, commandId = randomUUID(), lifetimeMs = COMMAND_LIFETIME_MS }) {
  const activation = activeRouteActivation(route, env)
  const key = requireSealKey(env)
  const at = new Date(Math.floor(now.getTime() / 1000) * 1000)
  const fields = { schema_version: 2, command_id: commandId, action, operation, requested_at: utcSeconds(at),
    expires_at: utcSeconds(new Date(at.getTime() + lifetimeMs)), producer: { kind: producerKind, generation: String(CODE_GENERATION) },
    actor_subject: actorSubject, route_activation: activation }
  const raw = sealEnvelope(fields, { targets, payload }, key)
  return { raw, digest: parseEnvelope(raw, { now }).digest, command_id: commandId }
}

async function submitSealed(spec) {
  let built
  try { built = buildSealedCommand(spec) } catch (error) {
    return { status: "refused", code: typeof error?.code === "string" ? error.code : "command_seal_failed", http_status: error?.status || 503 }
  }
  return submitCommand(built.raw)
}

function pick(body, keys) {
  return Object.fromEntries(keys.filter(key => Object.hasOwn(body || {}, key)).map(key => [key, body[key]]))
}

// One draft operation (or one all-or-nothing bulk rejection / episode correction): the operation,
// its exact request fields and the server-prepared inputs; never a patch of draft content.
export async function submitDraftUpdates(request, prepared, route, { operation, body = {}, params = null, mediaDescriptor = null,
  publishIntentId = null, checkedPolicySha = null, checkedAutomaticEpoch = null }) {
  if (prepared.length > MAX_BULK_TARGETS) return { status: "refused", code: "command_too_large", http_status: 413 }
  const parameters = params ?? pick(body, OPERATION_PARAMS[operation] ?? [])
  const payload = { operation, params_json: JSON.stringify(parameters), updates: prepared.map(item => item.update),
    media_descriptor_json: mediaDescriptor ? JSON.stringify(mediaDescriptor) : null,
    publish_intent_id: operation === "approve" ? publishIntentId : null,
    checked_policy_sha256: CONFIRM_ACTIONS.includes(operation) ? checkedPolicySha : null,
    checked_automatic_epoch: operation === "auto_approve" ? checkedAutomaticEpoch : null }
  return submitSealed({ action: "draft_update", operation, producerKind: "dashboard_editor", actorSubject: sessionActorSubject(request),
    route, targets: prepared.map(item => item.target), payload })
}

export async function submitReconciliation(request, payload, route) {
  return submitSealed({ action: "reconcile_delivery", operation: "reconcile_delivery", producerKind: "dashboard_reconciliation",
    actorSubject: sessionActorSubject(request), route, payload })
}

export async function submitFeedback(request, input, route) {
  return submitSealed({ action: "post_feedback", operation: "post_feedback", producerKind: "post_feedback",
    actorSubject: sessionActorSubject(request), route, payload: { input_json: JSON.stringify(input) } })
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
  if (submitted.status === "refused") {
    return { status: submitted.http_status || 409, body: { ok: false, status: "refused", code: submitted.code,
      error: "This change was not submitted; nothing changed." } }
  }
  return { status: 502, body: { ok: false, status: "not_submitted", code: "command_submission_failed",
    error: "The serialized writer did not accept this command; nothing changed.", command_id: submitted.command_id } }
}

export function submittedResponse(submitted, headers = {}) {
  const { status, body } = submittedBody(submitted)
  return Response.json(body, { status, headers })
}
