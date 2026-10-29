import { createHash } from "node:crypto"
import { requiredAttestations, validGistMedia } from "./gist-media.js"
import { validEditorialPolicy } from "./editorial-policy.js"
import { configuredAutomaticPolicy } from "./publication-control.js"
import { projectSavedClaimEvidence } from "./saved-claim-evidence.js"
import { buildOperatorClaimReferences, projectOperatorClaimReferenceHistory, projectOperatorClaimReferences } from "./operator-claim-references.js"
import { operatorClaimKindMatches } from "./operator-claim-reference-input.js"

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
  const payload = {
    event_id: draft.event_id ?? null, type: draft.type ?? null, tweet_date: draft.tweet_date ?? null,
    review_context: review, hot10_rows: draft.hot10_rows ?? null,
  }
  if (Object.hasOwn(draft, "media_attachment")) payload.media_attachment = structuredClone(draft.media_attachment)
  return payload
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

function policyMatches(binding, policy) {
  try { return validEditorialPolicy(policy) && validEditorialPolicy(binding?.editorial_policy) && fingerprint(binding.editorial_policy) === fingerprint(policy) && binding.policy_sha256 === fingerprint(policy) } catch { return false }
}

export function requiredChecksFingerprint(value) {
  const fields = ["schema_version", "check_set_id", "candidate_id", "derivation_id", "checker_state_sha256", "completion_sha256", "stages"]
  const exact = (v, keys) => v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === keys.length && keys.every((k) => Object.hasOwn(v, k))
  const sha = (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v)
  if (!exact(value, fields) || value.schema_version !== 1 || !fields.filter((k) => !["schema_version", "stages"].includes(k)).every((k) => sha(value[k]))) return null
  if (!exact(value.stages, ["deterministic", "safety", "fact_check", "critic"])) return null
  if (!Object.values(value.stages).every((row) => exact(row, ["grant_id", "request_sha256", "observation_sha256", "receipt_sha256"]) && Object.values(row).every(sha))) return null
  return fingerprint(value)
}
function proofMatches(value, binding) {
  if (!Object.hasOwn(value, "required_checks_binding")) return !Object.hasOwn(binding, "required_checks_sha256")
  const digest = requiredChecksFingerprint(value.required_checks_binding)
  return digest !== null && digest === binding.required_checks_sha256
}

function validDelegation(value) {
  const keys = ["scope", "reviewer", "authorization_sha256", "review_receipt_sha256"]
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value, k))
    && value.scope === "one_manual_post" && value.reviewer === "codex"
    && [value.authorization_sha256, value.review_receipt_sha256].every(v => typeof v === "string" && /^[a-f0-9]{64}$/.test(v))
}

export function reviewIsCurrent(draft, policy = null) {
  const media = Object.hasOwn(draft, "media_attachment")
  const binding = draft.review_binding
  if (media && (!validGistMedia(draft) || binding?.kind !== "human_media" || binding.media_sha256 !== fingerprint(draft.media_attachment))) return false
  // Published originals also need the person's exact label/context/reuse attestations.
  if (media && JSON.stringify(binding.published_attestations ?? null) !== JSON.stringify(attestationRecord(requiredAttestations(draft.media_attachment)))) return false
  if (draft.revision_conflicts?.length || !bindingMatches(draft, binding)) return false
  if (!policyMatches(binding, policy)) return false
  if (binding.kind === "human" || (media && binding.kind === "human_media")) return true
  if (binding.kind === "delegated") return validDelegation(binding.delegation)
  if (binding.kind !== "model" || !checksPass(twoBot(draft))) return false
  try { return proofMatches(twoBot(draft), binding) && binding.checks_sha256 === fingerprint(checks(twoBot(draft))) } catch { return false }
}

export function approvalIsCurrent(draft, mode = null, policy = null) {
  const binding = draft.approval_binding
  if (!reviewIsCurrent(draft, policy) || !bindingMatches(draft, binding) || !policyMatches(binding, policy)) return false
  if (!["manual", "auto"].includes(binding.mode) || (mode && binding.mode !== mode)) return false
  try { if (binding.decision_revision !== decisionRevision(draft)) return false } catch { return false }
  try { if ((draft.review_binding.kind === "delegated" || Object.hasOwn(binding, "review_binding_sha256")) && binding.review_binding_sha256 !== fingerprint(draft.review_binding)) return false } catch { return false }
  if ((binding.publish_intent_id ?? null) !== (draft.publish_intent_id ?? null)) return false
  return binding.mode !== "auto" || draft.review_binding.kind === "model"
}

