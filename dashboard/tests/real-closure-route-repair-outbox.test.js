// ROUTE repair B.3 (ROUTE-CONTRACT-v2 §5): the durable sender outbox. The approval writes its
// entry in the SAME PATCH; dispatch outcomes are persisted; definitely-unattempted/failed work is
// recovered; uncertain dispatch is exposed and never blindly resent; the sender's existing
// pre-egress ledger claim and the legacy pre-dispatch checks gate every (re)dispatch.
// OFFLINE transports only (recorded dispatches, invented runs). No real sender is run or dispatched.
// Red: receipts/red-b3-lost-sender-followup-v2.txt.
import test from "node:test"
import assert from "node:assert/strict"
import { runSenderOutbox } from "../lib/gist-command-consumer.js"
import { RESULTS_FILE } from "../lib/gist-write-route.js"
import { OUTBOX_MAX_ACTIVE, OUTBOX_MAX_ATTEMPTS, RUN_TITLE_PREFIX } from "../lib/gist-sender-outbox.js"
import { byId, commandStatus, consume, entry, identity, post, resultsDoc, seed, stateOf, withConsumerEnv, withRoute } from "./helpers/route-repair-fixture.js"

const repo = "invented/theheat"
const outbox = (now, env = {}) => withConsumerEnv(env, () => runSenderOutbox({ token: "invented", repo, ...(now ? { now: () => now } : {}) }))
const bot = gist => gist.dispatches.filter(row => row.workflow === "bot.yml")
const entryOf = (gist, intent) => resultsDoc(gist).outbox[intent]

async function approved(gist, draftId = "draft_route_1") {
  const draft = stateOf(gist).drafts.find(row => row.id === draftId)
  const response = await post("app/api/drafts/route.js", { action: "approve", draftId, expectedRevision: identity(draft) })
  assert.equal(response.status, 202)
  const report = await consume([entry(response.body.command)])
  assert.equal(report.applied.length, 1, JSON.stringify(report.refused))
  return { commandId: response.body.command_id, intent: byId(gist, draftId).publish_intent_id }
}

function setOutbox(gist, intent, patch) {
  const document = resultsDoc(gist)
  document.outbox[intent] = { ...document.outbox[intent], ...patch }
  gist.store.routestategist[RESULTS_FILE] = JSON.stringify(document)
}

test("B3 the outbox entry is written in the approval's own PATCH; a 403 fails definitely and a later drain recovers it", async () => {
  let reply = 403
  await withRoute(seed(1), async (gist) => {
    const { commandId, intent } = await approved(gist)
    const approvalPatch = gist.patches.at(-1)
    assert.deepEqual(approvalPatch.files, [RESULTS_FILE, "state.json"], "state + results(outbox) in ONE PATCH")
    assert.equal(entryOf(gist, intent).state, "queued")
    const first = await outbox()
    assert.deepEqual(first.dispatches.map(row => [row.state, row.code]), [["failed", "dispatch_http_403"]])
    assert.deepEqual([entryOf(gist, intent).state, entryOf(gist, intent).attempts], ["failed", 1])
    assert.deepEqual((await commandStatus(commandId)).body.follow_up, { state: "failed", code: "dispatch_http_403", attempts: 1, publish_intent_id: intent })
    reply = 204
    const second = await outbox()
    assert.deepEqual(second.dispatches.map(row => row.state), ["dispatched"])
    assert.equal(entryOf(gist, intent).attempts, 2)
    const sent = bot(gist).at(-1).body.inputs
    assert.deepEqual(sent, { mode: "manual_tweet", tweet_text: byId(gist, "draft_route_1").text, draft_id: "draft_route_1", publish_intent_id: intent })
    assert.ok(!JSON.stringify(resultsDoc(gist)).includes(sent.tweet_text), "the outbox never stores text")
  }, { gist: { dispatchHandler: row => new Response(null, { status: row.workflow === "bot.yml" ? reply : 204 }) } })
})

