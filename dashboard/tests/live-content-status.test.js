// Live-content program: the automatic TEXT cap and recheck invalidation through the
// actual drafts route (C3/C4). Invented drafts and an in-memory Gist; no network.
import { policy } from "./helpers/review-policy.js"
import test from "node:test"

process.env.THEHEAT_AUTOMATIC_PUBLICATION_ENABLED = "1"
process.env.THEHEAT_AUTOMATIC_PUBLICATION_EPOCH = "offline-live-content"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { importFresh } from "./helpers/import-fresh.js"
import { draftIdentity, fingerprint, initializeRevision, reviewIsCurrent, textHash } from "./helpers/review-policy.js"
import { AUTOMATIC_TEXT_MAX_SCALARS, HOLD_MESSAGES, MALFORMED, OVER_CAP, automaticTextHold, scalarCount } from "../lib/automatic-text.js"

const BASE = "Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal, the largest departure among 14 sampled cities"
const CONCISE = `${BASE}.`
const AT_CAP = `${BASE}, ahead of Baghdad at 8.1°C and Cairo at 7.4°C above their own monthly normals today.`
const OVER = `${BASE}, ahead of Baghdad at 8.1°C and Cairo at 7.4°C above their own monthly normals, today.`

function reviewed(text, id = "draft_live") {
  const draft = {
    id, event_id: `event_${id}`, type: "hot10", status: "pending", text, created_at: new Date().toISOString(),
    score: { total: 70 }, approval_policy: { mode: "suggested_auto", can_auto_approve: true, recommended_delay_minutes: 30 },
    candidates: [{ rank: 2, text: AT_CAP, score: { total: 66 } }],
    review_context: { source: "invented forecast bulletin", two_bot: {
      bundle: { event_id: `event_${id}`, signal_kind: "hot10", leader: "Riyadh" },
      fact_check: { passed: true }, critic: { passed: true, verdict: "PASS" },
    } },
  }
  const proof = draft.review_context.two_bot
  proof.reviewed_text_sha256 = textHash(draft.text)
  proof.reviewed_policy_sha256 = fingerprint(policy)
  proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
  return initializeRevision(draft)
}

async function withStore(drafts, run) {
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "reviewer", DASHBOARD_PASSWORD: "secret-pass",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "gist_live_content", GITHUB_TOKEN: "token_live_content" })
  let state = { drafts: structuredClone(drafts), publish_ledger: {}, errors: [], run_history: [{ started_at: new Date().toISOString(),
    runtime_inventory: { editorial_policy: structuredClone(policy), schema_version: 1, captured_at: new Date().toISOString(),
      flags: { automatic_publication_enabled: true, automatic_publication_epoch: "offline-live-content" } } }] }
  const originalFetch = globalThis.fetch
  const dispatches = []
  globalThis.fetch = async (url, request = {}) => {
    if (String(url).endsWith("/actions/workflows/bot.yml/dispatches")) {
      dispatches.push(JSON.parse(request.body)) // Recorded invented dispatch; nothing runs.
      return { ok: true, status: 204, async text() { return "" } }
    }
    assert.ok(String(url).startsWith("https://api.github.com/gists/gist_live_content"), `unexpected request ${url}`)
    if (request.method === "PATCH") {
      state = JSON.parse(JSON.parse(request.body).files["state.json"].content)
      return { ok: true, status: 200, async json() { return {} } }
    }
    const snapshot = JSON.stringify(state)
    return { ok: true, status: 200, async json() { return { files: { "state.json": { content: snapshot } } } } }
  }
  try {
    const route = await importFresh("app/api/drafts/route.js")
    const headers = { "Content-Type": "application/json", authorization: `Basic ${Buffer.from("reviewer:secret-pass").toString("base64")}` }
    const post = async (body) => {
      const response = await route.POST(new Request("http://localhost/api/drafts", { method: "POST", headers, body: JSON.stringify(body) }))
      return { status: response.status, body: await response.json() }
    }
    await run({ post, current: () => state.drafts[0], dispatches })
  } finally { globalThis.fetch = originalFetch }
}

const expected = (draft) => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })
const request = (draft, action, more = {}) => ({ draftId: draft.id, action, expectedRevision: expected(draft), ...more })

