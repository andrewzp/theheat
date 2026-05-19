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

test("drafts route rejects unauthenticated GET requests", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"

  const { GET } = await importFresh("app/api/drafts/route.js")
  const response = await GET(new Request("http://localhost/api/drafts"))

  assert.equal(response.status, 401)
  assert.equal(response.headers.get("WWW-Authenticate"), 'Basic realm="theheat dashboard"')
})

test("drafts route allows authenticated GET requests", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"
  process.env.GITHUB_TOKEN = "token_123"

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse({
    drafts: [
      { id: "draft_1", status: "pending", text: "Pending draft", created_at: "2026-04-09T00:00:00Z" },
      { id: "draft_2", status: "approved", text: "Approved draft", created_at: "2026-04-09T01:00:00Z" },
    ],
    posted_events: [],
    daily_tweet_count: {},
    pending_confirmations: [],
    run_history: [],
    errors: [],
    last_hot10: { date: null, cities: [] },
    streaks: {},
  })

  try {
    const { GET } = await importFresh("app/api/drafts/route.js")
    const response = await GET(new Request("http://localhost/api/drafts", {
      headers: {
        authorization: basicAuth("reviewer", "secret-pass"),
      },
    }))

    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.drafts.length, 1)
    assert.equal(payload.drafts[0].id, "draft_1")
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("trigger route rejects unauthenticated POST requests", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"

  const { POST } = await importFresh("app/api/trigger/route.js")
  const response = await POST(new Request("http://localhost/api/trigger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "alerts" }),
  }))

  assert.equal(response.status, 401)
})

test("generate route preserves Anthropic rate-limit failures", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.ANTHROPIC_API_KEY = "anthropic_test_key"

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: false,
    status: 429,
    async text() {
      return JSON.stringify({ error: { message: "rate limit exceeded" } })
    },
  })

  try {
    const { POST } = await importFresh("app/api/generate/route.js")
    const response = await POST(new Request("http://localhost/api/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        authorization: basicAuth("reviewer", "secret-pass"),
      },
      body: JSON.stringify({ prompt: "Write about Mauna Loa crossing 436 ppm." }),
    }))

    assert.equal(response.status, 429)
    const payload = await response.json()
    assert.match(payload.error, /rate limit/i)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("authenticated POST routes reject malformed JSON bodies", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.ANTHROPIC_API_KEY = "anthropic_test_key"
  process.env.GITHUB_TOKEN = "token_123"

  const routes = [
    ["app/api/generate/route.js", "http://localhost/api/generate"],
    ["app/api/drafts/route.js", "http://localhost/api/drafts"],
    ["app/api/post/route.js", "http://localhost/api/post"],
    ["app/api/trigger/route.js", "http://localhost/api/trigger"],
  ]

  for (const [modulePath, url] of routes) {
    const { POST } = await importFresh(modulePath)
    const response = await POST(new Request(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        authorization: basicAuth("reviewer", "secret-pass"),
      },
      body: "{",
    }))

    assert.equal(response.status, 400)
    assert.match((await response.json()).error, /invalid json/i)
  }
})

test("POST routes reject non-string text fields", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"
  process.env.ANTHROPIC_API_KEY = "anthropic_test_key"
  process.env.GITHUB_TOKEN = "token_123"
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_DB_PATH = ""
  process.env.GIST_ID = "gist_123"

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => gistResponse({
    drafts: [
      { id: "draft_1", status: "pending", text: "Pending draft", created_at: "2026-04-09T00:00:00Z" },
    ],
  })

  try {
    const cases = [
      ["app/api/generate/route.js", "http://localhost/api/generate", { prompt: { text: "not a string" } }, /prompt/i],
      ["app/api/post/route.js", "http://localhost/api/post", { tweet: { text: "not a string" } }, /tweet/i],
      ["app/api/drafts/route.js", "http://localhost/api/drafts", {
        action: "edit",
        draftId: "draft_1",
        editedText: { text: "not a string" },
      }, /invalid text/i],
    ]

    for (const [modulePath, url, body, errorPattern] of cases) {
      const { POST } = await importFresh(modulePath)
      const response = await POST(new Request(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          authorization: basicAuth("reviewer", "secret-pass"),
        },
        body: JSON.stringify(body),
      }))

      assert.equal(response.status, 400)
      assert.match((await response.json()).error, errorPattern)
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})

test("middleware blocks public dashboard access", async () => {
  process.env.NODE_ENV = "production"
  process.env.DASHBOARD_USERNAME = "reviewer"
  process.env.DASHBOARD_PASSWORD = "secret-pass"

  const { middleware } = await importFresh("middleware.js")
  const blocked = middleware(new Request("http://localhost/"))
  assert.equal(blocked.status, 401)

  const passed = middleware(new Request("http://localhost/", {
    headers: {
      authorization: basicAuth("reviewer", "secret-pass"),
    },
  }))
  assert.equal(passed.status, 200)
})
