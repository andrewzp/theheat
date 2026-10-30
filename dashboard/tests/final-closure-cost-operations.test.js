import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { projectOperationCost } from "../lib/operation-costs.js"
import { validUsageAttribution, validUsageObservation } from "../lib/usage-observations.js"
import { OperationCosts } from "../app/components/CostPanel.js"

const vectors = JSON.parse(readFileSync(new URL("../../tests/final_closure/fixtures/cost_attribution_vectors.json", import.meta.url)))

// Invented row in the shape src/two_bot/call_inventory.operation_cost_row persists.
const row = (requests = {}, allowances = []) => ({
  schema_version: 1, operation: "alerts", path: "ordinary", spend_class: "discovery", source: "newsworthiness",
  may_call: [{stage: "newsworthiness_verify", spend_class: "discovery", pricing: "estimate_partial"}],
  ceilings: ["provider_call_cap", "invoice_ceiling"], candidate_attempts: null, allowances,
  requests: {total: 1, by_outcome: {dispatched: 0, returned: 1, malformed: 0, unavailable: 0, unknown: 0, released_unstarted: 0},
    by_stage: {newsworthiness_verify: {requests: 1, unsettled: 0, unknown_or_malformed: 0, spend_class: "discovery", pricing: "estimate_partial"}},
    interrupted: 0, truncated: false, ...requests},
  unpriced_requests: 0, estimate_only_requests: 1, another_attempt_allowed: {}, actual_cost_known: false, financial_cap: false,
})

test("shared attribution vectors: valid, absent and malformed shapes", () => {
  assert.equal(validUsageObservation(vectors.base_observation), true)
  for (const value of vectors.valid) {
    assert.equal(validUsageAttribution(value), true)
    assert.equal(validUsageObservation({...vectors.base_observation, attribution: value}), true)
  }
  for (const value of vectors.invalid) {
    assert.equal(validUsageAttribution(value), false)
    assert.equal(validUsageObservation({...vectors.base_observation, attribution: value}), false)
  }
})

test("late requests after an operation closed are projected and shown as spent, unjoined", () => {
  const projected = projectOperationCost(row({late_after_close: 2, late_by_stage: {writer: 2, "Bearer invented": 1}}))
  assert.equal(projected.requests.late_after_close, 2)
  assert.deepEqual(projected.requests.late_by_stage, [{stage: "writer", requests: 2}])
  const html = renderToStaticMarkup(React.createElement(OperationCosts, {rows: [{...projected, run_started_at: "2026-10-30T09:00Z"}]}))
  assert.match(html, /2 requests were sent after this operation closed \(Writer 2\)/)
  assert.match(html, /not refundable and their charges stay unknown/)
  assert.doesNotMatch(html, /Bearer/)
  // Older rows did not record late requests; nothing is invented for them.
  const old = projectOperationCost(row())
  assert.equal(old.requests.late_after_close, null)
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(OperationCosts, {rows: [{...old, run_started_at: null}]})), /after this operation closed/)
})

test("exact cache reuse is visible beside the allowance without consuming a slot", () => {
  const allowance = {stages: {newsworthiness_verify: {limit: 6, reserved: 2, remaining: 4, refused_before_egress: 0, physical_attempts: 2,
    exact_cache_hits: 3, outcomes: {returned: 2, malformed: 0, unavailable: 0, unknown: 0, released_unstarted: 0},
    pricing: "estimate_partial", spend_class: "discovery"}}}
  const projected = projectOperationCost(row({}, [allowance]))
  assert.equal(projected.allowances[0].exact_cache_hits, 3)
  const html = renderToStaticMarkup(React.createElement(OperationCosts, {rows: [{...projected, run_started_at: null}]}))
  assert.match(html, /2 of 6 reserved · 2 physical attempts · 0 refused before sending · 3 exact cached results reused \(no request\)/)
  delete allowance.stages.newsworthiness_verify.exact_cache_hits
  assert.equal(projectOperationCost(row({}, [allowance])).allowances[0].exact_cache_hits, null)
})
