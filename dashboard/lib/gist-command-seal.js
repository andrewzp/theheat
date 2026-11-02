// P00c v2 protected transport (ROUTE-CONTRACT-v2 §1): AES-256-GCM from node:crypto, random
// 96-bit IV, 128-bit tag, every public envelope field bound as additional authenticated data.
// The dashboard server seals (and verifies retries); only the consume/drain jobs open. Python
// admission validates the same public shape WITHOUT the key (src/commands/gist_commands.py).
// Plaintext never leaves process memory: no log, artifact, report, result or status carries it.
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto"
import { canonical } from "./local-command-recovery.js"

export const SEAL_KEY_ENV = "THEHEAT_COMMAND_SEAL_KEY"
export const SEAL_ALG = "A256GCM"
export const ENVELOPE_SCHEMA = 2
export const MAX_ENVELOPE_BYTES = 64000 // < GitHub's 65,535-character workflow_dispatch input payload
export const MAX_PLAINTEXT_BYTES = 46000
export const MAX_CIPHERTEXT_B64 = 4 * Math.ceil(MAX_PLAINTEXT_BYTES / 3) // 61,336
export const MAX_LIFETIME_MS = 86400000
export const CLOCK_SKEW_MS = 300000
// Producer kind -> sealed actions it may submit; action -> the operations it may name.
export const SEALED_PRODUCERS = Object.freeze({
  dashboard_editor: ["draft_update"],
  dashboard_reconciliation: ["reconcile_delivery"],
  post_feedback: ["post_feedback"],
})
export const DRAFT_OPERATIONS = Object.freeze(["approve", "reject", "edit", "review", "auto_approve", "cancel_auto_approve",
  "select_candidate", "bulk_reject_below", "attach_graphic", "remove_graphic", "episode"])
export const SEALED_OPERATIONS = Object.freeze({
  draft_update: DRAFT_OPERATIONS,
  reconcile_delivery: ["reconcile_delivery"],
  post_feedback: ["post_feedback"],
})
const ENVELOPE_KEYS = ["action", "actor_subject", "command_id", "expires_at", "operation", "producer", "requested_at", "route_activation", "schema_version", "seal"]
const SEAL_KEYS = ["alg", "ciphertext", "iv", "kid", "tag"]
const KID = /^[a-z0-9][a-z0-9-]{0,31}$/
const B64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/
const ACTOR = /^[A-Za-z0-9_.:@-]{1,100}$/
const ASCII = /^[\x20-\x7e]*$/

export class SealError extends Error {
  constructor(code, status = 400) { super(code); this.code = code; this.status = status; this.statusCode = status }
}
const refuse = (code, status) => { throw new SealError(code, status) }
const exactKeys = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).sort().join() === [...keys].sort().join()
const utc = value => typeof value === "string" && UTC.test(value) && Number.isFinite(Date.parse(value))

function base64Bytes(value, { exact = null, max = null } = {}) {
  if (typeof value !== "string" || !B64.test(value) || (max !== null && value.length > max)) refuse("invalid_envelope")
  const bytes = Buffer.from(value, "base64")
  if (bytes.toString("base64") !== value || (exact !== null && bytes.length !== exact) || bytes.length === 0) refuse("invalid_envelope")
  return bytes
}

// `<kid>:<standard base64 of exactly 32 bytes>`; null when unset. Never logged or echoed.
export function sealKey(env = process.env) {
  const value = env[SEAL_KEY_ENV] ?? ""
  if (value === "") return null
  const separator = value.indexOf(":")
  const kid = value.slice(0, separator), encoded = value.slice(separator + 1)
  if (separator < 1 || !KID.test(kid) || !B64.test(encoded)) refuse("command_seal_key_invalid", 503)
  const key = Buffer.from(encoded, "base64")
  if (key.length !== 32 || key.toString("base64") !== encoded) refuse("command_seal_key_invalid", 503)
  return { kid, key }
}

export function requireSealKey(env = process.env) {
  const key = sealKey(env)
  if (!key) refuse("command_seal_key_missing", 503)
  return key
}

// Every public field, with the seal reduced to its algorithm and key id.
function aad(envelope) {
  return Buffer.from(canonical({ ...envelope, seal: { alg: envelope.seal.alg, kid: envelope.seal.kid } }), "utf8")
}

export function envelopeDigest(raw) { return createHash("sha256").update(raw, "utf8").digest("hex") }

