import test from "node:test"
import assert from "node:assert/strict"

import { readCollectionPause } from "../lib/automation.js"
import { collectionPauseSummary, dotColorForWorkflow, failingWorkflows } from "../lib/automation-status.js"

const bot = { name: "theheat-bot", file: "bot.yml", state: "active", last_run_conclusion: "success" }
const configured = { status: "configured", checked_at: "2026-10-11T12:00:00.000Z", reason: null }
let originalFetch, originalTimeout, originalToken, originalRepo

test.beforeEach(() => {
  originalFetch = globalThis.fetch
  originalTimeout = AbortSignal.timeout
  originalToken = process.env.GITHUB_TOKEN
  originalRepo = process.env.THEHEAT_REPO
  process.env.GITHUB_TOKEN = "invented-token"
  process.env.THEHEAT_REPO = "invented/repository"
})

test.afterEach(() => {
  globalThis.fetch = originalFetch
  AbortSignal.timeout = originalTimeout
  for (const [key, value] of [["GITHUB_TOKEN", originalToken], ["THEHEAT_REPO", originalRepo]]) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
})

for (const value of ["1", "0", "", "true", " 1", "1 ", "01"]) {
  test(`repository pause accepts exact string semantics ${JSON.stringify(value)}`, async () => {
    const calls = []
    let timeout
    AbortSignal.timeout = (ms) => { timeout = ms; return originalTimeout(ms) }
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options })
      return Response.json({ value, ignored: "never returned" })
    }
    const before = Date.now()
    const result = await readCollectionPause()
    assert.equal(result.status, value === "1" ? "configured" : "not_configured")
    assert.equal(result.reason, null)
    assert.ok(Date.parse(result.checked_at) >= before && Date.parse(result.checked_at) <= Date.now())
    assert.deepEqual(Object.keys(result).sort(), ["checked_at", "reason", "status"])
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url, "https://api.github.com/repos/invented/repository/actions/variables/THEHEAT_PRODUCTION_PAUSED")
    assert.equal(calls[0].options.cache, "no-store")
    assert.equal(timeout, 4000)
    assert.ok(calls[0].options.signal instanceof AbortSignal)
  })
}

for (const value of [null, {}, [], { value: true }, { value: 1 }, { value: null }]) {
  test(`invalid flag response is unknown: ${JSON.stringify(value)}`, async () => {
    globalThis.fetch = async () => Response.json(value)
    assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason: "invalid_response" })
  })
}

test("malformed JSON is unknown and does not expose upstream text", async () => {
  globalThis.fetch = async () => new Response("invented-private-upstream-body")
  assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason: "invalid_response" })
})

for (const status of [403, 404, 500]) {
  test(`HTTP ${status} is unknown with no retry or inferred absent flag`, async () => {
    let calls = 0
    globalThis.fetch = async () => { calls++; return new Response("invented-private-body", { status }) }
    assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason: "unavailable" })
    assert.equal(calls, 1)
  })
}

test("missing credentials makes no request", async () => {
  delete process.env.GITHUB_TOKEN
  globalThis.fetch = () => { throw new Error("must not request") }
  assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason: "missing_credentials" })
})

for (const [error, reason] of [[new DOMException("invented secret", "TimeoutError"), "timeout"], [new Error("invented secret"), "read_failed"]]) {
  test(`${reason} is bounded, safe and never a checked success`, async () => {
    let calls = 0
    globalThis.fetch = async () => { calls++; throw error }
    assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason })
    assert.equal(calls, 1)
  })
}

test("timeout while reading the response body stays unknown", async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => { throw new DOMException("body timeout", "TimeoutError") } })
  assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason: "timeout" })
})

test("native four-second abort ends a pending flag request without retry", async () => {
  let calls = 0
  // AbortSignal.timeout does not keep Node alive by itself.
  const keepAlive = setTimeout(() => {}, 5000)
  globalThis.fetch = async (_url, { signal }) => {
    calls++
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true })
    })
  }
  try {
    assert.deepEqual(await readCollectionPause(), { status: "unknown", checked_at: null, reason: "timeout" })
    assert.equal(calls, 1)
  } finally {
    clearTimeout(keepAlive)
  }
})

test("configured pause makes only the exact collector neutral without mutating retained results", () => {
  const original = structuredClone(bot)
  assert.equal(dotColorForWorkflow(bot, configured), "gray")
  assert.deepEqual(bot, original)
  for (const wf of [{ ...bot, file: "other.yml" }, { ...bot, name: "other" }, { ...bot, file: undefined }, { ...bot, name: undefined }]) {
    assert.equal(dotColorForWorkflow(wf, configured), "green")
  }
  assert.equal(dotColorForWorkflow(bot, { status: "unknown" }), "green")
  assert.equal(dotColorForWorkflow(bot, { status: "not_configured" }), "green")
})

test("real errors and existing disabled precedence survive configured pause", () => {
  for (const conclusion of ["failure", "timed_out", "startup_failure"]) {
    assert.equal(dotColorForWorkflow({ ...bot, last_run_conclusion: conclusion }, configured), "red")
    assert.equal(dotColorForWorkflow({ ...bot, file: "other.yml", last_run_conclusion: conclusion }, configured), "red")
    assert.equal(dotColorForWorkflow({ ...bot, state: "disabled_manually", last_run_conclusion: conclusion }, configured), "gray")
  }
  assert.equal(dotColorForWorkflow({ ...bot, error: "unavailable" }, configured), "red")
  assert.equal(dotColorForWorkflow({ ...bot, state: "disabled_manually", error: "unavailable" }, configured), "red")
  assert.deepEqual(failingWorkflows({ collection_pause: configured, workflows: [bot, { ...bot, error: "unavailable" }] }).map(wf => wf.error), ["unavailable"])
})

test("visible collection and dashboard labels preserve mismatch and unknown states", () => {
  const paused = collectionPauseSummary({ collection_pause: configured, dashboard_generation_pause: false })
  assert.equal(paused.collection, "Collection pause configured; saved source data may be old.")
  assert.equal(paused.dashboard, "Dashboard generation pause not configured.")
  assert.equal(paused.mismatch, true)
  assert.equal(collectionPauseSummary({ collection_pause: { status: "not_configured" }, dashboard_generation_pause: true }).mismatch, true)
  const unknown = collectionPauseSummary({ collection_pause: { status: "unknown" }, dashboard_generation_pause: true })
  assert.match(unknown.collection, /^Collection pause unknown;/)
  assert.equal(unknown.dashboard, "Dashboard generation pause configured.")
  assert.equal(unknown.mismatch, false)
})
