// P00c serialized Gist write route: mode, route record, writer guard and command envelope.
// Mirrors src/commands/gist_route.py and src/commands/gist_commands.py (same codes, same
// canonical bytes and digest). Default-off: with THEHEAT_GIST_WRITE_ROUTE unset and no route
// record in the state Gist, every direct writer behaves exactly as before.
import { createHash, randomUUID } from "node:crypto"
import { canonical } from "./local-command-recovery.js"
import { CLOCK_SKEW_MS, ENVELOPE_SCHEMA, MAX_LIFETIME_MS, parseEnvelope } from "./gist-command-seal.js"
import { CONTROL_ALG, controlKey, signRouteControl } from "./gist-route-control.js"

export const ROUTE_ENV = "THEHEAT_GIST_WRITE_ROUTE"
export const MARKER_ENV = "THEHEAT_SERIALIZED_WRITER"
export const ROUTE_FILE = "gist-write-route.json"
export const RESULTS_FILE = "gist-command-results.json"
export const CODE_GENERATION = 1
// v1 plaintext form: route control only (no private content). Sealed v2 bounds: gist-command-seal.js.
export const MAX_COMMAND_BYTES = 4096
export const CREDENTIAL_ENV = "THEHEAT_GIST_CREDENTIAL"
export const LEGACY_CREDENTIALS_ENV = "THEHEAT_LEGACY_CREDENTIALS_PRESENT"
export const ROUTE_CONTROL_ACTIONS = new Set(["activate_route", "deactivate_route"])
export const COMMAND_WORKFLOW = "gist-commands.yml"
export const ARTIFACT_PREFIX = "theheat-command-"
export const REFUSAL_PREFIX = "theheat-admission-refused-"
const REPO = "andrewzp/theheat"
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/
const MARKER = /^([0-9]{1,32}):([A-Za-z0-9_.-]{1,100})$/
export const PRODUCERS = Object.freeze({
  dashboard_editor: ["draft_update"],
  dashboard_reconciliation: ["reconcile_delivery"],
  post_feedback: ["post_feedback"],
  gist_route_control: ["activate_route", "deactivate_route"],
})
export const FEEDBACK_ACTIONS = new Set(["post_feedback"])
const ENVELOPE_KEYS = ["action", "actor_subject", "auth", "command_id", "expires_at", "payload", "producer", "requested_at", "schema_version", "targets"]
const B64_32 = /^[A-Za-z0-9+/]{43}=$/
const KID = /^[a-z0-9][a-z0-9-]{0,31}$/

export class RouteError extends Error {
  constructor(code, status = 409) { super(code); this.code = code; this.status = status; this.statusCode = status }
}
const refuse = (code, status) => { throw new RouteError(code, status) }

export function configuredRouteMode(env = process.env) {
  const value = env[ROUTE_ENV] ?? ""
  if (value === "" || value === "legacy") return "legacy"
  if (value === "serialized") return "serialized"
  refuse("invalid_gist_write_route", 503)
}

function utc(value) { return typeof value === "string" && UTC.test(value) && Number.isFinite(Date.parse(value)) }

export function decodeRouteRecord(content) {
  if (typeof content !== "string" || Buffer.byteLength(content) > 4096) refuse("gist_write_route_unreadable", 503)
  let value
  try { value = JSON.parse(content) } catch { refuse("gist_write_route_unreadable", 503) }
  const keys = ["changed_at", "changed_by_run", "command_id", "generation", "mode", "schema_version"]
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join() !== keys.join()
      || value.schema_version !== 1 || !["legacy", "serialized"].includes(value.mode)
      || !Number.isSafeInteger(value.generation) || value.generation < 1 || value.generation > 2 ** 31
      || !utc(value.changed_at) || typeof value.changed_by_run !== "string" || !MARKER.test(value.changed_by_run)
      || typeof value.command_id !== "string" || !UUID.test(value.command_id)) refuse("gist_write_route_unreadable", 503)
  return value
}

// Absent file: null (the legacy state). A present but truncated/malformed file refuses.
export function routeRecordFromFiles(files) {
  if (!files || typeof files !== "object" || !Object.hasOwn(files, ROUTE_FILE)) return null
  const meta = files[ROUTE_FILE]
  if (!meta || typeof meta !== "object" || meta.truncated) refuse("gist_write_route_unreadable", 503)
  return decodeRouteRecord(meta.content)
}

const plainObject = value => value && typeof value === "object" && !Array.isArray(value)

