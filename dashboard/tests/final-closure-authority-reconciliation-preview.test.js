import test from "node:test"
import assert from "node:assert/strict"

// E3: in local preview the reconciliation route reaches the local command
// authority (SQLite/PostgreSQL adapter) instead of refusing; it never touches the Gist.
test("preview reconciliation forwards exact bytes to the local authority and never the Gist", async () => {
  const saved = { ...process.env }
  const actualFetch = globalThis.fetch
  const calls = []
  for (const key of Object.keys(process.env)) if (/GIST|TOKEN|SECRET|PASSWORD|API_KEY/.test(key)) delete process.env[key]
  Object.assign(process.env, { NODE_ENV: "test", DASHBOARD_AUTH_DISABLED: "1", THEHEAT_LOCAL_COMMAND_URL: "http://127.0.0.1:3999" })
  delete process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET", body: options.body ? new TextDecoder().decode(options.body) : null })
    const payload = options.method === "POST" ? { status: "applied", state_version: 4 } : { rows: [], mutation: "none", local_preview: true }
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } })
  }
  const route = await import("../app/api/delivery-reconciliation/route.js")
  const request = (method, body, origin = "http://127.0.0.1:3033") => new Request("http://127.0.0.1:3033/api/delivery-reconciliation", {
    method, headers: { host: "127.0.0.1:3033", origin, authorization: "Basic " + Buffer.from("editor:invented-editor").toString("base64"),
      "content-type": "application/json" }, ...(body === undefined ? {} : { body }) })
  try {
    const view = await route.GET(request("GET"))
    assert.equal(view.status, 200)
    assert.deepEqual(await view.json(), { rows: [], mutation: "none", local_preview: true })
    // Writes stay an explicit exact-"1" capability even in preview.
    assert.equal((await route.POST(request("POST", "{}"))).status, 503)
    process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED = "1"
    const raw = '{"action":"confirm","reconciliation_id":"invented"}'
    const applied = await route.POST(request("POST", raw))
    assert.equal(applied.status, 200)
    assert.deepEqual(await applied.json(), { status: "applied", state_version: 4 })
    const tooLarge = await route.POST(request("POST", JSON.stringify({ pad: "x".repeat(17 * 1024) })))
    assert.equal(tooLarge.status, 413)
    assert.deepEqual(calls.map(c => [c.url, c.method]), [
      ["http://127.0.0.1:3999/delivery-reconciliation", "GET"], ["http://127.0.0.1:3999/delivery-reconciliation", "POST"]])
    assert.equal(calls[1].body, raw)
    assert.ok(calls.every(c => !c.url.includes("api.github.com")))
  } finally {
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})
