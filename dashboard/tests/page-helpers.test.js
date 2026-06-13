import test from "node:test"
import assert from "node:assert/strict"

import { formatDuration, hot10IsStale, timeAgo, todayTweetCount } from "../lib/format.js"

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

test("timeAgo formats dashboard relative timestamps", () => {
  const nowMs = Date.parse("2026-06-12T12:00:00Z")
  const realNow = Date.now
  Date.now = () => nowMs

  try {
    assert.equal(timeAgo(null), "never")
    assert.equal(timeAgo("2026-06-12T11:59:45Z"), "just now")
    assert.equal(timeAgo("2026-06-12T11:37:00Z"), "23m ago")
    assert.equal(timeAgo("2026-06-12T09:00:00Z"), "3h ago")
    assert.equal(timeAgo("2026-06-10T12:00:00Z"), "2d ago")
  } finally {
    Date.now = realNow
  }
})

test("formatDuration matches dashboard latency labels", () => {
  assert.equal(formatDuration(undefined), "—")
  assert.equal(formatDuration(null), "—")
  assert.equal(formatDuration(121), "121ms")
  assert.equal(formatDuration(15446), "15.4s")
})
