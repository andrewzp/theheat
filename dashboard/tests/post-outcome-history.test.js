import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ProductHealthPanel } from "../app/components/ProductHealthPanel.js"
import PostOutcomeHistory from "../app/components/PostOutcomeHistory.js"
import { postOutcomes } from "../lib/post-outcomes.js"
import { textHash } from "../lib/draft-revisions.js"
import { importFresh } from "./helpers/import-fresh.js"

const text = "Invented retained post <script>with escaped text</script>."
const fixture = () => ({ drafts: [], publish_ledger: { fixture: { phase: "confirmed", tweet_id: "123", text, text_sha256: textHash(text) } },
  tweet_metrics: { "123": { samples: { a: { schema_version: 1, tweet_id: "123", source: "x_api.public_metrics", sampled_at: "2026-01-02T00:00:00Z", posted_at: "2026-01-01T00:00:00Z", post_time_basis: "x_api.created_at", post_time_status: "recorded", post_age_seconds: 86400, counts: { likes: 0 } } } } } })
const render = state => renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes: postOutcomes(state) }))

test("actual component labels retained zero/missingness/age, escapes text and offers no collection action", () => {
  const state = fixture(), before = structuredClone(state), html = render(state)
  for (const copy of ["Retained post history", "does not collect metrics", "Unknown", "1d 0h after posting", "2026-01-02 00:00:00 UTC", "receipt time is not a substitute", "Topic, angle and human-edit attribution are not established"])
    assert.ok(html.includes(copy), copy)
  assert.match(html, /<dt>Likes<\/dt><dd>0<\/dd>/)
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"))
  assert.ok(!html.includes("<button") && !html.includes("<a "))
  assert.match(html, /<label[^>]*for="([^"]+)"[^>]*>Post with a retained receipt<\/label><select id="\1"/)
  assert.deepEqual(state, before)
})

test("unknown, conflicting and legacy evidence have explicit presentation", () => {
  assert.match(render(null), /publication evidence is unavailable/)
  assert.match(render({ drafts: [], publish_ledger: {} }), /No publication receipts/)
  const state = fixture(); state.publish_ledger.fixture.text_sha256 = "a".repeat(64)
  state.tweet_metrics["123"] = { at: "2026-01-02T00:00:00Z", likes: 0 }
  const html = render(state)
  assert.match(html, /Published revision conflicts/); assert.match(html, /Legacy snapshot/)
  assert.match(html, /Post age: Unknown/); assert.ok(!html.includes("&lt;script&gt;"))
})

test("existing ProductHealthPanel integrates history without requiring a new page/route", () => {
  const markup = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health: { post_outcomes: postOutcomes(fixture()) } }))
  assert.match(markup, /Operating status/); assert.match(markup, /Retained post history/)
})

test("large exact-post histories mount one bounded page and disclose total/range and controls", () => {
  const state = fixture(), sample = state.tweet_metrics["123"].samples.a
  state.tweet_metrics["123"].samples = Object.fromEntries(Array.from({ length: 1100 }, (_, i) => [String(i), { ...sample, counts: { likes: i } }]))
  const html = render(state)
  assert.equal((html.match(/<li /g) || []).length, 100)
  assert.match(html, /1100 retained observations/); assert.match(html, /Showing 1–100 of 1100/)
  assert.match(html, /Previous observations/); assert.match(html, /Next observations/)
  assert.match(html, /aria-posinset="100" aria-setsize="1100"/)
})

test("real authenticated dashboard GET projects the actual state; unauthenticated access reads nothing", async () => {
  const saved = { ...process.env }, originalFetch = globalThis.fetch, calls = [], state = fixture(), before = structuredClone(state)
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "fixture-reader", DASHBOARD_PASSWORD: "fixture-only", THEHEAT_STATE_BACKEND: "gist", GIST_ID: "fixture_outcomes", GITHUB_TOKEN: "fixture-only" })
  for (const key of ["DASHBOARD_AUTH_DISABLED", "THEHEAT_LOCAL_COMMAND_URL", "THEHEAT_DB_PATH"]) delete process.env[key]
  globalThis.fetch = async (url, options) => {
    assert.ok(!options?.method || options.method === "GET")
    calls.push(String(url))
    if (String(url) === "https://api.github.com/gists/fixture_outcomes") return Response.json({ files: { "state.json": { content: JSON.stringify(state) } } })
    if (String(url).endsWith("/actions/runs?per_page=10")) return Response.json({ workflow_runs: [] })
    throw new Error("Unexpected external request intercepted")
  }
  try {
    const { GET } = await importFresh("app/api/dashboard/route.js")
    const unauthorized = await GET(new Request("http://localhost/api/dashboard"))
    assert.equal(unauthorized.status, 401); assert.equal(calls.length, 0)
    const response = await GET(new Request("http://localhost/api/dashboard", { headers: { authorization: `Basic ${Buffer.from("fixture-reader:fixture-only").toString("base64")}` } }))
    assert.equal(response.status, 200)
    const body = await response.json()
    assert.equal(body.productHealth.post_outcomes.posts[0].text, text)
    assert.equal(body.productHealth.post_outcomes.posts[0].observations[0].counts.likes, 0)
    assert.equal(calls.length, 2, "only pre-existing state/workflow reads, both intercepted")
    const html = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health: body.productHealth }))
    assert.match(html, /Retained post history/); assert.match(html, /1d 0h after posting/)
    assert.deepEqual(state, before)
  } finally { globalThis.fetch = originalFetch; process.env = saved }
})
