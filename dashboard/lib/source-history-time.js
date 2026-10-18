import { reportTimestamp } from "./runtime-report.js"

const HOUR = 3600000
const MAX_ROWS = 4096
const STATUSES = new Set(["success", "failed", "degraded", "partial_failure", "skipped"])
const remainder = value => (/\.(\d+)/.exec(value)?.[1] || "").slice(3).replace(/0+$/, "")
function fractionAfter(a, b) {
  const x = remainder(a), y = remainder(b), length = Math.max(x.length, y.length)
  return x.padEnd(length, "0") > y.padEnd(length, "0")
}

// Collection timestamps describe retained attempts, never product observation
// times or a new live-availability check. Do not invent a freshness SLA here.
export function sourceHistoryTime(rows, { asOf }) {
  const now = reportTimestamp(asOf)
  if (!Number.isFinite(now)) throw new Error("source_history_clock_invalid")
  const result = {
    as_of: new Date(now).toISOString(),
    current_availability: "unverified",
    latest_recorded_at: null,
    latest_recorded_status: null,
    latest_recorded_age_hours: null,
    latest_status_ambiguous: false,
    last_successful_at: null,
    last_successful_age_hours: null,
    timestamp_coverage: "unavailable",
    supplied_rows: Array.isArray(rows) ? rows.length : null,
    valid_timestamp_rows: 0,
    invalid_timestamp_rows: 0,
    future_timestamp_rows: 0,
    unknown_status_rows: 0,
    conflicting_timestamp_groups: 0,
  }
  if (!Array.isArray(rows) || !rows.length) return result
  if (rows.length > MAX_ROWS) return { ...result, timestamp_coverage: "bound_exceeded" }
  const groups = new Map()
  for (const row of rows) {
    const at = reportTimestamp(row?.at)
    if (!Number.isFinite(at)) { result.invalid_timestamp_rows++; continue }
    if (at > now || (at === now && fractionAfter(row.at, asOf))) { result.future_timestamp_rows++; continue }
    result.valid_timestamp_rows++
    const status = STATUSES.has(row?.status) ? row.status : "unknown"
    if (status === "unknown") result.unknown_status_rows++
    if (!groups.has(at)) groups.set(at, { dates: new Set(), statuses: new Set() })
    groups.get(at).dates.add(row.at)
    groups.get(at).statuses.add(status)
  }
  const dated = [...groups].sort(([a], [b]) => b - a)
  for (const [at, group] of dated) {
    const ambiguous = group.statuses.size > 1
    if (ambiguous) result.conflicting_timestamp_groups++
    // Equivalent offsets can describe one instant. Keep an original spelling,
    // selected deterministically, without rewriting the supplied state.
    const original = [...group.dates].sort()[0]
    if (result.latest_recorded_at === null) {
      result.latest_recorded_at = original
      result.latest_recorded_status = ambiguous ? "ambiguous" : [...group.statuses][0]
      result.latest_recorded_age_hours = (now - at) / HOUR
      result.latest_status_ambiguous = ambiguous
    }
    if (result.last_successful_at === null && !ambiguous && group.statuses.has("success")) {
      result.last_successful_at = original
      result.last_successful_age_hours = (now - at) / HOUR
    }
  }
  result.timestamp_coverage = !dated.length ? "unavailable"
    : result.invalid_timestamp_rows || result.future_timestamp_rows || result.unknown_status_rows || result.conflicting_timestamp_groups
      ? "partial" : "supplied_rows_only"
  return result
}
