import test from "node:test"
import assert from "node:assert/strict"

import { projectStateForDashboard } from "../lib/projection.js"

test("projection returns only whitelisted keys", () => {
  const projected = projectStateForDashboard({
    last_hot10: { date: "2026-06-12", cities: [{ city: "Phoenix" }] },
    streaks: { Phoenix: { consecutive_days: 4 } },
    errors: [{ source: "ghcn", msg: "late" }],
    daily_tweet_count: { "2026-06-12": 2 },
    run_history: [{ id: "run_1", mode: "alerts" }],
    credential_expiry: { EARTHDATA_TOKEN: { label: "NASA Earthdata", expires_at: "2026-08-22T15:18:07Z", source: "jwt" } },
    drafts: [{ id: "draft_1" }],
    publish_ledger: { event_1: { tweet_id: "tweet_123" } },
    source_health: { ghcn: { success: 1 } },
  })

  assert.deepEqual(Object.keys(projected).sort(), [
    "credential_expiry",
    "daily_tweet_count",
    "errors",
    "last_hot10",
    "run_history",
    "streaks",
  ])
  assert.deepEqual(projected.last_hot10.cities, [{ city: "Phoenix" }])
  assert.deepEqual(projected.run_history, [{ id: "run_1", mode: "alerts" }])
  assert.equal(projected.credential_expiry.EARTHDATA_TOKEN.expires_at, "2026-08-22T15:18:07Z")
  assert.equal(projected.drafts, undefined)
  assert.equal(projected.publish_ledger, undefined)
  assert.equal(projected.source_health, undefined)
})

test("projection tolerates missing keys", () => {
  assert.deepEqual(projectStateForDashboard({}), {
    last_hot10: { date: null, cities: [] },
    streaks: {},
    errors: [],
    daily_tweet_count: {},
    run_history: [],
    credential_expiry: {},
  })
})
