import test from "node:test"
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"
import path from "node:path"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { importFresh } from "./helpers/import-fresh.js"
import { ProductHealthPanel } from "../app/components/ProductHealthPanel.js"
import { initializeRevision, policy, recordHumanReview, reviewIsCurrent } from "./helpers/review-policy.js"
import { projectRecoveredRecord, projectRecoveredState } from "../lib/recovery-continuity.js"
import RecoveredRecord from "../app/components/RecoveredRecord.js"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
let journey
function run() {
  if (journey) return journey
  const python = process.env.THEHEAT_TEST_PYTHON || "python3"
  const child = spawnSync(python, ["-I", path.join(root, "tests/remaining_campaign/w14_journey_child.py")], { cwd: root, encoding: "utf8",
    env: { PATH: process.env.PATH || "/usr/bin:/bin", HOME: process.env.HOME || "/tmp", LC_ALL: "C", TZ: "UTC" } })
  assert.equal(child.status, 0, child.stderr)
  journey = JSON.parse(child.stdout)
  return journey
}
const draftOf = (state, id) => state.drafts.find(d => d.id === id)

test("fresh-process journey output is readable on every surface with exact history", () => {
  const { state, provenance, journey: steps } = run()
  assert.deepEqual(steps.find(s => s.step === "cancel_delivered"), { step: "cancel_delivered", result: "refused", code: "delivered_content_retained" })
  const published = projectRecoveredRecord(draftOf(state, "w14j-delivered"), state, { surface: "published" })
  assert.equal(published.delivered.tweet_id, "1900000000000004242")
  assert.equal(published.delivered.text, state.publish_ledger["w14j-ev-delivered"].text)
  assert.deepEqual(published.actions, ["feedback"])
  assert.ok(published.holds.some(h => h.action === "retry" && h.code === "already_delivered"))
  assert.deepEqual(published.history.filter(h => h.kind === "attempt").map(h => h.entry.phase), ["confirmed"])
  const operations = projectRecoveredRecord(draftOf(state, "w14j-cancelled"), state, { surface: "operations" })
  assert.equal(operations.attempt.cancelled, true); assert.equal(operations.attempt.phase, "unknown")
  assert.deepEqual(operations.actions, [])
  assert.ok(operations.holds.some(h => h.code === "unknown_delivery_never_retried"))
  assert.ok(operations.holds.some(h => h.code === "intent_cancelled"))
  const imported = projectRecoveredState(state, { surface: "editor", provenance })
  for (const record of imported) {
    assert.equal(record.provenance.kind, "imported"); assert.equal(record.review_current, false); assert.deepEqual(record.actions, [])
    assert.ok(record.holds.some(h => h.action === "approve" && h.code === "imported_review_not_current"))
  }
  const importedOps = projectRecoveredState(state, { surface: "operations", provenance })
  assert.ok(importedOps.every(record => !record.actions.length))
  assert.equal(importedOps.find(r => r.draft_id === "w14j-delivered").delivered.text, state.publish_ledger["w14j-ev-delivered"].text)
})

test("an old successful review is never current merely because its bytes were imported", () => {
  const draft = { id: "w14j-review", event_id: "w14j-ev-review", status: "pending", text: "Invented Fallow Mere reached 40 C.",
    review_context: { two_bot: { bundle: { event_id: "w14j-ev-review", current_facts: [{ label: "place", value: "Fallow Mere" }] } } } }
  initializeRevision(draft); recordHumanReview(draft)
  assert.equal(reviewIsCurrent(draft), true)
  const state = { drafts: [draft], publish_ledger: {} }
  assert.equal(projectRecoveredRecord(draft, state, { surface: "editor", policy }).review_current, true)
  const imported = projectRecoveredRecord(draft, state, { surface: "editor", policy, provenance: { "w14j-review": { origin: "import", import_id: "w14j-import" } } })
  assert.equal(imported.review_current, false); assert.deepEqual(imported.actions, [])
  const superseded = projectRecoveredRecord(draft, state, { surface: "editor", provenance: { "w14j-review": { origin: "superseded", superseded_by: "w14j-newer" } } })
  assert.deepEqual(superseded.actions, []); assert.ok(superseded.holds.every(h => h.code === "superseded_by_newer_revision"))
})

test("continuity component renders provenance, delivered original and holds only", () => {
  const { state, provenance } = run()
  const record = projectRecoveredRecord(draftOf(state, "w14j-delivered"), state, { surface: "editor", provenance })
  const html = renderToStaticMarkup(React.createElement(RecoveredRecord, { record }))
  assert.match(html, /Imported history \(read-only\)/)
  assert.match(html, /An imported review is not a current review/)
  assert.match(html, /data-tweet="1900000000000004242"/)
  assert.doesNotMatch(html, /<button/)
})

