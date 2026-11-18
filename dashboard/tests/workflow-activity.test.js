import test, { afterEach } from "node:test"
import assert from "node:assert/strict"
import { botWorkflowActivity, botActivityPresentation, dotColorForWorkflow } from "../lib/automation-status.js"
import { importFresh } from "./helpers/import-fresh.js"

const NOW = Date.parse("2026-11-18T13:00:00Z")
const options = { repository: "andrewzp/theheat", branch: "main", now: NOW }
const run = (id = 8, status = "in_progress") => ({ id, status, event: "schedule",
  head_branch: "main", head_sha: "a".repeat(40), created_at: "2026-11-18T12:00:00Z" })
const envelope = (rows) => ({ ...botWorkflowActivity(rows, options), checked_at: "2026-11-18T13:00:00Z" })
const savedFetch = global.fetch
const keys = ["GITHUB_TOKEN", "GIST_ID", "STATE_BACKEND", "THEHEAT_STATE_BACKEND", "THEHEAT_REPO", "THEHEAT_AUTOMATION_BRANCH"]
const original = Object.fromEntries(keys.map((key) => [key, process.env[key]]))
afterEach(() => {
  global.fetch = savedFetch
  for (const key of keys) {
    if (original[key] === undefined) delete process.env[key]
    else process.env[key] = original[key]
  }
})

function wire(rows, { failed = false, malformed = false } = {}) {
  process.env.GITHUB_TOKEN = "invented-no-access"
  process.env.GIST_ID = "invented-activity-state"
  process.env.STATE_BACKEND = process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_REPO = "andrewzp/theheat"
  delete process.env.THEHEAT_AUTOMATION_BRANCH
  const calls = []
  global.fetch = async (input, init) => {
    const url = new URL(input)
    assert.equal(url.origin, "https://api.github.com")
    assert.equal(init?.method || "GET", "GET", "Activity must never mutate or dispatch")
    calls.push(url)
    let body
    if (url.pathname.endsWith("/runs")) {
      assert.equal(url.searchParams.get("branch"), "main")
      assert.equal(url.searchParams.get("exclude_pull_requests"), "true")
      assert.equal(url.searchParams.get("per_page"), "10")
      if (failed) return { ok: false, status: 503 }
      body = { workflow_runs: malformed ? "invalid" : rows }
    } else if (url.pathname.includes("/actions/workflows/")) body = { state: "active" }
    else if (url.pathname.endsWith("/THEHEAT_PRODUCTION_PAUSED")) body = { value: "0" }
    else if (url.pathname.includes("/actions/variables/")) return { ok: false, status: 404 }
    else if (url.pathname === "/gists/invented-activity-state") {
      body = { files: { "state.json": { content: JSON.stringify({ drafts: [] }), truncated: false } } }
    } else assert.fail("Unowned HTTP request")
    return { ok: true, status: 200, json: async () => body }
  }
  return calls
}

test("actual automation read exposes queued AND running without masking the last failure or adding reads", async () => {
  const rows = [{ ...run(7, "completed"), conclusion: "failure", created_at: "2020-01-01T10:00:00Z" },
    { ...run(9, "queued"), created_at: "2020-01-01T12:00:00Z" },
    { ...run(8), created_at: "2020-01-01T11:00:00Z" }]
  const calls = wire(rows)
  const { getAutomationStatus } = await importFresh("lib/automation.js")
  const result = await getAutomationStatus()
  const bot = result.workflows.find((row) => row.file === "bot.yml")
  assert.equal(bot.last_run_conclusion, "failure")
  assert.equal(bot.last_run_at, rows[0].created_at)
  assert.equal(dotColorForWorkflow(bot), "red")
  assert.equal(bot.current_activity.status, "reported")
  assert.deepEqual(bot.current_activity.runs.map((row) => row.id), [9, 8])
  assert.equal(bot.current_activity.window_size, 3)
  assert.ok(Number.isFinite(Date.parse(bot.current_activity.checked_at)))
  const view = botActivityPresentation(bot.current_activity)
  assert.deepEqual(view.runs.map((row) => row.label), ["queued", "running"])
  assert.deepEqual(view.runs.map((row) => row.href), [
    "https://github.com/andrewzp/theheat/actions/runs/9", "https://github.com/andrewzp/theheat/actions/runs/8",
  ])
  const reads = calls.filter((url) => url.pathname.endsWith("/runs"))
  assert.equal(reads.length, 5)
  assert.equal(new Set(reads.map(String)).size, 5)
  assert.ok(result.workflows.filter((row) => row.file !== "bot.yml").every((row) => !("current_activity" in row)))
})

