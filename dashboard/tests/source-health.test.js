import test from "node:test"
import assert from "node:assert/strict"

import { importFresh } from "./helpers/import-fresh.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

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
const EARTHDATA_403_ERROR = "Ice mass fetch failed: 403 Client Error: Forbidden for url: https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/..."
const GENERIC_GOV_403_ERROR = "403 Client Error: Forbidden for url: https://www.metoc.navy.mil/jtwc/products/..."

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
        { source: "nws_alerts", status: "success", observed: 10, promoted: 1, drafted: 1, duration_ms: 1000 },
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
        { source: "nws_alerts", status: "success", observed: 12, promoted: 0, drafted: 0, duration_ms: 500 },
        { source: "ocean", status: "failed", error: "timeout" },
      ],
    },
    {
      id: "run_alerts_3",
      mode: "alerts",
      started_at: TWO_HOURS_AGO,
      ended_at: TWO_HOURS_AGO,
      sources: [
        { source: "nws_alerts", status: "success", observed: 8, promoted: 0, drafted: 0, duration_ms: 1500 },
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
    assert.equal(byKey.nws_alerts.total_duration_ms, 3000)
    assert.equal(byKey.nws_alerts.avg_duration_ms, 1000)
    assert.equal(byKey.nws_alerts.max_duration_ms, 1500)

    // ocean: 1 success + 2 failures over 3 runs, last error 503 → upstream → external
    assert.equal(byKey.ocean.runs, 3)
    assert.equal(byKey.ocean.failures, 2)
    assert.equal(byKey.ocean.last_run_status, "failed")
    assert.equal(byKey.ocean.health, "external")
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

test("source-health API prefers durable source_health metrics over capped run_history", async () => {
  setupEnv()
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    gistResponse({
      ...RUN_HISTORY_STATE,
      run_history: [],
      source_health: {
        ghcn: {
          success: 1,
          degraded: 1,
          failed: 0,
          skipped: 0,
          total_duration_ms: 3000,
          avg_duration_ms: 1500,
          max_duration_ms: 2000,
          total_observed: 150,
          total_promoted: 6,
          total_triaged_in: 2,
          total_triaged_out: 4,
          total_writer_attempted: 1,
          total_drafted: 1,
          last_success_ts: "2026-05-09T03:00:00Z",
          last_error: "late diff",
          last_error_ts: "2026-05-09T04:00:00Z",
          runs: [
            { ts: "2026-05-09T03:00:00Z", status: "success", duration_ms: 1000, observed: 100 },
            { ts: "2026-05-09T04:00:00Z", status: "degraded", error: "late diff", duration_ms: 2000, observed: 50 },
          ],
        },
      },
    })

  try {
    const { GET } = await importFresh("app/api/source-health/route.js")
    const response = await GET(
      new Request("http://localhost/api/source-health", {
        headers: { authorization: basicAuth("reviewer", "secret-pass") },
      })
    )

    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.stats.runs_analyzed, 2)
    assert.equal(payload.sources.length, 1)
    assert.equal(payload.sources[0].source, "ghcn")
    assert.equal(payload.sources[0].total_observed, 150)
    assert.equal(payload.sources[0].total_writer_attempted, 1)
    assert.equal(payload.sources[0].avg_duration_ms, 1500)
    assert.equal(payload.sources[0].last_run_status, "degraded")
    assert.equal(payload.sources[0].last_error, "late diff")
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
    assert.equal(payload.stats.unhealthy_count, 0, "ocean's 503 is upstream → external, not unhealthy")
    assert.equal(payload.stats.external_count, 1, "ocean should be external")
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

test("source-health falls back to the latest problem row with a diagnostic", async () => {
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () =>
    gistResponse({
      run_history: [
        {
          id: "run_new",
          started_at: "2026-05-14T12:00:00Z",
          sources: [{ source: "ocean_sst", status: "degraded", note: "" }],
        },
        {
          id: "run_old",
          started_at: "2026-05-14T08:00:00Z",
          sources: [{ source: "ocean_sst", status: "failed", error: "provider timeout" }],
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
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.sources[0].last_error, "provider timeout")
    assert.equal(payload.sources[0].last_error_at, "2026-05-14T08:00:00Z")
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

// ---------------------------------------------------------------------------
// Direct lib tests: success-rate fraction denominator + recency-aware health.
// These exercise buildSourceHealthPayload against the durable source_health
// path (the one fed by src/state.py's 7-day rolling window).
// ---------------------------------------------------------------------------

function skip(ts) {
  return { ts, status: "skipped" }
}
function ok(ts) {
  return { ts, status: "success" }
}
function fail(ts) {
  return { ts, status: "failed", error: "boom" }
}
function degraded(ts) {
  return { ts, status: "degraded", error: "partial data" }
}

function failedSourceWithError(lastError) {
  return buildSourceHealthPayload({
    source_health: {
      ice_mass_greenland: {
        success: 0,
        failed: 3,
        degraded: 0,
        skipped: 0,
        last_error: lastError,
        runs: [
          fail("2026-05-27T00:00:00Z"),
          fail("2026-05-28T00:00:00Z"),
          fail("2026-05-29T00:00:00Z"),
        ],
      },
    },
  }).sources[0]
}

test("success-rate fraction uses active runs (skips excluded), not total runs", () => {
  // ice_mass-style: 1 success, 2 failed, 7 skipped over 10 runs.
  // The displayed fraction denominator must be `active` (3) — matching the
  // success_rate % — NOT `runs` (10), which renders a nonsensical "33% (1/10)".
  const runs = [
    skip("2026-05-20T00:00:00Z"),
    skip("2026-05-21T00:00:00Z"),
    skip("2026-05-22T00:00:00Z"),
    skip("2026-05-23T00:00:00Z"),
    skip("2026-05-24T00:00:00Z"),
    skip("2026-05-25T00:00:00Z"),
    skip("2026-05-26T00:00:00Z"),
    ok("2026-05-27T00:00:00Z"),
    fail("2026-05-28T00:00:00Z"),
    fail("2026-05-29T00:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      ice_mass_greenland: { success: 1, failed: 2, degraded: 0, skipped: 7, runs },
    },
  })
  const row = sources.find((s) => s.source === "ice_mass_greenland")
  assert.equal(row.active, 3, "active excludes the 7 skips")
  assert.equal(row.runs, 10, "runs is the full count including skips")
  assert.equal(row.skipped, 7)
  assert.equal(Math.round(row.success_rate * 100), 33)
  assert.equal(
    row.successes / row.active,
    row.success_rate,
    "fraction numerator/denominator must equal the displayed percent"
  )
})

test("classifies earthdata 403 as our_bug", () => {
  assert.equal(failedSourceWithError(EARTHDATA_403_ERROR).health, "unhealthy")
})

test("classifies generic gov 403 as upstream", () => {
  assert.equal(failedSourceWithError(GENERIC_GOV_403_ERROR).health, "external")
})

test("a cadence source whose recent runs are all skips is idle, not red on stale history", () => {
  // The recent RUN window (last 5) is all cadence skips → the source isn't
  // attempting right now, so it's idle — never judged "failing" on stale attempts
  // from days ago. (Matches the sentinel; fixes ice_mass showing red while idle.)
  const runs = [
    fail("2026-05-25T00:00:00Z"),
    ok("2026-05-26T00:00:00Z"),
    skip("2026-05-27T00:00:00Z"),
    skip("2026-05-28T00:00:00Z"),
    skip("2026-05-29T00:00:00Z"),
    skip("2026-05-30T00:00:00Z"),
    skip("2026-05-31T00:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      cadence_source: { success: 1, failed: 1, degraded: 0, skipped: 5, runs },
    },
  })
  const row = sources.find((s) => s.source === "cadence_source")
  assert.equal(row.last_run_status, "skipped")
  assert.equal(row.recent_active, 0)
  assert.equal(row.recent_successes, 0)
  assert.equal(row.health, "idle", "idle between cadence runs, not red on stale attempts")
})

test("a recovering source (recent runs all succeed) is healthy, not red", () => {
  // gpm_imerg-style: terrible 7-day cumulative (5 success / 28 failed) but the
  // most recent runs all succeeded. Recency wins → it has recovered, so healthy.
  const oldFailures = Array.from({ length: 28 }, (_, i) =>
    fail(`2026-05-31T${String(i % 24).padStart(2, "0")}:30:00Z`)
  )
  const recentSuccesses = Array.from({ length: 5 }, (_, i) =>
    ok(`2026-06-01T${String(18 + i).padStart(2, "0")}:00:00Z`)
  )
  const { sources } = buildSourceHealthPayload({
    source_health: {
      gpm_imerg: {
        success: 5,
        failed: 28,
        degraded: 0,
        skipped: 0,
        runs: [...oldFailures, ...recentSuccesses],
        last_error: "HTTP 503",
      },
    },
  })
  const row = sources.find((s) => s.source === "gpm_imerg")
  assert.equal(row.last_run_status, "success")
  assert.equal(row.health, "healthy", "recent window all clean → recovered, not red on stale failures")
})

test("old degraded rows do not keep a recovered durable source yellow", () => {
  // A single degraded row in the 7-day cumulative counter should not override
  // five clean recent attempts. The sentinel would call this healthy; the
  // dashboard must tell the same story.
  const runs = [
    { ts: "2026-06-01T00:00:00Z", status: "degraded", error: "old warning" },
    ok("2026-06-02T00:00:00Z"),
    ok("2026-06-03T00:00:00Z"),
    ok("2026-06-04T00:00:00Z"),
    ok("2026-06-05T00:00:00Z"),
    ok("2026-06-06T00:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      river_gauges: {
        success: 5,
        failed: 0,
        degraded: 1,
        skipped: 0,
        last_error: "old warning",
        runs,
      },
    },
  })
  const row = sources.find((s) => s.source === "river_gauges")
  assert.equal(row.recent_successes, 5)
  assert.equal(row.recent_active, 5)
  assert.equal(row.health, "healthy")
})

test("recovered healthy source clears stale last_error fields", () => {
  const runs = [
    { ts: "2026-06-01T00:00:00Z", status: "degraded", error: "old warning" },
    ok("2026-06-02T00:00:00Z"),
    ok("2026-06-03T00:00:00Z"),
    ok("2026-06-04T00:00:00Z"),
    ok("2026-06-05T00:00:00Z"),
    ok("2026-06-06T00:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      air_quality: {
        success: 5,
        failed: 0,
        degraded: 1,
        skipped: 0,
        last_error: "old warning",
        last_error_ts: "2026-06-01T00:00:00Z",
        runs,
      },
    },
  })
  const row = sources.find((s) => s.source === "air_quality")
  assert.equal(row.health, "healthy")
  assert.equal(row.last_error, null)
  assert.equal(row.last_error_at, null)
})

test("latest success hides stale upstream diagnostic while source is recovering", () => {
  const runs = [
    ok("2026-06-01T00:00:00Z"),
    fail("2026-06-01T01:00:00Z"),
    ok("2026-06-01T02:00:00Z"),
    ok("2026-06-01T03:00:00Z"),
    ok("2026-06-01T04:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      copernicus_ems: {
        success: 4,
        failed: 1,
        degraded: 0,
        skipped: 0,
        last_error: "503 Server Error: Service Temporarily Unavailable",
        last_error_ts: "2026-06-01T01:00:00Z",
        runs,
      },
    },
  })
  const row = sources.find((s) => s.source === "copernicus_ems")
  assert.equal(row.last_run_status, "success")
  assert.equal(row.health, "external")
  assert.equal(row.last_error, null)
  assert.equal(row.last_error_at, null)
})

test("a source degraded every cycle is degraded, not unhealthy (sync with sentinel #201)", () => {
  // air_quality loses a rate-limited tail chunk every run → `degraded` each
  // cycle, never a hard `failed`. With a 0% clean-success rate it must still
  // read as `degraded` (it IS producing data), NOT `unhealthy`. The Python
  // sentinel mirrors this — a consistently-degraded source is `degraded`, never
  // `failing` — so neither surface false-alarms (#201). Locks the cross-impl invariant.
  const runs = Array.from({ length: 5 }, (_, i) =>
    degraded(`2026-06-09T${String(3 + i).padStart(2, "0")}:00:00Z`)
  )
  const { sources } = buildSourceHealthPayload({
    source_health: {
      air_quality: {
        success: 0,
        failed: 0,
        degraded: 5,
        skipped: 0,
        last_error: "50 air-quality city fetches failed",
        runs,
      },
    },
  })
  const row = sources.find((s) => s.source === "air_quality")
  assert.equal(row.health, "degraded")
})

test("last run failed with an upstream 503 → external, not unhealthy", () => {
  // Recovering (3 of the last 5 succeeded) AND the failures are upstream (503),
  // so it's external (amber, NASA/gov), never our red.
  const oldFailures = Array.from({ length: 25 }, (_, i) =>
    fail(`2026-05-31T${String(i % 24).padStart(2, "0")}:30:00Z`)
  )
  const recent = [
    ok("2026-06-01T18:00:00Z"),
    ok("2026-06-01T19:00:00Z"),
    ok("2026-06-01T20:00:00Z"),
    fail("2026-06-01T21:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      recov: { success: 3, failed: 26, degraded: 0, skipped: 0, runs: [...oldFailures, ...recent], last_error: "503" },
    },
  })
  const row = sources.find((s) => s.source === "recov")
  assert.equal(row.last_run_status, "failed")
  assert.equal(row.health, "external", "upstream 503 → external, not our red")
})

