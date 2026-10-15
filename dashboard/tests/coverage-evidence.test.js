import test from "node:test"
import assert from "node:assert/strict"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import CoverageEvidence, { CoverageAssessment, coverageCommand } from "../app/components/CoverageEvidence.js"

test("actual coverage component keeps unknown recall and disabled refresh without configuration", () => {
  const html = renderToStaticMarkup(createElement(CoverageEvidence, { readOnly: true }))
  assert.match(html, /Global event coverage is not yet measurable/)
  assert.match(html, /No saved assessment is available/)
  assert.match(html, /aria-live="polite"/)
  assert.match(html, /disabled=""[^>]*>Refresh assessment/)
  assert.doesNotMatch(html, /0%|100%|missed [0-9]|perfect coverage/i)
})

test("exact reference command cannot upload source, counts or human verdicts", () => {
  const body = coverageCommand({ set_id: "fixture-set", expected_set_sha256: "a".repeat(64), expected_state_version: 0,
    expected_policy_sha256: "b".repeat(64), human_reviewed: true, recall: 100, raw: "private" }, new Date("2026-10-12T01:00:00Z"))
  assert.equal(body.action, "evaluate_reference_coverage")
  assert.deepEqual(body.targets, [])
  assert.deepEqual(Object.keys(body.payload).sort(), ["expected_policy_sha256", "expected_set_sha256", "expected_state_version", "set_id"])
  assert.equal(body.expires_at, "2026-10-12T02:00:00.000Z")
})

test("retained stage display escapes labels and separates replay and source availability", () => {
  const assessment = { cutoff: "2026-10-12T01:00:00Z", evaluated_at: "2026-10-12T01:00:01Z", units: [{ unit_id: "fixture",
    source_label: "<script>private()</script>", reference_state: "held", holds: ["grouping_unresolved"],
    report_refs: [{ lineage_id: "report1" }], stages: [{ stage: "story_prepared", state: "recorded", execution_class: "archival_replay", reason_codes: [] },
      { stage: "draft_saved", state: "not_observed_in_retained_scope", execution_class: "retained_runtime", reason_codes: ["trace_missing"] }] }] }
  const html = renderToStaticMarkup(createElement(CoverageAssessment, { assessment, onOpenReport: () => {} }))
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
  assert.match(html, /archival replay/)
  assert.match(html, /Not in retained trace/)
  assert.match(html, /Source availability is shown separately/)
  assert.match(html, /Open evidence/)
  assert.doesNotMatch(html, /confirmed miss|0%/i)
})


test("historical recorded checks and saved drafts explicitly display superseded binding", () => {
  const assessment = { cutoff: "2026-10-12T01:00:00Z", evaluated_at: "2026-10-12T01:00:01Z", units: [{ unit_id: "fixture",
    source_label: "Invented agency", reference_state: "held", holds: [], report_refs: [], stages: [
      { stage: "checks_completed", state: "recorded", current_binding: "superseded", reason_codes: [] },
      { stage: "draft_saved", state: "recorded", current_binding: "superseded", reason_codes: [] },
      { stage: "source_input_retained", state: "recorded", current_binding: "current", reason_codes: [] },
      { stage: "physical_episode_detected", state: "not_observed_in_retained_scope", current_binding: "unresolved", reason_codes: [] }] }] }
  const html = renderToStaticMarkup(createElement(CoverageAssessment, { assessment }))
  assert.equal((html.match(/Superseded — historical evidence only/g) || []).length, 2)
  assert.match(html, /Checks completed<\/dt><dd>Recorded<span[^>]*>Superseded/)
  assert.match(html, /Draft saved<\/dt><dd>Recorded<span[^>]*>Superseded/)
  assert.match(html, /Current evidence binding/)
  assert.match(html, /Evidence binding unresolved/)
})

test("actual coverage HTTP/component command survives separate consumer and retry", { skip: !process.env.THEHEAT_COVERAGE_TEST_CONFIG }, async () => {
  const { readFileSync } = await import("node:fs")
  const { spawnSync } = await import("node:child_process")
  const { createServer } = await import("node:http")
  const { Readable } = await import("node:stream")
  const config = JSON.parse(readFileSync(process.env.THEHEAT_COVERAGE_TEST_CONFIG, "utf8"))
  const saved = { ...process.env }
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_PRODUCTION_PAUSED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = config.endpoint
  const coverage = await import("../app/api/coverage/route.js")
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
      const route = incoming.url.startsWith("/api/coverage") ? coverage : incoming.url.startsWith("/api/reports") ? reports : drafts
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
    const before = await request("/api/coverage", null, "viewer")
    assert.equal(before.status, 200, JSON.stringify(before.body))
    assert.equal(before.body.ready, true)
    assert.equal(before.body.reference_readiness.report_lineages, config.expected_reports)
    assert.equal(before.body.assessment, null)
    const reportsView = await request("/api/reports", null, "viewer")
    assert.equal(reportsView.status, 200)
    assert.equal(reportsView.body.reports.length, config.expected_reports)
    for (const report of before.body.reports) assert.ok(reportsView.body.reports.some(row => row.lineage_id === report.lineage_id))
    const command = coverageCommand(before.body)
    assert.equal((await request("/api/coverage", command, "viewer")).status, 403)
    assert.equal((await request("/api/coverage", command, "editor", { Origin: "https://invalid.test" })).status, 403)
    assert.equal((await request("/api/coverage", { ...command, payload: { ...command.payload, human_reviewed: true } })).status, 409)
    const accepted = await request("/api/coverage", command)
    assert.equal(accepted.status, 202, JSON.stringify(accepted.body))
    assert.deepEqual((await request("/api/coverage", command)).body, accepted.body)
    assert.equal((await request("/api/coverage", { ...command, payload: { ...command.payload, expected_set_sha256: "f".repeat(64) } })).status, 409)
    assert.equal((await request(`/api/drafts?commandId=${command.command_id}`)).body.status, "pending")
    const pendingView = await request("/api/coverage")
    assert.equal(pendingView.body.pending_command.command_id, command.command_id)
    const result = consume(command.command_id)
    assert.equal(result.status, "applied", JSON.stringify(result))
    assert.deepEqual(result.changed_ids, [])
    assert.equal(result.state_version, 0)
    assert.equal(result.coverage.draft_mutated, false)
    assert.equal(result.coverage.provider_request_created, false)
    assert.deepEqual(consume(command.command_id), result)
    const after = await request("/api/coverage")
    assert.equal(after.body.assessment.cutoff, accepted.body.receipt.accepted_at)
    assert.equal(after.body.assessment.reference_readiness.report_lineages, config.expected_reports)
    assert.equal(after.body.assessment.reference_readiness.human_decisions_recorded, 0)
    assert.equal(after.body.assessment.metrics.event_recall, null)
    assert.equal(after.body.assessment.metrics.confirmed_misses, null)
    assert.ok(after.body.assessment.units.every(unit => unit.reference_state === "pending"))
    assert.equal(after.body.pending_command, null)
    const html = renderToStaticMarkup(createElement(CoverageEvidence, { initialView: after.body, onOpenReport: () => {} }))
    assert.match(html, /Global event coverage is not yet measurable/)
    assert.match(html, /Open evidence/)
    assert.doesNotMatch(html, /0%|100%|missed [0-9]/i)
    process.env.NODE_ENV = "production"
    assert.equal((await request("/api/coverage")).status, 503)
    delete process.env.THEHEAT_LOCAL_COMMAND_URL
    assert.equal((await request("/api/coverage")).status, 503)
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve))
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})
