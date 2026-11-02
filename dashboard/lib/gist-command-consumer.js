// P00c: the ONE serialized consumer of admitted Gist commands. It runs only inside a job of the
// `theheat-bot` GitHub Actions concurrency group (gist-commands.yml `consume`, bot.yml drain
// jobs), which exports THEHEAT_SERIALIZED_WRITER. v2 (ROUTE-CONTRACT-v2):
// - ordinary commands are sealed envelopes; they are opened here with THEHEAT_COMMAND_SEAL_KEY
//   and never logged, reported or persisted in plaintext (§1);
// - each one re-runs the SAME exported domain operation the legacy /api/drafts path runs, after
//   the exact v1 compare-and-swap checks; a patch can no longer express a mutation (§2);
// - it applies only while the variable AND the route record say serialized, under the activation
//   it was issued for; otherwise its terminal result is route_not_active / _generation_not_current (§3);
// - persisted duplicates are settled BEFORE the per-drain budget, and an artifact is acknowledged
//   (deleted) only after a fresh read shows its terminal result durably in the Gist (§4);
// - an approval writes its sender outbox entry in the same PATCH (§5, gist-sender-outbox.js).
// State commands: state + route record + results (+ outbox) in ONE PATCH. Feedback commands write
// only the feedback Gist; a state command never touches it and vice versa.
import { approvalIsCurrent, decisionRevision, draftIdentity, fingerprint, hasUnresolvedPublish } from "./draft-revisions.js"
import { dashboardEditorialPolicy } from "./editorial-policy.js"
import { assertGistEvidenceUnchanged } from "./lossless-gist.js"
import { decideReconciliation } from "./delivery-reconciliation.js"
import { confirmDraftDecision } from "./draft-decision-confirm.js"
import { validGistMedia } from "./gist-media.js"
import { applyEpisodeCommand } from "./hazard-episodes.js"
import { applyBulkReject, applyDraftAction, assertExpected, bulkRejectSelected, CONFIRM_ACTIONS, OPERATION_PARAMS, validIdentity } from "./draft-operations.js"
import { draftMutationSnapshot, mergeDraftIntoState, numericIdentitySha256, patchStateGistFiles, readStateGistSnapshot,
  reconciliationNumericSha256, reconciliationSnapshot, reparseGistState, revisionConflict } from "./state-store.js"
import { feedbackFilename, feedbackInputOf, loadFeedbackStores, patchFeedbackGist, planFeedbackSave } from "./post-feedback.js"
import { CODE_GENERATION, configuredRouteMode, FEEDBACK_ACTIONS, parseCommandRaw, producerGenerationCode, RESULTS_FILE, ROUTE_FILE,
  resultsDocumentFromFiles, resultsFileContent, RouteError, routeActive, routeApplyCode, routeCredentialCode, serializedWriterMarker } from "./gist-write-route.js"
import { openEnvelope, sealKey } from "./gist-command-seal.js"
import { activeOutboxCount, dispatchSender, findRun, lookupTargets, OUTBOX_MAX_ACTIVE, outboxEntry, planOutbox, pruneOutbox } from "./gist-sender-outbox.js"

export const RESULT_RETENTION_MS = 3 * 86400000 // > 1 day command lifetime + 2 day artifact retention.
export const REJECTED_RETENTION_MS = 4 * 86400000
export const MAX_RESULTS = 2000
export const MAX_REJECTED = 500
export const MAX_COMMANDS_PER_DRAIN = 100
export const MAX_BULK_UPDATES = 100

const CODE = /^[a-z0-9_]{1,64}$/
const HEX = /^[a-f0-9]{64}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const DRAFT_ID = /^[A-Za-z0-9_.:-]{1,200}$/
function codeOf(error) { return typeof error?.code === "string" && CODE.test(error.code) ? error.code : "command_apply_failed" }
function refusal(code) { return new RouteError(code) }
const exactKeys = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).sort().join() === [...keys].sort().join()
const object = value => value && typeof value === "object" && !Array.isArray(value)

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

function retainRejected(rejected, at) {
  const rows = Object.entries(rejected || {}).filter(([, row]) => !(Date.parse(row?.at) + REJECTED_RETENTION_MS < at.getTime()))
    .sort((a, b) => String(b[1]?.at).localeCompare(String(a[1]?.at))).slice(0, MAX_REJECTED)
  return Object.fromEntries(rows)
}

