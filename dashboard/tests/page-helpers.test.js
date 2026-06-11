import test from "node:test"
import assert from "node:assert/strict"

import { hot10IsStale, todayTweetCount } from "../lib/format.js"

test("today count uses UTC date key", () => {
  const counts = {
    "2026-06-10": 2,
    "2026-06-11": 7,
  }

  assert.equal(todayTweetCount(counts, "2026-06-11T00:30:00Z"), 7)
  assert.equal(todayTweetCount(counts, "2026-06-11T23:59:59Z"), 7)
  assert.equal(todayTweetCount(counts, "2026-06-12T00:00:00Z"), 0)
})

test("hot10 stale after 24h, fresh before", () => {
  assert.equal(hot10IsStale("2026-06-10", "2026-06-11T11:59:00Z"), false)
  assert.equal(hot10IsStale("2026-06-10", "2026-06-11T12:01:00Z"), true)
  assert.equal(hot10IsStale(null, "2026-06-11T12:01:00Z"), false)
})
