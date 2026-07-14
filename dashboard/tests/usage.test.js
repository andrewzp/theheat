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
      return { files: { "state.json": { content: JSON.stringify(state) } } }
    },
    async text() {
      return JSON.stringify(state)
    },
  }
}

function setEnv() {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"
  delete process.env.THEHEAT_MONTHLY_BUDGET_USD
}

const monthPrefix = new Date().toISOString().slice(0, 8)
const day1 = `${monthPrefix}01`
const day2 = `${monthPrefix}02`

const USAGE_STATE = {
  llm_usage: {
    [day1]: {
      "writer|claude-sonnet-4-6": {
        calls: 12, in: 24000, cached_in: 150000, cache_write: 15000, out: 2400, usd: 0.35,
      },
    },
    [day2]: {
      "writer|claude-sonnet-4-6": {
        calls: 8, in: 16000, cached_in: 90000, cache_write: 15000, out: 1600, usd: 0.25,
      },
    },
    "2020-01-01": {
      "writer|old": { calls: 1, in: 1, cached_in: 0, cache_write: 0, out: 1, usd: 42.0 },
    },
  },
}

test("usage API sums the current month and projects", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(USAGE_STATE)
  try {
    const { GET } = await importFresh("app/api/usage/route.js")
    const response = await GET(
      new Request("http://localhost/api/usage", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    // Only this month's days count: 0.35 + 0.25 — the 2020 day ($42) must not.
    assert.ok(Math.abs(payload.mtd_usd - 0.6) < 1e-9)
    assert.equal(payload.budget_usd, 14.0)
    assert.ok(payload.projected_usd > 0)
    assert.ok(payload.recent_days.length >= 2)
    const recent = payload.recent_days.find((d) => d.day === day2)
    assert.ok(recent)
    assert.ok(Math.abs(recent.usd - 0.25) < 1e-9)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("usage API requires auth", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(USAGE_STATE)
  try {
    const { GET } = await importFresh("app/api/usage/route.js")
    const response = await GET(new Request("http://localhost/api/usage"))
    assert.equal(response.status, 401)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("usage API is zero-safe on missing ledger", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse({})
  try {
    const { GET } = await importFresh("app/api/usage/route.js")
    const response = await GET(
      new Request("http://localhost/api/usage", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.mtd_usd, 0)
    assert.deepEqual(payload.recent_days, [])
  } finally {
    globalThis.fetch = originalFetch
  }
})
