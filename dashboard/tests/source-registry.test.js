import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import registry from "../lib/source-registry.json" with { type: "json" }
import { sourceContract, sourceInventory } from "../lib/source-registry.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"
import { SourceContractDetails } from "../app/components/SourceContractDetails.js"

test("every generated health key resolves uniquely; internal and historic labels do not gain a source", () => {
  const keys = registry.sources.flatMap(row => row.health_keys)
  assert.equal(new Set(keys).size, keys.length)
  for (const row of registry.sources) for (const key of row.health_keys) {
    const result = sourceContract(key)
    assert.equal(result.source_id, row.source_id)
    assert.equal(result.claim_permission_granted, false)
    assert.equal(result.current_availability, "unverified")
    assert.equal(result.provider_quota, null)
    assert.equal(result.reuse_rights, null)
  }
  assert.equal(sourceContract("budget").kind, "internal")
  for (const name of ["invented_old_source", "__proto__", "constructor", null]) {
    assert.deepEqual(sourceContract(name), { registered: false, kind: "unregistered", claim_permission_granted: false })
  }
})

test("wired inventory is independent of saved observations and never becomes a geographic denominator", () => {
  const missing = sourceInventory([])
  assert.equal(missing.wired_collectors, registry.sources.length)
  assert.equal(missing.wired_without_saved_rows.length, registry.sources.length)
  assert.equal(missing.effective_activation, null)
  assert.equal(missing.coverage_denominator, null)
  assert.equal(missing.claim_permission_granted, false)
  const some = sourceInventory(["nao", "ao", "nao", "nhc", "budget", "invented_old_source"])
  assert.equal(some.wired_without_saved_rows.includes("climate_indices"), false)
  assert.equal(some.wired_without_saved_rows.includes("nhc"), false)
  assert.equal(some.unregistered_saved_keys, 1)
  assert.equal(some.internal_saved_keys, 1)
  for (const value of [null, {}, Array(4097).fill("nhc")]) {
    const bounded = sourceInventory(value)
    assert.equal(bounded.wired_without_saved_rows, null)
    assert.equal(bounded.unregistered_saved_keys, null)
    assert.equal(bounded.saved_key_coverage, "unknown_bound_or_shape")
  }
})

test("historical source API preserves timing/status/fallback semantics and does not mutate inputs", () => {
  const asOf = "2026-10-18T12:00:00Z"
  const state = { source_health: {
    river_gauges: {success: 0, failed: 0, degraded: 1, runs: [{ts: "2026-10-15T12:00:00Z",status: "degraded"}], last_error: "served via open_meteo_flood"},
    air_quality: {success: 1, failed: 0, runs: [{ts: "2026-10-15T12:00:00Z",status: "success"}]},
    invented_old_source: {success: 1, runs: [{ts: "2026-10-17T12:00:00",status: "success"}]},
    budget: {runs: [{ts: "2026-10-15T12:00:00Z",status: "skipped"}]},
  }}
  const before = JSON.stringify(state)
  const result = buildSourceHealthPayload(state, {asOf})
  assert.equal(JSON.stringify(state), before)
  const byKey = Object.fromEntries(result.sources.map(row => [row.source, row]))
  assert.equal(byKey.river_gauges.health, "degraded")
  assert.equal(byKey.river_gauges.served_via, "open_meteo_flood")
  assert.equal(byKey.river_gauges.source_contract.data_family, "mixed")
  assert.equal(byKey.air_quality.history_time.last_successful_age_hours, 72)
  assert.equal(byKey.air_quality.source_contract.current_availability, "unverified")
  assert.equal(byKey.invented_old_source.history_time.last_successful_at, null)
  assert.equal(byKey.invented_old_source.source_contract.registered, false)
  assert.equal(result.source_inventory.unregistered_saved_keys, 1)
  assert.equal(result.source_inventory.coverage_denominator, null)
  const fallback = buildSourceHealthPayload({run_history:[{started_at: "2026-10-15T12:00:00Z", sources:[{source:"air_quality",status:"success"}]}]}, {asOf})
  assert.deepEqual(fallback.sources[0].source_contract, byKey.air_quality.source_contract)
})

test("caller changes cannot mutate future registry resolutions", () => {
  const original = sourceContract("air_quality")
  original.unknown_limits.length = 0
  original.scope = "invented changed scope"
  assert.ok(sourceContract("air_quality").unknown_limits.length > 0)
  assert.notEqual(sourceContract("air_quality").scope, original.scope)
})

test("mounted detail markup separates mixed/model/report evidence, unknowns and internal workflows", () => {
  const markup = key => renderToStaticMarkup(React.createElement(SourceContractDetails, {contract:sourceContract(key)}))
  assert.match(markup("air_quality"), /A model estimate is not a station observation/)
  assert.match(markup("river_gauges"), /Model discharge is not an observed gauge height/)
  assert.match(markup("ocean"), /not a buoy observation/)
  assert.match(markup("copernicus_ems"), /not a measured flood footprint/)
  assert.match(markup("nhc"), /when the provider updates/)
  assert.match(markup("budget"), /not an independent weather source/)
  assert.match(markup("invented_old_source"), /Scope not registered/)
  assert.doesNotMatch(markup("air_quality"), /src\/|\.py|api_key|claim_permission_granted/)
})
