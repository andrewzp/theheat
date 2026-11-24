/** Invented IDs/times, no provider, platform or state-writing calls. */
import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { postingCadence } from "../lib/posting-cadence.js"
import { buildProductHealth } from "../lib/product-health.js"
import { ProductHealthPanel } from "../app/components/ProductHealthPanel.js"

const now = Date.parse("2026-11-24T12:00:00Z")
const draft = (id = "10001", at = "2026-11-24T11:00:00Z") => ({ id: `draft-${id}`, status: "posted", tweet_id: id, posted_at: at })
const state = (drafts = [], publish_ledger = {}) => ({ drafts, publish_ledger })
const read = value => postingCadence(value, { now })
const sample = (changes = {}) => ({ schema_version: 1, tweet_id: "10001", source: "x_api.public_metrics",
  sampled_at: "2026-11-24T11:00:00Z", posted_at: "2026-11-23T12:00:00Z",
  post_time_basis: "x_api.created_at", post_time_status: "recorded", post_age_seconds: 82800,
  published_revision_status: "unknown", counts: { likes: 0 }, ...changes })
function withSamples(value, samples) { return { ...value, tweet_metrics: { "10001": { samples } } } }

test("four distinct dated receipts meet the recorded goal; flags, approvals and drafts do not", () => {
  const value = state([...Array.from({ length: 4 }, (_, i) => draft(String(10001 + i))),
    { status: "posted", posted_at: "2026-11-24T11:00:00Z" }, { status: "approved" }])
  const before = structuredClone(value), result = read(value)
  assert.equal(result.target_per_day, 4)
  assert.deepEqual(result.today, { status: "recorded", minimum_count: 4, uncertain_receipt_count: 0, target_met: true })
  assert.equal(result.last_24h.minimum_count, 4)
  assert.deepEqual(value, before)
})

test("an empty retained inventory records zero; absent or malformed collections cannot", () => {
  assert.equal(read(state()).today.status, "recorded")
  assert.equal(read(state()).today.minimum_count, 0)
  for (const value of [{}, { drafts: [] }, { drafts: null, publish_ledger: {} }, state([null]), state([], { malformed: null })]) {
    assert.equal(read(value).today.status, "unknown")
    assert.equal(read(value).today.target_met, null)
  }
})

test("draft, published revision and nested confirmed receipt copies count once in either order", () => {
  const saved = draft(), receipt = { phase: "confirmed", tweet_id: saved.tweet_id, confirmed_at: saved.posted_at }
  const data = state([saved, structuredClone(saved), { published_revision: receipt }], {
    a: receipt, b: { phase: "unknown", attempt_conflicts: [structuredClone(receipt),
      { phase: "confirmed", tweet_id: "10002", at: "2026-11-24T10:00:00Z" }] },
  })
  assert.equal(read(data).retained_receipt_count, 2)
  assert.equal(read(data).today.minimum_count, 2)
  data.drafts.reverse()
  data.publish_ledger = Object.fromEntries(Object.entries(data.publish_ledger).reverse())
  assert.equal(read(data).today.minimum_count, 2)
})

test("a later send attempt without a publication time never creates a fresh post milestone", () => {
  const value = state([{ id: "invented", status: "posted", tweet_id: "10001", last_publish_attempt_at: "2026-11-24T11:00:00Z" }])
  const health = buildProductHealth(value, { now })
  assert.equal(health.milestones.post_confirmed.status, "unknown")
  assert.equal(health.publication_cadence.today.minimum_count, 0)
  assert.equal(health.publication_cadence.today.target_met, null)
})