test("last run succeeded but recent window mostly failing → unhealthy (early degradation)", () => {
  // Source had a great cumulative history but has just started failing; the
  // last run happened to succeed. Recency should catch the degradation early.
  const oldSuccesses = Array.from({ length: 25 }, (_, i) =>
    ok(`2026-05-30T${String(i % 24).padStart(2, "0")}:30:00Z`)
  )
  const recent = [
    fail("2026-06-01T17:00:00Z"),
    fail("2026-06-01T18:00:00Z"),
    fail("2026-06-01T19:00:00Z"),
    ok("2026-06-01T20:00:00Z"),
  ]
  const { sources } = buildSourceHealthPayload({
    source_health: {
      degrading: { success: 26, failed: 3, degraded: 0, skipped: 0, runs: [...oldSuccesses, ...recent], last_error: "newly broken" },
    },
  })
  const row = sources.find((s) => s.source === "degrading")
  assert.equal(row.last_run_status, "success")
  assert.equal(row.health, "unhealthy", "3 of the last 4 active runs failed → currently broken")
})

test("same failure rate: upstream cause → external (amber), our cause → unhealthy (red)", () => {
  const failing = Array.from({ length: 5 }, (_, i) =>
    fail(`2026-06-01T${String(i).padStart(2, "0")}:00:00Z`)
  )
  const { sources } = buildSourceHealthPayload({
    source_health: {
      nasa_down: { success: 0, failed: 5, degraded: 0, skipped: 0, runs: failing, last_error: "502 Server Error: Bad Gateway" },
      our_bug: { success: 0, failed: 5, degraded: 0, skipped: 0, runs: failing, last_error: "KeyError: 'temperature'" },
    },
  })
  const byKey = Object.fromEntries(sources.map((s) => [s.source, s]))
  assert.equal(byKey.nasa_down.health, "external", "502 is NASA → external, not our problem")
  assert.equal(byKey.our_bug.health, "unhealthy", "KeyError is our bug → red")
})

