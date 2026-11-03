// ROUTE repairs for root's c749 checkpoint, Node side (R2, R4). OFFLINE FIXTURE: in-process Gist,
// recorded dispatches; a process stop is modelled by a POST that never answers (the run is then
// abandoned and a NEW consumer resumes from the durable Gist alone). No real sender is run.
// Red: receipts/red-review3-r2-sender-plaintext.txt, red-review3-r4-batch-journal.txt.
import test from "node:test"
import assert from "node:assert/strict"
import { runSenderOutbox } from "../lib/gist-command-consumer.js"
import { RESULTS_FILE } from "../lib/gist-write-route.js"
import { installMemoryGist } from "./helpers/route-memory-gist.js"
import { admit, byId, consume, entry, identity, post, resultsDoc, seed, stateOf, withConsumerEnv, withRoute } from "./helpers/route-repair-fixture.js"

const PRIVATE = "PRIVATE unpublished approved copy: Invented Ford reached 41°C."
const tick = () => new Promise(resolve => setTimeout(resolve, 10))
const outbox = () => withConsumerEnv({}, () => runSenderOutbox({ token: "invented", repo: "invented/theheat" }))
const bot = gist => gist.dispatches.filter(row => row.workflow === "bot.yml")
const answer = status => new Response(status === 204 ? null : "{}", { status })

async function approveTwo(gist) {
  const raws = []
  for (const id of ["draft_route_1", "draft_route_2"]) {
    const draft = stateOf(gist).drafts.find(row => row.id === id)
    raws.push((await post("app/api/drafts/route.js", { action: "approve", draftId: id, expectedRevision: identity(draft) })).body.command)
  }
  assert.equal((await consume(raws.map(raw => entry(raw)))).outbox_queued.length, 2)
  const ids = Object.keys(resultsDoc(gist).outbox)
  return { a: ids[0], b: ids[1] }
}

// Start a drain whose N-th bot.yml POST never answers; wait until that POST was made.
async function stopDuring(gist, nth) {
  void outbox()
  for (let i = 0; i < 200 && bot(gist).length < nth; i += 1) await tick()
  assert.equal(bot(gist).length, nth)
  await tick()
}

// A NEW consumer process: only what the Gist durably holds survives.
async function restart(gist, run) {
  const fresh = installMemoryGist({ gists: { routestategist: { ...gist.store.routestategist }, routefeedbackgist: {} } })
  try { return await run(fresh) } finally { fresh.restore() }
}

test("R4 interrupted during A: B stays queued (never attempted) and is dispatched after restart; A becomes uncertain, not resent", async () => {
  await withRoute(seed(2), async (gist) => {
    const { a, b } = await approveTwo(gist)
    await stopDuring(gist, 1)
    const journal = resultsDoc(gist).outbox
    assert.deepEqual([journal[a].state, journal[a].attempts, journal[b].state, journal[b].attempts], ["dispatching", 1, "queued", 0])
    await restart(gist, async (fresh) => {
      const report = await outbox()
      assert.deepEqual(report.dispatches.map(row => [row.publish_intent_id, row.state]), [[b, "dispatched"]])
      const after = JSON.parse(fresh.store.routestategist[RESULTS_FILE]).outbox
      assert.deepEqual([after[a].state, after[a].code, after[b].state, after[b].attempts], ["uncertain", "dispatch_outcome_unknown", "dispatched", 1])
      assert.deepEqual(bot(fresh).map(row => row.body.inputs.publish_intent_id), [b], "A is never blindly resent")
    })
  }, { gist: { dispatchHandler: row => row.workflow === "bot.yml" ? new Promise(() => {}) : answer(204) } })
})

test("R4 A gets a definite 4xx, then the process stops during B: A's failure survives and is recovered; B is uncertain", async () => {
  let posts = 0
  await withRoute(seed(2), async (gist) => {
    const { a, b } = await approveTwo(gist)
    await stopDuring(gist, 2)
    const journal = resultsDoc(gist).outbox
    assert.deepEqual([journal[a].state, journal[a].code, journal[a].attempts], ["failed", "dispatch_http_422", 1], "A's outcome was persisted before B's attempt")
    assert.deepEqual([journal[b].state, journal[b].attempts], ["dispatching", 1])
    await restart(gist, async (fresh) => {
      const report = await outbox()
      assert.deepEqual(report.dispatches.map(row => [row.publish_intent_id, row.state]), [[a, "dispatched"]])
      const after = JSON.parse(fresh.store.routestategist[RESULTS_FILE]).outbox
      assert.deepEqual([after[a].state, after[a].attempts, after[b].state], ["dispatched", 2, "uncertain"])
    })
  }, { gist: { dispatchHandler: row => {
    if (row.workflow !== "bot.yml") return answer(204)
    posts += 1
    return posts === 1 ? answer(422) : new Promise(() => {})
  } } })
})

test("R2 approval -> sealed intake -> outbox -> dispatch: no input, journal or report carries the private text", async () => {
  await withRoute(seed(1), async (gist) => {
    const draft = stateOf(gist).drafts[0]
    const edit = await post("app/api/drafts/route.js", { action: "edit", draftId: draft.id, expectedRevision: identity(draft), editedText: PRIVATE })
    assert.equal(admit(edit.body.command).result.admitted, true)
    await consume([entry(edit.body.command)])
    const edited = byId(gist, draft.id)
    // The edited draft needs a human review before approval (the same rules as the legacy route).
    const { dashboardEditorialPolicy } = await import("../lib/editorial-policy.js")
    const reviewed = await post("app/api/drafts/route.js", { action: "review", draftId: draft.id, expectedRevision: identity(edited), reviewConfirmed: true,
      expectedPolicySha256: dashboardEditorialPolicy(stateOf(gist)).policy_sha256 })
    await consume([entry(reviewed.body.command)])
    const approve = await post("app/api/drafts/route.js", { action: "approve", draftId: draft.id, expectedRevision: identity(byId(gist, draft.id)) })
    const consumed = await consume([entry(approve.body.command)])
    assert.equal(consumed.applied.length, 1, JSON.stringify(consumed.refused))
    const report = await outbox()
    assert.deepEqual(report.dispatches.map(row => row.state), ["dispatched"])
    const [dispatch] = bot(gist)
    assert.deepEqual(Object.keys(dispatch.body.inputs).sort(), ["draft_id", "mode", "publish_intent_id", "text_source"])
    assert.equal(dispatch.body.inputs.text_source, "state")
    for (const surface of [JSON.stringify(gist.dispatches), JSON.stringify(report), JSON.stringify(consumed), gist.store.routestategist[RESULTS_FILE]]) {
      assert.ok(!surface.includes(PRIVATE) && !surface.includes("41°C"), surface.slice(0, 200))
    }
    assert.equal(byId(gist, draft.id).text, PRIVATE, "the approved bytes live only in the secret Gist state")
  })
})
