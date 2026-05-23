import test from "node:test"
import assert from "node:assert/strict"

import { importFresh } from "./helpers/import-fresh.js"

function workflowResponse(state, updatedAt = "2026-05-22T10:00:00Z") {
  return {
    ok: true,
    status: 200,
    async json() {
      return { id: 12345, name: state, state, updated_at: updatedAt }
    },
    async text() {
      return JSON.stringify({ state })
    },
  }
}

function workflowRunsResponse(runs = []) {
  return {
    ok: true,
    status: 200,
    async json() {
      return { workflow_runs: runs }
    },
    async text() {
      return JSON.stringify({ workflow_runs: runs })
    },
  }
}

function gistResponseWithFiles(stateJson, beaconJson) {
  // The gist REST API returns BOTH files in one response. readStateStore and
  // readRoutineBeacon both hit the same gist URL but extract different files.
  return {
    ok: true,
    status: 200,
    async json() {
      const files = { "state.json": { content: JSON.stringify(stateJson), truncated: false } }
      if (beaconJson !== undefined) {
        files["routine_beacon.json"] = { content: JSON.stringify(beaconJson) }
      }
      return { files }
    },
    async text() {
      return JSON.stringify({ state: stateJson, beacon: beaconJson })
    },
  }
}

function basicAuth(username, password) {
  return `Basic ${Buffer.from(`${username}:${password}`, "utf-8").toString("base64")}`
}

test("fetchWorkflowState returns state + updated_at", async () => {
  const calls = []
  global.fetch = async (url) => {
    calls.push(url)
    return workflowResponse("active", "2026-05-22T09:00:00Z")
  }
  process.env.GITHUB_TOKEN = "ghp_test"

  const { fetchWorkflowState } = await importFresh("lib/automation.js")
  const result = await fetchWorkflowState("bot.yml")

  assert.equal(result.state, "active")
  assert.equal(result.updated_at, "2026-05-22T09:00:00Z")
  assert.match(calls[0], /actions\/workflows\/bot\.yml$/)
})

test("fetchWorkflowLastRun returns the most recent run", async () => {
  const calls = []
  global.fetch = async (url) => {
    calls.push(String(url))
    return (
    workflowRunsResponse([
      {
        id: 999,
        status: "completed",
        conclusion: "success",
        created_at: "2026-05-22T08:00:00Z",
      },
    ])
    )
  }
  process.env.GITHUB_TOKEN = "ghp_test"
  delete process.env.THEHEAT_AUTOMATION_BRANCH

  const { fetchWorkflowLastRun } = await importFresh("lib/automation.js")
  const result = await fetchWorkflowLastRun("bot.yml")

  assert.equal(result.id, 999)
  assert.equal(result.conclusion, "success")
  assert.match(calls[0], /branch=main/)
})

test("fetchWorkflowLastRun returns null when no runs exist", async () => {
  global.fetch = async () => workflowRunsResponse([])
  process.env.GITHUB_TOKEN = "ghp_test"

  const { fetchWorkflowLastRun } = await importFresh("lib/automation.js")
  const result = await fetchWorkflowLastRun("bot.yml")

  assert.equal(result, null)
})

