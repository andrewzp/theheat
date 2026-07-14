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

function buildUsageState() {
  // Built at call time (codex P2: a module-init prefix can straddle a UTC
  // month rollover against the route's own clock).
  const monthPrefix = new Date().toISOString().slice(0, 8)
  return {
    monthPrefix,
    state: {
      llm_usage: {
        [`${monthPrefix}01`]: {
          "writer|claude-sonnet-4-6": {
            calls: 12, in: 24000, cached_in: 150000, cache_write: 15000, out: 2400, usd: 0.35,
          },
        },
        [`${monthPrefix}02`]: {
          "writer|claude-sonnet-4-6": {
            calls: 8, in: 16000, cached_in: 90000, cache_write: 15000, out: 1600, usd: 0.25,
          },
        },
        "2020-01-01": {
          "writer|old": { calls: 1, in: 1, cached_in: 0, cache_write: 0, out: 1, usd: 42.0 },
        },
        // Junk keys (codex P2): shape-invalid AND shape-valid non-dates must
        // neither pollute the MTD sum nor steal 14-day-slice slots.
        [`${monthPrefix}zz`]: { "writer|junk": { usd: 99.0 } },
        "9999-99-00": { "writer|junk": { usd: 99.0 } },
      },
    },
  }
}

test("usage API sums the current month, rejects junk keys, and projects deterministically", async () => {
  setEnv()
  const { monthPrefix, state } = buildUsageState()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(state)
  try {
    const { GET } = await importFresh("app/api/usage/route.js")
    const response = await GET(
      new Request("http://localhost/api/usage", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    // Only this month's VALID days count: 0.35 + 0.25 — neither the 2020 day
    // ($42) nor the two junk keys ($99 each).
    assert.ok(Math.abs(payload.mtd_usd - 0.6) < 1e-9)
    assert.equal(payload.budget_usd, 14.0)
    // Projection is exact against the clock the route echoes back.
    const expected = (0.6 / payload.as_of_day) * payload.days_in_month
    assert.ok(Math.abs(payload.projected_usd - Number(expected.toFixed(2))) < 1e-9)
    // Junk keys never reach the recent series.
    assert.ok(payload.recent_days.every((d) => d.day !== "9999-99-00" && !d.day.endsWith("zz")))
    const recent = payload.recent_days.find((d) => d.day === `${monthPrefix}02`)
    assert.ok(recent)
    assert.ok(Math.abs(recent.usd - 0.25) < 1e-9)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("usage API requires auth", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(buildUsageState().state)
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
