import test from "node:test"
import assert from "node:assert/strict"
import { buildProductHealth } from "../lib/product-health.js"
import { recordHumanReview } from "../lib/draft-revisions.js"

const now = Date.parse("2026-09-08T18:00:00Z")
const build = (state) => buildProductHealth({ drafts: [], publish_ledger: {}, ...state }, { now })
const post = (tweet_id, posted_at = "2026-09-07T12:00:00Z") => ({ id: `d-${tweet_id}`, status: "posted", tweet_id, posted_at })

test("legacy state and green workflows do not imply a working product", () => {
  const result = buildProductHealth({ run_history: [{ ended_at: "2026-09-08T17:59:00Z", status: "success", sources: [{ source: "weather", status: "success" }] }] }, { now })
  assert.equal(result.generated_at, "2026-09-08T18:00:00.000Z")
  assert.equal(result.milestones.source_observed.status, "unknown")
  assert.equal(result.milestones.draft_created.status, "unknown")
  assert.equal(result.milestones.draft_reviewed.status, "unknown")
  assert.equal(result.milestones.post_confirmed.status, "unknown")
  assert.equal(result.writer.status, "unknown")
  assert.equal(result.writer.last_recorded_call_count, null)
  assert.equal(result.queue.status, "unknown")
  assert.equal(result.metrics.status, "unknown")
  assert.equal(result.queue.waiting_count, null)
  assert.equal(result.metrics.eligible_post_count, null)
  assert.deepEqual(result.metrics.totals, { likes: null, retweets: null, replies: null })
})

test("only present, valid draft and ledger collections establish an empty inventory", () => {
  for (const state of [{}, { drafts: [] }, { publish_ledger: {} }, { drafts: null, publish_ledger: {} }, { drafts: [null], publish_ledger: {} }, { drafts: [], publish_ledger: [] }, { drafts: [], publish_ledger: { malformed: null } }, { drafts: [], publish_ledger: { malformed: { tweet_id: "one", attempt_conflicts: [{ tweet_id: "two", attempt_conflicts: "invalid" }] } } }]) {
    const result = buildProductHealth(state, { now })
    assert.equal(result.queue.status, "unknown")
    assert.equal(result.queue.waiting_count, null)
    assert.equal(result.queue.unresolved_publish_count, null)
    assert.equal(result.metrics.status, "unknown")
    assert.equal(result.metrics.receipt_backed_post_count, null)
    assert.equal(result.metrics.eligible_post_count, null)
    assert.equal(result.metrics.recorded_post_count, null)
  }
  const recordedEmpty = build({})
  assert.equal(recordedEmpty.queue.status, "recorded")
  assert.equal(recordedEmpty.queue.waiting_count, 0)
  assert.equal(recordedEmpty.metrics.status, "inactive")
  assert.equal(recordedEmpty.metrics.receipt_backed_post_count, 0)
  assert.equal(recordedEmpty.metrics.eligible_post_count, 0)
})

test("latest observed source needs positive recorded observations, with its status retained", () => {
  const result = build({ source_health: {
    empty: { last_success_ts: "2026-09-08T17:00:00Z", runs: [{ ts: "2026-09-08T17:00:00Z", status: "success", observed: 0 }] },
    weather: { runs: [{ ts: "2026-09-08T12:00:00Z", status: "degraded", observed: 6 }] },
    future: { runs: [{ ts: "2026-09-09T12:00:00Z", status: "success", observed: 100 }] },
    twitter_metrics: { runs: [{ ts: "2026-09-08T17:00:00Z", status: "success", observed: 2 }] },
  } })
  assert.equal(result.milestones.source_observed.source, "weather")
  assert.equal(result.milestones.source_observed.observed, 6)
  assert.equal(result.milestones.source_observed.reported_status, "degraded")
  assert.equal(result.milestones.source_observed.age_hours, 6)
  const fallback = build({ run_history: [{ ended_at: "2026-09-08T15:00:00Z", sources: [{ source: "ocean", status: "success", observed: 2 }] }] })
  assert.equal(fallback.milestones.source_observed.timestamp_precision, "run")
  assert.equal(fallback.milestones.source_observed.source, "ocean")
})

test("review milestone verifies the current binding and excludes obsolete reviews", () => {
  const current = { id: "current", text: "40°C forecast", created_at: "2026-09-01T00:00:00Z", status: "pending" }
  recordHumanReview(current)
  current.review_binding.reviewed_at = "2026-09-07T12:00:00Z"
  const obsolete = structuredClone(current)
  Object.assign(obsolete, { id: "obsolete", text: "50°C forecast", created_at: "2026-09-08T12:00:00Z" })
  obsolete.review_binding.reviewed_at = "2026-09-08T13:00:00Z"
  const result = build({ drafts: [current, obsolete] })
  assert.equal(result.milestones.draft_created.id, "obsolete")
  assert.equal(result.milestones.draft_reviewed.id, "current")
  assert.equal(result.milestones.draft_reviewed.review_kind, "human")
})

