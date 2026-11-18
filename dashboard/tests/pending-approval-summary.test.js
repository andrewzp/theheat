/** Invented saved decisions through the real automation reader and actual strip. */
import test, { afterEach } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { policy, runtimeRun, initializeRevision, recordModelReview, recordHumanReview,
  authorizeDraft, revokeApproval, fingerprint, textHash } from "./helpers/review-policy.js"
import * as presentation from "../lib/automation-status.js"
import { importFresh } from "./helpers/import-fresh.js"

const EPOCH = "invented-pending-release"
const keys = ["GITHUB_TOKEN", "GIST_ID", "STATE_BACKEND", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH",
  "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH"]
const originalEnv = Object.fromEntries(keys.map(key => [key, process.env[key]]))
const originalFetch = global.fetch
afterEach(() => {
  global.fetch = originalFetch
  for (const key of keys) {
    if (originalEnv[key] === undefined) delete process.env[key]
    else process.env[key] = originalEnv[key]
  }
})

function configure() {
  process.env.GITHUB_TOKEN = "invented-no-access"
  process.env.GIST_ID = "invented-pending-store"
  process.env.STATE_BACKEND = process.env.THEHEAT_STATE_BACKEND = "gist"
  delete process.env.THEHEAT_DB_PATH
  process.env.THEHEAT_AUTOMATIC_PUBLICATION_ENABLED = "1"
  process.env.THEHEAT_AUTOMATIC_PUBLICATION_EPOCH = EPOCH
}

function draft(id = "invented-one", mode = "auto") {
  configure()
  const d = initializeRevision({ id, event_id: id, type: "observed_metar_contrast", status: "pending",
    text: "Invented airport comparison.", review_context: { two_bot: {
      bundle: { signal_kind: "observed_metar_contrast", value: 65 },
      fact_check: { passed: true }, critic: { passed: true },
    } }, approval_policy: { mode: "armed_auto", can_auto_approve: true } })
  const proof = d.review_context.two_bot
  proof.reviewed_policy_sha256 = fingerprint(policy)
  proof.reviewed_text_sha256 = textHash(d.text)
  proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
  if (mode === "auto") recordModelReview(d)
  else recordHumanReview(d)
  authorizeDraft(d, mode, null, mode === "auto" ? EPOCH : null)
  d.approval_mode = mode
  d.status = mode === "auto" ? "pending" : "approved"
  if (mode === "auto") {
    d.auto_approve_at = new Date(Date.now() + 60_000).toISOString()
    d.autoship_on_critic_pass = true
  }
  return d
}

function state(drafts = []) {
  const run = runtimeRun(new Date(Date.now() - 1000).toISOString())
  run.runtime_inventory.flags = { automatic_publication_enabled: true, automatic_publication_epoch: EPOCH }
  return { drafts, run_history: [run], publication_control: { retired_epochs: [] }, publish_ledger: {} }
}

function wire(saved, { failRead = false, runtimeReport = null } = {}) {
  configure()
  const calls = []
  global.fetch = async (input, init) => {
    const url = new URL(input)
    assert.equal(url.origin, "https://api.github.com")
    assert.equal(init?.method || "GET", "GET", "Counts cannot mutate or dispatch")
    calls.push(url)
    let body
    if (url.pathname === "/gists/invented-pending-store") {
      if (failRead) return { ok: false, status: 503, text: async () => "invented read failure" }
      body = { files: { "state.json": { content: JSON.stringify(saved), truncated: false },
        ...(runtimeReport ? { "runtime-inventory.json": { content: JSON.stringify(runtimeReport), truncated: false } } : {}) } }
    } else if (url.pathname.endsWith("/runs")) body = { workflow_runs: [] }
    else if (url.pathname.includes("/actions/workflows/")) body = { state: "active" }
    else if (url.pathname.endsWith("/THEHEAT_PRODUCTION_PAUSED")) body = { value: "0" }
    else if (url.pathname.includes("/actions/variables/")) return { ok: false, status: 404 }
    else assert.fail("Unowned request: " + url.pathname)
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) }
  }
  return calls
}

async function read(saved, options) {
  const calls = wire(saved, options), before = structuredClone(saved)
  const module = await importFresh("lib/automation.js")
  const result = await module.getAutomationStatus()
  assert.deepEqual(saved, before)
  assert.equal(calls.filter(url => url.pathname.startsWith("/gists/")).length, 1)
  assert.equal(calls.filter(url => url.pathname.endsWith("/runs")).length, 5)
  return result
}

