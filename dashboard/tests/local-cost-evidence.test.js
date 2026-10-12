import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createServer } from "node:http"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { localCostEvidence } from "../lib/local-cost-evidence.js"
import { CostPanel, formatMicroUsd } from "../app/components/CostPanel.js"
import { USAGE_OBSERVATION_CONTRACT as C } from "../lib/state-contract.js"

const stamp = "2026-10-12T00:00:00.000000Z"
function fixture() {
  const provider = "anthropic"
  return {schema_version: 1, status: "available", reason: null, scope: "local_shared_authority", actual_bill_available: false,
    accounting_complete: false, production_enforcement: false, snapshot: {state_version: 3, observed_at: stamp},
    integrity_scope: {summary: "existing_catalog_constraints_aggregate", details: "selected_rows_hash_and_join_checked"},
    summary: {configured_limits_micro_usd: {daily: "100", monthly: "100", per_job: "100"}, commitments_micro_usd: {daily: "10", monthly: "10", held: "10"}, overrun_count: 0,
      reservation_counts: {reserved: 0, dispatched: 0, uncertain: 1, released: 0, settled: 0}},
    requests: [{intent_id: "invented", job_id: "invented-job", provider, role: "writer", requested_model: "invented-model", reservation_state: "uncertain",
      reserved_at: stamp, last_at: stamp, reserve_micro_usd: "10", held_micro_usd: "10", recorded_settlement_micro_usd: null, charge_status: "unreconciled",
      origin: {kind: "unattributed", ...Object.fromEntries(["brief_id", "source_run_id", "generation_id", "check_set_id", "stage", "grant_id", "request_sha256", "raw_sha256", "receipt_id"].map(k => [k, null]))},
      usage: {parser_version: "retained_usage_v1", status: "unavailable", reason: "response_missing", observed_at: null, complete_response: null, resolved_model: null,
        ...Object.fromEntries(["counts", "labels", "breakdowns"].map(section => [section, Object.fromEntries(C[section][provider].map(k => [k, null]))])), invalid_fields: [], unsupported_fields: false}}],
    details_truncated: false, total_intents: 1, shown_intents: 1, omitted_intents: 0}
}
const render = props => renderToStaticMarkup(React.createElement(CostPanel, props))

test("closed local cost shape preserves exact money and unknowns", () => {
  const value = fixture()
  assert.deepEqual(localCostEvidence(value), value)
  assert.equal(formatMicroUsd("100000000000000000"), "$100,000,000,000.00")
  assert.equal(formatMicroUsd("1"), "$0.000001")
  assert.equal(formatMicroUsd("0"), "$0.00")
  for (const change of [v => { v.private = "secret" }, v => { v.requests[0].usage.private = "raw" }, v => { v.summary.commitments_micro_usd.held = 1 },
    v => { v.requests[0].recorded_settlement_micro_usd = "0" }, v => { v.snapshot.observed_at = "garbage" }, v => { v.accounting_complete = true },
    v => { v.requests[0].origin.kind = "new-origin" }, v => { v.requests[0].role = "invented-role" },
    v => { v.requests[0].usage.parser_version = "different" }, v => { v.requests[0].usage.counts.input_tokens = true },
    v => { v.requests[0].usage = JSON.parse('{"__proto__":{},"status":"present"}') }]) {
    const bad = structuredClone(value); change(bad)
    assert.equal(localCostEvidence(bad).status, "unavailable")
  }
})

test("local panel distinguishes hold, unknown charge, stale data and absent installation", () => {
  const html = render({localEvidence: fixture(), stale: true})
  for (const text of ["Local requests and reserved allowance", "Local workflow only", "Final charge unknown", "Outcome unknown; allowance remains reserved",
    "last loaded snapshot", "not bills", "missing usage is not zero", "Request reference: invented"]) assert.ok(html.includes(text), text)
  assert.doesNotMatch(html, /Retry|<button|progressbar/)
  assert.match(render({localEvidence: {schema_version: 1, status: "unconfigured", reason: "not_configured"}}), /Local cost records unavailable/)
  const zero = fixture(); zero.requests[0].reservation_state = "settled"; zero.requests[0].charge_status = "recorded_settlement"
  zero.requests[0].recorded_settlement_micro_usd = "0"; zero.requests[0].held_micro_usd = "0"
  zero.summary.reservation_counts.uncertain = 0; zero.summary.reservation_counts.settled = 1
  assert.match(render({localEvidence: zero}), /Recorded settlement \$0\.00/)
})

test("actual owned PostgreSQL HTTP -> dashboard API -> cost component, unavailable and recovery", {skip: !process.env.THEHEAT_COST_TEST_CONFIG}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_COST_TEST_CONFIG, "utf8"))
  const saved = {...process.env}, actualFetch = globalThis.fetch
  process.env.NODE_ENV = "test"; process.env.DASHBOARD_AUTH_DISABLED = "1"; process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  delete process.env.GITHUB_TOKEN; delete process.env.GIST_ID
  const {GET} = await import("../app/api/dashboard/route.js")
  let unavailable = false, reads = 0
  globalThis.fetch = (url, options) => {
    assert.equal(new URL(url).origin, config.endpoint, "Only the owned local backend may be read")
    assert.ok(!options?.method || options.method === "GET")
    if (unavailable) throw new Error("invented local outage")
    reads++
    return actualFetch(url, options)
  }
  const server = createServer(async (incoming, outgoing) => {
    try {
      const response = await GET(new Request(config.origin + incoming.url, {headers: incoming.headers}))
      outgoing.writeHead(response.status, Object.fromEntries(response.headers)); outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch { outgoing.writeHead(500); outgoing.end('{}') }
  })
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(new URL(config.origin).port), "127.0.0.1", resolve) })
  async function get(role = "viewer") {
    const response = await actualFetch(`http://127.0.0.1:${server.address().port}/api/dashboard`, {headers: {Origin: config.origin,
      Authorization: `Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`}})
    return {status: response.status, body: await response.json(), headers: response.headers}
  }
  try {
    const first = await get()
    assert.equal(first.status, 200, JSON.stringify(first.body))
    assert.equal(first.body.localCostEvidence.status, "available", JSON.stringify(first.body.localCostEvidence))
    assert.deepEqual(first.body.localCostEvidence.requests, config.expected.requests)
    assert.deepEqual(first.body.localCostEvidence.summary, config.expected.summary)
    assert.equal(reads, 1)
    const html = render({evidence: first.body.costEvidence, localEvidence: first.body.localCostEvidence})
    assert.match(html, /Local requests and reserved allowance/)
    assert.match(html, /Writing/); assert.match(html, /Safety/); assert.match(html, /Fact check/); assert.match(html, /Critic/)
    assert.match(html, /Final charge unknown/)
    unavailable = true
    assert.equal((await get()).status, 503)
    const stale = render({localEvidence: first.body.localCostEvidence, stale: true})
    assert.match(stale, /last loaded snapshot/)
    unavailable = false
    const recovered = await get("editor")
    assert.deepEqual(recovered.body.localCostEvidence.requests, first.body.localCostEvidence.requests)
    assert.equal(reads, 2)
  } finally {
    globalThis.fetch = actualFetch
    await new Promise(resolve => server.close(resolve))
    for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k]
    Object.assign(process.env, saved)
  }
})