test("billing failure remains visible despite green workflow and same-day writer calls", () => {
  const state = {
    llm_usage: { "2026-09-08": { "writer|claude-sonnet-4-6": { calls: 3 }, "critic|another-model": { calls: 50 } } },
    suppressions: [{ ts: "2026-09-08T10:00:00Z", stage: "budget_exhausted", reasons: ["anthropic writer: credit balance is too low"] }],
    run_history: [{ ended_at: "2026-09-08T17:00:00Z", status: "success", sources: [] }],
  }
  const result = build(state)
  assert.equal(result.writer.status, "failed")
  assert.equal(result.writer.last_recorded_call_count, 3)
  assert.deepEqual(result.writer.models, ["claude-sonnet-4-6"])
  assert.equal(result.writer.last_failure.stage, "budget_exhausted")
  state.suppressions[0].ts = "2026-09-07T10:00:00Z"
  assert.equal(build(state).writer.status, "calls_recorded")
  assert.equal(build(state).writer.last_failure.stage, "budget_exhausted")
})

test("missing, corrupt and future writer counters cannot become successful calls", () => {
  for (const calls of [undefined, "1", -1, 1.5, true, Infinity]) {
    assert.equal(build({ llm_usage: { "2026-09-08": { "writer|model": { calls } } } }).writer.status, "unknown")
  }
  assert.equal(build({ llm_usage: { "2026-02-31": { "writer|model": { calls: 1 } }, "2026-09-09": { "writer|model": { calls: 2 } } } }).writer.status, "unknown")
  assert.equal(build({ suppressions: [{ ts: "invalid", stage: "budget_exhausted" }] }).writer.status, "failed")
})

test("an undated writer error cannot disappear behind older failures and newer call counts", () => {
  const result = build({
    llm_usage: { "2026-09-08": { "writer|model": { calls: 1 } } },
    suppressions: [
      { ts: "2026-09-07T12:00:00Z", stage: "pipeline_error", reasons: ["older error"] },
      { ts: "invalid", stage: "budget_exhausted", reasons: ["undated credit failure"] },
    ],
  })
  assert.equal(result.writer.status, "failed")
  assert.equal(result.writer.last_failure.at, null)
  assert.deepEqual(result.writer.last_failure.reasons, ["undated credit failure"])
})

test("old receipt-backed posts mean metrics are inactive even with stored zero or green collection", () => {
  const result = build({
    drafts: [post("receipt", "2026-07-23T12:00:00Z")],
    tweet_metrics: { receipt: { at: "2026-08-01T12:00:00Z", likes: 0, retweets: 0, replies: 0 } },
    source_health: { twitter_metrics: { runs: [{ ts: "2026-09-08T12:00:00Z", status: "success" }] } },
  })
  assert.equal(result.milestones.post_confirmed.tweet_id, "receipt")
  assert.equal(result.metrics.status, "inactive")
  assert.equal(result.metrics.receipt_backed_post_count, 1)
  assert.equal(result.metrics.eligible_post_count, 0)
  assert.equal(result.metrics.last_sample_at, null)
  assert.equal(result.metrics.totals.likes, null)
})

test("missing metric fields remain unknown while explicit zero remains a measurement", () => {
  const state = { drafts: [post("one"), post("two")], tweet_metrics: {
    one: { at: "2026-09-08T12:00:00Z", likes: 0, retweets: 0, replies: 0 },
    two: { at: "2026-09-08T12:00:00Z", likes: 0, retweets: 0 },
  } }
  const result = build(state)
  assert.equal(result.metrics.status, "partial")
  assert.equal(result.metrics.recorded_post_count, 1)
  assert.equal(result.metrics.missing_post_count, 1)
  assert.deepEqual(result.metrics.totals, { likes: 0, retweets: 0, replies: null })
  state.tweet_metrics.two.replies = 0
  assert.equal(build(state).metrics.status, "recorded")
  assert.deepEqual(build(state).metrics.totals, { likes: 0, retweets: 0, replies: 0 })
})

test("fresh disabled collection is explicit without erasing existing metrics; stale settings are unknown", () => {
  const state = { drafts: [post("one")], tweet_metrics: {
    one: { at: "2026-09-08T12:00:00Z", likes: 0, retweets: 0, replies: 0 },
  }, run_history: [{ started_at: "2026-09-08T17:00:00Z", runtime_inventory: {
    schema_version: 1, captured_at: "2026-09-08T17:00:00Z", flags: { metrics_enabled: false },
  } }] }
  const result = build(state)
  assert.equal(result.metrics.collection_enabled, false)
  assert.equal(result.metrics.status, "recorded")
  assert.deepEqual(result.metrics.totals, { likes: 0, retweets: 0, replies: 0 })
  state.run_history[0].runtime_inventory.captured_at = "2026-09-07T17:00:00Z"
  assert.equal(build(state).metrics.collection_enabled, null)
  assert.equal(build(state).metrics.status, "recorded")
  delete state.run_history
  assert.equal(build(state).metrics.collection_enabled, null)
})