function parseEmbedded(text) {
  let value
  try { value = JSON.parse(text) } catch { throw refusal("invalid_payload") }
  if (!object(value)) throw refusal("invalid_payload")
  return value
}

// Full validation of an opened draft_update body (the envelope was authenticated already).
const DRAFT_PAYLOAD_KEYS = ["checked_automatic_epoch", "checked_policy_sha256", "media_descriptor_json", "operation", "params_json", "publish_intent_id", "updates"]
const TARGET_KEYS = ["content_revision", "decision_revision", "draft_id", "evidence_sha256", "text_sha256"]
function draftPayload(envelope, { targets, payload }) {
  const operation = envelope.operation
  if (!exactKeys(payload, DRAFT_PAYLOAD_KEYS) || payload.operation !== operation) throw refusal("invalid_payload")
  const updates = payload.updates
  if (!Array.isArray(updates) || updates.length < 1 || updates.length > MAX_BULK_UPDATES || updates.length !== targets.length
      || (operation !== "bulk_reject_below" && updates.length !== 1)) throw refusal("invalid_targets")
  const ids = new Set()
  for (const [index, update] of updates.entries()) {
    const target = targets[index]
    if (!exactKeys(target, TARGET_KEYS) || !validIdentity(target) || !DRAFT_ID.test(target.draft_id) || ids.has(target.draft_id)
        || !exactKeys(update, ["draft_id", "expected_numeric_sha256", "expected_snapshot"]) || update.draft_id !== target.draft_id
        || !HEX.test(update.expected_snapshot) || !HEX.test(update.expected_numeric_sha256)) throw refusal("invalid_targets")
    ids.add(target.draft_id)
  }
  const params = parseEmbedded(payload.params_json)
  if (operation !== "episode" && Object.keys(params).some(key => !(OPERATION_PARAMS[operation] ?? []).includes(key))) throw refusal("invalid_payload")
  const media = payload.media_descriptor_json === null ? null : parseEmbedded(payload.media_descriptor_json)
  if ((operation === "approve") !== (typeof payload.publish_intent_id === "string" && UUID.test(payload.publish_intent_id))
      || (operation !== "approve" && payload.publish_intent_id !== null)) throw refusal("invalid_payload")
  if (CONFIRM_ACTIONS.includes(operation) ? !HEX.test(payload.checked_policy_sha256 || "") : payload.checked_policy_sha256 !== null) throw refusal("invalid_payload")
  if (operation === "auto_approve" ? !(payload.checked_automatic_epoch === null || typeof payload.checked_automatic_epoch === "string")
    : payload.checked_automatic_epoch !== null) throw refusal("invalid_payload")
  return { params, media, targets, updates, operation }
}

// The descriptor the dashboard prepared (it alone can reach its preview origin), sealed with the
// command; the domain operation re-checks it against the latest draft exactly as at submit.
function sealedMedia(descriptor) {
  return async (draft, expectedMediaSha256) => {
    if (!descriptor || typeof expectedMediaSha256 !== "string" || fingerprint(descriptor) !== expectedMediaSha256 || !validGistMedia(draft, descriptor)) {
      throw Object.assign(new Error("The graphic changed; preview and review it again"), { status: 409, code: "media_changed" })
    }
    return structuredClone(descriptor)
  }
}

