import test from "node:test"
import assert from "node:assert/strict"
import { sourceOutcome } from "../lib/live-content-status.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

// Invented rows shaped like retained collector reports; no provider is contacted.
const zeroes = { observed: 0, promoted: 0, triaged_in: 0, triaged_out: 0, writer_attempted: 0, drafted: 0 }
const excluded = { source: "air_quality", status: "skipped", error_class: "editorial_scope", ...zeroes,
  note: "Forecast AQ acquisition skipped in observed-only scheduled mode" }

test("the exact retained forecast-policy skip explains exclusion instead of claiming no run", () => {
  const original = structuredClone(excluded)
  const value = sourceOutcome(excluded)
  assert.equal(value.state, "policy_excluded")
  assert.match(value.label, /observed-only policy/i)
  assert.match(value.next_action, /intentionally skipped/i)
  assert.match(value.next_action, /availability is unverified/i)
  assert.match(value.next_action, /previous errors/i)
  assert.doesNotMatch(JSON.stringify(value), /no retained run|recovered|healthy|source unavailable/i)
  assert.deepEqual(excluded, original)
})

for (const [field, value] of [
  ["source", "ocean"], ["status", "success"], ["error_class", "other"],
  ["note", "Other editorial scope"], ["error", "HTTP 503"],
  ...Object.keys(zeroes).map(key => [key, 1]),
]) test(`a contradictory or different ${field} is not an observed-only exclusion`, () => {
  assert.notEqual(sourceOutcome({ ...excluded, [field]: value }).state, "policy_excluded")
})

for (const key of Object.keys(zeroes)) test(`an unrecorded ${key} is not a zero-count exclusion`, () => {
  const missing = { ...excluded }; delete missing[key]
  assert.notEqual(sourceOutcome(missing).state, "policy_excluded")
})

test("the real source-health projection keeps the policy explanation and old failure evidence", () => {
  const failed = { source: "air_quality", status: "failed", error: "ReadTimeout", ...zeroes }
  const state = { source_health: { air_quality: { success: 0, failed: 1, skipped: 1,
    runs: [{ ts: "2026-11-18T03:00:00Z", status: "failed", error: "ReadTimeout" },
      { ts: "2026-11-18T04:00:00Z", status: "skipped", error_class: "editorial_scope" }] } },
    run_history: [{ started_at: "2026-11-18T04:00:00Z", mode: "alerts", sources: [excluded] },
      { started_at: "2026-11-18T03:00:00Z", mode: "alerts", sources: [failed] }] }
  const old = structuredClone(state)
  const [source] = buildSourceHealthPayload(state, { asOf: "2026-11-18T05:00:00Z" }).sources
  assert.equal(source.health, "idle")
  assert.equal(source.outcome.state, "policy_excluded")
  assert.equal(source.failures, 1)
  assert.equal(source.history_time.current_availability, "unverified")
  assert.equal(source.coverage_row.observed, 0)
  assert.deepEqual(state, old)
})

test("the no-work policy marker preserves explicit access failures and old copy rejections", () => {
  assert.equal(sourceOutcome({ ...excluded, details: { threshold_verification: "failure" } }).state, "baseline_unavailable")
  assert.equal(sourceOutcome({ ...excluded, details: { rainfall_opportunity: { primary_gate: "credential_expired" } } }).state, "access_expired")
  const previous = [{ source: "air_quality", stage: "critic" }]
  assert.equal(sourceOutcome(excluded, previous).state, "policy_excluded")
  assert.deepEqual(previous, [{ source: "air_quality", stage: "critic" }])
})

test("collecting candidates with zero drafts never directs the operator to nonexistent drafts", () => {
  const value = sourceOutcome({ source: "firms", status: "degraded", promoted: 5, drafted: 0 })
  assert.equal(value.state, "supplying")
  assert.match(value.next_action, /no saved draft/i)
  assert.doesNotMatch(value.next_action, /review the resulting drafts/i)
})

test("a recorded draft still requires checking its current review", () => {
  const value = sourceOutcome({ source: "firms", status: "success", promoted: 5, drafted: 1 })
  assert.equal(value.state, "supplying")
  assert.match(value.next_action, /saved drafts.*fresh review/i)
})

for (const drafted of [undefined, null, -1, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, 1.2, "0", false]) test(`unknown saved-draft count stays unknown (${String(drafted)})`, () => {
  const value = sourceOutcome({ source: "firms", status: "success", promoted: 5, drafted })
  assert.equal(value.state, "supplying")
  assert.match(value.next_action, /count was not recorded/i)
  assert.doesNotMatch(value.next_action, /no saved draft|review the resulting drafts/i)
})
