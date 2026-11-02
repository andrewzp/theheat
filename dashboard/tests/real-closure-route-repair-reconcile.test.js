// ROUTE repair follow-up: delivery reconciliation in route mode through the REAL reconciliation
// handler -> sealed envelope -> REAL Python admission CLI -> REAL Node consumer: applies; inactive
// route / stale generation refuse; decideReconciliation's domain refusal at consumption; actor
// rebinding; altered/forged envelopes. OFFLINE FIXTURE (invented W14 vectors, invented test key).
import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { canonical } from "../lib/local-command-recovery.js"
import { buildCommand, readRouteRecord } from "../lib/gist-write-route.js"
import { buildSealedCommand } from "../lib/gist-route-submit.js"
import { readStateGistSnapshot, reconciliationNumericSha256, reconciliationSnapshot } from "../lib/state-store.js"
import { OTHER_SEAL_KEY } from "./helpers/route-memory-gist.js"
import { admit, commandStatus, consume, entry, post, resultsDoc, sha, stateOf, withRoute } from "./helpers/route-repair-fixture.js"

const VECTORS = JSON.parse(readFileSync(new URL("../../tests/fixtures/w14_delivery_reconciliation_vectors.json", import.meta.url), "utf8"))
const REQUEST = VECTORS.cases[0].steps[0].request // confirm_matching_receipt on w14-ev-unknown
const EVENT = REQUEST.event_id
const reconcile = body => post("app/api/delivery-reconciliation/route.js", body)
const row = gist => stateOf(gist).publish_ledger[EVENT]

async function withReconciliation(run, options) {
  const saved = process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED
  process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED = "1"
  try { await withRoute(structuredClone(VECTORS.state), run, options) } finally {
    if (saved === undefined) delete process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED; else process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED = saved
  }
}

// Authentic bytes (the server's key) with exact snapshots, for cases the dashboard would not issue.
async function serverSealedReconciliation(request, { actor = "dashboard-operator" } = {}) {
  const snap = await readStateGistSnapshot()
  return buildSealedCommand({ action: "reconcile_delivery", operation: "reconcile_delivery", producerKind: "dashboard_reconciliation",
    actorSubject: "dashboard-operator", route: await readRouteRecord(),
    payload: { event_id: request.event_id, request_json: JSON.stringify(request), actor, at: "2026-10-30T11:00:00Z",
      expected_snapshot: reconciliationSnapshot(snap.state, request.event_id), expected_numeric_sha256: reconciliationNumericSha256(snap, request.event_id) } }).raw
}

test("reconcile: a legitimate confirmation applies under an active route through API -> admission -> consumer", async () => {
  await withReconciliation(async (gist) => {
    const submitted = await reconcile(REQUEST)
    assert.equal(submitted.status, 202, JSON.stringify(submitted.body))
    assert.deepEqual(gist.patches, [])
    const admitted = admit(submitted.body.command)
    assert.equal(admitted.result.admitted, true)
    assert.ok(!admitted.files["command.json"].includes(REQUEST.receipt.tweet_id), "the receipt travels sealed")
    const report = await consume([entry(submitted.body.command)])
    assert.equal(report.applied.length, 1, JSON.stringify(report.refused))
    assert.deepEqual([row(gist).phase, row(gist).tweet_id], ["confirmed", REQUEST.receipt.tweet_id])
    assert.equal(row(gist).reconciliation.actor, "dashboard-operator", "the ledger actor is the sealed session subject")
    assert.equal(resultsDoc(gist).results[submitted.body.command_id].reconciliation.status, "applied")
    assert.equal((await commandStatus(submitted.body.command_id, sha(submitted.body.command))).body.status, "applied")
  })
})