// The consumer's results file: {schema_version: 1, results, outbox?, rejected_envelopes?, control_results?}.
// Route-control results live in their OWN namespace: a control id can never settle a sealed command.
export function resultsDocumentFromFiles(files) {
  if (!files || typeof files !== "object" || !Object.hasOwn(files, RESULTS_FILE)) return { results: {}, outbox: {}, rejected: {}, control: {} }
  const meta = files[RESULTS_FILE]
  let value
  try {
    if (!meta || meta.truncated || typeof meta.content !== "string") throw new Error()
    value = JSON.parse(meta.content)
  } catch { refuse("command_results_unreadable", 503) }
  if (!value || value.schema_version !== 1 || !plainObject(value.results)
      || (Object.hasOwn(value, "outbox") && !plainObject(value.outbox))
      || (Object.hasOwn(value, "rejected_envelopes") && !plainObject(value.rejected_envelopes))
      || (Object.hasOwn(value, "control_results") && !plainObject(value.control_results))) refuse("command_results_unreadable", 503)
  return { results: value.results, outbox: value.outbox ?? {}, rejected: value.rejected_envelopes ?? {}, control: value.control_results ?? {} }
}

export function resultsFromFiles(files) { return resultsDocumentFromFiles(files).results }

export function resultsFileContent({ results, outbox = {}, rejected = {}, control = {} }) {
  return JSON.stringify({ schema_version: 1, results, ...(Object.keys(outbox).length ? { outbox } : {}),
    ...(Object.keys(rejected).length ? { rejected_envelopes: rejected } : {}),
    ...(Object.keys(control).length ? { control_results: control } : {}) })
}

export function serializedWriterMarker(env = process.env) {
  const value = env[MARKER_ENV] ?? ""
  if (value === "") return null
  const match = MARKER.exec(value)
  if (!match || (env.GITHUB_RUN_ID && match[1] !== env.GITHUB_RUN_ID)) refuse("invalid_serialized_writer_marker", 503)
  return value
}

export function routeEffective(record, env = process.env) {
  return configuredRouteMode(env) === "serialized" || record?.mode === "serialized"
}

// ROUTE-CONTRACT-v2 §3: ordinary commands are submitted and applied only while the variable
// AND the authoritative record both say serialized; the record's activation command id is the
// route generation a command is bound to. Any disagreement refuses (fail closed).
export function routeActive(record, env = process.env) {
  return configuredRouteMode(env) === "serialized" && record?.mode === "serialized"
}

export function activeRouteActivation(record, env = process.env) {
  if (!routeActive(record, env)) refuse("route_not_active", 409)
  return record.command_id
}

// Old-SHA fence (ROUTE-CONTRACT-v2 §6, amended 2026-11-02): route-era writes require the Gist
// writer token from its route-era secret name AND the workflow's presence check showing that no
// legacy Gist-writer or sender secret name still exists (reruns of old SHAs read only those).
// The workflow exports booleans only (`secrets.X != ''`), never values. Unset = fail closed.
export function routeCredentialCode(env = process.env) {
  if (env[CREDENTIAL_ENV] !== "route") return "route_writer_credential_legacy"
  if (env[LEGACY_CREDENTIALS_ENV] !== "false") return "route_legacy_credentials_present"
  return null
}

// Apply-time gate for one sealed command (terminal codes; null when it may apply).
export function routeApplyCode(envelope, record, env = process.env) {
  if (!routeActive(record, env)) return "route_not_active"
  if (record.command_id !== envelope.route_activation) return "route_generation_not_current"
  return null
}

// The exact Python check_writer rule: route mode requires the group marker and a code
// generation at least the recorded one; otherwise a direct PATCH is refused before egress.
export function assertDirectGistWrite(record, env = process.env) {
  if (!routeEffective(record, env)) return "legacy"
  if (serializedWriterMarker(env) === null) refuse("direct_write_disabled_by_route")
  if (record && CODE_GENERATION < record.generation) refuse("stale_writer_generation")
  return "serialized"
}

export function commandDigest(raw) { return createHash("sha256").update(raw, "utf8").digest("hex") }

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join() === [...keys].sort().join()
}

