import test from "node:test"
import assert from "node:assert/strict"

import { importFresh } from "./helpers/import-fresh.js"

// Invented, offline-only credentials. No Gist or GitHub request may leave.
const credential = `Basic ${Buffer.from("w13-editor:w13-invented-only").toString("base64")}`

function environment() {
  for (const key of ["THEHEAT_LOCAL_COMMAND_URL", "DASHBOARD_AUTH_DISABLED", "VERCEL_URL"]) delete process.env[key]
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "w13-editor"
  process.env.DASHBOARD_PASSWORD = "w13-invented-only"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.GIST_ID = "w13-fixture-gist"
  process.env.GITHUB_TOKEN = "w13-fixture-token"
}

async function trapped(run) {
  const calls = []
  const original = globalThis.fetch
  globalThis.fetch = async (url) => { calls.push(String(url)); return new Response("{}", { status: 503 }) }
  try { return await run(calls) } finally { globalThis.fetch = original }
}

function post(url, headers, body = { action: "approve", draftId: "w13-draft" }) {
  return new Request(url, { method: "POST", headers: { authorization: credential, "content-type": "application/json", ...headers },
    body: JSON.stringify(body) })
}

test("a valid credential cannot mutate Gist drafts from another origin; nothing is read or written", async () => {
  environment()
  const { POST } = await importFresh("app/api/drafts/route.js")
  await trapped(async (calls) => {
    for (const headers of [
      { origin: "https://attacker.invalid", host: "dashboard.invalid" },
      { origin: "null", host: "dashboard.invalid" },
      { origin: "", host: "dashboard.invalid" },
      { origin: "https://dashboard.invalid", host: "attacker.invalid" },
      { origin: "http://dashboard.invalid", host: "dashboard.invalid" },
      { "sec-fetch-site": "cross-site", host: "dashboard.invalid" },
      { "sec-fetch-site": "same-site", origin: "https://dashboard.invalid", host: "dashboard.invalid" },
    ]) {
      const response = await POST(post("https://dashboard.invalid/api/drafts", headers))
      assert.equal(response.status, 403, JSON.stringify(headers))
      const body = await response.json()
      assert.equal(body.code, "cross_origin_mutation_refused")
      assert.doesNotMatch(JSON.stringify(body), /w13-invented-only|w13-fixture-token|attacker/)
    }
    assert.deepEqual(calls, [])
  })
})

test("the same-origin page and a non-browser caller reach the existing revision checks", async () => {
  environment()
  const { POST } = await importFresh("app/api/drafts/route.js")
  await trapped(async () => {
    for (const headers of [
      { origin: "https://dashboard.invalid", host: "dashboard.invalid", "sec-fetch-site": "same-origin" },
      {},
    ]) {
      const response = await POST(post("https://dashboard.invalid/api/drafts", headers))
      assert.notEqual(response.status, 403)
      assert.notEqual((await response.json()).code, "cross_origin_mutation_refused")
    }
  })
})

test("authentication precedes the origin decision and reads are unaffected", async () => {
  environment()
  const { POST } = await importFresh("app/api/drafts/route.js")
  const { middleware } = await importFresh("middleware.js")
  const unauthenticated = new Request("https://dashboard.invalid/api/drafts", { method: "POST",
    headers: { origin: "https://attacker.invalid", "content-type": "application/json" }, body: "{}" })
  assert.equal((await POST(unauthenticated)).status, 401)
  const viaMiddleware = middleware(post("https://dashboard.invalid/api/trigger", { origin: "https://attacker.invalid", host: "dashboard.invalid" }))
  assert.equal(viaMiddleware.status, 403)
  const read = middleware(new Request("https://dashboard.invalid/api/drafts", { headers: { authorization: credential, origin: "https://attacker.invalid" } }))
  assert.notEqual(read.status, 403)
})

test("a loopback page canonicalized to localhost stays same-origin; another loopback port does not", async () => {
  environment()
  process.env.NODE_ENV = "development"
  const { mutationOriginError } = await importFresh("lib/auth.js")
  const same = post("http://localhost:3000/api/drafts", { origin: "http://127.0.0.1:3000", host: "127.0.0.1:3000" })
  assert.equal(mutationOriginError(same), null)
  const other = post("http://localhost:3000/api/drafts", { origin: "http://127.0.0.1:4000", host: "127.0.0.1:3000" })
  assert.equal(mutationOriginError(other).status, 403)
})
