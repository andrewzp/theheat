// Operator reconciliation of publish-ledger attempts (inspect / confirm / cancel).
// Mirrors src/commands/delivery_reconciliation.py exactly; both are checked against
// tests/fixtures/w14_delivery_reconciliation_vectors.json. Unknown stays unknown
// without a receipt whose text, time and media description match the attempt.
import { createHash } from "node:crypto"
import { decisionRevision, draftIdentity, fingerprint, revokeApproval } from "./draft-revisions.js"

const REQUEST_KEYS = ["reconciliation_id", "action", "event_id", "intent_id", "expected_decision_revision", "expected_evidence_sha256", "reason"]
const RECEIPT_KEYS = ["tweet_id", "text", "created_at"]
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)

export class ReconciliationError extends Error {
  constructor(code) { super(code); this.code = code }
}
const need = (condition, code) => { if (!condition) throw new ReconciliationError(code) }
const sha = text => createHash("sha256").update(text, "utf8").digest("hex")

function utc(value) {
  need(typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?(Z|\+00:00)$/.test(value), "receipt_time_invalid")
  return Date.parse(value.replace("+00:00", "Z"))
}

function draftFor(state, eventId) {
  const matches = (Array.isArray(state.drafts) ? state.drafts : []).filter(d => object(d) && (d.event_id || d.id) === eventId)
  return matches.length === 1 ? matches[0] : null
}

function boundElsewhere(state, eventId, tweetId) {
  for (const [other, row] of Object.entries(object(state.publish_ledger) ? state.publish_ledger : {})) {
    const rows = object(row) ? [row, ...(Array.isArray(row.attempt_conflicts) ? row.attempt_conflicts : [])] : []
    if (other !== eventId && rows.some(r => object(r) && String(r.tweet_id || "") === tweetId)) return true
  }
  return (state.drafts || []).some(d => object(d) && String(d.tweet_id || "") === tweetId && (d.event_id || d.id) !== eventId)
}

export function retryPermitted(row) {
  if (!object(row) || row.tweet_id || (Array.isArray(row.attempt_conflicts) ? row.attempt_conflicts.length : row.attempt_conflicts)) return false
  if (row.operator_cancellation) return false
  return row.phase === "not_sent"
}

export function validateRequest(request) {
  need(object(request), "reconciliation_request_invalid")
  const keys = Object.keys(request)
  need(REQUEST_KEYS.every(k => keys.includes(k)) && keys.every(k => REQUEST_KEYS.includes(k) || k === "receipt"), "reconciliation_request_invalid")
  need(["confirm", "cancel"].includes(request.action), "reconciliation_action_invalid")
  for (const key of ["reconciliation_id", "event_id", "intent_id", "reason"]) {
    need(typeof request[key] === "string" && request[key].length > 0 && request[key].length <= 200, "reconciliation_request_invalid")
  }
  need(Number.isSafeInteger(request.expected_decision_revision) && request.expected_decision_revision >= 0, "reconciliation_request_invalid")
  need(typeof request.expected_evidence_sha256 === "string" && /^[a-f0-9]{64}$/.test(request.expected_evidence_sha256), "reconciliation_request_invalid")
  if (request.action === "confirm") {
    const receipt = request.receipt
    need(object(receipt), "receipt_required")
    const rk = Object.keys(receipt)
    need(RECEIPT_KEYS.every(k => rk.includes(k)) && rk.every(k => RECEIPT_KEYS.includes(k) || k === "alt_text"), "receipt_invalid")
    need(typeof receipt.tweet_id === "string" && /^[0-9]{1,30}$/.test(receipt.tweet_id), "receipt_invalid")
    need(typeof receipt.text === "string" && typeof (receipt.alt_text ?? "") === "string", "receipt_invalid")
  } else {
    need(!Object.hasOwn(request, "receipt"), "reconciliation_request_invalid")
  }
  return request
}

