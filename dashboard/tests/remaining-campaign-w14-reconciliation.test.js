import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import path from "node:path"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { decideReconciliation, inspectReconciliation, ReconciliationError } from "../lib/delivery-reconciliation.js"
import { GET, POST } from "../app/api/delivery-reconciliation/route.js"
import DeliveryReconciliation from "../app/components/DeliveryReconciliation.js"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const VECTORS = JSON.parse(readFileSync(path.join(root, "tests/fixtures/w14_delivery_reconciliation_vectors.json"), "utf8"))
const subset = (actual, expected) => expected !== null && typeof expected === "object"
  ? actual !== null && typeof actual === "object" && Object.entries(expected).every(([k, v]) => subset(actual[k], v))
  : actual === expected

for (const kase of VECTORS.cases) {
  test(`shared vector ${kase.name} gives the Python result`, () => {
    let state = structuredClone(VECTORS.state)
    for (const step of kase.steps) {
      const before = structuredClone(state)
      if (step.expect.code) {
        assert.throws(() => decideReconciliation(state, step.request, { actor: "w14-publisher", at: "2026-10-30T11:00:00Z" }),
          error => error instanceof ReconciliationError && error.code === step.expect.code)
        assert.deepEqual(state, before)
        continue
      }
      const out = decideReconciliation(state, step.request, { actor: "w14-publisher", at: "2026-10-30T11:00:00Z" })
      state = out.state
      assert.equal(out.result.status, step.expect.status)
      assert.ok(subset(state.publish_ledger[step.request.event_id], step.expect.row || {}))
      if (step.expect.draft_status) assert.equal(state.drafts.find(d => d.event_id === step.request.event_id).status, step.expect.draft_status)
    }
  })
}

test("inspection and applied rows are byte-identical to the Python command path", () => {
  const python = process.env.THEHEAT_TEST_PYTHON || "python3"
  const confirm = VECTORS.cases[0].steps[0].request
  const script = "import json,sys\nfrom src.commands.delivery_reconciliation import inspect, decide\n" +
    "v=json.load(sys.stdin)\nstate,_=decide(v['state'],v['request'],actor='w14-publisher',at='2026-10-30T11:00:00Z')\n" +
    "print(json.dumps({'inspect':inspect(v['state']),'row':state['publish_ledger'][v['request']['event_id']]},sort_keys=True))"
  const run = spawnSync(python, ["-I", "-c", `import sys; sys.path.insert(0, ${JSON.stringify(root)})\n${script}`],
    { cwd: root, input: JSON.stringify({ state: VECTORS.state, request: confirm }), encoding: "utf8" })
  assert.equal(run.status, 0, run.stderr)
  const fromPython = JSON.parse(run.stdout)
  assert.deepEqual(inspectReconciliation(VECTORS.state), fromPython.inspect)
  const { state } = decideReconciliation(VECTORS.state, confirm, { actor: "w14-publisher", at: "2026-10-30T11:00:00Z" })
  assert.deepEqual(state.publish_ledger[confirm.event_id], fromPython.row)
})

async function gist(run, initial = VECTORS.state) {
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "editor", DASHBOARD_PASSWORD: "invented-test-only",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "fixture_state", GITHUB_TOKEN: "fixture_token" })
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  const original = globalThis.fetch, patches = []
  let current = structuredClone(initial)
  globalThis.fetch = async (url, options = {}) => {
    if (url === "https://api.github.com/gists/fixture_state" && options.method === "PATCH") {
      const body = JSON.parse(options.body)
      current = JSON.parse(body.files["state.json"].content)
      patches.push(current)
      return Response.json({})
    }
    if (url === "https://api.github.com/gists/fixture_state") return Response.json({ files: { "state.json": { content: JSON.stringify(current) } } })
    throw new Error(`unexpected egress ${url}`)
  }
  try { return await run({ patches, latest: () => current }) } finally { globalThis.fetch = original; delete process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED }
}
const auth = { authorization: `Basic ${btoa("editor:invented-test-only")}`, origin: "https://dashboard.example" }
const post = body => new Request("https://dashboard.example/api/delivery-reconciliation",
  { method: "POST", headers: { ...auth, "content-type": "application/json" }, body: JSON.stringify(body) })

test("route inspects, refuses by default, then confirms once and repeats as unchanged", async () => {
  await gist(async ({ patches, latest }) => {
    const view = await (await GET(new Request("https://dashboard.example/api/delivery-reconciliation", { headers: auth }))).json()
    assert.equal(view.mutation, "none"); assert.equal(view.writes_enabled, false)
    assert.deepEqual(view.rows.find(r => r.event_id === "w14-ev-unknown").actions, ["confirm", "cancel"])
    const confirm = VECTORS.cases[0].steps[0].request
    const disabled = await POST(post(confirm))
    assert.equal(disabled.status, 503); assert.equal((await disabled.json()).code, "delivery_reconciliation_disabled")
    process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED = "1"
    const stale = await POST(post({ ...confirm, reconciliation_id: "w14-stale", expected_decision_revision: 1 }))
    assert.equal(stale.status, 409); assert.equal((await stale.json()).code, "stale_decision_revision")
    const unrelated = await POST(post({ ...confirm, reconciliation_id: "w14-unrelated", receipt: { ...confirm.receipt, tweet_id: "1900000000000000777" } }))
    assert.equal((await unrelated.json()).code, "receipt_bound_elsewhere")
    assert.equal(patches.length, 0)
    const applied = await (await POST(post(confirm))).json()
    assert.equal(applied.status, "applied"); assert.equal(patches.length, 1)
    const row = latest().publish_ledger["w14-ev-unknown"]
    assert.equal(row.phase, "confirmed"); assert.equal(row.tweet_id, "1900000000000000901"); assert.equal(row.text, "Invented Fenwick Hollow reached 41 C.")
    assert.equal(latest().drafts.length, VECTORS.state.drafts.length)
    assert.equal(latest().publish_ledger["w14-ev-media"].phase, "unknown")
    const repeated = await (await POST(post(confirm))).json()
    assert.equal(repeated.status, "unchanged"); assert.equal(patches.length, 1)
  })
})

test("operations component renders holds and receipt-only actions", () => {
  const view = inspectReconciliation(VECTORS.state)
  const html = renderToStaticMarkup(React.createElement(DeliveryReconciliation, { initial: view }))
  assert.match(html, /Outcome unknown — needs a receipt/)
  assert.match(html, /Timing or silence is never proof/)
  assert.match(html, /Confirm with receipt/)
  assert.match(html, /Image description as published/)
  assert.match(html, /Not sent \(proven\)/)
  assert.doesNotMatch(html, /1900000000000000777/) // delivered rows without a reconciliation are not actionable here
})
