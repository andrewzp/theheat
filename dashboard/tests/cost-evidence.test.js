import test from "node:test"
import assert from "node:assert/strict"
import { buildCostEvidence } from "../lib/cost-evidence.js"
import { projectUsageCost } from "../lib/usage-cost-scenario.js"
import { COST_SCENARIO } from "../lib/usage-cost-contract.js"
import { USAGE_OBSERVATION_CONTRACT as U } from "../lib/state-contract.js"

const options = {scenario: COST_SCENARIO.scenario, now: Date.parse("2026-10-04T12:00:00Z")}
function syntheticCostState() {
  const row = {schema_version: 1, id: "a".repeat(32), observed_at: "2026-10-01T12:00:00.000Z", stage: "safety", provider: "google",
    requested_model: "gemini-flash-latest", resolved_model: "gemini-2.5-flash", response_id: "private-response-identifier",
    usage_status: "present", counts: {prompt_token_count: 1000, candidates_token_count: 100, thoughts_token_count: 300,
      total_token_count: 1400, cached_content_token_count: null, tool_use_prompt_token_count: 0},
    labels: {traffic_type: "ON_DEMAND"}, breakdowns: {...Object.fromEntries(U.breakdowns.google.map(key => [key, null])),
      prompt_tokens_details: [{modality: "TEXT", token_count: 1000}]}, invalid_fields: [], unsupported_fields: false}
  return {llm_usage: {"2026-10-01": {writer: {calls: 4, usd: 0.1, priced_usd: 0.1, priced_calls: 2, unpriced_calls: 2, missing_usage_calls: 1}}},
    llm_usage_observations: {schema_version: 1, observations: [row], truncated: true, invalid: false}}
}

test("cost projection separates known subtotal from token scenario and sanitizes private records", () => {
  const state = syntheticCostState(), before = structuredClone(state), result = buildCostEvidence(state, options)
  assert.deepEqual(state, before)
  assert.equal(result.recorded.priced_subtotal_usd, 0.1)
  assert.deepEqual(result.scenario.token_subtotal_usd, {min: "0.001030000", max: "0.001300000"})
  assert.equal(result.scenario.tokens.thought, 300)
  assert.deepEqual(result.scenario.observation_period, {first: "2026-10-01T12:00:00.000Z", last: "2026-10-01T12:00:00.000Z"})
  assert.equal(result.actual_bill_available, false)
  assert.equal(result.budget_enforced, false)
  for (const secret of ["private-response", "gemini-flash-latest", "gemini-2.5-flash", "aaaaaaa", "safety", "projected_usd", "pct_of_budget", '"rows"', '"groups"']) assert.ok(!JSON.stringify(result).includes(secret), secret)
})

test("missing data never becomes zero spend and the scenario requires an explicit trusted name", () => {
  assert.equal(buildCostEvidence(null, options).recorded.priced_subtotal_usd, undefined)
  assert.equal(buildCostEvidence({}, options).recorded.priced_subtotal_usd, null)
  assert.equal(buildCostEvidence({}, options).scenario.error, "usage_window_unavailable")
  assert.equal(buildCostEvidence(syntheticCostState()).scenario.status, "not_requested")
  assert.equal(buildCostEvidence(syntheticCostState(), {scenario: {rates: 0}}).scenario.error, "unsupported_cost_scenario")
})

test("malformed scenario cannot hide recorded evidence; broken ledger cannot hide scenario", () => {
  const state = syntheticCostState()
  state.llm_usage_observations.observations = "PRIVATE"
  const result = buildCostEvidence(state, options)
  assert.equal(result.scenario.error, "invalid_usage_window")
  assert.equal(result.recorded.priced_subtotal_usd, 0.1)
  const fresh = syntheticCostState()
  Object.defineProperty(fresh, "llm_usage", {get() {throw new Error("PRIVATE")}})
  const fallback = buildCostEvidence(fresh, options)
  assert.equal(fallback.recorded.error, "recorded_usage_unavailable")
  assert.equal(fallback.scenario.eligible_records, 1)
  assert.ok(!JSON.stringify(fallback).includes("PRIVATE"))
})

test("monthly view retains tiny positive values without rewriting compatibility rounding", () => {
  const state = syntheticCostState(), ledger = state.llm_usage["2026-10-01"].writer
  ledger.usd = ledger.priced_usd = 0.00000003
  assert.equal(buildCostEvidence(state, options).recorded.priced_subtotal_usd, 0.00000003)
})

test("nonfinite, booleans and fractions remain invalid; malformed identity fences its valid twin", () => {
  for (const value of [NaN, Infinity, true, 0.2]) {
    const state = syntheticCostState(), one = state.llm_usage_observations.observations[0], two = structuredClone(one)
    two.counts.prompt_token_count = value
    state.llm_usage_observations.observations.push(two)
    const report = projectUsageCost(state.llm_usage_observations, options)
    assert.equal(report.invalid_records, 1)
    assert.equal(report.conflicting_records, 1)
    assert.equal(report.eligible_token_subtotal_usd, null)
  }
})

test("prototype labels stay unknown and cannot select inherited rates", () => {
  for (const label of ["constructor", "__proto__", "toString"]) {
    const state = syntheticCostState(), row = state.llm_usage_observations.observations[0]
    row.resolved_model = row.stage = label
    const result = projectUsageCost(state.llm_usage_observations, options)
    assert.equal(result.eligible_records, 0)
    assert.equal(result.groups[0].model, "unknown")
    assert.equal(result.groups[0].stage, "unknown")
  }
})
