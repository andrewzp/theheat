// Decision-point cost rows persisted with run history (src/two_bot/call_inventory.py).
// Browser contract: fixed codes and bounded counts only. No prompt, header,
// credential, exception text or free label crosses this projection; anything
// unexpected is dropped, never repaired into a cost.

const OPERATIONS = ["alerts", "leaderboard", "publish", "manual_generation", "batch_generation", "threshold_refresh"]
const PATHS = ["ordinary", "manual", "batch", "maintenance"]
const SPEND = ["discovery", "selection", "acquisition", "platform", "hosting", "maintenance", "evaluation"]
const PRICING = ["estimate_partial", "unknown"]
const OUTCOMES = ["dispatched", "returned", "malformed", "unavailable", "unknown", "released_unstarted"]
const CEILINGS = ["candidate_attempts", "provider_call_cap", "estimated_token_cap", "local_spend_allowance",
  "daily_publication_cap", "monthly_budget_watch", "invoice_ceiling"]
const STAGE = /^[a-z][a-z0-9_]{0,39}$/
const MAX_RUNS = 5, MAX_ROWS = 8

const object = (v) => v !== null && typeof v === "object" && !Array.isArray(v)
const count = (v, max = 1000000) => Number.isSafeInteger(v) && v >= 0 && v <= max
const pick = (v, list) => (list.includes(v) ? v : null)

function stageRows(raw) {
  if (!object(raw)) return []
  return Object.entries(raw).filter(([stage]) => STAGE.test(stage)).slice(0, 24).flatMap(([stage, row]) => {
    if (!object(row) || !count(row.requests) || !count(row.unsettled) || !count(row.unknown_or_malformed)) return []
    return [{stage, requests: row.requests, unsettled: row.unsettled, unknown_or_malformed: row.unknown_or_malformed,
      spend_class: pick(row.spend_class, SPEND), pricing: pick(row.pricing, PRICING) || "unknown"}]
  })
}

function allowanceRows(raw) {
  if (!Array.isArray(raw)) return []
  return raw.slice(0, 4).flatMap((allowance) => {
    if (!object(allowance) || !object(allowance.stages)) return []
    return Object.entries(allowance.stages).filter(([stage]) => STAGE.test(stage)).slice(0, 8).flatMap(([stage, row]) => {
      if (!object(row) || ![row.limit, row.reserved, row.remaining, row.refused_before_egress, row.physical_attempts].every((v) => count(v))
          || !object(row.outcomes)) return []
      const outcomes = Object.fromEntries(OUTCOMES.slice(1).map((name) => [name, count(row.outcomes[name]) ? row.outcomes[name] : 0]))
      return [{stage, limit: row.limit, reserved: row.reserved, remaining: row.remaining,
        refused_before_egress: row.refused_before_egress, physical_attempts: row.physical_attempts, outcomes,
        pricing: pick(row.pricing, PRICING) || "unknown", spend_class: pick(row.spend_class, SPEND)}]
    })
  })
}

export function projectOperationCost(row) {
  if (!object(row) || row.schema_version !== 1 || !OPERATIONS.includes(row.operation) || !PATHS.includes(row.path)) return null
  const requests = object(row.requests) ? row.requests : {}
  const byOutcome = object(requests.by_outcome) ? requests.by_outcome : {}
  const attempts = object(row.candidate_attempts) ? row.candidate_attempts : null
  const another = object(row.another_attempt_allowed) ? row.another_attempt_allowed : {}
  return {
    operation: row.operation, path: row.path, spend_class: pick(row.spend_class, SPEND) || "selection",
    may_call: (Array.isArray(row.may_call) ? row.may_call : []).slice(0, 16).filter((c) => object(c) && STAGE.test(c.stage))
      .map((c) => ({stage: c.stage, spend_class: pick(c.spend_class, SPEND), pricing: pick(c.pricing, PRICING) || "unknown"})),
    ceilings: (Array.isArray(row.ceilings) ? row.ceilings : []).filter((c) => CEILINGS.includes(c)).slice(0, 8),
    candidate_attempts: attempts && (attempts.limit === null || count(attempts.limit)) && count(attempts.used)
      ? {limit: attempts.limit, used: attempts.used, returned_unstarted: count(attempts.returned_unstarted) ? attempts.returned_unstarted : 0,
          held: count(attempts.held) ? attempts.held : 0, refused: typeof attempts.refusal === "string"} : null,
    allowances: allowanceRows(row.allowances),
    requests: {total: count(requests.total) ? requests.total : null,
      by_outcome: Object.fromEntries(OUTCOMES.map((name) => [name, count(byOutcome[name]) ? byOutcome[name] : 0])),
      by_stage: stageRows(requests.by_stage), interrupted: count(requests.interrupted) ? requests.interrupted : 0,
      truncated: requests.truncated === true},
    unpriced_requests: count(row.unpriced_requests) ? row.unpriced_requests : null,
    estimate_only_requests: count(row.estimate_only_requests) ? row.estimate_only_requests : null,
    another_attempt_allowed: Object.fromEntries(Object.entries(another).filter(([k, v]) => STAGE.test(k) && typeof v === "boolean").slice(0, 8)),
    actual_cost_known: false, financial_cap: false,
  }
}

export function recentOperationCosts(state) {
  const runs = Array.isArray(state?.run_history) ? state.run_history.slice(0, MAX_RUNS) : []
  return runs.flatMap((run) => {
    if (!object(run) || !Array.isArray(run.operation_costs)) return []
    const started = typeof run.started_at === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(run.started_at) ? run.started_at.slice(0, 16) + "Z" : null
    return run.operation_costs.slice(-MAX_ROWS).map(projectOperationCost).filter(Boolean).map((row) => ({...row, run_started_at: started}))
  }).slice(0, 12)
}
