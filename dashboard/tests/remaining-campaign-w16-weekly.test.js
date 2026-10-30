// W16.1/W16.2: weekly evidence joins and one supported improvement, from invented retained state only.
import test from "node:test"
import assert from "node:assert/strict"
import { draftIdentity } from "../lib/draft-revisions.js"
import { buildWeeklyReview, weeklyReviewMarkdown } from "../lib/weekly-review.js"

const asOf = "2026-10-30T12:00:00.000Z"
function state(extra = {}) {
  const d = { id: "invented-draft", event_id: "invented-event", status: "posted", publish_outcome: "confirmed", tweet_id: "1234567890",
    text: "Invented Port Example forecast text.", content_revision: 1, posted_at: "2026-10-29T12:00:00.000Z" }
  return { drafts: [d], publish_ledger: { [d.event_id]: { ...draftIdentity(d), text: d.text, tweet_id: d.tweet_id, phase: "confirmed",
    intent_id: "10a97d68-2e51-4998-92ed-f830863f7218" } }, ...extra }
}
const RUN = { started_at: "2026-10-30T01:00:00Z", sources: [
  { source: "gpm_imerg", status: "failed", error: "EARTHDATA_TOKEN expired 2026-08-22T15:18:07Z" },
  { source: "leaderboard", status: "degraded", observed: 638, promoted: 0, note: "hot10_short_slate: 0 of 10 required qualified locations" },
  { source: "air_quality", status: "success", observed: 624, promoted: 2, details: { aq_availability: { requested_cities: 633, observed_cities: 624 } } },
] }

test("missing inputs produce a useful partial report, never zeros", () => {
  const r = buildWeeklyReview({ state: state(), asOf })
  assert.equal(r.evidence.source_outcomes.status, "unavailable")
  assert.equal(r.evidence.cost_reconciliation.status, "unavailable")
  assert.equal(r.evidence.post_age_outcomes.metrics_available, false)
  assert.equal(r.evidence.post_age_outcomes.posts[0].status, "unavailable")
  assert.equal(r.improvement.kind, "none")
  assert.equal(r.improvement.automatic_changes, false)
})

test("source outcomes, stage failures and post-age samples are joined from retained evidence", () => {
  const s = state({ run_history: [RUN],
    suppressions: [...Array(4)].map((_, i) => ({ ts: `2026-10-2${8 + (i % 2)}T0${i}:00:00Z`, stage: "fact_check", source: "air_quality" }))
      .concat([{ ts: "2026-10-01T00:00:00Z", stage: "critic" }]),
    tweet_metrics: { "1234567890": { samples: {
      a: { post_age_seconds: 3600 * 20, counts: { likes: 3, retweets: 1 } },
      b: { post_age_seconds: 3600 * 70, counts: { likes: 9, retweets: 2 } },
      c: { post_age_seconds: 3600 * 100, counts: { likes: 11, retweets: 2 } } } } } })
  const r = buildWeeklyReview({ state: s, asOf })
  const rows = Object.fromEntries(r.evidence.source_outcomes.rows.map(row => [row.source, row]))
  assert.equal(rows.gpm_imerg.state, "access_expired")
  assert.equal(rows.air_quality.universe_checked, 633)
  assert.equal(r.evidence.stage_failures.counts.fact_check, 4)
  assert.equal(r.evidence.stage_failures.counts.critic, 0)  // Outside the window.
  const age = r.evidence.post_age_outcomes.posts[0]
  assert.deepEqual([age.within_24h.post_age_hours, age.within_24h.counts.likes, age.within_72h.counts.likes], [20, 3, 9])
  assert.equal(r.improvement.kind, "owner_action")
  assert.match(r.improvement.proposed_change, /Renew the expired credential/)
})

test("selection order: owner access, then missing inputs, then a repeated local rejection", () => {
  const withoutOwner = { ...RUN, sources: RUN.sources.slice(1) }
  const input = buildWeeklyReview({ state: state({ run_history: [withoutOwner] }), asOf })
  assert.equal(input.improvement.kind, "source_uncertainty")
  assert.match(input.improvement.proposed_change, /build_normals/)
  const healthy = { ...RUN, sources: [RUN.sources[2]] }
  const local = buildWeeklyReview({ state: state({ run_history: [healthy], suppressions: [...Array(3)].map((_, i) => ({ ts: `2026-10-29T0${i}:00:00Z`, stage: "critic" })) }), asOf })
  assert.equal(local.improvement.kind, "local_repair")
  assert.match(local.improvement.issue, /3 candidates were rejected at critic/)
  assert.equal(local.improvement.publication_authorized, false)
})

test("a supplied cost reconciliation is carried without inventing totals", () => {
  const r = buildWeeklyReview({ state: state(), asOf, costReconciliation: { coverage: "partial", discrepancies: 2, unmatched_charges: 1 } })
  assert.deepEqual(r.evidence.cost_reconciliation, { status: "supplied", coverage: "partial", discrepancies: 2, reconciled_total_usd: null, unmatched_charges: 1 })
  assert.match(weeklyReviewMarkdown(r), /cost reconciliation supplied/)
  assert.equal(r.decision.promotion, "HOLD")
})