for (const rows of [[], [{ ...run(7, "completed"), conclusion: "success" }]]) {
  test(`actual read reports a bounded quiet window of ${rows.length}, not global liveness`, async () => {
    wire(rows)
    const { getAutomationStatus, fetchWorkflowLastRun } = await importFresh("lib/automation.js")
    const bot = (await getAutomationStatus()).workflows[0]
    assert.equal(bot.current_activity.status, "not_reported")
    assert.equal(bot.current_activity.window_size, rows.length)
    assert.deepEqual(botActivityPresentation(bot.current_activity).runs, [])
    assert.match(botActivityPresentation(bot.current_activity).message, rows.length ? /returned runs/ : /latest check/)
    const last = await fetchWorkflowLastRun("bot.yml")
    if (rows.length === 0) assert.equal(last, null)
    else assert.equal(last.conclusion, "success")
  })
}

for (const failure of [{ failed: true }, { malformed: true }]) {
  test(`failed or malformed actual read never becomes a quiet window ${JSON.stringify(failure)}`, async () => {
    wire([], failure)
    const { getAutomationStatus } = await importFresh("lib/automation.js")
    const bot = (await getAutomationStatus()).workflows[0]
    assert.equal(bot.current_activity.status, "unavailable")
    assert.equal(dotColorForWorkflow(bot), "red")
    assert.match(botActivityPresentation(bot.current_activity).message, /unavailable/)
  })
}

test("all five active states remain distinct and input order does not change the bounded view", () => {
  const rows = ["queued", "in_progress", "waiting", "pending", "requested"].map((status, i) => run(i + 1, status))
  const before = structuredClone(rows)
  const a = envelope(rows)
  assert.deepEqual(envelope([...rows].reverse()), a)
  assert.deepEqual(rows, before)
  assert.equal(botActivityPresentation(a, NOW).runs.length, 5)
})

for (const [name, mutate] of [
  ["foreign branch", (row) => { row.head_branch = "feature" }],
  ["pull request", (row) => { row.event = "pull_request" }],
  ["unknown event", (row) => { row.event = "push" }],
  ["unknown status", (row) => { row.status = "invented" }],
  ["unsafe id", (row) => { row.id = Number.MAX_SAFE_INTEGER + 1 }],
  ["string id", (row) => { row.id = "8" }],
  ["missing sha", (row) => { delete row.head_sha }],
  ["future", (row) => { row.created_at = "2027-01-01T00:00:00Z" }],
  ["impossible date", (row) => { row.created_at = "2026-02-31T00:00:00Z" }],
  ["undated", (row) => { delete row.created_at }],
]) {
  test(`${name} active metadata is unavailable, never a false quiet window or link`, () => {
    const row = run()
    mutate(row)
    const result = envelope([row])
    assert.equal(result.status, "unavailable")
    assert.deepEqual(botActivityPresentation(result, NOW).runs, [])
  })
}

test("duplicate or conflicting ids, oversized and malformed windows are held", () => {
  for (const rows of [[run(), run()], [run(), { ...run(), status: "completed" }],
    Array.from({ length: 11 }, (_, i) => run(i + 1)), [null], "invalid"]) {
    assert.equal(botWorkflowActivity(rows, options).status, "unavailable")
  }
})

test("links use only verified repository and id; provider URLs and names stay inert", () => {
  const result = envelope([{ ...run(), html_url: "javascript:alert(1)", name: "<script>invented</script>" }])
  const view = botActivityPresentation(result, NOW)
  assert.equal(view.runs[0].href, "https://github.com/andrewzp/theheat/actions/runs/8")
  assert.ok(!JSON.stringify(result).includes("<script>"))
  for (const repository of ["../evil", "example.com/../evil", "owner/repo?token=secret", "owner/repo#x"]) {
    assert.equal(botWorkflowActivity([run()], { ...options, repository }).status, "unavailable")
    assert.deepEqual(botActivityPresentation({ ...result, repository }, NOW).runs, [])
  }
})

test("presentation refuses forged scope/count/status/time instead of offering a handle", () => {
  const good = envelope([run()])
  for (const changed of [{ ...good, window_size: 0 }, { ...good, window_size: 99 },
    { ...good, status: "not_reported" }, { ...good, checked_at: "invalid" },
    { ...good, checked_at: "2026-11-18T11:00:00Z" }, { ...good, runs: [] }]) {
    assert.deepEqual(botActivityPresentation(changed, NOW).runs, [])
    assert.match(botActivityPresentation(changed, NOW).message, /unavailable/)
  }
})

test("a different client clock does not hide server-verified reported activity", () => {
  const activity = envelope([run()])
  const originalNow = Date.now
  try {
    Date.now = () => Date.parse("2020-01-01T00:00:00Z")
    assert.equal(botActivityPresentation(activity).runs[0].id, 8)
  } finally {
    Date.now = originalNow
  }
})
