import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { coverageRow, sourceOutcome } from "../lib/live-content-status.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const metric = changes => ({ source: "twitter_metrics", status: "success", observed: 5, promoted: 5,
  triaged_in: 0, triaged_out: 0, writer_attempted: 0, drafted: 0, error: null, ...changes })
function project(row) {
  return buildSourceHealthPayload({ run_history: [{ id: "invented-metrics-run", started_at: "2026-11-20T12:00:00Z",
    ended_at: "2026-11-20T12:01:00Z", sources: [row] }] }, { asOf: "2026-11-20T12:02:00Z" })
}
const current = row => project(row).sources.find(s => s.source === "twitter_metrics")

test("metrics request/response counts are not weather inputs or story candidates", () => {
  const row = metric(), before = structuredClone(row), out = current(row)
  assert.equal(out.outcome.state, "metrics_returned")
  assert.match(out.outcome.detail, /5 requested posts; 5 with usable counts/)
  assert.doesNotMatch(out.outcome.next_action, /draft|writing|selection/i)
  assert.equal(out.source_contract.kind, "internal")
  assert.deepEqual(out.coverage_row.universe, { checked: 5, usable: 5, label: "requested X post metrics" })
  assert.deepEqual(row, before)
})

test("a partial or empty lookup does not establish zero reach or provider recovery", () => {
  for (const promoted of [3, 0]) {
    const out = sourceOutcome(metric({ status: "partial_failure", promoted,
      error: "invented-provider-text", note: "untrusted-note" }))
    assert.equal(out.state, "metrics_partial")
    assert.match(out.detail, new RegExp(`5 requested posts; ${promoted} with usable counts`))
    assert.match(out.detail, /Missing counts are unknown/)
    assert.doesNotMatch(JSON.stringify(out), /invented-provider-text|untrusted-note|healthy|recovered/)
  }
})

test("known skips describe this opportunity without claiming a successful earlier lookup", () => {
  for (const [note, observed, reason] of [
    ["Metrics already polled today", 0, /daily polling opportunity was already used/],
    ["No recent tweet ids to poll", 0, /No recent post IDs were selected/],
    ["No Twitter credentials configured", 5, /credentials were unavailable/],
  ]) {
    const row = metric({ status: "skipped", promoted: 0, observed, note })
    const out = current(row).outcome
    assert.equal(out.state, "metrics_skipped")
    assert.match(out.detail, reason)
    assert.match(out.detail, /No new engagement counts/)
    assert.equal(coverageRow(row).universe.checked, null)
    assert.equal(coverageRow(row).universe.usable, null)
  }
})

test("inconsistent or missing lookup evidence remains unavailable", () => {
  const cases = [
    { observed: undefined }, { promoted: undefined }, { observed: true }, { promoted: -1 },
    { observed: Number.MAX_SAFE_INTEGER + 1 }, { promoted: 6 }, { promoted: 4 },
    { observed: 0, promoted: 0 }, { status: "partial_failure" }, { writer_attempted: 1 }, { error: "inconsistent" },
    { drafted: 1 }, { triaged_in: undefined }, { status: "degraded" },
    { status: "skipped", observed: 1, promoted: 0, note: "Metrics already polled today" },
    { status: "skipped", observed: 0, promoted: 0, note: "untrusted-note" },
    { status: "skipped", observed: 0, promoted: 0, note: "No recent tweet ids to poll", error: "failure" },
  ]
  for (const change of cases) {
    const row = metric(change), out = current(row).outcome
    assert.equal(out.state, "metrics_unavailable", JSON.stringify(change))
    assert.equal(coverageRow(row).universe.checked, null)
    assert.equal(coverageRow(row).universe.usable, null)
  }
})

test("metrics failures and unrelated old writer rejections cannot become weather outcomes", () => {
  const failed = sourceOutcome(metric({ status: "failed", promoted: 0, error: "candidate_budget_private" }))
  assert.equal(failed.state, "metrics_unavailable")
  assert.doesNotMatch(JSON.stringify(failed), /candidate_budget_private/)
  assert.equal(sourceOutcome(metric(), [{ source: "twitter_metrics", stage: "critic" }]).state, "metrics_returned")
  assert.equal(sourceOutcome({ source: "ordinary-weather-source", status: "success", promoted: 1 }).state, "supplying")
  assert.equal(sourceOutcome({ source: "ordinary-weather-source", status: "success", promoted: 0 }).state, "no_event")
})

const require = createRequire(import.meta.url), modules = new Map()
function component(filename) {
  if (modules.has(filename)) return modules.get(filename).exports
  const module = { exports: {} }; modules.set(filename, module)
  const code = transformSync(readFileSync(filename, "utf8"), {
    filename, jsc: { parser: { syntax: "ecmascript", jsx: true }, target: "es2022", transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" },
  }).code
  new Function("require", "module", "exports", code)(name => name.startsWith(".") ? component(resolve(dirname(filename), name)) : require(name), module, module.exports)
  return module.exports
}
const { SourcesView } = component(fileURLToPath(new URL("../app/components/SourcesView.js", import.meta.url)))
test("the real Sources view explains returned metrics without drafting or access actions", () => {
  const markup = renderToStaticMarkup(createElement(SourcesView, project(metric())))
  assert.match(markup, /Saved X metrics lookup/)
  assert.match(markup, /5 requested posts; 5 with usable counts/)
  assert.doesNotMatch(markup, /Supplying candidates|Review the resulting drafts|Approve \+ Post/)
})