test("readRoutineBeacon returns parsed routine_beacon.json from gist", async () => {
  global.fetch = async () =>
    gistResponseWithFiles(
      { drafts: [] },
      {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
    )
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"

  const { readRoutineBeacon } = await importFresh("lib/automation.js")
  const result = await readRoutineBeacon()

  assert.equal(result.routine_last_run_at, "2026-05-22T15:04:58Z")
  assert.equal(result.routine_last_run_outcome, "graded")
})

test("readRoutineBeacon returns null when gist has no beacon file", async () => {
  global.fetch = async () => gistResponseWithFiles({ drafts: [] }, undefined)
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"

  const { readRoutineBeacon } = await importFresh("lib/automation.js")
  const result = await readRoutineBeacon()

  assert.equal(result, null)
})

test("getAutomationStatus composes workflows + routine + posting mode", async () => {
  global.fetch = async (url) => {
    if (url.includes("/runs?")) {
      return workflowRunsResponse([
        {
          id: 1,
          status: "completed",
          conclusion: "success",
          created_at: "2026-05-22T08:00:00Z",
        },
      ])
    }
    if (url.includes("/actions/workflows/")) {
      return workflowResponse("active")
    }
    // Gist URL — both readStateStore + readRoutineBeacon land here.
    return gistResponseWithFiles(
      {
        drafts: [
          { status: "pending", approval_policy: { mode: "manual_only" } },
          { status: "pending", approval_policy: { mode: "manual_only" } },
          { status: "pending", approval_policy: { mode: "armed_auto" } },
          { status: "pending", approval_policy: { mode: "suggested_auto" } },
        ],
      },
      {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
    )
  }
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"
  process.env.STATE_BACKEND = "gist"
  process.env.THEHEAT_STATE_BACKEND = "gist"

  const { getAutomationStatus } = await importFresh("lib/automation.js")
  const status = await getAutomationStatus()

  assert.equal(status.workflows.length, 3)
  assert.equal(status.workflows[0].file, "bot.yml")
  assert.equal(status.routine.last_run_outcome, "graded")
  assert.equal(status.posting_mode_summary.manual_only_count, 2)
  assert.equal(status.posting_mode_summary.armed_auto_count, 1)
  assert.equal(status.posting_mode_summary.suggested_count, 1)
})

test("getAutomationStatus reports posting mode unavailable when state store read fails", async () => {
  global.fetch = async (url) => {
    if (url.includes("/runs?")) {
      return workflowRunsResponse([
        {
          id: 1,
          status: "completed",
          conclusion: "success",
          created_at: "2026-05-22T08:00:00Z",
        },
      ])
    }
    if (url.includes("/actions/workflows/")) {
      return workflowResponse("active")
    }
    throw new Error("gist unavailable")
  }
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"
  process.env.THEHEAT_STATE_BACKEND = "gist"

  const { getAutomationStatus } = await importFresh("lib/automation.js")
  const status = await getAutomationStatus()

  assert.equal(status.posting_mode_summary, null)
  assert.match(status.posting_mode_error, /gist unavailable|fetch failed/i)
})

test("GET /api/automation returns 401 without auth when configured", async () => {
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"
  process.env.STATE_BACKEND = "gist"
  process.env.THEHEAT_STATE_BACKEND = "gist"

  const { GET } = await importFresh("app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation")
  const res = await GET(req)

  assert.equal(res.status, 401)
})

test("GET /api/automation returns combined status with valid auth", async () => {
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"
  process.env.STATE_BACKEND = "gist"
  process.env.THEHEAT_STATE_BACKEND = "gist"

  global.fetch = async (url) => {
    if (url.includes("/runs?")) {
      return workflowRunsResponse([
        {
          id: 7,
          status: "completed",
          conclusion: "success",
          created_at: "2026-05-22T08:00:00Z",
        },
      ])
    }
    if (url.includes("/actions/workflows/")) {
      return workflowResponse("active")
    }
    return gistResponseWithFiles(
      { drafts: [{ status: "pending", approval_policy: { mode: "manual_only" } }] },
      {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
    )
  }

  const { GET } = await importFresh("app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation", {
    headers: { authorization: basicAuth("admin", "secret") },
  })
  const res = await GET(req)
  const body = await res.json()

  assert.equal(res.status, 200)
  assert.equal(body.workflows.length, 3)
  assert.equal(body.routine.last_run_outcome, "graded")
  assert.equal(body.posting_mode_summary.manual_only_count, 1)
})

test("GET /api/automation degrades to 200 with workflow errors when GH API throws", async () => {
  // getAutomationStatus catches per-workflow + per-helper errors and returns a
  // degraded-but-valid response. The dashboard strip should then show red dots
  // (per-workflow .error populated) rather than the whole strip failing.
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"
  process.env.STATE_BACKEND = "gist"
  process.env.THEHEAT_STATE_BACKEND = "gist"

  global.fetch = async () => {
    throw new Error("ECONNREFUSED")
  }

  const { GET } = await importFresh("app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation", {
    headers: { authorization: basicAuth("admin", "secret") },
  })
  const res = await GET(req)
  const body = await res.json()

  assert.equal(res.status, 200, "degraded — getAutomationStatus catches errors")
  assert.equal(body.workflows.length, 3, "all 3 workflow rows present")
  for (const wf of body.workflows) {
    assert.ok(wf.error, `workflow ${wf.name} should have .error populated`)
    assert.match(wf.error, /ECONNREFUSED|fetch failed/i)
  }
  // Routine + posting-mode helpers also return null on fetch fail.
  assert.equal(body.routine.last_run_at, null)
  assert.equal(body.posting_mode_summary, null)
  assert.match(body.posting_mode_error, /ECONNREFUSED|fetch failed/i)
})

test("GET /api/automation reuses the short-lived status cache", async () => {
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.GIST_ID = "test_gist_id"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  delete process.env.THEHEAT_AUTOMATION_CACHE_TTL_MS

  let actionCalls = 0
  let gistCalls = 0
  global.fetch = async (url) => {
    if (url.includes("/runs?")) {
      actionCalls++
      return workflowRunsResponse([
        {
          id: 7,
          status: "completed",
          conclusion: "success",
          created_at: "2026-05-22T08:00:00Z",
        },
      ])
    }
    if (url.includes("/actions/workflows/")) {
      actionCalls++
      return workflowResponse("active")
    }
    gistCalls++
    return gistResponseWithFiles(
      { drafts: [{ status: "pending", approval_policy: { mode: "manual_only" } }] },
      {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
    )
  }

  const { GET } = await importFresh("app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation", {
    headers: { authorization: basicAuth("admin", "secret") },
  })
  const first = await GET(req)
  const second = await GET(req)

  assert.equal(first.status, 200)
  assert.equal(second.status, 200)
  assert.equal(actionCalls, 6)
  assert.equal(gistCalls, 2)
})