export function inspectReconciliation(state) {
  const ledger = object(state?.publish_ledger) ? state.publish_ledger : {}
  const rows = Object.keys(ledger).sort().map(eventId => {
    const row = ledger[eventId], draft = draftFor(state, eventId)
    if (!object(row)) return { event_id: eventId, phase: "malformed", actions: [], hold: "malformed_evidence_preserved" }
    let current = null, revision = null
    try { current = draft ? draftIdentity(draft) : null; revision = draft ? decisionRevision(draft) : null } catch { current = null; revision = null }
    const confirmed = Boolean(row.tweet_id), cancelled = Boolean(row.operator_cancellation)
    const conflicts = Boolean(Array.isArray(row.attempt_conflicts) ? row.attempt_conflicts.length : row.attempt_conflicts)
    const open = !(confirmed || cancelled || conflicts || draft === null)
    const actions = open ? [...(row.phase === "not_sent" ? [] : ["confirm"]), "cancel"] : []
    return {
      event_id: eventId, draft_id: draft ? draft.id ?? null : null,
      phase: confirmed ? "confirmed" : String(row.phase || "legacy_unknown"),
      intent_id: row.intent_id ?? null, tweet_id: row.tweet_id ?? null, at: row.at ?? null,
      text_sha256: row.text_sha256 ?? null, evidence_sha256: row.evidence_sha256 ?? null,
      delivery_identity: structuredClone(row.delivery_identity ?? null), delivery_outcome: structuredClone(row.delivery_outcome ?? null),
      decision_revision: revision,
      source_snapshot_current: Boolean(current) && current.evidence_sha256 === row.evidence_sha256,
      retry_permitted: retryPermitted(row), cancelled, conflicts,
      reconciliation: structuredClone(row.reconciliation || row.operator_cancellation || null),
      actions,
      hold: conflicts ? "attempt_conflicts_require_review" : draft === null ? "draft_missing_or_ambiguous"
        : !confirmed && row.phase !== "not_sent" ? "receipt_required_unknown_stays_unknown" : null,
    }
  })
  return { rows, mutation: "none" }
}

export function decideReconciliation(state, rawRequest, { actor, at }) {
  const request = validateRequest(rawRequest)
  const digest = fingerprint(request)
  const ledger = state.publish_ledger
  need(object(ledger) && Object.hasOwn(ledger, request.event_id), "attempt_not_found")
  const row = ledger[request.event_id]
  need(object(row), "attempt_malformed")
  for (const recorded of [row.reconciliation, row.operator_cancellation]) {
    if (object(recorded) && recorded.reconciliation_id === request.reconciliation_id) {
      need(recorded.request_sha256 === digest, "reconciliation_id_reused")
      return { state, result: { status: "unchanged", reconciliation_id: request.reconciliation_id, event_id: request.event_id } }
    }
  }
  need(!(Array.isArray(row.attempt_conflicts) ? row.attempt_conflicts.length : row.attempt_conflicts), "attempt_conflicts_require_review")
  need(row.intent_id === request.intent_id, "attempt_mismatch")
  const draft = draftFor(state, request.event_id)
  need(draft !== null, "draft_missing_or_ambiguous")
  need(decisionRevision(draft) === request.expected_decision_revision, "stale_decision_revision")
  need(row.evidence_sha256 === request.expected_evidence_sha256 && draftIdentity(draft).evidence_sha256 === row.evidence_sha256, "source_snapshot_changed")
  const record = { reconciliation_id: request.reconciliation_id, request_sha256: digest, actor, at, reason: request.reason }
  const updated = structuredClone(state)
  const target = updated.publish_ledger[request.event_id]
  if (request.action === "cancel") {
    need(!row.tweet_id, "delivered_content_retained")
    need(!row.operator_cancellation, "already_cancelled")
    target.operator_cancellation = record
    const changed = draftFor(updated, request.event_id)
    revokeApproval(changed)
    Object.assign(changed, { status: "rejected", rejected_reason: "Publication intent cancelled; delivery evidence retained", updated_at: at })
    return { state: updated, result: { status: "applied", action: "cancel", reconciliation_id: request.reconciliation_id, event_id: request.event_id, phase: target.phase ?? null } }
  }
  const receipt = request.receipt
  need(!row.tweet_id, "attempt_already_confirmed")
  need(!row.operator_cancellation, "attempt_cancelled")
  need(row.phase !== "not_sent", "attempt_proven_not_sent")
  need(typeof row.text === "string" && receipt.text === row.text, "receipt_text_mismatch")
  need(typeof row.at === "string" && utc(receipt.created_at) >= utc(row.at), "receipt_predates_attempt")
  need(!boundElsewhere(state, request.event_id, receipt.tweet_id), "receipt_bound_elsewhere")
  const media = object(row.delivery_identity) ? row.delivery_identity : {}
  if (media.alt_sha256) need(typeof receipt.alt_text === "string" && sha(receipt.alt_text) === media.alt_sha256, "receipt_media_mismatch")
  Object.assign(record, { receipt_sha256: fingerprint(receipt), evidence: "operator_supplied_receipt",
    png_receipt_verification: media.png_sha256 ? "not_available_from_platform" : null })
  Object.assign(target, { tweet_id: receipt.tweet_id, phase: "confirmed", confirmed_at: receipt.created_at, reconciliation: record })
  return { state: updated, result: { status: "applied", action: "confirm", reconciliation_id: request.reconciliation_id, event_id: request.event_id, tweet_id: receipt.tweet_id } }
}