test("problem sources include a bounded troubleshooting log with run metrics", () => {
  const { sources } = buildSourceHealthPayload({
    source_health: {
      ocean_sst_anomaly: {
        success: 1,
        failed: 2,
        degraded: 1,
        skipped: 0,
        runs: [
          {
            ts: "2026-06-01T00:00:00Z",
            status: "success",
            duration_ms: 900,
            observed: 78,
          },
          {
            ts: "2026-06-01T01:00:00Z",
            status: "degraded",
            error: "served via noaa_star_nc",
            error_class: "upstream",
            duration_ms: 61200,
            observed: 78,
            promoted: 1,
            drafted: 0,
          },
          {
            ts: "2026-06-01T02:00:00Z",
            status: "failed",
            error: "coastwatch timeout",
            error_class: "upstream",
            duration_ms: 80800,
            observed: 0,
          },
          {
            ts: "2026-06-01T03:00:00Z",
            status: "failed",
            error: "KeyError: 'sea_surface_temperature_anomaly'",
            error_class: "our_bug",
            duration_ms: 1200,
            observed: 0,
          },
        ],
      },
    },
  })

  const row = sources.find((s) => s.source === "ocean_sst_anomaly")

  assert.equal(row.troubleshooting_log.length, 3)
  assert.deepEqual(row.troubleshooting_log[0], {
    at: "2026-06-01T03:00:00Z",
    status: "failed",
    diagnostic: "KeyError: 'sea_surface_temperature_anomaly'",
    error_class: "our_bug",
    duration_ms: 1200,
    observed: 0,
    promoted: 0,
    triaged_in: 0,
    triaged_out: 0,
    writer_attempted: 0,
    drafted: 0,
  })
  assert.equal(row.troubleshooting_log[1].diagnostic, "coastwatch timeout")
  assert.equal(row.troubleshooting_log[2].diagnostic, "served via noaa_star_nc")
})