// Structural mirror of the Python admission for the v1 plaintext form, which since v2 carries
// route control only (src/commands/gist_commands.parse_command). Anything else is refused.
export function validateCommandRaw(raw, { now = new Date() } = {}) {
  if (typeof raw !== "string" || Buffer.byteLength(raw) > MAX_COMMAND_BYTES) refuse("command_too_large", 413)
  let value
  try { value = JSON.parse(raw) } catch { refuse("invalid_json", 400) }
  let text
  try { text = canonical(value) } catch { refuse("unsafe_number", 400) }
  if (text !== raw) refuse("non_canonical_command", 400)
  if (value?.schema_version === 1 && ROUTE_CONTROL_ACTIONS.has(value.action) && !Object.hasOwn(value, "auth")) refuse("route_control_unauthenticated", 403)
  if (!exactKeys(value, ENVELOPE_KEYS) || value.schema_version !== 1) refuse("invalid_command", 400)
  if (!ROUTE_CONTROL_ACTIONS.has(value.action)) refuse("plaintext_command_refused", 400)
  if (!exactKeys(value.auth, ["alg", "kid", "mac"]) || value.auth.alg !== CONTROL_ALG || typeof value.auth.kid !== "string"
      || !KID.test(value.auth.kid) || typeof value.auth.mac !== "string" || !B64_32.test(value.auth.mac)) refuse("route_control_unauthenticated", 403)
  if (!UUID.test(value.command_id)) refuse("invalid_command_id", 400)
  const allowed = PRODUCERS[value.producer?.kind]
  if (!exactKeys(value.producer, ["kind", "generation"]) || !allowed || !allowed.includes(value.action)
      || typeof value.producer.generation !== "string") refuse("unauthorized_writer_generation_refused", 403)
  if (!utc(value.requested_at) || !utc(value.expires_at)) refuse("invalid_time", 400)
  const requested = Date.parse(value.requested_at), expires = Date.parse(value.expires_at)
  if (requested > now.getTime() + 300000 || expires <= requested || expires > requested + 86400000) refuse("invalid_time", 400)
  if (typeof value.actor_subject !== "string" || !value.actor_subject || value.actor_subject.length > 200) refuse("invalid_command", 400)
  if (!Array.isArray(value.targets) || !value.payload || typeof value.payload !== "object" || Array.isArray(value.payload)) refuse("invalid_command", 400)
  return { command: value, raw, digest: commandDigest(raw), expired: expires <= now.getTime() }
}

// Either form: {kind: "sealed", envelope, raw, digest, expired} or {kind: "control", command, ...}.
export function parseCommandRaw(raw, { now = new Date() } = {}) {
  let schema = null
  try { schema = JSON.parse(raw)?.schema_version } catch { /* reported by the strict parser below */ }
  if (schema === ENVELOPE_SCHEMA) return { kind: "sealed", ...parseEnvelope(raw, { now }) }
  if (typeof raw === "string" && Buffer.byteLength(raw) > MAX_COMMAND_BYTES && schema !== 1) refuse("command_too_large", 413)
  const item = validateCommandRaw(raw, { now })
  return { kind: "control", ...item }
}

// Producer generation against the authoritative route record (consumer side).
export function producerGenerationCode(command, record) {
  const text = command.producer.generation
  if (!/^(0|[1-9][0-9]{0,9})$/.test(text)) return "unauthorized_writer_generation_refused"
  const generation = Number(text)
  if (generation === 0 || generation < (record?.generation ?? 1)) return "retired_writer_generation_refused"
  if (generation > CODE_GENERATION) return "unauthorized_writer_generation_refused"
  return null
}

// Route control only (root's form; tests and parity): signed with THEHEAT_ROUTE_CONTROL_KEY.
export function buildCommand({ action, producerKind, actorSubject, targets = [], payload, now = new Date(), lifetimeMs = 3600000, commandId = randomUUID(),
  env = process.env }) {
  const at = new Date(Math.floor(now.getTime() / 1000) * 1000)
  const key = controlKey(env)
  if (!key) refuse("route_control_key_missing", 503)
  const command = signRouteControl({ schema_version: 1, command_id: commandId, action,
    requested_at: at.toISOString().replace(/\.\d{3}Z$/, "Z"), expires_at: new Date(at.getTime() + lifetimeMs).toISOString().replace(/\.\d{3}Z$/, "Z"),
    producer: { kind: producerKind, generation: String(CODE_GENERATION) }, actor_subject: actorSubject, targets, payload }, key)
  const raw = canonical(command)
  validateCommandRaw(raw, { now })
  return { command, raw, digest: commandDigest(raw) }
}

function githubHeaders(token) {
  return { Accept: "application/vnd.github.v3+json", ...(token ? { Authorization: `token ${token}` } : {}) }
}

