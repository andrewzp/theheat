import test from "node:test"
import assert from "node:assert/strict"

import { importFresh } from "./helpers/import-fresh.js"

const ENV_KEYS = [
  "NODE_ENV", "DASHBOARD_AUTH_DISABLED", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD",
  "THEHEAT_PRODUCTION_PAUSED", "ANTHROPIC_API_KEY", "GITHUB_TOKEN",
]
const CASES = [
  ["generate", { prompt: "Describe the supplied weather observation." }],
  ...["alerts", "leaderboard", "both"].map((mode) => ["trigger", { mode }]),
]
let previousEnv
let originalFetch
let calls

test.beforeEach(() => {
  previousEnv = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]))
  ENV_KEYS.forEach((key) => delete process.env[key])
  Object.assign(process.env, {
    NODE_ENV: "production",
    DASHBOARD_USERNAME: "reviewer",
    DASHBOARD_PASSWORD: "test-only-pass",
    ANTHROPIC_API_KEY: "test-only-provider-key",
    GITHUB_TOKEN: "test-only-dispatch-key",
  })
  originalFetch = globalThis.fetch
  calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    if (url === "https://api.anthropic.com/v1/messages") {
      return Response.json({ content: [{ text: "Offline writer response." }] })
    }
    return new Response(null, { status: 204 })
  }
})

test.afterEach(() => {
  globalThis.fetch = originalFetch
  for (const [key, value] of Object.entries(previousEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
})

function request(route, body, authenticated = true) {
  return new Request(`http://localhost/api/${route}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(authenticated ? { authorization: `Basic ${Buffer.from("reviewer:test-only-pass").toString("base64")}` } : {}),
    },
    body: JSON.stringify(body),
  })
}

test("production pause blocks preview and every collection mode before any external request", async () => {
  process.env.THEHEAT_PRODUCTION_PAUSED = "1"
  for (const [route, body] of CASES) {
    const { POST } = await importFresh(`app/api/${route}/route.js`)
    const incoming = request(route, body)
    const response = await POST(incoming)
    assert.equal(response.status, 503)
    assert.equal(response.headers.get("cache-control"), "no-store")
    const payload = await response.json()
    assert.equal(payload.code, "production_paused")
    assert.match(payload.error, /data collection and draft generation are paused/i)
    assert.equal(incoming.bodyUsed, false)
  }
  assert.deepEqual(calls, [])
})

test("production pause preserves authentication before exposing operational status", async () => {
  process.env.THEHEAT_PRODUCTION_PAUSED = "1"
  for (const [route, body] of CASES) {
    const { POST } = await importFresh(`app/api/${route}/route.js`)
    const response = await POST(request(route, body, false))
    assert.equal(response.status, 401)
    assert.equal(response.headers.get("www-authenticate"), 'Basic realm="theheat dashboard"')
  }
  assert.deepEqual(calls, [])
})

for (const resumedValue of [undefined, "0"]) {
  test(`clearing production pause (${resumedValue ?? "unset"}) restores preview and collection dispatch`, async () => {
    for (const [route, body] of CASES) {
      process.env.THEHEAT_PRODUCTION_PAUSED = "1"
      const { POST } = await importFresh(`app/api/${route}/route.js`)
      assert.equal((await POST(request(route, body))).status, 503)
      if (resumedValue === undefined) delete process.env.THEHEAT_PRODUCTION_PAUSED
      else process.env.THEHEAT_PRODUCTION_PAUSED = resumedValue
      const response = await POST(request(route, body))
      assert.equal(response.status, 200)
      const payload = await response.json()
      const call = calls.at(-1)
      assert.equal(call.options.method, "POST")
      if (route === "generate") {
        assert.equal(payload.tweet, "Offline writer response.")
        assert.equal(call.url, "https://api.anthropic.com/v1/messages")
        assert.equal(JSON.parse(call.options.body).messages[0].content, `Write a tweet about this:\n${body.prompt}`)
      } else {
        assert.deepEqual(payload, { ok: true, mode: body.mode })
        assert.equal(call.url, "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches")
        assert.deepEqual(JSON.parse(call.options.body), { ref: "main", inputs: body })
      }
    }
    assert.equal(calls.length, CASES.length)
  })
}
