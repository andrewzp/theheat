import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import PostOutcomeHistory from "../app/components/PostOutcomeHistory.js"
import { perPostMetricChange, METRIC_CHANGE_KEYS } from "../lib/per-post-metric-change.js"
import { postOutcomes, OUTCOME_METRICS } from "../lib/post-outcomes.js"
import { textHash } from "../lib/draft-revisions.js"

function observation(hour, impressions, char = "a") {
  return { id: "sample:" + char.repeat(64), kind: "sample", association: "recorded", age_status: "recorded",
    platform_created_at: "2026-11-20T00:00:00.000000Z", collected_at: `2026-11-20T0${hour}:00:00.000000Z`,
    post_age_seconds: hour * 3600, conflict: false,
    counts: { likes: 0, retweets: 0, replies: 0, quotes: 0, impressions, bookmarks: null } }
}
function post() {
  return { tweet_id: "1234567", text: "Invented station observation.", revision_status: "recorded",
    observations: [observation(1, 5), observation(2, 6, "b")] }
}
function markup(p) {
  return renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes: { posts: [p] } }))
}
test("the actual post-history component presents a within-post reported count change", () => {
  const html = markup(post())
  assert.match(html, /Changes between saved API observations/)
  assert.match(html, /5 → 6 · \+1/)
  assert.match(html, /not.*improvement/i)
})
test("one early API sample does not become a zero-baseline change", () => {
  const p = post(); p.observations = [observation(1, 2)]
  const html = markup(p)
  assert.match(html, /One saved API observation/)
  assert.doesNotMatch(html, /0 → 2|\+2/)
})

test("comparison is order-independent, reads only the latest two API samples and changes no input", () => {
  const p = post(), before = structuredClone(p)
  const expected = perPostMetricChange(p)
  assert.equal(expected.status, "comparable")
  assert.deepEqual(expected.metrics.find(r => r.key === "impressions"), { key: "impressions", previous: 5, latest: 6, change: 1 })
  assert.deepEqual(perPostMetricChange({ ...p, observations: [...p.observations].reverse() }), expected)
  assert.deepEqual(p, before)
  p.observations.push(observation(3, 4, "c"))
  assert.equal(perPostMetricChange(p).metrics.find(r => r.key === "impressions").change, -2)
  assert.match(markup(p), /6 → 4 · -2/)
  assert.deepEqual(METRIC_CHANGE_KEYS, OUTCOME_METRICS)
})

for (const invalid of [null, undefined, true, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, Infinity, "6"]) {
  test(`missing or invalid count ${String(invalid)} is unknown, never zero`, () => {
    const p = post(); p.observations[1].counts.impressions = invalid
    const out = perPostMetricChange(p)
    assert.equal(out.status, "comparable")
    assert.deepEqual(out.metrics.find(r => r.key === "impressions"), { key: "impressions", previous: 5, latest: null, change: null })
    assert.match(markup(p), /5 → Unknown · change unknown/)
  })
}
test("safe boundary counts subtract exactly; zero is distinct from unknown", () => {
  const p = post(); p.observations[0].counts.impressions = Number.MAX_SAFE_INTEGER
  p.observations[1].counts.impressions = 0
  assert.equal(perPostMetricChange(p).metrics.find(r => r.key === "impressions").change, -Number.MAX_SAFE_INTEGER)
  assert.equal(perPostMetricChange(p).metrics.find(r => r.key === "likes").change, 0)
  assert.equal(perPostMetricChange(p).metrics.find(r => r.key === "bookmarks").change, null)
})

const refusals = {
  "unknown publication revision": p => { p.revision_status = "unknown" },
  "conflicting publication revision": p => { p.revision_status = "conflict" },
  "missing history": p => { delete p.observations },
  "unknown history shape": p => { p.observations.push(null) },
  "undated API sample": p => { p.observations.push({ ...observation(3, 10, "c"), collected_at: null }) },
  "malformed date": p => { p.observations[1].collected_at = "2026-02-30T01:00:00.000000Z" },
  "newest conflict": p => { p.observations[1].conflict = true },
  "newest unassociated": p => { p.observations[1].association = "unusable" },
  "newest unknown age": p => { p.observations[1].age_status = "unknown" },
  "incorrect stored age": p => { p.observations[1].post_age_seconds++ },
  "nonfinite stored age": p => { p.observations[1].post_age_seconds = Infinity },
  "duplicate identity": p => { p.observations[1].id = p.observations[0].id },
  "different platform creation instant": p => { p.observations[1].platform_created_at = "2026-11-20T01:00:00.000000Z"; p.observations[1].post_age_seconds = 3600 },
  "equal collection times": p => { p.observations[1].collected_at = p.observations[0].collected_at; p.observations[1].post_age_seconds = 3600 },
  "ambiguous previous collection time": p => { p.observations.push({ ...observation(1, 99, "c") }) },
}
for (const [reason, mutate] of Object.entries(refusals)) test(`${reason} cannot select an older apparently valid comparison`, () => {
  const p = post(); mutate(p)
  assert.equal(perPostMetricChange(p).status, "unavailable")
  assert.doesNotMatch(markup(p), /5 → 6 · \+1/)
})

test("legacy snapshots do not invent API history and one sample has no baseline", () => {
  const p = post(); p.observations = [{ ...observation(1, 99), kind: "legacy" }]
  assert.deepEqual(perPostMetricChange(p), { status: "insufficient_samples", sample_count: 0 })
  p.observations.push(observation(2, 6, "b"))
  assert.deepEqual(perPostMetricChange(p), { status: "insufficient_samples", sample_count: 1 })
})

test("actual existing projection joins exact receipt and microsecond API observations before the component", () => {
  const text = "Invented retained sentence.", hash = textHash(text)
  const sample = (when, age, impressions) => ({ schema_version: 1, tweet_id: "1234567", source: "x_api.public_metrics",
    sampled_at: when, posted_at: "2026-11-20T00:00:00Z", post_time_basis: "x_api.created_at", post_time_status: "recorded",
    post_age_seconds: age, published_revision_status: "recorded", published_text_sha256: hash, counts: { impressions } })
  const state = { drafts: [{ id: "invented", status: "posted", tweet_id: "1234567", text }],
    publish_ledger: { invented: { phase: "confirmed", tweet_id: "1234567", text, text_sha256: hash } },
    tweet_metrics: { "1234567": { samples: {
      b: sample("2026-11-20T01:00:00.000002Z", 3600.000002, 6),
      a: sample("2026-11-20T01:00:00.000001Z", 3600.000001, 5) } } } }
  const before = structuredClone(state), projected = postOutcomes(state, { now: Date.parse("2026-11-21T00:00:00Z") })
  assert.equal(projected.posts.length, 1)
  const output = perPostMetricChange(projected.posts[0])
  assert.equal(output.status, "comparable")
  assert.equal(output.metrics.find(r => r.key === "impressions").change, 1)
  assert.match(markup(projected.posts[0]), /5 → 6 · \+1/)
  assert.deepEqual(state, before)
})