async function applyDraftUpdate(item, ctx) {
  const { envelope, body } = item
  const { params, media, targets, updates, operation } = draftPayload(envelope, body)
  const payload = body.payload
  if (operation === "approve" && activeOutboxCount(ctx.outbox) >= OUTBOX_MAX_ACTIVE) throw refusal("sender_outbox_full")
  let { state, document } = ctx
  let content = null
  const applied = []
  for (const [index, update] of updates.entries()) {
    const target = targets[index]
    const expected = { content_revision: target.content_revision, decision_revision: target.decision_revision,
      text_sha256: target.text_sha256, evidence_sha256: target.evidence_sha256 }
    const latestDraft = state.drafts?.find(draft => draft.id === update.draft_id)
    if (!latestDraft) throw refusal("draft_not_found")
    // The exact second-read checks of updateDraftStore, now against the serialized read.
    if (draftMutationSnapshot(latestDraft, state) !== update.expected_snapshot
      || numericIdentitySha256(document, update.draft_id) !== update.expected_numeric_sha256) throw revisionConflict()
    const draft = structuredClone(latestDraft)
    let nextDraft
    if (operation === "bulk_reject_below") {
      const threshold = params.threshold
      if (typeof threshold !== "number" || !Number.isFinite(threshold) || threshold < 0 || threshold > 100) throw refusal("invalid_threshold")
      if (!bulkRejectSelected(draft, threshold)) throw revisionConflict()
      nextDraft = applyBulkReject(draft, state, expected, threshold)
    } else if (operation === "episode") {
      assertExpected(draft, expected)
      nextDraft = applyEpisodeCommand(draft, params, { state, actor: "dashboard", now: ctx.consumedAt })
    } else {
      assertExpected(draft, expected)
      // The legacy confirmation (confirmContext) against THIS read, bound to what the operator
      // confirmed at submit; it runs before the operation so a policy/epoch/source change reports
      // the same code the legacy second read reports.
      if (CONFIRM_ACTIONS.includes(operation)) {
        confirmDraftDecision(state, { runtimeReport: ctx.runtimeReport }, { action: operation, draftId: update.draft_id,
          checkedPolicySha: payload.checked_policy_sha256, checkedAutomaticEpoch: payload.checked_automatic_epoch })
      }
      const done = await applyDraftAction(draft, state, { runtimeReport: ctx.runtimeReport, action: operation, body: params,
        prepareMedia: sealedMedia(media), now: () => ctx.at, newPublishIntentId: () => payload.publish_intent_id })
      nextDraft = done.draft
      // The decision stays bound to what the operator confirmed at submit.
      if (CONFIRM_ACTIONS.includes(operation) && done.checkedPolicySha !== payload.checked_policy_sha256) throw refusal("editorial_policy_changed")
      if (operation === "auto_approve" && done.checkedAutomaticEpoch !== payload.checked_automatic_epoch) throw refusal("automatic_publication_paused")
    }
    assertGistEvidenceUnchanged(document, [nextDraft])
    nextDraft.updated_at = ctx.consumedAt
    const reparsed = reparseGistState(mergeDraftIntoState(state, nextDraft), document)
    state = reparsed.state; document = reparsed.document; content = reparsed.content
    const saved = state.drafts.find(draft => draft.id === update.draft_id)
    applied.push({ draft_id: saved.id, ...draftIdentity(saved), decision_revision: decisionRevision(saved) })
  }
  const extra = { applied_identity: applied }
  let outbox = null
  if (operation === "approve") {
    // The legacy pre-dispatch check, on the state this consumer persists in the same PATCH.
    const saved = state.drafts.find(draft => draft.id === updates[0].draft_id)
    const policy = dashboardEditorialPolicy(state, { runtimeReport: ctx.runtimeReport }).policy
    if (approvalIsCurrent(saved, "manual", policy) && saved.publish_intent_id === payload.publish_intent_id && !hasUnresolvedPublish(saved, state)) {
      outbox = outboxEntry({ commandId: envelope.command_id, draft: saved, publishIntentId: payload.publish_intent_id,
        activation: envelope.route_activation, at: ctx.consumedAt })
      extra.follow_up = { publish_intent_id: payload.publish_intent_id }
    } else extra.follow_up = { code: "not_dispatched_draft_changed" }
  }
  return { state, document, content, stateChanged: true, extra, outbox }
}

function applyReconciliation(item, ctx) {
  const { envelope, body: { targets, payload } } = item
  if (targets.length || !exactKeys(payload, ["actor", "at", "event_id", "expected_numeric_sha256", "expected_snapshot", "request_json"])
      || typeof payload.event_id !== "string" || !HEX.test(payload.expected_snapshot || "") || !HEX.test(payload.expected_numeric_sha256 || "")) throw refusal("invalid_payload")
  // The ledger actor is the authenticated subject bound in the envelope; it cannot be rebound.
  if (payload.actor !== envelope.actor_subject) throw refusal("command_actor_mismatch")
  const request = parseEmbedded(payload.request_json)
  if (request.event_id !== payload.event_id) throw refusal("invalid_payload")
  const draft = ctx.state.drafts?.find(candidate => (candidate?.event_id || candidate?.id) === payload.event_id)
  if (!draft || reconciliationSnapshot(ctx.state, payload.event_id) !== payload.expected_snapshot
    || reconciliationNumericSha256(ctx, payload.event_id) !== payload.expected_numeric_sha256) throw revisionConflict()
  const { state: updated, result } = decideReconciliation(ctx.state, request, { actor: payload.actor, at: payload.at })
  if (result.status !== "applied") return { state: ctx.state, document: ctx.document, content: null, stateChanged: false, extra: { reconciliation: result } }
  const reparsed = reparseGistState(updated, ctx.document)
  return { state: reparsed.state, document: reparsed.document, content: reparsed.content, stateChanged: true, extra: { reconciliation: result } }
}