test("B3 a stop between the approval PATCH and the dispatch loses nothing: the next drain dispatches the queued entry", async () => {
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    assert.equal(bot(gist).length, 0, "the consumer stopped before its outbox step")
    const later = await outbox()
    assert.deepEqual(later.dispatches.map(row => row.state), ["dispatched"])
    assert.equal(entryOf(gist, intent).state, "dispatched")
    assert.equal(bot(gist).length, 1)
  })
})

test("B3 uncertain dispatch (network error, 5xx, crash after the POST) is exposed and never resent", async () => {
  for (const handler of [() => { throw new TypeError("fetch failed") }, () => new Response("{}", { status: 502 })]) {
    await withRoute(seed(1), async (gist) => {
      const { commandId, intent } = await approved(gist)
      await outbox()
      assert.equal(entryOf(gist, intent).state, "uncertain")
      await outbox()
      await outbox()
      assert.equal(bot(gist).length, 1, "never blindly resent")
      assert.equal((await commandStatus(commandId)).body.follow_up.state, "uncertain")
    }, { gist: { dispatchHandler: row => row.workflow === "bot.yml" ? handler() : new Response(null, { status: 204 }) } })
  }
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    // Crash after `dispatching` was persisted, before its outcome: unknown whether GitHub got it.
    setOutbox(gist, intent, { state: "dispatching", attempts: 1, attempt_at: new Date().toISOString() })
    const report = await outbox()
    assert.deepEqual(report.dispatches, [])
    assert.deepEqual([entryOf(gist, intent).state, entryOf(gist, intent).code], ["uncertain", "dispatch_outcome_unknown"])
    assert.equal(bot(gist).length, 0)
  })
})

test("B3 the sender's pre-egress ledger claim resolves the entry (claimed -> completed / sender_refused), never a resend", async () => {
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    setOutbox(gist, intent, { state: "uncertain", code: "dispatch_request_uncertain", attempts: 1, attempt_at: new Date().toISOString() })
    const state = stateOf(gist)
    state.publish_ledger.event_draft_route_1 = { intent_id: intent, phase: "submitted", tweet_id: null, text: state.drafts[0].text }
    gist.store.routestategist["state.json"] = JSON.stringify(state)
    await outbox()
    assert.equal(entryOf(gist, intent).state, "claimed")
    state.publish_ledger.event_draft_route_1 = { intent_id: intent, phase: "confirmed", tweet_id: "1900000000000000002", text: state.drafts[0].text }
    gist.store.routestategist["state.json"] = JSON.stringify(state)
    await outbox()
    assert.equal(entryOf(gist, intent).state, "completed")
    assert.equal(bot(gist).length, 0)
  })
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    const state = stateOf(gist)
    state.publish_ledger.event_draft_route_1 = { intent_id: intent, phase: "not_sent", tweet_id: null }
    gist.store.routestategist["state.json"] = JSON.stringify(state)
    await outbox()
    assert.equal(entryOf(gist, intent).state, "sender_refused")
    assert.equal(bot(gist).length, 0)
  })
})

test("B3 a pending manual_tweet run cancelled/replaced before any claim is recovered (after it settles); a finished run without a claim is not", async () => {
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    const t0 = new Date()
    await outbox(t0)
    assert.equal(entryOf(gist, intent).state, "dispatched")
    const run = { id: 77, display_title: `${RUN_TITLE_PREFIX}${intent}`, status: "completed", conclusion: "cancelled", created_at: t0.toISOString(), updated_at: t0.toISOString() }
    gist.runs.push(run)
    await outbox(new Date(t0.getTime() + 60000))
    assert.equal(entryOf(gist, intent).state, "dispatched", "not judged before the settle window")
    assert.equal(bot(gist).length, 1)
    const report = await outbox(new Date(t0.getTime() + 10 * 60000))
    // Review R4: the plan records the definite failure; the attempt itself is journaled per entry around its POST.
    assert.deepEqual(report.changes.map(row => row.to), ["failed"])
    assert.deepEqual(report.dispatches.map(row => row.state), ["dispatched"])
    assert.deepEqual([entryOf(gist, intent).attempts, bot(gist).length], [2, 2], "re-dispatched exactly once")
    run.status = "completed"; run.conclusion = "success"; run.updated_at = new Date(t0.getTime() + 10 * 60000).toISOString()
    gist.runs.splice(0, 1, { ...run, id: 78, created_at: new Date(t0.getTime() + 10 * 60000).toISOString() })
    const finished = await outbox(new Date(t0.getTime() + 30 * 60000))
    assert.equal(entryOf(gist, intent).state, "sender_finished_without_claim", JSON.stringify({ finished, entry: entryOf(gist, intent), runs: gist.runs }))
    await outbox(new Date(t0.getTime() + 60 * 60000))
    assert.equal(bot(gist).length, 2, "a run that executed is never retried by the outbox")
  })
})

