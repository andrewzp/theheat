// W03: product-level incidents reach the Sources payload through the real
// buildSourceHealthPayload reader. The run history is the shared invented fixture
// that tests/remaining_campaign/test_w03_source_incidents.py checks in Python.
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { buildSourceHealthPayload } from "../lib/source-health.js"
import { sourceOutcome } from "../lib/live-content-status.js"
import { latestIncidentState, sourceIncidents } from "../lib/source-incidents.js"

const fixture = JSON.parse(readFileSync(new URL("../../tests/remaining_campaign/fixtures/w03_run_history.json", import.meta.url)))

test("projection parity with the Python projection on the shared fixture", () => {
  const rows = new Map(sourceIncidents(fixture.run_history).map(row => [row.key, row]))
  assert.deepEqual([...rows.keys()].sort(), Object.keys(fixture.expected).sort())
  for (const [key, expected] of Object.entries(fixture.expected)) {
    for (const [field, value] of Object.entries(expected)) assert.deepEqual(rows.get(key)[field], value, `${key} ${field}`)
  }
})

test("a 404 names the leg and is never 'no event'; recovery needs a qualified result", () => {
  const oldest = fixture.run_history.at(-1)
  const firms = oldest.sources.find(row => row.source === "firms")
  const outcome = sourceOutcome(firms)
  assert.equal(outcome.state, "endpoint_missing")
  assert.match(outcome.detail, /firms\.viirs_noaa21_nrt/)
  assert.notEqual(outcome.state, "no_event")
  assert.match(outcome.next_action, /not 'no events'/)
  const reachable = fixture.run_history.find(run => run.id === "invented-run-3").sources.find(row => row.source === "firms")
  assert.equal(sourceOutcome(reachable).state, "reachable_unqualified")
  assert.equal(latestIncidentState(reachable).product_state, "reachable_unqualified")
})

test("Sources payload carries per-product incidents without labelling the whole source", () => {
  const payload = buildSourceHealthPayload({ run_history: fixture.run_history }, { asOf: "2026-10-25T00:00:00Z" })
  const firms = payload.sources.find(source => source.source === "firms")
  const states = Object.fromEntries(firms.incidents.map(row => [row.product_id, row.state]))
  assert.deepEqual(states, {
    "firms.modis_nrt": "reachable_unqualified", "firms.noaa_hms": "open",
    "firms.viirs_noaa20_nrt": "reachable_unqualified", "firms.viirs_noaa21_nrt": "recovered",
  })
  assert.equal(firms.outcome.state, "no_event")  // newest run: qualified primary, nothing promoted
  const gpm = payload.sources.find(source => source.source === "gpm_imerg")
  assert.equal(gpm.incidents.find(row => row.product_id === "gpm_imerg.imerg_late_opendap").state, "access_hold")
  assert.ok(JSON.stringify(payload).indexOf("invented-map-key") === -1)
})
