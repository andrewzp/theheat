import { createHash } from "node:crypto"

// Paired with src/editorial/revisions.py. This is a decision binding, not a lock.
function validUnicode(text) {
  if (Buffer.from(text, "utf8").toString("utf8") !== text) throw new Error("Invalid Unicode in revision data")
  return text
}

function canonical(value) {
  if (value === null) return ["null"]
  if (typeof value === "boolean") return ["boolean", value]
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Revision evidence must contain finite numbers")
    const bytes = Buffer.alloc(8)
    bytes.writeDoubleBE(value === 0 ? 0 : value)
    return ["number", bytes.toString("hex")]
  }
  if (typeof value === "string") return ["string", validUnicode(value)]
  if (Array.isArray(value)) return ["array", value.map(canonical)]
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value).map(validUnicode).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)))
    return ["object", keys.map((key) => [key, canonical(value[key])])]
  }
  throw new Error("Revision evidence must be JSON data")
}

export function fingerprint(value) {
  return createHash("sha256").update(JSON.stringify(canonical(value)), "utf8").digest("hex")
}

export function textHash(text) {
  if (typeof text !== "string") throw new Error("Draft text must be a string")
  return createHash("sha256").update(validUnicode(text), "utf8").digest("hex")
}

function evidencePayload(draft) {
  const review = structuredClone(draft.review_context ?? null)
  if (review && typeof review === "object" && !Array.isArray(review)) {
    const twoBot = review.two_bot
    delete review.two_bot
    if (twoBot && Object.hasOwn(twoBot, "bundle")) review.two_bot = { bundle: twoBot.bundle }
  }
  return {
    event_id: draft.event_id ?? null, type: draft.type ?? null, tweet_date: draft.tweet_date ?? null,
    review_context: review, hot10_rows: draft.hot10_rows ?? null,
  }
}

export function draftIdentity(draft) {
  const revision = draft.content_revision ?? 0
  if (!Number.isSafeInteger(revision) || revision < 0) throw new Error("Invalid content revision")
  return { content_revision: revision, text_sha256: textHash(draft.text ?? ""), evidence_sha256: fingerprint(evidencePayload(draft)) }
}

export function decisionRevision(draft) {
  const revision = draft.decision_revision ?? 0
  if (!Number.isSafeInteger(revision) || revision < 0 || revision >= Number.MAX_SAFE_INTEGER) throw new Error("Invalid decision revision")
  return revision
}

function advanceDecision(draft) { draft.decision_revision = decisionRevision(draft) + 1 }

export function bindingMatches(draft, binding) {
  if (!binding || typeof binding !== "object") return false
  try {
    return Object.entries(draftIdentity(draft)).every(([key, value]) => binding[key] === value)
  } catch { return false }
}

function twoBot(draft) { return draft.review_context?.two_bot ?? {} }
function checks(value) { return { fact_check: value.fact_check ?? null, critic: value.critic ?? null } }
function checksPass(value) { return value.fact_check?.passed === true && value.critic?.passed === true }

export function reviewIsCurrent(draft) {
  const binding = draft.review_binding
  if (draft.revision_conflicts?.length || !bindingMatches(draft, binding)) return false
  if (binding.kind === "human") return true
  if (binding.kind !== "model" || !checksPass(twoBot(draft))) return false
  try { return binding.checks_sha256 === fingerprint(checks(twoBot(draft))) } catch { return false }
}

export function approvalIsCurrent(draft, mode = null) {
  const binding = draft.approval_binding
  if (!reviewIsCurrent(draft) || !bindingMatches(draft, binding)) return false
  if (!["manual", "auto"].includes(binding.mode) || (mode && binding.mode !== mode)) return false
  try { if (binding.decision_revision !== decisionRevision(draft)) return false } catch { return false }
  if ((binding.publish_intent_id ?? null) !== (draft.publish_intent_id ?? null)) return false
  return binding.mode !== "auto" || draft.review_binding.kind === "model"
}