function applyRouteControl(item, ctx) {
  const { command } = item
  const generation = command.payload?.generation
  if (!Number.isSafeInteger(generation) || generation < 1 || generation > CODE_GENERATION) throw refusal("invalid_route_generation")
  const variable = configuredRouteMode(ctx.env)
  // Route state follows root's repository variable: activation only after it says serialized,
  // deactivation only after it is back to legacy. A token that can merely dispatch cannot flip it.
  if (command.action === "activate_route" && variable !== "serialized") throw refusal("route_variable_not_serialized")
  if (command.action === "deactivate_route" && variable === "serialized") throw refusal("route_variable_still_serialized")
  // Old-SHA fence (ROUTE-CONTRACT-v2 §6): activation only under the route-era writer secret name and
  // only once every legacy writer/sender secret name is gone. Deactivation (rollback) is never fenced.
  const credentialCode = command.action === "activate_route" ? routeCredentialCode(ctx.env) : null
  if (credentialCode) throw refusal(credentialCode)
  if (ctx.route && generation < ctx.route.generation) throw refusal("invalid_route_generation")
  const route = { schema_version: 1, mode: command.action === "activate_route" ? "serialized" : "legacy", generation,
    changed_at: ctx.consumedAt, changed_by_run: ctx.marker, command_id: command.command_id }
  return { state: ctx.state, document: ctx.document, content: null, stateChanged: false, route, extra: { route_mode: route.mode, generation } }
}

const actionOf = item => item.kind === "sealed" ? item.envelope.action : item.command.action
const producerOf = item => item.kind === "sealed" ? item.envelope : item.command
const requestedOf = item => producerOf(item).requested_at

// Gates shared by state and feedback commands; returns a terminal refusal code, null to apply,
// or throws `skip` for configuration that must not become a terminal result.
function gate(item, route, ctx) {
  if (item.expired) return "expired"
  const generationCode = producerGenerationCode(producerOf(item), route)
  if (generationCode) return generationCode
  if (item.kind !== "sealed") return null
  const code = routeApplyCode(item.envelope, route, ctx.env)
  if (code) return code
  const credentialCode = routeCredentialCode(ctx.env)
  if (credentialCode) throw Object.assign(refusal(credentialCode), { skip: true })
  return null
}