// R-01: a primary served by a redundancy witness records status "degraded" with
// the diagnostic "served via <leg>". Parity contract — these outcomes must match
// scripts/source_health_sentinel.py (tests/test_source_health_sentinel.py
// TestServedViaBackupLeg) on the same fixture: degraded + served_via leg.
function _backupServedState(lastError, status) {
  return {
    drafts: [],
    source_health: {
      firms: {
        success: status === "success" ? 5 : 0,
        failed: 0,
        degraded: status === "degraded" ? 5 : 0,
        skipped: 0,
        last_error: lastError,
        last_success_ts: "2026-05-09T04:00:00Z",
        runs: Array.from({ length: 5 }, (_, i) => ({
          ts: `2026-05-09T0${i}:00:00Z`,
          status,
        })),
      },
    },
  }
}

test("source-health: degraded when served via backup leg surfaces the leg", () => {
  const payload = buildSourceHealthPayload(_backupServedState("served via noaa_hms", "degraded"))
  const firms = payload.sources.find((s) => s.source === "firms")
  assert.equal(firms.health, "degraded")
  assert.equal(firms.served_via, "noaa_hms")
})

test("source-health: healthy when primary serves (no served_via)", () => {
  const payload = buildSourceHealthPayload(_backupServedState("", "success"))
  const firms = payload.sources.find((s) => s.source === "firms")
  assert.equal(firms.health, "healthy")
  assert.equal(firms.served_via, null)
})

