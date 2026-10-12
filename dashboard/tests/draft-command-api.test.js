import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createServer } from "node:http"
import { Readable } from "node:stream"
import { runFixtureWorker } from "../test-support/fixture-worker.js"
import { acceptLocalCommand } from "../lib/draft-command-client.js"
import { createDraftCommand } from "../lib/draft-command-request.js"

test("local mode blocks every legacy route before external I/O, including failed-first-refresh and accidental credentials", async () => {
  const saved = { ...process.env }
  const actualFetch = globalThis.fetch
  const calls = []
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = "http://127.0.0.1:3999"
  globalThis.fetch = async (url) => { calls.push(String(url)); throw new Error("No local authority listening") }
  const routes = await Promise.all(["dashboard", "automation", "generate", "trigger", "post", "source-health", "config"].map(async (name) => [name, await import(`../app/api/${name}/route.js`)]))
  const { middleware } = await import("../middleware.js")
  function request(name, method = "GET") {
    return new Request(`http://127.0.0.1:3033/api/${name}`, { method, headers: {
      host: "127.0.0.1:3033", origin: "http://127.0.0.1:3033", authorization: "Basic " + Buffer.from("editor:invented-editor").toString("base64"),
      "Content-Type": "application/json",
    }, ...(method === "POST" ? { body: '{"prompt":"invented","mode":"both"}' } : {}) })
  }
  try {
    const first = await routes[0][1].GET(request("dashboard"))
    assert.equal(first.status, 503)
    assert.equal((await first.json()).local_preview, true)
    assert.deepEqual(calls, ["http://127.0.0.1:3999/state"])
    for (const [name, route] of routes.slice(1)) {
      const method = route.POST ? "POST" : "GET"
      const response = await route[method](request(name, method))
      assert.equal(response.status, name === "generate" ? 400 : 503, name)
      assert.equal((await response.json()).code, name === "generate" ? "sourced_generation_command_required" : "local_preview_route_unavailable")
    }
    assert.deepEqual(calls, ["http://127.0.0.1:3999/state"])
    calls.length = 0
    for (const credential of ["GITHUB_TOKEN", "ANTHROPIC_API_KEY", "GH_GIST_TOKEN", "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS"]) {
      process.env[credential] = "invented-accidental-credential"
      for (const [name, route] of routes) {
        const method = route.POST ? "POST" : "GET"
        const response = await route[method](request(name, method))
        assert.equal(response.status, 503, name)
        assert.equal((await response.json()).code, "local_preview_credentials_refused")
      }
      assert.equal(middleware(request("drafts")).status, 503)
      delete process.env[credential]
    }
    assert.deepEqual(calls, [])
    assert.equal(middleware(request("drafts", "DELETE")).status, 405)
    const numeric = request("drafts")
    // Actual Next middleware rewrites only its loopback URL representation;
    // the numeric raw Host and exact port remain required independently.
    assert.equal(middleware(new Request("http://localhost:3033/api/drafts", { headers: numeric.headers })).status, 200)
    assert.equal(middleware(new Request("http://evil.invalid:3033/api/drafts", { headers: numeric.headers })).status, 403)
    assert.equal(middleware(new Request("http://localhost:3034/api/drafts", { headers: numeric.headers })).status, 403)
    assert.equal(middleware(new Request("http://localhost:3033/api/drafts", { headers: { ...Object.fromEntries(numeric.headers), host: "evil.invalid:3033" } })).status, 403)
    process.env.THEHEAT_ENVIRONMENT = "production"
    const production = await routes[0][1].GET(request("dashboard"))
    assert.equal(production.status, 503)
    assert.equal((await production.json()).code, "local_preview_configuration_refused")
    assert.deepEqual(calls, [])
    delete process.env.THEHEAT_ENVIRONMENT
    process.env.NODE_ENV = "production"
    process.env.DASHBOARD_AUTH_DISABLED = "0"
    process.env.DASHBOARD_USERNAME = "editor"
    process.env.DASHBOARD_PASSWORD = "invented-editor"
    assert.equal((await routes[0][1].GET(request("dashboard"))).status, 503)
    assert.deepEqual(calls, [])
  } finally {
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})

test("production refuses an explicitly configured preview before fetch", async () => {
  const old = { mode: process.env.NODE_ENV, url: process.env.THEHEAT_LOCAL_COMMAND_URL }
  process.env.NODE_ENV = "production"
  process.env.THEHEAT_LOCAL_COMMAND_URL = "http://127.0.0.1:3999"
  const savedFetch = globalThis.fetch
  globalThis.fetch = () => { throw new Error("Unexpected network") }
  try {
    const response = await acceptLocalCommand(new Request("http://127.0.0.1:3033/api/drafts", { method: "POST", body: "{}" }))
    assert.equal(response.status, 503)
    assert.match((await response.json()).code, /configuration_refused/)
  } finally {
    globalThis.fetch = savedFetch
    for (const [key, value] of [["NODE_ENV", old.mode], ["THEHEAT_LOCAL_COMMAND_URL", old.url]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value
    }
  }
})

test("real Next draft handlers over HTTP accept, conflict, review and park in PostgreSQL", {
  skip: !process.env.THEHEAT_PREVIEW_TEST_CONFIG && "Run through the actual PostgreSQL integration profile",
}, async () => {
  const config = JSON.parse(readFileSync(process.env.THEHEAT_PREVIEW_TEST_CONFIG, "utf8"))
  const testOrigin = config.origin
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  const drafts = await import("../app/api/drafts/route.js")
  const dashboard = await import("../app/api/dashboard/route.js")
  const stateStore = await import("../lib/state-store.js")
  const actualFetch = globalThis.fetch
  const allowed = new Set([config.endpoint, testOrigin])
  const externalCalls = []
  globalThis.fetch = (url, options) => {
    if (!allowed.has(new URL(url).origin)) {
      externalCalls.push(String(url))
      throw new Error("External network refused in integration test")
    }
    return actualFetch(url, options)
  }
  const server = createServer(async (incoming, outgoing) => {
    try {
      const request = new Request(`${testOrigin}${incoming.url}`, {
        method: incoming.method, headers: incoming.headers,
        ...(incoming.method === "POST" ? { body: Readable.toWeb(incoming), duplex: "half" } : {}),
      })
      const route = incoming.url.startsWith("/api/dashboard") ? dashboard : drafts
      const response = await route[incoming.method](request)
      outgoing.writeHead(response.status, Object.fromEntries(response.headers))
      outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch (error) { outgoing.writeHead(500); outgoing.end(JSON.stringify({ error: error.message })) }
  })
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(new URL(testOrigin).port), "127.0.0.1", resolve) })
  const authorization = (role) => `Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`
  async function request(path = "/api/drafts", { role = "editor", command, raw, extraHeaders = {} } = {}) {
    const response = await actualFetch(`${testOrigin}${path}`, {
      method: command || raw ? "POST" : "GET", headers: { Authorization: authorization(role),
        Origin: testOrigin, "Content-Type": "application/json", ...extraHeaders },
      ...(command || raw ? { body: raw || JSON.stringify(command) } : {}),
    })
    return { status: response.status, body: await response.json(), headers: response.headers }
  }
  async function consume(commandId) {
    const response = await runFixtureWorker(config.python, ["-m", "src.commands.preview_worker", ...config.workerArguments,
      ...(commandId ? ["--command-id", commandId] : [])], { cwd: config.root,
      env: { PATH: process.env.PATH, PYTHONPATH: config.root, no_proxy: "*" }, encoding: "utf8", timeout: 15000 })
    assert.equal(response.status, 0, response.stdout + response.stderr)
    return JSON.parse(response.stdout).result
  }
  try {
    const page = await request("/api/dashboard")
    assert.equal(page.status, 200)
    assert.equal(page.body.local_preview, true)
    assert.deepEqual(page.body.runs, [])
    assert.equal(page.headers.get("cache-control"), "private, no-store")
    let draft = page.body.drafts.drafts[0]
    const first = createDraftCommand(draft, "edit", { editedText: "Invented local dashboard edit." })
    const second = createDraftCommand(draft, "edit", { editedText: "Competing unsaved local edit." })
    const accepted = await request("/api/drafts", { command: first })
    assert.equal(accepted.status, 202)
    assert.deepEqual((await request("/api/drafts", { command: first })).body, accepted.body)
    assert.equal((await request("/api/drafts", { command: second })).status, 202)
    assert.equal((await request(`/api/drafts?commandId=${first.command_id}`)).body.status, "pending")
    assert.equal((await consume()).status, "applied")
    assert.equal((await consume()).code, "revision_conflict")
    const completed = await request(`/api/drafts?commandId=${first.command_id}`)
    assert.equal(completed.body.result.status, "applied")
    draft = (await request()).body.drafts[0]
    assert.equal(draft.text, first.payload.text)
    assert.equal(draft.review_status, "needs_revalidation")
    const review = createDraftCommand(draft, "review", { reviewConfirmed: true, expectedPolicySha256: draft.editorial_policy.policy_sha256 })
    assert.equal((await request("/api/drafts", { command: review })).status, 202)
    assert.equal((await consume()).status, "applied")
    draft = (await request()).body.drafts[0]
    assert.equal(draft.review_status, "passed")
    const approval = createDraftCommand(draft, "approve")
    assert.equal((await request("/api/drafts", { command: approval })).status, 403)
    assert.equal((await request("/api/drafts", { command: approval, role: "publisher" })).status, 202)
    const result = await consume()
    assert.equal(result.status, "applied")
    assert.equal((await consume(approval.command_id)).publish_intent_id, result.publish_intent_id)
    draft = (await request()).body.drafts[0]
    assert.equal(draft.parked_intent, result.publish_intent_id)
    assert.equal(draft.automatic_publication.enabled, false)
    assert.equal((await request("/api/drafts", { raw: '{"action":"x","action":"y"}' })).status, 400)
    assert.equal((await request("/api/drafts", { command: first, extraHeaders: { Origin: "http://evil.invalid" } })).status, 403)
    assert.equal((await request("/api/drafts", { command: first, extraHeaders: { "Content-Type": "text/plain" } })).status, 415)
    assert.equal((await request("/api/drafts", { raw: "x".repeat(128 * 1024 + 1) })).status, 413)
    assert.equal((await request("/api/drafts", { command: first, role: "viewer" })).status, 403)
    const auth = await request("/api/drafts", { extraHeaders: { Authorization: "Basic aW52YWxpZA==" } })
    assert.equal(auth.status, 401)
    assert.match(auth.headers.get("www-authenticate"), /Basic/)
    await assert.rejects(stateStore.readStateStore(), /authenticated_request/)
    await assert.rejects(stateStore.writeStateStore({}), /domain command/)
    await assert.rejects(stateStore.updateDraftStore("id", () => ({})), /domain command/)
    process.env.THEHEAT_LOCAL_COMMAND_URL = "http://127.0.0.1:1"
    allowed.add("http://127.0.0.1:1")
    assert.equal((await request()).status, 503)
    assert.deepEqual(externalCalls, [])
  } finally {
    globalThis.fetch = actualFetch
    await new Promise((resolve) => { server.close(resolve); server.closeAllConnections() })
    delete process.env.THEHEAT_LOCAL_COMMAND_URL
    delete process.env.DASHBOARD_AUTH_DISABLED
  }
})

