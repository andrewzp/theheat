import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createServer } from "node:http"
import { Readable } from "node:stream"
import { spawnSync } from "node:child_process"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import SourcedGeneration, { generationCommand, WriterUsage } from "../app/components/SourcedGeneration.js"
import { createCandidateCommand, createDraftCommand } from "../lib/draft-command-request.js"

test("source chooser labels and reference-only command use the actual component", () => {
  const html = renderToStaticMarkup(createElement(SourcedGeneration, { readOnly: true }))
  assert.match(html, /Write from retained evidence/)
  assert.match(html, /for="generation-brief"/)
  assert.match(html, /aria-live="polite"/)
  const body = generationCommand({ brief_id: "a".repeat(64), brief_sha256: "a".repeat(64), expected_state_version: 0, expected_policy_sha256: "b".repeat(64), prompt: "untrusted", samples: 3 })
  assert.deepEqual(Object.keys(body.payload).sort(), ["brief_id", "brief_sha256", "expected_policy_sha256", "expected_state_version"])
  assert.equal(body.action, "request_sourced_generation")
  const usage = renderToStaticMarkup(createElement(WriterUsage, { usage: { counts: { input_tokens: 0, output_tokens: null } } }))
  assert.match(usage, /Input: 0 tokens; output: unknown; cache read: unknown/)
  assert.match(usage, /final charge unknown/)
})

test("actual source API -> separate batch/check workers -> admitted draft -> edit", { skip: !process.env.THEHEAT_GENERATION_TEST_CONFIG }, async () => {
  const configFile = process.env.THEHEAT_GENERATION_TEST_CONFIG
  const config = JSON.parse(readFileSync(configFile, "utf8"))
  const saved = { ...process.env }
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  const generate = await import("../app/api/generate/route.js")
  const drafts = await import("../app/api/drafts/route.js")
  const dashboard = await import("../app/api/dashboard/route.js")
  const actualFetch = globalThis.fetch
  globalThis.fetch = (url, options) => {
    assert.ok([config.endpoint, config.origin].includes(new URL(url).origin), "External network refused")
    return actualFetch(url, options)
  }
  const server = createServer(async (incoming, outgoing) => {
    try {
      const request = new Request(`${config.origin}${incoming.url}`, { method: incoming.method, headers: incoming.headers,
        ...(incoming.method === "POST" ? { body: Readable.toWeb(incoming), duplex: "half" } : {}) })
      const route = incoming.url.startsWith("/api/generate") ? generate : incoming.url.startsWith("/api/dashboard") ? dashboard : drafts
      const response = await route[incoming.method](request)
      outgoing.writeHead(response.status, Object.fromEntries(response.headers))
      outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch (error) { outgoing.writeHead(500); outgoing.end(JSON.stringify({ error: error.message })) }
  })
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(new URL(config.origin).port), "127.0.0.1", resolve) })
  async function request(path, command, role = "editor") {
    console.error("fixture request", path, command?.action || "read", role)
    const response = await actualFetch(config.origin + path, { method: command ? "POST" : "GET",
      headers: { Origin: config.origin, Authorization: `Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`, "Content-Type": "application/json" },
      ...(command ? { body: JSON.stringify(command) } : {}) })
    return { status: response.status, body: await response.json() }
  }
  function worker(operation, command) {
    console.error("fixture worker", operation)
    const result = spawnSync(config.python, [config.child, configFile, operation, command], { cwd: config.root,
      env: { PATH: process.env.PATH, PYTHONPATH: config.root, no_proxy: "*" }, encoding: "utf8", timeout: 30000 })
    assert.equal(result.status, 0, result.stdout + result.stderr)
    return JSON.parse(result.stdout)
  }
  try {
    assert.equal((await request("/api/generate", { prompt: "Invent a record" })).status, 400)
    const view = await request("/api/generate")
    assert.equal(view.status, 200, JSON.stringify(view.body))
    const start = generationCommand(view.body.briefs[0])
    assert.equal((await request("/api/generate", start, "viewer")).status, 403)
    const accepted = await request("/api/generate", start)
    assert.equal(accepted.status, 202, JSON.stringify(accepted.body))
    assert.deepEqual((await request("/api/generate", start)).body, accepted.body)
    assert.equal(worker("consume", start.command_id).status, "applied")
    assert.equal(worker("submit", start.command_id).outcome, "submitted")
    assert.equal(worker("collect", start.command_id).outcome, "reviewed")
    const usage = (await request("/api/generate")).body.briefs[0].writer_usage
    assert.equal(usage.counts.input_tokens, 17)
    assert.equal(usage.cost_usd, null)
    assert.equal(worker("capture", start.command_id).outcome, "candidate_ready")
    let state = (await request("/api/dashboard")).body
    assert.equal(state.candidates.length, 1)
    const availability = state.candidates[0].checks_available_at
    assert.ok(availability)
    assert.equal(worker("projection", start.command_id)[0].checks_available_at, availability)
    assert.equal((await request("/api/dashboard")).body.candidates[0].checks_available_at, availability)
    const early = createCandidateCommand(state.candidates[0], "request_candidate_checks")
    assert.equal((await request("/api/drafts", early)).status, 202)
    const refused = worker("consume", early.command_id)
    assert.equal(refused.status, "rejected")
    assert.equal(refused.code, "batch_lease_busy")
    const wait = Date.parse(availability) - Date.now() + 250
    assert.ok(wait > 0 && wait <= 60500, "Only the real bounded writer lease may delay checks")
    await new Promise(resolve => setTimeout(resolve, wait))
    state = (await request("/api/dashboard")).body
    assert.equal(state.candidates[0].checks_available_at, undefined)
    const check = createCandidateCommand(state.candidates[0], "request_candidate_checks")
    assert.equal((await request("/api/drafts", check)).status, 202)
    const requested = worker("consume", check.command_id)
    assert.equal(requested.status, "unchanged", JSON.stringify(requested))
    assert.equal(requested.candidate.outcome, "checks_requested")
    for (const stage of ["deterministic", "safety", "fact_check", "critic"]) assert.equal(worker(stage, check.command_id).outcome, "completed")
    state = (await request("/api/dashboard")).body
    const admit = createCandidateCommand(state.candidates[0], "admit_checked_candidate")
    assert.equal((await request("/api/drafts", admit)).status, 202)
    const admitted = worker("consume", admit.command_id)
    assert.equal(admitted.status, "applied")
    const draft = (await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === admitted.changed_ids[0])
    const edit = createDraftCommand(draft, "edit", { editedText: "Edited after sourced generation; review is required." })
    assert.equal((await request("/api/drafts", edit)).status, 202)
    assert.equal(worker("consume", edit.command_id).status, "applied")
    const final = (await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === draft.id)
    assert.equal(final.review_binding, undefined)
    assert.equal(final.approval_binding, undefined)
  } finally {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})
