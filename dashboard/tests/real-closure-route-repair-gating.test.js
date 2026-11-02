// ROUTE repair B.4 (ROUTE-CONTRACT-v2 §3): default-off is real at submit AND apply, through the
// REAL handlers and the REAL consumer: unset/legacy, activation ordering, active mode, rollback at
// apply and re-activation. OFFLINE FIXTURE (in-process Gist, invented key). Red: red-b4-*-v2.txt.
import test from "node:test"
import assert from "node:assert/strict"
import { buildCommand, ROUTE_FILE } from "../lib/gist-write-route.js"
import { CONTROL_ENV } from "./helpers/route-memory-gist.js"
import { byId, consume, entry, identity, post, resultsDoc, seed, sha, withRoute, routeRecord, ROUTE_ACTIVATION } from "./helpers/route-repair-fixture.js"

const control = action => buildCommand({ action, producerKind: "gist_route_control", actorSubject: "root", payload: { generation: 1 }, env: CONTROL_ENV }).raw

test("B4 unset/legacy: legacy direct path unchanged; no submission; a retained sealed command is refused at apply and changes nothing", async () => {
  // A command sealed while the route was active (to have authentic bytes at all)...
  let retained
  await withRoute(seed(2), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    retained = (await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })).body.command
  })
  // ...then everything unset: variable absent, no route record (the live default).
  await withRoute(seed(2), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[1]
    const legacy = await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    assert.equal(legacy.status, 200, "legacy direct path unchanged")
    assert.deepEqual(gist.patches, [{ id: "routestategist", files: ["state.json"] }])
    assert.deepEqual(gist.dispatches, [])
    const retry = await post("app/api/commands/route.js", { command: retained })
    assert.deepEqual([retry.status, retry.body.code], [409, "route_not_active"])
    assert.deepEqual(gist.dispatches, [], "no submission while legacy")
    const before = gist.store.routestategist["state.json"]
    const report = await consume([entry(retained)], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.deepEqual(report.refused.map(row => row.code), ["route_not_active"])
    assert.equal(gist.store.routestategist["state.json"], before, "no state change through the consumer while legacy")
    assert.equal(gist.patches.at(-1).files.join(), "gist-command-results.json", "only its terminal result is recorded")
    assert.equal(resultsDoc(gist).results[JSON.parse(retained).command_id].code, "route_not_active")
  }, { variable: null, record: null })
})

test("B4 activation ordering: variable first (fail-closed window), then activate_route; only then do commands submit and apply", async () => {
  await withRoute(seed(1), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    const body = { action: "reject", draftId: draft.id, expectedRevision: identity(draft) }
    // Variable serialized, record absent: neither PATCH nor submission.
    const window = await post("app/api/drafts/route.js", body)
    assert.deepEqual([window.status, window.body.code], [409, "route_not_active"])
    assert.deepEqual([gist.patches, gist.dispatches], [[], []])
    const activate = control("activate_route")
    const report = await consume([entry(activate)])
    assert.equal(report.applied.length, 1)
    const record = JSON.parse(gist.store.routestategist[ROUTE_FILE])
    assert.equal(record.mode, "serialized")
    const submitted = await post("app/api/drafts/route.js", body)
    assert.equal(submitted.status, 202)
    assert.equal(JSON.parse(submitted.body.command).route_activation, record.command_id, "bound to this activation")
    const applied = await consume([entry(submitted.body.command)])
    assert.equal(applied.applied.length, 1)
    assert.equal(byId(gist, draft.id).status, "rejected")
  }, { record: null })
})

test("B4 rollback at apply and re-activation: retained commands never apply as a concurrent legacy writer", async () => {
  await withRoute(seed(3), async (gist) => {
    const [a, b, c] = JSON.parse(gist.store.routestategist["state.json"]).drafts
    const first = (await post("app/api/drafts/route.js", { action: "reject", draftId: a.id, expectedRevision: identity(a) })).body.command
    const second = (await post("app/api/drafts/route.js", { action: "reject", draftId: b.id, expectedRevision: identity(b) })).body.command
    // Rollback step 1: root sets the variable back to legacy. Retained commands refuse at apply.
    process.env.THEHEAT_GIST_WRITE_ROUTE = "legacy"
    const window = await post("app/api/drafts/route.js", { action: "reject", draftId: c.id, expectedRevision: identity(c) })
    assert.deepEqual([window.status, window.body.code], [409, "route_not_active"], "variable legacy + record serialized: fail closed, no direct write either")
    assert.equal(byId(gist, c.id).status, "pending")
    const rolled = await consume([entry(first)], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.deepEqual(rolled.refused.map(row => row.code), ["route_not_active"])
    assert.equal(byId(gist, a.id).status, "pending")
    // Rollback step 2: deactivate_route; then re-activation issues a NEW activation id.
    assert.equal((await consume([entry(control("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })).applied.length, 1)
    process.env.THEHEAT_GIST_WRITE_ROUTE = "serialized"
    assert.equal((await consume([entry(control("activate_route"))])).applied.length, 1)
    const record = JSON.parse(gist.store.routestategist[ROUTE_FILE])
    assert.notEqual(record.command_id, ROUTE_ACTIVATION)
    const stale = await consume([entry(second)])
    assert.deepEqual(stale.refused.map(row => row.code), ["route_generation_not_current"])
    assert.equal(byId(gist, b.id).status, "pending")
    const fresh = await post("app/api/drafts/route.js", { action: "reject", draftId: b.id, expectedRevision: identity(byId(gist, b.id)) })
    assert.equal((await consume([entry(fresh.body.command)])).applied.length, 1)
    assert.equal(byId(gist, b.id).status, "rejected")
    // The retry endpoint also refuses a command bound to an old activation.
    const retry = await post("app/api/commands/route.js", { command: second })
    assert.deepEqual([retry.status, retry.body.code], [409, "route_generation_not_current"])
  })
})

test("B4 active mode: the consumer refuses (fail closed, not recorded) under the legacy writer name or while legacy names exist", async () => {
  await withRoute(seed(1), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    const raw = (await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })).body.command
    for (const [env, code] of [[{ THEHEAT_GIST_CREDENTIAL: "legacy" }, "route_writer_credential_legacy"],
      [{ THEHEAT_LEGACY_CREDENTIALS_PRESENT: "true" }, "route_legacy_credentials_present"],
      [{ THEHEAT_LEGACY_CREDENTIALS_PRESENT: undefined }, "route_legacy_credentials_present"]]) {
      const report = await consume([entry(raw)], env)
      assert.deepEqual(report.skipped, [{ command_id: JSON.parse(raw).command_id, code }])
      assert.deepEqual(resultsDoc(gist).results, {}, "nothing terminal recorded for a configuration refusal")
      assert.equal(byId(gist, draft.id).status, "pending")
    }
    assert.equal((await consume([entry(raw)])).applied.length, 1)
    assert.equal(resultsDoc(gist).results[JSON.parse(raw).command_id].digest, sha(raw))
  }, { record: routeRecord() })
})
