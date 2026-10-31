// P00c: the ONE serialized consumer of admitted Gist commands. It runs only inside a job of the
// `theheat-bot` GitHub Actions concurrency group (gist-commands.yml `consume`, bot.yml drain
// jobs), which exports THEHEAT_SERIALIZED_WRITER. It reads the state Gist once, applies each
// command in (requested_at, command_id) order to the in-memory document with the dashboard's
// exact checks (re-exported from state-store.js / post-feedback.js / draft-decision-confirm.js,
// never re-implemented), and writes state + route record + command results in ONE PATCH.
// Feedback commands write only the feedback Gist (record + result in one PATCH); a state
// command never touches the feedback Gist and a feedback command never touches state.json.
import { approvalIsCurrent, decisionRevision, draftIdentity, hasUnresolvedPublish } from "./draft-revisions.js"
import { dashboardEditorialPolicy } from "./editorial-policy.js"
import { assertGistEvidenceUnchanged } from "./lossless-gist.js"
import { decideReconciliation } from "./delivery-reconciliation.js"
import { confirmDraftDecision } from "./draft-decision-confirm.js"
import { draftMutationSnapshot, mergeDraftIntoState, numericIdentitySha256, patchStateGistFiles, readStateGistSnapshot,
  reconciliationNumericSha256, reconciliationSnapshot, reparseGistState, revisionConflict } from "./state-store.js"
import { feedbackFilename, feedbackInputOf, loadFeedbackStores, patchFeedbackGist, planFeedbackSave } from "./post-feedback.js"
import { CODE_GENERATION, configuredRouteMode, FEEDBACK_ACTIONS, producerGenerationCode, RESULTS_FILE, ROUTE_FILE,
  resultsFromFiles, RouteError, serializedWriterMarker, validateCommandRaw } from "./gist-write-route.js"

export const RESULT_RETENTION_MS = 3 * 86400000 // > 1 day command lifetime + 2 day artifact retention.
export const MAX_RESULTS = 2000
export const MAX_COMMANDS_PER_DRAIN = 100

const CODE = /^[a-z0-9_]{1,64}$/
function codeOf(error) { return typeof error?.code === "string" && CODE.test(error.code) ? error.code : "command_apply_failed" }
function refusal(code) { return new RouteError(code) }

// Results are kept until three days after their command expired: the artifact (2 days) and the
// command lifetime (<= 1 day) are both gone by then, so a pruned id can never be re-applied.
export function retainResults(results, at) {
  const kept = {}
  let pruned = 0
  for (const [id, row] of Object.entries(results || {})) {
    const expires = Date.parse(row?.expires_at)
    if (Number.isFinite(expires) && expires + RESULT_RETENTION_MS < at.getTime()) pruned += 1
    else kept[id] = row
  }
  return { results: kept, pruned }
}

function rebuildDraft(latest, patch) {
  if (!patch || typeof patch !== "object" || !patch.set || !Array.isArray(patch.unset) || !Array.isArray(patch.order)) throw refusal("invalid_payload")
  // The CAS already proved latest equals the submitter's snapshot; any key drift is a conflict.
  for (const key of Object.keys(latest)) if (!patch.order.includes(key) && !patch.unset.includes(key)) throw revisionConflict()
  const out = {}
  for (const key of patch.order) {
    if (Object.hasOwn(patch.set, key)) out[key] = structuredClone(patch.set[key])
    else if (Object.hasOwn(latest, key)) out[key] = structuredClone(latest[key])
    else throw revisionConflict()
  }
  if (out.id !== latest.id) throw revisionConflict()
  return out
}

function applyDraftUpdate(command, ctx) {
  const { payload, targets } = command
  let { state, document } = ctx
  let content = null
  const applied = []
  for (const [index, update] of payload.updates.entries()) {
    const target = targets[index]
    if (!target || update.draft_id !== target.draft_id) throw refusal("invalid_payload")
    const latestDraft = state.drafts?.find(draft => draft.id === update.draft_id)
    if (!latestDraft) throw refusal("draft_not_found")
    // The exact second-read checks of updateDraftStore, now against the serialized read.
    if (draftMutationSnapshot(latestDraft, state) !== update.expected_snapshot
      || numericIdentitySha256(document, update.draft_id) !== update.expected_numeric_sha256) throw revisionConflict()
    const nextDraft = rebuildDraft(latestDraft, JSON.parse(update.patch_json))
    assertGistEvidenceUnchanged(document, [nextDraft])
    if (payload.confirm) {
      confirmDraftDecision(state, { runtimeReport: ctx.runtimeReport }, { action: payload.confirm.action, draftId: update.draft_id,
        checkedPolicySha: payload.confirm.checked_policy_sha256, checkedAutomaticEpoch: payload.confirm.checked_automatic_epoch })
    }
    nextDraft.updated_at = ctx.consumedAt
    const reparsed = reparseGistState(mergeDraftIntoState(state, nextDraft), document)
    state = reparsed.state; document = reparsed.document; content = reparsed.content
    const saved = state.drafts.find(draft => draft.id === update.draft_id)
    applied.push({ draft_id: saved.id, ...draftIdentity(saved), decision_revision: decisionRevision(saved) })
  }
  const extra = { applied_identity: applied }
  let followup = null
  if (payload.follow_up) {
    // The legacy pre-dispatch check, on the state this consumer just persisted in memory.
    const saved = state.drafts.find(draft => draft.id === payload.updates[0].draft_id)
    const policy = dashboardEditorialPolicy(state, { runtimeReport: ctx.runtimeReport }).policy
    if (approvalIsCurrent(saved, "manual", policy) && saved.publish_intent_id === payload.follow_up.publish_intent_id
        && !hasUnresolvedPublish(saved, state)) {
      followup = { mode: "manual_tweet", tweet_text: saved.text, draft_id: saved.id, publish_intent_id: saved.publish_intent_id }
      extra.follow_up = "manual_sender_dispatch_requested"
    } else extra.follow_up = "not_dispatched_draft_changed"
  }
  return { state, document, content, stateChanged: true, extra, followup }
}

