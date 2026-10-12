import { validUsageObservation } from "./usage-observations.js"

const object = v => v !== null && typeof v === "object" && !Array.isArray(v) && [Object.prototype, null].includes(Object.getPrototypeOf(v))
const keys = (v, fields) => object(v) && Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k))
const integer = (v, max = 100000) => Number.isSafeInteger(v) && v >= 0 && v <= max
const id = v => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v)
const sha = v => typeof v === "string" && /^[a-f0-9]{64}$/.test(v)
const money = v => typeof v === "string" && /^(0|[1-9][0-9]{0,17})$/.test(v) && BigInt(v) <= 100000000000000000n
const stamp = v => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString() === v.slice(0, 23) + "Z"
const states = ["reserved", "dispatched", "uncertain", "released", "settled"]
const unknown = () => ({schema_version: 1, status: "unavailable", reason: "journal_unavailable"})
const reasons = [null, "not_dispatched", "response_missing", "response_incomplete", "projection_limited", "unsupported_origin", "ambiguous_response", "invalid_envelope"]
const origins = ["brief_id", "source_run_id", "generation_id", "check_set_id", "stage", "grant_id", "request_sha256", "raw_sha256", "receipt_id"]

function validRequest(row) {
  if (!keys(row, ["intent_id", "job_id", "role", "provider", "requested_model", "reservation_state", "reserved_at", "last_at", "reserve_micro_usd", "held_micro_usd", "recorded_settlement_micro_usd", "charge_status", "origin", "usage"])) return false
  if (!["intent_id", "job_id", "role", "requested_model"].every(k => id(row[k])) || !["google", "anthropic", "unknown"].includes(row.provider)
      || !["writer", "safety", "fact_check", "critic", "news", "repair"].includes(row.role)
      || !states.includes(row.reservation_state) || !stamp(row.reserved_at) || !stamp(row.last_at) || row.last_at < row.reserved_at
      || !money(row.reserve_micro_usd) || !money(row.held_micro_usd) || BigInt(row.reserve_micro_usd) > 1000000000000n
      || !["unreconciled", "recorded_settlement"].includes(row.charge_status)) return false
  const settled = row.reservation_state === "settled", held = states.slice(0, 3).includes(row.reservation_state)
  if (settled !== (row.charge_status === "recorded_settlement") || (settled ? (!money(row.recorded_settlement_micro_usd) || BigInt(row.recorded_settlement_micro_usd) > 1000000000000n) : row.recorded_settlement_micro_usd !== null)
      || row.held_micro_usd !== (held ? row.reserve_micro_usd : "0")) return false
  const origin = row.origin, usage = row.usage
  if (!keys(origin, ["kind", ...origins]) || !["sourced_batch_writer", "sourced_synchronous_writer", "required_check", "unattributed"].includes(origin.kind)
      || origins.some(k => origin[k] !== null && !(k === "source_run_id" || k === "generation_id" || k === "stage" ? id(origin[k]) : sha(origin[k])))) return false
  if (origin.kind === "unattributed" && origins.some(k => origin[k] !== null)) return false
  if (origin.kind === "required_check" && (!["safety", "fact_check", "critic"].includes(origin.stage) || origin.stage !== row.role
      || ![origin.check_set_id, origin.grant_id, origin.request_sha256].every(sha))) return false
  if (!keys(usage, ["parser_version", "status", "reason", "observed_at", "complete_response", "resolved_model", "counts", "labels", "breakdowns", "invalid_fields", "unsupported_fields"])
      || usage.parser_version !== "retained_usage_v1"
      || !["present", "absent", "invalid", "unavailable"].includes(usage.status) || !reasons.includes(usage.reason)
      || (usage.observed_at !== null && !stamp(usage.observed_at)) || ![null, true, false].includes(usage.complete_response)) return false
  if (["present", "absent"].includes(usage.status) && (usage.complete_response !== true || !stamp(usage.observed_at))) return false
  return validUsageObservation({schema_version: 1, id: "0".repeat(32), observed_at: "2000-01-01T00:00:00.000Z",
    stage: row.role, provider: row.provider, requested_model: row.requested_model, resolved_model: usage.resolved_model, response_id: null,
    usage_status: usage.status === "unavailable" ? "absent" : usage.status, counts: usage.counts, labels: usage.labels,
    breakdowns: usage.breakdowns, invalid_fields: usage.invalid_fields, unsupported_fields: usage.unsupported_fields})
}

export function localCostEvidence(value) {
  try {
    if (JSON.stringify(value).length > 128 * 1024) return unknown()
    if (keys(value, ["schema_version", "status", "reason"]) && value.schema_version === 1
        && ["unavailable", "unconfigured"].includes(value.status)
        && ["journal_unavailable", "not_configured", "local_only", "projection_timeout", "projection_limited"].includes(value.reason)) return structuredClone(value)
    if (!keys(value, ["schema_version", "status", "reason", "scope", "actual_bill_available", "accounting_complete", "production_enforcement", "snapshot", "integrity_scope", "summary", "requests", "details_truncated", "total_intents", "shown_intents", "omitted_intents"])
        || value.schema_version !== 1 || value.status !== "available" || value.reason !== null || value.scope !== "local_shared_authority"
        || [value.actual_bill_available, value.accounting_complete, value.production_enforcement].some(v => v !== false)
        || !keys(value.snapshot, ["state_version", "observed_at"]) || !integer(value.snapshot.state_version, Number.MAX_SAFE_INTEGER) || !stamp(value.snapshot.observed_at)
        || !keys(value.integrity_scope, ["summary", "details"]) || value.integrity_scope.summary !== "existing_catalog_constraints_aggregate" || value.integrity_scope.details !== "selected_rows_hash_and_join_checked") return unknown()
    const s = value.summary
    if (!keys(s, ["configured_limits_micro_usd", "commitments_micro_usd", "overrun_count", "reservation_counts"])
        || !keys(s.configured_limits_micro_usd, ["daily", "monthly", "per_job"]) || !Object.values(s.configured_limits_micro_usd).every(v => money(v) && BigInt(v) <= 1000000000000n)
        || !keys(s.commitments_micro_usd, ["daily", "monthly", "held"]) || !Object.values(s.commitments_micro_usd).every(money)
        || !integer(s.overrun_count) || !keys(s.reservation_counts, states) || !Object.values(s.reservation_counts).every(v => integer(v))) return unknown()
    if (![value.total_intents, value.shown_intents, value.omitted_intents].every(v => integer(v)) || value.shown_intents > 20
        || value.total_intents !== value.shown_intents + value.omitted_intents || value.details_truncated !== (value.omitted_intents > 0)
        || Object.values(s.reservation_counts).reduce((a, b) => a + b, 0) !== value.total_intents
        || !Array.isArray(value.requests) || value.requests.length !== value.shown_intents || !value.requests.every(validRequest)
        || new Set(value.requests.map(r => r.intent_id)).size !== value.shown_intents) return unknown()
    return structuredClone(value)
  } catch { return unknown() }
}
