// ROUTE repair B.1 + B.5 (ROUTE-CONTRACT-v2 §1–§2): server-issued sealed commands and
// consumption-time domain authorization, through the REAL drafts / commands / feedback handlers,
// the REAL Python admission CLI and the REAL Node consumer. OFFLINE FIXTURE: in-process Gist,
// invented data, an invented test seal key. Red baselines: receipts/red-b1-*.txt, red-b5-*-v2.txt.
import test from "node:test"
import assert from "node:assert/strict"
import { importFresh } from "./helpers/import-fresh.js"
import { OTHER_SEAL_KEY } from "./helpers/route-memory-gist.js"
import { admit, byId, commandStatus, consume, entry, identity, post, resultsDoc, seed, sha, withRoute, ROUTE_ACTIVATION, TEST_SEAL_KEY } from "./helpers/route-repair-fixture.js"
import * as rp from "./helpers/review-policy.js"
import { canonical } from "../lib/local-command-recovery.js"
import { buildCommand, readRouteRecord } from "../lib/gist-write-route.js"
import { MAX_ENVELOPE_BYTES, MAX_PLAINTEXT_BYTES, openEnvelope, parseEnvelope, sealEnvelope, sealKey } from "../lib/gist-command-seal.js"
import { buildSealedCommand } from "../lib/gist-route-submit.js"
import { draftMutationSnapshot, numericIdentitySha256, readStateGistSnapshot } from "../lib/state-store.js"
import { dashboardEditorialPolicy } from "../lib/editorial-policy.js"

// What a caller with Gist read could build for the donor route, now sealed with the SERVER's key:
// it proves the consumer itself enforces the domain operation even for authentic bytes.
async function serverSealed(draftId, operation, { params = {}, intent = null, checked = null } = {}) {
  const snap = await readStateGistSnapshot()
  const draft = snap.state.drafts.find(row => row.id === draftId)
  const policySha = dashboardEditorialPolicy(snap.state, { runtimeReport: snap.runtimeReport }).policy_sha256
  return buildSealedCommand({ action: "draft_update", operation, producerKind: "dashboard_editor", actorSubject: "dashboard-operator",
    route: await readRouteRecord(), targets: [{ draft_id: draftId, ...identity(draft) }],
    payload: { operation, params_json: JSON.stringify(params), media_descriptor_json: null,
      updates: [{ draft_id: draftId, expected_snapshot: draftMutationSnapshot(draft, snap.state), expected_numeric_sha256: numericIdentitySha256(snap.document, draftId) }],
      publish_intent_id: intent, checked_policy_sha256: ["review", "approve", "auto_approve"].includes(operation) ? (checked ?? policySha) : null,
      checked_automatic_epoch: null } }).raw
}

async function admitAndConsume(raw) {
  const admitted = admit(raw)
  assert.equal(admitted.result.admitted, true, JSON.stringify(admitted.result))
  return { admitted, report: await consume([entry(raw)]) }
}

const posted = s => { const d = s.drafts[0]; d.status = "posted"; d.tweet_id = "1900000000000000001"; d.publish_outcome = "confirmed"
  s.publish_ledger[d.event_id] = { tweet_id: d.tweet_id, phase: "confirmed", text: d.text } }
const unresolved = s => { const d = s.drafts[0]; d.status = "approved"
  s.publish_ledger[d.event_id] = { phase: "submitted", tweet_id: null, intent_id: "11111111-1111-4111-8111-111111111111", text: d.text } }

