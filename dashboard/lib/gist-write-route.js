// P00c serialized Gist write route: mode, route record, writer guard and command envelope.
// Mirrors src/commands/gist_route.py and src/commands/gist_commands.py (same codes, same
// canonical bytes and digest). Default-off: with THEHEAT_GIST_WRITE_ROUTE unset and no route
// record in the state Gist, every direct writer behaves exactly as before.
import { createHash, randomUUID } from "node:crypto"
import { canonical } from "./local-command-recovery.js"

export const ROUTE_ENV = "THEHEAT_GIST_WRITE_ROUTE"
export const MARKER_ENV = "THEHEAT_SERIALIZED_WRITER"
export const ROUTE_FILE = "gist-write-route.json"
export const RESULTS_FILE = "gist-command-results.json"
export const CODE_GENERATION = 1
export const MAX_COMMAND_BYTES = 65535
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
const ENVELOPE_KEYS = ["action", "actor_subject", "command_id", "expires_at", "payload", "producer", "requested_at", "schema_version", "targets"]

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

export function resultsFromFiles(files) {
  if (!files || typeof files !== "object" || !Object.hasOwn(files, RESULTS_FILE)) return {}
  const meta = files[RESULTS_FILE]
  let value
  try {
    if (!meta || meta.truncated || typeof meta.content !== "string") throw new Error()
    value = JSON.parse(meta.content)
  } catch { refuse("command_results_unreadable", 503) }
  if (!value || value.schema_version !== 1 || !value.results || typeof value.results !== "object" || Array.isArray(value.results)) refuse("command_results_unreadable", 503)
  return value.results
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

// Structural mirror of the Python admission (src/commands/gist_commands.parse_command).
// The consumer and resubmission endpoint re-run it; payload semantics are re-verified at apply.
export function validateCommandRaw(raw, { now = new Date() } = {}) {
  if (typeof raw !== "string" || Buffer.byteLength(raw) > MAX_COMMAND_BYTES) refuse("command_too_large", 413)
  let value
  try { value = JSON.parse(raw) } catch { refuse("invalid_json", 400) }
  let text
  try { text = canonical(value) } catch { refuse("unsafe_number", 400) }
  if (text !== raw) refuse("non_canonical_command", 400)
  if (!exactKeys(value, ENVELOPE_KEYS) || value.schema_version !== 1) refuse("invalid_command", 400)
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

// Producer generation against the authoritative route record (consumer side).
export function producerGenerationCode(command, record) {
  const text = command.producer.generation
  if (!/^(0|[1-9][0-9]{0,9})$/.test(text)) return "unauthorized_writer_generation_refused"
  const generation = Number(text)
  if (generation === 0 || generation < (record?.generation ?? 1)) return "retired_writer_generation_refused"
  if (generation > CODE_GENERATION) return "unauthorized_writer_generation_refused"
  return null
}

export function buildCommand({ action, producerKind, actorSubject, targets = [], payload, now = new Date(), lifetimeMs = 3600000, commandId = randomUUID() }) {
  const at = new Date(Math.floor(now.getTime() / 1000) * 1000)
  const command = { schema_version: 1, command_id: commandId, action,
    requested_at: at.toISOString().replace(/\.\d{3}Z$/, "Z"), expires_at: new Date(at.getTime() + lifetimeMs).toISOString().replace(/\.\d{3}Z$/, "Z"),
    producer: { kind: producerKind, generation: String(CODE_GENERATION) }, actor_subject: actorSubject, targets, payload }
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
  const { command, digest } = validateCommandRaw(raw)
  const base = { command_id: command.command_id, digest, command: raw }
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

// applied | refused(code) | pending (admitted, not yet consumed) | unknown. Never synthesized.
export async function commandStatus(commandId, { fetchImpl = globalThis.fetch, token = process.env.GITHUB_TOKEN, repo = REPO,
  gistId = process.env.GIST_ID, feedbackGistId = process.env.THEHEAT_FEEDBACK_GIST_ID, digest = null } = {}) {
  if (!UUID.test(commandId || "")) refuse("invalid_command_id", 400)
  for (const id of [gistId, feedbackGistId].filter(value => /^[A-Za-z0-9_]+$/.test(value || ""))) {
    const result = resultsFromFiles(await gistFiles(id, { fetchImpl, token }))[commandId]
    if (result) {
      if (digest && result.digest !== digest) return { command_id: commandId, status: "refused", code: "command_id_reused", digest: result.digest }
      return { command_id: commandId, status: result.status, code: result.code ?? null, digest: result.digest,
        consumed_at: result.consumed_at, ...(result.follow_up ? { follow_up: result.follow_up } : {}) }
    }
  }
  const response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/artifacts?per_page=100`, { headers: githubHeaders(token), cache: "no-store" })
  if (!response.ok) refuse("command_status_unavailable", 503)
  const artifacts = (await response.json())?.artifacts ?? []
  const refusal = artifacts.find(row => typeof row?.name === "string" && row.name.startsWith(`${REFUSAL_PREFIX}${commandId}-`))
  if (refusal) return { command_id: commandId, status: "refused", code: refusal.name.slice(`${REFUSAL_PREFIX}${commandId}-`.length) || "admission_refused" }
  if (artifacts.some(row => row?.name === `${ARTIFACT_PREFIX}${commandId}` && row.expired !== true)) return { command_id: commandId, status: "pending" }
  return { command_id: commandId, status: "unknown" }
}
