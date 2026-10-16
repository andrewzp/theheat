// A separate Gist file carries configuration evidence, never draft state.
export const RUNTIME_REPORT_FILE = "runtime-inventory.json"
export const MAX_RUNTIME_REPORT_BYTES = 128 * 1024
const invalid = () => ({ invalid_report: true })

export function reportTimestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return NaN
  const calendar = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== value.slice(0, 10)) return NaN
  if (Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return NaN
  return Date.parse(value)
}

export function configurationReportRun(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || value.schema_version !== 1 || value.kind !== "configuration_only"
      || typeof value.id !== "string" || !/^config-[0-9]{1,32}-[0-9]{1,6}$/.test(value.id)
      || !Number.isSafeInteger(value.run_attempt) || value.run_attempt < 1
      || !Number.isFinite(reportTimestamp(value.started_at))) return null
  const snapshot = value.runtime_inventory
  if (!snapshot || snapshot.schema_version !== 1 || snapshot.mode !== "runtime_report"
      || typeof snapshot.github_run_id !== "string" || !/^[0-9]{1,32}$/.test(snapshot.github_run_id)
      || value.id !== `config-${snapshot.github_run_id}-${value.run_attempt}`
      || snapshot.captured_at !== value.started_at
      || !/^[a-f0-9]{40}$/.test(snapshot.git_sha || "")
      || snapshot.flags?.automatic_publication_enabled !== false
      || snapshot.flags?.writer_samples !== 1 || snapshot.flags?.critic_enabled !== true
      || snapshot.flags?.critic_revise_enabled !== false
      || value.collection_paused !== true) return null
  return { id: value.id, started_at: value.started_at, runtime_inventory: snapshot, configuration_only: true }
}

export function decodeRuntimeReportFile(file) {
  if (file === undefined) return null
  if (!file || file.truncated === true || typeof file.content !== "string"
      || new TextEncoder().encode(file.content).byteLength > MAX_RUNTIME_REPORT_BYTES) return invalid()
  try {
    const value = JSON.parse(file.content)
    return configurationReportRun(value) ? value : invalid()
  } catch { return invalid() }
}