async function consumeState(items, rejectedItems, snapshot, ctx, report) {
  const document0 = snapshot.resultsDocument
  const kept = retainResults(document0.results, ctx.at)
  const results = kept.results
  const rejected = retainRejected(document0.rejected, ctx.at)
  let outbox = pruneOutbox(document0.outbox, ctx.at)
  let state = snapshot.state, document = snapshot.document, route = snapshot.route
  let content = null, stateChanged = false, routeChanged = false
  let resultsChanged = kept.pruned > 0 || Object.keys(rejected).length !== Object.keys(document0.rejected).length
    || Object.keys(outbox).length !== Object.keys(document0.outbox).length
  for (const item of rejectedItems) {
    rejected[item.digest] = { code: "command_seal_invalid", command_id: item.id, at: ctx.consumedAt }
    report.rejected.push({ command_id: item.id, code: "command_seal_invalid" })
    resultsChanged = true
  }
  for (const item of items) {
    if (Object.keys(results).length >= MAX_RESULTS) { report.skipped.push({ command_id: item.id, code: "command_results_capacity" }); continue }
    const base = { digest: item.digest, action: actionOf(item), consumed_at: ctx.consumedAt, run: ctx.marker, expires_at: producerOf(item).expires_at }
    let row
    try {
      const code = gate(item, route, ctx)
      if (code) row = { ...base, status: "refused", code }
      else {
        const local = { ...ctx, state, document, route, outbox, runtimeReport: snapshot.runtimeReport }
        try {
          const action = actionOf(item)
          const out = action === "draft_update" ? await applyDraftUpdate(item, local)
            : action === "reconcile_delivery" ? applyReconciliation(item, local) : applyRouteControl(item, local)
          state = out.state; document = out.document
          if (out.stateChanged) { stateChanged = true; content = out.content }
          if (out.route) { route = out.route; routeChanged = true }
          if (out.outbox) { outbox = { ...outbox, [out.outbox.publish_intent_id]: out.outbox }; report.outbox_queued.push({ command_id: item.id, publish_intent_id: out.outbox.publish_intent_id }) }
          row = { ...base, status: "applied", code: null, ...out.extra }
        } catch (error) { row = { ...base, status: "refused", code: codeOf(error) } }
      }
    } catch (error) {
      if (!error?.skip) throw error
      report.skipped.push({ command_id: item.id, code: error.code })
      continue
    }
    results[item.id] = row
    resultsChanged = true
    report[row.status === "applied" ? "applied" : "refused"].push({ command_id: item.id, code: row.code ?? null })
  }
  report.outbox_active = activeOutboxCount(outbox)
  if (!stateChanged && !routeChanged && !resultsChanged) return
  const files = { [RESULTS_FILE]: { content: resultsFileContent({ results, outbox, rejected }) } }
  if (stateChanged) files["state.json"] = { content }
  if (routeChanged) files[ROUTE_FILE] = { content: JSON.stringify(route) }
  await patchStateGistFiles(files)
  report.state_patches += 1
}

function feedbackDocument(loaded) {
  return resultsDocumentFromFiles(loaded.resultsMeta ? { [RESULTS_FILE]: loaded.resultsMeta } : {})
}

async function consumeFeedback(items, ctx, report) {
  for (const item of items) {
    let input0
    try { input0 = parseEmbedded(item.body?.payload?.input_json) } catch { input0 = null }
    const loaded = await loadFeedbackStores(typeof input0?.request_id === "string" ? input0.request_id : null)
    if (loaded.route && CODE_GENERATION < loaded.route.generation) throw refusal("stale_writer_generation")
    const document0 = feedbackDocument(loaded)
    const results = retainResults(document0.results, ctx.at).results
    if (results[item.id]) {
      // Settled by an earlier consumer between our read and this one: never applied twice.
      report[results[item.id].digest === item.digest ? "duplicates" : "reused"].push(results[item.id].digest === item.digest ? item.id : { command_id: item.id, code: "command_id_reused" })
      continue
    }
    const base = { digest: item.digest, action: actionOf(item), consumed_at: ctx.consumedAt, run: ctx.marker, expires_at: item.envelope.expires_at }
    let row
    const files = {}
    try {
      const code = gate(item, loaded.route, ctx)
      if (code) row = { ...base, status: "refused", code }
      else {
        try {
          if (item.body.targets.length || !exactKeys(item.body.payload, ["input_json"]) || !input0) throw refusal("invalid_payload")
          const plan = planFeedbackSave(feedbackInputOf(input0), loaded, ctx.at)
          if (!plan.already_saved) files[feedbackFilename(plan.record.request_id)] = { content: JSON.stringify(plan.record) }
          row = { ...base, status: "applied", code: null, already_saved: plan.already_saved }
        } catch (error) { row = { ...base, status: "refused", code: codeOf(error) } }
      }
    } catch (error) {
      if (!error?.skip) throw error
      report.skipped.push({ command_id: item.id, code: error.code })
      continue
    }
    results[item.id] = row
    files[RESULTS_FILE] = { content: resultsFileContent({ ...document0, results }) }
    await patchFeedbackGist(files)
    report.feedback_patches += 1
    report[row.status === "applied" ? "applied" : "refused"].push({ command_id: item.id, code: row.code ?? null })
  }
}

