import test from "node:test"
import assert from "node:assert/strict"

import { importFresh } from "./helpers/import-fresh.js"

function basicAuth(username, password) {
  return `Basic ${Buffer.from(`${username}:${password}`, "utf-8").toString("base64")}`
}

function gistResponse(state) {
  return {
    ok: true,
    status: 200,
    async json() {
      return {
        files: {
          "state.json": {
            content: JSON.stringify(state),
          },
        },
      }
    },
    async text() {
      return JSON.stringify(state)
    },
  }
}

function actionsResponse() {
  return {
    ok: true,
    status: 200,
    async json() {
      return {
        workflow_runs: [
          {
            id: 123,
            status: "completed",
            conclusion: "success",
            created_at: "2026-05-20T10:00:00Z",
            updated_at: "2026-05-20T10:05:00Z",
            event: "schedule",
            html_url: "https://github.com/andrewzp/theheat/actions/runs/123",
          },
        ],
      }
    },
    async text() {
      return JSON.stringify({ workflow_runs: [] })
    },
  }
}

function setupEnv() {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"
}

test("dashboard API hydrates page data with one state read and one workflow read", async () => {
  setupEnv()
  const state = {
    drafts: [
      { id: "draft_low", status: "pending", score: { total: 20 }, created_at: "2026-05-20T09:00:00Z" },
      { id: "draft_high", status: "pending", score: { total: 80 }, created_at: "2026-05-20T08:00:00Z", tweet_id: "tweet_123" },
      { id: "draft_posted", status: "posted", score: { total: 99 }, created_at: "2026-05-20T07:00:00Z" },
    ],
    suppressions: [
      { id: "s1", source: "triage", stage: "triage", ts: "2026-05-20T09:00:00Z" },
      { id: "s2", source: "writer", stage: "writer", ts: "2026-05-20T08:00:00Z" },
    ],
    source_health: {
      ghcn: {
        success: 1,
        degraded: 0,
        failed: 0,
        skipped: 0,
        total_observed: 100,
        total_drafted: 1,
        avg_duration_ms: 1200,
        runs: [{ ts: "2026-05-20T09:00:00Z", status: "success", observed: 100, drafted: 1 }],
      },
    },
    run_history: [],
    posted_events: [],
    errors: [],
    last_hot10: { date: null, cities: [] },
    streaks: {},
    daily_tweet_count: {},
    pending_confirmations: [],
  }

  const fetchCalls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    const href = String(url)
    fetchCalls.push(href)
    if (href.includes("/actions/runs")) return actionsResponse()
    return gistResponse(state)
  }

  try {
    const { GET } = await importFresh("app/api/dashboard/route.js")
    const response = await GET(
      new Request("http://localhost/api/dashboard?limit=1&source=triage", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.stateBackend, "gist")
    assert.deepEqual(payload.drafts.drafts.map((d) => d.id), ["draft_high", "draft_low"])
    assert.equal(payload.drafts.drafts[0].tweet_id, "tweet_123")
    assert.deepEqual(payload.suppressions.suppressions.map((s) => s.id), ["s1"])
    assert.equal(payload.suppressions.stats.total, 1)
    assert.equal(payload.sourceHealth.sources[0].source, "ghcn")
    assert.equal(payload.sourceHealth.sources[0].avg_duration_ms, 1200)
    assert.equal(payload.config.writer_model, "claude-sonnet-4-6")
    assert.equal(payload.runs[0].id, 123)
    assert.equal(fetchCalls.filter((href) => href.includes("/gists/")).length, 1)
    assert.equal(fetchCalls.filter((href) => href.includes("/actions/runs")).length, 1)
  } finally {
    globalThis.fetch = originalFetch
  }
})
