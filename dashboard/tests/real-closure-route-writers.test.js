// P00c: every dashboard Gist writer is rerouted (command) or refuses in route mode, and is
// unchanged in legacy mode. OFFLINE FIXTURE: in-process whole-file Gist; no network.
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createHash } from "node:crypto"
import { importFresh } from "./helpers/import-fresh.js"
import { consumerMarker, installMemoryGist, routeEnv } from "./helpers/route-memory-gist.js"
import { policy, runtimeRun, initializeRevision, draftIdentity, textHash, fingerprint } from "./helpers/review-policy.js"
import { consumeGistCommands } from "../lib/gist-command-consumer.js"
import { assertDirectGistWrite, buildCommand, CODE_GENERATION, ROUTE_FILE } from "../lib/gist-write-route.js"
import { reconcileDeliveryStore, updateDraftStore, writeStateStore } from "../lib/state-store.js"
import { savePostFeedback } from "../lib/post-feedback.js"

const VECTORS = JSON.parse(readFileSync(new URL("../../tests/fixtures/w14_delivery_reconciliation_vectors.json", import.meta.url), "utf8"))
const sha = text => createHash("sha256").update(text, "utf8").digest("hex")
const headers = { "Content-Type": "application/json", authorization: `Basic ${Buffer.from("reviewer:invented-pass").toString("base64")}` }
const ROUTE_ON = JSON.stringify({ schema_version: 1, mode: "serialized", generation: 1, changed_at: "2026-10-30T12:00:00Z",
  changed_by_run: "77:consume", command_id: "00000000-0000-4000-8000-000000000001" })

function seed(count = 2) {
  const drafts = Array.from({ length: count }, (_, index) => {
    const id = `draft_route_${index + 1}`
    const draft = { id, event_id: `event_${id}`, type: "hot10", status: "pending", text: `Invented City ${index + 1} reached 40°C today.`,
      created_at: "2026-10-30T12:00:00Z", score: { total: 10 + index }, approval_policy: { can_auto_approve: true },
      review_context: { source: "invented observations", two_bot: { bundle: { event_id: `event_${id}` }, fact_check: { passed: true }, critic: { passed: true } } } }
    const proof = draft.review_context.two_bot
    proof.reviewed_text_sha256 = textHash(draft.text)
    proof.reviewed_policy_sha256 = fingerprint(policy)
    proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
    return initializeRevision(draft)
  })
  return { drafts, publish_ledger: {}, errors: [], run_history: [runtimeRun(new Date().toISOString())] }
}
const identity = draft => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })
const entry = raw => ({ raw, admission: { command_id: JSON.parse(raw).command_id, digest: sha(raw) }, source: "test" })

async function scenario(env, files, run) {
  const restore = routeEnv(env)
  const gist = installMemoryGist({ gists: { routestategist: files, routefeedbackgist: {} } })
  try { await run(gist) } finally { gist.restore(); restore() }
}
async function post(route, body, extraHeaders = {}) {
  const handler = await importFresh(route)
  const response = await handler.POST(new Request("http://localhost/api/x", { method: "POST", headers: { ...headers, ...extraHeaders }, body: JSON.stringify(body) }))
  return { status: response.status, body: await response.json() }
}

test("dashboard_editor: legacy PATCHes directly (unchanged); route mode by variable OR record submits a command; no submitter refuses", async () => {
  const initial = seed()
  const draft = initial.drafts[0]
  const body = { action: "reject", draftId: draft.id, expectedRevision: identity(draft) }
  await scenario({}, { "state.json": JSON.stringify(initial) }, async (gist) => {
    const response = await post("app/api/drafts/route.js", body)
    assert.equal(response.status, 200)
    assert.deepEqual(gist.patches, [{ id: "routestategist", files: ["state.json"] }], "legacy: exactly today's single state PATCH")
    assert.deepEqual(gist.dispatches, [])
  })
  for (const [env, files] of [[{ THEHEAT_GIST_WRITE_ROUTE: "serialized" }, {}], [{}, { [ROUTE_FILE]: ROUTE_ON }]]) {
    await scenario(env, { "state.json": JSON.stringify(initial), ...files }, async (gist) => {
      const response = await post("app/api/drafts/route.js", body)
      assert.equal(response.status, 202)
      assert.deepEqual(gist.patches, [])
      assert.equal(JSON.parse(gist.dispatches[0].body.inputs.command).producer.kind, "dashboard_editor")
      await assert.rejects(updateDraftStore(draft.id, record => { record.status = "rejected"; return record }, { expectedRevision: identity(draft) }),
        error => error.code === "direct_write_disabled_by_route" && error.status === 409)
      assert.deepEqual(gist.patches, [])
    })
  }
})

test("dashboard_editor: route-mode bulk rejection is ONE all-or-nothing command", async () => {
  const initial = seed(3)
  await scenario({ THEHEAT_GIST_WRITE_ROUTE: "serialized" }, { "state.json": JSON.stringify(initial) }, async (gist) => {
    const expectedRevisions = Object.fromEntries(initial.drafts.map(d => [d.id, identity(d)]))
    const response = await post("app/api/drafts/route.js", { action: "bulk_reject_below", delayMinutes: 100, expectedRevisions })
    assert.equal(response.status, 202)
    assert.equal(gist.dispatches.length, 1)
    const command = JSON.parse(response.body.command)
    assert.equal(command.payload.updates.length, 3)
    // A conflicting edit to one target refuses the whole command: no partial bulk outcome.
    const changed = JSON.parse(gist.store.routestategist["state.json"])
    changed.drafts[2].score = { total: 13 }
    gist.store.routestategist["state.json"] = JSON.stringify(changed)
    Object.assign(process.env, consumerMarker)
    const report = await consumeGistCommands([entry(response.body.command)])
    assert.deepEqual(report.refused.map(row => row.code), ["revision_conflict"])
    assert.ok(JSON.parse(gist.store.routestategist["state.json"]).drafts.every(d => d.status === "pending"))
  })
})

