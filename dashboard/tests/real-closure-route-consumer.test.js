// P00c: the ONE serialized consumer re-verifies dashboard decisions with the exact existing
// checks and writes state + results in one PATCH. OFFLINE FIXTURE: in-process whole-file Gist.
// Real routes submit the commands; the Python admission is exercised by tests/real_closure.
// v2 (ROUTE-CONTRACT-v2): commands are sealed and bound to the active route activation, so the
// fixture seeds an active route record and an invented test seal key; approvals hand their sender
// follow-up to the durable outbox (runSenderOutbox) instead of an in-memory follow-up list.
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createHash } from "node:crypto"
import { importFresh } from "./helpers/import-fresh.js"
import { CONTROL_ENV, consumerMarker, installMemoryGist, routeConsumerEnv, routeEnv, routeRecord, TEST_SEAL_KEY } from "./helpers/route-memory-gist.js"
import { policy, runtimeRun, initializeRevision, draftIdentity, textHash, fingerprint } from "./helpers/review-policy.js"
import { consumeGistCommands, retainResults, runSenderOutbox } from "../lib/gist-command-consumer.js"
import { buildCommand, CODE_GENERATION, producerGenerationCode, RESULTS_FILE, ROUTE_FILE, routeRecordFromFiles, validateCommandRaw } from "../lib/gist-write-route.js"
import { openEnvelope, parseEnvelope, sealKey } from "../lib/gist-command-seal.js"
import { buildSealedCommand } from "../lib/gist-route-submit.js"

const VECTORS = JSON.parse(readFileSync(new URL("../../tests/fixtures/w14_delivery_reconciliation_vectors.json", import.meta.url), "utf8"))
const sha = text => createHash("sha256").update(text, "utf8").digest("hex")

function seed(count = 2) {
  const at = new Date().toISOString()
  const drafts = Array.from({ length: count }, (_, index) => {
    const id = `draft_route_${index + 1}`
    const draft = { id, event_id: `event_${id}`, type: "hot10", status: "pending", text: `Invented City ${index + 1} reached 40°C today.`,
      created_at: "2026-10-30T12:00:00Z", score: { total: 60 }, approval_policy: { can_auto_approve: true, recommended_delay_minutes: 30 },
      review_context: { source: "invented observations", two_bot: { bundle: { event_id: `event_${id}`, headline_value: 40 },
        fact_check: { passed: true, extracted_claims: [{ kind: "measurement", value: 40 }] }, critic: { passed: true } } } }
    const proof = draft.review_context.two_bot
    proof.reviewed_text_sha256 = textHash(draft.text)
    proof.reviewed_policy_sha256 = fingerprint(policy)
    proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
    return initializeRevision(draft)
  })
  return { drafts, publish_ledger: {}, errors: [], run_history: [runtimeRun(at)] }
}
const identity = draft => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })
const headers = { "Content-Type": "application/json", authorization: `Basic ${Buffer.from("reviewer:invented-pass").toString("base64")}` }
const state = gist => JSON.parse(gist.store.routestategist["state.json"])
// Saved drafts are re-sorted by the existing merge (created_at, then updated_at): look up by id.
const byId = (gist, id) => state(gist).drafts.find(draft => draft.id === id)
const results = (gist, id = "routestategist") => JSON.parse(gist.store[id][RESULTS_FILE] ?? '{"results":{}}').results
const entry = raw => ({ raw, admission: { command_id: JSON.parse(raw).command_id, digest: sha(raw) }, source: "test" })

async function submit(body, route = "app/api/drafts/route.js") {
  const handler = await importFresh(route)
  const response = await handler.POST(new Request("http://localhost/api/x", { method: "POST", headers, body: JSON.stringify(body) }))
  return { status: response.status, body: await response.json() }
}

async function withRoute(initial, run, options = {}) {
  const restore = routeEnv({ THEHEAT_GIST_WRITE_ROUTE: "serialized", THEHEAT_COMMAND_SEAL_KEY: TEST_SEAL_KEY })
  const gist = installMemoryGist({ gists: { routestategist: { "state.json": JSON.stringify(initial),
    ...(options.record === false ? {} : { [ROUTE_FILE]: routeRecord() }), ...(options.files || {}) },
    routefeedbackgist: options.feedback || {} } })
  try { await run(gist) } finally { gist.restore(); restore() }
}

