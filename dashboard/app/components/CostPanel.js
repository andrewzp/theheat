import React from "react"
import { localCostEvidence } from "../../lib/local-cost-evidence.js"

const h = React.createElement
const count = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("en-US") : "Unknown"
const timestamp = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
  ? `${value.slice(0, 10)} ${value.slice(11, 16)} UTC` : "Unknown"
const nano = value => typeof value === "string" && /^\d{1,12}\.\d{9}$/.test(value) ? BigInt(value.replace(".", "")) : null
const exact = value => {
  const whole = value / 1000000000n, fraction = String(value % 1000000000n).padStart(9, "0").replace(/0+$/, "")
  return `$${whole.toLocaleString("en-US")}${fraction ? `.${fraction.padEnd(2, "0")}` : ".00"}`
}

export function formatTokenRange(value) {
  const min = nano(value?.min), max = nano(value?.max)
  if (min === null || max === null || max < min) return "Unavailable"
  if (min === max) return exact(min)
  // Keep positive sub-cent values visible; round other endpoints outwards.
  const low = min < 10000000n ? min : (min / 10000000n) * 10000000n
  const high = max < 10000000n ? max : ((max + 9999999n) / 10000000n) * 10000000n
  return `${exact(low)}–${exact(high)}`
}

export function formatRecordedAmount(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "Unavailable"
  if (value > 0 && value < 0.01) return "<$0.01"
  return value.toLocaleString("en-US", {style: "currency", currency: "USD"})
}

function Metric({title, children}) {
  return h("div", null, h("dt", null, title), h("dd", null, children))
}

export function CostPanel({evidence, stale = false, loading = false, localEvidence}) {
  const recorded = evidence?.recorded, scenario = evidence?.scenario
  const period = scenario?.observation_period
  const note = (text, props = {}) => h("p", {className: "runtime-note", ...props}, text)
  return h("section", {className: "card full runtime-panel cost-panel", "aria-label": "Cost visibility"},
    h("div", {className: "runtime-heading"}, h("h2", null, "Cost visibility"),
      h("span", {className: "cost-status"}, "Actual bill unavailable")),
    note(stale ? evidence ? "Refresh failed · showing the last loaded cost evidence." : "Refresh failed · cost evidence unavailable."
      : loading && !evidence ? "Loading cost evidence…"
        : "These are separate, incomplete estimates. They cannot establish your total spend or enforce a budget.", {role: "status"}),
    h("div", {className: "cost-columns"},
      h("div", null,
        h("h3", null, "Recorded priced subtotal"),
        h("p", {className: "cost-amount"}, formatRecordedAmount(recorded?.priced_subtotal_usd)),
        note(recorded?.month ? `${recorded.month} month to date · UTC` : "Monthly usage evidence unavailable."),
        note(recorded?.status === "inconsistent" ? "Conflicting usage records prevent a reliable subtotal."
          : "Retained price-table estimates only. Missing and unpriced activity is excluded.")),
      h("div", null,
        h("h3", null, "Google token scenario"),
        h("p", {className: "cost-amount"}, formatTokenRange(scenario?.token_subtotal_usd)),
        note(scenario?.pricing_date ? `Standard paid pricing snapshot: ${scenario.pricing_date}` : "Token scenario unavailable."),
        note(period ? `Observed: ${timestamp(period.first)} to ${timestamp(period.last)}.` : "No valid observation dates available."),
        note("A separate estimate for eligible text tokens. Do not add it to the recorded subtotal."))),
    h("details", {className: "runtime-details"},
      h("summary", null, "Cost coverage and missing charges"),
      h("dl", {className: "runtime-settings cost-counts"},
        h(Metric, {title: "Recorded priced responses"}, count(recorded?.priced_calls)),
        h(Metric, {title: "Recorded unpriced responses"}, count(recorded?.unpriced_calls)),
        h(Metric, {title: "Responses missing usage (part of unpriced)"}, count(recorded?.missing_usage_calls)),
        h(Metric, {title: "Legacy responses without coverage"}, count(recorded?.legacy_calls)),
        h(Metric, {title: "Conflicting / excluded ledger rows"}, `${count(recorded?.inconsistent_rows)} / ${count(recorded?.excluded_rows)}`),
        h(Metric, {title: "Scenario eligible / excluded responses"}, `${count(scenario?.eligible_records)} / ${count(scenario?.excluded_records)}`),
        h(Metric, {title: "Invalid / duplicate observations"}, `${count(scenario?.invalid_records)} / ${count(scenario?.duplicates)}`),
        h(Metric, {title: "Conflicting / other-provider observations"}, `${count(scenario?.conflicting_records)} / ${count(scenario?.non_google_records)}`),
        h(Metric, {title: "Eligible prompt tokens"}, count(scenario?.tokens?.prompt)),
        h(Metric, {title: "Eligible answer tokens"}, count(scenario?.tokens?.candidate)),
        h(Metric, {title: "Eligible thinking tokens"}, count(scenario?.tokens?.thought))),
      scenario?.truncated ? note("The observation window is truncated. Older responses are missing from this scenario.") : null,
      scenario?.invalid ? note("Invalid evidence is present. Invalid records and their conflicting counterparts are excluded.") : null,
      note("The scenario covers at most 32 recent observations, not a calendar month. Excluded responses do not cost zero. A missing cache count creates a range for eligible tokens only; it does not bound account charges."),
      note("Grounding, tools, cache storage, taxes, other pricing tiers and uncaptured requests are not included. Thinking tokens are counted separately from answer tokens. Actual account pricing and bills are unverified."),
      note("The monthly ledger can miss concurrent or unsaved activity. Neither view proves complete accounting, savings or an enforced spending cap."),
      h(SpendClasses, {classes: recorded?.spend_classes})),
    h(OperationCosts, {rows: Array.isArray(evidence?.operations) ? evidence.operations : null}),
    localEvidence === undefined ? null : h(LocalCosts, {evidence: localCostEvidence(localEvidence), stale}))
}

