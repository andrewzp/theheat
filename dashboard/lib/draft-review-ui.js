import { nwsSourceTiming } from "./nws-source-timing.js"
import { officialWarningTiming } from "./official-warning-evidence.js"
import { nhcAdvisoryTiming } from "./nhc-advisory-evidence.js"

function savedSourceTiming(draft, now) {
  for (const timing of [nwsSourceTiming, officialWarningTiming, nhcAdvisoryTiming]) {
    const value = timing(draft, now)
    if (value.blocked) return value
  }
  return { blocked: false }
}

// Browser-safe view decisions. Identities are computed by the server; the
// browser only carries them back for optimistic checks.
export function revisionKey(identity) {
  if (!identity) return ""
  return `${identity.content_revision}:${identity.text_sha256}:${identity.evidence_sha256}:${identity.decision_revision ?? 0}`
}

export function draftTextLength(text) { return typeof text === "string" ? Array.from(text).length : 0 }

export function reviewQueueOrder(drafts, { localPreview = false, now = Date.now() } = {}) {
  return [...drafts].sort((a, b) => {
    const held = localPreview ? 0 : Number(savedSourceTiming(a, now).blocked) - Number(savedSourceTiming(b, now).blocked)
    return held || (b.created_at || "").localeCompare(a.created_at || "")
  })
}

export function draftReviewControls(draft, now = Date.now()) {
  const pending = draft?.status === "pending"
  const mayEdit = !draft?.local_preview || ["editor", "publisher"].includes(draft.operator_role)
  const mayApprove = !draft?.local_preview || draft.operator_role === "publisher"
  const mutable = mayEdit && ["pending", "approved"].includes(draft?.status) && !draft?.publish_blocked
  const conflict = draft?.review_status === "conflict"
  const reviewed = draft?.review_status === "passed"
  // The local command authority owns its separate source/currentness contract.
  // This preflight is for the existing Gist publication workflow.
  const source = draft?.local_preview ? { blocked: false } : savedSourceTiming(draft, now)
  return {
    canEdit: mutable,
    canReview: mutable && pending && !source.blocked && !conflict && !reviewed && !["policy_unverified", "media_review_required"].includes(draft?.review_status),
    canApprove: mayApprove && mutable && pending && reviewed && !source.blocked,
    canSchedule: draft?.automatic_publication?.enabled === true && mutable && pending && reviewed && !source.blocked && draft.review_kind === "model" && draft.approval_policy?.can_auto_approve !== false,
    sourceHold: source.blocked ? source.message : null,
    needsReview: !reviewed,
    conflict,
  }
}

// Attribution is separate from validity; callers show this only for passed review.
export function manualReviewLabel(draft) {
  return draft?.review_kind === "delegated" ? "assistant reviewed"
    : ["human", "human_media"].includes(draft?.review_kind) ? (draft.review_kind === "human_media" ? "text and graphic reviewed" : "human reviewed") : null
}
