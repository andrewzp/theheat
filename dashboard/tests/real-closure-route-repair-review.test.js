// ROUTE repairs for the independent review (P2-1, P3-1, P3-3) through the REAL drafts handler,
// the REAL Python admission CLI, the REAL consumer, acknowledgement and status. OFFLINE FIXTURE:
// in-process Gist, invented data, invented test keys. Red: receipts/red-review-*.txt.
import test from "node:test"
import assert from "node:assert/strict"
import { randomUUID } from "node:crypto"
import { canonical } from "../lib/local-command-recovery.js"
import { acknowledgeArtifacts, MAX_CONTROL_RESULTS, MAX_RESULTS, runSenderOutbox } from "../lib/gist-command-consumer.js"
import { RESULTS_FILE, ROUTE_FILE } from "../lib/gist-write-route.js"
import { sealEnvelope } from "../lib/gist-command-seal.js"
import { signRouteControl } from "../lib/gist-route-control.js"
import { RUN_TITLE_PREFIX } from "../lib/gist-sender-outbox.js"
import { admit, byId, commandStatus, consume, entry, identity, post, resultsDoc, seed, sha, stateOf, withConsumerEnv, withRoute, ROUTE_ACTIVATION } from "./helpers/route-repair-fixture.js"

const z = date => date.toISOString().replace(/\.\d{3}Z$/, "Z")
const ROOT_KEY = { kid: "k-ctl-test", key: Buffer.alloc(32, 11) }
const control = (action, fields = {}, key = ROOT_KEY) => {
  const at = new Date(Math.floor(Date.now() / 1000) * 1000)
  const command = { schema_version: 1, command_id: randomUUID(), action, requested_at: z(at), expires_at: z(new Date(at.getTime() + 3600000)),
    producer: { kind: "gist_route_control", generation: "1" }, actor_subject: "root", targets: [], payload: { generation: 1 }, ...fields }
  return canonical(key ? signRouteControl(command, key) : command)
}
const ack = entries => withConsumerEnv({}, () => acknowledgeArtifacts(entries, { token: "invented", repo: "invented/theheat" }))
async function genuineReject(gist, id = "draft_route_1") {
  const draft = stateOf(gist).drafts.find(row => row.id === id)
  const issued = await post("app/api/drafts/route.js", { action: "reject", draftId: id, expectedRevision: identity(draft) })
  assert.equal(issued.status, 202)
  return issued.body.command
}

test("P2-1a route control is authenticated: an unsigned or foreign-key control reusing a genuine id never vetoes it", async () => {
  for (const sameDrain of [true, false]) {
    await withRoute(seed(1), async (gist) => {
      const genuine = await genuineReject(gist)
      const envelope = JSON.parse(genuine)
      const earlier = z(new Date(Date.parse(envelope.requested_at) - 1000))
      const unsigned = control("deactivate_route", { command_id: envelope.command_id, requested_at: earlier }, null)
      const foreign = control("deactivate_route", { command_id: envelope.command_id, requested_at: earlier }, { kid: "k-ctl-test", key: Buffer.alloc(32, 3) })
      assert.deepEqual([admit(genuine).result.admitted, admit(unsigned).result.code, admit(foreign).result.admitted], [true, "route_control_unauthenticated", true])
      gist.artifacts.push({ id: 1, name: `theheat-command-${envelope.command_id}` }, { id: 2, name: `theheat-command-${envelope.command_id}` })
      const forgedEntry = entry(foreign, { artifact_id: 2 })
      forgedEntry.admission.action = "deactivate_route"
      const genuineEntry = entry(genuine, { artifact_id: 1 })
      genuineEntry.admission.action = "draft_update"
      if (sameDrain) {
        const report = await consume([genuineEntry, forgedEntry])
        assert.deepEqual([report.applied.map(row => row.command_id), report.rejected.map(row => row.code)], [[envelope.command_id], ["route_control_invalid"]])
      } else {
        const first = await consume([forgedEntry])
        assert.deepEqual(first.rejected.map(row => row.code), ["route_control_invalid"])
        assert.equal((await consume([genuineEntry])).applied.length, 1)
      }
      assert.equal(byId(gist, "draft_route_1").status, "rejected", "the genuine reject applied")
      assert.equal(resultsDoc(gist).results[envelope.command_id].digest, sha(genuine))
      assert.deepEqual((await commandStatus(envelope.command_id, sha(genuine))).body.status, "applied")
      const acknowledged = await ack([genuineEntry, forgedEntry])
      assert.deepEqual(acknowledged.deleted.map(row => [row.artifact_id, row.reason]).sort(), [[1, "result_persisted"], [2, "envelope_rejected"]])
    })
  }
})