test("dashboard_state: the whole-state writer has no route caller and refuses in route mode; legacy unchanged", async () => {
  const initial = seed()
  await scenario({}, { "state.json": JSON.stringify(initial) }, async (gist) => {
    await writeStateStore({ errors: [] })
    assert.deepEqual(gist.patches.map(row => row.files), [["state.json"]])
  })
  for (const [env, files] of [[{ THEHEAT_GIST_WRITE_ROUTE: "serialized" }, {}], [{}, { [ROUTE_FILE]: ROUTE_ON }]]) {
    await scenario(env, { "state.json": JSON.stringify(initial), ...files }, async (gist) => {
      await assert.rejects(writeStateStore({ errors: [] }), error => error.code === "direct_write_disabled_by_route")
      assert.deepEqual(gist.patches, [])
    })
  }
})

test("dashboard_reconciliation: legacy unchanged; route mode submits the CAS decision or refuses without a submitter", async () => {
  const request = VECTORS.cases[0].steps[0].request
  const at = "2026-10-30T11:00:00Z"
  await scenario({}, { "state.json": JSON.stringify(VECTORS.state) }, async (gist) => {
    assert.equal((await reconcileDeliveryStore(request, { actor: "dashboard-operator", at })).status, "applied")
    assert.deepEqual(gist.patches.map(row => row.files), [["state.json"]])
  })
  await scenario({ THEHEAT_GIST_WRITE_ROUTE: "serialized" }, { "state.json": JSON.stringify(VECTORS.state) }, async (gist) => {
    await assert.rejects(reconcileDeliveryStore(request, { actor: "dashboard-operator", at }), error => error.code === "direct_write_disabled_by_route")
    const submitted = await reconcileDeliveryStore(request, { actor: "dashboard-operator", at, routeCommand: async payload => ({ payload }) })
    assert.equal(submitted.status, "submitted")
    assert.equal(submitted.submitted.payload.event_id, request.event_id)
    assert.match(submitted.submitted.payload.expected_numeric_sha256, /^[a-f0-9]{64}$/)
    assert.deepEqual(gist.patches, [])
  })
})

test("post_feedback: legacy writes only its record file; route mode submits; a direct save without submitter refuses", async () => {
  const initial = seed()
  const draft = initial.drafts[0]
  const value = { request_id: "21111111-2222-4333-8444-555555555555", subject: "copy", tags: ["useful"], note: "",
    target: { draft_id: draft.id, status: "pending", tweet_id: null, ...draftIdentity(draft), graphic_sha256: null } }
  await scenario({}, { "state.json": JSON.stringify(initial) }, async (gist) => {
    const saved = await savePostFeedback(value)
    assert.equal(saved.already_saved, false)
    assert.deepEqual(gist.patches, [{ id: "routefeedbackgist", files: [`editorial-feedback-${value.request_id}.json`] }])
  })
  await scenario({}, { "state.json": JSON.stringify(initial), [ROUTE_FILE]: ROUTE_ON }, async (gist) => {
    await assert.rejects(savePostFeedback(value), error => error.code === "direct_write_disabled_by_route")
    const routed = await savePostFeedback(value, { routeSubmit: async input => ({ status: "pending", input }) })
    assert.equal(routed.submitted.input.request_id, value.request_id)
    assert.deepEqual(gist.patches, [])
  })
})

test("gist_command_consumer: runs only with a valid serialized-group marker at a current generation", async () => {
  const initial = seed()
  await scenario({ THEHEAT_GIST_WRITE_ROUTE: "serialized" }, { "state.json": JSON.stringify(initial) }, async (gist) => {
    await assert.rejects(consumeGistCommands([]), error => error.code === "serialized_writer_marker_required")
    Object.assign(process.env, { GITHUB_RUN_ID: "5", THEHEAT_SERIALIZED_WRITER: "6:consume" })
    await assert.rejects(consumeGistCommands([]), error => error.code === "invalid_serialized_writer_marker")
    assert.equal(assertDirectGistWrite(null, { THEHEAT_GIST_WRITE_ROUTE: "serialized", GITHUB_RUN_ID: "5", THEHEAT_SERIALIZED_WRITER: "5:consume" }), "serialized")
    assert.throws(() => assertDirectGistWrite({ mode: "serialized", generation: CODE_GENERATION + 1 }, { GITHUB_RUN_ID: "5", THEHEAT_SERIALIZED_WRITER: "5:consume" }),
      error => error.code === "stale_writer_generation")
    assert.equal(assertDirectGistWrite(null, {}), "legacy")
    assert.deepEqual(gist.patches, [])
  })
})

test("gist_route_control: only root's dispatch may carry it; the dashboard resubmission endpoint refuses route control", async () => {
  await scenario({ THEHEAT_GIST_WRITE_ROUTE: "serialized" }, { "state.json": JSON.stringify(seed()) }, async (gist) => {
    const raw = buildCommand({ action: "activate_route", producerKind: "gist_route_control", actorSubject: "root", payload: { generation: 1 } }).raw
    const response = await post("app/api/commands/route.js", { command: raw }, { origin: "http://localhost" })
    assert.equal(response.status, 403)
    assert.equal(response.body.code, "route_control_not_dashboard")
    assert.deepEqual(gist.dispatches, [])
    assert.throws(() => buildCommand({ action: "activate_route", producerKind: "dashboard_editor", actorSubject: "x", payload: { generation: 1 } }),
      error => error.code === "unauthorized_writer_generation_refused")
  })
})
