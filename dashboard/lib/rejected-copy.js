import { fingerprint, textHash } from "./draft-revisions.js"

const object = value => value !== null && typeof value === "object"
  && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const nonempty = value => typeof value === "string" && value.trim().length > 0
const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length
  && keys.every(key => Object.hasOwn(value, key))

// Display bounds only. A matching digest is not a check, a source warrant or
// authority to retry, import or publish this candidate.
function safeJson(value, budget = { nodes: 0 }, depth = 0) {
  if (++budget.nodes > 12000 || depth > 40) return false
  if (typeof value === "string") return Buffer.from(value, "utf8").toString("utf8") === value
  if (typeof value === "number") return Number.isFinite(value)
    && (!Number.isInteger(value) || Number.isSafeInteger(value))
  if (value === null || typeof value === "boolean") return true
  if (Array.isArray(value)) return value.every(item => safeJson(item, budget, depth + 1))
  return object(value) && Object.entries(value).every(([key, child]) =>
    safeJson(key, budget, depth + 1) && safeJson(child, budget, depth + 1))
}

function persistedSizeBound(value) {
  // The producer's json.JSONEncoder uses ensure_ascii and separator spaces.
  // JSON parsing loses Python's int/float spelling: reserve the larger finite
  // spelling, including .0 / exponent padding. Near-limit ambiguity stays held.
  if (typeof value === "string") return JSON.stringify(value)
    .replace(/[\u007f-\uffff]/g, char => "\\u" + char.charCodeAt(0).toString(16).padStart(4, "0")).length
  if (typeof value === "number") return Number.isInteger(value)
    ? String(value).length + 2 + Number(Object.is(value, -0))
    : Math.max(String(value).length, value.toExponential().length) + 2
  if (value === null) return 4
  if (typeof value === "boolean") return value ? 4 : 5
  if (Array.isArray(value)) return 2 + value.reduce((sum, item) => sum + persistedSizeBound(item), 0)
    + Math.max(0, value.length - 1) * 2
  const pairs = Object.entries(value)
  return 2 + pairs.reduce((sum, [key, item]) => sum + persistedSizeBound(key) + 2 + persistedSizeBound(item), 0)
    + Math.max(0, pairs.length - 1) * 2
}

function negativeVerdict(packet, stage, row) {
  const v = packet.verdict
  if (!object(v) || v.passed !== false) return null
  const reasonMatches = reason => nonempty(reason) && Array.isArray(row.reasons) && row.reasons[0] === reason
  if (stage === "fact_check") {
    return exact(v, ["check_path", "passed", "failures", "extracted_claims", "response_diagnostic"])
      && ["local_precheck", "required_checker"].includes(v.check_path)
      && Array.isArray(v.failures) && v.failures.every(reason => typeof reason === "string")
      && reasonMatches(v.failures.join("; ") || "unknown")
      && Array.isArray(v.extracted_claims) && v.extracted_claims.every(claim =>
        exact(claim, ["text", "kind"]) && typeof claim.text === "string" && typeof claim.kind === "string")
      && typeof v.response_diagnostic === "string"
      && /^(?:response_chars=(?:0|[1-9][0-9]*) response_sha256=[a-f0-9]{64}|response_type=[A-Za-z_][A-Za-z_0-9]{0,63})$/.test(v.response_diagnostic)
      ? v.failures : null
  }
  if (stage === "safety") {
    return exact(v, ["check_path", "passed", "reason", "response_status", "response_diagnostic"])
      && v.check_path === "safety_pipeline" && reasonMatches(v.reason)
      && !v.reason.startsWith("safety_") && v.response_status === "not_exposed"
      && v.response_diagnostic === null ? [v.reason] : null
  }
  if (stage === "critic") {
    return exact(v, ["check_path", "passed", "verdict", "kill_reason", "response_diagnostic"])
      && v.check_path === "critic_review" && v.verdict === "KILL" && reasonMatches(v.kill_reason)
      && typeof v.response_diagnostic === "string"
      && /^response_chars=[1-9][0-9]* response_sha256=[a-f0-9]{64}$/.test(v.response_diagnostic)
      ? [v.kill_reason] : null
  }
  return exact(v, ["check_path", "passed", "reason", "subsequent_checks"])
    && v.check_path === "local_copy_gate" && reasonMatches(v.reason)
    && v.subsequent_checks === "not_run" ? [v.reason] : null
}

export function rejectedCopyPreview(row) {
  if (!object(row) || !Object.hasOwn(row, "rejected_candidate")) return { status: "missing" }
  const p = row.rejected_candidate
  if (!object(p)) return { status: "invalid" }
  const stage = row.stage
  const knownStage = ["fact_check", "safety", "critic", "copy_gate"].includes(stage)
  const schema = stage === "fact_check" ? p.schema_version === 1
    : p.schema_version === 2 && p.stage === stage
  if (!knownStage || !schema || p.scope !== `selected_${stage}_rejection`) return { status: "invalid" }
  // Provider unavailability is not a completed negative verdict. Never fall
  // back to raw text on an explicitly unavailable or malformed packet.
  if (p.status === "unavailable") return { status: "unavailable" }
  try {
    const limit = stage === "copy_gate" ? 8192 : 40960
    const fields = ["schema_version", "scope", "status", "attempt", "text", "text_sha256", "bundle", "bundle_phase", "bundle_sha256", "verdict"]
    if (stage !== "fact_check") fields.push("stage")
    if (!exact(p, fields) || p.status !== "retained" || ![1, 2].includes(p.attempt)
      || !Number.isInteger(p.attempt) || !nonempty(p.text)
      || Buffer.byteLength(p.text, "utf8") > 4096 || !safeJson(p)
      || persistedSizeBound(p) > limit
      || !sha(p.text_sha256) || textHash(p.text) !== p.text_sha256
      || !object(p.bundle) || !sha(p.bundle_sha256) || fingerprint(p.bundle) !== p.bundle_sha256
      || !nonempty(row.event_id) || p.bundle.event_id !== row.event_id
      || p.bundle_phase !== (stage === "fact_check" ? "before_local_fact_check" : `before_${stage}`)) {
      return { status: "invalid" }
    }
    const reasons = negativeVerdict(p, stage, row)
    if (reasons === null) return { status: "invalid" }
    return { status: "retained", stage, attempt: p.attempt, text: p.text,
      characters: [...p.text].length, reasons }
  } catch { return { status: "invalid" } }
}

export function projectSuppression(row) {
  return { ...row, rejected_copy: rejectedCopyPreview(row) }
}