export function hasUnresolvedPublish(draft, state) {
  function unresolved(attempt) {
    if (!attempt || typeof attempt !== "object" || Array.isArray(attempt)) return true
    const conflicts = Object.hasOwn(attempt, "attempt_conflicts") ? attempt.attempt_conflicts : []
    if (!Array.isArray(conflicts) || conflicts.some(unresolved)) return true
    if (attempt.tweet_id) {
      if (Object.hasOwn(attempt, "text_sha256")) return !bindingMatches(draft, attempt)
      return typeof attempt.text === "string" && attempt.text !== draft.text
    }
    return attempt.phase !== "not_sent"
  }
  const ledger = state.publish_ledger || {}
  const eventId = draft.event_id || draft.id
  if (Object.hasOwn(ledger, eventId) && unresolved(ledger[eventId])) return true
  if (["submitted", "unknown"].includes(draft.publish_outcome)) return true
  if (draft.status === "posted" || ["not_sent", "confirmed"].includes(draft.publish_outcome)) return false
  return !!(draft.autoship_attempted || draft.last_publish_attempt_at)
}

export function recordModelReview(draft, policy = null) {
  revokeApproval(draft)
  const value = twoBot(draft)
  let proven = false
  try {
    proven = !Object.hasOwn(value, "required_checks_binding") && !Object.hasOwn(draft, "media_attachment") && validEditorialPolicy(policy) && value.reviewed_policy_sha256 === fingerprint(policy) && checksPass(value) && value.reviewed_text_sha256 === textHash(draft.text ?? "")
      && Object.hasOwn(value, "bundle") && value.reviewed_bundle_sha256 === fingerprint(value.bundle)
  } catch { /* Invalid evidence cannot establish a review. */ }
  if (proven && !draft.revision_conflicts?.length) {
    draft.review_binding = { ...draftIdentity(draft), kind: "model", reviewed_at: new Date().toISOString(), checks_sha256: fingerprint(checks(value)), editorial_policy: structuredClone(policy), policy_sha256: fingerprint(policy) }
  } else delete draft.review_binding
  return draft
}

export function initializeRevision(draft, policy = null) {
  if (!Object.hasOwn(draft, "content_revision")) draft.content_revision = 1
  return recordModelReview(draft, policy)
}

export function recordHumanReview(draft, policy = null) {
  if (Object.hasOwn(draft, "media_attachment")) throw new Error("Joint media review is required; text-only review cannot approve this draft")
  if (draft.revision_conflicts?.length) throw new Error("Resolve the conflicting revision before reviewing")
  if (typeof draft.text !== "string" || !draft.text.trim() || [...draft.text].length > 280) throw new Error("Invalid draft text")
  if (!validEditorialPolicy(policy)) throw new Error("Editorial policy unverified; cannot establish a new review")
  draft.content_revision = Math.max(1, draftIdentity(draft).content_revision)
  revokeApproval(draft)
  draft.review_binding = { ...draftIdentity(draft), kind: "human", reviewed_at: new Date().toISOString(), editorial_policy: structuredClone(policy), policy_sha256: fingerprint(policy) }
  return draft
}

const attestationRecord = required => required.length ? { version: 1, confirmed: [...required] } : null

export function recordJointMediaReview(draft, policy = null, attestations = null) {
  if (!validGistMedia(draft)) throw new Error("This graphic needs a new preview")
  const required = requiredAttestations(draft.media_attachment), supplied = attestations ?? {}
  if (!supplied || typeof supplied !== "object" || Array.isArray(supplied) || Object.keys(supplied).length !== required.length
      || !required.every(name => supplied[name] === true)) throw new Error("Confirm every required published-image attestation")
  if (draft.revision_conflicts?.length) throw new Error("Resolve the conflicting revision before reviewing")
  if (typeof draft.text !== "string" || !draft.text.trim() || [...draft.text].length > 280) throw new Error("Invalid draft text")
  textHash(draft.text)
  if (!validEditorialPolicy(policy)) throw new Error("Editorial policy unverified")
  draft.content_revision = Math.max(1, draftIdentity(draft).content_revision)
  revokeApproval(draft)
  draft.review_binding = { ...draftIdentity(draft), kind: "human_media", reviewed_at: new Date().toISOString(),
    editorial_policy: structuredClone(policy), policy_sha256: fingerprint(policy), media_sha256: fingerprint(draft.media_attachment) }
  if (required.length) draft.review_binding.published_attestations = attestationRecord(required)
  return draft
}