async function consume(entries, env = {}) {
  Object.assign(process.env, routeConsumerEnv, env)
  try { return await consumeGistCommands(entries) } finally {
    for (const key of [...Object.keys(routeConsumerEnv)]) delete process.env[key]
  }
}

test("route mode: the drafts route submits a CAS command (no PATCH); the consumer applies it in ONE PATCH with its result", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const draft = initial.drafts[0]
    const response = await submit({ action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    assert.equal(response.status, 202)
    assert.equal(response.body.status, "pending")
    assert.deepEqual(gist.patches, [], "route mode never PATCHes from the dashboard")
    const raw = gist.dispatches[0].body.inputs.command
    assert.equal(gist.dispatches[0].workflow, "gist-commands.yml")
    assert.equal(raw, response.body.command)
    const report = await consume([entry(raw)])
    assert.deepEqual(report.applied.map(row => row.command_id), [response.body.command_id])
    assert.deepEqual(gist.patches, [{ id: "routestategist", files: [RESULTS_FILE, "state.json"] }])
    assert.equal(byId(gist, draft.id).status, "rejected")
    assert.equal(byId(gist, initial.drafts[1].id).status, "pending")
    const row = results(gist)[response.body.command_id]
    assert.equal(row.status, "applied")
    assert.equal(row.digest, sha(raw))
    assert.equal(row.run, "4242:consume")
    assert.deepEqual(row.applied_identity, [{ draft_id: draft.id, ...identity(byId(gist, draft.id)) }])
  })
})

test("conflicting decisions on one snapshot: the second is refused revision_conflict; non-conflicting ones both apply", async () => {
  const initial = seed(3)
  await withRoute(initial, async (gist) => {
    const [a, b] = initial.drafts
    const reject = await submit({ action: "reject", draftId: a.id, expectedRevision: identity(a) })
    const edit = await submit({ action: "edit", draftId: a.id, expectedRevision: identity(a), editedText: "Invented City 1 reached 41°C today." })
    const other = await submit({ action: "reject", draftId: b.id, expectedRevision: identity(b) })
    assert.deepEqual([reject.status, edit.status, other.status], [202, 202, 202])
    const raws = gist.dispatches.map(row => row.body.inputs.command)
    const report = await consume(raws.map(entry))
    const outcome = Object.fromEntries([...report.applied, ...report.refused].map(row => [row.command_id, row.code]))
    const firstOnA = [reject.body, edit.body].sort((x, y) => JSON.parse(x.command).requested_at.localeCompare(JSON.parse(y.command).requested_at)
      || x.command_id.localeCompare(y.command_id))
    assert.equal(outcome[firstOnA[0].command_id], null)
    assert.equal(outcome[firstOnA[1].command_id], "revision_conflict")
    assert.equal(outcome[other.body.command_id], null)
    assert.equal(gist.patches.length, 1, "all three results and both applied updates travel in ONE PATCH")
    const saved = state(gist)
    assert.equal(saved.drafts.find(d => d.id === b.id).status, "rejected")
    assert.equal(saved.drafts.find(d => d.id === initial.drafts[2].id).status, "pending")
  })
})

