import test from "node:test"
import assert from "node:assert/strict"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ReportsForReview, { ReportDetail, reportCommand } from "../app/components/ReportsForReview.js"

test("actual report component opens evidence review without promising a draft", () => {
  const html = renderToStaticMarkup(createElement(ReportsForReview, { readOnly: true }))
  assert.match(html, /Reports needing evidence/)
  assert.match(html, /for="report-choice"/)
  assert.match(html, /aria-live="polite"/)
  assert.match(html, /Open evidence/)
  assert.doesNotMatch(html, /Request draft/)
})

test("report command is exact references only and cannot carry claims or verdicts", () => {
  const report = { lineage_id: "fixture:report", report_sha256: "a".repeat(64), expected_policy_sha256: "b".repeat(64),
    episode_reference: null, facts: "untrusted", human_reviewed: true, cost: 0 }
  const body = reportCommand(report, new Date("2026-10-11T12:00:00Z"))
  assert.equal(body.action, "open_report_evidence")
  assert.deepEqual(body.targets, [])
  assert.deepEqual(Object.keys(body.payload).sort(), ["episode_reference", "expected_policy_sha256", "lineage_id", "report_sha256"])
  assert.equal(body.expires_at, "2026-10-11T13:00:00.000Z")
})

test("source wording is escaped, translation remains unreviewed and unknown time stays unknown", () => {
  const report = { claims: [{ claim_id: "claim1", summary: "Invented report", kind: "forecast", attribution: "Invented agency",
    original_language: "pt", excerpts: [{ text: '<script>fetch("https://invalid.test")</script>' }],
    translation: { text: "Invented interpretation", status: "unreviewed" }, times: {}, holds: ["translation_review_pending"] }] }
  const html = renderToStaticMarkup(createElement(ReportDetail, { report }))
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
  assert.match(html, /Translation \(unreviewed\)/)
  assert.match(html, /Unknown/)
  assert.match(html, /<details><summary>Original source wording/)
})


test("actual report HTTP and component command survive separate consumer and exact retry", { skip: !process.env.THEHEAT_REPORT_TEST_CONFIG }, async () => {
  const { readFileSync } = await import("node:fs")
  const { spawnSync } = await import("node:child_process")
  const { createServer } = await import("node:http")
  const { Readable } = await import("node:stream")
  const config = JSON.parse(readFileSync(process.env.THEHEAT_REPORT_TEST_CONFIG, "utf8"))
  const saved = { ...process.env }
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_PRODUCTION_PAUSED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  const reports = await import("../app/api/reports/route.js")
  const drafts = await import("../app/api/drafts/route.js")
  const { localPreviewGuard } = await import("../lib/local-preview-boundary.js")
  const actualFetch = globalThis.fetch
  globalThis.fetch = (url, options) => {
    assert.ok([config.endpoint, config.origin].includes(new URL(url).origin), "External network refused")
    return actualFetch(url, options)
  }
  const server = createServer(async (incoming, outgoing) => {
    try {
      const request = new Request(`${config.origin}${incoming.url}`, { method: incoming.method, headers: incoming.headers,
        ...(incoming.method === "POST" ? { body: Readable.toWeb(incoming), duplex: "half" } : {}) })
      const route = incoming.url.startsWith("/api/reports") ? reports : drafts
      const response = localPreviewGuard(request) || await route[incoming.method](request)
      outgoing.writeHead(response.status, Object.fromEntries(response.headers))
      outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch (error) { outgoing.writeHead(500); outgoing.end(JSON.stringify({ error: error.message })) }
  })
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(Number(new URL(config.origin).port), "127.0.0.1", resolve) })
  async function request(path, command, role = "editor", extras = {}) {
    const response = await actualFetch(config.origin + path, { method: command ? "POST" : "GET", headers: {
      Origin: config.origin, Authorization: `Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`,
      "Content-Type": "application/json", ...extras }, ...(command ? { body: JSON.stringify(command) } : {}) })
    assert.match(response.headers.get("cache-control"), /no-store/)
    const text = await response.text()
    return { status: response.status, body: response.headers.get("content-type")?.includes("application/json") ? JSON.parse(text) : text }
  }
  function consume(command) {
    const result = spawnSync(config.python, ["-m", "src.commands.preview_worker", ...config.arguments, "--command-id", command],
      { cwd: config.root, env: { PATH: process.env.PATH, PYTHONPATH: config.root, no_proxy: "*" }, encoding: "utf8", timeout: 30000 })
    assert.equal(result.status, 0, result.stdout+result.stderr)
    return JSON.parse(result.stdout).result
  }
  try {
    const view = await request("/api/reports", null, "viewer")
    assert.equal(view.status, 200, JSON.stringify(view.body))
    for (const entry of view.body.reports) {
    const command = reportCommand(entry)
    assert.equal((await request("/api/reports", command, "viewer")).status, 403)
    assert.equal((await request("/api/reports", command, "editor", { Origin: "https://invalid.test" })).status, 403)
    assert.equal((await request("/api/reports", { ...command, payload: { ...command.payload, human_reviewed: true } })).status, 409)
    const accepted = await request("/api/reports", command)
    assert.equal(accepted.status, 202, JSON.stringify(accepted.body))
    assert.deepEqual((await request("/api/reports", command)).body, accepted.body)
    assert.equal((await request("/api/reports", { ...command, payload: { ...command.payload, report_sha256: "f".repeat(64) } })).status, 409)
    assert.equal((await request(`/api/drafts?commandId=${command.command_id}`)).body.status, "pending")
    const result = consume(command.command_id)
    assert.equal(result.status, "applied", JSON.stringify(result))
    assert.equal(result.state_version, 0)
    assert.deepEqual(result.changed_ids, [])
    assert.equal(result.report_development.draft_mutated, false)
    assert.equal(result.report_development.provider_request_created, false)
    assert.deepEqual(consume(command.command_id), result)
    assert.deepEqual((await request(`/api/drafts?commandId=${command.command_id}`)).body.result, result)
    const opened = (await request("/api/reports")).body.reports.find(row => row.lineage_id === entry.lineage_id)
    assert.equal(opened.development_status, "evidence_review_required")
    assert.equal(!!opened.related_story, config.linked)
    assert.equal(opened.generation_available, false)
    const html = renderToStaticMarkup(createElement(ReportDetail, { report: opened }))
    assert.match(html, /evidence review required/)
    const repeat = reportCommand(opened)
    assert.equal((await request("/api/reports", repeat)).status, 202)
    const reused = consume(repeat.command_id)
    assert.equal(reused.report_development.reused, true)
    assert.equal(reused.report_development.item_sha256, result.report_development.item_sha256)
    }
    process.env.NODE_ENV = "production"
    assert.equal((await request("/api/reports")).status, 503)
    delete process.env.THEHEAT_LOCAL_COMMAND_URL
    assert.equal((await request("/api/reports")).status, 503)
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve))
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})