export function invalidateMediaAttachment(draft, attachment) {
  if (attachment !== null && (!attachment || typeof attachment !== "object" || Array.isArray(attachment))) throw new Error("Invalid media attachment")
  if (attachment === null && !Object.hasOwn(draft, "media_attachment")) return draft
  if (attachment !== null && Object.hasOwn(draft, "media_attachment") && fingerprint(attachment) === fingerprint(draft.media_attachment)) return draft
  const previous = {}
  for (const key of ["text", "review_context", "review_binding", "approval_binding", "revision_conflicts", "decision_revision", "media_attachment", "media_review_binding"]) {
    if (Object.hasOwn(draft, key)) previous[key] = structuredClone(draft[key])
  }
  Object.assign(previous, draftIdentity(draft), { invalidated_at: new Date().toISOString() })
  if (previous.content_revision >= Number.MAX_SAFE_INTEGER || decisionRevision(draft) >= Number.MAX_SAFE_INTEGER - 1) throw new Error("Revision exhausted")
  if (Object.hasOwn(draft, "revision_history") && (!Array.isArray(draft.revision_history) || draft.revision_history.some(x => !x || typeof x !== "object" || Array.isArray(x)))) throw new Error("Invalid revision history")
  draft.revision_history ??= []
  draft.revision_history.push(previous)
  draft.content_revision = previous.content_revision + 1
  draft.status = "pending"
  revokeApproval(draft)
  for (const key of ["review_binding", "media_review_binding", "revision_conflicts", "candidate_score", "selected_candidate_rank"]) delete draft[key]
  if (draft.review_context?.two_bot) draft.review_context.two_bot = Object.fromEntries(Object.entries(draft.review_context.two_bot).filter(([key]) => ["bundle", "signal_kind"].includes(key)))
  if (attachment === null) delete draft.media_attachment
  else draft.media_attachment = structuredClone(attachment)
  return draft
}