test("duplicate command is never reapplied; a reused id with other bytes is refused and keeps the first result", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const draft = initial.drafts[0]
    const first = await submit({ action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    const raw = first.body.command
    const parsed = JSON.parse(raw)
    // The server issues a second, different sealed envelope under the same id (never happens in
    // production: ids are random per command) — the consumer must refuse it as a reused id.
    const body = openEnvelope(parseEnvelope(raw), sealKey())
    const reused = buildSealedCommand({ action: "draft_update", operation: parsed.operation, producerKind: "dashboard_editor",
      actorSubject: "dashboard-operator", route: routeRecordFromFiles({ [ROUTE_FILE]: { content: gist.store.routestategist[ROUTE_FILE] } }),
      targets: body.targets, payload: body.payload, commandId: parsed.command_id, lifetimeMs: 1800000,
      now: new Date(Date.parse(parsed.requested_at) + 1000) }).raw
    assert.notEqual(reused, raw)
    const report = await consume([entry(raw), entry(raw), entry(reused)])
    assert.equal(report.applied.length, 1)
    assert.deepEqual(report.duplicates, [parsed.command_id])
    assert.deepEqual(report.reused, [{ command_id: parsed.command_id, code: "command_id_reused" }])
    const before = JSON.stringify(gist.store.routestategist)
    const again = await consume([entry(raw), entry(reused)])
    assert.equal(again.applied.length, 0)
    assert.equal(again.state_patches, 0, "nothing changed, nothing written")
    assert.equal(JSON.stringify(gist.store.routestategist), before)
    assert.equal(results(gist)[parsed.command_id].digest, sha(raw))
    assert.equal(byId(gist, draft.id).decision_revision, identity(draft).decision_revision + 1, "applied exactly once")
  })
})

test("a stale snapshot (another writer changed the draft after submission) is refused revision_conflict", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const draft = initial.drafts[0]
    const response = await submit({ action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    const changed = state(gist)
    changed.drafts[0].score = { total: 61 }
    gist.store.routestategist["state.json"] = JSON.stringify(changed)
    const report = await consume([entry(response.body.command)])
    assert.deepEqual(report.refused, [{ command_id: response.body.command_id, code: "revision_conflict" }])
    assert.equal(byId(gist, draft.id).status, "pending")
    assert.equal(results(gist)[response.body.command_id].code, "revision_conflict")
  })
})

test("expiry, producer generations, the marker and a stale consumer generation all refuse", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const draft = initial.drafts[0]
    const response = await submit({ action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    const later = new Date(Date.now() + 2 * 3600000)
    Object.assign(process.env, routeConsumerEnv)
    const report = await consumeGistCommands([entry(response.body.command)], { now: () => later })
    assert.deepEqual(report.refused, [{ command_id: response.body.command_id, code: "expired" }])
    assert.equal(state(gist).drafts[0].status, "pending")
    const command = JSON.parse(response.body.command)
    assert.equal(producerGenerationCode({ ...command, producer: { kind: "dashboard_editor", generation: "0" } }, null), "retired_writer_generation_refused")
    assert.equal(producerGenerationCode({ ...command, producer: { kind: "dashboard_editor", generation: String(CODE_GENERATION + 1) } }, null), "unauthorized_writer_generation_refused")
    assert.equal(producerGenerationCode({ ...command, producer: { kind: "dashboard_editor", generation: "1" } }, { generation: 2 }), "retired_writer_generation_refused")
    assert.equal(producerGenerationCode({ ...command, producer: { kind: "dashboard_editor", generation: "x" } }, null), "unauthorized_writer_generation_refused")
    assert.throws(() => validateCommandRaw(JSON.stringify({ ...command, producer: { kind: "dashboard_editor", generation: "1" }, action: "activate_route" })),
      error => error.code === "non_canonical_command" || error.code === "unauthorized_writer_generation_refused")
    delete process.env.THEHEAT_SERIALIZED_WRITER
    await assert.rejects(consumeGistCommands([entry(response.body.command)]), error => error.code === "serialized_writer_marker_required")
    gist.store.routestategist[ROUTE_FILE] = JSON.stringify({ schema_version: 1, mode: "serialized", generation: CODE_GENERATION + 1,
      changed_at: "2026-10-30T12:00:00Z", changed_by_run: "1:consume", command_id: "00000000-0000-4000-8000-000000000000" })
    await assert.rejects(consume([entry(response.body.command)]), error => error.code === "stale_writer_generation")
    assert.equal(state(gist).drafts[0].status, "pending")
  })
})