function applyReconciliation(command, ctx) {
  const { payload } = command
  const request = JSON.parse(payload.request_json)
  if (request?.event_id !== payload.event_id) throw refusal("invalid_payload")
  const draft = ctx.state.drafts?.find(candidate => (candidate?.event_id || candidate?.id) === payload.event_id)
  if (!draft || reconciliationSnapshot(ctx.state, payload.event_id) !== payload.expected_snapshot
    || reconciliationNumericSha256(ctx, payload.event_id) !== payload.expected_numeric_sha256) throw revisionConflict()
  const { state: updated, result } = decideReconciliation(ctx.state, request, { actor: payload.actor, at: payload.at })
  if (result.status !== "applied") return { state: ctx.state, document: ctx.document, content: null, stateChanged: false, extra: { reconciliation: result } }
  const reparsed = reparseGistState(updated, ctx.document)
  return { state: reparsed.state, document: reparsed.document, content: reparsed.content, stateChanged: true, extra: { reconciliation: result } }
}

function applyRouteControl(command, ctx) {
  const generation = command.payload?.generation
  if (!Number.isSafeInteger(generation) || generation < 1 || generation > CODE_GENERATION) throw refusal("invalid_route_generation")
  const variable = configuredRouteMode(ctx.env)
  // Route state follows root's repository variable: activation only after it says serialized,
  // deactivation only after it is back to legacy. A token that can merely dispatch cannot flip it.
  if (command.action === "activate_route" && variable !== "serialized") throw refusal("route_variable_not_serialized")
  if (command.action === "deactivate_route" && variable === "serialized") throw refusal("route_variable_still_serialized")
  if (ctx.route && generation < ctx.route.generation) throw refusal("invalid_route_generation")
  const route = { schema_version: 1, mode: command.action === "activate_route" ? "serialized" : "legacy", generation,
    changed_at: ctx.consumedAt, changed_by_run: ctx.marker, command_id: command.command_id }
  return { state: ctx.state, document: ctx.document, content: null, stateChanged: false, route, extra: { route_mode: route.mode, generation } }
}

function decide(item, ctx, results, report) {
  const { command, digest } = item
  const id = command.command_id
  const prior = results[id] ?? ctx.batch.get(id)
  if (prior) {
    // Idempotency: the same id is never applied twice; the same id with other bytes is refused.
    if (prior.digest === digest) report.duplicates.push(id)
    else report.reused.push({ command_id: id, code: "command_id_reused" })
    return null
  }
  if (Object.keys(results).length >= MAX_RESULTS) { report.skipped.push({ command_id: id, code: "command_results_capacity" }); return null }
  const base = { digest, action: command.action, consumed_at: ctx.consumedAt, run: ctx.marker, expires_at: command.expires_at }
  if (item.expired) return { ...base, status: "refused", code: "expired" }
  const generationCode = producerGenerationCode(command, ctx.route)
  if (generationCode) return { ...base, status: "refused", code: generationCode }
  return base
}

async function consumeState(items, ctx, report) {
  const snapshot = await readStateGistSnapshot()
  if (snapshot.route && CODE_GENERATION < snapshot.route.generation) throw refusal("stale_writer_generation")
  const kept = retainResults(snapshot.results, ctx.at)
  const results = kept.results
  let state = snapshot.state, document = snapshot.document, route = snapshot.route
  let content = null, stateChanged = false, routeChanged = false, resultsChanged = kept.pruned > 0
  const batch = new Map()
  for (const item of items) {
    const local = { ...ctx, state, document, route, runtimeReport: snapshot.runtimeReport, batch }
    const base = decide(item, local, results, report)
    if (!base) continue
    let row = base
    if (!base.status) {
      try {
        const action = item.command.action
        const out = action === "draft_update" ? applyDraftUpdate(item.command, local)
          : action === "reconcile_delivery" ? applyReconciliation(item.command, local) : applyRouteControl(item.command, local)
        state = out.state; document = out.document
        if (out.stateChanged) { stateChanged = true; content = out.content }
        if (out.route) { route = out.route; routeChanged = true }
        if (out.followup) report.followups.push({ command_id: item.command.command_id, ...out.followup })
        row = { ...base, status: "applied", code: null, ...out.extra }
      } catch (error) { row = { ...base, status: "refused", code: codeOf(error) } }
    }
    results[item.command.command_id] = row
    batch.set(item.command.command_id, row)
    resultsChanged = true
    report[row.status === "applied" ? "applied" : "refused"].push({ command_id: item.command.command_id, code: row.code ?? null })
  }
  if (!stateChanged && !routeChanged && !resultsChanged) return
  const files = { [RESULTS_FILE]: { content: JSON.stringify({ schema_version: 1, results }) } }
  if (stateChanged) files["state.json"] = { content }
  if (routeChanged) files[ROUTE_FILE] = { content: JSON.stringify(route) }
  await patchStateGistFiles(files)
  report.state_patches += 1
}

