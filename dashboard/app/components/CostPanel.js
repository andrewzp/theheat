import React from "react"

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

export function CostPanel({evidence, stale = false, loading = false}) {
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
      note("The monthly ledger can miss concurrent or unsaved activity. Neither view proves complete accounting, savings or an enforced spending cap.")))
}
