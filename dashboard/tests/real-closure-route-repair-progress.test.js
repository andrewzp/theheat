// ROUTE repair B.2 (ROUTE-CONTRACT-v2 §4): the drain budget counts NEW work after persisted
// duplicates are settled; an artifact is acknowledged (deleted) only after a fresh Gist read shows
// its terminal result; status is truthful by exact-name query. REAL drafts handler + REAL consumer;
// the paginated inbox scan is proven in tests/real_closure/test_route_repair_progress.py.
// OFFLINE FIXTURE (in-process Gist and artifact store). Red: red-b2-drain-starvation.txt.
import test from "node:test"
import assert from "node:assert/strict"
import { acknowledgeArtifacts } from "../lib/gist-command-consumer.js"
import { byId, commandStatus, consume, entry, identity, post, resultsDoc, seed, sha, stateOf, withConsumerEnv, withRoute } from "./helpers/route-repair-fixture.js"

async function rejectAll(gist, ids) {
  const out = []
  for (const id of ids) {
    const draft = stateOf(gist).drafts.find(row => row.id === id)
    const response = await post("app/api/drafts/route.js", { action: "reject", draftId: id, expectedRevision: identity(draft) })
    assert.equal(response.status, 202)
    out.push(response.body.command)
  }
  return out
}

// Admitted artifacts as the inbox presents them: one per command, plus unrelated ones interleaved.
function artifactsFor(gist, raws, { unrelated = 0 } = {}) {
  let id = 1000
  const now = Date.now()
  raws.forEach((raw, index) => {
    for (let n = 0; n < unrelated; n += 1) gist.artifacts.push({ id: id++, name: `bot-report-${index}-${n}`, expired: false, created_at: new Date(now).toISOString() })
    gist.artifacts.push({ id: id++, name: `theheat-command-${JSON.parse(raw).command_id}`, expired: false, created_at: new Date(now).toISOString() })
  })
  return raws.map(raw => entry(raw, { artifact_id: gist.artifacts.find(row => row.name === `theheat-command-${JSON.parse(raw).command_id}`).id }))
}

const ack = entries => withConsumerEnv({}, () => acknowledgeArtifacts(entries, { token: "invented", repo: "invented/theheat" }))

test("B2 >100 commands: drain 1 applies 100 and defers 1; drain 2 applies the 101st (duplicates never use the budget); acks retire them", async () => {
  await withRoute(seed(101), async (gist) => {
    const raws = await rejectAll(gist, stateOf(gist).drafts.map(row => row.id))
    const entries = artifactsFor(gist, raws, { unrelated: 2 })
    const first = await consume(entries)
    assert.deepEqual([first.applied.length, first.duplicates.length, first.deferred], [100, 0, 1])
    const firstAck = await ack(entries)
    assert.equal(firstAck.deleted.length, 100, "only the 100 durably recorded artifacts are retired")
    assert.equal(gist.artifacts.filter(row => row.name.startsWith("theheat-command-")).length, 1)
    assert.equal(gist.artifacts.length, 101 * 2 + 1, "unrelated artifacts untouched")
    // Even if the retired artifacts were still listed (e.g. a failed delete), they settle first.
    const second = await consume(entries)
    assert.deepEqual([second.applied.length, second.duplicates.length, second.deferred], [1, 100, 0])
    const secondAck = await ack(entries)
    assert.ok(secondAck.deleted.some(row => row.command_id === JSON.parse(raws.at(-1)).command_id))
    assert.equal(gist.deleted.length, 101, "each artifact deleted exactly once (already-gone ones answer 404)")
    assert.equal(gist.artifacts.filter(row => row.name.startsWith("theheat-command-")).length, 0)
    assert.ok(stateOf(gist).drafts.every(row => row.status === "rejected"))
  })
})

test("B2 restart mid-drain: a failed PATCH persists and acknowledges nothing; a crash after PATCH re-settles as duplicates", async () => {
  await withRoute(seed(3), async (gist) => {
    const raws = await rejectAll(gist, ["draft_route_1", "draft_route_2", "draft_route_3"])
    const entries = artifactsFor(gist, raws)
    const before = JSON.stringify(gist.store.routestategist)
    gist.restore()
    const failing = (await import("./helpers/route-memory-gist.js")).installMemoryGist({ gists: { routestategist: { ...gist.store.routestategist }, routefeedbackgist: {} },
      artifacts: gist.artifacts, patchStatus: 500 })
    await assert.rejects(consume(entries))
    assert.equal((await ack(entries)).deleted.length, 0, "nothing durable, nothing acknowledged")
    assert.equal(JSON.stringify(failing.store.routestategist), before)
    failing.restore()
    const healthy = (await import("./helpers/route-memory-gist.js")).installMemoryGist({ gists: { routestategist: failing.store.routestategist, routefeedbackgist: {} },
      artifacts: failing.artifacts })
    const applied = await consume(entries)
    assert.equal(applied.applied.length, 3)
    // "Crash" between PATCH and acknowledgement: the next drain settles them as duplicates and retires them.
    const again = await consume(entries)
    assert.deepEqual([again.applied.length, again.duplicates.length, again.state_patches], [0, 3, 0])
    assert.equal((await ack(entries)).deleted.length, 3)
    healthy.restore()
  })
})

test("B2 expiry and truthful status: expired commands are recorded and retired; exact-name status is pending/expired/applied/unknown", async () => {
  await withRoute(seed(2), async (gist) => {
    const [first, second] = await rejectAll(gist, ["draft_route_1", "draft_route_2"])
    const entries = artifactsFor(gist, [first, second], { unrelated: 150 })
    const id1 = JSON.parse(first).command_id, id2 = JSON.parse(second).command_id
    assert.deepEqual((await commandStatus(id1)).body, { command_id: id1, status: "pending" }, "found by exact name among 300 unrelated artifacts")
    const old = gist.artifacts.find(row => row.name === `theheat-command-${id2}`)
    old.created_at = new Date(Date.now() - 25 * 3600000).toISOString()
    assert.deepEqual((await commandStatus(id2)).body, { command_id: id2, status: "refused", code: "expired" }, "unconsumed past its lifetime")
    const later = new Date(Date.now() + 2 * 3600000)
    const report = await consume([entries[0]], {}, { now: () => later })
    assert.deepEqual(report.refused.map(row => row.code), ["expired"])
    assert.equal(byId(gist, "draft_route_1").status, "pending")
    assert.equal((await ack([entries[0]])).deleted.length, 1)
    assert.deepEqual((await commandStatus(id1, sha(first))).body.code, "expired")
    assert.deepEqual((await commandStatus("71111111-2222-4333-8444-555555555555")).body.status, "unknown")
    assert.equal(resultsDoc(gist).results[id1].status, "refused")
  })
})

test("B2 acknowledgement never retires an unconsumed, deferred, skipped or unknown artifact", async () => {
  await withRoute(seed(2), async (gist) => {
    const raws = await rejectAll(gist, ["draft_route_1", "draft_route_2"])
    const entries = artifactsFor(gist, raws)
    assert.equal((await ack(entries)).deleted.length, 0, "nothing consumed yet")
    const skipped = await consume(entries, { THEHEAT_COMMAND_SEAL_KEY: undefined })
    assert.equal(skipped.skipped.length, 2)
    assert.equal((await ack(entries)).deleted.length, 0, "skipped (no key) is not terminal")
    assert.equal(gist.artifacts.length, 2)
  })
})