test("B1 posted draft: the server never issues the edit; caller bytes are refused; even an authentic sealed edit is refused at consumption", async () => {
  await withRoute(seed(1, posted), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    const issued = await post("app/api/drafts/route.js", { action: "edit", draftId: draft.id, expectedRevision: identity(draft), editedText: "FORGED posted text." })
    assert.deepEqual([issued.status, issued.body.code], [409, "draft_not_editable"])
    assert.deepEqual(gist.dispatches, [])
    // The donor-style caller-built plaintext command: no longer accepted anywhere.
    const plaintext = buildCommand({ action: "activate_route", producerKind: "gist_route_control", actorSubject: "x", payload: { generation: 1 } }).raw
      .replace('"activate_route"', '"draft_update"').replace('"gist_route_control"', '"dashboard_editor"')
    assert.equal((await post("app/api/commands/route.js", { command: plaintext })).body.code, "plaintext_command_refused")
    assert.equal(admit(plaintext).result.code, "plaintext_command_refused")
    // Authentic bytes (server key) for a posted draft, exact CAS digests: the consumer's domain check refuses.
    const raw = await serverSealed(draft.id, "edit", { params: { editedText: "FORGED posted text." } })
    const { admitted, report } = await admitAndConsume(raw)
    assert.ok(!admitted.files["command.json"].includes("FORGED"), "the admitted artifact carries ciphertext only")
    assert.deepEqual(report.refused.map(row => row.code), ["draft_not_editable"])
    assert.equal(byId(gist, draft.id).text, draft.text)
    assert.equal(byId(gist, draft.id).status, "posted")
  }, { gist: {} })
})

test("B1 unresolved publication: refused at submit and, for authentic bytes, at consumption (publication_unresolved)", async () => {
  await withRoute(seed(1, unresolved), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    const issued = await post("app/api/drafts/route.js", { action: "edit", draftId: draft.id, expectedRevision: identity(draft), editedText: "FORGED unresolved text." })
    assert.deepEqual([issued.status, issued.body.code], [409, "publication_unresolved"])
    const { report } = await admitAndConsume(await serverSealed(draft.id, "edit", { params: { editedText: "FORGED unresolved text." } }))
    assert.deepEqual(report.refused.map(row => row.code), ["publication_unresolved"])
    assert.equal(byId(gist, draft.id).text, draft.text)
  })
})

test("B1 forged approval / review / confirmation: an unreviewed draft never becomes approved or reviewed, and no sender is queued", async () => {
  await withRoute(seed(1, s => { delete s.drafts[0].review_binding }), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    assert.deepEqual((await post("app/api/drafts/route.js", { action: "approve", draftId: draft.id, expectedRevision: identity(draft) })).body.code, "review_required")
    const approve = await serverSealed(draft.id, "approve", { intent: "22222222-2222-4222-8222-222222222222" })
    const review = await serverSealed(draft.id, "review", { params: { reviewConfirmed: false, expectedPolicySha256: "f".repeat(64) } })
    const forgedConfirm = await serverSealed(draft.id, "review", { params: { reviewConfirmed: true }, checked: "e".repeat(64) })
    const report = await consume([entry(approve), entry(review), entry(forgedConfirm)])
    const codes = Object.fromEntries(report.refused.map(row => [row.command_id, row.code]))
    assert.equal(codes[JSON.parse(approve).command_id], "review_required")
    assert.equal(codes[JSON.parse(review).command_id], "review_confirmation_required")
    assert.equal(codes[JSON.parse(forgedConfirm).command_id], "editorial_policy_changed")
    assert.deepEqual(report.applied, [])
    assert.deepEqual(report.outbox_queued, [])
    assert.equal(byId(gist, draft.id).status, "pending")
    assert.equal(byId(gist, draft.id).review_binding, undefined)
  })
})

