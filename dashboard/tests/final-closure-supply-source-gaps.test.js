// A7: actual source gaps and their miss reasons reach the coverage view (selection
// trace) and the weekly cadence, with the exact owner/operator next action. A gap
// names why a source supplied nothing; it is never a count of missed events.
import assert from "node:assert/strict"
import test from "node:test"
import { sourceOutcome } from "../lib/live-content-status.js"
import { selectionTrace } from "../lib/selection-trace.js"
import { buildWeeklyReview } from "../lib/weekly-review.js"

const incident = (product, outcome, state) => ({ schema: "theheat.source-incident/v1", product_state: state,
  attempts: [{ key: `${product}|w|r|p`, product_id: product, role: "primary", outcome }] })
const LATEST = { id: "run-latest", started_at: "2026-10-30T10:36:53Z", sources: [
  { source: "open_meteo_extreme_signals", status: "degraded", observed: 121, promoted: 0,
    details: { threshold_verification: "failure" } },
  { source: "gpm_imerg", status: "failed", error: "GPM IMERG fetch failed: Earthdata refused this credential at 2026-10-30T09:00:00Z; next attempt after 2026-10-30T15:00:00Z unless the credential is renewed (no request sent)",
    details: { incident: incident("gpm_imerg.imerg_late_opendap", "access_backoff", "access_hold") } },
  { source: "firms", status: "failed", error: "FIRMS/HMS fetch failed: HTTP 404",
    details: { incident: incident("firms.noaa_hms", "endpoint_missing", "unavailable") } },
  { source: "enso", status: "skipped", note: "Runs on the 1st of the month" },
  { source: "air_quality", status: "success", observed: 624, promoted: 5 },
] }

test("a refused or backed-off credential is an owner access outcome, not a retry-later outage", () => {
  const gpm = sourceOutcome(LATEST.sources[1])
  assert.equal(gpm.state, "access_refused")
  assert.match(gpm.next_action, /bounded backoff/)
  assert.match(gpm.detail, /gpm_imerg\.imerg_late_opendap/)
  const baseline = sourceOutcome(LATEST.sources[0])
  assert.equal(baseline.state, "baseline_unavailable")
  assert.match(baseline.next_action, /build_station_thresholds\.py resolve-inputs, fetch-inputs and package/)
  assert.match(baseline.next_action, /install-manifest/)
})

test("the coverage trace names each source gap with its reason; schedule skips and supplying sources are not gaps", () => {
  const trace = selectionTrace({ run_history: [LATEST], drafts: [], suppressions: [], candidates_log: [] })
  assert.deepEqual(trace.source_gaps.map(gap => [gap.source, gap.state]), [
    ["firms", "endpoint_missing"], ["gpm_imerg", "access_refused"], ["open_meteo_extreme_signals", "baseline_unavailable"]])
  assert.deepEqual(trace.not_fetched_sources, ["enso", "firms", "gpm_imerg"])
  assert.equal(trace.recall, null)
  assert.ok(trace.source_gaps.every(gap => typeof gap.next_action === "string" && gap.next_action.length > 0))
})

test("the weekly cadence proposes the owner access action first", () => {
  const review = buildWeeklyReview({ state: { drafts: [], run_history: [LATEST], publish_ledger: {} }, asOf: "2026-10-31T00:00:00Z" })
  const improvement = review.improvement
  assert.equal(improvement.kind, "owner_action")
  assert.match(improvement.issue, /gpm_imerg: Access refused/)
})
