// P00c durable sender outbox (ROUTE-CONTRACT-v2 §5). An approval applied by the serialized
// consumer writes a `queued` entry, tied to its exact publish intent, in the SAME PATCH as the
// approval. Later steps of the same group job (and every later drain) dispatch it, record each
// outcome durably, recover definitely-unattempted or definitely-failed work, and expose (never
// blindly resend) uncertain dispatches. Dispatching a workflow is never evidence that a post is
// safe: the sender's own checks and its write-first publish-intent ledger row remain the gate.
// Entries hold ids, states and codes only — never draft text.
import { approvalIsCurrent, hasUnresolvedPublish } from "./draft-revisions.js"
import { dashboardEditorialPolicy } from "./editorial-policy.js"

export const OUTBOX_MAX_ACTIVE = 50
export const OUTBOX_MAX_ATTEMPTS = 5
export const OUTBOX_TERMINAL_RETENTION_MS = 3 * 86400000
export const OUTBOX_UNSEEN_UNCERTAIN_MS = 6 * 3600000
// A run is judged only after it settled: an in-flight claim PATCH lands well within this window.
export const RUN_SETTLE_MS = 300000
// Every in-flight entry is observed each drain (active entries are bounded by OUTBOX_MAX_ACTIVE):
// run ids by one GET each, everything else from ONE shared bounded listing of bot.yml runs.
export const OUTBOX_MAX_LOOKUPS = OUTBOX_MAX_ACTIVE
export const RUN_LISTING_PAGES = 5
export const RUN_TITLE_PREFIX = "theheat-bot manual_tweet "
export const TERMINAL_STATES = new Set(["completed", "superseded", "sender_refused", "sender_finished_without_claim", "exhausted", "route_generation_changed"])
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export function outboxEntry({ commandId, draft, publishIntentId, activation, at }) {
  return { kind: "bot_manual_tweet", command_id: commandId, draft_id: draft.id, event_id: draft.event_id || draft.id,
    publish_intent_id: publishIntentId, route_activation: activation, state: "queued", code: null, attempts: 0,
    attempt_at: null, run_id: null, created_at: at, updated_at: at }
}

export function activeOutboxCount(outbox) {
  return Object.values(outbox || {}).filter(entry => !TERMINAL_STATES.has(entry?.state)).length
}

export function pruneOutbox(outbox, at) {
  const kept = {}
  for (const [id, entry] of Object.entries(outbox || {})) {
    const updated = Date.parse(entry?.updated_at)
    if (TERMINAL_STATES.has(entry?.state) && Number.isFinite(updated) && updated + OUTBOX_TERMINAL_RETENTION_MS < at.getTime()) continue
    kept[id] = entry
  }
  return kept
}

// The sender's existing write-first claim: publish_ledger[event].intent_id is written durably
// before any egress. A row for this intent is final evidence; no row means nothing was sent.
export function ledgerEvidence(state, entry) {
  const row = state.publish_ledger?.[entry.event_id]
  if (!row || typeof row !== "object" || row.intent_id !== entry.publish_intent_id) return null
  if (row.tweet_id || row.phase === "confirmed") return "completed"
  if (row.phase === "not_sent") return "sender_refused"
  return "claimed"
}

// The exact legacy pre-dispatch check (app/api/drafts/route.js before its bot.yml dispatch).
export function dispatchEligible(state, runtimeReport, entry) {
  const draft = state.drafts?.find(candidate => candidate?.id === entry.draft_id)
  if (!draft) return null
  const policy = dashboardEditorialPolicy(state, { runtimeReport }).policy
  return draft.status === "approved" && approvalIsCurrent(draft, "manual", policy) && draft.publish_intent_id === entry.publish_intent_id
    && !hasUnresolvedPublish(draft, state) ? draft : null
}

function transition(entry, state, code, at, extra = {}) {
  return { ...entry, ...extra, state, code, updated_at: at }
}

// Pure reconciliation on one fresh state read plus observed runs. Returns the next outbox and the
// entries due for a dispatch now. Due entries keep their state (queued/failed): the caller journals
// ONE entry as `dispatching` immediately before its own POST (review R4), never a batch.
export function planOutbox({ outbox, state, runtimeReport, activation, runs, at }) {
  const now = at.toISOString(), next = {}, dispatch = [], changes = []
  for (const [id, entry] of Object.entries(outbox || {})) {
    let row = entry
    if (!TERMINAL_STATES.has(row.state)) {
      if (row.route_activation !== activation) row = transition(row, "route_generation_changed", "route_generation_not_current", now)
      else {
        const evidence = ledgerEvidence(state, row)
        if (evidence) {
          if (evidence !== row.state) row = transition(row, evidence, null, now)
        } else if (!dispatchEligible(state, runtimeReport, row)) {
          row = transition(row, "superseded", "approval_not_current", now)
        } else {
          if (row.state === "dispatching") row = transition(row, "uncertain", "dispatch_outcome_unknown", now)
          const run = runs?.[id]
          if (["dispatched", "uncertain"].includes(row.state) && run) {
            const extra = { run_id: run.id ?? row.run_id }
            if (run.status !== "completed") { if (row.state !== "dispatched") row = transition(row, "dispatched", null, now, extra) }
            else if (run.conclusion === "cancelled") {
              // Cancelled (e.g. a replaced pending group entry) with NO sender claim: nothing was sent.
              if (at.getTime() - Date.parse(run.updated_at) >= RUN_SETTLE_MS) row = transition(row, "failed", "run_cancelled_before_claim", now, extra)
            } else row = transition(row, "sender_finished_without_claim", `run_${run.conclusion || "completed"}`, now, extra)
          } else if (row.state === "dispatched" && !run && Date.parse(row.attempt_at) + OUTBOX_UNSEEN_UNCERTAIN_MS < at.getTime()) {
            row = transition(row, "uncertain", "run_not_visible", now)
          }
          if (["queued", "failed"].includes(row.state)) {
            if ((row.attempts ?? 0) >= OUTBOX_MAX_ATTEMPTS) row = transition(row, "exhausted", row.code, now)
            else {
              dispatch.push(id)
            }
          }
        }
      }
    }
    if (row !== entry) changes.push({ publish_intent_id: id, from: entry.state, to: row.state, code: row.code ?? null })
    next[id] = row
  }
  return { outbox: next, dispatch, changes }
}

