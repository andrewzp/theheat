import { summarizeUsage } from "./usage-ledger.js"
import { projectUsageCost } from "./usage-cost-scenario.js"

// Browser contract: totals/counts only. No row identities, provider content,
// arbitrary labels, monthly projections or configured budget presented as a cap.
export function buildCostEvidence(state, { scenario, now = Date.now() } = {}) {
  const result = {
    schema_version: 1, actual_bill_available: false, budget_enforced: false,
    recorded: {status: "unavailable"}, scenario: {status: "unavailable"},
  }
  if (!state) return result
  try {
    const summary = summarizeUsage({llm_usage: state.llm_usage}, {now, roundAmounts: false})
    result.recorded = {
      status: summary.coverage, month: new Date(now).toISOString().slice(0, 7),
      priced_subtotal_usd: summary.known_cost_usd,
      priced_calls: summary.priced_calls, unpriced_calls: summary.unpriced_calls,
      missing_usage_calls: summary.missing_usage_calls, legacy_calls: summary.legacy_calls,
      inconsistent_rows: summary.inconsistent_rows, excluded_rows: summary.excluded_rows,
    }
  } catch { result.recorded = {status: "unavailable", error: "recorded_usage_unavailable"} }
  try {
    if (scenario == null) { result.scenario = {status: "not_requested"}; return result }
    const report = projectUsageCost(state.llm_usage_observations, {scenario})
    result.scenario = {
      status: "partial", name: report.scenario, pricing_date: report.pricing.verified_on,
      observation_period: report.observation_period, input_records: report.input_records,
      invalid_records: report.invalid_records, duplicates: report.exact_duplicates,
      eligible_records: report.eligible_records, excluded_records: report.excluded_records,
      conflicting_records: report.conflicting_records, non_google_records: report.non_google_records,
      truncated: report.window_truncated, invalid: report.window_invalid,
      token_subtotal_usd: report.eligible_token_subtotal_usd, tokens: report.eligible_tokens,
    }
  } catch (error) {
    const safe = ["unsupported_cost_scenario", "usage_window_unavailable", "invalid_usage_window"]
    result.scenario = {status: "unavailable", error: safe.includes(error?.message) ? error.message : "cost_scenario_unavailable"}
  }
  return result
}
