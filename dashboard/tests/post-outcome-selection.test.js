import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import PostOutcomeHistory from "../app/components/PostOutcomeHistory.js"
import { postOutcomes } from "../lib/post-outcomes.js"
import { textHash } from "../lib/draft-revisions.js"

// Invented receipts and API responses, passed through the real outcome reader.
const now = Date.parse("2026-11-22T12:00:00Z")
function stateFor(rows) {
  return {
    drafts: [],
    publish_ledger: Object.fromEntries(rows.map(row => [row.id, {
      phase: "confirmed", tweet_id: row.id, text: `Invented post ${row.id}.`,
      text_sha256: textHash(`Invented post ${row.id}.`),
    }])),
    tweet_metrics: Object.fromEntries(rows.filter(row => row.samples).map(row => [row.id, {
      samples: Object.fromEntries(row.samples.map((sample, n) => [String(n), {
        schema_version: 1, tweet_id: row.id, source: "x_api.public_metrics",
        sampled_at: sample.at, posted_at: sample.created ?? "2026-11-19T00:00:00Z",
        post_time_basis: "x_api.created_at", post_time_status: "recorded",
        post_age_seconds: (Date.parse(sample.at) - Date.parse(sample.created ?? "2026-11-19T00:00:00Z")) / 1000,
        published_revision_status: "recorded", published_text_sha256: textHash(`Invented post ${row.id}.`),
        counts: { impressions: sample.impressions ?? 0 }, ...sample.overrides,
      }])) } ])),
  }
}
const project = state => postOutcomes(state, { now })
const render = outcomes => renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes }))
function selected(html) {
  const option = html.match(/<option\b[^>]*\bselected=""[^>]*>/)?.[0]
  return option?.match(/\bvalue="([^"]+)"/)?.[1] ?? null
}

test("initial history opens on recent saved sampling rather than an old empty receipt", () => {
  const state = stateFor([{ id: "100" }, { id: "200", samples: [{ at: "2026-11-21T00:00:00Z" }] }])
  const before = structuredClone(state), outcomes = project(state), html = render(outcomes)
  assert.equal(selected(html), "200")
  assert.match(html, /Invented post 200\./)
  assert.match(html, /Post 100 · 0 saved observations/)
  assert.match(html, /Post 200 · 1 saved observation/)
  assert.deepEqual(state, before)
})

test("sampling clock wins over identifier order and impression counts", () => {
  const outcomes = project(stateFor([
    { id: "100", samples: [{ at: "2026-11-21T00:00:00Z", impressions: 0 }] },
    { id: "999", samples: [{ at: "2026-11-20T00:00:00Z", impressions: 1000000 }] },
  ]))
  assert.equal(selected(render(outcomes)), "100")
})

test("one poll's ties use a verified platform creation clock rather than source or ID order", () => {
  const outcomes = project(stateFor([
    { id: "100", samples: [{ at: "2026-11-21T00:00:00Z", created: "2026-11-19T00:00:00Z" }] },
    { id: "200", samples: [{ at: "2026-11-21T00:00:00Z", created: "2026-11-20T00:00:00Z" }] },
  ]))
  assert.equal(selected(render(outcomes)), "200")
  assert.equal(selected(render({ ...outcomes, posts: [...outcomes.posts].reverse() })), "200")
})

test("unverified post age cannot win a same-poll tie", () => {
  const outcomes = project(stateFor([
    { id: "100", samples: [{ at: "2026-11-21T00:00:00Z" }] },
    { id: "200", samples: [{ at: "2026-11-21T00:00:00Z", created: "2026-11-20T23:00:00Z", overrides: { post_age_seconds: 1 } }] },
  ]))
  assert.equal(selected(render(outcomes)), "100")
})

test("a newer conflicting API sample remains the initial view rather than being hidden", () => {
  const outcomes = project(stateFor([
    { id: "100", samples: [{ at: "2026-11-20T00:00:00Z" }] },
    { id: "200", samples: [
      { at: "2026-11-21T00:00:00Z", impressions: 2 },
      { at: "2026-11-21T00:00:00Z", impressions: 3 },
    ] },
  ]))
  const html = render(outcomes)
  assert.equal(selected(html), "200")
  assert.match(html, /Conflicting observations at this collection time/)
  assert.match(html, /Saved API observations cannot be compared/)
})

test("canonical microseconds remain ordered without millisecond rounding", () => {
  const outcomes = project(stateFor([
    { id: "100", samples: [{ at: "2026-11-21T00:00:00.000001Z", overrides: { post_age_seconds: 172800.000001 } }] },
    { id: "200", samples: [{ at: "2026-11-21T00:00:00.000002Z", overrides: { post_age_seconds: 172800.000002 } }] },
  ]))
  assert.equal(selected(render(outcomes)), "200")
})

test("missing, invalid or legacy-only clocks retain the original first-receipt fallback", () => {
  const state = stateFor([{ id: "100" }, { id: "200" }])
  state.tweet_metrics["200"] = { at: "2026-11-21T00:00:00Z", likes: 3 }
  assert.equal(selected(render(project(state))), "100")
  const outcomes = project(state)
  outcomes.posts[1].observations = [{ kind: "sample", association: "recorded", collected_at: "2026-02-31T00:00:00.000000Z" }]
  assert.equal(selected(render(outcomes)), "100")
  assert.equal(selected(render(project({ drafts: [], publish_ledger: {} }))), null)
})

test("malformed history's option count remains unknown rather than zero", () => {
  const outcomes = project(stateFor([{ id: "100" }, { id: "200" }]))
  outcomes.posts[1].observations = null
  assert.match(render(outcomes), /Post 200 · Unknown observations/)
})
