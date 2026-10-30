import { sourceOutcome } from "./live-content-status.js"

// Source gaps: why a source supplied nothing in the latest run, with its owner/next action.
const GAP_STATES = new Set(["access_expired", "access_refused", "baseline_unavailable", "unqualified_input",
  "endpoint_missing", "regional_hold", "unavailable", "reachable_unqualified", "alternate_served", "stale_data"])

// Coverage-to-selection trace (W08.6) from retained state only. Each event gets
// exactly one of six distinct outcomes; unknown denominators stay null and a
// complete trace is never global recall or calibrated preference.
export const TRACE_OUTCOMES = Object.freeze({
  not_fetched: "Source not fetched or unavailable this run",
  unqualified: "Fetched, but withheld by evidence/qualification checks",
  not_selected: "Qualified, but not selected within the candidate allowance",
  failed_checks: "Selected; copy failed a required check",
  waiting: "Draft waiting for review or delivery",
  posted: "Posted with a retained receipt",
})
const CHECK_STAGES = new Set(["writer", "safety", "fact_check", "critic", "honesty_gate"])
const QUALIFICATION_STAGES = new Set(["evidence_contract", "evidence", "admission", "qualification"])
// episode_repeat: a repeated poll with no new material fact; portfolio_not_selected: outside the plan.
const SELECTION_STAGES = new Set(["candidate_budget", "selector", "triage", "global_cap", "budget", "episode_repeat",
  "portfolio_not_selected"])

function list(value) { return Array.isArray(value) ? value : [] }

export function selectionTrace(state, { referenceOpportunities = null } = {}) {
  const rows = new Map()
  const put = (eventId, outcome, detail) => {
    if (!eventId) return
    const order = Object.keys(TRACE_OUTCOMES)
    const current = rows.get(eventId)
    // Later lifecycle stages win: posted > waiting > failed_checks > not_selected > unqualified.
    if (!current || order.indexOf(outcome) > order.indexOf(current.outcome)) rows.set(eventId, { event_id: eventId, outcome, label: TRACE_OUTCOMES[outcome], detail })
  }
  for (const row of list(state?.candidates_log)) put(row?.event_id, "not_selected", "qualified candidate; no draft yet")
  for (const s of list(state?.suppressions)) {
    const stage = String(s?.stage ?? "")
    if (QUALIFICATION_STAGES.has(stage)) put(s?.event_id, "unqualified", stage)
    else if (CHECK_STAGES.has(stage)) put(s?.event_id, "failed_checks", stage)
    else if (SELECTION_STAGES.has(stage)) put(s?.event_id, "not_selected", stage)
  }
  for (const d of list(state?.drafts)) {
    if (d?.status === "posted" && (d?.tweet_id || d?.receipt)) put(d?.event_id, "posted", d?.tweet_id ? "receipt retained" : "receipt")
    else if (d?.status === "pending" || d?.status === "approved" || d?.publish_outcome === "unknown") {
      put(d?.event_id, "waiting", d?.publish_outcome === "unknown" ? "delivery unknown; never resent" : d?.status)
    }
  }
  const notFetched = []
  const gaps = []
  for (const run of list(state?.run_history).slice(0, 1)) {
    for (const s of list(run?.sources)) {
      if (s?.status === "failed" || s?.status === "skipped") notFetched.push(s?.source)
      const why = sourceOutcome(s)
      if (GAP_STATES.has(why.state)) {
        gaps.push({ source: why.source, status: why.status, state: why.state, reason: why.label, detail: why.detail,
          next_action: why.next_action })
      }
    }
  }
  const reference = Array.isArray(referenceOpportunities) ? referenceOpportunities : null
  for (const id of reference ?? []) if (!rows.has(id)) put(id, "not_fetched", "reference opportunity with no retained candidate")
  const counts = Object.fromEntries(Object.keys(TRACE_OUTCOMES).map(k => [k, 0]))
  for (const row of rows.values()) counts[row.outcome] += 1
  return {
    events: [...rows.values()].sort((a, b) => a.event_id.localeCompare(b.event_id)),
    counts,
    not_fetched_sources: notFetched.sort(),
    // Miss reasons for the coverage view and weekly cadence; a gap is not a count of missed events.
    source_gaps: gaps.sort((a, b) => String(a.source).localeCompare(String(b.source))),
    reference_denominator: reference ? reference.length : null,
    recall: null,
    scope: "Retained candidates, checks and drafts only; not global recall or calibrated editor preference.",
  }
}