test("source-health: stale served-via cleared once primary recovers to healthy", () => {
  // All-success recent window -> healthy -> the stale "served via" must not show.
  const payload = buildSourceHealthPayload(_backupServedState("served via noaa_hms", "success"))
  const firms = payload.sources.find((s) => s.source === "firms")
  assert.equal(firms.health, "healthy")
  assert.equal(firms.served_via, null)
})

// ---------------------------------------------------------------------------
// coverageWatch: JS mirror of scripts/source_health_sentinel.py coverage_watch
// ---------------------------------------------------------------------------

import { coverageWatch } from "../lib/source-health.js"

const CW_NOW = new Date("2026-06-25T00:00:00Z")
const cwLog = (country, continent, n) => Array.from({ length: n }, (_, i) =>
  ({ cls: "heat", event_id: `${country}-${i}`, country, continent, date: "2026-06-25" }))
const cwAlerts = () => [{ id: "r", mode: "alerts", started_at: "2026-06-25T00:00:00Z" }]

test("coverageWatch flags US-only heat", () => {
  const out = coverageWatch(cwLog("United States", "North America", 22), cwAlerts(), CW_NOW)
  assert.equal(out.length, 1); assert.equal(out[0].kind, "mono_regional"); assert.ok(out[0].share >= 0.85)
})
test("coverageWatch ignores diversified heat", () => {
  assert.deepEqual(coverageWatch([...cwLog("United States", "North America", 8),
    ...cwLog("Spain", "Europe", 7), ...cwLog("India", "Asia", 7)], cwAlerts(), CW_NOW), [])
})
test("coverageWatch reports insufficient_data, not silent", () => {
  assert.equal(coverageWatch(cwLog("United States", "North America", 10), cwAlerts(), CW_NOW)[0].kind, "insufficient_data")
})
test("coverageWatch flags no-data while drafting", () => {
  assert.equal(coverageWatch([], cwAlerts(), CW_NOW)[0].kind, "no_data")
})

// ---------------------------------------------------------------------------
// writerWatch: JS mirror of scripts/source_health_sentinel.py writer_watch
// ---------------------------------------------------------------------------
import { writerWatch } from "../lib/source-health.js"

const WW_NOW = new Date("2026-07-04T12:00:00Z")
const wwSupp = (ts, stage = "budget_exhausted") => ({ id: `supp_${ts}`, ts, stage })
const wwAlerts = () => [{ id: "r", mode: "alerts", started_at: "2026-07-04T00:00:00Z" }]

