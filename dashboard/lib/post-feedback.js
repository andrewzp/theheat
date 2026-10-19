import { bindingMatches, draftIdentity, fingerprint, textHash } from "./draft-revisions.js"
import { parseGistDocument } from "./lossless-gist.js"

const PREFIX = "editorial-feedback-"
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const LIMIT = 100
const READ_LIMIT = 1000
const object = v => v && Object.getPrototypeOf(v) === Object.prototype
const exact = (v, keys) => object(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k))
const TARGET_KEYS = ["draft_id", "tweet_id", "posted_at", "text", "content_revision", "text_sha256", "evidence_sha256", "intent_id"]
const INPUT_KEYS = ["request_id", "target", "punch", "clarity", "economy", "note", "own_rating"]

export class FeedbackError extends Error {
  constructor(code, status = 503, diagnostic = null) {
    super(code); this.code = code; this.status = status
    Object.defineProperty(this, "diagnostic", {value:diagnostic})
  }
}
const fail = (code, status, diagnostic) => { throw new FeedbackError(code, status, diagnostic) }
const STAGES = new Set(["configuration", "feedback_archive", "feedback_records", "production_state_metadata", "production_state_raw", "production_state_document"])
const REASONS = new Set(["missing_or_invalid", "request_failed", "http_error", "response_unreadable", "invalid_json", "invalid_document", "not_private", "missing_state_file", "invalid_raw_origin"])
const storeFailure = (stage, reason, http_status = null) => fail("feedback_store_unavailable", 503, {stage, reason, http_status})

// Server logs get only this fixed vocabulary, never provider messages, URLs,
// credentials, receipt/text data or an arbitrary Error object's properties.
export function feedbackDiagnostic(error) {
  if (!(error instanceof FeedbackError) || error.code !== "feedback_store_unavailable") return null
  const value = error.diagnostic
  if (!exact(value, ["stage", "reason", "http_status"]) || !STAGES.has(value.stage) || !REASONS.has(value.reason) ||
      (value.http_status !== null && (!Number.isInteger(value.http_status) || value.http_status < 100 || value.http_status > 599))) return null
  return {stage:value.stage, reason:value.reason, http_status:value.http_status}
}

export function feedbackTarget(draft, state) {
  try {
    const receipt = state.publish_ledger?.[draft.event_id || draft.id]
    if (draft.status !== "posted" || draft.publish_outcome !== "confirmed" ||
        typeof draft.id !== "string" || !draft.id || typeof draft.tweet_id !== "string" || !/^[0-9]{1,30}$/.test(draft.tweet_id) ||
        typeof draft.posted_at !== "string" || !Number.isFinite(Date.parse(draft.posted_at)) ||
        typeof draft.text !== "string" || !draft.text.trim() || [...draft.text].length > 280 ||
        (draft.content_revision ?? 0) < 1 || draft.revision_conflicts?.length || !object(receipt) || receipt.phase !== "confirmed" ||
        receipt.tweet_id !== draft.tweet_id || receipt.text !== draft.text ||
        !UUID.test(receipt.intent_id) || (Object.hasOwn(receipt, "attempt_conflicts") &&
          (!Array.isArray(receipt.attempt_conflicts) || receipt.attempt_conflicts.length)) ||
        !bindingMatches(draft, receipt)) return null
    return { draft_id:draft.id, tweet_id:draft.tweet_id, posted_at:draft.posted_at, text:draft.text,
      ...draftIdentity(draft), intent_id:receipt.intent_id }
  } catch { return null }
}

export function feedbackInput(value) {
  if (!exact(value, INPUT_KEYS) || !UUID.test(value.request_id) || !exact(value.target, TARGET_KEYS) ||
      value.own_rating !== true || ![value.punch, value.clarity, value.economy].every(v => Number.isInteger(v) && v >= 1 && v <= 5) ||
      typeof value.note !== "string" || [...value.note].length > 500 ||
      Buffer.from(value.note, "utf8").toString("utf8") !== value.note) fail("invalid_feedback", 400)
  const target = value.target
  try {
    if (typeof target.draft_id !== "string" || !target.draft_id || target.draft_id.length > 200 ||
        typeof target.tweet_id !== "string" || !/^[0-9]{1,30}$/.test(target.tweet_id) ||
        typeof target.posted_at !== "string" || !Number.isFinite(Date.parse(target.posted_at)) ||
        typeof target.text !== "string" || !target.text.trim() || [...target.text].length > 280 ||
        !Number.isSafeInteger(target.content_revision) || target.content_revision < 1 ||
        target.text_sha256 !== textHash(target.text) || !/^[a-f0-9]{64}$/.test(target.evidence_sha256) ||
        !UUID.test(target.intent_id)) fail("invalid_feedback", 400)
    fingerprint(value)
  } catch { fail("invalid_feedback", 400) }
  return structuredClone(value)
}