// ---- W14.6 provenance channel: import journal -> local preview /state -> /api/dashboard -> editor/Published.
// tests/remaining_campaign/w14_provenance_child.py imports an invented snapshot through the real
// importer, then the real Python preview handler answers GET /state with recovery_provenance.
let provenanceRun
function provenanceChild() {
  if (provenanceRun) return provenanceRun
  const python = process.env.THEHEAT_TEST_PYTHON || "python3"
  const child = spawnSync(python, ["-I", path.join(root, "tests/remaining_campaign/w14_provenance_child.py")], { cwd: root, encoding: "utf8",
    env: { PATH: process.env.PATH || "/usr/bin:/bin", HOME: process.env.HOME || "/tmp", LC_ALL: "C", TZ: "UTC" } })
  assert.equal(child.status, 0, child.stderr)
  provenanceRun = JSON.parse(child.stdout)
  return provenanceRun
}

// Compile the actual JSX workbench with the installed Next compiler (no substitutions).
const requireModule = createRequire(import.meta.url)
const compiled = new Map()
function component(filename) {
  if (filename.endsWith(".json")) return JSON.parse(readFileSync(filename, "utf8"))
  if (compiled.has(filename)) return compiled.get(filename).exports
  const module = { exports: {} }
  compiled.set(filename, module)
  const code = transformSync(readFileSync(filename, "utf8"), {
    filename, jsc: { parser: { syntax: "ecmascript", jsx: true }, target: "es2022", transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" },
  }).code
  const localRequire = name => name.startsWith(".") ? component(path.resolve(path.dirname(filename), name)) : requireModule(name)
  new Function("require", "module", "exports", code)(localRequire, module, module.exports)
  return module.exports
}
const { DraftWorkbench } = component(fileURLToPath(new URL("../app/components/DraftWorkbench.js", import.meta.url)))

async function withEnvironment(values, fetchImpl, run) {
  const saved = { ...process.env }
  const actualFetch = globalThis.fetch
  Object.assign(process.env, values)
  globalThis.fetch = fetchImpl
  try { return await run() } finally {
    globalThis.fetch = actualFetch
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved, key)) delete process.env[key]
    Object.assign(process.env, saved)
  }
}

async function localDashboard(reply) {
  const calls = []
  const payload = await withEnvironment({ NODE_ENV: "test", DASHBOARD_AUTH_DISABLED: "1", THEHEAT_LOCAL_COMMAND_URL: "http://127.0.0.1:3999" },
    async (url) => { calls.push(String(url)); return new Response(JSON.stringify(reply), { status: 200, headers: { "Content-Type": "application/json" } }) },
    async () => {
      const { GET } = await importFresh("app/api/dashboard/route.js")
      const response = await GET(new Request("http://127.0.0.1:3033/api/dashboard?limit=50", { headers: {
        host: "127.0.0.1:3033", authorization: "Basic " + Buffer.from("w14p-publisher:invented-w14p-password").toString("base64") } }))
      return { status: response.status, body: await response.json() }
    })
  return { ...payload, calls }
}

const workbench = (drafts, selectedDraftId) => renderToStaticMarkup(React.createElement(DraftWorkbench, {
  drafts, selectedDraftId, setSelectedDraftId() {}, localRole: "publisher", botRuns: [], editText: "", draftAct() {}, startEditing() {} }))

test("the real route projects the journal's imported records read-only with their import id", async () => {
  const { reply, source_sha256: sha } = provenanceChild()
  const { status, body, calls } = await localDashboard(reply)
  assert.equal(status, 200, JSON.stringify(body))
  assert.deepEqual(calls, ["http://127.0.0.1:3999/state"])
  const drafts = Object.fromEntries(body.drafts.drafts.map(d => [d.id, d]))
  assert.deepEqual(Object.keys(drafts).sort(), ["w14p-edited", "w14p-fresh", "w14p-held"])
  const held = drafts["w14p-held"].recovery
  assert.deepEqual(held.provenance, { kind: "imported", import_id: "w14p-import", source_sha256: sha })
  assert.equal(held.surface, "editor"); assert.equal(held.review_current, false); assert.deepEqual(held.actions, [])
  assert.ok(held.holds.some(h => h.action === "approve" && h.code === "imported_review_not_current"))
  // Imported bytes carry a passed review, yet the record stays history: the hold, not the pill, decides.
  assert.equal(drafts["w14p-held"].review_status, "passed")
  assert.equal(drafts["w14p-edited"].recovery.provenance.kind, "imported")
  assert.deepEqual(drafts["w14p-edited"].recovery.actions, [])
  assert.equal(Object.hasOwn(drafts["w14p-fresh"], "recovery"), false)
  assert.equal(body.recoveredPublished.length, 1)
  const [posted] = body.recoveredPublished
  assert.equal(posted.draft_id, "w14p-posted"); assert.equal(posted.surface, "published")
  assert.equal(posted.provenance.import_id, "w14p-import"); assert.equal(posted.delivered.tweet_id, "1900000000000005151")
  assert.ok(posted.holds.some(h => h.action === "retry" && h.code === "imported_record_read_only"))
})

