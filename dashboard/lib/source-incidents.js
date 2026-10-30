// Product-level source incidents from retained run rows (mirror of
// src/data/source_incidents.py project_incidents). One identity is the exact
// product leg + requested window + region + parser contract. Nothing here fetches
// or infers availability: a cleared transport error is "reachable, unqualified",
// and only a later qualified attempt for the same identity is recovery.
export const INCIDENT_SCHEMA = "theheat.source-incident/v1"

const QUALIFIED = new Set(["qualified"])
const REACHABLE_UNQUALIFIED = new Set(["empty_success", "stale_product", "malformed"])
const ACCESS_HOLDS = new Set(["access_refused", "access_expired", "access_not_configured", "access_backoff"])
const KNOWN = new Set([
  "qualified", "empty_success", "stale_product", "malformed", "endpoint_missing", "access_refused",
  "access_expired", "access_not_configured", "access_backoff", "rate_limited", "provider_error",
  "transport_failure", "granule_missing", "not_attempted",
])

export const INCIDENT_LABELS = Object.freeze({
  open: "Open incident",
  access_hold: "Owner access hold",
  reachable_unqualified: "Reachable, not qualified",
  recovered: "Recovered (qualified result)",
  qualified: "Qualified",
})

export const OUTCOME_TEXT = Object.freeze({
  endpoint_missing: "HTTP 404/410: endpoint or product file missing. This is not 'no events'.",
  access_refused: "Provider refused access; owner account/key check required.",
  access_expired: "Credential expired; owner renewal required. No request was sent.",
  access_not_configured: "Credential not configured; no request was sent.",
  access_backoff: "Provider refused this same credential recently; no request was sent inside its backoff.",
  empty_success: "Provider answered with no product rows; not recovery.",
  stale_product: "Provider answered with stale rows only; not recovery.",
  malformed: "Provider answered with something other than the product; not recovery.",
  rate_limited: "Provider rate limit (HTTP 429).",
  provider_error: "Provider-side failure (HTTP 5xx).",
  transport_failure: "Timeout or connection failure before a provider answer.",
  granule_missing: "No product file published inside the bounded window.",
})

function runsOldestFirst(runHistory) {
  const runs = Array.isArray(runHistory) ? runHistory.filter(run => run && typeof run === "object") : []
  return [...runs].sort((a, b) => String(a.started_at ?? "").localeCompare(String(b.started_at ?? "")))
}

export function sourceIncidents(runHistory, source = null) {
  const table = new Map()
  for (const run of runsOldestFirst(runHistory)) {
    const at = String(run.started_at ?? "")
    for (const entry of Array.isArray(run.sources) ? run.sources : []) {
      if (!entry || typeof entry !== "object" || (source !== null && entry.source !== source)) continue
      const incident = entry.details?.incident
      if (!incident || incident.schema !== INCIDENT_SCHEMA) continue
      for (const item of Array.isArray(incident.attempts) ? incident.attempts : []) {
        if (!item || !KNOWN.has(item.outcome) || item.outcome === "not_attempted") continue
        const key = String(item.key)
        let row = table.get(key)
        if (!row) {
          row = {
            key, source: entry.source ?? null, product_id: item.product_id ?? null, role: item.role ?? null,
            provider: item.provider ?? null, window: item.window ?? null, region: item.region ?? null,
            parser_contract: item.parser_contract ?? null, first_failure: null, last_failure: null, failures: 0,
            last_outcome: null, last_at: null, recovered_at: null, recovery_run: null, failure_outcomes: [],
          }
          table.set(key, row)
        }
        row.last_outcome = item.outcome
        row.last_at = at
        if (QUALIFIED.has(item.outcome)) {
          if (row.failures && row.recovered_at === null) { row.recovered_at = at; row.recovery_run = run.id ?? null }
          continue
        }
        if (row.recovered_at !== null) { row.recovered_at = null; row.recovery_run = null }
        row.failures += 1
        row.first_failure = row.first_failure ?? at
        row.last_failure = at
        if (!row.failure_outcomes.includes(item.outcome)) row.failure_outcomes.push(item.outcome)
      }
    }
  }
  const rows = [...table.values()].map(row => {
    const last = row.last_outcome
    const state = QUALIFIED.has(last) ? (row.failures ? "recovered" : "qualified")
      : REACHABLE_UNQUALIFIED.has(last) ? "reachable_unqualified"
        : ACCESS_HOLDS.has(last) ? "access_hold" : "open"
    return { ...row, state, label: INCIDENT_LABELS[state], text: OUTCOME_TEXT[last] ?? null,
      retained_window: "retained_run_history_only" }
  })
  return rows.sort((a, b) => String(a.source).localeCompare(String(b.source)) || a.key.localeCompare(b.key))
}

// The newest run's product state for one source, read from its own incident payload.
export function latestIncidentState(row) {
  const incident = row?.details?.incident
  if (!incident || incident.schema !== INCIDENT_SCHEMA) return null
  const attempts = Array.isArray(incident.attempts) ? incident.attempts : []
  const failing = attempts.filter(item => item && KNOWN.has(item.outcome) && !QUALIFIED.has(item.outcome)
    && item.outcome !== "not_attempted")
  return {
    product_state: typeof incident.product_state === "string" ? incident.product_state : null,
    served_product_ids: Array.isArray(incident.served_product_ids) ? incident.served_product_ids : [],
    failing: failing.map(item => ({ product_id: item.product_id ?? null, outcome: item.outcome,
      text: OUTCOME_TEXT[item.outcome] ?? null })),
  }
}
