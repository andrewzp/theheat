// Browser-safe view decisions. Identities are computed by the server; the
// browser only carries them back for optimistic checks.
export function revisionKey(identity) {
  if (!identity) return ""
  return `${identity.content_revision}:${identity.text_sha256}:${identity.evidence_sha256}:${identity.decision_revision ?? 0}`
}

export function draftTextLength(text) { return typeof text === "string" ? Array.from(text).length : 0 }

export function draftReviewControls(draft) {
  const pending = draft?.status === "pending"
  const mutable = ["pending", "approved"].includes(draft?.status) && !draft?.publish_blocked
  const conflict = draft?.review_status === "conflict"
  const reviewed = draft?.review_status === "passed"
  return {
    canEdit: mutable,
    canReview: mutable && pending && !conflict && !reviewed,
    canApprove: mutable && pending && reviewed,
    canSchedule: mutable && pending && reviewed && draft.review_kind === "model" && draft.approval_policy?.can_auto_approve !== false,
    needsReview: !reviewed,
    conflict,
  }
}
