import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { sourceOutcome } from "../lib/live-content-status.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

// Invented census, shaped by the real NIFC parser/runner; no source request.
const row = { source: "fire_footprint", status: "degraded", observed: 3, promoted: 0,
  triaged_in: 0, triaged_out: 0, writer_attempted: 0, drafted: 0, error: null,
  details: { raw_rows: 11, qualified_rows: 3, held_rows: 5,
    row_holds: { stale: 2, invalid_size: 3, child: 1, below_floor: 2 }, coverage_truncated: false } }
const context = { fireReportCurrent: true }
const current = r => sourceOutcome(r, [], context)

test("known report holds cannot read as an empty feed with nothing to do", () => {
  const before = structuredClone(row)
  const value = current(row)
  assert.equal(value.state, "fire_reports_held")
  assert.match(value.detail, /3 qualified.*5 held.*0 queued/)
  assert.match(value.detail, /invalid size: 3; stale report: 2/)
  assert.match(value.next_action, /held/i)
  assert.doesNotMatch(value.next_action, /nothing to do/i)
  assert.deepEqual(row, before)
})

test("the actual durable-health reader preserves held rows and prior failures", () => {
  const state = { source_health: { fire_footprint: { degraded: 1, failed: 1,
    runs: [{ ts: "2026-11-18T01:00:00Z", status: "failed", error: "Invented timeout" },
      { ts: "2026-11-18T02:00:01Z", status: "degraded", observed: 3 }] } },
    run_history: [{ id: "invented-fire-run", mode: "alerts", started_at: "2026-11-18T02:00:00Z",
      ended_at: "2026-11-18T02:00:02Z", sources: [row] }] }
  const old = structuredClone(state)
  const fire = buildSourceHealthPayload(state, { asOf: "2026-11-18T03:00:00Z" }).sources[0]
  assert.equal(fire.outcome.state, "fire_reports_held")
  assert.equal(fire.failures, 1)
  assert.equal(fire.coverage_row.observed, 3)
  assert.equal(fire.coverage_row.promoted, 0)
  assert.deepEqual(state, old)
})

test("queued reports keep supplying and display the known census separately", () => {
  const value = current({ ...row, promoted: 1 })
  assert.equal(value.state, "supplying")
  assert.match(value.detail, /5 held.*1 queued/)
  assert.match(value.next_action, /no saved draft/)
})

for (const [name, change] of [
  ["missing", r => { delete r.details }],
  ["negative", r => { r.details.held_rows = -1 }],
  ["noninteger", r => { r.details.raw_rows = 11.5 }],
  ["unsafe", r => { r.details.raw_rows = Number.MAX_SAFE_INTEGER + 1 }],
  ["boolean count", r => { r.details.qualified_rows = true }],
  ["unknown reason", r => { r.details.row_holds["private-provider-message"] = 1 }],
  ["nonpartition", r => { r.details.raw_rows = 12 }],
  ["false held total", r => { r.details.held_rows = 4 }],
  ["different observed", r => { r.observed = 4 }],
  ["excess promoted", r => { r.promoted = 4 }],
  ["invalid truncation", r => { r.details.coverage_truncated = "false" }],
  ["excess admission holds", r => { r.details.admission_holds = 4 }],
  ["missing saved-draft count", r => { delete r.drafted }],
  ["impossible saved-draft count", r => { r.drafted = 1 }],
]) test(`a ${name} census is unavailable, not an empty feed`, () => {
  const changed = structuredClone(row); change(changed)
  const value = current(changed)
  assert.equal(value.state, "fire_reports_unavailable")
  assert.doesNotMatch(JSON.stringify(value), /private-provider-message|Nothing to do/)
})

for (const [name, change] of [
  ["newer health row", s => { s.source_health.fire_footprint.runs[0].ts = "2026-11-18T03:00:00Z" }],
  ["different observations", s => { s.source_health.fire_footprint.runs[0].observed = 4 }],
  ["different health status", s => { s.source_health.fire_footprint.runs[0].status = "success" }],
  ["future source run", s => { s.run_history[0].ended_at = "2026-11-19T02:00:02Z" }],
  ["duplicate source row", s => { s.run_history[0].sources.push(structuredClone(row)) }],
  ["missing interval", s => { delete s.run_history[0].ended_at }],
]) test(`${name} cannot lend old fire-report details to the current reader`, () => {
  const state = { source_health: { fire_footprint: { degraded: 1,
    runs: [{ ts: "2026-11-18T02:00:01Z", status: "degraded", observed: 3 }] } },
    run_history: [{ id: "invented-fire-run", mode: "alerts", started_at: "2026-11-18T02:00:00Z",
      ended_at: "2026-11-18T02:00:02Z", sources: [structuredClone(row)] }] }
  change(state)
  const value = buildSourceHealthPayload(state, { asOf: "2026-11-18T04:00:00Z" })
    .sources.find(r => r.source === "fire_footprint").outcome
  assert.equal(value.state, "fire_reports_unavailable")
})

test("no currency proof, wrong source, and explicit failures cannot borrow the census", () => {
  assert.equal(sourceOutcome(row).state, "fire_reports_unavailable")
  assert.equal(sourceOutcome(row, [], { fireReportCurrent: false }).state, "fire_reports_unavailable")
  assert.equal(current({ ...row, source: "other" }).state, "no_event")
  assert.equal(current({ ...row, status: "failed" }).state, "unavailable")
  assert.equal(current({ ...row, status: "failed", error: "token expired" }).state, "access_expired")
})

test("a complete no-hold census says checked, without inventing a reason for no queue", () => {
  const value = current({ ...row, status: "success", observed: 3,
    details: { raw_rows: 3, qualified_rows: 3, held_rows: 0, row_holds: {}, coverage_truncated: false } })
  assert.equal(value.state, "fire_reports_checked")
  assert.match(value.next_action, /no candidate.*queued/i)
  assert.doesNotMatch(value.next_action, /nothing to do|no fires|no events/i)
})

test("truncation and admission refusal remain holds even with no rejected input rows", () => {
  const clean = { ...row, details: { raw_rows: 3, qualified_rows: 3,
    held_rows: 0, row_holds: {}, coverage_truncated: false } }
  for (const details of [{ ...clean.details, coverage_truncated: true }, { ...clean.details, admission_holds: 1 }]) {
    assert.equal(current({ ...clean, details }).state, "fire_reports_held")
  }
})

// Same installed compiler and real component loading used by the existing
// Sources tests. There is no substitute success component or network access.
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
test("the existing SourcesView renders the held census and keeps its publication controls absent", () => {
  const state = { run_history: [{ id: "invented-source-run", mode: "alerts", started_at: "2026-11-18T02:00:00Z",
    ended_at: "2026-11-18T02:00:02Z", sources: [row] }] }
  const payload = buildSourceHealthPayload(state, { asOf: "2026-11-18T03:00:00Z" })
  const markup = renderToStaticMarkup(createElement(SourcesView, payload))
  assert.match(markup, /data-outcome="fire_reports_held"/)
  assert.ok(markup.includes(payload.sources[0].outcome.detail))
  assert.match(markup, /Past collection results, not a live source check/)
  assert.doesNotMatch(markup, /Nothing to do|Approve \+ Post|Post now/)
})