test("collector failure is unavailable, and no telemetry is unknown for eligible receipts", () => {
  const state = { drafts: [post("one")] }
  assert.equal(build(state).metrics.status, "unknown")
  state.source_health = { twitter_metrics: { runs: [{ ts: "2026-09-08T12:00:00Z", status: "failed", error: "401 Unauthorized" }] } }
  assert.equal(build(state).metrics.status, "unavailable")
  assert.equal(build(state).metrics.last_collector.error, "401 Unauthorized")
  assert.equal(build(state).metrics.totals.likes, null)
})

test("posted without ID and legacy generation memory never establish publication", () => {
  const result = build({ drafts: [{ id: "unconfirmed", status: "posted", posted_at: "2026-09-08T17:00:00Z" }],
    tweet_memory: [{ text: "Generated before publication", at: "2026-09-08T17:00:00Z" }],
    publish_ledger: { event: { phase: "unknown", at: "2026-09-08T16:00:00Z" } },
  })
  assert.equal(result.milestones.post_confirmed.status, "unknown")
  assert.equal(result.metrics.receipt_backed_post_count, 0)
  assert.equal(result.queue.unresolved_publish_count, 1)
})

test("unknown publish evidence remains in the waiting queue after rejection and alongside old receipts", () => {
  const state = { drafts: [
    { id: "pending", status: "pending", created_at: "2026-09-07T18:00:00Z" },
    { id: "rejected", event_id: "event", status: "rejected", text: "Edited text", created_at: "2026-09-01T18:00:00Z", publish_outcome: "unknown" },
    { id: "approved", status: "approved", created_at: "bad-date" },
  ], publish_ledger: {
    event: { tweet_id: "old-receipt", at: "2026-09-02T18:00:00Z", text: "Old text", attempt_conflicts: [{ phase: "unknown", at: "2026-09-03T18:00:00Z" }] },
    orphan: { phase: "unknown", at: "2026-08-01T18:00:00Z" },
    refused: { phase: "not_sent", at: "2026-07-01T18:00:00Z" },
  } }
  const snapshot = structuredClone(state)
  const result = build(state)
  assert.equal(result.queue.waiting_count, 4)
  assert.equal(result.queue.pending_count, 1)
  assert.equal(result.queue.approved_count, 1)
  assert.equal(result.queue.unresolved_publish_count, 2)
  assert.equal(result.queue.oldest_waiting_age_hours, 38 * 24)
  assert.equal(result.queue.unknown_age_count, 1)
  assert.equal(result.milestones.post_confirmed.tweet_id, "old-receipt")
  assert.deepEqual(state, snapshot)
})

test("receipt deduplication includes conflict receipts but missing dates cannot imply active collection", () => {
  const result = build({ drafts: [post("one")], publish_ledger: {
    event: { tweet_id: "one", at: "2026-09-07T12:00:00Z", confirmed_at: "2026-09-07T12:01:00Z", attempt_conflicts: [{ tweet_id: "two", at: "bad-date" }] },
  } })
  assert.equal(result.metrics.receipt_backed_post_count, 2)
  assert.equal(result.metrics.eligible_post_count, 1)
  assert.equal(result.metrics.undated_receipt_count, 1)
  assert.equal(result.metrics.collector_unseen_receipt_count, 1)
  assert.equal(result.milestones.post_confirmed.at, "2026-09-07T12:01:00.000Z")
  assert.equal(build({ drafts: [post("undated", "bad-date")] }).metrics.status, "unknown")
})

test("a dated conflict receipt is publication evidence but outside the current collector's selection path", () => {
  const result = build({ publish_ledger: { event: { phase: "not_sent", attempt_conflicts: [{ tweet_id: "nested", at: "2026-09-07T12:00:00Z" }] } } })
  assert.equal(result.milestones.post_confirmed.tweet_id, "nested")
  assert.equal(result.metrics.receipt_backed_post_count, 1)
  assert.equal(result.metrics.eligible_post_count, 0)
  assert.equal(result.metrics.collector_unseen_receipt_count, 1)
})

test("invalid calendar and future timestamps are not freshness or engagement evidence", () => {
  const result = build({ drafts: [
    { id: "invalid", status: "pending", created_at: "2026-02-31T12:00:00Z" },
    { id: "future", status: "approved", created_at: "2026-09-09T12:00:00Z" },
    post("receipt"),
  ], tweet_metrics: { receipt: { at: "2026-09-09T12:00:00Z", likes: 100, retweets: 0, replies: 0 } } })
  assert.equal(result.milestones.draft_created.status, "unknown")
  assert.equal(result.queue.oldest_waiting_age_hours, null)
  assert.equal(result.queue.unknown_age_count, 2)
  assert.equal(result.metrics.totals.likes, null)
  assert.throws(() => buildProductHealth({}, { now: NaN }), /valid clock/)
})

test("metrics use the collector's inclusive 30-day boundary and 50-ID cap", () => {
  const boundary = build({ drafts: [post("included", "2026-08-09T18:00:00Z"), post("excluded", "2026-08-09T17:59:59Z")] })
  assert.equal(boundary.metrics.eligible_post_count, 1)
  const capped = build({ drafts: Array.from({ length: 51 }, (_, i) => post(`receipt-${i}`)) })
  assert.equal(capped.metrics.receipt_backed_post_count, 51)
  assert.equal(capped.metrics.eligible_post_count, 50)
})