test("activation follows the repository variable; deactivation only after it returns to legacy; record rides the same PATCH", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const command = (action, now = new Date()) => buildCommand({ action, producerKind: "gist_route_control", actorSubject: "root", payload: { generation: 1 }, now, env: CONTROL_ENV }).raw
    const off = await consume([entry(command("activate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.equal(off.refused[0].code, "route_variable_not_serialized")
    assert.equal(gist.store.routestategist[ROUTE_FILE], undefined)
    // Old-SHA fence: activation needs the route-era writer name AND no legacy secret name left.
    const legacyName = await consume([entry(command("activate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "serialized", THEHEAT_GIST_CREDENTIAL: "legacy" })
    assert.equal(legacyName.refused[0].code, "route_writer_credential_legacy")
    const legacyPresent = await consume([entry(command("activate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "serialized", THEHEAT_LEGACY_CREDENTIALS_PRESENT: "true" })
    assert.equal(legacyPresent.refused[0].code, "route_legacy_credentials_present")
    assert.equal(gist.store.routestategist[ROUTE_FILE], undefined)
    const on = await consume([entry(command("activate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "serialized" })
    assert.equal(on.applied.length, 1)
    const record = JSON.parse(gist.store.routestategist[ROUTE_FILE])
    assert.deepEqual([record.mode, record.generation, record.changed_by_run], ["serialized", 1, "4242:consume"])
    assert.deepEqual(gist.patches.at(-1).files, [RESULTS_FILE, ROUTE_FILE].sort(), "route record + result in one PATCH; state.json untouched")
    const stuck = await consume([entry(command("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "serialized" })
    assert.equal(stuck.refused[0].code, "route_variable_still_serialized")
    const back = await consume([entry(command("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.equal(back.applied.length, 1)
    assert.equal(JSON.parse(gist.store.routestategist[ROUTE_FILE]).mode, "legacy")
    assert.equal(gist.store.routestategist["state.json"], JSON.stringify(initial))
  }, { record: false })
})

test("feedback commands write only the feedback Gist; state commands never touch it", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const draft = initial.drafts[1]
    const target = { draft_id: draft.id, status: "pending", tweet_id: null, ...draftIdentity(draft), graphic_sha256: null }
    const requestId = "11111111-2222-4333-8444-555555555555"
    const handler = await importFresh("app/api/post-feedback/route.js")
    const feedback = await handler.POST(new Request("http://localhost/api/post-feedback", { method: "POST",
      headers: { ...headers, origin: "http://localhost", "sec-fetch-site": "same-origin" },
      body: JSON.stringify({ request_id: requestId, target, subject: "copy", tags: ["concise"], note: "" }) }))
    assert.equal(feedback.status, 202)
    const reject = await submit({ action: "reject", draftId: initial.drafts[0].id, expectedRevision: identity(initial.drafts[0]) })
    assert.deepEqual(gist.patches, [])
    const stateBefore = JSON.stringify(state(gist))
    const report = await consume(gist.dispatches.map(row => entry(row.body.inputs.command)))
    assert.equal(report.applied.length, 2)
    const byGist = Object.groupBy(gist.patches, row => row.id)
    assert.deepEqual(byGist.routestategist.map(row => row.files), [[RESULTS_FILE, "state.json"]])
    assert.deepEqual(byGist.routefeedbackgist.map(row => row.files), [[RESULTS_FILE, `editorial-feedback-${requestId}.json`].sort()])
    assert.equal(gist.store.routefeedbackgist["state.json"], undefined)
    assert.ok(!Object.keys(results(gist)).includes((await (await feedback.json())).command_id))
    assert.notEqual(JSON.stringify(state(gist)), stateBefore)
    assert.equal(byId(gist, draft.id).status, "pending", "feedback never changes the draft")
    assert.equal(Object.keys(results(gist, "routefeedbackgist")).length, 1)
    assert.ok(results(gist)[reject.body.command_id])
  })
})

test("approve: the consumer repeats the policy confirmation and requests the manual sender only after applying", async () => {
  const initial = seed()
  await withRoute(initial, async (gist) => {
    const draft = initial.drafts[0]
    const approve = await submit({ action: "approve", draftId: draft.id, expectedRevision: identity(draft) })
    assert.equal(approve.status, 202)
    assert.deepEqual(gist.dispatches.map(row => row.workflow), ["gist-commands.yml"], "no bot.yml dispatch before the approval is applied")
    const report = await consume([entry(approve.body.command)])
    assert.equal(report.applied.length, 1)
    const saved = byId(gist, draft.id)
    assert.equal(saved.status, "approved")
    // v2: the follow-up is a durable outbox entry written in the approval's own PATCH (no text).
    assert.deepEqual(report.outbox_queued, [{ command_id: approve.body.command_id, publish_intent_id: saved.publish_intent_id }])
    assert.deepEqual(results(gist)[approve.body.command_id].follow_up, { publish_intent_id: saved.publish_intent_id })
    const queued = JSON.parse(gist.store.routestategist[RESULTS_FILE]).outbox[saved.publish_intent_id]
    assert.equal(queued.state, "queued")
    assert.ok(!JSON.stringify(queued).includes(saved.text), "the outbox holds ids and states, never text")
    Object.assign(process.env, routeConsumerEnv)
    try {
      const sent = await runSenderOutbox({ token: "invented", repo: "invented/theheat" })
      assert.deepEqual(sent.dispatches.map(row => row.state), ["dispatched"])
    } finally { for (const key of Object.keys(routeConsumerEnv)) delete process.env[key] }
    assert.deepEqual(gist.dispatches.at(-1), { workflow: "bot.yml", body: { ref: "main", inputs: { mode: "manual_tweet",
      tweet_text: saved.text, draft_id: saved.id, publish_intent_id: saved.publish_intent_id } } })
    assert.equal(JSON.parse(gist.store.routestategist[RESULTS_FILE]).outbox[saved.publish_intent_id].state, "dispatched")
  })
  const second = seed()
  await withRoute(second, async (gist) => {
    const draft = second.drafts[0]
    const approve = await submit({ action: "approve", draftId: draft.id, expectedRevision: identity(draft) })
    const changed = state(gist)
    changed.run_history[0].runtime_inventory.editorial_policy.execution_sha256 = "b".repeat(64)
    gist.store.routestategist["state.json"] = JSON.stringify(changed)
    const report = await consume([entry(approve.body.command)])
    assert.deepEqual(report.refused.map(row => row.code), ["editorial_policy_changed"])
    assert.equal(byId(gist, draft.id).status, "pending")
    assert.deepEqual(report.outbox_queued, [])
  })
})

test("delivery reconciliation: the consumer re-runs the snapshot checks and the same decision", async () => {
  const request = VECTORS.cases[0].steps[0].request
  const restore = routeEnv({ THEHEAT_GIST_WRITE_ROUTE: "serialized", THEHEAT_DELIVERY_RECONCILIATION_ENABLED: "1", THEHEAT_COMMAND_SEAL_KEY: TEST_SEAL_KEY })
  const gist = installMemoryGist({ gists: { routestategist: { "state.json": JSON.stringify(VECTORS.state), [ROUTE_FILE]: routeRecord() } } })
  try {
    process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED = "1"
    const handler = await importFresh("app/api/delivery-reconciliation/route.js")
    const response = await handler.POST(new Request("http://localhost/api/delivery-reconciliation", { method: "POST", headers, body: JSON.stringify(request) }))
    const body = await response.json()
    assert.equal(response.status, 202)
    assert.deepEqual(gist.patches, [])
    const report = await consume([entry(body.command)])
    assert.equal(report.applied.length, 1)
    assert.equal(JSON.parse(gist.store.routestategist["state.json"]).publish_ledger[request.event_id].reconciliation.reconciliation_id, request.reconciliation_id)
    assert.equal(results(gist)[body.command_id].reconciliation.status, "applied")
  } finally { delete process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED; gist.restore(); restore() }
})

test("results are retained until three days after expiry, then pruned", () => {
  const now = new Date("2026-10-30T12:00:00Z")
  const kept = retainResults({ a: { expires_at: "2026-10-27T11:59:59Z" }, b: { expires_at: "2026-10-27T12:00:01Z" }, c: { expires_at: "2026-10-30T13:00:00Z" } }, now)
  assert.deepEqual(Object.keys(kept.results), ["b", "c"])
  assert.equal(kept.pruned, 1)
})
