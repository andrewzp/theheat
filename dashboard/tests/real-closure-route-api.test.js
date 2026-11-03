// P00c: command-result retrieval, retained-body resubmission and lost responses.
// OFFLINE FIXTURE: in-process whole-file Gist + recorded workflow dispatches; no network.
// v2 (ROUTE-CONTRACT-v2): commands are sealed envelopes bound to the active route activation
// (invented test seal key, seeded active route record); status uses exact-name artifact queries,
// so an admission refusal reports the generic `admission_refused` (its specific code is in the run log).
import test from "node:test"
import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { importFresh } from "./helpers/import-fresh.js"
import { installMemoryGist, ROUTE_ACTIVATION, routeEnv, routeRecord, TEST_SEAL_KEY } from "./helpers/route-memory-gist.js"
import { policy, runtimeRun, initializeRevision, draftIdentity, textHash, fingerprint } from "./helpers/review-policy.js"
import { RESULTS_FILE, ROUTE_FILE } from "../lib/gist-write-route.js"
import { buildSealedCommand } from "../lib/gist-route-submit.js"
import { followRouteCommand } from "../lib/route-command-recovery.js"

const sha = text => createHash("sha256").update(text, "utf8").digest("hex")
const auth = { authorization: `Basic ${Buffer.from("reviewer:invented-pass").toString("base64")}` }
const ACTIVE = { schema_version: 1, mode: "serialized", generation: 1, changed_at: "2026-10-30T12:00:00Z", changed_by_run: "77:consume", command_id: ROUTE_ACTIVATION }
function seed() {
  const draft = { id: "draft_route_1", event_id: "event_draft_route_1", type: "hot10", status: "pending", text: "Invented City reached 40°C today.",
    created_at: "2026-10-30T12:00:00Z", review_context: { two_bot: { bundle: { event_id: "event_draft_route_1" }, fact_check: { passed: true }, critic: { passed: true } } } }
  const proof = draft.review_context.two_bot
  proof.reviewed_text_sha256 = textHash(draft.text)
  proof.reviewed_policy_sha256 = fingerprint(policy)
  proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
  return { drafts: [initializeRevision(draft)], publish_ledger: {}, run_history: [runtimeRun(new Date().toISOString())] }
}
const sealed = (now = new Date()) => buildSealedCommand({ action: "draft_update", operation: "reject", producerKind: "dashboard_editor",
  actorSubject: "dashboard-operator", route: ACTIVE, now,
  targets: [{ draft_id: "draft_route_1", content_revision: 1, decision_revision: 0, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) }],
  payload: { operation: "reject", params_json: "{}", updates: [{ draft_id: "draft_route_1", expected_snapshot: "c".repeat(64), expected_numeric_sha256: "d".repeat(64) }],
    media_descriptor_json: null, publish_intent_id: null, checked_policy_sha256: null, checked_automatic_epoch: null } })
const routeOn = extra => routeEnv({ THEHEAT_GIST_WRITE_ROUTE: "serialized", THEHEAT_COMMAND_SEAL_KEY: TEST_SEAL_KEY, ...extra })

async function status(id, query = "") {
  const handler = await importFresh("app/api/commands/[id]/route.js")
  const response = await handler.GET(new Request(`http://localhost/api/commands/${id}${query}`, { headers: auth }), { params: Promise.resolve({ id }) })
  return { status: response.status, body: await response.json() }
}

test("status: applied, refused, pending (admitted, unconsumed), unknown, admission refusal and reused-id digest", async () => {
  const restore = routeOn()
  const { raw, command_id: id, digest } = sealed()
  const gist = installMemoryGist({ gists: { routestategist: { "state.json": "{}" }, routefeedbackgist: {} } })
  try {
    assert.deepEqual((await status(id)).body, { command_id: id, status: "unknown" })
    gist.artifacts.push({ id: 1, name: `theheat-command-${id}`, expired: false, created_at: new Date().toISOString() })
    assert.deepEqual((await status(id)).body, { command_id: id, status: "pending" })
    gist.store.routestategist[RESULTS_FILE] = JSON.stringify({ schema_version: 1, results: { [id]: { status: "applied", code: null, digest,
      consumed_at: "2026-10-30T12:00:00.000Z" } } })
    assert.equal((await status(id)).body.status, "applied")
    assert.deepEqual((await status(id, `?digest=${"e".repeat(64)}`)).body, { command_id: id, status: "refused", code: "command_id_reused", digest })
    gist.store.routestategist[RESULTS_FILE] = JSON.stringify({ schema_version: 1, results: { [id]: { status: "refused", code: "revision_conflict", digest } } })
    assert.deepEqual([(await status(id)).body.status, (await status(id)).body.code], ["refused", "revision_conflict"])
    const other = sealed().command_id
    gist.artifacts.push({ id: 2, name: `theheat-admission-refused-${other}`, expired: false })
    assert.deepEqual((await status(other)).body, { command_id: other, status: "refused", code: "admission_refused" })
    assert.equal((await status("not-a-uuid")).status, 400)
    const handler = await importFresh("app/api/commands/[id]/route.js")
    const anonymous = await handler.GET(new Request(`http://localhost/api/commands/${id}`), { params: Promise.resolve({ id }) })
    assert.equal(anonymous.status, 401)
    assert.ok(raw.length > 0)
  } finally { gist.restore(); restore() }
})

