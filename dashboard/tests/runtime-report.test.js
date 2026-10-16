import test from "node:test"
import assert from "node:assert/strict"
import { configurationReportRun, decodeRuntimeReportFile, MAX_RUNTIME_REPORT_BYTES } from "../lib/runtime-report.js"
import { buildRuntimeConfig } from "../lib/runtime-inventory.js"
import { dashboardEditorialPolicy } from "../lib/editorial-policy.js"
import { dashboardAutomaticPolicy } from "../lib/publication-control.js"
import { buildProductHealth } from "../lib/product-health.js"
import { policy, runtimeRun, draftIdentity, fingerprint } from "./helpers/review-policy.js"
import { importFresh } from "./helpers/import-fresh.js"

const now = Date.parse("2026-10-16T19:00:00Z")
function report(at = new Date(now - 1000).toISOString()) {
  return { schema_version: 1, kind: "configuration_only", id: "config-123-1", run_attempt: 1,
    started_at: at, collection_paused: true, runtime_inventory: {
      schema_version: 1, mode: "runtime_report", github_run_id: "123", git_sha: "b".repeat(40), captured_at: at,
      models: structuredClone(policy.models), editorial_policy: structuredClone(policy),
      flags: { writer_samples: 1, critic_enabled: true, critic_revise_enabled: false, automatic_publication_enabled: false },
      credentials_present: { safety_gemini: policy.flags.safety_llm_enabled },
    } }
}
const oldState = () => ({ run_history: [runtimeRun("2026-10-11T15:51:26Z")] })

test("configuration evidence refreshes manual policy without inventing source/writer health or automatic release", () => {
  const state = oldState(), before = structuredClone(state), runtimeReport = report()
  assert.equal(dashboardEditorialPolicy(state, { now, runtimeReport }).policy_sha256, fingerprint(policy))
  const config = buildRuntimeConfig(state, { now, runtimeReport })
  assert.equal(config.report_kind, "configuration_only")
  assert.match(config.reason, /no source collection, drafting or provider access/)
  assert.equal(config.credentials_present.twitter, undefined)
  assert.equal(dashboardAutomaticPolicy(state, { now, runtimeReport, env: {
    THEHEAT_AUTOMATIC_PUBLICATION_ENABLED: "1", THEHEAT_AUTOMATIC_PUBLICATION_EPOCH: "invented-epoch" } }).enabled, false)
  const health = buildProductHealth(state, { now, runtimeReport })
  assert.equal(health.milestones.source_observed.at, null)
  assert.equal(health.milestones.draft_created.at, null)
  assert.equal(health.writer.status, "unknown")
  assert.deepEqual(state, before)
})

for (const [name, mutate] of Object.entries({
  stale: r => { r.started_at = r.runtime_inventory.captured_at = new Date(now - 7 * 3600000).toISOString() },
  future: r => { r.started_at = r.runtime_inventory.captured_at = new Date(now + 1).toISOString() },
  badCalendar: r => { r.started_at = r.runtime_inventory.captured_at = "2026-02-30T10:00:00Z" },
  wrongSource: r => { r.runtime_inventory.editorial_policy.source_sha256 = "c".repeat(64) },
  wrongModel: r => { r.runtime_inventory.models.writer = "different-writer" },
  wrongFlags: r => { r.runtime_inventory.flags.critic_enabled = false },
  missingSafety: r => { delete r.runtime_inventory.credentials_present.safety_gemini },
  wrongRun: r => { r.runtime_inventory.github_run_id = "456" },
  wrongAttempt: r => { r.run_attempt = 2 },
  publishingEnabled: r => { r.runtime_inventory.flags.automatic_publication_enabled = true },
  collectionEnabled: r => { r.collection_paused = false },
})) test(`${name} evidence cannot establish review policy`, () => {
  const runtimeReport = report(); mutate(runtimeReport)
  assert.equal(dashboardEditorialPolicy(oldState(), { now, runtimeReport }).policy, null)
  if (!configurationReportRun(runtimeReport)) assert.equal(dashboardEditorialPolicy({ run_history: [runtimeRun(new Date(now - 2000).toISOString())] }, { now, runtimeReport }).policy, null)
})

test("newer uninstrumented run blocks configuration inheritance; decoder rejects corrupt or excessive UTF8 data", () => {
  const state = oldState(); state.run_history.push({ started_at: new Date(now - 500).toISOString() })
  assert.equal(dashboardEditorialPolicy(state, { now, runtimeReport: report() }).policy, null)
  assert.equal(decodeRuntimeReportFile(undefined), null)
  assert.deepEqual(decodeRuntimeReportFile({ content: JSON.stringify(report()) }), report())
  for (const file of [null, { content: "{" }, { content: "{}" }, { truncated: true, content: JSON.stringify(report()) },
    { content: "é".repeat(MAX_RUNTIME_REPORT_BYTES / 2 + 1) }]) assert.deepEqual(decodeRuntimeReportFile(file), { invalid_report: true })
})

test("new paused configuration vetoes an older enabled bot report; only a newer real bot report can establish a release", () => {
  const enabledRun = at => ({ ...runtimeRun(at), runtime_inventory: { ...runtimeRun(at).runtime_inventory,
    flags: { automatic_publication_enabled: true, automatic_publication_epoch: "invented-epoch" } } })
  const state = { run_history: [enabledRun(new Date(now - 2000).toISOString())] }
  const options = { now, runtimeReport: report(), env: {
    THEHEAT_AUTOMATIC_PUBLICATION_ENABLED: "1", THEHEAT_AUTOMATIC_PUBLICATION_EPOCH: "invented-epoch" } }
  assert.equal(dashboardAutomaticPolicy(state, options).enabled, false)
  state.run_history.push(enabledRun(new Date(now - 500).toISOString()))
  assert.equal(dashboardAutomaticPolicy(state, options).enabled, true)
})