test("P2-1a a correctly signed control that shares a sealed id lives in its own namespace and settles nothing else", async () => {
  await withRoute(seed(1), async (gist) => {
    const genuine = await genuineReject(gist)
    const envelope = JSON.parse(genuine)
    const signed = control("deactivate_route", { command_id: envelope.command_id, requested_at: z(new Date(Date.parse(envelope.requested_at) - 1000)) })
    const report = await consume([entry(genuine), entry(signed)])
    assert.deepEqual(report.refused.map(row => [row.command_id, row.code, row.route_control]), [[envelope.command_id, "route_variable_still_serialized", true]])
    assert.deepEqual(report.applied.map(row => row.command_id), [envelope.command_id])
    const document = resultsDoc(gist)
    assert.deepEqual([document.results[envelope.command_id].digest, document.control_results[envelope.command_id].digest], [sha(genuine), sha(signed)])
    assert.equal(byId(gist, "draft_route_1").status, "rejected")
  })
})

test("P2-1b a no-op activation or deactivation is refused and never rotates the activation or strands commands", async () => {
  await withRoute(seed(2), async (gist) => {
    const genuine = await genuineReject(gist)
    const before = gist.store.routestategist[ROUTE_FILE]
    const unsigned = control("activate_route", {}, null)
    const report = await consume([entry(control("activate_route")), entry(genuine)])
    assert.deepEqual(report.refused.map(row => row.code), ["route_transition_noop"])
    assert.deepEqual(report.applied.map(row => row.command_id), [JSON.parse(genuine).command_id])
    assert.equal(gist.store.routestategist[ROUTE_FILE], before, "activation id unchanged")
    assert.equal(admit(unsigned).result.code, "route_control_unauthenticated")
    // An outstanding approval's outbox entry is not moved to route_generation_changed.
    const draft = byId(gist, "draft_route_2")
    const approve = await post("app/api/drafts/route.js", { action: "approve", draftId: draft.id, expectedRevision: identity(draft) })
    assert.equal(approve.status, 202, JSON.stringify(approve.body))
    await consume([entry(approve.body.command)])
    await consume([entry(control("activate_route"))])
    const intent = byId(gist, draft.id).publish_intent_id
    assert.equal(resultsDoc(gist).outbox[intent].state, "queued")
    // Rollback then a second deactivation: the second is a no-op.
    assert.equal((await consume([entry(control("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })).applied.length, 1)
    const again = await consume([entry(control("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.deepEqual(again.refused.map(row => row.code), ["route_transition_noop"])
    assert.equal(JSON.parse(gist.store.routestategist[ROUTE_FILE]).mode, "legacy")
  })
})

test("P2-1c control results are bounded separately and never consume the sealed-command capacity", async () => {
  await withRoute(seed(1), async (gist) => {
    const expires = new Date(Date.now() + 3600000).toISOString()
    const full = Object.fromEntries(Array.from({ length: MAX_CONTROL_RESULTS }, () => [randomUUID(), { digest: "0".repeat(64), status: "refused", code: "route_transition_noop", expires_at: expires }]))
    gist.store.routestategist[RESULTS_FILE] = JSON.stringify({ schema_version: 1, results: {}, control_results: full })
    const genuine = await genuineReject(gist)
    const report = await consume([entry(control("activate_route")), entry(genuine)])
    assert.deepEqual(report.skipped.map(row => row.code), ["control_results_capacity"])
    assert.deepEqual(report.applied.map(row => row.command_id), [JSON.parse(genuine).command_id])
    assert.ok(Object.keys(resultsDoc(gist).results).length < MAX_RESULTS)
  })
})

test("P3-1 unknown-kid, unopenable and invalid envelopes are settled by digest once expired and acknowledged; live ones are not", async () => {
  await withRoute(seed(1), async (gist) => {
    const at = new Date(Date.now() - 2 * 3600000)
    const sealUnder = (kid, startedAt) => sealEnvelope({ schema_version: 2, command_id: randomUUID(), action: "draft_update", operation: "reject",
      requested_at: z(startedAt), expires_at: z(new Date(startedAt.getTime() + 3 * 3600000)), producer: { kind: "dashboard_editor", generation: "1" },
      actor_subject: "dashboard-operator", route_activation: ROUTE_ACTIVATION }, { targets: [], payload: {} }, { kid, key: Buffer.alloc(32, 1) })
    const unknown = sealUnder("attacker", at)
    assert.equal(admit(unknown).result.code, "command_seal_kid_unknown", "admission accepts only the configured kid")
    const live = sealUnder("attacker", new Date())
    const later = () => new Date(Date.now() + 2 * 3600000)
    const garbled = { raw: "{", admission: { command_id: randomUUID(), digest: "e".repeat(64), action: "draft_update", expires_at: z(new Date(Date.now() - 1000)) }, source: "x", artifact_id: 9 }
    gist.artifacts.push({ id: 7, name: `theheat-command-${JSON.parse(unknown).command_id}` }, { id: 8, name: `theheat-command-${JSON.parse(live).command_id}` },
      { id: 9, name: `theheat-command-${garbled.admission.command_id}` })
    const entries = [entry(unknown, { artifact_id: 7 }), entry(live, { artifact_id: 8 }), garbled]
    const report = await consume(entries, {}, { now: later })
    assert.deepEqual(report.rejected.map(row => row.code).sort(), ["expired_unopened", "invalid_expired"], "expired unknown-kid and expired unreadable are settled")
    assert.deepEqual(report.skipped.map(row => row.code), ["command_seal_key_unknown"], "the live one is only skipped")
    const acknowledged = await ack(entries)
    assert.deepEqual(acknowledged.deleted.map(row => row.artifact_id).sort(), [7, 9])
    // Not yet expired under another kid: left for a correctly keyed run, never settled.
    const now = await consume([entry(live, { artifact_id: 8 })])
    assert.deepEqual(now.skipped.map(row => row.code), ["command_seal_key_unknown"])
    assert.ok(!resultsDoc(gist).rejected_envelopes[sha(live)])
    assert.deepEqual(resultsDoc(gist).results, {}, "no command id was bound")
  })
})

test("P3-3 every in-flight outbox entry is observed: a cancelled run beyond the 20th entry is recovered", async () => {
  await withRoute(seed(23), async (gist) => {
    const raws = []
    for (const draft of stateOf(gist).drafts) raws.push((await post("app/api/drafts/route.js", { action: "approve", draftId: draft.id, expectedRevision: identity(draft) })).body.command)
    assert.equal((await consume(raws.map(raw => entry(raw)))).outbox_queued.length, 23)
    const outbox = now => withConsumerEnv({}, () => runSenderOutbox({ token: "invented", repo: "invented/theheat", now: () => now }))
    const t0 = new Date()
    await outbox(t0)
    const ids = Object.keys(resultsDoc(gist).outbox)
    for (const index of [20, 22]) gist.runs.push({ id: 900 + index, display_title: RUN_TITLE_PREFIX + ids[index], status: "completed", conclusion: "cancelled",
      created_at: t0.toISOString(), updated_at: t0.toISOString() })
    const recovered = await outbox(new Date(t0.getTime() + 10 * 60000))
    assert.deepEqual(recovered.dispatches.map(row => row.publish_intent_id).sort(), [ids[20], ids[22]].sort())
    for (const index of [20, 22]) assert.deepEqual([resultsDoc(gist).outbox[ids[index]].state, resultsDoc(gist).outbox[ids[index]].attempts], ["dispatched", 2])
    assert.equal(resultsDoc(gist).outbox[ids[0]].attempts, 1)
  })
})