test("conflicting dates for one ID cannot be resolved by choosing the newest or the first", () => {
  for (const reverse of [false, true]) {
    const copies = [draft("10001", "2026-11-20T12:00:00Z"), draft("10001")]
    if (reverse) copies.reverse()
    const result = read(state(copies))
    assert.equal(result.retained_receipt_count, 1)
    assert.equal(result.today.minimum_count, 0)
    assert.equal(result.today.uncertain_receipt_count, 1)
    assert.equal(result.latest_dated_receipt.status, "unknown")
  }
  const health = buildProductHealth(state([draft("10001", "2026-11-20T12:00:00Z")], {
    event: { phase: "confirmed", tweet_id: "10001", confirmed_at: "2026-11-24T11:00:00Z" },
  }), { now })
  assert.equal(health.milestones.post_confirmed.status, "unknown")
})

test("different supplied times wholly inside one window count one receipt but do not establish an exact time", () => {
  const result = read(state([draft(), draft("10001", "2026-11-24T10:00:00Z")]))
  assert.equal(result.today.minimum_count, 1)
  assert.equal(result.today.target_met, false)
  assert.equal(result.latest_dated_receipt.status, "unknown")
})

test("UTC midnight, offsets and inclusive rolling boundary retain microsecond distinctions", () => {
  const result = read(state([
    draft("10001", "2026-11-24T00:00:00Z"),
    draft("10002", "2026-11-23T19:00:00-05:00"),
    draft("10003", "2026-11-23T12:00:00Z"),
    draft("10004", "2026-11-23T11:59:59.999999Z"),
  ]))
  assert.equal(result.today.minimum_count, 2)
  assert.equal(result.last_24h.minimum_count, 3)
  assert.equal(read(state([draft("10001", "2026-11-24T12:00:00.000001Z")])).today.uncertain_receipt_count, 1)
})

test("bad dates, local clocks and future values remain unknown even beside a good copy", () => {
  for (const at of ["bad-date", "2026-02-30T12:00:00Z", "2026-11-24T11:00:00", "2026-11-25T00:00:00Z"]) {
    const result = read(state([draft(), draft("10001", at)]))
    assert.equal(result.today.minimum_count, 0)
    assert.equal(result.today.uncertain_receipt_count, 1)
  }
})

test("an undated copy can use a genuine confirmation, while unknown attempt dates cannot", () => {
  const a = state([draft("10001", null)], { event: { phase: "confirmed", tweet_id: "10001", at: "2026-11-24T11:00:00Z" } })
  assert.equal(read(a).today.minimum_count, 1)
  a.publish_ledger.event.phase = "unknown"
  assert.equal(read(a).today.minimum_count, 0)
  assert.equal(read(a).today.uncertain_receipt_count, 1)
})

test("invalid IDs and contradictory not-sent records cannot inflate counts or erase confirmed children", () => {
  const result = read(state([draft("<script>secret</script>"), draft(10001)], {
    event: { phase: "not_sent", tweet_id: "10002", confirmed_at: "2026-11-24T11:00:00Z", attempt_conflicts: [
      { phase: "confirmed", tweet_id: "10003", confirmed_at: "2026-11-24T11:00:00Z" },
    ] },
  }))
  assert.equal(result.today.minimum_count, 1)
  assert.equal(result.inventory_known, false)
  assert.doesNotMatch(JSON.stringify(result), /script|secret/)
})

test("partial evidence preserves a supported lower bound and never awards an unsupported goal", () => {
  const result = read({ drafts: [draft()] })
  assert.equal(result.today.status, "partial")
  assert.equal(result.today.minimum_count, 1)
  assert.equal(result.today.target_met, null)
  assert.equal(read({ drafts: Array.from({ length: 4 }, (_, i) => draft(String(10001 + i))) }).today.target_met, true)
})

test("a supported platform creation time resolves local acknowledgement dates through the real outcome reader", () => {
  const value = withSamples(state([draft()], {
    event: { phase: "confirmed", tweet_id: "10001", confirmed_at: "2026-11-20T12:00:00Z" },
  }), { original: sample(), repeated: sample() })
  const before = structuredClone(value), health = buildProductHealth(value, { now })
  assert.equal(health.post_outcomes.posts[0].observations.length, 1)
  assert.equal(health.post_outcomes.posts[0].observations[0].age_status, "recorded")
  assert.equal(health.publication_cadence.today.minimum_count, 0)
  assert.equal(health.publication_cadence.last_24h.minimum_count, 1)
  assert.equal(health.milestones.post_confirmed.at, "2026-11-23T12:00:00.000Z")
  assert.deepEqual(value, before)
})

