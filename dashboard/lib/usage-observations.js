// Paired with src/two_bot/usage_observations.py. Diagnostic window, not billing.
import { USAGE_OBSERVATION_CONTRACT as C } from "./state-contract.js"

const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const identifierRE = new RegExp(C.identifier_pattern)
const identifier = value => typeof value === "string" && identifierRE.exec(value)?.[0] === value
const count = value => Number.isSafeInteger(value) && value >= 0 && value <= C.count_limit
const sameKeys = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value, k))
const recordKeys = ["schema_version", "id", "observed_at", "stage", "provider", "requested_model", "resolved_model", "response_id", "usage_status", "counts", "labels", "breakdowns", "invalid_fields", "unsupported_fields"]
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0
const canonical = value => JSON.stringify(value && typeof value === "object"
  ? Array.isArray(value) ? value.map(v => JSON.parse(canonical(v)))
    : Object.fromEntries(Object.keys(value).sort().map(k => [k, JSON.parse(canonical(value[k]))]))
  : value)

function validTimestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) || value.startsWith("0000-")) return false
  const time = new Date(value)
  return Number.isFinite(time.getTime()) && time.toISOString() === value
}

export function validUsageObservation(row) {
  if (!sameKeys(row, recordKeys) || row.schema_version !== 1
      || typeof row.id !== "string" || !/^[a-f0-9]{32}$/.test(row.id) || row.id.length !== 32
      || !validTimestamp(row.observed_at)
      || !["google", "anthropic", "unknown"].includes(row.provider)
      || !["present", "absent", "invalid"].includes(row.usage_status)
      || typeof row.unsupported_fields !== "boolean") return false
  if (["stage", "requested_model", "resolved_model", "response_id"].some(k => row[k] !== null && !identifier(row[k]))) return false
  const paths = ["provider", "stage", "requested_model", "resolved_model", "response_id", "usage", "capture", ...C.counts[row.provider], ...C.labels[row.provider], ...C.breakdowns[row.provider]]
  if (!Array.isArray(row.invalid_fields) || !row.invalid_fields.every(v => typeof v === "string" && paths.includes(v))
      || JSON.stringify(row.invalid_fields) !== JSON.stringify([...new Set(row.invalid_fields)].sort())) return false
  for (const section of ["counts", "labels", "breakdowns"]) {
    if (!sameKeys(row[section], C[section][row.provider])) return false
    for (const value of Object.values(row[section])) {
      if (value === null) continue
      if (section === "counts" && !count(value)) return false
      if (section === "labels" && !identifier(value)) return false
      if (section === "breakdowns") {
        if (!Array.isArray(value) || value.length > C.modality_limit) return false
        const seen = new Set()
        for (const item of value) {
          if (!sameKeys(item, ["modality", "token_count"]) || !C.modalities.includes(item.modality)
              || seen.has(item.modality) || !count(item.token_count)) return false
          seen.add(item.modality)
        }
        if (JSON.stringify([...seen]) !== JSON.stringify([...seen].sort())) return false
      }
    }
  }
  // All accepted strings are ASCII, so character length equals encoded bytes.
  return canonical(row).length <= C.record_bytes
}

export function mergeUsageObservations(...values) {
  const result = {schema_version: 1, observations: [], truncated: false, invalid: false}
  const rows = new Map()
  for (const raw of values) {
    if (raw == null || (object(raw) && Object.keys(raw).length === 0)) continue
    if (!sameKeys(raw, Object.keys(result)) || raw.schema_version !== 1
        || typeof raw.truncated !== "boolean" || typeof raw.invalid !== "boolean" || !Array.isArray(raw.observations)) {
      result.invalid = true; continue
    }
    result.truncated ||= raw.truncated || raw.observations.length > C.input_limit
    result.invalid ||= raw.invalid
    for (const row of raw.observations.slice(0, C.input_limit)) {
      if (!validUsageObservation(row)) { result.invalid = true; continue }
      const key = canonical(row)
      rows.set(key, JSON.parse(key))
    }
  }
  const ordered = [...rows.keys()].sort((a, b) => compare(rows.get(b).observed_at, rows.get(a).observed_at)
    || compare(rows.get(b).id, rows.get(a).id) || compare(b, a))
  result.truncated ||= ordered.length > C.limit
  result.observations = ordered.slice(0, C.limit).map(k => rows.get(k))
  return result
}

export function summarizeUsageObservations(value) {
  const window = mergeUsageObservations(value), ids = window.observations.map(r => r.id)
  return {...window, retained_conflicting_ids: [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))].sort(),
    accounting_complete: false, scope: "Recent provider-reported usage only; not an invoice or complete call history."}
}
