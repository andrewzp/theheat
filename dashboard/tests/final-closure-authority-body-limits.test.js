import test from "node:test"
import assert from "node:assert/strict"
import { MAX_JSON_BODY_BYTES, readJsonObject } from "../lib/request-json.js"

// E2 (P13 bounded bodies): Gist-mode mutation routes refuse oversized bodies
// before any state read; the serialized command path already used 128 KiB.
test("readJsonObject bounds declared and streamed bodies and keeps strict parsing", async () => {
  const make = (body, headers = {}) => new Request("https://dashboard.example/api/drafts", { method: "POST", body, headers })
  assert.equal(MAX_JSON_BODY_BYTES, 128 * 1024)
  assert.deepEqual((await readJsonObject(make('{"a":1}'))).body, { a: 1 })
  const declared = await readJsonObject(make("{}", { "content-length": String(MAX_JSON_BODY_BYTES + 1) }))
  assert.equal(declared.error.status, 413)
  const streamed = await readJsonObject(make(JSON.stringify({ pad: "x".repeat(MAX_JSON_BODY_BYTES) })))
  assert.equal(streamed.error.status, 413)
  assert.equal((await streamed.error.json()).code, "request_body_too_large")
  assert.equal((await readJsonObject(make('{"a":1,"a":2}'), { strict: true })).error.status, 400)
  assert.equal((await readJsonObject(make("[]"))).error.status, 400)
  assert.equal((await readJsonObject(make(""))).error.status, 400)
})

test("an oversized draft mutation is refused before any Gist read or write", async () => {
  const saved = { ...process.env }
  const original = globalThis.fetch
  const calls = []
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "editor", DASHBOARD_PASSWORD: "invented-test-only",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "fixture_state", GITHUB_TOKEN: "fixture_token" })
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  globalThis.fetch = async (url) => { calls.push(String(url)); throw new Error(`unexpected egress ${url}`) }
  try {
    const { POST } = await import("../app/api/drafts/route.js")
    const response = await POST(new Request("https://dashboard.example/api/drafts", { method: "POST",
      headers: { authorization: `Basic ${btoa("editor:invented-test-only")}`, origin: "https://dashboard.example", "content-type": "application/json" },
      body: JSON.stringify({ id: "invented", action: "edit", text: "x".repeat(MAX_JSON_BODY_BYTES) }) }))
    assert.equal(response.status, 413)
    assert.deepEqual(calls, [])
  } finally {
    globalThis.fetch = original
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})
