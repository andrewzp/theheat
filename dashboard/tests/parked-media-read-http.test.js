import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { performance } from "node:perf_hooks"

// Invented local fixture only. The owning real PostgreSQL test supplies config.
test("parked current delivery reads through the unchanged eight-second client", {
  skip: !process.env.THEHEAT_PARKED_READ_HTTP_CONFIG,
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_PARKED_READ_HTTP_CONFIG, "utf8"))
  const endpoint = new URL(config.endpoint), origin = new URL(config.origin)
  assert.match(endpoint.href, /^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}\/$/)
  assert.match(origin.href, /^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}\/$/)
  const keys = ["NODE_ENV", "DASHBOARD_AUTH_DISABLED", "THEHEAT_LOCAL_COMMAND_URL"]
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]))
  const originalFetch = globalThis.fetch
  let calls = 0
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = endpoint.origin
  globalThis.fetch = (url, options) => {
    assert.equal(new URL(url).origin, endpoint.origin, "Only the invented loopback authority is allowed")
    assert.equal(options.method, "GET", "This test cannot dispatch commands or posts")
    calls += 1
    return originalFetch(url, options)
  }
  try {
    const { GET } = await import("../app/api/editor-media/route.js")
    const request = new Request(`${origin.origin}/api/editor-media?draftId=${encodeURIComponent(config.draft_id)}`, {
      headers: { Host: origin.host, Origin: origin.origin,
        Authorization: `Basic ${Buffer.from("editor:invented-editor").toString("base64")}` },
    })
    const started = performance.now()
    const response = await GET(request)
    const body = await response.json()
    const elapsed = performance.now() - started
    assert.equal(response.status, 200, JSON.stringify(body))
    assert.equal(response.headers.get("cache-control"), "private, no-store")
    assert.equal(body.parked, true, JSON.stringify(body))
    assert.equal(body.review_current, true)
    assert.equal(body.checks_status, "passed")
    assert.equal(body.publication_approved, false)
    assert.equal(body.delivery.publication_approved, false)
    const intent = body.delivery.intents.filter(row => row.intent_id === config.intent)
    assert.equal(intent.length, 1)
    assert.equal(intent[0].current, true, JSON.stringify(intent))
    assert.equal(intent[0].reason, null)
    assert.equal(calls, 1, "No transport retry is permitted")
    assert.ok(elapsed < 8000, `Actual parked read took ${elapsed.toFixed(1)}ms`)
    console.log(JSON.stringify({ parked_read_ms: elapsed, one_get: calls, current_intent: true }))
  } finally {
    globalThis.fetch = originalFetch
    for (const key of keys) {
      if (saved[key] === undefined) delete process.env[key]
      else process.env[key] = saved[key]
    }
  }
})