test("editor shows an imported record read-only without edit, review or approve controls", async () => {
  const { body } = await localDashboard(provenanceChild().reply)
  const drafts = body.drafts.drafts
  const imported = workbench(drafts, "w14p-held")
  assert.match(imported, /Imported history \(read-only\)<\/strong> · w14p-import/)
  assert.match(imported, /An imported review is not a current review/)
  assert.match(imported, /<span class="workbench-pill">Imported history \(read-only\)<\/span>/)
  for (const control of [/>Approve locally</, />Edit</, />Reject</, />Record human review</, />Use This</, /class="draft-actions"/])
    assert.doesNotMatch(imported, control)
  assert.match(workbench(drafts, "w14p-edited"), /Imported history \(read-only\)/)
  for (const id of ["w14p-fresh"]) {
    const current = workbench(drafts, id)
    const detail = current.slice(current.indexOf('<div class="draft-workbench">'))
    assert.match(detail, new RegExp(`<strong>w14p-ev-${id.slice(5)}</strong>`))
    assert.doesNotMatch(detail, /recovered-record|read-only\)/)
    assert.match(detail, />Approve locally</); assert.match(detail, />Edit</)
  }
})

test("Published shows the imported delivered record beside outcomes and nothing when all records are current", async () => {
  const { body } = await localDashboard(provenanceChild().reply)
  const panel = recovered => renderToStaticMarkup(React.createElement(ProductHealthPanel, { health: body.productHealth, recovered }))
  const html = panel(body.recoveredPublished)
  assert.match(html, /Recovered published history/)
  assert.match(html, /Imported history \(read-only\)<\/strong> · w14p-import/)
  assert.match(html, /data-tweet="1900000000000005151"/)
  const section = html.slice(html.indexOf('aria-label="Recovered published history"'))
  assert.doesNotMatch(section.slice(0, section.indexOf("</section>")), /<button|<a /)
  const without = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health: body.productHealth }))
  assert.equal(panel([]), without); assert.equal(panel(undefined), without)
  assert.doesNotMatch(without, /recovered-record|Recovered published history/)
  assert.equal(renderToStaticMarkup(React.createElement(RecoveredRecord, { record: projectRecoveredRecord(
    { id: "w14p-now", status: "posted", text: "Invented current." }, { publish_ledger: {} }, { surface: "published" }) })), "")
})

test("an unconfigured journal keeps every record current and a malformed map refuses the read", async () => {
  const { reply } = provenanceChild()
  const empty = await localDashboard({ ...reply, recovery_provenance: {} })
  assert.equal(empty.status, 200)
  assert.ok(empty.body.drafts.drafts.every(d => !Object.hasOwn(d, "recovery")))
  assert.deepEqual(empty.body.recoveredPublished, [])
  const { recovery_provenance: _omitted, ...older } = reply
  assert.deepEqual((await localDashboard(older)).body.recoveredPublished, [])
  for (const bad of [[], { "w14p-held": { origin: "import" } }, { "w14p-held": { origin: "current" } }, { "w14p-held": null }]) {
    const refused = await localDashboard({ ...reply, recovery_provenance: bad })
    assert.equal(refused.status, 503); assert.equal(refused.body.code, "recovery_provenance_invalid")
  }
})

test("the production Gist path never carries provenance, recovery views or recovered Published records", async () => {
  const { reply } = provenanceChild()
  const gist = { ok: true, status: 200, async json() { return { files: { "state.json": { content: JSON.stringify(reply.state) } } } },
    async text() { return JSON.stringify(reply.state) } }
  const runs = { ok: true, status: 200, async json() { return { workflow_runs: [] } }, async text() { return "{}" } }
  const body = await withEnvironment({ NODE_ENV: "production", DASHBOARD_USERNAME: "reviewer", DASHBOARD_PASSWORD: "invented-pass",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "gist_w14p", GITHUB_TOKEN: "invented-token" },
  async (url) => String(url).includes("/actions/runs") ? runs : gist, async () => {
    const { GET } = await importFresh("app/api/dashboard/route.js")
    const response = await GET(new Request("http://localhost/api/dashboard", { headers: { authorization: "Basic " + Buffer.from("reviewer:invented-pass").toString("base64") } }))
    assert.equal(response.status, 200)
    return response.json()
  })
  assert.ok(body.drafts.drafts.length > 0)
  assert.ok(body.drafts.drafts.every(d => !Object.hasOwn(d, "recovery")))
  assert.equal(Object.hasOwn(body, "recoveredPublished"), false)
})