test("resubmission re-dispatches the exact retained bytes; expired or altered bytes are refused", async () => {
  const restore = routeOn()
  const gist = installMemoryGist({ gists: { routestategist: { "state.json": "{}", [ROUTE_FILE]: routeRecord() } } })
  try {
    const { raw } = sealed()
    const handler = await importFresh("app/api/commands/route.js")
    const send = async body => handler.POST(new Request("http://localhost/api/commands", { method: "POST",
      headers: { ...auth, "Content-Type": "application/json", origin: "http://localhost" }, body: JSON.stringify(body) }))
    const ok = await send({ command: raw })
    assert.equal(ok.status, 202)
    assert.equal(gist.dispatches[0].body.inputs.command, raw, "byte-identical resubmission")
    assert.equal((await send({ command: raw.replace('"reject"', '"reject" ') })).status, 400)
    const old = sealed(new Date(Date.now() - 2 * 3600000)).raw
    const expired = await send({ command: old })
    assert.equal(expired.status, 409)
    assert.equal((await expired.json()).code, "expired")
    assert.equal(gist.dispatches.length, 1)
    const crossSite = await handler.POST(new Request("http://localhost/api/commands", { method: "POST",
      headers: { ...auth, "Content-Type": "application/json", origin: "https://elsewhere.invalid" }, body: JSON.stringify({ command: raw }) }))
    assert.equal(crossSite.status, 403)
  } finally { gist.restore(); restore() }
})

test("a lost dispatch response is uncertain with the retained command; a refused dispatch is not submitted", async () => {
  for (const [options, code, httpStatus] of [[{ dispatchThrows: true }, "command_submission_uncertain", 503], [{ dispatchStatus: 422 }, "command_submission_failed", 502]]) {
    const restore = routeOn()
    const initial = seed()
    const gist = installMemoryGist({ gists: { routestategist: { "state.json": JSON.stringify(initial), [ROUTE_FILE]: routeRecord() } }, ...options })
    try {
      const handler = await importFresh("app/api/drafts/route.js")
      const draft = initial.drafts[0]
      const response = await handler.POST(new Request("http://localhost/api/drafts", { method: "POST", headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ action: "reject", draftId: draft.id, expectedRevision: { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 } }) }))
      const body = await response.json()
      assert.equal(response.status, httpStatus)
      assert.equal(body.code, code)
      assert.equal(body.ok, false, "never reported as saved")
      if (code === "command_submission_uncertain") assert.equal(body.command, gist.dispatches[0].body.inputs.command)
      assert.deepEqual(gist.patches, [])
    } finally { gist.restore(); restore() }
  }
})

test("client follow-up resubmits the same bytes only after an uncertain submission that is still unknown", async () => {
  const restore = routeOn()
  let built
  try { built = sealed() } finally { restore() }
  const { raw, command_id, digest } = built
  const calls = []
  const answers = [{ status: "unknown" }, { status: "pending" }, { status: "applied", code: null }]
  const fetchImpl = async (url, init = {}) => {
    calls.push([init.method || "GET", url, init.body ?? null])
    if (init.method === "POST") return new Response(JSON.stringify({ status: "pending", command_id }), { status: 202 })
    return new Response(JSON.stringify({ command_id, ...answers.shift() }), { status: 200 })
  }
  const outcome = await followRouteCommand({ command_id, digest, command: raw, status: "submission_uncertain" },
    { fetchImpl, sleep: async () => {}, attempts: 5 })
  assert.equal(outcome.status, "applied")
  assert.deepEqual(calls.filter(([method]) => method === "POST").map(([, , body]) => JSON.parse(body).command), [raw])
  const confirmedCalls = []
  const quiet = await followRouteCommand({ command_id, digest, command: raw, status: "pending" },
    { fetchImpl: async (url, init = {}) => { confirmedCalls.push(init.method || "GET"); return new Response(JSON.stringify({ status: "unknown" })) },
      sleep: async () => {}, attempts: 3 })
  assert.equal(quiet.status, "pending")
  assert.ok(!confirmedCalls.includes("POST"), "a confirmed submission is never resubmitted")
  assert.equal(sha(raw), digest)
})