test("B3 a 200 dispatch response's workflow_run_id is recorded and used for reconciliation", async () => {
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    await outbox()
    assert.equal(entryOf(gist, intent).run_id, 4321)
    gist.runs.push({ id: 4321, display_title: "anything", status: "in_progress", conclusion: null, updated_at: new Date().toISOString() })
    await outbox()
    assert.equal(entryOf(gist, intent).state, "dispatched")
  }, { gist: { dispatchHandler: row => row.workflow === "bot.yml" ? Response.json({ workflow_run_id: 4321, run_url: "https://invented", html_url: "https://invented" }) : new Response(null, { status: 204 }) } })
})

test("B3 superseded, exhausted, route inactive and legacy credentials: no dispatch", async () => {
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    const state = stateOf(gist)
    state.drafts[0].status = "rejected"
    gist.store.routestategist["state.json"] = JSON.stringify(state)
    await outbox()
    assert.deepEqual([entryOf(gist, intent).state, entryOf(gist, intent).code], ["superseded", "approval_not_current"])
    assert.equal(bot(gist).length, 0)
  })
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    for (let attempt = 0; attempt < OUTBOX_MAX_ATTEMPTS + 2; attempt += 1) await outbox()
    assert.equal(entryOf(gist, intent).state, "exhausted")
    assert.equal(bot(gist).length, OUTBOX_MAX_ATTEMPTS)
  }, { gist: { dispatchHandler: row => row.workflow === "bot.yml" ? new Response("{}", { status: 403 }) : new Response(null, { status: 204 }) } })
  await withRoute(seed(1), async (gist) => {
    const { intent } = await approved(gist)
    const patches = gist.patches.length
    assert.equal((await outbox(null, { THEHEAT_GIST_WRITE_ROUTE: "legacy" })).status, "route_not_active")
    assert.equal((await outbox(null, { THEHEAT_LEGACY_CREDENTIALS_PRESENT: "true" })).status, "route_legacy_credentials_present")
    assert.equal((await outbox(null, { THEHEAT_GIST_CREDENTIAL: "legacy" })).status, "route_writer_credential_legacy")
    assert.deepEqual([gist.patches.length, bot(gist).length, entryOf(gist, intent).state], [patches, 0, "queued"])
  })
})

test("B3 the outbox is bounded: an approval beyond the active-entry limit is refused before it applies", async () => {
  await withRoute(seed(1), async (gist) => {
    const document = { schema_version: 1, results: {}, outbox: {} }
    for (let index = 0; index < OUTBOX_MAX_ACTIVE; index += 1) {
      const id = `${String(index).padStart(8, "0")}-0000-4000-8000-000000000000`
      document.outbox[id] = { kind: "bot_manual_tweet", publish_intent_id: id, state: "uncertain", route_activation: "x", updated_at: new Date().toISOString() }
    }
    gist.store.routestategist[RESULTS_FILE] = JSON.stringify(document)
    const draft = stateOf(gist).drafts[0]
    const response = await post("app/api/drafts/route.js", { action: "approve", draftId: draft.id, expectedRevision: identity(draft) })
    const report = await consume([entry(response.body.command)])
    assert.deepEqual(report.refused.map(row => row.code), ["sender_outbox_full"])
    assert.equal(byId(gist, draft.id).status, "pending")
  })
})