const spendLabels = {discovery: "News discovery", selection: "Candidate writing and checks", other: "Other recorded stages"}
function SpendClasses({classes}) {
  if (!classes || typeof classes !== "object") return h("p", {className: "runtime-note"}, "Discovery and selection responses unavailable.")
  return h("dl", {className: "runtime-settings cost-counts", "aria-label": "Responses by spending purpose"},
    Object.entries(spendLabels).map(([key, title]) => h(Metric, {key, title},
      `${count(classes[key]?.recorded_calls)} recorded · ${count(classes[key]?.unpriced_calls)} unpriced`)))
}

const operationLabels = {alerts: "Alerts run", leaderboard: "Hot 10", publish: "Publishing", manual_generation: "Manual writing",
  batch_generation: "Batch writing", threshold_refresh: "Threshold refresh"}
const stageLabels = {writer: "Writer", safety: "Safety", fact_check: "Fact check", critic: "Critic",
  newsworthiness_search: "News search", newsworthiness_verify: "News verification", news_verification_page: "News source page",
  source_http_get: "Source data", gist_state: "State storage", x_publish: "X", bluesky_publish: "Bluesky",
  x_metrics_read: "X metrics", batch_writer: "Batch writer", synchronous_writer: "Urgent writer", local_required_check: "Local check"}
const label = stage => stageLabels[stage] || stage.replaceAll("_", " ")
const ceilingLabels = {candidate_attempts: "candidate attempts (this operation)", provider_call_cap: "provider calls per stage",
  estimated_token_cap: "estimated token cap (trial)", local_spend_allowance: "local reserved allowance",
  daily_publication_cap: "daily publication cap", monthly_budget_watch: "monthly budget watch (alert only, not a cap)",
  invoice_ceiling: "invoice ceiling (not enforced: no invoice access)"}