test("reconcile: refused at submit while inactive; retained commands refuse at apply on rollback and after re-activation", async () => {
  await withReconciliation(async (gist) => {
    const window = await reconcile(REQUEST)
    assert.deepEqual([window.status, window.body.code], [409, "route_not_active"])
    assert.deepEqual([gist.patches, gist.dispatches], [[], []])
  }, { record: null })
  await withReconciliation(async (gist) => {
    const retained = (await reconcile(REQUEST)).body.command
    const rolled = await consume([entry(retained)], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.deepEqual(rolled.refused.map(item => item.code), ["route_not_active"])
    assert.equal(row(gist).tweet_id, null)
    const control = action => buildCommand({ action, producerKind: "gist_route_control", actorSubject: "root", payload: { generation: 1 } }).raw
    assert.equal((await consume([entry(control("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })).applied.length, 1)
    assert.equal((await consume([entry(control("activate_route"))])).applied.length, 1)
    const second = (await withoutResult(gist, retained))
    const stale = await consume([entry(second)])
    assert.deepEqual(stale.refused.map(item => item.code), ["route_generation_not_current"])
    assert.equal(row(gist).tweet_id, null)
  })
})

// A second command sealed under the FIRST activation (the first one's id already has a result).
async function withoutResult(gist, first) {
  const envelope = JSON.parse(first)
  const restoreRecord = gist.store.routestategist["gist-write-route.json"]
  gist.store.routestategist["gist-write-route.json"] = JSON.stringify({ ...JSON.parse(restoreRecord), command_id: envelope.route_activation })
  try { return await serverSealedReconciliation(REQUEST) } finally { gist.store.routestategist["gist-write-route.json"] = restoreRecord }
}

test("reconcile: decideReconciliation refuses at consumption on its own read; a rebound ledger actor refuses", async () => {
  await withReconciliation(async (gist) => {
    const submitted = await reconcile(REQUEST)
    assert.equal(submitted.status, 202)
    // Another event now holds this receipt (its own ledger row, outside this event's CAS snapshot).
    const state = stateOf(gist)
    state.publish_ledger["w14-ev-altered"].tweet_id = REQUEST.receipt.tweet_id
    gist.store.routestategist["state.json"] = JSON.stringify(state)
    const rebound = await serverSealedReconciliation({ ...REQUEST, reconciliation_id: "w14-route-r2" }, { actor: "someone-else" })
    assert.equal(admit(rebound).result.admitted, true)
    const report = await consume([entry(submitted.body.command), entry(rebound)])
    const codes = Object.fromEntries(report.refused.map(item => [item.command_id, item.code]))
    assert.equal(codes[submitted.body.command_id], "receipt_bound_elsewhere")
    assert.equal(codes[JSON.parse(rebound).command_id], "command_actor_mismatch")
    assert.deepEqual(report.applied, [])
    assert.equal(row(gist).tweet_id, null)
    // At submit the handler runs the same decision and issues nothing for a refused request.
    const refused = await reconcile({ ...REQUEST, reconciliation_id: "w14-route-r3" })
    assert.deepEqual([refused.status, refused.body.code], [409, "receipt_bound_elsewhere"])
  })
})

test("reconcile: altered, rebound or forged envelopes refuse; a tampered direct dispatch is rejected by digest", async () => {
  await withReconciliation(async (gist) => {
    const issued = await reconcile(REQUEST)
    const envelope = JSON.parse(issued.body.command)
    const flip = value => value.slice(0, 8) + (value[8] === "A" ? "B" : "A") + value.slice(9)
    for (const [label, value] of Object.entries({
      ciphertext: { ...envelope, seal: { ...envelope.seal, ciphertext: flip(envelope.seal.ciphertext) } },
      actor: { ...envelope, actor_subject: "someone-else" },
      generation: { ...envelope, route_activation: "00000000-0000-4000-8000-0000000000dd" },
    })) {
      const response = await post("app/api/commands/route.js", { command: canonical(value) })
      assert.deepEqual([response.status === 202, response.body.code], [false, "command_seal_invalid"], label)
    }
    assert.equal(gist.dispatches.length, 1)
    const tampered = canonical({ ...envelope, seal: { ...envelope.seal, tag: flip(envelope.seal.tag) } })
    assert.equal(admit(tampered).result.admitted, true)
    const realKey = process.env.THEHEAT_COMMAND_SEAL_KEY
    process.env.THEHEAT_COMMAND_SEAL_KEY = OTHER_SEAL_KEY
    const forged = await serverSealedReconciliation({ ...REQUEST, reconciliation_id: "w14-route-forged" })
    process.env.THEHEAT_COMMAND_SEAL_KEY = realKey
    const report = await consume([entry(tampered), entry(forged)])
    assert.deepEqual(report.rejected.map(item => item.code), ["command_seal_invalid", "command_seal_invalid"])
    assert.deepEqual([report.applied, resultsDoc(gist).results], [[], {}])
    assert.equal(row(gist).tweet_id, null)
    assert.equal((await consume([entry(issued.body.command)])).applied.length, 1, "the genuine command still applies")
  })
})
