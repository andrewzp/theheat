import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { decideReconciliation, inspectReconciliation, retryPermitted } from "../lib/delivery-reconciliation.js"
import { draftIdentity } from "../lib/draft-revisions.js"
import { GET, POST } from "../app/api/delivery-reconciliation/route.js"

const vectors = JSON.parse(readFileSync(new URL("../../tests/fixtures/w14_delivery_reconciliation_vectors.json", import.meta.url), "utf8"))
const steps = vectors.cases.at(-1).steps
const event = steps[0].request.event_id
const at = "2026-10-30T11:00:00Z"
const auth = { authorization: `Basic ${btoa("editor:invented-test-only")}`, origin: "https://dashboard.example" }
const post = body => new Request("https://dashboard.example/api/delivery-reconciliation", {
  method: "POST", headers: { ...auth, "content-type": "application/json" }, body: JSON.stringify(body),
})
const get = () => new Request("https://dashboard.example/api/delivery-reconciliation", { headers: auth })

// Every HTTP access is replaced and restricted to this invented in-memory Gist.
async function gist(run, { initial = JSON.stringify(vectors.state), onGet = raw => raw, patchFailure = false } = {}) {
  const settings = { NODE_ENV: "production", DASHBOARD_USERNAME: "editor", DASHBOARD_PASSWORD: "invented-test-only",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "invented_reconciliation", GITHUB_TOKEN: "",
    THEHEAT_DELIVERY_RECONCILIATION_ENABLED: "1", THEHEAT_LOCAL_COMMAND_URL: "", VERCEL: "" }
  const env = Object.fromEntries(Object.keys(settings).map(key => [key, process.env[key]]))
  Object.assign(process.env, settings)
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  const original = globalThis.fetch, writes = [], methods = []
  let raw = initial, gets = 0
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(url, "https://api.github.com/gists/invented_reconciliation", "unexpected egress")
    const method = options.method || "GET"
    methods.push(method)
    if (method === "GET") {
      raw = onGet(raw, ++gets)
      return Response.json({ files: { "state.json": { content: raw } } })
    }
    assert.equal(method, "PATCH")
    raw = JSON.parse(options.body).files["state.json"].content
    writes.push(raw)
    if (patchFailure) throw new Error("invented lost PATCH response")
    return Response.json({})
  }
  try { await run({ writes, methods, raw: () => raw }) }
  finally {
    globalThis.fetch = original
    for (const [key, value] of Object.entries(env)) { if (value === undefined) delete process.env[key]; else process.env[key] = value }
  }
}

test("withdrawal is separate from transport, including reload and receipt idempotency", () => {
  let state = decideReconciliation(structuredClone(vectors.state), steps[0].request, { actor: "invented-publisher", at }).state
  const cancellation = structuredClone(state.publish_ledger[event].operator_cancellation)
  const view = inspectReconciliation(state).rows.find(row => row.event_id === event)
  assert.deepEqual(view.actions, ["confirm"])
  assert.equal(view.cancelled, true); assert.equal(view.retry_permitted, false)
  state = JSON.parse(JSON.stringify(state))
  state = decideReconciliation(state, steps[1].request, { actor: "invented-publisher", at }).state
  assert.equal(state.publish_ledger[event].phase, "confirmed")
  assert.deepEqual(state.publish_ledger[event].operator_cancellation, cancellation)
  assert.equal(retryPermitted(state.publish_ledger[event]), false)
  assert.equal(state.drafts[0].status, "rejected")
  assert.equal(decideReconciliation(state, steps[2].request, { actor: "invented-publisher", at }).result.status, "unchanged")
  assert.throws(() => decideReconciliation(state, steps[3].request, { actor: "invented-publisher", at }), { code: "delivered_content_retained" })
})

test("actual handler withdraws then accepts a late receipt while preserving withdrawal and no retry", async () => {
  await gist(async ({ writes, raw }) => {
    assert.equal((await POST(post(steps[0].request))).status, 200)
    const cancellation = structuredClone(JSON.parse(raw()).publish_ledger[event].operator_cancellation)
    const view = await (await GET(get())).json()
    const row = view.rows.find(row => row.event_id === event)
    assert.deepEqual(row.actions, ["confirm"]); assert.equal(row.retry_permitted, false)
    const confirmed = await POST(post(steps[1].request))
    assert.equal(confirmed.status, 200, JSON.stringify(await confirmed.json()))
    const state = JSON.parse(raw())
    assert.equal(state.publish_ledger[event].phase, "confirmed")
    assert.deepEqual(state.publish_ledger[event].operator_cancellation, cancellation)
    assert.equal(state.drafts[0].status, "rejected"); assert.equal(retryPermitted(state.publish_ledger[event]), false)
    assert.equal((await (await POST(post(steps[2].request))).json()).status, "unchanged")
    assert.equal((await POST(post(steps[3].request))).status, 409)
    assert.equal(writes.length, 2)
  })
})

const drifts = {
  source: state => { state.drafts[0].review_context.two_bot.bundle.current_facts[0].value = "Invented changed source" },
  decision: state => { state.drafts[0].decision_revision++ },
  cancellation: state => { state.publish_ledger[event].operator_cancellation = { reconciliation_id: "invented-other-withdrawal" } },
  attempt: state => { state.publish_ledger[event].intent_id = "invented-replacement-intent" },
  media: state => { state.publish_ledger[event].delivery_identity = { alt_sha256: "1".repeat(64) } },
  target: state => { state.drafts[0].id = "invented-replacement-draft" },
  duplicate: state => { state.drafts.push(structuredClone(state.drafts[0])) },
}
for (const [name, mutate] of Object.entries(drifts)) {
  for (const changedRead of [2, 3]) test(`store GET #${changedRead} sees ${name} drift and returns 409 with zero PATCH`, async () => {
    await gist(async ({ writes, methods }) => {
      const response = await POST(post(vectors.cases[0].steps[0].request))
      assert.equal(response.status, 409)
      assert.equal((await response.json()).code, "revision_conflict")
      assert.equal(writes.length, 0); assert.deepEqual(methods, Array(changedRead).fill("GET"))
    }, { onGet: (raw, count) => { if (count !== changedRead) return raw; const state = JSON.parse(raw); mutate(state); return JSON.stringify(state) } })
  })
}

