import test from "node:test"
import assert from "node:assert/strict"
import { sourceHistoryTime } from "../lib/source-history-time.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const AS_OF = "2026-10-18T12:00:00Z"
const early = "2026-10-16T12:00:00Z", later = "2026-10-17T12:00:00Z"
const project = rows => sourceHistoryTime(rows, { asOf: AS_OF })

test("old success remains explicitly historical, never live availability", () => {
  const value = project([{ at: early, status: "success", observed: 0 }])
  assert.equal(value.current_availability, "unverified")
  assert.equal(value.latest_recorded_age_hours, 48)
  assert.equal(value.last_successful_at, early)
  assert.equal(value.last_successful_age_hours, 48)
  assert.equal(value.timestamp_coverage, "supplied_rows_only")
})
test("unsorted failures and skips do not erase the dated last success", () => {
  const rows = [{ at: later, status: "failed" }, { at: early, status: "success" }, { at: AS_OF, status: "skipped" }]
  const before = structuredClone(rows), value = project(rows)
  assert.equal(value.latest_recorded_at, AS_OF)
  assert.equal(value.latest_recorded_status, "skipped")
  assert.equal(value.last_successful_at, early)
  assert.deepEqual(rows, before)
})
test("degraded alternate delivery is not primary recovery", () => {
  const value = project([{ at: later, status: "degraded", note: "served via alternate" }])
  assert.equal(value.latest_recorded_status, "degraded")
  assert.equal(value.last_successful_at, null)
})
test("skipped-only history has no recorded successful collection", () => {
  const value = project([{ at: early, status: "skipped" }])
  assert.equal(value.last_successful_at, null)
  assert.equal(value.last_successful_age_hours, null)
})
for (const invalid of [undefined, null, "2026-02-30T12:00:00Z", "2026-10-17T24:00:00Z", "2026-10-17T12:00:00", 0, true]) {
  test(`invalid or unaware timestamp cannot establish dated success: ${String(invalid)}`, () => {
    const value = project([{ at: invalid, status: "success" }])
    assert.equal(value.latest_recorded_at, null)
    assert.equal(value.last_successful_at, null)
    assert.equal(value.invalid_timestamp_rows, 1)
    assert.equal(value.timestamp_coverage, "unavailable")
  })
}
test("future success, including sub-millisecond future time, cannot look current", () => {
  const value = project([{ at: "2026-10-19T00:00:00Z", status: "success" }, { at: "2026-10-18T12:00:00.000001Z", status: "success" }, { at: early, status: "failed" }])
  assert.equal(value.future_timestamp_rows, 2)
  assert.equal(value.latest_recorded_at, early)
  assert.equal(value.last_successful_at, null)
  assert.equal(value.timestamp_coverage, "partial")
})
test("equivalent offsets retain one original date and do not conflict", () => {
  const values = [{ at: later, status: "success" }, { at: "2026-10-17T15:00:00+03:00", status: "success" }]
  const value = project(values)
  assert.equal(value.latest_recorded_age_hours, 24)
  assert.equal(value.conflicting_timestamp_groups, 0)
  assert.equal(value.last_successful_at, later)
  assert.deepEqual(project([...values].reverse()), value)
})
test("same-time conflicting success never wins; older unambiguous success remains", () => {
  const value = project([{ at: later, status: "success" }, { at: later, status: "failed" }, { at: early, status: "success" }])
  assert.equal(value.latest_recorded_status, "ambiguous")
  assert.equal(value.latest_status_ambiguous, true)
  assert.equal(value.conflicting_timestamp_groups, 1)
  assert.equal(value.last_successful_at, early)
})
test("unknown status conflicts with success and cannot certify a successful run", () => {
  const value = project([{ at: later, status: "success" }, { at: later, status: "invented-status" }])
  assert.equal(value.last_successful_at, null)
  assert.equal(value.unknown_status_rows, 1)
  assert.equal(value.latest_recorded_status, "ambiguous")
})
test("missing and over-bound inventories remain unavailable without invented zero ages", () => {
  for (const rows of [null, [], new Array(4097).fill({ at: later, status: "success" })]) {
    const value = project(rows)
    assert.equal(value.latest_recorded_at, null)
    assert.equal(value.last_successful_age_hours, null)
    assert.equal(value.current_availability, "unverified")
  }
  assert.equal(project(new Array(4097)).timestamp_coverage, "bound_exceeded")
})
test("clock requires an aware valid calendar timestamp", () => {
  for (const asOf of [undefined, "2026-10-18T12:00:00", "2026-02-30T12:00:00Z", true, 0]) {
    assert.throws(() => sourceHistoryTime([], { asOf }), /source_history_clock_invalid/)
  }
})
const durable = runs => ({ drafts: [], source_health: { invented: { runs, success: 1, failed: 1 } } })
test("durable and run-history dates give equivalent recorded timing with explicit precision", () => {
  const fromDurable = buildSourceHealthPayload(durable([{ ts: later, status: "failed" }, { ts: early, status: "success" }]), { asOf: AS_OF })
  const fromHistory = buildSourceHealthPayload({ drafts: [], run_history: [{ started_at: later, sources: [{ source: "invented", status: "failed" }] }, { started_at: early, sources: [{ source: "invented", status: "success" }] }] }, { asOf: AS_OF })
  assert.equal(fromDurable.sources[0].history_time.last_successful_at, fromHistory.sources[0].history_time.last_successful_at)
  assert.equal(fromDurable.sources[0].history_time.timestamp_precision, "source_run")
  assert.equal(fromHistory.sources[0].history_time.timestamp_precision, "collection_run_start")
  assert.equal(fromDurable.stats.current_availability, "unverified")
  assert.equal(fromDurable.stats.as_of, "2026-10-18T12:00:00.000Z")
})
test("existing durable preference excludes contradictory fallback history", () => {
  const state = { ...durable([{ ts: early, status: "failed" }]), run_history: [{ started_at: later, sources: [{ source: "invented", status: "success" }] }] }
  const value = buildSourceHealthPayload(state, { asOf: AS_OF })
  assert.equal(value.sources[0].history_time.last_successful_at, null)
  assert.equal(value.sources[0].history_time.latest_recorded_at, early)
})
test("pure payload projection never fetches, mutates state or emits raw notes in new timing fields", () => {
  const state = durable([{ ts: early, status: "success", note: "private provider body" }]), before = structuredClone(state)
  const oldFetch = globalThis.fetch
  globalThis.fetch = () => { throw Error("network forbidden") }
  try {
    const value = buildSourceHealthPayload(state, { asOf: AS_OF })
    assert.equal(JSON.stringify(value.sources[0].history_time).includes("private provider body"), false)
    assert.deepEqual(state, before)
  } finally { globalThis.fetch = oldFetch }
})
