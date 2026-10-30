import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { postOutcomes } from "../lib/post-outcomes.js"
import { textHash } from "../lib/draft-revisions.js"
import PostOutcomeHistory from "../app/components/PostOutcomeHistory.js"

// Shared with src/two_bot/usage_observations.py (cost lane D3).
const vectors = JSON.parse(readFileSync(new URL("../../tests/final_closure/fixtures/cost_attribution_vectors.json", import.meta.url)))
const now = Date.parse("2026-11-02T12:00:00Z")
const text = "Invented delivered sentence about Fictionland."
const EVENT = "invented_event_1"
let serial = 0
const observation = (stage, attribution, changes = {}) => {
  serial += 1
  const row = { ...structuredClone(vectors.base_observation), id: serial.toString(16).padStart(32, "0"), stage, ...changes }
  return attribution === undefined ? row : { ...row, attribution }
}
const joined = (eventId, attempt = "0123456789abcdef") => ({ schema_version: 1, status: "joined_attempt", operation: "alerts",
  path: "ordinary", attempt, event_id: eventId })
const fixture = (observations, eventId = EVENT) => ({
  drafts: [{ id: "d1", event_id: eventId, status: "posted", tweet_id: "900", text }],
  publish_ledger: { [eventId]: { phase: "confirmed", tweet_id: "900", text, text_sha256: textHash(text) } },
  ...(observations === undefined ? {} : { llm_usage_observations: { schema_version: 1, observations, invalid: 0, truncated: false } }),
})
const usage = (state) => postOutcomes(state, { now }).posts[0].generation_usage
const VECTOR_EVENT = "gdacs_TC_1001_red"

test("model responses attributed to the post's exact receipt event join by stage, with the charge unknown", () => {
  const result = usage(fixture([
    observation("writer", joined(EVENT)),
    observation("critic", joined(EVENT), { usage_status: "absent" }),
    observation("writer", joined(EVENT, "fedcba9876543210")),
    observation("writer", joined("unrelated_event")),
  ]))
  assert.equal(result.status, "joined")
  assert.equal(result.responses, 3)
  assert.equal(result.attempts, 2)
  assert.deepEqual(result.by_stage, {
    writer: { responses: 2, usage_present: 2, providers: ["anthropic"] },
    critic: { responses: 1, usage_present: 0, providers: ["anthropic"] },
  })
  assert.equal(result.charge, "unknown")
})

test("unattributed, operation-only, late, unjoined and invalid rows are never assigned to a post", () => {
  const notAssigned = [
    observation("writer", undefined),
    observation("writer", { schema_version: 1, status: "joined_operation", operation: "alerts", path: "ordinary", attempt: null, event_id: null }),
    ...vectors.valid.filter((row) => row.status !== "joined_attempt").map((row) => observation("writer", row)),
    // Unchanged shared invalid vectors; several name the post's own event and must still never join.
    ...vectors.invalid.map((row) => observation("writer", row)),
  ]
  assert.deepEqual(usage(fixture(notAssigned, VECTOR_EVENT)), { status: "not_joined", charge: "unknown" })
  // The one valid joined vector for that event does join, proving the event matched.
  const valid = vectors.valid.find((row) => row.status === "joined_attempt" && row.event_id === VECTOR_EVENT)
  assert.equal(usage(fixture([...notAssigned, observation("writer", valid)], VECTOR_EVENT)).responses, 1)
  assert.deepEqual(usage(fixture(undefined)), { status: "not_loaded", charge: "unknown" })
})

test("the history view never presents missing attribution as zero cost", () => {
  const joinedView = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes: postOutcomes(fixture([observation("writer", joined(EVENT))]), { now }) }))
  assert.match(joinedView, /1 model response\(s\) across 1 attempt\(s\) \(writer 1\)/)
  assert.match(joinedView, /the charge is unknown/)
  const none = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes: postOutcomes(fixture([]), { now }) }))
  assert.match(none, /this is not zero cost/)
})
