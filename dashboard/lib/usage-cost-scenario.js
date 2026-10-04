// Pure server-side counterpart of usage_cost_scenario.py; no provider or state writes.
import { COST_SCENARIO as C } from "./usage-cost-contract.js"
import { USAGE_OBSERVATION_CONTRACT as U } from "./state-contract.js"
import { validUsageObservation } from "./usage-observations.js"

const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const canonical = value => JSON.stringify(value && typeof value === "object"
  ? Array.isArray(value) ? value.map(v => JSON.parse(canonical(v)))
    : Object.fromEntries(Object.keys(value).sort().map(k => [k, JSON.parse(canonical(value[k]))]))
  : value)
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0
const money = value => `${value / 1000000000n}.${String(value % 1000000000n).padStart(9, "0")}`
const safeRecord = value => { try { return validUsageObservation(value) } catch { return false } }
const identifierRE = new RegExp(U.identifier_pattern)
const identifier = value => typeof value === "string" && identifierRE.exec(value)?.[0] === value
const modelKnown = model => typeof model === "string" && Object.hasOwn(C.rates, model)
const textBreakdown = (value, count, required = false) => value === null ? !required
  : count !== null && value.every(item => item.modality === "TEXT") && value.reduce((n, item) => n + item.token_count, 0) === count

function eligible(row) {
  const no = reason => ({reasons: [reason], amount: null})
  if (row.provider !== "google") return no("other_provider")
  if (row.usage_status !== "present" || row.invalid_fields.length || row.unsupported_fields) return no("incomplete_or_unsupported_capture")
  if (!modelKnown(row.resolved_model)) return no("unpriced_resolved_model")
  const counts = row.counts
  if (C.required_counts.some(name => counts[name] === null)) return no("missing_required_count")
  const [prompt, candidate, thought, total] = C.required_counts.map(name => counts[name])
  let tool = counts.tool_use_prompt_token_count
  const reasons = []
  if (tool === null) {
    if (total !== prompt + candidate + thought) return no("unexplained_total")
    tool = 0
    reasons.push("zero_tool_tokens_derived_from_total")
  } else if (total !== prompt + candidate + thought + tool) return no("inconsistent_total")
  if (tool) return no("tool_input_not_priced")
  const cache = counts.cached_content_token_count, details = row.breakdowns
  if (cache !== null && cache > prompt) return no("cache_exceeds_prompt")
  if (!textBreakdown(details.prompt_tokens_details, prompt, true)
      || !textBreakdown(details.candidates_tokens_details, candidate)
      || !textBreakdown(details.cache_tokens_details, cache)
      || !textBreakdown(details.tool_use_prompt_tokens_details, tool)) return no("unsupported_or_inconsistent_modality")
  if (cache === null) reasons.push("cache_count_unknown_interval")
  const [, incoming, cached, outgoing] = C.rates[row.resolved_model].find(rate => rate[0] === null || prompt <= rate[0])
  const price = cacheCount => BigInt(prompt - cacheCount) * BigInt(incoming)
    + BigInt(cacheCount) * BigInt(cached) + BigInt(candidate + thought) * BigInt(outgoing)
  return {reasons, amount: {min: price(cache ?? prompt), max: price(cache ?? 0), tokens: {prompt, candidate, thought}}}
}

function summary(rows) {
  const selected = rows.filter(row => row.disposition === "eligible")
  return {
    unique_valid_records: rows.length, eligible_records: selected.length, excluded_records: rows.length - selected.length,
    conflicting_records: rows.filter(row => row.disposition === "conflict").length,
    non_google_records: rows.filter(row => row.provider !== "google").length,
    eligible_token_subtotal_usd: selected.length ? Object.fromEntries(["min", "max"].map(key =>
      [key, money(selected.reduce((n, row) => n + row._amount[key], 0n))])) : null,
    eligible_tokens: selected.length ? Object.fromEntries(["prompt", "candidate", "thought"].map(key =>
      [key, selected.reduce((n, row) => n + row._amount.tokens[key], 0)])) : null,
  }
}

export function projectUsageCost(window, {scenario} = {}) {
  if (scenario !== C.scenario) throw new Error("unsupported_cost_scenario")
  if (window == null) throw new Error("usage_window_unavailable")
  const keys = ["schema_version", "observations", "truncated", "invalid"]
  if (!object(window) || Object.keys(window).length !== keys.length || !keys.every(key => Object.hasOwn(window, key))
      || window.schema_version !== 1 || typeof window.truncated !== "boolean" || typeof window.invalid !== "boolean"
      || !Array.isArray(window.observations) || window.observations.length > U.limit) throw new Error("invalid_usage_window")
  const unique = new Map(), invalidIds = new Set(), invalidResponses = new Set()
  let invalid = 0, duplicates = 0
  const responseKey = row => canonical([row.provider, row.response_id])
  for (const row of window.observations) {
    if (!safeRecord(row)) {
      invalid++
      if (object(row)) {
        if (typeof row.id === "string" && /^[a-f0-9]{32}$/.test(row.id) && row.id.length === 32) invalidIds.add(row.id)
        if (["google", "anthropic", "unknown"].includes(row.provider) && identifier(row.response_id)) invalidResponses.add(responseKey(row))
      }
      continue
    }
    // JS JSON numbers already have integer semantics; validator excludes bools,
    // fractions, nonfinite and out-of-range counts before canonical serialization.
    const key = canonical(row)
    if (unique.has(key)) duplicates++
    else unique.set(key, row)
  }
  const ids = new Map(), responses = new Map()
  const increment = (map, key) => map.set(key, (map.get(key) || 0) + 1)
  for (const row of unique.values()) {
    increment(ids, row.id)
    if (row.response_id !== null) increment(responses, responseKey(row))
  }
  const rows = [...unique.keys()].sort().map(key => {
    const row = unique.get(key)
    const conflict = ids.get(row.id) > 1 || invalidIds.has(row.id) || (row.response_id !== null
      && (responses.get(responseKey(row)) > 1 || invalidResponses.has(responseKey(row))))
    const {reasons, amount} = conflict ? {reasons: ["conflicting_observation_identity"], amount: null} : eligible(row)
    return {observation_id: row.id, provider: row.provider, stage: C.stages.includes(row.stage) ? row.stage : "unknown",
      model: row.provider === "google" && modelKnown(row.resolved_model) ? row.resolved_model : "unknown",
      disposition: conflict ? "conflict" : amount !== null ? "eligible" : "excluded", reasons, _amount: amount}
  })
  const groups = new Map()
  for (const row of rows) {
    const key = canonical([row.stage, row.model])
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }
  const times = [...unique.values()].map(row => row.observed_at).sort()
  return {
    schema_version: C.schema_version, identity_semantics: C.identity_semantics, scenario: C.scenario, pricing: {...C.pricing},
    actual_cost_known: false, complete_account_coverage: false,
    window_truncated: window.truncated, window_invalid: window.invalid || invalid > 0,
    input_records: window.observations.length, invalid_records: invalid, exact_duplicates: duplicates,
    observation_period: times.length ? {first: times[0], last: times.at(-1)} : null,
    ...summary(rows),
    groups: [...groups.values()].sort((a, b) => compare(a[0].stage, b[0].stage) || compare(a[0].model, b[0].model))
      .map(group => ({stage: group[0].stage, model: group[0].model, ...summary(group)})),
    limitations: [...C.limitations],
    rows: rows.map(({_amount, ...row}) => ({...row, token_component_usd: _amount
      ? {min: money(_amount.min), max: money(_amount.max)} : null})),
  }
}
