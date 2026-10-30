// W08.6: six distinct trace outcomes reach the real Sources payload; unknown denominators stay null.
import test from "node:test"
import assert from "node:assert/strict"
import { buildSourceHealthPayload } from "../lib/source-health.js"
import { selectionTrace } from "../lib/selection-trace.js"

const state = {
  candidates_log: [{ event_id: "e-qualified" }, { event_id: "e-failed" }, { event_id: "e-waiting" }, { event_id: "e-posted" }],
  suppressions: [{ event_id: "e-unqualified", stage: "evidence_contract" }, { event_id: "e-failed", stage: "fact_check" }],
  drafts: [{ event_id: "e-waiting", status: "pending" }, { event_id: "e-posted", status: "posted", tweet_id: "invented-1" },
    { event_id: "e-unknown", status: "approved", publish_outcome: "unknown" }],
  run_history: [{ started_at: "2026-10-29T06:00:00Z", sources: [{ source: "firms", status: "failed" }, { source: "gdacs", status: "success" }] }],
}

test("each event has exactly one of the six outcomes", () => {
  const trace = selectionTrace(state, { referenceOpportunities: ["e-posted", "e-missing"] })
  const outcomes = Object.fromEntries(trace.events.map(e => [e.event_id, e.outcome]))
  assert.deepEqual(outcomes, {
    "e-failed": "failed_checks", "e-missing": "not_fetched", "e-posted": "posted", "e-qualified": "not_selected",
    "e-unknown": "waiting", "e-unqualified": "unqualified", "e-waiting": "waiting",
  })
  assert.equal(trace.reference_denominator, 2)
  assert.equal(trace.recall, null)
  assert.deepEqual(trace.not_fetched_sources, ["firms"])
})

test("Sources payload carries the trace with an unknown denominator", () => {
  const payload = buildSourceHealthPayload(state, { asOf: "2026-10-30T00:00:00Z" })
  assert.equal(payload.selection_trace.reference_denominator, null)
  assert.equal(payload.selection_trace.counts.posted, 1)
  assert.match(payload.selection_trace.scope, /not global recall/)
})

test("a repeated episode poll and a portfolio miss are 'not selected', never unqualified", () => {
  const trace = selectionTrace({ suppressions: [{ event_id: "e-repeat", stage: "episode_repeat" },
    { event_id: "e-incomplete", stage: "portfolio_not_selected" }] })
  assert.deepEqual(trace.events.map(e => [e.event_id, e.outcome, e.detail]), [
    ["e-incomplete", "not_selected", "portfolio_not_selected"], ["e-repeat", "not_selected", "episode_repeat"]])
})
