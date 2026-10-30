// W05: the Sources reader names each held national service and keeps denominators
// as supplied (named stations, never national coverage). Invented run row.
import test from "node:test"
import assert from "node:assert/strict"
import { coverageRow, sourceOutcome } from "../lib/live-content-status.js"

const row = {
  source: "regional_observed", status: "degraded", promoted: 0, observed: 2,
  details: { regional_observed: { regions: {
    aemet: { status: "processed", requested_stations: 3, returned_stations: 3, qualified_station_days: 2, candidates_admitted: 0 },
    imd: { status: "held", hold: "schema_contract_unverified", text: "No owner-supplied schema contract accompanies this packet." },
    saws: { status: "held", hold: "access_unavailable", text: "SAWS station-data access and its column/QC/day-definition contract have not been supplied." },
  } } },
}

test("held services are named one by one; supplied regions keep their own denominators", () => {
  const outcome = sourceOutcome(row)
  assert.equal(outcome.state, "regional_hold")
  assert.match(outcome.detail, /imd: No owner-supplied schema contract/)
  assert.match(outcome.detail, /saws: SAWS station-data access/)
  assert.doesNotMatch(outcome.detail, /aemet/)
  const coverage = coverageRow(row)
  assert.deepEqual(coverage.universe, { checked: 3, usable: 2, label: "named stations in supplied packets" })
})

test("a supplying region is reported as supplying, not hidden behind other holds", () => {
  assert.equal(sourceOutcome({ ...row, promoted: 2 }).state, "supplying")
})