// Structural validation of a v2 envelope (no key): the exact checks Python admission runs.
export function parseEnvelope(raw, { now = new Date() } = {}) {
  if (typeof raw !== "string" || Buffer.byteLength(raw) > MAX_ENVELOPE_BYTES) refuse("command_too_large", 413)
  if (!ASCII.test(raw)) refuse("invalid_envelope")
  let value
  try { value = JSON.parse(raw) } catch { refuse("invalid_json") }
  let text
  try { text = canonical(value) } catch { refuse("unsafe_number") }
  if (text !== raw) refuse("non_canonical_command")
  if (!exactKeys(value, ENVELOPE_KEYS) || value.schema_version !== ENVELOPE_SCHEMA) refuse("invalid_envelope")
  if (!UUID.test(value.command_id)) refuse("invalid_command_id")
  if (!Object.hasOwn(SEALED_OPERATIONS, value.action)) refuse("invalid_action")
  if (!SEALED_OPERATIONS[value.action].includes(value.operation)) refuse("invalid_operation")
  const allowed = SEALED_PRODUCERS[value.producer?.kind]
  if (!exactKeys(value.producer, ["kind", "generation"]) || !allowed || !allowed.includes(value.action)
      || typeof value.producer.generation !== "string") refuse("unauthorized_writer_generation_refused", 403)
  if (typeof value.actor_subject !== "string" || !ACTOR.test(value.actor_subject)) refuse("invalid_envelope")
  if (typeof value.route_activation !== "string" || !UUID.test(value.route_activation)) refuse("invalid_envelope")
  if (!utc(value.requested_at) || !utc(value.expires_at)) refuse("invalid_time")
  const requested = Date.parse(value.requested_at), expires = Date.parse(value.expires_at)
  if (requested > now.getTime() + CLOCK_SKEW_MS || expires <= requested || expires > requested + MAX_LIFETIME_MS) refuse("invalid_time")
  const seal = value.seal
  if (!exactKeys(seal, SEAL_KEYS) || seal.alg !== SEAL_ALG || typeof seal.kid !== "string" || !KID.test(seal.kid)) refuse("invalid_envelope")
  base64Bytes(seal.iv, { exact: 12 })
  base64Bytes(seal.tag, { exact: 16 })
  base64Bytes(seal.ciphertext, { max: MAX_CIPHERTEXT_B64 })
  return { envelope: value, raw, digest: envelopeDigest(raw), expired: expires <= now.getTime() }
}

// Seal `{targets, payload}` under the public fields. The result is the exact dispatch input.
export function sealEnvelope(publicFields, body, key) {
  const plaintext = Buffer.from(canonical(body), "utf8")
  if (plaintext.length > MAX_PLAINTEXT_BYTES) refuse("command_too_large", 413)
  const envelope = { ...publicFields, seal: { alg: SEAL_ALG, kid: key.kid } }
  const iv = randomBytes(12)
  const cipher = createCipheriv("aes-256-gcm", key.key, iv, { authTagLength: 16 })
  cipher.setAAD(aad(envelope))
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()])
  envelope.seal = { ...envelope.seal, iv: iv.toString("base64"), tag: cipher.getAuthTag().toString("base64"), ciphertext: ciphertext.toString("base64") }
  const raw = canonical(envelope)
  if (Buffer.byteLength(raw) > MAX_ENVELOPE_BYTES) refuse("command_too_large", 413)
  return raw
}

// Authenticate and decrypt a structurally valid envelope. kid differs: command_seal_key_unknown
// (not terminal: another key may open it). Anything else that fails: command_seal_invalid.
export function openEnvelope(parsed, key) {
  const { envelope } = parsed
  if (envelope.seal.kid !== key.kid) refuse("command_seal_key_unknown", 409)
  let plaintext
  try {
    const decipher = createDecipheriv("aes-256-gcm", key.key, Buffer.from(envelope.seal.iv, "base64"), { authTagLength: 16 })
    decipher.setAAD(aad(envelope))
    decipher.setAuthTag(Buffer.from(envelope.seal.tag, "base64"))
    plaintext = Buffer.concat([decipher.update(Buffer.from(envelope.seal.ciphertext, "base64")), decipher.final()])
  } catch { refuse("command_seal_invalid", 403) }
  if (plaintext.length > MAX_PLAINTEXT_BYTES) refuse("command_seal_invalid", 403)
  let body
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(plaintext)
    body = JSON.parse(text)
    if (canonical(body) !== text) throw new Error("non-canonical")
  } catch { refuse("command_seal_invalid", 403) }
  if (!exactKeys(body, ["payload", "targets"]) || !Array.isArray(body.targets)
      || !body.payload || typeof body.payload !== "object" || Array.isArray(body.payload)) refuse("command_seal_invalid", 403)
  return body
}
