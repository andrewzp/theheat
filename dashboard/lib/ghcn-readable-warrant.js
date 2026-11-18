// Passive presentation shape only. Python independently checks the complete warrant.
export const GHCN_READABLE_SCHEMA = "theheat-ghcn-complete-readable-table-v1"
const FORMAT = "ghcn-complete-readable-table-v1"
const VARIABLES = ["temperature_2m_max", "temperature_2m_min"]
const FIELDS = ["accepted_years", "accepted_samples", "previous_date", "previous_c"]
const BASELINE_FIELDS = "schema_version source_product station_id evidence_type comparison_scope comparison_before cutoff requested_comparison_cutoff retrieved_at source_payload_sha256 reconciled variables revision_id wire_profile calendar_table".split(" ")
const SCOPE_FIELDS = "sample_count expected_count coverage_fraction complete years_with_samples start cutoff conflicting_dates previous_value_c previous_date requested_comparison_cutoff source_calendar_count source_coverage_complete source_coverage_fraction source_gap_count source_latest_cell source_missing_count source_qc_rejected_count verified_source_cutoff monthly_years monthly_samples record_dates record_values_c".split(" ")
const SHA = /^[a-f0-9]{64}$/
const encoder = new TextEncoder()
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value))
const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length
  && keys.every(key => Object.hasOwn(value, key))
const positive = value => Number.isSafeInteger(value) && value > 0
const dayDate = value => {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || Number(value.slice(0, 4)) < 1) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value
}

function bounded(value) {
  let nodes = 0, characters = 0
  const ancestors = new Set()
  function walk(item, depth) {
    if (++nodes > 65536 || depth > 32) throw new Error("bound")
    if (item === null || typeof item === "boolean") characters += 5
    else if (typeof item === "number") {
      if (!Number.isFinite(item) || (Number.isInteger(item) && !Number.isSafeInteger(item))) throw new Error("scalar")
      characters += String(item).length
    } else if (typeof item === "string") {
      if (!item.isWellFormed()) throw new Error("unicode")
      characters += item.length + 2
    } else if (Array.isArray(item) || object(item)) {
      if (ancestors.has(item)) throw new Error("cycle")
      ancestors.add(item); characters += 2
      if (Array.isArray(item)) {
        if (item.length > 65536) throw new Error("bound")
        for (const child of item) walk(child, depth + 1)
      } else {
        const keys = Reflect.ownKeys(item)
        if (keys.length > 65536 || keys.some(key => typeof key !== "string")) throw new Error("keys")
        for (const key of keys) {
          const descriptor = Object.getOwnPropertyDescriptor(item, key)
          if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) throw new Error("property")
          walk(key, depth + 1); walk(descriptor.value, depth + 1)
        }
      }
      ancestors.delete(item)
    } else throw new Error("scalar")
    if (characters > 32768) throw new Error("bound")
  }
  try {
    walk(value, 0)
    return encoder.encode(JSON.stringify(value)).length <= 32768
  } catch { return false }
}

export function hasReadableGHCNMarker(bundle) {
  const baseline = bundle?.raw_signal_dump?.evidence?.baseline
  const alias = bundle?.historical_context?.baseline
  return !!(object(baseline) && (Object.hasOwn(baseline, "wire_profile") || Object.hasOwn(baseline, "calendar_table")
      || typeof baseline.schema_version === "string" && baseline.schema_version.startsWith("theheat-ghcn-"))
    || object(alias) && (Object.hasOwn(alias, "same_document_baseline") || Object.hasOwn(alias, "full_baseline_sha256")))
}

export function readableGHCNWarrantForDisplay(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle
  if (!hasReadableGHCNMarker(bundle)) return { status: "absent" }
  const unavailable = { status: "unavailable" }
  if (!bounded(bundle)) return unavailable
  const evidence = bundle.raw_signal_dump?.evidence, baseline = evidence?.baseline
  const alias = bundle.historical_context?.baseline, profile = baseline?.wire_profile, table = baseline?.calendar_table
  if (!object(evidence) || evidence.source_product !== "noaa-ghcn-daily-v2" || evidence.evidence_type !== "observed"
      || typeof evidence.station_id !== "string" || !/^[A-Z0-9]{11}$/.test(evidence.station_id)
      || !dayDate(evidence.valid_date) || baseline?.schema_version !== GHCN_READABLE_SCHEMA
      || !exact(baseline, BASELINE_FIELDS) || baseline.station_id !== evidence.station_id
      || baseline.source_product !== evidence.source_product || baseline.evidence_type !== "observed"
      || !exact(profile, ["format", "original_schema_version", "all_null_group"])
      || profile.format !== FORMAT || profile.original_schema_version !== 2 || profile.all_null_group !== "absent_calendar_key_not_zero"
      || !exact(alias, ["same_document_baseline", "full_baseline_sha256"])
      || alias.same_document_baseline !== "raw_signal_dump.evidence.baseline" || !SHA.test(alias.full_baseline_sha256)
      || !exact(table, ["variables", "columns", "rows"]) || !object(baseline.variables)) return unavailable
  const names = VARIABLES.filter(name => Object.hasOwn(baseline.variables, name))
  if (!names.length || names.length !== Object.keys(baseline.variables).length || JSON.stringify(table.variables) !== JSON.stringify(names)) return unavailable
  for (const name of names) {
    const scope = baseline.variables[name]
    const keys = object(scope) && Object.hasOwn(scope, "candidate_accepted") ? [...SCOPE_FIELDS, "candidate_accepted"] : SCOPE_FIELDS
    if (!exact(scope, keys) || !exact(scope.record_dates, ["all_time", "monthly"])
        || !exact(scope.record_values_c, ["all_time", "monthly"]) || !object(scope.monthly_years)
        || !object(scope.monthly_samples) || !object(scope.record_dates.monthly) || !object(scope.record_values_c.monthly)) return unavailable
  }
  const columns = ["calendar_day", ...names.flatMap(name => FIELDS.map(field => `${name}:${field}`))]
  if (JSON.stringify(table.columns) !== JSON.stringify(columns) || !Array.isArray(table.rows) || table.rows.length > 366) return unavailable
  let previous = ""
  for (const row of table.rows) {
    if (!Array.isArray(row) || row.length !== columns.length || typeof row[0] !== "string"
        || !/^[0-9]{2}-[0-9]{2}$/.test(row[0]) || !dayDate(`2000-${row[0]}`) || row[0] <= previous) return unavailable
    previous = row[0]
    let present = false
    for (let i = 0; i < names.length; i++) {
      const [years, samples, sourceDate, value] = row.slice(1 + 4 * i, 5 + 4 * i)
      if ([years, samples, sourceDate, value].every(item => item === null)) continue
      if (!positive(years) || !positive(samples) || samples < years || !dayDate(sourceDate)
          || sourceDate.slice(5) !== row[0] || typeof value !== "number" || !Number.isFinite(value)) return unavailable
      present = true
    }
    if (!present) return unavailable
  }
  return { status: "saved", station: evidence.station_id, validDate: evidence.valid_date,
    retrievedAt: typeof evidence.retrieved_at === "string" ? evidence.retrieved_at : null,
    cutoff: typeof baseline.cutoff === "string" ? baseline.cutoff : null,
    columns: [...columns], variables: [...names], rows: table.rows.map(row => [...row]),
    baselineSHA256: alias.full_baseline_sha256 }
}
