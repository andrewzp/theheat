// ROUTE repair follow-up: physical-episode corrections in route mode through the REAL episodes API
// handler -> sealed envelope -> REAL Python admission CLI -> REAL Node consumer (ROUTE-CONTRACT-v2
// §1–§3). Positive apply; inactive route and stale generation; the episode domain guards of
// applyEpisodeCommand at consumption; altered/forged envelopes. OFFLINE FIXTURE (in-process Gist,
// invented data, invented test key).
import test from "node:test"
import assert from "node:assert/strict"
import { canonical } from "../lib/local-command-recovery.js"
import { buildCommand, readRouteRecord, ROUTE_FILE } from "../lib/gist-write-route.js"
import { buildSealedCommand } from "../lib/gist-route-submit.js"
import { draftMutationSnapshot, numericIdentitySha256, readStateGistSnapshot } from "../lib/state-store.js"
import { OTHER_SEAL_KEY } from "./helpers/route-memory-gist.js"
import { admit, byId, commandStatus, consume, entry, identity, post, resultsDoc, seed, sha, stateOf, withRoute } from "./helpers/route-repair-fixture.js"

const EPISODE = "ep1:flood:gdacs:FL-77", OTHER = "ep1:flood:gdacs:FL-78"
function episodes(state) {
  state.drafts[0].review_context.physical_episode = { episode_id: EPISODE, source_revision: "rev-1", history: [], relationships: [],
    report_joins: [{ join_id: "join-1", report_sha256: "a".repeat(64), status: "matched", removed: false }] }
  state.drafts[1].review_context.physical_episode = { episode_id: OTHER, source_revision: "rev-2", history: [], relationships: [], report_joins: [] }
}
const episodePost = (gist, body) => post("app/api/episodes/route.js", { draftId: "draft_route_1", expectedRevision: identity(byId(gist, "draft_route_1")), ...body })

// Authentic bytes (the server's own key) for a command the dashboard would refuse to issue: proves
// the consumer itself runs applyEpisodeCommand's guards.
async function serverSealedEpisode(draftId, params) {
  const snap = await readStateGistSnapshot()
  const draft = snap.state.drafts.find(row => row.id === draftId)
  return buildSealedCommand({ action: "draft_update", operation: "episode", producerKind: "dashboard_editor", actorSubject: "dashboard-operator",
    route: await readRouteRecord(), targets: [{ draft_id: draftId, ...identity(draft) }],
    payload: { operation: "episode", params_json: JSON.stringify(params), media_descriptor_json: null,
      updates: [{ draft_id: draftId, expected_snapshot: draftMutationSnapshot(draft, snap.state), expected_numeric_sha256: numericIdentitySha256(snap.document, draftId) }],
      publish_intent_id: null, checked_policy_sha256: null, checked_automatic_epoch: null } }).raw
}

test("episodes: a legitimate remove_join and supersede apply under an active route through API -> admission -> consumer", async () => {
  await withRoute(seed(2, episodes), async (gist) => {
    const before = byId(gist, "draft_route_1")
    const removed = await episodePost(gist, { action: "remove_join", joinId: "join-1" })
    assert.equal(removed.status, 202, JSON.stringify(removed.body))
    assert.deepEqual(gist.patches, [], "the episodes handler never PATCHes in route mode")
    const envelope = JSON.parse(removed.body.command)
    assert.deepEqual([envelope.action, envelope.operation, envelope.producer.kind], ["draft_update", "episode", "dashboard_editor"])
    const admitted = admit(removed.body.command)
    assert.equal(admitted.result.admitted, true)
    assert.ok(!admitted.files["command.json"].includes("join-1"), "episode parameters travel sealed")
    const report = await consume([entry(removed.body.command)])
    assert.equal(report.applied.length, 1, JSON.stringify(report.refused))
    const after = byId(gist, "draft_route_1")
    assert.equal(after.review_context.physical_episode.report_joins[0].removed, true)
    assert.equal(after.review_context.physical_episode.history.at(-1).action, "remove_join")
    assert.equal(after.content_revision, before.content_revision + 1)
    assert.equal(after.episode_invalidated, true)
    assert.equal((await commandStatus(removed.body.command_id, sha(removed.body.command))).body.status, "applied")
    const superseded = await episodePost(gist, { action: "supersede", supersededBy: OTHER })
    assert.equal(superseded.status, 202)
    assert.equal(admit(superseded.body.command).result.admitted, true)
    assert.equal((await consume([entry(superseded.body.command)])).applied.length, 1)
    assert.equal(byId(gist, "draft_route_1").review_context.physical_episode.superseded_by, OTHER)
  })
})

test("episodes: refused at submit while inactive; retained commands refuse at apply on rollback and after re-activation", async () => {
  await withRoute(seed(2, episodes), async (gist) => {
    const window = await episodePost(gist, { action: "remove_join", joinId: "join-1" })
    assert.deepEqual([window.status, window.body.code], [409, "route_not_active"], "variable serialized, record absent")
    assert.deepEqual([gist.patches, gist.dispatches], [[], []])
  }, { record: null })
  await withRoute(seed(2, episodes), async (gist) => {
    const first = (await episodePost(gist, { action: "remove_join", joinId: "join-1" })).body.command
    const second = (await episodePost(gist, { action: "supersede", supersededBy: OTHER })).body.command
    const rolled = await consume([entry(first)], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })
    assert.deepEqual(rolled.refused.map(row => row.code), ["route_not_active"])
    assert.equal(byId(gist, "draft_route_1").review_context.physical_episode.report_joins[0].removed, false)
    const control = action => buildCommand({ action, producerKind: "gist_route_control", actorSubject: "root", payload: { generation: 1 } }).raw
    assert.equal((await consume([entry(control("deactivate_route"))], { THEHEAT_GIST_WRITE_ROUTE: "legacy" })).applied.length, 1)
    assert.equal((await consume([entry(control("activate_route"))])).applied.length, 1)
    const stale = await consume([entry(second)])
    assert.deepEqual(stale.refused.map(row => row.code), ["route_generation_not_current"])
    assert.equal(byId(gist, "draft_route_1").review_context.physical_episode.superseded_by, undefined)
    assert.notEqual(JSON.parse(gist.store.routestategist[ROUTE_FILE]).command_id, JSON.parse(second).route_activation)
  })
})