test("B1 legitimate edit, review, approve and reject still apply through API -> admission -> consumer", async () => {
  await withRoute(seed(3), async (gist) => {
    const [a, b, c] = JSON.parse(gist.store.routestategist["state.json"]).drafts
    const edit = await post("app/api/drafts/route.js", { action: "edit", draftId: a.id, expectedRevision: identity(a), editedText: "Invented City 1 reached 41°C today." })
    const reject = await post("app/api/drafts/route.js", { action: "reject", draftId: c.id, expectedRevision: identity(c) })
    const approve = await post("app/api/drafts/route.js", { action: "approve", draftId: b.id, expectedRevision: identity(b) })
    assert.deepEqual([edit.status, reject.status, approve.status], [202, 202, 202])
    for (const response of [edit, reject, approve]) assert.equal(admit(response.body.command).result.admitted, true)
    const report = await consume([edit, reject, approve].map(response => entry(response.body.command)))
    assert.equal(report.applied.length, 3, JSON.stringify(report.refused))
    assert.equal(byId(gist, a.id).text, "Invented City 1 reached 41°C today.")
    assert.equal(byId(gist, c.id).status, "rejected")
    assert.equal(byId(gist, b.id).status, "approved")
    assert.equal(byId(gist, b.id).publish_intent_id, openEnvelope(parseEnvelope(approve.body.command), sealKey()).payload.publish_intent_id,
      "the server-generated, sealed intent id is the one applied")
    // Human review of the edited draft, then its approval: both through the real route.
    const edited = byId(gist, a.id)
    const policySha = dashboardEditorialPolicy(JSON.parse(gist.store.routestategist["state.json"])).policy_sha256
    const reviewed = await post("app/api/drafts/route.js", { action: "review", draftId: a.id, expectedRevision: identity(edited), reviewConfirmed: true, expectedPolicySha256: policySha })
    assert.equal(reviewed.status, 202, JSON.stringify(reviewed.body))
    const second = await consume([entry(reviewed.body.command)])
    assert.equal(second.applied.length, 1, JSON.stringify(second.refused))
    assert.equal(byId(gist, a.id).review_binding.kind, "human")
  })
})

test("B1 altered or rebound retry bytes are refused by /api/commands; nothing is dispatched", async () => {
  await withRoute(seed(1), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    const issued = await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    assert.equal(issued.status, 202)
    const envelope = JSON.parse(issued.body.command)
    const flip = value => value.slice(0, 10) + (value[10] === "A" ? "B" : "A") + value.slice(11)
    const variants = {
      ciphertext: { ...envelope, seal: { ...envelope.seal, ciphertext: flip(envelope.seal.ciphertext) } },
      tag: { ...envelope, seal: { ...envelope.seal, tag: flip(envelope.seal.tag) } },
      operation: { ...envelope, operation: "approve" },
      actor: { ...envelope, actor_subject: "someone-else" },
      generation: { ...envelope, route_activation: "00000000-0000-4000-8000-0000000000ff" },
      expiry: { ...envelope, expires_at: new Date(Date.parse(envelope.expires_at) - 60000).toISOString().replace(/\.\d{3}Z$/, "Z") },
    }
    for (const [label, value] of Object.entries(variants)) {
      const response = await post("app/api/commands/route.js", { command: canonical(value) })
      assert.notEqual(response.status, 202, label)
      assert.equal(response.body.code, "command_seal_invalid", label)
    }
    assert.equal((await post("app/api/commands/route.js", { command: issued.body.command + " " })).status, 400)
    assert.equal((await post("app/api/commands/route.js", { command: "{" })).body.code, "invalid_json")
    assert.equal(gist.dispatches.length, 1, "only the server-issued submission was dispatched")
    const exact = await post("app/api/commands/route.js", { command: issued.body.command })
    assert.equal(exact.status, 202)
    assert.equal(gist.dispatches.at(-1).body.inputs.command, issued.body.command)
  })
})

