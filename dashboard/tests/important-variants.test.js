import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { transformSync } from "next/dist/build/swc/index.js"
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createServer } from "node:http"
import { Readable } from "node:stream"
import { runFixtureWorker } from "../test-support/fixture-worker.js"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { generationCommand, GenerationRequest } from "../app/components/SourcedGeneration.js"
import { createCandidateCommand, createDraftCommand, localCommandEndpoint } from "../lib/draft-command-request.js"
import { projectDraft } from "../lib/draft-revisions.js"
import { draftReviewControls } from "../lib/draft-review-ui.js"

// Compile the actual JSX component and its local imports, using the already
// installed Next compiler. This loader is local to this test, with no hooks or
// production component substitutions.
const require = createRequire(import.meta.url)
const cache = new Map()
function component(filename) {
  if (filename.endsWith(".json")) return JSON.parse(readFileSync(filename, "utf8"))
  if (cache.has(filename)) return cache.get(filename).exports
  const module = { exports: {} }
  cache.set(filename, module)
  const code = transformSync(readFileSync(filename, "utf8"), {
    filename, jsc: { parser: { syntax: "ecmascript", jsx: true }, target: "es2022", transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" },
  }).code
  const localRequire = name => name.startsWith(".") ? component(resolve(dirname(filename), name)) : require(name)
  new Function("require", "module", "exports", code)(localRequire, module, module.exports)
  return module.exports
}
const { DraftWorkbench } = component(fileURLToPath(new URL("../app/components/DraftWorkbench.js", import.meta.url)))
test("actual workbench offers group admission and keeps absent scores unknown", () => {
  const row = { admission_input_id: "a".repeat(64), status: "checks_completed", text: "First returned angle.",
    important_slate: true, slate_can_admit: true, stages: {}, source: { type: "fire", event_id: "invented" } }
  const props = { drafts: [], localCandidates: [row], localRole: "editor", botRuns: [] }
  let html = renderToStaticMarkup(createElement(DraftWorkbench, props))
  assert.match(html, />Add checked important-event draft</)
  assert.doesNotMatch(html, />Add to local drafts<|>Validate and add to local drafts</)
  html = renderToStaticMarkup(createElement(DraftWorkbench, { ...props, localCandidates: [{ ...row, slate_can_admit: false }] }))
  assert.doesNotMatch(html, />Add checked important-event draft</)
  for (const change of [{ localRole: "viewer" }, { pendingCommand: { command: {} } }, { editingId: "other" }]) {
    html = renderToStaticMarkup(createElement(DraftWorkbench, { ...props, ...change }))
    assert.match(html, /disabled=""[^>]*>Add checked important-event draft</)
  }
  const draft = { id: "invented", text: "First returned angle.", status: "pending", local_preview: true,
    revision_identity: { draft_revision: 1, decision_revision: 1, content_hash: "a".repeat(64) },
    candidates: [{ rank: 1, text: "First returned angle.", score: null, source: "retained_important_writer" },
      { rank: 2, text: "Second returned angle.", score: null, source: "retained_important_writer" }] }
  html = renderToStaticMarkup(createElement(DraftWorkbench, { ...props, localCandidates: [], drafts: [draft] }))
  assert.match(html, /alt #2 · score unavailable/)
  assert.doesNotMatch(html, /copy 0/)
  assert.match(html, />Use This</)
})

test("important source and slate commands expose only immutable references", () => {
  const row = { execution_mode: "important_batch", brief_id: "a".repeat(64), brief_sha256: "a".repeat(64),
    allowance_id: "b".repeat(64), allowance_sha256: "b".repeat(64), expected_state_version: 2,
    expected_policy_sha256: "c".repeat(64), prompt: "forbidden", reserve_micro_usd: 1, samples: 3 }
  const request = generationCommand(row)
  assert.equal(request.action, "request_important_variants")
  assert.equal(localCommandEndpoint(request), "/api/generate")
  assert.deepEqual(Object.keys(request.payload).sort(), ["brief_id", "brief_sha256", "allowance_id", "allowance_sha256", "expected_state_version", "expected_policy_sha256"].sort())
  const rendered = renderToStaticMarkup(createElement(GenerationRequest, { brief: { ...row, status: "ready" } }))
  assert.match(rendered, /Request two important-event angles/)
  const slate = createCandidateCommand({ slate_id: "iv_" + "d".repeat(64), slate_sha256: "e".repeat(64),
    expected_state_version: 2, expected_policy_sha256: "c".repeat(64), expected_completion_set_sha256: "f".repeat(64),
    text: "forbidden", candidates: [{ passed: true }] }, "admit_checked_slate")
  assert.equal(localCommandEndpoint(slate), "/api/drafts")
  assert.deepEqual(Object.keys(slate.payload).sort(), ["slate_id", "slate_sha256", "expected_state_version", "expected_policy_sha256", "expected_completion_set_sha256"].sort())
})

test("actual important API -> two independently checked results -> exact retained selection", { skip: !process.env.THEHEAT_IMPORTANT_TEST_CONFIG }, async () => {
  const configFile = process.env.THEHEAT_IMPORTANT_TEST_CONFIG
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
  async function worker(operation, command) {
    console.error("fixture worker", operation)
    const result = await runFixtureWorker(config.python, [config.child, configFile, operation, command], { cwd: config.root,
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
    assert.equal((await worker("consume", start.command_id)).status, "applied")
    assert.equal((await worker("submit", start.command_id)).outcome, "submitted")
    assert.equal((await worker("collect", start.command_id)).outcome, "reviewed")
    const usage = (await request("/api/generate")).body.briefs[0].writer_usage
    assert.equal(usage.counts.input_tokens, 34)
    assert.equal(usage.cost_usd, null)
    assert.equal((await worker("capture", start.command_id)).outcome, "candidate_ready")
    let state = (await request("/api/dashboard")).body
    assert.equal(state.candidates.length, 2)
    const availability = state.candidates[0].checks_available_at
    assert.ok(availability)
    assert.equal((await worker("projection", start.command_id))[0].checks_available_at, availability)
    assert.equal((await request("/api/dashboard")).body.candidates[0].checks_available_at, availability)
    const early = createCandidateCommand(state.candidates[0], "request_candidate_checks")
    assert.equal((await request("/api/drafts", early)).status, 202)
    const refused = await worker("consume", early.command_id)
    assert.equal(refused.status, "rejected")
    assert.equal(refused.code, "batch_lease_busy")
    const wait = Date.parse(availability) - Date.now() + 250
    assert.ok(wait > 0 && wait <= 60500, "Only the real bounded writer lease may delay checks")
    await new Promise(resolve => setTimeout(resolve, wait))
    state = (await request("/api/dashboard")).body
    assert.equal(state.candidates[0].checks_available_at, undefined)
    const candidateIds = state.candidates.map(row => row.admission_input_id)
    for (const candidateId of candidateIds) {
      // Re-read after the first real enrollment/checks. Reusing the initial
      // array hid a sibling disabled by its own group's live shared lease.
      state = (await request("/api/dashboard")).body
      const row = state.candidates.find(item => item.admission_input_id === candidateId)
      assert.equal(row.status, "not_checked")
      assert.equal(row.checks_available_at, undefined)
      const html = renderToStaticMarkup(createElement(DraftWorkbench, {
        drafts: [], localCandidates: [row], localRole: "editor", botRuns: [],
      }))
      const checkButton = html.match(/<button\b[^>]*>Check candidate<\/button>/)?.[0]
      assert.ok(checkButton, "Actual projected candidate must render its real check control")
      assert.doesNotMatch(checkButton, /disabled/)
      const check = createCandidateCommand(row, "request_candidate_checks")
      assert.equal((await request("/api/drafts", check)).status, 202)
      const requested = await worker("consume", check.command_id)
      assert.equal(requested.status, "unchanged", JSON.stringify(requested))
      assert.equal(requested.candidate.outcome, "checks_requested")
      for (const stage of ["deterministic", "safety", "fact_check", "critic"]) {
        const checked = await worker(stage, check.command_id)
        assert.equal(checked.outcome, "completed", JSON.stringify(checked))
        assert.equal(checked.checks.stages[stage], "passed")
      }
    }
    state = (await request("/api/dashboard")).body
    const admittedRow = state.candidates.find(row => row.slate_can_admit)
    assert.ok(admittedRow, JSON.stringify(state.candidates))
    const admit = createCandidateCommand(admittedRow, "admit_checked_slate")
    assert.equal((await request("/api/drafts", admit)).status, 202)
    const admitted = await worker("consume", admit.command_id)
    assert.equal(admitted.status, "applied", JSON.stringify(admitted))
    assert.deepEqual(await worker("consume", admit.command_id), admitted)
    const draft = (await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === admitted.changed_ids[0])
    assert.equal(draft.candidates.length, 2)
    assert.ok(draft.review_binding)
    const alternate = draft.candidates.find(row => row.rank === 2)
    assert.equal(alternate.score, null)
    const select = createDraftCommand(draft, "select_candidate", { candidateRank: alternate.rank })
    assert.deepEqual(select.payload, { candidate_rank: 2, candidate_sha256: alternate.command_sha256 })
    assert.equal((await request("/api/drafts", select, "viewer")).status, 403)
    const selectionReceipt = await request("/api/drafts", select)
    assert.equal(selectionReceipt.status, 202)
    assert.equal((await worker("consume", select.command_id)).status, "applied")
    const final = (await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === draft.id)
    assert.equal(final.text, alternate.text)
    assert.equal(final.review_binding, undefined)
    assert.equal(final.approval_binding, undefined)
    assert.deepEqual(final.candidates, draft.candidates)
    assert.deepEqual((await request("/api/drafts", select)).body, selectionReceipt.body)
    assert.equal((await worker("consume", select.command_id)).status, "applied")
    const stale = createDraftCommand(draft, "select_candidate", { candidateRank: 1 })
    assert.equal((await request("/api/drafts", stale)).status, 202)
    assert.equal((await worker("consume", stale.command_id)).status, "rejected")
    assert.deepEqual(await worker("consume", admit.command_id), admitted)
    assert.equal((await request("/api/dashboard")).body.drafts.drafts.find(d => d.id === draft.id).review_binding, undefined)
  } finally {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
})


test("local attached-media summaries route to the joint panel without claiming its state", () => {
  for (const status of ["pending", "approved"]) {
    const draft = { ...projectDraft({ id: "invented-media", type: "fire", text: "Invented local draft.", status,
      media_attachment: { proposal_sha256: "a".repeat(64) } }), local_preview: true, operator_role: "publisher" }
    assert.equal(draft.review_status, "media_review_required")
    const html = renderToStaticMarkup(createElement(DraftWorkbench, { drafts: [draft], botRuns: [] }))
    assert.equal((html.match(/Text and graphic status/g) || []).length, 2)
    assert.match(html, /Publishing is unavailable\. See Text and graphic for current review status\./)
    assert.match(html, /Use Text and graphic for joint review, required checks and local approval status\./)
    assert.match(html, /aria-label="Local text and graphic review"/)
    assert.doesNotMatch(html, /graphic review needed|This graphic needs joint review|Joint graphic review is not available here yet|Approval parked for this text and graphic|All four required checks passed/)
    const controls = draftReviewControls(draft)
    assert.equal(controls.canReview, false)
    assert.equal(controls.canApprove, false)
    assert.equal(controls.canSchedule, false)
  }
})

test("production attached-media wording and text-only review guards remain unchanged", () => {
  const draft = projectDraft({ id: "invented-production", type: "fire", text: "Invented attached draft.", status: "pending",
    media_attachment: { proposal_sha256: "a".repeat(64) } })
  const html = renderToStaticMarkup(createElement(DraftWorkbench, { drafts: [draft], botRuns: [] }))
  assert.equal((html.match(/graphic review needed/g) || []).length, 2)
  assert.match(html, /Automatic scheduling is paused or unverified\. This graphic needs joint review\./)
  assert.match(html, /Joint graphic review is not available here yet\./)
  assert.doesNotMatch(html, /Text and graphic status|See Text and graphic|Use Text and graphic/)
  for (const key of ["canReview", "canApprove", "canSchedule"]) assert.equal(draftReviewControls(draft)[key], false)
})

test("local text-only and conflict summaries never acquire the attached-media routing label", () => {
  const base = { id: "invented-local", type: "fire", text: "Invented text-only draft.", status: "pending" }
  for (const raw of [base, { ...base, type: "rain", media_attachment: {} }, { ...base, media_attachment: {}, revision_conflicts: [{ reason: "invented conflict" }] }]) {
    const draft = { ...projectDraft(raw), local_preview: true, operator_role: "publisher" }
    const html = renderToStaticMarkup(createElement(DraftWorkbench, { drafts: [draft], botRuns: [] }))
    assert.doesNotMatch(html, /Text and graphic status|See Text and graphic|Use Text and graphic/)
    if (raw.revision_conflicts) {
      assert.equal(draft.review_status, "conflict")
      assert.match(html, /conflicting versions/)
    } else assert.equal(draft.review_status, raw.media_attachment ? "media_review_required" : "policy_unverified")
    assert.equal(draftReviewControls(draft).canApprove, false)
    assert.equal(draftReviewControls(draft).canSchedule, false)
  }
})
