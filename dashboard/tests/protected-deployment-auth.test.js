import test from "node:test"
import assert from "node:assert/strict"

import { requireDashboardAuth, verifyDashboardAuth } from "../lib/auth.js"
import { importFresh } from "./helpers/import-fresh.js"

const GENERATED_HOST = "dashboard-build123-reviewer-projects.vercel.app"
const ALIAS_HOST = "dashboard-production.vercel.app"
const ENV_KEYS = ["NODE_ENV", "DASHBOARD_AUTH_DISABLED", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "VERCEL", "VERCEL_ENV", "VERCEL_URL"]
let previousEnv

test.beforeEach(() => {
  previousEnv = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]))
  ENV_KEYS.forEach((key) => delete process.env[key])
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_AUTH_DISABLED: "1", VERCEL_URL: GENERATED_HOST })
})

test.afterEach(() => {
  for (const [key, value] of Object.entries(previousEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
})

function request(host, path = "/", options = {}) {
  return new Request(`https://${host}${path}`, {
    ...options,
    headers: { host, ...options.headers },
  })
}

test("public aliases redirect GET and HEAD to the protected host with path/query and no caching", () => {
  for (const method of ["GET", "HEAD"]) {
    for (const host of [ALIAS_HOST, "dashboard.example.com"]) {
      const response = requireDashboardAuth(request(host, "/api/drafts?label=a%20b&score=75", { method }))
      assert.equal(response.status, 307)
      assert.equal(response.headers.get("location"), `https://${GENERATED_HOST}/api/drafts?label=a%20b&score=75`)
      assert.equal(response.headers.get("cache-control"), "no-store")
      assert.equal(response.headers.get("www-authenticate"), null)
    }
  }
})

test("a double-slash path cannot redirect to an attacker-controlled origin", () => {
  const response = requireDashboardAuth(request(ALIAS_HOST, "//attacker.example/path?x=1"))
  const location = new URL(response.headers.get("location"))
  assert.equal(location.origin, `https://${GENERATED_HOST}`)
  assert.equal(location.pathname, "//attacker.example/path")
  assert.equal(location.search, "?x=1")
})

test("only matching generated URL and raw Host are allowed, independently of forwarded headers", async () => {
  for (const method of ["GET", "POST"]) {
    assert.equal(requireDashboardAuth(request(GENERATED_HOST, "/api/drafts", {
      method,
      headers: { "x-forwarded-host": ALIAS_HOST, forwarded: `host=${ALIAS_HOST}` },
    })), null)
  }
  const forgedForwarded = requireDashboardAuth(request(ALIAS_HOST, "/api/drafts", {
    headers: { "x-forwarded-host": GENERATED_HOST, forwarded: `host=${GENERATED_HOST}` },
  }))
  assert.equal(forgedForwarded.status, 307)

  for (const rawHost of [ALIAS_HOST, `${GENERATED_HOST}:444`, ""]) {
    const response = requireDashboardAuth(request(GENERATED_HOST, "/api/drafts", {
      headers: { host: rawHost, "x-forwarded-host": GENERATED_HOST },
    }))
    assert.equal(response.status, 403)
    assert.equal(response.headers.get("location"), null, "host conflicts must not redirect to themselves")
    assert.equal((await response.json()).code, "sign_in_required")
  }
  const spoofedRawHost = requireDashboardAuth(request(ALIAS_HOST, "/api/drafts", { headers: { host: GENERATED_HOST } }))
  assert.equal(spoofedRawHost.status, 307, "raw Host alone cannot grant access")
})

test("alias mutations are rejected without redirecting their bodies", async () => {
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]) {
    const incoming = request(ALIAS_HOST, "/api/drafts", { method, body: "private-unsaved-edit" })
    const response = requireDashboardAuth(incoming)
    assert.equal(response.status, 403)
    assert.equal(response.headers.get("location"), null)
    assert.equal(response.headers.get("cache-control"), "no-store")
    assert.equal(incoming.bodyUsed, false)
    const payload = await response.json()
    assert.equal(payload.code, "sign_in_required")
    assert.match(payload.error, /sign in/i)
    assert.equal(payload.signInUrl, `https://${GENERATED_HOST}/`)
  }
})

test("production opt-out fails closed without any Vercel environment metadata", () => {
  delete process.env.VERCEL_URL
  assert.equal(requireDashboardAuth(request(ALIAS_HOST)).status, 503)
  assert.equal(requireDashboardAuth(request(ALIAS_HOST, "/api/drafts", { method: "POST" })).status, 503)
})

test("invalid deployment hosts fail closed instead of creating an open redirect", () => {
  for (const value of ["", "https://safe.vercel.app", "attacker.example", "safe.vercel.app.attacker.example", "safe.vercel.app/path", "safe.vercel.app?x=1", "user@safe.vercel.app", "safe.vercel.app:443", "safe.vercel.app\\@attacker.example", "-bad.vercel.app"]) {
    process.env.VERCEL_URL = value
    const response = requireDashboardAuth(request(ALIAS_HOST))
    assert.equal(response.status, 503, value)
    assert.equal(response.headers.get("location"), null)
    assert.equal(response.headers.get("cache-control"), "no-store")
  }
})

test("middleware and direct API handlers enforce the same alias gate before any state/model calls", async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => { throw new Error("No external calls may run before authentication") }
  try {
    const { middleware } = await importFresh("middleware.js")
    assert.equal(middleware(request(ALIAS_HOST)).status, 307)
    assert.equal(middleware(request(GENERATED_HOST)).status, 200)
    for (const route of ["drafts", "dashboard", "automation"]) {
      const { GET } = await importFresh(`app/api/${route}/route.js`)
      assert.equal((await GET(request(ALIAS_HOST, `/api/${route}`))).status, 307)
    }
    for (const route of ["drafts", "post", "trigger", "generate"]) {
      const { POST } = await importFresh(`app/api/${route}/route.js`)
      const incoming = request(ALIAS_HOST, `/api/${route}`, { method: "POST", body: "{" })
      const response = await POST(incoming)
      assert.equal(response.status, 403, route)
      assert.equal((await response.json()).code, "sign_in_required")
      assert.equal(incoming.bodyUsed, false)
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("Basic-auth mode is unchanged on aliases even without Vercel metadata", () => {
  delete process.env.DASHBOARD_AUTH_DISABLED
  delete process.env.VERCEL_URL
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "test-only-pass"
  assert.equal(requireDashboardAuth(request(ALIAS_HOST)).status, 401)
  const authorization = `Basic ${Buffer.from("reviewer:test-only-pass").toString("base64")}`
  assert.equal(requireDashboardAuth(request(ALIAS_HOST, "/", { headers: { authorization } })), null)
})

test("non-production intentional opt-out still works locally", () => {
  process.env.NODE_ENV = "development"
  delete process.env.VERCEL_URL
  assert.equal(verifyDashboardAuth(new Request("http://localhost:3000/")).ok, true)
})
