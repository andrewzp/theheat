import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { configuredAutomaticPolicy, dashboardAutomaticPolicy, mergePublicationControl } from "../lib/publication-control.js"
import { draftReviewControls } from "../lib/draft-review-ui.js"
import { draftIdentity, fingerprint, initializeRevision, textHash } from "../lib/draft-revisions.js"
import { importFresh } from "./helpers/import-fresh.js"

const epoch = "offline-release-one"
function state() {
  const at = new Date().toISOString()
  return { publication_control: { retired_epochs: [] }, run_history: [{ started_at: at, runtime_inventory: {
    schema_version: 1, captured_at: at, flags: { automatic_publication_enabled: true, automatic_publication_epoch: epoch },
  } }] }
}
const env = { THEHEAT_AUTOMATIC_PUBLICATION_ENABLED: "1", THEHEAT_AUTOMATIC_PUBLICATION_EPOCH: epoch }

test("dashboard defaults paused and requires fresh bot agreement before scheduling", () => {
  assert.equal(configuredAutomaticPolicy({}).enabled, false)
  assert.equal(configuredAutomaticPolicy({ ...env, THEHEAT_AUTOMATIC_PUBLICATION_ENABLED: "true" }).enabled, false)
  assert.equal(dashboardAutomaticPolicy(state(), { env }).enabled, true)
  const variants = [{}, { ...state(), publication_control: { retired_epochs: [epoch] } },
    { ...state(), publication_control: { retired_epochs: "corrupt" } }]
  for (const snapshot of variants) assert.equal(dashboardAutomaticPolicy(snapshot, { env }).enabled, false)
  for (const flags of [{ automatic_publication_enabled: false, automatic_publication_epoch: epoch },
    { automatic_publication_enabled: true, automatic_publication_epoch: "other-release" }]) {
    const snapshot = state()
    snapshot.run_history[0].runtime_inventory.flags = flags
    assert.equal(dashboardAutomaticPolicy(snapshot, { env }).enabled, false)
  }
  assert.equal(dashboardAutomaticPolicy(state(), { env, now: Date.now() + 7 * 3600000 }).enabled, false)
})

test("retired release union cannot be lost when a stale dashboard merges state", () => {
  const a = { retired_epochs: [epoch], epoch, observed_at: "2026-09-08T13:00:00Z", enabled: false }
  const b = { retired_epochs: ["previous-release"], epoch, observed_at: "2026-09-08T12:00:00Z", enabled: true }
  assert.deepEqual(mergePublicationControl(a, b), mergePublicationControl(b, a))
  assert.deepEqual(mergePublicationControl(a, b).retired_epochs, [epoch, "previous-release"])
  assert.equal(mergePublicationControl(a, b).enabled, false)
})

test("UI preserves manual review while automatic scheduling is paused or unknown", () => {
  const d = { status: "pending", review_status: "passed", review_kind: "model", approval_policy: { can_auto_approve: true } }
  assert.equal(draftReviewControls(d).canSchedule, false)
  assert.equal(draftReviewControls(d).canApprove, true)
  assert.equal(draftReviewControls({ ...d, automatic_publication: { enabled: false } }).canSchedule, false)
  assert.equal(draftReviewControls({ ...d, automatic_publication: { enabled: true } }).canSchedule, true)
})

function auth() {
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_AUTH_DISABLED: "0", DASHBOARD_USERNAME: "reviewer", DASHBOARD_PASSWORD: "secret-pass", THEHEAT_STATE_BACKEND: "gist", GIST_ID: "mock-gist", GITHUB_TOKEN: "mock-token", THEHEAT_DB_PATH: "" })
  return { "Content-Type": "application/json", authorization: `Basic ${Buffer.from("reviewer:secret-pass").toString("base64")}` }
}

test("ad-hoc posting route refuses text without any platform or workflow request", async () => {
  const headers = auth()
  const previous = globalThis.fetch
  let calls = 0
  globalThis.fetch = async () => { calls++; throw new Error("unexpected network") }
  try {
    const { POST } = await importFresh("app/api/post/route.js")
    const response = await POST(new Request("http://localhost/api/post", { method: "POST", headers, body: JSON.stringify({ tweet: "A raw manual tweet." }) }))
    assert.equal(response.status, 409)
    assert.equal((await response.json()).code, "sourced_draft_required")
    assert.equal(calls, 0)
  } finally { globalThis.fetch = previous }
})

test("paused scheduling API rejects a current reviewed draft before writing or dispatching", async () => {
  const headers = auth()
  Object.assign(process.env, env, { THEHEAT_AUTOMATIC_PUBLICATION_ENABLED: "0" })
  const d = { id: "draft", event_id: "event", status: "pending", text: "Sourced text.", approval_policy: { can_auto_approve: true },
    review_context: { two_bot: { bundle: {}, fact_check: { passed: true }, critic: { passed: true }, reviewed_text_sha256: textHash("Sourced text."), reviewed_bundle_sha256: fingerprint({}) } } }
  initializeRevision(d)
  const snapshot = { ...state(), drafts: [d] }
  const previous = globalThis.fetch
  let writes = 0
  globalThis.fetch = async (_url, options = {}) => {
    if (options.method) { writes++; throw new Error("unexpected mutation") }
    return { ok: true, json: async () => ({ files: { "state.json": { content: JSON.stringify(snapshot) } } }) }
  }
  try {
    const { POST } = await importFresh("app/api/drafts/route.js")
    const response = await POST(new Request("http://localhost/api/drafts", { method: "POST", headers,
      body: JSON.stringify({ action: "auto_approve", draftId: d.id, expectedRevision: { ...draftIdentity(d), decision_revision: d.decision_revision } }) }))
    assert.equal(response.status, 409)
    assert.equal((await response.json()).code, "automatic_publication_paused")
    assert.equal(writes, 0)
  } finally { globalThis.fetch = previous }
})

test("composer offers a writing preview without a publication action", () => {
  const page = readFileSync(new URL("../app/page.js", import.meta.url), "utf8")
  assert.ok(!page.includes('fetch("/api/post"'))
  assert.ok(page.includes("Publishing requires a sourced draft"))
})

test("shared Python and JavaScript control merge contract", () => {
  const rows = JSON.parse(readFileSync(new URL("../../tests/fixtures/publication_control_merge.json", import.meta.url), "utf8"))
  for (const row of rows) assert.deepEqual(mergePublicationControl(row.a, row.b), row.expected, row.name)
})
