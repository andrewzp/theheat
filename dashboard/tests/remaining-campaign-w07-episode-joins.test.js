// W07.2/07.3/07.6 on the real episodes route over an invented Gist: inspect why records are
// joined or separate, remove a join, split and supersede, each with the draft's expected
// revision; review/approval are invalidated, the previous context stays in revision history,
// delivered snapshots are refused and the report is named by hash only. The state comes from
// the real Python producer (runner admission, operator ledger, publish projection).
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { importFresh } from "./helpers/import-fresh.js"
import { draftIdentity, policy, recordHumanReview, reviewIsCurrent } from "./helpers/review-policy.js"
import { EpisodeJoins, episodeRequest } from "../app/components/EpisodeJoins.js"

const ROOT = new URL("../..", import.meta.url).pathname
function python(args, input) {
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "tests.remaining_campaign.w07_editor_child", ...args], {
    cwd: ROOT, encoding: "utf8", input: input === undefined ? undefined : JSON.stringify(input),
    env: { PATH: process.env.PATH, HOME: "/nonexistent-invented-w07", LC_ALL: "C", TZ: "UTC", PYTHONDONTWRITEBYTECODE: "1" },
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout.trim().split("\n").at(-1))
}

const revision = draft => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })

async function withEpisodes(run) {
  const produced = python([])
  let raw = produced.raw_state
  const keys = ["NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "GIST_ID", "GITHUB_TOKEN", "VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "THEHEAT_LOCAL_PREVIEW_URL"]
  const previous = Object.fromEntries(keys.map(k => [k, process.env[k]]))
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented-reviewer", DASHBOARD_PASSWORD: "invented-password",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "invented-gist-episodes", GITHUB_TOKEN: "invented-not-a-real-token" })
  for (const key of ["VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "THEHEAT_LOCAL_PREVIEW_URL"]) delete process.env[key]
  const originalFetch = globalThis.fetch
  const patches = []
  globalThis.fetch = async (url, request = {}) => {
    if (String(url) !== "https://api.github.com/gists/invented-gist-episodes") assert.fail(`Unexpected external request: ${url}`)
    if (request.method === "PATCH") { raw = JSON.parse(request.body).files["state.json"].content; patches.push(raw); return new Response("{}") }
    return new Response(JSON.stringify({ files: { "state.json": { content: raw } } }))
  }
  const auth = `Basic ${Buffer.from("invented-reviewer:invented-password").toString("base64")}`
  const headers = { "Content-Type": "application/json", Host: "localhost:3000", Authorization: auth }
  try {
    const route = await importFresh("app/api/episodes/route.js")
    const get = async id => { const r = await route.GET(new Request(`http://localhost:3000/api/episodes?draftId=${id}`, { headers })); return { status: r.status, body: await r.json() } }
    const post = async (value, extra = {}) => { const r = await route.POST(new Request("http://localhost:3000/api/episodes", { method: "POST", headers: { ...headers, ...extra }, body: JSON.stringify(value) })); return { status: r.status, body: await r.json() } }
    const draft = id => JSON.parse(raw).drafts.find(d => d.id === id)
    const replace = mutate => { const state = JSON.parse(raw); mutate(state); raw = JSON.stringify(state) }
    await run({ get, post, draft, replace, raw: () => raw, patches, produced })
  } finally {
    globalThis.fetch = originalFetch
    for (const key of keys) { if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key] }
  }
}

test("the editor sees identity layers and why records are joined, separate or proposed only", async () => {
  await withEpisodes(async t => {
    const { status, body } = await t.get("d-river")
    assert.equal(status, 200)
    assert.equal(body.identity.episode_id, "ep1:flood:gdacs:FL-77")
    assert.equal(body.identity.candidate_id, "gdacs_FL_77_2026-10-28")
    assert.deepEqual(body.identity.publication, { draft_id: "d-river", tweet_id: null })
    assert.notEqual(body.identity.source_revision, body.identity.episode_id)
    assert.deepEqual(body.same_episode.map(r => [r.draft_id, r.status, r.eligibility]), [["d-posted", "posted", ["new_place"]]])
    const why = Object.fromEntries(body.separate.map(r => [r.draft_id, r.why]))
    assert.match(why["d-ems"], /^Joined by shared identifier; human impacts are never combined/)
    assert.match(why["d-namesake"], /^Proposed only: insufficient join evidence/)
    assert.deepEqual(body.report_joins.map(j => [j.status, j.removed, j.statement]), [
      ["matched", false, "The Ficta River left its banks at Exemplar Ford."], ["report_claim_only", false, null]])
    assert.ok(body.report_joins.every(j => j.report_sha256 === t.produced.report_sha256))
    const html = renderToStaticMarkup(React.createElement(EpisodeJoins, { draft: { id: "d-river", revision_identity: revision(t.draft("d-river")) }, initialView: body }))
    assert.match(html, /Joined by shared identifier/); assert.match(html, /Remove join/); assert.match(html, /Report claim only/)
    // A same-name event in another country under another ID stays its own episode.
    assert.equal((await t.get("d-namesake")).body.identity.episode_id, "ep1:flood:gdacs:FL-78")
  })
})

test("removing a join invalidates review and approval, keeps history and flows back to the ledger", async () => {
  await withEpisodes(async t => {
    t.replace(state => { const d = state.drafts.find(x => x.id === "d-river"); recordHumanReview(d, policy) })
    const before = t.draft("d-river")
    assert.equal(reviewIsCurrent(before), true)
    const join = before.review_context.physical_episode.report_joins[0]
    const stale = await t.post({ action: "remove_join", draftId: "d-river", joinId: join.join_id,
      expectedRevision: { ...revision(before), content_revision: before.content_revision + 1 } })
    assert.equal(stale.status, 409)
    const removed = await t.post(episodeRequest({ id: "d-river", revision_identity: revision(before) }, "remove_join", { joinId: join.join_id }))
    assert.equal(removed.status, 200, JSON.stringify(removed.body))
    const after = t.draft("d-river")
    assert.equal(reviewIsCurrent(after), false); assert.equal(after.review_binding, undefined)
    assert.equal(after.content_revision, before.content_revision + 1); assert.equal(after.status, "pending")
    const kept = after.revision_history.at(-1)
    assert.equal(kept.review_context.physical_episode.report_joins[0].removed, false)  // the previous context is retained
    const now = after.review_context.physical_episode.report_joins[0]
    assert.equal(now.removed, true); assert.equal(now.report_sha256, t.produced.report_sha256)
    assert.equal(removed.body.view.report_joins[0].removed, true)
    // Python republish withdraws the join in the operator ledger: the next brief cannot use it.
    const back = python(["republish"], { raw_state: t.raw(), ledger: t.produced.ledger, episode: "ep1:flood:gdacs:FL-77" })
    assert.deepEqual(back.published.withdrawn_joins, [join.join_id]); assert.deepEqual(back.writer, [])
  })
})

test("split and supersede use the expected revision; delivered drafts and foreign origins are refused", async () => {
  await withEpisodes(async t => {
    const posted = t.draft("d-posted")
    const refused = await t.post({ action: "split", draftId: "d-posted", newSourceId: "FL-77b", expectedRevision: revision(posted) })
    assert.equal(refused.status, 409); assert.equal(refused.body.code, "draft_delivered"); assert.equal(t.patches.length, 0)
    const crossOrigin = await t.post({ action: "split", draftId: "d-river", newSourceId: "FL-77b", expectedRevision: revision(t.draft("d-river")) },
      { Origin: "https://elsewhere.invalid" })
    assert.equal(crossOrigin.status, 403); assert.equal(t.patches.length, 0)
    const duplicate = await t.post({ action: "split", draftId: "d-river", newSourceId: "FL-78", expectedRevision: revision(t.draft("d-river")) })
    assert.equal(duplicate.body.code, "episode_split_target")
    const split = await t.post({ action: "split", draftId: "d-river", newSourceId: "FL-77b", expectedRevision: revision(t.draft("d-river")) })
    assert.equal(split.status, 200, JSON.stringify(split.body))
    const moved = t.draft("d-river").review_context.physical_episode
    assert.equal(moved.episode_id, "ep1:flood:gdacs:FL-77b"); assert.equal(moved.split_from, "ep1:flood:gdacs:FL-77")
    assert.deepEqual(moved.report_joins, []); assert.equal(moved.history.at(-1).action, "split")
    assert.equal(t.draft("d-posted").review_context.physical_episode.episode_id, "ep1:flood:gdacs:FL-77")  // snapshot untouched
    const sup = await t.post({ action: "supersede", draftId: "d-namesake", supersededBy: "ep1:flood:gdacs:FL-77b", expectedRevision: revision(t.draft("d-namesake")) })
    assert.equal(sup.status, 200, JSON.stringify(sup.body))
    assert.deepEqual([sup.body.view.status, sup.body.view.superseded_by], ["superseded", "ep1:flood:gdacs:FL-77b"])
    const badTarget = await t.post({ action: "supersede", draftId: "d-ems", supersededBy: "ep1:fire:firms:none", expectedRevision: revision(t.draft("d-ems")) })
    assert.equal(badTarget.body.code, "episode_supersede_target")
  })
})

test("the Gist evidence guard admits only the exact episode correction, never a quiet rewrite", async () => {
  const { assertGistEvidenceUnchanged, parseGistDocument } = await import("../lib/lossless-gist.js")
  const { applyEpisodeCommand } = await import("../lib/hazard-episodes.js")
  const produced = python([])
  const document = parseGistDocument(produced.raw_state)
  const state = JSON.parse(produced.raw_state)
  const fresh = () => structuredClone(state.drafts)
  const river = drafts => drafts.find(d => d.id === "d-river")
  const corrected = fresh()
  applyEpisodeCommand(river(corrected), { action: "remove_join", joinId: river(corrected).review_context.physical_episode.report_joins[0].join_id }, { state })
  assert.doesNotThrow(() => assertGistEvidenceUnchanged(document, corrected))
  const tamper = [
    drafts => { river(drafts).review_context.physical_episode.episode_id = "ep1:flood:gdacs:FL-79" },  // no correction entry
    drafts => { const d = river(drafts); applyEpisodeCommand(d, { action: "remove_join", joinId: d.review_context.physical_episode.report_joins[0].join_id }, { state })
      d.review_context.physical_episode.report_joins[0].claim = { text: "Rewritten statement." } },  // join content changed
    drafts => { const d = river(drafts); applyEpisodeCommand(d, { action: "supersede", supersededBy: "ep1:flood:gdacs:FL-78" }, { state })
      d.review_context.physical_episode.eligibility = ["value_changed"] },  // admission record changed too
    drafts => { const d = river(drafts); applyEpisodeCommand(d, { action: "split", newSourceId: "FL-77c" }, { state }); d.revision_history = [] },
  ]
  for (const change of tamper) {
    const drafts = fresh(); change(drafts)
    assert.throws(() => assertGistEvidenceUnchanged(document, drafts), error => error.code === "state_evidence_preservation")
  }
})