async function consumeFeedback(items, ctx, report) {
  for (const item of items) {
    let input0
    try { input0 = JSON.parse(item.command.payload.input_json) } catch { input0 = null }
    const loaded = await loadFeedbackStores(typeof input0?.request_id === "string" ? input0.request_id : null)
    if (loaded.route && CODE_GENERATION < loaded.route.generation) throw refusal("stale_writer_generation")
    const kept = retainResults(resultsFromFiles(loaded.resultsMeta ? { [RESULTS_FILE]: loaded.resultsMeta } : {}), ctx.at)
    const results = kept.results
    const base = decide(item, { ...ctx, route: loaded.route, batch: new Map() }, results, report)
    if (!base) continue
    let row = base
    const files = {}
    if (!base.status) {
      try {
        const plan = planFeedbackSave(feedbackInputOf(input0), loaded, ctx.at)
        if (!plan.already_saved) files[feedbackFilename(plan.record.request_id)] = { content: JSON.stringify(plan.record) }
        row = { ...base, status: "applied", code: null, already_saved: plan.already_saved }
      } catch (error) { row = { ...base, status: "refused", code: codeOf(error) } }
    }
    results[item.command.command_id] = row
    files[RESULTS_FILE] = { content: JSON.stringify({ schema_version: 1, results }) }
    await patchFeedbackGist(files)
    report.feedback_patches += 1
    report[row.status === "applied" ? "applied" : "refused"].push({ command_id: item.command.command_id, code: row.code ?? null })
  }
}

// entries: [{ raw, admission, source }] from the admitted-artifact inbox.
export async function consumeGistCommands(entries, { env = process.env, now = () => new Date() } = {}) {
  const marker = serializedWriterMarker(env)
  if (!marker) throw new RouteError("serialized_writer_marker_required", 503)
  configuredRouteMode(env)
  const at = now()
  const ctx = { env, marker, at, consumedAt: at.toISOString() }
  const report = { marker, consumed_at: ctx.consumedAt, invalid: [], applied: [], refused: [], duplicates: [], reused: [],
    skipped: [], followups: [], state_patches: 0, feedback_patches: 0 }
  const valid = []
  for (const entry of entries) {
    try {
      const item = validateCommandRaw(entry.raw, { now: at })
      if (!entry.admission || entry.admission.digest !== item.digest || entry.admission.command_id !== item.command.command_id) {
        throw new RouteError("admission_digest_mismatch")
      }
      valid.push(item)
    } catch (error) { report.invalid.push({ source: entry.source ?? null, code: codeOf(error) }) }
  }
  valid.sort((a, b) => a.command.requested_at.localeCompare(b.command.requested_at)
    || a.command.command_id.localeCompare(b.command.command_id) || a.digest.localeCompare(b.digest))
  const batch = valid.slice(0, MAX_COMMANDS_PER_DRAIN)
  report.deferred = valid.length - batch.length
  const stateItems = batch.filter(item => !FEEDBACK_ACTIONS.has(item.command.action))
  const feedbackItems = batch.filter(item => FEEDBACK_ACTIONS.has(item.command.action))
  if (stateItems.length) await consumeState(stateItems, ctx, report)
  if (feedbackItems.length) await consumeFeedback(feedbackItems, ctx, report)
  return report
}

// The approve follow-up: the same bot.yml manual_tweet dispatch the legacy route performed,
// now issued after the approval is durably applied. A failure leaves the approval queued.
export async function dispatchFollowups(followups, { fetchImpl = globalThis.fetch, token, repo }) {
  const out = []
  for (const item of followups) {
    let status
    try {
      const response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/workflows/bot.yml/dispatches`, {
        method: "POST", headers: { Accept: "application/vnd.github.v3+json", Authorization: `token ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { mode: item.mode, tweet_text: item.tweet_text, draft_id: item.draft_id, publish_intent_id: item.publish_intent_id } }),
      })
      status = response.status === 204 || response.ok ? "dispatched" : "dispatch_failed"
    } catch { status = "dispatch_uncertain" }
    out.push({ command_id: item.command_id, draft_id: item.draft_id, status })
  }
  return out
}