// Durable intake = a workflow_dispatch of gist-commands.yml with the exact canonical bytes.
// A lost response is reported as uncertain with the retained body; never as success.
export async function submitCommand(raw, { fetchImpl = globalThis.fetch, token = process.env.GITHUB_TOKEN, repo = REPO } = {}) {
  const parsed = parseCommandRaw(raw)
  const commandId = parsed.kind === "sealed" ? parsed.envelope.command_id : parsed.command.command_id
  const base = { command_id: commandId, digest: parsed.digest, command: raw }
  let response
  try {
    response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/workflows/${COMMAND_WORKFLOW}/dispatches`, {
      method: "POST", headers: { ...githubHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs: { command: raw } }),
    })
  } catch {
    return { ...base, status: "submission_uncertain", code: "command_submission_uncertain" }
  }
  if (response.status === 204 || response.ok) return { ...base, status: "pending" }
  return { ...base, status: "not_submitted", code: "command_submission_failed", http_status: response.status }
}

async function gistFiles(id, { fetchImpl, token }) {
  const response = await fetchImpl(`https://api.github.com/gists/${id}`, { headers: githubHeaders(token), cache: "no-store" })
  if (!response.ok) refuse("command_status_unavailable", 503)
  const gist = await response.json()
  return gist?.files ?? {}
}

// The authoritative route record, read fresh from the state Gist (secret-Gist GET needs no write).
export async function readRouteRecord({ fetchImpl = globalThis.fetch, token = process.env.GITHUB_TOKEN, gistId = process.env.GIST_ID } = {}) {
  if (!/^[A-Za-z0-9_]+$/.test(gistId || "")) refuse("route_record_unavailable", 503)
  return routeRecordFromFiles(await gistFiles(gistId, { fetchImpl, token }))
}

async function artifactsNamed(name, { fetchImpl, token, repo }) {
  const response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/artifacts?name=${encodeURIComponent(name)}&per_page=100`,
    { headers: githubHeaders(token), cache: "no-store" })
  if (!response.ok) refuse("command_status_unavailable", 503)
  const rows = (await response.json())?.artifacts
  return Array.isArray(rows) ? rows.filter(row => row?.name === name) : []
}

// Safe follow-up projection of the sender outbox entry an approval created (ids/codes only).
export function followUpOf(outbox, commandId) {
  const entry = Object.values(outbox || {}).find(row => row?.command_id === commandId)
  return entry ? { state: entry.state, code: entry.code ?? null, attempts: entry.attempts ?? 0, publish_intent_id: entry.publish_intent_id } : null
}

// applied | refused(code) | pending (admitted, not yet consumed) | unknown. Never synthesized:
// persisted results first, then EXACT-name artifact queries (no bounded scan can hide a command).
export async function commandStatus(commandId, { fetchImpl = globalThis.fetch, token = process.env.GITHUB_TOKEN, repo = REPO,
  gistId = process.env.GIST_ID, feedbackGistId = process.env.THEHEAT_FEEDBACK_GIST_ID, digest = null, now = new Date() } = {}) {
  if (!UUID.test(commandId || "")) refuse("invalid_command_id", 400)
  const rejected = {}, control = {}
  for (const id of [gistId, feedbackGistId].filter(value => /^[A-Za-z0-9_]+$/.test(value || ""))) {
    const document = resultsDocumentFromFiles(await gistFiles(id, { fetchImpl, token }))
    Object.assign(control, document.control)
    const result = document.results[commandId]
    if (result) {
      if (digest && result.digest !== digest) return { command_id: commandId, status: "refused", code: "command_id_reused", digest: result.digest }
      const followUp = followUpOf(document.outbox, commandId)
      return { command_id: commandId, status: result.status, code: result.code ?? null, digest: result.digest,
        consumed_at: result.consumed_at, ...(followUp ? { follow_up: followUp } : {}) }
    }
    Object.assign(rejected, document.rejected)
  }
  if (digest && rejected[digest]) return { command_id: commandId, status: "refused", code: rejected[digest].code, digest }
  // Root's route control: its own namespace, consulted only after every sealed-command record.
  const controlRow = control[commandId]
  if (controlRow && (!digest || controlRow.digest === digest)) {
    return { command_id: commandId, status: controlRow.status, code: controlRow.code ?? null, digest: controlRow.digest, consumed_at: controlRow.consumed_at, route_control: true }
  }
  const admitted = await artifactsNamed(`${ARTIFACT_PREFIX}${commandId}`, { fetchImpl, token, repo })
  const live = admitted.filter(row => row.expired !== true)
  const created = live.map(row => Date.parse(row.created_at)).filter(Number.isFinite)
  // A command lives at most 24 h after its request, which precedes admission by at most the skew.
  if (live.length && created.length === live.length && Math.min(...created) + MAX_LIFETIME_MS + CLOCK_SKEW_MS < now.getTime()) {
    return { command_id: commandId, status: "refused", code: "expired" }
  }
  if (live.length) return { command_id: commandId, status: "pending" }
  if (admitted.length) return { command_id: commandId, status: "refused", code: "expired" }
  if ((await artifactsNamed(`${REFUSAL_PREFIX}${commandId}`, { fetchImpl, token, repo })).length) {
    return { command_id: commandId, status: "refused", code: "admission_refused" }
  }
  return { command_id: commandId, status: "unknown" }
}