test("actual Next handlers request checks, admit a retained candidate, and invalidate an edit", {
  skip: !process.env.THEHEAT_CANDIDATE_TEST_CONFIG && "Run through the actual candidate PostgreSQL profile",
}, async () => {
  const configFile = process.env.THEHEAT_CANDIDATE_TEST_CONFIG
  const config = JSON.parse(readFileSync(configFile, "utf8"))
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  const { createCandidateCommand } = await import("../lib/draft-command-request.js")
  const drafts = await import("../app/api/drafts/route.js")
  const dashboard = await import("../app/api/dashboard/route.js")
  const actualFetch = globalThis.fetch
  globalThis.fetch = (url, options) => {
    assert.ok([config.origin, config.endpoint].includes(new URL(url).origin), "Only the two owned loopback services may be contacted")
    return actualFetch(url, options)
  }
  const server = createServer(async (incoming, outgoing) => {
    try {
      const request = new Request(`${config.origin}${incoming.url}`, { method: incoming.method, headers: incoming.headers,
        ...(incoming.method === "POST" ? { body: Readable.toWeb(incoming), duplex: "half" } : {}) })
      const route = incoming.url.startsWith("/api/dashboard") ? dashboard : drafts
      const response = await route[incoming.method](request)
      outgoing.writeHead(response.status, Object.fromEntries(response.headers))
      outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch (error) { outgoing.writeHead(500); outgoing.end(JSON.stringify({ error: error.message })) }
  })
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(new URL(config.origin).port), "127.0.0.1", resolve) })
  async function request(path = "/api/drafts", command = null, role = "editor") {
    const response = await actualFetch(`${config.origin}${path}`, { method: command ? "POST" : "GET",
      headers: { Authorization: `Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`, Origin: config.origin, "Content-Type": "application/json" },
      ...(command ? { body: JSON.stringify(command) } : {}) })
    return { status: response.status, body: await response.json() }
  }
  async function worker(mode, command, stage) {
    const result = await runFixtureWorker(config.python, [config.child, configFile, mode, command, ...(stage ? [stage] : [])], {
      cwd: config.root, env: { PATH: process.env.PATH, PYTHONPATH: config.root, no_proxy: "*" }, encoding: "utf8", timeout: 30000 })
    assert.equal(result.status, 0, result.stdout + result.stderr)
    return JSON.parse(result.stdout)
  }
  try {
    let view = await request("/api/dashboard")
    assert.equal(view.status, 200)
    let candidate = view.body.candidates[0]
    assert.equal(candidate.status, "not_checked")
    assert.equal(candidate.cost_usd, null)
    assert.equal(candidate.publication_approved, false)
    const check = createCandidateCommand(candidate, "request_candidate_checks")
    assert.deepEqual(check.targets, [])
    assert.equal((await request("/api/drafts", check, "viewer")).status, 403)
    assert.equal((await request("/api/drafts", check)).status, 202)
    assert.equal((await request(`/api/drafts?commandId=${check.command_id}`)).body.status, "pending")
    assert.equal((await worker("consume", check.command_id)).candidate.outcome, "checks_requested")
    for (const stage of ["deterministic", "safety", "fact_check", "critic"]) {
      const result = await worker("stage", check.command_id, stage)
      assert.equal(result.outcome, "completed", JSON.stringify(result))
      candidate = (await request()).body.candidates[0]
      assert.equal(candidate.stages[stage], "passed")
    }
    assert.equal(candidate.required_checks_completed, true)
    const save = createCandidateCommand(candidate, "admit_checked_candidate")
    assert.equal((await request("/api/drafts", save)).status, 202)
    const saved = await worker("consume", save.command_id)
    assert.equal(saved.candidate.outcome, "candidate_admitted")
    let draft = (await request()).body.drafts.find((d) => d.id === saved.candidate.draft_id)
    assert.equal(draft.review_status, "passed")
    assert.equal(draft.review_kind, "model")
    assert.equal(draft.status, "pending")
    assert.equal(draft.approval_binding, undefined)
    assert.equal((await worker("consume", save.command_id)).state_version, saved.state_version)
    const approval = createDraftCommand(draft, "approve")
    assert.equal((await request("/api/drafts", approval, "publisher")).status, 202)
    assert.ok((await worker("consume", approval.command_id)).publish_intent_id)
    draft = (await request()).body.drafts.find((d) => d.id === draft.id)
    const edit = createDraftCommand(draft, "edit", { editedText: "Edited after required checks; a new review is required." })
    assert.equal((await request("/api/drafts", edit)).status, 202)
    assert.equal((await worker("consume", edit.command_id)).status, "applied")
    draft = (await request()).body.drafts.find((d) => d.id === draft.id)
    assert.equal(draft.review_status, "needs_revalidation")
    assert.equal(draft.approval_binding, undefined)
    assert.equal(draft.publish_intent_id, undefined)
  } finally {
    globalThis.fetch = actualFetch
    await new Promise((resolve) => server.close(resolve))
    delete process.env.THEHEAT_LOCAL_COMMAND_URL
  }
})
