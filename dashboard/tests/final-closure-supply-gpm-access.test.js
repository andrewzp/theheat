// A3: GPM/Earthdata access health reaches the Sources payload through the real
// buildSourceHealthPayload reader, with parity to src/data/source_access.py on the
// shared invented fixture (tests/final_closure/fixtures/supply_gpm_access.json).
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { buildSourceHealthPayload } from "../lib/source-health.js"
import { gpmAccessHealth, refusalBackoff } from "../lib/source-access.js"
import { latestIncidentState, sourceIncidents } from "../lib/source-incidents.js"

const fixture = JSON.parse(readFileSync(new URL("../../tests/final_closure/fixtures/supply_gpm_access.json", import.meta.url)))

test("access health matches the Python projection on every shared case", () => {
  for (const [name, item] of Object.entries(fixture.cases)) {
    const out = gpmAccessHealth(item.state, { asOf: item.as_of })
    for (const field of fixture.compared_fields) assert.deepEqual(out[field], item.expected[field], `${name} ${field}`)
    assert.equal(out.empty_feed_is_not_coverage, true)
  }
})

test("the Sources payload shows the expired credential and the last good GPM data age", () => {
  const item = fixture.cases.expired
  const state = { ...item.state, run_history: [{ id: "r1", started_at: "2026-10-30T10:39:23Z", sources: [
    { source: "gpm_imerg", status: "failed", error: "GPM IMERG fetch failed: EARTHDATA_TOKEN expired", details: {} }] }] }
  const payload = buildSourceHealthPayload(state, { asOf: item.as_of })
  const gpm = payload.sources.find(source => source.source === "gpm_imerg")
  assert.equal(gpm.access_health.stage, "access_expired")
  assert.match(gpm.access_health.public_text, /Last good GPM data 2026-08-20 \(71 days old\)/)
  assert.equal(payload.sources.find(source => source.source !== "gpm_imerg")?.access_health ?? null, null)
})

test("a backoff skip is an owner-access hold, never an open outage or recovery", () => {
  const item = fixture.cases.refused_backoff
  const backoff = refusalBackoff(item.state.run_history, { credentialExpiresAt: "2026-12-30T00:00:00Z", now: new Date(item.as_of) })
  assert.equal(backoff.consecutive_refusals, 2)
  const skipped = { source: "gpm_imerg", details: { incident: { schema: "theheat.source-incident/v1", product_state: "access_hold",
    attempts: [{ key: "k", product_id: "gpm_imerg.imerg_late_opendap", role: "primary", outcome: "access_backoff" }] } } }
  assert.equal(latestIncidentState(skipped).failing[0].outcome, "access_backoff")
  const rows = sourceIncidents([{ id: "x", started_at: "2026-10-30T12:00:00Z", sources: [skipped] }], "gpm_imerg")
  assert.equal(rows[0].state, "access_hold")
  assert.match(rows[0].text, /no request was sent/)
})
