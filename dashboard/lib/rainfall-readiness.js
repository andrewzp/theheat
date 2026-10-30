// Regional rainfall readiness from retained run details (W06.2/06.6). Mirror of
// src/data/rainfall_supply.py readiness() and revisit_ages() for the Sources view:
// details.rainfall_scan (theheat.rainfall-regional-scan/v1) gives the examined
// regions, their outcome/hold and checkpoint; details.rainfall_packet_holds names
// each rainfall packet stopped before paid generation and why. Nothing here fetches,
// estimates global recall or infers availability from a scan.
export const RAINFALL_SCAN_SCHEMA = "theheat.rainfall-regional-scan/v1"

export const PACKET_HOLD_TEXT = Object.freeze({
  rainfall_window_missing: "No accumulation window retained with the packet",
  accumulation_window_missing: "Accumulation start/end missing",
  integration_interval_inconsistent: "Accumulation interval does not match its start and end",
  unit_not_mm: "Rainfall unit is not millimetres",
  footprint_missing: "Grid cell, point or area footprint missing",
  evidence_type_unknown: "Satellite, gauge or model evidence type not named",
  source_product_missing: "Source product and version not named",
  bundle_raw_signal_missing: "Retained source packet missing",
})

const list = value => Array.isArray(value) ? value : []
const object = value => value && typeof value === "object" && !Array.isArray(value)
const day = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
const daysBetween = (later, earlier) => Math.round((Date.parse(`${later}T00:00:00Z`) - Date.parse(`${earlier}T00:00:00Z`)) / 86400000)

export function rainfallReadiness(runHistory, source, { asOf = null } = {}) {
  const runs = list(runHistory).filter(object).slice().sort((a, b) => String(a.started_at ?? "").localeCompare(String(b.started_at ?? "")))
  const regions = new Map()
  let scan = null, packetHolds = null
  for (const run of runs) {
    for (const entry of list(run.sources)) {
      if (!object(entry) || entry.source !== source || !object(entry.details)) continue
      const details = entry.details
      if (object(details.rainfall_scan) && details.rainfall_scan.schema === RAINFALL_SCAN_SCHEMA) {
        const value = details.rainfall_scan
        const attempts = list(value.attempts).filter(object)
        scan = { at: run.started_at ?? null, region_set_sha256: value.region_set_sha256 ?? null,
          examined: value.examined ?? null, selected: value.selected ?? null, universe: value.universe ?? null,
          next_cursor: value.next_cursor ?? null, calls: value.calls ?? null,
          not_attempted: attempts.filter(row => row.outcome === "not_attempted_limit").map(row => row.region),
          scope: value.scope ?? "Examined regions only; no global recall is estimated from a scan." }
        for (const row of attempts) {
          if (row.outcome === "not_attempted_limit" || row.outcome == null) continue
          regions.set(String(row.region), { region: String(row.region), outcome: String(row.outcome), hold: row.hold ?? null,
            failure_class: row.failure_class ?? null, at: run.started_at ?? null })
        }
      }
      if (Array.isArray(details.rainfall_packet_holds)) {
        packetHolds = { at: run.started_at ?? null, rows: details.rainfall_packet_holds.filter(object).map(row => ({
          event_id: row.event_id ?? null, location: row.location ?? null,
          holds: list(row.holds).map(code => ({ code: String(code), text: PACKET_HOLD_TEXT[code] ?? String(code) })) })) }
      }
    }
  }
  if (!scan && !packetHolds) return null
  const today = day(asOf)
  const rows = [...regions.values()].sort((a, b) => a.region.localeCompare(b.region)).map(row => ({
    ...row, revisit_age_days: today && day(row.at) ? daysBetween(today, day(row.at)) : null }))
  return { regions: rows, scan, packet_holds: packetHolds,
    held: rows.filter(row => row.outcome !== "qualified").length + (packetHolds?.rows.length ?? 0),
    recall: null }
}