// Entries whose GitHub run must be observed this drain (bounded).
// The journal entry written immediately before one POST. A new attempt observes only its own run.
export function startAttempt(entry, at) {
  return { ...entry, state: "dispatching", attempts: (entry.attempts ?? 0) + 1, attempt_at: at, run_id: null, updated_at: at }
}

export const MAX_DISPATCHES_PER_DRAIN = 10

export function lookupTargets(outbox) {
  return Object.entries(outbox || {}).filter(([, entry]) => ["dispatched", "uncertain", "dispatching"].includes(entry?.state))
    .slice(0, OUTBOX_MAX_LOOKUPS).map(([id, entry]) => ({ id, entry }))
}

const runView = run => ({ id: run.id, status: run.status, conclusion: run.conclusion ?? null, updated_at: run.updated_at, created_at: run.created_at })

// The run for each target: an attempt that is still running dominates; otherwise its newest run.
export async function observeRuns(targets, { fetchImpl = globalThis.fetch, token, repo }) {
  const runs = {}
  let failed = 0
  const titled = []
  for (const { id, entry } of targets) {
    if (Number.isSafeInteger(entry.run_id)) {
      try {
        const response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/runs/${entry.run_id}`, { headers: headers(token), cache: "no-store" })
        if (!response.ok) throw new Error("run lookup failed")
        runs[id] = runView(await response.json())
      } catch { failed += 1 }
    } else if (UUID.test(entry.publish_intent_id) && Number.isFinite(Date.parse(entry.attempt_at))) titled.push({ id, entry })
  }
  if (!titled.length) return { runs, failed }
  const oldest = Math.min(...titled.map(({ entry }) => Date.parse(entry.attempt_at)))
  const since = new Date(oldest - 60000).toISOString().replace(/\.\d{3}Z$/, "Z")
  const listed = []
  try {
    for (let page = 1; page <= RUN_LISTING_PAGES; page += 1) {
      const response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/workflows/bot.yml/runs?event=workflow_dispatch&per_page=100&page=${page}&created=${encodeURIComponent(`>=${since}`)}`,
        { headers: headers(token), cache: "no-store" })
      if (!response.ok) throw new Error("run listing failed")
      const rows = (await response.json())?.workflow_runs
      if (!Array.isArray(rows)) throw new Error("run listing failed")
      listed.push(...rows)
      if (rows.length < 100) break
    }
  } catch { return { runs, failed: failed + titled.length } }
  for (const { id, entry } of titled) {
    const title = `${RUN_TITLE_PREFIX}${entry.publish_intent_id}`
    const after = Date.parse(entry.attempt_at) - 60000
    const matches = listed.filter(run => run?.display_title === title && !(Date.parse(run.created_at) < after))
    if (!matches.length) continue
    const live = matches.find(run => run.status !== "completed")
    runs[id] = runView(live ?? matches.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0])
  }
  return { runs, failed }
}

function headers(token) {
  return { Accept: "application/vnd.github+json", ...(token ? { Authorization: `token ${token}` } : {}) }
}

// One bot.yml manual_tweet dispatch. 2xx accepted; 4xx (incl. 429) definitely not accepted;
// a thrown request or 5xx may have been accepted and is uncertain.
export async function dispatchSender(draft, entry, { fetchImpl = globalThis.fetch, token, repo }) {
  let response
  try {
    response = await fetchImpl(`https://api.github.com/repos/${repo}/actions/workflows/bot.yml/dispatches`, {
      method: "POST", headers: { ...headers(token), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs: { mode: "manual_tweet", tweet_text: draft.text, draft_id: draft.id,
        publish_intent_id: entry.publish_intent_id } }),
    })
  } catch { return { state: "uncertain", code: "dispatch_request_uncertain" } }
  if (response.status >= 200 && response.status < 300) {
    let runId = null
    try { const body = await response.json(); if (Number.isSafeInteger(body?.workflow_run_id)) runId = body.workflow_run_id } catch { /* 204 has no body */ }
    return { state: "dispatched", code: null, run_id: runId }
  }
  if (response.status >= 400 && response.status < 500) return { state: "failed", code: `dispatch_http_${response.status}` }
  return { state: "uncertain", code: `dispatch_http_${response.status}` }
}