test("JavaScript counts Unicode scalars like Python and refuses malformed text", () => {
  assert.equal(AUTOMATIC_TEXT_MAX_SCALARS, 200)
  assert.equal(scalarCount("🔥".repeat(200)), 200)
  assert.equal(automaticTextHold("🔥".repeat(200)), null)
  assert.equal(automaticTextHold("🔥".repeat(201)), OVER_CAP)
  assert.equal(scalarCount("é"), 2)
  assert.equal(automaticTextHold("a\ud800"), MALFORMED)
  assert.equal(automaticTextHold(AT_CAP), null)
  assert.equal(automaticTextHold(OVER), OVER_CAP)
})

test("the route schedules a model-reviewed draft at the cap but refuses one character over", async () => {
  await withStore([reviewed(AT_CAP)], async ({ post, current }) => {
    const scheduled = await post(request(current(), "auto_approve"))
    assert.equal(scheduled.status, 200)
    assert.equal(current().approval_binding.mode, "auto")
  })
  await withStore([reviewed(OVER)], async ({ post, current, dispatches }) => {
    const before = structuredClone(current())
    const refused = await post(request(before, "auto_approve"))
    assert.equal(refused.status, 409)
    assert.equal(refused.body.code, OVER_CAP)
    assert.equal(refused.body.error, HOLD_MESSAGES[OVER_CAP])
    assert.deepEqual(current(), before) // Never truncated, rewritten or partially scheduled.
    const manual = await post(request(current(), "approve"))
    assert.equal(manual.status, 200) // The cap never applies to ordinary manual approval.
    assert.equal(dispatches.length, 1)
    assert.equal(dispatches[0].inputs.tweet_text, OVER)
  })
})

test("edit, candidate select and restored text cannot reuse old passes", async () => {
  await withStore([reviewed(CONCISE)], async ({ post, current }) => {
    assert.equal(reviewIsCurrent(current()), true)
    const edited = await post(request(current(), "edit", { editedText: CONCISE.replace("largest", "biggest") }))
    assert.equal(edited.status, 200)
    assert.equal(reviewIsCurrent(current()), false)
    assert.deepEqual(Object.keys(current().review_context.two_bot).sort(), ["bundle"].concat(current().review_context.two_bot.signal_kind ? ["signal_kind"] : []).sort())
    let schedule = await post(request(current(), "auto_approve"))
    assert.equal(schedule.status, 409)
    assert.equal((await post(request(current(), "edit", { editedText: CONCISE }))).status, 200) // Restored text.
    assert.equal(reviewIsCurrent(current()), false)
    schedule = await post(request(current(), "auto_approve"))
    assert.equal(schedule.status, 409)
    assert.equal((await post(request(current(), "select_candidate", { candidateRank: 2 }))).status, 200)
    assert.equal(current().text, AT_CAP)
    assert.equal(reviewIsCurrent(current()), false)
    assert.equal((await post(request(current(), "auto_approve"))).status, 409)
    assert.equal(current().auto_approve_at, undefined)
  })
})

test("a changed saved source invalidates the stale review before scheduling", async () => {
  const original = reviewed(CONCISE)
  const changed = structuredClone(original)
  changed.review_context.two_bot.bundle.leader = "Baghdad"
  await withStore([changed], async ({ post, current }) => {
    assert.equal(reviewIsCurrent(current()), false)
    assert.equal((await post(request(original, "auto_approve"))).status, 409)
    assert.equal(current().approval_binding, undefined)
  })
})

// ---------------------------------------------------------------- E3/E4/F3 projections
import { coverageRow, draftStatusCounts, sourceOutcome } from "../lib/live-content-status.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const RETAINED_RUN = { started_at: "2026-10-30T01:07:00Z", sources: [
  { source: "gpm_imerg", status: "failed", error: "EARTHDATA_TOKEN expired 2026-08-22T15:18:07Z", details: { rainfall_opportunity: { primary_gate: "credential_expired" } } },
  { source: "open_meteo_extreme_signals", status: "degraded", observed: 121, promoted: 0, details: { world_total: 591, cached_count: 121, identity_quarantined: 591, threshold_verification: "failure" } },
  { source: "leaderboard", status: "degraded", observed: 638, promoted: 0, note: "hot10_short_slate: 0 of 10 required qualified locations; excluded {'missing_normal': 638}" },
  { source: "air_quality", status: "success", observed: 624, promoted: 5, triaged_in: 5, triaged_out: 4, writer_attempted: 1, drafted: 0, details: { aq_availability: { requested_cities: 633, observed_cities: 624 } } },
  { source: "gdacs", status: "degraded", observed: 264, promoted: 0 },
  { source: "newsworthiness", status: "failed", error: "HTTPError" },
] }