test("B5 keys: wrong key / missing key at the dashboard or consumer never fall back to plaintext and never become terminal by id", async () => {
  await withRoute(seed(1), async (gist) => {
    const draft = JSON.parse(gist.store.routestategist["state.json"]).drafts[0]
    const issued = await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    process.env.THEHEAT_COMMAND_SEAL_KEY = OTHER_SEAL_KEY.replace("k-test", "k-other")
    assert.equal((await post("app/api/commands/route.js", { command: issued.body.command })).body.code, "command_seal_key_unknown")
    process.env.THEHEAT_COMMAND_SEAL_KEY = OTHER_SEAL_KEY
    assert.equal((await post("app/api/commands/route.js", { command: issued.body.command })).body.code, "command_seal_invalid")
    delete process.env.THEHEAT_COMMAND_SEAL_KEY
    const refused = await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    assert.deepEqual([refused.status, refused.body.code], [503, "command_seal_key_missing"])
    assert.equal(gist.dispatches.length, 1, "no plaintext fallback submission")
    // Consumer without a key / with another kid: skipped, not recorded, not acknowledged.
    const none = await consume([entry(issued.body.command)], { THEHEAT_COMMAND_SEAL_KEY: undefined })
    assert.deepEqual(none.skipped, [{ command_id: issued.body.command_id, code: "command_seal_key_missing" }])
    const otherKid = await consume([entry(issued.body.command)], { THEHEAT_COMMAND_SEAL_KEY: OTHER_SEAL_KEY.replace("k-test", "k-other") })
    assert.deepEqual(otherKid.skipped.map(row => row.code), ["command_seal_key_unknown"])
    assert.deepEqual(resultsDoc(gist).results, {})
    // Same kid, wrong key value: authentication fails -> recorded by DIGEST only, never by id.
    const wrong = await consume([entry(issued.body.command)], { THEHEAT_COMMAND_SEAL_KEY: OTHER_SEAL_KEY })
    assert.deepEqual(wrong.rejected, [{ command_id: issued.body.command_id, code: "command_seal_invalid" }])
    assert.deepEqual(resultsDoc(gist).results, {})
    assert.equal(resultsDoc(gist).rejected_envelopes[sha(issued.body.command)].code, "command_seal_invalid")
    assert.deepEqual((await commandStatus(issued.body.command_id, sha(issued.body.command))).body.code, "command_seal_invalid")
    // The genuine bytes under the right key still apply (the id was never bound by the rejection).
    process.env.THEHEAT_COMMAND_SEAL_KEY = TEST_SEAL_KEY
    const genuine = await post("app/api/drafts/route.js", { action: "reject", draftId: draft.id, expectedRevision: identity(draft) })
    const ok = await consume([entry(genuine.body.command)])
    assert.equal(ok.applied.length, 1)
  })
})

test("B5 private content never appears in the dispatch input, admitted artifact, consumer report or results", async () => {
  await withRoute(seed(2), async (gist) => {
    const [a, b] = JSON.parse(gist.store.routestategist["state.json"]).drafts
    const text = "PRIVATE unpublished edit: Invented City 1 reached 41°C."
    const note = "PRIVATE operator note about tone"
    const edit = await post("app/api/drafts/route.js", { action: "edit", draftId: a.id, expectedRevision: identity(a), editedText: text })
    const target = { draft_id: b.id, status: "pending", tweet_id: null, ...rp.draftIdentity(b), graphic_sha256: null }
    const feedback = await post("app/api/post-feedback/route.js", { request_id: "41111111-2222-4333-8444-555555555555", target, subject: "copy", tags: ["useful"], note })
    assert.deepEqual([edit.status, feedback.status], [202, 202])
    const secrets = [text, JSON.stringify(text).slice(1, -1), note, a.text, "41°C", "tone"]
    for (const row of gist.dispatches) for (const secret of secrets) assert.ok(!JSON.stringify(row).includes(secret), "dispatch input")
    for (const response of [edit, feedback]) {
      const { result, files } = admit(response.body.command)
      assert.equal(result.admitted, true)
      assert.deepEqual(Object.keys(files).sort(), ["admission.json", "command.json"])
      for (const content of Object.values(files)) for (const secret of secrets) assert.ok(!content.includes(secret), "admitted artifact bytes")
      for (const content of Object.values(result)) for (const secret of secrets) assert.ok(!String(content).includes(secret))
    }
    const report = await consume([entry(edit.body.command), entry(feedback.body.command)])
    assert.equal(report.applied.length, 2, JSON.stringify(report.refused))
    for (const secret of [note, "tone"]) assert.ok(!JSON.stringify(report).includes(secret), "consumer report")
    assert.ok(!JSON.stringify(report).includes(text))
    for (const store of ["routestategist", "routefeedbackgist"]) assert.ok(!(gist.store[store]["gist-command-results.json"] || "").includes(note))
    assert.ok(!(gist.store.routestategist["gist-command-results.json"] || "").includes(text))
    assert.equal(byId(gist, a.id).text, text, "the consumer applied the private edit to state only")
  })
})

