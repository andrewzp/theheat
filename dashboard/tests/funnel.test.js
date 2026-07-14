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

function runWithFunnel(id, isoTs, funnel, slate) {
  return {
    id,
    mode: "alerts",
    status: "success",
    started_at: isoTs,
    ended_at: isoTs,
    sources: [],
    funnel,
    shadow_slate: slate || [],
  }
}

const NOW = new Date()
const recentTs = NOW.toISOString()
const oldTs = new Date(NOW.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString()

const FUNNEL_STATE = {
  drafts: [],
  posted_events: [],
  errors: [],
  last_hot10: { date: null, cities: [] },
  streaks: {},
  daily_tweet_count: {},
  pending_confirmations: [],
  suppressions: [],
  run_history: [
    runWithFunnel(
      "r_recent_1",
      recentTs,
      {
        observed: 100, promoted: 10, triaged_in: 5, triaged_out: 3,
        writer_attempted: 3, drafted: 1,
        passes: { writer: 3, fact_check: 3, critic: 1 },
        kills: { critic: 2, city_cooldown: 1 },
      },
      [{ event_id: "e1", type: "fire", score_total: 90, terminal_stage: "critic", summary: "Mali" }],
    ),
    runWithFunnel(
      "r_recent_2",
      recentTs,
      {
        observed: 200, promoted: 20, triaged_in: 6, triaged_out: 4,
        writer_attempted: 4, drafted: 2,
        passes: { writer: 4, fact_check: 4, critic: 2 },
        kills: { critic: 2, writer: 1 },
      },
      [],
    ),
    // older than 7d — must be excluded from the rollup
    runWithFunnel(
      "r_old",
      oldTs,
      {
        observed: 9999, promoted: 9999, triaged_in: 99, triaged_out: 99,
        writer_attempted: 99, drafted: 99,
        passes: { writer: 99, fact_check: 99, critic: 99 },
        kills: { critic: 99 },
      },
      [],
    ),
    // a run with no funnel (telemetry was off) — must not crash
    { id: "r_nofunnel", mode: "alerts", status: "success", started_at: recentTs, ended_at: recentTs, sources: [] },
  ],
}

function setEnv() {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"
}

test("funnel API rolls up the last 7 days from run_history only", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(FUNNEL_STATE)
  try {
    const { GET } = await importFresh("app/api/funnel/route.js")
    const response = await GET(
      new Request("http://localhost/api/funnel", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.window_days, 7)
    // only the 2 recent funnels summed; old one excluded
    assert.equal(payload.funnel.observed, 300)
    assert.equal(payload.funnel.drafted, 3)
    assert.equal(payload.funnel.passes.critic, 3)
    assert.equal(payload.funnel.kills.critic, 4)
    assert.equal(payload.funnel.kills.writer, 1)
    assert.equal(payload.runs_counted, 2)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("funnel API computes critic_pass_rate = passes/(passes+kills)", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(FUNNEL_STATE)
  try {
    const { GET } = await importFresh("app/api/funnel/route.js")
    const response = await GET(
      new Request("http://localhost/api/funnel", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    const payload = await response.json()
    // critic: 3 passes, 4 kills => 3/7
    assert.ok(Math.abs(payload.rates.critic_pass_rate - 3 / 7) < 1e-9)
    assert.equal(payload.rates.stages.critic.attempts, 7)
    // draft_yield = 3 drafted / 7 writer_attempted
    assert.ok(Math.abs(payload.rates.draft_yield - 3 / 7) < 1e-9)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("funnel API surfaces recent shadow slates", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(FUNNEL_STATE)
  try {
    const { GET } = await importFresh("app/api/funnel/route.js")
    const response = await GET(
      new Request("http://localhost/api/funnel", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    const payload = await response.json()
    const withSlate = payload.recent_slates.find((r) => r.slate.length > 0)
    assert.ok(withSlate, "a recent run with a non-empty slate should be present")
    assert.equal(withSlate.slate[0].event_id, "e1")
    assert.equal(withSlate.slate[0].terminal_stage, "critic")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("funnel API keeps billing skips out of triage_cut without hiding real cuts", async () => {
  setEnv()
  // The producer counts billing-skipped candidates in triaged_out at bump
  // time, so billing_aborted is informational and never subtracted here.
  // Scenario (codex r4): 5 in, 3 survivors selected (2 REAL editorial cuts),
  // billing aborted 2 survivors — the 2 editorial cuts must stay visible.
  const billingState = {
    ...FUNNEL_STATE,
    run_history: [
      runWithFunnel(
        "r_billing",
        recentTs,
        {
          observed: 50, promoted: 5, triaged_in: 5, triaged_out: 3,
          billing_aborted: 2, writer_attempted: 1, drafted: 0,
          passes: {},
          kills: { budget_exhausted: 1, billing_cycle_abort: 1 },
        },
        [],
      ),
    ],
  }
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(billingState)
  try {
    const { GET } = await importFresh("app/api/funnel/route.js")
    const response = await GET(
      new Request("http://localhost/api/funnel", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    const payload = await response.json()
    assert.equal(payload.funnel.billing_aborted, 2)
    assert.equal(payload.rates.billing_aborted, 2)
    // The 2 editorial cuts survive; the 2 billing skips (inside triaged_out)
    // never inflate them.
    assert.equal(payload.rates.triage_cut, 2)
    assert.ok(Math.abs(payload.rates.triage_cap_rate - 2 / 5) < 1e-9)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("funnel API requires auth", async () => {
  setEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(FUNNEL_STATE)
  try {
    const { GET } = await importFresh("app/api/funnel/route.js")
    const response = await GET(new Request("http://localhost/api/funnel"))
    assert.equal(response.status, 401)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("funnel API is zero-safe on empty run_history", async () => {
  setEnv()
  const emptyState = { ...FUNNEL_STATE, run_history: [] }
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse(emptyState)
  try {
    const { GET } = await importFresh("app/api/funnel/route.js")
    const response = await GET(
      new Request("http://localhost/api/funnel", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.funnel.observed, 0)
    assert.equal(payload.rates.critic_pass_rate, null)
    assert.equal(payload.runs_counted, 0)
  } finally {
    globalThis.fetch = originalFetch
  }
})