const yesNo = value => value === true ? "yes" : value === false ? "no" : "unknown"
export function OperationCosts({rows}) {
  const note = text => h("p", {className: "runtime-note"}, text)
  if (rows === null) return null
  return h("section", {className: "local-cost-section", "aria-label": "Recent operations: calls and allowances"},
    h("h3", null, "Recent operations: calls and allowances"),
    note("Each row joins the requests an operation actually sent. Charges stay unknown; estimates are not added together."),
    rows.length === 0 ? note("No operation records retained yet.") : h("ul", {className: "local-cost-requests"}, rows.map((row, index) => {
      const outcomes = row.requests.by_outcome, another = Object.entries(row.another_attempt_allowed)
      return h("li", {key: `${row.run_started_at}-${row.operation}-${row.spend_class}-${index}`},
        h("details", null,
          h("summary", null, `${operationLabels[row.operation] || row.operation} · ${row.spend_class === "discovery" ? "discovery" : "selection"} · ${count(row.requests.total)} requests${row.requests.interrupted ? ` · ${row.requests.interrupted} interrupted` : ""}`),
          note(`Run started: ${row.run_started_at ? row.run_started_at.replace("T", " ").replace("Z", " UTC") : "Unknown"}`),
          note(`May call: ${row.may_call.map(c => `${label(c.stage)}${c.pricing === "unknown" ? " (unpriced)" : ""}`).join(", ") || "none declared"}.`),
          row.candidate_attempts ? note(`Candidate attempts: ${count(row.candidate_attempts.used)} of ${row.candidate_attempts.limit === null ? "no operation limit" : count(row.candidate_attempts.limit)} used · ${count(row.candidate_attempts.returned_unstarted)} returned unstarted${row.candidate_attempts.refused ? " · configuration refused" : ""}.`) : null,
          row.allowances.length ? h("dl", {className: "runtime-settings cost-counts"}, row.allowances.map(a => h(Metric, {key: a.stage, title: `${label(a.stage)} allowance`},
            `${count(a.reserved)} of ${count(a.limit)} reserved · ${count(a.physical_attempts)} physical attempts · ${count(a.refused_before_egress)} refused before sending${a.exact_cache_hits ? ` · ${count(a.exact_cache_hits)} exact cached results reused (no request)` : ""}`))) : null,
          h("dl", {className: "runtime-settings cost-counts"},
            h(Metric, {title: "Returned"}, count(outcomes.returned)),
            h(Metric, {title: "Interrupted (outcome unknown)"}, count(outcomes.dispatched)),
            h(Metric, {title: "Failed after sending"}, count(outcomes.unknown)),
            h(Metric, {title: "Malformed responses"}, count(outcomes.malformed)),
            h(Metric, {title: "Unpriced requests"}, count(row.unpriced_requests)),
            h(Metric, {title: "Estimate-only requests"}, count(row.estimate_only_requests))),
          row.requests.by_stage.length ? note(`Observed: ${row.requests.by_stage.map(s => `${label(s.stage)} ${count(s.requests)}`).join(", ")}.`) : note("No requests were sent."),
          another.length ? note(`Another attempt allowed: ${another.map(([k, v]) => `${label(k)} ${yesNo(v)}`).join(", ")}.`) : null,
          row.requests.truncated ? note("More requests were sent than this record retains; the extra requests stay unknown.") : null,
          row.requests.late_after_close ? note(`${count(row.requests.late_after_close)} request${row.requests.late_after_close === 1 ? " was" : "s were"} sent after this operation closed (${row.requests.late_by_stage.map(s => `${label(s.stage)} ${count(s.requests)}`).join(", ") || "stage unknown"}). They are not in the counts above, are not refundable and their charges stay unknown.`) : null,
          note(`Applicable limits: ${row.ceilings.map(c => ceilingLabels[c] || c.replaceAll("_", " ")).join(", ")}.`)))
    })))
}


export function formatMicroUsd(value) {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,17})$/.test(value)) return "Unknown"
  const amount = BigInt(value), fraction = String(amount % 1000000n).padStart(6, "0").replace(/0+$/, "")
  return `$${(amount / 1000000n).toLocaleString("en-US")}${fraction ? `.${fraction.padEnd(2, "0")}` : ".00"}`
}