for (const action of ["confirm", "cancel"]) for (const owner of ["draft", "attempt"]) {
  for (const changedRead of [2, 3]) test(`${action}: raw ${owner} numeric drift on GET #${changedRead} refuses before PATCH`, async () => {
    const state = structuredClone(vectors.state)
    state.drafts[0].retained_number = 500
    state.publish_ledger[event].retained_number = 600
    const initial = JSON.stringify(state).replace('"retained_number":500', '"retained_number":500.0').replace('"retained_number":600', '"retained_number":600.0')
    const token = owner === "draft" ? "500.0" : "600.0"
    await gist(async ({ writes }) => {
      const response = await POST(post(action === "confirm" ? vectors.cases[0].steps[0].request : steps[0].request))
      assert.equal(response.status, 409); assert.equal((await response.json()).code, "revision_conflict")
      assert.equal(writes.length, 0)
    }, { initial, onGet: (raw, count) => count === changedRead ? raw.replace(token, token.slice(0, -2)) : raw })
  })
}

test("reconciliation is re-evaluated on final GET, including a receipt now bound elsewhere", async () => {
  await gist(async ({ writes }) => {
    const response = await POST(post(vectors.cases[0].steps[0].request))
    assert.equal(response.status, 409); assert.equal((await response.json()).code, "receipt_bound_elsewhere")
    assert.equal(writes.length, 0)
  }, { onGet: (raw, count) => {
    if (count !== 3) return raw
    const state = JSON.parse(raw)
    state.publish_ledger["w14-ev-confirmed"].tweet_id = vectors.cases[0].steps[0].request.receipt.tweet_id
    return JSON.stringify(state)
  } })
})

test("current target permits unrelated final-GET updates and preserves exact numeric lexemes", async () => {
  const state = structuredClone(vectors.state)
  state.drafts[0].review_context.two_bot.bundle.retained_number = 500
  state.publish_ledger[event].evidence_sha256 = draftIdentity(state.drafts[0]).evidence_sha256
  state.publish_ledger[event].retained_number = 600
  const request = { ...vectors.cases[0].steps[0].request, expected_evidence_sha256: state.publish_ledger[event].evidence_sha256 }
  const initial = JSON.stringify(state).replace('"retained_number":500', '"retained_number":500.0').replace('"retained_number":600', '"retained_number":600.0')
  await gist(async ({ writes, methods, raw }) => {
    assert.equal((await POST(post(request))).status, 200)
    assert.deepEqual(methods, ["GET", "GET", "GET", "PATCH"])
    assert.match(raw(), /"retained_number":500\.0/); assert.match(raw(), /"retained_number":600\.0/)
    assert.match(raw(), /"invented_extra":1\.0e3/)
    assert.deepEqual(JSON.parse(raw()).drafts, state.drafts)
    assert.deepEqual(JSON.parse(raw()).publish_ledger["w14-ev-media"], state.publish_ledger["w14-ev-media"])
    assert.equal(writes.length, 1)
  }, { initial, onGet: (raw, count) => count === 3 ? raw.replace(/}$/, ',"invented_extra":1.0e3}') : raw })
})

test("lost PATCH response remains unconfirmed, with one request and no automatic resend", async () => {
  await gist(async ({ writes, methods }) => {
    const response = await POST(post(vectors.cases[0].steps[0].request))
    assert.equal(response.status, 503); assert.equal((await response.json()).code, "reconciliation_write_unconfirmed")
    assert.equal(writes.length, 1); assert.deepEqual(methods, ["GET", "GET", "GET", "PATCH"])
    const replay = await (await POST(post(vectors.cases[0].steps[0].request))).json()
    assert.equal(replay.status, "unchanged"); assert.equal(writes.length, 1)
  }, { patchFailure: true })
})

test("withdrawn media still checks its receipt description through the actual handler", async () => {
  const request = structuredClone(vectors.cases.find(kase => kase.name === "media_alt_match").steps[0].request)
  const { receipt: _receipt, ...cancel } = request
  cancel.action = "cancel"; cancel.reconciliation_id = "invented-media-withdrawal"
  await gist(async ({ writes, raw }) => {
    assert.equal((await POST(post(cancel))).status, 200)
    const before = JSON.parse(raw()).publish_ledger[request.event_id]
    request.expected_decision_revision = 3
    const bad = { ...request, receipt: { ...request.receipt, alt_text: "Invented unrelated description." } }
    const refusal = await POST(post(bad))
    assert.equal(refusal.status, 409); assert.equal((await refusal.json()).code, "receipt_media_mismatch")
    assert.equal(writes.length, 1)
    assert.equal((await POST(post(request))).status, 200)
    const row = JSON.parse(raw()).publish_ledger[request.event_id]
    assert.deepEqual(row.operator_cancellation, before.operator_cancellation)
    assert.deepEqual(row.delivery_identity, before.delivery_identity)
    assert.equal(row.reconciliation.png_receipt_verification, "not_available_from_platform")
    assert.equal(retryPermitted(row), false); assert.equal(writes.length, 2)
  })
})