test("episodes: applyEpisodeCommand's guards refuse at submit and, for authentic bytes, at consumption", async () => {
  await withRoute(seed(2, episodes), async (gist) => {
    // At submit the dashboard runs the same function and issues nothing.
    const unknown = await episodePost(gist, { action: "remove_join", joinId: "join-missing" })
    assert.deepEqual([unknown.status, unknown.body.code], [409, "report_join_unknown"])
    assert.deepEqual([(await episodePost(gist, { action: "supersede", supersededBy: "ep1:fire:gdacs:X" })).body.code], ["episode_supersede_target"])
    assert.deepEqual(gist.dispatches, [])
    // Authentic sealed commands that the domain rejects on the consumer's own read.
    const missingJoin = await serverSealedEpisode("draft_route_1", { action: "remove_join", joinId: "join-missing" })
    const unbound = await serverSealedEpisode("draft_route_2", { action: "split", newSourceId: "FL-90" })
    const state = stateOf(gist)
    delete state.drafts[1].review_context.physical_episode
    gist.store.routestategist["state.json"] = JSON.stringify(state)
    const unboundNow = await serverSealedEpisode("draft_route_2", { action: "split", newSourceId: "FL-90" })
    const posted = stateOf(gist)
    Object.assign(posted.drafts[0], { status: "posted", tweet_id: "1900000000000000003", publish_outcome: "confirmed" })
    gist.store.routestategist["state.json"] = JSON.stringify(posted)
    const delivered = await serverSealedEpisode("draft_route_1", { action: "remove_join", joinId: "join-1" })
    const unknownAction = await serverSealedEpisode("draft_route_1", { action: "merge_everything" })
    for (const raw of [unboundNow, delivered, unknownAction]) assert.equal(admit(raw).result.admitted, true)
    const report = await consume([entry(unboundNow), entry(delivered), entry(unknownAction)])
    assert.deepEqual(report.refused.map(row => row.code).sort(), ["draft_delivered", "episode_unbound", "invalid_episode_action"])
    assert.deepEqual(report.applied, [])
    // A command sealed before the binding vanished no longer matches the CAS snapshot.
    const stale = await consume([entry(unbound), entry(missingJoin)])
    assert.deepEqual(stale.refused.map(row => row.code), ["revision_conflict", "revision_conflict"])
    assert.equal(byId(gist, "draft_route_1").review_context.physical_episode.report_joins[0].removed, false)
  })
})

test("episodes: altered, rebound or forged envelopes refuse; a tampered direct dispatch is rejected by digest and changes nothing", async () => {
  await withRoute(seed(2, episodes), async (gist) => {
    const issued = await episodePost(gist, { action: "remove_join", joinId: "join-1" })
    const envelope = JSON.parse(issued.body.command)
    const flip = value => value.slice(0, 8) + (value[8] === "A" ? "B" : "A") + value.slice(9)
    const variants = {
      ciphertext: { ...envelope, seal: { ...envelope.seal, ciphertext: flip(envelope.seal.ciphertext) } },
      operation: { ...envelope, operation: "reject" },
      actor: { ...envelope, actor_subject: "someone-else" },
      generation: { ...envelope, route_activation: "00000000-0000-4000-8000-0000000000ee" },
    }
    for (const [label, value] of Object.entries(variants)) {
      const response = await post("app/api/commands/route.js", { command: canonical(value) })
      assert.deepEqual([response.status === 202, response.body.code], [false, "command_seal_invalid"], label)
    }
    assert.equal(gist.dispatches.length, 1, "only the server-issued submission was dispatched")
    // Bypassing the dashboard (a direct workflow_dispatch): admission sees a well-formed public shape,
    // the consumer's authentication rejects it by digest and never binds the command id.
    const tampered = canonical(variants.ciphertext)
    assert.equal(admit(tampered).result.admitted, true)
    const forgedKey = process.env.THEHEAT_COMMAND_SEAL_KEY
    process.env.THEHEAT_COMMAND_SEAL_KEY = OTHER_SEAL_KEY
    const forged = await serverSealedEpisode("draft_route_1", { action: "remove_join", joinId: "join-1" })
    process.env.THEHEAT_COMMAND_SEAL_KEY = forgedKey
    const report = await consume([entry(tampered), entry(forged)])
    assert.deepEqual(report.rejected.map(row => row.code), ["command_seal_invalid", "command_seal_invalid"])
    assert.deepEqual([report.applied, resultsDoc(gist).results], [[], {}])
    assert.equal(byId(gist, "draft_route_1").review_context.physical_episode.report_joins[0].removed, false)
    // The genuine command still applies afterwards.
    assert.equal((await consume([entry(issued.body.command)])).applied.length, 1)
  })
})