test("each retained source row becomes one plain outcome with a concrete next action", () => {
  const by = Object.fromEntries(RETAINED_RUN.sources.map(row => [row.source, sourceOutcome(row)]))
  assert.equal(by.gpm_imerg.state, "access_expired")
  assert.match(by.gpm_imerg.detail, /GPM Earthdata token expired: a named access block/)
  assert.match(by.gpm_imerg.next_action, /A stored key is not recovery/)
  assert.equal(by.open_meteo_extreme_signals.state, "baseline_unavailable")
  assert.equal(by.leaderboard.state, "unqualified_input")
  assert.equal(by.air_quality.state, "supplying")
  assert.equal(by.gdacs.state, "no_event")
  assert.equal(by.newsworthiness.state, "unavailable")
  const rejected = sourceOutcome({ source: "air_quality", status: "success", promoted: 0 }, [{ source: "air_quality", stage: "critic" }])
  assert.equal(rejected.state, "writer_or_check_rejection")
  assert.equal(sourceOutcome({ source: "x", status: "success", note: "candidate_budget_config_invalid" }).state, "selector_or_budget_hold")
  assert.equal(sourceOutcome(null).state, "unknown")
})

test("coverage rows keep retained denominators and unknowns, never global recall", () => {
  const aq = coverageRow(RETAINED_RUN.sources[3])
  assert.deepEqual([aq.observed, aq.promoted, aq.triaged_out, aq.writer_attempted, aq.drafted], [624, 5, 4, 1, 0])
  assert.deepEqual(aq.universe, { checked: 633, usable: 624, label: "sampled catalogue cities" })
  const world = coverageRow(RETAINED_RUN.sources[1])
  assert.deepEqual(world.universe, { checked: 591, usable: 121, label: "sampled world cities", quarantined: 591 })
  const unknown = coverageRow({ source: "gdacs" })
  assert.equal(unknown.observed, null)
  assert.equal(unknown.universe.checked, null)
  assert.match(aq.scope, /not global recall and not a count of posts/)
})

test("retained posted and rejected drafts are history, not a backlog", () => {
  const drafts = [...Array(40)].map((_, i) => ({ id: `p${i}`, status: "posted" })).concat([...Array(26)].map((_, i) => ({ id: `r${i}`, status: "rejected" })))
  const counts = draftStatusCounts({ drafts })
  assert.deepEqual([counts.retained_total, counts.posted, counts.rejected, counts.pending, counts.approved], [66, 40, 26, 0, 0])
  const mixed = draftStatusCounts({ drafts: [
    { status: "pending", text: CONCISE, auto_approve_at: "2026-10-29T09:20:00Z" },
    { status: "pending", text: OVER, automatic_text_hold: "automatic_text_over_200_scalars" },
    { status: "pending", text: CONCISE, media_attachment: { kind: "gist_pm25_forecast_v1" } },
  ] })
  assert.deepEqual([mixed.pending, mixed.automatic_text_ready, mixed.manual_image_review, mixed.source_or_check_hold], [3, 1, 1, 1])
  assert.equal(draftStatusCounts({}).pending, null)
})

test("the health payload carries outcomes, coverage and draft counts from the newest row", () => {
  const payload = buildSourceHealthPayload({ run_history: [RETAINED_RUN], drafts: [{ status: "posted" }], suppressions: [] }, { asOf: "2026-10-30T02:00:00Z" })
  const gpm = payload.sources.find(s => s.source === "gpm_imerg")
  assert.equal(gpm.outcome.state, "access_expired")
  assert.equal(payload.sources.find(s => s.source === "air_quality").coverage_row.universe.checked, 633)
  assert.equal(payload.drafts.pending, 0)
  assert.equal(payload.drafts.posted, 1)
})

test("Andrew's optional post feedback stays separate from automated critic details", () => {
  const route = readFileSync(new URL("../app/api/post-feedback/route.js", import.meta.url), "utf8")
  const lib = readFileSync(new URL("../lib/post-feedback.js", import.meta.url), "utf8")
  for (const source of [route, lib]) assert.equal(/critic|quality_note|quality/.test(source), false)
  assert.equal(draftStatusCounts({ drafts: [{ status: "posted", review_context: { two_bot: { critic: { quality: { focus: "single" } } } } }] }).posted, 1)
})
