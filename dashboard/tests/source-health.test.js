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

const NOW = "2026-05-09T05:00:00Z"
const HOUR_AGO = "2026-05-09T04:00:00Z"
const TWO_HOURS_AGO = "2026-05-09T03:00:00Z"

const RUN_HISTORY_STATE = {
  drafts: [],
  posted_events: [],
  errors: [],
  last_hot10: { date: null, cities: [] },
  streaks: {},
  daily_tweet_count: {},
  pending_confirmations: [],
  suppressions: [],
  // run_history is newest-first per src/state.py:finalize_run
  run_history: [
    {
      id: "run_alerts_1",
      mode: "alerts",
      started_at: NOW,
      ended_at: NOW,
      sources: [
        { source: "nws_alerts", status: "success", observed: 10, promoted: 1, drafted: 1 },
        { source: "ocean", status: "failed", error: "503 Service Unavailable" },
        { source: "drought", status: "skipped", note: "Friday only" },
      ],
    },
    {
      id: "run_alerts_2",
      mode: "alerts",
      started_at: HOUR_AGO,
      ended_at: HOUR_AGO,
      sources: [
        { source: "nws_alerts", status: "success", observed: 12, promoted: 0, drafted: 0 },
        { source: "ocean", status: "failed", error: "timeout" },
      ],
    },
    {
      id: "run_alerts_3",
      mode: "alerts",
      started_at: TWO_HOURS_AGO,
      ended_at: TWO_HOURS_AGO,
      sources: [
        { source: "nws_alerts", status: "success", observed: 8, promoted: 0, drafted: 0 },
        { source: "ocean", status: "success", observed: 5, promoted: 0, drafted: 0 },
      ],
    },
  ],
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

test("source-health API aggregates per-source success/failure across run_history", async () => {
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(RUN_HISTORY_STATE)

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.ok(Array.isArray(payload.sources), "sources should be an array")

    const byKey = Object.fromEntries(payload.sources.map((s) => [s.source, s]))

    // nws_alerts: 3 successes / 3 runs → healthy
    assert.equal(byKey.nws_alerts.runs, 3)
    assert.equal(byKey.nws_alerts.successes, 3)
    assert.equal(byKey.nws_alerts.failures, 0)
    assert.equal(byKey.nws_alerts.success_rate, 1)
    assert.equal(byKey.nws_alerts.health, "healthy")
    assert.equal(byKey.nws_alerts.total_observed, 30)
    assert.equal(byKey.nws_alerts.total_drafted, 1)

    // ocean: 1 success + 2 failures over 3 runs → success_rate ~0.33, last run failed → unhealthy
    assert.equal(byKey.ocean.runs, 3)
    assert.equal(byKey.ocean.failures, 2)
    assert.equal(byKey.ocean.last_run_status, "failed")
    assert.equal(byKey.ocean.health, "unhealthy")
    assert.equal(byKey.ocean.last_error, "503 Service Unavailable")
    assert.equal(byKey.ocean.last_error_at, NOW)

    // drought: 1 skipped of 1 → success_rate 0, last_run_status='skipped', NOT classified as failed
    assert.equal(byKey.drought.skipped, 1)
    assert.equal(byKey.drought.last_run_status, "skipped")
    assert.notEqual(byKey.drought.health, "unhealthy")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("source-health stats counts unhealthy and degraded sources", async () => {
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(RUN_HISTORY_STATE)

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    assert.equal(payload.stats.runs_analyzed, 3)
    assert.equal(payload.stats.unhealthy_count, 1, "ocean should be unhealthy")
    assert.equal(payload.stats.healthy_count, 1, "nws_alerts should be healthy")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("source-health treats degraded source runs as active problems", async () => {
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    gistResponse({
      ...RUN_HISTORY_STATE,
      run_history: [
        {
          id: "run_degraded_1",
          mode: "alerts",
          started_at: NOW,
          ended_at: NOW,
          sources: [
            {
              source: "open_meteo_extreme_signals",
              status: "degraded",
              observed: 11907,
              promoted: 4,
              drafted: 0,
              note: "provider:ghcn diff_dates_missing:4",
            },
            {
              source: "auto_publish_due",
              status: "partial_failure",
              observed: 3,
              promoted: 3,
              drafted: 1,
              error: "draft_a: rate limited",
            },
          ],
        },
      ],
    })

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    const byKey = Object.fromEntries(payload.sources.map((s) => [s.source, s]))
    const source = byKey.open_meteo_extreme_signals
    assert.equal(source.degraded, 1)
    assert.equal(source.health, "degraded")
    assert.equal(source.success_rate, 0)
    assert.equal(byKey.auto_publish_due.partial_failures, 1)
    assert.notEqual(byKey.auto_publish_due.health, "idle")
    assert.equal(payload.stats.degraded_count, 1)
    assert.equal(payload.stats.idle_count, 0)

    // Codex PR #70: last_error must surface for problem statuses beyond
    // just "failed", otherwise the dashboard hides actionable error text
    // for partial_failure / degraded runs.
    assert.equal(byKey.auto_publish_due.last_error, "draft_a: rate limited")
    assert.equal(byKey.auto_publish_due.last_error_at, NOW)
    assert.equal(source.last_error, "provider:ghcn diff_dates_missing:4")
    assert.equal(source.last_error_at, NOW)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("source-health last_error stays null when only success/skipped runs exist", async () => {
  // Negative case: a healthy source should NOT get a phantom last_error
  // populated from a note on a successful run.
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    gistResponse({
      ...RUN_HISTORY_STATE,
      run_history: [
        {
          id: "run_healthy_1",
          mode: "alerts",
          started_at: NOW,
          ended_at: NOW,
          sources: [
            {
              source: "nws_alerts",
              status: "success",
              observed: 10,
              promoted: 1,
              drafted: 1,
              note: "informational success note that must NOT surface as error",
            },
          ],
        },
      ],
    })

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    const nws = payload.sources.find((s) => s.source === "nws_alerts")
    assert.equal(nws.health, "healthy")
    assert.equal(nws.last_error, null, "healthy run note must not populate last_error")
    assert.equal(nws.last_error_at, null)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("source-health sorts worst-first so problem sources surface", async () => {
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(RUN_HISTORY_STATE)

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    // ocean (unhealthy) must come before nws_alerts (healthy)
    const oceanIdx = payload.sources.findIndex((s) => s.source === "ocean")
    const nwsIdx = payload.sources.findIndex((s) => s.source === "nws_alerts")
    assert.ok(oceanIdx < nwsIdx, "unhealthy ocean should sort before healthy nws_alerts")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("source-health returns empty payload when no run_history", async () => {
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    gistResponse({
      ...RUN_HISTORY_STATE,
      run_history: [],
    })

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    assert.equal(response.status, 200)
    assert.equal(payload.sources.length, 0)
    assert.equal(payload.stats.runs_analyzed, 0)
  } finally {
    globalThis.fetch = originalFetch
  }
})