test("writerWatch flags recent budget_exhausted kills (2026-07-03 incident shape)", () => {
  const out = writerWatch(
    [wwSupp("2026-07-04T10:00:00Z"), wwSupp("2026-07-04T11:00:00Z")], wwAlerts(), WW_NOW)
  assert.deepEqual(out, [{ kind: "budget_exhausted", count: 2, last_ts: "2026-07-04T11:00:00Z" }])
})
test("writerWatch ignores old rows and other stages", () => {
  assert.deepEqual(writerWatch(
    [wwSupp("2026-07-02T10:00:00Z"), wwSupp("2026-07-04T10:00:00Z", "critic")], wwAlerts(), WW_NOW), [])
})
test("writerWatch silent when not drafting", () => {
  assert.deepEqual(writerWatch([wwSupp("2026-07-04T10:00:00Z")], [], WW_NOW), [])
})
test("writerWatch tolerates empty/malformed input", () => {
  assert.deepEqual(writerWatch(null, wwAlerts(), WW_NOW), [])
  assert.deepEqual(writerWatch([null, { ts: null }], wwAlerts(), WW_NOW), [])
})
test("writerWatch skips malformed budget-row timestamps (no lexical false-recent)", () => {
  const junk = [wwSupp("not-a-date"), wwSupp(""), wwSupp("2026-13-99T99:99:99Z"), wwSupp("2026-02-31T00:00:00Z")]
  assert.deepEqual(writerWatch(junk, wwAlerts(), WW_NOW), [])
  const out = writerWatch([...junk, wwSupp("2026-07-04T11:00:00Z")], wwAlerts(), WW_NOW)
  assert.equal(out[0].count, 1)
})
test("buildSourceHealthPayload surfaces writer findings alongside coverage", () => {
  const state = {
    source_health: { open_meteo: { runs: [] } },
    run_history: [{ id: "r", mode: "alerts", started_at: "2026-07-04T00:00:00Z" }],
    suppressions: [wwSupp(new Date(Date.now() - 3600000).toISOString())],
  }
  const payload = buildSourceHealthPayload(state)
  assert.equal(payload.writer.length, 1)
  assert.equal(payload.writer[0].kind, "budget_exhausted")
})

// ---------------------------------------------------------------------------
// queueWatch: JS mirror of scripts/source_health_sentinel.py queue_watch
// ---------------------------------------------------------------------------
import { queueWatch } from "../lib/source-health.js"

const QW_NOW = new Date("2026-07-04T12:00:00Z")
const qwDraft = (created_at, mode = "manual_only", status = "pending", type = "regional_anomaly") =>
  ({ id: `d_${created_at}`, status, type, created_at, approval_policy: { mode } })

test("queueWatch flags aged human-gated drafts with types and oldest age", () => {
  const out = queueWatch(
    [qwDraft("2026-07-03T06:00:00Z", "manual_only", "pending", "all_time_high")], QW_NOW)
  assert.deepEqual(out, [{ kind: "stale_reviews", count: 1, oldest_age_h: 30, types: { all_time_high: 1 } }])
})
test("queueWatch ignores fresh, posted, and auto-owned drafts", () => {
  const autoOwned = { ...qwDraft("2026-07-01T06:00:00Z", "armed_auto"),
    approval_mode: "auto", auto_approve_at: "2026-07-04T13:00:00Z" }
  assert.deepEqual(queueWatch([
    qwDraft("2026-07-04T06:00:00Z"),
    qwDraft("2026-07-01T06:00:00Z", "manual_only", "posted"),
    autoOwned,
  ], QW_NOW), [])
})
test("queueWatch excludes a live policy_auto draft (legacy armed_auto path)", () => {
  const live = { ...qwDraft("2026-07-01T06:00:00Z", "armed_auto"),
    approval_mode: "policy_auto", auto_approve_at: "2026-07-04T13:00:00Z" }
  assert.deepEqual(queueWatch([live], QW_NOW), [])
})
test("queueWatch counts a failed-closed armed_auto-policy draft as human-gated", () => {
  // policy says armed_auto, but runnable state is manual (no auto_approve_at)
  const out = queueWatch([qwDraft("2026-07-01T06:00:00Z", "armed_auto")], QW_NOW)
  assert.equal(out[0].count, 1)
})
test("queueWatch counts suggested_auto and missing-mode as human-gated, skips junk timestamps", () => {
  const out = queueWatch([
    qwDraft("2026-07-02T06:00:00Z", "suggested_auto"),
    { status: "pending", type: "fire", created_at: "2026-07-02T06:00:00Z" },
    qwDraft("2026-02-31T00:00:00Z"),
  ], QW_NOW)
  assert.equal(out[0].count, 2)
  assert.deepEqual(out[0].types, { regional_anomaly: 1, fire: 1 })
})
test("buildSourceHealthPayload surfaces queue findings", () => {
  const state = {
    source_health: { open_meteo: { runs: [] } },
    drafts: [qwDraft("2026-07-01T06:00:00Z")],
  }
  const payload = buildSourceHealthPayload(state)
  assert.equal(payload.queue.length, 1)
  assert.equal(payload.queue[0].kind, "stale_reviews")
})
