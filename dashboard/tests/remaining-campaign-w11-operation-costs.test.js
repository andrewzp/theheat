import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { projectOperationCost, recentOperationCosts } from "../lib/operation-costs.js"
import { buildCostEvidence } from "../lib/cost-evidence.js"
import { SPEND_CLASS_STAGES, summarizeUsage } from "../lib/usage-ledger.js"
import { CostPanel } from "../app/components/CostPanel.js"

// Invented row in the shape src/two_bot/call_inventory.operation_cost_row persists.
const row = (overrides = {}) => ({
  schema_version: 1, operation: "alerts", path: "ordinary", spend_class: "selection", source: null,
  may_call: [{stage: "writer", spend_class: "selection", pricing: "estimate_partial"},
    {stage: "gist_state", spend_class: "hosting", pricing: "unknown"}],
  ceilings: ["candidate_attempts", "provider_call_cap", "daily_publication_cap", "monthly_budget_watch", "invoice_ceiling"],
  candidate_attempts: {limit: 1, used: 1, returned_unstarted: 0, held: 2, refusal: null, joined_requests: 2},
  allowances: [],
  requests: {total: 2, by_outcome: {dispatched: 1, returned: 1, malformed: 0, unavailable: 0, unknown: 0, released_unstarted: 0},
    by_stage: {writer: {requests: 1, unsettled: 1, unknown_or_malformed: 0, spend_class: "selection", pricing: "estimate_partial"},
      safety: {requests: 1, unsettled: 0, unknown_or_malformed: 0, spend_class: "selection", pricing: "estimate_partial"}},
    interrupted: 1, truncated: false},
  unpriced_requests: 0, estimate_only_requests: 2, another_attempt_allowed: {candidate_attempt: false},
  actual_cost_known: false, financial_cap: false, ...overrides,
})

test("projection keeps interrupted requests and fixed codes, and drops secrets and free text", () => {
  const raw = row({error: "Authorization: Bearer invented-secret", prompt: "invented prompt",
    requests: {...row().requests, by_stage: {...row().requests.by_stage, "Bearer invented-secret": {requests: 1, unsettled: 0, unknown_or_malformed: 0}}}})
  const projected = projectOperationCost(raw)
  const text = JSON.stringify(projected)
  assert.equal(projected.requests.interrupted, 1)
  assert.equal(projected.requests.by_outcome.dispatched, 1)
  assert.equal(projected.another_attempt_allowed.candidate_attempt, false)
  assert.equal(projected.actual_cost_known, false)
  assert.equal(projected.financial_cap, false)
  assert.doesNotMatch(text, /invented-secret|invented prompt|Bearer/)
  assert.deepEqual(projected.requests.by_stage.map(s => s.stage), ["writer", "safety"])
})

test("invalid rows are dropped rather than repaired into a cost", () => {
  assert.equal(projectOperationCost(row({schema_version: 2})), null)
  assert.equal(projectOperationCost(row({operation: "invented"})), null)
  assert.equal(projectOperationCost(null), null)
  const odd = projectOperationCost(row({requests: {total: -1, by_outcome: {returned: "9"}}, unpriced_requests: 1.5}))
  assert.equal(odd.requests.total, null)
  assert.equal(odd.requests.by_outcome.returned, 0)
  assert.equal(odd.unpriced_requests, null)
})

test("rows persisted with run history survive a reload and render in Operations", () => {
  const state = {run_history: [{started_at: "2026-10-29T09:00:00Z", operation_costs: [row(),
    row({spend_class: "discovery", source: "newsworthiness", candidate_attempts: null, requests: {total: 0, by_outcome: {}, by_stage: {}, interrupted: 0, truncated: false},
      allowances: [{stages: {newsworthiness_verify: {limit: 6, reserved: 6, remaining: 0, refused_before_egress: 3, physical_attempts: 6,
        outcomes: {returned: 5, malformed: 0, unavailable: 0, unknown: 1, released_unstarted: 0}, pricing: "estimate_partial", spend_class: "discovery"}}}],
      another_attempt_allowed: {newsworthiness_verify: false}})]}]}
  const reloaded = JSON.parse(JSON.stringify(state))
  const rows = recentOperationCosts(reloaded)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].run_started_at, "2026-10-29T09:00Z")
  const evidence = buildCostEvidence(reloaded)
  assert.equal(evidence.operations.length, 2)
  const html = renderToStaticMarkup(React.createElement(CostPanel, {evidence}))
  assert.match(html, /Recent operations: calls and allowances/)
  assert.match(html, /1 interrupted/)
  assert.match(html, /Interrupted \(outcome unknown\)/)
  assert.match(html, /State storage \(unpriced\)/)
  assert.match(html, /News verification allowance/)
  assert.match(html, /6 of 6 reserved · 6 physical attempts · 3 refused before sending/)
  assert.match(html, /Another attempt allowed: Candidate attempt no|Another attempt allowed: candidate attempt no/)
  assert.match(html, /invoice ceiling \(not enforced: no invoice access\)/)
  assert.match(html, /monthly budget watch \(alert only, not a cap\)/)
  assert.doesNotMatch(html, /total cost/i)
})

test("operations section is absent only when evidence was never loaded", () => {
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(CostPanel, {})), /Recent operations/)
  assert.match(renderToStaticMarkup(React.createElement(CostPanel, {evidence: buildCostEvidence({})})), /No operation records retained yet/)
})

test("discovery and selection usage stay separate and match the Python stage classes", () => {
  const agg = {in: 1, cached_in: 0, cache_write: 0, out: 1, calls: 2, usd: 0, priced_calls: 0, unpriced_calls: 2, missing_usage_calls: 0, priced_usd: 0}
  const summary = summarizeUsage({llm_usage: {"2026-10-29": {"writer|invented": agg, "newsworthiness_search|invented": {...agg, calls: 1, unpriced_calls: 1}}}},
    {now: Date.parse("2026-10-29T12:00:00Z")})
  assert.equal(summary.spend_classes.selection.recorded_calls, 2)
  assert.equal(summary.spend_classes.discovery.recorded_calls, 1)
  const python = readFileSync(new URL("../../src/two_bot/usage_summary.py", import.meta.url), "utf8")
  for (const [name, stages] of Object.entries(SPEND_CLASS_STAGES)) {
    assert.match(python, new RegExp(`'${name}': \\[${stages.map(s => `'${s}'`).join(", ")}\\]`))
  }
})
