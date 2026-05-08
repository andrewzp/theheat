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

const SUPPRESSION_STATE = {
  drafts: [],
  posted_events: [],
  run_history: [],
  errors: [],
  last_hot10: { date: null, cities: [] },
  streaks: {},
  daily_tweet_count: {},
  pending_confirmations: [],
  suppressions: [
    {
      id: "s1",
      ts: new Date().toISOString(),
      source: "noaa_alerts",
      stage: "score_gate",
      score_total: 48,
      threshold: 60,
      summary: "Heat advisory below threshold",
    },
    {
      id: "s2",
      ts: new Date().toISOString(),
      source: "era5",
      stage: "writer",
      score_total: 65,
      threshold: 60,
      summary: "Writer rejected draft",
    },
    {
      id: "s3",
      ts: new Date().toISOString(),
      source: "noaa_alerts",
      stage: "score_gate",
      score_total: 40,
      threshold: 60,
      summary: "Flash flood watch — score too low",
    },
    {
      id: "s4",
      ts: new Date().toISOString(),
      source: "ecmwf",
      // no stage field — legacy record
      score_total: 55,
      threshold: 60,
      summary: "Legacy suppression without stage",
    },
    {
      id: "s5",
      ts: new Date().toISOString(),
      source: "era5",
      stage: "city_cooldown",
      score_total: 72,
      threshold: 60,
      summary: "City on cooldown",
    },
  ],
}

test("suppressions API returns stage_counts aggregated by stage field", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(SUPPRESSION_STATE)

  try {
    const { GET } = await importFresh("app/api/suppressions/route.js")
    const response = await GET(
      new Request("http://localhost/api/suppressions?limit=50", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.ok(payload.stats, "stats object should be present")

    const stageCounts = payload.stats.stage_counts
    assert.ok(stageCounts, "stage_counts should be present in stats")
    assert.equal(stageCounts.score_gate, 2, "score_gate should have count 2")
    assert.equal(stageCounts.writer, 1, "writer should have count 1")
    assert.equal(stageCounts.city_cooldown, 1, "city_cooldown should have count 1")
    assert.equal(stageCounts.unknown, 1, "records with no stage should count as unknown")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("suppressions API returns top_stage for the most frequent kill stage", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(SUPPRESSION_STATE)

  try {
    const { GET } = await importFresh("app/api/suppressions/route.js")
    const response = await GET(
      new Request("http://localhost/api/suppressions?limit=50", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    assert.equal(payload.stats.top_stage, "score_gate", "top_stage should be score_gate (2 hits)")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("suppressions API stage_counts still present for empty suppressions list", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"

  const emptyState = { ...SUPPRESSION_STATE, suppressions: [] }
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(emptyState)

  try {
    const { GET } = await importFresh("app/api/suppressions/route.js")
    const response = await GET(
      new Request("http://localhost/api/suppressions?limit=50", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    const payload = await response.json()
    assert.deepEqual(payload.stats.stage_counts, {}, "stage_counts should be empty object when no suppressions")
    assert.equal(payload.stats.top_stage, null, "top_stage should be null when no suppressions")
  } finally {
    globalThis.fetch = originalFetch
  }
})