async function withStore(run, options = {}) {
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented", DASHBOARD_PASSWORD: "offline-only",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "invented-gist", GITHUB_TOKEN: "invented-token",
    THEHEAT_AUTOMATIC_PUBLICATION_ENABLED: "0" })
  const originalFetch = globalThis.fetch
  let state = { ...oldState(), drafts: [{ id: "invented-1", event_id: "invented-event", text: "Invented warning test.", status: "pending",
    created_at: new Date(now - 1000).toISOString(), review_context: { source: "Invented offline evidence", two_bot: { bundle: { event_id: "invented-event" } } } }],
    publish_ledger: {}, posted_events: ["preserved-event"] }
  let reads = 0
  const runtimeReport = options.noReport ? null : report(new Date().toISOString()), patches = [], dispatches = []
  globalThis.fetch = async (url, request = {}) => {
    assert.match(String(url), /^https:\/\/api.github.com\//)
    if (String(url).includes("/dispatches")) { dispatches.push(JSON.parse(request.body)); return { ok: true, status: 204 } }
    assert.match(String(url), /gists\/invented-gist$/)
    if (request.method === "PATCH") {
      const files = JSON.parse(request.body).files
      assert.deepEqual(Object.keys(files), ["state.json"])
      state = JSON.parse(files["state.json"].content)
      assert.equal(Object.hasOwn(state, "runtimeReport"), false)
      assert.equal(Object.hasOwn(state, "runtime_inventory"), false)
      patches.push(files); return { ok: true, status: 200 }
    }
    const value = structuredClone(runtimeReport)
    if (++reads === options.changeOnRead) value.runtime_inventory.models.writer = "changed-writer"
    return { ok: true, status: 200, async json() { return { files: { "state.json": { content: JSON.stringify(state) },
      ...(value ? { "runtime-inventory.json": { content: JSON.stringify(value) } } : {}) } } } }
  }
  try {
    const route = await importFresh("app/api/drafts/route.js")
    const headers = { "content-type": "application/json", authorization: `Basic ${Buffer.from("invented:offline-only").toString("base64")}` }
    async function post(action, extra = {}) {
      const d = state.drafts[0]
      const response = await route.POST(new Request("http://localhost/api/drafts", { method: "POST", headers,
        body: JSON.stringify({ draftId: d.id, action, expectedRevision: { ...draftIdentity(d), decision_revision: d.decision_revision ?? 0 }, ...extra }) }))
      return { status: response.status, body: await response.json() }
    }
    await run({ route, headers, post, state: () => state, patches, dispatches })
  } finally { globalThis.fetch = originalFetch }
}

test("actual handlers: metadata -> human review -> edit revokes -> new review -> exact manual approval", async () => {
  await withStore(async ({ post, state, route, headers, patches, dispatches }) => {
    const visible = (await (await route.GET(new Request("http://localhost/api/drafts", { headers }))).json()).drafts[0]
    assert.equal(visible.editorial_policy.status, "recorded")
    assert.equal(visible.automatic_publication.enabled, false)
    assert.equal((await post("auto_approve")).body.code, "automatic_publication_paused")
    assert.equal((await post("approve")).body.code, "review_required")
    const confirm = { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) }
    assert.equal((await post("review", confirm)).body.draft.review_kind, "human")
    assert.equal((await post("edit", { editedText: "Invented edited wording." })).status, 200)
    assert.equal(state().drafts[0].review_binding, undefined)
    assert.equal((await post("approve")).body.code, "review_required")
    assert.equal((await post("review", confirm)).status, 200)
    assert.equal((await post("approve")).status, 200)
    assert.equal(dispatches.length, 1)
    assert.equal(dispatches[0].inputs.tweet_text, "Invented edited wording.")
    assert.equal(state().drafts[0].approval_binding.mode, "manual")
    assert.deepEqual(state().posted_events, ["preserved-event"])
    assert.deepEqual(state().publish_ledger, {})
    assert.equal(patches.length, 4)
  })
})

test("changed metadata between reads rejects review before any state write", async () => {
  await withStore(async ({ post, patches, dispatches }) => {
    const response = await post("review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) })
    assert.equal(response.status, 409); assert.equal(response.body.code, "editorial_policy_changed")
    assert.equal(patches.length, 0); assert.equal(dispatches.length, 0)
  }, { changeOnRead: 2 })
})

test("changed metadata on approval's second read cannot save authorization or dispatch", async () => {
  await withStore(async ({ post, state, patches, dispatches }) => {
    assert.equal((await post("review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) })).status, 200)
    const response = await post("approve")
    assert.equal(response.status, 409); assert.equal(response.body.code, "editorial_policy_changed")
    assert.equal(state().drafts[0].approval_binding, undefined)
    assert.equal(patches.length, 1); assert.equal(dispatches.length, 0)
  }, { changeOnRead: 4 })
})

test("missing report with stale normal policy keeps review blocked", async () => {
  await withStore(async ({ post, patches }) => {
    assert.equal((await post("review", { reviewConfirmed: true, expectedPolicySha256: fingerprint(policy) })).body.code, "editorial_policy_unverified")
    assert.equal(patches.length, 0)
  }, { noReport: true })
})

test("config endpoint projects separate report without adding bot history", async () => {
  await withStore(async ({ headers, state }) => {
    const route = await importFresh("app/api/config/route.js")
    const response = await route.GET(new Request("http://localhost/api/config", { headers }))
    assert.equal((await response.json()).report_kind, "configuration_only")
    assert.equal(state().run_history.length, 1)
  })
})