function filename(id) { return `${PREFIX}${id}.json` }
function recordInput(record) { return Object.fromEntries(INPUT_KEYS.map(k => [k, record[k]])) }
export function feedbackRecord(value) {
  const record = structuredClone(value)
  try { feedbackInput(recordInput(record)) } catch { fail("feedback_store_unavailable") }
  if (!exact(record, [...INPUT_KEYS, "schema_version", "kind", "received_at"]) || record.schema_version !== 1 ||
      record.kind !== "dashboard_editorial_opinion" ||
      typeof record.received_at !== "string" || !Number.isFinite(Date.parse(record.received_at))) fail("feedback_store_unavailable")
  return record
}
function decodeRecord(file, name) {
  if (!file || file.truncated || typeof file.content !== "string" || Buffer.byteLength(file.content) > 8192) fail("feedback_store_unavailable")
  let record
  try { record = feedbackRecord(JSON.parse(file.content)) } catch { fail("feedback_store_unavailable") }
  if (name !== filename(record.request_id)) fail("feedback_store_unavailable")
  return record
}

async function github(path, options = {}, storage = "feedback") {
  const token = process.env.GITHUB_TOKEN, gistId = storage === "state" ? process.env.GIST_ID : process.env.THEHEAT_FEEDBACK_GIST_ID
  const stage = storage === "state" ? "production_state_metadata" : "feedback_archive"
  if (!token || !/^[a-zA-Z0-9_]+$/.test(gistId || "")) storeFailure("configuration", "missing_or_invalid")
  try {
    return await fetch(`https://api.github.com/gists/${gistId}${path}`, {
      ...options, headers:{ Accept:"application/vnd.github+json", Authorization:`token ${token}`,
        ...(options.body ? { "Content-Type":"application/json" } : {}) },
      cache:"no-store", redirect:"error", signal:AbortSignal.timeout(8000),
    })
  } catch { storeFailure(stage, "request_failed") }
}

async function boundedText(response, limit, stage) {
  if (!response.body) storeFailure(stage, "response_unreadable")
  const reader = response.body.getReader(), chunks = []
  let size = 0, timer
  const deadline = new Promise((_, reject) => {timer = setTimeout(() => reject(new FeedbackError("feedback_store_unavailable")), 8000)})
  try {
    while (true) {
      const {done, value} = await Promise.race([reader.read(), deadline])
      if (done) break
      size += value.byteLength
      if (size > limit) fail("feedback_store_unavailable")
      chunks.push(Buffer.from(value))
    }
    return new TextDecoder("utf-8", {fatal:true}).decode(Buffer.concat(chunks))
  } catch { storeFailure(stage, "response_unreadable") }
  finally {clearTimeout(timer); void reader.cancel().catch(() => {})}
}

