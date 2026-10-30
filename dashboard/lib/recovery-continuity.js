// Cross-surface recovery continuity: one pure projection of a draft for the editor,
// Published and Operations surfaces after import, restore or supersession.
// Provenance is supplied explicitly by the caller (import/restore results from the
// local command authority); nothing is inferred from bytes. An imported or restored
// review is never current here, a superseded revision is read-only, an unknown
// attempt is never retried and delivered content is never cancelled or rewritten.
import { reviewIsCurrent } from "./draft-revisions.js"
import { inspectReconciliation } from "./delivery-reconciliation.js"

const SURFACE_ACTIONS = {
  editor: ["edit", "review", "approve"],
  published: ["feedback", "retry"],
  operations: ["confirm", "cancel", "retry"],
}
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)

export function recoveryProvenance(draft, provenance = {}) {
  const key = String(draft?.id)
  const entry = object(provenance) && Object.hasOwn(provenance, key) ? provenance[key] : null
  if (object(entry) && ["import", "restore"].includes(entry.origin)) return { kind: entry.origin === "import" ? "imported" : "restored",
    import_id: typeof entry.import_id === "string" ? entry.import_id : null, source_sha256: typeof entry.source_sha256 === "string" ? entry.source_sha256 : null }
  if (object(entry) && entry.origin === "superseded") return { kind: "superseded", superseded_by: entry.superseded_by ?? null }
  return { kind: "current" }
}

function history(draft, row) {
  const revisions = (Array.isArray(draft.revision_history) ? draft.revision_history : []).map((entry, index) => ({ kind: "revision", index, entry: structuredClone(entry) }))
  const attempts = object(row) ? [row, ...(Array.isArray(row.attempt_conflicts) ? row.attempt_conflicts : [])] : []
  return [...revisions, ...attempts.map((attempt, index) => ({ kind: index ? "conflicting_attempt" : "attempt", entry: structuredClone(attempt) }))]
}

export function projectRecoveredRecord(draft, state, { surface, provenance = {}, policy = null } = {}) {
  if (!Object.hasOwn(SURFACE_ACTIONS, surface)) throw new Error("unknown_surface")
  const eventId = draft.event_id || draft.id
  const row = object(state.publish_ledger) ? state.publish_ledger[eventId] : undefined
  const origin = recoveryProvenance(draft, provenance)
  const attempt = inspectReconciliation({ drafts: [draft], publish_ledger: row === undefined ? {} : { [eventId]: row } }).rows[0] || null
  const delivered = object(row) && row.tweet_id ? { tweet_id: String(row.tweet_id), text: typeof row.text === "string" ? row.text : null,
    confirmed_at: row.confirmed_at ?? row.at ?? null } : null
  let reviewCurrent = false
  try { reviewCurrent = origin.kind === "current" && reviewIsCurrent(draft, policy) } catch { reviewCurrent = false }
  const holds = []
  const hold = (action, code) => { if (SURFACE_ACTIONS[surface].includes(action)) holds.push({ action, code }) }
  if (origin.kind === "imported" || origin.kind === "restored") {
    for (const action of ["edit", "review", "approve", "retry", "confirm", "cancel"]) hold(action, `${origin.kind}_record_read_only`)
    hold("approve", "imported_review_not_current")
  }
  if (origin.kind === "superseded") for (const action of ["edit", "review", "approve", "retry"]) hold(action, "superseded_by_newer_revision")
  if (delivered) { hold("cancel", "delivered_content_retained"); hold("retry", "already_delivered"); hold("edit", "delivered_original_preserved") }
  if (attempt && !delivered && attempt.phase !== "not_sent") hold("retry", "unknown_delivery_never_retried")
  if (attempt?.cancelled) hold("retry", "intent_cancelled")
  if (!reviewCurrent && origin.kind === "current") hold("approve", "review_required")
  const unique = holds.filter((h, i) => holds.findIndex(o => o.action === h.action && o.code === h.code) === i)
  const blocked = new Set(unique.map(h => h.action))
  return {
    surface, draft_id: draft.id ?? null, event_id: eventId, status: draft.status ?? null, provenance: origin,
    text: typeof draft.text === "string" ? draft.text : null, delivered, attempt,
    review_current: reviewCurrent, history: history(draft, row),
    actions: SURFACE_ACTIONS[surface].filter(action => !blocked.has(action)
      && (action !== "confirm" && action !== "cancel" || attempt?.actions.includes(action))
      && (action !== "retry" || attempt?.retry_permitted === true)
      && (action !== "feedback" || Boolean(delivered))),
    holds: unique,
  }
}

export function projectRecoveredState(state, options = {}) {
  return (Array.isArray(state?.drafts) ? state.drafts : []).filter(object).map(draft => projectRecoveredRecord(draft, state, options))
}

// The local preview's read-only provenance channel (`/state` recovery_provenance from
// src/commands/recovery_provenance.py). Absent means no journal is configured: every
// record is current. A malformed map refuses the whole read instead of presenting
// imported history as current.
const SHA = /^[a-f0-9]{64}$/
export function recoveryProvenanceMap(value) {
  if (value === undefined) return {}
  const refuse = () => { throw Object.assign(new Error("recovery_provenance_invalid"), { code: "recovery_provenance_invalid", status: 503 }) }
  if (!object(value) || Object.keys(value).length > 20000) refuse()
  for (const entry of Object.values(value)) {
    if (!object(entry)) refuse()
    if (["import", "restore"].includes(entry.origin) ? typeof entry.import_id !== "string" || !entry.import_id || !SHA.test(entry.source_sha256 || "")
      : entry.origin !== "superseded" || typeof entry.superseded_by !== "string") refuse()
  }
  return value
}

// One surface's record for a non-current draft; null for a current one, so production
// pages (empty provenance) are unchanged. An unprojectable record stays read-only.
export function recoveredRecordFor(draft, state, { surface, provenance = {}, policy = null } = {}) {
  if (!object(draft) || recoveryProvenance(draft, provenance).kind === "current") return null
  try { return projectRecoveredRecord(draft, state, { surface, provenance, policy }) } catch {
    return { surface, draft_id: draft.id ?? null, event_id: draft.event_id || draft.id || null, status: draft.status ?? null,
      provenance: recoveryProvenance(draft, provenance), text: typeof draft.text === "string" ? draft.text : null, delivered: null,
      attempt: null, review_current: false, history: [], actions: [], holds: [{ action: "edit", code: "recovery_projection_unavailable" }] }
  }
}

// Published: non-current records with delivered content, newest receipt first.
export function recoveredPublishedRecords(state, provenance = {}) {
  if (!Object.keys(provenance).length) return []
  return (Array.isArray(state?.drafts) ? state.drafts : []).filter(draft => object(draft) && Object.hasOwn(provenance, draft.id))
    .map(draft => recoveredRecordFor(draft, state, { surface: "published", provenance }))
    .filter(record => record && (record.delivered || record.status === "posted"))
    .sort((a, b) => String(b.delivered?.confirmed_at ?? "").localeCompare(String(a.delivered?.confirmed_at ?? ""))).slice(0, 20)
}
