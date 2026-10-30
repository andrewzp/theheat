import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { postOutcomes } from "../lib/post-outcomes.js"
import { textHash } from "../lib/draft-revisions.js"
import PostOutcomeHistory from "../app/components/PostOutcomeHistory.js"

const now = Date.parse("2026-11-02T12:00:00Z")
const text = "Invented delivered sentence about Fictionland."
const hash = textHash(text)
const fixture = (coverage_log) => ({
  drafts: [{ id: "d1", event_id: "invented_event_1", status: "posted", tweet_id: "900", text }],
  publish_ledger: { invented_event_1: { phase: "confirmed", tweet_id: "900", text, text_sha256: hash } },
  tweet_metrics: {},
  ...(coverage_log === undefined ? {} : { coverage_log }),
})
const coverage = (state) => postOutcomes(state, { now }).posts[0].coverage

test("a delivered post joins the coverage class and region logged for its exact receipt event", () => {
  const result = coverage(fixture([
    { cls: "heat", continent: "Atlantis", country: "Fictionland", date: "2026-11-01", event_id: "invented_event_1" },
    { cls: "flood", continent: "Lemuria", country: "Elsewhere", date: "2026-11-01", event_id: "unrelated_event" },
  ]))
  assert.deepEqual(result, { status: "recorded", rows: 1, coverage_class: "heat", continent: "Atlantis",
    country: "Fictionland", date: "2026-11-01", scope: "output_geography_not_recall" })
})

test("absent, unmatched, malformed and conflicting coverage rows never become a selected region", () => {
  // Absent equals the contract default [] (as the dashboard route decodes it); malformed is unknown.
  assert.deepEqual(coverage(fixture(undefined)), { status: "not_recorded", rows: 0 })
  assert.deepEqual(coverage(fixture({ rows: [] })), { status: "unknown", rows: 0 })
  assert.deepEqual(coverage(fixture([{ cls: "heat", continent: "A", country: "B", event_id: "other" }])), { status: "not_recorded", rows: 0 })
  assert.equal(coverage(fixture([{ cls: "heat", continent: 7, country: "B", event_id: "invented_event_1" }])).status, "unknown")
  const conflict = coverage(fixture([
    { cls: "heat", continent: "Atlantis", country: "Fictionland", event_id: "invented_event_1" },
    { cls: "fire", continent: "Atlantis", country: "Fictionland", event_id: "invented_event_1" },
  ]))
  assert.deepEqual(conflict, { status: "conflict", rows: 2 })
  // The current draft's own fields are never used to complete a missing join.
  const state = fixture([])
  state.drafts[0].type = "heat"
  assert.equal(coverage(state).status, "not_recorded")
})

test("the history view states coverage as output geography, not what was missed", () => {
  const outcomes = postOutcomes(fixture([{ cls: "heat", continent: "Atlantis", country: "Fictionland", date: "2026-11-01", event_id: "invented_event_1" }]), { now })
  const markup = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes }))
  assert.match(markup, /Logged coverage: heat · Fictionland, Atlantis/)
  assert.match(markup, /not a measure of what was missed/)
  const none = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes: postOutcomes(fixture(undefined), { now }) }))
  assert.match(none, /No coverage log row matches this post's event/)
  const malformed = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes: postOutcomes(fixture({ rows: [] }), { now }) }))
  assert.match(malformed, /Coverage class and region are unknown/)
})