async function load(requestId = null) {
  const response = await github("")
  if (!response.ok) storeFailure("feedback_archive", "http_error", response.status)
  let gist
  try { gist = JSON.parse(await boundedText(response, 16 * 1024 * 1024, "feedback_archive")) }
  catch (error) { if (error instanceof FeedbackError) throw error; storeFailure("feedback_archive", "invalid_json") }
  // Opinions belong only in the separately configured secret feedback Gist. Never
  // follow raw feedback URLs or expose the provider's response/error body.
  if (!object(gist) || !object(gist.files)) storeFailure("feedback_archive", "invalid_document")
  if (gist.public !== false) storeFailure("feedback_archive", "not_private")
  const names = Object.keys(gist.files).filter(name => name.startsWith(PREFIX))
  // The write threshold is admission, not a transactional ceiling. Concurrent
  // writers can cross it; keep those receipts readable. Beyond the full archive
  // read bound, an exact request ID still has a bounded recovery path.
  if (names.length > READ_LIMIT && !requestId) fail("feedback_capacity")
  const selected = names.length > READ_LIMIT ? names.filter(name => name === filename(requestId)) : names
  let records
  try { records = selected.map(name => decodeRecord(gist.files[name], name)) }
  catch { storeFailure("feedback_records", "invalid_document") }
  const stateResponse = await github("", {}, "state")
  if (!stateResponse.ok) storeFailure("production_state_metadata", "http_error", stateResponse.status)
  let stateGist
  try {stateGist = JSON.parse(await boundedText(stateResponse, 16 * 1024 * 1024, "production_state_metadata"))}
  catch (error) { if (error instanceof FeedbackError) throw error; storeFailure("production_state_metadata", "invalid_json") }
  if (!object(stateGist) || !object(stateGist.files)) storeFailure("production_state_metadata", "invalid_document")
  const file = stateGist.files?.["state.json"]
  if (!file) storeFailure("production_state_metadata", "missing_state_file")
  let content = file.content
  if (file.truncated) {
    // Same fixed GitHub origin as the existing state reader, never arbitrary URLs.
    let raw
    try { raw = new URL(file.raw_url) } catch { storeFailure("production_state_raw", "invalid_raw_origin") }
    if (raw.protocol !== "https:" || raw.hostname !== "gist.githubusercontent.com" || raw.username || raw.password || raw.port) storeFailure("production_state_raw", "invalid_raw_origin")
    let response
    try { response = await fetch(raw.href, {cache:"no-store", redirect:"error", signal:AbortSignal.timeout(8000)}) } catch { storeFailure("production_state_raw", "request_failed") }
    if (!response.ok) storeFailure("production_state_raw", "http_error", response.status)
    content = await boundedText(response, 8 * 1024 * 1024, "production_state_raw")
  }
  let state
  try { state = parseGistDocument(content).value } catch { storeFailure("production_state_document", "invalid_document") }
  if (!object(state) || !Array.isArray(state.drafts)) storeFailure("production_state_document", "invalid_document")
  return { state, records, recordCount:names.length }
}

function currentTargets(state) {
  return state.drafts.map(d => feedbackTarget(d, state)).filter(Boolean)
    .sort((a, b) => Date.parse(b.posted_at) - Date.parse(a.posted_at))
}

export async function readPostFeedback(requestId = null) {
  if (requestId !== null && !UUID.test(requestId)) fail("invalid_feedback", 400)
  const { state, records, recordCount } = await load(requestId)
  const targets = currentTargets(state)
  const posts = targets.map(target => ({ target, ratings:records.filter(r => fingerprint(r.target) === fingerprint(target))
    .sort((a, b) => b.received_at.localeCompare(a.received_at) || b.request_id.localeCompare(a.request_id)) }))
  return { posts, remaining:Math.max(0, LIMIT - recordCount),
    request:requestId ? records.find(r => r.request_id === requestId) || null : null,
    kind:"dashboard_editorial_opinion", archive_complete:recordCount <= READ_LIMIT, independent_human_benchmark:false }
}

export async function savePostFeedback(value) {
  const input = feedbackInput(value)
  const { state, records, recordCount } = await load(input.request_id)
  const existing = records.find(r => r.request_id === input.request_id)
  if (existing) {
    if (fingerprint(recordInput(existing)) !== fingerprint(input)) fail("feedback_id_conflict", 409)
    return { record:existing, already_saved:true }
  }
  if (recordCount >= LIMIT) fail("feedback_capacity", 409)
  if (!currentTargets(state).some(target => fingerprint(target) === fingerprint(input.target))) fail("post_changed", 409)
  const record = { ...input, schema_version:1, kind:"dashboard_editorial_opinion", received_at:new Date().toISOString() }
  // Auxiliary immutable UUID file in the secret feedback archive only. No state.json rewrite or review/approval
  // command. Separate IDs do not overwrite one shared feedback list. Gist is
  // still not transactional; do not retry an uncertain PATCH automatically.
  try {
    const result = await github("", { method:"PATCH", body:JSON.stringify({files:{[filename(input.request_id)]:{content:JSON.stringify(record)}}}) })
    if (!result.ok) fail("feedback_write_uncertain")
    const after = await load(input.request_id)
    const saved = after.records.find(r => r.request_id === input.request_id)
    if (!saved || fingerprint(saved) !== fingerprint(record)) fail("feedback_write_uncertain")
    return {record:saved, already_saved:false}
  } catch { fail("feedback_write_uncertain") }
}