test("B5 malformed envelopes and size bounds refuse at admission and in Node; plaintext and envelope bounds hold", async () => {
  await withRoute(seed(1), async () => {
    const key = sealKey()
    const route = await readRouteRecord()
    const fields = { schema_version: 2, command_id: "61111111-2222-4333-8444-555555555555", action: "draft_update", operation: "edit",
      requested_at: new Date(Math.floor(Date.now() / 1000) * 1000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      expires_at: new Date(Math.floor(Date.now() / 1000) * 1000 + 600000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      producer: { kind: "dashboard_editor", generation: "1" }, actor_subject: "dashboard-operator", route_activation: route.command_id }
    assert.throws(() => sealEnvelope(fields, { targets: [], payload: { x: "y".repeat(MAX_PLAINTEXT_BYTES) } }, key), error => error.code === "command_too_large")
    const near = sealEnvelope(fields, { targets: [], payload: { x: "y".repeat(MAX_PLAINTEXT_BYTES - 40) } }, key)
    assert.ok(Buffer.byteLength(near) <= MAX_ENVELOPE_BYTES && Buffer.byteLength(near) < 65535)
    assert.equal(admit(near).result.admitted, true, "the largest sealable plaintext stays within the dispatch bound")
    const valid = JSON.parse(near)
    const bad = {
      "missing-seal-field": { ...valid, seal: { ...valid.seal, tag: undefined } },
      "short-iv": { ...valid, seal: { ...valid.seal, iv: Buffer.alloc(8).toString("base64") } },
      "non-canonical-b64": { ...valid, seal: { ...valid.seal, tag: valid.seal.tag.replace(/=*$/, "") } },
      "unknown-alg": { ...valid, seal: { ...valid.seal, alg: "A128GCM" } },
      "operation-not-for-action": { ...valid, operation: "post_feedback" },
      "extra-field": { ...valid, payload: {} },
      "oversize-ciphertext": { ...valid, seal: { ...valid.seal, ciphertext: Buffer.alloc(46010, 1).toString("base64") } },
    }
    for (const [label, value] of Object.entries(bad)) {
      const raw = canonical(JSON.parse(JSON.stringify(value)))
      assert.equal(admit(raw).result.admitted, false, label)
      assert.throws(() => parseEnvelope(raw), label)
    }
    assert.equal(admit("x".repeat(64001)).result.code, "command_too_large")
  })
})

test("B1 an authentic envelope cannot carry a generic patch, foreign request fields or an approval without its intent", async () => {
  await withRoute(seed(1), async (gist) => {
    const snap = await readStateGistSnapshot()
    const draft = snap.state.drafts[0]
    const route = await readRouteRecord()
    const update = { draft_id: draft.id, expected_snapshot: draftMutationSnapshot(draft, snap.state), expected_numeric_sha256: numericIdentitySha256(snap.document, draft.id) }
    const base = { operation: "edit", params_json: JSON.stringify({ editedText: "x" }), updates: [update], media_descriptor_json: null,
      publish_intent_id: null, checked_policy_sha256: null, checked_automatic_epoch: null }
    const build = (operation, payload) => buildSealedCommand({ action: "draft_update", operation, producerKind: "dashboard_editor",
      actorSubject: "dashboard-operator", route, targets: [{ draft_id: draft.id, ...identity(draft) }], payload: { ...base, operation, ...payload } }).raw
    const cases = {
      patch: build("edit", { patch_json: JSON.stringify({ set: { status: "approved" }, unset: [], order: [] }) }),
      foreign: build("reject", { params_json: JSON.stringify({ status: "approved" }) }),
      intentless: build("approve", { params_json: "{}", checked_policy_sha256: dashboardEditorialPolicy(snap.state).policy_sha256 }),
      intentOnReject: build("reject", { params_json: "{}", publish_intent_id: "33333333-3333-4333-8333-333333333333" }),
    }
    const report = await consume(Object.values(cases).map(raw => entry(raw)))
    assert.deepEqual(report.refused.map(row => row.code), ["invalid_payload", "invalid_payload", "invalid_payload", "invalid_payload"])
    assert.deepEqual(report.applied, [])
    assert.equal(byId(gist, draft.id).status, "pending")
  })
})