// entries: [{ raw, admission, source }] from the admitted-artifact inbox.
export async function consumeGistCommands(entries, { env = process.env, now = () => new Date() } = {}) {
  const marker = serializedWriterMarker(env)
  if (!marker) throw new RouteError("serialized_writer_marker_required", 503)
  configuredRouteMode(env)
  const at = now()
  const ctx = { env, marker, at, consumedAt: at.toISOString() }
  const report = { marker, consumed_at: ctx.consumedAt, invalid: [], applied: [], refused: [], duplicates: [], reused: [], rejected: [],
    skipped: [], deferred: 0, outbox_queued: [], outbox_active: 0, state_patches: 0, feedback_patches: 0 }
  const parsed = []
  for (const entry of entries) {
    try {
      const item = parseCommandRaw(entry.raw, { now: at })
      const id = item.kind === "sealed" ? item.envelope.command_id : item.command.command_id
      if (!entry.admission || entry.admission.digest !== item.digest || entry.admission.command_id !== id) throw new RouteError("admission_digest_mismatch")
      parsed.push({ ...item, id, source: entry.source ?? null })
    } catch (error) { report.invalid.push({ source: entry.source ?? null, code: codeOf(error) }) }
  }
  // Open sealed commands. No key / another key id: not terminal (left for a correctly configured run).
  let key = null, keyCode = "command_seal_key_missing"
  try { key = sealKey(env) } catch (error) { keyCode = codeOf(error) }
  const opened = [], rejected = []
  for (const item of parsed) {
    if (item.kind !== "sealed") { opened.push(item); continue }
    if (!key) { report.skipped.push({ command_id: item.id, code: keyCode }); continue }
    try { opened.push({ ...item, body: openEnvelope(item, key) }) } catch (error) {
      if (error.code === "command_seal_key_unknown") report.skipped.push({ command_id: item.id, code: error.code })
      else rejected.push(item)
    }
  }
  opened.sort((a, b) => requestedOf(a).localeCompare(requestedOf(b)) || a.id.localeCompare(b.id) || a.digest.localeCompare(b.digest))
  const snapshot = await readStateGistSnapshot()
  if (snapshot.route && CODE_GENERATION < snapshot.route.generation) throw refusal("stale_writer_generation")
  const feedbackOpened = opened.filter(item => FEEDBACK_ACTIONS.has(actionOf(item)))
  const feedbackDoc = feedbackOpened.length ? feedbackDocument(await loadFeedbackStores(null)) : { results: {} }
  // Settle what is already terminal BEFORE budgeting new work (B.2): persisted duplicates, reused
  // ids and already-rejected envelopes never occupy the per-drain budget.
  const fresh = [], seen = new Map()
  for (const item of opened) {
    const prior = (FEEDBACK_ACTIONS.has(actionOf(item)) ? feedbackDoc.results : snapshot.resultsDocument.results)[item.id]
    const digest = prior?.digest ?? seen.get(item.id)
    if (digest !== undefined) {
      if (digest === item.digest) report.duplicates.push(item.id)
      else report.reused.push({ command_id: item.id, code: "command_id_reused" })
      continue
    }
    seen.set(item.id, item.digest)
    fresh.push(item)
  }
  const unrecorded = rejected.filter(item => {
    if (!snapshot.resultsDocument.rejected[item.digest]) return true
    report.duplicates.push(item.id)
    return false
  })
  const batch = fresh.slice(0, MAX_COMMANDS_PER_DRAIN)
  report.deferred = fresh.length - batch.length
  const stateItems = batch.filter(item => !FEEDBACK_ACTIONS.has(actionOf(item)))
  const feedbackItems = batch.filter(item => FEEDBACK_ACTIONS.has(actionOf(item)))
  await consumeState(stateItems, unrecorded, snapshot, ctx, report)
  if (feedbackItems.length) await consumeFeedback(feedbackItems, ctx, report)
  return report
}