export function hasUnresolvedPublish(draft, state) {
  function unresolved(attempt) {
    if (!attempt || typeof attempt !== "object") return false
    if (attempt.attempt_conflicts != null && !Array.isArray(attempt.attempt_conflicts)) return true
    if ((attempt.attempt_conflicts ?? []).some(unresolved)) return true
    if (attempt.tweet_id) {
      if (Object.hasOwn(attempt, "text_sha256")) return !bindingMatches(draft, attempt)
      return typeof attempt.text === "string" && attempt.text !== draft.text
    }
    return attempt.phase !== "not_sent"
  }
  if (unresolved(state.publish_ledger?.[draft.event_id || draft.id])) return true
  if (["submitted", "unknown"].includes(draft.publish_outcome)) return true
  if (draft.status === "posted" || ["not_sent", "confirmed"].includes(draft.publish_outcome)) return false
  return !!(draft.autoship_attempted || draft.last_publish_attempt_at)
}

export function recordModelReview(draft) {
  revokeApproval(draft)
  const value = twoBot(draft)
  let proven = false
  try {
    proven = checksPass(value) && value.reviewed_text_sha256 === textHash(draft.text ?? "")
      && Object.hasOwn(value, "bundle") && value.reviewed_bundle_sha256 === fingerprint(value.bundle)
  } catch { /* Invalid evidence cannot establish a review. */ }
  if (proven && !draft.revision_conflicts?.length) {
    draft.review_binding = { ...draftIdentity(draft), kind: "model", reviewed_at: new Date().toISOString(), checks_sha256: fingerprint(checks(value)) }
  } else delete draft.review_binding
  return draft
}

export function initializeRevision(draft) {
  if (!Object.hasOwn(draft, "content_revision")) draft.content_revision = 1
  return recordModelReview(draft)
}

export function recordHumanReview(draft) {
  if (draft.revision_conflicts?.length) throw new Error("Resolve the conflicting revision before reviewing")
  if (typeof draft.text !== "string" || !draft.text.trim() || [...draft.text].length > 280) throw new Error("Invalid draft text")
  draft.content_revision = Math.max(1, draftIdentity(draft).content_revision)
  revokeApproval(draft)
  draft.review_binding = { ...draftIdentity(draft), kind: "human", reviewed_at: new Date().toISOString() }
  return draft
}

export function authorizeDraft(draft, mode, intentId = null) {
  if (!reviewIsCurrent(draft)) throw new Error("This revision needs revalidation")
  if (!["manual", "auto"].includes(mode)) throw new Error("Invalid approval mode")
  if (mode === "auto" && draft.review_binding.kind !== "model") throw new Error("Scheduling requires a current model review")
  advanceDecision(draft)
  draft.approval_binding = { ...draftIdentity(draft), decision_revision: draft.decision_revision, mode, authorized_at: new Date().toISOString() }
  if (intentId) {
    draft.approval_binding.publish_intent_id = intentId
    draft.publish_intent_id = intentId
  }
  return draft
}

export function revokeApproval(draft) {
  advanceDecision(draft)
  for (const key of ["approval_binding", "approved_at", "auto_approve_at", "auto_approve_requested_at", "publish_requested_at", "publish_intent_id", "autoship_on_critic_pass"]) delete draft[key]
  draft.approval_mode = "manual"
  return draft
}

export function invalidateText(draft, newText) {
  if (typeof newText !== "string" || !newText.trim() || [...newText].length > 280) throw new Error("Invalid draft text")
  textHash(newText) // Reject malformed Unicode before changing durable fields.
  if (newText === draft.text && !draft.revision_conflicts?.length) return draft
  const previous = {}
  for (const key of ["text", "review_context", "review_binding", "approval_binding", "revision_conflicts", "decision_revision"]) {
    if (Object.hasOwn(draft, key)) previous[key] = structuredClone(draft[key])
  }
  Object.assign(previous, draftIdentity(draft), { invalidated_at: new Date().toISOString() })
  draft.revision_history ??= []
  draft.revision_history.push(previous)
  draft.content_revision = previous.content_revision + 1
  draft.text = newText
  draft.status = "pending"
  revokeApproval(draft)
  for (const key of ["review_binding", "revision_conflicts", "candidate_score", "selected_candidate_rank"]) delete draft[key]
  if (draft.review_context?.two_bot) {
    draft.review_context.two_bot = Object.fromEntries(Object.entries(draft.review_context.two_bot).filter(([key]) => ["bundle", "signal_kind"].includes(key)))
  }
  return draft
}

export function projectDraft(draft) {
  const current = reviewIsCurrent(draft)
  return { ...draft, revision_identity: { ...draftIdentity(draft), decision_revision: decisionRevision(draft) }, review_status: draft.revision_conflicts?.length ? "conflict" : current ? "passed" : "needs_revalidation", review_kind: current ? draft.review_binding.kind : null }
}