test("different supported platform dates stay alternatives in either input order", () => {
  const a = sample(), b = sample({ posted_at: "2026-11-24T10:00:00Z", post_age_seconds: 3600 })
  for (const samples of [{ a, b }, { b, a }]) {
    const result = read(withSamples(state([draft()]), samples))
    assert.equal(result.today.minimum_count, 0)
    assert.equal(result.today.uncertain_receipt_count, 1)
    assert.equal(result.last_24h.minimum_count, 1)
    assert.equal(result.latest_dated_receipt.status, "unknown")
  }
})

test("unusable associations, unsupported clock labels and inconsistent ages cannot redouble a saved post", () => {
  for (const changes of [{ tweet_id: "10002" }, { source: "unqualified" }, { post_time_basis: "receipt.confirmed_at" },
    { post_time_status: "unknown" }, { post_age_seconds: 1 }, { posted_at: "2026-11-25T00:00:00Z" },
    { sampled_at: "2026-11-25T00:00:00Z" }]) {
    const result = read(withSamples(state([draft("10001", "2026-11-20T12:00:00Z")]), { unqualified: sample(changes) }))
    assert.equal(result.today.minimum_count, 0)
    assert.equal(result.last_24h.minimum_count, 0)
    assert.equal(result.latest_dated_receipt.at, "2026-11-20T12:00:00.000Z")
  }
  const result = read(withSamples(state([draft()]), { valid: sample(), inconsistent: sample({ post_age_seconds: 1 }) }))
  assert.equal(result.today.uncertain_receipt_count, 1)
  assert.equal(result.latest_dated_receipt.status, "unknown")
})

test("a pending draft with a stray ID and metrics is not a publication receipt", () => {
  const result = read(withSamples(state([{ ...draft(), status: "pending" }]), { original: sample() }))
  assert.equal(result.retained_receipt_count, 0)
  assert.equal(result.today.minimum_count, 0)
  const revision = { phase: "confirmed", tweet_id: "10001", at: "2026-11-24T11:00:00Z" }
  assert.equal(read(state([{ status: "pending", published_revision: revision }])).today.minimum_count, 1)
})

test("an older dated receipt beside an undated ID is described as dated evidence, never full recent history", () => {
  const health = buildProductHealth(state([draft("10001", "2026-11-20T12:00:00Z"), draft("10002", null)]), { now,
    settings: { auto_publish_enabled: true } })
  assert.equal(health.publication_cadence.today.target_met, null)
  assert.equal(health.publication_cadence.uncertain_time_receipts, 1)
  const html = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health }))
  assert.match(html, /1 post IDs have missing or conflicting times/)
})

test("bounded malformed and cyclic conflict trees withhold inventory certainty", () => {
  const receipt = { phase: "confirmed", tweet_id: "10001", at: "2026-11-24T11:00:00Z" }
  receipt.attempt_conflicts = [receipt]
  assert.equal(read(state([], { receipt })).inventory_known, false)
  const tooMany = state(Array.from({ length: 10_001 }, () => draft()))
  assert.equal(read(tooMany).inventory_known, false)
})

test("the actual panel displays the goal and supported counts without changing publication settings", () => {
  const input = state([draft(), draft("10002", "2026-11-23T14:00:00Z")])
  const before = structuredClone(input)
  const health = buildProductHealth(input, { now })
  const html = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health }))
  assert.match(html, /Goal: 4 per day/)
  assert.match(html, /Today \(UTC\): 1 · Last 24 hours: 2/)
  assert.match(html, /Drafts and send attempts are not posts/)
  assert.deepEqual(input, before)
  const unknown = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health: buildProductHealth({}, { now }) }))
  assert.match(unknown, /Today \(UTC\): Unknown/)
})
