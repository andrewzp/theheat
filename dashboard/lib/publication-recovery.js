// W09.4: a read-only view of the publication attempt that pauses a draft. Display only:
// hasUnresolvedPublish (draft-revisions.js) stays the authority, and no field here
// enables an action. An unknown outcome is reconciled against the platform record by
// its owner; this page never offers a retry, resend or replacement for it.
const PHASES = ["submitted", "unknown", "confirmed", "not_sent"]
const INTENT = /^[A-Za-z0-9_.:-]{1,128}$/
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/

export const RECOVERY_NOTE = "Nothing on this page publishes, resends or spends for this draft. "
  + "Reconcile this attempt against the platform record first (owner action); an unknown outcome is never retried automatically."

export function publicationAttempt(draft, state) {
  const ledger = state?.publish_ledger, eventId = draft?.event_id || draft?.id
  const row = ledger && typeof ledger === "object" && !Array.isArray(ledger) && typeof eventId === "string"
    && Object.hasOwn(ledger, eventId) ? ledger[eventId] : undefined
  if (row === undefined) {
    return ["submitted", "unknown"].includes(draft?.publish_outcome)
      ? { status: "outcome_only", phase: draft.publish_outcome, intent_id: null, at: null, content_revision: null, receipt: "none", conflicts: 0 }
      : null
  }
  if (!row || typeof row !== "object" || Array.isArray(row) || !PHASES.includes(row.phase)) return { status: "unreadable" }
  const conflicts = Array.isArray(row.attempt_conflicts) ? row.attempt_conflicts.length : Object.hasOwn(row, "attempt_conflicts") ? null : 0
  return {
    status: "recorded", phase: row.phase,
    intent_id: typeof row.intent_id === "string" && INTENT.test(row.intent_id) ? row.intent_id : null,
    at: typeof row.at === "string" && ISO.test(row.at) ? row.at : null,
    content_revision: Number.isSafeInteger(row.content_revision) && row.content_revision >= 0 ? row.content_revision : null,
    receipt: typeof row.tweet_id === "string" && row.tweet_id ? "recorded" : "none",
    conflicts,
  }
}

const PHASE_TEXT = { submitted: "submitted; the platform outcome was never confirmed", unknown: "outcome unknown (an acknowledgement was lost)",
  confirmed: "confirmed for a different revision than this draft", not_sent: "recorded as not sent, with conflicting attempts" }

export function publicationAttemptLines(attempt) {
  if (!attempt) return []
  if (attempt.status === "unreadable") return ["The recorded attempt is unreadable; treat its outcome as unknown."]
  return [
    `Affected attempt: ${attempt.intent_id ? `intent ${attempt.intent_id}` : "intent not recorded"}${attempt.content_revision === null ? "" : ` for version ${attempt.content_revision}`}.`,
    `State: ${PHASE_TEXT[attempt.phase] || "unknown"}${attempt.at ? ` · recorded ${attempt.at}` : ""}.`,
    attempt.receipt === "recorded" ? "A platform receipt is recorded for that attempt." : "No platform receipt is recorded; delivery may or may not have happened.",
    ...(attempt.conflicts ? [`${attempt.conflicts} conflicting attempt record(s) also need reconciliation.`] : attempt.conflicts === null ? ["Conflicting attempt records are unreadable."] : []),
  ]
}