const roles = {writer: "Writing", safety: "Safety", fact_check: "Fact check", critic: "Critic", news: "News", repair: "Repair"}
const usageLabels = {input_tokens: "Input tokens", output_tokens: "Output tokens", prompt_token_count: "Prompt tokens",
  candidates_token_count: "Answer tokens", thoughts_token_count: "Thinking tokens", cached_content_token_count: "Cached tokens",
  total_token_count: "Total tokens", tool_use_prompt_token_count: "Tool prompt tokens", cache_creation_input_tokens: "Cache creation tokens",
  cache_read_input_tokens: "Cache read tokens"}
const localTimestamp = value => value ? `${value.slice(0, 10)} ${value.slice(11, 19)} UTC` : "Unknown"
function LocalCosts({evidence, stale}) {
  const note = text => h("p", {className: "runtime-note"}, text)
  return h("section", {className: "local-cost-section", "aria-label": "Local requests and reserved allowance"},
    h("h3", null, "Local requests and reserved allowance"),
    note(evidence.scope === "hosted_staging_fixture" ? "Hosted staging fixture only · final bill unavailable" : "Local workflow only · final bill unavailable"),
    evidence.status !== "available" ? h("p", {role: "status"}, "Local cost records unavailable.") : h(React.Fragment, null,
      h("p", {className: "runtime-note", role: "status"}, `${stale ? "Refresh failed · last loaded snapshot: " : "Observed: "}${localTimestamp(evidence.snapshot.observed_at)}.`),
      h("dl", {className: "runtime-settings cost-counts"},
        h(Metric, {title: "Reserved allowance"}, formatMicroUsd(evidence.summary.commitments_micro_usd.held)),
        h(Metric, {title: "Daily commitments"}, formatMicroUsd(evidence.summary.commitments_micro_usd.daily)),
        h(Metric, {title: "Monthly commitments"}, formatMicroUsd(evidence.summary.commitments_micro_usd.monthly)),
        h(Metric, {title: "Requests awaiting a final charge"}, count(evidence.total_intents - evidence.summary.reservation_counts.settled - evidence.summary.reservation_counts.released))),
      note("Commitments come from local reservation records; they are not bills. Detailed usage covers only the requests shown below. Do not add these amounts to the estimates above."),
      evidence.total_intents === 0 ? note("No local requests recorded.") : note(`Showing ${evidence.shown_intents} of ${evidence.total_intents} requests${evidence.details_truncated ? ` · ${evidence.omitted_intents} omitted` : ""}.`),
      h("ul", {className: "local-cost-requests"}, evidence.requests.map(row => h("li", {key: row.intent_id},
        h("details", null,
          h("summary", null, `${roles[row.role] || "Other request"} · ${row.reservation_state} · ${row.charge_status === "recorded_settlement" ? `Recorded settlement ${formatMicroUsd(row.recorded_settlement_micro_usd)}` : "Final charge unknown"}`),
          note(`${row.provider} · ${row.requested_model} · ${localTimestamp(row.reserved_at)}`),
          row.reservation_state === "uncertain" ? note("Outcome unknown; allowance remains reserved.") : null,
          note(`Reserved: ${formatMicroUsd(row.reserve_micro_usd)}. Currently held: ${formatMicroUsd(row.held_micro_usd)}.`),
          row.charge_status === "recorded_settlement" ? note("This is a recorded settlement, not invoice reconciliation.") : null,
          row.usage.status === "unavailable" ? note(row.usage.reason === "projection_limited" ? "Usage exceeds this view’s read limit; the reservation is included above." : "Retained usage unavailable; missing usage is not zero.")
            : row.usage.status === "invalid" ? note("Retained usage is invalid; the charge remains unknown.")
              : row.usage.status === "absent" ? note("The response did not report usage; the charge remains unknown.")
                : h("dl", {className: "runtime-settings cost-counts"}, Object.entries(row.usage.counts).map(([key, value]) => h(Metric, {key, title: usageLabels[key] || key.replaceAll("_", " ").replaceAll(".", " · ")}, count(value)))),
          row.usage.unsupported_fields ? note("The response includes unsupported usage fields; coverage is incomplete.") : null,
          note(`Request reference: ${row.intent_id}`),
          row.origin.grant_id ? note(`Grant reference: ${row.origin.grant_id}`) : null,
          row.origin.raw_sha256 ? note(`Response reference: ${row.origin.raw_sha256}`) : null))))))
}