export function authorizeDraft(draft, mode, intentId = null, publicationEpoch = null, policy = null) {
  if (!reviewIsCurrent(draft, policy)) throw new Error("This revision needs revalidation")
  if (!["manual", "auto"].includes(mode)) throw new Error("Invalid approval mode")
  if (mode === "auto" && draft.review_binding.kind !== "model") throw new Error("Scheduling requires a current model review")
  if (mode === "auto") {
    const publication = configuredAutomaticPolicy()
    if (!publication.enabled || (publicationEpoch !== null && publicationEpoch !== publication.epoch)) throw new Error("Automatic publication is paused")
    publicationEpoch = publication.epoch
  }
  advanceDecision(draft)
  draft.approval_binding = { ...draftIdentity(draft), decision_revision: draft.decision_revision, mode, authorized_at: new Date().toISOString(), editorial_policy: structuredClone(policy), policy_sha256: fingerprint(policy) }
  if (draft.review_binding.kind === "delegated") draft.approval_binding.review_binding_sha256 = fingerprint(draft.review_binding)
  if (mode === "auto") draft.approval_binding.publication_epoch = publicationEpoch
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

const referencesOmitted = Symbol("references omitted")
export function invalidateText(draft, newText, operatorClaimReferences = referencesOmitted) {
  if (typeof newText !== "string" || !newText.trim() || [...newText].length > 280) throw new Error("Invalid draft text")
  textHash(newText) // Reject malformed Unicode before changing durable fields.
  if (draft.review_context != null && (typeof draft.review_context !== "object" || Array.isArray(draft.review_context))) throw new Error("Invalid draft review context")
  const old = draft.review_context && Object.hasOwn(draft.review_context, "operator_claim_references") ? draft.review_context.operator_claim_references : referencesOmitted
  let references
  if (operatorClaimReferences === referencesOmitted) references = newText === draft.text ? old : referencesOmitted
  else {
    const bundle = draft.review_context?.two_bot?.bundle
    if (Array.isArray(operatorClaimReferences) && operatorClaimReferences.length && (bundle?.event_id !== draft.event_id || !operatorClaimKindMatches(draft.type, bundle?.signal_kind))) throw new Error("Saved source snapshot does not match this draft")
    references = buildOperatorClaimReferences(newText, bundle, operatorClaimReferences) ?? referencesOmitted
  }
  const sameReferences = references === old || (references !== referencesOmitted && old !== referencesOmitted && fingerprint(references) === fingerprint(old))
  if (newText === draft.text && sameReferences && !draft.revision_conflicts?.length) return draft
  const previous = {}
  for (const key of ["text", "review_context", "review_binding", "approval_binding", "revision_conflicts", "decision_revision", "media_attachment", "media_review_binding"]) {
    if (Object.hasOwn(draft, key)) previous[key] = structuredClone(draft[key])
  }
  Object.assign(previous, draftIdentity(draft), { invalidated_at: new Date().toISOString() })
  if (previous.content_revision >= Number.MAX_SAFE_INTEGER) throw new Error("Content revision exhausted")
  if (decisionRevision(draft) >= Number.MAX_SAFE_INTEGER - 1) throw new Error("Decision revision exhausted")
  if (Object.hasOwn(draft, "revision_history") && (!Array.isArray(draft.revision_history) || draft.revision_history.some((row) => !row || typeof row !== "object" || Array.isArray(row)))) throw new Error("Invalid revision history")
  draft.revision_history ??= []
  draft.revision_history.push(previous)
  draft.content_revision = previous.content_revision + 1
  draft.text = newText
  draft.status = "pending"
  revokeApproval(draft)
  for (const key of ["review_binding", "media_review_binding", "revision_conflicts", "candidate_score", "selected_candidate_rank"]) delete draft[key]
  if (draft.review_context?.two_bot) {
    draft.review_context.two_bot = Object.fromEntries(Object.entries(draft.review_context.two_bot).filter(([key]) => ["bundle", "signal_kind"].includes(key)))
  }
  if (references === referencesOmitted) {
    if (draft.review_context) delete draft.review_context.operator_claim_references
  } else {
    draft.review_context ??= {}
    draft.review_context.operator_claim_references = structuredClone(references)
  }
  return draft
}

export function projectDraft(draft, policy = null) {
  const current = reviewIsCurrent(draft, policy)
  const identity = { ...draftIdentity(draft), decision_revision: decisionRevision(draft) }
  const value = twoBot(draft), binding = draft.review_binding
  let analysisMatches = false
  try {
    // Content binding can survive a policy change. This is historical model
    // analysis for the saved input, never a current check or permission to post.
    analysisMatches = !draft.revision_conflicts?.length && binding?.kind === "model"
      && bindingMatches(draft, binding) && proofMatches(value, binding)
      && value.reviewed_text_sha256 === identity.text_sha256
      && value.reviewed_bundle_sha256 === fingerprint(value.bundle)
      && binding.checks_sha256 === fingerprint(checks(value))
  } catch { /* An unverifiable historical analysis stays hidden. */ }
  return { ...draft, revision_identity: identity,
    media_attachment_sha256: validGistMedia(draft) ? fingerprint(draft.media_attachment) : null,
    claim_evidence: projectSavedClaimEvidence(draft, { identity, analysisMatches }),
    operator_claim_reference_view: projectOperatorClaimReferences(draft, draftIdentity(draft)),
    operator_claim_reference_history: projectOperatorClaimReferenceHistory(draft),
    review_status: draft.revision_conflicts?.length ? "conflict" : Object.hasOwn(draft, "media_attachment") && !current ? "media_review_required" : !validEditorialPolicy(policy) ? "policy_unverified" : current ? "passed" : "needs_revalidation", review_kind: current ? draft.review_binding.kind : null }
}

// Passive provenance never participates in draftIdentity or authorization.
export function mergePassiveMaps(...maps) {
  const rows = new Map()
  for (const value of maps) {
    if (!passiveObject(value)) {
      const retained = unavailableRecord("container", value)
      rows.set(retained.sha256, retained.payload)
      continue
    }
    for (const [key, payload] of Object.entries(value)) {
      if (storedUnavailable(key, payload)) rows.set(key, structuredClone(payload))
      else {
        const retained = passivePayload(payload)
        rows.set(retained.sha256, retained.payload)
      }
    }
  }
  return Object.fromEntries([...rows].sort(([a], [b]) => a.localeCompare(b)))
}
export function normalizePassiveSnapshots(value) {
  const out = structuredClone(value)
  if (!out || typeof out !== "object" || Array.isArray(out)) return out
  for (const key of ["writer_observations", "publication_observations"]) {
    if (Object.hasOwn(out, key)) out[key] = mergePassiveMaps(out[key])
  }
  const two = out.review_context?.two_bot
  if (two && typeof two === "object" && !Array.isArray(two) && Object.hasOwn(two, "accepted_writer_observation")) {
    two.accepted_writer_observation = passivePayload(two.accepted_writer_observation).payload
  }
  for (const key of ["revision_history", "revision_conflicts", "attempt_conflicts"]) {
    if (Array.isArray(out[key])) out[key] = out[key].map(normalizePassiveSnapshots)
  }
  if (Object.hasOwn(out, "published_revision")) out.published_revision = normalizePassiveSnapshots(out.published_revision)
  return out
}
function passiveUnicodeCanonical(value) {
  if (typeof value === "string") return ["string", value]
  if (Array.isArray(value)) return ["array", value.map(passiveUnicodeCanonical)]
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    const compare = (a, b) => {
      const left = Array.from(a, char => char.codePointAt(0)), right = Array.from(b, char => char.codePointAt(0))
      for (let index = 0; index < Math.min(left.length, right.length); index++) {
        if (left[index] !== right[index]) return left[index] - right[index]
      }
      return left.length - right.length
    }
    return ["object", Object.keys(value).sort(compare).map(key => [key, passiveUnicodeCanonical(value[key])])]
  }
  return canonical(value)
}
export function passiveComparisonValue(value) {
  return JSON.stringify(passiveUnicodeCanonical(value)).replace(/[\u007f-\uffff]/g,
    char => "\\u" + char.charCodeAt(0).toString(16).padStart(4, "0"))
}
const unavailablePrefix = "unavailable-v1:"
const unavailableDomain = "theheat.passive.unavailable-record.v1\0"
function unavailableRecord(category, value) {
  const payload = { passive_unavailable_record: { schema_version: 1, category, raw_data: passiveComparisonValue(value) } }
  const digest = createHash("sha256").update(unavailableDomain + passiveComparisonValue(payload), "ascii").digest("hex")
  return { sha256: unavailablePrefix + digest, payload }
}
function decodePassiveData(value) {
  if (!Array.isArray(value) || !value.length || typeof value[0] !== "string") throw new Error("Invalid passive data")
  const [kind, item] = value
  if (kind === "null" && value.length === 1) return null
  if (value.length !== 2) throw new Error("Invalid passive data")
  if (kind === "boolean" && typeof item === "boolean") return item
  if (kind === "string" && typeof item === "string") return item
  if (kind === "number" && typeof item === "string" && /^[a-f0-9]{16}$/.test(item)) {
    const number = Buffer.from(item, "hex").readDoubleBE()
    if (Number.isFinite(number)) return number
  }
  if (kind === "array" && Array.isArray(item)) return item.map(decodePassiveData)
  if (kind === "object" && Array.isArray(item)) {
    const entries = [], keys = new Set()
    for (const pair of item) {
      if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string" || keys.has(pair[0])) throw new Error("Invalid passive data")
      keys.add(pair[0]); entries.push([pair[0], decodePassiveData(pair[1])])
    }
    return Object.fromEntries(entries)
  }
  throw new Error("Invalid passive data")
}
function storedUnavailable(key, value) {
  if (typeof key !== "string" || !key.startsWith(unavailablePrefix) || !passiveExact(value, ["passive_unavailable_record"])) return false
  const record = value.passive_unavailable_record
  if (!passiveExact(record, ["schema_version", "category", "raw_data"]) || record.schema_version !== 1
    || !["unicode_payload", "container"].includes(record.category) || typeof record.raw_data !== "string" || /[^\x00-\x7f]/.test(record.raw_data)) return false
  try {
    const raw = decodePassiveData(JSON.parse(record.raw_data))
    if (passiveComparisonValue(raw) !== record.raw_data) return false
    if (record.category === "container") { if (passiveObject(raw)) return false }
    else {
      let invalidUnicode = false
      try { fingerprint(raw) } catch { invalidUnicode = true }
      if (!invalidUnicode) return false
    }
    const expected = unavailableRecord(record.category, raw)
    return expected.sha256 === key && fingerprint(expected.payload) === fingerprint(value)
  } catch { return false }
}
export function passivePayload(value) {
  try { return { sha256: fingerprint(value), payload: structuredClone(value) } } catch {
    return unavailableRecord("unicode_payload", value)
  }
}
const passiveObject = value => value !== null && typeof value === "object" && !Array.isArray(value)
const passiveSha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const passiveExact = (value, keys) => passiveObject(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
function passiveIdentity(value) {
  return passiveExact(value, ["content_revision", "text_sha256", "evidence_sha256"])
    && Number.isSafeInteger(value.content_revision) && value.content_revision >= 1
    && passiveSha(value.text_sha256) && passiveSha(value.evidence_sha256)
}
function passiveTime(value) {
  if (typeof value !== "string") return null
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/.exec(value)
  if (!match || Number(value.slice(0, 4)) < 1 || +match[2] > 23 || +match[3] > 59 || +match[4] > 59 || +(match[7] || 0) > 23 || +(match[8] || 0) > 59) return null
  const day = new Date(`${match[1]}T00:00:00Z`)
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== match[1]) return null
  const parsed = Date.parse(value.replace(/\.\d+(?=Z|[+-])/, ""))
  return Number.isFinite(parsed) ? BigInt(parsed) * 1000n + BigInt((match[5] || "").padEnd(6, "0")) : null
}
export function acceptedWriterObservation(text, bundle, angle, eventId) {
  return { schema_version: 1, basis: "accepted_writer_result", event_id: eventId,
    angle_chosen: angle, text_sha256: textHash(text), bundle_sha256: fingerprint(bundle) }
}
export function validWriterObservation(value, { admitted = true } = {}) {
  const keys = ["schema_version", "basis", "event_id", "angle_chosen", "text_sha256", "bundle_sha256", ...(admitted ? ["original_identity"] : [])]
  return passiveExact(value, keys) && value.schema_version === 1 && value.basis === "accepted_writer_result"
    && typeof value.event_id === "string" && value.event_id.trim().length > 0
    && typeof value.angle_chosen === "string" && value.angle_chosen.length <= 80 && /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(value.angle_chosen)
    && passiveSha(value.text_sha256) && passiveSha(value.bundle_sha256)
    && (!admitted || (passiveIdentity(value.original_identity) && value.original_identity.text_sha256 === value.text_sha256))
}
export function admitWriterObservation(draft) {
  const value = twoBot(draft).accepted_writer_observation, bundle = twoBot(draft).bundle
  if (!validWriterObservation(value, { admitted: false }) || !passiveObject(bundle)) return
  const identity = draftIdentity(draft)
  if (value.event_id !== draft.event_id || bundle.event_id !== value.event_id || value.text_sha256 !== identity.text_sha256 || value.bundle_sha256 !== fingerprint(bundle)) return
  draft.writer_observations = mergePassiveMaps({ captured: { ...structuredClone(value), original_identity: identity } })
}
export function publicationObservation(draft, eventId, receipt) {
  if (!Object.hasOwn(draft, "writer_observations")) return null
  const writers = mergePassiveMaps(draft.writer_observations), bundle = twoBot(draft).bundle
  const source = passiveObject(bundle) && bundle.event_id === eventId ? fingerprint(bundle) : null
  const history = {}, retained = Array.isArray(draft.revision_history) ? draft.revision_history : []
  let unavailable = Object.hasOwn(draft, "revision_history") && !Array.isArray(draft.revision_history)
  for (const row of retained) {
    try {
      const at = passiveObject(row) ? passiveTime(row.invalidated_at) : null
      const identity = Object.fromEntries(["content_revision", "text_sha256", "evidence_sha256"].map(key => [key, row?.[key]]))
      if (!passiveObject(row) || !passiveIdentity(identity) || row.content_revision >= receipt.content_revision
        || typeof row.text !== "string" || textHash(row.text) !== row.text_sha256 || at === null
        || passiveTime(receipt.at) === null || at > passiveTime(receipt.at)) { unavailable = true; continue }
      const compact = Object.fromEntries(["content_revision", "text_sha256", "invalidated_at"].map(key => [key, row[key]]))
      history[fingerprint(compact)] = compact
    } catch { unavailable = true }
  }
  const writer = Object.values(writers).length === 1 ? Object.values(writers)[0] : null
  const valid = validWriterObservation(writer)
  return { schema_version: 1, basis: "pretransport_snapshot", event_id: eventId, intent_id: receipt.intent_id ?? null,
    at: receipt.at ?? null, identity: draftIdentity(draft), source_bundle_sha256: source,
    source_relation: valid && source ? (writer.bundle_sha256 === source ? "matches" : "differs") : "unknown",
    text_comparison: valid ? (writer.text_sha256 === textHash(draft.text) ? "matches" : "differs") : "unknown",
    writer_observations: writers,
    history_scope: "retained_incomplete", history_unavailable: unavailable, text_observations: mergePassiveMaps(history) }
}
export function publicationObservationStatus(value, eventId, receipt) {
  try { return checkedPublicationObservationStatus(value, eventId, receipt) } catch { return "unknown" }
}
function checkedPublicationObservationStatus(value, eventId, receipt) {
  const keys = ["schema_version", "basis", "event_id", "intent_id", "at", "identity", "source_bundle_sha256", "writer_observations", "history_scope", "history_unavailable", "text_observations", "source_relation", "text_comparison"]
  if (!passiveExact(value, keys)) return "unknown"
  const identity = Object.fromEntries(["content_revision", "text_sha256", "evidence_sha256"].map(key => [key, receipt[key] ?? null]))
  if (value.schema_version !== 1 || value.basis !== "pretransport_snapshot" || value.event_id !== eventId
    || typeof eventId !== "string" || !eventId.trim() || typeof value.intent_id !== "string" || !value.intent_id.trim()
    || value.intent_id !== receipt.intent_id || value.at !== receipt.at || passiveTime(value.at) === null
    || !passiveIdentity(value.identity) || fingerprint(value.identity) !== fingerprint(identity)
    || typeof receipt.text !== "string" || textHash(receipt.text) !== value.identity.text_sha256
    || value.history_scope !== "retained_incomplete" || typeof value.history_unavailable !== "boolean"
    || !passiveObject(value.writer_observations) || !passiveObject(value.text_observations)) return "unknown"
  const writers = Object.values(mergePassiveMaps(value.writer_observations))
  if (writers.length > 1) return "conflict"
  if (writers.length !== 1 || !validWriterObservation(writers[0]) || writers[0].event_id !== eventId
    || writers[0].original_identity.content_revision > value.identity.content_revision
    || writers[0].bundle_sha256 !== value.source_bundle_sha256 || value.source_relation !== "matches"
    || value.text_comparison !== (writers[0].text_sha256 === value.identity.text_sha256 ? "matches" : "differs")
    || (writers[0].original_identity.content_revision === value.identity.content_revision
      && fingerprint(writers[0].original_identity) !== fingerprint(value.identity))) return "unknown"
  const revisions = new Map()
  for (const row of Object.values(value.text_observations)) {
    if (!passiveExact(row, ["content_revision", "text_sha256", "invalidated_at"])
      || !Number.isSafeInteger(row.content_revision) || row.content_revision < 1 || row.content_revision >= value.identity.content_revision
      || !passiveSha(row.text_sha256) || passiveTime(row.invalidated_at) === null || passiveTime(row.invalidated_at) > passiveTime(value.at)) return "unknown"
    if (!revisions.has(row.content_revision)) revisions.set(row.content_revision, new Set())
    revisions.get(row.content_revision).add(row.text_sha256)
  }
  return [...revisions.values()].some(hashes => hashes.size > 1) ? "conflict" : "recorded"
}
export function qualifyingPublicationContext(receipt, eventId) {
  if (receipt.phase !== "confirmed" || !receipt.tweet_id || !Object.hasOwn(receipt, "publication_observations")
    || (Object.hasOwn(receipt, "attempt_conflicts") && (!Array.isArray(receipt.attempt_conflicts) || receipt.attempt_conflicts.some(row => !passiveObject(row))))) return null
  const values = Object.entries(mergePassiveMaps(receipt.publication_observations))
  return values.length === 1 && publicationObservationStatus(values[0][1], eventId, receipt) === "recorded" ? values[0][0] : null
}