// Reuse the existing test-local Next compiler pattern; load the actual strip
// and all real local imports, with no production component substitutions.
const require = createRequire(import.meta.url), modules = new Map()
function component(filename) {
  if (modules.has(filename)) return modules.get(filename).exports
  const module = { exports: {} }
  modules.set(filename, module)
  const code = transformSync(readFileSync(filename, "utf8"), {
    filename, jsc: { parser: { syntax: "ecmascript", jsx: true }, target: "es2022", transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" },
  }).code
  new Function("require", "module", "exports", code)(name => name.startsWith(".") ? component(resolve(dirname(filename), name)) : require(name), module, module.exports)
  return module.exports
}
const { AutomationStatusStrip } = component(fileURLToPath(new URL("../app/components/AutomationStrip.js", import.meta.url)))
const html = status => renderToStaticMarkup(createElement(AutomationStatusStrip, { status }))

test("revoked source-held policy recommendation is attention, never an automatic approval in the actual strip", async () => {
  const d = draft()
  revokeApproval(d)
  d.post_error = "Observed airport report needs fresh source review: awc_transport_timeout"
  const result = await read(state([d]))
  assert.equal(result.posting_mode_summary.armed_auto_count, 1) // Legacy route recommendation retained.
  assert.match(html(result), /1 need(?:s)? attention/)
  assert.doesNotMatch(html(result), /1 auto(?:-approved| scheduled| \/)/)
  assert.equal(result.posting_mode_summary_basis, "policy_recommendations")
  assert.equal(result.posting_state_summary.attention_required_count, 1)
  assert.equal(result.posting_state_summary.auto_scheduled_count, 0)
})

test("real current automatic and manual bindings are distinct from attention and unresolved sends", async () => {
  const auto = draft("auto"), manual = draft("manual", "manual"), held = draft("held"), unresolved = draft("unknown")
  revokeApproval(held)
  const saved = state([auto, manual, held, unresolved, { id: "posted", status: "posted" }, { id: "rejected", status: "rejected" }])
  saved.publish_ledger[unresolved.event_id] = { phase: "submitted" }
  const result = await read(saved)
  assert.deepEqual(Object.fromEntries(["pending_count", "attention_required_count", "auto_scheduled_count", "manual_approved_count", "unresolved_send_count"].map(k => [k, result.posting_state_summary[k]])),
    { pending_count: 4, attention_required_count: 1, auto_scheduled_count: 1, manual_approved_count: 1, unresolved_send_count: 1 })
  assert.equal(result.posting_state_summary.status, "recorded")
  assert.match(html(result), /1 auto-approved/)
  assert.match(html(result), /1 manually approved/)
  assert.match(html(result), /1 unresolved send/)
  assert.doesNotMatch(html(result), /ready to post|source verified/i)
})

for (const [name, change] of [
  ["text changed", d => { d.text += " Changed." }],
  ["check changed", d => { d.review_context.two_bot.critic.passed = false }],
  ["review missing", d => { delete d.review_binding }],
  ["approval revoked", d => { revokeApproval(d) }],
  ["old epoch", d => { d.approval_binding.publication_epoch = "invented-retired-release" }],
  ["wrong mode", d => { d.approval_mode = "manual" }],
  ["route refuses", d => { d.approval_policy.can_auto_approve = false }],
  ["missing deadline", d => { delete d.auto_approve_at }],
  ["invalid deadline", d => { d.auto_approve_at = "2026-02-30T00:00:00Z" }],
  ["missing autoship intent", d => { delete d.autoship_on_critic_pass }],
]) test(`stored ${name} cannot borrow automatic authorization from its policy route`, async () => {
  const d = draft(); change(d)
  const result = await read(state([d]))
  assert.equal(result.posting_state_summary.auto_scheduled_count, 0)
  assert.equal(result.posting_state_summary.attention_required_count, 1)
})

for (const [name, change] of [
  ["missing", s => { s.run_history = [] }],
  ["stale", s => { const at = new Date(Date.now() - 8 * 3600_000).toISOString(); s.run_history[0].started_at = s.run_history[0].runtime_inventory.captured_at = at }],
  ["different policy", s => { s.run_history[0].runtime_inventory.editorial_policy.source_sha256 = "0".repeat(64) }],
  ["retired epoch", s => { s.publication_control.retired_epochs = [EPOCH] }],
  ["automatic release off", s => { s.run_history[0].runtime_inventory.flags.automatic_publication_enabled = false }],
]) test(`${name} runtime or release cannot establish an automatic schedule`, async () => {
  const saved = state([draft()]); change(saved)
  const result = await read(saved)
  assert.equal(result.posting_state_summary.auto_scheduled_count, 0)
  assert.equal(result.posting_state_summary.attention_required_count, 1)
})

for (const [name, change] of [
  ["unknown outcome", (d, s) => { d.publish_outcome = "unknown" }],
  ["submitted outcome", (d, s) => { d.publish_outcome = "submitted" }],
  ["contradictory attempts", (d, s) => { s.publish_ledger[d.event_id] = { phase: "not_sent", attempt_conflicts: [{ phase: "submitted" }] } }],
]) test(`${name} stays an unresolved send, ahead of review or approval labels`, async () => {
  const d = draft(), saved = state([d]); change(d, saved)
  const result = await read(saved)
  assert.equal(result.posting_state_summary.unresolved_send_count, 1)
  assert.equal(result.posting_state_summary.auto_scheduled_count, 0)
})

test("empty and unreadable snapshots remain distinct without extra state reads", async () => {
  const empty = await read(state())
  assert.equal(empty.posting_state_summary.status, "recorded")
  assert.equal(empty.posting_state_summary.pending_count, 0)
  const failed = await read(state(), { failRead: true })
  assert.equal(failed.posting_state_summary, null)
  assert.match(html(failed), /Saved approvals unavailable/)
})

test("configuration-only evidence from the same Gist read can verify manual approval but never automatic scheduling", async () => {
  const saved = state([draft("automatic"), draft("manual", "manual")])
  saved.run_history = []
  const at = new Date(Date.now() - 1000).toISOString()
  const runtimeReport = { schema_version: 1, kind: "configuration_only", id: "config-123-1", run_attempt: 1,
    started_at: at, collection_paused: true, runtime_inventory: {
      schema_version: 1, mode: "runtime_report", github_run_id: "123", git_sha: "b".repeat(40), captured_at: at,
      models: structuredClone(policy.models), editorial_policy: structuredClone(policy),
      flags: { writer_samples: 1, critic_enabled: true, critic_revise_enabled: false, automatic_publication_enabled: false },
      credentials_present: { safety_gemini: policy.flags.safety_llm_enabled },
    } }
  const result = await read(saved, { runtimeReport })
  assert.equal(result.posting_state_summary.manual_approved_count, 1)
  assert.equal(result.posting_state_summary.auto_scheduled_count, 0)
  assert.equal(result.posting_state_summary.attention_required_count, 1)
})

test("classification preserves the exact saved state and uses its supplied server time", async () => {
  const saved = state([draft("automatic"), draft("manual", "manual")]), before = structuredClone(saved)
  const { summarizePostingStates } = await importFresh("lib/automation.js")
  const now = Date.now()
  const summary = summarizePostingStates(saved, { now })
  assert.equal(summary.auto_scheduled_count, 1)
  assert.equal(summary.manual_approved_count, 1)
  assert.equal(summary.checked_at, new Date(now).toISOString())
  assert.deepEqual(saved, before)
})

for (const [name, rows] of [
  ["unreadable collection", "bad"], ["malformed row", [null]],
  ["ambiguous pending ids", [{ id: "same", status: "pending" }, { id: "same", status: "approved" }]],
  ["pending id shared with posted row", [{ id: "same", status: "pending" }, { id: "same", status: "posted" }]],
  ["missing pending id", [{ status: "pending" }]],
  ["unsupported row status", [{ id: "unknown", status: "invented" }]],
]) test(`${name} cannot produce a verified zero or schedule count`, async () => {
  const result = await read(state(rows))
  assert.equal(result.posting_state_summary?.status, "unavailable")
  assert.match(html(result), /Saved approvals unavailable/)
})

test("presentation refuses missing, forged and inconsistent counts and never falls back to policy recommendations", () => {
  assert.equal(typeof presentation.postingStatePresentation, "function")
  const good = { schema_version: 1, status: "recorded", checked_at: "2026-11-18T14:00:00Z", pending_count: 1,
    attention_required_count: 1, auto_scheduled_count: 0, manual_approved_count: 0, unresolved_send_count: 0 }
  assert.equal(presentation.postingStatePresentation(good).status, "recorded")
  assert.equal(presentation.postingStatePresentation({ ...good, checked_at: "2099-11-18T14:00:00Z" }).status, "recorded",
    "Client clock differences cannot overturn a supported server snapshot")
  for (const value of [null, {}, { ...good, schema_version: 2 }, { ...good, checked_at: "bad" },
    { ...good, auto_scheduled_count: 1 }, { ...good, pending_count: -1 },
    { ...good, pending_count: 2 ** 54 }, { ...good, attention_required_count: "1" }]) {
    assert.equal(presentation.postingStatePresentation(value).status, "unavailable")
    const markup = html({ workflows: [], posting_state_summary: value, posting_mode_summary: { armed_auto_count: 5 } })
    assert.match(markup, /Saved approvals unavailable/)
    assert.doesNotMatch(markup, /5 auto/)
  }
})