// Durable sender outbox step (ROUTE-CONTRACT-v2 §5): reconcile every entry on a fresh read,
// persist `dispatching` BEFORE each POST, then persist each outcome. Only while the route is
// active under the route-era credential; otherwise nothing is written or dispatched.
export async function runSenderOutbox({ env = process.env, now = () => new Date(), fetchImpl = globalThis.fetch, token, repo }) {
  if (!serializedWriterMarker(env)) throw new RouteError("serialized_writer_marker_required", 503)
  const report = { status: "ok", changes: [], dispatches: [], lookups_failed: 0 }
  const snapshot = await readStateGistSnapshot()
  if (!routeActive(snapshot.route, env)) return { ...report, status: "route_not_active" }
  const credentialCode = routeCredentialCode(env)
  if (credentialCode) return { ...report, status: credentialCode }
  const document0 = snapshot.resultsDocument
  if (!Object.keys(document0.outbox).length) return report
  const at = now()
  const runs = {}
  for (const { id, entry } of lookupTargets(document0.outbox)) {
    try { const run = await findRun(entry, { fetchImpl, token, repo }); if (run) runs[id] = run } catch { report.lookups_failed += 1 }
  }
  const pruned = pruneOutbox(document0.outbox, at)
  const plan = planOutbox({ outbox: pruned, state: snapshot.state, runtimeReport: snapshot.runtimeReport,
    activation: snapshot.route.command_id, runs, at })
  report.changes = plan.changes
  if (!plan.changes.length && Object.keys(pruned).length === Object.keys(document0.outbox).length) return report
  await patchStateGistFiles({ [RESULTS_FILE]: { content: resultsFileContent({ ...document0, outbox: plan.outbox }) } })
  if (!plan.dispatch.length) return report
  const outcomes = {}
  for (const id of plan.dispatch) {
    const entry = plan.outbox[id]
    const draft = snapshot.state.drafts.find(candidate => candidate.id === entry.draft_id)
    outcomes[id] = await dispatchSender(draft, entry, { fetchImpl, token, repo })
    report.dispatches.push({ publish_intent_id: id, command_id: entry.command_id, state: outcomes[id].state, code: outcomes[id].code })
  }
  // Only this serialized job writes the results file; re-read it and record each outcome.
  const latest = (await readStateGistSnapshot()).resultsDocument
  const outbox = { ...latest.outbox }
  const stamp = now().toISOString()
  for (const [id, outcome] of Object.entries(outcomes)) {
    if (outbox[id]?.state !== "dispatching") continue
    outbox[id] = { ...outbox[id], state: outcome.state, code: outcome.code, run_id: outcome.run_id ?? outbox[id].run_id ?? null, updated_at: stamp }
  }
  await patchStateGistFiles({ [RESULTS_FILE]: { content: resultsFileContent({ ...latest, outbox }) } })
  return report
}

// B.2 acknowledgement: an inbox artifact may be deleted only when a FRESH read of the Gists shows
// a terminal record for it — its id with its digest, its id under another digest (it can never
// apply), or its digest among the rejected envelopes. Everything else stays for a later drain.
export function acknowledgeable(entries, { stateDocument, feedbackDocument: feedback = { results: {}, rejected: {} } }) {
  const out = []
  for (const entry of entries) {
    const id = entry.admission?.command_id, digest = entry.admission?.digest
    if (!Number.isSafeInteger(entry.artifact_id) || typeof id !== "string" || typeof digest !== "string") continue
    const row = stateDocument.results[id] ?? feedback.results[id]
    if (row) out.push({ artifact_id: entry.artifact_id, command_id: id, reason: row.digest === digest ? "result_persisted" : "command_id_reused" })
    else if (stateDocument.rejected[digest]) out.push({ artifact_id: entry.artifact_id, command_id: id, reason: "envelope_rejected" })
  }
  return out
}

export async function acknowledgeArtifacts(entries, { fetchImpl = globalThis.fetch, token, repo, readFeedback = true }) {
  const stateDocument = (await readStateGistSnapshot()).resultsDocument
  let feedback = { results: {}, rejected: {} }
  if (readFeedback) { try { feedback = feedbackDocument(await loadFeedbackStores(null)) } catch { feedback = null } }
  const candidates = acknowledgeable(entries, { stateDocument, feedbackDocument: feedback ?? { results: {}, rejected: {} } })
    // Without a readable feedback Gist, only state-recorded artifacts are acknowledged.
    .filter(row => feedback || stateDocument.results[row.command_id] || row.reason === "envelope_rejected")
  const deleted = [], failed = []
  for (const row of candidates) {
    try {
      const response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/artifacts/${row.artifact_id}`, { method: "DELETE",
        headers: { Accept: "application/vnd.github+json", ...(token ? { Authorization: `token ${token}` } : {}) } })
      if (response.status === 204 || response.status === 404) deleted.push(row)
      else failed.push({ ...row, code: `delete_http_${response.status}` })
    } catch { failed.push({ ...row, code: "delete_request_failed" }) }
  }
  return { deleted, failed }
}
